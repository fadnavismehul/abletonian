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
