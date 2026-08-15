"""
Unit tests for src.audio.blackhole_source: BlackHole virtual-device
discovery (pure, hardware-independent).

_normalize_chunk and the PyAudio-backed I/O class (start/stop) aren't
covered here: tests/conftest.py stubs `numpy` out with a MagicMock for the
whole suite (CI installs only pytest+pytest-asyncio+python-dotenv, not the
full numeric stack), and start/stop need real hardware/driver — same gap
as WASAPILoopbackSource, this module's Windows counterpart.
"""

from src.audio.blackhole_source import _find_blackhole_device


class FakePyAudio:
    def __init__(self, devices):
        self._devices = devices

    def get_device_count(self):
        return len(self._devices)

    def get_device_info_by_index(self, i):
        return self._devices[i]


class TestFindBlackholeDevice:
    def test_finds_device_by_name_case_insensitive(self):
        devices = [
            {"name": "MacBook Pro Microphone", "maxInputChannels": 1},
            {"name": "BlackHole 2ch", "maxInputChannels": 2},
        ]
        found = _find_blackhole_device(FakePyAudio(devices))
        assert found["name"] == "BlackHole 2ch"

    def test_ignores_blackhole_device_with_no_input_channels(self):
        devices = [{"name": "BlackHole 2ch", "maxInputChannels": 0}]
        assert _find_blackhole_device(FakePyAudio(devices)) is None

    def test_returns_none_when_not_installed(self):
        devices = [{"name": "MacBook Pro Microphone", "maxInputChannels": 1}]
        assert _find_blackhole_device(FakePyAudio(devices)) is None

    def test_matches_other_channel_count_variants(self):
        devices = [{"name": "BlackHole 16ch", "maxInputChannels": 16}]
        found = _find_blackhole_device(FakePyAudio(devices))
        assert found["name"] == "BlackHole 16ch"
