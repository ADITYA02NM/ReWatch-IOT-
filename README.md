<h1 align="center">ReWatch IoT</h1>

<p align="center"><b>Detect → score → alert → respond on the IoT layer of a building — zero cloud.</b></p>

<p align="center">
  <img src="https://img.shields.io/badge/phase-detect%20·%20govern%20·%20alert%20·%20respond-34d27b" alt="scope">
  <img src="https://img.shields.io/badge/hardware-2×Pi3%20·%20Pi4%20·%202×ESP32-4c8dff" alt="hardware">
  <img src="https://img.shields.io/badge/cloud-none-ff4a3d" alt="zero cloud">
  <img src="https://img.shields.io/badge/licence-Apache--2.0-blue" alt="licence">
</p>

---

ReWatch is a small box of real hardware that watches the smart devices in a
building. It sniffs the network for scans and floods, learns what each IoT
device normally does, and when something is wrong it **scores** the risk,
**lights** a shelf indicator, **e-mails** the owner — and if nobody answers in
two minutes, it **acts on its own** and puts the device back to normal.

It is five boards on a shelf next to the router. Nothing phones home.

```
         ┌─ port 1 ── ROUTER (data comes in)
 8-PORT  ├─ port 2 ── Pi 3  SENTINEL   detect scans/anomalies + log to USB pen drive
 SWITCH  ├─ port 3 ── Pi 4  CORE       MQTT · threat engine · dashboard · Wi-Fi verifier
         └─ port 4 ── Pi 3  HERALD     SMTP alert e-mails (TL-WN722N)

 Pi 4 USB ── ESP32-C3  indicator   NeoPixel band + OLED score (+ boot animation)
 Wi-Fi    ── ESP32-WROOM rig       the room AC controllers (demo devices)
```

## How the loop works

1. **Sentinel** (Pi 3) sniffs the LAN and watches every device's telemetry.
   It detects nmap scans, ping sweeps, floods and new devices, and flags any AC
   unit that goes abnormal. Every message is logged to the **USB pen drive**.
2. **Core** (Pi 4) fuses all of that into one score, `0–100`, and a band.
   It also joins the Wi-Fi on a second radio (**AC600**) and asks each device
   directly, cross-checking what the bus claims against what the device says.
3. The band drives everything: the **dashboard** at `rewatch.local`, the shelf
   **NeoPixel + OLED**, and — on RED — an **e-mail** from Herald.
4. On RED a **2-minute countdown** starts. Acknowledge it and you own it; ignore
   it and ReWatch turns **PURPLE**, treats it as unauthorised, and **responds** —
   forcing the AC back to its baseline, or blocking the attacking host.

| Band | Score | Means | Indicator |
|------|-------|-------|-----------|
| 🟢 GREEN | 0–29 | normal | steady green |
| 🔵 BLUE | — | a node is offline | slow blue throb |
| 🟡 YELLOW | 30–69 | a scan or a drifting device | 2 Hz yellow |
| 🔴 RED | 70–100 | critical | 4 Hz red blink + e-mail |
| 🟣 PURPLE | — | nobody responded → auto action | 1 Hz purple |

## Dashboard

`https://rewatch.local` (or `http://<pi4-ip>:8080`). Locked with a **passkey** —
only the owner's registered device can open it. Inside:

- live **threat score** with the risk-engine inputs that make it up;
- the **incident** panel with the 2-minute countdown and **Acknowledge**;
- a live **twin of the OLED** and the NeoPixel colour;
- the **IoT topology** (switch, Pis, ESP32s, rooms) coloured by state;
- the **rooms**, each AC's temperature with a Wi-Fi-verified tick;
- **alerts & events**, the **fleet** health, and the raw **vitals** page.
- `/reports.html` — *"the events that happened in the last 5 hours."*

The frontend is plain HTML/CSS/JS with self-hosted fonts. No build step, no CDN.

---

# Installation

## 0. What you need

| Qty | Part | Role |
|----|------|------|
| 1 | Raspberry Pi 4 (4/8 GB) + SD card | **Core** |
| 2 | Raspberry Pi 3 + SD cards | **Sentinel**, **Herald** |
| 1 | 5-/8-port Gigabit switch | production LAN |
| 1 | USB pen drive | Sentinel evidence log |
| 1 | TP-Link **AC600** USB Wi-Fi | Pi 4 verifier radio |
| 1 | TP-Link **TL-WN722N** USB Wi-Fi | Herald e-mail radio |
| 1 | ESP32-C3 SuperMini + SSD1306 OLED | indicator |
| 1 | ESP32-WROOM-32 | room rig (demo devices) |
| — | Cat6 cables, USB cables, power | — |

Give each Pi a **static IP**: Core `…​.1`, Sentinel `…​.2`, Herald `…​.3`
(the installer defaults to `192.168.100.0/24`).

## 1. Wire it (step by step)

1. **Switch port 1 → router.** This is where the data comes in.
2. **Switch port 2 → Pi 3 Sentinel** (eth0). Plug the **USB pen drive** into
   Sentinel — this is where every event is logged.
3. **Switch port 3 → Pi 4 Core** (eth0).
4. **Switch port 4 → Pi 3 Herald** (eth0). Plug the **TL-WN722N** into Herald
   and join it to the same Wi-Fi — alerts go out over this radio.
5. **Pi 4 Core:** plug in the **AC600** (join it to the IoT Wi-Fi — this is the
   verifier radio) and the **ESP32-C3** over USB (the indicator).
