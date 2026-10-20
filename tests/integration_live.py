"""Live end-to-end check against a real mosquitto broker.

Starts the engine + dashboard, plays the Room-1 20->35 scenario through the real
anomaly detector, asserts the incident opens (RED), auto-responds (PURPLE) and
publishes the setpoint command, then checks the dashboard API returns it all.

Run:  python tests/integration_live.py   (needs mosquitto on :1883)
"""
import json
import os
import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "common"))
sys.path.insert(0, str(ROOT / "pi4-core"))
os.environ.setdefault("REWATCH_MQTT_HOST", "127.0.0.1")
os.environ["ACK_TIMEOUT_S"] = "4"
os.environ["PURPLE_HOLD_S"] = "4"
os.environ["REWATCH_PORT"] = "8099"
os.environ["REWATCH_DATA_DIR"] = "/tmp/rewatch-itest"
os.environ["REWATCH_ACCESS_CODE"] = "1234"

import rewatch as rw  # noqa: E402

PASS, FAIL = [], []


def check(name, ok):
    (PASS if ok else FAIL).append(name)
    print(("  PASS " if ok else "  FAIL ") + name)


def main():
    import paho.mqtt.client as mqtt

    # collect everything the engine publishes
    seen = {"alert": [], "cmd": [], "state": [], "action": []}
    sub = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="itest-sub")

    def on_msg(c, u, m):
        try:
            d = json.loads(m.payload.decode())
        except Exception:
            return
        t = m.topic
        if t.startswith("rewatch/alert/"):
            seen["alert"].append(d)
        elif t.endswith("/cmd") and "/iot/" in t:
            seen["cmd"].append(d)
        elif t == "rewatch/threat/state":
            seen["state"].append(d)
        elif t.startswith("rewatch/action/"):
            seen["action"].append(d)

    sub.on_message = on_msg
    sub.connect("127.0.0.1", 1883)
    sub.subscribe("rewatch/#")
    sub.loop_start()

    # a publisher to play the scenario + stand in for the fleet
    pub = rw.Bus("itest-pub")
    time.sleep(0.5)

    # start the engine in-process
    import engine
    eng = engine.ThreatEngine(ack_timeout=4, purple_hold=4, resolve_hold=2)
    stop = threading.Event()
    lock = threading.Lock()
    ebus = rw.Bus("core", subscriptions=["rewatch/detect/#", "rewatch/iot/+/telemetry",
                                         "rewatch/verify/#", "rewatch/health/+",
                                         "rewatch/ack", "rewatch/respond"],
                  on_message=lambda t, d: eng.on_message(t, d),
                  heartbeat_info=lambda: {"band": eng.band})

    def engine_loop():
        while not stop.wait(0.3):
            with lock:
                eng.tick()
                out, eng.out = eng.out, []
            for t, p, r in out:
                ebus.publish(t, p, retain=r)

    threading.Thread(target=engine_loop, daemon=True).start()

    # fleet heartbeats so the band isn't stuck BLUE
    for n in ("sentinel", "herald"):
        pub.publish(rw.topic("health", n), {"node": n, "online": True}, retain=True)

    # the real anomaly detector, driven by telemetry
    sys.path.insert(0, str(ROOT / "pi3-sentinel"))
    from detector import AnomalyDetector
    det = AnomalyDetector()

    def telemetry(temp):
        tel = {"device": "room1-ac", "room": "Room 1", "kind": "ac", "temp_c": temp,
               "setpoint": 20, "ip": "127.0.0.1"}
        pub.publish(rw.topic("iot", "room1-ac", "telemetry"), tel)
        cond = det.feed(tel)
        if cond:
            pub.publish(rw.topic("detect", "anomaly", "room1-ac"), cond)

    # normal for a moment
    for _ in range(4):
        telemetry(20.0)
        time.sleep(0.25)
    check("green while normal", eng.band == rw.GREEN)

    # spike to 35 and hold
    print("  -- spiking Room 1 AC to 35 C --")
    for _ in range(16):
        telemetry(35.0)
        time.sleep(0.25)
    check("RED incident opened", any(a.get("band") == "RED" for a in seen["alert"]))
    check("alert names Room 1", any("Room 1" in (a.get("room", "") + a.get("title", ""))
                                    for a in seen["alert"]))

    # nobody acknowledges -> wait past the 4s deadline
    print("  -- waiting out the acknowledge countdown --")
    time.sleep(6)
    check("PURPLE auto-response", eng.band in (rw.PURPLE,) or any(
        s.get("band") == "PURPLE" for s in seen["state"]))
    check("setpoint command back to 20", any(c.get("setpoint") == 20 for c in seen["cmd"]))

    # rig would then cool it; simulate the device obeying
    print("  -- device returns to 20 C --")
    for _ in range(14):
        telemetry(20.0)
        time.sleep(0.25)
    check("resolves back to green", eng.band == rw.GREEN)

    # ── dashboard API ────────────────────────────────────────────────────────
    srv = subprocess.Popen([sys.executable, "-m", "server.app"],
                           cwd=str(ROOT / "pi4-core"),
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                           env=dict(os.environ))
    time.sleep(2.5)
    try:
        hz = json.loads(urllib.request.urlopen("http://127.0.0.1:8099/healthz", timeout=4).read())
        check("dashboard /healthz ok", hz.get("ok") is True)
        check("dashboard sees mqtt", hz.get("mqtt") is True)
        # sign in with the access code to reach the gated API
        cj = _login("http://127.0.0.1:8099", "1234")
        state = _get("http://127.0.0.1:8099/api/state", cj)
        check("api/state gated+served", isinstance(state, dict) and "events" in state)
        rep = _get("http://127.0.0.1:8099/api/report?hours=1", cj)
        check("report has events", rep.get("events") is not None)
    except Exception as e:  # noqa: BLE001
        check(f"dashboard API ({e})", False)
    finally:
        srv.terminate()

    stop.set()
    time.sleep(0.3)
    pub.stop(); ebus.stop(); sub.loop_stop()
    print(f"\n  {len(PASS)} passed, {len(FAIL)} failed")
    sys.exit(1 if FAIL else 0)


def _login(base, code):
    import http.cookiejar
    cj = http.cookiejar.CookieJar()
    op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))
    req = urllib.request.Request(base + "/auth/demo", data=json.dumps({"code": code}).encode(),
                                 headers={"Content-Type": "application/json"})
    op.open(req, timeout=4)
    globals()["_OP"] = op
    return cj


def _get(url, cj):
    op = globals()["_OP"]
    return json.loads(op.open(url, timeout=4).read())


if __name__ == "__main__":
    main()
