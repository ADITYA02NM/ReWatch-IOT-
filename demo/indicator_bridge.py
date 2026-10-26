#!/usr/bin/env python3
"""Mirror the local demo onto an optional USB C3; never computes risk itself."""
import argparse
import json
import os
from pathlib import Path
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.request import HTTPCookieProcessor, Request, build_opener

import serial

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "common"))
import rewatch as rw  # noqa: E402


def make_frame(snapshot: dict) -> dict:
    state = snapshot.get("state") or {}
    incident = state.get("incident") or {}
    opened = incident.get("state") == "open"
    nodes = snapshot.get("nodes") or {}
    return {"score": round(state.get("score", 0)), "band": state.get("band", "GREEN"),
            "open": int(opened), "cd": int(incident.get("remaining", -1)) if opened else -1,
            "msg": (state.get("reason") or "BLACK HAT: discovering ACs")[:40],
            "nodes": "".join("1" if nodes.get(n, {}).get("online") else "0"
                             for n in ("core", "sentinel", "herald", "rig"))}


def main():
    rw.load_env(Path(__file__).with_name(".env"))
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", required=True, help="USB serial port, e.g. /dev/ttyUSB0")
    parser.add_argument("--http-port", type=int, default=int(os.environ.get("DEMO_PORT", "8080")))
    args = parser.parse_args()
    base = f"http://localhost:{args.http_port}"
    opener = build_opener(HTTPCookieProcessor())
    login = Request(base + "/auth/demo", data=json.dumps({"code": os.environ.get("DEMO_CODE", "rewatch")}).encode(),
                    headers={"Content-Type": "application/json"})
    with opener.open(login, timeout=5) as response:
        response.read()
    with serial.Serial(args.port, 115200, timeout=0.1, write_timeout=1) as link:
        link.dtr = False
        link.rts = False
        print(f"Black Hat → C3 on {args.port}; Ctrl+C stops mirroring.", flush=True)
        while True:
            try:
                with opener.open(base + "/api/state", timeout=2) as response:
                    frame = make_frame(json.load(response))
            except (HTTPError, URLError, TimeoutError):
                frame = {"score": 0, "band": "BLUE", "open": 0, "cd": -1,
                         "msg": "Black Hat server unavailable", "nodes": "0000"}
            link.write((json.dumps(frame, separators=(",", ":")) + "\n").encode())
            time.sleep(0.2)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
