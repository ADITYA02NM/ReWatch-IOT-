# ReWatch(Iot) — Black Hat workspace

**Last updated: 2026-10-26**

Exercise the detector, threat engine and operator dashboard against 28 office
assets, four per device kind. No Raspberry Pi, MQTT broker, root access or ESP32
is required. Black Hat generates traffic, telemetry and responses for controlled
scenarios; these are not physical monitoring evidence.
See the [project overview](../README.md) and [hardware limits](../hardware.md).

## Start and sign in

From the repository root, with Python 3.10+ and `venv` available:

```bash
./demo/run.sh
# Optional port override:
./demo/run.sh --port 9000
```

The launcher creates `.venv` when absent and installs missing workspace dependencies.
To explicitly synchronize an existing environment:

```bash
.venv/bin/python -m pip install -r demo/requirements.txt
```

Open **http://localhost:8080**, choose **Access code**, and enter the code printed
by the launcher. The source/default code is `rewatch`; `DEMO_CODE` in the ignored
local configuration can override it. This shared exercise code is not a
production password. Normal passkey sign-in
requires an enrolled credential and a verified ceremony.

## Exercise sequence and controls

**Replay** or **Ctrl+Shift+R** resets the shared Black Hat timeline, score, events and
graph while retaining discovered devices and restoring their simulated baseline
readings. Ordinary refresh reconnects without resetting. All viewers share one
building; Replay affects every viewer.

| Time from Replay | Scenario |
| --- | --- |
| +20 s on initial discovery | 28 devices appear: four each of AC, camera, door, plug, light, fan and sensor |
| +30 s | Room 1 starts heating toward 35 °C |
| Warning, then critical hold | YELLOW, then RED opens an incident |
| RED +20 s without ACK | PURPLE; a simulated command requests the 20 °C setpoint |
| ACK before deadline | Records operator ownership and cancels automatic escalation; the fault remains |

The Black Hat ACK window defaults to **20 seconds**; production defaults to
**120 seconds**. Setpoint commands do not make temperature recover instantly.
Use the separate manual **AC spike/reset** controls to change the simulated
fault. **Black Hat feed** injects synthetic detections only: it does not launch
scans or attacks. Replay restarts the scenario, not the retained report history.
Select a topology tile for observed evidence and supported synthetic controls.
The firmware drill changes a reported version string; it does not flash a device
or prove integrity. Door control is lock-only, with explicit confirmation.

The dashboard, `/reports.html`, `/debug.html` and `/manual.html` are available.
The dashboard is one non-scrolling 3×2 grid: **01 Risk** (semi-circular
speedometer gauge with hover tooltip, big score, and a history graph whose
tooltip shows the score, band and alert at the hovered moment — while calm the
published score breathes gently, always well inside GREEN), **02 Alerts**
(incident ring, per-alert Acknowledge, paginated feed), **03 BlackBox**
(schematic of the box internals with packet pulses on live events and lids
opening on detections), **04 IoT connections** (a modular flowchart: the ReWatch(Iot)
box feeds seven device-kind nodes — AC, camera, door, plug, light, fan, sensor —
with live counts; selecting any kind reveals four location cards with live
readings and hover/focus details), **05 Controls** (AC rig start/stop, Clear, Export .md,
Refresh, OLED+LED preview, Mail test, Replay, Black Hat feed, Firmware drill)
and **06 IoT details** (kind groups with sub-device evidence, firmware facts and
the capability-approved control forms). On a phone, panels appear one at a time
through the footer switcher.

### Simulated office inventory

These are synthetic devices, not discovered physical office hardware. Each
location has its own device ID, simulated IP and capability-approved controls.

