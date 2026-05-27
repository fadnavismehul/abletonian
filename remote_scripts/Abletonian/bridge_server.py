"""Read-only Abletonian bridge server for Ableton Live Remote Scripts."""

from __future__ import annotations

import json
import socket
import struct
import sys
import threading
import traceback
from collections import Counter

try:
    from ableton.v2.control_surface import ControlSurface
except Exception:
    class ControlSurface:  # type: ignore[no-redef]
        """Fallback so this module can be imported outside Ableton for linting."""

        def __init__(self, c_instance=None):
            self._c_instance = c_instance

        def song(self):
            raise RuntimeError("Ableton ControlSurface is unavailable outside Live")

        def application(self):
            return None

        def log_message(self, message):
            print(message)

        def disconnect(self):
            return None


HOST = "127.0.0.1"
PORT = 9877
PROTOCOL_VERSION = "abletonian.bridge.v1"
ADAPTER_VERSION = "0.1.0"
MAX_FRAME_BYTES = 4 * 1024 * 1024


class AbletonianBridgeControlSurface(ControlSurface):
    """Small read-only bridge hosted inside Ableton Live."""

    def __init__(self, c_instance):
        super().__init__(c_instance)
        self._server = _BridgeServer(self)
        self._server.start()
        self._log("Abletonian bridge started on 127.0.0.1:9877")

    def disconnect(self):
        self._server.stop()
        self._log("Abletonian bridge stopped")
        super().disconnect()

    def handle_request(self, method, params):
        if method == "daw.health":
            return self._health(params)
        if method == "ableton.get_selected_context":
            return self._selected_context()
        if method == "workflow.plan_drum_rack_extraction":
            return self._plan_drum_rack_extraction()
        raise RuntimeError(f"unsupported Abletonian Remote Script method '{method}'")

    def _health(self, params):
        target_daw = params.get("target_daw", "ableton")
        if target_daw != "ableton":
            raise RuntimeError(f"Abletonian Remote Script cannot target '{target_daw}'")
        return {
            "target_daw": "ableton",
            "adapter_type": "ableton_remote_script",
            "adapter_version": ADAPTER_VERSION,
            "live_version": _live_version(_live_object(self, "application")),
            "python_runtime": sys.version.split()[0],
            "protocol_version": PROTOCOL_VERSION,
            "capabilities": [
                "read_project_state",
                "read_selected_context",
                "read_drum_rack",
                "plan_drum_rack_extraction",
            ],
            "unsupported_capabilities": [
                "create_track",
                "duplicate_track",
                "write_midi_notes",
                "execute_drum_rack_extraction",
            ],
        }

    def _selected_context(self):
        track = _live_object(self, "song").view.selected_track
        device = _selected_device(track)
        return {
            "track": {
                "name": str(getattr(track, "name", "")),
                "color_index": getattr(track, "color_index", None),
                "is_foldable": bool(getattr(track, "is_foldable", False)),
                "device_count": len(tuple(getattr(track, "devices", ()))),
            },
            "device": _device_payload(device),
        }

    def _plan_drum_rack_extraction(self):
        track = _live_object(self, "song").view.selected_track
        device = _selected_drum_rack(track)
        pitch_counts = Counter(
            note["pitch"]
            for clip in _session_midi_clips(track)
            for note in _clip_notes(clip)
        )
        outputs = []
        skipped_pad_names = []

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

    def _log(self, message):
        try:
            self.log_message(f"[Abletonian] {message}")
        except Exception:
            print(f"[Abletonian] {message}")


class _BridgeServer:
    def __init__(self, surface):
        self._surface = surface
        self._stop_event = threading.Event()
        self._socket = None
        self._thread = threading.Thread(target=self._serve, name="AbletonianBridge")
        self._thread.daemon = True

    def start(self):
        self._thread.start()

    def stop(self):
        self._stop_event.set()
        if self._socket is not None:
            try:
                self._socket.close()
            except OSError:
                pass

    def _serve(self):
        try:
            server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            server.bind((HOST, PORT))
            server.listen(4)
            server.settimeout(0.5)
            self._socket = server
        except Exception as exc:
            self._surface._log(f"bridge failed to start: {exc}")
            return

        while not self._stop_event.is_set():
            try:
                client, _address = server.accept()
            except TimeoutError:
                continue
            except OSError:
                break
            with client:
                try:
                    frame = _recv_frame(client)
                    client.sendall(_dispatch_frame(self._surface, frame))
                except Exception:
                    self._surface._log(traceback.format_exc())


def _dispatch_frame(surface, frame):
    request_id = ""
    try:
        request = _decode_frame(frame)
        request_id = _request_id(request)
        method = _method(request)
        params = _params(request)
        result = surface.handle_request(method, params)
        return _encode_frame({"id": request_id, "ok": True, "result": result})
    except Exception as exc:
        return _encode_frame(
            {
                "id": request_id,
                "ok": False,
                "result": {},
                "error": {
                    "code": "adapter_error" if request_id else "invalid_frame",
                    "message": str(exc),
                    "recoverable": False,
                    "hint": "Check daw.health capabilities before retrying.",
                },
            }
        )


def _recv_frame(sock):
    header = _recv_exact(sock, 4)
    length = struct.unpack(">I", header)[0]
    if length <= 0 or length > MAX_FRAME_BYTES:
        raise ValueError("invalid frame length")
    return header + _recv_exact(sock, length)


