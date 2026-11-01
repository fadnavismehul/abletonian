import unittest
from types import SimpleNamespace

import _bootstrap  # noqa: F401

from remote_scripts.Abletonian import live_ops
from remote_scripts.Abletonian.bridge_server import AbletonianBridgeControlSurface
from remote_scripts.Abletonian.live_ops import LiveOpsError


class Param:
    def __init__(self, name, value=0.0, low=0.0, high=1.0, items=None, display=None):
        self.name = name
        self.original_name = name
        self.value = value
        self.min = low
        self.max = high
        self.is_enabled = True
        self.is_quantized = items is not None
        self.value_items = tuple(items or ())
        self._display = display

    def str_for_value(self, value):
        if self.is_quantized:
            return self.value_items[int(value)]
        if self._display:
            return self._display(value)
        return f"{value:.2f}"


def gain_display(value):
    # Linear stand-in for Utility Gain: raw -1..1 shows as -35..35 dB.
    return f"{value * 35:.1f} dB"


def pan_display(value):
    if abs(value) < 1e-9:
        return "C"
    return f"{abs(value) * 50:.0f}{'L' if value < 0 else 'R'}"


class Routing:
    def __init__(self, display_name):
        self.display_name = display_name


class Track:
    def __init__(self, name, sends=2, group=None):
        self.name = name
        self.color_index = 0
        self.color = 0x112233
        self.is_foldable = False
        self.group_track = group
        self.mute = False
        self.solo = False
        self.devices = []
        self.available_output_routing_types = (Routing("Master"), Routing("Main"), Routing("Bus"))
        self.available_output_routing_channels = (Routing("Track In"), Routing("Post Mixer"))
        self.output_routing_type = self.available_output_routing_types[0]
        self.output_routing_channel = self.available_output_routing_channels[0]
        self.mixer_device = SimpleNamespace(
            volume=Param("Track Volume", 0.85, display=lambda v: f"{(v - 0.85) * 40:.1f} dB"),
            panning=Param("Track Panning", 0.0, -1.0, 1.0, display=pan_display),
            sends=tuple(Param(f"Send {i}") for i in range(sends)),
        )

    def insert_device(self, device_name, index):
        if device_name not in ("Utility", "Glue Compressor"):
            raise RuntimeError("unknown device")
        device = SimpleNamespace(
            name=device_name,
            class_name="StereoGain",
            class_display_name=device_name,
            is_active=True,
            can_have_chains=False,
            parameters=(
                Param("Device On", 1.0, items=("Off", "On")),
                Param("Gain", 0.0, -1.0, 1.0, display=gain_display),
            ),
        )
        self.devices.insert(index, device)


class Song:
    def __init__(self):
        self.tracks = (Track("Kick"), Track("Bass"), Track("Vox"))
        self.return_tracks = (Track("A-Reverb", sends=0), Track("B-Delay", sends=0))
        self.master_track = Track("Main", sends=0)
        self.undo_steps = []
        self.undone = 0
        self.can_undo = True

    def begin_undo_step(self):
        self.undo_steps.append("begin")

    def end_undo_step(self):
        self.undo_steps.append("end")

    def undo(self):
        self.undone += 1


