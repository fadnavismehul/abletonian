"""Fake Ableton adapter used for workflow tests without launching Live."""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Any

from abletonian.bridge.protocol import PROTOCOL_VERSION

FAKE_ADAPTER_VERSION = "0.1.0"
FAKE_ADAPTER_CAPABILITIES = (
    "read_project_state",
    "read_selected_context",
    "read_drum_rack",
    "plan_drum_rack_extraction",
    "execute_drum_rack_extraction",
)
FAKE_ADAPTER_UNSUPPORTED_CAPABILITIES = (
    "manual_rtfm_lookup",
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
class FakeDrumRackDevice:
    """A minimal Drum Rack device with pads."""

    id: str
    name: str
    pads: tuple[FakeDrumPad, ...] = ()


@dataclass(frozen=True)
class FakeTrack:
    """A minimal Ableton track with clips and devices."""

    id: str
    name: str
    color: str | None = None
    clips: tuple[FakeClip, ...] = ()
    devices: tuple[FakeDrumRackDevice, ...] = ()


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
        if self.selected_device_id is not None:
            for device in track.devices:
                if device.id == self.selected_device_id:
                    return device
            raise FakeAdapterError(f"selected device '{self.selected_device_id}' was not found")
        if not track.devices:
            raise FakeAdapterError(f"selected track '{track.name}' has no Drum Rack device")
        return track.devices[0]


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
        if method == "workflow.plan_drum_rack_extraction":
            return self._plan_drum_rack_extraction()
        if method == "workflow.execute_drum_rack_extraction":
            return self._execute_drum_rack_extraction(request_params)
        raise FakeAdapterError(f"unsupported fake adapter method '{method}'")

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
        post_tracks = (*self.state.tracks, *created_tracks)

        return {
            "operation": "split_drum_rack",
            "mode": "fake_execute",
            "target": plan["target"],
            "preserved_tracks": [source_track.id],
            "touched_tracks": [],
            "created_tracks": [
                _created_track_payload(track, output)
                for track, output in zip(created_tracks, plan["output_tracks"], strict=True)
            ],
            "post_state": {
                "track_count": len(post_tracks),
                "track_names": [track.name for track in post_tracks],
                "created_track_ids": [track.id for track in created_tracks],
            },
            "warnings": plan["warnings"],
            "verification": {
                "source_track_preserved": True,
                "created_track_count": len(created_tracks),
                "mutates_real_ableton_set": False,
            },
        }


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


def _created_track_payload(track: FakeTrack, output: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": track.id,
        "name": track.name,
        "color": track.color,
        "source_pad": output["source_pad"],
        "devices": output["devices"],
        "clips": [_clip_payload(clip) for clip in track.clips],
    }


def _clip_payload(clip: FakeClip) -> dict[str, Any]:
    return {
        "id": clip.id,
        "name": clip.name,
        "note_count": len(clip.notes),
        "note_pitches": sorted({note.pitch for note in clip.notes}),
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
