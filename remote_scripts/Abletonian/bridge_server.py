"""Abletonian bridge server for Ableton Live Remote Scripts."""

from __future__ import annotations

import hmac
import json
import os
import secrets
import socket
import struct
import sys
import threading
import time
import traceback
from collections import Counter

from . import live_ops

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
# 39877, not 9877: several other Ableton MCP Remote Scripts listen on 9877
# (RFC 0004). Must match DEFAULT_BRIDGE_PORT in src/abletonian/config.py.
PORT = 39877
PROTOCOL_VERSION = "abletonian.bridge.v2"
ADAPTER_VERSION = "0.6.1"
# The per-install key every request must carry (RFC 0004). Same path as
# DEFAULT_BRIDGE_KEY_PATH in src/abletonian/bridge/client.py.
KEY_PATH = os.path.join(os.path.expanduser("~"), ".abletonian", "bridge_key")
KEY_HINT = (
    "abletonian and Live must run as the same user, so both read the same key file. "
    "If the key file was replaced or deleted, switch the Abletonian Control Surface "
    "slot in Live to None and back to load or create it, then try again."
)
MAX_FRAME_BYTES = 4 * 1024 * 1024
# Live must start a request within this time or it is cancelled unrun, so a
# client that gives up never sees its change applied later.
REQUEST_START_TIMEOUT_SECONDS = 5.0
# Once started, a request (such as a long batch) may run this long.
REQUEST_RUN_TIMEOUT_SECONDS = 25.0
# A per-operation batch runs each operation this many Live ticks after the
# previous one, so Live does not merge their undo steps.
BATCH_OPERATION_TICK_DELAY = 1
# ableton.read_levels takes one meter sample every this many Live ticks.
LEVEL_SAMPLE_TICK_DELAY = 1
# How much longer than its window a level read may take (slow or skipped
# ticks) before the socket thread gives up on it. With the start timeout of
# the setup call, a read ends within seconds + 10 s; the MCP server's client
# timeout must be longer (LEVEL_READ_OVERHEAD_SECONDS in
# src/abletonian/adapters/remote_script.py).
LEVEL_READ_GRACE_SECONDS = 5.0
LEVEL_READ_METHOD = "ableton.read_levels"
# Live Undo presses per track the Drum Rack workflow creates (Live 12.4.16).
UNDO_STEPS_PER_CREATED_TRACK = 2
UNFILTERED_SCAFFOLD_WARNING = (
    "Scaffold tracks are full duplicates; MIDI clips have not been filtered yet."
)


