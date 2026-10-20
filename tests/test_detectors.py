"""Sentinel detector unit tests — scan detection and AC anomaly logic."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "common"))
sys.path.insert(0, str(ROOT / "pi3-sentinel"))
from detector import ScanDetector, ScanConfig, AnomalyDetector, AcProfile, DeviceRegistry  # noqa: E402


def test_tcp_portscan_detected():
    d = ScanDetector(ScanConfig(tcp_ports=12, cooldown_s=0))
    evs = []
    for port in range(1, 20):
        evs += d.feed("tcp-syn", "10.0.0.5", "10.0.0.1", port, t=1.0)
    kinds = [e["kind"] for e in evs]
    assert "portscan" in kinds


def test_own_ip_ignored():
    d = ScanDetector(ScanConfig(tcp_ports=5, cooldown_s=0), ignore={"10.0.0.5"})
    evs = []
    for port in range(1, 20):
        evs += d.feed("tcp-syn", "10.0.0.5", "10.0.0.1", port, t=1.0)
    assert not evs


def test_arp_sweep_detected():
    d = ScanDetector(ScanConfig(arp_targets=12, cooldown_s=0))
    evs = []
    for i in range(1, 20):
        evs += d.feed("arp-req", "10.0.0.5", f"10.0.0.{i}", t=1.0)
    assert any(e["kind"] == "arpsweep" for e in evs)


def test_ac_critical_requires_hold():
    a = AnomalyDetector(AcProfile(crit_hold_s=2))
    # one spike sample -> not critical yet (warn)
    c = a.feed({"device": "room1-ac", "temp_c": 35, "setpoint": 20, "room": "Room 1"}, t=0)
    assert c["level"] in ("warn", "ok")
    # still hot 2.5 s later -> critical
    c = a.feed({"device": "room1-ac", "temp_c": 35, "setpoint": 20, "room": "Room 1"}, t=2.5)
    assert c and c["level"] == "critical"


def test_ac_normal_is_ok():
    a = AnomalyDetector()
    c = a.feed({"device": "room2-ac", "temp_c": 20, "setpoint": 20}, t=0)
    assert c["level"] == "ok"


def test_new_device_after_learning(tmp_path):
    reg = DeviceRegistry(tmp_path / "known.json", learn_s=0)
    reg.learn_until = 0  # learning window already closed
    ev = reg.see("aa:bb:cc:dd:ee:ff", "10.0.0.50")
    assert ev and ev["kind"] == "newdevice"
    # second sighting is silent
    assert reg.see("aa:bb:cc:dd:ee:ff", "10.0.0.50") is None


def test_non_nmap_stealth_probe_and_slow_scan():
    for proto in ("tcp-fin", "tcp-null", "tcp-xmas"):
        detector = ScanDetector(ScanConfig(cooldown_s=0))
        events = []
        for port in range(20):
            events += detector.feed(proto, "10.0.0.8", "10.0.0.1", port, t=100)
        assert any(e["kind"] == "portscan" for e in events)
        assert all("tool_hint" not in e["detail"] for e in events)
    detector = ScanDetector(ScanConfig(cooldown_s=0))
    events = []
    for port in range(40):
        events += detector.feed("tcp-syn", "10.0.0.8", "10.0.0.1", port, t=100 + port * 5)
    assert any(e["kind"] == "slow-scan" for e in events)


def test_non_ac_profiles_and_invalid_numeric_input():
    detector = AnomalyDetector()
    for device, kind, field in [("cam", "camera", "tamper"), ("lock", "door", "forced_open"),
                                ("smoke", "sensor", "smoke")]:
        condition = detector.feed({"device": device, "kind": kind, field: True}, t=100)
        assert condition["level"] == "critical"
        assert detector.feed({"device": device, "kind": kind, field: False}, t=101)["level"] == "ok"
    assert detector.feed({"device": "plug", "kind": "plug", "power_w": 3000}, t=100)["level"] == "critical"
    assert detector.feed({"device": "ac", "temp_c": float("nan")}, t=100) is None
