import unittest
from types import SimpleNamespace

import _bootstrap  # noqa: F401

from abletonian.bridge.protocol import PROTOCOL_VERSION
from remote_scripts.Abletonian.bridge_server import (
    AbletonianBridgeControlSurface,
    _decode_frame,
    _dispatch_frame,
    _encode_frame,
    _live_object,
)


class RemoteScriptBridgeTests(unittest.TestCase):
    def test_health_accepts_application_property(self) -> None:
        class Application:
            def get_major_version(self):
                return 12

            def get_minor_version(self):
                return 4

            def get_bugfix_version(self):
                return 0

        class Surface:
            application = Application()

        health = AbletonianBridgeControlSurface._health(Surface(), {"target_daw": "ableton"})

        self.assertEqual(health["live_version"], "12.4.0")

    def test_live_object_accepts_method_or_property(self) -> None:
        expected = object()

        class MethodSurface:
            def song(self):
                return expected

        class PropertySurface:
            song = expected

        self.assertIs(_live_object(MethodSurface(), "song"), expected)
        self.assertIs(_live_object(PropertySurface(), "song"), expected)

    def test_dispatch_frame_uses_live_scheduler_when_available(self) -> None:
        class Surface:
            def __init__(self):
                self.scheduled = False
                self.scheduled_delay = None

            def schedule_message(self, delay, callback):
                self.scheduled = True
                self.scheduled_delay = delay
                callback()

            def handle_request(self, method, params):
                if not self.scheduled:
                    raise RuntimeError("request was not scheduled")
                return {"method": method, "params": params}

        surface = Surface()
        frame = _encode_frame(
            {"id": "request-1", "method": "example.method", "params": {"x": 1}}
        )

        response = _decode_frame(_dispatch_frame(surface, frame))

        self.assertTrue(response["ok"])
        self.assertEqual(surface.scheduled_delay, 0)
        self.assertEqual(response["result"], {"method": "example.method", "params": {"x": 1}})

    def test_request_live_never_starts_is_cancelled(self) -> None:
        from remote_scripts.Abletonian import bridge_server

        class Surface:
            def __init__(self):
                self.pending = []
                self.handled = False

            def schedule_message(self, delay, callback):
                self.pending.append(callback)

            def handle_request(self, method, params):
                self.handled = True
                return {}

        surface = Surface()
        frame = _encode_frame({"id": "r1", "method": "ableton.set_mixer", "params": {}})
        original = bridge_server.REQUEST_START_TIMEOUT_SECONDS
        bridge_server.REQUEST_START_TIMEOUT_SECONDS = 0.05
        try:
            response = _decode_frame(_dispatch_frame(surface, frame))
        finally:
            bridge_server.REQUEST_START_TIMEOUT_SECONDS = original
        surface.pending[0]()

        self.assertFalse(response["ok"])
        self.assertIn("nothing changed", response["error"]["message"])
        self.assertFalse(surface.handled)

    def test_bridge_surface_plans_drum_rack_extraction(self) -> None:
        class Clip:
            name = "Beat"
            length = 1.0
            is_midi_clip = True

            def get_notes_extended(self, *_args):
                return {
                    "notes": (
                        {"pitch": 36, "start_time": 0.0, "duration": 0.25, "velocity": 100},
                    )
                }

        chain = SimpleNamespace(
            name="Kick Chain",
            color_index=5,
            devices=(SimpleNamespace(name="Kick Sampler"),),
        )
        pad = SimpleNamespace(note=36, name="Kick", chains=(chain,))
        rack = SimpleNamespace(
            name="Drum Rack",
            class_name="DrumGroupDevice",
            drum_pads=(pad,),
            _live_ptr="device-drum-rack",
        )
        track = SimpleNamespace(
            name="Drums",
            color_index=3,
            devices=(rack,),
            clip_slots=(SimpleNamespace(has_clip=True, clip=Clip()),),
            view=SimpleNamespace(selected_device=rack),
            _live_ptr="track-drums",
        )
        surface = AbletonianBridgeControlSurface.__new__(AbletonianBridgeControlSurface)
        surface.song = SimpleNamespace(view=SimpleNamespace(selected_track=track))

        plan = surface.handle_request("workflow.plan_drum_rack_extraction", {})

        self.assertEqual(plan["operation"], "split_drum_rack")
        self.assertEqual(plan["target"]["track_id"], "track-drums")
        self.assertEqual(plan["output_tracks"][0]["name"], "Drums - Kick")
        self.assertEqual(plan["output_tracks"][0]["clip_note_count"], 1)

    def test_bridge_surface_scaffolds_drum_rack_extraction(self) -> None:
        class Clip:
            def __init__(self, notes=None):
                self.name = "Beat"
                self.length = 1.0
                self.is_midi_clip = True
                self._notes = tuple(
                    notes
                    or (
                        {"pitch": 36, "start_time": 0.0, "duration": 0.25, "velocity": 100},
                    )
                )

            def get_notes_extended(self, *_args):
                return {"notes": self._notes}

            def remove_notes_extended(self, from_pitch, pitch_span, *_args):
                pitch_stop = from_pitch + pitch_span
                self._notes = tuple(
                    note
                    for note in self._notes
                    if not from_pitch <= int(note["pitch"]) < pitch_stop
                )

            def duplicate(self):
                return Clip(self._notes)

            @property
            def note_pitches(self):
                return [int(note["pitch"]) for note in self._notes]

        class Track:
            def __init__(self, name="Drums", live_id="track-drums", color_index=3, clip=None):
                self.name = name
                self.color_index = color_index
                self._live_ptr = live_id
                self.clip_slots = (SimpleNamespace(has_clip=True, clip=clip or Clip()),)
                self.devices = (rack,)
                self.view = SimpleNamespace(selected_device=rack)

            def duplicate(self, suffix):
                return Track(
                    f"{self.name} Copy",
                    f"{self._live_ptr}-copy-{suffix}",
                    self.color_index,
                    self.clip_slots[0].clip.duplicate(),
                )

        class Song:
            def __init__(self):
                self.tracks = [Track()]
                self.view = SimpleNamespace(selected_track=self.tracks[0])
                self.duplicate_track_calls = []

            def duplicate_track(self, index):
                self.duplicate_track_calls.append(index)
                duplicate = self.tracks[index].duplicate(len(self.duplicate_track_calls))
                self.tracks.insert(index + 1, duplicate)

        chain = SimpleNamespace(
            name="Kick Chain",
            color_index=5,
            devices=(SimpleNamespace(name="Kick Sampler"),),
        )
        pad = SimpleNamespace(note=36, name="Kick", chains=(chain,))
        rack = SimpleNamespace(
            name="Drum Rack",
            class_name="DrumGroupDevice",
            drum_pads=(pad,),
            _live_ptr="device-drum-rack",
        )
        song = Song()
        surface = AbletonianBridgeControlSurface.__new__(AbletonianBridgeControlSurface)
        surface.song = song

        result = surface.handle_request("workflow.scaffold_drum_rack_extraction", {"confirm": True})

        self.assertEqual(result["mode"], "scaffold_tracks")
        self.assertEqual(result["created_tracks"][0]["name"], "Drums - Kick")
        self.assertEqual(song.duplicate_track_calls, [0])
        self.assertEqual([track.name for track in song.tracks], ["Drums", "Drums - Kick"])

    def test_bridge_surface_executes_drum_rack_extraction(self) -> None:
        class Clip:
            def __init__(self, notes=None):
                self.name = "Beat"
                self.length = 1.0
                self.is_midi_clip = True
                self._notes = tuple(
                    notes
                    or (
                        {"pitch": 36, "start_time": 0.0, "duration": 0.25, "velocity": 100},
                        {"pitch": 38, "start_time": 0.5, "duration": 0.25, "velocity": 100},
                        {"pitch": 36, "start_time": 0.75, "duration": 0.25, "velocity": 100},
                    )
                )

            def get_notes_extended(self, *_args):
                return {"notes": self._notes}

            def remove_notes_extended(self, from_pitch, pitch_span, *_args):
                pitch_stop = from_pitch + pitch_span
                self._notes = tuple(
                    note
                    for note in self._notes
                    if not from_pitch <= int(note["pitch"]) < pitch_stop
                )

            def duplicate(self):
                return Clip(self._notes)

            @property
            def note_pitches(self):
                return [int(note["pitch"]) for note in self._notes]

        class Track:
            def __init__(self, name="Drums", live_id="track-drums", color_index=3, clip=None):
                self.name = name
                self.color_index = color_index
                self._live_ptr = live_id
                self.clip_slots = (SimpleNamespace(has_clip=True, clip=clip or Clip()),)
                self.devices = (rack,)
                self.view = SimpleNamespace(selected_device=rack)

            def duplicate(self, suffix):
                return Track(
                    f"{self.name} Copy",
                    f"{self._live_ptr}-copy-{suffix}",
                    self.color_index,
                    self.clip_slots[0].clip.duplicate(),
                )

        class Song:
            def __init__(self):
                self.tracks = [Track()]
                self.view = SimpleNamespace(selected_track=self.tracks[0])
                self.duplicate_track_calls = []

            def duplicate_track(self, index):
                self.duplicate_track_calls.append(index)
                duplicate = self.tracks[index].duplicate(len(self.duplicate_track_calls))
                self.tracks.insert(index + 1, duplicate)

        kick_chain = SimpleNamespace(
            name="Kick Chain",
            color_index=5,
            devices=(SimpleNamespace(name="Kick Sampler"),),
        )
        snare_chain = SimpleNamespace(
            name="Snare Chain",
            color_index=7,
            devices=(SimpleNamespace(name="Snare Sampler"),),
        )
        rack = SimpleNamespace(
            name="Drum Rack",
            class_name="DrumGroupDevice",
            drum_pads=(
                SimpleNamespace(note=36, name="Kick", chains=(kick_chain,)),
                SimpleNamespace(note=38, name="Snare", chains=(snare_chain,)),
            ),
            _live_ptr="device-drum-rack",
        )
        song = Song()
        surface = AbletonianBridgeControlSurface.__new__(AbletonianBridgeControlSurface)
        surface.song = song

        result = surface.handle_request("workflow.execute_drum_rack_extraction", {"confirm": True})

        self.assertEqual(result["mode"], "execute")
        self.assertEqual(
            [track["name"] for track in result["created_tracks"]],
            ["Drums - Kick", "Drums - Snare"],
        )
        self.assertEqual(song.tracks[0].clip_slots[0].clip.note_pitches, [36, 38, 36])
        self.assertEqual(song.tracks[1].clip_slots[0].clip.note_pitches, [36, 36])
        self.assertEqual(song.tracks[2].clip_slots[0].clip.note_pitches, [38])
        self.assertEqual(
            [clip["note_pitches"] for track in result["created_tracks"] for clip in track["clips"]],
            [[36], [38]],
        )
        self.assertTrue(result["verification"]["midi_filtering_applied"])