class AbletonianBridgeControlSurface(ControlSurface):
    """Small bridge hosted inside Ableton Live."""

    def __init__(self, c_instance):
        super().__init__(c_instance)
        self._bridge_key = BridgeKey(KEY_PATH)
        try:
            self._bridge_key.load_or_create()
        except OSError as exc:
            # Fail closed: without a key every request is refused.
            self._log(f"could not create the bridge key at {KEY_PATH}: {exc}")
        self._server = _BridgeServer(self)
        self._server.start()
        self._log(f"Abletonian bridge started on {HOST}:{PORT}")

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
        if method == "workflow.scaffold_drum_rack_extraction":
            return self._scaffold_drum_rack_extraction(params)
        if method == "workflow.execute_drum_rack_extraction":
            return self._execute_drum_rack_extraction(params)
        if method == LEVEL_READ_METHOD:
            # Reached only without Live's timer: _call_surface runs level
            # reads through _run_level_read when schedule_message exists.
            raise live_ops.NotSupported(
                "read_levels samples meters on Live's timer, which this host does not have"
            )
        result = live_ops.handle(_live_object(self, "song"), method, params)
        if result is not None:
            return result
        raise live_ops.NotSupported(
            f"unsupported Abletonian Remote Script method '{method}'",
            "The Remote Script in Live may be older than abletonian. Reinstall it "
            "(python -m scripts.install_remote_script), then switch the Abletonian "
            "Control Surface slot to None and back. daw.health lists what it supports.",
        )

    def _health(self, params):
        target_daw = params.get("target_daw", "ableton")
        if target_daw != "ableton":
            raise live_ops.NotSupported(
                f"Abletonian Remote Script cannot target '{target_daw}'",
                "Start abletonian with --target-daw ableton.",
            )
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
                "scaffold_drum_rack_extraction",
                "execute_drum_rack_extraction",
                "list_tracks",
                "list_devices",
                "read_rack_macros",
                "set_device_parameter",
                "set_track_output_routing",
                "set_track_properties",
                "set_mixer",
                "insert_device",
                "create_return_track",
                "delete_device",
                "batch",
                "undo",
                "undo_count",
                "batch_per_operation_undo",
                "single_call_undo_steps",
                "read_levels",
            ],
            "unsupported_capabilities": [
                "create_track",
                "group_tracks",
                "reorder_tracks",
                "write_midi_notes",
                "set_rack_macro_value",
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

    def _scaffold_drum_rack_extraction(self, params):
        if params.get("confirm") is not True:
            raise live_ops.NeedsConfirmation(
                "workflow.scaffold_drum_rack_extraction requires confirmation"
            )

        song = _live_object(self, "song")
        source_track = song.view.selected_track
        source_track_index = _track_index(song, source_track)
        duplicate_index = source_track_index
        plan = self._plan_drum_rack_extraction()
        warnings = [
            *plan["warnings"],
            UNFILTERED_SCAFFOLD_WARNING,
        ]
        created_tracks = []

        for output in plan["output_tracks"]:
            created_track = _duplicate_track_after(song, duplicate_index)
            _assign_track_name(created_track, str(output["name"]), warnings)
            _assign_track_color(created_track, output.get("color"), warnings)
            created_track_index = _track_index(song, created_track)
            created_tracks.append(
                {
                    "id": _object_id(created_track),
                    "name": _string_attr(created_track, "name"),
                    "track_index": created_track_index,
                    "source_pad": output["source_pad"],
                    "midi_filter": output["midi_filter"],
                    "clip_note_count": output["clip_note_count"],
                    "devices": output["devices"],
                    "color": getattr(created_track, "color_index", None),
                    "contains_unfiltered_clips": True,
                }
            )
            duplicate_index = created_track_index

        return {
            "operation": "split_drum_rack",
            "mode": "scaffold_tracks",
            "target": plan["target"],
            "preserved_tracks": [_object_id(source_track)],
            "touched_tracks": [track["id"] for track in created_tracks],
            "created_tracks": created_tracks,
            "warnings": warnings,
            "backout": {
                "primary": _undo_backout_text(len(created_tracks)),
                "fallback": "Close the Live Set without saving to discard scaffold tracks.",
            },
            "verification": {
                "source_track_preserved": True,
                "created_track_count": len(created_tracks),
                "midi_filtering_applied": False,
                "saved_live_set": False,
                "mutates_real_ableton_set": True,
            },
        }

    def _execute_drum_rack_extraction(self, params):
        if params.get("confirm") is not True:
            raise live_ops.NeedsConfirmation(
                "workflow.execute_drum_rack_extraction requires confirmation"
            )

        song = _live_object(self, "song")
        scaffold = self._scaffold_drum_rack_extraction(params)
        warnings = [
            warning
            for warning in scaffold["warnings"]
            if warning != UNFILTERED_SCAFFOLD_WARNING
        ]
        created_tracks = []

        for created_track in scaffold["created_tracks"]:
            track = _track_by_id(song, str(created_track["id"]))
            keep_pitch = int(created_track["midi_filter"]["keep_pitch"])
            pad_name = str(created_track["source_pad"]["name"])
            clips = _filter_track_midi_clips(track, keep_pitch, pad_name, warnings)
            created_tracks.append(
                {
                    **created_track,
                    "clips": clips,
                    "contains_unfiltered_clips": False,
                }
            )

        return {
            "operation": "split_drum_rack",
            "mode": "execute",
            "target": scaffold["target"],
            "preserved_tracks": scaffold["preserved_tracks"],
            "touched_tracks": scaffold["touched_tracks"],
            "created_tracks": created_tracks,
            "warnings": warnings,
            "backout": scaffold["backout"],
            "verification": {
                "source_track_preserved": True,
                "created_track_count": len(created_tracks),
                "midi_filtering_applied": True,
                "saved_live_set": False,
                "mutates_real_ableton_set": True,
            },
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
        # Bind here, on Live's main thread, so a reload that stops the old
        # instance first always frees the port before this one binds.
        for attempt in range(5):
            try:
                self._socket = _listen_socket()
                break
            except OSError as exc:
                if attempt == 4:
                    self._surface._log(f"bridge failed to start: {exc}")
                    return
                time.sleep(0.2)
        self._thread.start()

    def stop(self):
        self._stop_event.set()
        if self._socket is not None:
            try:
                self._socket.close()
            except OSError:
                pass
        if self._thread.is_alive():
            self._thread.join(1.0)

    def _serve(self):
        server = self._socket
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


def _listen_socket():
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        server.bind((HOST, PORT))
        server.listen(4)
    except OSError:
        server.close()
        raise
    server.settimeout(0.5)
    return server


class BridgeKey:
    """The per-install key in ``~/.abletonian/bridge_key`` (RFC 0004).

    The Remote Script creates it; the MCP server only reads it. The file holds
    64 hex characters. Checks use ``hmac.compare_digest``.
    """

    def __init__(self, path):
        self.path = path
        self._value = None

    def load_or_create(self):
        value = self._read()
        if value is None:
            value = self._create()
        self._value = value
        return value

    def matches(self, presented):
        # compare_digest raises on non-ASCII str, so refuse those first.
        if not isinstance(presented, str) or not presented or not presented.isascii():
            return False
        if self._value is not None and hmac.compare_digest(presented, self._value):
            return True
        # The file may have been replaced since Live started: read it once more.
        self._value = self._read()
        return self._value is not None and hmac.compare_digest(presented, self._value)

    def _read(self):
        # A key in a folder or file other users can write could have been
        # planted, so it is not trusted.
        if not _private(os.path.dirname(self.path), 0o022) or not _private(self.path, 0o077):
            return None
        try:
            with open(self.path, encoding="ascii") as handle:
                value = handle.read().strip()
        except (OSError, UnicodeDecodeError):
            return None
        if len(value) < 32 or any(c not in "0123456789abcdef" for c in value):
            return None
        return value

    def _create(self):
        folder = os.path.dirname(self.path)
        os.makedirs(folder, mode=0o700, exist_ok=True)
        _make_private(folder, 0o700)
        value = secrets.token_hex(32)
        temp = f"{self.path}.{os.getpid()}.{secrets.token_hex(4)}.tmp"
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(temp, flags, 0o600)
        try:
            with os.fdopen(descriptor, "w", encoding="ascii") as handle:
                handle.write(value + "\n")
            os.replace(temp, self.path)
        except BaseException:
            # Never leave a working key behind in a stray file.
            try:
                os.unlink(temp)
            except OSError:
                pass
            raise
        return value


def _private(path, forbidden_bits):
    """True if ``path`` is owned by this user and has none of ``forbidden_bits``.

    Always true where POSIX ownership does not apply (Windows), where the
    home folder's own permissions protect the file.
    """

    if os.name != "posix":
        return True
    try:
        info = os.lstat(path)
    except OSError:
        return False
    return info.st_uid == os.getuid() and not info.st_mode & forbidden_bits


def _make_private(path, mode):
    """Tighten a folder this user owns; refuse one owned by someone else."""

    if os.name != "posix":
        return
    info = os.lstat(path)
    if info.st_uid != os.getuid():
        raise PermissionError(f"{path} is owned by another user")
    if info.st_mode & 0o077:
        os.chmod(path, mode)


class _Unauthorized(Exception):
    pass


def _check_key(surface, request):
    """Refuse unless the request carries this install's key. Runs on the
    socket thread, before anything is scheduled on Live's main thread."""

    key = getattr(surface, "_bridge_key", None)
    if key is None or not key.matches(request.get("key")):
        raise _Unauthorized(
            f"Live's Abletonian Remote Script did not accept this request's key "
            f"({KEY_PATH}); nothing was changed."
        )


def _dispatch_frame(surface, frame):
    request_id = ""
    try:
        request = _decode_frame(frame)
        request_id = _request_id(request)
        _check_key(surface, request)
        method = _method(request)
        params = _params(request)
        result = _call_surface(surface, method, params)
        return _encode_frame({"id": request_id, "ok": True, "result": result})
    except _Unauthorized as exc:
        return _encode_frame(
            {
                "id": request_id,
                "ok": False,
                "result": {},
                "error": {
                    "code": "unauthorized",
                    "message": str(exc),
                    "recoverable": False,
                    "hint": KEY_HINT,
                },
            }
        )
    except Exception as exc:
        code, hint = _error_code_and_hint(exc, request_id)
        error = {"code": code, "message": str(exc), "recoverable": False}
        if hint:
            error["hint"] = hint
        return _encode_frame({"id": request_id, "ok": False, "result": {}, "error": error})


# Timeouts raised by _call_on_main_thread, matched by their message.
_NOT_STARTED = "did not start the request"
_NOT_FINISHED = "did not finish it in time"
_LEVELS_NOT_FINISHED = "did not finish sampling meters in time"


def _error_code_and_hint(exc, request_id):
    """The error code and the next-step hint for an exception (issue MEH-25).

    Errors from live_ops carry their own. Timeouts say whether Live may
    still change the Set. Anything else gets no hint rather than a wrong one.
    """

    if not request_id:
        return "invalid_frame", "Send one length-prefixed JSON request object."
    if isinstance(exc, live_ops.LiveOpsError):
        return exc.code, exc.hint
    if isinstance(exc, TimeoutError):
        if _NOT_STARTED in str(exc):
            return "timeout", "Live was busy and nothing was changed. Try again in a moment."
        if _NOT_FINISHED in str(exc):
            return (
                "timeout",
                "Live may still apply this change. Check the Set with list_tracks or "
                "list_devices before trying again.",
            )
        if _LEVELS_NOT_FINISHED in str(exc):
            return (
                "timeout",
                "Live was too busy to sample the whole window; nothing was changed. Try "
                "again, or read fewer seconds or tracks.",
            )
        return "timeout", None
    return "adapter_error", None


def _call_surface(surface, method, params):
    if method == LEVEL_READ_METHOD and callable(getattr(surface, "schedule_message", None)):
        return _run_level_read(surface, params)
    if _is_per_operation_batch(method, params) and callable(
        getattr(surface, "schedule_message", None)
    ):
        return _run_batch_per_operation(surface, params)
    return _call_on_main_thread(surface, lambda: surface.handle_request(method, params))


def _is_per_operation_batch(method, params):
    return method == "ableton.batch" and params.get("atomic") is False


def _run_batch_per_operation(surface, params):
    """Run each operation of an ``atomic=false`` batch in its own callback.

    Live 12.4.16 merged parameter changes made in one main-thread callback
    into one undo step, even with a separate begin/end_undo_step pair around
    each (2026-11-03 run, issue #26). Separate requests stayed separate. So
    each operation runs a tick after the previous one finished. The batch is
    checked first and changes nothing if it is malformed. Operations not
    started before the deadline are not run, so a client that gave up does
    not see later changes.
    """

    deadline = time.monotonic() + REQUEST_RUN_TIMEOUT_SECONDS

    def song():
        return _live_object(surface, "song")

    plan = _call_on_main_thread(surface, lambda: live_ops.prepare_batch(song(), params))
    results = []
    for position in range(len(plan["operations"])):
        try:
            if time.monotonic() > deadline:
                raise TimeoutError(
                    "the batch ran out of time; this and later operations were not run"
                )
            results.append(
                _call_on_main_thread(
                    surface,
                    lambda p=position: live_ops.run_batch_operation(song(), plan, p),
                    delay=BATCH_OPERATION_TICK_DELAY,
                )
            )
        except Exception as exc:
            return live_ops.batch_failure(plan, results, position, exc)
    return live_ops.batch_success(plan, results)


def _level_clock():
    """Seconds on a monotonic clock, for level windows. Tests replace it."""

    return time.monotonic()


def _run_level_read(surface, params):
    """Sample track meters over several Live ticks, then answer (issue #45).

    Runs on the socket thread, which only waits; every Live read happens on
    the main thread. The setup call checks the request and the transport and
    pins the tracks. Then one callback samples the meters and schedules
    itself again LEVEL_SAMPLE_TICK_DELAY ticks later, until the window says
    it is over. Nothing sleeps or loops on the main thread, and the
    transport is never touched. If the window does not finish in time the
    socket thread stops waiting and the next tick ends the chain; the read
    changed nothing, so there is nothing to put back.
    """

    schedule_message = surface.schedule_message

    def song():
        return _live_object(surface, "song")

    window = _call_on_main_thread(
        surface,
        lambda: live_ops.LevelWindow(live_ops.prepare_level_read(song(), params), _level_clock()),
    )
    finished = threading.Event()
    state = {"abandoned": False}

    def tick():
        if state["abandoned"]:
            return
        try:
            done = window.sample(song(), _level_clock())
        except Exception as exc:
            state["error"] = exc
            done = True
        if done:
            finished.set()
        else:
            schedule_message(LEVEL_SAMPLE_TICK_DELAY, tick)

    schedule_message(0, tick)
    if not finished.wait(window.seconds + LEVEL_READ_GRACE_SECONDS):
        state["abandoned"] = True
        raise TimeoutError(f"Live {_LEVELS_NOT_FINISHED}; nothing was changed")
    if "error" in state:
        raise state["error"]
    return window.result(tick_delay=LEVEL_SAMPLE_TICK_DELAY)


def _call_on_main_thread(surface, action, delay=0):
    schedule_message = getattr(surface, "schedule_message", None)
    if not callable(schedule_message):
        return action()

    started = threading.Event()
    completed = threading.Event()
    lock = threading.Lock()
    state = {"cancelled": False}

    def run_request():
        with lock:
            if state["cancelled"]:
                return
            started.set()
        try:
            state["result"] = action()
        except Exception as exc:
            state["error"] = exc
        finally:
            completed.set()

    schedule_message(delay, run_request)
    if not started.wait(REQUEST_START_TIMEOUT_SECONDS):
        with lock:
            if not started.is_set():
                state["cancelled"] = True
                raise TimeoutError(f"Live was busy and {_NOT_STARTED}; nothing changed")
    if not completed.wait(REQUEST_RUN_TIMEOUT_SECONDS):
        raise TimeoutError(f"Live started the request but {_NOT_FINISHED}")
    if "error" in state:
        raise state["error"]
    return state["result"]


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
    raise live_ops.NotFound(
        f"selected track '{_string_attr(track, 'name')}' has no Drum Rack",
        "Select the track that holds the Drum Rack in Live, then plan again.",
    )


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


def _track_index(song, target_track):
    target_id = _object_id(target_track)
    for index, track in enumerate(_song_tracks(song)):
        if track is target_track or _object_id(track) == target_id:
            return index
    raise RuntimeError(f"track '{_string_attr(target_track, 'name')}' is unavailable")


def _song_tracks(song):
    return _as_tuple(getattr(song, "tracks", ()))


def _track_by_id(song, track_id):
    for track in _song_tracks(song):
        if _object_id(track) == track_id:
            return track
    raise RuntimeError(f"track '{track_id}' is unavailable")


def _duplicate_track_after(song, source_index):
    before = _song_tracks(song)
    duplicate_track = getattr(song, "duplicate_track", None)
    if not callable(duplicate_track):
        raise RuntimeError("Abletonian Remote Script cannot duplicate tracks")
    returned = duplicate_track(source_index)
    after = _song_tracks(song)
    if returned is not None:
        return returned
    if len(after) != len(before) + 1:
        raise RuntimeError("Live did not report a duplicated track")
    created_index = source_index + 1
    if created_index >= len(after):
        raise RuntimeError("duplicated track index is unavailable")
    return after[created_index]


def _assign_track_name(track, name, warnings):
    try:
        track.name = name
    except Exception as exc:
        warnings.append(f"Could not rename scaffold track to '{name}': {exc}")


def _assign_track_color(track, color, warnings):
    if color is None:
        return
    try:
        track.color_index = int(color)
    except (TypeError, ValueError):
        warnings.append(f"Could not apply non-integer scaffold color '{color}'")
    except Exception as exc:
        track_name = _string_attr(track, "name")
        warnings.append(f"Could not color scaffold track '{track_name}': {exc}")


def _filter_track_midi_clips(track, keep_pitch, pad_name, warnings):
    clips = []
    for clip in _session_midi_clips(track):
        clip_payload = _filter_clip_for_pitch(clip, keep_pitch, pad_name, warnings)
        if clip_payload is not None:
            clips.append(clip_payload)
    if not clips:
        track_name = _string_attr(track, "name")
        warnings.append(f"No MIDI clips on '{track_name}' retained pitch {keep_pitch}")
    return clips


def _filter_clip_for_pitch(clip, keep_pitch, pad_name, warnings):
    before_notes = _clip_notes(clip)
    if not before_notes:
        return None

    _remove_notes_below_pitch(clip, keep_pitch)
    _remove_notes_above_pitch(clip, keep_pitch)
    _assign_clip_name(clip, f"{_string_attr(clip, 'name')} - {pad_name}", warnings)

    after_notes = _clip_notes(clip)
    note_pitches = sorted({note["pitch"] for note in after_notes})
    if any(pitch != keep_pitch for pitch in note_pitches):
        warnings.append(
            f"Clip '{_string_attr(clip, 'name')}' still contains notes outside pitch {keep_pitch}"
        )
    if not after_notes:
        return None
    return {
        "id": _object_id(clip),
        "name": _string_attr(clip, "name"),
        "note_count": len(after_notes),
        "note_pitches": note_pitches,
        "removed_note_count": len(before_notes) - len(after_notes),
    }


def _remove_notes_below_pitch(clip, keep_pitch):
    _remove_notes_in_pitch_range(clip, 0, keep_pitch)


def _remove_notes_above_pitch(clip, keep_pitch):
    _remove_notes_in_pitch_range(clip, keep_pitch + 1, 127 - keep_pitch)


def _remove_notes_in_pitch_range(clip, from_pitch, pitch_span):
    if pitch_span <= 0:
        return
    remove_notes = getattr(clip, "remove_notes_extended", None)
    if not callable(remove_notes):
        remove_notes = getattr(clip, "remove_notes", None)
    if not callable(remove_notes):
        raise RuntimeError(f"clip '{_string_attr(clip, 'name')}' cannot remove MIDI notes")
    remove_notes(from_pitch, pitch_span, 0.0, _clip_time_span(clip))


def _assign_clip_name(clip, name, warnings):
    try:
        clip.name = name
    except Exception as exc:
        warnings.append(f"Could not rename filtered clip to '{name}': {exc}")


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


def _undo_backout_text(created_count):
    """How many Live Undo presses remove the workflow's tracks.

    In Live 12.4.16 each created track took two undo steps: "Duplicate
    Track(s)", then one step for its name and colour. Execute's clip
    filtering joined the last of those steps, so scaffold and execute both
    took two presses per track (2026-11-03 run, issue #26).
    """

    presses = created_count * UNDO_STEPS_PER_CREATED_TRACK
    return (
        f"Use Live Undo {presses} times to remove the {created_count} new tracks "
        f"({UNDO_STEPS_PER_CREATED_TRACK} steps per track: the duplicate, then its "
        "name and colour)."
    )


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
