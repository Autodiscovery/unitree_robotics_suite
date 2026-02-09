# Autonomous Execution Package

This package provides modular components for autonomous multi-policy execution on the G1 robot.

## Package Structure

```
autonomous/
├── __init__.py           # Package exports
├── types.py              # State machine enums and type definitions
├── policy_manager.py     # GPU policy lifecycle management
├── signal_handler.py     # WebSocket communication for state coordination
└── executor.py           # Core autonomous execution orchestration
```

## Quick Start

### Using the Complete System

```python
from unitree_lerobot.eval_robot.autonomous import autonomous_execution
import asyncio

asyncio.run(autonomous_execution(
    policy1_path="/path/to/policy1",
    policy1_repo_id="dataset1",
    policy1_root="/data/root",
    policy1_rename_map={},
    policy1_timeout=30.0,
    policy1_max_retries=3,
    policy2_path="/path/to/policy2",
    policy2_repo_id="dataset2",
    policy2_root="/data/root",
    policy2_rename_map={},
    policy2_timeout=30.0,
    ws_host="localhost",
    ws_port=8765,
    frequency=60.0,
    arm="G1_29",
    ee="inspire_fake",
    motion=False,
    visualization=False,
))
```

### Using Individual Components

#### PolicyManager

```python
from unitree_lerobot.eval_robot.autonomous import PolicyManager
import torch

device = torch.device("cuda")
manager = PolicyManager(device=device)

# Load a policy
policy, preprocessor, postprocessor, dataset = manager.load_policy(
    policy_path="/path/to/policy",
    repo_id="my_dataset",
    root="/data/root",
    rename_map={},
    policy_name="My Policy"
)

# Use the policy...

# Unload when done
manager.unload_policy()
```

#### SignalHandler

```python
from unitree_lerobot.eval_robot.autonomous import SignalHandler, SignalType
import asyncio

async def coordinate():
    handler = SignalHandler(host="localhost", port=8765)
    await handler.connect()
    
    # Send status
    await handler.send_status(ExecutionState.EXECUTING_POLICY_1, "Running...")
    
    # Wait for signal
    signal = await handler.wait_for_signal(timeout=10.0)
    if signal == SignalType.POLICY_SUCCESS:
        print("Success!")
    
    await handler.disconnect()

asyncio.run(coordinate())
```

## Modules

### types.py

Defines enums for state machine and WebSocket signals:

- `ExecutionState`: IDLE, WAITING_START, EXECUTING_POLICY_1, HOLDING_POSE, WAITING_NAV_COMPLETE, EXECUTING_POLICY_2, COMPLETE, ABORTED
- `SignalType`: START_EXECUTION, POLICY_SUCCESS, POLICY_FAILURE, NAV_COMPLETE, ABORT, HEARTBEAT

### policy_manager.py

Manages GPU policy lifecycle:

- `load_policy()`: Load policy with preprocessing onto GPU
- `unload_policy()`: Clean unload with GPU cache clearing
- `get_current_policy()`: Access currently loaded policy

### signal_handler.py

Handles WebSocket communication:

- `connect()` / `disconnect()`: Connection management
- `send_message()` / `send_status()`: Outgoing messages
- `wait_for_signal()`: Receive signals with timeout
- Background heartbeat and receive loops

### executor.py

Core autonomous execution orchestration:

1. Setup & Policy 1 loading
2. Wait for START signal
3. Execute Policy 1 with automatic retry
4. Freeze pose & wait for navigation
5. Unload Policy 1, load Policy 2 (background)
6. Execute Policy 2 (timeout-based)
7. Completion & cleanup

## Benefits

✅ **Modular**: Each component has a single, clear purpose  
✅ **Reusable**: Components can be used independently in other scripts  
✅ **Testable**: Easy to test components in isolation  
✅ **Maintainable**: Clear organization and documentation  
✅ **Backward Compatible**: Works with existing `autonomous.py` entry point
