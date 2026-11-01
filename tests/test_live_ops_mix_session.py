"""Live Set operations requested in issue #13 (limits found in a real mix session)."""

import json
import unittest
from types import SimpleNamespace

import _bootstrap  # noqa: F401
from test_live_ops import Param, Song, Track

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

    def batch(self, *operations):
        return live_ops.handle(self.song, "ableton.batch", {"operations": list(operations)})

    def add_second_utility(self):
        live_ops.handle(self.song, "ableton.insert_device", {"track": 0, "device_name": "Utility"})
        self.assertEqual(
            [d.name for d in self.track.devices], ["Utility", "Glue Compressor", "Utility"]
        )

    def test_batch_deletes_by_index_refer_to_the_set_before_the_batch(self):
        # Review of PR #21: deleting 0 then 1 used to remove the third device.
        self.add_second_utility()

        result = self.batch(
            {
                "method": "ableton.delete_device",
                "params": {"track": 0, "device": 0, "confirm": True},
            },
            {
                "method": "ableton.delete_device",
                "params": {"track": 0, "device": 1, "confirm": True},
            },
        )

        self.assertIsNone(result["failed"])
        self.assertEqual(
            [r["device"]["name"] for r in result["completed"]], ["Utility", "Glue Compressor"]
        )
        self.assertEqual([d.name for d in self.track.devices], ["Utility"])
        self.assertIs(self.track.devices[0], self.track.devices[-1])

    def test_batch_deleting_the_same_device_twice_fails_the_second(self):
        result = self.batch(
            {
                "method": "ableton.delete_device",
                "params": {"track": 0, "device": 0, "confirm": True},
            },
            {
                "method": "ableton.delete_device",
                "params": {"track": 0, "device": "Utility", "confirm": True},
            },
        )

        self.assertEqual(result["failed"]["index"], 1)
        self.assertIn("no longer there", result["failed"]["error"])

    def test_batch_with_an_unconfirmed_delete_changes_nothing(self):
        for confirm in (None, False, "true"):
            params = {"track": 0, "device": 0}
            if confirm is not None:
                params["confirm"] = confirm
            with self.subTest(confirm=confirm):
                with self.assertRaisesRegex(LiveOpsError, 'needs "confirm": true'):
                    self.batch(
                        {
                            "method": "ableton.set_track_properties",
                            "params": {"track": 0, "name": "X"},
                        },
                        {"method": "ableton.delete_device", "params": params},
                    )
                self.assertEqual(self.track.name, "Kick")
                self.assertEqual(len(self.track.devices), 2)
        self.assertEqual(self.song.undo_steps, [])

    def test_batch_with_an_unknown_delete_target_changes_nothing(self):
        with self.assertRaisesRegex(LiveOpsError, "operation 1: no device named 'Limiter'"):
            self.batch(
                {"method": "ableton.set_track_properties", "params": {"track": 0, "name": "X"}},
                {
                    "method": "ableton.delete_device",
                    "params": {"track": 0, "device": "Limiter", "confirm": True},
                },
            )
        self.assertEqual(self.track.name, "Kick")

    def test_unknown_device_lists_the_choices(self):
        with self.assertRaisesRegex(LiveOpsError, "Devices: Utility, Glue Compressor"):
            self.delete(device="Limiter", confirm=True)


class LiveProxy:
    """A fresh wrapper per read, as Live's Python API hands out for LOM objects.

    Two wrappers of the same device are equal and share ``_live_ptr`` but are
    not the same Python object.
    """

    def __init__(self, target):
        object.__setattr__(self, "_target", target)
        object.__setattr__(self, "_live_ptr", id(target))

    def __getattr__(self, name):
        return getattr(self._target, name)

    def __eq__(self, other):
        return isinstance(other, LiveProxy) and other._live_ptr == self._live_ptr

    def __hash__(self):
        return self._live_ptr


class ProxyTrack(Track):
    @property
    def devices(self):
        return tuple(LiveProxy(device) for device in self._devices)

    @devices.setter
    def devices(self, value):
        self._devices = list(value)

    def insert_device(self, device_name, index):
        devices = self._devices
        Track.insert_device(SimpleNamespace(devices=devices), device_name, index)

    def delete_device(self, index):
        del self._devices[index]


class DeleteDeviceLiveProxyTests(unittest.TestCase):
    """Found in Live 12.4: every delete failed with "is no longer there",
    because a device read twice from the LOM is equal but not identical."""

    def setUp(self):
        self.song = Song()
        self.song.tracks = (ProxyTrack("1-Audio"),)
        for name in ("Utility", "Glue Compressor", "Utility"):
            live_ops.handle(self.song, "ableton.insert_device", {"track": 0, "device_name": name})
        self.track = self.song.tracks[0]

    def names(self):
        return [d.name for d in self.track.devices]

    def test_preview_and_delete_work_when_each_read_gives_a_new_wrapper(self):
        preview = live_ops.handle(
            self.song, "ableton.delete_device", {"track": 0, "device": "Glue Compressor"}
        )
        self.assertFalse(preview["deleted"])
        self.assertEqual(preview["would_delete"]["device"]["index"], 1)

        result = live_ops.handle(
            self.song,
            "ableton.delete_device",
            {"track": 0, "device": "Glue Compressor", "confirm": True},
        )
        self.assertTrue(result["deleted"])
        self.assertEqual(self.names(), ["Utility", "Utility"])

    def test_batch_deletes_by_index_still_refer_to_the_set_before_the_batch(self):
        result = live_ops.handle(
            self.song,
            "ableton.batch",
            {
                "operations": [
                    {
                        "method": "ableton.delete_device",
                        "params": {"track": 0, "device": 0, "confirm": True},
                    },
                    {
                        "method": "ableton.delete_device",
                        "params": {"track": 0, "device": 1, "confirm": True},
                    },
                ]
            },
        )

        self.assertIsNone(result["failed"])
        self.assertEqual(self.names(), ["Utility"])

    def test_a_failed_insert_removes_only_the_new_device(self):
        with self.assertRaises(LiveOpsError):
            live_ops.handle(
                self.song,
                "ableton.insert_device",
                {
                    "track": 0,
                    "device_name": "Glue Compressor",
                    "index": 3,
                    "parameters": {"No Such Parameter": 1},
                },
            )

        self.assertEqual(self.names(), ["Utility", "Glue Compressor", "Utility"])
        self.assertEqual(len({d._live_ptr for d in self.track.devices}), 3)


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


