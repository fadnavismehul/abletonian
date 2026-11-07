"""Mixer, routing, and device operations on the open Live Set.

Every function here takes Live's ``song`` object and plain JSON params, and
returns plain JSON. The bridge calls them on Live's main thread.

Track references accept:

- an integer index into ``song.tracks``,
- ``"master"`` or ``"main"`` for the main track,
- ``"return:N"`` or a return letter such as ``"A"`` for return tracks,
- a track name (exact match first, then case-insensitive).
"""

from __future__ import annotations

import math
import re

# Live's API names some parameters differently from the device UI.
PARAMETER_ALIASES = {
    "StereoGain": {"gain": "Output"},  # Utility shows "Gain"; the API calls it "Output".
}

# Live 12 racks have up to 16 macros.
MAX_RACK_MACROS = 16
# Racks inside racks are listed this deep; deeper chains are marked truncated.
MAX_RACK_DEPTH = 4

BATCHABLE_METHODS = (
    "ableton.set_device_parameter",
    "ableton.set_track_output_routing",
    "ableton.set_track_properties",
    "ableton.set_mixer",
    "ableton.insert_device",
    "ableton.create_return_track",
    "ableton.delete_device",
)


class LiveOpsError(RuntimeError):
    """Raised when a request cannot be applied to the open Live Set.

    ``code`` and ``hint`` reach the caller in the bridge error payload. The
    message says what is wrong; the hint says what to do next. Subclasses
    set both for a kind of error, and a raise can pass a more exact hint.
    """

    code = "live_error"
    hint = None

    def __init__(self, message, hint=None):
        super().__init__(message)
        if hint is not None:
            self.hint = hint


class NotFound(LiveOpsError):
    code = "not_found"
    hint = (
        "Use list_tracks or list_devices to see what is there, then use a name, "
        "index or path from that list."
    )


class InvalidValue(LiveOpsError):
    code = "invalid_value"


class NotSupported(LiveOpsError):
    code = "not_supported"


class NeedsConfirmation(LiveOpsError):
    code = "confirmation_required"
    hint = "Show the user what would change and ask them. Send confirm=true only if they agree."


TRACK_HINT = "Use list_tracks to see track names and indexes."
DEVICE_HINT = "Use list_devices on that track to see its devices, paths and parameters."
VALUE_HINT = (
    "Use list_devices on that track to see this parameter's range, display text "
    "and options, or send {\"raw\": <number>} within its range."
)
SELECTION_HINT = "Select the track (and Rack) in Live, or name the track and device in the call."


def handle(song, method, params):
    """Dispatch one ``ableton.*`` method. Returns None for unknown methods.

    A mutating call runs as its own Live undo step, so one Undo reverts that
    call and nothing before it (issue #3). ``batch`` brackets its own steps.
    """

    handler = _HANDLERS.get(method)
    if handler is None:
        return None
    if method in BATCHABLE_METHODS and not _is_delete_preview(method, params):
        return _in_undo_step(song, lambda: handler(song, params))
    return handler(song, params)


def _is_delete_preview(method, params):
    return method == "ableton.delete_device" and params.get("confirm") is not True


def _in_undo_step(song, action):
    """Run ``action`` between ``Song.begin_undo_step`` and ``end_undo_step``.

    In Live 12.4.16 separate unbracketed calls in a row merged into one
    "Custom Action" step (issue #3). Community reports (for example
    adamjmurray/producer-pal#1209) say a begin/end pair makes its writes one
    step and that steps do not nest, so this is never called inside
    ``batch``'s own bracket.

    Checked in Live 12.4.16 on 2026-11-03 (issue #26): a bracketed call is
    kept apart from the call before it. Within one call Live still keeps
    parameter value changes ("Change ...") in a separate step from other
    changes ("Custom Action"), and it merges parameter changes made in the
    same main-thread callback even across separate brackets.
    """

    begin = getattr(song, "begin_undo_step", None)
    end = getattr(song, "end_undo_step", None)
    if not (callable(begin) and callable(end)):
        return action()
    begin()
    try:
        return action()
    finally:
        end()


def list_tracks(song, params):
    """List tracks. ``detail`` is "full" (default) or "compact".

    Compact leaves out the available routing options and gives volume, pan,
    and sends as display text only, so large sets fit in one tool result.
    ``name`` keeps tracks whose name contains it (case-insensitive).
    """

    include_returns = params.get("include_returns", True)
    include_master = params.get("include_master", True)
    detail = params.get("detail", "full")
    if detail not in ("full", "compact"):
        raise InvalidValue(f"detail must be 'full' or 'compact', got '{detail}'")
    name_filter = params.get("name")
    name_filter = str(name_filter).lower() if name_filter else None
    return_names = [_str(track.name) for track in _tuple(song.return_tracks)]
    items = [("track", i, t) for i, t in enumerate(_tuple(song.tracks))]
    if include_returns:
        items.extend(("return", i, t) for i, t in enumerate(_tuple(song.return_tracks)))
    if include_master:
        items.append(("master", 0, song.master_track))
    if name_filter is not None:
        items = [item for item in items if name_filter in _str(item[2].name).lower()]
    payload = _compact_track_payload if detail == "compact" else _track_payload
    return {
        "tracks": [payload(track, kind, index, return_names) for kind, index, track in items],
        "return_track_names": return_names,
        "detail": detail,
    }


def list_devices(song, params):
    track_ref = params.get("track")
    include_parameters = params.get("include_parameters")
    if include_parameters is None:
        # Every parameter of every device can exceed the bridge frame limit.
        include_parameters = track_ref is not None
    if track_ref is None:
        targets = _all_tracks(song)
    else:
        targets = [resolve_track(song, track_ref)]
    return {
        "tracks": [
            {
                "track": _track_ref_payload(kind, index, track),
                "devices": [
                    _device_payload(
                        device, device_index, include_parameters, track, device_index
                    )
                    for device_index, device in enumerate(_tuple(track.devices))
                ],
            }
            for kind, index, track in targets
        ]
    }


def get_selected_rack_macros(song, params):
    """Read the macros of the selected Rack. Never changes the Live Set.

    ``track`` and ``device`` pick a rack explicitly. Without them the selected
    track is used, and its selected device if that is a rack, else the first
    rack on the track.
    """

    track_ref = params.get("track")
    if track_ref is None:
        kind, index, track = _locate_track(song, song.view.selected_track)
    else:
        kind, index, track = resolve_track(song, track_ref)
    devices = _tuple(track.devices)

    device_ref = params.get("device")
    if device_ref is not None:
        device_index, device = resolve_device(track, device_ref)
        selection = "explicit"
    else:
        device_index, device, selection = _selected_or_first_rack(track, devices)
    if not _is_rack(device):
        raise LiveOpsError(
            f"device '{_str(device.name)}' on track '{_str(track.name)}' is not a Rack"
        )

    macro_parameters = _macro_parameters(device)
    mapped = _tuple(_get(device, "macros_mapped", None)) or None
    visible = _get(device, "visible_macro_count", None)
    macros = []
    for macro_index, parameter in enumerate(macro_parameters, start=1):
        if visible is not None and macro_index > int(visible):
            break
        value = float(parameter.value)
        macros.append(
            {
                "index": macro_index,
                "name": _str(parameter.name),
                "original_name": _str(_get(parameter, "original_name", parameter.name)),
                "value": value,
                "min": float(parameter.min),
                "max": float(parameter.max),
                "display": _display(parameter, value),
                "is_mapped": (
                    bool(mapped[macro_index - 1])
                    if mapped is not None and macro_index <= len(mapped)
                    else None
                ),
                "is_enabled": bool(_get(parameter, "is_enabled", True)),
            }
        )

    class_name = _str(_get(device, "class_name", ""))
    return {
        "track": {
            **_track_ref_payload(kind, index, track),
            "color": _hex_color(_get(track, "color")),
        },
        "device": {
            "index": device_index,
            "name": _str(device.name),
            "class_name": class_name,
            "class_display_name": _str(_get(device, "class_display_name", "")),
            "type": "drum_rack" if class_name == "DrumGroupDevice" else "rack",
            "chain_names": [_str(chain.name) for chain in _tuple(_get(device, "chains", ()))],
        },
        "selection": selection,
        "visible_macro_count": None if visible is None else int(visible),
        "macros": macros,
    }


