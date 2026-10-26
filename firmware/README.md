# ReWatch(Iot) firmware

**Last updated: 2026-10-26**

Both ESP32 boards are enclosure components: **C3 = display of the Pi 4 engine**,
**WROOM = optional four-room Black Hat AC rig**. WROOM uses Wi-Fi MQTT; C3 can
use its optional MQTT transport or the stock serial transport. The laptop is
used for flashing and administration, not as their required runtime host.
Neither board computes threat scores. The rig
models temperatures in software; it does not switch a real AC, relay or mains load.

## Build and flash

Run these from the repository root with Python 3 and PlatformIO Core installed:

```sh
python3 -m pip install --user platformio
pio device list
pio run -d firmware/esp32-c3-indicator -e esp32-c3-devkitm-1
pio run -d firmware/esp32-wroom-rig -e compile-check
```

The C3 default needs **no credentials** and does not start its radio. The rig's
`compile-check` environment uses only the public `src/secrets.example.h` placeholders;
**do not flash that image**. For deployment, create
`firmware/esp32-wroom-rig/src/secrets.h` from the adjacent example and fill in
your own Wi-Fi/broker settings. Do not import credentials from reference projects
or commit `secrets.h`. An empty broker username disables MQTT authentication.

```sh
pio run -d firmware/esp32-wroom-rig -e esp32dev
```

Select the actual ports from `pio device list` (examples below are not automatic
board detection). Close any serial monitor and stop the Pi's
`rewatch-indicator` service before taking over its C3 serial port.

```sh
pio run -d firmware/esp32-c3-indicator -e esp32-c3-devkitm-1 -t upload --upload-port /dev/ttyACM0
pio run -d firmware/esp32-wroom-rig -e esp32dev -t upload --upload-port /dev/ttyUSB0
pio device monitor --port /dev/ttyUSB0 --baud 115200
```

The default C3 environment enables hardware USB CDC (`ARDUINO_USB_MODE=1`,
`ARDUINO_USB_CDC_ON_BOOT=1`), so `Serial` uses the C3's native USB connection.
For initial flashing, if needed hold BOOT, tap RESET, release BOOT, then retry;
the port can change after reset. WROOM uses its development board's USB/UART bridge.
On a C3 board wired through a UART bridge rather than native USB, select the
`esp32-c3-uart` environment described in the USB-to-UART appendix below instead
of assuming the native-USB environment works.

## Pins and electrical limits

| Board | Pin/connection | Function |
| --- | --- | --- |
| C3 | native USB (GPIO18 D− / GPIO19 D+) or board UART bridge | Select the matching environment; JSON serial at 115200 |
| C3 | GPIO5 | SSD1306 OLED SDA |
| C3 | GPIO6 | SSD1306 OLED SCL |
| C3 | 3V3 / GND | OLED supply/common ground; use 3.3 V I2C pull-ups |
| C3 | GPIO8 | WS2812/NeoPixel data, one GRB pixel by default |
| WROOM | GPIO2 | onboard status LED (active-high assumed) |
| WROOM | GPIO0 | active-low BOOT button, internal pull-up |
| WROOM | USB | power, flash and 115200-baud diagnostics |

C3 display: 128×64 SSD1306, normally I2C `0x3C` or `0x3D`, 400 kHz.
Settings live in `esp32-c3-indicator/include/config.h`. Verify the actual board:
not every “C3 SuperMini” has an addressable RGB LED; some have only a plain LED
on GPIO8. Use an external compatible pixel if needed. GPIO8 and WROOM GPIO0 are
boot-strapping pins: external wiring must not force an invalid boot level. Do
not hold WROOM BOOT during reset unless entering the bootloader.

No GPIO is 5 V tolerant. An external pixel/strip needs a suitably rated supply,
common ground and appropriate data level shifting; do not power a strip from
an ESP32 GPIO. Default pixel brightness is full-scale. Missing OLED hardware
does not prevent serial parsing or pixel updates.

## C3 USB protocol (current dashboard)

`pi4-core/indicator.py` bridges `rewatch/threat/state` and node health into one
newline-terminated JSON object every 100 ms at **115200 baud**:

```json
{"score":72,"band":"RED","open":1,"cd":94,"msg":"Room 1 AC 35.0 C","nodes":"1111"}
```

