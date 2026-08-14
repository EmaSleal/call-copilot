"""
Unit tests for src.core.updater — `call-copilot update`.

Reinstalls the pipx package at its latest commit, reusing the same
optional-dependency profile install.sh saved at install time (so the user
isn't re-prompted every update).
"""

from unittest.mock import MagicMock
import pytest

from src.core.updater import build_pip_spec, read_install_profile, run_update


class TestBuildPipSpec:
    def test_no_extras_uses_base_package(self):
        spec = build_pip_spec("")
        assert spec.startswith("call-copilot @ ")
        assert "[" not in spec.split(" @ ")[0]

    def test_single_extra(self):
        spec = build_pip_spec("rag")
        assert spec.startswith("call-copilot[rag] @ ")

    def test_multiple_extras_comma_joined(self):
        spec = build_pip_spec("rag,video")
        assert spec.startswith("call-copilot[rag,video] @ ")

    def test_spec_points_at_the_git_repo(self):
        spec = build_pip_spec("")
        assert spec.endswith("git+https://github.com/EmaSleal/call-copilot.git@linux-support")


class TestReadInstallProfile:
    def test_missing_file_returns_empty_string(self, tmp_path, monkeypatch):
        monkeypatch.setattr("src.core.updater._profile_path", lambda: tmp_path / "install-profile")
        assert read_install_profile() == ""

    def test_existing_file_is_read_and_stripped(self, tmp_path, monkeypatch):
        profile_file = tmp_path / "install-profile"
        profile_file.write_text("rag,video\n")
        monkeypatch.setattr("src.core.updater._profile_path", lambda: profile_file)
        assert read_install_profile() == "rag,video"


class TestRunUpdate:
    def test_calls_pipx_install_force_with_built_spec(self, monkeypatch):
        monkeypatch.setattr("src.core.updater.read_install_profile", lambda: "rag")
        mock_run = MagicMock(return_value=MagicMock(returncode=0))
        monkeypatch.setattr("src.core.updater.subprocess.run", mock_run)

        exit_code = run_update()

        assert exit_code == 0
        mock_run.assert_called_once()
        args = mock_run.call_args[0][0]
        assert args[:3] == ["pipx", "install", "--force"]
        assert args[3].startswith("call-copilot[rag] @ ")

    def test_propagates_pipx_failure_exit_code(self, monkeypatch):
        monkeypatch.setattr("src.core.updater.read_install_profile", lambda: "")
        mock_run = MagicMock(return_value=MagicMock(returncode=1))
        monkeypatch.setattr("src.core.updater.subprocess.run", mock_run)

        assert run_update() == 1

    def test_missing_pipx_returns_nonzero_without_raising(self, monkeypatch):
        monkeypatch.setattr("src.core.updater.read_install_profile", lambda: "")

        def _raise(*a, **k):
            raise FileNotFoundError()

        monkeypatch.setattr("src.core.updater.subprocess.run", _raise)

        assert run_update() == 1
