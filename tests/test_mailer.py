import importlib.util
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("herald_mailer", ROOT / "pi3-herald/mailer.py")
mailer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mailer)


class MailComposerTests(unittest.TestCase):
    def test_demo_timeout_is_seconds_not_one_minute(self):
        _, text, _ = mailer.compose("alert", {"ack_timeout": 20}, "http://localhost:8080")
        self.assertIn("20 seconds", text)
        self.assertNotIn("1 minute", text)

    def test_production_timeout_is_two_minutes(self):
        _, text, _ = mailer.compose("alert", {"ack_timeout": 120}, "https://rewatch.local")
        self.assertIn("2 minutes", text)