| Field | Meaning |
| --- | --- |
| `score` | required integer 0–100; rounded by the Pi bridge |
| `band` | required string: GREEN, BLUE, YELLOW, RED or PURPLE |
| `open` | 1 for an open incident, otherwise 0 |
| `cd` | acknowledgement countdown seconds; −1 when none |
| `msg` | reason, capped at 40 characters by the bridge; accepted/stored, not displayed in the current OLED layout |
| `nodes` | exactly four bits: core, sentinel, herald, rig; absent/invalid entries show down |

The OLED labels these nodes `P4`, `3A`, `3B`, `RG`. Filled boxes mean recent
heartbeats; they are not extra scorers. The countdown and ECG reflect engine
state. Purple is labelled `LOCKDOWN` by the inherited display, but means the
engine's automated-response phase, not necessarily a network lockdown.

GREEN is steady; BLUE blinks at 0.5 Hz (one full cycle every 2 seconds); YELLOW at 2 Hz; RED at 4 Hz; PURPLE
at 1 Hz. These are full-colour on/off blinks, **not smooth brightness throbs**.
Unknown bands render blue, never green. After more than 3 seconds without an
accepted frame, both OLED and pixel show link loss (sleeping face / blue).
Malformed JSON, missing score/band, and out-of-range scores do not renew that
watchdog. Lines over 640 bytes are discarded through the next newline, avoiding
acceptance of a valid-looking suffix. CR is ignored. The larger bound covers
Python's JSON escaping of the bridge's 40-character Unicode message.

The host marks engine state older than 5 seconds BLUE even while USB remains
connected. This is distinct from the firmware's 3-second transport timeout.
Set `INDICATOR_PORT` on the Pi to a stable `/dev/serial/by-id/...` path when
multiple serial devices are connected.

## Optional Wi-Fi mirror

To use MQTT inside the enclosure, copy
`esp32-c3-indicator/include/secrets.example.h` to the adjacent ignored
`secrets.h`, replace `wifi name` / `wifi pass` and set the Core broker address,
then build and flash the matching board environment. Both C3 environments
enable Wi-Fi when that header exists; without it they remain serial-only.

The firmware subscribes to `rewatch/indicator/frame` and `rewatch/threat/state`
over plain, unauthenticated MQTT. Keep this transport on an isolated trusted
network. It has a **512-byte total MQTT packet buffer**, including topic and
protocol overhead, and rejects payloads of 640 bytes or more. Rich threat
states can therefore exceed its limits. Direct threat-state messages do not
reconstruct fleet health; a compact frame can carry `nodes` and countdown
fields, but the repository does not provide a Core compact-frame MQTT publisher.
The wired Pi bridge supplies the complete aggregated frame.

Choose one authoritative feed: serial remains active in a wireless build and
conflicting inputs can overwrite each other. Stop `rewatch-indicator` if using
MQTT exclusively. The local Black Hat workspace does not publish MQTT. Wireless
operation still requires validation on your actual board/network; it is not
claimed equivalent to the serial path.

## WROOM AC rig protocol

