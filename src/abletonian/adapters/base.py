"""The DawAdapter interface between the MCP tools and a DAW (RFC 0003).

The MCP tools build the request objects below and hand them to an adapter.
An adapter translates them to its own transport: the Remote Script adapter
sends ``ableton.*`` bridge methods, the fake adapter changes in-memory state.
Request field names match today's MCP tool parameters and bridge params, so
moving a tool onto this interface does not change what reaches Live.

Results stay JSON objects for now (RFC 0003, "Results stay JSON objects").
Anything an adapter returns came from outside this process and must be
validated before the server builds on it.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field, fields
from typing import Any, ClassVar, Protocol, runtime_checkable

TrackRef = int | str
DeviceRef = int | str
# A raw number, display text ("-3 dB", "Auto"), or {"raw": number} for an
# explicit raw value. The Remote Script decides how a bare number is read.
ParameterValue = float | str | Mapping[str, float]


class AdapterError(RuntimeError):
    """Base class for errors raised by a DawAdapter."""


class AdapterUnavailable(AdapterError):
    """The DAW could not be reached, or did not answer in time."""


class AdapterRefused(AdapterError):
    """The DAW answered and refused the request."""

    def __init__(
        self,
        message: str,
        code: str = "adapter_error",
        hint: str | None = None,
        text: str | None = None,
    ):
        super().__init__(message)
        self.code = code
        self.hint = hint
        # The exact text to show, when the transport already formatted one.
        self.text = text

    def __str__(self) -> str:
        if self.text is not None:
            return self.text
        text = f"{self.code}: {super().__str__()}"
        return f"{text} Hint: {self.hint}" if self.hint else text


class UnsupportedOperation(AdapterError):
    """The adapter does not advertise the capability an operation needs."""

    def __init__(self, operation: str):
        super().__init__(f"this DAW adapter cannot {operation.replace('_', ' ')}")
        self.operation = operation


class AdapterResponseError(AdapterError):
    """The adapter returned data the server cannot trust or use."""


class _Request:
    """Shared behaviour for request objects: one dataclass per operation."""

    OPERATION: ClassVar[str]

    def params(self) -> dict[str, Any]:
        """Return the non-None fields as JSON-ready params."""

        out: dict[str, Any] = {}
        for item in fields(self):  # type: ignore[arg-type]
            value = getattr(self, item.name)
            if value is None:
                continue
            if isinstance(value, Mapping):
                value = dict(value)
            out[item.name] = value
        return out


# Read-only requests.


@dataclass(frozen=True)
class TrackQuery(_Request):
    OPERATION: ClassVar[str] = "list_tracks"

    include_returns: bool = True
    include_master: bool = True
    detail: str = "compact"
    name: str | None = None


@dataclass(frozen=True)
class DeviceQuery(_Request):
    OPERATION: ClassVar[str] = "list_devices"

    track: TrackRef | None = None
    # True lists every parameter ("full"); the MCP tool sends False by default.
    include_parameters: bool = True
    max_depth: int | None = None


@dataclass(frozen=True)
class DeviceRead(_Request):
    OPERATION: ClassVar[str] = "get_device"

    track: TrackRef
    device: DeviceRef
    # A name or substring, or a list of them; None returns every parameter.
    parameters: str | tuple[str, ...] | None = None

    def params(self) -> dict[str, Any]:
        out = super().params()
        if isinstance(self.parameters, tuple):
            out["parameters"] = list(self.parameters)
        return out


@dataclass(frozen=True)
class RackRef(_Request):
    OPERATION: ClassVar[str] = "get_selected_rack_macros"

    track: TrackRef | None = None
    device: DeviceRef | None = None


@dataclass(frozen=True)
class ClipQuery(_Request):
    """A track's Arrangement View clips."""

    OPERATION: ClassVar[str] = "list_clips"

    track: TrackRef


# Realtime reads: they take wall-clock time and depend on playback, but do
# not change the Set or the transport.


@dataclass(frozen=True)
class LevelRead(_Request):
    """Sample track output meters for ``seconds`` while Live plays (issue #45).

    Values are Live meter positions 0..1, not dBFS. Limits match
    LEVEL_MIN_SECONDS, LEVEL_MAX_SECONDS and MAX_LEVEL_TRACKS in the Remote
    Script's live_ops.py, which checks them again.
    """

    OPERATION: ClassVar[str] = "read_levels"
    MIN_SECONDS: ClassVar[float] = 0.5
    MAX_SECONDS: ClassVar[float] = 10.0
    MAX_TRACKS: ClassVar[int] = 16

    tracks: tuple[TrackRef, ...] | None = None
    seconds: float = 4.0
    include_returns: bool = False
    include_main: bool = False

    def __post_init__(self) -> None:
        if self.tracks is not None:
            object.__setattr__(self, "tracks", tuple(self.tracks))
            if not self.tracks:
                raise ValueError("tracks must name at least one track, or be left out")
            if len(self.tracks) > self.MAX_TRACKS:
                raise ValueError(
                    f"read at most {self.MAX_TRACKS} tracks at once, got {len(self.tracks)}"
                )
        seconds = self.seconds
        if isinstance(seconds, bool) or not isinstance(seconds, (int, float)):
            raise ValueError("seconds must be a number")
        if not self.MIN_SECONDS <= seconds <= self.MAX_SECONDS:
            raise ValueError(
                f"seconds must be from {self.MIN_SECONDS} to {self.MAX_SECONDS}, got {seconds}"
            )

    def params(self) -> dict[str, Any]:
        out = super().params()
        if self.tracks is not None:
            out["tracks"] = list(self.tracks)
        return out


