"""Run the browser startup/session-state check with the existing Node harness."""

from pathlib import Path
import subprocess


def test_frontend_restores_saved_session():
    script = Path(__file__).with_name("test_index_auth_sessions.js")
    result = subprocess.run(["node", str(script)], capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stdout + result.stderr