class FakeApplication:
    def __init__(self, version: str) -> None:
        self._parts = [int(part) for part in version.split(".")]

    def get_major_version(self) -> int:
        return self._parts[0]

    def get_minor_version(self) -> int:
        return self._parts[1]

    def get_bugfix_version(self) -> int:
        return self._parts[2]


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
        self._notes = tuple(dict(note) for note in notes)

    def get_notes_extended(
        self,
        _from_pitch: int,
        _pitch_span: int,
        _from_time: float,
        _time_span: float,
    ) -> dict[str, tuple[dict[str, object], ...]]:
        return {"notes": self._notes}

    def remove_notes_extended(
        self,
        from_pitch: int,
        pitch_span: int,
        _from_time: float,
        _time_span: float,
    ) -> None:
        pitch_stop = from_pitch + pitch_span
        self._notes = tuple(
            note
            for note in self._notes
            if not from_pitch <= int(note["pitch"]) < pitch_stop
        )

    def duplicate(self) -> "FakeClip":
        return FakeClip(self.name, self._notes)

    @property
    def note_pitches(self) -> list[int]:
        return [int(note["pitch"]) for note in self._notes]


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

    def duplicate(self, suffix: int) -> "FakeTrack":
        return FakeTrack(
            name=f"{self.name} Copy",
            devices=self.devices,
            clip_slots=tuple(
                FakeClipSlot(slot.clip.duplicate()) if slot.clip is not None else FakeClipSlot()
                for slot in self.clip_slots
            ),
            color_index=self.color_index,
            is_foldable=self.is_foldable,
            live_id=f"{self._live_ptr}-copy-{suffix}",
        )


