# GPIO Reader for Unitree G1

Simple Python script to read GPIO5 and GPIO6 binary inputs (switch states) on the Unitree G1's Jetson Orin 16GB.

## GPIO Mapping

Based on Unitree G1 SDK documentation:
- **GPIO5** → GPIO3_PCC.02 (NVIDIA Pin 128) → sysfs name: `PCC.02`
- **GPIO6** → GPIO3_PCC.03 (NVIDIA Pin 130) → sysfs name: `PCC.03`

> [!NOTE]
> This Jetson kernel uses **port.pin naming** (e.g., `PCC.02`) in sysfs instead of numeric GPIO numbers.

## Usage

### Read both GPIO5 and GPIO6:
```bash
sudo python3 teleop/utils/read_gpio.py
```

Output:
```
GPIO5: 0
GPIO6: 1
```

### Read only GPIO5:
```bash
sudo python3 teleop/utils/read_gpio.py --gpio 5
```

Output:
```
GPIO5: 0
```

### Read only GPIO6:
```bash
sudo python3 teleop/utils/read_gpio.py --gpio 6
```

Output:
```
GPIO6: 1
```

### Verbose mode (shows GPIO names):
```bash
sudo python3 teleop/utils/read_gpio.py --verbose
```

Output:
```
GPIO Mappings:
  GPIO5 -> PCC.02 (GPIO3_PCC.02 (NVIDIA Pin 128))
  GPIO6 -> PCC.03 (GPIO3_PCC.03 (NVIDIA Pin 130))

GPIO5 (PCC.02): 0
GPIO6 (PCC.03): 1
```

### Monitor mode (real-time state changes):
```bash
sudo python3 teleop/utils/read_gpio.py --monitor
```

Output:
```
Monitoring GPIO state changes (polling every 0.1s)
Press Ctrl+C to stop

[10:35:42.123] GPIO5: 1 (initial)
[10:35:42.124] GPIO6: 1 (initial)

Monitoring for changes...

[10:35:45.678] GPIO5: 1 → 0 (LOW)
[10:35:47.234] GPIO5: 0 → 1 (HIGH)
[10:35:49.567] GPIO6: 1 → 0 (LOW)
```

### Monitor specific GPIO with custom poll rate:
```bash
sudo python3 teleop/utils/read_gpio.py --monitor --gpio 5 --poll-rate 0.05
```

## Using as a Python Library

```python
from teleop.utils.read_gpio import JetsonGPIOReader

# Create reader instance
reader = JetsonGPIOReader()

# Read GPIO5
value = reader.read_gpio(5)
if value is not None:
    print(f"Switch state: {value}")  # 0 or 1

# Read GPIO6
value = reader.read_gpio(6)
if value is not None:
    print(f"Switch state: {value}")  # 0 or 1

# Cleanup (optional)
reader.cleanup()
```

## Requirements

- **Root privileges**: The script requires sudo to access GPIO sysfs interface
- **No additional installations**: Uses standard Linux sysfs GPIO interface

## Return Values

- `0`: GPIO is LOW (switch not pressed / connected to GND)
- `1`: GPIO is HIGH (switch pressed / connected to 3.3V)

## Notes

- The script automatically exports and configures GPIOs as inputs
- The script handles GPIO setup automatically on first read
- GPIOs are accessed using port.pin naming (PCC.02, PCC.03) as required by this Jetson kernel