def set_device_parameter(song, params):
    kind, index, track = resolve_track(song, _required(params, "track"))
    path, device_index, device, _owner = resolve_device_path(track, _required(params, "device"))
    parameter = resolve_parameter(device, _required(params, "parameter"))
    before = _param_payload(parameter)
    reading = set_parameter_value(parameter, _required(params, "value"))
    result = {
        "track": _track_ref_payload(kind, index, track),
        "device": {"index": device_index, "name": _str(device.name), "path": path},
        "before": before,
        "after": _param_payload(parameter),
        "read_as": reading["read_as"],
    }
    if reading["note"]:
        result["note"] = reading["note"]
    return result


def set_track_output_routing(song, params):
    kind, index, track = resolve_track(song, _required(params, "track"))
    routing_type = _required(params, "routing_type")
    routing_channel = params.get("routing_channel")
    before = _routing_payload(track)
    previous_type = track.output_routing_type
    track.output_routing_type = _match_routing(
        track.available_output_routing_types, routing_type, "output routing type"
    )
    if routing_channel is not None:
        # Channel options depend on the type, so match after setting it and
        # put the old type back if the channel does not exist.
        try:
            channel = _match_routing(
                track.available_output_routing_channels, routing_channel, "output routing channel"
            )
        except LiveOpsError as exc:
            track.output_routing_type = previous_type
            raise LiveOpsError(
                f"{exc}. The output type was put back; Live may still list this as an "
                "undo step that changes nothing."
            ) from exc
        track.output_routing_channel = channel
    return {
        "track": _track_ref_payload(kind, index, track),
        "before": before,
        "after": _routing_payload(track),
    }


def set_track_properties(song, params):
    kind, index, track = resolve_track(song, _required(params, "track"))
    before = {"name": _str(track.name), "color_index": _get(track, "color_index")}
    if params.get("name") is not None:
        name = str(params["name"])
        if kind == "return":
            name = _without_return_prefix(name, index)
        track.name = name
    if params.get("color_index") is not None:
        track.color_index = int(params["color_index"])
    if params.get("color") is not None:
        track.color = _parse_color(params["color"])
    return {
        "track": _track_ref_payload(kind, index, track),
        "before": before,
        "after": {
            "name": _str(track.name),
            "color_index": _get(track, "color_index"),
            "color": _hex_color(_get(track, "color")),
        },
    }


def set_mixer(song, params):
    kind, index, track = resolve_track(song, _required(params, "track"))
    mixer = track.mixer_device
    return_names = [_str(t.name) for t in _tuple(song.return_tracks)]
    send_params = _tuple(_get(mixer, "sends", ()))

    # Work out every change before applying any, so a bad argument leaves the
    # track untouched.
    planned = []
    for key in ("volume", "panning"):
        if params.get(key) is not None:
            parameter = getattr(mixer, key)
            planned.append((key, None, parameter, _raw_value(parameter, params[key])))
    for send_ref, value in (params.get("sends") or {}).items():
        send_index = _resolve_send(send_ref, return_names, len(send_params))
        parameter = send_params[send_index]
        planned.append(("sends", return_names[send_index], parameter, _raw_value(parameter, value)))
    switches = []
    for key in ("mute", "solo"):
        if params.get(key) is not None:
            if kind == "master":
                raise LiveOpsError(f"the main track has no {key} switch")
            switches.append((key, bool(params[key])))
    if not planned and not switches:
        raise LiveOpsError("set_mixer needs at least one of volume, panning, sends, mute, solo")

    changed = {}
    for key, send_name, parameter, raw in planned:
        parameter.value = raw
        if key == "sends":
            changed.setdefault("sends", {})[send_name] = _param_payload(parameter)
        else:
            changed[key] = _param_payload(parameter)
    for key, value in switches:
        setattr(track, key, value)
        changed[key] = bool(getattr(track, key))
    return {"track": _track_ref_payload(kind, index, track), "changed": changed}


def insert_device(song, params):
    kind, index, track = resolve_track(song, _required(params, "track"))
    device_name = str(_required(params, "device_name"))
    # Check what can be checked without the device before inserting it, so a
    # malformed value changes nothing at all (issue #44).
    requested = _check_parameter_settings(params.get("parameters"))
    position = params.get("index")
    insert = getattr(track, "insert_device", None)
    if not callable(insert):
        raise NotSupported(
            "Track.insert_device is unavailable; it needs Live 12.3 or later",
            "Update Live to 12.3 or later, or add the device in Live yourself.",
        )
    devices_before = _tuple(track.devices)
    count_before = len(devices_before)
    if position is None:
        position = count_before
    position = int(position)
    if position < 0 or position > count_before:
        raise InvalidValue(
            f"device index {position} is out of range for '{_str(track.name)}' "
            f"(0..{count_before})",
            "Leave index out to add the device at the end of the chain.",
        )
    try:
        insert(device_name, position)
    except Exception as exc:
        raise NotFound(
            f"Live could not insert '{device_name}': {exc}",
            "Use the name of one of Live's own devices as its browser shows it, for example "
            "'EQ Eight' or 'Utility'. Third-party plugins cannot be inserted yet.",
        ) from exc
    devices = _tuple(track.devices)
    if len(devices) != count_before + 1:
        raise LiveOpsError(f"Live did not report a new device after inserting '{device_name}'")
    # Live may place the device elsewhere (device order rules on MIDI tracks),
    # so find it by Live identity rather than trusting the requested position.
    new_positions = [
        i
        for i, device in enumerate(devices)
        if not any(_same(device, old) for old in devices_before)
    ]
    if len(new_positions) == 1:
        position = new_positions[0]
    device = devices[position]
    changed = []
    try:
        # Parameter names only exist on the inserted device. Resolve them all
        # before writing any value, so a wrong name fails before a parameter
        # changes. Values are resolved and set in the order given, since one
        # parameter's display can depend on another (a sync switch).
        targets = [(resolve_parameter(device, ref), value) for ref, value in requested]
        for parameter, value in targets:
            reading = set_parameter_value(parameter, value)
            payload = _param_payload(parameter)
            payload["read_as"] = reading["read_as"]
            if reading["note"]:
                payload["note"] = reading["note"]
            changed.append(payload)
    except Exception as exc:
        # Leave the track as it was rather than with a half-configured device.
        # The Live API cannot drop an undo step (Song has begin_undo_step,
        # end_undo_step and undo, Cycling '74 LOM docs), and pressing undo
        # here could reach the musician's own edits, so the insert-and-delete
        # stays in Undo History as a step that changes nothing.
        delete = getattr(track, "delete_device", None)
        if callable(delete):
            delete(position)
            message = (
                f"{exc}. The new '{device_name}' was removed again; Live may still list "
                "this as an undo step that changes nothing."
            )
            if isinstance(exc, LiveOpsError):
                raise type(exc)(message, _insert_hint(exc)) from exc
            raise LiveOpsError(message) from exc
        raise
    return {
        "track": _track_ref_payload(kind, index, track),
        "device": _device_payload(device, position, False, track, position),
        "parameters_set": changed,
    }


def _check_parameter_settings(settings):
    """Check ``insert_device``'s ``parameters`` without a device; return its items."""

    if settings is None:
        return []
    if not isinstance(settings, dict):
        raise InvalidValue(
            "insert_device 'parameters' must be an object of parameter name to value, "
            'such as {"Gain": "-3 dB"}'
        )
    for ref, value in settings.items():
        if not isinstance(ref, (str, int)) or isinstance(ref, bool) or not str(ref).strip():
            raise InvalidValue(f"parameter name {ref!r} in 'parameters' is not a name or index")
        check_value_shape(value, str(ref))
    return list(settings.items())


