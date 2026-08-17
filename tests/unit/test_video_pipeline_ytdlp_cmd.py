"""
Unit tests for src.video.pipeline._yt_dlp_cmd() — the base yt-dlp
invocation shared by _get_title/_download_audio/_download_video.

Bugfix: YouTube's current anti-bot rollout returns HTTP 403 for yt-dlp's
default "android_vr" player client on this machine (confirmed manually:
`android_vr` -> 403, `web` -> images only, `tv` -> DRM-blocked, `mweb`
without a solver -> 403). The fix pins the "mweb" client (the one client
that still exposes at least one PO-token-free muxed format) and enables
the remote JS-challenge solver via --remote-components, which mweb needs
for the "n" parameter. Pure function — no subprocess/network involved,
easy to test without hitting yt-dlp itself.
"""

from src.video.pipeline import _yt_dlp_cmd


class TestYtDlpCmd:
    def test_pins_mweb_player_client(self):
        cmd = _yt_dlp_cmd()
        assert "--extractor-args" in cmd
        idx = cmd.index("--extractor-args")
        assert cmd[idx + 1] == "youtube:player_client=mweb"

    def test_enables_remote_ejs_solver(self):
        cmd = _yt_dlp_cmd()
        assert "--remote-components" in cmd
        idx = cmd.index("--remote-components")
        assert cmd[idx + 1] == "ejs:github"

    def test_still_invokes_yt_dlp_as_a_module_of_the_current_interpreter(self):
        import sys

        cmd = _yt_dlp_cmd()
        assert cmd[0] == sys.executable
        assert cmd[1:3] == ["-m", "yt_dlp"]
