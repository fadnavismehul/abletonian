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


# Issues #43 and #44: how a caller's value becomes a raw Live value. --------


class StepParam(Param):
    """A stepped parameter shaped like Glue Compressor's Release or Echo's
    "L Synced": an integer raw range, display text from ``str_for_value``,
    and (as reported in Live 12.4.16, issue #44) no ``value_items``.
    ``writes`` records every write so tests can check lookups never write.
    """

    def __init__(self, name, labels, value=0.0, quantized=True, constant=None):
        super().__init__(name, value, 0.0, float(len(labels) - 1))
        self.is_quantized = quantized
        self.value_items = ()
        self.labels = tuple(labels)
        self.constant = constant
        self.writes = []

    def __setattr__(self, key, value):
        if key == "value" and "writes" in self.__dict__:
            self.writes.append(value)
        object.__setattr__(self, key, value)

    def str_for_value(self, value):
        if self.constant is not None:
            return self.constant
        return self.labels[int(round(value))]


def q_display(value):
    # EQ Eight Q stand-in: raw 0..1 shows 0.10..18.00 with no unit.
    return f"{0.1 * 180 ** value:.2f}"


GLUE_RELEASE = (".1", ".2", ".4", ".6", ".8", "1.2", "A")
GLUE_ATTACK = (".01", ".1", ".3", "1", "3", "10", "30")
ECHO_SYNCED = ("1/64", "1/32", "1/16", "1/8", "1/4", "1/2", "1")


class BareNumberTests(unittest.TestCase):
    """Issue #43: a bare number is not silently read as raw when that is ambiguous."""

    def setUp(self):
        self.q = Param("2 Q A", 0.5, display=q_display)

    def test_ambiguous_bare_number_is_refused_with_both_readings(self):
        with self.assertRaises(LiveOpsError) as raised:
            live_ops.set_parameter_value(self.q, 1)

        message = str(raised.exception)
        self.assertIn("ambiguous", message)
        self.assertIn("'18.00'", message)
        self.assertIn("'1.00'", message)
        self.assertIn('{"raw": 1}', raised.exception.hint)
        self.assertIn('"1"', raised.exception.hint)
        self.assertEqual(self.q.value, 0.5)

    def test_display_text_and_explicit_raw(self):
        live_ops.set_parameter_value(self.q, "1.00")
        self.assertEqual(q_display(self.q.value), "1.00")

        reading = live_ops.set_parameter_value(self.q, {"raw": 1.0})
        self.assertEqual(self.q.value, 1.0)
        self.assertEqual(reading["read_as"], "raw")

    def test_explicit_raw_is_range_checked_and_shape_checked(self):
        with self.assertRaisesRegex(LiveOpsError, "outside"):
            live_ops.set_parameter_value(self.q, {"raw": 3})
        for bad in ({"raw": "1"}, {"raw": 1, "display": "1"}, {"value": 1}, [1], None):
            with self.subTest(bad=bad), self.assertRaises(LiveOpsError):
                live_ops.set_parameter_value(self.q, bad)
        self.assertEqual(self.q.value, 0.5)

    def test_number_outside_raw_range_is_read_as_display(self):
        reading = live_ops.set_parameter_value(self.q, 3)

        self.assertEqual(q_display(self.q.value), "3.00")
        self.assertEqual(reading["read_as"], "display")
        self.assertIn("outside the raw range", reading["note"])

    def test_raw_and_display_that_agree_keep_working(self):
        knob = Param("Amount", 0.0, 0.0, 127.0, display=lambda v: f"{v:.0f}")

        reading = live_ops.set_parameter_value(knob, 64)

        self.assertEqual(knob.value, 64.0)
        self.assertEqual(reading, {"raw": 64.0, "read_as": "raw", "note": None})

    def test_unit_display_keeps_raw_reading_with_a_note(self):
        gain = Param("Output", 0.0, -1.0, 1.0, display=gain_display)

        reading = live_ops.set_parameter_value(gain, 0.5)

        self.assertEqual(gain.value, 0.5)
        self.assertEqual(reading["read_as"], "raw")
        self.assertIn("'17.5 dB'", reading["note"])

    def test_out_of_range_unit_number_names_the_display_reading(self):
        gain = Param("Output", 0.0, -1.0, 1.0, display=gain_display)

        with self.assertRaises(LiveOpsError) as raised:
            live_ops.set_parameter_value(gain, -6)

        self.assertIn("outside", str(raised.exception))
        self.assertIn("'-6.0 dB'", raised.exception.hint)
        self.assertEqual(gain.value, 0.0)

    def test_option_steps_take_the_step_number_without_a_note(self):
        switch = Param("Device On", 1.0, items=("Off", "On"))

        reading = live_ops.set_parameter_value(switch, 0)

        self.assertEqual(switch.value, 0.0)
        self.assertIsNone(reading["note"])

    def test_set_device_parameter_reports_how_the_value_was_read(self):
        song = Song()
        song.tracks[0].devices = [
            SimpleNamespace(
                name="EQ Eight",
                class_name="Eq8",
                can_have_chains=False,
                parameters=(Param("Device On", 1.0, items=("Off", "On")), self.q),
            )
        ]
        params = {"track": 0, "device": 0, "parameter": "2 Q A"}

        result = live_ops.handle(song, "ableton.set_device_parameter", {**params, "value": "1.00"})
        self.assertEqual(result["after"]["display"], "1.00")
        self.assertEqual(result["read_as"], "display")
        with self.assertRaisesRegex(LiveOpsError, "ambiguous"):
            live_ops.handle(song, "ableton.set_device_parameter", {**params, "value": 1})
        self.assertEqual(q_display(self.q.value), "1.00")


