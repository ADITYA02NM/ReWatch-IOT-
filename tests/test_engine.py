"""Threat-engine unit tests — the scoring, bands and incident lifecycle.
Run: pytest -q  (from the repo root)."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "common"))
sys.path.insert(0, str(ROOT / "pi4-core"))
import rewatch as rw            # noqa: E402
from engine import ThreatEngine  # noqa: E402


def anomaly(dev, level, temp, room="Room 1", setpoint=20):
    return {"device": dev, "level": level, "reason": f"{temp} C", "temp_c": temp,
            "setpoint": setpoint, "room": room, "active": level != "ok", "changed": True}


def test_green_when_idle():
    eng = ThreatEngine()
    st = eng.tick(now=0)
    assert st["band"] == rw.GREEN
    assert st["score"] == 0


def test_portscan_impulse_decays():
    eng = ThreatEngine(half_life=60)
    eng.on_message(rw.topic("detect", "portscan"),
                   rw.make_event("portscan", "high", "scan", src="10.0.0.9"), now=0)
    s0 = eng.tick(now=0)["score"]
    assert s0 >= 30 and eng.band == rw.YELLOW
    # after two half-lives it should be a quarter and back to green
    eng.tick(now=120)
    assert eng.score < s0 / 3
    assert eng.band == rw.GREEN


def test_critical_opens_incident_then_auto_responds():
    eng = ThreatEngine(ack_timeout=5, purple_hold=5, resolve_hold=2)
    # device goes critical -> condition 90 -> RED
    eng.on_message(rw.topic("iot", "room1-ac", "telemetry"),
                   {"device": "room1-ac", "room": "Room 1", "temp_c": 35, "setpoint": 20}, now=0)
    eng.on_message(rw.topic("detect", "anomaly", "room1-ac"),
                   anomaly("room1-ac", "critical", 35), now=0)
    st = eng.tick(now=0)
    assert st["band"] == rw.RED
    assert st["incident"] and st["incident"]["state"] == "open"
    # an alert was queued for Herald
    assert any(t.startswith(rw.topic("alert")) for t, _, _ in eng.out)
    eng.out.clear()
    # nobody acks; past the deadline -> PURPLE + a setpoint command back to 20
    eng.tick(now=6)
    assert eng.band == rw.PURPLE
    cmds = [p for t, p, _ in eng.out if t == rw.topic("iot", "room1-ac", "cmd")]
    assert cmds and cmds[0]["setpoint"] == 20


def test_acknowledge_cancels_auto():
    eng = ThreatEngine(ack_timeout=5)
    eng.on_message(rw.topic("detect", "anomaly", "room1-ac"),
                   anomaly("room1-ac", "critical", 35), now=0)
    eng.tick(now=0)
    inc = eng.incident
    assert eng.ack(inc.id, "owner", now=1) is True
    eng.tick(now=1)
    assert eng.incident.state == "acked"
    # past the old deadline the engine must NOT auto-respond
    eng.tick(now=7)
    assert eng.incident.action is None


def test_offline_required_node_is_blue():
    eng = ThreatEngine()
    eng.started = -1000  # pretend we've been up a while
    st = eng.tick(now=0)
    assert st["band"] == rw.BLUE
    assert "sentinel" in st["offline"] and "herald" in st["offline"]
    # once they report, green
    eng.on_message(rw.topic("health", "sentinel"), {"node": "sentinel", "online": True}, now=0)
    eng.on_message(rw.topic("health", "herald"), {"node": "herald", "online": True}, now=0)
    assert eng.tick(now=0)["band"] == rw.GREEN


def test_integrity_mismatch_scores():
    eng = ThreatEngine()
    eng.on_message(rw.topic("verify", "room1-ac"),
                   {"device": "room1-ac", "ok": False, "alarm": True,
                    "mqtt_temp": 20, "wifi_temp": 35}, now=0)
    st = eng.tick(now=0)
    assert st["score"] >= 30
