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
            name = "Beat"
            length = 1.0
            is_midi_clip = True

            def get_notes_extended(self, *_args):
                return {
                    "notes": (
                        {"pitch": 36, "start_time": 0.0, "duration": 0.25, "velocity": 100},
                    )
                }

        class Track:
            def __init__(self, name="Drums", live_id="track-drums", color_index=3):
                self.name = name
                self.color_index = color_index
                self._live_ptr = live_id
                self.clip_slots = (SimpleNamespace(has_clip=True, clip=Clip()),)
                self.devices = (rack,)
                self.view = SimpleNamespace(selected_device=rack)

            def duplicate(self, suffix):
                return Track(
                    f"{self.name} Copy",
                    f"{self._live_ptr}-copy-{suffix}",
                    self.color_index,
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


if __name__ == "__main__":
    unittest.main()
