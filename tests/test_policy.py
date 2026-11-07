import asyncio
import json
import unittest
from typing import Any

import _bootstrap  # noqa: F401

from abletonian.adapters.base import (
    AdapterRefused,
    DeviceDelete,
    MixerChange,
    UnsupportedOperation,
)
from abletonian.adapters.remote_script import RemoteScriptAdapter
from abletonian.bridge.client import BridgeRefusedError
from abletonian.config import AbletonianConfig
from abletonian.policy import OPERATIONS, PolicyRefused, SafetyClass, SafetyPolicy
from abletonian.server import build_mcp, parse_batch

HEALTH = {
    "target_daw": "ableton",
    "adapter_type": "ableton_remote_script",
    "adapter_version": "0.5.0",
    "live_version": "12.4.16",
    "protocol_version": "abletonian.bridge.v1",
    "capabilities": ["list_tracks", "set_mixer", "batch", "delete_device"],
    "unsupported_capabilities": [],
}

# Which operation each DAW-facing tool runs. Tools not listed here must be
# read-only or only write local files.
TOOL_OPERATIONS = {
    "list_tracks": "list_tracks",
    "list_devices": "list_devices",
    "get_device": "get_device",
    "list_clips": "list_clips",
    "set_clip_gain": "set_clip_gain",
    "set_device_parameter": "set_device_parameter",
    "set_track_output_routing": "set_track_output_routing",
    "set_track_properties": "set_track_properties",
    "set_mixer": "set_mixer",
    "set_device_sidechain": "set_device_sidechain",
    "insert_device": "insert_device",
    "create_return_track": "create_return_track",
    "delete_device": "delete_device",
    "apply_batch": "batch",
    "undo_last_change": "undo",
    "plan_drum_rack_extraction": "plan_drum_rack_extraction",
    "execute_drum_rack_extraction": "execute_drum_rack_extraction",
    "generate_macro_cockpit": "get_selected_rack_macros",
    "open_macro_cockpit": "get_selected_rack_macros",
}
LOCAL_FILE_TOOLS = {"save_macro_cockpit", "show_macro_cockpit"}


