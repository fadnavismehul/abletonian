import unittest

import _bootstrap  # noqa: F401

from abletonian.adapters.remote_script import RemoteScriptAdapter
from abletonian.bridge.protocol import PROTOCOL_VERSION


class FakeDevice:
    def __init__(
        self,
        name: str,
        class_name: str,
        drum_pads: tuple[object, ...] = (),
        live_id: str | None = None,
    ) -> None:
        self.name = name
        self.class_name = class_name
        self.drum_pads = drum_pads
        self._live_ptr = live_id or name


class FakeChain:
    def __init__(
        self,
        name: str,
        devices: tuple[FakeDevice, ...],
        color_index: int = 0,
    ) -> None:
        self.name = name
        self.devices = devices
        self.color_index = color_index


class FakeDrumPad:
    def __init__(self, note: int, name: str, chains: tuple[FakeChain, ...]) -> None:
        self.note = note
        self.name = name
        self.chains = chains


class FakeClip:
    def __init__(self, name: str, notes: tuple[dict[str, object], ...]) -> None:
        self.name = name
        self.length = 2.0
        self.is_midi_clip = True
        self._notes = notes

    def get_notes_extended(
        self,
        _from_pitch: int,
        _pitch_span: int,
        _from_time: float,
        _time_span: float,
    ) -> dict[str, tuple[dict[str, object], ...]]:
        return {"notes": self._notes}


class FakeClipSlot:
    def __init__(self, clip: FakeClip | None = None) -> None:
        self.clip = clip
        self.has_clip = clip is not None


class FakeTrackView:
    def __init__(self, selected_device: FakeDevice | None = None) -> None:
        self.selected_device = selected_device


class FakeTrack:
    def __init__(
        self,
        name: str,
        devices: tuple[FakeDevice, ...],
        clip_slots: tuple[FakeClipSlot, ...] = (),
        color_index: int = 4,
        is_foldable: bool = False,
        live_id: str | None = None,
    ) -> None:
        self.name = name
        self.devices = devices
        self.clip_slots = clip_slots
        self.color_index = color_index
        self.is_foldable = is_foldable
        self._live_ptr = live_id or name
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
        self.assertIn("plan_drum_rack_extraction", health["capabilities"])
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

    def test_plans_drum_rack_extraction_from_session_midi_notes(self) -> None:
        kick_chain = FakeChain(
            "Kick Chain",
            (FakeDevice("Kick Sampler", "OriginalSimpler"),),
            color_index=5,
        )
        snare_chain = FakeChain(
            "Snare Chain",
            (
                FakeDevice("Snare Sampler", "OriginalSimpler"),
                FakeDevice("Compressor", "Compressor2"),
            ),
            color_index=7,
        )
        hat_chain = FakeChain(
            "Hat Chain",
            (FakeDevice("Hat Sampler", "OriginalSimpler"),),
            color_index=9,
        )
        drum_rack = FakeDevice(
            "Drum Rack",
            "DrumGroupDevice",
            drum_pads=(
                FakeDrumPad(36, "Kick", (kick_chain,)),
                FakeDrumPad(38, "Snare", (snare_chain,)),
                FakeDrumPad(42, "Closed Hat", (hat_chain,)),
            ),
            live_id="device-drum-rack",
        )
        clip = FakeClip(
            "Beat",
            (
                {"pitch": 36, "start_time": 0.0, "duration": 0.25, "velocity": 108},
                {"pitch": 38, "start_time": 0.5, "duration": 0.25, "velocity": 96},
                {"pitch": 36, "start_time": 1.0, "duration": 0.25, "velocity": 104},
            ),
        )
        track = FakeTrack(
            "Drums",
            (drum_rack,),
            clip_slots=(FakeClipSlot(clip),),
            color_index=3,
            live_id="track-drums",
        )
        adapter = RemoteScriptAdapter(song=FakeSong(track), live_version="12.4.0")

        plan = adapter.handle_request("workflow.plan_drum_rack_extraction", {})

        self.assertEqual(plan["operation"], "split_drum_rack")
        self.assertEqual(plan["mode"], "dry_run")
        self.assertEqual(
            plan["target"],
            {
                "track_id": "track-drums",
                "track_name": "Drums",
                "device_id": "device-drum-rack",
                "device_name": "Drum Rack",
            },
        )
        self.assertEqual(
            [output["name"] for output in plan["output_tracks"]],
            ["Drums - Kick", "Drums - Snare"],
        )
        self.assertEqual(
            [output["clip_note_count"] for output in plan["output_tracks"]],
            [2, 1],
        )
        self.assertEqual(
            [output["devices"] for output in plan["output_tracks"]],
            [["Kick Sampler"], ["Snare Sampler", "Compressor"]],
        )
        self.assertEqual(plan["output_tracks"][0]["midi_filter"], {"keep_pitch": 36})
        self.assertEqual(plan["output_tracks"][1]["source_pad"]["chain_name"], "Snare Chain")
        self.assertEqual(plan["steps"][0], {"action": "duplicate_track", "count": 2})
        self.assertEqual(plan["preserves"], ["source_track", "source_clips", "source_devices"])
        self.assertTrue(plan["requires_confirmation"])
        self.assertIn(
            "Skipped 1 drum pad without matching MIDI notes: Closed Hat",
            plan["warnings"],
        )
