#!/bin/bash

# Autonomous Multi-Policy Execution Deployment Script
# Based on run_g1.sh
#
# This script now uses a JSON config file for all configuration.
# Edit config.json or specify a custom config file with --config.

# ============================================================================
# Default Configuration
# ============================================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEFAULT_CONFIG="$SCRIPT_DIR/unitree_lerobot/eval_robot/config.json"
CONFIG_FILE=""
MOTION_OVERRIDE=""
ARM_OVERRIDE=""

# ============================================================================
# Parse Command Line Arguments
# ============================================================================

while [[ $# -gt 0 ]]; do
    case $1 in
        --config)
            CONFIG_FILE="$2"
            shift 2
            ;;
        --motion)
            # Allow motion override from command line for safety
            MOTION_OVERRIDE="$2"
            shift 2
            ;;
        --arm)
            # Allow robot type override from command line
            ARM_OVERRIDE="$2"
            shift 2
            ;;
        --help|-h)
            echo "Usage: $0 [OPTIONS]"
            echo ""
            echo "Autonomous Multi-Policy Execution Script"
            echo ""
            echo "Options:"
            echo "  --config FILE     Path to JSON config file (default: $DEFAULT_CONFIG)"
            echo "  --motion true/false   Override motion mode from config (for safety)"
            echo "  --arm ROBOT_TYPE      Override robot type (G1_29, G1_23, H1_2, H1)"
            echo "  --help, -h        Show this help message"
            echo ""
            echo "Configuration is loaded from config.json which contains:"
            echo "  - Policy paths, timeouts, and retry settings"
            echo "  - Robot configuration (arm type, end effector, frequency)"
            echo "  - WebSocket server settings"
            echo "  - Custom initial poses"
            echo ""
            echo "Example:"
            echo "  $0                           # Use default config.json"
            echo "  $0 --config my_config.json   # Use custom config file"
            echo "  $0 --motion false            # Override motion mode (for testing)"
            echo "  $0 --arm H1_2                # Override robot type to H1_2"
            echo ""
            exit 0
            ;;
        *)
            echo "Unknown option: $1"
            echo "Use --help for usage information"
            exit 1
            ;;
    esac
done

# Use default config if not specified
if [[ -z "$CONFIG_FILE" ]]; then
    CONFIG_FILE="$DEFAULT_CONFIG"
fi

# ============================================================================
# Validate Config File
# ============================================================================

if [[ ! -f "$CONFIG_FILE" ]]; then
    echo "❌ ERROR: Config file not found: $CONFIG_FILE"
    echo ""
    echo "Please create a config.json file or specify a valid config file path."
    echo "See unitree_lerobot/eval_robot/config.json for an example."
    exit 1
fi

echo ""
echo "============================================"
echo "AUTONOMOUS MULTI-POLICY EXECUTION"
echo "============================================"
echo ""
echo "Config file: $CONFIG_FILE"
echo ""

# Read some values from config for display (requires jq)
if command -v jq &> /dev/null; then
    POLICY1_PATH=$(jq -r '.policy_config.policy_1.model // "not set"' "$CONFIG_FILE")
    POLICY2_PATH=$(jq -r '.policy_config.policy_2.model // "not set"' "$CONFIG_FILE")
    ARM=$(jq -r '.policy_config.robot.arm // "G1_29"' "$CONFIG_FILE")
    WS_HOST=$(jq -r '.policy_config.websocket.host // "localhost"' "$CONFIG_FILE")
    WS_PORT=$(jq -r '.policy_config.websocket.port // 8765' "$CONFIG_FILE")
    MOTION=$(jq -r '.policy_config.robot.motion // false' "$CONFIG_FILE")
    EE=$(jq -r '.policy_config.robot.ee // "inspire_fake"' "$CONFIG_FILE")
    FREQUENCY=$(jq -r '.policy_config.robot.frequency // 60.0' "$CONFIG_FILE")
    
    # Apply motion override if specified
    if [[ -n "$MOTION_OVERRIDE" ]]; then
        MOTION="$MOTION_OVERRIDE"
        echo "⚠️  Motion mode overridden to: $MOTION"
        echo ""
    fi
    
    # Apply arm override if specified
    if [[ -n "$ARM_OVERRIDE" ]]; then
        ARM="$ARM_OVERRIDE"
        echo "⚠️  Robot type overridden to: $ARM"
        echo ""
    fi
    
    echo "Configuration (from JSON):"
    echo "  Policy 1 model: $POLICY1_PATH"
    echo "  Policy 2 model: $POLICY2_PATH"
    echo "  Robot Type: $ARM"
    echo "  End Effector: $EE"
    echo "  Frequency: ${FREQUENCY} Hz"
    echo "  Motion Mode: $MOTION"
    echo "  WebSocket: $WS_HOST:$WS_PORT"
    echo ""
