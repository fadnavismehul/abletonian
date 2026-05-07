"""Length-prefixed JSON frames for the abletonian bridge."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4

MAX_FRAME_BYTES = 4 * 1024 * 1024


@dataclass(frozen=True)
class BridgeRequest:
    """Request sent from the MCP process to the Ableton bridge."""

    method: str
    params: dict[str, Any] = field(default_factory=dict)
    id: str = field(default_factory=lambda: uuid4().hex)

    def to_wire(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "method": self.method,
            "params": self.params,
        }


@dataclass(frozen=True)
class BridgeResponse:
    """Response returned by the Ableton bridge."""

    id: str
    ok: bool
    result: dict[str, Any] = field(default_factory=dict)
    error: str | None = None

    def to_wire(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "id": self.id,
            "ok": self.ok,
            "result": self.result,
        }
        if self.error is not None:
            payload["error"] = self.error
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

    message = json.loads(frame[4:].decode("utf-8"))
    if not isinstance(message, dict):
        raise ValueError("bridge frame payload must be a JSON object")
    return message
