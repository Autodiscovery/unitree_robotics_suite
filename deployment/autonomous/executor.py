"""
Core autonomous execution orchestration for Unitree robots.

This module contains the main autonomous_execution function that orchestrates
the full multi-policy execution sequence with state machine logic.

Supports all robot types: G1_29, G1_23, H1_2, H1
"""

import time
import torch
import asyncio
import numpy as np
import logging_mp
from typing import Optional
from multiprocessing.sharedctypes import SynchronizedArray

from lerobot.utils.utils import get_safe_torch_device
from lerobot.datasets.lerobot_dataset import LeRobotDataset

from unitree_lerobot.eval_robot.make_robot import (
    setup_image_client,
    setup_robot_interface,
    process_images_and_observations,
)
from unitree_lerobot.eval_robot.utils.utils import (
    cleanup_resources,
    predict_action,
    to_list,
    to_scalar,
)

from .types import ExecutionState, SignalType
from .policy_manager import PolicyManager
from .signal_handler import SignalHandler

logger_mp = logging_mp.get_logger(__name__)


# Robot controller mapping - all controllers share the same interface
from unitree_lerobot.eval_robot.robot_control.robot_arm import (
    G1_29_ArmController,
    G1_23_ArmController,
    H1_2_ArmController,
    H1_ArmController,
)

ROBOT_CONTROLLERS = {
    "G1_29": G1_29_ArmController,
    "G1_23": G1_23_ArmController,
    "H1_2": H1_2_ArmController,
    "H1": H1_ArmController,
}

# DOF (Degrees of Freedom) per arm for each robot type
ROBOT_ARM_DOF = {
    "G1_29": 7,  # 7 DOF per arm (shoulder_pitch, shoulder_roll, shoulder_yaw, elbow, wrist_roll, wrist_pitch, wrist_yaw)
    "G1_23": 5,  # 5 DOF per arm (shoulder_pitch, shoulder_roll, shoulder_yaw, elbow, wrist_roll)
    "H1_2": 7,   # 7 DOF per arm (shoulder_pitch, shoulder_roll, shoulder_yaw, elbow_pitch, elbow_roll, wrist_pitch, wrist_yaw)
    "H1": 4,     # 4 DOF per arm (shoulder_pitch, shoulder_roll, shoulder_yaw, elbow)
}


def get_total_arm_dof(arm_type: str) -> int:
    """Get total DOF for both arms combined."""
    if arm_type not in ROBOT_ARM_DOF:
        raise ValueError(f"Unknown robot type: {arm_type}. Supported types: {list(ROBOT_ARM_DOF.keys())}")
    return ROBOT_ARM_DOF[arm_type] * 2


def validate_pose(pose: Optional[list[float]], arm_type: str, pose_name: str) -> None:
    """Validate that a pose has the correct DOF for the robot type."""
    if pose is None:
        return
    
    expected_dof = get_total_arm_dof(arm_type)
    if len(pose) != expected_dof:
        raise ValueError(
            f"{pose_name} has {len(pose)} DOF, but {arm_type} requires {expected_dof} DOF "
            f"({ROBOT_ARM_DOF[arm_type]} per arm × 2 arms)"
        )



