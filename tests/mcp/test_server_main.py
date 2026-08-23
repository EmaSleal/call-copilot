"""Unit test for src/mcp/server.py::main() — a bare load_dotenv() call
resolves relative to the CALLING FILE's location (python-dotenv's
find_dotenv(), frame-based upward search), not app_home(). For a pipx
install launched by an external client (Claude Desktop) from an unrelated
cwd, that search never reaches ~/.call-copilot/.env — the same file
src/core/env_store.py (and the TUI's settings screen) writes to.
Confirmed empirically: find_dotenv() returned '' when run from /tmp
against the installed package. main() must pass env_store.ENV_PATH
explicitly instead of relying on the default search.
"""

from unittest.mock import MagicMock, patch


class TestMain:
    def test_loads_dotenv_from_the_explicit_env_path_not_default_search(self):
        from src.core import env_store
        from src.mcp import server

        fake_server = MagicMock()
        with (
            patch.object(server, "load_dotenv") as mock_load_dotenv,
            patch.object(server, "build_server", return_value=fake_server) as mock_build,
        ):
            server.main()

        mock_load_dotenv.assert_called_once_with(env_store.ENV_PATH)
        mock_build.assert_called_once()
        fake_server.run.assert_called_once_with(transport="stdio")
