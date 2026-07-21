"""Tests for the restored command-line music-library scanner."""

import sys
from argparse import Namespace
from unittest.mock import MagicMock, patch

from app.main import _default_vector_index_path, main, run_scan


def test_cli_parser_registers_scan_command(tmp_path) -> None:
    """The scan command forwards its folder argument to the runner."""
    with patch.object(sys, "argv", ["app/main.py", "scan", str(tmp_path)]):
        with patch("app.main.run_scan") as runner:
            main()

    runner.assert_called_once()
    assert runner.call_args.args[0].command == "scan"
    assert runner.call_args.args[0].folder == str(tmp_path)


def test_run_scan_indexes_valid_folder(tmp_path, capsys) -> None:
    """The CLI runs the shared indexing worker synchronously and reports its count."""
    worker = MagicMock()
    worker.finished.connect.side_effect = lambda callback: callback(2)

    with patch("app.ui.workers.ScanWorker", return_value=worker) as worker_class:
        run_scan(Namespace(folder=str(tmp_path)))

    worker_class.assert_called_once_with(
        folder_path=tmp_path.resolve(),
        vector_index_path=_default_vector_index_path(),
    )
    worker.run.assert_called_once()
    assert "Indexed 2 new or updated song(s)." in capsys.readouterr().out


def test_run_scan_rejects_missing_folder(tmp_path, capsys) -> None:
    """A missing path is rejected before creating an indexing worker."""
    missing_folder = tmp_path / "missing"
    with patch("app.ui.workers.ScanWorker") as worker_class:
        run_scan(Namespace(folder=str(missing_folder)))

    worker_class.assert_not_called()
    assert "is not a directory" in capsys.readouterr().out
