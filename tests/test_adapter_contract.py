"""Contract tests: the fake and the Remote Script must agree (RFC 0003 step 4).

The same small Drum Rack set is built twice: as fake adapter state, and as
Live-shaped objects driven through the real Remote Script code
(remote_scripts/Abletonian) via RemoteScriptAdapter. Where both adapters
implement an operation, they must give the same answer. Where the fake does
not model an operation yet, it must say so instead of pretending.

Not covered yet (Linear MEH-21): the Drum Rack execute result, whose shape
differs between the two adapters (mode, touched_tracks, backout, clip
fields), and refusals, which this direct harness does not map the way the
real bridge does.
"""

import asyncio
import unittest
from types import SimpleNamespace
from typing import Any

import _bootstrap  # noqa: F401

from abletonian.adapters.base import (
    AdapterHealth,
    AdapterRefused,
    DawAdapter,
    MixerChange,
    RackRef,
    TrackQuery,
    UnsupportedOperation,
)
from abletonian.adapters.fake import (
    FakeAbletonAdapter,
    FakeAbletonState,
    FakeClip,
    FakeDrumPad,
    FakeDrumRackDevice,
    FakeMidiNote,
    FakeTrack,
)
from abletonian.adapters.remote_script import RemoteScriptAdapter
from abletonian.config import AbletonianConfig
from abletonian.policy import OPERATIONS
from abletonian.server import build_mcp
from remote_scripts.Abletonian.bridge_server import AbletonianBridgeControlSurface

# One Drum Rack track "Drums": Kick on note 36 played twice, Snare on 38 never
# played (so it is skipped with a warning).


def fake_adapter() -> FakeAbletonAdapter:
    rack = FakeDrumRackDevice(
        id="device-drum-rack",
        name="Drum Rack",
        pads=(
            FakeDrumPad(note=36, name="Kick", chain_name="Kick Chain", devices=("Kick Sampler",)),
            FakeDrumPad(note=38, name="Snare", chain_name="Snare Chain", devices=("Snare",)),
        ),
    )
    clip = FakeClip(
        id="clip-beat",
        name="Beat",
        notes=(
            FakeMidiNote(pitch=36, start=0.0, duration=0.25, velocity=100),
            FakeMidiNote(pitch=36, start=0.5, duration=0.25, velocity=100),
        ),
    )
    track = FakeTrack(id="track-drums", name="Drums", clips=(clip,), devices=(rack,))
    return FakeAbletonAdapter(
        FakeAbletonState(
            live_version="12.4.16",
            tracks=(track,),
            selected_track_id="track-drums",
            selected_device_id="device-drum-rack",
        )
    )


class _Clip:
    name = "Beat"
    length = 1.0
    is_midi_clip = True

    def get_notes_extended(self, *_args: Any) -> dict[str, Any]:
        return {
            "notes": (
                {"pitch": 36, "start_time": 0.0, "duration": 0.25, "velocity": 100},
                {"pitch": 36, "start_time": 0.5, "duration": 0.25, "velocity": 100},
            )
        }


