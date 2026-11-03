"""Length-prefixed JSON frames for the abletonian bridge."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from json import JSONDecodeError
from typing import Any
from uuid import uuid4

MAX_FRAME_BYTES = 4 * 1024 * 1024
PROTOCOL_VERSION = "abletonian.bridge.v2"


@dataclass(frozen=True)
class BridgeRequest:
    """Request sent from the MCP process to the Ableton bridge."""

    method: str
    params: dict[str, Any] = field(default_factory=dict)
    id: str = field(default_factory=lambda: uuid4().hex)
    # The per-install key (RFC 0004). Never logged or echoed back.
    key: str | None = field(default=None, repr=False)

    def to_wire(self) -> dict[str, Any]:
        wire: dict[str, Any] = {
            "id": self.id,
            "method": self.method,
            "params": self.params,
        }
        if self.key is not None:
            wire["key"] = self.key
        return wire


@dataclass(frozen=True)
class BridgeErrorPayload:
    """Typed bridge error details returned by adapters."""

    code: str
    message: str
    recoverable: bool
    hint: str | None = None

    def to_wire(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "code": self.code,
            "message": self.message,
            "recoverable": self.recoverable,
        }
        if self.hint is not None:
            payload["hint"] = self.hint
        return payload


@dataclass(frozen=True)
class BridgeResponse:
    """Response returned by the Ableton bridge."""

    id: str
    ok: bool
    result: dict[str, Any] = field(default_factory=dict)
    error: BridgeErrorPayload | str | None = None

    def to_wire(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "id": self.id,
            "ok": self.ok,
            "result": self.result,
        }
        if self.error is not None:
            payload["error"] = (
                self.error.to_wire()
                if isinstance(self.error, BridgeErrorPayload)
                else self.error
            )
        return payload


def encode_frame(message: dict[str, Any]) -> bytes:
    """Encode a JSON object as a 4-byte length-prefixed frame."""

    body = json.dumps(message, separators=(",", ":"), sort_keys=True).encode("utf-8")
    if len(body) > MAX_FRAME_BYTES:
        raise ValueError("bridge frame is too large")
    return len(body).to_bytes(4, "big") + body


def decode_frame(frame: bytes) -> dict[str, Any]:
    """Decode a complete 4-byte length-prefixed JSON frame."""

    if len(frame) < 4:
        raise ValueError("bridge frame is missing its length prefix")

    length = int.from_bytes(frame[:4], "big")
    if length <= 0:
        raise ValueError("bridge frame length must be positive")
    if length > MAX_FRAME_BYTES:
        raise ValueError("bridge frame exceeds maximum size")
    if len(frame) - 4 != length:
        raise ValueError("bridge frame length does not match payload size")

    try:
        message = json.loads(frame[4:].decode("utf-8"))
    except JSONDecodeError as exc:
        raise ValueError("bridge frame payload must be valid JSON") from exc
    if not isinstance(message, dict):
        raise ValueError("bridge frame payload must be a JSON object")
    return message
