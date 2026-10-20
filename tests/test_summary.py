import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "common"))
from summary import ReportWindow  # noqa: E402


def test_summary_every_five_minutes_includes_window_and_no_duplicates():
    window = ReportWindow(start=100)
    window.observe("rewatch/threat/state", {"band": "RED", "score": 90,
                   "devices": {"camera": {}}, "incident": {"state": "open"}}, 101)
    window.observe("rewatch/health/sentinel", {"online": True}, 399)
    window.observe("rewatch/detect/portscan", {"kind": "portscan"}, 102)
    window.observe("rewatch/action/a", {"summary": "requested"}, 103)
    assert window.poll(399) is None
    window.observe("rewatch/threat/state", window.state, 399)
    report = window.poll(400)
    assert report["kind"] == "summary"
    assert report["peak"] == 90
    assert report["devices"] == 1
    assert report["detections"] == 1
    assert report["responses"] == 1
    assert report["band"] == "RED"
    assert window.poll(400) is None
    next_report = window.poll(700)
    assert next_report["detections"] == 0
    assert next_report["responses"] == 0
    assert "sentinel" in next_report["offline"]


def test_no_telemetry_is_not_claimed_healthy():
    report = ReportWindow(start=0).poll(300)
    assert report["band"] == "UNKNOWN"
    assert report["state_received"] is False


def test_mail_summary_is_not_test_message():
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "pi3-herald"))
    from mailer import compose
    report = ReportWindow(start=0).poll(300)
    subject, text, _ = compose("summary", report, "http://localhost:8080")
    assert "5-minute" in subject
    assert "Detections" in text
    assert "reports.html" in text
