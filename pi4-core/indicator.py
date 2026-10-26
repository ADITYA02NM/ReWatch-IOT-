#!/usr/bin/env python3
"""ReWatch(Iot) indicator bridge — Pi 4 USB -> ESP32-C3 mini (NeoPixel + OLED).

Reads the retained `rewatch/threat/state` and writes one JSON line per 100 ms
down the USB serial link (115200 baud):

  {"score":72,"band":"RED","open":1,"cd":94,"msg":"Room 1 AC 35.0 C","nodes":"1111"}

  band   GREEN | BLUE | YELLOW | RED | PURPLE  (the board picks colour + motion)
  cd     seconds left on the acknowledge countdown (-1 when none)
  nodes  core, sentinel, herald, rig — 1 = heart-beating

The board shows a sleeping face and turns blue if this line stops.
"""

from __future__ import annotations

import glob
import json
import signal
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "common"))
import rewatch as rw  # noqa: E402

LOG = rw.setup_logging("rewatch.indicator")
NODE_ORDER = ("core", "sentinel", "herald", "rig")


def find_port() -> str | None:
    want = rw.env("INDICATOR_PORT", "")
    if want:
        return want
    for pat in ("/dev/serial/by-id/*Espressif*", "/dev/serial/by-id/*CP210*",
                "/dev/serial/by-id/*CH34*", "/dev/ttyACM*", "/dev/ttyUSB*"):
        hits = sorted(glob.glob(pat))
        if hits:
            return hits[0]
    return None


def main() -> None:
    rw.load_env()
    import serial  # pyserial

    state: dict = {}
    health: dict[str, dict] = {}
    lock = threading.Lock()
    link = {"port": None, "open": False}

    def on_msg(t, d):
        if not isinstance(d, dict):
            return
        with lock:
            if t == rw.topic("threat", "state"):
                state.clear()
                state.update(d)
            elif t.startswith(rw.topic("health")):
                health[t.split("/")[-1]] = {**d, "rx": time.time()}

    bus = rw.Bus("indicator", subscriptions=[rw.topic("threat", "state"), rw.topic("health", "+")],
                 on_message=on_msg,
                 heartbeat_info=lambda: {"role": "neopixel + oled", "serial": link["port"],
                                         "link": link["open"]})
    stop = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    signal.signal(signal.SIGINT, lambda *_: stop.set())

    ser = None
    while not stop.is_set():
        if ser is None:
            port = find_port()
            link["port"] = port
            if not port:
                stop.wait(3)
                continue
            try:
                ser = serial.Serial(port, 115200, timeout=0.1)
                link["open"] = True
                LOG.info("indicator on %s", port)
            except (OSError, serial.SerialException) as e:
                LOG.warning("open %s failed: %s", port, e)
                stop.wait(3)
                continue
        with lock:
            s = dict(state)
            h = dict(health)
        now = time.time()
        fresh = s and now - float(s.get("ts", 0)) < 5
        inc = s.get("incident") or {}
        nodes = "".join("1" if (h.get(n, {}).get("online") and now - h[n]["rx"] < rw.NODE_TIMEOUT_S)
                        else "0" for n in NODE_ORDER)
        frame = {
            "score": int(round(s.get("score", 0))) if fresh else 0,
            "band": s.get("band", "BLUE") if fresh else "BLUE",
            "open": 1 if inc and inc.get("state") == "open" else 0,
            "cd": int(inc.get("remaining", -1)) if inc and inc.get("state") == "open" else -1,
            "msg": (s.get("reason") or "")[:40] if fresh else "engine silent",
            "nodes": nodes,
        }
        try:
            ser.write((json.dumps(frame, separators=(",", ":")) + "\n").encode())
        except (OSError, serial.SerialException) as e:
            LOG.warning("serial lost: %s", e)
            link["open"] = False
            try:
                ser.close()
            except Exception:  # noqa: BLE001
                pass
            ser = None
        stop.wait(0.1)
    bus.stop()


if __name__ == "__main__":
    main()
