"""
Unit tests for src.core.updater — `call-copilot update`.

Reinstalls the pipx package at its latest commit, reusing the same
optional-dependency profile install.sh saved at install time (so the user
isn't re-prompted every update).
"""

import importlib.metadata
from unittest.mock import MagicMock
import pytest

from src.core.updater import (
    build_pip_spec,
    get_installed_commit,
    get_remote_commit,
    read_install_profile,
    run_check_update,
    run_doctor,
    run_uninstall,
    run_update,
    run_version,
)


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


# ─────────────────────────────────────────────────────────────
# get_installed_commit() — dev checkout (git rev-parse HEAD) vs installed
# package (PEP 610 direct_url.json via importlib.metadata), verified for
# real against pipx 1.15.0's actual direct_url.json shape.
# ─────────────────────────────────────────────────────────────

class TestGetInstalledCommit:
    def test_dev_checkout_uses_git_rev_parse(self, monkeypatch):
        monkeypatch.setattr("src.core.updater._is_dev_checkout", lambda: True)
        mock_run = MagicMock(return_value=MagicMock(
            returncode=0, stdout="541135c9e2861a5cf4d9fd1f312312d3c84a4216\n",
        ))
        monkeypatch.setattr("src.core.updater.subprocess.run", mock_run)

        commit = get_installed_commit()

        assert commit == "541135c9e2861a5cf4d9fd1f312312d3c84a4216"
        args = mock_run.call_args[0][0]
        assert args == ["git", "rev-parse", "HEAD"]

    def test_dev_checkout_git_failure_returns_none(self, monkeypatch):
        monkeypatch.setattr("src.core.updater._is_dev_checkout", lambda: True)

        def _raise(*a, **k):
            raise FileNotFoundError()

        monkeypatch.setattr("src.core.updater.subprocess.run", _raise)

        assert get_installed_commit() is None

    def test_installed_reads_direct_url_commit_id(self, monkeypatch):
        monkeypatch.setattr("src.core.updater._is_dev_checkout", lambda: False)
        mock_dist = MagicMock()
        mock_dist.origin.vcs_info.commit_id = "541135c9e2861a5cf4d9fd1f312312d3c84a4216"
        monkeypatch.setattr(
            "src.core.updater.importlib.metadata.distribution",
            lambda name: mock_dist,
        )

        assert get_installed_commit() == "541135c9e2861a5cf4d9fd1f312312d3c84a4216"

    def test_installed_but_not_found_returns_none(self, monkeypatch):
        monkeypatch.setattr("src.core.updater._is_dev_checkout", lambda: False)

        def _raise(name):
            raise importlib.metadata.PackageNotFoundError(name)

        monkeypatch.setattr("src.core.updater.importlib.metadata.distribution", _raise)

        assert get_installed_commit() is None


# ─────────────────────────────────────────────────────────────
# get_remote_commit() — `git ls-remote`, verified for real against the
# actual public repo (returns "<sha>\trefs/heads/<branch>").
# ─────────────────────────────────────────────────────────────

class TestGetRemoteCommit:
    def test_parses_sha_from_ls_remote_output(self, monkeypatch):
        mock_run = MagicMock(return_value=MagicMock(
            returncode=0,
            stdout="541135c9e2861a5cf4d9fd1f312312d3c84a4216\trefs/heads/linux-support\n",
        ))
        monkeypatch.setattr("src.core.updater.subprocess.run", mock_run)

        assert get_remote_commit() == "541135c9e2861a5cf4d9fd1f312312d3c84a4216"

    def test_network_failure_returns_none(self, monkeypatch):
        import subprocess as sp
        mock_run = MagicMock(side_effect=sp.CalledProcessError(1, ["git"]))
        monkeypatch.setattr("src.core.updater.subprocess.run", mock_run)

        assert get_remote_commit() is None

    def test_empty_output_returns_none(self, monkeypatch):
        mock_run = MagicMock(return_value=MagicMock(returncode=0, stdout=""))
        monkeypatch.setattr("src.core.updater.subprocess.run", mock_run)

        assert get_remote_commit() is None


# ─────────────────────────────────────────────────────────────
# run_version()
# ─────────────────────────────────────────────────────────────

