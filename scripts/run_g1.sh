#!/bin/bash

# Model paths
CAN_MODEL_PATH="/home/iagi/Desktop/pi05_05000/pretrained_model"
SUITCASE_PI05_MODEL_PATH="/home/iagi/Desktop/suitcase/pi05/pretrained_model"
SUITCASE_GROOT_MODEL_PATH="/home/iagi/Desktop/suitcase/groot/pretrained_model"

# Dataset paths
CAN_DATASET_ROOT="/home/iagi/Desktop/converted_dataset/converted_dataset"
SUITCASE_DATASET_ROOT="/home/iagi/Desktop/suitcase/converted_dataset"

# Default values
MODEL="suitcase_pi05"
VISUALIZATION="true"
MOTION="true"
SEND_REAL_ROBOT="true"
EE="inspire_fake"

# Parse command line arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --model|-m)
            MODEL="$2"
            shift 2
            ;;
        --visualization|-v)
            VISUALIZATION="$2"
            shift 2
            ;;
        --motion)
            MOTION="$2"
            shift 2
            ;;
        --send_real_robot)
            SEND_REAL_ROBOT="$2"
            shift 2
            ;;
        --ee)
            EE="$2"
            shift 2
            ;;
        --help|-h)cancan
            echo "Usage: $0 [OPTIONS]"
            echo ""
            echo "Options:"
            echo "  --model, -m          Model to use: can, suitcase_pi05, suitcase_groot (default: suitcase_pi05)"
            echo "  --visualization, -v  Enable visualization: true/false (default: true)"
            echo "  --motion             Enable motion: true/false (default: true)"
            echo "  --send_real_robot    Send to real robot: true/false (default: true)"
            echo "  --ee                 End effector: inspire1, inspire_fake, dex3, etc. (default: inspire_fake)"
            echo "  --help, -h           Show this help message"
            exit 0
            ;;
        *)
            echo "Unknown option: $1"
            echo "Use --help for usage information"
            exit 1
            ;;
    esac
done

# Select model path and dataset based on model choice
case $MODEL in
    can)
        MODEL_PATH="$CAN_MODEL_PATH"
        DATASET_ROOT="$CAN_DATASET_ROOT"
        ;;
    suitcase_pi05)
        MODEL_PATH="$SUITCASE_PI05_MODEL_PATH"
        DATASET_ROOT="$SUITCASE_DATASET_ROOT"
        ;;
    suitcase_groot)
        MODEL_PATH="$SUITCASE_GROOT_MODEL_PATH"
        DATASET_ROOT="$SUITCASE_DATASET_ROOT"
        ;;
    *)
        echo "Unknown model: $MODEL"
        echo "Available models: can, suitcase_pi05, suitcase_groot"
        exit 1
        ;;
esac

echo "Running with model: $MODEL"
echo "Model path: $MODEL_PATH"
echo "Dataset root: $DATASET_ROOT"
echo ""

# Safety confirmation before running
echo "============================================"
if [[ "$MOTION" == "true" ]]; then
    echo "⚠️  MOTION MODE ENABLED"
    echo ""
    echo "Please ensure the robot is powered on and in walk/sport mode before continuing."
else
    echo "⚠️  MOTION MODE DISABLED (Robot will be switched to debug mode)"
    echo ""
    echo "Please ensure that the robot is powered on, and is fully supported on the crane before continuing."
fi
echo "============================================"
echo ""
read -p "Press ENTER to confirm and continue..."
echo ""

python unitree_lerobot/eval_robot/eval_g1.py  \
    --policy.path="$MODEL_PATH" \
    --repo_id=converted_dataset \
    --root="$DATASET_ROOT" \
    --episodes=0 \
    --frequency=30 \
    --arm="G1_29" \
    --ee="$EE" \
    --visualization="$VISUALIZATION" \
    --motion="$MOTION" \
    --send_real_robot="$SEND_REAL_ROBOT"