def _insert_hint(exc):
    hint = getattr(exc, "hint", None)
    extra = (
        "Parameter names, options and display text can only be checked once the device "
        "is in the Set: insert it without parameters, read them with list_devices, then "
        "use set_device_parameter."
    )
    return f"{hint} {extra}" if hint else extra


def create_return_track(song, params):
    """Add a return track at the end (``Song.create_return_track``). Additive."""

    create = getattr(song, "create_return_track", None)
    if not callable(create):
        raise NotSupported(
            "this version of Live cannot create return tracks from a script",
            "Add the return track in Live yourself (Create > Insert Return Track).",
        )
    before = len(_tuple(song.return_tracks))
    create()
    returns = _tuple(song.return_tracks)
    if len(returns) != before + 1:
        raise LiveOpsError("Live did not add a return track")
    index = len(returns) - 1
    track = returns[index]
    if params.get("name") is not None:
        track.name = _without_return_prefix(str(params["name"]), index)
    if params.get("color") is not None:
        track.color = _parse_color(params["color"])
    return {
        "track": _track_ref_payload("return", index, track),
        "letter": chr(ord("A") + index) if index < 26 else None,
        "color": _hex_color(_get(track, "color")),
        "note": "Every track now has a send to this return; check send levels before playing.",
    }


def delete_device(song, params, target=None):
    """Delete a device. Destructive: without ``confirm=true`` it only previews.

    ``target`` is set by ``batch``: the device resolved before the batch ran,
    so earlier deletes in the same batch cannot shift which device an index
    or name points at.
    """

    if target is None:
        target = _resolve_delete_target(song, params)
    kind, index, track, path, device, owner = target
    device_index = _current_index(owner, device, path)
    preview = {
        "track": _track_ref_payload(kind, index, track),
        "device": {
            "index": device_index,
            "name": _str(device.name),
            "path": path,
            "class_name": _str(_get(device, "class_name", "")),
            "parameters": {
                _str(p.name): _shown(p) for p in _tuple(_get(device, "parameters", ()))
            },
        },
    }
    if params.get("confirm") is not True:
        return {
            "deleted": False,
            "would_delete": preview,
            "hint": "Nothing was changed. Call again with confirm=true to delete this device.",
        }
    remove = getattr(owner, "delete_device", None)
    if not callable(remove):
        raise NotSupported(
            f"Live cannot delete devices inside '{_str(owner.name)}' from a script",
            "Delete it in Live yourself, or turn it off with its Device On parameter.",
        )
    remove(device_index)
    return {"deleted": True, **preview, "undo": "Live's Undo restores the device and settings."}


def _resolve_delete_target(song, params):
    kind, index, track = resolve_track(song, _required(params, "track"))
    path, _device_index, device, owner = resolve_device_path(track, _required(params, "device"))
    return kind, index, track, path, device, owner


def _current_index(owner, device, path):
    for position, candidate in enumerate(_tuple(owner.devices)):
        if _same(candidate, device):
            return position
    raise NotFound(
        f"device '{path}' is no longer there (was it deleted earlier in this batch?)",
        DEVICE_HINT,
    )


def batch(song, params):
    """Run several operations. With ``atomic`` (default) they share one undo
    step. With ``atomic=false`` each gets its own step, but only when each
    runs in its own main-thread callback: in Live 12.4.16, parameter changes
    made in one callback merged into one undo step even across separate
    ``begin_undo_step``/``end_undo_step`` pairs (2026-11-03 run, issue #26).
    The bridge therefore runs a per-operation batch through ``prepare_batch``
    and ``run_batch_operation``, one callback each; this single-callback
    path is the fallback when no scheduler is available.
    """

    plan = prepare_batch(song, params)
    results = []
    if plan["atomic"]:
        grouped = plan["summary"]["grouped_undo"]
        if grouped:
            song.begin_undo_step()
        try:
            for position in range(len(plan["operations"])):
                try:
                    results.append(_run_planned(song, plan, position))
                except Exception as exc:
                    return batch_failure(plan, results, position, exc)
        finally:
            if grouped:
                song.end_undo_step()
        return batch_success(plan, results)

    for position in range(len(plan["operations"])):
        try:
            results.append(run_batch_operation(song, plan, position))
        except Exception as exc:
            return batch_failure(plan, results, position, exc)
    return batch_success(plan, results)


def prepare_batch(song, params):
    """Check a batch and pin its delete targets before anything changes.

    Returns a plan for ``run_batch_operation``. Raises ``LiveOpsError`` and
    changes nothing when the batch is malformed.
    """

    operations = _required(params, "operations")
    if not isinstance(operations, list) or not operations:
        raise InvalidValue("batch operations must be a non-empty list")
    for position, operation in enumerate(operations):
        method = operation.get("method") if isinstance(operation, dict) else None
        if method not in BATCHABLE_METHODS:
            raise LiveOpsError(
                f"operation {position} has unsupported method '{method}'; "
                f"allowed: {', '.join(BATCHABLE_METHODS)}"
            )

    # Value shapes need no Live object, so a malformed value rejects the whole
    # batch before anything changes.
    for position, operation in enumerate(operations):
        operation_params = operation.get("params", {})
        try:
            if not isinstance(operation_params, dict):
                continue
            if operation["method"] == "ableton.set_device_parameter":
                if "value" in operation_params:
                    label = str(operation_params.get("parameter"))
                    check_value_shape(operation_params["value"], label)
            elif operation["method"] == "ableton.insert_device":
                _check_parameter_settings(operation_params.get("parameters"))
        except LiveOpsError as exc:
            raise type(exc)(f"operation {position}: {exc}; nothing was changed", exc.hint) from exc

    # Deletes are checked and resolved before anything runs: an unconfirmed
    # delete rejects the whole batch (rather than "completing" as a preview),
    # and each target is pinned to the device the caller saw, so deleting
    # index 0 does not make a later "index 1" point at a different device.
    delete_targets = {}
    for position, operation in enumerate(operations):
        if operation["method"] != "ableton.delete_device":
            continue
        operation_params = operation.get("params", {})
        if operation_params.get("confirm") is not True:
            raise NeedsConfirmation(
                f"operation {position} (ableton.delete_device) needs \"confirm\": true "
                "inside a batch; nothing was changed"
            )
        try:
            delete_targets[position] = _resolve_delete_target(song, operation_params)
        except LiveOpsError as exc:
            # Keep the kind and hint of the underlying error.
            wrapped = type(exc)(f"operation {position}: {exc}; nothing was changed", exc.hint)
            raise wrapped from exc

    atomic = params.get("atomic", True)
    if not isinstance(atomic, bool):
        raise InvalidValue("batch 'atomic' must be true or false")
    grouped_undo = callable(getattr(song, "begin_undo_step", None)) and callable(
        getattr(song, "end_undo_step", None)
    )
    return {
        "operations": operations,
        "delete_targets": delete_targets,
        "atomic": atomic,
        "summary": {
            "grouped_undo": grouped_undo,
            "undo_steps": ("one" if atomic else "per_operation") if grouped_undo else "none",
        },
    }


def run_batch_operation(song, plan, position):
    """Run one operation of a per-operation plan as its own undo step."""

    return _in_undo_step(song, lambda: _run_planned(song, plan, position))


def _run_planned(song, plan, position):
    operation = plan["operations"][position]
    operation_params = operation.get("params", {})
    if position in plan["delete_targets"]:
        return delete_device(song, operation_params, plan["delete_targets"][position])
    return _HANDLERS[operation["method"]](song, operation_params)


def batch_success(plan, results):
    return {"completed": results, "failed": None, **plan["summary"]}


def batch_failure(plan, results, position, exc):
    summary = plan["summary"]
    failure = {
        "completed": results,
        "failed": {
            "index": position,
            "operation": plan["operations"][position],
            "error": str(exc),
            **_error_fields(exc),
        },
        **summary,
    }
    if summary["undo_steps"] == "per_operation":
        failure["note"] = (
            "Each completed operation is one undo step. If the failed one had started "
            "changing the Set it was put back, but Live may still count it as a step."
        )
    return failure


