"""list_devices detail levels and get_device (issue #42); printed paths (issue #24)."""

import json
import unittest
from types import SimpleNamespace

import _bootstrap  # noqa: F401
from test_live_ops import Param, Song, gain_display
from test_live_ops_mix_session import Chain, plain, rack

from remote_scripts.Abletonian import live_ops
from remote_scripts.Abletonian.live_ops import LiveOpsError


class RecordingParam(Param):
    """A Param that records every write to ``value``, so reads can prove none."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.writes = []

    def __setattr__(self, key, value):
        if key == "value" and "writes" in self.__dict__:
            self.writes.append(value)
        object.__setattr__(self, key, value)


def simpler(name, parameter_count=40):
    """A Simpler-sized device: Device On plus many continuous parameters."""

    parameters = [RecordingParam("Device On", 1.0, items=("Off", "On"))]
    parameters += [
        RecordingParam(f"Param {i}", 0.5, display=lambda v: f"{v * 100:.0f} %")
        for i in range(parameter_count - 1)
    ]
    return SimpleNamespace(
        name=name,
        class_name="OriginalSimpler",
        class_display_name="Simpler",
        can_have_chains=False,
        is_active=True,
        parameters=tuple(parameters),
    )


def utility():
    return SimpleNamespace(
        name="Utility",
        class_name="StereoGain",
        class_display_name="Utility",
        can_have_chains=False,
        is_active=True,
        parameters=(
            RecordingParam("Device On", 1.0, items=("Off", "On")),
            RecordingParam("Output", 0.0, -1.0, 1.0, display=gain_display),
            RecordingParam("Width", 0.5),
            RecordingParam("Mute", 0.0, items=("Off", "On")),
        ),
    )


def all_payloads(result):
    found = []

    def walk(devices):
        for device in devices:
            found.append(device)
            for chain in device.get("chains", []) + device.get("return_chains", []):
                walk(chain.get("devices", []))

    for track in result["tracks"]:
        walk(track["devices"])
    return found


def all_objects(devices):
    """Live device objects in the order list_devices prints them."""

    found = []
    for device in devices:
        found.append(device)
        if getattr(device, "can_have_chains", False):
            for chain in (*device.chains, *getattr(device, "return_chains", ())):
                found.extend(all_objects(chain.devices))
    return found


class DrumKitSong:
    """The C78 Core Kit from issue #24: chains 4 and 6 are both "Guiro Short"."""

    def __init__(self, pads=16):
        self.song = Song()
        self.track = self.song.tracks[0]
        names = ["Kick", "Snare", "Clap", "Hat", "Guiro Short", "Tom", "Guiro Short"]
        names += [f"Pad {i}" for i in range(len(names), pads)]
        self.chains = [
            Chain(name, [simpler(name), plain("Saturator"), plain("Reverb")]) for name in names
        ]
        self.kit = rack(
            "C78 Core Kit",
            self.chains,
            return_chains=[Chain("Room", [plain("Limiter")])],
            class_name="DrumGroupDevice",
        )
        self.utility = utility()
        self.track.devices = [self.kit, self.utility]

    def call(self, method, **params):
        return live_ops.handle(self.song, method, params)


