"""Read-only Ableton Remote Script adapter core."""

from __future__ import annotations

import sys
from dataclasses import dataclass
from typing import Any

from abletonian.bridge.protocol import PROTOCOL_VERSION

REMOTE_SCRIPT_ADAPTER_VERSION = "0.1.0"
REMOTE_SCRIPT_READ_CAPABILITIES = (
    "read_project_state",
    "read_selected_context",
    "read_drum_rack",
)
REMOTE_SCRIPT_UNSUPPORTED_CAPABILITIES = (
    "create_track",
    "duplicate_track",
    "write_midi_notes",
    "execute_drum_rack_extraction",
)


class RemoteScriptAdapterError(RuntimeError):
    """Raised when the read-only Remote Script adapter cannot satisfy a request."""


@dataclass(frozen=True)
class RemoteScriptAdapter:
    """Read-only adapter over an Ableton Live Remote Script song object."""

    song: Any
    live_version: str

    def handle_request(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        request_params = params or {}
        if method == "daw.health":
            return self._health(request_params)
        if method == "ableton.get_selected_context":
            return self._selected_context()
        raise RemoteScriptAdapterError(f"unsupported Remote Script method '{method}'")

    def _health(self, params: dict[str, Any]) -> dict[str, Any]:
        target_daw = params.get("target_daw", "ableton")
        if target_daw != "ableton":
            raise RemoteScriptAdapterError(
                f"Remote Script adapter cannot target '{target_daw}'"
            )
        return {
            "target_daw": "ableton",
            "adapter_type": "ableton_remote_script",
            "adapter_version": REMOTE_SCRIPT_ADAPTER_VERSION,
            "live_version": self.live_version,
            "python_runtime": sys.version.split()[0],
            "protocol_version": PROTOCOL_VERSION,
            "capabilities": list(REMOTE_SCRIPT_READ_CAPABILITIES),
            "unsupported_capabilities": list(REMOTE_SCRIPT_UNSUPPORTED_CAPABILITIES),
        }

    def _selected_context(self) -> dict[str, Any]:
        track = self._selected_track()
        device = _selected_device(track)
        return {
            "track": {
                "name": _string_attr(track, "name"),
                "color_index": _optional_attr(track, "color_index"),
                "is_foldable": bool(_optional_attr(track, "is_foldable", False)),
                "device_count": len(tuple(getattr(track, "devices", ()))),
            },
            "device": _device_payload(device),
        }

    def _selected_track(self) -> Any:
        try:
            return self.song.view.selected_track
        except AttributeError as exc:
            raise RemoteScriptAdapterError("selected track is unavailable") from exc


def _selected_device(track: Any) -> Any:
    track_view = getattr(track, "view", None)
    device = getattr(track_view, "selected_device", None)
    if device is not None:
        return device

    devices = tuple(getattr(track, "devices", ()))
    if not devices:
        return None
    return devices[0]


def _device_payload(device: Any) -> dict[str, Any] | None:
    if device is None:
        return None

    class_name = _string_attr(device, "class_name")
    return {
        "name": _string_attr(device, "name"),
        "class_name": class_name,
        "type": _device_type(class_name),
    }


def _device_type(class_name: str) -> str:
    if class_name == "DrumGroupDevice":
        return "drum_rack"
    if class_name.endswith("GroupDevice"):
        return "rack"
    return "device"


def _string_attr(target: Any, name: str) -> str:
    value = getattr(target, name, "")
    return str(value)


def _optional_attr(target: Any, name: str, default: Any = None) -> Any:
    return getattr(target, name, default)