def _error_fields(exc):
    fields = {"code": getattr(exc, "code", "live_error")}
    hint = getattr(exc, "hint", None)
    if hint:
        fields["hint"] = hint
    return fields


MAX_UNDO_COUNT = 20


def undo(song, params):
    """Run Live's Undo ``count`` times (default 1; above 1 needs ``confirm``).
    Stops early when Live has nothing left to undo, and reports how many
    steps were undone."""

    count = params.get("count", 1)
    if isinstance(count, bool) or not isinstance(count, int) or not 1 <= count <= MAX_UNDO_COUNT:
        raise InvalidValue(f"undo count must be an integer from 1 to {MAX_UNDO_COUNT}")
    if count > 1 and params.get("confirm") is not True:
        raise NeedsConfirmation(
            f"undoing {count} steps needs \"confirm\": true; Live's undo history also holds "
            "the user's own edits. Nothing was changed."
        )
    undone = 0
    while undone < count and bool(getattr(song, "can_undo", True)):
        song.undo()
        undone += 1
    if undone == 0:
        raise LiveOpsError("Live has nothing to undo")
    result = {"undone": True, "steps": undone}
    if undone < count:
        result["note"] = f"Live had only {undone} step(s) to undo."
    return result


# Lookup -------------------------------------------------------------------


def resolve_track(song, ref):
    """Return ``(kind, index, track)`` for a track reference."""

    tracks = _tuple(song.tracks)
    returns = _tuple(song.return_tracks)
    if isinstance(ref, bool):
        raise LiveOpsError("track reference must be an index or a name")
    if isinstance(ref, int):
        if 0 <= ref < len(tracks):
            return ("track", ref, tracks[ref])
        raise NotFound(f"track index {ref} is out of range (0..{len(tracks) - 1})", TRACK_HINT)
    text = str(ref).strip()
    lowered = text.lower()
    candidates = _all_tracks(song)

    # A real track name wins over the shorthand forms below, so tracks named
    # "808" or "A" stay reachable.
    exact = [item for item in candidates if _str(item[2].name) == text]
    if len(exact) == 1:
        return exact[0]
    if lowered in ("master", "main"):
        return ("master", 0, song.master_track)
    if lowered.startswith("return:"):
        return_index = _int_or_error(text.split(":", 1)[1], "return index")
        if 0 <= return_index < len(returns):
            return ("return", return_index, returns[return_index])
        raise NotFound(f"return index {return_index} is out of range", TRACK_HINT)
    if len(text) == 1 and text.isalpha() and text.upper() < chr(ord("A") + len(returns)):
        return_index = ord(text.upper()) - ord("A")
        return ("return", return_index, returns[return_index])
    if text.isdigit():
        return resolve_track(song, int(text))

    for matcher in (lambda name: name == text, lambda name: name.lower() == lowered):
        matches = [item for item in candidates if matcher(_str(item[2].name))]
        if len(matches) == 1:
            return matches[0]
        if len(matches) > 1:
            raise LiveOpsError(
                f"track name '{text}' is ambiguous; use an index: "
                + ", ".join(f"{kind}:{index}" for kind, index, _ in matches)
            )
    names = ", ".join(_str(item[2].name) for item in candidates)
    raise NotFound(f"no track named '{text}'. Tracks: {names}", TRACK_HINT)


def resolve_device(track, ref):
    devices = _tuple(track.devices)
    if isinstance(ref, int) and not isinstance(ref, bool):
        if 0 <= ref < len(devices):
            return ref, devices[ref]
        raise NotFound(
            f"device index {ref} is out of range on '{_str(track.name)}' ({len(devices)} devices)",
            DEVICE_HINT,
        )
    text = str(ref)
    # "#N" always means index N, even if a device is named "#N" (issue #24).
    if re.fullmatch(r"#\d+", text.strip()):
        return resolve_device(track, int(text.strip()[1:]))
    for matcher in (lambda d: _str(d.name) == text, lambda d: _str(d.name).lower() == text.lower()):
        matches = [(i, d) for i, d in enumerate(devices) if matcher(d)]
        if len(matches) == 1:
            return matches[0]
        if len(matches) > 1:
            raise LiveOpsError(
                f"device name '{text}' is ambiguous on '{_str(track.name)}'; use an index: "
                + ", ".join(str(i) for i, _ in matches)
            )
    if text.strip().isdigit():
        return resolve_device(track, int(text))
    names = ", ".join(_str(d.name) for d in devices) or "(none)"
    raise NotFound(
        f"no device named '{text}' on '{_str(track.name)}'. Devices: {names}", DEVICE_HINT
    )


def resolve_device_path(track, ref, _render=True):
    """Resolve a device anywhere on a track. Returns ``(path, index, device, owner)``.

    ``ref`` is an index, a top-level device name, or a path through racks:
    ``"Instrument Rack/Piano/Reverb"`` (rack / chain / device, repeated for
    nested racks) or ``"Drum Rack/returns/0/Limiter"`` for a Drum Rack return
    chain. Names or indexes work for every segment. A top-level device whose
    whole name matches wins, so names containing "/" still work. ``owner`` is
    the track or chain holding the device; ``index`` is its position there.
    ``path`` is how list_devices would print it, or None if no printable
    path resolves back to this device (see ``_printable_path``).
    Uses RackDevice.chains, RackDevice.return_chains, and Chain.devices from
    the Live Object Model (issue #17; return chains confirmed in Live 12.4.16).
    """

    if isinstance(ref, int) or "/" not in str(ref) or _has_device_named(track, str(ref)):
        index, device = resolve_device(track, ref)
        path = _printable_path(track, index, [], device) if _render else None
        return path, index, device, track
    segments = [part.strip() for part in str(ref).split("/")]
    if any(not part for part in segments):
        raise InvalidValue(f"device path '{ref}' has an empty part", DEVICE_HINT)
    index, device = resolve_device(track, segments[0])
    top_index = index
    path = [_str(device.name)]  # for error messages only
    tail = []
    owner = track
    rest = segments[1:]
    while rest:
        if not bool(_get(device, "can_have_chains", False)):
            raise NotFound(
                f"'{'/'.join(path)}' is not a Rack, so it has no chain '{rest[0]}'", DEVICE_HINT
            )
        if rest[0].lower() == "returns":
            chains = _tuple(_get(device, "return_chains", ()))
            label = "return chain"
            path.append("returns")
            tail.append("returns")
            rest = rest[1:]
            if not rest:
                raise InvalidValue(
                    f"device path '{ref}' needs a return chain after 'returns'", DEVICE_HINT
                )
        else:
            chains = _tuple(_get(device, "chains", ()))
            label = "chain"
        chain_index, chain = _pick(chains, rest[0], label, "/".join(path))
        path.append(_str(chain.name))
        tail.append(_path_segment(chains, chain_index))
        if len(rest) < 2:
            raise InvalidValue(
                f"device path '{ref}' ends at a chain; add a device name", DEVICE_HINT
            )
        chain_devices = _tuple(chain.devices)
        index, device = _pick(chain_devices, rest[1], "device", "/".join(path))
        path.append(_str(device.name))
        tail.append(_path_segment(chain_devices, index))
        owner = chain
        rest = rest[2:]
    printed = _printable_path(track, top_index, tail, device) if _render else None
    return printed, index, device, owner


def _path_segment(items, position):
    """The text for one part of a device path that resolves back to ``items[position]``.

    The name is used when it picks this item unambiguously; otherwise the
    index is (issue #24: two Drum Rack chains both named "Guiro Short").
    Names that would be read as something else also get the index: digits
    (read as an index), "returns" (the return-chain marker), names with "/"
    (the separator), and names with surrounding spaces (segments are
    stripped).
    """

    name = _str(items[position].name)
    exact = sum(1 for item in items if _str(item.name) == name)
    if (
        exact == 1
        and name
        and name == name.strip()
        and not name.isdigit()
        and "/" not in name
        and name.lower() != "returns"
    ):
        return name
    return str(position)


