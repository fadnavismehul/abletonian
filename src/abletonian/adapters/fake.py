"""Fake Ableton adapter used for workflow tests without launching Live."""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Any

from abletonian.adapters.base import (
    AdapterHealth,
    AdapterRefused,
    Batch,
    DeviceDelete,
    DeviceInsert,
    DeviceQuery,
    MixerChange,
    ParameterChange,
    RackRef,
    ReturnTrackCreate,
    RoutingChange,
    TrackPropertiesChange,
    TrackQuery,
    UndoRequest,
    UnsupportedOperation,
)
from abletonian.bridge.protocol import PROTOCOL_VERSION

FAKE_ADAPTER_VERSION = "0.1.0"
FAKE_ADAPTER_CAPABILITIES = (
    "read_project_state",
    "read_selected_context",
    "read_drum_rack",
    "plan_drum_rack_extraction",
    "execute_drum_rack_extraction",
    "read_rack_macros",
)
FAKE_ADAPTER_UNSUPPORTED_CAPABILITIES = (
    "manual_rtfm_lookup",
    "set_rack_macro_value",
)


@dataclass(frozen=True)
class FakeMidiNote:
    """A minimal MIDI note model for fake Ableton clips."""

    pitch: int
    start: float
    duration: float
    velocity: int


@dataclass(frozen=True)
class FakeClip:
    """A minimal MIDI clip model for fake Ableton tracks."""

    id: str
    name: str
    notes: tuple[FakeMidiNote, ...] = ()


@dataclass(frozen=True)
class FakeDrumPad:
    """A Drum Rack pad and its chain metadata."""

    note: int
    name: str
    chain_name: str
    color: str | None = None
    devices: tuple[str, ...] = ()


@dataclass(frozen=True)
class FakeRackMacro:
    """One rack macro. ``name`` equals ``original_name`` until the user renames it."""

    index: int
    name: str
    value: float = 0.0
    is_mapped: bool = True
    original_name: str | None = None
    min: float = 0.0
    max: float = 127.0

    def wire(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "name": self.name,
            "original_name": self.original_name or f"Macro {self.index}",
            "value": self.value,
            "min": self.min,
            "max": self.max,
            "display": f"{self.value:.0f}",
            "is_mapped": self.is_mapped,
            "is_enabled": True,
        }


@dataclass(frozen=True)
class FakeDrumRackDevice:
    """A minimal Drum Rack device with pads."""

    id: str
    name: str
    pads: tuple[FakeDrumPad, ...] = ()
    macros: tuple[FakeRackMacro, ...] = ()
    class_name: str = "DrumGroupDevice"


@dataclass(frozen=True)
class FakeRackDevice:
    """An Instrument, Audio Effect, or MIDI Effect Rack with macros."""

    id: str
    name: str
    macros: tuple[FakeRackMacro, ...] = ()
    class_name: str = "InstrumentGroupDevice"
    chain_names: tuple[str, ...] = ()


@dataclass(frozen=True)
class FakePlainDevice:
    """A device that is not a rack, such as a Utility."""

    id: str
    name: str
    class_name: str = "StereoGain"


@dataclass(frozen=True)
class FakeTrack:
    """A minimal Ableton track with clips and devices."""

    id: str
    name: str
    color: str | None = None
    clips: tuple[FakeClip, ...] = ()
    devices: tuple[FakeDrumRackDevice | FakeRackDevice | FakePlainDevice, ...] = ()


