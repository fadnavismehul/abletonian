"""TCP client for the abletonian bridge protocol."""

from __future__ import annotations

import socket
from typing import Any

from abletonian.bridge.protocol import BridgeRequest, decode_frame, encode_frame


class BridgeConnectionError(RuntimeError):
    """Raised when the local Ableton bridge cannot be reached or understood."""


class BridgeClient:
    """Small synchronous client for the Ableton bridge."""

    def __init__(self, host: str, port: int, timeout: float) -> None:
        self.host = host
        self.port = port
        self.timeout = timeout

    def request(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        """Send one bridge request and return the decoded response result."""

        request = BridgeRequest(method=method, params=params or {})
        payload = encode_frame(request.to_wire())

        try:
            with socket.create_connection((self.host, self.port), timeout=self.timeout) as sock:
                sock.settimeout(self.timeout)
                sock.sendall(payload)
                response = decode_frame(_recv_exact(sock))
        except OSError as exc:
            raise BridgeConnectionError(
                f"could not connect to {self.host}:{self.port}"
            ) from exc
        except ValueError as exc:
            raise BridgeConnectionError("bridge returned an invalid response") from exc

        if response.get("id") != request.id:
            raise BridgeConnectionError("bridge response ID did not match request ID")
        if not response.get("ok", False):
            error = response.get("error", "unknown bridge error")
            raise BridgeConnectionError(str(error))

        result = response.get("result", {})
        if not isinstance(result, dict):
            raise BridgeConnectionError("bridge result must be a JSON object")
        return result


def _recv_exact(sock: socket.socket) -> bytes:
    """Receive one length-prefixed frame from a socket."""

    header = _recv_n(sock, 4)
    length = int.from_bytes(header, "big")
    if length <= 0:
        raise ValueError("frame length must be positive")
    return header + _recv_n(sock, length)


def _recv_n(sock: socket.socket, length: int) -> bytes:
    chunks: list[bytes] = []
    remaining = length
    while remaining > 0:
        chunk = sock.recv(remaining)
        if not chunk:
            raise ValueError("socket closed before frame was complete")
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)