def _printable_path(track, top_index, tail, device):
    """A path that resolves back to ``device``, or None if none does.

    ``tail`` holds the segments below the top-level device; ``_path_segment``
    makes those unambiguous on its own, because chain and chain-device
    lookups read digits as an index first. Top-level lookups try a whole
    device name before splitting on "/", then names, then digits, so the top
    segment is the device's name if that is unique, else ``N`` if no device
    is named "N", else ``#N``, which ``resolve_device`` always reads as an
    index. A candidate is skipped if the whole path equals some top-level
    device's name, since that lookup would win (issue #24). These rules are
    checked without re-resolving, because list_devices runs on Live's main
    thread; tests resolve every printed path to check them.
    """

    devices = _tuple(track.devices)
    name = _str(devices[top_index].name)
    unique = sum(1 for d in devices if _str(d.name) == name) == 1
    candidates = []
    if (
        unique
        and name
        and name == name.strip()
        and (not tail or "/" not in name)
        and not re.fullmatch(r"#\d+", name)
    ):
        candidates.append(name)
    index_text = str(top_index)
    if not any(_str(d.name).strip() == index_text for d in devices):
        candidates.append(index_text)
    candidates.append(f"#{top_index}")
    for top in candidates:
        text = "/".join([top, *tail])
        if tail and _has_device_named(track, text):
            continue
        return text
    return None


def _has_device_named(track, name):
    return any(_str(d.name).lower() == name.lower() for d in _tuple(track.devices))


def _pick(items, ref, label, where):
    """Pick from a Live list by index or name (exact, then case-insensitive)."""

    text = str(ref).strip()
    if isinstance(ref, int) and not isinstance(ref, bool) or text.isdigit():
        position = int(text)
        if 0 <= position < len(items):
            return position, items[position]
    for matcher in (lambda n: n == text, lambda n: n.lower() == text.lower()):
        matches = [(i, item) for i, item in enumerate(items) if matcher(_str(item.name))]
        if len(matches) == 1:
            return matches[0]
        if len(matches) > 1:
            raise LiveOpsError(
                f"{label} name '{text}' is ambiguous in '{where}'; use an index: "
                + ", ".join(str(i) for i, _ in matches)
            )
    names = ", ".join(f"{i}:{_str(item.name)}" for i, item in enumerate(items)) or "(none)"
    raise NotFound(f"no {label} '{text}' in '{where}'. Choices: {names}", DEVICE_HINT)


def resolve_parameter(device, ref):
    parameters = _tuple(device.parameters)
    if isinstance(ref, int) and not isinstance(ref, bool):
        if 0 <= ref < len(parameters):
            return parameters[ref]
        raise NotFound(
            f"parameter index {ref} is out of range on '{_str(device.name)}'", DEVICE_HINT
        )
    lowered = str(ref).lower()
    aliases = PARAMETER_ALIASES.get(_str(_get(device, "class_name", "")), {})
    lowered = aliases.get(lowered, lowered).lower()
    for attribute in ("name", "original_name"):
        for parameter in parameters:
            if _str(_get(parameter, attribute, "")).lower() == lowered:
                return parameter
    if str(ref).strip().isdigit():
        return resolve_parameter(device, int(str(ref)))
    names = ", ".join(_str(p.name) for p in parameters)
    raise NotFound(
        f"no parameter '{ref}' on '{_str(device.name)}'. Parameters: {names}", DEVICE_HINT
    )


# Parameter values ---------------------------------------------------------
#
# What Live tells us about a parameter (Cycling '74 LOM docs, DeviceParameter):
# ``min``/``max``/``value`` are raw numbers, ``is_quantized`` marks stepped
# parameters, ``value_items`` lists their option names ("Only valid for
# quantized parameters"), and ``str_for_value(value)`` returns the display
# text for a raw value without setting it. Nothing in this section writes
# ``parameter.value``: a failed lookup changes nothing and leaves no undo step.
#
# Live 12.4.16 runs showed two gaps: some plugins' ``str_for_value`` returns
# the current value's text whatever it is given (issue #16), and some
# stepped native parameters (Glue Compressor Attack/Release/Ratio, Echo
# "L Synced") gave no options and failed display lookups (issue #44). Whether
# those report ``is_quantized`` and ``value_items`` is not known; the code
# below works either way, which is a guess until checked in Live.

# A quantized parameter without value_items lists the display text of each
# step as its options when it has at most this many steps.
MAX_LISTED_STEPS = 128
# A parameter that is not marked quantized but has a small integer raw range
# whose half steps show no new text is treated as stepped (a guess, issue #44).
MAX_GUESSED_STEPS = 64
# When looking for display text, every integer step of a range up to this
# size is sampled, along with EVEN_SAMPLES evenly spaced points.
MAX_SAMPLED_STEPS = 256
EVEN_SAMPLES = 33
# Lists of display texts in error messages are cut to this many entries.
MAX_LISTED_TEXTS = 24

RAW_VALUE_HINT = 'Send {"raw": <number>} to set a raw value exactly.'


def set_parameter_value(parameter, value):
    """Set ``value`` as ``resolve_value`` reads it and return that reading."""

    reading = resolve_value(parameter, value)
    parameter.value = reading["raw"]
    return reading


def _raw_value(parameter, value):
    """Validate ``value`` for ``parameter`` and return the raw value to set."""

    return resolve_value(parameter, value)["raw"]


def check_value_shape(value, label):
    """Refuse a value that is not a number, a string or ``{"raw": number}``.

    Needs no Live object, so callers can check before changing anything.
    """

    if isinstance(value, dict):
        raw = value.get("raw")
        if (
            set(value) == {"raw"}
            and isinstance(raw, (int, float))
            and not isinstance(raw, bool)
            and math.isfinite(raw)
        ):
            return
        raise InvalidValue(
            f"value {value!r} for '{label}' is not understood; an object value must be "
            '{"raw": <number>}',
            RAW_VALUE_HINT,
        )
    if isinstance(value, bool) or isinstance(value, str):
        return
    if isinstance(value, (int, float)) and math.isfinite(value):
        return
    raise InvalidValue(
        f"value {value!r} for '{label}' must be a number, display text, or "
        '{"raw": <number>}',
        VALUE_HINT,
    )


def resolve_value(parameter, value):
    """Work out the raw value that ``value`` means for ``parameter``.

    - ``{"raw": n}`` is the raw value ``n``.
    - A string is display text or an option name: ``"-6 dB"``, ``"1.00"``,
      ``"Auto"``, ``"1/8"``.
    - A bare number is read by ``_resolve_number`` (issue #43).

    Returns ``{"raw": float, "read_as": "raw" | "display", "note": str | None}``.
    Never writes the parameter.
    """

    name = _str(parameter.name)
    if not bool(_get(parameter, "is_enabled", True)):
        raise LiveOpsError(
            f"parameter '{name}' is not editable right now "
            "(it may be controlled by a macro or modulation)"
        )
    check_value_shape(value, name)
    low, high = float(parameter.min), float(parameter.max)
    if isinstance(value, dict):
        raw = float(value["raw"])
        _check_range(parameter, raw, low, high)
        return {"raw": raw, "read_as": "raw", "note": None}
    if isinstance(value, bool):
        value = float(value)
    if isinstance(value, (int, float)):
        return _resolve_number(parameter, float(value), low, high)
    raw = value_for_display(parameter, str(value))
    _check_range(parameter, raw, low, high)
    return {"raw": raw, "read_as": "display", "note": None}


def _check_range(parameter, raw, low, high, hint=VALUE_HINT):
    if raw < low or raw > high:
        raise InvalidValue(
            f"value {raw} is outside '{_str(parameter.name)}' range {low}..{high}", hint
        )


