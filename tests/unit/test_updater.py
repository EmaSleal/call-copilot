"""
Unit tests for src.core.updater — `call-copilot update`.

Reinstalls the pipx package at its latest commit, reusing the same
optional-dependency profile install.sh saved at install time (so the user
isn't re-prompted every update).
"""

import importlib.metadata
from pathlib import Path
from unittest.mock import MagicMock
import pytest

from src.core.updater import (
    _hermes_cli_available,
    _hermes_has_call_copilot_registered,
    _offer_hermes_connection,
    _pipx_venvs_dir,
    build_pip_spec,
    get_installed_commit,
    get_latest_release_tag,
    get_remote_commit,
    read_install_profile,
    run_check_update,
    run_doctor,
    run_install_mcp,
    run_uninstall,
    run_update,
    run_version,
)


class TestBuildPipSpec:
    def test_no_extras_uses_base_package(self):
        spec = build_pip_spec("", ref="main")
        assert spec.startswith("call-copilot @ ")
        assert "[" not in spec.split(" @ ")[0]

    def test_single_extra(self):
        spec = build_pip_spec("rag", ref="main")
        assert spec.startswith("call-copilot[rag] @ ")

    def test_multiple_extras_comma_joined(self):
        spec = build_pip_spec("rag,video", ref="main")
        assert spec.startswith("call-copilot[rag,video] @ ")

    def test_spec_points_at_the_given_ref(self):
        spec = build_pip_spec("", ref="v0.2.0")
        assert spec.endswith("git+https://github.com/EmaSleal/call-copilot.git@v0.2.0")


class TestGetLatestReleaseTag:
    def test_returns_highest_semver_tag(self, monkeypatch):
        mock_run = MagicMock(return_value=MagicMock(
            returncode=0,
            stdout=(
                "541135c9e2861a5cf4d9fd1f312312d3c84a4216\trefs/tags/v0.2.0\n"
                "99c369f85d317b113ce89355a3b98528e6022c0\trefs/tags/v0.1.0\n"
            ),
        ))
        monkeypatch.setattr("src.core.updater.subprocess.run", mock_run)

        assert get_latest_release_tag() == "v0.2.0"
        args = mock_run.call_args[0][0]
        assert args[:4] == ["git", "ls-remote", "--tags", "--refs"]

    def test_falls_back_to_main_when_no_tags_exist(self, monkeypatch):
        mock_run = MagicMock(return_value=MagicMock(returncode=0, stdout=""))
        monkeypatch.setattr("src.core.updater.subprocess.run", mock_run)

        assert get_latest_release_tag() == "main"

    def test_falls_back_to_main_on_network_failure(self, monkeypatch):
        import subprocess as sp
        mock_run = MagicMock(side_effect=sp.CalledProcessError(1, ["git"]))
        monkeypatch.setattr("src.core.updater.subprocess.run", mock_run)

        assert get_latest_release_tag() == "main"


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
        monkeypatch.setattr("src.core.updater.get_latest_release_tag", lambda: "v0.2.0")
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
        assert install_args[2].endswith("@v0.2.0")

    def test_uninstall_failure_does_not_block_install(self, monkeypatch):
        """First run ever (nothing installed yet) — `pipx uninstall` of a
        non-existent package returns nonzero; that must not stop install."""
        monkeypatch.setattr("src.core.updater.read_install_profile", lambda: "")
        monkeypatch.setattr("src.core.updater.get_latest_release_tag", lambda: "v0.2.0")
        mock_run = MagicMock(side_effect=[
            MagicMock(returncode=1),  # uninstall: "not installed"
            MagicMock(returncode=0),  # install: succeeds
        ])
        monkeypatch.setattr("src.core.updater.subprocess.run", mock_run)

        assert run_update() == 0
        assert mock_run.call_count == 2

    def test_missing_pipx_returns_nonzero_without_raising(self, monkeypatch):
        monkeypatch.setattr("src.core.updater.read_install_profile", lambda: "")
        monkeypatch.setattr("src.core.updater.get_latest_release_tag", lambda: "v0.2.0")

        def _raise(*a, **k):
            raise FileNotFoundError()

        monkeypatch.setattr("src.core.updater.subprocess.run", _raise)

        assert run_update() == 1


