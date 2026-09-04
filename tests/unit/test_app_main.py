"""
Unit tests for src.tui.app:main()'s argv dispatch — `call-copilot` (no args)
launches the TUI as before; `call-copilot update` runs the updater instead
and never touches the TUI/DB bootstrap path.
"""

import importlib
from unittest.mock import MagicMock, patch
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

    def test_doctor_arg_dispatches_and_skips_tui(self, monkeypatch):
        """Any known subcommand routes the same way — not just 'update'."""
        import src.tui.app as app_module

        monkeypatch.setattr("sys.argv", ["call-copilot", "doctor"])
        mock_run_doctor = MagicMock(return_value=0)
        monkeypatch.setattr("src.core.updater.run_doctor", mock_run_doctor)
        mock_init_db = MagicMock()
        monkeypatch.setattr(app_module, "init_db", mock_init_db)
        mock_app_cls = MagicMock()
        monkeypatch.setattr(app_module, "UnifiedApp", mock_app_cls)

        exit_code = app_module.main()

        assert exit_code == 0
        mock_run_doctor.assert_called_once()
        mock_init_db.assert_not_called()

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


class TestAppLoadDotenv:
    def test_loads_dotenv_from_the_explicit_env_path_not_default_search(self):
        """Same bug class already documented/fixed for src/mcp/server.py
        (see tests/mcp/test_server_main.py): a bare load_dotenv() resolves
        via python-dotenv's frame-based find_dotenv() search, starting from
        THIS module's own file location — for a pipx install that never
        reaches ~/.call-copilot/.env, the file env_store.py (and the
        Settings screen) actually writes to. Reproduced empirically:
        importing the installed package from an unrelated cwd left
        OPENAI_API_KEY out of os.environ even with a valid saved key on
        disk. Must pass env_store.ENV_PATH explicitly instead — the same
        fix src/mcp/server.py::main() already has."""
        from src.core import env_store

        mock_load_dotenv = MagicMock()
        with patch("dotenv.load_dotenv", mock_load_dotenv):
            import src.tui.app as app_module
            importlib.reload(app_module)

        try:
            mock_load_dotenv.assert_called_once_with(env_store.ENV_PATH)
        finally:
            # Restore the module to its real, unpatched state so any other
            # test importing src.tui.app afterward gets the real load_dotenv.
            importlib.reload(app_module)