else
    echo "Note: Install 'jq' to see config summary"
    echo ""
    # Try to get motion value without jq for safety check
    MOTION=$(grep -o '"motion"[[:space:]]*:[[:space:]]*[a-z]*' "$CONFIG_FILE" | grep -o '[a-z]*$' | head -1)
    if [[ -n "$MOTION_OVERRIDE" ]]; then
        MOTION="$MOTION_OVERRIDE"
    fi
    WS_HOST="localhost"
    WS_PORT="8765"
fi

echo "============================================"
echo ""

# ============================================================================
# Safety Confirmation
# ============================================================================

if [[ "$MOTION" == "true" ]]; then
    echo "⚠️  MOTION MODE ENABLED"
    echo ""
    echo "IMPORTANT SAFETY CHECKS:"
    echo "  1. Robot is powered on and in walk/sport mode"
    echo "  2. Workspace is clear of obstacles"
    echo "  3. Emergency stop is accessible"
    echo "  4. Safety observer is present"
    echo ""
else
    echo "⚠️  MOTION MODE DISABLED (Debug Mode)"
    echo ""
    echo "IMPORTANT CHECKS:"
    echo "  1. Robot is powered on"
    echo "  2. Robot is fully supported on crane"
    echo "  3. WebSocket signal server is running"
    echo ""
fi

echo "============================================"
echo ""
read -p "Press ENTER to confirm and continue..."
echo ""

# ============================================================================
# Check WebSocket Server
# ============================================================================

echo "Checking if WebSocket server is running..."

# Check if port is listening without connecting (avoids triggering the server)
PORT_LISTENING=false
if command -v ss &> /dev/null; then
    if ss -tln | grep -q ":$WS_PORT "; then
        PORT_LISTENING=true
    fi
elif command -v netstat &> /dev/null; then
    if netstat -tln | grep -q ":$WS_PORT "; then
        PORT_LISTENING=true
    fi
elif command -v lsof &> /dev/null; then
    if lsof -i ":$WS_PORT" -sTCP:LISTEN &>/dev/null; then
        PORT_LISTENING=true
    fi
else
    echo "⚠️  Cannot check port (ss/netstat/lsof not found)"
    PORT_LISTENING="unknown"
fi

if [[ "$PORT_LISTENING" == "true" ]]; then
    echo "✅ WebSocket server is listening on port $WS_PORT"
elif [[ "$PORT_LISTENING" == "unknown" ]]; then
    echo "   The connection will be checked when the script starts."
else
    echo "❌ WARNING: No server listening on port $WS_PORT"
    echo ""
    echo "Make sure the signal server is running:"
    echo "  python unitree_lerobot/eval_robot/signal_server.py --port $WS_PORT"
    echo ""
    read -p "Continue anyway? (y/N): " confirm
    if [[ ! "$confirm" =~ ^[Yy]$ ]]; then
        echo "Aborted."
        exit 1
    fi
fi


# ============================================================================
# Run Autonomous Execution
# ============================================================================

# Build command with config file
CMD="python unitree_lerobot/eval_robot/autonomous.py --config=\"$CONFIG_FILE\""

# Add motion override if specified
if [[ -n "$MOTION_OVERRIDE" ]]; then
    CMD="$CMD --motion=\"$MOTION_OVERRIDE\""
fi

# Add arm override if specified
if [[ -n "$ARM_OVERRIDE" ]]; then
    CMD="$CMD --arm=\"$ARM_OVERRIDE\""
fi

# Run the command
eval $CMD

echo ""
echo "Autonomous execution completed."
echo ""
