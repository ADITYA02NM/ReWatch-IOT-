"""Run the shared DOM renderer contract without launching a browser."""

from pathlib import Path
import shutil
import subprocess

import pytest


def test_shared_location_cards():
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node.js is required for the shared renderer contract")
    result = subprocess.run(
        [node, str(Path(__file__).with_name("device_cards.cjs"))],
        capture_output=True, text=True, timeout=15,
    )
    assert result.returncode == 0, result.stdout + result.stderr
