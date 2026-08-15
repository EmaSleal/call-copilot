"""
Unit tests for build_audio_sink_options — the pure function backing the
"Salida de audio a capturar" Select in CallCopilotTab. Lets the user pick
which device to capture instead of always trusting the OS's notion of
"default": on Linux, a PulseAudio/PipeWire sink (`pactl get-default-sink`
can silently diverge from the device actually playing the call audio);
on Windows, a WASAPI loopback device (mirrors the same rationale).
"""

from unittest.mock import patch

from src.audio.pulse_source import SinkInfo
from src.audio.wasapi_source import DeviceInfo


class TestBuildAudioSinkOptions:
    def test_always_includes_default_option_first(self):
        from src.tui.tabs.call import build_audio_sink_options
        with (
            patch("src.audio.pulse_source.list_sinks", return_value=[]),
            patch("src.audio.wasapi_source.list_output_devices", return_value=[]),
        ):
            options = build_audio_sink_options()
        assert options[0] == ("Default (dispositivo del sistema)", "")

    def test_default_option_value_is_empty_string(self):
        """Empty string means 'no override' — PulseLoopbackSource(device=None)
        / WASAPILoopbackSource(device_index=None)."""
        from src.tui.tabs.call import build_audio_sink_options
        with (
            patch("src.audio.pulse_source.list_sinks", return_value=[]),
            patch("src.audio.wasapi_source.list_output_devices", return_value=[]),
        ):
            options = build_audio_sink_options()
        assert options[0][1] == ""

    def test_appends_one_option_per_sink(self):
        from src.tui.tabs.call import build_audio_sink_options
        sinks = [
            SinkInfo(name="alsa_output.usb-Generic_EarPods-00.analog-stereo", state="RUNNING"),
            SinkInfo(name="alsa_output.usb-Corsair-00.analog-stereo", state="SUSPENDED"),
        ]
        with (
            patch("src.audio.pulse_source.list_sinks", return_value=sinks),
            patch("src.audio.wasapi_source.list_output_devices", return_value=[]),
        ):
            options = build_audio_sink_options()
        assert len(options) == 3  # default + 2 sinks

    def test_sink_option_value_is_the_raw_sink_name(self):
        """Value must be the bare sink name (no .monitor suffix) — that
        suffix is appended by PulseLoopbackSource itself."""
        from src.tui.tabs.call import build_audio_sink_options
        sinks = [SinkInfo(name="alsa_output.usb-Generic_EarPods-00.analog-stereo", state="RUNNING")]
        with (
            patch("src.audio.pulse_source.list_sinks", return_value=sinks),
            patch("src.audio.wasapi_source.list_output_devices", return_value=[]),
        ):
            options = build_audio_sink_options()
        assert options[1][1] == "alsa_output.usb-Generic_EarPods-00.analog-stereo"

    def test_sink_option_label_shows_state(self):
        from src.tui.tabs.call import build_audio_sink_options
        sinks = [SinkInfo(name="alsa_output.usb-Generic_EarPods-00.analog-stereo", state="RUNNING")]
        with (
            patch("src.audio.pulse_source.list_sinks", return_value=sinks),
            patch("src.audio.wasapi_source.list_output_devices", return_value=[]),
        ):
            options = build_audio_sink_options()
        assert "RUNNING" in options[1][0]

    def test_no_sinks_available_returns_only_default(self):
        from src.tui.tabs.call import build_audio_sink_options
        with (
            patch("src.audio.pulse_source.list_sinks", return_value=[]),
            patch("src.audio.wasapi_source.list_output_devices", return_value=[]),
        ):
            options = build_audio_sink_options()
        assert len(options) == 1

    def test_appends_one_option_per_wasapi_device(self):
        from src.tui.tabs.call import build_audio_sink_options
        devices = [
            DeviceInfo(index=1, name="Auriculares (Realtek) [Loopback]"),
            DeviceInfo(index=3, name="Altavoces (USB) [Loopback]"),
        ]
        with (
            patch("src.audio.pulse_source.list_sinks", return_value=[]),
            patch("src.audio.wasapi_source.list_output_devices", return_value=devices),
        ):
            options = build_audio_sink_options()
        assert len(options) == 3  # default + 2 devices

    def test_wasapi_device_option_value_is_the_device_index_as_str(self):
        """Value must round-trip through int() at the call site
        (WASAPILoopbackSource(device_index=int(value)))."""
        from src.tui.tabs.call import build_audio_sink_options
        devices = [DeviceInfo(index=3, name="Altavoces (USB) [Loopback]")]
        with (
            patch("src.audio.pulse_source.list_sinks", return_value=[]),
            patch("src.audio.wasapi_source.list_output_devices", return_value=devices),
        ):
            options = build_audio_sink_options()
        assert options[1] == ("Altavoces (USB) [Loopback]", "3")
