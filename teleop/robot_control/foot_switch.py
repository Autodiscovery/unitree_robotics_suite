#!/usr/bin/env python3
import evdev
from evdev import InputDevice, categorize, ecodes
import hid
import time
import sys
import math
import argparse
from threading import Thread

# Import common components
from unitree_sdk2py.core.channel import ChannelSubscriber, ChannelFactoryInitialize
from unitree_sdk2py.idl.unitree_go.msg.dds_ import SportModeState_

# Pedal configuration
PEDAL_VENDOR_ID = 0x2563
PEDAL_PRODUCT_ID = 0x0575
PEDAL_AXIS_MAP = {
    0: "action1",       # Left pedal (forward/backward)
    2: "action2",       # Middle pedal (rotate_left/strafe_left)
    5: "action3"        # Right pedal (rotate_right/strafe_right)
}

# Switch configuration
SWITCH_VENDOR_ID = 0x3553
SWITCH_PRODUCT_ID = 0xB001

class MovementMode:
    DEFAULT = "default"  # forward, rotate_left, rotate_right
    ALTERNATE = "alternate"  # backward, strafe_left, strafe_right

class PedalController:
    def __init__(self):
        self.dev = self._find_device()
        self.pedal_values = {'action1': 0, 'action2': 0, 'action3': 0}
        self.running = True
        
    def _find_device(self):
        devices = [InputDevice(path) for path in evdev.list_devices()]
        for device in devices:
            if device.info.vendor == PEDAL_VENDOR_ID and device.info.product == PEDAL_PRODUCT_ID:
                print(f"Found pedal device: {device.path} ({device.name})")
                return device
        raise Exception("Pedal device not found. Make sure it's connected.")

    def update_values(self):
        try:
            for event in self.dev.read_loop():
                if not self.running:
                    break
                if event.type == ecodes.EV_ABS:
                    axis = categorize(event)
                    name = PEDAL_AXIS_MAP.get(axis.event.code)
                    if name:
                        self.pedal_values[name] = axis.event.value
        except OSError:
            # Device disconnected
            print("Pedal device disconnected")
            self.running = False

    def stop(self):
        self.running = False

class FootSwitchController:
    def __init__(self, mode_change_callback):
        self.device = None
        self.pedal_states = {
            4: False,  # Pedal A (switch to default mode)
            5: False,  # Pedal B (unused)
            6: False   # Pedal C (switch to alternate mode)
        }
        self.last_press_time = {4: 0, 5: 0, 6: 0}
        self.debounce_delay = 0.2
        self.mode_change_callback = mode_change_callback
        self.running = True
        
    def initialize_device(self):
        try:
            self.device = hid.device()
            self.device.open(SWITCH_VENDOR_ID, SWITCH_PRODUCT_ID)
            self.device.set_nonblocking(1)
            print(f"Switch device opened: {self.device.get_product_string()}")
            return True
        except IOError as e:
            print(f"Switch device access error: {e}")
            return False
            
    def toggle_pedal(self, pedal_value):
        current_time = time.time()
        
        # Debounce check
        if current_time - self.last_press_time[pedal_value] < self.debounce_delay:
            return
            
        self.last_press_time[pedal_value] = current_time
        self.pedal_states[pedal_value] = not self.pedal_states[pedal_value]
        
        # Handle mode changes
        if pedal_value == 4 and self.pedal_states[pedal_value]:  # Switch A pressed
            print("Switch A pressed - Changing to DEFAULT mode")
            self.mode_change_callback(MovementMode.DEFAULT)
        elif pedal_value == 6 and self.pedal_states[pedal_value]:  # Switch C pressed
            print("Switch C pressed - Changing to ALTERNATE mode")
            self.mode_change_callback(MovementMode.ALTERNATE)
            
    def process_data(self, data):
        # Check for pedal values in positions 3, 4, and 5
        for i in range(3, 6):
            if data[i] in [4, 5, 6]:
                self.toggle_pedal(data[i])

    def update_values(self):
        if not self.device:
            return
            
        try:
            while self.running:
                data = self.device.read(8)
                if data:
                    self.process_data(data)
                time.sleep(0.01)
        except Exception as e:
            print(f"Switch reading error: {e}")
        finally:
            if self.device:
                try:
                    self.device.close()
                except:
                    pass

    def stop(self):
        self.running = False

