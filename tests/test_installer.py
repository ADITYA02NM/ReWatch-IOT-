from pathlib import Path
import os
import subprocess
import unittest
import tempfile

ROOT = Path(__file__).resolve().parents[1]


class InstallerSafetyTests(unittest.TestCase):
    def run_installer(self, *args, input_text="\n", **overrides):
        env = dict(os.environ, SSH_USER="pi", IP_CORE="192.168.100.1",
                   IP_SENTINEL="192.168.100.2", IP_HERALD="192.168.100.3",
                   SMTP_HOST="smtp.example.org", SMTP_PORT="587", SMTP_USER="demo@example.org",
                   SMTP_PASS="dummy-not-a-real-password", ALERT_TO="owner@example.org",
                   REWATCH_HOSTNAME="rewatch.local", REWATCH_ACCESS_CODE="demo-code")
        env.update(overrides)
        return subprocess.run(["bash", str(ROOT / "start.sh"), *args], env=env,
                              input=input_text, text=True, capture_output=True, timeout=10)

    def test_dry_run_has_no_credentials_or_ssh(self):
        result = self.run_installer("--dry-run")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("--dry-run: stopping here", result.stdout)
        self.assertNotIn("dummy-not-a-real-password", result.stdout + result.stderr)
        self.assertNotIn("checking SSH", result.stdout)

    def test_default_confirmation_is_no(self):
        result = self.run_installer()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("aborted", result.stdout)
        self.assertNotIn("checking SSH", result.stdout)

    def test_unsafe_inputs_rejected_before_network(self):
        for values in ({"IP_CORE": "999.1.2.3"}, {"SSH_USER": "pi;touch /tmp/no"},
                       {"SMTP_PORT": "70000"}, {"SMTP_PASS": "bad\nINJECTED=1"}):
            result = self.run_installer("--dry-run", **values)
            self.assertNotEqual(result.returncode, 0, values)
            self.assertNotIn("checking SSH", result.stdout)

    def test_missing_config_and_unknown_option_are_errors(self):
        for args in (("--config",), ("--unknown",), ("--config", "/missing/rewatch-config")):
            self.assertNotEqual(self.run_installer(*args).returncode, 0)

    def test_config_argument_preserves_following_dry_run(self):
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory) / 'trusted.env'
            config.write_text('IP_CORE=192.0.2.10\n')
            result = self.run_installer('--config', str(config), '--dry-run')
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('192.0.2.10', result.stdout)
            self.assertNotIn('checking SSH', result.stdout)

    def test_failed_remote_directory_stops_copy_and_reports_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            stub = Path(directory)
            (stub / 'ssh').write_text('#!/bin/sh\ncase "$*" in *" true") exit 0;; *) exit 1;; esac\n')
            (stub / 'rsync').write_text('#!/bin/sh\necho UNSAFE_COPY_AFTER_FAILURE\nexit 1\n')
            for program in stub.iterdir():
                program.chmod(0o700)
            result = self.run_installer(input_text='yes\n', PATH=f'{directory}:{os.environ["PATH"]}')
            self.assertNotEqual(result.returncode, 0)
            self.assertNotIn('UNSAFE_COPY_AFTER_FAILURE', result.stdout)
