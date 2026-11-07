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


def time_display(value):
    # Log-style time: raw 0..1 maps 1 ms..60 s and switches unit at 1 s.
    seconds = 0.001 * (60000 ** value)
    return f"{seconds * 1000:.0f} ms" if seconds < 1 else f"{seconds:.2f} s"


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
                Param("Output", 0.0, -1.0, 1.0, display=gain_display),
            ),
        )
        self.devices.insert(index, device)

    def delete_device(self, index):
        del self.devices[index]


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


def macro_param(index, name=None, value=0.0):
    param = Param(name or f"Macro {index}", value, 0.0, 127.0, display=lambda v: f"{v:.0f}")
    param.original_name = f"Macro {index}"
    return param


def instrument_rack(name="Keys Rack", names=None, mapped=None, visible=8):
    names = names or {}
    mapped = mapped if mapped is not None else (True,) * 16
    return SimpleNamespace(
        name=name,
        class_name="InstrumentGroupDevice",
        class_display_name="Instrument Rack",
        can_have_chains=True,
        chains=(SimpleNamespace(name="Piano", devices=()),),
        visible_macro_count=visible,
        macros_mapped=tuple(mapped),
        parameters=(
            Param("Device On", 1.0, items=("Off", "On")),
            *(macro_param(i, names.get(i), float(i)) for i in range(1, 17)),
        ),
    )


def utility():
    return SimpleNamespace(
        name="Utility", class_name="StereoGain", can_have_chains=False, parameters=()
    )