class RobotController:
    def __init__(self, robot_type="h1", network_interface=""):
        # Store robot type
        self.robot_type = robot_type.lower()
        
        # Initialize channel
        ChannelFactoryInitialize(0, network_interface)
        
        # Import and initialize appropriate client based on robot type
        if self.robot_type == "h1":
            from unitree_sdk2py.h1.loco.h1_loco_client import LocoClient as H1LocoClient
            self.sport_client = H1LocoClient()
            
            # H1-specific parameters
            self.max_distance = 3.0  # meters
            self.max_rotate_angle = 180  # degrees
            self.forward_pedal_baseline = 128  # H1 forward pedal resting value
            
        elif self.robot_type == "g1":
            # Try to import G1 client - note the import path might vary
            try:
                # First try the direct import
                from unitree_sdk2py.g1.loco.g1_loco_client import LocoClient as G1LocoClient
                self.sport_client = G1LocoClient()
            except ImportError:
                # Try alternative import path
                try:
                    from unitree_sdk2py.h1.loco.g1_loco_client import LocoClient as G1LocoClient
                    self.sport_client = G1LocoClient()
                except ImportError:
                    # Fall back to H1 client if G1 not available (some SDKs use same client)
                    print("Note: Using H1 LocoClient for G1 (some SDKs use same client)")
                    from unitree_sdk2py.h1.loco.h1_loco_client import LocoClient as H1LocoClient
                    self.sport_client = H1LocoClient()
            
            # G1-specific parameters (adjust based on your testing)
            self.max_distance = 1.5  # G1 might have smaller movement range
            self.max_rotate_angle = 90  # degrees
            self.forward_pedal_baseline = 128  # Same as H1
            
        else:
            raise ValueError(f"Unsupported robot type: {robot_type}. Use 'h1' or 'g1'")
        
        # Initialize the client
        self.sport_client.SetTimeout(10.0)
        self.sport_client.Init()
        
        # Common configuration
        self.deadzone = 15
        self.forward_pedal_deadzone = 10   # Additional threshold above baseline
        self.last_command = None
        
        # Movement mode
        self.current_mode = MovementMode.DEFAULT
        self.print_mode_info()
        
        # Additional G1-specific features
        if self.robot_type == "g1":
            self.g1_actions = {
                "damp": self.sport_client.Damp,
                "stand": lambda: self.sport_client.Squat2StandUp(),
                "squat": self.sport_client.StandUp2Squat,
                "low_stand": self.sport_client.LowStand,
                "high_stand": self.sport_client.HighStand,
                "wave": self.sport_client.WaveHand,
                "shake": self.sport_client.ShakeHand,
                "lie_stand": lambda: self.sport_client.Lie2StandUp()
            }

    def change_mode(self, new_mode):
        self.current_mode = new_mode
        self.print_mode_info()

    def print_mode_info(self):
        if self.current_mode == MovementMode.DEFAULT:
            print("=== DEFAULT MODE ===")
            print("Left pedal: Forward | Middle pedal: Rotate Left | Right pedal: Rotate Right")
        else:
            print("=== ALTERNATE MODE ===")
            print("Left pedal: Backward | Middle pedal: Strafe Left | Right pedal: Strafe Right")
        print("=" * 50)

    def _scale_value(self, value, max_distance):
        value = max(0, value - self.deadzone)
        return (value / (255 - self.deadzone)) * max_distance

    def _scale_forward_pedal_value(self, value, max_distance):
        # For forward pedal: baseline is 128, so we need to subtract that first
        effective_value = max(0, value - self.forward_pedal_baseline - self.forward_pedal_deadzone)
        max_effective_range = 255 - self.forward_pedal_baseline - self.forward_pedal_deadzone
        return (effective_value / max_effective_range) * max_distance

    def _is_pedal_pressed(self, pedal_name, value):
        if pedal_name == "action1":  # Left pedal (forward/backward)
            # Forward pedal is pressed if it's significantly above its baseline
            return value > (self.forward_pedal_baseline + self.forward_pedal_deadzone)
        else:
            # Rotation/strafe pedals use normal deadzone
            return value > self.deadzone

    def _execute_movement(self, pedal_name, value):
        """Execute movement based on current mode and pedal pressed"""
        if self.current_mode == MovementMode.DEFAULT:
            # Default mode: forward, rotate_left, rotate_right
            if pedal_name == "action1":  # Left pedal -> Forward
                distance = self._scale_forward_pedal_value(value, self.max_distance)
                print(f"Moving forward {distance:.2f}m")
                self.sport_client.Move(distance, 0, 0)
            elif pedal_name == "action2":  # Middle pedal -> Rotate Left
                angle = self._scale_value(value, self.max_rotate_angle)
                print(f"Rotating {angle:.1f}° left")
                self.sport_client.Move(0, 0, math.radians(angle))
            elif pedal_name == "action3":  # Right pedal -> Rotate Right
                angle = self._scale_value(value, self.max_rotate_angle)
                print(f"Rotating {angle:.1f}° right")
                self.sport_client.Move(0, 0, math.radians(angle) * -1)
        else:
            # Alternate mode: backward, strafe_left, strafe_right
            if pedal_name == "action1":  # Left pedal -> Backward
                distance = self._scale_forward_pedal_value(value, self.max_distance)
                print(f"Moving backward {distance:.2f}m")
                self.sport_client.Move(-distance, 0, 0)
            elif pedal_name == "action2":  # Middle pedal -> Strafe Left
                distance = self._scale_value(value, self.max_distance)
                print(f"Strafing left {distance:.2f}m")
                self.sport_client.Move(0, distance, 0)
            elif pedal_name == "action3":  # Right pedal -> Strafe Right
                distance = self._scale_value(value, self.max_distance)
                print(f"Strafing right {distance:.2f}m")
                self.sport_client.Move(0, -distance, 0)

    def control_loop(self, pedal_controller):
        print(f"Starting combined pedal and switch control for {self.robot_type.upper()}...")
        print(f"Forward pedal baseline: {self.forward_pedal_baseline}, deadzone: {self.forward_pedal_deadzone}")
        prev_state = {name: False for name in PEDAL_AXIS_MAP.values()}
        
        # If G1, offer additional control options
        if self.robot_type == "g1":
            print("\nAdditional G1 Controls (via keyboard while running):")
            print("  'd' - Damp mode")
            print("  's' - Stand up")
            print("  'q' - Squat down")
            print("  'l' - Low stand")
            print("  'h' - High stand")
            print("  'w' - Wave hand")
            print("  'k' - Shake hand")
            print("  'b' - Lie to stand (CAUTION)")
            print()
        
        try:
            while pedal_controller.running:
                current_values = pedal_controller.pedal_values
                
                # Check each pedal for new presses
                for pedal in PEDAL_AXIS_MAP.values():
                    current_value = current_values[pedal]
                    is_pressed = self._is_pedal_pressed(pedal, current_value)
                    was_pressed = prev_state[pedal]
                    
                    if is_pressed and not was_pressed:
                        # New pedal press detected
                        self._execute_movement(pedal, current_value)
                        self.last_command = time.time()
                    
                    prev_state[pedal] = is_pressed

                # Handle keyboard input for G1 special actions
                if self.robot_type == "g1":
                    try:
                        import select
                        import termios
                        import tty
                        
                        # Check for keyboard input without blocking
                        old_settings = termios.tcgetattr(sys.stdin)
                        try:
                            tty.setcbreak(sys.stdin.fileno())
                            
                            if select.select([sys.stdin], [], [], 0)[0]:
                                key = sys.stdin.read(1)
                                
                                if key == 'd':
                                    print("Activating damp mode")
                                    self.sport_client.Damp()
                                elif key == 's':
                                    print("Standing up")
                                    self.sport_client.Damp()
                                    time.sleep(0.5)
                                    self.sport_client.Squat2StandUp()
                                elif key == 'q':
                                    print("Squatting down")
                                    self.sport_client.StandUp2Squat()
                                elif key == 'l':
                                    print("Low stand")
                                    self.sport_client.LowStand()
                                elif key == 'h':
                                    print("High stand")
                                    self.sport_client.HighStand()
                                elif key == 'w':
                                    print("Waving hand")
                                    self.sport_client.WaveHand()
                                elif key == 'k':
                                    print("Shaking hand")
                                    self.sport_client.ShakeHand()
                                    time.sleep(3)
                                    self.sport_client.ShakeHand()
                                elif key == 'b':
                                    print("CAUTION: Lie to stand - ensure robot is on hard, flat surface")
                                    self.sport_client.Damp()
                                    time.sleep(0.5)
                                    self.sport_client.Lie2StandUp()
                                
                        finally:
                            termios.tcsetattr(sys.stdin, termios.TCSADRAIN, old_settings)
                    except ImportError:
                        # If termios not available (Windows), skip keyboard input
                        pass
                
                time.sleep(0.02)

        except KeyboardInterrupt:
            print("\nExiting...")

