import unittest

import _bootstrap  # noqa: F401

from abletonian.adapters.remote_script import RemoteScriptAdapter
from abletonian.bridge.protocol import PROTOCOL_VERSION


class FakeDevice:
    def __init__(self, name: str, class_name: str) -> None:
        self.name = name
        self.class_name = class_name


class FakeTrackView:
    def __init__(self, selected_device: FakeDevice | None = None) -> None:
        self.selected_device = selected_device


class FakeTrack:
    def __init__(
        self,
        name: str,
        devices: tuple[FakeDevice, ...],
        color_index: int = 4,
        is_foldable: bool = False,
    ) -> None:
        self.name = name
        self.devices = devices
        self.color_index = color_index
        self.is_foldable = is_foldable
        self.view = FakeTrackView(devices[0] if devices else None)


class FakeSongView:
    def __init__(self, selected_track: FakeTrack) -> None:
        self.selected_track = selected_track


class FakeSong:
    def __init__(self, selected_track: FakeTrack) -> None:
        self.view = FakeSongView(selected_track)
        self.tracks = (selected_track,)


class RemoteScriptAdapterTests(unittest.TestCase):
    def test_health_reports_read_only_remote_script_capabilities(self) -> None:
        adapter = RemoteScriptAdapter(song=FakeSong(FakeTrack("Drums", ())), live_version="12.1.0")

        health = adapter.handle_request("daw.health", {"target_daw": "ableton"})

        self.assertEqual(health["adapter_type"], "ableton_remote_script")
        self.assertEqual(health["live_version"], "12.1.0")
        self.assertEqual(health["protocol_version"], PROTOCOL_VERSION)
        self.assertIn("read_selected_context", health["capabilities"])
        self.assertIn("create_track", health["unsupported_capabilities"])

    def test_selected_context_reports_track_and_selected_drum_rack(self) -> None:
        drum_rack = FakeDevice("Drum Rack", "DrumGroupDevice")
        adapter = RemoteScriptAdapter(
            song=FakeSong(FakeTrack("Drums", (drum_rack,), color_index=9, is_foldable=True)),
            live_version="12.1.0",
        )

        context = adapter.handle_request("ableton.get_selected_context", {})

        self.assertEqual(
            context,
            {
                "track": {
                    "name": "Drums",
                    "color_index": 9,
                    "is_foldable": True,
                    "device_count": 1,
                },
                "device": {
                    "name": "Drum Rack",
                    "class_name": "DrumGroupDevice",
                    "type": "drum_rack",
                },
            },
        )
