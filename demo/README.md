# ReWatch IoT — laptop demonstration

**Last updated: 2026-10-21**

Run the detector and threat engine against a ten-device, four-room AC building,
with a browser dashboard. No Raspberry Pi, MQTT broker, root access or ESP32 is
required. Synthetic traffic, telemetry and responses are not physical evidence.
See the [project overview](../README.md) and [hardware limits](../hardware.md).

## Start and sign in

From the repository root, with Python 3.10+ and `venv` available:

```bash
./demo/run.sh
# Optional port override:
./demo/run.sh --port 9000
```

The launcher creates `.venv` when absent and installs missing demo dependencies.
To explicitly synchronize an existing environment:

```bash
.venv/bin/python -m pip install -r demo/requirements.txt
```

Open **http://localhost:8080**, choose **Access code**, and enter the code printed
by the launcher. The source/default example code is `rewatch`; this workstation's
ignored `demo/.env` overrides it with `P2408`. That local recording code is not a
production password or a portable repository default. Normal passkey sign-in
requires an enrolled credential and a verified ceremony.

## Recording sequence and controls

Only **Replay** resets the shared simulation timeline. Refresh, including
**Ctrl+Shift+R**, reconnects to the current simulation rather than resetting it.
All viewers share one building; Replay affects every viewer.

| Time from Replay | Scenario |
| --- | --- |
| +20 s | Ten devices appear: four ACs, camera, door, plug, light, fan and sensor |
| +30 s | Room 1 starts heating toward 35 °C |
| Warning, then critical hold | YELLOW, then RED opens an incident |
| RED +20 s without ACK | PURPLE; a simulated command requests the 20 °C setpoint |
| ACK before deadline | Records operator ownership and cancels automatic escalation; the fault remains |

The demo ACK window defaults to **20 seconds**; production defaults to
**120 seconds**. Setpoint commands do not make temperature recover instantly.
Use the separate manual **AC spike/reset** controls to change the simulated
fault. **Black Hat feed** injects synthetic detections only: it does not launch
scans or attacks. Replay restarts the scenario, not the retained report history.
Select a topology tile for observed evidence and supported synthetic controls.
The firmware demo changes a reported version string; it does not flash a device
or prove integrity. Door control is lock-only, with explicit confirmation.

The dashboard, `/reports.html`, `/debug.html` and `/manual.html` are available.
The five-hour report uses SQLite-retained events, score samples and incidents
across Replay and process restart. Five hours is a reporting window, not a claim
that five hours of evidence already exist; only accumulated records can appear.

## Passkey preview: recording only, never production

```bash
DEMO_PASSKEY_PREVIEW=1 ./demo/run.sh
```

This explicitly labelled, **off-by-default** option requests a browser passkey
prompt and grants an **unverified local demo session even if you cancel**.
It is cosmetic, **not authentication**, and must **never** be used in production.
Preview access is restricted to loopback; use `localhost`. Normal verified
passkey routes and production authentication are separate from this preview.

The browser and operating system control the QR/phone/biometric UI. The website
cannot force a QR code to appear or guarantee an unenrolled phone can complete
the ceremony. A prompt, cancellation or demo unlock is not proof of identity.

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

## Optional USB display bridge

Flash the matching C3 environment using the [firmware guide](../firmware/README.md),
start the demo, then in another terminal run:

```bash
.venv/bin/python demo/indicator_bridge.py --port /dev/ttyUSB0
# If the server uses another port, also pass --http-port 9000.
```

Confirm the serial device first. The bridge reads the local demo configuration
and writes newline-delimited JSON at 115200 baud. Do not run a serial monitor,
production bridge or second writer on the same port. Mirroring a simulation
does not validate real monitoring. The connected C3 upload was verified;
physical OLED/pixel appearance still needs inspection.

## Configuration

| Setting | Source default | Effect |
| --- | --- | --- |
| `DEMO_PORT` | `8080` | HTTP port |
| `DEMO_CODE` | `rewatch` | Shared local demo access code; ignored `.env` may override |
| `DEMO_AUTO_SPIKE` | `1` | Enable the automatic +30 s AC scenario |
| `DEMO_ACK_TIMEOUT_S` | `20` | Demo acknowledgement window in seconds |
| `DEMO_SEND_MAIL` | `0` | Preview only unless explicitly enabled |
| `DEMO_PASSKEY_PREVIEW` | `0` | Cosmetic, unverified loopback-only preview |

The AC scenario is not a universal device-compatibility demonstration. Other
device types require explicitly supported, opted-in MQTT bridge capability
profiles and device-specific validation; do not infer native ONVIF or Matter
support. Do not use this demo to unlock physical doors or write firmware.
