"""
Unit tests for src.audio.pulse_source: sink listing/parsing (pure) and
letting PulseLoopbackSource capture from an explicitly chosen sink instead
of always trusting `pactl get-default-sink` — which can silently diverge
from the device actually playing the call audio (e.g. default sink is a
suspended headset while audio is routed to a different, running device).
"""

import asyncio
import subprocess
from unittest.mock import MagicMock, patch

from src.audio.pulse_source import (
    SinkInfo,
    _parse_sinks,
    sink_label,
    list_sinks,
    PulseLoopbackSource,
)

SAMPLE_PACTL_OUTPUT = (
    "732\talsa_output.pci-0000_01_00.1.hdmi-stereo\tPipeWire\ts32le 2ch 48000Hz\tSUSPENDED\n"
    "733\talsa_output.usb-Generic_EarPods_20210726905926-00.analog-stereo\tPipeWire\ts24le 2ch 48000Hz\tRUNNING\n"
    "737\talsa_output.usb-Corsair_Corsair_HS65_SURROUND-00.analog-stereo\tPipeWire\ts24le 2ch 48000Hz\tSUSPENDED\n"
)


class TestParseSinks:
    def test_parses_all_rows(self):
        assert len(_parse_sinks(SAMPLE_PACTL_OUTPUT)) == 3

    def test_extracts_name_and_state(self):
        sinks = _parse_sinks(SAMPLE_PACTL_OUTPUT)
        earpods = sinks[1]
        assert earpods.name == "alsa_output.usb-Generic_EarPods_20210726905926-00.analog-stereo"
        assert earpods.state == "RUNNING"

    def test_empty_output_returns_empty_list(self):
        assert _parse_sinks("") == []

    def test_ignores_malformed_lines(self):
        assert _parse_sinks("not\tenough\tcolumns\n") == []

    def test_ignores_blank_lines(self):
        raw = "\n" + SAMPLE_PACTL_OUTPUT + "\n\n"
        assert len(_parse_sinks(raw)) == 3


class TestSinkLabel:
    def test_strips_alsa_output_prefix(self):
        sink = SinkInfo(name="alsa_output.usb-Generic_EarPods-00.analog-stereo", state="RUNNING")
        assert "alsa_output." not in sink_label(sink)

    def test_includes_state_so_user_can_spot_the_active_device(self):
        sink = SinkInfo(name="alsa_output.usb-Corsair-00.analog-stereo", state="SUSPENDED")
        assert "SUSPENDED" in sink_label(sink)

    def test_includes_device_identity(self):
        sink = SinkInfo(name="alsa_output.usb-Generic_EarPods-00.analog-stereo", state="RUNNING")
        assert "Generic_EarPods" in sink_label(sink)


class TestListSinks:
    def test_returns_parsed_sinks_on_success(self):
        with patch("subprocess.check_output", return_value=SAMPLE_PACTL_OUTPUT):
            assert len(list_sinks()) == 3

    def test_returns_empty_list_when_pactl_missing(self):
        with patch("subprocess.check_output", side_effect=FileNotFoundError):
            assert list_sinks() == []

    def test_returns_empty_list_when_pactl_fails(self):
        with patch("subprocess.check_output", side_effect=subprocess.CalledProcessError(1, "pactl")):
            assert list_sinks() == []


class TestPulseLoopbackSourceDeviceOverride:
    def test_default_device_is_none(self):
        assert PulseLoopbackSource().device is None

    def test_explicit_device_stored_verbatim(self):
        source = PulseLoopbackSource(device="alsa_output.usb-Generic_EarPods-00.analog-stereo")
        assert source.device == "alsa_output.usb-Generic_EarPods-00.analog-stereo"

    def test_explicit_device_used_as_parec_monitor(self):
        source = PulseLoopbackSource(device="alsa_output.usb-Generic_EarPods-00.analog-stereo")

        async def run():
            with (
                patch("src.audio.pulse_source.subprocess.Popen") as mock_popen,
                patch("src.audio.pulse_source._default_monitor") as mock_default,
            ):
                mock_popen.return_value.stdout = MagicMock()
                await source.start()
                await source.stop()
            return mock_popen, mock_default

        mock_popen, mock_default = asyncio.run(run())
        mock_default.assert_not_called()
        parec_args = mock_popen.call_args[0][0]
        assert "--device=alsa_output.usb-Generic_EarPods-00.analog-stereo.monitor" in parec_args

    def test_falls_back_to_default_monitor_when_no_device_chosen(self):
        source = PulseLoopbackSource()

        async def run():
            with (
                patch("src.audio.pulse_source.subprocess.Popen") as mock_popen,
                patch("src.audio.pulse_source._default_monitor", return_value="fallback.monitor") as mock_default,
            ):
                mock_popen.return_value.stdout = MagicMock()
                await source.start()
                await source.stop()
            return mock_popen, mock_default

        mock_popen, mock_default = asyncio.run(run())
        mock_default.assert_called_once()
        parec_args = mock_popen.call_args[0][0]
        assert "--device=fallback.monitor" in parec_args