def _resolve_number(parameter, number, low, high):
    """Read a bare JSON number (issue #43).

    A bare number is the raw value, except where that would surprise:

    - If Live shows the raw value as that same number (a 0..127 parameter
      showing "64" at raw 64), raw and display agree and it is set.
    - If the parameter shows plain numbers with no unit (EQ Eight Q), or is
      stepped with numeric steps (Glue Compressor Attack), and the number is
      also a display value at a different raw value, it is refused as
      ambiguous; the error names both readings.
    - Outside the raw range, such a parameter reads it as display text.
    - A parameter that shows units ("dB", "Hz") or option names keeps the
      documented raw reading (Track Volume 0.85); the result's note says what
      Live shows for it.
    """

    name = _str(parameter.name)
    text = _format_number(number)
    in_range = low <= number <= high
    shown = _display(parameter, number) if in_range else None
    if shown is not None and _number_agrees(shown, number):
        return {"raw": number, "read_as": "raw", "note": None}

    steps = _steps(parameter)
    unitless = steps is None and _shows_plain_numbers(parameter, low, high)
    display_raw = None
    if steps is not None:
        index = _match_step_number(text, steps)
        if index is not None:
            display_raw = low + index
    elif unitless:
        display_raw = _display_lookup(parameter, text)

    if in_range:
        if display_raw is not None and _display(parameter, display_raw) != shown:
            raise InvalidValue(
                f"{text} is ambiguous for '{name}': as a raw value it shows as '{shown}', "
                f"but '{_display(parameter, display_raw)}' is raw {_format_number(display_raw)}",
                f'Send the text "{text}" (a string) to set what Live shows, or '
                f'{{"raw": {text}}} to set the raw value.',
            )
        if steps is not None and _plain_number(shown) is None:
            # An option name ("On", "Bell"): the step number is the usual reading.
            return {"raw": number, "read_as": "raw", "note": None}
        return {
            "raw": number,
            "read_as": "raw",
            "note": (
                f"{text} was read as a raw value, which Live shows as '{shown}'. To set "
                "what Live shows, send display text as a string (for example "
                f'"{text}" with its unit), or {{"raw": {text}}} to keep this reading.'
            ),
        }
    if display_raw is not None:
        return {
            "raw": display_raw,
            "read_as": "display",
            "note": (
                f"{text} is outside the raw range {low}..{high}, so it was read as display "
                f"text; Live shows '{_display(parameter, display_raw)}' at raw "
                f"{_format_number(display_raw)}."
            ),
        }
    hint = VALUE_HINT
    if steps is None and not unitless:
        # Name the display reading too, so the caller can see what they meant.
        candidate = _display_lookup(parameter, text)
        if candidate is not None:
            hint = (
                f"{VALUE_HINT} Live shows '{_display(parameter, candidate)}' at raw "
                f"{_format_number(candidate)}; to set that, send the display text as a "
                f'string, such as "{text}" with its unit.'
            )
    raise InvalidValue(f"value {number} is outside '{name}' range {low}..{high}", hint)


def _display_lookup(parameter, text):
    try:
        return value_for_display(parameter, text)
    except LiveOpsError:
        return None


def _format_number(number):
    return f"{number:g}"


def value_for_display(parameter, text):
    """Find the raw value whose display matches ``text``. Never writes."""

    name = _str(parameter.name)
    low, high = float(parameter.min), float(parameter.max)
    steps = _steps(parameter)
    if steps is not None:
        index = _match_step(text, steps)
        if index is not None:
            return low + index
        raise InvalidValue(
            f"'{text}' is not an option for '{name}'. "
            f"Options: {_list_texts(_option_names(steps))}",
            "Use one of the options listed, spelled as shown, or "
            '{"raw": <step>} with the step number (the first option is '
            f"{_format_number(low)}).",
        )

    target = parse_display_number(text)
    if target is not None:
        low_number = parse_display_number(_display(parameter, low))
        high_number = parse_display_number(_display(parameter, high))
        if None not in (low_number, high_number) and low_number != high_number:
            return _search_display(parameter, _display, low, high, target, text)

    # The ends do not show distinct numbers: the display is text ("1/8"), or
    # Live gives the same text for every value. Look at what Live shows
    # across the range and match the text against that.
    samples = _sample_displays(parameter, low, high)
    index = _match_step(text, [(None, shown) for _raw, shown in samples])
    if index is not None:
        return samples[index][0]
    raise _no_display_match(parameter, text, target, samples, low, high)


def _no_display_match(parameter, text, target, samples, low, high):
    name = _str(parameter.name)
    seen = [shown for _raw, shown in samples]
    lead = "" if target is not None else f"could not read a number from '{text}' for '{name}'. "
    if len(seen) == 1:
        return InvalidValue(
            f"{lead}'{name}' shows '{seen[0]}' for every value Live was asked about "
            f"(raw {low} to {high}), so display text cannot be matched. Live's "
            "str_for_value may only format the current value (as some plugins do), or "
            "the display may depend on another parameter such as a sync or mode switch. "
            f"Use a raw value between {low} and {high} instead.",
            RAW_VALUE_HINT,
        )
    return InvalidValue(
        f"{lead}no value of '{name}' shows '{text}'. Across raw {low} to {high} it shows: "
        f"{_list_texts(seen)}. Send one of those, or a raw value between {low} and {high}.",
        RAW_VALUE_HINT,
    )


def _steps(parameter):
    """``(option name, display text)`` per step of a stepped parameter, or None.

    Step ``i`` is raw ``min + i``. Option names come from ``value_items``
    when Live gives them; display text from ``str_for_value``. Returns None
    when the steps cannot be named, for example when ``str_for_value`` shows
    the same text for every step.
    """

    low, high = float(parameter.min), float(parameter.max)
    items = [str(item) for item in _tuple(_get(parameter, "value_items", ()))]
    quantized = bool(_get(parameter, "is_quantized", False))
    if quantized and items:
        return [(item, _display(parameter, low + i)) for i, item in enumerate(items)]
    if not (low.is_integer() and high.is_integer() and high > low):
        return None
    span = int(high - low)
    if quantized:
        if span > MAX_LISTED_STEPS:
            return None
    else:
        # A guess (issue #44): a small integer range whose half step shows the
        # text of a neighbouring step behaves like a chooser.
        if span < 2 or span > MAX_GUESSED_STEPS:
            return None
        half = _display(parameter, low + 0.5)
        if half not in (_display(parameter, low), _display(parameter, low + 1)):
            return None
    shown = [_display(parameter, low + i) for i in range(span + 1)]
    if len(set(shown)) < 2:
        return None
    return [(None, text) for text in shown]


def _option_names(steps):
    return [item if item is not None else shown for item, shown in steps]


def _match_step(text, steps):
    """Index of the step ``text`` names: exact text, then number, then prefix."""

    wanted = text.strip().lower()
    if not wanted:
        return None
    for index, names in enumerate(steps):
        if any(name is not None and name.strip().lower() == wanted for name in names):
            return index
    if _plain_number(text) is not None:
        return _match_step_number(text, steps)
    # "Auto" for a step Live shows as "A", or "Sp" for "Sparse"; only when
    # exactly one step fits.
    found = {
        index
        for index, names in enumerate(steps)
        for name in names
        if name is not None
        and name.strip()
        and (name.strip().lower().startswith(wanted) or wanted.startswith(name.strip().lower()))
    }
    return found.pop() if len(found) == 1 else None


def _match_step_number(text, steps):
    wanted = _plain_number(text)
    if wanted is None:
        return None
    for index, names in enumerate(steps):
        for name in names:
            shown = _plain_number(name) if name is not None else None
            if shown is not None and _numbers_match(wanted, shown):
                return index
    return None


_PLAIN = re.compile(r"^\s*([-+]?(?:\d+\.?\d*|\.\d+))\s*([a-z%]*)\s*$", re.IGNORECASE)


def _plain_number(text):
    """``(number, decimals, unit)`` when ``text`` is one number with an optional
    unit ("1.00", ".1", "10 ms", "50 %"), else None. "1/8" is not one."""

    match = _PLAIN.match(str(text))
    if not match:
        return None
    digits = match.group(1)
    decimals = len(digits.split(".")[1]) if "." in digits else 0
    return float(digits), decimals, match.group(2).lower()


