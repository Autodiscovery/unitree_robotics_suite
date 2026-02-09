from unitree_sdk2py.core.channel import ChannelPublisher, ChannelSubscriber
from unitree_sdk2py.idl.unitree_go.msg.dds_ import MotorCmds_, MotorStates_
from unitree_sdk2py.idl.default import unitree_go_msg_dds__MotorCmd_
from teleop.robot_control.hand_retargeting import HandRetargeting, HandType
import numpy as np
from enum import IntEnum
import threading
import time
from multiprocessing import Process, Array

import logging_mp
logger_mp = logging_mp.get_logger(__name__)

Hand16_Num_Motors = 6
kTopicHand16Command = "rt/hand16/cmd"
kTopicHand16State = "rt/hand16/state"

class Hand16_Controller:
    def __init__(self, left_hand_array, right_hand_array, dual_hand_data_lock=None, 
                 dual_hand_state_array=None, dual_hand_action_array=None, 
                 fps=100.0, Unit_Test=False, simulation_mode=False):
        logger_mp.info("Initialize Hand16_Controller...")
        self.fps = fps
        self.Unit_Test = Unit_Test
        self.simulation_mode = simulation_mode
        
        # Initialize hand retargeting with HAND16 config
        if not self.Unit_Test:
            self.hand_retargeting = HandRetargeting(HandType.HAND16)
        else:
            self.hand_retargeting = HandRetargeting(HandType.HAND16_Unit_Test)
        
        # Initialize DDS publishers/subscribers
        self.HandCmd_publisher = ChannelPublisher(kTopicHand16Command, MotorCmds_)
        self.HandCmd_publisher.Init()
        
        self.HandState_subscriber = ChannelSubscriber(kTopicHand16State, MotorStates_)
        self.HandState_subscriber.Init()
        
        # Shared arrays for hand states
        self.left_hand_state_array = Array('d', Hand16_Num_Motors, lock=True)
        self.right_hand_state_array = Array('d', Hand16_Num_Motors, lock=True)
        
        # Start subscription thread
        self.subscribe_state_thread = threading.Thread(target=self._subscribe_hand_state)
        self.subscribe_state_thread.daemon = True
        self.subscribe_state_thread.start()
        
        # Wait for initial DDS connection
        wait_count = 0
        while True:
            if any(self.right_hand_state_array) or any(self.left_hand_state_array):
                break
            if wait_count % 100 == 0:
                logger_mp.warning("[Hand16_Controller] Waiting to subscribe DDS...")
            time.sleep(0.01)
            wait_count += 1
            if wait_count > 500:  # 5 second timeout
                logger_mp.warning("[Hand16_Controller] Timeout waiting for DDS. Proceeding anyway.")
                break
        logger_mp.info("[Hand16_Controller] Subscribe DDS ok.")
        
        # Start control process
        hand_control_process = Process(
            target=self.control_process,
            args=(left_hand_array, right_hand_array, 
                  self.left_hand_state_array, self.right_hand_state_array,
                  dual_hand_data_lock, dual_hand_state_array, dual_hand_action_array)
        )
        hand_control_process.daemon = True
        hand_control_process.start()
        
        logger_mp.info("Initialize Hand16_Controller OK!")
    
    def _subscribe_hand_state(self):
        while True:
            hand_msg = self.HandState_subscriber.Read()
            if hand_msg is not None:
                # Right hand: indices 0-5, Left hand: indices 6-11
                with self.right_hand_state_array.get_lock():
                    for idx in range(Hand16_Num_Motors):
                        self.right_hand_state_array[idx] = hand_msg.states[idx].q
                with self.left_hand_state_array.get_lock():
                    for idx in range(Hand16_Num_Motors):
                        self.left_hand_state_array[idx] = hand_msg.states[idx + 6].q
            time.sleep(0.002)
    
    def ctrl_dual_hand(self, left_q_target, right_q_target):
        """Send commands to both hands via DDS"""
        # Right hand: indices 0-5
        for idx in range(Hand16_Num_Motors):
            self.hand_msg.cmds[idx].q = right_q_target[idx]
        # Left hand: indices 6-11
        for idx in range(Hand16_Num_Motors):
            self.hand_msg.cmds[idx + 6].q = left_q_target[idx]
        
        self.HandCmd_publisher.Write(self.hand_msg)
    
    def control_process(self, left_hand_array, right_hand_array, 
                       left_hand_state_array, right_hand_state_array,
                       dual_hand_data_lock=None, dual_hand_state_array=None, 
                       dual_hand_action_array=None):
        self.running = True
        
        left_q_target = np.full(Hand16_Num_Motors, 0.0)
        right_q_target = np.full(Hand16_Num_Motors, 0.0)
        
        # Initialize DDS message
        self.hand_msg = MotorCmds_()
        self.hand_msg.cmds = [unitree_go_msg_dds__MotorCmd_() for _ in range(12)]
        
        # Initialize all commands to 0.0
        for idx in range(12):
            self.hand_msg.cmds[idx].q = 0.0
        
        try:
            while self.running:
                start_time = time.time()
                
                # Get XR hand tracking data
                with left_hand_array.get_lock():
                    left_hand_data = np.array(left_hand_array[:]).reshape(25, 3).copy()
                with right_hand_array.get_lock():
                    right_hand_data = np.array(right_hand_array[:]).reshape(25, 3).copy()
                
                # Read current hand state
                state_data = np.concatenate((
                    np.array(left_hand_state_array[:]),
                    np.array(right_hand_state_array[:])
                ))
                
                # Retarget if hand data is valid
                if not np.all(right_hand_data == 0.0) and \
                   not np.all(left_hand_data[4] == np.array([-1.13, 0.3, 0.15])):
                    
                    # Vector retargeting
                    ref_left_value = left_hand_data[self.hand_retargeting.left_indices[1,:]] - \
                                    left_hand_data[self.hand_retargeting.left_indices[0,:]]
                    ref_right_value = right_hand_data[self.hand_retargeting.right_indices[1,:]] - \
                                     right_hand_data[self.hand_retargeting.right_indices[0,:]]
                    
                    left_q_target_raw = self.hand_retargeting.left_retargeting.retarget(ref_left_value)
                    right_q_target_raw = self.hand_retargeting.right_retargeting.retarget(ref_right_value)
                    
                    # Normalize to [0, 1] range
                    # Vector retargeting outputs normalized vectors, need to map to joint space
                    # Using similar normalization as Inspire hands
                    def normalize(val, min_val, max_val):
                        return np.clip((val - min_val) / (max_val - min_val), 0.0, 1.0)
                    
                    # Assuming retargeting outputs are in approximate range [0, 1.7] for fingers
                    # Adjust these ranges based on actual retargeting output
                    left_q_target = np.clip(left_q_target_raw / 1.7, 0.0, 1.0)
                    right_q_target = np.clip(right_q_target_raw / 1.7, 0.0, 1.0)
                
                # Update shared arrays for recording
                action_data = np.concatenate((left_q_target, right_q_target))
                if dual_hand_state_array and dual_hand_action_array:
                    with dual_hand_data_lock:
                        dual_hand_state_array[:] = state_data
                        dual_hand_action_array[:] = action_data
                
                # Send commands
                self.ctrl_dual_hand(left_q_target, right_q_target)
                
                # Maintain control frequency
                current_time = time.time()
                time_elapsed = current_time - start_time
                sleep_time = max(0, (1 / self.fps) - time_elapsed)
                time.sleep(sleep_time)
        finally:
            logger_mp.info("Hand16_Controller has been closed.")

# Joint index definitions (matching DDS message order)
# Order: pinky, ring, middle, index, thumb_bend, thumb_rotation
class Hand16_Right_Hand_JointIndex(IntEnum):
    kRightHandPinky = 0
    kRightHandRing = 1
    kRightHandMiddle = 2
    kRightHandIndex = 3
    kRightHandThumbBend = 4
    kRightHandThumbRotation = 5

class Hand16_Left_Hand_JointIndex(IntEnum):
    kLeftHandPinky = 6
    kLeftHandRing = 7
    kLeftHandMiddle = 8
    kLeftHandIndex = 9
    kLeftHandThumbBend = 10
    kLeftHandThumbRotation = 11
