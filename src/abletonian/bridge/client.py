"""TCP client for the abletonian bridge protocol."""

from __future__ import annotations

import os
import socket
from typing import Any

from abletonian.bridge.protocol import BridgeRequest, decode_frame, encode_frame

# Written by the Remote Script in Live; read here on every request (RFC 0004).
DEFAULT_BRIDGE_KEY_PATH = os.path.join(os.path.expanduser("~"), ".abletonian", "bridge_key")


class BridgeConnectionError(RuntimeError):
    """Raised when the local Ableton bridge cannot be reached or understood."""


class BridgeRefusedError(BridgeConnectionError):
    """Raised when the bridge answered with ok=false.

    Subclasses BridgeConnectionError so existing callers keep working; the
    message is the same text they show today.
    """

    def __init__(
        self,
        text: str,
        code: str | None = None,
        message: str | None = None,
        hint: str | None = None,
    ):
        super().__init__(text)
        self.code = code
        self.message = message
        self.hint = hint


class BridgeClient:
    """Small synchronous client for the Ableton bridge."""

    def __init__(
        self,
        host: str,
        port: int,
        timeout: float,
        key_path: str = DEFAULT_BRIDGE_KEY_PATH,
    ) -> None:
        self.host = host
        self.port = port
        self.timeout = timeout
        self.key_path = key_path

    def request(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        """Send one bridge request and return the decoded response result."""

        request = BridgeRequest(method=method, params=params or {}, key=self._read_key())
        payload = encode_frame(request.to_wire())

        try:
            with socket.create_connection((self.host, self.port), timeout=self.timeout) as sock:
                sock.settimeout(self.timeout)
                sock.sendall(payload)
                response = decode_frame(_recv_exact(sock))
        except TimeoutError as exc:
            raise BridgeConnectionError(
                f"timed out waiting for {self.host}:{self.port}; "
                "Live may still apply the change, so check state before retrying"
            ) from exc
        except OSError as exc:
            raise BridgeConnectionError(
                f"could not connect to {self.host}:{self.port}. Check that Live is open with "
                "the Abletonian Control Surface enabled. If you upgraded abletonian, "
                "reinstall the Remote Script: it now listens on port 39877"
            ) from exc
        except ValueError as exc:
            raise BridgeConnectionError("bridge returned an invalid response") from exc

        if response.get("id") != request.id:
            raise BridgeConnectionError("bridge response ID did not match request ID")
        if not response.get("ok", False):
            error = response.get("error")
            fields = error if isinstance(error, dict) else {}
            raise BridgeRefusedError(
                _format_bridge_error(error),
                code=_text_or_none(fields.get("code")),
                message=_text_or_none(fields.get("message")),
                hint=_text_or_none(fields.get("hint")),
            )

        result = response.get("result", {})
        if not isinstance(result, dict):
            raise BridgeConnectionError("bridge result must be a JSON object")
        return result


    def _read_key(self) -> str:
        try:
            with open(self.key_path, encoding="ascii") as handle:
                key = handle.read().strip()
        except (OSError, UnicodeDecodeError) as exc:
            raise BridgeConnectionError(
                f"no bridge key found at {self.key_path}. Open Live with the Abletonian "
                "Remote Script enabled once; it creates the key"
            ) from exc
        if not key:
            raise BridgeConnectionError(
                f"the bridge key at {self.key_path} is empty. Delete it, then switch the "
                "Abletonian Control Surface slot in Live to None and back to make a new one"
            )
        return key


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


def _format_bridge_error(error: Any) -> str:
    if isinstance(error, dict):
        code = error.get("code", "bridge_error")
        message = error.get("message", "unknown bridge error")
        hint = error.get("hint")
        if hint:
            return f"{code}: {message} Hint: {hint}"
        return f"{code}: {message}"
    if error is None:
        return "unknown bridge error"
    return str(error)


def _text_or_none(value: Any) -> str | None:
    return value if isinstance(value, str) else None