The rig joins the configured IoT Wi-Fi and MQTT broker. Topic prefix is fixed
to `rewatch` in this firmware (match the host's prefix). Four devices,
`room1-ac` through `room4-ac`, publish at about 2 Hz:

```text
rewatch/iot/room1-ac/telemetry
{"device":"room1-ac","room":"Room 1","kind":"ac","temp_c":20.0,"setpoint":20,"power":"on","ip":"192.168.100.50","uptime_s":123}
```

Telemetry is not retained. `uptime_s` is not Unix time: no NTP is configured,
and the Pi records receive time. `GET http://<rig-ip>/status` returns the board's
`node`, `ip`, `rssi` and a `devices` array containing each device's `device`,
`room`, `temp_c` and `setpoint`. This is the format used by
`pi4-core/verifier.py`; the dashboard and verifier observe the same model.

| Topic | Payload / effect |
| --- | --- |
| `rewatch/rig/cmd` | `{"scenario":"ac-spike","device":"room1-ac"}` drives that room toward 35 °C; omitted device defaults to room 1 |
| `rewatch/rig/cmd` | `{"scenario":"reset"}` clears all spikes and resets setpoints to 20 °C |
| `rewatch/iot/room1-ac/cmd` | `{"setpoint":20,"by":"rewatch-responder"}` clears that spike and drives toward the supplied setpoint |
| `rewatch/health/rig` | retained `{"node":"rig","online":true}` on connect and every 5 seconds; retained `online:false` last will on unexpected disconnect |

Setpoints must be numeric, finite and within **16–35 °C**; other values are
ignored. Use non-retained commands to avoid replaying old scenarios after
reconnect. BOOT toggles the room-1 spike after boot. Temperature changes ease
toward the target with small noise: reset/recovery is not instantaneous. The
status LED is steady normally and toggles during spikes.

These MQTT commands and HTTP status are **not a production AC control/security
boundary**: HTTP has no authentication/TLS and MQTT uses plain TCP with optional
credentials. Keep this Black Hat rig on a trusted isolated network with broker ACLs.
Switch the rig off when real building devices are connected, especially if
they use the same device IDs; nothing else should depend on the scenario board.

## Reference provenance and deliberate differences

Compared read-only with sibling repositories (no private `secrets.h` copied):

- `ULTRON` at `127d11a`, `firmware/esp32-c3-indicator/`: source of the USB-first
  dumb-display design, Wall-E eyes, ECG, shared stale-link state and saturated
  pixel rails. ReWatch(Iot) keeps that design but uses its current `rewatch` topics,
  BLUE band, countdown and `core/sentinel/herald/rig` node order. Old `ultron`
  risk/score, risk/band and `up` health messages are not the current protocol.
- `ULTRON/firmware/esp32-wroom-tripwire/` at the same revision: a **radio-off
  reed-switch tripwire** on GPIO16–19 with GPIO2 heartbeat. It is a different
  hardware role, not a drop-in rig update. None of those reed/output pins or
  semantics are transplanted into ReWatch(Iot)'s AC rig.
- `voidmain` at `ecbae88`, `firmware/esp32-risk-mini/`: older MQTT-driven display
  reference for colour/motion, fleet tiles and OLED probing. Its mDNS discovery,
  `voidmain` topics, muted colour rails and device overrides are deliberately
  not restored: the Pi 4 engine/USB bridge remains authoritative here.

## Validation status

PlatformIO builds passed for the default C3 USB environment and WROOM
`compile-check` using public placeholders (Espressif32 7.0.1 / Arduino ESP32
2.0.17, ArduinoJson 7.4.3, PubSubClient 2.8.0). This is compilation only, not a
claim of complete live MQTT/USB behaviour. Separately, on 21 October 2026 the
connected C3 was identified through a CP2102 UART bridge and uploaded using
`esp32-c3-uart`, with flash hash verification. The Black Hat serial bridge was
started at 115200 baud. That confirms upload/host-link evidence, **not visual
verification of the OLED or pixel**. The WROOM physical rig, C3 optional Wi-Fi
path and complete three-Pi deployment remain unvalidated.

The host-side parser/framing regression check also passed:

```sh
python3 firmware/tests/check_indicator.py
```

It needs `g++` and the C3 build's downloaded ArduinoJson headers. It extracts
the firmware's actual parsing/framing functions and exercises them with a
host clock and serial stub; it does not emulate the ESP32 or OLED.

Before deployment, check real pin/LED variants, USB enumeration, all five bands,
countdown/node bits, unplug-to-blue behaviour, oversized/malformed-line recovery,
BOOT spike/reset, responder setpoint recovery, HTTP/MQTT agreement, and rig
heartbeat loss on broker/network/power failure.
## Appendix: USB-to-UART C3 variant

For a C3 connected through a CP210x/CH340 USB bridge (`/dev/ttyUSB*`), use
`pio run -d firmware/esp32-c3-indicator -e esp32-c3-uart -t upload --upload-port /dev/ttyUSB0`.
That environment keeps `Serial` on UART0. The default C3 environment uses native
USB CDC (`/dev/ttyACM*`). Identify the chip and port before uploading.

USB is used temporarily for flashing. During normal enclosed operation use the
chosen MQTT feed, or Core serial as an alternative. The legacy Black Hat serial
bridge remains available for compatibility, not as a laptop connection required
by the enclosure. See the [Black Hat guide](../demo/README.md) and
[hardware reference](../hardware.md) for transport boundaries and wiring cautions.

This firmware does not establish camera, door, plug, light, fan or sensor
compatibility. Such integrations need separately supported MQTT bridge profiles
and device-specific validation; no native universal ONVIF/Matter support,
automatic door unlocking or firmware-writing response is implied.