6. **ESP32-C3:** OLED to **SDA = GPIO5, SCL = GPIO6**; the NeoPixel is the
   onboard pixel on **GPIO8**.
7. **ESP32-WROOM:** power over USB; it joins the Wi-Fi on its own. This is the
   demo rig standing in for the building's AC controllers — switch it off and
   keep it aside once the real devices are present.

## 2. Flash the two ESP32 boards

Install [PlatformIO](https://platformio.org/) (`pip install platformio`), then:

```bash
# indicator (plugs into the Pi 4 by USB)
cd firmware/esp32-c3-indicator && pio run -t upload

# room rig (needs Wi-Fi creds)
cd firmware/esp32-wroom-rig
cp src/secrets.example.h src/secrets.h   # fill in SSID / password / Pi 4 IP
pio run -t upload
```

See [`firmware/README.md`](firmware/README.md) for the pin tables.

## 3. Deploy the three Pis — one command

From your laptop (needs `ssh` + `rsync`; put your key on each Pi first with
`ssh-copy-id pi@<ip>`):

```bash
./start.sh
```

It asks for each Pi's IP, your SMTP details and the dashboard hostname, prints
the plan, and on your confirmation **SSHes into every node, copies the code,
installs the broker and all the Python services, writes `/etc/rewatch/rewatch.env`,
and starts everything** — then exits. Re-running it is safe; it never wipes your
data or passkeys. Preview without touching anything: `./start.sh --dry-run`.

> Under the hood each node runs [`tools/node-install.sh <role>`](tools/node-install.sh),
> which you can also run by hand on a Pi. Services are `systemd` units named
> `rewatch-*`; check them with `systemctl status 'rewatch-*'`.

## 4. Register your passkey

On the Pi 4, mint a one-time enrolment code:

```bash
ssh pi@<pi4-ip> 'cd ~/rewatch-src/pi4-core && sudo /opt/rewatch/venv/bin/python -m server.enroll'
```

Open the dashboard → **First time? Register this device** → paste the code →
approve the passkey prompt. That device now unlocks ReWatch. (For the Black Hat
demo laptops that can't use the passkey, set an access code in `start.sh` and use
**Use access code**.)

## 5. HTTPS (optional but recommended)

Passkeys work over `localhost` out of the box. To serve `https://rewatch.local`
across the network, generate an offline CA and cert, install the CA on your
devices, and point the env at them:

```bash
./tools/make_local_ca.sh                 # writes ca/ and certs/
# copy certs/server.{crt,key} to the Pi 4 under /etc/rewatch/certs/
# in /etc/rewatch/rewatch.env set REWATCH_TLS_CERT, REWATCH_TLS_KEY, REWATCH_PORT=443
sudo systemctl restart rewatch-dashboard
```

Keep `ca/ca.key` **off the Pi** — it lives on your admin machine only.

## 6. Check it

- `systemctl status 'rewatch-*'` on each Pi — all active.
- Dashboard **fleet** panel: Core / Sentinel / Herald green, USB **mounted**,
  SMTP **ready**.
- Dashboard → **Send test e-mail** → it arrives.
- Run `nmap -sS <any-host-on-the-LAN>` → a **port scan** event appears within
  seconds and the score jumps to YELLOW.

---

## Repository layout

```
real/
├── start.sh                 one-shot SSH deployer (run from your laptop)
├── common/rewatch.py        shared contract: topics, bands, MQTT helper
├── pi3-sentinel/            detection + USB evidence logging
│   └── detector.py
├── pi4-core/                the brain
│   ├── engine.py            threat engine + responder (scoring, incidents, playbooks)
│   ├── verifier.py          AC600 Wi-Fi cross-check
│   ├── indicator.py         USB bridge -> ESP32-C3
│   ├── server/              dashboard: aiohttp, passkey auth, WS, reports
│   ├── web/                 the frontend (index/reports/debug/manual + assets)
│   ├── systemd/  mosquitto/
├── pi3-herald/mailer.py     SMTP alert e-mails (TL-WN722N)
├── firmware/                esp32-c3-indicator/ · esp32-wroom-rig/
├── tools/                   node-install.sh · make_local_ca.sh
└── tests/                   pytest suite (engine, detectors, server)
```

## Security notes

- Dashboard is **passkey-only** (WebAuthn); sessions are 1-hour, cookies
  `Secure; HttpOnly; SameSite=Strict`, session IDs stored as SHA-256 hashes.
- The broker is open on the trusted production LAN by default. To require
  per-client auth, set `allow_anonymous false` + a `password_file` in
  `pi4-core/mosquitto/rewatch.conf` and fill `REWATCH_MQTT_USER/PASS`.
- The firewall response (`RESPONDER_NFT=1`) uses an `nft` set `inet rewatch
  blocklist` — create it on the Pi 4 before enabling.
- ReWatch monitors **your own** network. Passive Wi-Fi/LAN watching and any
  response action must stay inside networks you are authorised to operate.

## Licence

Apache-2.0 — see [`LICENSE`](LICENSE) and [`NOTICE`](NOTICE). Third-party
inventory (fonts, dependencies, invoked-not-linked programs) in
[`THIRD_PARTY.md`](THIRD_PARTY.md). ReWatch grew out of the ULTRON project and
carries parts of its passkey module, local-CA script and ESP32-C3 firmware.
