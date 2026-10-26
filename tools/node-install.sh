#!/usr/bin/env bash
# ReWatch(Iot) — per-node installer. Runs ON a Raspberry Pi, as root.
#
#   sudo ./tools/node-install.sh <role>
#   role = core | sentinel | herald
#
# start.sh runs this for you over SSH. It is safe to re-run (idempotent): it
# refreshes code and services without touching /var/lib/rewatch data or the
# passkey database.
set -euo pipefail

ROLE="${1:-}"
SRC="$(cd "$(dirname "$0")/.." && pwd)"
DEST=/opt/rewatch
ENVFILE=/etc/rewatch/rewatch.env

case "$ROLE" in core|sentinel|herald) ;; *)
  echo "usage: node-install.sh <core|sentinel|herald>" >&2; exit 2 ;; esac
[[ $EUID -eq 0 ]] || { echo "run with sudo" >&2; exit 1; }

echo "── ReWatch(Iot) $ROLE install ─────────────────────────────────────────"

# 1. system packages
export DEBIAN_FRONTEND=noninteractive
APT="python3 python3-venv python3-pip rsync"
[[ "$ROLE" == core ]]     && APT="$APT mosquitto mosquitto-clients nftables"
[[ "$ROLE" == sentinel ]] && APT="$APT libpcap0.8 tcpdump"
apt-get update -qq
apt-get install -y -qq $APT

# 2. service account + dirs
id rewatch &>/dev/null || useradd --system --home "$DEST" --shell /usr/sbin/nologin rewatch
usermod -aG dialout rewatch 2>/dev/null || true
install -d -o rewatch -g rewatch /var/lib/rewatch
install -d /etc/rewatch

# 3. code -> /opt/rewatch
install -d "$DEST"
rsync -a --delete \
  --exclude 'demo/' --exclude '.git/' --exclude 'tests/' --exclude 'ca/' --exclude 'certs/' \
  "$SRC/common" "$SRC/tools" "$DEST/"
case "$ROLE" in
  core)     rsync -a --delete "$SRC/pi4-core" "$DEST/" ;;
  sentinel) rsync -a --delete "$SRC/pi3-sentinel" "$DEST/" ;;
  herald)   rsync -a --delete "$SRC/pi3-herald" "$DEST/" ;;
esac
chown -R rewatch:rewatch "$DEST"

# 4. python venv
if [[ ! -x "$DEST/venv/bin/python" ]]; then
  python3 -m venv "$DEST/venv"
fi
"$DEST/venv/bin/pip" install --quiet --upgrade pip
install -m 644 "$SRC/requirements.txt" "$DEST/requirements.txt"
echo "   installing pinned requirements.txt"
"$DEST/venv/bin/pip" install --quiet -r "$DEST/requirements.txt"
chown -R rewatch:rewatch "$DEST/venv"

# 5. env file (start.sh usually pushes this first; keep an existing one)
if [[ ! -f "$ENVFILE" ]]; then
  cp "$SRC/.env.example" "$ENVFILE"
  echo "   wrote $ENVFILE from template — edit SMTP/IPs as needed"
fi
chmod 640 "$ENVFILE"; chown root:rewatch "$ENVFILE"
# Enrollment is operator-owned; upgrades never overwrite an existing policy.
if [[ ! -f /etc/rewatch/devices.json ]]; then
  install -m 640 -o root -g rewatch "$SRC/devices.example.json" /etc/rewatch/devices.json
fi

# 6. broker (core only)
if [[ "$ROLE" == core ]]; then
  install -m 644 "$SRC/pi4-core/mosquitto/rewatch.conf" /etc/mosquitto/conf.d/rewatch.conf
  systemctl enable --now mosquitto
  systemctl restart mosquitto
fi

# 7. systemd units
case "$ROLE" in
  core)     UNITS="rewatch-core rewatch-dashboard rewatch-verifier rewatch-indicator"; UDIR="$SRC/pi4-core/systemd" ;;
  sentinel) UNITS="rewatch-sentinel"; UDIR="$SRC/pi3-sentinel/systemd" ;;
  herald)   UNITS="rewatch-herald";   UDIR="$SRC/pi3-herald/systemd" ;;
esac
for u in $UNITS; do install -m 644 "$UDIR/$u.service" /etc/systemd/system/; done
systemctl daemon-reload
for u in $UNITS; do systemctl enable "$u"; systemctl restart "$u"; done

echo "── $ROLE up. services: $UNITS"
if [[ "$ROLE" == core ]]; then
  echo "   register your passkey — get a code with:"
  echo "     cd $DEST/pi4-core && sudo -u rewatch env REWATCH_DATA_DIR=/var/lib/rewatch $DEST/venv/bin/python -m server.enroll"
fi
