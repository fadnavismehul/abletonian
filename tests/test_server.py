import asyncio
import json
import unittest

import _bootstrap  # noqa: F401

from abletonian.config import AbletonianConfig
from abletonian.server import build_mcp


class RecordingBridge:
    def __init__(self) -> None:
        self.requests: list[tuple[str, dict[str, object]]] = []

    def request(self, method: str, params: dict[str, object] | None = None) -> dict[str, object]:
        self.requests.append((method, params or {}))
        if method == "workflow.plan_drum_rack_extraction":
            return {"operation": "split_drum_rack", "mode": "dry_run"}
        raise AssertionError(f"unexpected method: {method}")


def tool_text(result: object) -> str:
    return result[0][0].text  # type: ignore[index, no-any-return]


class ServerToolTests(unittest.TestCase):
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
