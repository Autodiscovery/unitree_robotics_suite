# Unitree Robotics Suite

**Unified repository for Unitree humanoid robot teleoperation, imitation learning training, and policy deployment.**

This repository integrates:
- **XR Teleoperation** (`xr_teleoperate` v1.5) - Data collection via XR-based teleoperation
- **IL Training & Deployment** (`unitree_il_robot` v0.3) - LeRobot-based policy training and real-world deployment

---

## 📋 Table of Contents

- [Features](#features)
- [Repository Structure](#repository-structure)
- [Installation](#installation)
- [Quick Start](#quick-start)
- [Workflows](#workflows)
  - [1. Data Collection (Teleoperation)](#1-data-collection-teleoperation)
  - [2. Data Conversion](#2-data-conversion)
  - [3. Policy Training](#3-policy-training)
  - [4. Policy Deployment](#4-policy-deployment)
  - [5. Autonomous Execution](#5-autonomous-execution)
- [Supported Hardware](#supported-hardware)
- [Troubleshooting](#troubleshooting)
- [License](#license)

---

## ✨ Features

### Teleoperation
- **XR-based control** via Meta Quest, Apple Vision Pro, or browser
- **Multi-robot support**: G1 (29/23 DOF), H1, H1_2
- **Hand controllers**: Dex1, Dex3, Inspire (FTP/DFX), BrainCo, HAND16
- **Real-time visualization** with Rerun
- **Image streaming** via ZMQ and WebRTC (OAK-D camera support)
- **JSON episode recording** for training

### Training
- **LeRobot framework** integration
- **Multiple policy types**: ACT, Diffusion, Pi0, Pi0.5, Groot
- **HuggingFace Hub** integration for datasets and models
- **Multi-GPU training** support

### Deployment
- **Real-time policy execution** on physical robots
- **Simulation testing** with Isaac Sim
- **Autonomous chaining** of multiple policies with navigation
- **WebSocket-based coordination** for multi-robot systems

---

## 📁 Repository Structure

```
unitree_robotics/
├── teleop/                      # Teleoperation & data recording
│   ├── teleop_hand_and_arm.py  # Main teleoperation script
│   ├── robot_control/          # Shared robot control (G1, H1)
│   │   ├── robot_arm.py
│   │   ├── robot_arm_ik.py
│   │   └── robot_hand_*.py     # Hand controllers
│   ├── televuer/               # XR interface (submodule)
│   ├── teleimager/             # Image streaming (submodule)
│   │   └── src/teleimager/
│   │       ├── oak_d_server.py # OAK-D camera server
│   │       └── image_client.py # Image client
│   └── utils/                  # Episode writer, visualizers
│
├── deployment/                  # Policy deployment
│   ├── eval_g1.py              # Real robot deployment
│   ├── eval_g1_sim.py          # Simulation deployment
│   ├── autonomous.py           # Multi-policy chaining
│   ├── make_robot.py           # Robot interface factory
│   └── utils/                  # Deployment utilities
│
├── training/                    # LeRobot training
│   └── lerobot/                # LeRobot framework (submodule)
│
├── utils/                       # Data conversion
│   ├── convert_unitree_json_to_lerobot.py
│   └── sort_and_rename_folders.py
│
├── assets/                      # URDF files
├── scripts/                     # Convenience scripts
├── pyproject.toml              # Package configuration
├── requirements.txt            # Python dependencies
├── environment.yml             # Conda environment
└── README.md                   # This file
```

---

## 🔧 Installation

> [!IMPORTANT]
> This repository has **two separate installation paths** that serve different purposes:
> 1. **Teleop + Deployment** - For data collection and policy deployment (running on robot or sim)
> 2. **Training** - For training models with LeRobot framework (requires GPU)

### Prerequisites

- **Operating System**: Ubuntu 22.04 or higher
- **Python**: 3.10 (required)
- **Conda**: Miniconda or Anaconda
- **CUDA**: 11.8+ (for training with GPU)
- **Hardware**:
  - Real robot: Unitree G1/H1/H1_2 (optional, can be sim)
  - Cameras: OAK-D or RealSense (optional for image streaming)
  - XR Device: Meta Quest, Apple Vision Pro, or Pico 4 Ultra Enterprise

### Installation Path 1: Teleoperation + Deployment

This installation is for:
- ✅ Running XR teleoperation
- ✅ Collecting demonstration data
- ✅ Deploying trained policies on the robot
- ❌ NOT for training new policies

#### Host PC Setup (Where you control the robot)

**System Requirements:** Ubuntu 22.04 or higher, Python 3.10

```bash
# Clone repository
cd /path/to/your/workspace
git clone https://github.com/Autodiscovery/unitree_robotics_suite.git
cd unitree_robotics_suite

# Create conda environment
conda env create -f environment_teleop.yml
conda activate unitree_teleop

# Install local packages
pip install -e ./teleop/teleimager --no-deps
pip install -e ./teleop/televuer
pip install -e ./teleop/robot_control/dex-retargeting

# Install Unitree SDK2 (COMPULSORY for real robot)
pip install git+https://github.com/unitreerobotics/unitree_sdk2_python.git

# Install main package
pip install -e .

```

#### Robot PC Setup (Robot's onboard computer)

The robot needs to run an image server. Choose based on your camera:

**Option A: OAK-D Camera (Custom)** 

```bash
# On robot PC
cd /path/to/unitree_robotics_suite
pip install -r requirements_robot_oakd.txt
pip install -e ./teleop/teleimager --no-deps

# Test camera
python -c "import depthai; print(depthai.Device.getAllAvailableDevices())"

# Run server
cd teleop/teleimager/src
python -m teleimager.oak_d_server
```

**Option B: RealSense Camera**

```bash
# On robot PC
cd /path/to/unitree_robotics_suite
pip install -r requirements_robot_realsense.txt
pip install -e ./teleop/teleimager --no-deps

# Test camera
python -c "import pyrealsense2 as rs; ctx = rs.context(); print(f'Found {len(ctx.devices)} RealSense devices')"

# Run server
cd teleop/teleimager/src
python -m teleimager.image_server  # Use standard server for RealSense
```

#### SSL Certificates for XR Devices

For Meta Quest / Apple Vision Pro / Pico to connect securely:

```bash
cd teleop/televuer

# Generate certificates (choose based on your XR device)

# For Meta Quest / PICO
openssl req -x509 -nodes -days 365 -newkey rsa:2048 -keyout key.pem -out cert.pem

# For Apple Vision Pro (requires special setup)
openssl genrsa -out rootCA.key 2048
openssl req -x509 -new -nodes -key rootCA.key -sha256 -days 365 -out rootCA.pem -subj "/CN=xr-teleoperate"
openssl genrsa -out key.pem 2048
openssl req -new -key key.pem -out server.csr -subj "/CN=localhost"

# Create server_ext.cnf (replace 192.168.123.2 with your host IP)
cat > server_ext.cnf << EOF
subjectAltName = @alt_names
[alt_names]
DNS.1 = localhost
IP.1 = 192.168.123.164
IP.2 = 192.168.123.2
EOF

openssl x509 -req -in server.csr -CA rootCA.pem -CAkey rootCA.key -CAcreateserial \
    -out cert.pem -days 365 -sha256 -extfile server_ext.cnf

# Copy certificates to config directory
mkdir -p ~/.config/xr_teleoperate/
cp cert.pem key.pem ~/.config/xr_teleoperate/

# For Apple Vision Pro: AirDrop rootCA.pem to device and install
```

---

### Installation Path 2: Training

This installation is for:
- ✅ Training imitation learning policies
- ✅ Data processing and conversion
- ✅ Model evaluation
- ❌ NOT for teleoperation or deployment

> [!NOTE]
> Training may require **multiple conda environments** for different models (PI-0.5, GR00T, etc.). 
> Start with the base environment below, then create model-specific environments as needed.

#### Base Training Environment

```bash
# Clone repository (if not already done)
cd /path/to/your/workspace
git clone https://github.com/Autodiscovery/unitree_robotics_suite.git
cd unitree_robotics_suite

# Create conda environment
conda env create -f environment_training.yml
conda activate unitree_training

# Install LeRobot framework (installs ~200+ dependencies)
cd training/lerobot
pip install -e .

# Install unitree-specific training code
cd ../..
pip install -e .

```

#### Model-Specific Environments

Some models may require separate environments:

**PI-0.5 / GR00T Environment:** (Create when needed)
```bash
# Will be documented when implementing these models
# Different transformers/torch versions may be required
```

---

## 🚀 Quick Start

### 1. Test Simulation (Setup Required)

To gather data or test in simulation, you need to set up the [Unitree Isaac Lab Simulation](https://github.com/unitreerobotics/unitree_sim_isaaclab).

1.  **Install Isaac Lab Environment**:
    Follow the [installation guide](https://github.com/unitreerobotics/unitree_sim_isaaclab) to set up Isaac Sim and the Unitree simulation environment.
    *   Requires substantial GPU resources.
    *   Clone the repo: `git clone https://github.com/unitreerobotics/unitree_sim_isaaclab`

2.  **Run Teleoperation with Simulation**:
    Once the simulation environment is running (e.g., waiting for DDS commands via `sim_main.py`), you can use this repository to send controls.

    ```bash
    # In unitree_sim_isaaclab terminal:
    python sim_main.py --device cpu --enable_cameras --task Isaac-PickPlace-Cylinder-G129-Dex1-Joint --enable_dex1_dds --robot_type g129
    ```

    ```bash
    # In unitree_robotics_suite terminal (Teleop Env):
    python teleop/teleop_hand_and_arm.py --arm=G1_29 --ee=dex1 --sim
    ```

### 2. Collect Data on Real Robot

```bash
# Start OAK-D camera server (on robot)
cd teleop/teleimager/src
python -m teleimager.oak_d_server

# Start teleoperation (on workstation)
cd teleop
python teleop_hand_and_arm.py \
    --arm=G1_29 \
    --ee=dex3 \
    --record \
    --task-name="open_door" \
    --task-desc="Open the white door with right hand" \
    --task-steps="1. Approach door; 2. Grasp handle; 3. Turn handle; 4. Push door" \
    --server-ip=192.168.123.164
```

**Teleoperation Arguments:**
- `--arm`: Robot type (`G1_29`, `G1_23`, `H1_2`, `H1`)
- `--ee`: End-effector (`dex1`, `dex3`, `inspire_ftp`, `inspire_dfx`, `brainco`, `hand16`)
- `--task-name`: Name of the directory for saved data (default: "pick cube")
- `--task-desc`: Description of the task for the dataset (default: "task description")
- `--task-steps`: Text description of steps (default: "step1: do this;...")
- `--task-dir`: Path to save data (default: `./utils/data/`)
- `--record`: Enable recording to disk
- `--sim`: Enable simulation mode (communicates with Isaac Lab)
- `--motion`: Enable motion control mode in sports mode for real robot

### 3. Train a Policy

```bash
# Convert data to LeRobot format
# Ensure you are in the TRAINING environment
conda activate unitree_training

python utils/convert_unitree_json_to_lerobot.py \
    --raw-dir teleop/utils/data/open_door \
    --repo-id your_name/open_door_dataset \
    --robot_type Unitree_G1_Dex3 \
    --push_to_hub  # Optional: Upload to Hugging Face
```

**Conversion Arguments:**
- `--raw-dir`: Directory containing your recorded JSON episodes (e.g., `teleop/utils/data/<task_name>`)
- `--repo-id`: Hugging Face repository ID (e.g., `user/dataset_name`)
- `--robot_type`: Type of robot used, matching `ROBOT_CONFIGS` (e.g., `Unitree_G1_Dex3`, `Unitree_H1`, etc.)

```bash
# Train policy with LeRobot
cd training/lerobot
python src/lerobot/scripts/lerobot_train.py \
    --dataset.repo_id=your_name/open_door_dataset \
    --policy.type=diffusion \
    --policy.push_to_hub=false
```

### 4. Deploy Policy

```bash
# Run on real robot
cd deployment
python eval_g1.py \
    --pretrained-policy-name-or-path=outputs/train/diffusion/checkpoints/last/pretrained_model \
    --robot-ip=192.168.123.164
```

---

## 📚 Workflows

### 1. Data Collection (Teleoperation)

#### Simulation Mode
Requires `unitree_sim_isaaclab` running in background.
```bash
cd teleop
python teleop_hand_and_arm.py --arm=G1_29 --ee=dex3 --sim --record --task-name="sim_test"
```

#### Real Robot Mode

**On Robot (Jetson):**
```bash
# Start camera server
cd teleop/teleimager/src
python -m teleimager.oak_d_server
```

**On Workstation:**
```bash
cd teleop
python teleop_hand_and_arm.py \
    --arm=G1_29 \
    --ee=dex3 \
    --record \
    --task-name=pick_and_place \
    --server-ip=192.168.123.164 \
    --motion 
```

**Output:** Episodes saved to `teleop/utils/data/<task_name>/episode_XXXX/`

---

### 2. Data Conversion

Convert recorded JSON episodes to LeRobot HDF5 format:

```bash
python utils/convert_unitree_json_to_lerobot.py \
    --raw-dir teleop/utils/data/pick_and_place \
    --repo-id your_name/pick_and_place_dataset \
    --robot_type Unitree_G1_Dex3 \
    --push_to_hub  # Optional: upload to HuggingFace
```

**Robot Types:**
- `Unitree_G1_Dex1` (23 DOF)
- `Unitree_G1_Dex3` (29 DOF)
- `Unitree_H1` (19 DOF)
- `Unitree_H1_2` (21 DOF)

---

### 3. Policy Training

#### Train with LeRobot

```bash
cd training/lerobot

# ACT Policy
python src/lerobot/scripts/lerobot_train.py \
    --dataset.repo_id=your_name/dataset \
    --policy.type=act \
    --policy.push_to_hub=false

# Diffusion Policy (Recommended)
python src/lerobot/scripts/lerobot_train.py \
    --dataset.repo_id=your_name/dataset \
    --policy.type=diffusion \
    --policy.push_to_hub=false

# Pi0.5 (Vision-Language-Action)
python src/lerobot/scripts/lerobot_train.py \
    --dataset.repo_id=your_name/dataset \
    --policy.type=pi05 \
    --policy.push_to_hub=false
```

**Multi-GPU Training:**
```bash
torchrun --nproc_per_node=4 src/lerobot/scripts/lerobot_train.py \
    --dataset.repo_id=your_name/dataset \
    --policy.type=diffusion
```

**Output:** Model checkpoints in `outputs/train/<policy_type>/checkpoints/`

---

### 4. Policy Deployment

#### Real Robot

**On Robot (Jetson):**
```bash
# Start camera server
cd teleop/teleimager/src
python -m teleimager.oak_d_server
```

**On Workstation:**
```bash
cd deployment
python eval_g1.py \
    --pretrained-policy-name-or-path=outputs/train/diffusion/checkpoints/last/pretrained_model \
    --robot-ip=192.168.123.164 \
    --arm=G1_29
```

#### Simulation

```bash
cd deployment
python eval_g1_sim.py \
    --pretrained-policy-name-or-path=outputs/train/diffusion/checkpoints/last/pretrained_model \
    --arm=G1_29
```

#### Dataset Replay (Debugging)

```bash
cd deployment
python eval_g1_dataset.py \
    --pretrained-policy-name-or-path=outputs/train/diffusion/checkpoints/last/pretrained_model \
    --dataset-repo-id=your_name/dataset
```

---

### 5. Autonomous Execution

Chain multiple policies with navigation for complex tasks:

**On Host PC:**
```bash
cd deployment
python signal_server.py  # Start coordination server
```

**On Robot:**
```bash
cd scripts
./run_autonomous_g1.sh --arm=G1_29
```

**Configuration:** Edit `deployment/autonomous/config.yaml` to define:
- Policy sequence
- Navigation waypoints
- Timeout settings
- Success criteria

---

## 🤖 Supported Hardware

### Robots
- **Unitree G1** (29 DOF, 23 DOF)
- **Unitree H1** (19 DOF)
- **Unitree H1_2** (21 DOF)

### Hands
- **Unitree Dex1** (6 DOF)
- **Unitree Dex3** (12 DOF)
- **Inspire FTP/DFX** (6 DOF)
- **BrainCo** (6 DOF)
- **HAND16** (16 DOF)

### Cameras
- **OAK-D** (RGB + Depth)
- **RealSense D435** (via custom integration)
- **USB Webcams**

### XR Devices
- **Meta Quest 2/3/Pro**
- **Apple Vision Pro**
- **Pico 4 Ultra Enterprise**
- **Browser-based** (WebXR)

---

## 🐛 Troubleshooting

### Robot Connection Issues

```bash
# Check robot IP
ping 192.168.123.164

# Verify SDK installation
python -c "import unitree_sdk2py; print('SDK OK')"

# Check DDS communication
# Robot should be in damping mode, not sport mode
```

### Camera Streaming Issues

```bash
# Verify OAK-D connection
python -c "import depthai as dai; print(dai.Device.getAllAvailableDevices())"

# Check ZMQ ports
netstat -tuln | grep 55555  # ZMQ port
netstat -tuln | grep 60001  # WebRTC port

# Test camera server
cd teleop/teleimager/src
python -m teleimager.oak_d_server
# Open browser: https://<robot-ip>:60001
```

### Training Issues

```bash
# CUDA out of memory
# Reduce batch size in training config

# Slow data loading
# Increase num_workers in dataset config

# NaN loss
# Reduce learning rate or check data normalization
```

---

## 📄 License

This project is licensed under the Apache License 2.0.

Portions of this codebase are derived from:
- [xr_teleoperate](https://github.com/unitreerobotics/xr_teleoperate) (Unitree Robotics)
- [Unitree LeRobot](https://github.com/unitreerobotics/unitree_IL_lerobot) (Unitree Robotics)

---

## 🙏 Acknowledgments

- **Unitree Robotics**
- **HuggingFace** for the LeRobot framework
- **Pinocchio** for inverse kinematics