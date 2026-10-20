# Security and responsible operation

ReWatch is a prototype for **authorized lab and building-IoT experiments**.
Do not rely on it as a safety interlock, certified alarm or guaranteed intrusion
prevention system. Do not connect the WROOM rig directly to mains equipment.

## Boundaries and known limitations

- **Network trust:** the shipped Mosquitto configuration permits anonymous,
  unencrypted LAN MQTT. An attached client may spoof telemetry, heartbeat,
  detection or command topics. Segregate the lab; restrict listener access,
  enable authentication and topic ACLs, and protect transport before expanding
  the trust boundary. No Internet exposure or automatic secure provisioning is
  supplied by the installer.
- **Observation:** Sentinel sees traffic delivered to its interface, not every
  switched packet. Validate SPAN/TAP placement. Threshold detection can miss
  attacks or raise false positives; device HTTP verification is not attestation.
- **Response:** a published command is an attempt, not confirmed repair. A local
  nftables rule cannot isolate unrelated peer-to-peer LAN traffic. Only enable
  firewall responses after designing and testing the actual enforcement path.
- **Device capabilities:** production controls require a trusted local device
  policy and explicit opt-in; telemetry cannot grant permissions. MQTT bridges
  are device-specific, not universal vendor integrations. Doors are lock-only
  with confirmation; no firmware writes or automatic non-AC playbooks exist.
  Firmware-version comparisons use unattested metadata, not signed attestation.
  Demo network responses cannot invoke firewall enforcement, even if the
  production firewall environment flag is inherited.
- **Authentication:** real WebAuthn requires enrolled credentials, user
  verification and a trusted origin/RP ID. Use HTTPS for remote LAN access;
  HTTP localhost is a development exception. The optional shared access code
  is a weaker fallback—leave it empty outside a controlled demonstration.
- **Recording-only bypass:** `DEMO_PASSKEY_PREVIEW=1` enables a plainly labelled,
  unverified local demo unlock after any browser prompt result, including cancel.
  It is off by default, loopback/Host restricted and audited; it does not exist
  in the production application. Never present it as fingerprint verification.
- **Credentials:** copy only example configuration. Keep `.env`, `secrets.h`,
  databases, private keys and CA material out of Git and recordings. Revoke any
  exposed SMTP app password before creating a replacement. E-mail previews do
  not send; SMTP acceptance does not prove inbox arrival.
- **Deployment:** `start.sh --config` sources trusted shell code, not a passive
  data file. `--dry-run` performs local parsing/temporary configuration only;
  never load an untrusted config. Deployment installs packages, overwrites
  source/config and restarts services. Back up first. It does not provision
  Wi-Fi, routing, mounts, trusted TLS, mirror ports or comprehensive hardening.
- **Evidence:** USB JSONL and dashboard records are not immutable/tamper-proof
  forensic storage. Protect access, synchronize clocks, set retention and
  backups, and consider log privacy. Demo live state is synthetic and in memory;
  its SQLite events, samples and incidents persist across Replay and restart.

## Before deployment

1. Record hardware revisions, firmware, interface names, capture visibility,
   stable power, storage mount/permissions and update/backup procedures.
2. Restrict SSH, MQTT and dashboard access; install trusted HTTPS, enroll the
   owner and disable unnecessary fallback access.
3. Test real SMTP delivery, ACK/no-ACK behavior, offline/serial link loss,
   command execution and independently observed outcomes using the safe rig.

## Reporting a vulnerability

Use the repository's **Security → Report a vulnerability** flow if available.
If it is unavailable, open an issue requesting a private contact **without**
exploit details, personal network data or secrets. Do not post live credentials.
There is no published response SLA or guarantee of a bounty.

Security notes do not alter the [Apache-2.0 license](LICENSE).