async def autonomous_execution(
    policy1_path: str,
    policy1_repo_id: str,
    policy1_root: str,
    policy1_rename_map: dict[str, str],
    policy1_timeout: float,
    policy1_max_retries: int,
    policy2_path: str,
    policy2_repo_id: str,
    policy2_root: str,
    policy2_rename_map: dict[str, str],
    policy2_timeout: float,
    ws_host: str,
    ws_port: int,
    frequency: float,
    arm: str,
    ee: str,
    motion: bool,
    visualization: bool,
    use_amp: bool = False,
    ready_pose: Optional[list[float]] = None,
    policy1_initial_pose: Optional[list[float]] = None,
    policy2_initial_pose: Optional[list[float]] = None,
    image_server_ip: str = "192.168.123.164", # Added arg
):
    """
    Main autonomous execution function.
    
    Supports all robot types: G1_29, G1_23, H1_2, H1
    
    Executes the full autonomous sequence:
    1. Load Policy 1 and move to initial pose
    2. Wait for START signal
    3. Execute Policy 1 with timeout/retry
    4. Freeze pose and wait for navigation
    5. Unload Policy 1, load Policy 2
    6. Execute Policy 2
    7. Complete and go home
    
    Args:
        arm: Robot type (G1_29, G1_23, H1_2, or H1)
        ready_pose: Optional ready pose (must match robot DOF)
        policy1_initial_pose: Optional Policy 1 initial pose (must match robot DOF)
        policy2_initial_pose: Optional Policy 2 initial pose (must match robot DOF)
        image_server_ip: IP address of the image server
    """
    # Validate robot type
    if arm not in ROBOT_CONTROLLERS:
        raise ValueError(f"Unknown robot type: {arm}. Supported types: {list(ROBOT_CONTROLLERS.keys())}")
    
    # Validate poses have correct DOF for robot type
    validate_pose(ready_pose, arm, "ready_pose")
    validate_pose(policy1_initial_pose, arm, "policy1_initial_pose")
    validate_pose(policy2_initial_pose, arm, "policy2_initial_pose")
    
    # Get device
    device = get_safe_torch_device("cuda", log=True)
    
    # Initialize managers
    policy_manager = PolicyManager(device=device, use_amp=use_amp)
    signal_handler = SignalHandler(host=ws_host, port=ws_port)
    
    # State tracking
    current_state = ExecutionState.IDLE
    policy1_retry_count = 0
    last_arm_action = None
    
    # Robot interfaces
    image_info = None
    robot_interface = None
    
from unitree_sdk2py.core.channel import ChannelFactoryInitialize

