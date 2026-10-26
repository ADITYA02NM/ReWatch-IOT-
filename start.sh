#!/usr/bin/env bash
# ══════════════════════════════════════════════════════════════════════════════
#  ReWatch(Iot) — one-shot deployer.
#
#  Run this once from your admin laptop. It asks for the IP address of each
#  device, then SSHes into every one, copies the code, installs the Python
#  services and the MQTT broker, writes the config, and starts everything —
#  Sentinel detection, the Pi 4 threat engine + dashboard + Wi-Fi verifier +
#  indicator bridge, and the Herald mailer. Then it exits.
#
#      ./start.sh                 interactive
#      ./start.sh --dry-run       show what it would do, touch nothing
#      ./start.sh --config a.env  source a TRUSTED shell file (executes code)
#
#  Requirements on this laptop: bash, ssh, rsync. Each Pi needs SSH enabled and
#  your key installed (ssh-copy-id pi@<ip>), or you will be asked for passwords.
# ══════════════════════════════════════════════════════════════════════════════
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
DRY=0; CONFIG=""
while (($#)); do
  case "$1" in
    --dry-run) DRY=1 ;;
    --config) [[ $# -ge 2 && -n "$2" ]] || { echo "--config needs a trusted file" >&2; exit 2; }; CONFIG="$2"; shift ;;
    --config=*) CONFIG="${1#*=}"; [[ -n "$CONFIG" ]] || exit 2 ;;
    -h|--help) grep '^#' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "Unknown argument: $1" >&2; exit 2 ;;
  esac
  shift
done

c_g(){ printf '\033[32m%s\033[0m' "$1"; }
c_b(){ printf '\033[1;36m%s\033[0m' "$1"; }
c_y(){ printf '\033[33m%s\033[0m' "$1"; }
hr(){ printf '%s\n' "────────────────────────────────────────────────────────────"; }
ask(){ local p="$1" d="${2:-}" v; read -rp "$(c_b "$p")${d:+ [$d]}: " v; echo "${v:-$d}"; }
asksecret(){ local p="$1" v; read -rsp "$(c_b "$p"): " v; echo >&2; echo "$v"; }

echo; c_g "  ReWatch(Iot) — deployer"; echo; hr
echo "  I'll set up three Raspberry Pis and the broker from here."
echo "  Nothing is sent until you confirm the plan."; hr

# ── gather answers ────────────────────────────────────────────────────────────
if [[ -n "$CONFIG" ]]; then
  [[ -f "$CONFIG" ]] || { echo "Config file not found" >&2; exit 2; }
  echo "Loading trusted shell configuration: $CONFIG"
  set -a; source "$(realpath "$CONFIG")"; set +a
fi

SSH_USER="${SSH_USER:-$(ask 'SSH username on the Pis' 'pi')}"
IP_CORE="${IP_CORE:-$(ask 'Pi 4 CORE ip (engine + dashboard, switch port 3)' '192.168.100.1')}"
IP_SENTINEL="${IP_SENTINEL:-$(ask 'Pi 3 SENTINEL ip (detection + USB log, switch port 2)' '192.168.100.2')}"
IP_HERALD="${IP_HERALD:-$(ask 'Pi 3 HERALD ip (SMTP alerts, switch port 4)' '192.168.100.3')}"

echo; c_y "  E-mail alerts (Herald)"; echo
SMTP_HOST="${SMTP_HOST:-$(ask 'SMTP host' 'smtp.gmail.com')}"
SMTP_PORT="${SMTP_PORT:-$(ask 'SMTP port' '587')}"
SMTP_USER="${SMTP_USER:-$(ask 'SMTP username (sender)' '')}"
SMTP_PASS="${SMTP_PASS:-$(asksecret 'SMTP password / app password')}"
ALERT_TO="${ALERT_TO:-$(ask 'Send alerts to (comma-separated)' "$SMTP_USER")}"

echo; c_y "  Dashboard"; echo
REWATCH_HOSTNAME="${REWATCH_HOSTNAME:-$(ask 'Dashboard hostname' 'rewatch.local')}"
ACCESS_CODE="${REWATCH_ACCESS_CODE:-$(ask 'Fallback access code for isolated Black Hat exercises (blank = passkey only)' '')}"

