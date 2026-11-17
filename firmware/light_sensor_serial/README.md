# SolarTwin Wi-Fi light node

The ESP32 reads a BH1750 over I²C and posts real lux readings directly to the VM over Wi-Fi. The laptop collector is not part of this path.

## Wiring

- BH1750 SDA -> ESP32 GPIO 21
- BH1750 SCL -> ESP32 GPIO 22
- BH1750 VCC -> 3.3 V (or the breakout board's supported supply)
- BH1750 GND -> ESP32 GND

The firmware probes BH1750 addresses `0x23` and `0x5C`, takes a fresh one-shot high-resolution reading every five seconds, and posts JSON to `http://172.16.0.188:8000/api/sensors/data` with `node`, `light_lux`, and `source: real` fields.

## Wi-Fi credentials

Copy `src/wifi_secrets.example.h` to `src/wifi_secrets.h` and fill in the 2.4 GHz SSID and password. The real credentials file is ignored by Git; never commit it. Use a network that can reach the VM at `172.16.0.188`.

## Build and upload

From this folder:

```powershell
platformio run
platformio run --target upload --upload-port COM20
```

Stop any process using COM20 before uploading. The serial console runs at 9600 baud and reports Wi-Fi connection and VM HTTP status. After upload, the ESP32 sends readings directly to the VM; it no longer needs the laptop collector.
