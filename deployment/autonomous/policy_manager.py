"""
GPU policy lifecycle management for autonomous execution.

This module provides the PolicyManager class for loading, unloading, and managing
PyTorch policies on GPU, including memory management and state tracking.
"""

import torch
import logging_mp
from typing import Optional
from lerobot.policies.factory import make_policy, make_pre_post_processors
from lerobot.datasets.lerobot_dataset import LeRobotDataset
from lerobot.policies.pretrained import PreTrainedPolicy
from lerobot.processor.rename_processor import rename_stats
from lerobot.processor import PolicyProcessorPipeline

logger_mp = logging_mp.get_logger(__name__)


class PolicyManager:
    """Manages loading and unloading of policies from GPU memory."""
    
    def __init__(self, device: torch.device, use_amp: bool = False):
        self.device = device
        self.use_amp = use_amp
        self.current_policy: Optional[PreTrainedPolicy] = None
        self.current_preprocessor: Optional[PolicyProcessorPipeline] = None
        self.current_postprocessor: Optional[PolicyProcessorPipeline] = None
        self.current_dataset: Optional[LeRobotDataset] = None
        self.current_policy_name: Optional[str] = None
        
    def load_policy(
        self,
        policy_path: str,
        repo_id: str,
        root: str,
        rename_map: dict[str, str],
        policy_name: str = "policy"
    ) -> tuple[PreTrainedPolicy, PolicyProcessorPipeline, PolicyProcessorPipeline, LeRobotDataset]:
        """
        Load a policy onto GPU.
        
        Args:
            policy_path: Path to pretrained policy
            repo_id: Dataset repository ID
            root: Dataset root directory
            rename_map: Observation rename mapping
            policy_name: Name for logging purposes
            
        Returns:
            Tuple of (policy, preprocessor, postprocessor, dataset)
        """
        logger_mp.info(f"Loading {policy_name} from {policy_path}")
        
        # Load dataset
        dataset = LeRobotDataset(repo_id=repo_id, root=root if root else None)
        logger_mp.info(f"Dataset loaded: {len(dataset)} frames")
        
        # Load policy configuration from pretrained path
        from lerobot.configs.policies import PreTrainedConfig
        policy_cfg = PreTrainedConfig.from_pretrained(policy_path)
        policy_cfg.pretrained_path = policy_path
        policy_cfg.device = str(self.device)
        
        # Create policy
        policy = make_policy(cfg=policy_cfg, ds_meta=dataset.meta)
        policy.eval()
        policy.to(self.device)
        logger_mp.info(f"Policy loaded to {self.device}")
        
        # Create preprocessor and postprocessor
        preprocessor, postprocessor = make_pre_post_processors(
            policy_cfg=policy_cfg,
            pretrained_path=policy_path,
            dataset_stats=rename_stats(dataset.meta.stats, rename_map),
            preprocessor_overrides={
                "device_processor": {"device": str(self.device)},
                "rename_observations_processor": {"rename_map": rename_map},
            },
        )
        
        # Store references
        self.current_policy = policy
        self.current_preprocessor = preprocessor
        self.current_postprocessor = postprocessor
        self.current_dataset = dataset
        self.current_policy_name = policy_name
        
        # Reset policy state
        policy.reset()
        preprocessor.reset()
        postprocessor.reset()
        
        logger_mp.info(f"{policy_name} loaded successfully")
        return policy, preprocessor, postprocessor, dataset
    
    def unload_policy(self):
        """Unload current policy from GPU and free memory."""
        if self.current_policy is None:
            logger_mp.warning("No policy loaded to unload")
            return
        
        logger_mp.info(f"Unloading {self.current_policy_name} from GPU")
        
        # Delete references
        del self.current_policy
        del self.current_preprocessor
        del self.current_postprocessor
        del self.current_dataset
        
        # Clear GPU cache
        if self.device.type == "cuda":
            torch.cuda.empty_cache()
            torch.cuda.synchronize()
            
            # Log GPU memory status
            if torch.cuda.is_available():
                allocated = torch.cuda.memory_allocated(self.device) / 1024**3
                reserved = torch.cuda.memory_reserved(self.device) / 1024**3
                logger_mp.info(f"GPU Memory - Allocated: {allocated:.2f}GB, Reserved: {reserved:.2f}GB")
        
        # Reset references
        self.current_policy = None
        self.current_preprocessor = None
        self.current_postprocessor = None
        self.current_dataset = None
        self.current_policy_name = None
        
        logger_mp.info("Policy unloaded successfully")
    
    def get_current_policy(self) -> tuple[PreTrainedPolicy, PolicyProcessorPipeline, PolicyProcessorPipeline, LeRobotDataset]:
        """Get currently loaded policy components."""
        if self.current_policy is None:
            raise RuntimeError("No policy currently loaded")
        return self.current_policy, self.current_preprocessor, self.current_postprocessor, self.current_dataset
