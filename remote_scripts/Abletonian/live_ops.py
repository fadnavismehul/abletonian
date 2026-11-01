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
    """Raised when a request cannot be applied to the open Live Set."""


def handle(song, method, params):
    """Dispatch one ``ableton.*`` method. Returns None for unknown methods."""

    handler = _HANDLERS.get(method)
    if handler is None:
        return None
    return handler(song, params)


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
        raise LiveOpsError(f"detail must be 'full' or 'compact', got '{detail}'")
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
                    _device_payload(device, device_index, include_parameters)
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
    device_index, device = resolve_device(track, _required(params, "device"))
    parameter = resolve_parameter(device, _required(params, "parameter"))
    before = _param_payload(parameter)
    set_parameter_value(parameter, _required(params, "value"))
    return {
        "track": _track_ref_payload(kind, index, track),
        "device": {"index": device_index, "name": _str(device.name)},
        "before": before,
        "after": _param_payload(parameter),
    }


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
        except LiveOpsError:
            track.output_routing_type = previous_type
            raise
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
    position = params.get("index")
    insert = getattr(track, "insert_device", None)
    if not callable(insert):
        raise LiveOpsError("Track.insert_device is unavailable; it needs Live 12.3 or later")
    devices_before = _tuple(track.devices)
    count_before = len(devices_before)
    if position is None:
        position = count_before
    position = int(position)
    if position < 0 or position > count_before:
        raise LiveOpsError(
            f"device index {position} is out of range for '{_str(track.name)}' "
            f"(0..{count_before})"
        )
    try:
        insert(device_name, position)
    except Exception as exc:
        raise LiveOpsError(f"Live could not insert '{device_name}': {exc}") from exc
    devices = _tuple(track.devices)
    if len(devices) != count_before + 1:
        raise LiveOpsError(f"Live did not report a new device after inserting '{device_name}'")
    # Live may place the device elsewhere (device order rules on MIDI tracks),
    # so find it by identity rather than trusting the requested position.
    new_positions = [
        i for i, device in enumerate(devices) if not any(device is old for old in devices_before)
    ]
    if len(new_positions) == 1:
        position = new_positions[0]
    device = devices[position]
    changed = []
    try:
        for parameter_ref, value in (params.get("parameters") or {}).items():
            parameter = resolve_parameter(device, parameter_ref)
            set_parameter_value(parameter, value)
            changed.append(_param_payload(parameter))
    except Exception as exc:
        # Leave the track as it was rather than with a half-configured device.
        delete = getattr(track, "delete_device", None)
        if callable(delete):
            delete(position)
            raise LiveOpsError(f"{exc}. The new '{device_name}' was removed again.") from exc
        raise
    return {
        "track": _track_ref_payload(kind, index, track),
        "device": _device_payload(device, position, include_parameters=False),
        "parameters_set": changed,
    }


def create_return_track(song, params):
    """Add a return track at the end (``Song.create_return_track``). Additive."""

    create = getattr(song, "create_return_track", None)
    if not callable(create):
        raise LiveOpsError("this version of Live cannot create return tracks from a script")
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


