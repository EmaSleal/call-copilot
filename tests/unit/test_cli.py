"""
Unit tests for src.core.cli.dispatch() — `call-copilot <subcommand>`
routing, called from src/tui/app.py's main() before falling through to
launching the TUI.
"""

from unittest.mock import MagicMock
import pytest

from src.core.cli import dispatch


class TestDispatch:
    def test_no_args_returns_none(self):
        assert dispatch([]) is None

    def test_unknown_first_arg_returns_none(self):
        assert dispatch(["--some-unrelated-flag"]) is None

    @pytest.mark.parametrize("command,target", [
        ("update", "run_update"),
        ("check-update", "run_check_update"),
        ("version", "run_version"),
        ("uninstall", "run_uninstall"),
        ("doctor", "run_doctor"),
    ])
    def test_known_commands_dispatch_to_updater(self, monkeypatch, command, target):
        mock_fn = MagicMock(return_value=0)
        monkeypatch.setattr(f"src.core.updater.{target}", mock_fn)

        exit_code = dispatch([command])

        assert exit_code == 0
        mock_fn.assert_called_once()

    def test_propagates_handler_exit_code(self, monkeypatch):
        monkeypatch.setattr("src.core.updater.run_update", lambda: 1)
        assert dispatch(["update"]) == 1

    def test_extra_args_after_command_are_ignored_by_dispatch(self, monkeypatch):
        """Subcommands here take no arguments of their own — dispatch just
        needs the first token to route correctly."""
        mock_fn = MagicMock(return_value=0)
        monkeypatch.setattr("src.core.updater.run_version", mock_fn)

        assert dispatch(["version", "--extra", "stuff"]) == 0
