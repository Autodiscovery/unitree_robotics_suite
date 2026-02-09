"""
Autonomous execution package for G1 robot.

This package provides modular components for autonomous multi-policy execution:
- types: State machine enums and type definitions
- policy_manager: GPU policy lifecycle management
- signal_handler: WebSocket communication for state coordination
- executor: Core autonomous execution orchestration
"""

from .types import ExecutionState, SignalType
from .policy_manager import PolicyManager
from .signal_handler import SignalHandler
from .executor import autonomous_execution

__all__ = [
    "ExecutionState",
    "SignalType",
    "PolicyManager",
    "SignalHandler",
    "autonomous_execution",
]
