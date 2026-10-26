"""Public Black Hat labels must not rename the workspace's wire contracts."""

from pathlib import Path
import sys
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "demo"))
import demo_server  # noqa: E402


def test_black_hat_workspace_labels():
    index = (ROOT / "demo/web/index.html").read_text()
    live = (ROOT / "demo/web/assets/live.js").read_text()
    assert "Black Hat workspace" in index
    assert "Local recording demo" not in index
    assert "Nothing leaves this machine" not in index
    assert "ReWatch(Iot) · BLACK HAT" in live
    assert "AC rig · start/stop" in index
    assert "Black Hat (generated)" in live
    assert 'send({ op: "firmware-demo" })' in live


def test_black_hat_snapshot_preserves_legacy_contract():
    with patch.object(demo_server.rw, "env_float", side_effect=lambda key, default: default):
        sim = demo_server.Sim({"broadcast": lambda frame: None}, False)
    snapshot = sim.snapshot()
    assert snapshot["simulation"] is True
    assert snapshot["version"] == "demo"
    assert "demo_elapsed" in snapshot


def test_workspace_manual_matches_shared_manual():
    assert (ROOT / "demo/web/manual.html").read_bytes() == (
        ROOT / "pi4-core/web/manual.html"
    ).read_bytes()
