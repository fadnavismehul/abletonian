import json
import unittest

import _bootstrap  # noqa: F401

from abletonian.adapters.fake import (
    FakeAbletonAdapter,
    FakeAbletonState,
    FakeDrumPad,
    FakeDrumRackDevice,
    FakePlainDevice,
    FakeRackDevice,
    FakeRackMacro,
    FakeTrack,
)
from abletonian.cockpit import (
    SCHEMA_VERSION,
    CockpitError,
    MacroCockpitSpec,
    generate_macro_cockpit,
    rack_fingerprint,
    render_cockpit_text,
)

NAMED_MACROS = (
    FakeRackMacro(1, "Brightness", 64.0),
    FakeRackMacro(2, "Drive", 20.0),
    FakeRackMacro(3, "Attack", 0.0),
    FakeRackMacro(4, "LFO Rate", 90.0),
    FakeRackMacro(5, "Reverb", 30.0),
    FakeRackMacro(6, "Dry/Wet", 127.0),
    FakeRackMacro(7, "Crowd", 10.0),
    FakeRackMacro(8, "Macro 8", 0.0),
)


def adapter_for(*devices, selected_device_id=None) -> FakeAbletonAdapter:
    return FakeAbletonAdapter(
        FakeAbletonState(
            live_version="12.4.16",
            tracks=(
                FakeTrack(id="t0", name="Bass"),
                FakeTrack(id="t1", name="Keys", color="#3b82f6", devices=devices),
            ),
            selected_track_id="t1",
            selected_device_id=selected_device_id,
        )
    )


def cockpit_for(adapter: FakeAbletonAdapter):
    rack = adapter.handle_request("ableton.get_selected_rack_macros")
    health = adapter.handle_request("daw.health")
    return generate_macro_cockpit(rack, health, created_at="2026-11-01T00:00:00+00:00")


class MacroCockpitGenerationTests(unittest.TestCase):
    def test_named_macros_are_grouped_by_name_and_keep_source_identity(self) -> None:
        spec = cockpit_for(adapter_for(FakeRackDevice("keys-rack", "Keys Rack", NAMED_MACROS)))

        groups = {group.id: list(group.controls) for group in spec.groups}
        self.assertEqual(
            groups,
            {
                "tone": ["macro-1", "macro-2"],
                "dynamics": ["macro-3"],
                "movement": ["macro-4"],
                "space": ["macro-5"],
                "utility": ["macro-6"],
                "other": ["macro-7"],
                "inspect": ["macro-8"],
            },
        )
        brightness = spec.control("macro-1")
        self.assertEqual(brightness.source_macro_index, 1)
        self.assertEqual(brightness.label, "Brightness")
        self.assertEqual(brightness.original_name, "Macro 1")
        self.assertAlmostEqual(brightness.normalized_value, 64 / 127)
        self.assertEqual(spec.title, "Keys Rack Macro Cockpit")
        self.assertEqual(spec.mode, "temporary")
        self.assertEqual(spec.source["track_name"], "Keys")
        self.assertEqual(spec.source["live_version"], "12.4.16")
        self.assertEqual(spec.source["selection"], "first_rack_on_track")

    def test_fake_adapter_cockpit_is_simulated_and_cannot_control_live(self) -> None:
        spec = cockpit_for(adapter_for(FakeRackDevice("r", "Rack", NAMED_MACROS)))

        self.assertEqual(spec.connection, "simulated")
        self.assertEqual(
            spec.permissions,
            {"read_macros": True, "control_macro_values": False, "save_sidecar": True},
        )

    def test_remote_script_without_write_capability_is_read_only(self) -> None:
        rack = adapter_for(FakeRackDevice("r", "Rack", NAMED_MACROS)).handle_request(
            "ableton.get_selected_rack_macros"
        )
        health = {"adapter_type": "ableton_remote_script", "capabilities": ["read_rack_macros"]}

        self.assertEqual(generate_macro_cockpit(rack, health).connection, "read_only")

    def test_unnamed_macros_go_to_inspect(self) -> None:
        macros = tuple(FakeRackMacro(i, f"Macro {i}", 0.0) for i in range(1, 5))
        spec = cockpit_for(adapter_for(FakeRackDevice("r", "Rack", macros)))

        self.assertEqual([group.id for group in spec.groups], ["inspect"])
        self.assertEqual(len(spec.groups[0].controls), 4)

    def test_rack_without_macros_has_no_controls_and_says_so(self) -> None:
        spec = cockpit_for(adapter_for(FakeRackDevice("r", "Empty Rack")))

        self.assertEqual(spec.controls, ())
        self.assertEqual(spec.groups, ())
        self.assertIn("no mapped macros", spec.warnings[0])

    def test_unmapped_macros_are_left_out_and_listed(self) -> None:
        macros = (
            FakeRackMacro(1, "Cutoff", 10.0),
            FakeRackMacro(2, "Macro 2", 0.0, is_mapped=False),
        )
        spec = cockpit_for(adapter_for(FakeRackDevice("r", "Rack", macros)))

        self.assertEqual([control.id for control in spec.controls], ["macro-1"])
        self.assertEqual(spec.omitted_macros[0]["source_macro_index"], 2)

    def test_ambiguous_names_are_not_guessed(self) -> None:
        # "Reverb Mix" scores one word for Space and one for Utility.
        spec = cockpit_for(
            adapter_for(FakeRackDevice("r", "Rack", (FakeRackMacro(1, "Reverb Mix"),)))
        )

        self.assertEqual(spec.groups[0].id, "other")

    def test_selected_drum_rack_is_used_and_reported(self) -> None:
        drum_rack = FakeDrumRackDevice(
            id="kit",
            name="C78 Core Kit",
            pads=(FakeDrumPad(36, "Kick", "Kick"),),
            macros=(FakeRackMacro(1, "Kick Tone", 50.0),),
        )
        adapter = adapter_for(
            FakePlainDevice("util", "Utility"), drum_rack, selected_device_id="kit"
        )
        spec = cockpit_for(adapter)

        self.assertEqual(spec.source["device_type"], "drum_rack")
        self.assertEqual(spec.source["device_index"], 1)
        self.assertEqual(spec.source["selection"], "selected_device")
        self.assertEqual(spec.warnings, ())

    def test_track_without_rack_is_an_adapter_error(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "has no Rack"):
            adapter_for(FakePlainDevice("util", "Utility")).handle_request(
                "ableton.get_selected_rack_macros"
            )

    def test_fingerprint_ignores_values_but_tracks_layout(self) -> None:
        def fingerprint(macros):
            adapter = adapter_for(FakeRackDevice("r", "Rack", macros))
            return rack_fingerprint(adapter.handle_request("ableton.get_selected_rack_macros"))

        base = fingerprint((FakeRackMacro(1, "Cutoff", 10.0),))
        self.assertEqual(base, fingerprint((FakeRackMacro(1, "Cutoff", 99.0),)))
        self.assertNotEqual(base, fingerprint((FakeRackMacro(1, "Drive", 10.0),)))


