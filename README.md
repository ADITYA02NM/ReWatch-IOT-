<p align="center"><img src="assets/banner.svg" alt="ReWatch IoT — observe, assess, alert, respond"></p>

<h1 align="center">ReWatch IoT</h1>
<p align="center"><b>Local IoT monitoring with an operator in the loop.</b><br>Three Raspberry Pis · two ESP32s · one visible risk picture</p>

## Abstract

ReWatch watches an authorized building IoT network, combines network events with
device telemetry, and presents a shared risk score on a browser dashboard and a
small OLED/LED indicator. The central example is an AC controller: an abnormal
temperature becomes a visible warning, a critical condition opens an incident,
and an operator can acknowledge it before a configured response is attempted.

The software separates **Sentinel** detection, **Core** decision-making and
**Herald** e-mail delivery across three Raspberry Pis. An ESP32-C3 displays the
result; an ESP32-WROOM provides four simulated room ACs for an authorized test
rig. Scoring and the dashboard are local; configured SMTP delivery may use an
external provider. This is a research/prototype system, not a certified building
safety controller or a guarantee of intrusion prevention.

> **Current evidence:** the laptop simulation and automated software checks are
> distinct from a complete physical deployment. The connected C3 was uploaded
> successfully on 21 October 2026; OLED/pixel appearance, three-Pi deployment,
> wireless verification and real SMTP delivery still require physical checks.
> All repository hardware artwork is labelled illustration, not photography.

