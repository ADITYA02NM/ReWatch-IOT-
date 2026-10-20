"""Sentinel detector unit tests — scan detection and AC anomaly logic."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "common"))
sys.path.insert(0, str(ROOT / "pi3-sentinel"))
import rewatch as rw  # noqa: E402
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