# Requests that change the Set. These are the ones a Batch may hold.


@dataclass(frozen=True)
class ParameterChange(_Request):
    OPERATION: ClassVar[str] = "set_device_parameter"

    track: TrackRef
    device: DeviceRef
    parameter: int | str
    value: ParameterValue


@dataclass(frozen=True)
class RoutingChange(_Request):
    OPERATION: ClassVar[str] = "set_track_output_routing"

    track: TrackRef
    routing_type: str
    routing_channel: str | None = None


@dataclass(frozen=True)
class SidechainChange(_Request):
    """Point a device's sidechain input at a source, by display name."""

    OPERATION: ClassVar[str] = "set_device_sidechain"

    track: TrackRef
    device: DeviceRef
    from_track: str
    channel: str | None = None


@dataclass(frozen=True)
class ClipGainChange(_Request):
    """Set an arrangement audio clip's gain, in dB ("-3 dB" or -3)."""

    OPERATION: ClassVar[str] = "set_clip_gain"

    track: TrackRef
    clip: int | str
    gain_db: ParameterValue


@dataclass(frozen=True)
class TrackPropertiesChange(_Request):
    OPERATION: ClassVar[str] = "set_track_properties"

    track: TrackRef
    name: str | None = None
    color: str | None = None
    color_index: int | None = None


@dataclass(frozen=True)
class DevicePropertiesChange(_Request):
    """Rename a device; ``device`` may be a path inside racks."""

    OPERATION: ClassVar[str] = "set_device_properties"

    track: TrackRef
    device: DeviceRef
    name: str


@dataclass(frozen=True)
class ChainPropertiesChange(_Request):
    """Rename a rack chain; ``chain`` is a rack path plus a chain, "Rack/Piano"."""

    OPERATION: ClassVar[str] = "set_chain_properties"

    track: TrackRef
    chain: str
    name: str


@dataclass(frozen=True)
class MixerChange(_Request):
    OPERATION: ClassVar[str] = "set_mixer"

    track: TrackRef
    volume: ParameterValue | None = None
    panning: ParameterValue | None = None
    sends: Mapping[str, ParameterValue] | None = None
    mute: bool | None = None
    solo: bool | None = None


@dataclass(frozen=True)
class DeviceInsert(_Request):
    OPERATION: ClassVar[str] = "insert_device"

    track: TrackRef
    device_name: str
    index: int | None = None
    parameters: Mapping[str, ParameterValue] | None = None
    name: str | None = None


@dataclass(frozen=True)
class ReturnTrackCreate(_Request):
    OPERATION: ClassVar[str] = "create_return_track"

    name: str | None = None
    color: str | None = None


@dataclass(frozen=True)
class TrackCreate(_Request):
    """Add a MIDI or audio track. index None (or -1) appends after the last track."""

    OPERATION: ClassVar[str] = "create_track"

    kind: str
    name: str | None = None
    index: int | None = None
    color_index: int | None = None
    color: str | None = None


@dataclass(frozen=True)
class DeviceDelete(_Request):
    """Delete a device. Without confirm it is a preview and changes nothing."""

    OPERATION: ClassVar[str] = "delete_device"

    track: TrackRef
    device: DeviceRef
    confirm: bool = False

    def params(self) -> dict[str, Any]:
        # The bridge reads a missing confirm as a preview; send it explicitly
        # so the request says what it means.
        return {"track": self.track, "device": self.device, "confirm": self.confirm is True}


Change = (
    ParameterChange
    | RoutingChange
    | TrackPropertiesChange
    | DevicePropertiesChange
    | ChainPropertiesChange
    | MixerChange
    | DeviceInsert
    | ReturnTrackCreate
    | TrackCreate
    | DeviceDelete
    | SidechainChange
    | ClipGainChange
)

CHANGE_TYPES: tuple[type[_Request], ...] = (
    ParameterChange,
    RoutingChange,
    TrackPropertiesChange,
    DevicePropertiesChange,
    ChainPropertiesChange,
    MixerChange,
    DeviceInsert,
    ReturnTrackCreate,
    TrackCreate,
    DeviceDelete,
    SidechainChange,
    ClipGainChange,
)


