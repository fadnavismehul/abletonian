import unittest

from abletonian.adapters.base import (
    AdapterHealth,
    AdapterRefused,
    AdapterResponseError,
    Batch,
    ClipGainChange,
    DawAdapter,
    DeviceDelete,
    DeviceInsert,
    MixerChange,
    TrackQuery,
    UndoRequest,
    UnsupportedOperation,
)

HEALTH = {
    "target_daw": "ableton",
    "adapter_type": "ableton_remote_script",
    "adapter_version": "0.5.0",
    "live_version": "12.4.16",
    "protocol_version": "abletonian.bridge.v1",
    "capabilities": ["list_tracks", "set_mixer"],
    "unsupported_capabilities": ["create_track"],
}


class RequestParamsTests(unittest.TestCase):
    def test_none_fields_are_left_out(self) -> None:
        change = MixerChange(track="Bass", volume="-6 dB")
        self.assertEqual(change.params(), {"track": "Bass", "volume": "-6 dB"})

    def test_defaults_are_sent(self) -> None:
        self.assertEqual(
            TrackQuery().params(),
            {"include_returns": True, "include_master": True, "detail": "compact"},
        )

    def test_mappings_become_plain_dicts(self) -> None:
        change = DeviceInsert(track=0, device_name="Utility", parameters={"Gain": "-3 dB"})
        self.assertEqual(type(change.params()["parameters"]), dict)

    def test_delete_always_sends_confirm(self) -> None:
        self.assertEqual(
            DeviceDelete(track=0, device=1).params(),
            {"track": 0, "device": 1, "confirm": False},
        )
        self.assertTrue(DeviceDelete(track=0, device=1, confirm=True).params()["confirm"])

    def test_operation_names_match_bridge_methods(self) -> None:
        self.assertEqual(MixerChange.OPERATION, "set_mixer")
        self.assertEqual(UndoRequest.OPERATION, "undo")


class BatchTests(unittest.TestCase):
    def test_empty_batch_is_refused(self) -> None:
        with self.assertRaises(ValueError):
            Batch(operations=())

    def test_batch_holds_only_changes(self) -> None:
        with self.assertRaises(TypeError):
            Batch(operations=(TrackQuery(),))  # type: ignore[arg-type]

    def test_batch_stores_a_tuple(self) -> None:
        batch = Batch(operations=[MixerChange(track=0, mute=True)])  # type: ignore[arg-type]
        self.assertIsInstance(batch.operations, tuple)

    def test_batch_keeps_order(self) -> None:
        first = MixerChange(track=0, mute=True)
        second = DeviceDelete(track=1, device=0, confirm=True)
        self.assertEqual(Batch(operations=(first, second)).operations, (first, second))


class UndoRequestTests(unittest.TestCase):
    def test_count_must_be_in_range(self) -> None:
        for bad in (0, -3, 21, True, 1.5, "2"):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                UndoRequest(count=bad)  # type: ignore[arg-type]

    def test_valid_counts(self) -> None:
        self.assertEqual(UndoRequest(count=20, confirm=True).count, 20)


class ClipGainChangeTests(unittest.TestCase):
    def test_gain_is_a_number_or_text_only(self) -> None:
        for bad in ({"raw": 0.7}, True, None, [-3]):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                ClipGainChange(track=1, clip=0, gain_db=bad)  # type: ignore[arg-type]
        self.assertEqual(ClipGainChange(track=1, clip=0, gain_db=-3).gain_db, -3)
        self.assertEqual(ClipGainChange(track=1, clip=0, gain_db="-3 dB").gain_db, "-3 dB")


class HealthTests(unittest.TestCase):
    def test_valid_health(self) -> None:
        health = AdapterHealth.from_wire(HEALTH)
        self.assertEqual(health.adapter_version, "0.5.0")
        self.assertEqual(health.daw_version, "12.4.16")
        self.assertEqual(health.capabilities, frozenset({"list_tracks", "set_mixer"}))
        self.assertEqual(health.unsupported_capabilities, frozenset({"create_track"}))

    def test_rejects_non_objects(self) -> None:
        with self.assertRaises(AdapterResponseError):
            AdapterHealth.from_wire(["not", "a", "dict"])

    def test_rejects_missing_version(self) -> None:
        with self.assertRaises(AdapterResponseError):
            AdapterHealth.from_wire({**HEALTH, "adapter_version": ""})

    def test_rejects_bad_capabilities(self) -> None:
        for bad in (None, "list_tracks", ["list_tracks", 3]):
            with self.subTest(bad=bad), self.assertRaises(AdapterResponseError):
                AdapterHealth.from_wire({**HEALTH, "capabilities": bad})

    def test_rejects_non_text_daw_version(self) -> None:
        with self.assertRaises(AdapterResponseError):
            AdapterHealth.from_wire({**HEALTH, "live_version": 12})


class ErrorTests(unittest.TestCase):
    def test_refused_includes_code_and_hint(self) -> None:
        error = AdapterRefused("no track 'X'", code="not_found", hint="Use list_tracks.")
        self.assertEqual(str(error), "not_found: no track 'X' Hint: Use list_tracks.")

    def test_unsupported_names_the_operation(self) -> None:
        error = UnsupportedOperation("set_track_output_routing")
        self.assertIn("set track output routing", str(error))



class ProtocolTests(unittest.TestCase):
    def test_an_object_without_methods_is_not_an_adapter(self) -> None:
        self.assertNotIsInstance(object(), DawAdapter)

    def test_a_full_implementation_is_an_adapter(self) -> None:
        names = [
            name
            for name in vars(DawAdapter)
            if not name.startswith("_") and callable(getattr(DawAdapter, name))
        ]
        implementation = type("Impl", (), {name: lambda self, *a: {} for name in names})()
        self.assertIsInstance(implementation, DawAdapter)


if __name__ == "__main__":
    unittest.main()