class _SurfaceBridge:
    """Calls the Remote Script's request handler directly, without a socket."""

    def __init__(self, surface: Any) -> None:
        self.surface = surface

    def request(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        result: dict[str, Any] = self.surface.handle_request(method, params or {})
        return result


def remote_script_adapter() -> RemoteScriptAdapter:
    def chain(name: str, device: str) -> SimpleNamespace:
        return SimpleNamespace(name=name, color_index=None, devices=(SimpleNamespace(name=device),))

    rack = SimpleNamespace(
        name="Drum Rack",
        class_name="DrumGroupDevice",
        drum_pads=(
            SimpleNamespace(note=36, name="Kick", chains=(chain("Kick Chain", "Kick Sampler"),)),
            SimpleNamespace(note=38, name="Snare", chains=(chain("Snare Chain", "Snare"),)),
        ),
        _live_ptr="device-drum-rack",
    )
    track = SimpleNamespace(
        name="Drums",
        color_index=None,
        devices=(rack,),
        clip_slots=(SimpleNamespace(has_clip=True, clip=_Clip()),),
        view=SimpleNamespace(selected_device=rack),
        _live_ptr="track-drums",
    )
    surface = AbletonianBridgeControlSurface.__new__(AbletonianBridgeControlSurface)
    surface.song = SimpleNamespace(view=SimpleNamespace(selected_track=track))
    return RemoteScriptAdapter(_SurfaceBridge(surface))


def both() -> list[tuple[str, Any]]:
    return [("fake", fake_adapter()), ("remote_script", remote_script_adapter())]


class ProtocolContractTests(unittest.TestCase):
    def test_both_are_daw_adapters(self) -> None:
        for name, adapter in both():
            with self.subTest(adapter=name):
                self.assertIsInstance(adapter, DawAdapter)

    def test_fake_health_validates(self) -> None:
        health = fake_adapter().health()
        self.assertIsInstance(health, AdapterHealth)
        self.assertEqual(health.capabilities, fake_adapter().capabilities())

    def test_fake_capabilities_name_only_what_it_implements(self) -> None:
        adapter = fake_adapter()
        for operation in OPERATIONS.values():
            with self.subTest(operation=operation.name):
                advertised = operation.capability in adapter.capabilities()
                implemented = _implemented(adapter, operation.name)
                self.assertEqual(advertised, implemented)

    def test_unmodelled_operations_say_so(self) -> None:
        adapter = fake_adapter()
        with self.assertRaises(UnsupportedOperation):
            adapter.list_tracks(TrackQuery())
        with self.assertRaises(UnsupportedOperation):
            adapter.set_mixer(MixerChange(track=0, mute=True))


def _implemented(adapter: FakeAbletonAdapter, operation: str) -> bool:
    """True unless the fake raises UnsupportedOperation for this operation.

    A refusal for this fixture (for example no rack selected) still counts as
    implemented; only UnsupportedOperation means "not modelled".
    """

    method = getattr(adapter, "apply_batch" if operation == "batch" else operation)
    try:
        if operation in ("plan_drum_rack_extraction", "execute_drum_rack_extraction"):
            method()
        elif operation == "get_selected_rack_macros":
            method(RackRef())
        else:
            method(None)  # unmodelled methods refuse before reading the request
    except UnsupportedOperation:
        return False
    except AdapterRefused:
        return True
    return True


class DrumRackPlanContractTests(unittest.TestCase):
    def plans(self) -> dict[str, dict[str, Any]]:
        return {name: adapter.plan_drum_rack_extraction() for name, adapter in both()}

    def test_same_operation_and_mode(self) -> None:
        for name, plan in self.plans().items():
            with self.subTest(adapter=name):
                self.assertEqual(plan["operation"], "split_drum_rack")
                self.assertEqual(plan["mode"], "dry_run")
                self.assertTrue(plan["requires_confirmation"])

    def test_same_target(self) -> None:
        plans = self.plans()
        self.assertEqual(plans["fake"]["target"], plans["remote_script"]["target"])

    def test_same_output_tracks(self) -> None:
        # Known difference, excluded on purpose: "color". The fake takes the
        # pad's (or track's) hex colour; the Remote Script takes the chain's
        # Live palette index first. Nothing in the server reads it yet;
        # reconciling it is part of Linear MEH-21.
        def summary(plan: dict[str, Any]) -> list[dict[str, Any]]:
            return [
                {key: value for key, value in output.items() if key != "color"}
                for output in plan["output_tracks"]
            ]

        plans = self.plans()
        self.assertEqual(summary(plans["fake"]), summary(plans["remote_script"]))
        self.assertEqual(
            summary(plans["fake"]),
            [
                {
                    "source_pad": {"note": 36, "name": "Kick", "chain_name": "Kick Chain"},
                    "name": "Drums - Kick",
                    "devices": ["Kick Sampler"],
                    "midi_filter": {"keep_pitch": 36},
                    "clip_note_count": 2,
                }
            ],
        )

    def test_same_steps_preserves_and_warnings(self) -> None:
        plans = self.plans()
        for key in ("steps", "preserves", "warnings"):
            with self.subTest(key=key):
                self.assertEqual(plans["fake"][key], plans["remote_script"][key])
        self.assertEqual(len(plans["fake"]["warnings"]), 1)
        self.assertIn("Snare", plans["fake"]["warnings"][0])


class ServerWithFakeTests(unittest.TestCase):
    """build_mcp(adapter=FakeAbletonAdapter) runs the real tools with no bridge."""

    def call(self, tool: str, args: dict[str, Any]) -> str:
        mcp = build_mcp(AbletonianConfig(), adapter=fake_adapter())
        result = asyncio.run(mcp.call_tool(tool, args))
        return result.content[0].text  # type: ignore[attr-defined, no-any-return]

    def test_plan_tool_runs_on_the_fake(self) -> None:
        self.assertIn('"split_drum_rack"', self.call("plan_drum_rack_extraction", {}))

    def test_unmodelled_tool_is_refused_before_reaching_the_fake(self) -> None:
        text = self.call("list_tracks", {})
        self.assertIn("Not supported", text)
        self.assertIn("Nothing was sent", text)


if __name__ == "__main__":
    unittest.main()
