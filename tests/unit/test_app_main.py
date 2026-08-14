"""
Unit tests for src.tui.app:main()'s argv dispatch — `call-copilot` (no args)
launches the TUI as before; `call-copilot update` runs the updater instead
and never touches the TUI/DB bootstrap path.
"""

from unittest.mock import MagicMock
import pytest


class TestMainArgvDispatch:
    def test_update_arg_calls_run_update_and_skips_tui(self, monkeypatch):
        import src.tui.app as app_module

        monkeypatch.setattr("sys.argv", ["call-copilot", "update"])
        mock_run_update = MagicMock(return_value=0)
        monkeypatch.setattr("src.core.updater.run_update", mock_run_update)
        mock_init_db = MagicMock()
        monkeypatch.setattr(app_module, "init_db", mock_init_db)
        mock_app_cls = MagicMock()
        monkeypatch.setattr(app_module, "UnifiedApp", mock_app_cls)

        exit_code = app_module.main()

        assert exit_code == 0
        mock_run_update.assert_called_once()
        mock_init_db.assert_not_called()
        mock_app_cls.assert_not_called()

    def test_no_args_launches_tui_as_before(self, monkeypatch):
        import src.tui.app as app_module

        monkeypatch.setattr("sys.argv", ["call-copilot"])
        mock_init_db = MagicMock()
        monkeypatch.setattr(app_module, "init_db", mock_init_db)
        mock_preload = MagicMock()
        monkeypatch.setattr(app_module.bootstrap, "_preload_models", mock_preload)
        mock_instance = MagicMock()
        mock_app_cls = MagicMock(return_value=mock_instance)
        monkeypatch.setattr(app_module, "UnifiedApp", mock_app_cls)

        app_module.main()

        mock_init_db.assert_called_once()
        mock_preload.assert_called_once()
        mock_instance.run.assert_called_once()