class RackMacroTests(unittest.TestCase):
    def setUp(self):
        self.song = Song()
        self.track = self.song.tracks[1]
        self.rack = instrument_rack(
            names={1: "Brightness", 2: "Drive"},
            mapped=(True, True, False) + (True,) * 13,
        )
        self.track.devices = [utility(), self.rack]
        self.track.view = SimpleNamespace(selected_device=self.track.devices[0])
        self.song.view = SimpleNamespace(selected_track=self.track)

    def read(self, **params):
        return live_ops.handle(self.song, "ableton.get_selected_rack_macros", params)

    def test_reads_visible_macros_of_the_selected_tracks_rack(self):
        result = self.read()

        self.assertEqual(result["track"], {"kind": "track", "index": 1, "name": "Bass",
                                           "color": "#112233"})
        self.assertEqual(result["device"]["index"], 1)
        self.assertEqual(result["device"]["type"], "rack")
        self.assertEqual(result["device"]["chain_names"], ["Piano"])
        self.assertEqual(result["selection"], "first_rack_on_track")
        self.assertEqual(len(result["macros"]), 8)
        first, _, third = result["macros"][:3]
        self.assertEqual(
            (first["index"], first["name"], first["original_name"], first["value"]),
            (1, "Brightness", "Macro 1", 1.0),
        )
        self.assertEqual(first["display"], "1")
        self.assertFalse(third["is_mapped"])

    def test_prefers_the_selected_rack_and_accepts_explicit_refs(self):
        self.track.view.selected_device = self.rack
        self.assertEqual(self.read()["selection"], "selected_device")

        result = self.read(track="Bass", device=1)
        self.assertEqual(result["selection"], "explicit")

    def test_reading_macros_does_not_change_the_set(self):
        before = [p.value for p in self.rack.parameters]

        self.read()

        self.assertEqual([p.value for p in self.rack.parameters], before)
        self.assertEqual(self.song.undo_steps, [])

    def test_rejects_tracks_and_devices_that_are_not_racks(self):
        self.track.devices = [utility()]
        with self.assertRaisesRegex(LiveOpsError, "has no Rack"):
            self.read()
        with self.assertRaisesRegex(LiveOpsError, "is not a Rack"):
            self.read(track="Bass", device=0)

    def test_without_macros_mapped_reads_up_to_sixteen_macros(self):
        del self.rack.macros_mapped
        del self.rack.visible_macro_count

        macros = self.read()["macros"]

        self.assertEqual(len(macros), 16)
        self.assertIsNone(macros[0]["is_mapped"])


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

    def test_insert_device_removes_device_when_a_parameter_fails(self):
        with self.assertRaises(LiveOpsError) as raised:
            self.call(
                "ableton.insert_device",
                track=0,
                device_name="Utility",
                parameters={"Width": "50 %"},
            )

        self.assertIn("removed again", str(raised.exception))
        self.assertEqual(self.song.tracks[0].devices, [])

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
        self.assertEqual(device["parameters"][1]["name"], "Output")
        self.assertEqual(device["parameters"][0]["options"], ["Off", "On"])

    def test_parse_display_number(self):
        self.assertEqual(live_ops.parse_display_number("-inf dB"), float("-inf"))
        self.assertEqual(live_ops.parse_display_number("2.5 kHz"), 2500.0)
        self.assertEqual(live_ops.parse_display_number("C"), 0.0)
        self.assertEqual(live_ops.parse_display_number("30R"), 30.0)

    def test_display_values_follow_unit_changes(self):
        decay = Param("Decay", 0.0, display=time_display)

        live_ops.set_parameter_value(decay, "500 ms")
        self.assertEqual(time_display(decay.value), "500 ms")
        live_ops.set_parameter_value(decay, "1.5 s")
        self.assertEqual(time_display(decay.value), "1.50 s")

    def test_display_value_that_cannot_be_matched_raises(self):
        # Not monotonic: shows 10 at both ends and 0 in the middle.
        odd = Param("Odd", 0.0, display=lambda v: f"{abs(v - 0.5) * 20:.1f}")

        with self.assertRaises(LiveOpsError):
            live_ops.set_parameter_value(odd, "3")

    def test_quantized_parameter_without_options_uses_numbers(self):
        steps = Param("Transpose", 0.0, -48.0, 48.0, display=lambda v: f"{v:.0f} st")
        steps.is_quantized = True

        live_ops.set_parameter_value(steps, "12 st")

        self.assertEqual(steps.value, 12.0)

    def test_numeric_strings_select_device_and_parameter_by_index(self):
        self.call("ableton.insert_device", track=0, device_name="Utility")

        result = self.call(
            "ableton.set_device_parameter", track="0", device="0", parameter="1", value=0.5
        )

        self.assertEqual(result["after"]["name"], "Output")

    def test_real_track_names_win_over_shorthand(self):
        self.song.tracks[0].name = "808"
        self.song.tracks[1].name = "A"

        self.assertEqual(live_ops.resolve_track(self.song, "808")[1], 0)
        self.assertEqual(live_ops.resolve_track(self.song, "A")[:2], ("track", 1))
        self.assertEqual(live_ops.resolve_track(self.song, "B")[0], "return")

    def test_set_mixer_checks_everything_before_changing(self):
        master_volume = self.song.master_track.mixer_device.volume.value

        with self.assertRaises(LiveOpsError):
            self.call("ableton.set_mixer", track="main", volume="-3 dB", mute=True)
        with self.assertRaises(LiveOpsError):
            self.call("ableton.set_mixer", track=0, volume="-3 dB", sends={"Z-Missing": 0.5})

        self.assertEqual(self.song.master_track.mixer_device.volume.value, master_volume)
        self.assertEqual(self.song.tracks[0].mixer_device.volume.value, 0.85)

    def test_routing_reverts_type_when_channel_is_unknown(self):
        with self.assertRaises(LiveOpsError):
            self.call(
                "ableton.set_track_output_routing",
                track=0,
                routing_type="Main",
                routing_channel="Nope",
            )

        self.assertEqual(self.song.tracks[0].output_routing_type.display_name, "Master")

    def test_insert_device_finds_device_that_live_placed_elsewhere(self):
        track = self.song.tracks[0]
        track.devices = [SimpleNamespace(name="Synth", parameters=())]
        original_insert = track.insert_device

        def insert_at_end(device_name, index):
            original_insert(device_name, len(track.devices))

        track.insert_device = insert_at_end

        with self.assertRaises(LiveOpsError):
            self.call(
                "ableton.insert_device",
                track=0,
                device_name="Utility",
                index=0,
                parameters={"Missing": 1},
            )

        self.assertEqual([d.name for d in track.devices], ["Synth"])

    def test_list_devices_for_whole_set_skips_parameters_by_default(self):
        self.call("ableton.insert_device", track=0, device_name="Utility")

        result = self.call("ableton.list_devices")

        self.assertNotIn("parameters", result["tracks"][0]["devices"][0])

    def test_bridge_surface_dispatches_live_ops(self):
        surface = AbletonianBridgeControlSurface.__new__(AbletonianBridgeControlSurface)
        surface.song = self.song

        result = surface.handle_request("ableton.list_tracks", {"include_returns": False})

        self.assertEqual(len(result["tracks"]), 4)


def named_device(name, class_name="Compressor2"):
    return SimpleNamespace(
        name=name,
        class_name=class_name,
        can_have_chains=False,
        parameters=(Param("Device On", 1.0, items=("Off", "On")),),
    )


