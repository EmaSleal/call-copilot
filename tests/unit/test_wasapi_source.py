"""
Unit tests for src.audio.wasapi_source: WASAPI loopback device listing
(pure-ish, wraps pyaudiowpatch) and letting WASAPILoopbackSource capture
from an explicitly chosen device instead of always auto-detecting the
current default output — mirrors test_pulse_source.py's device-override
coverage on the Linux side.

pyaudiowpatch is a win32-only dependency (pyproject.toml), so every test
here patches the module-level `pyaudio` name in src.audio.wasapi_source
with a fake object exposing just the bits of the PyAudioWPatch API this
module actually uses.
"""

import asyncio
from unittest.mock import MagicMock, patch

from src.audio.wasapi_source import (
    DeviceInfo,
    WASAPILoopbackSource,
    device_label,
    list_output_devices,
)

WASAPI_HOST_API_INDEX = 2


def _fake_pyaudio(devices: list[dict], wasapi_index: int = WASAPI_HOST_API_INDEX):
    """Builds a fake pyaudiowpatch-like module + PyAudio instance backed
    by the given device dicts (each needs at least index/name/hostApi/
    isLoopbackDevice keys for list_output_devices)."""
    pa_instance = MagicMock()
    pa_instance.get_host_api_info_by_type.return_value = {"index": wasapi_index}
    pa_instance.get_device_count.return_value = len(devices)
    pa_instance.get_device_info_by_index.side_effect = lambda i: devices[i]

    fake_module = MagicMock()
    fake_module.PyAudio.return_value = pa_instance
    fake_module.paWASAPI = "WASAPI_CONST"
    return fake_module, pa_instance


class TestDeviceLabel:
    def test_returns_device_name(self):
        device = DeviceInfo(index=3, name="Auriculares (Realtek)")
        assert device_label(device) == "Auriculares (Realtek)"


class TestListOutputDevices:
    def test_returns_empty_list_when_pyaudio_unavailable(self):
        with patch("src.audio.wasapi_source.pyaudio", None):
            assert list_output_devices() == []

    def test_returns_only_loopback_devices_on_the_wasapi_host_api(self):
        devices = [
            {"index": 0, "name": "Mic", "hostApi": WASAPI_HOST_API_INDEX, "isLoopbackDevice": False},
            {"index": 1, "name": "Speakers [Loopback]", "hostApi": WASAPI_HOST_API_INDEX, "isLoopbackDevice": True},
            {"index": 2, "name": "Other API device", "hostApi": 0, "isLoopbackDevice": True},
        ]
        fake_module, _ = _fake_pyaudio(devices)
        with patch("src.audio.wasapi_source.pyaudio", fake_module):
            result = list_output_devices()
        assert result == [DeviceInfo(index=1, name="Speakers [Loopback]")]

    def test_returns_empty_list_when_no_loopback_devices_present(self):
        devices = [
            {"index": 0, "name": "Mic", "hostApi": WASAPI_HOST_API_INDEX, "isLoopbackDevice": False},
        ]
        fake_module, _ = _fake_pyaudio(devices)
        with patch("src.audio.wasapi_source.pyaudio", fake_module):
            assert list_output_devices() == []

    def test_returns_empty_list_when_wasapi_host_api_lookup_fails(self):
        fake_module, pa_instance = _fake_pyaudio([])
        pa_instance.get_host_api_info_by_type.side_effect = OSError
        with patch("src.audio.wasapi_source.pyaudio", fake_module):
            assert list_output_devices() == []

    def test_terminates_pyaudio_instance_on_success(self):
        fake_module, pa_instance = _fake_pyaudio([])
        with patch("src.audio.wasapi_source.pyaudio", fake_module):
            list_output_devices()
        pa_instance.terminate.assert_called_once()

    def test_terminates_pyaudio_instance_even_when_lookup_fails(self):
        fake_module, pa_instance = _fake_pyaudio([])
        pa_instance.get_host_api_info_by_type.side_effect = OSError
        with patch("src.audio.wasapi_source.pyaudio", fake_module):
            list_output_devices()
        pa_instance.terminate.assert_called_once()


class TestWASAPILoopbackSourceDeviceOverride:
    def test_default_device_index_is_none(self):
        assert WASAPILoopbackSource().device_index is None

    def test_explicit_device_index_stored_verbatim(self):
        source = WASAPILoopbackSource(device_index=5)
        assert source.device_index == 5

    def test_start_uses_explicit_device_index_bypassing_default_detection(self):
        devices = [
            {"index": 0, "name": "Mic", "hostApi": WASAPI_HOST_API_INDEX, "isLoopbackDevice": False},
            {
                "index": 1, "name": "Auriculares [Loopback]",
                "hostApi": WASAPI_HOST_API_INDEX, "isLoopbackDevice": True,
                "defaultSampleRate": 48000.0, "maxInputChannels": 2,
            },
        ]
        fake_module, pa_instance = _fake_pyaudio(devices)
        pa_instance.open.return_value = MagicMock()
        source = WASAPILoopbackSource(device_index=1)

        with patch("src.audio.wasapi_source.pyaudio", fake_module):
            asyncio.run(source.start())

        pa_instance.get_host_api_info_by_type.assert_not_called()
        assert pa_instance.open.call_args.kwargs["input_device_index"] == 1