@dataclass(frozen=True)
class Batch:
    """Several changes. atomic=True asks for one undo step for the whole batch."""

    OPERATION: ClassVar[str] = "batch"

    operations: tuple[Change, ...]
    atomic: bool = True

    def __post_init__(self) -> None:
        # Store a tuple even when given a list, so the batch cannot change later.
        object.__setattr__(self, "operations", tuple(self.operations))
        if not self.operations:
            raise ValueError("a batch needs at least one operation")
        for operation in self.operations:
            if not isinstance(operation, CHANGE_TYPES):
                raise TypeError(f"a batch cannot hold {type(operation).__name__}")


@dataclass(frozen=True)
class UndoRequest(_Request):
    OPERATION: ClassVar[str] = "undo"
    MAX_COUNT: ClassVar[int] = 20

    count: int = 1
    confirm: bool = False

    def __post_init__(self) -> None:
        # Fail closed: a bad count must never reach Live as a plain Undo.
        if isinstance(self.count, bool) or not isinstance(self.count, int):
            raise ValueError("undo count must be a whole number")
        if not 1 <= self.count <= self.MAX_COUNT:
            raise ValueError(f"undo count must be from 1 to {self.MAX_COUNT}")


# Health.


@dataclass(frozen=True)
class AdapterHealth:
    """What an adapter says about itself, validated from its health answer."""

    target_daw: str
    adapter_type: str
    adapter_version: str
    protocol_version: str
    capabilities: frozenset[str]
    unsupported_capabilities: frozenset[str] = frozenset()
    daw_version: str | None = None
    raw: Mapping[str, Any] = field(default_factory=dict, compare=False)

    @classmethod
    def from_wire(cls, payload: Any) -> AdapterHealth:
        """Validate a ``daw.health`` result. Raises AdapterResponseError."""

        if not isinstance(payload, Mapping):
            raise AdapterResponseError("health answer must be a JSON object")
        text = {}
        for key in ("target_daw", "adapter_type", "adapter_version", "protocol_version"):
            value = payload.get(key)
            if not isinstance(value, str) or not value:
                raise AdapterResponseError(f"health answer has no valid {key!r}")
            text[key] = value
        daw_version = payload.get("live_version", payload.get("daw_version"))
        if daw_version is not None and not isinstance(daw_version, str):
            raise AdapterResponseError("health answer has a non-text DAW version")
        return cls(
            **text,
            capabilities=_names(payload.get("capabilities"), "capabilities"),
            unsupported_capabilities=_names(
                payload.get("unsupported_capabilities", []), "unsupported_capabilities"
            ),
            daw_version=daw_version,
            raw=dict(payload),
        )


def _names(value: Any, key: str) -> frozenset[str]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise AdapterResponseError(f"health answer {key!r} must be a list of names")
    return frozenset(value)


# The interface.


@runtime_checkable
class DawAdapter(Protocol):
    """One DAW connection. See docs/rfcs/0003-daw-adapter-and-safety-policy.md.

    Methods return the adapter's JSON result as a dict. They raise
    AdapterUnavailable, AdapterRefused, UnsupportedOperation, or
    AdapterResponseError; they never return an error as a result.
    """

    def health(self) -> AdapterHealth: ...

    def capabilities(self) -> frozenset[str]: ...

    # Read-only: must not change the Set.
    def list_tracks(self, query: TrackQuery) -> dict[str, Any]: ...

    def list_devices(self, query: DeviceQuery) -> dict[str, Any]: ...

    def get_device(self, request: DeviceRead) -> dict[str, Any]: ...

    def get_selected_rack_macros(self, ref: RackRef) -> dict[str, Any]: ...

    def list_clips(self, query: ClipQuery) -> dict[str, Any]: ...

    def plan_drum_rack_extraction(self) -> dict[str, Any]: ...

    # Realtime read: samples meters over time; must not change the Set or transport.
    def read_levels(self, request: LevelRead) -> dict[str, Any]: ...

    # Change the Set (DeviceDelete without confirm is a read-only preview).
    def set_device_parameter(self, change: ParameterChange) -> dict[str, Any]: ...

    def set_track_output_routing(self, change: RoutingChange) -> dict[str, Any]: ...

    def set_track_properties(self, change: TrackPropertiesChange) -> dict[str, Any]: ...

    def set_device_properties(self, change: DevicePropertiesChange) -> dict[str, Any]: ...

    def set_chain_properties(self, change: ChainPropertiesChange) -> dict[str, Any]: ...

    def set_mixer(self, change: MixerChange) -> dict[str, Any]: ...

    def insert_device(self, change: DeviceInsert) -> dict[str, Any]: ...

    def create_return_track(self, change: ReturnTrackCreate) -> dict[str, Any]: ...

    def create_track(self, change: TrackCreate) -> dict[str, Any]: ...

    def delete_device(self, change: DeviceDelete) -> dict[str, Any]: ...

    def set_device_sidechain(self, change: SidechainChange) -> dict[str, Any]: ...

    def set_clip_gain(self, change: ClipGainChange) -> dict[str, Any]: ...

    def apply_batch(self, batch: Batch) -> dict[str, Any]: ...

    def undo(self, request: UndoRequest) -> dict[str, Any]: ...

    def execute_drum_rack_extraction(self) -> dict[str, Any]: ...
