#!/usr/bin/env python3
"""ReWatch(Iot) verifier — Pi 4 + TP-Link AC600 (USB Wi-Fi) joined to the IoT Wi-Fi.

The Pi 4 does not trust the bus alone. Every IoT device reports over MQTT, but
the Pi 4 also has its own radio on the same Wi-Fi, so it asks each device
directly — `GET http://<device-ip>/status`, sent *out of the AC600 interface*
(source-bound to its address) — and compares the two readings.

* agreement within VERIFY_TOLERANCE_C            -> verify/<device> {"ok": true}
* disagreement 3 polls in a row                  -> verify/<device> {"ok": false, "alarm": true}
  (the engine turns that into an "integrity" impulse: someone is lying on the bus)
* device unreachable over Wi-Fi                  -> verify/<device> {"ok": null, "reachable": false}
"""

from __future__ import annotations

import http.client
import json
import signal
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "common"))
import rewatch as rw  # noqa: E402

LOG = rw.setup_logging("rewatch.verifier")


def poll(ip: str, src_ip: str | None, timeout: float = 2.0) -> dict | None:
    try:
        conn = http.client.HTTPConnection(ip, 80, timeout=timeout,
                                          source_address=(src_ip, 0) if src_ip else None)
        conn.request("GET", "/status")
        r = conn.getresponse()
        if r.status != 200:
            return None
        return json.loads(r.read(4096).decode())
    except (OSError, ValueError, http.client.HTTPException):
        return None


def main() -> None:
    rw.load_env()
    iface = rw.env("VERIFY_IFACE", "wlan1")
    tol = rw.env_float("VERIFY_TOLERANCE_C", 1.5)
    period = rw.env_float("VERIFY_PERIOD_S", 3.0)
    latest: dict[str, dict] = {}
    strikes: dict[str, int] = {}
    lock = threading.Lock()

    def on_msg(t, d):
        if isinstance(d, dict) and t.endswith("/telemetry"):
            with lock:
                latest[t.split("/")[2]] = {**d, "rx": time.time()}

    stats = {"polls": 0, "mismatches": 0}
    bus = rw.Bus("verifier", subscriptions=[rw.topic("iot", "+", "telemetry")], on_message=on_msg,
                 heartbeat_info=lambda: {"role": "wifi cross-check", "iface": iface,
                                         "iface_ip": rw.iface_ip(iface), **stats})
    stop = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    signal.signal(signal.SIGINT, lambda *_: stop.set())
    LOG.info("verifier up on %s (tolerance %.1f °C)", iface, tol)

    while not stop.wait(period):
        src = rw.iface_ip(iface)
        with lock:
            snap = dict(latest)
        for dev, tel in snap.items():
            ip = tel.get("ip")
            if not ip or time.time() - tel["rx"] > 15:
                continue
            got = poll(ip, src)
            stats["polls"] += 1
            if got is None:
                bus.publish(rw.topic("verify", dev), {"device": dev, "ok": None,
                                                      "reachable": False, "via": iface,
                                                      "ts": rw.now()})
                continue
            # one device board may serve several rooms: pick this device's entry
            entry = got
            if isinstance(got.get("devices"), list):
                entry = next((x for x in got["devices"] if x.get("device") == dev), {})
            try:
                wifi_t = float(entry.get("temp_c"))
                bus_t = float(tel.get("temp_c"))
            except (TypeError, ValueError):
                continue
            delta = abs(wifi_t - bus_t)
            ok = delta <= tol
            strikes[dev] = 0 if ok else strikes.get(dev, 0) + 1
            alarm = strikes[dev] == 3
            if alarm:
                stats["mismatches"] += 1
                LOG.warning("%s mismatch: bus %.1f vs wifi %.1f", dev, bus_t, wifi_t)
            bus.publish(rw.topic("verify", dev), {
                "device": dev, "ok": ok, "reachable": True, "mqtt_temp": bus_t,
                "wifi_temp": wifi_t, "delta": round(delta, 2), "alarm": alarm, "via": iface,
                "rssi": got.get("rssi"), "ts": rw.now()})
    bus.stop()


if __name__ == "__main__":
    main()