@dataclass(frozen=True)
class FakeAbletonState:
    """The Live-like state visible to the fake adapter."""

    live_version: str
    tracks: tuple[FakeTrack, ...] = ()
    selected_track_id: str | None = None
    selected_device_id: str | None = None

    def selected_track(self) -> FakeTrack:
        """Return the selected track or raise a typed adapter error."""

        if self.selected_track_id is None:
            raise FakeAdapterError("no selected track")
        for track in self.tracks:
            if track.id == self.selected_track_id:
                return track
        raise FakeAdapterError(f"selected track '{self.selected_track_id}' was not found")

    def selected_drum_rack(self) -> FakeDrumRackDevice:
        """Return the selected Drum Rack device on the selected track."""

        track = self.selected_track()
        drum_racks = [d for d in track.devices if isinstance(d, FakeDrumRackDevice)]
        if self.selected_device_id is not None:
            for device in track.devices:
                if device.id == self.selected_device_id:
                    if isinstance(device, FakeDrumRackDevice):
                        return device
                    break
            else:
                raise FakeAdapterError(
                    f"selected device '{self.selected_device_id}' was not found"
                )
        if not drum_racks:
            raise FakeAdapterError(f"selected track '{track.name}' has no Drum Rack device")
        return drum_racks[0]

    def selected_rack(self) -> tuple[int, FakeDrumRackDevice | FakeRackDevice, str]:
        """Return (device index, rack, how it was chosen) on the selected track."""

        track = self.selected_track()
        racks = [
            (index, device)
            for index, device in enumerate(track.devices)
            if isinstance(device, (FakeDrumRackDevice, FakeRackDevice))
        ]
        if self.selected_device_id is not None:
            for index, device in racks:
                if device.id == self.selected_device_id:
                    return index, device, "selected_device"
        if not racks:
            raise FakeAdapterError(f"track '{track.name}' has no Rack")
        return racks[0][0], racks[0][1], "first_rack_on_track"


class FakeAdapterError(RuntimeError):
    """Raised when the fake Ableton adapter cannot satisfy a request."""


