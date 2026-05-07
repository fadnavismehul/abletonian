import unittest

import _bootstrap  # noqa: F401

from abletonian.bridge.protocol import BridgeRequest, BridgeResponse, decode_frame, encode_frame


class ProtocolTests(unittest.TestCase):
    def test_round_trips_request_frame(self) -> None:
        request = BridgeRequest(id="abc123", method="live.health", params={"probe": True})

        decoded = decode_frame(encode_frame(request.to_wire()))

        self.assertEqual(
            decoded,
            {
                "id": "abc123",
                "method": "live.health",
                "params": {"probe": True},
            },
        )

    def test_round_trips_response_frame(self) -> None:
        response = BridgeResponse(id="abc123", ok=True, result={"status": "ok"})

        decoded = decode_frame(encode_frame(response.to_wire()))

        self.assertEqual(decoded["id"], "abc123")
        self.assertTrue(decoded["ok"])
        self.assertEqual(decoded["result"], {"status": "ok"})

    def test_rejects_truncated_frame(self) -> None:
        frame = encode_frame({"ok": True})

        with self.assertRaises(ValueError):
            decode_frame(frame[:-1])


if __name__ == "__main__":
    unittest.main()