**Start here:** [Laptop demo](#laptop-demo) · [Hardware](hardware.md) ·
[Firmware](firmware/README.md) · [Story](story.md) · [Security](SECURITY.md) ·
[Verification record](docs/BUILD-CHECKLIST.md)

## Architecture

![Intended network topology and indicator wiring](assets/hardware/diagram.svg)

```text
Authorized LAN / IoT telemetry
          │
   Pi 3 SENTINEL ── detections / anomalies ──┐
   packet capture + USB JSONL log            │ MQTT on Core
                                            ▼
   Wi-Fi /status ── Pi 4 CORE ── score / incident / command
                    │   │   │
                    │   │   └── Pi 3 HERALD ── SMTP alert
                    │   └────── ESP32-C3 USB ── OLED + LED
                    └────────── Browser ── acknowledge / reports

   ESP32-WROOM rig ── four simulated room ACs, MQTT + HTTP
```

An ordinary switch does **not** give Sentinel every other host's unicast
traffic. Use an appropriate mirror/SPAN port or TAP and validate visibility.
Core's optional host firewall does **not** quarantine arbitrary LAN peers
unless traffic actually traverses Core. See [deployment limits](hardware.md#observation-and-deployment-limits).

## How it works

1. **Observe.** Sentinel detects observable TCP/UDP scans, FIN/NULL/Xmas probes,
   slower scan patterns, ARP/ICMP sweeps, floods and device changes. Thresholds
   evaluate AC telemetry and supported tamper/safety/power fields. Firmware
   version changes are **unattested metadata**, not verified firmware integrity.
   These are explicit rules, not machine learning or reliable tool attribution:
   nmap and other tools can produce the same patterns.
2. **Cross-check.** Core's verifier queries a device's HTTP `/status` through the
   configured Wi-Fi interface and compares values. This is a consistency check,
   not cryptographic proof that the device or sensor is honest.
3. **Assess.** The threat engine combines persistent conditions and decaying
   event impulses. It broadcasts a score, band, explanation and incident state.
4. **Alert.** On RED, Herald attempts an e-mail. The dashboard and C3 display the
   acknowledgement deadline. SMTP acceptance is not proof of inbox delivery.
5. **Respond.** ACK records operator ownership and cancels automatic escalation;
   it does not repair the AC or erase risk. Without ACK, the engine enters
    PURPLE and attempts its response. Only explicitly enrolled AC/thermostat
    playbooks can request the trusted baseline setpoint; other devices remain
    operator-review only. Verify the resulting state independently.

### Score and bands

`score = clamp(max(active condition points) + sum(decaying impulses), 0, 100)`.
Warning conditions contribute 45 points; critical conditions 90. Event impulses
default to a 60-second half-life: portscan 45, ARP sweep 35, ping sweep 30,
new device 20, integrity mismatch 40, firmware-version change 40, slow scan 45,
flood 75 and device offline 10.

| Band | Meaning | C3 indication |
| --- | --- | --- |
| GREEN | Score below 30 | Steady green |
| YELLOW | Score 30–69 | Yellow, 2 Hz |
| RED | Score at least 70; incident opens | Red, 4 Hz; ACK countdown |
| BLUE | Required Sentinel/Herald heartbeat missing after timeout | Blue, 0.5 Hz blink |
| PURPLE | Unacknowledged incident; response state | Purple, 1 Hz |

BLUE and PURPLE are state overrides, not extra score ranges. USB link loss can
also make the indicator BLUE independently of the engine's band. Production
defaults to **120 seconds** for ACK; the recording demo defaults to **20 seconds**.

## Laptop demo

Requires Python 3.10+ with `venv`; no Pi, root access, broker or frontend build.
Python 3.14 was used for the recorded software checks.

```bash
git clone https://github.com/ADITYA02NM/ReWatch-IOT-.git
cd ReWatch-IOT-
./demo/run.sh
```

The launcher creates `.venv` if absent and installs missing demo dependencies.
For an existing environment, explicitly synchronize versions with
`.venv/bin/python -m pip install -r demo/requirements.txt`.
Open **http://localhost:8080** → **Access code** → `rewatch`.
This deliberately simple local demo code is not a production password.

| Recording step | Behavior |
| --- | --- |
| First dashboard connection or Replay | Start the shared simulation timeline |
| +20 s on first connection | 28 simulated office devices appear, four per kind, including ACs near 20 °C |
| +30 s | Room 1 begins heating toward 35 °C |
| Warning → critical | YELLOW then RED after the detector's critical hold |
| RED +20 s, no ACK | PURPLE; simulated command returns the AC setpoint to 20 °C |
| ACK before deadline | Automatic action cancelled; abnormal temperature remains until reset |

All viewers share one simulated building. Ordinary refresh reconnects without
resetting it. **Replay or Ctrl+Shift+R resets the demo scene while preserving
discovered device inventory.** Black Hat feed
injects synthetic detections only—it launches no scans or attacks. Manual AC
spike/reset and firmware-version-change controls are separate. SQLite retains
events, samples and incidents across Replay and server restarts. The five-hour
report window displays accumulated evidence, not five hours of fabricated data.

### Device capabilities, not universal vendor control

The logical topology lists observed/enrolled devices and selectable evidence.
MQTT bridge profiles support AC/thermostat setpoints, camera recording, door
**locking only**, plug/light/fan power, light brightness and fan speed. Sensors
are observe-only. The demo provides **28 synthetic office devices**, four per
kind. Selecting any kind shows four location cards in the same format as the
AC rooms, with live kind-specific readings and hover/focus evidence. See the
[demo office inventory](demo/README.md#simulated-office-inventory) for locations.
This is **not native ONVIF, Matter, HomeKit or arbitrary IP-camera integration**;
each real device needs a trusted bridge implementing the topic contract.

Production starts observe-only. The installer seeds `/etc/rewatch/devices.json`
from [devices.example.json](devices.example.json) only when absent. Review exact
device IDs, kind, permitted actions and bounds; set `enabled: true` only after
authorized bench testing. Core and Sentinel read `REWATCH_DEVICES_FILE`; keep
their trusted policy consistent and restart their services after changes.
Telemetry cannot grant itself control capabilities. No firmware writes, door
unlocking or automatic cross-device shutdown are implemented.

Authenticated `GET /api/devices` exposes this policy and observed metadata.
`POST /api/control` validates the enrolled action/value, publishes
`rewatch/iot/<device>/cmd`, and returns **202 requested**, not confirmed.
Bridges must honor `action`/`value` and publish resulting telemetry; AC commands
also retain the legacy `setpoint` field. Do not interpret broker acceptance as
physical actuation or use this prototype for life-safety access control.

### Demo passkey preview and optional physical display

Normal passkey routes verify credentials. For recording **only**, the explicitly
labelled preview requests a browser passkey prompt and then grants an unverified
local session even when the prompt is dismissed:

```bash
DEMO_PASSKEY_PREVIEW=1 ./demo/run.sh
```

This is **not authentication**. It is off by default, restricted to loopback, and
absent from production. Browser/OS software decides whether a QR code appears;
the website cannot force that UI or guarantee a phone can finish an unenrolled
passkey ceremony. Use `localhost`, not a LAN IP, for WebAuthn development.

After flashing the matching C3 environment, mirror the demo onto it:

```bash
.venv/bin/python demo/indicator_bridge.py --port /dev/ttyUSB0
```

Do not run two serial writers at once. This bridge forwards simulated state;
it does not turn synthetic devices into real monitoring evidence.

### SMTP: preview first, real delivery only when configured

```bash
cp demo/.env.example demo/.env
chmod 600 demo/.env
# Edit locally: SMTP_USER, a NEW SMTP_PASS, ALERT_TO, DEMO_SEND_MAIL=1.
# Restart ./demo/run.sh after changing configuration.
```

Herald produces a system summary every **five minutes** (including unknown or
stale state when no fresh evidence exists). The demo preserves this cadence
across Replay and displays its preview/status in the feed. Default demo behavior
is **preview—not sent**. With delivery enabled, a bounded
background worker reuses Herald's TLS transport and reports acceptance or
failure separately. Never paste an app password into source, chat, video or
Git. Revoke any credential already exposed and create a replacement. Demo
settings are loaded from ignored `demo/.env`; passwords are not shipped in the
repository. SMTP checks need a real account and network and are not claimed
as completed by unit tests. Production mail results use
`rewatch/mail/result/<id>`, separate from the `rewatch/mail/test` request topic.

## Physical installation

The [hardware guide](hardware.md) contains the full bill of materials, pin
tables, photo placeholders, power cautions and five LED-state illustrations.
Prepare Raspberry Pi OS with SSH, independent adequate power and known LAN
addresses. Set up routing and wireless association yourself; the installer does
not configure the router, DHCP reservations, Wi-Fi credentials or switch SPAN.

### 1. Connect the intended topology

- Router → switch port 1; Sentinel → port 2; Core → port 3; Herald → port 4.
  Port numbers are a lab convention, not a requirement. Configure mirroring/TAP.
- Sentinel: USB evidence drive mounted at `/mnt/rewatch-usb`, writable by the
  service. Verify mount persistence, free space and physical log retention.
- Core: AC600 adapter for HTTP verification and C3 over USB. Confirm the adapter's
  actual chipset/driver and interface name; `wlan1` is only a default.
- Herald: TL-WN722N Wi-Fi uplink for SMTP. Record hardware revision and route;
  a second Wi-Fi connection is not inherently a separate management network.
- WROOM: USB power, authorized test Wi-Fi and MQTT broker details. This board
  simulates room controllers; it is not wired to a mains-powered AC appliance.

### 2. Build and flash firmware

Install PlatformIO separately. From the repository root:

```bash
# Native-USB C3 (usually /dev/ttyACM0):
pio run -d firmware/esp32-c3-indicator -e esp32-c3-devkitm-1 -t upload --upload-port /dev/ttyACM0
# CP210x/CH340 UART C3 (usually /dev/ttyUSB0), used for the connected board:
pio run -d firmware/esp32-c3-indicator -e esp32-c3-uart -t upload --upload-port /dev/ttyUSB0

# WROOM: edit the ignored copy with your own test-network credentials first.
cp firmware/esp32-wroom-rig/src/secrets.example.h firmware/esp32-wroom-rig/src/secrets.h
pio run -d firmware/esp32-wroom-rig -e esp32dev -t upload --upload-port /dev/ttyUSB1
```

Confirm port and chip identity before uploading; port numbers can change.
C3 defaults: OLED SDA GPIO5, SCL GPIO6, address `0x3C`, 128×64; pixel data
GPIO8; serial 115200 baud. Not every SuperMini has an onboard addressable pixel.
See [firmware documentation](firmware/README.md) before wiring or changing pins.

### 3. Preview, then deploy the three Pis

```bash
./start.sh --dry-run    # asks questions, prints plan; no SSH or installation
./start.sh              # same questions; deployment requires typing yes
```

The deployer requests each Pi's IP, SSH username, SMTP settings and hostname.
Defaults are Core `192.168.100.1`, Sentinel `.2`, Herald `.3`; replace them with
the actual addresses. The confirmation defaults to **no**. The SMTP password is
not echoed. Multi-line or ambiguous quoted/escaped environment values are
rejected. `--config file` **executes trusted shell code**; never source an
untrusted downloaded configuration.

Only after confirmation: SSH connectivity is checked, selected source is copied,
private transient configuration is installed at `/etc/rewatch/rewatch.env`, and
`tools/node-install.sh` installs packages, a pinned virtual environment, the
broker on Core and role-specific `systemd` services. Local secrets and build
artifacts are excluded. Updates replace deployed source/configuration and
restart services; back up configuration and `/var/lib/rewatch` first. Existing
data/passkey directories are not intentionally deleted. No physical deployment
is performed by the laptop demo or by the unit tests.

### 4. Enable trusted HTTPS before LAN passkeys

The installer initially uses **HTTP on port 8080**, not automatically trusted
HTTPS. Remote passkeys require a secure origin with a matching RP hostname.
Resolve `rewatch.local` to Core (DNS/mDNS/hosts), generate the local CA/cert
with `./tools/make_local_ca.sh`, trust the CA on each client, and securely install
the server certificate/key under `/etc/rewatch/certs/`. Keep the CA private key
off Core. Grant the `rewatch` service read access to the server key only.

Configure `/etc/rewatch/rewatch.env` on Core:

```dotenv
REWATCH_HOSTNAME=rewatch.local
REWATCH_RP_ID=rewatch.local
REWATCH_TLS_CERT=/etc/rewatch/certs/server.crt
REWATCH_TLS_KEY=/etc/rewatch/certs/server.key
REWATCH_PORT=443
DASHBOARD_URL=https://rewatch.local
```

Update Herald's `DASHBOARD_URL` too, then restart the relevant services.
Mint an enrolment token **on Core**, using the service's data directory:

```bash
cd /opt/rewatch/pi4-core
sudo -u rewatch env REWATCH_DATA_DIR=/var/lib/rewatch /opt/rewatch/venv/bin/python -m server.enroll
```

Open the trusted HTTPS dashboard → **First time? Register this device** →
paste the token and approve the real passkey ceremony. Leave
`REWATCH_ACCESS_CODE` empty to disable the weaker shared-code fallback.
The demo preview flag has no effect on the production server.

### 5. Check the installation, do not assume it

On each node: `systemctl status 'rewatch-*'` and `journalctl -u <service>`.
Confirm Sentinel capture visibility and USB writes, Core MQTT/device telemetry,
Wi-Fi verification, C3 serial/link-loss rendering and Herald test-mail arrival.
Perform scans only against an explicitly authorized lab target. Test ACK and
non-ACK playbooks with the WROOM rig, then independently verify each response.

## Dashboard and source map

Production pages are `/` (the operator dashboard), `/reports.html` (recorded
evidence), `/debug.html` (raw vitals) and `/manual.html` (operator guide). The
demo retains all four. Fonts and assets are self-hosted; the plain
HTML/CSS/JavaScript frontend has no npm build or CDN dependency.

The dashboard is a single non-scrolling 3×2 grid (verified at 1366×768):

| Panel | Contents |
| --- | --- |
| 01 Risk | Semi-circular speedometer gauge (band, score, threshold ticks) with the big score at the right and a hover tooltip on the gauge, plus the scored history graph whose hover shows the score, band and the alert active at that moment |
| 02 Alerts | Incident ring with ACK countdown, a per-alert **Acknowledge** control that targets that alert's incident id, and a paginated event feed |
| 03 BlackBox | Schematic of the inside of the box — Core, Sentinel, Herald, ESP32 rig and the USB-linked C3 — with packet pulses on live events and the board lids opening on detections |
| 04 IoT connections | Modular flowchart: the ReWatch box feeds seven device-kind nodes (AC, camera, door, plug, light, fan, sensor) with live counts; selecting a kind reveals its sub-devices |
| 05 Controls | Demo (AC start/stop), Clear, Export .md, Refresh, OLED+LED preview and Mail test; the demo build adds Replay, Black Hat feed and Firmware drill |
| 06 IoT details | Selected device evidence, firmware/version facts and the capability-approved control forms |

On a phone the same six panels appear one at a time through the footer switcher.
Export writes the last five hours as a Markdown evidence file; the BlackBox and
connections diagrams are drawn from live state, never from assumed wiring.

```text
common/rewatch.py           topic contract, MQTT helpers and configuration
common/iot.py               trusted capability policy and version-change monitor
common/summary.py           five-minute observed-system summary window
pi3-sentinel/detector.py    network/device detection and USB evidence logging
pi4-core/engine.py          score, incident lifecycle and response commands
pi4-core/verifier.py        Wi-Fi HTTP telemetry consistency check
pi4-core/indicator.py       production MQTT → USB display bridge
pi4-core/server/            aiohttp server, WebAuthn, sessions and report store
pi4-core/web/               production dashboard, manual, debug and reports
pi3-herald/mailer.py        SMTP/TLS transport and alert composition
firmware/                  C3 indicator and WROOM room simulator
demo/                      isolated laptop simulation and recording controls
tools/                     node installer and local-CA helper
tests/                     detector, engine, demo, mail and installer regressions
```

## Development and validation

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt -r requirements-dev.txt
.venv/bin/python -m pytest -o addopts='' -q
.venv/bin/ruff check . --select F
bash -n start.sh tools/node-install.sh demo/run.sh
python3 firmware/tests/check_indicator.py
# Browser tests start their own isolated server, never the user's port 8080:
.venv/bin/python -m playwright install chromium
.venv/bin/python tests/browser_demo.py
# Credential-free WROOM compilation (esp32dev requires local secrets.h):
pio run -d firmware/esp32-wroom-rig -e compile-check
```

See the [verification record](docs/BUILD-CHECKLIST.md) for actual commands and
limitations. Firmware build success does not establish electrical correctness;
simulation tests do not establish physical deployment or e-mail arrival.

## Security, provenance and license

The default broker is anonymous and unencrypted on the lab LAN. Do not expose
MQTT or the dashboard to the Internet. Segregate the lab, configure broker auth,
restrict topic permissions and protect transport before using untrusted devices.
See [SECURITY.md](SECURITY.md) for trust boundaries and known prototype limits.

**Apache-2.0**, as retained in [LICENSE](LICENSE) and [NOTICE](NOTICE).
[THIRD_PARTY.md](THIRD_PARTY.md) records fonts, dependencies and reference
provenance. ULTRON and VoidMain informed earlier work; their local repositories
are references, not runtime dependencies. A security disclaimer does not replace
the license or remove its rights and obligations. Monitor and control only
systems you are authorized to operate.