def _recv_exact(sock, length):
    chunks = []
    remaining = length
    while remaining > 0:
        chunk = sock.recv(remaining)
        if not chunk:
            raise ValueError("socket closed before frame was complete")
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def _encode_frame(message):
    body = json.dumps(message, separators=(",", ":"), sort_keys=True).encode("utf-8")
    return struct.pack(">I", len(body)) + body


def _decode_frame(frame):
    if len(frame) < 4:
        raise ValueError("bridge frame is missing its length prefix")
    length = struct.unpack(">I", frame[:4])[0]
    if len(frame) - 4 != length:
        raise ValueError("bridge frame length does not match payload size")
    message = json.loads(frame[4:].decode("utf-8"))
    if not isinstance(message, dict):
        raise ValueError("bridge frame payload must be a JSON object")
    return message


def _request_id(request):
    request_id = request.get("id")
    if not isinstance(request_id, str) or request_id == "":
        raise ValueError("bridge request id must be a non-empty string")
    return request_id


def _method(request):
    method = request.get("method")
    if not isinstance(method, str) or method == "":
        raise ValueError("bridge request method must be a non-empty string")
    return method


def _params(request):
    params = request.get("params", {})
    if not isinstance(params, dict):
        raise ValueError("bridge request params must be a JSON object")
    return params


def _selected_device(track):
    track_view = getattr(track, "view", None)
    device = getattr(track_view, "selected_device", None)
    if device is not None:
        return device
    devices = tuple(getattr(track, "devices", ()))
    return devices[0] if devices else None


def _selected_drum_rack(track):
    selected = _selected_device(track)
    if selected is not None and _device_type(_string_attr(selected, "class_name")) == "drum_rack":
        return selected
    for device in _as_tuple(getattr(track, "devices", ())):
        if _device_type(_string_attr(device, "class_name")) == "drum_rack":
            return device
    raise RuntimeError(f"selected track '{_string_attr(track, 'name')}' has no Drum Rack")


def _drum_pads(device):
    visible = _as_tuple(getattr(device, "visible_drum_pads", ()))
    if visible:
        return visible
    return _as_tuple(getattr(device, "drum_pads", ()))


def _session_midi_clips(track):
    clips = []
    for slot in _as_tuple(getattr(track, "clip_slots", ())):
        if not bool(getattr(slot, "has_clip", False)):
            continue
        clip = getattr(slot, "clip", None)
        if clip is not None and bool(getattr(clip, "is_midi_clip", False)):
            clips.append(clip)
    return tuple(clips)


def _clip_notes(clip):
    result = _get_notes_extended(clip)
    if result is None:
        result = _get_notes_legacy(clip)
    return tuple(
        note_payload
        for note in _notes_from_result(result)
        if (note_payload := _note_payload(note)) is not None
    )


def _get_notes_extended(clip):
    get_notes = getattr(clip, "get_notes_extended", None)
    if not callable(get_notes):
        return None
    return get_notes(0, 128, 0.0, _clip_time_span(clip))


def _get_notes_legacy(clip):
    get_notes = getattr(clip, "get_notes", None)
    if not callable(get_notes):
        return ()
    return get_notes(0.0, 0, _clip_time_span(clip), 128)


def _clip_time_span(clip):
    for name in ("length", "loop_end", "end_marker"):
        value = getattr(clip, name, None)
        if value is not None:
            try:
                return max(float(value), 1.0)
            except (TypeError, ValueError):
                pass
    return 16384.0


def _notes_from_result(result):
    if isinstance(result, dict):
        return _as_tuple(result.get("notes", ()))
    return _as_tuple(result)


def _note_payload(note):
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


def _live_object(surface, name):
    value = getattr(surface, name)
    if callable(value):
        return value()
    return value


def _string_attr(target, name):
    value = getattr(target, name, "")
    return str(value)


def _int_attr(target, name):
    value = getattr(target, name, None)
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _object_id(target):
    for name in ("_live_ptr", "id"):
        value = getattr(target, name, None)
        if value is not None:
            return str(value)
    return _string_attr(target, "name")


def _chain_name(chains, fallback):
    for chain in chains:
        name = _string_attr(chain, "name")
        if name:
            return name
    return fallback


def _first_color(track, pad, chains):
    for target in (*chains, pad, track):
        for name in ("color_index", "color"):
            value = getattr(target, name, None)
            if value is not None:
                return value
    return None


def _chain_device_names(chains):
    names = []
    for chain in chains:
        for device in _as_tuple(getattr(chain, "devices", ())):
            name = _string_attr(device, "name")
            if name:
                names.append(name)
    return names


def _skipped_pad_warning(pad_names):
    count = len(pad_names)
    noun = "drum pad" if count == 1 else "drum pads"
    return f"Skipped {count} {noun} without matching MIDI notes: {', '.join(pad_names)}"


def _as_tuple(value):
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


def _device_payload(device):
    if device is None:
        return None
    class_name = str(getattr(device, "class_name", ""))
    return {
        "name": str(getattr(device, "name", "")),
        "class_name": class_name,
        "type": _device_type(class_name),
    }


def _device_type(class_name):
    if class_name == "DrumGroupDevice":
        return "drum_rack"
    if class_name.endswith("GroupDevice"):
        return "rack"
    return "device"


def _live_version(application):
    if application is None:
        return "unknown"
    parts = []
    for method_name in ("get_major_version", "get_minor_version", "get_bugfix_version"):
        method = getattr(application, method_name, None)
        if callable(method):
            try:
                parts.append(str(method()))
            except Exception:
                pass
    if parts:
        return ".".join(parts)
    return str(getattr(application, "version", "unknown"))