# ... imports ...

    try:
        # ====================================================================
        # SETUP PHASE
        # ====================================================================
        logger_mp.info("=" * 60)
        logger_mp.info("AUTONOMOUS EXECUTION - SETUP PHASE")
        logger_mp.info(f"Robot Type: {arm} ({ROBOT_ARM_DOF[arm]} DOF per arm)")
        logger_mp.info("=" * 60)
        
        # Connect to WebSocket server
        await signal_handler.connect()
        if not signal_handler.connected:
            raise RuntimeError("Failed to connect to WebSocket server")
            
        # Initialize Unitree DDS Channel (0 for real robot)
        ChannelFactoryInitialize(0)
        
        # Setup robot interfaces
        from argparse import Namespace
        cfg_namespace = Namespace(
            arm=arm,
            ee=ee,
            motion=motion,
            sim=False,
            image_server_ip=image_server_ip,
        )
        
        image_info = setup_image_client(cfg_namespace)
        robot_interface = setup_robot_interface(cfg_namespace)
        
        # Unpack interfaces
        arm_ctrl, arm_ik, ee_shared_mem, arm_dof, ee_dof = (
            robot_interface[key] for key in ["arm_ctrl", "arm_ik", "ee_shared_mem", "arm_dof", "ee_dof"]
        )
        tv_img_array, wrist_img_array, tv_img_shape, wrist_img_shape, is_binocular, has_wrist_cam = (
            image_info[key]
            for key in [
                "tv_img_array", "wrist_img_array", "tv_img_shape",
                "wrist_img_shape", "is_binocular", "has_wrist_cam",
            ]
        )
        
        # Move to ready pose first (if specified)
        if ready_pose is not None:
            logger_mp.info("Moving to ready pose...")
            ready_pose_np = np.array(ready_pose[:arm_dof])
            tau = arm_ik.solve_tau(ready_pose_np)
            arm_ctrl.ctrl_dual_arm(ready_pose_np, tau)
            time.sleep(2.0)
        
        # Load Policy 1
        logger_mp.info("Loading Policy 1...")
        policy1, preprocessor1, postprocessor1, dataset1 = policy_manager.load_policy(
            policy_path=policy1_path,
            repo_id=policy1_repo_id,
            root=policy1_root,
            rename_map=policy1_rename_map,
            policy_name="Policy 1"
        )
        
        # Get initial pose - use custom pose if specified, otherwise from dataset
        from_idx = dataset1.meta.episodes["dataset_from_index"][0]
        step = dataset1[from_idx]
        
        if policy1_initial_pose is not None:
            logger_mp.info("Using custom initial pose for Policy 1")
            init_arm_pose = np.array(policy1_initial_pose[:arm_dof])
        else:
            init_arm_pose = step["observation.state"][:arm_dof].cpu().numpy()
        
        # Move to initial pose
        logger_mp.info("Moving to Policy 1 initial pose...")
        tau = arm_ik.solve_tau(init_arm_pose)
        arm_ctrl.ctrl_dual_arm(init_arm_pose, tau)
        time.sleep(2.0)
        
        current_state = ExecutionState.WAITING_START
        await signal_handler.send_status(current_state, "Ready to start - waiting for START_EXECUTION signal")
        logger_mp.info("Robot ready. Waiting for START_EXECUTION signal...")
        
        # ====================================================================
        # WAIT FOR START SIGNAL
        # ====================================================================
        while current_state == ExecutionState.WAITING_START:
            signal = await signal_handler.wait_for_signal(timeout=1.0)
            
            if signal == SignalType.START_EXECUTION:
                current_state = ExecutionState.EXECUTING_POLICY_1
                await signal_handler.send_status(current_state, "Starting Policy 1 execution")
                logger_mp.info("START signal received. Beginning Policy 1 execution...")
                break
            elif signal == SignalType.ABORT:
                current_state = ExecutionState.ABORTED
                raise KeyboardInterrupt("Abort signal received")
            
            # Check connection
            if not signal_handler.connected:
                raise RuntimeError("WebSocket connection lost")
        
        # ====================================================================
        # POLICY 1 EXECUTION LOOP WITH AUTOMATIC RETRY
        # ====================================================================
        while current_state == ExecutionState.EXECUTING_POLICY_1:
            
            # Execute Policy 1
            logger_mp.info(f"Executing Policy 1 at {frequency} Hz (timeout: {policy1_timeout}s)")
            logger_mp.info(f"Retry attempt: {policy1_retry_count + 1}/{policy1_max_retries + 1}")
            execution_start_time = time.perf_counter()
            idx = 0
            
            policy_succeeded = False
            
            while True:
                loop_start_time = time.perf_counter()
                
                # Check for timeout
                elapsed_time = time.perf_counter() - execution_start_time
                if elapsed_time > policy1_timeout:
                    logger_mp.warning(f"Policy 1 execution timeout ({policy1_timeout}s exceeded)")
                    
                    # Check if we can retry
                    if policy1_retry_count < policy1_max_retries:
                        policy1_retry_count += 1
                        logger_mp.info(f"Automatically retrying Policy 1 (attempt {policy1_retry_count + 1}/{policy1_max_retries + 1})")
                        await signal_handler.send_status(
                            ExecutionState.EXECUTING_POLICY_1, 
                            f"Timeout - retrying (attempt {policy1_retry_count + 1}/{policy1_max_retries + 1})"
                        )
                        
                        # Move back to initial pose
                        logger_mp.info("Moving back to Policy 1 initial pose...")
                        tau = arm_ik.solve_tau(init_arm_pose)
                        arm_ctrl.ctrl_dual_arm(init_arm_pose, tau)
                        time.sleep(2.0)
                        
                        # Reset policy
                        logger_mp.info("Resetting Policy 1...")
                        policy1.reset()
                        preprocessor1.reset()
                        postprocessor1.reset()
                        
                        # Break inner loop to restart execution
                        break
                    else:
                        logger_mp.error(f"Policy 1 failed after {policy1_max_retries + 1} attempts")
                        raise RuntimeError(f"Policy 1 failed after {policy1_max_retries + 1} attempts")
                
                # Check for signals (non-blocking)
                try:
                    signal = await asyncio.wait_for(signal_handler.signal_queue.get(), timeout=0.001)
                    
                    if signal == SignalType.POLICY_SUCCESS:
                        logger_mp.info("Policy 1 SUCCESS signal received - continuing for 2 more seconds")
                        await signal_handler.send_status(ExecutionState.EXECUTING_POLICY_1, "Success signal received, finishing execution")
                        
                        # Continue executing for 2 more seconds before freezing pose
                        success_time = time.perf_counter()
                        while time.perf_counter() - success_time < 2.0:
                            loop_start_time_delay = time.perf_counter()
                            
                            # Get observations
                            observation_delay, current_arm_q_delay = process_images_and_observations(
                                tv_img_array, wrist_img_array, tv_img_shape, wrist_img_shape,
                                is_binocular, has_wrist_cam, arm_ctrl
                            )
                            
                            # Get end-effector state
                            left_ee_state_delay = right_ee_state_delay = np.array([])
                            if ee_dof > 0:
                                with ee_shared_mem["lock"]:
                                    full_state_delay = np.array(ee_shared_mem["state"][:])
                                    left_ee_state_delay = full_state_delay[:ee_dof]
                                    right_ee_state_delay = full_state_delay[ee_dof:]
                            
                            state_tensor_delay = torch.from_numpy(
                                np.concatenate((current_arm_q_delay, left_ee_state_delay, right_ee_state_delay), axis=0)
                            ).float()
                            observation_delay["observation.state"] = state_tensor_delay
                            
                            # Predict action
                            action_delay = predict_action(
                                observation_delay, policy1, device, preprocessor1, postprocessor1,
                                use_amp, step["task"], use_dataset=False, robot_type=None
                            )
                            action_np_delay = action_delay.cpu().numpy()
                            
                            # Execute action
                            arm_action_delay = action_np_delay[:arm_dof]
                            tau_delay = arm_ik.solve_tau(arm_action_delay)
                            arm_ctrl.ctrl_dual_arm(arm_action_delay, tau_delay)
                            last_arm_action = arm_action_delay  # Save for pose holding
                            
                            # Execute end-effector action
                            if ee_dof > 0:
                                ee_action_start_idx_delay = arm_dof
                                left_ee_action_delay = action_np_delay[ee_action_start_idx_delay : ee_action_start_idx_delay + ee_dof]
                                right_ee_action_delay = action_np_delay[ee_action_start_idx_delay + ee_dof : ee_action_start_idx_delay + 2 * ee_dof]
                                
                                if isinstance(ee_shared_mem["left"], SynchronizedArray):
                                    ee_shared_mem["left"][:] = to_list(left_ee_action_delay)
                                    ee_shared_mem["right"][:] = to_list(right_ee_action_delay)
                                elif hasattr(ee_shared_mem["left"], "value"):
                                    ee_shared_mem["left"].value = to_scalar(left_ee_action_delay)
                                    ee_shared_mem["right"].value = to_scalar(right_ee_action_delay)
                            
                            # Maintain frequency
                            time.sleep(max(0, (1.0 / frequency) - (time.perf_counter() - loop_start_time_delay)))
                        
                        logger_mp.info("2-second delay complete - freezing pose")
                        current_state = ExecutionState.HOLDING_POSE
                        await signal_handler.send_status(current_state, "Policy 1 completed successfully")
                        policy_succeeded = True
                        break
                    elif signal == SignalType.ABORT:
                        raise KeyboardInterrupt("Abort signal received")
                        
                except asyncio.TimeoutError:
                    pass  # No signal, continue execution
                
                # Get observations
                observation, current_arm_q = process_images_and_observations(
                    tv_img_array, wrist_img_array, tv_img_shape, wrist_img_shape,
                    is_binocular, has_wrist_cam, arm_ctrl
                )
                
                # Get end-effector state
                left_ee_state = right_ee_state = np.array([])
                if ee_dof > 0:
                    with ee_shared_mem["lock"]:
                        full_state = np.array(ee_shared_mem["state"][:])
                        left_ee_state = full_state[:ee_dof]
                        right_ee_state = full_state[ee_dof:]
                
                state_tensor = torch.from_numpy(
                    np.concatenate((current_arm_q, left_ee_state, right_ee_state), axis=0)
                ).float()
                observation["observation.state"] = state_tensor
                
                # Predict action
                action = predict_action(
                    observation, policy1, device, preprocessor1, postprocessor1,
                    use_amp, step["task"], use_dataset=False, robot_type=None
                )
                action_np = action.cpu().numpy()
                
                # Execute action
                arm_action = action_np[:arm_dof]
                tau = arm_ik.solve_tau(arm_action)
                arm_ctrl.ctrl_dual_arm(arm_action, tau)
                last_arm_action = arm_action  # Save for pose holding
                
                # Execute end-effector action
                if ee_dof > 0:
                    ee_action_start_idx = arm_dof
                    left_ee_action = action_np[ee_action_start_idx : ee_action_start_idx + ee_dof]
                    right_ee_action = action_np[ee_action_start_idx + ee_dof : ee_action_start_idx + 2 * ee_dof]
                    
                    if isinstance(ee_shared_mem["left"], SynchronizedArray):
                        ee_shared_mem["left"][:] = to_list(left_ee_action)
                        ee_shared_mem["right"][:] = to_list(right_ee_action)
                    elif hasattr(ee_shared_mem["left"], "value"):
                        ee_shared_mem["left"].value = to_scalar(left_ee_action)
                        ee_shared_mem["right"].value = to_scalar(right_ee_action)
                
                idx += 1
                
                # Maintain frequency
                time.sleep(max(0, (1.0 / frequency) - (time.perf_counter() - loop_start_time)))
            
            # If policy succeeded, exit the retry loop
            if policy_succeeded:
                break
        
        # ====================================================================
        # HOLDING POSE & NAVIGATION PHASE
        # ====================================================================
        if current_state == ExecutionState.HOLDING_POSE:
            logger_mp.info("Freezing pose and preparing for navigation...")
            logger_mp.info(f"Holding arm pose: {last_arm_action}")
            
            # Send ready for navigation signal
            await signal_handler.send_message({
                "type": "READY_FOR_NAV",
                "message": "Robot pose frozen, ready for navigation"
            })
            
            current_state = ExecutionState.WAITING_NAV_COMPLETE
            await signal_handler.send_status(current_state, "Waiting for navigation to complete")
            
            # Store policy2_initial_pose in closure for background task
            _policy2_initial_pose = policy2_initial_pose
            
            # Start background task to unload Policy 1 and load Policy 2
            async def load_policy2_background():
                logger_mp.info("Unloading Policy 1 from GPU...")
                # Run unload in thread to avoid blocking event loop
                await asyncio.to_thread(policy_manager.unload_policy)
                
                logger_mp.info("Loading Policy 2 to GPU...")
                await asyncio.sleep(0.5)  # Small delay to ensure cleanup
                # Run load in thread to avoid blocking event loop during heavy PyTorch operations
                # This keeps the WebSocket heartbeat alive during the ~23 second load time
                await asyncio.to_thread(
                    policy_manager.load_policy,
                    policy_path=policy2_path,
                    repo_id=policy2_repo_id,
                    root=policy2_root,
                    rename_map=policy2_rename_map,
                    policy_name="Policy 2"
                )
                logger_mp.info("Policy 2 loaded and ready")
                
                # Move to Policy 2 initial pose if specified
                if _policy2_initial_pose is not None:
                    logger_mp.info("Moving to Policy 2 initial pose...")
                    policy2_init_pose_np = np.array(_policy2_initial_pose[:arm_dof])
                    tau = arm_ik.solve_tau(policy2_init_pose_np)
                    arm_ctrl.ctrl_dual_arm(policy2_init_pose_np, tau)
            
            # Start loading Policy 2 in background
            policy2_load_task = asyncio.create_task(load_policy2_background())
            
            # Hold pose while waiting for navigation
            logger_mp.info("Holding pose during navigation...")
            while current_state == ExecutionState.WAITING_NAV_COMPLETE:
                loop_start_time = time.perf_counter()
                
                # Continuously send the frozen pose
                if last_arm_action is not None:
                    tau = arm_ik.solve_tau(last_arm_action)
                    arm_ctrl.ctrl_dual_arm(last_arm_action, tau)
                
                # Check for navigation complete signal
                try:
                    signal = await asyncio.wait_for(signal_handler.signal_queue.get(), timeout=0.1)
                    
                    if signal == SignalType.NAV_COMPLETE:
                        logger_mp.info("Navigation COMPLETE signal received")
                        
                        # Check if Policy 2 loading is complete
                        if policy2_load_task.done():
                            logger_mp.info("✅ Policy 2 loading complete - ready for execution")
                        else:
                            logger_mp.info("⏳ Policy 2 still loading - waiting for completion...")
                        
                        # Wait for Policy 2 to finish loading
                        await policy2_load_task
                        
                        if not policy2_load_task.done():
                            logger_mp.info("✅ Policy 2 loading finished")
                        
                        current_state = ExecutionState.EXECUTING_POLICY_2
                        await signal_handler.send_status(current_state, "Starting Policy 2 execution")
                        break
                    elif signal == SignalType.ABORT:
                        raise KeyboardInterrupt("Abort signal received")
                        
                except asyncio.TimeoutError:
                    pass  # No signal, continue holding
                
                # Check connection
                if not signal_handler.connected:
                    raise RuntimeError("WebSocket connection lost during navigation")
                
                # Maintain frequency
                time.sleep(max(0, (1.0 / frequency) - (time.perf_counter() - loop_start_time)))
        
        # ====================================================================
        # POLICY 2 EXECUTION (TIMEOUT-BASED ONLY)
        # ====================================================================
        if current_state == ExecutionState.EXECUTING_POLICY_2:
            logger_mp.info(f"Executing Policy 2 at {frequency} Hz (timeout: {policy2_timeout}s)")
            logger_mp.info("Policy 2 will execute for timeout duration only (no success signal)")
            
            # Get Policy 2 components
            policy2, preprocessor2, postprocessor2, dataset2 = policy_manager.get_current_policy()
            
            # Get task from Policy 2 dataset
            from_idx2 = dataset2.meta.episodes["dataset_from_index"][0]
            step2 = dataset2[from_idx2]
            
            execution_start_time = time.perf_counter()
            idx = 0
            
            while current_state == ExecutionState.EXECUTING_POLICY_2:
                loop_start_time = time.perf_counter()
                
                # Check for timeout
                elapsed_time = time.perf_counter() - execution_start_time
                if elapsed_time > policy2_timeout:
                    logger_mp.info(f"Policy 2 timeout reached ({policy2_timeout}s) - completing execution")
                    
                    # Move to ready pose
                    if ready_pose is not None:
                        logger_mp.info("Moving to ready pose...")
                        ready_pose_np = np.array(ready_pose[:arm_dof])
                        tau = arm_ik.solve_tau(ready_pose_np)
                        arm_ctrl.ctrl_dual_arm(ready_pose_np, tau)
                        time.sleep(2.0)
                    
                    current_state = ExecutionState.COMPLETE
                    await signal_handler.send_status(current_state, "Policy 2 completed (timeout)")
                    break
                
                # Check for abort signal only (ignore success signals)
                try:
                    signal = await asyncio.wait_for(signal_handler.signal_queue.get(), timeout=0.001)
                    
                    if signal == SignalType.ABORT:
                        raise KeyboardInterrupt("Abort signal received")
                    # Ignore POLICY_SUCCESS signals for Policy 2
                        
                except asyncio.TimeoutError:
                    pass  # No signal, continue execution
                
                # Get observations
                observation, current_arm_q = process_images_and_observations(
                    tv_img_array, wrist_img_array, tv_img_shape, wrist_img_shape,
                    is_binocular, has_wrist_cam, arm_ctrl
                )
                
                # Get end-effector state
                left_ee_state = right_ee_state = np.array([])
                if ee_dof > 0:
                    with ee_shared_mem["lock"]:
                        full_state = np.array(ee_shared_mem["state"][:])
                        left_ee_state = full_state[:ee_dof]
                        right_ee_state = full_state[ee_dof:]
                
                state_tensor = torch.from_numpy(
                    np.concatenate((current_arm_q, left_ee_state, right_ee_state), axis=0)
                ).float()
                observation["observation.state"] = state_tensor
                
                # Predict action
                action = predict_action(
                    observation, policy2, device, preprocessor2, postprocessor2,
                    use_amp, step2["task"], use_dataset=False, robot_type=None
                )
                action_np = action.cpu().numpy()
                
                # Execute action
                arm_action = action_np[:arm_dof]
                tau = arm_ik.solve_tau(arm_action)
                arm_ctrl.ctrl_dual_arm(arm_action, tau)
                
                # Execute end-effector action
                if ee_dof > 0:
                    ee_action_start_idx = arm_dof
                    left_ee_action = action_np[ee_action_start_idx : ee_action_start_idx + ee_dof]
                    right_ee_action = action_np[ee_action_start_idx + ee_dof : ee_action_start_idx + 2 * ee_dof]
                    
                    if isinstance(ee_shared_mem["left"], SynchronizedArray):
                        ee_shared_mem["left"][:] = to_list(left_ee_action)
                        ee_shared_mem["right"][:] = to_list(right_ee_action)
                    elif hasattr(ee_shared_mem["left"], "value"):
                        ee_shared_mem["left"].value = to_scalar(left_ee_action)
                        ee_shared_mem["right"].value = to_scalar(right_ee_action)
                
                idx += 1
                
                # Maintain frequency
                time.sleep(max(0, (1.0 / frequency) - (time.perf_counter() - loop_start_time)))
        
        # ====================================================================
        # COMPLETION
        # ====================================================================
        if current_state == ExecutionState.COMPLETE:
            logger_mp.info("=" * 60)
            logger_mp.info("AUTONOMOUS EXECUTION COMPLETED SUCCESSFULLY")
            logger_mp.info("=" * 60)
            logger_mp.info("=" * 60)
            logger_mp.info("AUTONOMOUS EXECUTION COMPLETED SUCCESSFULLY")
            logger_mp.info("=" * 60)
            
            # Send completion signal
            await signal_handler.send_message({
                "type": "POLICY_2_COMPLETE",
                "message": "Policy 2 finished execution"
            })
            
            await signal_handler.send_status(current_state, "Execution completed successfully")
            
    except KeyboardInterrupt:
        logger_mp.info("Keyboard interrupt or abort signal received. Shutting down...")
        current_state = ExecutionState.ABORTED
        await signal_handler.send_status(current_state, "Execution aborted")
        
    except Exception as e:
        logger_mp.error(f"Error during autonomous execution: {e}")
        import traceback
        traceback.print_exc()
        current_state = ExecutionState.ABORTED
        await signal_handler.send_status(current_state, f"Error: {str(e)}")
        
    finally:
        # Cleanup
        logger_mp.info("Cleaning up resources...")
        
        # Send robot to home position
        if robot_interface and "arm_ctrl" in robot_interface:
            try:
                logger_mp.info("Sending robot arm to home position...")
                # robot_interface["arm_ctrl"].ctrl_dual_arm_go_home()
                # Move to ready pose first (if specified)
                if ready_pose is not None:
                    logger_mp.info("Moving to ready pose...")
                    ready_pose_np = np.array(ready_pose[:arm_dof])
                    tau = arm_ik.solve_tau(ready_pose_np)
                    arm_ctrl.ctrl_dual_arm(ready_pose_np, tau)
                    time.sleep(2.0)

                time.sleep(1.0)
            except Exception as e:
                logger_mp.error(f"Error sending arm to home: {e}")
        
        # Unload any remaining policy
        try:
            policy_manager.unload_policy()
        except:
            pass
        
        # Cleanup image resources
        if image_info:
            cleanup_resources(image_info)
        
        # Disconnect WebSocket
        await signal_handler.disconnect()
        
        logger_mp.info("Shutdown complete")
