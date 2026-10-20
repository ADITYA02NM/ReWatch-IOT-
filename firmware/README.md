# ReWatch firmware

Two ESP32 boards. Both build with [PlatformIO](https://platformio.org/)
(`pip install platformio`, then `pio run -t upload` inside each folder).

## `esp32-c3-indicator/` — the shelf indicator (NeoPixel + OLED)

The visible state of the appliance. Plugs into the **Pi 4 by USB** and renders
whatever the Pi 4 sends down the serial link at 115200 baud — the score, the
band colour, the fleet, the acknowledge countdown and an ECG trace.

| Wire | From | To |
|------|------|----|
| USB | ESP32-C3 | **Pi 4 USB** (serial 115200, newline JSON) |
| I2C SDA | GPIO5 | SSD1306 OLED SDA |
| I2C SCL | GPIO6 | SSD1306 OLED SCL |
| NeoPixel | GPIO8 (onboard) | — (or external WS2812 DIN) |

Band → pixel: **green** steady · **blue** slow throb (offline) · **yellow** 2 Hz ·
**red** 4 Hz blink · **purple** 1 Hz.

Default build is cable-only. To also drive it from the broker with no host
attached, copy `include/secrets.example.h` to `include/secrets.h`.

## `esp32-wroom-rig/` — the room rig (demo AC controllers)

Models rooms 1–4 as real AC devices on the IoT Wi-Fi: publishes telemetry,
obeys setpoint commands from the Pi 4 responder, and answers `GET /status` for
the Wi-Fi verifier. This is the board that produces the Room-1 20→35 °C event.

Copy `src/secrets.example.h` to `src/secrets.h` first. Press the **BOOT button**
to toggle the Room 1 spike by hand, or use the dashboard "Rig: Room 1 AC spike"
button. **Switch it off and keep it aside** when the building's real IoT devices
are connected — nothing else depends on it.
