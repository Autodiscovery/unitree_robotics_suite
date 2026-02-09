"""
Type definitions and enums for autonomous execution.
"""

from enum import Enum


class ExecutionState(Enum):
    """States for autonomous execution state machine."""
    IDLE = "idle"
    WAITING_START = "waiting_start"
    EXECUTING_POLICY_1 = "executing_policy_1"
    # POLICY_1_FAILED removed - automatic retry instead
    HOLDING_POSE = "holding_pose"
    WAITING_NAV_COMPLETE = "waiting_nav_complete"
    LOADING_POLICY_2 = "loading_policy_2"
    EXECUTING_POLICY_2 = "executing_policy_2"
    COMPLETE = "complete"
    ABORTED = "aborted"


class SignalType(Enum):
    """WebSocket signal types."""
    START_EXECUTION = "START_EXECUTION"
    POLICY_SUCCESS = "POLICY_SUCCESS"
    POLICY_FAILURE = "POLICY_FAILURE"
    RETRY_POLICY = "RETRY_POLICY"
    NAV_COMPLETE = "NAV_COMPLETE"
    ABORT = "ABORT"
    HEARTBEAT = "HEARTBEAT"