@dataclass(frozen=True)
class FakeAbletonAdapter:
    """In-process adapter that mirrors the first Ableton bridge capabilities."""

    state: FakeAbletonState = field(
        default_factory=lambda: FakeAbletonState(live_version="unknown")
    )

    def handle_request(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        """Handle a bridge-style request and return a JSON-ready result."""

        request_params = params or {}
        if method == "daw.health":
            return self._health(request_params)
        if method == "ableton.get_selected_context":
            return self._selected_context()
        if method == "ableton.get_selected_rack_macros":
            return self._selected_rack_macros()
        if method == "workflow.plan_drum_rack_extraction":
            return self._plan_drum_rack_extraction()
        if method == "workflow.execute_drum_rack_extraction":
            return self._execute_drum_rack_extraction(request_params)
        raise FakeAdapterError(f"unsupported fake adapter method '{method}'")

    # DawAdapter (RFC 0003). Operations the fake does not model yet raise
    # UnsupportedOperation and are absent from its capabilities; parity with
    # the Remote Script is tracked in Linear MEH-21.

    def health(self) -> AdapterHealth:
        return AdapterHealth.from_wire(self._health({"target_daw": "ableton"}))

    def capabilities(self) -> frozenset[str]:
        return frozenset(FAKE_ADAPTER_CAPABILITIES)

    def known_capabilities(self) -> frozenset[str]:
        return self.capabilities()

    def get_selected_rack_macros(self, ref: RackRef) -> dict[str, Any]:
        if ref.track is not None or ref.device is not None:
            raise AdapterRefused(
                "the fake adapter reads only the selected rack", code="unsupported_request"
            )
        return self._refusing(self._selected_rack_macros)

    def plan_drum_rack_extraction(self) -> dict[str, Any]:
        return self._refusing(self._plan_drum_rack_extraction)

    def execute_drum_rack_extraction(self) -> dict[str, Any]:
        return self._refusing(lambda: self._execute_drum_rack_extraction({"confirm": True}))

    def list_tracks(self, query: TrackQuery) -> dict[str, Any]:
        raise UnsupportedOperation(TrackQuery.OPERATION)

    def list_devices(self, query: DeviceQuery) -> dict[str, Any]:
        raise UnsupportedOperation(DeviceQuery.OPERATION)

    def set_device_parameter(self, change: ParameterChange) -> dict[str, Any]:
        raise UnsupportedOperation(ParameterChange.OPERATION)

    def set_track_output_routing(self, change: RoutingChange) -> dict[str, Any]:
        raise UnsupportedOperation(RoutingChange.OPERATION)

    def set_track_properties(self, change: TrackPropertiesChange) -> dict[str, Any]:
        raise UnsupportedOperation(TrackPropertiesChange.OPERATION)

    def set_mixer(self, change: MixerChange) -> dict[str, Any]:
        raise UnsupportedOperation(MixerChange.OPERATION)

    def insert_device(self, change: DeviceInsert) -> dict[str, Any]:
        raise UnsupportedOperation(DeviceInsert.OPERATION)

    def create_return_track(self, change: ReturnTrackCreate) -> dict[str, Any]:
        raise UnsupportedOperation(ReturnTrackCreate.OPERATION)

    def delete_device(self, change: DeviceDelete) -> dict[str, Any]:
        raise UnsupportedOperation(DeviceDelete.OPERATION)

    def apply_batch(self, batch: Batch) -> dict[str, Any]:
        raise UnsupportedOperation(Batch.OPERATION)

    def undo(self, request: UndoRequest) -> dict[str, Any]:
        raise UnsupportedOperation(UndoRequest.OPERATION)

    @staticmethod
    def _refusing(call: Any) -> dict[str, Any]:
        try:
            result: dict[str, Any] = call()
        except FakeAdapterError as exc:
            raise AdapterRefused(str(exc), code="adapter_error") from exc
        return result

    def _health(self, params: dict[str, Any]) -> dict[str, Any]:
        target_daw = params.get("target_daw", "ableton")
        if target_daw != "ableton":
            raise FakeAdapterError(f"fake Ableton adapter cannot target '{target_daw}'")
        return {
            "target_daw": "ableton",
            "adapter_type": "fake",
            "adapter_version": FAKE_ADAPTER_VERSION,
            "live_version": self.state.live_version,
            "protocol_version": PROTOCOL_VERSION,
            "capabilities": list(FAKE_ADAPTER_CAPABILITIES),
            "unsupported_capabilities": list(FAKE_ADAPTER_UNSUPPORTED_CAPABILITIES),
        }

    def _selected_context(self) -> dict[str, Any]:
        track = self.state.selected_track()
        device = self.state.selected_drum_rack()
        return {
            "track": {
                "id": track.id,
                "name": track.name,
                "color": track.color,
            },
            "device": {
                "id": device.id,
                "name": device.name,
                "type": "drum_rack",
            },
        }

    def _selected_rack_macros(self) -> dict[str, Any]:
        track = self.state.selected_track()
        track_index = self.state.tracks.index(track)
        device_index, device, selection = self.state.selected_rack()
        if isinstance(device, FakeDrumRackDevice):
            chain_names = [pad.chain_name for pad in device.pads]
            device_type = "drum_rack"
        else:
            chain_names = list(device.chain_names)
            device_type = "rack"
        return {
            "track": {"kind": "track", "index": track_index, "name": track.name,
                      "color": track.color},
            "device": {
                "index": device_index,
                "name": device.name,
                "class_name": device.class_name,
                "class_display_name": device.name,
                "type": device_type,
                "chain_names": chain_names,
            },
            "selection": selection,
            "visible_macro_count": len(device.macros),
            "macros": [macro.wire() for macro in device.macros],
        }

    def _plan_drum_rack_extraction(self) -> dict[str, Any]:
        track = self.state.selected_track()
        device = self.state.selected_drum_rack()
        pitch_counts = Counter(
            note.pitch for clip in track.clips for note in clip.notes
        )
        outputs: list[dict[str, Any]] = []
        skipped_pad_names: list[str] = []

        for pad in device.pads:
            note_count = pitch_counts.get(pad.note, 0)
            if note_count == 0:
                skipped_pad_names.append(pad.name)
                continue
            outputs.append(
                {
                    "source_pad": {
                        "note": pad.note,
                        "name": pad.name,
                        "chain_name": pad.chain_name,
                    },
                    "name": f"{track.name} - {pad.name}",
                    "color": pad.color or track.color,
                    "devices": list(pad.devices),
                    "midi_filter": {"keep_pitch": pad.note},
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
                "track_id": track.id,
                "track_name": track.name,
                "device_id": device.id,
                "device_name": device.name,
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

    def _execute_drum_rack_extraction(self, params: dict[str, Any]) -> dict[str, Any]:
        """Same result shape as the Remote Script's execute (bridge_server.py).

        Differences on purpose: verification.mutates_real_ableton_set is
        False, and the fake adds post_state and each clip's notes. The fake's
        state is not changed, so a second call returns the same result.
        """

        if params.get("confirm") is not True:
            raise FakeAdapterError(
                "workflow.execute_drum_rack_extraction requires confirmation"
            )

        source_track = self.state.selected_track()
        plan = self._plan_drum_rack_extraction()
        created_tracks = [
            _create_extracted_track(source_track, output)
            for output in plan["output_tracks"]
        ]
        # Live duplicates each new track after the previous one, so they sit
        # right after the source track, in plan order.
        source_index = self.state.tracks.index(source_track)
        post_tracks = (
            *self.state.tracks[: source_index + 1],
            *created_tracks,
            *self.state.tracks[source_index + 1 :],
        )
        created_payloads = [
            _created_track_payload(track, output, source_track, source_index + 1 + position)
            for position, (track, output) in enumerate(
                zip(created_tracks, plan["output_tracks"], strict=True)
            )
        ]

        return {
            "operation": "split_drum_rack",
            "mode": "execute",
            "target": plan["target"],
            "preserved_tracks": [source_track.id],
            "touched_tracks": [track.id for track in created_tracks],
            "created_tracks": created_payloads,
            "warnings": plan["warnings"],
            "backout": {
                "primary": _undo_backout_text(len(created_tracks)),
                "fallback": "Close the Live Set without saving to discard scaffold tracks.",
            },
            "verification": {
                "source_track_preserved": True,
                "created_track_count": len(created_tracks),
                "midi_filtering_applied": True,
                "saved_live_set": False,
                "mutates_real_ableton_set": False,
            },
            "post_state": {
                "track_count": len(post_tracks),
                "track_names": [track.name for track in post_tracks],
                "created_track_ids": [track.id for track in created_tracks],
            },
        }


# Live Undo presses per track the Drum Rack workflow creates. Same value and
# text as the Remote Script (bridge_server.py); checked in Live 12.4.16 on
# 2026-11-03 (issue #26, step 11): "Duplicate Track(s)", then one step for the
# track's name and colour.
UNDO_STEPS_PER_CREATED_TRACK = 2


def _undo_backout_text(created_count: int) -> str:
    presses = created_count * UNDO_STEPS_PER_CREATED_TRACK
    return (
        f"Use Live Undo {presses} times to remove the {created_count} new tracks "
        f"({UNDO_STEPS_PER_CREATED_TRACK} steps per track: the duplicate, then its "
        "name and colour)."
    )


def _skipped_pad_warning(pad_names: list[str]) -> str:
    count = len(pad_names)
    noun = "drum pad" if count == 1 else "drum pads"
    return f"Skipped {count} {noun} without matching MIDI notes: {', '.join(pad_names)}"


def _create_extracted_track(source_track: FakeTrack, output: dict[str, Any]) -> FakeTrack:
    pad_name = str(output["source_pad"]["name"])
    pitch = int(output["midi_filter"]["keep_pitch"])
    clips = tuple(
        filtered_clip
        for clip in source_track.clips
        if (filtered_clip := _filter_clip_for_pitch(clip, pitch, pad_name)) is not None
    )
    return FakeTrack(
        id=f"{source_track.id}__extract__{_slug(pad_name)}",
        name=str(output["name"]),
        color=output.get("color"),
        clips=clips,
    )


def _filter_clip_for_pitch(clip: FakeClip, pitch: int, pad_name: str) -> FakeClip | None:
    notes = tuple(note for note in clip.notes if note.pitch == pitch)
    if not notes:
        return None
    return FakeClip(
        id=f"{clip.id}__{_slug(pad_name)}",
        name=f"{clip.name} - {pad_name}",
        notes=notes,
    )


def _created_track_payload(
    track: FakeTrack, output: dict[str, Any], source_track: FakeTrack, track_index: int
) -> dict[str, Any]:
    pitch = int(output["midi_filter"]["keep_pitch"])
    source_clips = {clip.id: clip for clip in source_track.clips}
    return {
        "id": track.id,
        "name": track.name,
        "track_index": track_index,
        "source_pad": output["source_pad"],
        "midi_filter": output["midi_filter"],
        "clip_note_count": output["clip_note_count"],
        "devices": output["devices"],
        "color": track.color,
        "contains_unfiltered_clips": False,
        "clips": [_clip_payload(clip, source_clips, pitch) for clip in track.clips],
    }


def _clip_payload(
    clip: FakeClip, source_clips: dict[str, FakeClip], pitch: int
) -> dict[str, Any]:
    source_id = clip.id.rsplit("__", 1)[0]
    source = source_clips.get(source_id)
    before = len(source.notes) if source is not None else len(clip.notes)
    return {
        "id": clip.id,
        "name": clip.name,
        "note_count": len(clip.notes),
        "note_pitches": sorted({note.pitch for note in clip.notes}),
        "removed_note_count": before - len(clip.notes),
        "notes": [
            {
                "pitch": note.pitch,
                "start": note.start,
                "duration": note.duration,
                "velocity": note.velocity,
            }
            for note in clip.notes
        ],
    }


def _slug(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug or "pad"
