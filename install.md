# ReWatch installation: three Pis, ESP32s and laptop operation

This guide starts with blank Raspberry Pi SD cards and ends with a dashboard,
observed telemetry, evidence logs and an alert-path check. It also provides two
separate laptop setups: the **self-contained simulation** and the **real MQTT
stack**. Commands are for Raspberry Pi OS / Debian / Ubuntu unless stated otherwise.

> **Scope and safety:** ReWatch is a research prototype, not a certified safety
> controller or a production-hardened security appliance. Outstanding security
> review findings are not fixed by following an installation guide. Use an
> isolated, authorized lab network; do not expose the dashboard, MQTT broker or
> ESP HTTP endpoints to the Internet. Software tests are not evidence that a
> complete three-Pi installation, Wi-Fi path, OLED or mail delivery works.

## Contents

1. [Choose a deployment](#1-choose-a-deployment)
2. [Collect hardware and installation information](#2-collect-hardware-and-installation-information)
3. [Install Raspberry Pi OS on all three Pis](#3-install-raspberry-pi-os-on-all-three-pis)
4. [Establish SSH and verify identities](#4-establish-ssh-and-verify-identities)
5. [Prepare capture, Wi-Fi and evidence storage](#5-prepare-capture-wi-fi-and-evidence-storage)
6. [Deploy the three Pi roles](#6-deploy-the-three-pi-roles)
7. [Configure trusted HTTPS and enroll an owner](#7-configure-trusted-https-and-enroll-an-owner)
8. [Build and flash both ESP32 firmwares](#8-build-and-flash-both-esp32-firmwares)
9. [Connect real telemetry and supported controls](#9-connect-real-telemetry-and-supported-controls)
10. [Start and verify the complete Pi system](#10-start-and-verify-the-complete-pi-system)
11. [Laptop: self-contained simulation](#11-laptop-self-contained-simulation)
12. [Laptop: real-data dashboard and collectors](#12-laptop-real-data-dashboard-and-collectors)
13. [Troubleshooting](#13-troubleshooting)
14. [Shutdown, updates, backups and acceptance record](#14-shutdown-updates-backups-and-acceptance-record)
15. [Reference material](#15-reference-material)

## 1. Choose a deployment

| Mode | What runs | What the displayed data means |
|---|---|---|
| Three Pis | Core on Pi 4; Sentinel and Herald on separate Pi 3s; optional ESP32s | Real messages and observations from the configured network and adapters |
| Laptop simulation | `demo/run.sh`; no MQTT or Pis required | 28 synthetic office assets, four per kind; not real network discovery |
| Laptop real-data stack | Production dashboard, engine, MQTT, Sentinel and Herald on Linux; optional verifier/indicator | Real incoming MQTT telemetry and authorized capture, not the office simulation |

The WROOM firmware models four AC rooms in software. It is a physical network
endpoint, **not four physical air conditioners**. The ESP32-C3 is an indicator,
not a detector. Cameras, doors, plugs, lights, fans and sensors require compatible
external telemetry/control bridges for a real installation. The demo's 28 assets
do not automatically become 28 physical integrations.

## 2. Collect hardware and installation information

### Hardware checklist

- One Raspberry Pi 4 for Core and two Raspberry Pi 3 boards for Sentinel/Herald.
  Use a supported 64-bit OS on compatible Pi 3/4 models; check your exact board.
- Three reliable SD cards, adequate independent power supplies, Ethernet cables
  and an isolated router/switch. A managed mirror/SPAN port or a TAP is needed
  for observing other devices' unicast traffic.
- Core's USB Wi-Fi adapter for the verification path; Herald's USB Wi-Fi adapter
  for SMTP. Check chipset/revision and Linux driver support, not just AC600 or
  TL-WN722N branding.
- Sentinel USB evidence drive, with an existing filesystem you can mount.
- ESP32-C3 with a data-capable USB cable; optional SSD1306 128×64 I²C OLED and
  compatible addressable RGB pixel. See [wiring](hardware.md).
- Optional ESP32-WROOM rig and a second data USB cable.
- Linux admin laptop with Internet access for downloading packages and flashing.
  Windows/macOS can run the simulation; the live capture instructions below
  target Linux. A VM needs deliberate USB/network passthrough and routing.

Disconnect power before wiring. Use 3.3 V logic and a shared ground; never attach
mains voltage or an air-conditioner load to GPIO. A relay/mains installation is
outside this project's rig and needs appropriate qualified engineering.

### Fill in a private installation worksheet

These are **example addresses**, not addresses to copy onto an existing network.
Use DHCP reservations where possible, and confirm there are no collisions.

| Item | Example / information to record |
|---|---|
| Admin SSH user, same on all three Pis | `rewatchadmin` — create this user in Imager |
| Core hostname / Ethernet IP | `rewatch-core` / `192.168.50.10` |
| Sentinel hostname / Ethernet IP | `rewatch-sentinel` / `192.168.50.11` |
| Herald hostname / Ethernet IP | `rewatch-herald` / `192.168.50.12` |
| Laptop IP, if hosting the real broker | `192.168.50.20` |
| Gateway, subnet, DNS, time zone | Your router's actual settings |
| Dashboard name | `rewatch.local` for the bundled certificate helper |
| Capture interface | Actual Sentinel Ethernet/mirror interface, not assumed `eth0` |
| Verification and SMTP interfaces | Actual associated USB Wi-Fi interfaces, not assumed `wlan1` |
| Rig Wi-Fi / IP / broker address | SSID, DHCP reservation, Core or laptop broker IP |
| Evidence drive | Filesystem, UUID, mount path, free space |
| Serial boards | Chip model, `/dev/serial/by-id/...`, C3 USB mode |
| SMTP | Provider, STARTTLS host/port, sender, recipient and fresh app credential |

Keep passwords, recovery information, enrollment tokens and private keys out of
this worksheet if it will be shared. Never paste them into issues, screenshots,
chat or Git. A previously disclosed app password must be revoked and replaced.

## 3. Install Raspberry Pi OS on all three Pis

On the admin computer, install current **Raspberry Pi Imager** from the official
Raspberry Pi site. Repeat the following for each Pi:

1. Select the exact Pi model, then Raspberry Pi OS Lite (64-bit) where supported.
   A desktop image is not required for the services.
2. Select that Pi's SD card. **Writing erases the selected card**: verify device
   size/name and unplug unrelated removable drives before confirming.
3. In OS customization set its distinct hostname, your admin username, time zone
   and a strong local password. There is no universal default `pi` account on a
   freshly customized modern installation.
4. Enable SSH under remote access. Prefer public-key authentication and install
   your laptop's public key. If using initial password authentication, migrate
   to a key after boot and verify it before disabling passwords.
5. Configure country/SSID for an initial Wi-Fi connection if needed. Ethernet is
   preferred for the Pi-to-Pi bus; this initial Wi-Fi setup does not configure
   every external USB adapter automatically.
6. Write and verify the image, eject safely, insert the card, attach Ethernet
   and boot. Reserve the assigned IP in the router.

Use the router's lease table or a directly connected keyboard/display to find
each address. Do not run broad scans against a network you do not administer.
Check the date after boot; incorrect time breaks TLS and complicates evidence.

On **each Pi**, after SSH works:

```bash
sudo apt update
sudo apt full-upgrade
sudo apt install -y rsync ca-certificates curl
hostnamectl
ip -br address
ip route
timedatectl status
```

Reboot if the upgrade requires it, then reconnect. Confirm all three devices
have distinct addresses and can reach Core and the required package repositories.

## 4. Establish SSH and verify identities

On the **admin laptop**, install the deployment tools and obtain the source:

```bash
sudo apt update
sudo apt install -y git openssh-client rsync python3 python3-venv openssl
git clone https://github.com/ADITYA02NM/ReWatch-IOT-.git
cd ReWatch-IOT-
git rev-parse HEAD
```

Create a key if you do not already have a suitable one. Use a passphrase; never
overwrite an existing key inadvertently:

```bash
ssh-keygen -t ed25519 -f "$HOME/.ssh/rewatch_admin"
ssh-add "$HOME/.ssh/rewatch_admin"
```

If `ssh-add` reports no agent, configure/start your desktop SSH agent first.
Set these variables to your **actual** worksheet values in this laptop terminal:

```bash
export SSH_USER=rewatchadmin
export IP_CORE=192.168.50.10
export IP_SENTINEL=192.168.50.11
export IP_HERALD=192.168.50.12
```

Before accepting each host key, compare the SSH fingerprint with the value from
that Pi's local console or another trusted channel:

```bash
# Run locally on the Pi console to display its public host-key fingerprint.
sudo ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub
```

Then, on the laptop, if the key was not already installed by Imager:

```bash
ssh-copy-id -i "$HOME/.ssh/rewatch_admin.pub" "$SSH_USER@$IP_CORE"
ssh-copy-id -i "$HOME/.ssh/rewatch_admin.pub" "$SSH_USER@$IP_SENTINEL"
ssh-copy-id -i "$HOME/.ssh/rewatch_admin.pub" "$SSH_USER@$IP_HERALD"
```

Test a normal login and `sudo -v` on all three. The deployer's installation step
allocates a terminal (`ssh -t`) and supports an interactive sudo password prompt;
remain at the terminal during deployment. Do not enable root SSH or grant blanket
passwordless sudo just to make deployment work. Its SSH command
uses your agent/default SSH configuration, so load the non-default key or add a
per-host `IdentityFile` in your private `~/.ssh/config`.

```bash
ssh -t "$SSH_USER@$IP_CORE" 'hostname; sudo -v'
ssh -t "$SSH_USER@$IP_SENTINEL" 'hostname; sudo -v'
ssh -t "$SSH_USER@$IP_HERALD" 'hostname; sudo -v'
```

Do not suppress a changed-host-key warning. Confirm whether the Pi was actually
reimaged and verify its new fingerprint before updating your known-host entry.

## 5. Prepare capture, Wi-Fi and evidence storage

### Sentinel: give packet capture something to see

Connect Sentinel's capture interface to an authorized switch mirror/SPAN port or
TAP. Configure the switch to mirror the intended IoT ports/VLAN in the required
directions. A normal switch access port normally sees its own traffic and
broadcast/multicast, **not every other device's unicast traffic**.

On Sentinel, identify interfaces with `ip -br link`. The installer will install
tcpdump. After deployment, a short, bounded observation is:

```bash
# On Sentinel; replace eth0 with the actual capture interface.
sudo timeout 10 tcpdump -ni eth0 -c 20
```

Run this only with permission. Do not put packet captures containing other
people's data into Git or public support requests. Passive observation does not
provide switch port ownership or prove an attacker's identity.

### Core and Herald: associate the correct Wi-Fi adapter

On Core and Herald, plug in each designated USB adapter and inspect:

```bash
lsusb
ip -br link
nmcli device status
nmcli device wifi list
```

On Raspberry Pi OS using NetworkManager, connect the chosen adapter interactively
so the passphrase is not embedded in shell history:

```bash
# Change the interface and SSID; run separately on the appropriate Pi.
sudo nmcli --ask device wifi connect 'YOUR-LAB-SSID' ifname wlan1
ip -br address show wlan1
ip route
```

If the OS uses a different network manager, use that manager rather than running
two competing managers on the interface. Keep a working Ethernet/console path
while changing routes. The verifier needs a route from its Wi-Fi IP to the rig's
HTTP endpoint. Herald needs DNS and Internet/SMTP reachability on its Wi-Fi path.
DHCP association alone does not establish either property.

Record actual names in `VERIFY_IFACE` and `SMTP_IFACE` after deployment. If an
interface has no address, a component may fall back to normal routing; that is
**not evidence of an independent Wi-Fi verification or SMTP path**.

### Sentinel: mount the evidence drive persistently

This procedure mounts an **existing** filesystem and does not format it. Back up
the drive first. On Sentinel:

```bash
lsblk -f
sudo install -d -m 0755 /mnt/rewatch-usb
sudoedit /etc/fstab
```

Add an entry using the correct UUID and filesystem. Example for an existing
ext4 filesystem; replace the UUID and use the actual filesystem type/options:

```text
UUID=REPLACE-WITH-DRIVE-UUID /mnt/rewatch-usb ext4 defaults,nofail 0 2
```

```bash
sudo mount /mnt/rewatch-usb
mountpoint /mnt/rewatch-usb
findmnt /mnt/rewatch-usb
df -h /mnt/rewatch-usb
sudo test -w /mnt/rewatch-usb && printf 'evidence mount writable\n'
```

The Sentinel service runs as root for packet capture. It writes daily JSONL
under `/mnt/rewatch-usb/rewatch/YYYY-MM-DD/` when the path is a real mount; otherwise
it falls back to `/var/log/rewatch/YYYY-MM-DD/`. Relevant files include
`bus.jsonl`, `events.jsonl` and `telemetry.jsonl`. A plain directory is not proof
the USB drive is mounted. Check the dashboard's USB state and free space too.

## 6. Deploy the three Pi roles

From the **repository root on the admin laptop**, first inspect the plan:

```bash
bash start.sh --dry-run
```

Answer the SSH-user, three IPs, SMTP and dashboard-hostname prompts using your
worksheet. The default SSH user is `pi`; override it if you created another user.
Dry-run still asks for settings, but stops before deployment. The real deployment
is:

```bash
bash start.sh
```

Review the printed plan and type `yes` only if the hosts and roles are correct.
Leave the fallback access code blank for passkey-only operation. If SMTP is not
being configured yet, do not invent credentials; expect mail testing to remain
unconfigured until the private settings are completed.

The installer:

- Copies code over SSH/rsync to `~/rewatch-src`, then into `/opt/rewatch`.
- Creates a non-login `rewatch` service user, `/opt/rewatch/venv`, configuration
  under `/etc/rewatch`, and state under `/var/lib/rewatch`.
- Installs the shared Python requirements and role-specific OS packages.
- Installs/restarts Mosquitto on Core and the following systemd units:

| Node | Units |
|---|---|
| Core | `rewatch-core`, `rewatch-dashboard`, `rewatch-verifier`, `rewatch-indicator` |
| Sentinel | `rewatch-sentinel` |
| Herald | `rewatch-herald` |

`start.sh` is a **remote three-node deployer**, not the command for starting a
local laptop server. `--config FILE` sources trusted shell code; never use an
untrusted downloaded config. Re-running deployment replaces deployed code and
the generated environment file and restarts services. Back up configuration
first, especially after making TLS, interface or SMTP changes below.

### Review each node's private configuration

On **each Pi**:

```bash
sudoedit /etc/rewatch/rewatch.env
sudo chown root:rewatch /etc/rewatch/rewatch.env
sudo chmod 0640 /etc/rewatch/rewatch.env
```

The file contains `KEY=value` lines, not executable shell. Keep secrets local;
do not print or attach its full contents. The relevant settings are:

| Settings | Required meaning |
|---|---|
| `REWATCH_MQTT_HOST`, `REWATCH_MQTT_PORT` | Core's reachable address and `1883`, consistently on all nodes/rig |
| `REWATCH_MQTT_USER`, `REWATCH_MQTT_PASS` | Match broker authentication if you separately configure it |
| `REWATCH_DATA_DIR` | `/var/lib/rewatch` for installed services |
| `REWATCH_DEVICES_FILE` | `/etc/rewatch/devices.json` for capabilities/approved device metadata |
| `SENTINEL_IFACE`, `SENTINEL_USB_MOUNT` | Actual capture interface and mounted evidence path |
| `SENTINEL_LEARN_S` | Initial device learning interval; default 300 seconds |
| `VERIFY_IFACE`, `VERIFY_TOLERANCE_C` | Associated verification Wi-Fi interface; default tolerance 1.5 °C |
| `SMTP_HOST`, `SMTP_PORT` | Provider's SMTP STARTTLS endpoint, commonly port 587 |
| `SMTP_USER`, `SMTP_PASS`, `SMTP_FROM`, `ALERT_TO` | New valid credentials and intended recipients |
| `SMTP_IFACE` | Herald's actual Wi-Fi interface with a working outbound route |
| `ACK_TIMEOUT_S`, `AC_BASELINE_C` | Production default 120 seconds and baseline 20 °C |
| `RESPONDER_NFT` | Keep `0` for the normal isolated lab setup |

The shared installer distributes the SMTP configuration to all three Pis. Treat
all three environment files as sensitive, even if a role does not send mail.
Use an app-specific credential where your provider requires it. An SMTP success
means **accepted by the SMTP server, not guaranteed inbox delivery**.

### Broker boundary

The bundled [Mosquitto configuration](pi4-core/mosquitto/rewatch.conf) listens on
port 1883 with anonymous access and no TLS. Do not mistake this for Mosquitto's
unconfigured local-only defaults. Isolate the broker, limit network access to
authorized hosts, and do not forward this port from the Internet. A production
broker needs separately designed authentication, ACLs and transport security;
setting username/password environment variables alone does not configure them.

Host firewall rules on Core do not quarantine other LAN devices unless Core is
actually their inline gateway. Do not enable `RESPONDER_NFT` assuming it changes
the switch/router topology.

## 7. Configure trusted HTTPS and enroll an owner

### Why an IP and port are not enough for passkeys

`http://CORE-IP:8080` may display a page on an authorized LAN, but remote WebAuthn
requires a secure context and a suitable **domain-based relying-party ID**.
Simply adding an IP address to a URL, using plain remote HTTP, or ignoring a
certificate warning is not a supported real-passkey setup. The local exception
is `http://localhost:PORT` on the same computer as the browser.

For LAN access use `https://rewatch.local`, resolve that name to Core, and trust
the issuing CA on each owner device. Relying-party IDs contain neither a scheme
nor a port. Origins include scheme, hostname and any non-default port. A passkey
registered for `localhost` does not become a `rewatch.local` passkey.

### Generate and deploy the lab certificate

On the **admin laptop**, in the repository root:

```bash
bash tools/make_local_ca.sh
openssl x509 -in certs/server.crt -noout -subject -dates -ext subjectAltName
```

The helper issues for **`rewatch.local` only**. It creates `ca/ca.crt`,
`ca/ca.key`, `certs/server.crt` and `certs/server.key`. Do not re-run with
`--reissue` unless you intend to rotate the server certificate/key. Keep the CA
private key offline/private; never deploy or commit it. Do not run the helper
on every node and create unrelated CAs with the same name.

Transfer only the server certificate/key to Core, then install them with the
service-readable permissions shown below. The staging directory is private;
remove its two staged files after verifying installation.

```bash
ssh "$SSH_USER@$IP_CORE" 'install -d -m 700 ~/rewatch-cert-stage'
scp certs/server.crt certs/server.key "$SSH_USER@$IP_CORE:rewatch-cert-stage/"
ssh -t "$SSH_USER@$IP_CORE" 'chmod 600 ~/rewatch-cert-stage/server.key && sudo install -d -o root -g rewatch -m 0750 /etc/rewatch/certs && sudo install -o root -g rewatch -m 0644 ~/rewatch-cert-stage/server.crt /etc/rewatch/certs/server.crt && sudo install -o root -g rewatch -m 0640 ~/rewatch-cert-stage/server.key /etc/rewatch/certs/server.key'
```

On Core, edit the existing environment file: replace existing values rather than
adding conflicting duplicate assignments. Use these settings:

```dotenv
REWATCH_HOSTNAME=rewatch.local
REWATCH_RP_ID=rewatch.local
REWATCH_PORT=443
REWATCH_TLS_CERT=/etc/rewatch/certs/server.crt
REWATCH_TLS_KEY=/etc/rewatch/certs/server.key
REWATCH_ORIGINS=https://rewatch.local
REWATCH_BIND=0.0.0.0
DASHBOARD_URL=https://rewatch.local
```

Also set `DASHBOARD_URL=https://rewatch.local` on Herald so email links are
correct. The shipped dashboard unit grants the service the capability to bind
443; do not run the whole dashboard as root. Restart after editing:

```bash
# Core
sudo systemctl restart rewatch-dashboard
sudo systemctl status rewatch-dashboard --no-pager
# On Herald, after its configuration change
sudo systemctl restart rewatch-herald
```

Arrange DNS/mDNS or an owner-device hosts entry mapping `rewatch.local` to Core's
actual IP. Core's OS hostname need not be the dashboard name. On Linux, a manual
entry belongs in `/etc/hosts`; use the actual address, for example:

```text
192.168.50.10 rewatch.local
```

Import **only `ca/ca.crt`** into the trusted certificate authorities on each owner
computer/phone. On Debian/Ubuntu owner computers:

```bash
sudo install -m 0644 ca/ca.crt /usr/local/share/ca-certificates/rewatch-lab.crt
sudo update-ca-certificates
```

Some browsers use their own trust store; import the same CA there if necessary.
On macOS use Keychain Access; on Windows use the appropriate Trusted Root
Certification Authorities store; phones may require an additional explicit
certificate-trust setting. Verify the CA fingerprint through a trusted channel.
Never import a private key as a CA, and never work around the issue with browser
security-disabling flags.

From the laptop, verify the certificate/hostname without bypassing verification:

```bash
curl --cacert ca/ca.crt https://rewatch.local/healthz
```

For a different domain or port, obtain a certificate covering that domain and
update DNS, hostname, RP ID, origins, URL and port consistently. The bundled
helper does not accept an arbitrary-domain argument.

### Enroll and use a real passkey

On Core, generate a short-lived one-use enrollment code as the service owner:

```bash
cd /opt/rewatch/pi4-core
sudo -u rewatch env REWATCH_DATA_DIR=/var/lib/rewatch /opt/rewatch/venv/bin/python -m server.enroll
```

Open `https://rewatch.local` in the owner browser, choose **First time? Register
this device**, enter that code and complete user verification on the
authenticator. The enrollment token expires after ten minutes by default.
Then sign out and sign in again to check the normal path. Register a second
approved authenticator as a recovery option. Do not use `--reset` as a normal
setup step: it removes owner credentials. Preserve the authentication database.

Any configured fallback code is a separate access path, not a passkey. The demo's
recording-only passkey preview is also not authentication and must not be used
as evidence that this enrollment procedure works.

## 8. Build and flash both ESP32 firmwares

These commands run on the **flashing laptop**, not necessarily Core. Start from
the repository root. Install PlatformIO in its own virtual environment, without
`sudo pip`:

```bash
python3 -m venv "$HOME/.venvs/rewatch-pio"
"$HOME/.venvs/rewatch-pio/bin/python" -m pip install --upgrade pip
"$HOME/.venvs/rewatch-pio/bin/python" -m pip install 'platformio==6.1.18'
export PATH="$HOME/.venvs/rewatch-pio/bin:$PATH"
pio device list
ls -l /dev/serial/by-id/
```

On Debian-family Linux, add your flashing user to `dialout` if necessary, then
log out and back in before using the port:

```bash
sudo usermod -aG dialout "$USER"
```

Follow PlatformIO's official udev/device-permission guidance if the board still
cannot be opened. Do not make all serial devices world-writable. Close serial
monitors and stop any indicator bridge using the port before upload. If the board
is plugged into Core, stop `rewatch-indicator` there during flashing and restart
it afterward. For bootloader problems, use the board's documented BOOT/RESET
sequence and confirm the chip, cable and port before retrying.

### ESP32-C3: wired OLED/pixel indicator

Read [firmware instructions](firmware/README.md) and review
[`include/config.h`](firmware/esp32-c3-indicator/include/config.h) before wiring.
Defaults are OLED SDA GPIO5 / SCL GPIO6, 3.3 V and common ground; one addressable
RGB pixel on GPIO8. Confirm OLED address (`0x3C` by default), display geometry,
board pin labels and pixel type. A simple on-board LED is not automatically an
addressable pixel; strapping pins and current limits are board-specific.

```bash
cd firmware/esp32-c3-indicator
# Native USB CDC board, data lines on GPIO18/19:
pio run -e esp32-c3-devkitm-1
pio run -e esp32-c3-devkitm-1 -t upload --upload-port /dev/ttyACM0
# OR: C3 board reached through a CP210x/CH340 UART bridge:
pio run -e esp32-c3-uart
pio run -e esp32-c3-uart -t upload --upload-port /dev/ttyUSB0
cd ../..
```

Choose **one** environment matching the actual board/USB connection; port names
above are examples. The wired C3 path requires no Wi-Fi credential. Once attached
to Core, set `INDICATOR_PORT=/dev/serial/by-id/YOUR-C3-ID` in Core's environment
file, then restart `rewatch-indicator`. Stable by-id paths are preferable to
guessing which `ttyUSB0` device appears first.

Core sends newline-delimited JSON at 115200 baud, approximately every 100 ms.
Unknown/stale data should show BLUE rather than a reassuring remembered score.
Verify the OLED and pixel visually; successful compilation/upload does not prove
wiring or display appearance.

### ESP32-WROOM: optional four-room AC rig

Do not power this rig on a network with real devices using the same
`room1-ac`–`room4-ac` IDs. Keep it in the lab. Copy the public example into the
ignored local secrets file and edit it privately:

```bash
cp firmware/esp32-wroom-rig/src/secrets.example.h firmware/esp32-wroom-rig/src/secrets.h
chmod 600 firmware/esp32-wroom-rig/src/secrets.h
# Open src/secrets.h in a local editor; never commit it.
```

Set `REWATCH_WIFI_SSID`, `REWATCH_WIFI_PASS`, `REWATCH_MQTT_HOST` (Core's reachable
IP, or laptop IP for laptop-real mode), `REWATCH_MQTT_PORT`, and any broker
credentials. Use the firmware's exact C macro names. Then:

```bash
cd firmware/esp32-wroom-rig
pio run -e esp32dev
pio run -e esp32dev -t upload --upload-port /dev/ttyUSB0
cd ../..
```

The `compile-check` environment builds with public placeholder credentials for
validation only; **do not flash it as a configured deployment**. Firmware
dependencies follow the current `platformio.ini`; a past successful toolchain
version is not a guarantee that all dependency ranges are locked.

Find the rig's actual DHCP address. Its `http://RIG-IP/status` endpoint reports
the four room readings and IP; MQTT sends their individual telemetry topics.
Confirm the HTTP endpoint from Core's intended Wi-Fi interface, replacing both
the interface and address:

```bash
curl --interface wlan1 --max-time 5 http://192.168.50.30/status
```

This HTTP endpoint is unencrypted/unauthenticated in the lab firmware. The
verifier compares MQTT AC temperature with this HTTP reading; it does not prove
firmware identity or create a tamper-proof independent sensor.

## 9. Connect real telemetry and supported controls

### Learn what is actually connected

Before enabling actions, collect each asset's stable device ID, kind, location,
bridge address, firmware metadata, observed fields and supported commands.
Compare router leases, the bridge's own status, MQTT messages and the intended
physical asset. IP discovery alone neither enrolls a device nor grants control.

On Core, or an authorized MQTT client host, observe a small sample. Use your
actual broker IP and do not add `-r` to test publications:

```bash
mosquitto_sub -h 192.168.50.10 -p 1883 -t 'rewatch/health/#' -v -C 6 -W 15
mosquitto_sub -h 192.168.50.10 -p 1883 -t 'rewatch/iot/+/telemetry' -v -C 8 -W 15
mosquitto_sub -h 192.168.50.10 -p 1883 -t 'rewatch/verify/#' -v -C 4 -W 15
```

Install `mosquitto-clients` on the client host if needed. Use your broker's secure
credential-handling mechanism if authentication is configured; do not put a
password in a pasted command line. Subscriber timeouts can simply mean that no
matching publisher is sending; they are not proof of a broken dashboard.

| Topic | Source / purpose |
|---|---|
| `rewatch/health/<node>` | Node liveness and role health |
| `rewatch/iot/<device>/telemetry` | Device/bridge observations |
| `rewatch/detect/...` | Sentinel detections/conditions |
| `rewatch/verify/<device>` | HTTP vs MQTT AC cross-check result |
| `rewatch/threat/state` | Core's score, band and incident state |
| `rewatch/iot/<device>/cmd` | Supported command consumed by a trusted bridge |
| `rewatch/rig/cmd` | WROOM lab rig scenario control, not a physical AC command |

For the topic/configuration contract see [common/rewatch.py](common/rewatch.py),
and for capability validation see [common/iot.py](common/iot.py). A compatible
AC telemetry message identifies the device and can include `kind`, `room`,
`temp_c`, `setpoint`, `power`, `ip` and firmware metadata. Non-AC bridges use the
documented per-kind fields, such as `recording`, `lock`, `forced_open`, `power_w`,
`brightness`, `speed`, `smoke` and `leak`. Missing observations must remain
unknown, not be displayed as a successfully verified clear condition.

### Define capabilities deliberately

The installed `/etc/rewatch/devices.json` begins from
[`devices.example.json`](devices.example.json), with actions **disabled**. Add
only devices/bridges you own and have tested. Core's policy determines commands;
Sentinel's policy supplies detector profiles and approved firmware metadata.
Keep their copies consistent and restart the relevant services after changes.

| Kind | Allowed action names | Important boundary |
|---|---|---|
| AC | `setpoint` | UI/API range 16–30 °C; confirm bridge behavior |
| Camera | `recording` | Boolean bridge action, not native universal camera control |
| Door | `lock` | Lock-only and explicit confirmation; no remote unlock action |
| Plug | `power` | Boolean; configure an appropriate `max_power_w` |
| Light | `power`, `brightness` | Boolean / 0–100 |
| Fan | `power`, `speed` | Boolean / 0–100 |
| Sensor | None | Observe-only |

Keep `enabled: false` until the bridge's actual command handling and read-back
are checked. Add all four AC IDs explicitly if you intentionally enable the
four-room lab rig. A successful `/api/control` response is **202 requested**, not
proof that a physical action occurred. Confirm fresh telemetry and, where
applicable, the physical device. ReWatch does not supply general ONVIF, Matter,
vendor-cloud or door-controller integrations merely because a kind appears in
the UI. Firmware strings are metadata, not remote attestation.

For a consistency cross-check the bridge must serve compatible JSON on HTTP
port 80 at `/status`; the supplied verifier is AC-temperature-specific. Without
that implementation, an unreachable/unknown Wi-Fi result is honest and expected.

## 10. Start and verify the complete Pi system

The installer already enables and starts units at boot. After configuration,
check/restart explicitly on the appropriate nodes:

```bash
# Core
sudo systemctl restart mosquitto
sudo systemctl restart rewatch-core rewatch-dashboard rewatch-verifier rewatch-indicator
sudo systemctl status mosquitto rewatch-core rewatch-dashboard rewatch-verifier rewatch-indicator --no-pager
sudo journalctl -u rewatch-core -u rewatch-dashboard -n 80 --no-pager
```

```bash
# Sentinel
sudo systemctl restart rewatch-sentinel
sudo systemctl status rewatch-sentinel --no-pager
sudo journalctl -u rewatch-sentinel -n 60 --no-pager
```

```bash
# Herald
sudo systemctl restart rewatch-herald
sudo systemctl status rewatch-herald --no-pager
sudo journalctl -u rewatch-herald -n 60 --no-pager
```

A process being active is only the first check. In the owner dashboard verify:

1. **Transport:** live connection, production MQTT connected, correct node
   heartbeat ages. Missing Sentinel/Herald can put the real engine in BLUE;
   do not hide this by injecting fake heartbeats.
2. **Inventory:** only intended observed/enrolled assets, stable IDs and current
   readings. Production inventory is not automatically the demo's 28 devices.
3. **Capture:** bounded authorized traffic appears on Sentinel's selected
   interface; understand the initial 300-second device-learning window.
4. **Evidence:** mount/USB indication and actual dated JSONL files agree; Core's
   database at `/var/lib/rewatch/rewatch.db` persists its events/incidents.
5. **Verification:** the rig HTTP path works over the selected associated Wi-Fi
   adapter; actual MQTT and HTTP readings agree within the configured tolerance.
6. **Indicator:** one writer owns the C3 port; OLED/pixel match the current band
   and become stale/BLUE when the relevant feed is lost.
7. **Mail:** use **Send test e-mail**, check Herald's SMTP result, then independently
   check the intended mailbox and spam folder. SMTP acceptance is not delivery.
8. **Authentication:** the enrolled real passkey works at the intended trusted
   hostname; preserve a recovery authenticator. This does not resolve the
   repository's broader outstanding security-review findings.

For an optional response drill, use only the isolated WROOM model. The following
commands change its simulated temperatures; do not run them against a broker
with colliding real device IDs:

```bash
mosquitto_pub -h 192.168.50.10 -t 'rewatch/rig/cmd' -m '{"scenario":"ac-spike","device":"room1-ac"}'
# End the drill and return model rooms to baseline:
mosquitto_pub -h 192.168.50.10 -t 'rewatch/rig/cmd' -m '{"scenario":"reset"}'
```

Check the engine's incident/band transitions and ACK deadline rather than
assuming a particular instantaneous score. An automatic control response
requires an intentionally enabled, matching bridge policy. Do not leave a
temperature/safety drill active unattended.

## 11. Laptop: self-contained simulation

This is the quickest way to demonstrate the dashboard. No MQTT broker, Pi,
packet capture, USB drive or hardware is required. In a fresh local checkout:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r demo/requirements.txt
./demo/run.sh
```

Open **`http://localhost:8080` on that laptop**. The stock public demo code is
`rewatch`; a locally configured `DEMO_CODE` overrides it. This published default
is not a production secret. See [the demo guide](demo/README.md) for its UI flow.
On Windows, create the virtual environment with `py -m venv .venv`, install with
`.venv\Scripts\python.exe -m pip install -r demo\requirements.txt`, and launch
`.venv\Scripts\python.exe demo\demo_server.py` instead of the Bash wrapper.

For private options, copy the public demo template once, then edit locally:

```bash
cp demo/.env.example demo/.env
chmod 600 demo/.env
```

Do not overwrite an existing configured `demo/.env`. Useful settings are:

| Setting | Meaning |
|---|---|
| `DEMO_PORT=8080` | Local server port |
| `DEMO_AUTO_SPIKE=1` | Scripted AC spike after the demo discovery phase; `0` disables it |
| `DEMO_SEND_MAIL=0` | Keep off for a no-mail demo; configure private SMTP only if deliberately testing |
| `DEMO_PASSKEY_PREVIEW=0` | Keep preview disabled for normal use; it is an unverified recording convenience |

The demo binds loopback by default. Its first scene discovers 28 synthetic
office devices after approximately 20 seconds and can spike an AC at 30 seconds.
Simulation ACK defaults to 20 seconds rather than production's 120 seconds.
Replay resets score/events/history and scenario state while preserving discovered
inventory; stored evidence is separate. Black Hat mode generates simulated
events, not real attacks or capture. The calm score animation is demo-only.

Stop with Ctrl+C and restart with `./demo/run.sh`. It is not a background boot
service just because it ran once. Do not expose its recording preview over the
LAN or treat dismissal of a preview passkey prompt as a successful real login.

Optional physical C3 demonstration, after flashing it and closing other serial
writers, uses a second terminal:

```bash
.venv/bin/python demo/indicator_bridge.py --port /dev/serial/by-id/YOUR-C3-ID
```

This bridge forwards **simulation** state. Stop it before using the production
indicator process or uploading new firmware to the same serial board.

## 12. Laptop: real-data dashboard and collectors

This is the production Python stack run locally, **not** `demo_server.py`.
Use an authorized Linux lab laptop. A physical Pi is optional, but actual data
requires real MQTT publishers/bridges, and packet-derived detections require
capture visibility/privileges. A dashboard alone is not a collector or engine.

### Prepare software and private local state

Run from the repository root. If using the same checkout as the simulation,
reuse the virtual environment but install the full requirements:

```bash
sudo apt update
sudo apt install -y python3 python3-venv mosquitto mosquitto-clients libpcap0.8 tcpdump
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
export REWATCH_ROOT="$PWD"
install -d -m 700 "$HOME/.config/rewatch-laptop" "$HOME/.local/share/rewatch-laptop"
cp devices.example.json "$HOME/.config/rewatch-laptop/devices.json"
export REWATCH_ENV="$HOME/.config/rewatch-laptop/rewatch.env"
umask 077
cat > "$REWATCH_ENV" <<EOF
REWATCH_MQTT_HOST=127.0.0.1
REWATCH_MQTT_PORT=1883
REWATCH_HOSTNAME=localhost
REWATCH_RP_ID=localhost
REWATCH_BIND=127.0.0.1
REWATCH_PORT=8081
REWATCH_ORIGINS=http://localhost:8081
REWATCH_DATA_DIR=$HOME/.local/share/rewatch-laptop
REWATCH_DEVICES_FILE=$HOME/.config/rewatch-laptop/devices.json
REWATCH_ACCESS_CODE=
SENTINEL_IFACE=eth0
SENTINEL_USB_MOUNT=/mnt/rewatch-usb
SENTINEL_STATE_DIR=$HOME/.local/share/rewatch-laptop/sentinel-state
SENTINEL_FALLBACK_DIR=$HOME/.local/share/rewatch-laptop/sentinel-logs
SENTINEL_LEARN_S=300
VERIFY_IFACE=wlan1
VERIFY_TOLERANCE_C=1.5
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=
SMTP_PASS=
SMTP_FROM=
ALERT_TO=
SMTP_IFACE=wlan1
DASHBOARD_URL=http://localhost:8081
ACK_TIMEOUT_S=120
AC_BASELINE_C=20
RESPONDER_NFT=0
EOF
chmod 600 "$REWATCH_ENV"
```

These copy/write commands are for **first setup**; back up existing local
configuration before re-running them. Edit the file with the actual capture,
verification and SMTP interface names, broker address and any private SMTP
credentials. Unset inherited `REWATCH_*`/SMTP overrides that conflict with this
mode; the loader gives existing environment variables precedence. Set
`REWATCH_ENV` **before starting each process**. The production programs do not
automatically use `demo/.env` or a repository-root `.env`.

Port 8081 avoids collision with a simulation still on 8080. The two modes have
separate databases and can coexist, but do not share an indicator's serial port.
For clarity stop the simulation while checking real observations.

### Choose one broker

**Existing lab broker:** put its actual address/port in the private environment
file. Point the publishers at that same broker. No local broker is needed.

**Laptop-hosted broker:** for local-only publishers the distribution's broker
may already be listening on loopback. Check `systemctl status mosquitto` and
`ss -ltn` before starting anything. To accept an external rig, explicitly
configure a listener reachable on the authorized lab interface. For example,
the following is a separate foreground lab broker configuration; replace the
address with the laptop's actual lab IP, and use it only if port 1883 is free:

```bash
umask 077
cat > "$HOME/.config/rewatch-laptop/mosquitto.conf" <<'EOF'
listener 1883 192.168.50.20
allow_anonymous true
persistence false
EOF
mosquitto -c "$HOME/.config/rewatch-laptop/mosquitto.conf" -v
```

It binds **that address**, not loopback: change `REWATCH_MQTT_HOST` in the laptop
environment file to the same lab IP and point the rig there too. Never run this
anonymous listener on an untrusted/shared network. Limit host/network access
appropriately. Do not start a second broker on an occupied port or stop an
existing shared broker without approval. Persistence is off in this foreground
example; Core's SQLite evidence is still separate.

### Start the actual components

Use separate terminals, all in the same checkout. In **each** terminal set:

```bash
export REWATCH_ROOT="/absolute/path/to/ReWatch-IOT-"
export REWATCH_ENV="$HOME/.config/rewatch-laptop/rewatch.env"
cd "$REWATCH_ROOT"
```

Then run one component per terminal:

```bash
# Terminal A: engine / incident state
.venv/bin/python pi4-core/engine.py
```

```bash
# Terminal B: production dashboard (module launched from pi4-core)
cd "$REWATCH_ROOT/pi4-core"
"$REWATCH_ROOT/.venv/bin/python" -m server.app
```

```bash
# Terminal C: real authorized capture; keep privilege limited to this process
sudo env REWATCH_ENV="$REWATCH_ENV" "$REWATCH_ROOT/.venv/bin/python" "$REWATCH_ROOT/pi3-sentinel/detector.py"
```

```bash
# Terminal D: Herald / liveness / SMTP when configured
.venv/bin/python pi3-herald/mailer.py
```

Do not run the dashboard/engine as root or use `sudo pip`. Sentinel needs raw
capture privileges; its separate state/log directories may be root-owned, so
do not reuse them as the dashboard's authentication directory. If laptop capture
cannot see the IoT VLAN, use a properly connected remote Sentinel instead. Run
only one intended instance of each node identity on a broker.

Optional terminals, if the actual Wi-Fi route/HTTP bridge or C3 is present:

```bash
.venv/bin/python pi4-core/verifier.py
```

```bash
# Set a real connected by-id path, and ensure no demo bridge owns it.
export INDICATOR_PORT=/dev/serial/by-id/YOUR-C3-ID
.venv/bin/python pi4-core/indicator.py
```

Without a compatible HTTP status endpoint, the verifier cannot magically verify
non-AC devices. Without actual Sentinel/Herald heartbeats the engine can show
BLUE even if the browser connection is healthy. Use actual role processes or
properly configured remote nodes, not simulated heartbeats to make it look green.

### Enroll locally and confirm real data

In another terminal with the **same `REWATCH_ENV`**, run:

```bash
cd "$REWATCH_ROOT/pi4-core"
"$REWATCH_ROOT/.venv/bin/python" -m server.enroll
```

Open **`http://localhost:8081` on the laptop**, register the owner with the
one-use code, and complete the authenticator prompt. Localhost is the browser's
secure-context exception. If the browser has no suitable authenticator, use a
supported hardware/security key or an explicitly chosen fallback-access setup;
do not enable demo preview in the production server.

Point the WROOM/real bridges at the broker chosen above, inspect their telemetry
topics and verify current readings in the production dashboard. For other real
devices, complete [capability enrollment](#9-connect-real-telemetry-and-supported-controls)
and implement the corresponding bridge. The production stack does not inject
the 28-asset office scene or a breathing baseline to fill missing data.

To view this laptop-hosted **real** dashboard from another computer, configure
trusted HTTPS, name resolution, matching RP ID/origins and a deliberate LAN bind
as in [the HTTPS section](#7-configure-trusted-https-and-enroll-an-owner). Use a
non-privileged TLS port such as 8443 for a normal laptop user and include it in
`REWATCH_ORIGINS` and `DASHBOARD_URL`. The certificate must cover the hostname;
`http://LAPTOP-IP:8081` is not a real remote-passkey solution. Email links using
`localhost` are usable only on the machine hosting that dashboard.

## 13. Troubleshooting

| Symptom | Check before changing code |
|---|---|
| SSH unreachable | Correct lease/IP/user, SSH enabled in Imager, Ethernet, routing and host fingerprint |
| Deploy skips a node | Manual SSH and interactive sudo work; rsync installed; read that role's installer output |
| Dashboard refused / port occupied | Correct process/unit, bind address, chosen port and `ss -ltn`; don't start two servers on one port |
| Login HTML loads but passkey fails | Trusted HTTPS and correct DNS/RP/origin; or actual browser-local `localhost`; correct system clock |
| Old passkey stops working after a hostname change | Passkeys are RP-scoped; re-enroll at the new trusted hostname, preserve old DB/recovery credentials |
| MQTT disconnected | Same broker address/port on all clients, listener bound to reachable interface, firewall/isolation and matching broker credentials |
| BLUE band | Inspect Sentinel/Herald freshness and the state's reason; browser LIVE is not the same as all nodes healthy |
| No device cards in real mode | Publishers must send valid telemetry; demo assets are not real auto-discovery; check policy and topics |
| Few captured packets | Correct interface and SPAN/TAP wiring; ordinary switched/Wi-Fi client traffic may not expose peers |
| USB indicator says absent | `mountpoint`, not just directory existence; drive permissions/free space and Sentinel fallback path |
| Wi-Fi verifier unknown | Interface has IP/route, rig `/status` reachable on port 80, correct device ID and temperature fields |
| Device request denied or no form | Policy disabled/observe-only, unsupported action, stale observations, door confirmation, invalid value |
| HTTP 202 but device unchanged | Only a request was accepted; inspect the bridge subscriber and fresh physical read-back |
| SMTP accepted but inbox empty | Independently check recipient/spam/provider; acceptance is not delivery |
| C3 upload cannot open port | Correct USB mode/data cable/permissions; close serial monitors and the bridge; use documented BOOT/RESET |
| C3 stays BLUE | Actual serial port/baud, current host state and node heartbeat freshness; one serial writer only |
| OLED/pixel blank | Physical power/common ground/pin mapping/I²C address/display/pixel type; compilation does not validate wiring |
| Simulated data mistaken for real data | Check which server/port you opened; demo has `simulation: true`, no real MQTT, and synthetic office assets |

Review journal/log excerpts locally and redact credentials, tokens, email
addresses and network data before sharing them. Never attach `auth.db`, private
keys, `.env` files or `secrets.h` to a troubleshooting issue.

## 14. Shutdown, updates, backups and acceptance record

### Shut down cleanly

Stop foreground laptop programs with Ctrl+C. On Pis, stop the role services before
maintenance, then `sudo poweroff`; wait before removing power. Stop Sentinel
before unmounting/removing the USB evidence drive:

```bash
# Sentinel, during planned maintenance
sudo systemctl stop rewatch-sentinel
sudo umount /mnt/rewatch-usb
```

Remount and restart the service afterward. Do not delete evidence or owner
credentials as a shortcut for fixing a display/reset problem.

### Back up before updating

Protect copies of `/etc/rewatch/rewatch.env`, `devices.json`, server certificate
and key, authentication/evidence databases, Sentinel state and USB logs. Stop
the relevant writers or use a consistent SQLite backup procedure; blindly
copying an active `.db` while ignoring WAL files can lose data. Encrypt/access-
restrict backups. Keep CA private-key backups separate from deployed nodes.

On the admin checkout, record the deployed Git SHA, review updates, and re-run
the deployer's dry-run before a deliberate deployment. It overwrites generated
environment settings: reapply/verify TLS, actual interfaces and local policy
afterward. Do not assume a successful software update validates physical paths.

### Record what was actually verified

- [ ] Pi model/OS/kernel and deployed source commit recorded for each role.
- [ ] SSH identity/key login, hostname, reserved IP and correct time checked.
- [ ] Actual capture topology and authorized observation demonstrated.
- [ ] MQTT connectivity, genuine node health and real telemetry checked.
- [ ] Device IDs/capabilities reviewed; no demo/rig identity collision.
- [ ] Wi-Fi HTTP verification path measured, or explicitly marked unverified.
- [ ] Persistent USB evidence and fallback behavior checked.
- [ ] Trusted HTTPS and real owner enrollment/login checked on intended devices.
- [ ] C3 flashed and physical OLED/pixel output checked, or explicitly unverified.
- [ ] SMTP transport and inbox delivery recorded separately.
- [ ] Authorized isolated response/ACK drill completed and returned to baseline.
- [ ] Protected backups, recovery authenticator and shutdown procedure checked.

Repository tests can be run without deploying hardware:

```bash
.venv/bin/python -m pip install -r requirements.txt -r requirements-dev.txt
.venv/bin/python -m pytest -o addopts='' -q --disable-warnings
.venv/bin/ruff check . --select F
```

Browser integration and physical acceptance are separate. Do not report these
commands as proof of hardware operation or mail delivery. See the dated
[verification record](docs/BUILD-CHECKLIST.md) for the existing evidence boundary.

## 15. Reference material

Repository sources used by this guide:

- [Hardware and wiring](hardware.md), [firmware guide](firmware/README.md),
  [demo guide](demo/README.md), [security model](SECURITY.md).
- [Remote deployment script](start.sh), [node installer](tools/node-install.sh),
  [environment template](.env.example), [device policy template](devices.example.json).
- [Core services](pi4-core/systemd/), [Sentinel service](pi3-sentinel/systemd/),
  [Herald service](pi3-herald/systemd/), [lab certificate helper](tools/make_local_ca.sh).

Current platform references (check these when OS/browser tooling differs):

- [Raspberry Pi OS installation](https://www.raspberrypi.com/documentation/computers/getting-started.html)
  and [remote access](https://www.raspberrypi.com/documentation/computers/remote-access.html).
- [PlatformIO Core installation](https://docs.platformio.org/en/latest/core/installation/index.html)
  and [device permissions](https://docs.platformio.org/en/latest/core/installation/udev-rules.html).
- [NetworkManager nmcli](https://networkmanager.dev/docs/api/latest/nmcli.html).
- [Mosquitto configuration](https://mosquitto.org/man/mosquitto-conf-5.html).
- [WebAuthn security requirements](https://www.w3.org/TR/webauthn-3/)
  and [browser credential creation](https://developer.mozilla.org/en-US/docs/Web/API/CredentialsContainer/create).
