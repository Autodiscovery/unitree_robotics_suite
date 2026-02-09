from unitree_sdk2py.core.channel import ChannelPublisher, ChannelSubscriber, ChannelFactoryInitialize # dds
from unitree_sdk2py.idl.unitree_go.msg.dds_ import MotorCmds_, MotorStates_                           # idl
from unitree_sdk2py.idl.default import unitree_go_msg_dds__MotorCmd_

from teleop.robot_control.hand_retargeting import HandRetargeting, HandType
import numpy as np
from enum import IntEnum
import threading
import time
from multiprocessing import Process, Array, Value

import logging_mp
logger_mp = logging_mp.get_logger(__name__)

brainco_Num_Motors = 6
kTopicbraincoLeftCommand = "rt/brainco/left/cmd"
kTopicbraincoLeftState = "rt/brainco/left/state"
kTopicbraincoRightCommand = "rt/brainco/right/cmd"
kTopicbraincoRightState = "rt/brainco/right/state"

class Brainco_Controller:
    def __init__(self, left_hand_array, right_hand_array, dual_hand_data_lock = None, dual_hand_state_array = None,
                       dual_hand_action_array = None, fps = 100.0, Unit_Test = False, simulation_mode = False, 
                       hands='both'):
        logger_mp.info("Initialize Brainco_Controller...")
        self.fps = fps
        self.Unit_Test = Unit_Test
        self.simulation_mode = simulation_mode
        self.hands = hands.lower()  # 'left', 'right', or 'both'

        logger_mp.info(f"Brainco_Controller hand configuration: {self.hands}")

        if not self.Unit_Test:
            self.hand_retargeting = HandRetargeting(HandType.BRAINCO_HAND)
        else:
            self.hand_retargeting = HandRetargeting(HandType.BRAINCO_HAND_Unit_Test)

        if self.simulation_mode:
            ChannelFactoryInitialize(1)
        else:
            ChannelFactoryInitialize(0)

        # Initialize publishers and subscribers based on hand configuration
        if self.hands in ['left', 'both']:
            self.LeftHandCmb_publisher = ChannelPublisher(kTopicbraincoLeftCommand, MotorCmds_)
            self.LeftHandCmb_publisher.Init()
            self.LeftHandState_subscriber = ChannelSubscriber(kTopicbraincoLeftState, MotorStates_)
            self.LeftHandState_subscriber.Init()
        else:
            self.LeftHandCmb_publisher = None
            self.LeftHandState_subscriber = None
            logger_mp.info("Left hand disabled")

        if self.hands in ['right', 'both']:
            self.RightHandCmb_publisher = ChannelPublisher(kTopicbraincoRightCommand, MotorCmds_)
            self.RightHandCmb_publisher.Init()
            self.RightHandState_subscriber = ChannelSubscriber(kTopicbraincoRightState, MotorStates_)
            self.RightHandState_subscriber.Init()
        else:
            self.RightHandCmb_publisher = None
            self.RightHandState_subscriber = None
            logger_mp.info("Right hand disabled")

        # Shared Arrays for hand states
        self.left_hand_state_array  = Array('d', brainco_Num_Motors, lock=True)  
        self.right_hand_state_array = Array('d', brainco_Num_Motors, lock=True)
        
        # Shared flags for hand readiness
        self.left_hand_ready_flag = Value('i', 0, lock=True)
        self.right_hand_ready_flag = Value('i', 0, lock=True)

        # Initialize with zeros
        for i in range(brainco_Num_Motors):
            self.left_hand_state_array[i] = 0.0
            self.right_hand_state_array[i] = 0.0

        # Quick initial detection only for enabled hands
        logger_mp.info("Detecting hands...")
        left_detected = False
        right_detected = False
        
        for attempt in range(10):
            if self.hands in ['left', 'both'] and not left_detected:
                left_msg = self.LeftHandState_subscriber.Read()
                if left_msg is not None:
                    left_detected = True
                    logger_mp.info("✓ Left hand detected")
                    for idx, id in enumerate(Brainco_Left_Hand_JointIndex):
                        self.left_hand_state_array[idx] = left_msg.states[id].q
                    with self.left_hand_ready_flag.get_lock():
                        self.left_hand_ready_flag.value = 1
            
            if self.hands in ['right', 'both'] and not right_detected:
                right_msg = self.RightHandState_subscriber.Read()
                if right_msg is not None:
                    right_detected = True
                    logger_mp.info("✓ Right hand detected")
                    for idx, id in enumerate(Brainco_Right_Hand_JointIndex):
                        self.right_hand_state_array[idx] = right_msg.states[id].q
                    with self.right_hand_ready_flag.get_lock():
                        self.right_hand_ready_flag.value = 1
            
            if (self.hands == 'left' and left_detected) or \
               (self.hands == 'right' and right_detected) or \
               (self.hands == 'both' and (left_detected or right_detected)):
                break
            
            time.sleep(0.1)
        
        if not left_detected and self.hands in ['left', 'both']:
            logger_mp.warning("Left hand not detected initially")
        if not right_detected and self.hands in ['right', 'both']:
            logger_mp.warning("Right hand not detected initially")

        # Start subscription thread for enabled hands
        self.subscribe_state_thread = threading.Thread(target=self._subscribe_hand_state)
        self.subscribe_state_thread.daemon = True
        self.subscribe_state_thread.start()

        # Wait for enabled hands to be ready with timeout
        timeout = 5.0
        start_wait = time.time()
        
        # Check initial detection status
        with self.left_hand_ready_flag.get_lock():
            left_ready = self.left_hand_ready_flag.value == 1
        with self.right_hand_ready_flag.get_lock():
            right_ready = self.right_hand_ready_flag.value == 1
            
        # If no hands detected initially, wait for subscription thread
        needs_wait = False
        if self.hands in ['left', 'both'] and not left_ready:
            needs_wait = True
        if self.hands in ['right', 'both'] and not right_ready:
            needs_wait = True
            
        if needs_wait:
            logger_mp.info("Waiting for subscription thread to detect hands...")
            while True:
                elapsed = time.time() - start_wait
                
                with self.left_hand_ready_flag.get_lock():
                    left_ready = self.left_hand_ready_flag.value == 1
                with self.right_hand_ready_flag.get_lock():
                    right_ready = self.right_hand_ready_flag.value == 1
                
                # Check if we have at least one enabled hand ready
                ready = False
                if self.hands == 'left' and left_ready:
                    ready = True
                elif self.hands == 'right' and right_ready:
                    ready = True
                elif self.hands == 'both' and (left_ready or right_ready):
                    ready = True
                
                if ready:
                    break
                
                if elapsed > timeout:
                    logger_mp.warning(f"Timeout waiting for hand subscription after {timeout}s. Proceeding anyway...")
                    break
                
                time.sleep(0.1)
                logger_mp.warning(f"Waiting to subscribe dds... ({elapsed:.1f}s)")
        
        if left_ready and self.hands in ['left', 'both']:
            logger_mp.info("Left hand ready.")
        if right_ready and self.hands in ['right', 'both']:
            logger_mp.info("Right hand ready.")
        
        if (left_ready and self.hands in ['left', 'both']) or (right_ready and self.hands in ['right', 'both']):
            logger_mp.info("Subscribe dds ok. Proceeding with available hands.")
        else:
            logger_mp.warning("No hands ready, but proceeding anyway.")

        # Use multiprocessing for control
        hand_control_process = Process(target=self.control_process, args=(left_hand_array, right_hand_array,  
                                                                          self.left_hand_state_array, self.right_hand_state_array,
                                                                          self.left_hand_ready_flag, self.right_hand_ready_flag,
                                                                          dual_hand_data_lock, dual_hand_state_array, 
                                                                          dual_hand_action_array))
        hand_control_process.daemon = True
        hand_control_process.start()

        logger_mp.info("Initialize brainco_Controller OK!\n")

    def _subscribe_hand_state(self):
        """Subscribe to hand state messages - only for enabled hands"""
        while True:
            try:
                if self.hands in ['left', 'both']:
                    left_hand_msg = self.LeftHandState_subscriber.Read()
                    if left_hand_msg is not None:
                        with self.left_hand_ready_flag.get_lock():
                            self.left_hand_ready_flag.value = 1
                        for idx, id in enumerate(Brainco_Left_Hand_JointIndex):
                            self.left_hand_state_array[idx] = left_hand_msg.states[id].q
                
                if self.hands in ['right', 'both']:
                    right_hand_msg = self.RightHandState_subscriber.Read()
                    if right_hand_msg is not None:
                        with self.right_hand_ready_flag.get_lock():
                            self.right_hand_ready_flag.value = 1
                        for idx, id in enumerate(Brainco_Right_Hand_JointIndex):
                            self.right_hand_state_array[idx] = right_hand_msg.states[id].q
                
                time.sleep(0.002)
            except Exception as e:
                logger_mp.error(f"Error in _subscribe_hand_state: {e}")
                time.sleep(0.01)

    def ctrl_dual_hand(self, left_q_target, right_q_target, left_hand_msg, right_hand_msg, 
                       left_ready, right_ready):
        """
        Set current left, right hand motor state target q - only for enabled hands
        """
        try:
            if left_ready and self.hands in ['left', 'both']:
                for idx, id in enumerate(Brainco_Left_Hand_JointIndex):             
                    left_hand_msg.cmds[id].q = left_q_target[idx]
                self.LeftHandCmb_publisher.Write(left_hand_msg)
            
            if right_ready and self.hands in ['right', 'both']:
                for idx, id in enumerate(Brainco_Right_Hand_JointIndex):             
                    right_hand_msg.cmds[id].q = right_q_target[idx]
                self.RightHandCmb_publisher.Write(right_hand_msg)
        except Exception as e:
            logger_mp.error(f"Error in ctrl_dual_hand: {e}")
    
    def control_process(self, left_hand_array, right_hand_array, left_hand_state_array, right_hand_state_array,
                              left_hand_ready_flag, right_hand_ready_flag,
                              dual_hand_data_lock = None, dual_hand_state_array = None, dual_hand_action_array = None):
        self.running = True

        left_q_target  = np.full(brainco_Num_Motors, 0)
        right_q_target = np.full(brainco_Num_Motors, 0)

        # Initialize hand command messages only for enabled hands
        if self.hands in ['left', 'both']:
            left_hand_msg = MotorCmds_()
            left_hand_msg.cmds = [unitree_go_msg_dds__MotorCmd_() for _ in range(len(Brainco_Left_Hand_JointIndex))]
            for idx, id in enumerate(Brainco_Left_Hand_JointIndex):
                left_hand_msg.cmds[id].q = 0.0
                left_hand_msg.cmds[id].dq = 1.0
        else:
            left_hand_msg = None

        if self.hands in ['right', 'both']:
            right_hand_msg = MotorCmds_()
            right_hand_msg.cmds = [unitree_go_msg_dds__MotorCmd_() for _ in range(len(Brainco_Right_Hand_JointIndex))]
            for idx, id in enumerate(Brainco_Right_Hand_JointIndex):
                right_hand_msg.cmds[id].q = 0.0
                right_hand_msg.cmds[id].dq = 1.0
        else:
            right_hand_msg = None

        # Read initial ready status
        with left_hand_ready_flag.get_lock():
            left_ready = left_hand_ready_flag.value == 1 and self.hands in ['left', 'both']
        with right_hand_ready_flag.get_lock():
            right_ready = right_hand_ready_flag.value == 1 and self.hands in ['right', 'both']

        logger_mp.info(f"Control process started. Left hand ready: {left_ready}, Right hand ready: {right_ready}")

        try:
            while self.running:
                start_time = time.time()
                
                # Read current ready status from shared flags
                with left_hand_ready_flag.get_lock():
                    left_ready = left_hand_ready_flag.value == 1 and self.hands in ['left', 'both']
                with right_hand_ready_flag.get_lock():
                    right_ready = right_hand_ready_flag.value == 1 and self.hands in ['right', 'both']
                
                # Get hand data from shared arrays
                try:
                    with left_hand_array.get_lock():
                        left_hand_data  = np.array(left_hand_array[:]).reshape(25, 3).copy()
                    with right_hand_array.get_lock():
                        right_hand_data = np.array(right_hand_array[:]).reshape(25, 3).copy()
                except Exception as e:
                    logger_mp.error(f"Error reading hand arrays: {e}")
                    time.sleep(0.01)
                    continue

                # Read left and right q_state from shared arrays
                state_data = np.concatenate((np.array(left_hand_state_array[:]), np.array(right_hand_state_array[:])))

                # Check if hand data is valid
                left_data_valid = not np.all(left_hand_data[4] == np.array([-1.13, 0.3, 0.15]))
                right_data_valid = not np.all(right_hand_data == 0.0)

                # Process left hand if enabled, connected, and data is valid
                if left_ready and left_data_valid and self.hands in ['left', 'both']:
                    try:
                        ref_left_value = left_hand_data[self.hand_retargeting.left_indices[1,:]] - left_hand_data[self.hand_retargeting.left_indices[0,:]]
                        left_q_target  = self.hand_retargeting.left_retargeting.retarget(ref_left_value)[self.hand_retargeting.left_dex_retargeting_to_hardware]

                        # Normalize left hand values
                        for idx in range(brainco_Num_Motors):
                            if idx == 0:
                                left_q_target[idx]  = self._normalize(left_q_target[idx], 0.0, 1.52)
                            elif idx == 1:
                                left_q_target[idx]  = self._normalize(left_q_target[idx], 0.0, 1.05)
                            elif idx >= 2:
                                left_q_target[idx]  = self._normalize(left_q_target[idx], 0.0, 1.47)
                    except Exception as e:
                        logger_mp.error(f"Error processing left hand: {e}")
                        left_q_target = np.full(brainco_Num_Motors, 0)
                else:
                    left_q_target = np.full(brainco_Num_Motors, 0)

                # Process right hand if enabled, connected, and data is valid
                if right_ready and right_data_valid and self.hands in ['right', 'both']:
                    try:
                        ref_right_value = right_hand_data[self.hand_retargeting.right_indices[1,:]] - right_hand_data[self.hand_retargeting.right_indices[0,:]]
                        right_q_target = self.hand_retargeting.right_retargeting.retarget(ref_right_value)[self.hand_retargeting.right_dex_retargeting_to_hardware]

                        # Normalize right hand values
                        for idx in range(brainco_Num_Motors):
                            if idx == 0:
                                right_q_target[idx] = self._normalize(right_q_target[idx], 0.0, 1.52)
                            elif idx == 1:
                                right_q_target[idx] = self._normalize(right_q_target[idx], 0.0, 1.05)
                            elif idx >= 2:
                                right_q_target[idx] = self._normalize(right_q_target[idx], 0.0, 1.47)
                    except Exception as e:
                        logger_mp.error(f"Error processing right hand: {e}")
                        right_q_target = np.full(brainco_Num_Motors, 0)
                else:
                    right_q_target = np.full(brainco_Num_Motors, 0)

                # Get dual hand action
                action_data = np.concatenate((left_q_target, right_q_target))    
                if dual_hand_state_array and dual_hand_action_array and dual_hand_data_lock:
                    try:
                        with dual_hand_data_lock:
                            dual_hand_state_array[:] = state_data
                            dual_hand_action_array[:] = action_data
                    except Exception as e:
                        logger_mp.error(f"Error updating dual hand arrays: {e}")
                
                self.ctrl_dual_hand(left_q_target, right_q_target, left_hand_msg, right_hand_msg, left_ready, right_ready)
                
                current_time = time.time()
                time_elapsed = current_time - start_time
                sleep_time = max(0, (1 / self.fps) - time_elapsed)
                time.sleep(sleep_time)
        except Exception as e:
            logger_mp.error(f"Error in control_process: {e}", exc_info=True)
        finally:
            logger_mp.info("brainco_Controller has been closed.")

    def _normalize(self, val, min_val, max_val):
        """Normalize values from radians to [0, 1] range"""
        return 1.0 - np.clip((max_val - val) / (max_val - min_val), 0.0, 1.0)

    def close(self):
        """Properly close the controller"""
        logger_mp.info("Closing Brainco_Controller...")
        self.running = False
        logger_mp.info("Brainco_Controller closed")

# Brainco Hand Joint Index definitions remain the same...
class Brainco_Right_Hand_JointIndex(IntEnum):
    kRightHandThumb = 0
    kRightHandThumbAux = 1
    kRightHandIndex = 2
    kRightHandMiddle = 3
    kRightHandRing = 4
    kRightHandPinky = 5

class Brainco_Left_Hand_JointIndex(IntEnum):
    kLeftHandThumb = 0
    kLeftHandThumbAux = 1
    kLeftHandIndex = 2
    kLeftHandMiddle = 3
    kLeftHandRing = 4
    kLeftHandPinky = 5