class TestRunVersion:
    def test_prints_commit_and_returns_zero(self, monkeypatch, capsys):
        monkeypatch.setattr("src.core.updater.get_installed_commit", lambda: "541135c9e286")
        monkeypatch.setattr("src.core.updater._is_dev_checkout", lambda: False)

        assert run_version() == 0
        out = capsys.readouterr().out
        assert "541135c9e286" in out

    def test_unknown_commit_does_not_crash(self, monkeypatch, capsys):
        monkeypatch.setattr("src.core.updater.get_installed_commit", lambda: None)
        monkeypatch.setattr("src.core.updater._is_dev_checkout", lambda: False)

        assert run_version() == 0


# ─────────────────────────────────────────────────────────────
# run_check_update()
# ─────────────────────────────────────────────────────────────

class TestRunCheckUpdate:
    def test_up_to_date(self, monkeypatch, capsys):
        monkeypatch.setattr("src.core.updater.get_installed_commit", lambda: "abc123")
        monkeypatch.setattr("src.core.updater.get_remote_commit", lambda: "abc123")

        assert run_check_update() == 0
        assert "al día" in capsys.readouterr().out

    def test_update_available(self, monkeypatch, capsys):
        monkeypatch.setattr("src.core.updater.get_installed_commit", lambda: "abc123")
        monkeypatch.setattr("src.core.updater.get_remote_commit", lambda: "def456")

        assert run_check_update() == 0
        out = capsys.readouterr().out
        assert "def456"[:12] in out or "def456" in out
        assert "update" in out.lower()

    def test_no_network_returns_nonzero(self, monkeypatch, capsys):
        monkeypatch.setattr("src.core.updater.get_installed_commit", lambda: "abc123")
        monkeypatch.setattr("src.core.updater.get_remote_commit", lambda: None)

        assert run_check_update() == 1

    def test_unknown_installed_commit_returns_nonzero(self, monkeypatch, capsys):
        monkeypatch.setattr("src.core.updater.get_installed_commit", lambda: None)
        monkeypatch.setattr("src.core.updater.get_remote_commit", lambda: "def456")

        assert run_check_update() == 1


# ─────────────────────────────────────────────────────────────
# run_uninstall()
# ─────────────────────────────────────────────────────────────

class TestRunUninstall:
    def test_calls_pipx_uninstall(self, monkeypatch, tmp_path):
        monkeypatch.setattr("src.core.updater.app_home", lambda: tmp_path)
        mock_run = MagicMock(return_value=MagicMock(returncode=0))
        monkeypatch.setattr("src.core.updater.subprocess.run", mock_run)

        assert run_uninstall() == 0
        mock_run.assert_called_once_with(["pipx", "uninstall", "call-copilot"])

    def test_missing_pipx_returns_nonzero(self, monkeypatch):
        def _raise(*a, **k):
            raise FileNotFoundError()

        monkeypatch.setattr("src.core.updater.subprocess.run", _raise)

        assert run_uninstall() == 1

    def test_propagates_pipx_exit_code(self, monkeypatch, tmp_path):
        monkeypatch.setattr("src.core.updater.app_home", lambda: tmp_path)
        mock_run = MagicMock(return_value=MagicMock(returncode=1))
        monkeypatch.setattr("src.core.updater.subprocess.run", mock_run)

        assert run_uninstall() == 1


# ─────────────────────────────────────────────────────────────
# run_doctor()
# ─────────────────────────────────────────────────────────────

class TestRunDoctor:
    def test_returns_zero_and_prints_a_report(self, monkeypatch, capsys):
        monkeypatch.setattr("src.core.updater._is_dev_checkout", lambda: True)
        monkeypatch.setattr("src.core.updater.get_installed_commit", lambda: "abc123")
        monkeypatch.setattr("src.core.updater.app_home", lambda: __import__("pathlib").Path("/fake"))
        monkeypatch.setattr("src.core.updater._pipx_version", lambda: "1.15.0")
        monkeypatch.setattr("src.core.updater._module_available", lambda name: name == "chromadb")

        assert run_doctor() == 0
        out = capsys.readouterr().out
        assert "chromadb" in out.lower()
        assert "1.15.0" in out

    def test_missing_pipx_reported_not_crashed(self, monkeypatch, capsys):
        monkeypatch.setattr("src.core.updater._is_dev_checkout", lambda: True)
        monkeypatch.setattr("src.core.updater.get_installed_commit", lambda: None)
        monkeypatch.setattr("src.core.updater.app_home", lambda: __import__("pathlib").Path("/fake"))
        monkeypatch.setattr("src.core.updater._pipx_version", lambda: None)
        monkeypatch.setattr("src.core.updater._module_available", lambda name: False)

        assert run_doctor() == 0
