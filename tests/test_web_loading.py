from pathlib import Path
import subprocess


def test_frontend_loading_races_and_recovery():
    result = subprocess.run(["node", str(Path(__file__).with_name("test_index_loading.js"))],
                            capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stdout + result.stderr
