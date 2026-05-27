import unittest

import _bootstrap  # noqa: F401

from abletonian.adapters.fake import FakeAbletonAdapter, FakeAbletonState
from abletonian.bridge.dispatcher import dispatch_frame
from abletonian.bridge.protocol import decode_frame, encode_frame


class BridgeDispatcherTests(unittest.TestCase):
    def test_dispatches_framed_request_to_adapter_and_preserves_request_id(self) -> None:
        adapter = FakeAbletonAdapter(FakeAbletonState(live_version="12.1.0"))
        request = encode_frame(
            {
                "id": "request-123",
                "method": "daw.health",
                "params": {"target_daw": "ableton"},
            }
        )

        response = decode_frame(dispatch_frame(adapter, request))

        self.assertEqual(response["id"], "request-123")
        self.assertTrue(response["ok"])
        self.assertEqual(response["result"]["adapter_type"], "fake")
        self.assertEqual(response["result"]["live_version"], "12.1.0")

    def test_returns_typed_error_for_unknown_adapter_method(self) -> None:
        adapter = FakeAbletonAdapter(FakeAbletonState(live_version="12.1.0"))
        request = encode_frame(
            {
                "id": "request-456",
                "method": "workflow.not_supported",
                "params": {},
            }
        )

        response = decode_frame(dispatch_frame(adapter, request))

        self.assertEqual(response["id"], "request-456")
        self.assertFalse(response["ok"])
        self.assertEqual(response["error"]["code"], "adapter_error")
        self.assertFalse(response["error"]["recoverable"])
        self.assertIn("unsupported fake adapter method", response["error"]["message"])

    def test_returns_typed_error_for_invalid_frame_without_request_id(self) -> None:
        response = decode_frame(dispatch_frame(FakeAbletonAdapter(), b"\x00\x00\x00\x02{}"))

        self.assertEqual(response["id"], "")
        self.assertFalse(response["ok"])
        self.assertEqual(response["error"]["code"], "invalid_frame")
        self.assertFalse(response["error"]["recoverable"])