class MacroCockpitSpecTests(unittest.TestCase):
    def test_wire_round_trip_through_json(self) -> None:
        spec = cockpit_for(adapter_for(FakeRackDevice("r", "Rack", NAMED_MACROS)))

        wire = json.loads(json.dumps(spec.to_wire()))

        self.assertEqual(wire["schema_version"], SCHEMA_VERSION)
        self.assertEqual(wire["groups"][0]["description_source"], "generated")
        self.assertEqual(MacroCockpitSpec.from_wire(wire), spec)

    def test_from_wire_rejects_bad_specs(self) -> None:
        wire = cockpit_for(adapter_for(FakeRackDevice("r", "Rack", NAMED_MACROS))).to_wire()

        cases = {
            "schema_version": {**wire, "schema_version": "v0"},
            "unknown controls": {
                **wire,
                "groups": [{"id": "x", "label": "X", "controls": ["macro-99"]}],
            },
            "only one group": {
                **wire,
                "groups": [
                    {"id": "a", "label": "A", "controls": ["macro-1"]},
                    {"id": "b", "label": "B", "controls": ["macro-1"]},
                ],
            },
            "mode": {**wire, "mode": "forever"},
        }
        for message, bad in cases.items():
            with self.subTest(message), self.assertRaisesRegex(CockpitError, message):
                MacroCockpitSpec.from_wire(bad)

    def test_generation_rejects_untrusted_rack_payloads(self) -> None:
        good = adapter_for(FakeRackDevice("r", "Rack", NAMED_MACROS)).handle_request(
            "ableton.get_selected_rack_macros"
        )
        bad_payloads = [
            {**good, "macros": "nope"},
            {**good, "macros": [{**good["macros"][0], "index": 17}]},
            {**good, "macros": [good["macros"][0], good["macros"][0]]},
            {**good, "macros": [{**good["macros"][0], "value": "loud"}]},
            {**good, "device": None},
        ]
        for payload in bad_payloads:
            with self.subTest(payload=payload), self.assertRaises(CockpitError):
                generate_macro_cockpit(payload)

    def test_text_fallback_shows_context_groups_status_and_notes(self) -> None:
        macros = (*NAMED_MACROS, FakeRackMacro(9, "Macro 9", is_mapped=False))
        spec = cockpit_for(adapter_for(FakeRackDevice("r", "Keys Rack", macros)))

        text = render_cockpit_text(spec)

        self.assertIn("Track: Keys | Device: Keys Rack (rack) | Live 12.4.16", text)
        self.assertIn("simulated", text)
        self.assertIn("temporary, not saved", text)
        self.assertIn("[ 1] Brightness (was Macro 1): 64 [#####-----]", text)
        self.assertIn("Left out (unmapped): 9 Macro 9", text)
        self.assertIn("Note: The selected device is not a Rack", text)


if __name__ == "__main__":
    unittest.main()