class FakeSongView:
    def __init__(self, selected_track: FakeTrack) -> None:
        self.selected_track = selected_track


class FakeSong:
    def __init__(self, selected_track: FakeTrack) -> None:
        self.view = FakeSongView(selected_track)
        self.tracks = [selected_track]
        self.duplicate_track_calls: list[int] = []

    def duplicate_track(self, index: int) -> None:
        self.duplicate_track_calls.append(index)
        duplicate = self.tracks[index].duplicate(len(self.duplicate_track_calls))
        self.tracks.insert(index + 1, duplicate)


def bridge_surface(song: FakeSong, live_version: str = "12.4.0") -> AbletonianBridgeControlSurface:
    """Build the bridge surface without starting its socket server."""
    surface = AbletonianBridgeControlSurface.__new__(AbletonianBridgeControlSurface)
    surface.song = song
    surface.application = FakeApplication(live_version)
    return surface


class BridgeSurfaceDrumRackWorkflowTests(unittest.TestCase):
    def test_health_reports_remote_script_capabilities(self) -> None:
        surface = bridge_surface(FakeSong(FakeTrack("Drums", ())), live_version="12.1.0")

        health = surface.handle_request("daw.health", {"target_daw": "ableton"})

        self.assertEqual(health["adapter_type"], "ableton_remote_script")
        self.assertEqual(health["live_version"], "12.1.0")
        self.assertEqual(health["protocol_version"], PROTOCOL_VERSION)
        self.assertIn("read_selected_context", health["capabilities"])
        self.assertIn("plan_drum_rack_extraction", health["capabilities"])
        self.assertIn("scaffold_drum_rack_extraction", health["capabilities"])
        self.assertIn("execute_drum_rack_extraction", health["capabilities"])
        self.assertIn("write_midi_notes", health["unsupported_capabilities"])

    def test_selected_context_reports_track_and_selected_drum_rack(self) -> None:
        drum_rack = FakeDevice("Drum Rack", "DrumGroupDevice")
        surface = bridge_surface(
            FakeSong(FakeTrack("Drums", (drum_rack,), color_index=9, is_foldable=True))
        )

        context = surface.handle_request("ableton.get_selected_context", {})

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
        surface = bridge_surface(drum_rack_song())

        plan = surface.handle_request("workflow.plan_drum_rack_extraction", {})

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

    def test_scaffold_drum_rack_extraction_requires_confirmation(self) -> None:
        surface = bridge_surface(drum_rack_song())

        with self.assertRaisesRegex(RuntimeError, "requires confirmation"):
            surface.handle_request("workflow.scaffold_drum_rack_extraction", {})

    def test_scaffold_drum_rack_extraction_duplicates_renames_and_returns_manifest(self) -> None:
        song = drum_rack_song()
        surface = bridge_surface(song)

        result = surface.handle_request(
            "workflow.scaffold_drum_rack_extraction",
            {"confirm": True},
        )

        self.assertEqual(result["operation"], "split_drum_rack")
        self.assertEqual(result["mode"], "scaffold_tracks")
        self.assertEqual(result["preserved_tracks"], ["track-drums"])
        self.assertEqual(song.duplicate_track_calls, [0, 1])
        self.assertEqual(
            [track.name for track in song.tracks],
            ["Drums", "Drums - Kick", "Drums - Snare"],
        )
        self.assertEqual([track.color_index for track in song.tracks[1:]], [5, 7])
        self.assertEqual(
            [track["name"] for track in result["created_tracks"]],
            ["Drums - Kick", "Drums - Snare"],
        )
        self.assertEqual(
            [track["source_pad"]["name"] for track in result["created_tracks"]],
            ["Kick", "Snare"],
        )
        self.assertEqual(
            result["verification"],
            {
                "source_track_preserved": True,
                "created_track_count": 2,
                "midi_filtering_applied": False,
                "saved_live_set": False,
                "mutates_real_ableton_set": True,
            },
        )
        self.assertIn("Use Live Undo", result["backout"]["primary"])

    def test_execute_drum_rack_extraction_requires_confirmation(self) -> None:
        surface = bridge_surface(drum_rack_song())

        with self.assertRaisesRegex(RuntimeError, "requires confirmation"):
            surface.handle_request("workflow.execute_drum_rack_extraction", {})

    def test_execute_drum_rack_extraction_filters_duplicate_clips_and_preserves_source(
        self,
    ) -> None:
        song = drum_rack_song()
        surface = bridge_surface(song)

        result = surface.handle_request(
            "workflow.execute_drum_rack_extraction",
            {"confirm": True},
        )

        self.assertEqual(result["operation"], "split_drum_rack")
        self.assertEqual(result["mode"], "execute")
        self.assertEqual(result["preserved_tracks"], ["track-drums"])
        self.assertEqual(song.duplicate_track_calls, [0, 1])
        self.assertEqual(
            [track.name for track in song.tracks],
            ["Drums", "Drums - Kick", "Drums - Snare"],
        )
        self.assertEqual(song.tracks[0].clip_slots[0].clip.note_pitches, [36, 38, 36])
        self.assertEqual(song.tracks[1].clip_slots[0].clip.note_pitches, [36, 36])
        self.assertEqual(song.tracks[2].clip_slots[0].clip.note_pitches, [38])
        self.assertEqual(
            [clip["note_pitches"] for track in result["created_tracks"] for clip in track["clips"]],
            [[36], [38]],
        )
        self.assertEqual(
            [clip["note_count"] for track in result["created_tracks"] for clip in track["clips"]],
            [2, 1],
        )
        self.assertEqual(
            [track["contains_unfiltered_clips"] for track in result["created_tracks"]],
            [False, False],
        )
        self.assertEqual(
            result["verification"],
            {
                "source_track_preserved": True,
                "created_track_count": 2,
                "midi_filtering_applied": True,
                "saved_live_set": False,
                "mutates_real_ableton_set": True,
            },
        )


def drum_rack_song() -> FakeSong:
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
    return FakeSong(
        FakeTrack(
            "Drums",
            (drum_rack,),
            clip_slots=(FakeClipSlot(clip),),
            color_index=3,
            live_id="track-drums",
        )
    )


if __name__ == "__main__":
    unittest.main()
