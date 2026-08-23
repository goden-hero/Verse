import subprocess
import pytest
from pathlib import Path

def test_frontend_playlist_seed_transmission():
    """Runs Node test verifying frontend playlist seed transmission logic in app/web/index.js."""
    script_path = Path(__file__).parent / "test_index_seed_transmission.js"
    res = subprocess.run(["node", str(script_path)], capture_output=True, text=True)
    assert res.returncode == 0, f"Frontend seed transmission test failed:\nSTDOUT:\n{res.stdout}\nSTDERR:\n{res.stderr}"
    assert "All Frontend Seed Transmission Tests Passed Successfully!" in res.stdout