def chain(name, devices):
    return SimpleNamespace(name=name, devices=list(devices))


def rack(name, chains, return_chains=(), class_name="AudioEffectGroupDevice"):
    return SimpleNamespace(
        name=name,
        class_name=class_name,
        can_have_chains=True,
        chains=tuple(chains),
        return_chains=tuple(return_chains),
        parameters=(Param("Device On", 1.0, items=("Off", "On")),),
    )


class RenameDeviceTests(unittest.TestCase):
    """Issue #46: Device.name and Chain.name are read/write (Cycling '74 LOM docs)."""

    def setUp(self):
        self.song = Song()
        self.track = self.song.tracks[2]
        self.inner = rack("Inner", [chain("Deep", [named_device("Reverb", "Reverb")])])
        self.vocal_rack = rack(
            "Vocal Rack",
            [chain("Main", [named_device("Compressor"), self.inner]), chain("Air", [])],
        )
        self.kit = rack(
            "Kit",
            [chain("Kick", [])],
            return_chains=[chain("Room", [named_device("Limiter", "Limiter")])],
            class_name="DrumGroupDevice",
        )
        self.track.devices = [
            named_device("Compressor"),
            named_device("Compressor"),
            self.vocal_rack,
            self.kit,
        ]

    def rename(self, device, name):
        return live_ops.handle(
            self.song,
            "ableton.set_device_properties",
            {"track": "Vox", "device": device, "name": name},
        )

    def rename_chain(self, path, name):
        return live_ops.handle(
            self.song,
            "ableton.set_chain_properties",
            {"track": "Vox", "chain": path, "name": name},
        )

    def test_renames_a_duplicate_top_level_device_and_reports_new_paths(self):
        result = self.rename("#1", "De-esser")

        self.assertEqual(self.track.devices[1].name, "De-esser")
        self.assertEqual(result["before"], {"name": "Compressor", "path": "1"})
        self.assertEqual(result["after"], {"name": "De-esser", "path": "De-esser"})
        self.assertEqual(result["device"]["index"], 1)
        # The other Compressor is unique now, so list_devices prints it by name.
        listed = live_ops.handle(self.song, "ableton.list_devices", {"track": "Vox"})
        paths = [d["path"] for d in listed["tracks"][0]["devices"]]
        self.assertEqual(paths, ["Compressor", "De-esser", "Vocal Rack", "Kit"])
        self.assertEqual(self.song.undo_steps, ["begin", "end"])

    def test_renames_a_device_inside_nested_racks(self):
        result = self.rename("Vocal Rack/Main/Inner/Deep/Reverb", "Plate")

        self.assertEqual(self.inner.chains[0].devices[0].name, "Plate")
        self.assertEqual(result["after"]["path"], "Vocal Rack/Main/Inner/Deep/Plate")
        _path, _index, device, _owner = live_ops.resolve_device_path(
            self.track, result["after"]["path"]
        )
        self.assertIs(device, self.inner.chains[0].devices[0])

    def test_renaming_a_rack_changes_the_paths_below_it(self):
        result = self.rename("Vocal Rack", "Vox Chain")

        self.assertEqual(result["after"]["path"], "Vox Chain")
        self.assertEqual(
            live_ops.resolve_device_path(self.track, "Vox Chain/Main/Compressor")[2],
            self.vocal_rack.chains[0].devices[0],
        )

    def test_rejects_empty_names_and_missing_devices_without_changing_anything(self):
        for name in ("", "   ", 5):
            with self.subTest(name=name), self.assertRaisesRegex(LiveOpsError, "non-empty"):
                self.rename(0, name)
        with self.assertRaisesRegex(LiveOpsError, "missing required parameter 'name'"):
            live_ops.handle(
                self.song, "ableton.set_device_properties", {"track": "Vox", "device": 0}
            )
        with self.assertRaisesRegex(LiveOpsError, "no device 'Gate'"):
            self.rename("Vocal Rack/Main/Gate", "X")
        self.assertEqual([d.name for d in self.track.devices][:2], ["Compressor", "Compressor"])

    def test_renames_a_rack_chain(self):
        result = self.rename_chain("Vocal Rack/Main", "Body")

        self.assertEqual(self.vocal_rack.chains[0].name, "Body")
        self.assertEqual(result["before"], {"name": "Main", "path": "Vocal Rack/Main"})
        self.assertEqual(result["after"], {"name": "Body", "path": "Vocal Rack/Body"})
        self.assertEqual(result["rack"], {"name": "Vocal Rack", "path": "Vocal Rack"})
        self.assertFalse(result["chain"]["is_return_chain"])
        self.assertEqual(
            live_ops.resolve_device_path(self.track, "Vocal Rack/Body/Compressor")[2],
            self.vocal_rack.chains[0].devices[0],
        )

    def test_renames_by_index_nested_and_return_chains(self):
        self.assertEqual(self.rename_chain("2/1", "Shine")["after"]["path"], "Vocal Rack/Shine")
        nested = self.rename_chain("Vocal Rack/Main/Inner/0", "Tail")
        self.assertEqual(nested["after"]["path"], "Vocal Rack/Main/Inner/Tail")
        returns = self.rename_chain("Kit/returns/Room", "Hall")
        self.assertEqual(self.kit.return_chains[0].name, "Hall")
        self.assertEqual(returns["after"]["path"], "Kit/returns/Hall")
        self.assertTrue(returns["chain"]["is_return_chain"])

    def test_a_chain_name_that_would_be_misread_is_printed_by_index(self):
        result = self.rename_chain("Vocal Rack/Air", "returns")

        self.assertEqual(result["after"]["path"], "Vocal Rack/1")

    def test_chain_errors_name_the_rack_and_choices(self):
        cases = {
            "Vocal Rack": "needs a rack and a chain",
            "Compressor/Main": "ambiguous",
            "#0/Main": "is not a Rack",
            "Vocal Rack/Drums": "no chain 'Drums' in 'Vocal Rack'. Choices: 0:Main, 1:Air",
            "Kit/returns/Nope": "no return chain 'Nope'",
            "Vocal Rack/": "empty part",
        }
        for path, message in cases.items():
            with self.subTest(path=path), self.assertRaisesRegex(LiveOpsError, message):
                self.rename_chain(path, "X")

    def test_renames_run_inside_a_batch(self):
        result = live_ops.handle(
            self.song,
            "ableton.batch",
            {
                "operations": [
                    {
                        "method": "ableton.set_device_properties",
                        "params": {"track": 2, "device": "#1", "name": "De-esser"},
                    },
                    {
                        "method": "ableton.set_chain_properties",
                        "params": {"track": 2, "chain": "Vocal Rack/Air", "name": "Shine"},
                    },
                ]
            },
        )

        self.assertIsNone(result["failed"])
        self.assertEqual(self.track.devices[1].name, "De-esser")
        self.assertEqual(self.vocal_rack.chains[1].name, "Shine")

    def test_insert_device_can_name_the_new_device(self):
        result = live_ops.handle(
            self.song,
            "ableton.insert_device",
            {"track": 0, "device_name": "Glue Compressor", "name": "Bus Glue"},
        )

        self.assertEqual(self.song.tracks[0].devices[0].name, "Bus Glue")
        self.assertEqual(result["device"]["name"], "Bus Glue")
        self.assertEqual(result["device"]["path"], "Bus Glue")

    def test_insert_device_with_an_empty_name_inserts_nothing(self):
        with self.assertRaisesRegex(LiveOpsError, "non-empty"):
            live_ops.handle(
                self.song,
                "ableton.insert_device",
                {"track": 0, "device_name": "Utility", "name": " "},
            )
        self.assertEqual(self.song.tracks[0].devices, [])


