"""Macro Cockpit specs generated from a selected Ableton Rack (RFC 0002).

See docs/rfcs/0002-selected-rack-macro-cockpit.md.

A cockpit is a declarative spec, not a frontend. Renderers (text today; a
local web panel, MCP Apps, or an in-Live surface later) consume the spec.

V1 is read-only and conservative:

- it uses only the rack's existing macros and keeps each macro's index and
  name as Live reports them,
- it never invents mappings; unmapped macros are left out and listed,
- grouping is rule-based on macro names, and anything ambiguous stays in
  ``Other`` or ``Inspect``,
- generated text is marked as generated.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

SCHEMA_VERSION = "abletonian.macro_cockpit.v1"
MAX_MACROS = 16
CONTROL_CAPABILITY = "set_rack_macro_value"

# (id, label, description, keywords). A keyword matches a word in the macro
# name that starts with it; keywords of two letters must match a whole word.
GROUP_RULES: tuple[tuple[str, str, str, tuple[str, ...]], ...] = (
    (
        "tone",
        "Tone",
        "Brightness, colour, body, and saturation.",
        (
            "tone", "bright", "dark", "filter", "cutoff", "freq", "eq", "colo", "warm",
            "drive", "satur", "distort", "dirt", "crunch", "body", "timbre", "reso",
            "lp", "hp", "lowpass", "highpass", "air", "bite", "fold", "crush",
        ),
    ),
    (
        "dynamics",
        "Dynamics",
        "Level, punch, envelope, and compression.",
        (
            "gain", "volume", "vol", "level", "comp", "punch", "attack", "decay",
            "release", "sustain", "env", "transient", "glue", "velocity", "dyn",
            "squash", "snap", "thump", "tail",
        ),
    ),
    (
        "movement",
        "Movement",
        "Modulation and motion over time.",
        (
            "lfo", "rate", "mod", "wobble", "chorus", "phase", "flange", "trem",
            "vibrato", "speed", "motion", "move", "sweep", "depth", "swing", "groove",
            "shuffle", "random", "drift",
        ),
    ),
    (
        "space",
        "Space",
        "Reverb, delay, and stereo width.",
        (
            "reverb", "verb", "delay", "echo", "space", "room", "hall", "width",
            "wide", "stereo", "pan", "size", "feedback", "ambien", "shimmer",
        ),
    ),
    (
        "utility",
        "Utility",
        "Mix balance, output, and tuning.",
        (
            "dry", "wet", "mix", "blend", "output", "out", "input", "trim", "tune",
            "pitch", "transpose", "semi", "fine",
        ),
    ),
)
OTHER_GROUP = ("other", "Other", "Named macros that do not fit a group by name.")
INSPECT_GROUP = (
    "inspect",
    "Inspect",
    "Macros still named 'Macro N' in Live. Check what they control before relying on them.",
)
_DEFAULT_MACRO_NAME = re.compile(r"^Macro \d+$")


class CockpitError(ValueError):
    """Raised when rack data or a stored spec is not a valid cockpit."""


@dataclass(frozen=True)
class MacroCockpitControl:
    """One control in a cockpit, backed by exactly one existing rack macro."""

    id: str
    source_macro_index: int
    source_name: str
    original_name: str
    label: str
    value: float
    min: float
    max: float
    display: str
    is_mapped: bool | None
    description: str | None = None
    style: str = "knob"
    risk: str = "live_parameter"

    @property
    def normalized_value(self) -> float:
        span = self.max - self.min
        return 0.0 if span <= 0 else (self.value - self.min) / span

    def to_wire(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "source_macro_index": self.source_macro_index,
            "source_name": self.source_name,
            "original_name": self.original_name,
            "label": self.label,
            "description": self.description,
            "value": self.value,
            "min": self.min,
            "max": self.max,
            "normalized_value": round(self.normalized_value, 6),
            "display": self.display,
            "is_mapped": self.is_mapped,
            "style": self.style,
            "risk": self.risk,
        }

    @classmethod
    def from_wire(cls, data: Any) -> MacroCockpitControl:
        data = _require_dict(data, "control")
        return cls(
            id=_require_str(data, "id"),
            source_macro_index=_require_macro_index(data.get("source_macro_index")),
            source_name=_require_str(data, "source_name"),
            original_name=_require_str(data, "original_name"),
            label=_require_str(data, "label"),
            value=_require_number(data, "value"),
            min=_require_number(data, "min"),
            max=_require_number(data, "max"),
            display=str(data.get("display", "")),
            is_mapped=_optional_bool(data.get("is_mapped")),
            description=_optional_str(data.get("description")),
            style=str(data.get("style", "knob")),
            risk=str(data.get("risk", "live_parameter")),
        )


@dataclass(frozen=True)
class MacroCockpitGroup:
    """A labelled set of controls. Descriptions are generated, not from Live."""

    id: str
    label: str
    description: str
    controls: tuple[str, ...]

    def to_wire(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "label": self.label,
            "description": self.description,
            "description_source": "generated",
            "controls": list(self.controls),
        }

    @classmethod
    def from_wire(cls, data: Any) -> MacroCockpitGroup:
        data = _require_dict(data, "group")
        controls = data.get("controls")
        if not isinstance(controls, list) or not all(isinstance(c, str) for c in controls):
            raise CockpitError("group 'controls' must be a list of control ids")
        return cls(
            id=_require_str(data, "id"),
            label=_require_str(data, "label"),
            description=str(data.get("description", "")),
            controls=tuple(controls),
        )


@dataclass(frozen=True)
class MacroCockpitSpec:
    """An interface-neutral Macro Cockpit."""

    id: str
    title: str
    created_at: str
    source: dict[str, Any]
    permissions: dict[str, bool]
    connection: str
    groups: tuple[MacroCockpitGroup, ...]
    controls: tuple[MacroCockpitControl, ...]
    omitted_macros: tuple[dict[str, Any], ...] = ()
    warnings: tuple[str, ...] = ()
    mode: str = "temporary"
    renderer_hints: dict[str, Any] = field(
        default_factory=lambda: {
            "density": "compact",
            "primary_layout": "grouped_controls",
            "show_source_context": True,
        }
    )

    def __post_init__(self) -> None:
        _check_structure(self)

    def control(self, control_id: str) -> MacroCockpitControl:
        for control in self.controls:
            if control.id == control_id:
                return control
        raise KeyError(control_id)

    def to_wire(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "schema_version": SCHEMA_VERSION,
            "title": self.title,
            "mode": self.mode,
            "created_at": self.created_at,
            "source": dict(self.source),
            "permissions": dict(self.permissions),
            "connection": self.connection,
            "groups": [group.to_wire() for group in self.groups],
            "controls": [control.to_wire() for control in self.controls],
            "omitted_macros": [dict(item) for item in self.omitted_macros],
            "warnings": list(self.warnings),
            "renderer_hints": dict(self.renderer_hints),
        }

    @classmethod
    def from_wire(cls, data: Any) -> MacroCockpitSpec:
        """Load and validate a spec, for example from a saved sidecar."""

        data = _require_dict(data, "cockpit")
        if data.get("schema_version") != SCHEMA_VERSION:
            raise CockpitError(
                f"unsupported cockpit schema_version {data.get('schema_version')!r}; "
                f"expected {SCHEMA_VERSION!r}"
            )
        groups = data.get("groups")
        controls = data.get("controls")
        if not isinstance(groups, list) or not isinstance(controls, list):
            raise CockpitError("cockpit 'groups' and 'controls' must be lists")
        permissions = _require_dict(data.get("permissions"), "permissions")
        return cls(
            id=_require_str(data, "id"),
            title=_require_str(data, "title"),
            mode=_require_str(data, "mode"),
            created_at=_require_str(data, "created_at"),
            source=_require_dict(data.get("source"), "source"),
            permissions={str(k): bool(v) for k, v in permissions.items()},
            connection=_require_str(data, "connection"),
            groups=tuple(MacroCockpitGroup.from_wire(group) for group in groups),
            controls=tuple(MacroCockpitControl.from_wire(control) for control in controls),
            omitted_macros=tuple(
                _require_dict(item, "omitted macro") for item in data.get("omitted_macros", [])
            ),
            warnings=tuple(str(item) for item in data.get("warnings", [])),
            renderer_hints=_require_dict(data.get("renderer_hints", {}), "renderer_hints"),
        )


def generate_macro_cockpit(
    rack: dict[str, Any],
    health: dict[str, Any] | None = None,
    created_at: str | None = None,
) -> MacroCockpitSpec:
    """Build a cockpit from an ``ableton.get_selected_rack_macros`` result.

    ``health`` is the adapter's ``daw.health`` result, used for the Live
    version and capabilities. The rack payload is untrusted and validated.
    """

    rack = _require_dict(rack, "rack")
    track = _require_dict(rack.get("track"), "track")
    device = _require_dict(rack.get("device"), "device")
    raw_macros = rack.get("macros")
    if not isinstance(raw_macros, list):
        raise CockpitError("rack 'macros' must be a list")
    if len(raw_macros) > MAX_MACROS:
        raise CockpitError(f"rack reported {len(raw_macros)} macros; at most {MAX_MACROS}")
    health = health or {}
    capabilities = health.get("capabilities") or []

    controls: list[MacroCockpitControl] = []
    omitted: list[dict[str, Any]] = []
    seen_indexes: set[int] = set()
    for raw in raw_macros:
        macro = _require_dict(raw, "macro")
        index = _require_macro_index(macro.get("index"))
        if index in seen_indexes:
            raise CockpitError(f"rack reported macro {index} twice")
        seen_indexes.add(index)
        name = _require_str(macro, "name")
        is_mapped = _optional_bool(macro.get("is_mapped"))
        if is_mapped is False:
            omitted.append({"source_macro_index": index, "source_name": name,
                            "reason": "not mapped to any parameter"})
            continue
        original_name = str(macro.get("original_name") or f"Macro {index}")
        controls.append(
            MacroCockpitControl(
                id=f"macro-{index}",
                source_macro_index=index,
                source_name=name,
                original_name=original_name,
                label=name,
                value=_require_number(macro, "value"),
                min=_require_number(macro, "min"),
                max=_require_number(macro, "max"),
                display=str(macro.get("display", "")),
                is_mapped=is_mapped,
            )
        )

    groups = _group_controls(controls)
    warnings: list[str] = []
    if not controls:
        warnings.append(
            "This rack has no mapped macros, so the cockpit has no controls. "
            "Map parameters to macros in Live, then generate it again."
        )
    if rack.get("selection") == "first_rack_on_track":
        warnings.append(
            f"The selected device is not a Rack; used '{device.get('name')}', "
            "the first Rack on the track."
        )
    if any(control.is_mapped is None for control in controls):
        warnings.append("The adapter did not report which macros are mapped; all are shown.")

    fingerprint = rack_fingerprint(rack)
    adapter_type = str(health.get("adapter_type", "unknown"))
    source = {
        "target_daw": str(health.get("target_daw", "ableton")),
        "live_version": str(health.get("live_version", "unknown")),
        "adapter_type": adapter_type,
        "adapter_version": str(health.get("adapter_version", "unknown")),
        "track_kind": str(track.get("kind", "track")),
        "track_index": track.get("index"),
        "track_name": str(track.get("name", "")),
        "device_index": device.get("index"),
        "device_name": str(device.get("name", "")),
        "device_class_name": str(device.get("class_name", "")),
        "device_type": str(device.get("type", "rack")),
        "selection": str(rack.get("selection", "unknown")),
        "fingerprint": fingerprint,
    }
    can_control = CONTROL_CAPABILITY in capabilities
    return MacroCockpitSpec(
        id=f"macro-cockpit-{_slug(source['device_name'])}-{fingerprint[:8]}",
        title=f"{source['device_name'] or 'Rack'} Macro Cockpit",
        created_at=created_at or datetime.now(timezone.utc).isoformat(timespec="seconds"),
        source=source,
        permissions={
            "read_macros": True,
            "control_macro_values": can_control,
            "save_sidecar": True,
        },
        connection=(
            "simulated" if adapter_type == "fake" else "connected" if can_control else "read_only"
        ),
        groups=groups,
        controls=tuple(controls),
        omitted_macros=tuple(omitted),
        warnings=tuple(warnings),
    )


def rack_fingerprint(rack: dict[str, Any]) -> str:
    """Hash the rack's identity and macro layout, not its current values.

    A saved cockpit whose fingerprint differs from the selected rack's is stale.
    """

    device = rack.get("device") or {}
    identity = {
        "class_name": device.get("class_name"),
        "name": device.get("name"),
        "chain_names": device.get("chain_names", []),
        "macros": [
            [m.get("index"), m.get("original_name"), m.get("name"), m.get("is_mapped")]
            for m in rack.get("macros", [])
            if isinstance(m, dict)
        ],
    }
    encoded = json.dumps(identity, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()[:16]


def render_cockpit_text(spec: MacroCockpitSpec) -> str:
    """Plain-text fallback for hosts without an interactive renderer."""

    source = spec.source
    connection = {
        "read_only": "read-only preview (controls cannot move Live yet)",
        "connected": "connected to Live",
        "simulated": "simulated (fake adapter, not Live)",
    }.get(spec.connection, spec.connection)
    lines = [
        spec.title,
        f"Track: {source.get('track_name')} | Device: {source.get('device_name')} "
        f"({source.get('device_type')}) | Live {source.get('live_version')}",
        f"Status: {connection}; {spec.mode}, not saved",
    ]
    for group in spec.groups:
        lines.append("")
        lines.append(f"{group.label} - {group.description}")
        for control_id in group.controls:
            control = spec.control(control_id)
            renamed = (
                f" (was {control.original_name})"
                if control.original_name != control.source_name
                and _DEFAULT_MACRO_NAME.match(control.original_name)
                and not _DEFAULT_MACRO_NAME.match(control.source_name)
                else ""
            )
            display = control.display or f"{control.value:g}"
            lines.append(
                f"  [{control.source_macro_index:>2}] {control.label}{renamed}: {display} "
                f"{_meter(control.normalized_value)}"
            )
    if spec.omitted_macros:
        lines.append("")
        names = ", ".join(
            f"{m['source_macro_index']} {m['source_name']}" for m in spec.omitted_macros
        )
        lines.append(f"Left out (unmapped): {names}")
    for warning in spec.warnings:
        lines.append(f"Note: {warning}")
    return "\n".join(lines)


# Helpers ------------------------------------------------------------------


def _group_controls(controls: list[MacroCockpitControl]) -> tuple[MacroCockpitGroup, ...]:
    members: dict[str, list[str]] = {}
    for control in controls:
        members.setdefault(_group_for(control), []).append(control.id)
    ordered = [*GROUP_RULES, (*OTHER_GROUP, ()), (*INSPECT_GROUP, ())]
    return tuple(
        MacroCockpitGroup(id=gid, label=label, description=description,
                          controls=tuple(members[gid]))
        for gid, label, description, _keywords in ordered
        if members.get(gid)
    )


def _group_for(control: MacroCockpitControl) -> str:
    if _DEFAULT_MACRO_NAME.match(control.source_name.strip()):
        return INSPECT_GROUP[0]
    words = re.findall(r"[a-z]+", control.source_name.lower())
    scores: dict[str, int] = {}
    for gid, _label, _description, keywords in GROUP_RULES:
        score = sum(1 for word in words if any(_keyword_matches(k, word) for k in keywords))
        if score:
            scores[gid] = score
    if not scores:
        return OTHER_GROUP[0]
    best = max(scores.values())
    winners = [gid for gid, score in scores.items() if score == best]
    # A tie means the name points at two groups; do not guess.
    return winners[0] if len(winners) == 1 else OTHER_GROUP[0]


def _keyword_matches(keyword: str, word: str) -> bool:
    if len(keyword) <= 2:
        return word == keyword
    return word.startswith(keyword)


def _meter(normalized: float, width: int = 10) -> str:
    filled = max(0, min(width, round(normalized * width)))
    return "[" + "#" * filled + "-" * (width - filled) + "]"


def _check_structure(spec: MacroCockpitSpec) -> None:
    if spec.mode not in ("temporary", "saved"):
        raise CockpitError(f"cockpit mode must be 'temporary' or 'saved', got {spec.mode!r}")
    ids = [control.id for control in spec.controls]
    if len(ids) != len(set(ids)):
        raise CockpitError("cockpit control ids must be unique")
    indexes = [control.source_macro_index for control in spec.controls]
    if len(indexes) != len(set(indexes)):
        raise CockpitError("each macro may back only one control")
    grouped: list[str] = [cid for group in spec.groups for cid in group.controls]
    unknown = sorted(set(grouped) - set(ids))
    if unknown:
        raise CockpitError(f"groups reference unknown controls: {', '.join(unknown)}")
    if len(grouped) != len(set(grouped)):
        raise CockpitError("a control may appear in only one group")


def _require_dict(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise CockpitError(f"{label} must be a JSON object")
    return value


def _require_str(data: dict[str, Any], key: str) -> str:
    value = data.get(key)
    if not isinstance(value, str):
        raise CockpitError(f"'{key}' must be a string")
    return value


def _require_number(data: dict[str, Any], key: str) -> float:
    value = data.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise CockpitError(f"'{key}' must be a number")
    return float(value)


def _require_macro_index(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= MAX_MACROS:
        raise CockpitError(f"macro index must be an integer from 1 to {MAX_MACROS}")
    return value


def _optional_bool(value: Any) -> bool | None:
    if value is None or isinstance(value, bool):
        return value
    raise CockpitError("'is_mapped' must be true, false, or null")


def _optional_str(value: Any) -> str | None:
    return None if value is None else str(value)


def _slug(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug or "rack"
