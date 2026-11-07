"""Compressor sidechain routing (issue #49), against LOM-shaped fakes.

The fakes follow the Cycling '74 LOM docs for Live 11+
``CompressorDevice``: ``available_input_routing_types``,
``available_input_routing_channels``, ``input_routing_type`` and
``input_routing_channel``, each routing object having ``display_name``.
Not validated in Live.
"""

import unittest
from types import SimpleNamespace

import _bootstrap  # noqa: F401
from test_live_ops import Param, Routing, Song

from remote_scripts.Abletonian import live_ops
from remote_scripts.Abletonian.live_ops import LiveOpsError, NotFound, NotSupported

CHANNELS = {
    "No Input": (),
    "1-Kick": (Routing("Pre FX"), Routing("Post FX"), Routing("Post Mixer")),
    "2-32 Pad Kit Jazz": (Routing("Pre FX"), Routing("Post FX"), Routing("Post Mixer")),
}


class Compressor:
    """Shaped like Live.CompressorDevice.CompressorDevice (Live 11+)."""

    class_name = "Compressor2"
    class_display_name = "Compressor"
    can_have_chains = False
    is_active = True

    def __init__(self, name="Compressor", source="2-32 Pad Kit Jazz", on=True):
        self.name = name
        self.available_input_routing_types = tuple(Routing(n) for n in CHANNELS)
        self._type = next(r for r in self.available_input_routing_types if r.display_name == source)
        self.input_routing_channel = CHANNELS[source][1] if CHANNELS[source] else None
        self.parameters = (
            Param("Device On", 1.0, items=("Off", "On")),
            Param("Threshold", 0.5),
            Param("S/C On", 1.0 if on else 0.0, items=("Off", "On")),
        )
        self.writes = []

    @property
    def input_routing_type(self):
        return self._type

    @input_routing_type.setter
    def input_routing_type(self, value):
        self.writes.append(("type", value.display_name))
        self._type = value

    @property
    def available_input_routing_channels(self):
        return CHANNELS[self._type.display_name]


def eq_eight():
    return SimpleNamespace(
        name="EQ Eight",
        class_name="Eq8",
        class_display_name="EQ Eight",
        can_have_chains=False,
        is_active=True,
        parameters=(Param("Device On", 1.0, items=("Off", "On")),),
    )


class SidechainTests(unittest.TestCase):
    def setUp(self):
        self.song = Song()
        self.bass = self.song.tracks[1]
        self.compressor = Compressor()
        self.bass.devices = [eq_eight(), self.compressor]

    def call(self, method, **params):
        return live_ops.handle(self.song, method, params)

    def test_list_devices_shows_the_sidechain_of_a_compressor_only(self):
        devices = self.call("ableton.list_devices", track="Bass")["tracks"][0]["devices"]

        self.assertNotIn("sidechain", devices[0])
        self.assertEqual(
            devices[1]["sidechain"], {"on": True, "from": "2-32 Pad Kit Jazz", "channel": "Post FX"}
        )

    def test_sidechain_off_and_missing_switch(self):
        self.compressor.parameters[2].value = 0.0
        self.assertFalse(live_ops._sidechain_payload(self.compressor)["on"])
        self.compressor.parameters = self.compressor.parameters[:2]
        self.assertIsNone(live_ops._sidechain_payload(self.compressor)["on"])

    def test_listing_does_not_change_the_set(self):
        self.call("ableton.list_devices", track="Bass", include_parameters=False)

        self.assertEqual(self.compressor.writes, [])
        self.assertEqual(self.song.undo_steps, [])

    def test_sets_source_and_channel_as_one_undo_step(self):
        result = self.call(
            "ableton.set_device_sidechain",
            track="Bass",
            device="Compressor",
            from_track="1-kick",
            channel="pre fx",
        )

        self.assertEqual(result["before"]["from"], "2-32 Pad Kit Jazz")
        self.assertEqual(result["after"], {"on": True, "from": "1-Kick", "channel": "Pre FX"})
        self.assertEqual(result["device"], {"index": 1, "name": "Compressor", "path": "Compressor"})
        self.assertEqual(self.song.undo_steps, ["begin", "end"])

    def test_bare_track_name_matches_the_numbered_source(self):
        result = self.call(
            "ableton.set_device_sidechain", track="Bass", device=1, from_track="Kick"
        )
        self.assertEqual(result["after"]["from"], "1-Kick")

    def test_unknown_source_lists_choices_and_changes_nothing(self):
        with self.assertRaises(NotFound) as raised:
            self.call("ableton.set_device_sidechain", track="Bass", device=1, from_track="Drums")

        self.assertIn("2-32 Pad Kit Jazz", str(raised.exception))
        self.assertIn("every source Live offers", raised.exception.hint)
        self.assertNotIn("list_tracks", raised.exception.hint)
        self.assertEqual(self.compressor.writes, [])

    def test_unknown_channel_puts_the_source_back(self):
        with self.assertRaises(LiveOpsError) as raised:
            self.call(
                "ableton.set_device_sidechain",
                track="Bass",
                device=1,
                from_track="1-Kick",
                channel="Post Nothing",
            )

        self.assertIn("sidechain source was put back", str(raised.exception))
        self.assertEqual(self.compressor.input_routing_type.display_name, "2-32 Pad Kit Jazz")

    def test_device_without_sidechain_routing_is_not_supported(self):
        with self.assertRaises(NotSupported) as raised:
            self.call("ableton.set_device_sidechain", track="Bass", device=0, from_track="1-Kick")
        self.assertIn("EQ Eight", str(raised.exception))

    def test_runs_inside_a_batch(self):
        result = self.call(
            "ableton.batch",
            operations=[
                {
                    "method": "ableton.set_device_sidechain",
                    "params": {"track": "Bass", "device": 1, "from_track": "1-Kick"},
                }
            ],
        )
        self.assertIsNone(result["failed"])
        self.assertEqual(self.compressor.input_routing_type.display_name, "1-Kick")

    def test_output_routing_still_puts_its_type_back(self):
        with self.assertRaises(LiveOpsError) as raised:
            self.call(
                "ableton.set_track_output_routing",
                track="Bass",
                routing_type="Main",
                routing_channel="Nowhere",
            )
        self.assertIn("output type was put back", str(raised.exception))
        self.assertIn("list_tracks", raised.exception.hint)
        self.assertEqual(self.bass.output_routing_type.display_name, "Master")


if __name__ == "__main__":
    unittest.main()