def main():
    parser = argparse.ArgumentParser(description='Unitree Robot Pedal Controller')
    parser.add_argument('network_interface', nargs='?', default='',
                       help='Network interface (e.g., eth0)')
    parser.add_argument('--robot', choices=['h1', 'g1'], default='h1',
                       help='Robot type: h1 or g1 (default: h1)')
    
    args = parser.parse_args()
    
    print(f"WARNING: Ensure the {args.robot.upper()} robot has space and is powered on!")
    print(f"Robot Type: {args.robot.upper()}")
    print("Switch A: Default mode | Switch C: Alternate mode")
    print()
    
    # Initialize robot controller
    robot_controller = RobotController(robot_type=args.robot, 
                                      network_interface=args.network_interface)
    
    # Initialize pedal controller
    try:
        pedal_controller = PedalController()
    except Exception as e:
        print(f"Failed to initialize pedal controller: {e}")
        return

    # Initialize switch controller
    switch_controller = FootSwitchController(robot_controller.change_mode)
    switch_available = switch_controller.initialize_device()
    
    if not switch_available:
        print("Switch controller not available - continuing with pedals only in default mode")

    # Start separate threads
    pedal_thread = Thread(target=pedal_controller.update_values, daemon=True)
    pedal_thread.start()

    if switch_available:
        switch_thread = Thread(target=switch_controller.update_values, daemon=True)
        switch_thread.start()

    try:
        # Start control loop
        robot_controller.control_loop(pedal_controller)
    finally:
        # Clean shutdown
        pedal_controller.stop()
        if switch_available:
            switch_controller.stop()

if __name__ == "__main__":
    main()
