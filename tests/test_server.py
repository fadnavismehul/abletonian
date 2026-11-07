import asyncio
import json
import unittest

import _bootstrap  # noqa: F401

from abletonian.adapters.fake import (
    FakeAbletonAdapter,
    FakeAbletonState,
    FakeRackDevice,
    FakeRackMacro,
    FakeTrack,
)
from abletonian.config import AbletonianConfig
from abletonian.server import build_mcp


class RecordingBridge:
    def __init__(self) -> None:
        self.requests: list[tuple[str, dict[str, object]]] = []

    def request(self, method: str, params: dict[str, object] | None = None) -> dict[str, object]:
        self.requests.append((method, params or {}))
        if method == "workflow.plan_drum_rack_extraction":
            return {"operation": "split_drum_rack", "mode": "dry_run"}
        if method == "workflow.execute_drum_rack_extraction":
            return {"operation": "split_drum_rack", "mode": "execute"}
        raise AssertionError(f"unexpected method: {method}")


def tool_text(result: object) -> str:
    return result.content[0].text  # type: ignore[attr-defined, no-any-return]


class FakeAdapterBridge:
    def __init__(self, adapter: FakeAbletonAdapter) -> None:
        self.adapter = adapter
        self.methods: list[str] = []

    def request(self, method: str, params: dict[str, object] | None = None) -> dict[str, object]:
        self.methods.append(method)
        return self.adapter.handle_request(method, params)


class RecordingOnlyBridge:
    def __init__(self) -> None:
        self.requests: list[tuple[str, dict[str, object]]] = []

    def request(self, method: str, params: dict[str, object] | None = None) -> dict[str, object]:
        self.requests.append((method, params or {}))
        return {"ok": True}


class DeleteDeviceToolTests(unittest.TestCase):
    """Review of PR #21: the tool must not turn "true", 1, "yes" into confirm=True."""

    def call(self, confirm: object) -> RecordingOnlyBridge:
        bridge = RecordingOnlyBridge()
        mcp = build_mcp(AbletonianConfig(), bridge=bridge)
        try:
            asyncio.run(
                mcp.call_tool("delete_device", {"track": 0, "device": 0, "confirm": confirm})
            )
        except Exception:  # noqa: BLE001 - a validation error is an acceptable refusal
            pass
        return bridge

    def test_non_boolean_confirm_never_reaches_the_bridge_as_true(self) -> None:
        for confirm in ("true", "yes", 1, "1", "on", "True"):
            with self.subTest(confirm=confirm):
                sent = [params.get("confirm") for _m, params in self.call(confirm).requests]
                self.assertNotIn(True, sent)

    def test_boolean_confirm_passes_through(self) -> None:
        self.assertEqual(self.call(True).requests[0][1]["confirm"], True)
        self.assertEqual(self.call(False).requests[0][1]["confirm"], False)


