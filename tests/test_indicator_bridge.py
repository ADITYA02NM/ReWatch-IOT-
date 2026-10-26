from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "demo"))
from indicator_bridge import make_frame  # noqa: E402


class IndicatorFrameTests(unittest.TestCase):
    def test_mirrors_incident_and_fleet_without_scoring(self):
        frame = make_frame({"state": {"score": 90, "band": "RED", "reason": "Room 1 AC",
                            "incident": {"state": "open", "remaining": 17}},
                            "nodes": {"core": {"online": True}}})
        self.assertEqual(frame["score"], 90)
        self.assertEqual(frame["band"], "RED")
        self.assertEqual(frame["cd"], 17)
        self.assertEqual(frame["nodes"], "1000")

    def test_empty_state_is_explicit_demo_discovery(self):
        frame = make_frame({})
        self.assertEqual(frame["band"], "GREEN")
        self.assertEqual(frame["cd"], -1)
        self.assertIn("BLACK HAT", frame["msg"])
