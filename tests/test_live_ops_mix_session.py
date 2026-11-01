"""Live Set operations requested in issue #13 (limits found in a real mix session)."""

import json
import unittest

import _bootstrap  # noqa: F401
from test_live_ops import Song, Track

from remote_scripts.Abletonian import live_ops
from remote_scripts.Abletonian.live_ops import LiveOpsError


def big_song(track_count=30, return_count=6):
    song = Song()
    song.return_tracks = tuple(
        Track(f"{chr(ord('A') + i)}-Return {i}", sends=0) for i in range(return_count)
    )
    song.tracks = tuple(
        Track(f"{i + 1}-Track {i + 1}", sends=return_count) for i in range(track_count)
    )
    for track in song.tracks:
        track.devices = [type("D", (), {"name": "EQ Eight"})()]
        # A realistic routing list: every other track is a possible output.
        track.available_output_routing_types = tuple(
            type("R", (), {"display_name": t.name})() for t in song.tracks
        )
    return song


class ListTracksTests(unittest.TestCase):
    """Issue #14."""

    def call(self, song, **params):
        return live_ops.handle(song, "ableton.list_tracks", params)

    def test_compact_output_for_a_large_set_is_small(self):
        song = big_song()

        full = json.dumps(self.call(song, detail="full"))
        compact = json.dumps(self.call(song, detail="compact"))

        self.assertGreater(len(full), 30_000)
        self.assertLess(len(compact), 15_000)
        self.assertLess(len(compact) * 3, len(full))

    def test_compact_track_shape(self):
        song = big_song(track_count=2, return_count=2)
        song.tracks[0].mute = True

        track = self.call(song, detail="compact")["tracks"][0]

        self.assertEqual(track["name"], "1-Track 1")
        self.assertEqual(track["output"], "Master")
        self.assertEqual(track["volume"], "0.0 dB")
        self.assertEqual(track["pan"], "C")
        self.assertEqual(set(track["sends"]), {"A-Return 0", "B-Return 1"})
        self.assertTrue(track["mute"])
        self.assertNotIn("solo", track)
        self.assertNotIn("available_output_routing_types", json.dumps(track))

    def test_full_is_still_the_bridge_default(self):
        result = self.call(Song())

        self.assertEqual(result["detail"], "full")
        self.assertIn("available_output_routing_types", result["tracks"][0]["routing"])

    def test_name_filter_matches_any_kind(self):
        names = [t["name"] for t in self.call(Song(), name="DEL", detail="compact")["tracks"]]

        self.assertEqual(names, ["B-Delay"])

    def test_rejects_unknown_detail(self):
        with self.assertRaises(LiveOpsError):
            self.call(Song(), detail="tiny")


class ReturnRenameTests(unittest.TestCase):
    """Issue #15: Live shows the return letter itself."""

    def rename(self, song, track, name):
        return live_ops.handle(song, "ableton.set_track_properties", {"track": track, "name": name})

    def test_strips_own_letter_prefix(self):
        song = Song()
        for requested in ("A-Room", "a-Room", "Room"):
            with self.subTest(requested=requested):
                self.rename(song, "return:0", requested)
                self.assertEqual(song.return_tracks[0].name, "Room")

    def test_keeps_other_letters_and_regular_tracks(self):
        song = Song()

        self.rename(song, "return:0", "B-Room")
        self.rename(song, 0, "A-Kick")

        self.assertEqual(song.return_tracks[0].name, "B-Room")
        self.assertEqual(song.tracks[0].name, "A-Kick")

    def test_name_that_is_only_the_prefix_is_kept(self):
        song = Song()

        self.rename(song, "return:1", "B-")

        self.assertEqual(song.return_tracks[1].name, "B-")


class ReturnSong(Song):
    def __init__(self):
        super().__init__()
        self.created = 0

    def create_return_track(self):
        self.created += 1
        letter = chr(ord("A") + len(self.return_tracks))
        self.return_tracks = (*self.return_tracks, Track(f"{letter}-Return", sends=0))


class CreateReturnTrackTests(unittest.TestCase):
    """Issue #18."""

    def test_adds_a_named_coloured_return(self):
        song = ReturnSong()

        result = live_ops.handle(
            song, "ableton.create_return_track", {"name": "C-Room", "color": "#FF0000"}
        )

        self.assertEqual(song.created, 1)
        self.assertEqual(result["track"], {"kind": "return", "index": 2, "name": "Room"})
        self.assertEqual(result["letter"], "C")
        self.assertEqual(result["color"], "#FF0000")

    def test_without_name_keeps_lives_default(self):
        song = ReturnSong()

        result = live_ops.handle(song, "ableton.create_return_track", {})

        self.assertEqual(result["track"]["name"], "C-Return")

    def test_runs_inside_a_batch(self):
        song = ReturnSong()

        result = live_ops.handle(
            song,
            "ableton.batch",
            {"operations": [{"method": "ableton.create_return_track", "params": {"name": "Hall"}}]},
        )

        self.assertIsNone(result["failed"])
        self.assertEqual(song.undo_steps, ["begin", "end"])

    def test_live_without_the_call_gets_a_clear_error(self):
        with self.assertRaisesRegex(LiveOpsError, "cannot create return tracks"):
            live_ops.handle(Song(), "ableton.create_return_track", {})