class ServerToolTests(unittest.TestCase):
    def test_generate_macro_cockpit_reads_rack_and_returns_spec_and_text(self) -> None:
        adapter = FakeAbletonAdapter(
            FakeAbletonState(
                live_version="12.4.16",
                tracks=(
                    FakeTrack(
                        id="t0",
                        name="Keys",
                        devices=(
                            FakeRackDevice("r", "Keys Rack", (FakeRackMacro(1, "Cutoff", 100.0),)),
                        ),
                    ),
                ),
                selected_track_id="t0",
            )
        )
        bridge = FakeAdapterBridge(adapter)
        mcp = build_mcp(AbletonianConfig(), bridge=bridge)

        result = json.loads(tool_text(asyncio.run(mcp.call_tool("generate_macro_cockpit", {}))))

        self.assertEqual(bridge.methods, ["ableton.get_selected_rack_macros", "daw.health"])
        self.assertEqual(result["cockpit"]["title"], "Keys Rack Macro Cockpit")
        self.assertEqual(result["cockpit"]["groups"][0]["id"], "tone")
        self.assertIn("[ 1] Cutoff", result["text"])

    def test_plan_drum_rack_extraction_delegates_to_bridge(self) -> None:
        bridge = RecordingBridge()
        mcp = build_mcp(AbletonianConfig(), bridge=bridge)

        result = asyncio.run(mcp.call_tool("plan_drum_rack_extraction", {}))

        self.assertEqual(
            bridge.requests,
            [("workflow.plan_drum_rack_extraction", {"target_daw": "ableton"})],
        )
        self.assertEqual(
            json.loads(tool_text(result)),
            {"operation": "split_drum_rack", "mode": "dry_run"},
        )

    def test_execute_drum_rack_extraction_requires_confirmation(self) -> None:
        bridge = RecordingBridge()
        mcp = build_mcp(AbletonianConfig(), bridge=bridge)

        result = asyncio.run(mcp.call_tool("execute_drum_rack_extraction", {}))

        self.assertIn("requires confirm=true", tool_text(result))
        self.assertEqual(bridge.requests, [])

    def test_execute_drum_rack_extraction_delegates_to_bridge_after_confirmation(self) -> None:
        bridge = RecordingBridge()
        mcp = build_mcp(AbletonianConfig(), bridge=bridge)

        result = asyncio.run(mcp.call_tool("execute_drum_rack_extraction", {"confirm": True}))

        self.assertEqual(
            bridge.requests,
            [("workflow.execute_drum_rack_extraction", {"target_daw": "ableton", "confirm": True})],
        )
        self.assertEqual(
            json.loads(tool_text(result)),
            {"operation": "split_drum_rack", "mode": "execute"},
        )

    def test_lookup_ableton_manual_returns_cited_result(self) -> None:
        mcp = build_mcp(AbletonianConfig())

        result = asyncio.run(
            mcp.call_tool(
                "lookup_ableton_manual",
                {
                    "query": "extract drum rack chains",
                    "live_version": "12",
                },
            )
        )
        payload = json.loads(tool_text(result))

        self.assertEqual(payload["status"], "ok")
        self.assertGreaterEqual(len(payload["citations"]), 1)


class PassthroughBridge:
    def __init__(self) -> None:
        self.requests: list[tuple[str, dict[str, object]]] = []

    def request(self, method: str, params: dict[str, object] | None = None) -> dict[str, object]:
        self.requests.append((method, params or {}))
        return {"ok": True}


class LiveControlToolTests(unittest.TestCase):
    def test_insert_device_drops_unset_arguments(self) -> None:
        bridge = PassthroughBridge()
        mcp = build_mcp(AbletonianConfig(), bridge=bridge)

        asyncio.run(
            mcp.call_tool(
                "insert_device",
                {"track": "Kick", "device_name": "Utility", "parameters": {"Gain": "-3 dB"}},
            )
        )

        self.assertEqual(
            bridge.requests,
            [
                (
                    "ableton.insert_device",
                    {"track": "Kick", "device_name": "Utility", "parameters": {"Gain": "-3 dB"}},
                )
            ],
        )

    def test_parameter_values_keep_their_form(self) -> None:
        # Issue #43: a string is display text, {"raw": n} is raw, and a bare
        # number stays a number for the Remote Script to read.
        bridge = PassthroughBridge()
        mcp = build_mcp(AbletonianConfig(), bridge=bridge)
        target = {"track": "16 Vox", "device": 0, "parameter": "2 Q A"}

        for value in ("1.00", {"raw": 1.0}, 1):
            asyncio.run(mcp.call_tool("set_device_parameter", {**target, "value": value}))
        asyncio.run(
            mcp.call_tool(
                "insert_device",
                {"track": 0, "device_name": "EQ Eight", "parameters": {"2 Q A": {"raw": 0.5}}},
            )
        )

        values = [params.get("value") for _method, params in bridge.requests[:3]]
        self.assertEqual(values, ["1.00", {"raw": 1.0}, 1])
        self.assertIsInstance(values[0], str)
        self.assertEqual(bridge.requests[3][1]["parameters"], {"2 Q A": {"raw": 0.5}})

    def test_track_accepts_index_or_name(self) -> None:
        bridge = PassthroughBridge()
        mcp = build_mcp(AbletonianConfig(), bridge=bridge)

        asyncio.run(mcp.call_tool("set_track_output_routing", {"track": 3, "routing_type": "Main"}))
        asyncio.run(mcp.call_tool("set_mixer", {"track": "Vox", "sends": {"A": "-12 dB"}}))

        self.assertEqual(bridge.requests[0][1], {"track": 3, "routing_type": "Main"})
        self.assertEqual(bridge.requests[1][1], {"track": "Vox", "sends": {"A": "-12 dB"}})

    def test_batch_passes_operations_through(self) -> None:
        bridge = PassthroughBridge()
        mcp = build_mcp(AbletonianConfig(), bridge=bridge)
        operations = [{"method": "ableton.set_mixer", "params": {"track": 0, "mute": True}}]

        asyncio.run(mcp.call_tool("apply_batch", {"operations": operations}))

        self.assertEqual(bridge.requests, [("ableton.batch", {"operations": operations})])


