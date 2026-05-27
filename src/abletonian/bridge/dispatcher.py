"""Bridge frame dispatcher shared by fake and real adapter hosts."""

from __future__ import annotations

from typing import Any

from abletonian.bridge.protocol import (
    BridgeErrorPayload,
    BridgeResponse,
    decode_frame,
    encode_frame,
)


def dispatch_frame(adapter: Any, frame: bytes) -> bytes:
    """Decode one request frame, dispatch it to an adapter, and encode a response."""

    try:
        request = decode_frame(frame)
        request_id = _request_id(request)
        method = _method(request)
        params = _params(request)
    except ValueError as exc:
        return _error_response(
            "",
            "invalid_frame",
            str(exc),
            recoverable=False,
            hint="Send one length-prefixed JSON request object.",
        )

    try:
        result = adapter.handle_request(method, params)
    except Exception as exc:
        return _error_response(
            request_id,
            "adapter_error",
            str(exc),
            recoverable=False,
            hint="Check daw.health capabilities before retrying.",
        )

    return encode_frame(BridgeResponse(id=request_id, ok=True, result=result).to_wire())


def _request_id(request: dict[str, Any]) -> str:
    request_id = request.get("id")
    if not isinstance(request_id, str) or request_id == "":
        raise ValueError("bridge request id must be a non-empty string")
    return request_id


def _method(request: dict[str, Any]) -> str:
    method = request.get("method")
    if not isinstance(method, str) or method == "":
        raise ValueError("bridge request method must be a non-empty string")
    return method


def _params(request: dict[str, Any]) -> dict[str, Any]:
    params = request.get("params", {})
    if not isinstance(params, dict):
        raise ValueError("bridge request params must be a JSON object")
    return params


def _error_response(
    request_id: str,
    code: str,
    message: str,
    *,
    recoverable: bool,
    hint: str,
) -> bytes:
    return encode_frame(
        BridgeResponse(
            id=request_id,
            ok=False,
            error=BridgeErrorPayload(
                code=code,
                message=message,
                recoverable=recoverable,
                hint=hint,
            ),
        ).to_wire()
    )
