"""Streaming dashboard regressions against the actual JavaScript modules."""
from pathlib import Path
import shutil
import subprocess

import pytest


@pytest.mark.parametrize("scenario", ["live", "topology"])
def test_streaming_section_interactions(scenario):
    node = shutil.which("node")
    if not node:
        pytest.skip("Node.js is required for renderer regressions")
    result = subprocess.run(
        [node, str(Path(__file__).with_name("dashboard_rendering.cjs")), scenario],
        capture_output=True, text=True, timeout=15,
    )
    assert result.returncode == 0, result.stdout + result.stderr