class Bridge:
    def __init__(self, results: dict[str, Any] | None = None) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.results = results or {}

    def request(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        self.calls.append((method, params or {}))
        result = self.results.get(method, {"ok": True})
        if isinstance(result, Exception):
            raise result
        return result


def call_tool(bridge: Bridge, tool: str, args: dict[str, Any]) -> str:
    mcp = build_mcp(AbletonianConfig(), bridge=bridge)
    result = asyncio.run(mcp.call_tool(tool, args))
    return result.content[0].text  # type: ignore[attr-defined, no-any-return]


class PolicyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.bridge = Bridge({"daw.health": HEALTH})
        self.adapter = RemoteScriptAdapter(self.bridge)
        self.policy = SafetyPolicy(self.adapter, clock=lambda: 1.0)

    def test_unknown_capabilities_do_not_add_a_round_trip(self) -> None:
        change = MixerChange(track=0, mute=True)
        self.policy.run("set_mixer", change, lambda: self.adapter.set_mixer(change))
        self.assertEqual([c[0] for c in self.bridge.calls], ["ableton.set_mixer"])

    def test_missing_capability_is_refused_before_sending(self) -> None:
        self.adapter.health()
        self.bridge.calls.clear()
        with self.assertRaises(UnsupportedOperation):
            self.policy.run("insert_device", None, lambda: {"sent": True})
        self.assertEqual(self.bridge.calls, [])
        self.assertEqual(self.policy.log[-1].outcome, "UnsupportedOperation")

    def test_advertised_capability_runs(self) -> None:
        self.adapter.health()
        change = MixerChange(track=0, mute=True)
        result = self.policy.run("set_mixer", change, lambda: self.adapter.set_mixer(change))
        self.assertEqual(result, {"ok": True})
        self.assertEqual(self.policy.log[-1].outcome, "ok")

    def test_delete_preview_logs_as_read_only(self) -> None:
        preview = DeviceDelete(track=0, device=0)
        self.policy.run("delete_device", preview, lambda: {"preview": True})
        self.assertIs(self.policy.log[-1].safety_class, SafetyClass.READ_ONLY)
        confirmed = DeviceDelete(track=0, device=0, confirm=True)
        self.policy.run("delete_device", confirmed, lambda: {"deleted": True})
        self.assertIs(self.policy.log[-1].safety_class, SafetyClass.DESTRUCTIVE)

    def test_adapter_errors_are_logged_and_raised(self) -> None:
        def fail() -> dict[str, Any]:
            raise AdapterRefused("no track 'X'", code="not_found")

        with self.assertRaises(AdapterRefused):
            self.policy.run("list_tracks", None, fail)
        self.assertEqual(self.policy.log[-1].outcome, "AdapterRefused")

    def test_undo_steps_are_recorded(self) -> None:
        self.policy.run("batch", _batch(), lambda: {"undo_steps": "one"})
        self.assertEqual(self.policy.log[-1].undo_steps, "one")

    def test_log_is_bounded(self) -> None:
        for _ in range(SafetyPolicy.MAX_LOG_ENTRIES + 5):
            self.policy.run("list_tracks", None, lambda: {})
        self.assertEqual(len(self.policy.log), SafetyPolicy.MAX_LOG_ENTRIES)

    def test_policy_refusal_sends_nothing(self) -> None:
        with self.assertRaises(PolicyRefused):
            self.policy.run("execute_drum_rack_extraction", False, lambda: {"sent": True})
        self.assertEqual(self.bridge.calls, [])
        self.assertEqual(self.policy.log[-1].outcome, "refused_by_policy")


def _batch() -> Any:
    from abletonian.adapters.base import Batch

    return Batch(operations=(MixerChange(track=0, mute=True),))


class AnnotationTests(unittest.TestCase):
    def setUp(self) -> None:
        mcp = build_mcp(AbletonianConfig(), bridge=Bridge())
        self.tools = {tool.name: tool for tool in asyncio.run(mcp.list_tools())}

    def test_daw_tools_take_annotations_from_the_table(self) -> None:
        for tool, operation in TOOL_OPERATIONS.items():
            with self.subTest(tool=tool):
                self.assertEqual(self.tools[tool].annotations, OPERATIONS[operation].annotations())

    def test_every_tool_that_can_change_things_is_accounted_for(self) -> None:
        for name, tool in self.tools.items():
            if tool.annotations.read_only_hint:
                continue
            with self.subTest(tool=name):
                self.assertTrue(name in TOOL_OPERATIONS or name in LOCAL_FILE_TOOLS)

    def test_every_operation_is_used(self) -> None:
        self.assertEqual(set(TOOL_OPERATIONS.values()), set(OPERATIONS))


class BatchParsingTests(unittest.TestCase):
    def test_unknown_method(self) -> None:
        with self.assertRaisesRegex(ValueError, "operation 1 has unsupported method"):
            parse_batch(
                [
                    {"method": "ableton.set_mixer", "params": {"track": 0}},
                    {"method": "ableton.explode", "params": {}},
                ]
            )

    def test_unknown_parameter(self) -> None:
        with self.assertRaisesRegex(ValueError, r"operation 0 \(ableton.set_mixer\)"):
            parse_batch([{"method": "ableton.set_mixer", "params": {"track": 0, "gain": 1}}])

    def test_params_must_be_an_object(self) -> None:
        with self.assertRaisesRegex(ValueError, "params must be an object"):
            parse_batch([{"method": "ableton.set_mixer", "params": [1]}])

    def test_nulls_are_dropped(self) -> None:
        (change,) = parse_batch(
            [
                {
                    "method": "ableton.set_track_output_routing",
                    "params": {"track": 0, "routing_type": "Main", "routing_channel": None},
                }
            ]
        )
        self.assertEqual(change.params(), {"track": 0, "routing_type": "Main"})


class ToolBehaviourTests(unittest.TestCase):
    def test_unconfirmed_delete_in_batch_sends_nothing(self) -> None:
        bridge = Bridge()
        text = call_tool(
            bridge,
            "apply_batch",
            {
                "operations": [
                    {"method": "ableton.set_mixer", "params": {"track": 0, "mute": True}},
                    {"method": "ableton.delete_device", "params": {"track": 0, "device": 0}},
                ]
            },
        )
        self.assertIn('operation 1 (ableton.delete_device) needs "confirm": true', text)
        self.assertEqual(bridge.calls, [])

    def test_string_confirm_in_batch_is_not_a_confirm(self) -> None:
        bridge = Bridge()
        call_tool(
            bridge,
            "apply_batch",
            {
                "operations": [
                    {
                        "method": "ableton.delete_device",
                        "params": {"track": 0, "device": 0, "confirm": "true"},
                    }
                ]
            },
        )
        self.assertEqual(bridge.calls, [])

    def test_bad_batch_says_nothing_changed(self) -> None:
        bridge = Bridge()
        text = call_tool(bridge, "apply_batch", {"operations": [{"method": "nope"}]})
        self.assertIn("Nothing was changed.", text)
        self.assertEqual(bridge.calls, [])

    def test_refusal_text_is_unchanged(self) -> None:
        bridge = Bridge(
            {
                "ableton.set_mixer": BridgeRefusedError(
                    "not_found: no track 'X' Hint: Use list_tracks.",
                    code="not_found",
                    message="no track 'X'",
                    hint="Use list_tracks.",
                )
            }
        )
        text = call_tool(bridge, "set_mixer", {"track": "X", "mute": True})
        self.assertEqual(text, "Bridge error: not_found: no track 'X' Hint: Use list_tracks.")

    def test_health_prints_the_raw_answer(self) -> None:
        bridge = Bridge({"daw.health": HEALTH})
        self.assertEqual(json.loads(call_tool(bridge, "check_bridge_health", {})), HEALTH)

    def test_unusable_health_is_named(self) -> None:
        bridge = Bridge({"daw.health": {"target_daw": "ableton"}})
        text = call_tool(bridge, "check_bridge_health", {})
        self.assertIn("health report is not usable", text)

    def test_after_health_an_unsupported_tool_is_refused_locally(self) -> None:
        bridge = Bridge({"daw.health": HEALTH})
        mcp = build_mcp(AbletonianConfig(), bridge=bridge)
        asyncio.run(mcp.call_tool("check_bridge_health", {}))
        result = asyncio.run(
            mcp.call_tool("create_return_track", {"name": "Room"})
        )
        text = result.content[0].text  # type: ignore[attr-defined]
        self.assertIn("cannot create return track", text)
        self.assertIn("run check_bridge_health", text)
        self.assertEqual([c[0] for c in bridge.calls], ["daw.health"])

    def test_drum_rack_execute_needs_a_real_true(self) -> None:
        for loose in ("true", 1, "yes"):
            with self.subTest(confirm=loose):
                bridge = Bridge()
                mcp = build_mcp(AbletonianConfig(), bridge=bridge)
                try:
                    asyncio.run(
                        mcp.call_tool("execute_drum_rack_extraction", {"confirm": loose})
                    )
                except Exception:  # noqa: BLE001 - pydantic may reject it outright
                    pass
                self.assertEqual(bridge.calls, [])


if __name__ == "__main__":
    unittest.main()