class ListDevicesDetailTests(unittest.TestCase):
    def setUp(self):
        self.kit = DrumKitSong()

    def test_compact_has_names_paths_and_chain_counts_but_no_parameters(self):
        result = self.kit.call("ableton.list_devices", track=0, detail="compact")

        self.assertEqual(result["detail"], "compact")
        rack_payload, utility_payload = result["tracks"][0]["devices"]
        self.assertEqual(rack_payload["path"], "C78 Core Kit")
        self.assertEqual(rack_payload["class_name"], "DrumGroupDevice")
        self.assertTrue(utility_payload["is_active"])
        kick = rack_payload["chains"][0]
        self.assertEqual((kick["index"], kick["name"], kick["device_count"]), (0, "Kick", 3))
        self.assertEqual(kick["devices"][0]["path"], "C78 Core Kit/Kick/Kick")
        self.assertNotIn("parameters", json.dumps(result))

    def test_include_parameters_true_is_still_the_full_listing(self):
        result = self.kit.call("ableton.list_devices", track=0, include_parameters=True)

        self.assertEqual(result["detail"], "full")
        for payload in all_payloads(result):
            self.assertIn("parameters", payload)
        utility_payload = result["tracks"][0]["devices"][1]
        self.assertEqual(utility_payload["parameters"][1]["name"], "Output")
        self.assertEqual(utility_payload["parameters"][0]["options"], ["Off", "On"])

    def test_include_parameters_wins_over_detail(self):
        result = self.kit.call(
            "ableton.list_devices", track=0, detail="full", include_parameters=False
        )

        self.assertEqual(result["detail"], "compact")
        self.assertNotIn("parameters", json.dumps(result))

    def test_bridge_default_is_unchanged_without_either_switch(self):
        one_track = self.kit.call("ableton.list_devices", track=0)
        whole_set = self.kit.call("ableton.list_devices")

        self.assertEqual(one_track["detail"], "full")
        self.assertEqual(whole_set["detail"], "compact")

    def test_max_depth_zero_lists_chains_without_their_devices(self):
        result = self.kit.call("ableton.list_devices", track=0, max_depth=0, detail="full")

        rack_payload = result["tracks"][0]["devices"][0]
        self.assertEqual(result["max_depth"], 0)
        self.assertEqual(len(rack_payload["chains"]), 16)
        self.assertEqual(
            rack_payload["chains"][4],
            {"index": 4, "name": "Guiro Short", "device_count": 3, "truncated": True},
        )
        self.assertEqual(rack_payload["return_chains"][0]["name"], "Room")
        self.assertNotIn("devices", json.dumps(rack_payload["chains"]))
        self.assertIn("parameters", rack_payload)  # the rack's own parameters only

    def test_compact_and_max_depth_shrink_a_drum_rack_listing(self):
        def size(**params):
            return len(json.dumps(self.kit.call("ableton.list_devices", track=0, **params)))

        full = size(include_parameters=True)
        compact = size(detail="compact")
        shallow = size(detail="compact", max_depth=0)

        self.assertLess(compact * 5, full)
        self.assertLess(shallow * 3, compact)

    def test_rejects_bad_detail_and_max_depth(self):
        for params in (
            {"detail": "everything"},
            {"max_depth": -1},
            {"max_depth": live_ops.MAX_RACK_DEPTH + 1},
            {"max_depth": "2"},
            {"max_depth": True},
            {"include_parameters": "yes"},
        ):
            with self.subTest(params=params), self.assertRaises(LiveOpsError):
                self.kit.call("ableton.list_devices", track=0, **params)


