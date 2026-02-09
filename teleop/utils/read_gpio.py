#!/usr/bin/env python3
"""
GPIO Reader for Unitree G1 (Jetson Orin 16GB)
Reads GPIO5 and GPIO6 binary inputs (switch states)

GPIO Mapping (from Unitree G1 SDK):
- GPIO5 = PCC.02 (GPIO3_PCC.02, NVIDIA Pin 128)
- GPIO6 = PCC.03 (GPIO3_PCC.03, NVIDIA Pin 130)

Usage:
    sudo python3 read_gpio.py              # Read both GPIO5 and GPIO6
    sudo python3 read_gpio.py --gpio 5     # Read only GPIO5
    sudo python3 read_gpio.py --gpio 6     # Read only GPIO6
"""

import os
import sys
import argparse


class JetsonGPIOReader:
    """Read GPIO inputs on Jetson Orin using sysfs interface"""
    
    # GPIO mapping from Unitree G1 documentation
    # This Jetson kernel uses port.pin naming (e.g., "PCC.02") instead of numeric GPIOs
    GPIO_MAPPING = {
        5: {'name': 'PCC.02', 'description': 'GPIO3_PCC.02 (NVIDIA Pin 128)'},  # GPIO5
        6: {'name': 'PCC.03', 'description': 'GPIO3_PCC.03 (NVIDIA Pin 130)'},  # GPIO6
    }
    
    def __init__(self):
        """Initialize GPIO reader"""
        # Store GPIO names (port.pin format used by this kernel)
        self.gpio_names = {gpio_id: info['name'] for gpio_id, info in self.GPIO_MAPPING.items()}
    
    def _export_gpio(self, gpio_name):
        """Export GPIO if not already exported"""
        gpio_path = f"/sys/class/gpio/{gpio_name}"
        
        if os.path.exists(gpio_path):
            return True
            
        try:
            with open("/sys/class/gpio/export", "w") as f:
                f.write(gpio_name)
            return True
        except IOError as e:
            print(f"Error exporting GPIO {gpio_name}: {e}", file=sys.stderr)
            return False
    
    def _set_direction(self, gpio_name, direction="in"):
        """Set GPIO direction (in/out)"""
        direction_path = f"/sys/class/gpio/{gpio_name}/direction"
        
        try:
            with open(direction_path, "w") as f:
                f.write(direction)
            return True
        except IOError as e:
            print(f"Error setting direction for GPIO {gpio_name}: {e}", file=sys.stderr)
            return False
    
    def setup_gpio(self, gpio_id):
        """Setup GPIO for reading (export and set as input)"""
        if gpio_id not in self.gpio_names:
            print(f"Error: Invalid GPIO ID {gpio_id}. Valid IDs: {list(self.gpio_names.keys())}", 
                  file=sys.stderr)
            return False
        
        gpio_name = self.gpio_names[gpio_id]
        
        if not self._export_gpio(gpio_name):
            return False
        
        if not self._set_direction(gpio_name, "in"):
            return False
        
        return True
    
    def read_gpio(self, gpio_id):
        """
        Read GPIO value
        
        Args:
            gpio_id: GPIO identifier (5 or 6)
            
        Returns:
            int: 0 or 1, or None if error
        """
        if gpio_id not in self.gpio_names:
            print(f"Error: Invalid GPIO ID {gpio_id}", file=sys.stderr)
            return None
        
        gpio_name = self.gpio_names[gpio_id]
        value_path = f"/sys/class/gpio/{gpio_name}/value"
        
        # Setup GPIO if not already done
        if not os.path.exists(value_path):
            if not self.setup_gpio(gpio_id):
                return None
        else:
            # Ensure it's set as input
            self._set_direction(gpio_name, "in")
        
        try:
            with open(value_path, "r") as f:
                value = int(f.read().strip())
            return value
        except IOError as e:
            print(f"Error reading GPIO {gpio_id} ({gpio_name}): {e}", file=sys.stderr)
            return None
    
    def cleanup(self, gpio_id=None):
        """
        Unexport GPIO(s)
        
        Args:
            gpio_id: Specific GPIO to cleanup, or None for all
        """
        gpio_ids = [gpio_id] if gpio_id else list(self.gpio_names.keys())
        
        for gid in gpio_ids:
            if gid not in self.gpio_names:
                continue
                
            gpio_name = self.gpio_names[gid]
            try:
                with open("/sys/class/gpio/unexport", "w") as f:
                    f.write(gpio_name)
            except IOError:
                pass  # GPIO might not be exported


