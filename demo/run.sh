#!/usr/bin/env bash
# Local Black Hat workspace. No SSH, MQTT broker, root, or hardware required.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(dirname "$HERE")"
if [[ ! -x "$ROOT/.venv/bin/python" ]]; then
  echo "Creating local Python environment…"
  python3 -m venv "$ROOT/.venv"
fi
if ! "$ROOT/.venv/bin/python" -c 'import aiohttp, webauthn' 2>/dev/null; then
  "$ROOT/.venv/bin/python" -m pip install -r "$HERE/requirements.txt"
fi
exec "$ROOT/.venv/bin/python" "$HERE/demo_server.py" "$@"