fail(){ echo "Invalid $1; refusing deployment." >&2; exit 2; }
ipv4(){
  local label="$1" value="$2" octet
  [[ "$value" =~ ^[0-9]{1,3}(\.[0-9]{1,3}){3}$ ]] || fail "$label"
  local -a octets; IFS=. read -ra octets <<< "$value"
  for octet in "${octets[@]}"; do ((10#$octet <= 255)) || fail "$label"; done
}
hostname(){
  local label="$1" value="$2" part
  [[ ${#value} -le 253 && "$value" != *..* ]] || fail "$label"
  local -a parts; IFS=. read -ra parts <<< "$value"
  for part in "${parts[@]}"; do
    [[ "$part" =~ ^[a-zA-Z0-9]([a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?$ ]] || fail "$label"
  done
  [[ -n "$value" && "$value" != .* && "$value" != *. ]] || fail "$label"
}
[[ "$SSH_USER" =~ ^[a-z_][a-z0-9_-]{0,31}$ ]] || fail SSH_USER
ipv4 IP_CORE "$IP_CORE"; ipv4 IP_SENTINEL "$IP_SENTINEL"; ipv4 IP_HERALD "$IP_HERALD"
[[ "$IP_CORE" != "$IP_SENTINEL" && "$IP_CORE" != "$IP_HERALD" && "$IP_SENTINEL" != "$IP_HERALD" ]] || fail 'duplicate node IPs'
hostname SMTP_HOST "$SMTP_HOST"; hostname REWATCH_HOSTNAME "$REWATCH_HOSTNAME"
[[ "$SMTP_PORT" =~ ^[0-9]{1,5}$ ]] && ((10#$SMTP_PORT >= 1 && 10#$SMTP_PORT <= 65535)) || fail SMTP_PORT
# EnvironmentFile and Python env-reader share this deliberately simple format.
# Reject ambiguous quotes/escapes and multiline injection rather than misparse secrets.
for name in SMTP_USER SMTP_PASS ALERT_TO ACCESS_CODE; do
  value="${!name}"
  [[ "$value" != *$'\n'* && "$value" != *$'\r'* && "$value" != *'"'* && "$value" != *"'"* && "$value" != *'\'* ]] || fail "$name (multiline/quote/escape)"
  [[ "$value" != [[:space:]]* && "$value" != *[[:space:]] ]] || fail "$name (edge whitespace)"
done

# ── build the shared env ──────────────────────────────────────────────────────
umask 077
TMP_ENV="$(mktemp "${TMPDIR:-/tmp}/rewatch-env.XXXXXXXX")"; trap 'rm -f "$TMP_ENV"' EXIT
DASH_URL="http://${REWATCH_HOSTNAME}:8080"
cat > "$TMP_ENV" <<EOF
REWATCH_MQTT_HOST=$IP_CORE
REWATCH_MQTT_PORT=1883
REWATCH_HOSTNAME=$REWATCH_HOSTNAME
REWATCH_RP_ID=$REWATCH_HOSTNAME
REWATCH_PORT=8080
REWATCH_DATA_DIR=/var/lib/rewatch
REWATCH_DEVICES_FILE=/etc/rewatch/devices.json
REWATCH_ACCESS_CODE=$ACCESS_CODE
SENTINEL_IFACE=eth0
SENTINEL_USB_MOUNT=/mnt/rewatch-usb
AC_CRITICAL_C=32
VERIFY_IFACE=wlan1
VERIFY_TOLERANCE_C=1.5
SMTP_HOST=$SMTP_HOST
SMTP_PORT=$SMTP_PORT
SMTP_USER=$SMTP_USER
SMTP_PASS=$SMTP_PASS
SMTP_FROM=$SMTP_USER
ALERT_TO=$ALERT_TO
SMTP_IFACE=wlan1
DASHBOARD_URL=$DASH_URL
ACK_TIMEOUT_S=120
AC_BASELINE_C=20
RESPONDER_NFT=0
EOF

echo; hr; c_g "  Plan"; echo
printf "   %-10s %-16s %s\n" CORE "$IP_CORE" "mosquitto · engine · dashboard · verifier · indicator"
printf "   %-10s %-16s %s\n" SENTINEL "$IP_SENTINEL" "detection · USB evidence log"
printf "   %-10s %-16s %s\n" HERALD "$IP_HERALD" "SMTP alerts -> $ALERT_TO"
printf "   dashboard  %s\n" "$DASH_URL"
hr
[[ "$DRY" == 1 ]] && { echo "  --dry-run: stopping here."; exit 0; }
[[ "$(ask 'Deploy now? (yes/no)' 'no')" == yes ]] || { echo "aborted."; exit 0; }

# ── deploy to one node ────────────────────────────────────────────────────────
SSH_OPTS=(-o ConnectTimeout=10 -o StrictHostKeyChecking=accept-new)
deploy(){
  local role="$1" ip="$2" host="$SSH_USER@$2" remote_env
  echo; hr; c_g "  → $role @ $ip"; echo
  echo "   checking SSH…"
  ssh "${SSH_OPTS[@]}" "$host" true || { c_y "   cannot reach $host — skipped"; echo; return 1; }
  echo "   copying code…"
  ssh "${SSH_OPTS[@]}" "$host" 'mkdir -p ~/rewatch-src' || return 1
  rsync -az --delete -e "ssh ${SSH_OPTS[*]}" \
    --exclude '.git' --exclude 'demo' --exclude 'tests' --exclude 'ca' --exclude 'certs' \
    --exclude '.venv' --exclude 'venv' --exclude '.pio' --exclude 'node_modules' \
    --exclude '.env' --exclude '*.env' --exclude 'secrets.h' --exclude '*.db*' \
    --exclude '__pycache__' --exclude '*.pyc' --exclude '*.pem' --exclude '*.key' \
    "$HERE/" "$host:~/rewatch-src/" || return 1
  echo "   writing config…"
  remote_env="$(ssh "${SSH_OPTS[@]}" "$host" 'umask 077; mktemp /tmp/rewatch-env.XXXXXXXX')" || return 1
  [[ "$remote_env" =~ ^/tmp/rewatch-env\.[a-zA-Z0-9]{8}$ ]] || return 1
  if ! scp "${SSH_OPTS[@]}" -q "$TMP_ENV" "$host:$remote_env"; then
    ssh "${SSH_OPTS[@]}" "$host" "rm -f '$remote_env'" || true
    return 1
  fi
  echo "   installing (sudo)…"
  if ! ssh -t "${SSH_OPTS[@]}" "$host" \
    "trap 'rm -f $remote_env' EXIT; sudo install -d /etc/rewatch && sudo install -m640 '$remote_env' /etc/rewatch/rewatch.env && rm -f '$remote_env' && sudo bash ~/rewatch-src/tools/node-install.sh $role"; then
    ssh "${SSH_OPTS[@]}" "$host" "rm -f '$remote_env'" || true
    return 1
  fi
  c_g "   ✓ $role up"; echo
}

FAIL=0
deploy core     "$IP_CORE"     || FAIL=1
deploy sentinel "$IP_SENTINEL" || FAIL=1
deploy herald   "$IP_HERALD"   || FAIL=1

echo; hr
if [[ "$FAIL" == 0 ]]; then c_g "  All three nodes are up."; else c_y "  Finished with some nodes skipped — see above."; fi
echo
echo "  Next:"
echo "   1. Open   $DASH_URL"
echo "   2. Register your passkey. On the Pi 4, get a code with:"
echo "        ssh $SSH_USER@$IP_CORE 'cd /opt/rewatch/pi4-core && sudo -u rewatch env REWATCH_DATA_DIR=/var/lib/rewatch /opt/rewatch/venv/bin/python -m server.enroll'"
echo "      then type it into \"First time? Register this device\"."
echo "   3. Click \"Send test e-mail\" to confirm the alert path."
hr; echo
exit "$FAIL"