def plain(name, value=1.0):
    return SimpleNamespace(
        name=name,
        class_name="Reverb",
        can_have_chains=False,
        parameters=(Param("Device On", value, items=("Off", "On")),),
    )


class Chain:
    def __init__(self, name, devices):
        self.name = name
        self.devices = list(devices)

    def delete_device(self, index):
        del self.devices[index]


def rack(name, chains, return_chains=(), class_name="InstrumentGroupDevice"):
    return SimpleNamespace(
        name=name,
        class_name=class_name,
        can_have_chains=True,
        chains=tuple(chains),
        return_chains=tuple(return_chains),
        parameters=(Param("Device On", 1.0, items=("Off", "On")),),
    )


class NestedDeviceTests(unittest.TestCase):
    """Issue #17."""

    def setUp(self):
        self.song = Song()
        self.track = self.song.tracks[0]
        self.inner = rack("Inner Rack", [Chain("Deep", [plain("Reverb")])])
        self.synth = rack(
            "Drama Synth",
            [Chain("Piano", [plain("Reverb"), plain("Echo")]), Chain("Pad", [self.inner])],
        )
        self.kit = rack(
            "Kit",
            [Chain("Kick", [plain("Saturator")])],
            return_chains=[Chain("Room", [plain("Limiter")])],
            class_name="DrumGroupDevice",
        )
        self.track.devices = [self.synth, self.kit, plain("Slash/Name")]

    def turn_off(self, device):
        return live_ops.handle(
            self.song,
            "ableton.set_device_parameter",
            {"track": 0, "device": device, "parameter": "Device On", "value": "Off"},
        )

    def test_sets_a_parameter_inside_a_rack_chain(self):
        result = self.turn_off("Drama Synth/Piano/Reverb")

        self.assertEqual(result["device"]["path"], "Drama Synth/Piano/Reverb")
        self.assertEqual(self.synth.chains[0].devices[0].parameters[0].value, 0.0)
        self.assertEqual(self.synth.chains[0].devices[1].parameters[0].value, 1.0)

    def test_nested_racks_indexes_and_case(self):
        result = self.turn_off("0/pad/inner rack/0/0")

        self.assertEqual(result["device"]["path"], "Drama Synth/Pad/Inner Rack/Deep/Reverb")
        self.assertEqual(self.inner.chains[0].devices[0].parameters[0].value, 0.0)

    def test_drum_rack_return_chains(self):
        result = self.turn_off("Kit/returns/Room/Limiter")

        self.assertEqual(result["device"]["path"], "Kit/returns/Room/Limiter")
        self.assertEqual(self.kit.return_chains[0].devices[0].parameters[0].value, 0.0)

    def test_a_top_level_name_with_a_slash_still_works(self):
        self.assertEqual(self.turn_off("Slash/Name")["device"]["path"], "Slash/Name")

    def test_errors_name_the_place_and_the_choices(self):
        cases = {
            "Drama Synth/Drums/Reverb": "no chain 'Drums' in 'Drama Synth'. Choices: 0:Piano",
            "Drama Synth/Piano/Delay": "no device 'Delay' in 'Drama Synth/Piano'",
            "Drama Synth/Piano": "ends at a chain",
            "Drama Synth/Piano/Reverb/X/Y": "is not a Rack",
            "Kit/returns": "needs a return chain",
            "Drama Synth//Reverb": "empty part",
        }
        for path, message in cases.items():
            with self.subTest(path=path), self.assertRaisesRegex(LiveOpsError, message):
                self.turn_off(path)

    def test_list_devices_shows_nested_devices_and_return_chains_with_paths(self):
        result = live_ops.handle(
            self.song, "ableton.list_devices", {"track": 0, "include_parameters": False}
        )

        synth, kit, _ = result["tracks"][0]["devices"]
        self.assertEqual(
            [d["path"] for d in synth["chains"][0]["devices"]],
            ["Drama Synth/Piano/Reverb", "Drama Synth/Piano/Echo"],
        )
        inner = synth["chains"][1]["devices"][0]
        self.assertEqual(
            inner["chains"][0]["devices"][0]["path"], "Drama Synth/Pad/Inner Rack/Deep/Reverb"
        )
        self.assertEqual(kit["return_chains"][0]["devices"][0]["path"], "Kit/returns/Room/Limiter")

    def test_deletes_a_device_inside_a_chain(self):
        preview = live_ops.handle(
            self.song, "ableton.delete_device", {"track": 0, "device": "Kit/returns/Room/Limiter"}
        )
        self.assertFalse(preview["deleted"])
        self.assertEqual(len(self.kit.return_chains[0].devices), 1)

        result = live_ops.handle(
            self.song,
            "ableton.delete_device",
            {"track": 0, "device": "Drama Synth/Piano/Echo", "confirm": True},
        )

        self.assertTrue(result["deleted"])
        self.assertEqual([d.name for d in self.synth.chains[0].devices], ["Reverb"])
        self.assertEqual(len(self.track.devices), 3)


if __name__ == "__main__":
    unittest.main()