class GetDeviceTests(unittest.TestCase):
    def setUp(self):
        self.kit = DrumKitSong()

    def get(self, device, **params):
        return self.kit.call("ableton.get_device", track=0, device=device, **params)["device"]

    def test_reads_every_parameter_of_one_device(self):
        device = self.get("Utility")

        self.assertEqual(device["path"], "Utility")
        self.assertEqual(device["parameter_count"], 4)
        output = device["parameters"][1]
        self.assertEqual(output["index"], 1)
        self.assertEqual(output["name"], "Output")
        self.assertEqual(output["original_name"], "Output")
        self.assertEqual((output["value"], output["min"], output["max"]), (0.0, -1.0, 1.0))
        self.assertEqual(output["display"], "0.0 dB")
        self.assertEqual(device["parameters"][3]["options"], ["Off", "On"])

    def test_filters_by_substring_list_and_alias(self):
        self.assertEqual([p["name"] for p in self.get(1, parameters="mu")["parameters"]], ["Mute"])
        names = [p["name"] for p in self.get(1, parameters=["width", "DEVICE"])["parameters"]]
        self.assertEqual(names, ["Device On", "Width"])
        # Utility shows "Gain"; the API calls it "Output".
        self.assertEqual(
            [p["name"] for p in self.get(1, parameters="Gain")["parameters"]], ["Output"]
        )

    def test_no_match_lists_the_parameters(self):
        with self.assertRaisesRegex(LiveOpsError, "Parameters: Device On, Output, Width, Mute"):
            self.get("Utility", parameters="Cutoff")
        for bad in ("", [], [3], {"a": 1}):
            with self.subTest(bad=bad), self.assertRaises(LiveOpsError):
                self.get("Utility", parameters=bad)

    def test_reads_a_device_inside_a_duplicate_named_chain(self):
        device = self.get("C78 Core Kit/6/Guiro Short", parameters="Device On")

        self.assertEqual(device["path"], "C78 Core Kit/6/Guiro Short")
        self.assertEqual(device["class_name"], "OriginalSimpler")
        self.assertEqual(len(device["parameters"]), 1)

    def test_a_rack_lists_its_chains_without_their_devices(self):
        device = self.get("C78 Core Kit")

        self.assertEqual(len(device["chains"]), 16)
        self.assertEqual(device["chains"][0]["device_count"], 3)
        self.assertNotIn("devices", json.dumps(device["chains"]))
        self.assertEqual(device["return_chains"][0]["name"], "Room")

    def test_reads_do_not_change_the_set(self):
        parameters = [
            parameter
            for device in all_objects(self.kit.track.devices)
            for parameter in getattr(device, "parameters", ())
            if isinstance(parameter, RecordingParam)
        ]
        self.assertIn(self.kit.utility.parameters[1], parameters)

        self.get("Utility")
        self.get("Utility", parameters="Gain")
        self.get("C78 Core Kit/Kick/Kick")
        self.kit.call("ableton.list_devices", track=0, detail="full")

        self.assertEqual([p.writes for p in parameters if p.writes], [])
        self.assertEqual(self.kit.song.undo_steps, [])
        self.assertEqual(len(self.kit.track.devices), 2)

    def test_unknown_device(self):
        with self.assertRaisesRegex(LiveOpsError, "no device named"):
            self.get("Compressor")
        with self.assertRaisesRegex(LiveOpsError, "ambiguous"):
            self.get("C78 Core Kit/Guiro Short/Guiro Short")


class PrintedPathsResolveTests(unittest.TestCase):
    """Issue #24: every path list_devices prints resolves to the device it labels."""

    def setUp(self):
        self.kit = DrumKitSong()

    def test_duplicate_chain_names_print_the_index(self):
        result = self.kit.call("ableton.list_devices", track=0, detail="compact")
        paths = [payload["path"] for payload in all_payloads(result)]

        self.assertIn("C78 Core Kit/4/Guiro Short", paths)
        self.assertIn("C78 Core Kit/6/Guiro Short", paths)
        self.assertNotIn("C78 Core Kit/Guiro Short/Guiro Short", paths)
        self.assertIn("C78 Core Kit/Tom/Tom", paths)

    def test_every_printed_path_resolves_to_that_object(self):
        expected = all_objects(self.kit.track.devices)
        for params in ({"detail": "compact"}, {"include_parameters": True}):
            result = self.kit.call("ableton.list_devices", track=0, **params)
            payloads = all_payloads(result)
            self.assertEqual(len(payloads), len(expected))
            for payload, device in zip(payloads, expected, strict=True):
                with self.subTest(path=payload["path"], **params):
                    self.assertEqual(payload["name"], device.name)
                    path, _index, found, _owner = live_ops.resolve_device_path(
                        self.kit.track, payload["path"]
                    )
                    self.assertIs(found, device)
                    self.assertEqual(path, payload["path"])
                    read = self.kit.call("ableton.get_device", track=0, device=payload["path"])[
                        "device"
                    ]
                    self.assertEqual(read["path"], payload["path"])


if __name__ == "__main__":
    unittest.main()
