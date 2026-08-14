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
    """`pipx install --force` was tried first but is unreliable with pipx's
    uv-backed venv creation (uv refuses to clear a venv from a prior
    session, verified for real against pipx 1.15.0 + uv). Uninstall-then-
    install sidesteps that entirely."""

    def test_uninstalls_then_installs_without_force(self, monkeypatch):
        monkeypatch.setattr("src.core.updater.read_install_profile", lambda: "rag")
        mock_run = MagicMock(return_value=MagicMock(returncode=0))
        monkeypatch.setattr("src.core.updater.subprocess.run", mock_run)

        exit_code = run_update()

        assert exit_code == 0
        assert mock_run.call_count == 2
        uninstall_args = mock_run.call_args_list[0][0][0]
        install_args = mock_run.call_args_list[1][0][0]
        assert uninstall_args == ["pipx", "uninstall", "call-copilot"]
        assert install_args[:2] == ["pipx", "install"]
        assert "--force" not in install_args
        assert install_args[2].startswith("call-copilot[rag] @ ")

    def test_uninstall_failure_does_not_block_install(self, monkeypatch):
        """First run ever (nothing installed yet) — `pipx uninstall` of a
        non-existent package returns nonzero; that must not stop install."""
        monkeypatch.setattr("src.core.updater.read_install_profile", lambda: "")
        mock_run = MagicMock(side_effect=[
            MagicMock(returncode=1),  # uninstall: "not installed"
            MagicMock(returncode=0),  # install: succeeds
        ])
        monkeypatch.setattr("src.core.updater.subprocess.run", mock_run)

        assert run_update() == 0
        assert mock_run.call_count == 2

    def test_propagates_install_failure_exit_code(self, monkeypatch):
        monkeypatch.setattr("src.core.updater.read_install_profile", lambda: "")
        mock_run = MagicMock(side_effect=[
            MagicMock(returncode=0),
            MagicMock(returncode=1),
        ])
        monkeypatch.setattr("src.core.updater.subprocess.run", mock_run)

        assert run_update() == 1

    def test_missing_pipx_returns_nonzero_without_raising(self, monkeypatch):
        monkeypatch.setattr("src.core.updater.read_install_profile", lambda: "")

        def _raise(*a, **k):
            raise FileNotFoundError()

        monkeypatch.setattr("src.core.updater.subprocess.run", _raise)

        assert run_update() == 1
