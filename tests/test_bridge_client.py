import unittest
from unittest.mock import patch

import _bootstrap  # noqa: F401

from abletonian.bridge.client import BridgeClient, BridgeConnectionError
from abletonian.bridge.protocol import BridgeErrorPayload, BridgeResponse, encode_frame


class FakeSocket:
    def __init__(self, payload: bytes) -> None:
        self.payload = payload
        self.sent = b""
        self.timeout: float | None = None

    def __enter__(self) -> "FakeSocket":
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:  # noqa: ANN001
        return None

    def settimeout(self, timeout: float) -> None:
        self.timeout = timeout

    def sendall(self, payload: bytes) -> None:
        self.sent += payload

    def recv(self, length: int) -> bytes:
        chunk = self.payload[:length]
        self.payload = self.payload[length:]
        return chunk


class BridgeClientTests(unittest.TestCase):
    def test_raises_bridge_error_with_typed_payload_details(self) -> None:
        socket = FakeSocket(
            encode_frame(
                BridgeResponse(
                    id="request-id",
                    ok=False,
                    error=BridgeErrorPayload(
                        code="unsupported_method",
                        message="method is not supported by this adapter",
                        recoverable=False,
                        hint="Call daw.health and choose a supported capability.",
                    ),
                ).to_wire()
            )
        )

        with patch("abletonian.bridge.client.BridgeRequest") as request_type:
            request_type.return_value.id = "request-id"
            request_type.return_value.to_wire.return_value = {
                "id": "request-id",
                "method": "workflow.missing",
                "params": {},
            }
            with patch("socket.create_connection", return_value=socket):
                client = BridgeClient("127.0.0.1", 9877, 1.0)

                with self.assertRaises(BridgeConnectionError) as raised:
                    client.request("workflow.missing")

        self.assertIn("unsupported_method", str(raised.exception))
        self.assertIn("method is not supported", str(raised.exception))
        self.assertIn("Call daw.health", str(raised.exception))