class TestRunUpdateRetry:
    """Windows-specific failure mode: antivirus/real-time scanning
    transiently locks files mid-uninstall, leaving a half-deleted venv
    that then makes the following install fail even though pipx reported
    the uninstall as successful. run_update() force-deletes the leftover
    venv and retries once — same fix a human would otherwise do by hand."""

    def test_retries_once_after_cleaning_a_stale_venv(self, monkeypatch, tmp_path):
        monkeypatch.setattr("src.core.updater.read_install_profile", lambda: "")
        monkeypatch.setattr("src.core.updater.get_latest_release_tag", lambda: "v0.2.0")
        monkeypatch.setattr("src.core.updater._pipx_venvs_dir", lambda: tmp_path)
        mock_rmtree = MagicMock()
        monkeypatch.setattr("src.core.updater.shutil.rmtree", mock_rmtree)
        mock_run = MagicMock(side_effect=[
            MagicMock(returncode=0),  # uninstall
            MagicMock(returncode=1),  # install: fails (stale venv)
            MagicMock(returncode=0),  # retry install: succeeds
        ])
        monkeypatch.setattr("src.core.updater.subprocess.run", mock_run)

        assert run_update() == 0
        assert mock_run.call_count == 3
        mock_rmtree.assert_called_once_with(tmp_path / "call-copilot", ignore_errors=True)

    def test_retry_failure_still_propagates_nonzero(self, monkeypatch, tmp_path):
        monkeypatch.setattr("src.core.updater.read_install_profile", lambda: "")
        monkeypatch.setattr("src.core.updater.get_latest_release_tag", lambda: "v0.2.0")
        monkeypatch.setattr("src.core.updater._pipx_venvs_dir", lambda: tmp_path)
        monkeypatch.setattr("src.core.updater.shutil.rmtree", MagicMock())
        mock_run = MagicMock(side_effect=[
            MagicMock(returncode=0),
            MagicMock(returncode=1),
            MagicMock(returncode=1),  # retry also fails — not our problem to hide
        ])
        monkeypatch.setattr("src.core.updater.subprocess.run", mock_run)

        assert run_update() == 1
        assert mock_run.call_count == 3

    def test_does_not_retry_when_venvs_dir_cannot_be_determined(self, monkeypatch):
        """pipx itself missing/broken -- retrying with an unknown venv
        path would be guessing at a location to rm -rf. Just propagate."""
        monkeypatch.setattr("src.core.updater.read_install_profile", lambda: "")
        monkeypatch.setattr("src.core.updater.get_latest_release_tag", lambda: "v0.2.0")
        monkeypatch.setattr("src.core.updater._pipx_venvs_dir", lambda: None)
        mock_run = MagicMock(side_effect=[
            MagicMock(returncode=0),
            MagicMock(returncode=1),
        ])
        monkeypatch.setattr("src.core.updater.subprocess.run", mock_run)

        assert run_update() == 1
        assert mock_run.call_count == 2

    def test_no_retry_when_install_succeeds_first_try(self, monkeypatch, tmp_path):
        monkeypatch.setattr("src.core.updater.read_install_profile", lambda: "")
        monkeypatch.setattr("src.core.updater.get_latest_release_tag", lambda: "v0.2.0")
        mock_venvs_dir = MagicMock(return_value=tmp_path)
        monkeypatch.setattr("src.core.updater._pipx_venvs_dir", mock_venvs_dir)
        mock_run = MagicMock(return_value=MagicMock(returncode=0))
        monkeypatch.setattr("src.core.updater.subprocess.run", mock_run)

        assert run_update() == 0
        assert mock_run.call_count == 2
        mock_venvs_dir.assert_not_called()


