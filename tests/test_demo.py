"""Demo simulation contracts, without an HTTP server or aiohttp test fixtures.

Run with: python -m unittest discover -s tests -p test_demo.py -v
"""

import ast
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "demo"))
import demo_server  # noqa: E402


class DemoSimulationTests(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(os.environ)
        self.env.start()
        self.addCleanup(self.env.stop)
        for key in ("DEMO_ACK_TIMEOUT_S", "DEMO_AUTO_SPIKE", "DEMO_AUTO_SPIKE_S"):
            os.environ.pop(key, None)
        noise = patch.object(demo_server.random, "uniform", return_value=0.0)
        noise.start()
        self.addCleanup(noise.stop)
        self.frames = []
        self.sim = demo_server.Sim({"broadcast": self.frames.append}, False)

    def replay(self, now=100.0):
        self.sim.replay(now)

    def open_incident(self):
        """Drive the real detector and engine rather than fabricating an incident."""
        self.replay()
        self.sim.rig("ac-spike")
        for step in range(120):
            now = 100.0 + step * 0.5
            self.sim.tick(now)
            if self.sim.eng.incident is not None:
                self.assertEqual(self.sim.eng.incident.state, "open")
                return self.sim.eng.incident, now
        self.fail("Room 1 AC spike never opened a RED incident")

    def test_demo_ack_timeout_defaults_to_twenty_seconds(self):
        self.assertEqual(self.sim.eng.ack_timeout, 20)

    def test_discovery_starts_at_twenty_seconds_not_before(self):
        self.replay()
        self.assertEqual(self.sim.telemetry, {})
        self.sim.tick(119.9)
        self.assertEqual(self.sim.telemetry, {})
        self.sim.tick(120.0)
        self.assertTrue(set(demo_server.ROOMS) <= set(self.sim.telemetry))
        self.assertEqual({t['kind'] for t in self.sim.telemetry.values()},
                         {'ac', 'camera', 'door', 'plug', 'light', 'fan', 'sensor'})

    def test_automatic_spike_defaults_on_and_starts_at_thirty_seconds(self):
        self.replay()
        self.sim.tick(120.0)
        self.sim.tick(129.9)
        self.assertFalse(self.sim.rooms["room1-ac"]["spiked"])
        self.assertEqual(self.sim.rooms["room1-ac"]["target"], 20)
        self.sim.tick(130.0)
        self.assertTrue(self.sim.rooms["room1-ac"]["spiked"])
        self.assertEqual(self.sim.rooms["room1-ac"]["target"], 35)
        for device in ("room2-ac", "room3-ac", "room4-ac"):
            self.assertFalse(self.sim.rooms[device]["spiked"])

    def test_automatic_spike_can_be_disabled(self):
        os.environ["DEMO_AUTO_SPIKE"] = "0"
        self.sim = demo_server.Sim({"broadcast": self.frames.append}, False)
        self.replay()
        for now in (120.0, 129.9, 130.0, 150.0):
            self.sim.tick(now)
        self.assertFalse(self.sim.rooms["room1-ac"]["spiked"])
        self.assertEqual(self.sim.rooms["room1-ac"]["target"], 20)
        self.assertIsNone(self.sim.eng.incident)

    def test_manual_spike_bypasses_discovery(self):
        self.replay()
        self.sim.rig("ac-spike")
        self.sim.tick(100.0)
        self.assertTrue(self.sim.rooms["room1-ac"]["spiked"])
        self.assertEqual(self.sim.rooms["room1-ac"]["target"], 35)
        self.assertIn("room1-ac", self.sim.telemetry)
        self.assertEqual(self.sim.telemetry["room1-ac"]["power"], "fault")

    def test_unacknowledged_red_automates_at_twenty_seconds(self):
        incident, red_at = self.open_incident()
        self.assertEqual(incident.deadline, red_at + 20)
        self.sim.tick(red_at + 19.9)
        self.assertEqual(incident.state, "open")
        self.assertEqual(self.sim.rooms["room1-ac"]["target"], 35)
        self.sim.tick(red_at + 20)
        self.assertEqual(incident.state, "auto")
        self.assertIsNotNone(incident.action)
        self.assertEqual(self.sim.rooms["room1-ac"]["target"], 20)

    def test_acknowledgement_prevents_automatic_response(self):
        incident, red_at = self.open_incident()
        with patch.object(demo_server.time, "time", return_value=red_at + 1):
            self.sim.ack(incident.id)
        for now in (red_at + 20, red_at + 21):
            self.sim.tick(now)
        self.assertEqual(incident.state, "acked")
        self.assertIsNone(incident.action)
        self.assertEqual(self.sim.rooms["room1-ac"]["target"], 35)

    def test_snapshot_explicitly_identifies_simulation_without_mqtt(self):
        snapshot = self.sim.snapshot()
        self.assertIs(snapshot.get("simulation"), True)
        self.assertIs(snapshot["mqtt"], False)

    def test_replay_clears_prior_run_and_restarts_discovery_clock(self):
        incident, red_at = self.open_incident()
        self.sim.tick(red_at + 20)
        self.sim.toggle_briefing()
        self.assertTrue(self.sim.telemetry)
        self.assertTrue(self.sim.recent)
        self.assertTrue(self.sim.history)
        self.assertTrue(self.sim.briefing)
        self.assertIsNotNone(incident.action)

        self.replay(200.0)
        snapshot = self.sim.snapshot()
        self.assertEqual(snapshot["telemetry"], {})
        self.assertEqual(snapshot["verify"], {})
        self.assertEqual(snapshot["events"], [])
        self.assertEqual(snapshot["history"], [])
        self.assertFalse(self.sim.briefing)
        self.assertIsNone(self.sim.eng.incident)
        self.assertEqual(self.sim.eng.recent, [])
        self.assertEqual(self.sim.eng.conditions, {})
        self.assertEqual(self.sim.eng.impulses, [])
        self.assertEqual(self.sim.eng.devices, {})
        for room in self.sim.rooms.values():
            self.assertEqual(room["target"], 20)
            self.assertEqual(room["setpoint"], 20)
            self.assertFalse(room["spiked"])
        self.sim.tick(219.9)
        self.assertEqual(self.sim.telemetry, {})
        self.sim.tick(220.0)
        self.assertEqual(len(self.sim.telemetry), 10)
        self.sim.tick(229.9)
        self.assertFalse(self.sim.rooms["room1-ac"]["spiked"])
        self.sim.tick(230.0)
        self.assertTrue(self.sim.rooms["room1-ac"]["spiked"])

    def test_mail_preview_does_not_claim_delivery(self):
        self.sim._mail("alert", {"id": "preview", "title": "AC spike"})
        mails = [frame["e"] for frame in self.frames
                 if frame.get("t") == "event" and frame["e"]["kind"] == "mail"]
        self.assertTrue(mails)
        self.assertNotIn("sent", mails[-1]["title"].lower())
        self.assertIn("preview", mails[-1]["title"].lower())

    def test_capability_command_changes_only_simulated_device(self):
        self.replay()
        self.sim.tick(120)
        command = self.sim.policy.command('lobby-plug', 'power', False)
        self.sim._on_engine('rewatch/iot/lobby-plug/cmd', command)
        self.sim.tick(121)
        self.assertIs(self.sim.telemetry['lobby-plug']['power'], False)
        self.assertTrue(any('SIMULATED' in e['title'] for e in self.sim.recent))

    def test_summary_every_five_minutes_survives_replay(self):
        from summary import ReportWindow
        self.sim.app['summary'] = ReportWindow(start=100)
        self.replay(100)
        self.sim.tick(399)
        self.assertFalse(any(e['kind'] == 'summary' for e in self.sim.recent))
        window = self.sim.app['summary']
        self.replay(399)
        self.sim.tick(400)
        self.assertIs(self.sim.app['summary'], window)
        self.assertEqual(len([e for e in self.sim.recent if e['kind'] == 'summary']), 1)
        self.assertTrue(any('5-minute' in e['title'] for e in self.sim.recent if e['kind'] == 'mail'))

    def test_demo_network_response_never_invokes_firewall_even_if_enabled(self):
        os.environ['RESPONDER_NFT'] = '1'
        self.replay(100)
        event = demo_server.rw.make_event('flood', 'critical', 'Synthetic flood', src='192.0.2.10')
        self.sim.eng.on_message('rewatch/detect/flood', event, 100)
        self.sim.tick(100)
        incident = self.sim.eng.incident
        self.assertIsNotNone(incident)
        with patch.object(demo_server.engmod, 'nft_block', return_value=True) as firewall:
            self.assertTrue(self.sim.eng.respond(incident.id, 101, manual=True))
        firewall.assert_not_called()
        self.assertFalse(incident.action['applied'])

    def test_summary_counts_each_generated_detection_once(self):
        from summary import ReportWindow
        self.sim.app['summary'] = ReportWindow(start=100)
        self.replay(100)
        self.sim.tick(120)  # Initial normal conditions are not detections.
        self.sim._random_event(121)
        self.sim.firmware_demo()
        self.sim.tick(122)
        self.sim.tick(400)
        report = self.sim.app['last_summary']
        # One synthetic scan/discovery event and one firmware-version change.
        self.assertEqual(report['detections'], 2)

    def test_mail_result_only_reports_success_for_ok_true(self):
        for result in (
            {"ok": True, "to": ["owner@example.com"], "subject": "AC spike"},
            {"ok": False, "error": "SMTP unavailable"},
            {"error": "No delivery result"},
            {"ok": None, "error": "Not attempted"},
        ):
            with self.subTest(result=result):
                self.frames.clear()
                self.sim.apply_mail_result(result)
                mails = [frame["e"] for frame in self.frames
                         if frame.get("t") == "event" and frame["e"]["kind"] == "mail"]
                self.assertEqual(len(mails), 1)
                title = mails[0]["title"].lower()
                if result.get("ok") is True:
                    self.assertIn("sent", title)
                    self.assertNotIn("failed", title)
                else:
                    self.assertIn("failed", title)
                    self.assertNotIn("sent", title)


class ProductionDefaultsTests(unittest.TestCase):
    def test_production_ack_timeout_remains_two_minutes(self):
        # Inspect the production source, avoiding the cached demo `engine` module.
        tree = ast.parse((ROOT / "pi4-core" / "engine.py").read_text())
        engine = next(node for node in tree.body
                      if isinstance(node, ast.ClassDef) and node.name == "ThreatEngine")
        constructor = next(node for node in engine.body
                           if isinstance(node, ast.FunctionDef) and node.name == "__init__")
        defaults = dict(zip((arg.arg for arg in constructor.args.kwonlyargs),
                            constructor.args.kw_defaults))
        self.assertEqual(ast.literal_eval(defaults["ack_timeout"]), 120)


if __name__ == "__main__":
    unittest.main()