class SteppedParameterTests(unittest.TestCase):
    """Issue #44: stepped parameters resolve by step name and list their steps."""

    def test_glue_release_resolves_auto_and_numbers(self):
        for quantized in (True, False):
            release = StepParam("Release", GLUE_RELEASE, quantized=quantized)
            with self.subTest(quantized=quantized):
                for text, raw in (("Auto", 6.0), ("A", 6.0), ("0.1", 0.0), ("1.2", 5.0)):
                    self.assertEqual(live_ops.value_for_display(release, text), raw)
                self.assertEqual(release.writes, [])

    def test_glue_release_lists_each_step_as_an_option(self):
        release = StepParam("Release", GLUE_RELEASE, quantized=False)

        self.assertEqual(live_ops._param_payload(release)["options"], list(GLUE_RELEASE))

    def test_glue_release_bare_number_with_no_matching_step_is_raw(self):
        release = StepParam("Release", GLUE_RELEASE)

        reading = live_ops.set_parameter_value(release, 1)

        self.assertEqual(release.value, 1.0)
        self.assertIn("'.2'", reading["note"])

    def test_glue_attack_bare_number_matching_another_step_is_ambiguous(self):
        attack = StepParam("Attack", GLUE_ATTACK)

        with self.assertRaisesRegex(LiveOpsError, "ambiguous.*'.1'.*'1' is raw 3"):
            live_ops.set_parameter_value(attack, 1)
        self.assertEqual(attack.writes, [])
        live_ops.set_parameter_value(attack, "1")
        self.assertEqual(attack.value, 3.0)

    def test_glue_ratio_number_beyond_the_steps_is_read_as_display(self):
        ratio = StepParam("Ratio", ("2", "4", "10"))

        reading = live_ops.set_parameter_value(ratio, 4)

        self.assertEqual(ratio.value, 1.0)
        self.assertEqual(reading["read_as"], "display")

    def test_unknown_step_lists_the_options(self):
        release = StepParam("Release", GLUE_RELEASE)

        with self.assertRaisesRegex(LiveOpsError, "Options: .1, .2, .4, .6, .8, 1.2, A"):
            live_ops.set_parameter_value(release, "Slow")
        self.assertEqual(release.writes, [])

    def test_echo_synced_division_matches_text_not_its_leading_number(self):
        synced = StepParam("L Synced", ECHO_SYNCED)

        self.assertEqual(live_ops.value_for_display(synced, "1/8"), 3.0)
        self.assertEqual(live_ops.value_for_display(synced, "1"), 6.0)
        self.assertEqual(live_ops._param_payload(synced)["options"], list(ECHO_SYNCED))

    def test_echo_synced_constant_display_is_explained(self):
        # What Live 12.4.16 reported: '1/64' for every value (issue #44).
        synced = StepParam("L Synced", ECHO_SYNCED, constant="1/64")

        with self.assertRaises(LiveOpsError) as raised:
            live_ops.set_parameter_value(synced, "1/8")

        message = str(raised.exception)
        self.assertIn("shows '1/64' for every value", message)
        self.assertIn("depend on another parameter", message)
        self.assertIn('{"raw"', raised.exception.hint)
        self.assertEqual(synced.writes, [])
        self.assertFalse(live_ops._param_payload(synced).get("options"))

    def test_text_display_is_matched_by_sampling_and_misses_list_what_was_seen(self):
        mode = Param("Mode", 0.0, display=lambda v: "Low" if v < 0.5 else "High")

        self.assertGreaterEqual(live_ops.value_for_display(mode, "high"), 0.5)
        with self.assertRaisesRegex(LiveOpsError, "it shows: Low, High"):
            live_ops.value_for_display(mode, "Mid")

    def test_continuous_integer_range_is_not_mistaken_for_steps(self):
        knob = Param("Amount", 0.0, 0.0, 10.0, display=lambda v: f"{v:.1f}")

        self.assertNotIn("options", live_ops._param_payload(knob))
        self.assertAlmostEqual(live_ops.value_for_display(knob, "2.5"), 2.5, places=1)