| Kind | Locations | Card reading / controls |
| --- | --- | --- |
| AC | Room 1, Room 2, Room 3, Room 4 | Temperature and setpoint / setpoint |
| Camera | Reception, Main Entrance, Corridor, Parking | Recording status / recording |
| Door | Main Entrance, Meeting Room, Server Room, Emergency Exit | Lock and forced-open status / lock only, with confirmation |
| Plug | Workstations, Printer Area, Pantry, Server Rack | Observed watts and power status / power |
| Light | Reception, Open Office, Meeting Room, Corridor | Brightness and power status / brightness, power |
| Fan | Open Office, Meeting Room, Pantry, Utility Room | Speed and power status / speed, power |
| Sensor | Server Room, Pantry, Washroom, Open Office | Smoke and leak status / observe-only |

All kinds use the same two-column location-card layout. Hover or focus a card
for its ID, IP, reported firmware (unattested) and link evidence; click it to
select that individual device. Missing readings show **—**, not an invented
healthy state. Selecting or controlling one location does not select or change
its peers. The control selector includes the device kind to distinguish shared
location names such as Meeting Room.

The five-hour report uses SQLite-retained events, score samples and incidents
across Replay and process restart. Five hours is a reporting window, not a claim
that five hours of evidence already exist; only accumulated records can appear.

## Local access boundary

```bash
DEMO_PASSKEY_PREVIEW=1 ./demo/run.sh
```

This **off-by-default** option requests a browser passkey
prompt and grants an **unverified local Black Hat session even if you cancel**.
It is cosmetic, **not authentication**, and must **never** be used in production.
Preview access is restricted to loopback; use `localhost`. Normal verified
passkey routes and production authentication are separate from this preview.

The browser and operating system control the QR/phone/biometric UI. The website
cannot force a QR code to appear or guarantee an unenrolled phone can complete
the ceremony. A prompt, cancellation or workspace unlock is not proof of identity.

## E-mail: preview by default

**SMTP delivery is disabled by default** (`DEMO_SEND_MAIL=0`); the event feed
explicitly shows an e-mail preview, not a sent message. A system summary is
generated every five minutes; Replay does not restart that cadence. To opt in:

```bash
# First-time configuration only; do not overwrite an existing local .env.
cp demo/.env.example demo/.env
chmod 600 demo/.env
# Edit locally: SMTP_USER, a NEW SMTP_PASS, ALERT_TO, DEMO_SEND_MAIL=1.
# Restart ./demo/run.sh after edits.
```

The bounded background mail worker uses Herald's TLS transport. A successful
result means **the SMTP server accepted the message**, not that it reached an
inbox. Check recipient delivery separately. Never publish passwords or record
them on screen; revoke exposed credentials and generate replacements. Settings
are loaded from ignored `demo/.env`; do not commit that file.

## Enclosure transport

The ESP32 boards live inside the enclosure, not on the laptop as required
peripherals. WROOM uses Wi-Fi MQTT. C3 has an
[optional MQTT transport](../firmware/README.md#optional-wi-fi-mirror), with
Core serial as an alternative; USB is used temporarily for flashing. The stock
C3 build remains serial-only until a local wireless header is configured.

This Black Hat workspace does not publish MQTT to the enclosure. Its legacy
serial bridge remains available for compatibility, not as part of the required
runtime wiring. Generated scenes do not validate live monitoring. The recorded
C3 upload check does not establish wireless or OLED/pixel validation.

## Configuration

| Setting | Source default | Effect |
| --- | --- | --- |
| `DEMO_PORT` | `8080` | HTTP port |
| `DEMO_CODE` | `rewatch` | Shared local exercise access code; ignored `.env` may override |
| `DEMO_AUTO_SPIKE` | `1` | Enable the automatic +30 s AC scenario |
| `DEMO_ACK_TIMEOUT_S` | `20` | Black Hat acknowledgement window in seconds |
| `DEMO_SEND_MAIL` | `0` | Preview only unless explicitly enabled |
| `DEMO_PASSKEY_PREVIEW` | `0` | Cosmetic, unverified loopback-only preview |

The AC scenario does not establish universal device compatibility. Other
device types require explicitly supported, opted-in MQTT bridge capability
profiles and device-specific validation; do not infer native ONVIF or Matter
support. Do not use Black Hat exercises to unlock physical doors or write firmware.
