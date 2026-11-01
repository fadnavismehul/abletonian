import unittest
from types import SimpleNamespace

import _bootstrap  # noqa: F401

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


if __name__ == "__main__":
    unittest.main()
