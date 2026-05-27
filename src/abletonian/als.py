"""Read-only Ableton Live Set loading for local validation fixtures."""

from __future__ import annotations

import gzip
import pathlib
import re
import xml.etree.ElementTree as ET

from abletonian.adapters.fake import (
    FakeAbletonState,
    FakeClip,
    FakeDrumPad,
    FakeDrumRackDevice,
    FakeMidiNote,
    FakeTrack,
)

TRACK_TAGS = {"MidiTrack", "AudioTrack", "GroupTrack", "ReturnTrack"}


def load_als_as_fake_state(path: str | pathlib.Path) -> FakeAbletonState:
    """Load a compressed Ableton `.als` file into the fake adapter state model."""

    set_path = pathlib.Path(path)
    root = ET.parse(gzip.open(set_path, "rb")).getroot()
    tracks = tuple(
        _track_from_xml(track)
        for track in root.findall(".//Tracks/*")
        if track.tag in TRACK_TAGS
    )
    return FakeAbletonState(
        live_version=_live_version(root),
        tracks=tracks,
        selected_track_id=tracks[0].id if tracks else None,
        selected_device_id=_first_device_id(tracks),
    )


def _live_version(root: ET.Element) -> str:
    creator = root.attrib.get("Creator", "")
    match = re.search(r"Ableton Live\s+([0-9.]+)", creator)
    if match:
        return match.group(1)
    return creator or "unknown"


def _track_from_xml(track: ET.Element) -> FakeTrack:
    track_id = track.attrib.get("Id", "")
    return FakeTrack(
        id=track_id,
        name=_track_name(track),
        color=_value_at(track, "./Color"),
        clips=_clips(track),
        devices=_drum_racks(track),
    )


def _track_name(track: ET.Element) -> str:
    user_name = _value_at(track, "./Name/UserName")
    if user_name:
        return user_name
    effective_name = _value_at(track, "./Name/EffectiveName")
    if effective_name:
        return effective_name
    return f"{track.tag}-{track.attrib.get('Id', 'unknown')}"


def _value_at(element: ET.Element, path: str) -> str | None:
    found = element.find(path)
    if found is None:
        return None
    return found.attrib.get("Value")


def _drum_racks(track: ET.Element) -> tuple[FakeDrumRackDevice, ...]:
    drum_racks = []
    for device in track.iter("DrumGroupDevice"):
        device_id = device.attrib.get("Id", "")
        drum_racks.append(
            FakeDrumRackDevice(
                id=device_id,
                name=_device_name(device) or "Drum Rack",
                pads=_drum_pads(device),
            )
        )
    return tuple(drum_racks)


def _clips(track: ET.Element) -> tuple[FakeClip, ...]:
    clips = []
    for clip in track.iter("MidiClip"):
        clip_id = clip.attrib.get("Id", "")
        clips.append(
            FakeClip(
                id=clip_id,
                name=_value_at(clip, "./Name") or f"MidiClip-{clip_id}",
                notes=_midi_notes(clip),
            )
        )
    return tuple(clips)


def _midi_notes(clip: ET.Element) -> tuple[FakeMidiNote, ...]:
    notes = []
    for key_track in clip.findall("./Notes/KeyTracks/KeyTrack"):
        midi_key = _int_value_at(key_track, "./MidiKey")
        if midi_key is None:
            continue
        for note in key_track.findall("./Notes/MidiNoteEvent"):
            notes.append(
                FakeMidiNote(
                    pitch=midi_key,
                    start=float(note.attrib.get("Time", "0")),
                    duration=float(note.attrib.get("Duration", "0")),
                    velocity=int(note.attrib.get("Velocity", "0")),
                )
            )
    return tuple(notes)


def _drum_pads(device: ET.Element) -> tuple[FakeDrumPad, ...]:
    pads = []
    for branch in device.findall("./Branches/DrumBranch"):
        receiving_note = _first_descendant_int(branch, "ReceivingNote")
        if receiving_note is None:
            continue
        name = _branch_name(branch)
        pads.append(
            FakeDrumPad(
                note=_ableton_receiving_note_to_midi_pitch(receiving_note),
                name=name,
                chain_name=name,
                color=_value_at(branch, "./Color"),
                devices=_branch_device_names(branch),
            )
        )
    return tuple(sorted(pads, key=lambda pad: pad.note))


def _branch_name(branch: ET.Element) -> str:
    user_name = _value_at(branch, "./Name/UserName")
    if user_name:
        return user_name
    effective_name = _value_at(branch, "./Name/EffectiveName")
    if effective_name:
        return effective_name
    return f"DrumBranch-{branch.attrib.get('Id', 'unknown')}"


def _ableton_receiving_note_to_midi_pitch(receiving_note: int) -> int:
    return 128 - receiving_note


def _branch_device_names(branch: ET.Element) -> tuple[str, ...]:
    names: list[str] = []
    for device in branch.findall("./DeviceChain/MidiToAudioDeviceChain/Devices/*"):
        name = _device_name(device)
        if name:
            names.append(name)
    return tuple(names)


def _device_name(device: ET.Element) -> str | None:
    for path in ("./UserName", "./Name/UserName", "./Name/EffectiveName"):
        name = _value_at(device, path)
        if name:
            return name
    return None


def _int_value_at(element: ET.Element, path: str) -> int | None:
    value = _value_at(element, path)
    if value is None:
        return None
    return int(value)


def _first_descendant_int(element: ET.Element, tag: str) -> int | None:
    for descendant in element.iter(tag):
        value = descendant.attrib.get("Value")
        if value is not None:
            return int(value)
    return None


def _first_device_id(tracks: tuple[FakeTrack, ...]) -> str | None:
    for track in tracks:
        if track.devices:
            return track.devices[0].id
    return None