def delete_device(song, params):
    """Delete a device. Destructive: without ``confirm=true`` it only previews."""

    kind, index, track = resolve_track(song, _required(params, "track"))
    device_index, device = resolve_device(track, _required(params, "device"))
    preview = {
        "track": _track_ref_payload(kind, index, track),
        "device": {
            "index": device_index,
            "name": _str(device.name),
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
    track.delete_device(device_index)
    return {"deleted": True, **preview, "undo": "Live's Undo restores the device and settings."}


def batch(song, params):
    operations = _required(params, "operations")
    if not isinstance(operations, list) or not operations:
        raise LiveOpsError("batch operations must be a non-empty list")
    for position, operation in enumerate(operations):
        method = operation.get("method") if isinstance(operation, dict) else None
        if method not in BATCHABLE_METHODS:
            raise LiveOpsError(
                f"operation {position} has unsupported method '{method}'; "
                f"allowed: {', '.join(BATCHABLE_METHODS)}"
            )

    results = []
    begin = getattr(song, "begin_undo_step", None)
    end = getattr(song, "end_undo_step", None)
    grouped_undo = callable(begin) and callable(end)
    if grouped_undo:
        begin()
    try:
        for position, operation in enumerate(operations):
            try:
                results.append(_HANDLERS[operation["method"]](song, operation.get("params", {})))
            except Exception as exc:
                return {
                    "completed": results,
                    "failed": {"index": position, "operation": operation, "error": str(exc)},
                    "grouped_undo": grouped_undo,
                }
    finally:
        if grouped_undo:
            end()
    return {"completed": results, "failed": None, "grouped_undo": grouped_undo}


def undo(song, params):
    if not bool(getattr(song, "can_undo", True)):
        raise LiveOpsError("Live has nothing to undo")
    song.undo()
    return {"undone": True}


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
        raise LiveOpsError(f"track index {ref} is out of range (0..{len(tracks) - 1})")
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
        raise LiveOpsError(f"return index {return_index} is out of range")
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
    raise LiveOpsError(f"no track named '{text}'. Tracks: {names}")


def resolve_device(track, ref):
    devices = _tuple(track.devices)
    if isinstance(ref, int) and not isinstance(ref, bool):
        if 0 <= ref < len(devices):
            return ref, devices[ref]
        raise LiveOpsError(
            f"device index {ref} is out of range on '{_str(track.name)}' ({len(devices)} devices)"
        )
    text = str(ref)
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
    raise LiveOpsError(f"no device named '{text}' on '{_str(track.name)}'. Devices: {names}")


def resolve_parameter(device, ref):
    parameters = _tuple(device.parameters)
    if isinstance(ref, int) and not isinstance(ref, bool):
        if 0 <= ref < len(parameters):
            return parameters[ref]
        raise LiveOpsError(f"parameter index {ref} is out of range on '{_str(device.name)}'")
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
    raise LiveOpsError(f"no parameter '{ref}' on '{_str(device.name)}'. Parameters: {names}")


# Parameter values ---------------------------------------------------------


def set_parameter_value(parameter, value):
    """Set a raw number, or a display string such as ``"-6 dB"`` or ``"25L"``."""

    parameter.value = _raw_value(parameter, value)


def _raw_value(parameter, value):
    """Validate ``value`` for ``parameter`` and return the raw value to set."""

    if not bool(_get(parameter, "is_enabled", True)):
        raise LiveOpsError(
            f"parameter '{_str(parameter.name)}' is not editable right now "
            "(it may be controlled by a macro or modulation)"
        )
    if isinstance(value, bool):
        value = float(value)
    if isinstance(value, (int, float)):
        raw = float(value)
    else:
        raw = value_for_display(parameter, str(value))
    low, high = float(parameter.min), float(parameter.max)
    if raw < low or raw > high:
        raise LiveOpsError(
            f"value {raw} is outside '{_str(parameter.name)}' range {low}..{high}"
        )
    return raw


def value_for_display(parameter, text):
    """Find the raw value whose display matches ``text``."""

    items = [str(item) for item in _tuple(_get(parameter, "value_items", ()))]
    quantized = bool(_get(parameter, "is_quantized", False))
    if quantized and items:
        for item_index, item in enumerate(items):
            if item.lower() == text.strip().lower():
                return float(parameter.min) + item_index
        raise LiveOpsError(
            f"'{text}' is not an option for '{_str(parameter.name)}'. Options: {', '.join(items)}"
        )

    target = parse_display_number(text)
    if target is None:
        raise LiveOpsError(f"could not read a number from '{text}'")
    low, high = float(parameter.min), float(parameter.max)
    low_number = _display_number(parameter, low)
    high_number = _display_number(parameter, high)
    if low_number is None or high_number is None:
        raise LiveOpsError(f"'{_str(parameter.name)}' does not show numeric values")
    rising = high_number >= low_number
    bottom, top = (low_number, high_number) if rising else (high_number, low_number)
    if target <= bottom or target >= top:
        edge = (low if rising else high) if target <= bottom else (high if rising else low)
        _check_display_match(parameter, edge, target, text)
        return edge
    # Displays are rounded, so many raw values show the same number. Find the
    # span of raw values that display the target and aim for its middle.
    start = _first_raw_where(parameter, low, high, rising, lambda n: n >= target)
    stop = _first_raw_where(parameter, low, high, rising, lambda n: n > target)
    if _display_number(parameter, start) == target and stop > start:
        result = (start + stop) / 2.0
    else:
        result = start
    if quantized:
        result = float(round(result))
    _check_display_match(parameter, result, target, text)
    return result


def _check_display_match(parameter, raw, target, text):
    # Guards against displays the bisection cannot follow, such as a parameter
    # whose numbers are not monotonic.
    shown = _display_number(parameter, raw)
    if shown is None or math.isinf(target) or math.isinf(shown):
        return
    tolerance = max(abs(target) * 0.05, 0.051)
    if abs(shown - target) > tolerance:
        raise LiveOpsError(
            f"could not find a value of '{_str(parameter.name)}' that shows '{text}'; "
            f"closest was '{_display(parameter, raw)}'. Use a raw value instead."
        )


def _first_raw_where(parameter, low, high, rising, predicate):
    """Bisect for the first raw value whose display number satisfies predicate.

    ``rising`` says whether display numbers grow with the raw value; for a
    falling parameter the search runs from the high end.
    """

    for _ in range(60):
        middle = (low + high) / 2.0
        number = _display_number(parameter, middle)
        if number is None:
            break
        if predicate(number) == rising:
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


def _display_number(parameter, value):
    return parse_display_number(_display(parameter, value))


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


def _device_payload(device, index, include_parameters):
    payload = {
        "index": index,
        "name": _str(device.name),
        "class_name": _str(_get(device, "class_name", "")),
        "class_display_name": _str(_get(device, "class_display_name", "")),
        "is_active": bool(_get(device, "is_active", True)),
    }
    if bool(_get(device, "can_have_chains", False)):
        payload["chains"] = [
            {"name": _str(chain.name), "devices": [_str(d.name) for d in _tuple(chain.devices)]}
            for chain in _tuple(_get(device, "chains", ()))
        ]
    if include_parameters:
        payload["parameters"] = [
            {"index": i, **_param_payload(parameter)}
            for i, parameter in enumerate(_tuple(device.parameters))
        ]
    return payload


def _param_payload(parameter, compact=False):
    value = float(parameter.value)
    payload = {"value": value, "display": _display(parameter, value)}
    if compact:
        return payload
    payload = {"name": _str(parameter.name), **payload}
    payload["min"] = float(parameter.min)
    payload["max"] = float(parameter.max)
    if bool(_get(parameter, "is_quantized", False)):
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
        raise LiveOpsError("no track is selected")
    for kind, index, track in _all_tracks(song):
        if track is target:
            return kind, index, track
    raise LiveOpsError(f"selected track '{_str(_get(target, 'name'))}' was not found")


def _is_rack(device):
    return bool(_get(device, "can_have_chains", False)) and _str(
        _get(device, "class_name", "")
    ).endswith("GroupDevice")


def _selected_or_first_rack(track, devices):
    selected = _get(_get(track, "view"), "selected_device")
    for device_index, device in enumerate(devices):
        if device is selected and _is_rack(device):
            return device_index, device, "selected_device"
    for device_index, device in enumerate(devices):
        if _is_rack(device):
            return device_index, device, "first_rack_on_track"
    raise LiveOpsError(f"track '{_str(track.name)}' has no Rack")


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
    raise LiveOpsError(f"no {label} '{wanted}'. Available: {names}")


def _resolve_send(ref, return_names, send_count):
    if isinstance(ref, int) or (isinstance(ref, str) and ref.isdigit()):
        send_index = int(ref)
    elif isinstance(ref, str) and len(ref) == 1 and ref.isalpha():
        send_index = ord(ref.upper()) - ord("A")
    else:
        lowered = str(ref).lower()
        matches = [i for i, name in enumerate(return_names) if name.lower() == lowered]
        if not matches:
            raise LiveOpsError(f"no return track '{ref}'. Returns: {', '.join(return_names)}")
        send_index = matches[0]
    if not 0 <= send_index < send_count:
        raise LiveOpsError(f"send {ref} is out of range ({send_count} sends)")
    return send_index


def _parse_color(value):
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    text = str(value).strip().lstrip("#")
    if not re.fullmatch(r"[0-9a-fA-F]{6}", text):
        raise LiveOpsError(f"color must be an RGB integer or '#RRGGBB', got '{value}'")
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
        raise LiveOpsError(f"missing required parameter '{key}'")
    return params[key]


def _int_or_error(text, label):
    try:
        return int(text)
    except (TypeError, ValueError) as exc:
        raise LiveOpsError(f"{label} must be an integer, got '{text}'") from exc


def _get(target, name, default=None):
    try:
        return getattr(target, name, default)
    except Exception:
        return default


def _str(value):
    return "" if value is None else str(value)


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