class TestPipxVenvsDir:
    def test_returns_path_from_pipx_environment(self, monkeypatch):
        mock_run = MagicMock(return_value=MagicMock(
            returncode=0, stdout="/home/user/.local/share/pipx/venvs\n",
        ))
        monkeypatch.setattr("src.core.updater.subprocess.run", mock_run)

        result = _pipx_venvs_dir()

        assert result == Path("/home/user/.local/share/pipx/venvs")
        assert mock_run.call_args[0][0] == ["pipx", "environment", "--value", "PIPX_LOCAL_VENVS"]

    def test_returns_none_when_pipx_missing(self, monkeypatch):
        def _raise(*a, **k):
            raise FileNotFoundError()

        monkeypatch.setattr("src.core.updater.subprocess.run", _raise)

        assert _pipx_venvs_dir() is None

    def test_returns_none_on_empty_output(self, monkeypatch):
        mock_run = MagicMock(return_value=MagicMock(returncode=0, stdout=""))
        monkeypatch.setattr("src.core.updater.subprocess.run", mock_run)

        assert _pipx_venvs_dir() is None


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
        monkeypatch.setattr("src.core.updater.get_latest_release_tag", lambda: "v0.2.0")
        monkeypatch.setattr("src.core.updater.get_remote_commit", lambda ref: "abc123")

        assert run_check_update() == 0
        out = capsys.readouterr().out
        assert "al día" in out
        assert "v0.2.0" in out

    def test_update_available(self, monkeypatch, capsys):
        monkeypatch.setattr("src.core.updater.get_installed_commit", lambda: "abc123")
        monkeypatch.setattr("src.core.updater.get_latest_release_tag", lambda: "v0.3.0")
        monkeypatch.setattr("src.core.updater.get_remote_commit", lambda ref: "def456")

        assert run_check_update() == 0
        out = capsys.readouterr().out
        assert "def456"[:12] in out or "def456" in out
        assert "v0.3.0" in out
        assert "update" in out.lower()

    def test_no_network_returns_nonzero(self, monkeypatch, capsys):
        monkeypatch.setattr("src.core.updater.get_installed_commit", lambda: "abc123")
        monkeypatch.setattr("src.core.updater.get_latest_release_tag", lambda: "v0.2.0")
        monkeypatch.setattr("src.core.updater.get_remote_commit", lambda ref: None)

        assert run_check_update() == 1

    def test_unknown_installed_commit_returns_nonzero(self, monkeypatch, capsys):
        monkeypatch.setattr("src.core.updater.get_installed_commit", lambda: None)
        monkeypatch.setattr("src.core.updater.get_latest_release_tag", lambda: "v0.2.0")
        monkeypatch.setattr("src.core.updater.get_remote_commit", lambda ref: "def456")

        assert run_check_update() == 1


# ─────────────────────────────────────────────────────────────
# run_uninstall()
# ─────────────────────────────────────────────────────────────

class TestRunUninstall:
    def test_calls_pipx_uninstall(self, monkeypatch, tmp_path):
        monkeypatch.setattr("src.core.updater.app_home", lambda: tmp_path)
        monkeypatch.setattr("src.core.updater._pipx_venvs_dir", lambda: None)
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
        monkeypatch.setattr("src.core.updater._pipx_venvs_dir", lambda: None)
        mock_run = MagicMock(return_value=MagicMock(returncode=1))
        monkeypatch.setattr("src.core.updater.subprocess.run", mock_run)

        assert run_uninstall() == 1

    def test_sweeps_leftover_venv_even_when_pipx_reports_success(self, monkeypatch, tmp_path):
        """The exact Windows failure mode seen live: pipx fails to move
        the venv to trash (AV/permissions) but still reports the
        uninstall as successful, leaving a directory behind that breaks
        the next install."""
        monkeypatch.setattr("src.core.updater.app_home", lambda: tmp_path)
        venvs_dir = tmp_path / "venvs"
        leftover = venvs_dir / "call-copilot"
        leftover.mkdir(parents=True)
        (leftover / "pyvenv.cfg").write_text("stale")
        monkeypatch.setattr("src.core.updater._pipx_venvs_dir", lambda: venvs_dir)
        mock_run = MagicMock(return_value=MagicMock(returncode=0))
        monkeypatch.setattr("src.core.updater.subprocess.run", mock_run)

        assert run_uninstall() == 0
        assert not leftover.exists()

    def test_no_op_when_nothing_left_behind(self, monkeypatch, tmp_path):
        monkeypatch.setattr("src.core.updater.app_home", lambda: tmp_path)
        venvs_dir = tmp_path / "venvs"
        venvs_dir.mkdir()
        monkeypatch.setattr("src.core.updater._pipx_venvs_dir", lambda: venvs_dir)
        mock_run = MagicMock(return_value=MagicMock(returncode=0))
        monkeypatch.setattr("src.core.updater.subprocess.run", mock_run)

        assert run_uninstall() == 0


# ─────────────────────────────────────────────────────────────
# run_install_mcp()
# ─────────────────────────────────────────────────────────────