def _numbers_match(wanted, shown):
    """Whether a typed number names a displayed one, at the display's resolution."""

    number, _decimals, unit = wanted
    shown_number, decimals, shown_unit = shown
    tolerance = 0.5 * 10 ** -decimals + 1e-9
    if unit and shown_unit and unit != shown_unit:
        if unit not in _UNIT_SCALE or shown_unit not in _UNIT_SCALE:
            return False
        scale = _UNIT_SCALE[shown_unit]
        return abs(number * _UNIT_SCALE[unit] - shown_number * scale) <= tolerance * scale
    return abs(number - shown_number) <= tolerance


def _number_agrees(shown, number):
    """Whether Live's text for raw ``number`` reads as that same number."""

    plain = _plain_number(shown)
    return plain is not None and _numbers_match((number, 0, ""), plain)


def _shows_plain_numbers(parameter, low, high):
    """Whether the display is a bare number with no unit at both ends."""

    for raw in (low, high):
        plain = _plain_number(_display(parameter, raw))
        if plain is None or plain[2]:
            return False
    return True


def _sample_displays(parameter, low, high):
    """Distinct display texts across the range, as ``(raw, text)`` in raw order.

    Samples every integer step when the range is integer and at most
    MAX_SAMPLED_STEPS wide, plus EVEN_SAMPLES evenly spaced points. Reads
    ``str_for_value`` only.
    """

    points = {low, high}
    if low.is_integer() and high.is_integer() and 0 < high - low <= MAX_SAMPLED_STEPS:
        points.update(low + i for i in range(int(high - low) + 1))
    if high > low:
        points.update(low + (high - low) * i / (EVEN_SAMPLES - 1) for i in range(EVEN_SAMPLES))
    seen = {}
    for raw in sorted(points):
        seen.setdefault(_display(parameter, raw), raw)
    return [(raw, text) for text, raw in seen.items()]


def _list_texts(texts):
    texts = list(texts)
    if len(texts) <= MAX_LISTED_TEXTS:
        return ", ".join(texts)
    head = ", ".join(texts[: MAX_LISTED_TEXTS - 1])
    return f"{head}, ... {texts[-1]} ({len(texts)} in all)"


def _search_display(parameter, reader, low, high, target, text):
    """Bisect for the raw value whose number display is ``target``.

    The caller has checked that both ends show distinct numbers.
    """

    def number(value):
        return parse_display_number(reader(parameter, value))

    low_number, high_number = number(low), number(high)
    rising = high_number >= low_number
    bottom, top = (low_number, high_number) if rising else (high_number, low_number)
    if target <= bottom or target >= top:
        edge = (low if rising else high) if target <= bottom else (high if rising else low)
        _check_display_match(parameter, reader, edge, target, text, low, high)
        return edge
    # Displays are rounded, so many raw values show the same number. Find the
    # span of raw values that display the target and aim for its middle.
    start = _first_raw_where(number, low, high, rising, lambda n: n >= target)
    stop = _first_raw_where(number, low, high, rising, lambda n: n > target)
    if number(start) == target and stop > start:
        result = (start + stop) / 2.0
    else:
        result = start
    if bool(_get(parameter, "is_quantized", False)):
        result = float(round(result))
    _check_display_match(parameter, reader, result, target, text, low, high)
    return result


def _check_display_match(parameter, reader, raw, target, text, low, high):
    # Guards against displays the bisection cannot follow, such as a parameter
    # whose numbers are not monotonic.
    shown = parse_display_number(reader(parameter, raw))
    if shown is None or math.isinf(target) or math.isinf(shown):
        return
    tolerance = max(abs(target) * 0.05, 0.051)
    if abs(shown - target) > tolerance:
        raise InvalidValue(
            f"could not find a value of '{_str(parameter.name)}' that shows '{text}'; "
            f"closest was '{reader(parameter, raw)}' (range '{reader(parameter, low)}' to "
            f"'{reader(parameter, high)}'). Use a raw value between {low} and {high} instead."
        )


def _first_raw_where(number, low, high, rising, predicate, steps=60):
    """Bisect for the first raw value whose display number satisfies predicate.

    ``rising`` says whether display numbers grow with the raw value; for a
    falling parameter the search runs from the high end.
    """

    for _ in range(steps):
        middle = (low + high) / 2.0
        shown = number(middle)
        if shown is None:
            break
        if predicate(shown) == rising:
            high = middle
        else:
            low = middle
    return high if rising else low


_NUMBER = re.compile(r"(-?inf|[-+]?\d*\.?\d+)\s*(khz|hz|ms|s|k)?(?![a-z])", re.IGNORECASE)
# Scale to a base unit so displays that switch unit ("850 ms" to "1.00 s",
# "999 Hz" to "1.00 kHz") still compare in order.
_UNIT_SCALE = {"k": 1000.0, "khz": 1000.0, "hz": 1.0, "ms": 0.001, "s": 1.0}
_PAN = re.compile(r"^\s*(\d*\.?\d+)\s*([LR])\s*$", re.IGNORECASE)


def parse_display_number(text):
    """Read a number from Live display text: ``-6.0 dB``, ``2.5 kHz``, ``850 ms``, ``25L``."""

    text = text.strip()
    if text.upper() == "C":
        return 0.0
    pan = _PAN.match(text)
    if pan:
        amount = float(pan.group(1))
        return -amount if pan.group(2).upper() == "L" else amount
    match = _NUMBER.search(text)
    if not match:
        return None
    raw = match.group(1).lower()
    if raw == "-inf":
        return -math.inf
    if raw == "inf":
        return math.inf
    number = float(raw)
    if match.group(2):
        number *= _UNIT_SCALE[match.group(2).lower()]
    return number


def _shown(parameter):
    return _display(parameter, float(parameter.value))


def _display(parameter, value):
    str_for_value = getattr(parameter, "str_for_value", None)
    if callable(str_for_value):
        try:
            return str(str_for_value(value))
        except Exception:
            pass
    return str(value)


# Payloads -----------------------------------------------------------------


def _track_payload(track, kind, index, return_names):
    mixer = track.mixer_device
    group = _get(track, "group_track")
    payload = {
        **_track_ref_payload(kind, index, track),
        "color_index": _get(track, "color_index"),
        "color": _hex_color(_get(track, "color")),
        "is_group": bool(_get(track, "is_foldable", False)),
        "group": _str(group.name) if group is not None else None,
        "routing": _routing_payload(track),
        "volume": _param_payload(mixer.volume, compact=True),
        "panning": _param_payload(mixer.panning, compact=True),
        "sends": [
            {"return": return_names[i] if i < len(return_names) else str(i),
             **_param_payload(send, compact=True)}
            for i, send in enumerate(_tuple(_get(mixer, "sends", ())))
        ],
        "devices": [_str(device.name) for device in _tuple(track.devices)],
    }
    if kind != "master":
        payload["mute"] = bool(_get(track, "mute", False))
        payload["solo"] = bool(_get(track, "solo", False))
    return payload


def _compact_track_payload(track, kind, index, return_names):
    mixer = track.mixer_device
    group = _get(track, "group_track")
    routing = _get(track, "output_routing_type")
    payload = {
        **_track_ref_payload(kind, index, track),
        "color": _hex_color(_get(track, "color")),
        "group": _str(group.name) if group is not None else None,
        "output": _str(_get(routing, "display_name", "")) if routing is not None else None,
        "volume": _shown(mixer.volume),
        "pan": _shown(mixer.panning),
        "sends": {
            (return_names[i] if i < len(return_names) else str(i)): _shown(send)
            for i, send in enumerate(_tuple(_get(mixer, "sends", ())))
        },
        "devices": [_str(device.name) for device in _tuple(track.devices)],
    }
    if bool(_get(track, "is_foldable", False)):
        payload["is_group"] = True
    if kind != "master":
        if bool(_get(track, "mute", False)):
            payload["mute"] = True
        if bool(_get(track, "solo", False)):
            payload["solo"] = True
    return payload


def _track_ref_payload(kind, index, track):
    return {"kind": kind, "index": index, "name": _str(track.name)}


def _routing_payload(track):
    payload = {}
    for key in ("output_routing_type", "output_routing_channel"):
        value = _get(track, key)
        payload[key] = _str(_get(value, "display_name", "")) if value is not None else None
    available = _get(track, "available_output_routing_types", ())
    payload["available_output_routing_types"] = [
        _str(_get(item, "display_name", "")) for item in _tuple(available)
    ]
    return payload


