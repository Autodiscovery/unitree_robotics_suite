"""
Autonomous multi-policy execution script for Unitree robots.

This script chains two manipulation policies with navigation in between:
1. Execute Policy 1 (e.g., pick object)
2. Freeze pose and wait for navigation
3. Unload Policy 1, load Policy 2
4. Execute Policy 2 (e.g., place object)

Supports all robot types: G1_29, G1_23, H1_2, H1

Uses WebSocket signaling for state coordination.
Based on: unitree_lerobot/eval_robot/eval_g1.py

Refactored into modular architecture - see autonomous/ package for implementation.
"""

import asyncio
import logging_mp

from lerobot.utils.utils import init_logging

from unitree_lerobot.eval_robot.config import (
    POLICY_CONFIG,
    CUSTOM_INITIAL_POSES,
    reload_config,
)

# Import from modular autonomous package
from deployment.autonomous import autonomous_execution

logging_mp.basic_config(level=logging_mp.INFO)
logger_mp = logging_mp.get_logger(__name__)


# ============================================================================
# Entry Point
# ============================================================================

def main():
    """Main entry point - parses arguments and runs autonomous execution.
    
    Uses POLICY_CONFIG and CUSTOM_INITIAL_POSES from config.py as defaults.
    A custom config file can be specified with --config.
    Command line arguments can override the config values.
    """
    import argparse
    import sys
    
    # Pre-parse to check for --config argument first
    pre_parser = argparse.ArgumentParser(add_help=False)
    pre_parser.add_argument("--config", type=str, default=None,
                           help="Path to JSON config file (default: uses config.json in eval_robot directory)")
    pre_args, _ = pre_parser.parse_known_args()
    
    # If a custom config is specified, reload it before setting up defaults
    if pre_args.config:
        logger_mp.info(f"Loading custom config from: {pre_args.config}")
        reload_config(pre_args.config)
    
    # Get defaults from config (possibly reloaded)
    policy1_cfg = POLICY_CONFIG.get("policy_1", {})
    policy2_cfg = POLICY_CONFIG.get("policy_2", {})
    robot_cfg = POLICY_CONFIG.get("robot", {})
    ws_cfg = POLICY_CONFIG.get("websocket", {})
    
    parser = argparse.ArgumentParser(
        description="Autonomous multi-policy execution for Unitree robots (G1_29, G1_23, H1_2, H1)",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter
    )
    
    # Config file argument (already parsed, but include for help display)
    parser.add_argument("--config", type=str, default=None,
                        help="Path to JSON config file (default: uses config.json in eval_robot directory)")
    
    # Policy 1 configuration (defaults from POLICY_CONFIG)
    parser.add_argument("--policy1_path", type=str, 
                        default=policy1_cfg.get("model", ""),
                        help="Path to Policy 1 pretrained model")
    parser.add_argument("--policy1_repo_id", type=str,
                        default=policy1_cfg.get("repo_id", "converted_dataset"),
                        help="Policy 1 dataset repo ID")
    parser.add_argument("--policy1_root", type=str,
                        default=policy1_cfg.get("root", ""),
                        help="Policy 1 dataset root directory")
    parser.add_argument("--policy1_timeout", type=float,
                        default=policy1_cfg.get("timeout", 30.0),
                        help="Policy 1 execution timeout (seconds)")
    parser.add_argument("--policy1_max_retries", type=int,
                        default=policy1_cfg.get("max_retries", 3),
                        help="Policy 1 max retry attempts")
    
    # Policy 2 configuration (defaults from POLICY_CONFIG)
    parser.add_argument("--policy2_path", type=str,
                        default=policy2_cfg.get("model", ""),
                        help="Path to Policy 2 pretrained model")
    parser.add_argument("--policy2_repo_id", type=str,
                        default=policy2_cfg.get("repo_id", "converted_dataset"),
                        help="Policy 2 dataset repo ID")
    parser.add_argument("--policy2_root", type=str,
                        default=policy2_cfg.get("root", ""),
                        help="Policy 2 dataset root directory")
    parser.add_argument("--policy2_timeout", type=float,
                        default=policy2_cfg.get("timeout", 30.0),
                        help="Policy 2 execution timeout (seconds)")
    
    # WebSocket configuration (defaults from POLICY_CONFIG)
    parser.add_argument("--ws_host", type=str,
                        default=ws_cfg.get("host", "localhost"),
                        help="WebSocket server host")
    parser.add_argument("--ws_port", type=int,
                        default=ws_cfg.get("port", 8765),
                        help="WebSocket server port")
    
    # Robot configuration (defaults from POLICY_CONFIG)
    parser.add_argument("--frequency", type=float,
                        default=robot_cfg.get("frequency", 60.0),
                        help="Control frequency (Hz)")
    parser.add_argument("--arm", type=str,
                        default=robot_cfg.get("arm", "G1_29"),
                        choices=["G1_29", "G1_23", "H1_2", "H1"],
                        help="Robot arm type")
    parser.add_argument("--ee", type=str,
                        default=robot_cfg.get("ee", "inspire_fake"),
                        help="End effector type")
    parser.add_argument("--motion", type=str,
                        default=str(robot_cfg.get("motion", False)).lower(),
                        help="Enable motion mode (true/false)")
    parser.add_argument("--visualization", type=str,
                        default=str(robot_cfg.get("visualization", False)).lower(),
                        help="Enable visualization (true/false)")
    
    # Custom initial pose arguments (keys from CUSTOM_INITIAL_POSES)
    parser.add_argument("--ready_pose", type=str,
                        default="ready_pose",
                        help="Key name for ready pose in CUSTOM_INITIAL_POSES, or 'none' to skip")
    parser.add_argument("--policy1_initial_pose", type=str,
                        default="policy_1_initial_pose",
                        help="Key name for Policy 1 initial pose in CUSTOM_INITIAL_POSES, or 'none' to use dataset")
    parser.add_argument("--policy2_initial_pose", type=str,
                        default="policy_2_initial_pose",
                        help="Key name for Policy 2 initial pose in CUSTOM_INITIAL_POSES, or 'none' to skip")
    parser.add_argument("--image_server_ip", type=str,
                        default="192.168.123.164",
                        help="IP address of the image server")

    args = parser.parse_args()
    
    # Validate required paths
    if not args.policy1_path:
        parser.error("--policy1_path is required (not set in config or command line)")
    if not args.policy2_path:
        parser.error("--policy2_path is required (not set in config or command line)")
    
    # Convert string booleans
    motion = args.motion.lower() == "true"
    visualization = args.visualization.lower() == "true"
    
    # Empty rename maps (can be extended if needed)
    policy1_rename_map = {}
    policy2_rename_map = {}
    
    
    # Get custom initial poses from CUSTOM_INITIAL_POSES
    ready_pose = None
    if args.ready_pose.lower() != "none":
        ready_pose = CUSTOM_INITIAL_POSES.get(args.ready_pose)
        if ready_pose is None:
            logger_mp.warning(f"Ready pose '{args.ready_pose}' not found in CUSTOM_INITIAL_POSES, skipping")
    
    policy1_initial_pose = None
    if args.policy1_initial_pose.lower() != "none":
        policy1_initial_pose = CUSTOM_INITIAL_POSES.get(args.policy1_initial_pose)
        if policy1_initial_pose is None:
            logger_mp.warning(f"Policy 1 initial pose '{args.policy1_initial_pose}' not found in CUSTOM_INITIAL_POSES, using dataset")
    
    policy2_initial_pose = None
    if args.policy2_initial_pose.lower() != "none":
        policy2_initial_pose = CUSTOM_INITIAL_POSES.get(args.policy2_initial_pose)
        if policy2_initial_pose is None:
            logger_mp.warning(f"Policy 2 initial pose '{args.policy2_initial_pose}' not found in CUSTOM_INITIAL_POSES, skipping")
    
    # Log configuration being used
    logger_mp.info("=" * 60)
    logger_mp.info("CONFIGURATION")
    logger_mp.info("=" * 60)
    if args.config:
        logger_mp.info(f"Config file: {args.config}")
    else:
        logger_mp.info("Config file: (default config.json)")
    logger_mp.info(f"Policy 1: {args.policy1_path}")
    logger_mp.info(f"Policy 2: {args.policy2_path}")
    logger_mp.info(f"Robot: arm={args.arm}, ee={args.ee}, motion={motion}")
    logger_mp.info(f"Image Server IP: {args.image_server_ip}")
    logger_mp.info(f"WebSocket: {args.ws_host}:{args.ws_port}")
    logger_mp.info(f"Frequency: {args.frequency} Hz")
    logger_mp.info(f"Ready pose: {args.ready_pose}")
    logger_mp.info(f"Policy 1 initial pose: {args.policy1_initial_pose}")
    logger_mp.info(f"Policy 2 initial pose: {args.policy2_initial_pose}")
    logger_mp.info("=" * 60)
    
    # Run autonomous execution
    asyncio.run(autonomous_execution(
        policy1_path=args.policy1_path,
        policy1_repo_id=args.policy1_repo_id,
        policy1_root=args.policy1_root,
        policy1_rename_map=policy1_rename_map,
        policy1_timeout=args.policy1_timeout,
        policy1_max_retries=args.policy1_max_retries,
        policy2_path=args.policy2_path,
        policy2_repo_id=args.policy2_repo_id,
        policy2_root=args.policy2_root,
        policy2_rename_map=policy2_rename_map,
        policy2_timeout=args.policy2_timeout,
        ws_host=args.ws_host,
        ws_port=args.ws_port,
        frequency=args.frequency,
        arm=args.arm,
        ee=args.ee,
        motion=motion,
        visualization=visualization,
        use_amp=False,
        ready_pose=ready_pose,
        policy1_initial_pose=policy1_initial_pose,
        policy2_initial_pose=policy2_initial_pose,
        image_server_ip=args.image_server_ip,
    ))


if __name__ == "__main__":
    init_logging()
    main()