class TestRunInstallMcp:
    """`call-copilot install-mcp` — adds the `mcp` extra without a full
    reinstall. Persisting it into the install-profile matters: run_update()
    rebuilds its pip spec from that same file, so skipping the persist
    would silently drop the extra on the next `call-copilot update`."""

    @pytest.fixture(autouse=True)
    def _no_hermes_offer(self, monkeypatch):
        """Isolates pip-install behavior from the Hermes-connection offer
        (_offer_hermes_connection has its own dedicated tests below) —
        otherwise these tests would depend on whether `hermes` happens to
        be on PATH on the machine running the suite."""
        monkeypatch.setattr("src.core.updater._offer_hermes_connection", lambda: None)

    def test_dev_checkout_pip_installs_into_current_venv(self, monkeypatch):
        monkeypatch.setattr("src.core.updater._is_dev_checkout", lambda: True)
        mock_run = MagicMock(return_value=MagicMock(returncode=0))
        monkeypatch.setattr("src.core.updater.subprocess.run", mock_run)

        assert run_install_mcp() == 0
        args = mock_run.call_args[0][0]
        assert args[1:] == ["-m", "pip", "install", "mcp>=1.0.0"]

    def test_dev_checkout_propagates_pip_failure(self, monkeypatch):
        monkeypatch.setattr("src.core.updater._is_dev_checkout", lambda: True)
        mock_run = MagicMock(return_value=MagicMock(returncode=1))
        monkeypatch.setattr("src.core.updater.subprocess.run", mock_run)

        assert run_install_mcp() == 1

    def test_pipx_install_injects_and_persists_profile(self, monkeypatch, tmp_path):
        monkeypatch.setattr("src.core.updater._is_dev_checkout", lambda: False)
        profile_file = tmp_path / "install-profile"
        profile_file.write_text("rag")
        monkeypatch.setattr("src.core.updater._profile_path", lambda: profile_file)
        mock_run = MagicMock(return_value=MagicMock(returncode=0))
        monkeypatch.setattr("src.core.updater.subprocess.run", mock_run)

        assert run_install_mcp() == 0
        mock_run.assert_called_once_with(["pipx", "inject", "call-copilot", "mcp>=1.0.0"])
        assert profile_file.read_text() == "rag,mcp"

    def test_pipx_install_persists_profile_when_none_existed(self, monkeypatch, tmp_path):
        monkeypatch.setattr("src.core.updater._is_dev_checkout", lambda: False)
        profile_file = tmp_path / "install-profile"
        monkeypatch.setattr("src.core.updater._profile_path", lambda: profile_file)
        mock_run = MagicMock(return_value=MagicMock(returncode=0))
        monkeypatch.setattr("src.core.updater.subprocess.run", mock_run)

        assert run_install_mcp() == 0
        assert profile_file.read_text() == "mcp"

    def test_already_in_profile_is_not_duplicated(self, monkeypatch, tmp_path):
        monkeypatch.setattr("src.core.updater._is_dev_checkout", lambda: False)
        profile_file = tmp_path / "install-profile"
        profile_file.write_text("rag,mcp")
        monkeypatch.setattr("src.core.updater._profile_path", lambda: profile_file)
        mock_run = MagicMock(return_value=MagicMock(returncode=0))
        monkeypatch.setattr("src.core.updater.subprocess.run", mock_run)

        assert run_install_mcp() == 0
        assert profile_file.read_text() == "rag,mcp"

    def test_pipx_failure_does_not_touch_profile(self, monkeypatch, tmp_path):
        monkeypatch.setattr("src.core.updater._is_dev_checkout", lambda: False)
        profile_file = tmp_path / "install-profile"
        profile_file.write_text("rag")
        monkeypatch.setattr("src.core.updater._profile_path", lambda: profile_file)
        mock_run = MagicMock(return_value=MagicMock(returncode=1))
        monkeypatch.setattr("src.core.updater.subprocess.run", mock_run)

        assert run_install_mcp() == 1
        assert profile_file.read_text() == "rag"

    def test_missing_pipx_returns_nonzero_without_raising(self, monkeypatch):
        monkeypatch.setattr("src.core.updater._is_dev_checkout", lambda: False)

        def _raise(*a, **k):
            raise FileNotFoundError()

        monkeypatch.setattr("src.core.updater.subprocess.run", _raise)

        assert run_install_mcp() == 1


# ─────────────────────────────────────────────────────────────
# _offer_hermes_connection() — bonus step after a successful `install-mcp`:
# registers call-copilot as an MCP server in Hermes via `hermes mcp add`,
# never by rewriting ~/.hermes/config.yaml directly.
# ─────────────────────────────────────────────────────────────

