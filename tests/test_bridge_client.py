import json
import os
import tempfile
import unittest
from unittest.mock import patch

import _bootstrap  # noqa: F401

from abletonian.bridge.client import BridgeClient, BridgeConnectionError, BridgeRefusedError
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
    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.key_path = os.path.join(directory.name, "bridge_key")
        with open(self.key_path, "w", encoding="ascii") as handle:
            handle.write("ab" * 32 + "\n")

    def ok_socket(self) -> FakeSocket:
        return FakeSocket(encode_frame(BridgeResponse(id="request-id", ok=True).to_wire()))

    def test_sends_the_key_on_every_frame(self) -> None:
        sock = self.ok_socket()
        with patch("abletonian.bridge.protocol.uuid4") as uuid4:
            uuid4.return_value.hex = "request-id"
            with patch("socket.create_connection", return_value=sock):
                BridgeClient("127.0.0.1", 39877, 1.0, key_path=self.key_path).request(
                    "daw.health"
                )
        sent = json.loads(sock.sent[4:])
        self.assertEqual(sent["key"], "ab" * 32)

    def test_missing_key_file_says_how_to_create_it(self) -> None:
        missing = self.key_path + ".missing"
        with patch("socket.create_connection") as connect:
            with self.assertRaises(BridgeConnectionError) as raised:
                BridgeClient("127.0.0.1", 39877, 1.0, key_path=missing).request("daw.health")
        self.assertIn("no bridge key found", str(raised.exception))
        self.assertIn("Open Live", str(raised.exception))
        connect.assert_not_called()

    def test_unreachable_live_mentions_the_new_port(self) -> None:
        with patch("socket.create_connection", side_effect=ConnectionRefusedError()):
            with self.assertRaises(BridgeConnectionError) as raised:
                BridgeClient("127.0.0.1", 39877, 1.0, key_path=self.key_path).request(
                    "daw.health"
                )
        self.assertIn("39877", str(raised.exception))
        self.assertIn("reinstall the Remote Script", str(raised.exception))

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
                client = BridgeClient("127.0.0.1", 39877, 1.0, key_path=self.key_path)

                with self.assertRaises(BridgeConnectionError) as raised:
                    client.request("workflow.missing")

        self.assertIn("unsupported_method", str(raised.exception))
        self.assertIn("method is not supported", str(raised.exception))
        self.assertIn("Call daw.health", str(raised.exception))
        self.assertIsInstance(raised.exception, BridgeRefusedError)
        self.assertEqual(raised.exception.code, "unsupported_method")
        self.assertEqual(raised.exception.message, "method is not supported by this adapter")
        self.assertEqual(
            raised.exception.hint, "Call daw.health and choose a supported capability."
        )