def _device_payload(device, index, include_parameters, track, top_index, tail=(), depth=0):
    """``track``/``top_index``/``tail`` locate the device so its printed
    ``path`` can be checked to resolve back to it (None if it cannot)."""

    payload = {
        "index": index,
        "name": _str(device.name),
        "path": _printable_path(track, top_index, list(tail), device),
        "class_name": _str(_get(device, "class_name", "")),
        "class_display_name": _str(_get(device, "class_display_name", "")),
        "is_active": bool(_get(device, "is_active", True)),
    }
    if bool(_get(device, "can_have_chains", False)):
        context = (include_parameters, track, top_index, depth)
        payload["chains"] = _chains_payload(_get(device, "chains", ()), tail, *context)
        return_chains = _tuple(_get(device, "return_chains", ()))
        if return_chains:
            payload["return_chains"] = _chains_payload(
                return_chains, (*tail, "returns"), *context
            )
    if include_parameters:
        payload["parameters"] = [
            {"index": i, **_param_payload(parameter)}
            for i, parameter in enumerate(_tuple(device.parameters))
        ]
    return payload


def _chains_payload(chains, tail, include_parameters, track, top_index, depth):
    chains = _tuple(chains)
    if depth >= MAX_RACK_DEPTH:
        return [{"name": _str(chain.name), "truncated": True} for chain in chains]
    result = []
    for chain_index, chain in enumerate(chains):
        chain_tail = (*tail, _path_segment(chains, chain_index))
        devices = _tuple(chain.devices)
        result.append(
            {
                "name": _str(chain.name),
                "devices": [
                    _device_payload(
                        device,
                        i,
                        include_parameters,
                        track,
                        top_index,
                        (*chain_tail, _path_segment(devices, i)),
                        depth + 1,
                    )
                    for i, device in enumerate(devices)
                ],
            }
        )
    return result


def _param_payload(parameter, compact=False):
    value = float(parameter.value)
    payload = {"value": value, "display": _display(parameter, value)}
    if compact:
        return payload
    payload = {"name": _str(parameter.name), **payload}
    payload["min"] = float(parameter.min)
    payload["max"] = float(parameter.max)
    steps = _steps(parameter)
    if steps is not None:
        # Option names, or each step's display text when Live lists none
        # (Glue Compressor Release, issue #44).
        payload["options"] = _option_names(steps)
    elif bool(_get(parameter, "is_quantized", False)):
        payload["options"] = [str(item) for item in _tuple(_get(parameter, "value_items", ()))]
    return payload


# Helpers ------------------------------------------------------------------


def _without_return_prefix(name, return_index):
    """Drop a leading "A-" from a name for return A.

    Live shows a return's letter in front of its name, so storing "A-Room" on
    return A shows "A-A-Room" (seen in Live 12.4.16, issue #15). A different
    letter ("B-Room" on return A) is kept as the user typed it.
    """

    letter = chr(ord("A") + return_index) if return_index < 26 else None
    if letter and len(name) > 2 and name[:2].upper() == f"{letter}-":
        return name[2:].lstrip() or name
    return name


def _locate_track(song, target):
    if target is None:
        raise NotFound("no track is selected", SELECTION_HINT)
    for kind, index, track in _all_tracks(song):
        if _same(track, target):
            return kind, index, track
    raise NotFound(f"selected track '{_str(_get(target, 'name'))}' was not found", SELECTION_HINT)


def _is_rack(device):
    return bool(_get(device, "can_have_chains", False)) and _str(
        _get(device, "class_name", "")
    ).endswith("GroupDevice")


def _selected_or_first_rack(track, devices):
    selected = _get(_get(track, "view"), "selected_device")
    for device_index, device in enumerate(devices):
        if _same(device, selected) and _is_rack(device):
            return device_index, device, "selected_device"
    for device_index, device in enumerate(devices):
        if _is_rack(device):
            return device_index, device, "first_rack_on_track"
    raise NotFound(f"track '{_str(track.name)}' has no Rack", SELECTION_HINT)


def _macro_parameters(device):
    # parameters[0] is "Device On"; the macros follow in order. Live 11+ reports
    # one macros_mapped entry per macro, which tells how many there are.
    parameters = _tuple(device.parameters)[1:]
    mapped = _tuple(_get(device, "macros_mapped", None))
    if mapped:
        return parameters[: len(mapped)]
    return parameters[:MAX_RACK_MACROS]


def _all_tracks(song):
    items = [("track", i, t) for i, t in enumerate(_tuple(song.tracks))]
    items.extend(("return", i, t) for i, t in enumerate(_tuple(song.return_tracks)))
    items.append(("master", 0, song.master_track))
    return items


def _match_routing(available, wanted, label):
    options = _tuple(available)
    wanted_text = str(wanted).strip().lower()
    for option in options:
        if _str(_get(option, "display_name", "")).lower() == wanted_text:
            return option
    names = ", ".join(_str(_get(option, "display_name", "")) for option in options)
    raise NotFound(
        f"no {label} '{wanted}'. Available: {names}",
        "Use one of the names listed, or list_tracks with detail 'full' for every choice.",
    )


def _resolve_send(ref, return_names, send_count):
    if isinstance(ref, int) or (isinstance(ref, str) and ref.isdigit()):
        send_index = int(ref)
    elif isinstance(ref, str) and len(ref) == 1 and ref.isalpha():
        send_index = ord(ref.upper()) - ord("A")
    else:
        lowered = str(ref).lower()
        matches = [i for i, name in enumerate(return_names) if name.lower() == lowered]
        if not matches:
            raise NotFound(
                f"no return track '{ref}'. Returns: {', '.join(return_names)}", TRACK_HINT
            )
        send_index = matches[0]
    if not 0 <= send_index < send_count:
        raise NotFound(f"send {ref} is out of range ({send_count} sends)", TRACK_HINT)
    return send_index


def _parse_color(value):
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    text = str(value).strip().lstrip("#")
    if not re.fullmatch(r"[0-9a-fA-F]{6}", text):
        raise InvalidValue(f"color must be an RGB integer or '#RRGGBB', got '{value}'")
    return int(text, 16)


def _hex_color(value):
    if value is None:
        return None
    try:
        return f"#{int(value):06X}"
    except (TypeError, ValueError):
        return None


def _required(params, key):
    if params.get(key) is None:
        raise InvalidValue(f"missing required parameter '{key}'")
    return params[key]


def _int_or_error(text, label):
    try:
        return int(text)
    except (TypeError, ValueError) as exc:
        raise InvalidValue(f"{label} must be an integer, got '{text}'") from exc


def _get(target, name, default=None):
    try:
        return getattr(target, name, default)
    except Exception:
        return default


def _str(value):
    return "" if value is None else str(value)


def _same(a, b):
    """Whether two LOM references are the same Live object.

    Live hands out a new Python wrapper each time a property is read, so two
    reads of one device are not ``is``-identical; ``_live_ptr`` names the
    object underneath.
    """

    if a is b:
        return True
    pointer = _get(a, "_live_ptr")
    return pointer is not None and pointer == _get(b, "_live_ptr")


def _tuple(value):
    if value is None:
        return ()
    if isinstance(value, tuple):
        return value
    try:
        return tuple(value)
    except TypeError:
        return (value,)


_HANDLERS = {
    "ableton.list_tracks": list_tracks,
    "ableton.list_devices": list_devices,
    "ableton.get_selected_rack_macros": get_selected_rack_macros,
    "ableton.set_device_parameter": set_device_parameter,
    "ableton.set_track_output_routing": set_track_output_routing,
    "ableton.set_track_properties": set_track_properties,
    "ableton.set_mixer": set_mixer,
    "ableton.insert_device": insert_device,
    "ableton.create_return_track": create_return_track,
    "ableton.delete_device": delete_device,
    "ableton.batch": batch,
    "ableton.undo": undo,
}