class TestHermesCliAvailable:
    def test_true_when_on_path(self, monkeypatch):
        monkeypatch.setattr("src.core.updater.shutil.which", lambda name: "/usr/bin/hermes")
        assert _hermes_cli_available() is True

    def test_false_when_not_on_path(self, monkeypatch):
        monkeypatch.setattr("src.core.updater.shutil.which", lambda name: None)
        assert _hermes_cli_available() is False


class TestHermesHasCallCopilotRegistered:
    def test_true_when_name_appears_in_listing(self, monkeypatch):
        mock_run = MagicMock(return_value=MagicMock(
            stdout="  codegraph  ...\n  call-copilot  ...\n", returncode=0,
        ))
        monkeypatch.setattr("src.core.updater.subprocess.run", mock_run)
        assert _hermes_has_call_copilot_registered() is True

    def test_false_when_name_absent(self, monkeypatch):
        mock_run = MagicMock(return_value=MagicMock(
            stdout="  codegraph  ...\n  context7  ...\n", returncode=0,
        ))
        monkeypatch.setattr("src.core.updater.subprocess.run", mock_run)
        assert _hermes_has_call_copilot_registered() is False

    def test_false_when_hermes_binary_missing(self, monkeypatch):
        def _raise(*a, **k):
            raise FileNotFoundError()
        monkeypatch.setattr("src.core.updater.subprocess.run", _raise)
        assert _hermes_has_call_copilot_registered() is False


class TestOfferHermesConnection:
    def test_noop_when_hermes_not_installed(self, monkeypatch, capsys):
        monkeypatch.setattr("src.core.updater._hermes_cli_available", lambda: False)
        mock_run = MagicMock()
        monkeypatch.setattr("src.core.updater.subprocess.run", mock_run)

        _offer_hermes_connection()

        mock_run.assert_not_called()
        assert capsys.readouterr().out == ""

    def test_noop_when_already_registered(self, monkeypatch, capsys):
        monkeypatch.setattr("src.core.updater._hermes_cli_available", lambda: True)
        monkeypatch.setattr("src.core.updater._hermes_has_call_copilot_registered", lambda: True)
        mock_run = MagicMock()
        monkeypatch.setattr("src.core.updater.subprocess.run", mock_run)

        _offer_hermes_connection()

        mock_run.assert_not_called()
        assert "ya tiene" in capsys.readouterr().out

    def test_declining_the_prompt_does_not_register(self, monkeypatch):
        monkeypatch.setattr("src.core.updater._hermes_cli_available", lambda: True)
        monkeypatch.setattr("src.core.updater._hermes_has_call_copilot_registered", lambda: False)
        monkeypatch.setattr("builtins.input", lambda prompt="": "n")
        mock_run = MagicMock()
        monkeypatch.setattr("src.core.updater.subprocess.run", mock_run)

        _offer_hermes_connection()

        mock_run.assert_not_called()

    def test_accepting_the_prompt_registers_without_env_override(self, monkeypatch):
        """No --env MCP_ALLOW_TOOL_INGESTION here — that write-gate stays
        controlled by call-copilot's own Settings toggle, independent of
        whether Hermes is connected."""
        monkeypatch.setattr("src.core.updater._hermes_cli_available", lambda: True)
        monkeypatch.setattr("src.core.updater._hermes_has_call_copilot_registered", lambda: False)
        monkeypatch.setattr("builtins.input", lambda prompt="": "y")
        mock_run = MagicMock(return_value=MagicMock(returncode=0))
        monkeypatch.setattr("src.core.updater.subprocess.run", mock_run)

        _offer_hermes_connection()

        mock_run.assert_called_once_with(
            ["hermes", "mcp", "add", "call-copilot", "--command", "call-copilot-mcp"]
        )

    def test_registration_failure_does_not_raise(self, monkeypatch, capsys):
        monkeypatch.setattr("src.core.updater._hermes_cli_available", lambda: True)
        monkeypatch.setattr("src.core.updater._hermes_has_call_copilot_registered", lambda: False)
        monkeypatch.setattr("builtins.input", lambda prompt="": "y")
        mock_run = MagicMock(return_value=MagicMock(returncode=1))
        monkeypatch.setattr("src.core.updater.subprocess.run", mock_run)

        _offer_hermes_connection()

        assert "No se pudo" in capsys.readouterr().out


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