class DeleteDeviceTests(unittest.TestCase):
    """Issue #19."""

    def setUp(self):
        self.song = Song()
        live_ops.handle(self.song, "ableton.insert_device", {"track": 0, "device_name": "Utility"})
        live_ops.handle(
            self.song, "ableton.insert_device", {"track": 0, "device_name": "Glue Compressor"}
        )
        self.track = self.song.tracks[0]

    def delete(self, **params):
        return live_ops.handle(self.song, "ableton.delete_device", {"track": 0, **params})

    def test_without_confirm_only_previews(self):
        result = self.delete(device="Glue Compressor")

        self.assertFalse(result["deleted"])
        self.assertEqual(result["would_delete"]["device"]["index"], 1)
        self.assertIn("Output", result["would_delete"]["device"]["parameters"])
        self.assertEqual(len(self.track.devices), 2)

    def test_truthy_values_other_than_true_do_not_confirm(self):
        for confirm in ("true", 1, "yes"):
            with self.subTest(confirm=confirm):
                self.assertFalse(self.delete(device=0, confirm=confirm)["deleted"])
        self.assertEqual(len(self.track.devices), 2)

    def test_deletes_the_named_device_with_confirm(self):
        result = self.delete(device="Utility", confirm=True)

        self.assertTrue(result["deleted"])
        self.assertEqual(result["device"]["name"], "Utility")
        self.assertEqual([d.name for d in self.track.devices], ["Glue Compressor"])

    def test_unknown_device_lists_the_choices(self):
        with self.assertRaisesRegex(LiveOpsError, "Devices: Utility, Glue Compressor"):
            self.delete(device="Limiter", confirm=True)


class PluginParam:
    """A plugin parameter whose str_for_value ignores its argument.

    This is the suspected Live behaviour behind issue #16: the display can
    only be read for the current value, through str(parameter).
    """

    def __init__(self, name, value, to_display):
        self.name = name
        self.original_name = name
        self.value = value
        self.min = 0.0
        self.max = 1.0
        self.is_enabled = True
        self.is_quantized = False
        self.value_items = ()
        self._to_display = to_display
        self.writes = []

    def __setattr__(self, key, value):
        if key == "value" and "writes" in self.__dict__:
            self.writes.append(value)
        object.__setattr__(self, key, value)

    def str_for_value(self, _value):
        return self._to_display(self.value)

    def __str__(self):
        return self._to_display(self.value)


def linear_hz(raw):
    return f"{10 + raw * 1990:.0f}Hz"


def log_hz(raw):
    return f"{20 * (1000**raw):.1f} Hz"


class PluginDisplayTextTests(unittest.TestCase):
    """Issue #16."""

    def test_finds_raw_value_for_a_linear_plugin_parameter(self):
        param = PluginParam("LowCut", 0.0, linear_hz)

        live_ops.set_parameter_value(param, "400 Hz")

        self.assertAlmostEqual(param.value, (400 - 10) / 1990, places=3)
        self.assertEqual(str(param), "400Hz")

    def test_log_mapping_and_units(self):
        param = PluginParam("HighCut", 1.0, log_hz)

        live_ops.set_parameter_value(param, "2 kHz")

        self.assertEqual(str(param), "2000.0 Hz")

    def test_probing_restores_the_value_before_the_final_set(self):
        param = PluginParam("LowCut", 0.5, linear_hz)

        raw = live_ops.value_for_display(param, "400 Hz")

        self.assertEqual(param.value, 0.5)
        self.assertNotEqual(raw, 0.5)
        self.assertLess(len(param.writes), 60)  # bounded probing

    def test_unmatched_text_restores_and_shows_the_range(self):
        param = PluginParam("Mode", 0.3, lambda raw: "Mode 1" if raw < 0.5 else "Mode 2")

        with self.assertRaisesRegex(LiveOpsError, "Use a raw value between 0.0 and 1.0"):
            live_ops.set_parameter_value(param, "400 Hz")

        self.assertEqual(param.value, 0.3)

    def test_constant_display_is_reported_without_guessing(self):
        param = PluginParam("Locked", 0.3, lambda raw: "12 Hz")

        with self.assertRaisesRegex(LiveOpsError, "shows '12 Hz' for every value"):
            live_ops.set_parameter_value(param, "400 Hz")

        self.assertEqual(param.value, 0.3)

    def test_native_parameters_never_probe(self):
        song = Song()
        utility = live_ops.handle(
            song, "ableton.insert_device", {"track": 0, "device_name": "Utility"}
        )
        gain = song.tracks[0].devices[0].parameters[1]
        gain.value = 0.0

        live_ops.handle(
            song,
            "ableton.set_device_parameter",
            {"track": 0, "device": "Utility", "parameter": "Gain", "value": "-3 dB"},
        )

        self.assertIsNotNone(utility)
        self.assertAlmostEqual(gain.value * 35, -3.0, places=1)


if __name__ == "__main__":
    unittest.main()