class LiveOpsTests(unittest.TestCase):
    def setUp(self):
        self.song = Song()

    def call(self, method, **params):
        return live_ops.handle(self.song, method, params)

    def test_list_tracks_reports_routing_mixer_and_sends(self):
        result = self.call("ableton.list_tracks")

        names = [(t["kind"], t["name"]) for t in result["tracks"]]
        self.assertEqual(names[0], ("track", "Kick"))
        self.assertIn(("return", "A-Reverb"), names)
        self.assertEqual(names[-1], ("master", "Main"))
        kick = result["tracks"][0]
        self.assertEqual(kick["routing"]["output_routing_type"], "Master")
        self.assertEqual(kick["volume"]["display"], "0.0 dB")
        self.assertEqual([s["return"] for s in kick["sends"]], ["A-Reverb", "B-Delay"])
        self.assertEqual(kick["color"], "#112233")

    def test_resolves_tracks_by_index_name_return_letter_and_master(self):
        self.assertEqual(live_ops.resolve_track(self.song, 1)[2].name, "Bass")
        self.assertEqual(live_ops.resolve_track(self.song, "vox")[2].name, "Vox")
        self.assertEqual(live_ops.resolve_track(self.song, "B")[2].name, "B-Delay")
        self.assertEqual(live_ops.resolve_track(self.song, "return:0")[2].name, "A-Reverb")
        self.assertEqual(live_ops.resolve_track(self.song, "main")[0], "master")
        with self.assertRaises(LiveOpsError):
            live_ops.resolve_track(self.song, "Nope")

    def test_insert_device_at_end_and_set_gain_by_display(self):
        result = self.call(
            "ableton.insert_device",
            track="Kick",
            device_name="Utility",
            parameters={"Gain": "-3 dB"},
        )

        self.assertEqual(result["device"]["index"], 0)
        self.assertEqual(result["parameters_set"][0]["display"], "-3.0 dB")
        self.assertAlmostEqual(self.song.tracks[0].devices[0].parameters[1].value, -3 / 35, 4)

    def test_insert_device_rejects_out_of_range_index(self):
        with self.assertRaises(LiveOpsError):
            self.call("ableton.insert_device", track=0, device_name="Utility", index=5)

    def test_set_device_parameter_by_raw_value_and_option(self):
        self.call("ableton.insert_device", track=0, device_name="Utility")

        result = self.call(
            "ableton.set_device_parameter", track=0, device="utility", parameter="Gain", value=0.5
        )
        self.assertEqual(result["after"]["display"], "17.5 dB")
        self.call(
            "ableton.set_device_parameter", track=0, device=0, parameter="Device On", value="Off"
        )
        self.assertEqual(self.song.tracks[0].devices[0].parameters[0].value, 0.0)
        with self.assertRaises(LiveOpsError):
            self.call(
                "ableton.set_device_parameter", track=0, device=0, parameter="Gain", value=4.0
            )

    def test_set_output_routing_matches_display_name(self):
        result = self.call("ableton.set_track_output_routing", track="Bass", routing_type="main")

        self.assertEqual(result["before"]["output_routing_type"], "Master")
        self.assertEqual(result["after"]["output_routing_type"], "Main")
        with self.assertRaises(LiveOpsError):
            self.call("ableton.set_track_output_routing", track="Bass", routing_type="Drums")

    def test_set_track_properties_renames_and_colours(self):
        result = self.call(
            "ableton.set_track_properties", track=2, name="Lead Vox", color="#FF0000"
        )

        self.assertEqual(result["after"]["name"], "Lead Vox")
        self.assertEqual(self.song.tracks[2].color, 0xFF0000)

    def test_set_mixer_volume_pan_and_sends(self):
        result = self.call(
            "ableton.set_mixer",
            track="Vox",
            volume="-6 dB",
            panning="25L",
            sends={"A-Reverb": 0.3, "B": "0.10"},
        )

        self.assertEqual(result["changed"]["volume"]["display"], "-6.0 dB")
        self.assertEqual(result["changed"]["panning"]["display"], "25L")
        self.assertAlmostEqual(self.song.tracks[2].mixer_device.sends[0].value, 0.3)
        self.assertAlmostEqual(self.song.tracks[2].mixer_device.sends[1].value, 0.1, 3)

    def test_batch_groups_undo_and_stops_on_first_error(self):
        result = self.call(
            "ableton.batch",
            operations=[
                {
                    "method": "ableton.insert_device",
                    "params": {"track": i, "device_name": "Utility"},
                }
                for i in range(3)
            ]
            + [{"method": "ableton.set_track_properties", "params": {"track": "Missing"}}],
        )

        self.assertEqual(len(result["completed"]), 3)
        self.assertEqual(result["failed"]["index"], 3)
        self.assertEqual(self.song.undo_steps, ["begin", "end"])
        self.assertTrue(all(len(t.devices) == 1 for t in self.song.tracks))

    def test_batch_rejects_reads_and_nested_batches(self):
        with self.assertRaises(LiveOpsError):
            self.call("ableton.batch", operations=[{"method": "ableton.batch", "params": {}}])

    def test_list_devices_includes_parameters(self):
        self.call("ableton.insert_device", track=0, device_name="Utility")

        result = self.call("ableton.list_devices", track=0)

        device = result["tracks"][0]["devices"][0]
        self.assertEqual(device["name"], "Utility")
        self.assertEqual(device["parameters"][1]["name"], "Gain")
        self.assertEqual(device["parameters"][0]["options"], ["Off", "On"])

    def test_parse_display_number(self):
        self.assertEqual(live_ops.parse_display_number("-inf dB"), float("-inf"))
        self.assertEqual(live_ops.parse_display_number("2.5 kHz"), 2500.0)
        self.assertEqual(live_ops.parse_display_number("C"), 0.0)
        self.assertEqual(live_ops.parse_display_number("30R"), 30.0)

    def test_bridge_surface_dispatches_live_ops(self):
        surface = AbletonianBridgeControlSurface.__new__(AbletonianBridgeControlSurface)
        surface.song = self.song

        result = surface.handle_request("ableton.list_tracks", {"include_returns": False})

        self.assertEqual(len(result["tracks"]), 4)


if __name__ == "__main__":
    unittest.main()