class GlueTrack(Track):
    """insert_device makes a Glue Compressor with stepped parameters."""

    def __init__(self, name):
        super().__init__(name)
        self.inserted = []

    def insert_device(self, device_name, index):
        device = SimpleNamespace(
            name=device_name,
            class_name="GlueCompressor",
            can_have_chains=False,
            parameters=(
                Param("Device On", 1.0, items=("Off", "On")),
                StepParam("Attack", GLUE_ATTACK),
                StepParam("Release", GLUE_RELEASE),
            ),
        )
        self.inserted.append(device)
        self.devices.insert(index, device)


class InsertWithParametersTests(unittest.TestCase):
    """Issue #44: insert_device checks what it can before inserting."""

    def setUp(self):
        self.song = Song()
        self.track = GlueTrack("Drums")
        self.song.tracks = (self.track,)

    def insert(self, parameters):
        return live_ops.handle(
            self.song,
            "ableton.insert_device",
            {"track": 0, "device_name": "Glue Compressor", "parameters": parameters},
        )

    def test_step_names_resolve_on_insert(self):
        result = self.insert({"Release": "Auto", "Attack": "1"})

        self.assertEqual([p["display"] for p in result["parameters_set"]], ["A", "1"])

    def test_malformed_values_are_refused_before_inserting(self):
        for parameters in ({"Release": [1]}, {"Release": {"raw": "x"}}, ["Release"], {"": 1}):
            with self.subTest(parameters=parameters), self.assertRaises(LiveOpsError):
                self.insert(parameters)
        self.assertEqual(self.track.inserted, [])

    def test_unknown_name_fails_before_any_parameter_is_written(self):
        with self.assertRaises(LiveOpsError) as raised:
            self.insert({"Release": "Auto", "Knee": 3})

        self.assertIn("removed again", str(raised.exception))
        self.assertIn("list_devices", raised.exception.hint)
        self.assertEqual(self.track.devices, [])
        self.assertEqual(self.track.inserted[0].parameters[2].writes, [])

    def test_unresolvable_value_keeps_its_code_and_explains(self):
        with self.assertRaises(live_ops.InvalidValue) as raised:
            self.insert({"Release": "Slow"})

        self.assertIn("Options:", str(raised.exception))
        self.assertIn("removed again", str(raised.exception))
        self.assertIn("insert it without parameters", raised.exception.hint)
        self.assertEqual(self.track.devices, [])

    def test_batch_rejects_malformed_values_before_anything_runs(self):
        with self.assertRaisesRegex(LiveOpsError, "operation 1"):
            live_ops.handle(
                self.song,
                "ableton.batch",
                {
                    "operations": [
                        {
                            "method": "ableton.insert_device",
                            "params": {"track": 0, "device_name": "Glue Compressor"},
                        },
                        {
                            "method": "ableton.set_device_parameter",
                            "params": {
                                "track": 0,
                                "device": 0,
                                "parameter": "Release",
                                "value": [1],
                            },
                        },
                    ]
                },
            )
        self.assertEqual(self.track.inserted, [])
        self.assertEqual(self.song.undo_steps, [])


if __name__ == "__main__":
    unittest.main()
