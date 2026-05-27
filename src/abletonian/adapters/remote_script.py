"""Read-only Ableton Remote Script adapter core."""

from __future__ import annotations

import sys
from collections import Counter
from dataclasses import dataclass
from typing import Any

from abletonian.bridge.protocol import PROTOCOL_VERSION

REMOTE_SCRIPT_ADAPTER_VERSION = "0.1.0"
REMOTE_SCRIPT_READ_CAPABILITIES = (
    "read_project_state",
    "read_selected_context",
    "read_drum_rack",
    "plan_drum_rack_extraction",
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
        if method == "workflow.plan_drum_rack_extraction":
            return self._plan_drum_rack_extraction()
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

    def _plan_drum_rack_extraction(self) -> dict[str, Any]:
        track = self._selected_track()
        device = _selected_drum_rack(track)
        pitch_counts = Counter(
            note["pitch"]
            for clip in _session_midi_clips(track)
            for note in _clip_notes(clip)
        )
        outputs: list[dict[str, Any]] = []
        skipped_pad_names: list[str] = []

        for pad in _drum_pads(device):
            chains = _as_tuple(getattr(pad, "chains", ()))
            if not chains:
                continue
            note = _int_attr(pad, "note")
            if note is None:
                continue
            pad_name = _string_attr(pad, "name") or f"Pad {note}"
            note_count = pitch_counts.get(note, 0)
            if note_count == 0:
                skipped_pad_names.append(pad_name)
                continue

            outputs.append(
                {
                    "source_pad": {
                        "note": note,
                        "name": pad_name,
                        "chain_name": _chain_name(chains, pad_name),
                    },
                    "name": f"{_string_attr(track, 'name')} - {pad_name}",
                    "color": _first_color(track, pad, chains),
                    "devices": _chain_device_names(chains),
                    "midi_filter": {"keep_pitch": note},
                    "clip_note_count": note_count,
                }
            )

        warnings = []
        if skipped_pad_names:
            warnings.append(_skipped_pad_warning(skipped_pad_names))

        return {
            "operation": "split_drum_rack",
            "mode": "dry_run",
            "target": {
                "track_id": _object_id(track),
                "track_name": _string_attr(track, "name"),
                "device_id": _object_id(device),
                "device_name": _string_attr(device, "name"),
            },
            "steps": [
                {"action": "duplicate_track", "count": len(outputs)},
                {"action": "filter_midi_notes", "policy": "one_note_per_output_track"},
                {"action": "rename_tracks", "source": "pad_name"},
                {"action": "set_colors", "source": "pad_color"},
            ],
            "output_tracks": outputs,
            "preserves": ["source_track", "source_clips", "source_devices"],
            "requires_confirmation": True,
            "warnings": warnings,
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


def _selected_drum_rack(track: Any) -> Any:
    selected = _selected_device(track)
    if selected is not None and _device_type(_string_attr(selected, "class_name")) == "drum_rack":
        return selected
    for device in _as_tuple(getattr(track, "devices", ())):
        if _device_type(_string_attr(device, "class_name")) == "drum_rack":
            return device
    raise RemoteScriptAdapterError(
        f"selected track '{_string_attr(track, 'name')}' has no Drum Rack"
    )


def _drum_pads(device: Any) -> tuple[Any, ...]:
    visible = _as_tuple(getattr(device, "visible_drum_pads", ()))
    if visible:
        return visible
    return _as_tuple(getattr(device, "drum_pads", ()))


def _session_midi_clips(track: Any) -> tuple[Any, ...]:
    clips = []
    for slot in _as_tuple(getattr(track, "clip_slots", ())):
        if not bool(getattr(slot, "has_clip", False)):
            continue
        clip = getattr(slot, "clip", None)
        if clip is not None and bool(getattr(clip, "is_midi_clip", False)):
            clips.append(clip)
    return tuple(clips)


def _clip_notes(clip: Any) -> tuple[dict[str, Any], ...]:
    result = _get_notes_extended(clip)
    if result is None:
        result = _get_notes_legacy(clip)
    return tuple(
        note_payload
        for note in _notes_from_result(result)
        if (note_payload := _note_payload(note)) is not None
    )


def _get_notes_extended(clip: Any) -> Any:
    get_notes = getattr(clip, "get_notes_extended", None)
    if not callable(get_notes):
        return None
    return get_notes(0, 128, 0.0, _clip_time_span(clip))


def _get_notes_legacy(clip: Any) -> Any:
    get_notes = getattr(clip, "get_notes", None)
    if not callable(get_notes):
        return ()
    return get_notes(0.0, 0, _clip_time_span(clip), 128)


def _clip_time_span(clip: Any) -> float:
    for name in ("length", "loop_end", "end_marker"):
        value = getattr(clip, name, None)
        if value is not None:
            try:
                return max(float(value), 1.0)
            except (TypeError, ValueError):
                pass
    return 16384.0


def _notes_from_result(result: Any) -> tuple[Any, ...]:
    if isinstance(result, dict):
        return _as_tuple(result.get("notes", ()))
    return _as_tuple(result)


def _note_payload(note: Any) -> dict[str, Any] | None:
    if isinstance(note, dict):
        pitch = note.get("pitch")
    elif isinstance(note, (list, tuple)) and note:
        pitch = note[0]
    else:
        pitch = getattr(note, "pitch", None)
    try:
        return {"pitch": int(pitch)}
    except (TypeError, ValueError):
        return None


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


def _int_attr(target: Any, name: str) -> int | None:
    value = getattr(target, name, None)
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _optional_attr(target: Any, name: str, default: Any = None) -> Any:
    return getattr(target, name, default)


def _object_id(target: Any) -> str:
    for name in ("_live_ptr", "id"):
        value = getattr(target, name, None)
        if value is not None:
            return str(value)
    return _string_attr(target, "name")


def _chain_name(chains: tuple[Any, ...], fallback: str) -> str:
    for chain in chains:
        name = _string_attr(chain, "name")
        if name:
            return name
    return fallback


def _first_color(track: Any, pad: Any, chains: tuple[Any, ...]) -> Any:
    for target in (*chains, pad, track):
        for name in ("color_index", "color"):
            value = getattr(target, name, None)
            if value is not None:
                return value
    return None


def _chain_device_names(chains: tuple[Any, ...]) -> list[str]:
    names: list[str] = []
    for chain in chains:
        for device in _as_tuple(getattr(chain, "devices", ())):
            name = _string_attr(device, "name")
            if name:
                names.append(name)
    return names


def _skipped_pad_warning(pad_names: list[str]) -> str:
    count = len(pad_names)
    noun = "drum pad" if count == 1 else "drum pads"
    return f"Skipped {count} {noun} without matching MIDI notes: {', '.join(pad_names)}"


def _as_tuple(value: Any) -> tuple[Any, ...]:
    if value is None:
        return ()
    if isinstance(value, tuple):
        return value
    if isinstance(value, list):
        return tuple(value)
    try:
        return tuple(value)
    except TypeError:
        return (value,)
