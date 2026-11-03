import unittest

import _bootstrap  # noqa: F401

from abletonian.adapters.fake import (
    FakeAbletonAdapter,
    FakeAbletonState,
    FakeClip,
    FakeDrumPad,
    FakeDrumRackDevice,
    FakeMidiNote,
    FakeTrack,
)
from abletonian.bridge.protocol import PROTOCOL_VERSION


def drum_rack_fixture() -> FakeAbletonState:
    """Return a small Live-like state with one selected Drum Rack track."""

    drum_rack = FakeDrumRackDevice(
        id="device-drum-rack",
        name="Drum Rack",
        pads=(
            FakeDrumPad(
                note=36,
                name="Kick",
                chain_name="Kick Chain",
                color="#d94f30",
                devices=("Kick Synth",),
            ),
            FakeDrumPad(
                note=38,
                name="Snare",
                chain_name="Snare Chain",
                color="#3b82f6",
                devices=("Snare Sampler", "Compressor"),
            ),
            FakeDrumPad(
                note=42,
                name="Closed Hat",
                chain_name="Hat Chain",
                color="#f2c94c",
                devices=("Hat Sampler",),
            ),
        ),
    )
    clip = FakeClip(
        id="clip-beat",
        name="Beat",
        notes=(
            FakeMidiNote(pitch=36, start=0.0, duration=0.25, velocity=108),
            FakeMidiNote(pitch=38, start=0.5, duration=0.25, velocity=96),
            FakeMidiNote(pitch=36, start=1.0, duration=0.25, velocity=104),
        ),
    )
    track = FakeTrack(
        id="track-drums",
        name="Drums",
        color="#8b5cf6",
        clips=(clip,),
        devices=(drum_rack,),
    )
    return FakeAbletonState(
        live_version="12.1.0",
        tracks=(track,),
        selected_track_id="track-drums",
        selected_device_id="device-drum-rack",
    )


class FakeAbletonAdapterTests(unittest.TestCase):
    def test_health_reports_protocol_version_adapter_identity_and_capabilities(self) -> None:
        adapter = FakeAbletonAdapter(drum_rack_fixture())

        health = adapter.handle_request("daw.health", {"target_daw": "ableton"})

        self.assertEqual(health["target_daw"], "ableton")
        self.assertEqual(health["adapter_type"], "fake")
        self.assertEqual(health["adapter_version"], "0.1.0")
        self.assertEqual(health["live_version"], "12.1.0")
        self.assertEqual(health["protocol_version"], PROTOCOL_VERSION)
        self.assertIn("read_selected_context", health["capabilities"])
        self.assertIn("plan_drum_rack_extraction", health["capabilities"])
        self.assertIn("execute_drum_rack_extraction", health["capabilities"])

    def test_plans_drum_rack_extraction_as_a_non_mutating_dry_run(self) -> None:
        adapter = FakeAbletonAdapter(drum_rack_fixture())

        plan = adapter.handle_request("workflow.plan_drum_rack_extraction", {})

        self.assertEqual(plan["operation"], "split_drum_rack")
        self.assertEqual(plan["mode"], "dry_run")
        self.assertEqual(
            plan["target"],
            {
                "track_id": "track-drums",
                "track_name": "Drums",
                "device_id": "device-drum-rack",
                "device_name": "Drum Rack",
            },
        )
        self.assertEqual(
            [output["name"] for output in plan["output_tracks"]],
            ["Drums - Kick", "Drums - Snare"],
        )
        self.assertEqual(plan["output_tracks"][0]["midi_filter"], {"keep_pitch": 36})
        self.assertEqual(plan["output_tracks"][1]["midi_filter"], {"keep_pitch": 38})
        self.assertEqual(plan["steps"][0], {"action": "duplicate_track", "count": 2})
        self.assertEqual(plan["preserves"], ["source_track", "source_clips", "source_devices"])
        self.assertTrue(plan["requires_confirmation"])
        self.assertIn(
            "Skipped 1 drum pad without matching MIDI notes: Closed Hat",
            plan["warnings"],
        )

    def test_fake_execution_requires_confirmation(self) -> None:
        adapter = FakeAbletonAdapter(drum_rack_fixture())

        with self.assertRaisesRegex(Exception, "requires confirmation"):
            adapter.handle_request("workflow.execute_drum_rack_extraction", {})

    def test_fake_execution_returns_manifest_and_filtered_post_state(self) -> None:
        adapter = FakeAbletonAdapter(drum_rack_fixture())

        result = adapter.handle_request(
            "workflow.execute_drum_rack_extraction",
            {"confirm": True},
        )

        self.assertEqual(result["operation"], "split_drum_rack")
        self.assertEqual(result["mode"], "execute")
        self.assertEqual(
            result["touched_tracks"],
            [track["id"] for track in result["created_tracks"]],
        )
        self.assertEqual(
            result["backout"]["primary"],
            "Use Live Undo 4 times to remove the 2 new tracks "
            "(2 steps per track: the duplicate, then its name and colour).",
        )
        self.assertFalse(result["verification"]["mutates_real_ableton_set"])
        self.assertEqual(
            [track["track_index"] for track in result["created_tracks"]], [1, 2]
        )
        self.assertEqual(
            [track["clips"][0]["removed_note_count"] for track in result["created_tracks"]],
            [1, 2],
        )
        self.assertEqual(result["preserved_tracks"], ["track-drums"])
        self.assertEqual(
            [track["name"] for track in result["created_tracks"]],
            ["Drums - Kick", "Drums - Snare"],
        )
        self.assertEqual(
            [track["clips"][0]["note_pitches"] for track in result["created_tracks"]],
            [[36], [38]],
        )
        self.assertEqual(
            [track["clips"][0]["note_count"] for track in result["created_tracks"]],
            [2, 1],
        )
        self.assertEqual(
            result["post_state"]["track_names"],
            ["Drums", "Drums - Kick", "Drums - Snare"],
        )
        self.assertEqual(result["post_state"]["track_count"], 3)
        self.assertIn(
            "Skipped 1 drum pad without matching MIDI notes: Closed Hat",
            result["warnings"],
        )


if __name__ == "__main__":
    unittest.main()
