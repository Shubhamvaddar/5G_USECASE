# Serial-only BH1750 light sensor firmware

This firmware reads a BH1750 light sensor on the ESP32 and prints one line per sample over USB serial. It does not require Wi-Fi.

## Wiring

- BH1750 SDA -> ESP32 GPIO 21
- BH1750 SCL -> ESP32 GPIO 22
- BH1750 VCC -> 3.3 V (or the breakout board's supported supply)
- BH1750 GND -> ESP32 GND

The firmware probes both BH1750 I2C addresses (`0x23` and `0x5C`). It prints readings as `Light: <lux> lx` at 9600 baud, which matches the SolarTwin laptop collector configuration (`LIGHT_PORT=COM20`, `LIGHT_BAUDRATE=9600`).

## Build and upload

From this folder, use PlatformIO with the `espressif32` platform:

```powershell
platformio run
platformio run --target upload --upload-port COM20
```

The USB serial port must be free before uploading. Stop the laptop collector while flashing, then start it again afterward.
