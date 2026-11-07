import unittest
from typing import Any

from abletonian.adapters.base import (
    AdapterRefused,
    AdapterResponseError,
    AdapterUnavailable,
    Batch,
    ClipGainChange,
    ClipQuery,
    DawAdapter,
    DeviceDelete,
    DeviceInsert,
    DeviceQuery,
    DeviceRead,
    MixerChange,
    ParameterChange,
    RackRef,
    ReturnTrackCreate,
    RoutingChange,
    SidechainChange,
    TrackPropertiesChange,
    TrackQuery,
    UndoRequest,
)
from abletonian.adapters.remote_script import (
    OLD_SCRIPT_BATCH_WARNING,
    OLD_SCRIPT_UNDO_WARNING,
    RemoteScriptAdapter,
)
from abletonian.bridge.client import BridgeConnectionError, BridgeRefusedError

HEALTH = {
    "target_daw": "ableton",
    "adapter_type": "ableton_remote_script",
    "adapter_version": "0.5.0",
    "live_version": "12.4.16",
    "protocol_version": "abletonian.bridge.v1",
    "capabilities": ["list_tracks", "set_mixer", "batch_per_operation_undo"],
    "unsupported_capabilities": [],
}


class RecordingBridge:
    def __init__(self, results: dict[str, Any] | None = None) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.results = results or {}
        self.error: Exception | None = None

    def request(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        self.calls.append((method, params or {}))
        if self.error is not None:
            raise self.error
        return self.results.get(method, {"ok": True})


class WireShapeTests(unittest.TestCase):
    """Each method sends what server.py sends today."""

    def setUp(self) -> None:
        self.bridge = RecordingBridge()
        self.adapter = RemoteScriptAdapter(self.bridge)

    def last(self) -> tuple[str, dict[str, Any]]:
        return self.bridge.calls[-1]

    def test_it_is_a_daw_adapter(self) -> None:
        self.assertIsInstance(self.adapter, DawAdapter)

    def test_reads(self) -> None:
        cases = [
            (
                lambda: self.adapter.list_tracks(TrackQuery(name="Kit")),
                (
                    "ableton.list_tracks",
                    {
                        "include_returns": True,
                        "include_master": True,
                        "detail": "compact",
                        "name": "Kit",
                    },
                ),
            ),
            (
                lambda: self.adapter.list_devices(DeviceQuery(track=2)),
                ("ableton.list_devices", {"track": 2, "include_parameters": True}),
            ),
            (
                lambda: self.adapter.list_devices(
                    DeviceQuery(track=2, include_parameters=False, max_depth=0)
                ),
                (
                    "ableton.list_devices",
                    {"track": 2, "include_parameters": False, "max_depth": 0},
                ),
            ),
            (
                lambda: self.adapter.get_device(
                    DeviceRead(track="Kit", device="Kit/4/Guiro Short", parameters=("Gain", "Pan"))
                ),
                (
                    "ableton.get_device",
                    {"track": "Kit", "device": "Kit/4/Guiro Short", "parameters": ["Gain", "Pan"]},
                ),
            ),
            (
                lambda: self.adapter.get_device(DeviceRead(track=0, device=1)),
                ("ableton.get_device", {"track": 0, "device": 1}),
            ),
            (
                lambda: self.adapter.get_selected_rack_macros(RackRef()),
                ("ableton.get_selected_rack_macros", {}),
            ),
            (
                lambda: self.adapter.plan_drum_rack_extraction(),
                ("workflow.plan_drum_rack_extraction", {"target_daw": "ableton"}),
            ),
        ]
        for call, expected in cases:
            with self.subTest(expected=expected[0]):
                call()
                self.assertEqual(self.last(), expected)

    def test_changes(self) -> None:
        cases = [
            (
                ParameterChange(track=0, device="Reverb", parameter="Dry/Wet", value="25 %"),
                self.adapter.set_device_parameter,
                (
                    "ableton.set_device_parameter",
                    {"track": 0, "device": "Reverb", "parameter": "Dry/Wet", "value": "25 %"},
                ),
            ),
            (
                RoutingChange(track="Kit", routing_type="Main"),
                self.adapter.set_track_output_routing,
                ("ableton.set_track_output_routing", {"track": "Kit", "routing_type": "Main"}),
            ),
            (
                TrackPropertiesChange(track=1, color="#ff0000"),
                self.adapter.set_track_properties,
                ("ableton.set_track_properties", {"track": 1, "color": "#ff0000"}),
            ),
            (
                MixerChange(track=1, sends={"A": "-12 dB"}, mute=False),
                self.adapter.set_mixer,
                ("ableton.set_mixer", {"track": 1, "sends": {"A": "-12 dB"}, "mute": False}),
            ),
            (
                DeviceInsert(track=1, device_name="Utility", parameters={"Gain": "-3 dB"}),
                self.adapter.insert_device,
                (
                    "ableton.insert_device",
                    {"track": 1, "device_name": "Utility", "parameters": {"Gain": "-3 dB"}},
                ),
            ),
            (
                ReturnTrackCreate(name="Room"),
                self.adapter.create_return_track,
                ("ableton.create_return_track", {"name": "Room"}),
            ),
            (
                DeviceDelete(track=1, device=0),
                self.adapter.delete_device,
                ("ableton.delete_device", {"track": 1, "device": 0, "confirm": False}),
            ),
        ]
        for change, method, expected in cases:
            with self.subTest(expected=expected[0]):
                method(change)
                self.assertEqual(self.last(), expected)

    def test_execute_drum_rack_extraction_sends_confirm(self) -> None:
        self.adapter.execute_drum_rack_extraction()
        self.assertEqual(
            self.last(),
            ("workflow.execute_drum_rack_extraction", {"target_daw": "ableton", "confirm": True}),
        )

    def test_target_daw_is_passed_through(self) -> None:
        RemoteScriptAdapter(self.bridge, target_daw="fl-studio").plan_drum_rack_extraction()
        self.assertEqual(self.last()[1], {"target_daw": "fl-studio"})


class BatchTests(unittest.TestCase):
    def test_atomic_batch(self) -> None:
        bridge = RecordingBridge({"ableton.batch": {"completed": 2, "undo_steps": "one"}})
        result = RemoteScriptAdapter(bridge).apply_batch(
            Batch(
                operations=(
                    MixerChange(track=0, volume="-6 dB"),
                    DeviceDelete(track=1, device=0, confirm=True),
                )
            )
        )
        self.assertEqual(
            bridge.calls[-1],
            (
                "ableton.batch",
                {
                    "operations": [
                        {"method": "ableton.set_mixer", "params": {"track": 0, "volume": "-6 dB"}},
                        {
                            "method": "ableton.delete_device",
                            "params": {"track": 1, "device": 0, "confirm": True},
                        },
                    ]
                },
            ),
        )
        self.assertNotIn("warning", result)

    def test_non_atomic_batch_sends_atomic_false(self) -> None:
        bridge = RecordingBridge({"ableton.batch": {"undo_steps": "per_operation"}})
        result = RemoteScriptAdapter(bridge).apply_batch(
            Batch(operations=(MixerChange(track=0, mute=True),), atomic=False)
        )
        self.assertIs(bridge.calls[-1][1]["atomic"], False)
        self.assertNotIn("warning", result)

    def test_old_script_batch_warns(self) -> None:
        bridge = RecordingBridge({"ableton.batch": {"completed": 1}})
        result = RemoteScriptAdapter(bridge).apply_batch(
            Batch(operations=(MixerChange(track=0, mute=True),), atomic=False)
        )
        self.assertEqual(result["warning"], OLD_SCRIPT_BATCH_WARNING)


class UndoTests(unittest.TestCase):
    def test_single_undo_sends_no_params(self) -> None:
        bridge = RecordingBridge()
        RemoteScriptAdapter(bridge).undo(UndoRequest())
        self.assertEqual(bridge.calls[-1], ("ableton.undo", {}))

    def test_several_undo_steps_send_count_and_confirm(self) -> None:
        bridge = RecordingBridge({"ableton.undo": {"steps": 3}})
        result = RemoteScriptAdapter(bridge).undo(UndoRequest(count=3, confirm=True))
        self.assertEqual(bridge.calls[-1], ("ableton.undo", {"count": 3, "confirm": True}))
        self.assertEqual(result, {"steps": 3})

    def test_several_steps_without_confirm_send_nothing(self) -> None:
        bridge = RecordingBridge()
        with self.assertRaises(AdapterRefused) as caught:
            RemoteScriptAdapter(bridge).undo(UndoRequest(count=2))
        self.assertEqual(caught.exception.code, "confirmation_required")
        self.assertEqual(bridge.calls, [])

    def test_old_script_undo_warns(self) -> None:
        bridge = RecordingBridge({"ableton.undo": {"undone": True}})
        result = RemoteScriptAdapter(bridge).undo(UndoRequest(count=2, confirm=True))
        self.assertEqual(result["steps"], 1)
        self.assertEqual(result["warning"], OLD_SCRIPT_UNDO_WARNING)


class HealthTests(unittest.TestCase):
    def test_capabilities_read_health_once(self) -> None:
        bridge = RecordingBridge({"daw.health": HEALTH})
        adapter = RemoteScriptAdapter(bridge)
        self.assertIn("set_mixer", adapter.capabilities())
        self.assertIn("list_tracks", adapter.capabilities())
        self.assertEqual([c[0] for c in bridge.calls], ["daw.health"])
        self.assertEqual(bridge.calls[0][1], {"target_daw": "ableton"})

    def test_bad_health_is_rejected(self) -> None:
        bridge = RecordingBridge({"daw.health": {"target_daw": "ableton"}})
        with self.assertRaises(AdapterResponseError):
            RemoteScriptAdapter(bridge).health()

    def test_connection_error_forgets_health(self) -> None:
        bridge = RecordingBridge({"daw.health": HEALTH})
        adapter = RemoteScriptAdapter(bridge)
        adapter.capabilities()
        bridge.error = BridgeConnectionError("could not connect to 127.0.0.1:39877")
        with self.assertRaises(AdapterUnavailable):
            adapter.list_tracks(TrackQuery())
        bridge.error = None
        adapter.capabilities()
        self.assertEqual([c[0] for c in bridge.calls].count("daw.health"), 2)


class ErrorTests(unittest.TestCase):
    def test_refusal_keeps_the_text_tools_show(self) -> None:
        bridge = RecordingBridge()
        bridge.error = BridgeRefusedError(
            "not_found: no track 'X' Hint: Use list_tracks.",
            code="not_found",
            message="no track 'X'",
            hint="Use list_tracks.",
        )
        with self.assertRaises(AdapterRefused) as caught:
            RemoteScriptAdapter(bridge).set_mixer(MixerChange(track="X", mute=True))
        self.assertEqual(str(caught.exception), "not_found: no track 'X' Hint: Use list_tracks.")
        self.assertEqual(caught.exception.code, "not_found")

    def test_refusal_text_matches_the_client_for_odd_payloads(self) -> None:
        from abletonian.bridge.client import _format_bridge_error, _text_or_none

        payloads = [
            {"code": "adapter_error", "message": "", "hint": "Check daw.health."},
            {"code": "", "message": "m"},
            {"code": "x", "message": None},
            {"code": 7, "message": "m"},
            {"code": "x", "message": "m", "hint": ["a"]},
            {},
            "boom",
            None,
        ]
        for payload in payloads:
            with self.subTest(payload=payload):
                fields = payload if isinstance(payload, dict) else {}
                bridge = RecordingBridge()
                bridge.error = BridgeRefusedError(
                    _format_bridge_error(payload),
                    code=_text_or_none(fields.get("code")),
                    message=_text_or_none(fields.get("message")),
                    hint=_text_or_none(fields.get("hint")),
                )
                with self.assertRaises(AdapterRefused) as caught:
                    RemoteScriptAdapter(bridge).list_tracks(TrackQuery())
                self.assertEqual(str(caught.exception), _format_bridge_error(payload))

    def test_unavailable_keeps_the_message(self) -> None:
        bridge = RecordingBridge()
        bridge.error = BridgeConnectionError("could not connect to 127.0.0.1:39877")
        with self.assertRaises(AdapterUnavailable) as caught:
            RemoteScriptAdapter(bridge).list_tracks(TrackQuery())
        self.assertEqual(str(caught.exception), "could not connect to 127.0.0.1:39877")


class SidechainWireTests(unittest.TestCase):
    def test_set_device_sidechain_sends_names_and_drops_unset_channel(self) -> None:
        bridge = RecordingBridge()
        adapter = RemoteScriptAdapter(bridge)

        adapter.set_device_sidechain(SidechainChange(track="Bass", device=1, from_track="1-Kick"))
        adapter.set_device_sidechain(
            SidechainChange(track=1, device="Compressor", from_track="Kick", channel="Post FX")
        )

        self.assertEqual(
            bridge.calls,
            [
                (
                    "ableton.set_device_sidechain",
                    {"track": "Bass", "device": 1, "from_track": "1-Kick"},
                ),
                (
                    "ableton.set_device_sidechain",
                    {
                        "track": 1,
                        "device": "Compressor",
                        "from_track": "Kick",
                        "channel": "Post FX",
                    },
                ),
            ],
        )


class ClipWireTests(unittest.TestCase):
    def test_list_clips_and_set_clip_gain(self) -> None:
        bridge = RecordingBridge()
        adapter = RemoteScriptAdapter(bridge)

        adapter.list_clips(ClipQuery(track="Bass"))
        adapter.set_clip_gain(ClipGainChange(track=1, clip=0, gain_db="-3 dB"))
        adapter.set_clip_gain(ClipGainChange(track="Bass", clip="Intro", gain_db=-6.0))

        self.assertEqual(
            bridge.calls,
            [
                ("ableton.list_clips", {"track": "Bass"}),
                ("ableton.set_clip_gain", {"track": 1, "clip": 0, "gain_db": "-3 dB"}),
                ("ableton.set_clip_gain", {"track": "Bass", "clip": "Intro", "gain_db": -6.0}),
            ],
        )


if __name__ == "__main__":
    unittest.main()
