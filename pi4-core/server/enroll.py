"""ReWatch passkey enrolment helper (run on the Pi 4).

  sudo /opt/rewatch/venv/bin/python -m server.enroll            # one-time code, 10 min
  sudo /opt/rewatch/venv/bin/python -m server.enroll --list     # registered passkeys
  sudo /opt/rewatch/venv/bin/python -m server.enroll --reset    # forget every passkey

The code is typed into "First time? Register this device" on the lock screen.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "common"))
import rewatch as rw  # noqa: E402

from .auth_db import AuthDB  # noqa: E402


def main() -> None:
    rw.load_env()
    ap = argparse.ArgumentParser()
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--reset", action="store_true")
    ap.add_argument("--ttl", type=int, default=600)
    a = ap.parse_args()
    db = AuthDB(Path(rw.env("REWATCH_DATA_DIR", "/var/lib/rewatch")) / "auth.db")
    if a.list:
        for c in db.list_credentials():
            print(f"{c.id[:16]}…  revoked={c.revoked}")
        return
    if a.reset:
        db.reset_owner()
        print("all passkeys removed — register again with a new code")
    tok = db.create_enrollment_token(ttl=a.ttl)
    print(tok)
    try:
        os.chmod(db.path, 0o600)
    except OSError:
        pass


if __name__ == "__main__":
    main()