class NoColourTrack(Track):
    """A track whose colour cannot be set, to test fail-closed cleanup."""

    @property
    def color(self):
        return 0

    @color.setter
    def color(self, value):
        if value != 0x112233:  # Track.__init__ sets this one
            raise RuntimeError("colour refused")


class TrackSong(Song):
    """Song.create_midi_track / create_audio_track / delete_track (Cycling '74 LOM)."""

    def __init__(self, track_class=Track):
        super().__init__()
        self.track_class = track_class
        self.created = []
        self.deleted = []

    def _create(self, kind, index):
        tracks = list(self.tracks)
        if not -1 <= index <= len(tracks):
            raise RuntimeError("Index out of range")
        position = len(tracks) if index == -1 else index
        track = self.track_class(f"{position + 1}-{kind}")
        track.has_midi_input = kind == "MIDI"
        tracks.insert(position, track)
        self.tracks = tuple(tracks)
        self.created.append((kind, index))

    def create_midi_track(self, index):
        self._create("MIDI", index)

    def create_audio_track(self, index):
        self._create("Audio", index)

    def delete_track(self, index):
        tracks = list(self.tracks)
        del tracks[index]
        self.tracks = tuple(tracks)
        self.deleted.append(index)


class CreateTrackTests(unittest.TestCase):
    """Issue #47."""

    def setUp(self):
        self.song = TrackSong()

    def create(self, **params):
        return live_ops.handle(self.song, "ableton.create_track", params)

    def test_appends_a_midi_track_by_default(self):
        result = self.create(kind="midi")

        self.assertEqual(self.song.created, [("MIDI", -1)])
        self.assertEqual([t.name for t in self.song.tracks][-1], "4-MIDI")
        self.assertEqual(result["track_type"], "midi")
        self.assertEqual(result["track"]["kind"], "track")
        self.assertEqual(result["track"]["index"], 3)
        self.assertEqual(result["track"]["name"], "4-MIDI")
        self.assertNotIn("note", result)
        self.assertEqual(self.song.undo_steps, ["begin", "end"])

    def test_result_is_shaped_like_compact_list_tracks(self):
        result = self.create(kind="audio", name="Vox Double")

        listed = live_ops.handle(self.song, "ableton.list_tracks", {"detail": "compact"})
        self.assertEqual(result["track"], listed["tracks"][3])

    def test_inserts_named_and_coloured_audio_track_at_an_index(self):
        result = self.create(kind="Audio", name="Vox Double", index=1, color="#FF0000")

        self.assertEqual(self.song.created, [("Audio", 1)])
        self.assertEqual(
            [t.name for t in self.song.tracks], ["Kick", "Vox Double", "Bass", "Vox"]
        )
        self.assertEqual(self.song.tracks[1].color, 0xFF0000)
        self.assertEqual(result["track"]["index"], 1)
        self.assertEqual(result["track"]["color"], "#FF0000")
        self.assertIn("moved down by one", result["note"])

    def test_sets_a_palette_colour_index(self):
        self.create(kind="midi", color_index=12)

        self.assertEqual(self.song.tracks[-1].color_index, 12)

    def test_bad_arguments_create_nothing(self):
        cases = [
            ({"kind": "group"}, "must be 'midi' or 'audio'"),
            ({"kind": "midi", "index": 9}, "out of range"),
            ({"kind": "midi", "index": -2}, "out of range"),
            ({"kind": "midi", "index": True}, "out of range"),
            ({"kind": "midi", "name": " "}, "non-empty"),
            ({"kind": "midi", "color": "red"}, "color must be"),
            ({"kind": "midi", "color_index": "3"}, "whole number"),
            ({}, "missing required parameter 'kind'"),
        ]
        for params, message in cases:
            with self.subTest(params=params), self.assertRaisesRegex(LiveOpsError, message):
                self.create(**params)
        self.assertEqual(self.song.created, [])
        self.assertEqual(len(self.song.tracks), 3)

    def test_a_failed_setup_deletes_the_new_track(self):
        self.song = TrackSong(track_class=NoColourTrack)
        self.song.tracks = (Track("Kick"), Track("Bass"))

        with self.assertRaisesRegex(LiveOpsError, "removed again"):
            self.create(kind="audio", name="Temp", index=0, color="#00FF00")

        self.assertEqual(self.song.deleted, [0])
        self.assertEqual([t.name for t in self.song.tracks], ["Kick", "Bass"])
        self.assertEqual(self.song.undo_steps, ["begin", "end"])

    def test_live_errors_and_missing_calls_are_reported(self):
        with self.assertRaisesRegex(LiveOpsError, "cannot create midi tracks"):
            live_ops.handle(Song(), "ableton.create_track", {"kind": "midi"})

        def refuse(index):
            raise RuntimeError("no room")

        self.song.create_audio_track = refuse
        with self.assertRaisesRegex(LiveOpsError, "could not create a new audio track: no room"):
            self.create(kind="audio")

    def test_runs_inside_a_batch(self):
        result = live_ops.handle(
            self.song,
            "ableton.batch",
            {
                "operations": [
                    {"method": "ableton.create_track", "params": {"kind": "midi", "name": "Keys"}},
                    {"method": "ableton.set_mixer", "params": {"track": "Keys", "mute": True}},
                ]
            },
        )

        self.assertIsNone(result["failed"])
        self.assertTrue(self.song.tracks[-1].mute)
        self.assertEqual(self.song.undo_steps, ["begin", "end"])


if __name__ == "__main__":
    unittest.main()