def main():
    """Main function for command-line usage"""
    parser = argparse.ArgumentParser(
        description='Read GPIO inputs from Unitree G1 (Jetson Orin)'
    )
    parser.add_argument(
        '--gpio', 
        type=int, 
        choices=[5, 6],
        help='Specific GPIO to read (5 or 6). If not specified, reads both.'
    )
    parser.add_argument(
        '--verbose', 
        action='store_true',
        help='Show verbose output with GPIO names'
    )
    parser.add_argument(
        '--monitor',
        action='store_true',
        help='Continuously monitor GPIO state changes in real-time'
    )
    parser.add_argument(
        '--poll-rate',
        type=float,
        default=0.1,
        help='Polling rate in seconds for monitor mode (default: 0.1)'
    )
    
    args = parser.parse_args()
    
    # Check if running as root
    if os.geteuid() != 0:
        print("Error: This script requires root privileges. Run with sudo.", file=sys.stderr)
        sys.exit(1)
    
    # Create reader
    reader = JetsonGPIOReader()
    
    if args.verbose:
        print(f"GPIO Mappings:")
        for gpio_id, gpio_name in reader.gpio_names.items():
            info = reader.GPIO_MAPPING[gpio_id]
            print(f"  GPIO{gpio_id} -> {gpio_name} ({info['description']})")
        print()
    
    # Determine which GPIOs to monitor
    gpio_ids = [args.gpio] if args.gpio else [5, 6]
    
    # Monitor mode - continuous polling
    if args.monitor:
        import time
        from datetime import datetime
        
        print(f"Monitoring GPIO state changes (polling every {args.poll_rate}s)")
        print("Press Ctrl+C to stop\n")
        
        # Store previous states
        prev_states = {}
        for gpio_id in gpio_ids:
            value = reader.read_gpio(gpio_id)
            if value is not None:
                prev_states[gpio_id] = value
                timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
                print(f"[{timestamp}] GPIO{gpio_id}: {value} (initial)")
        
        print("\nMonitoring for changes...\n")
        
        try:
            while True:
                time.sleep(args.poll_rate)
                
                for gpio_id in gpio_ids:
                    value = reader.read_gpio(gpio_id)
                    if value is None:
                        continue
                    
                    # Check if state changed
                    if gpio_id in prev_states and prev_states[gpio_id] != value:
                        timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
                        change = "HIGH" if value == 1 else "LOW"
                        print(f"[{timestamp}] GPIO{gpio_id}: {prev_states[gpio_id]} → {value} ({change})")
                        prev_states[gpio_id] = value
                    elif gpio_id not in prev_states:
                        prev_states[gpio_id] = value
                        
        except KeyboardInterrupt:
            print("\n\nMonitoring stopped.")
            sys.exit(0)
    
    # Single read mode
    else:
        for gpio_id in gpio_ids:
            value = reader.read_gpio(gpio_id)
            if value is not None:
                if args.verbose:
                    gpio_name = reader.gpio_names[gpio_id]
                    print(f"GPIO{gpio_id} ({gpio_name}): {value}")
                else:
                    print(f"GPIO{gpio_id}: {value}")
            else:
                print(f"GPIO{gpio_id}: ERROR", file=sys.stderr)
                sys.exit(1)


if __name__ == "__main__":
    main()