class ToolAnnotationTests(unittest.TestCase):
    """Annotations follow the safety classes so clients can tell reads from changes."""

    def setUp(self) -> None:
        mcp = build_mcp(AbletonianConfig(), bridge=PassthroughBridge())
        self.tools = {tool.name: tool for tool in asyncio.run(mcp.list_tools())}

    def test_every_tool_is_annotated(self) -> None:
        for name, tool in self.tools.items():
            with self.subTest(tool=name):
                self.assertIsNotNone(tool.annotations)
                self.assertIsNotNone(tool.annotations.read_only_hint)

    def test_reads_are_read_only(self) -> None:
        reads = ("list_tracks", "list_devices", "generate_macro_cockpit", "check_bridge_health")
        for name in reads:
            with self.subTest(tool=name):
                self.assertTrue(self.tools[name].annotations.read_only_hint)

    def test_changes_are_not_read_only_and_deletes_are_destructive(self) -> None:
        for name in ("set_mixer", "insert_device", "delete_device", "apply_batch"):
            with self.subTest(tool=name):
                self.assertFalse(self.tools[name].annotations.read_only_hint)
        self.assertTrue(self.tools["delete_device"].annotations.destructive_hint)
        self.assertFalse(self.tools["insert_device"].annotations.destructive_hint)
        self.assertFalse(self.tools["insert_device"].annotations.idempotent_hint)


class OldScriptBridge(PassthroughBridge):
    """A Remote Script from before per-step undo: ignores atomic and count."""

    def request(self, method: str, params: dict[str, object] | None = None) -> dict[str, object]:
        super().request(method, params)
        if method == "ableton.undo":
            return {"undone": True}
        return {"completed": [], "failed": None, "grouped_undo": True}


class UndoToolTests(unittest.TestCase):
    def call(self, bridge: PassthroughBridge, tool: str, args: dict[str, object]) -> str:
        mcp = build_mcp(AbletonianConfig(), bridge=bridge)
        result = asyncio.run(mcp.call_tool(tool, args))
        return result.content[0].text if hasattr(result, "content") else str(result)

    def test_non_atomic_batch_and_undo_count_reach_the_bridge(self) -> None:
        bridge = PassthroughBridge()
        operations = [{"method": "ableton.set_mixer", "params": {"track": 0, "mute": True}}]

        self.call(bridge, "apply_batch", {"operations": operations, "atomic": False})
        self.call(bridge, "undo_last_change", {"count": 3, "confirm": True})
        self.call(bridge, "undo_last_change", {})

        self.assertEqual(
            bridge.requests,
            [
                ("ableton.batch", {"operations": operations, "atomic": False}),
                ("ableton.undo", {"count": 3, "confirm": True}),
                ("ableton.undo", {}),
            ],
        )

    def test_undo_count_out_of_range_never_reaches_the_bridge(self) -> None:
        bridge = PassthroughBridge()

        text = self.call(bridge, "undo_last_change", {"count": 50})

        self.assertIn("1 to 20", text)
        self.assertEqual(bridge.requests, [])

    def test_an_older_remote_script_is_reported(self) -> None:
        operations = [{"method": "ableton.set_mixer", "params": {"track": 0, "mute": True}}]

        batch = self.call(
            OldScriptBridge(), "apply_batch", {"operations": operations, "atomic": False}
        )
        undo = self.call(OldScriptBridge(), "undo_last_change", {"count": 2, "confirm": True})

        self.assertIn("older", batch)
        self.assertIn("undid only one step", undo)

    def test_undoing_several_steps_needs_confirmation(self) -> None:
        bridge = PassthroughBridge()

        text = self.call(bridge, "undo_last_change", {"count": 3})

        self.assertIn("confirm=true", text)
        self.assertEqual(bridge.requests, [])
