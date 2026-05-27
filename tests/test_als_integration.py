import pathlib
import unittest

import _bootstrap  # noqa: F401

from abletonian.adapters.fake import FakeAbletonAdapter
from abletonian.als import load_als_as_fake_state

FIRST_LIGHT_SET = pathlib.Path("testing/First Light Project/First Light.als")


@unittest.skipUnless(
    FIRST_LIGHT_SET.exists(),
    "testing/First Light Project/First Light.als is not present",
)
class AbletonSetIntegrationTests(unittest.TestCase):
    def test_loads_first_light_set_tracks_into_fake_state(self) -> None:
        state = load_als_as_fake_state(FIRST_LIGHT_SET)

        self.assertEqual(state.live_version, "12.4")
        self.assertEqual(
            [track.name for track in state.tracks],
            ["1-C78 Core Kit", "2-MIDI", "3-Audio", "4-Audio", "A-Reverb", "B-Delay"],
        )
        self.assertEqual(state.selected_track_id, "12")

    def test_loads_first_light_drum_rack_pads_and_bossa_clip_notes(self) -> None:
        state = load_als_as_fake_state(FIRST_LIGHT_SET)
        track = state.tracks[0]
        rack = track.devices[0]

        self.assertEqual(track.name, "1-C78 Core Kit")
        self.assertEqual([clip.name for clip in track.clips], ["Bossa"])
        self.assertEqual(rack.name, "C78 Core Kit")
        self.assertEqual(len(rack.pads), 16)
        pads_by_note = {pad.note: pad.name for pad in rack.pads}
        self.assertEqual(pads_by_note[38], "Snare")
        self.assertEqual(pads_by_note[41], "Kick")
        self.assertEqual(pads_by_note[42], "Closed Hi Hat")
        self.assertEqual(sorted({note.pitch for note in track.clips[0].notes}), [38, 41, 42])

    def test_first_light_set_can_plan_bossa_drum_rack_extraction(self) -> None:
        adapter = FakeAbletonAdapter(load_als_as_fake_state(FIRST_LIGHT_SET))

        plan = adapter.handle_request("workflow.plan_drum_rack_extraction", {})

        self.assertEqual(plan["operation"], "split_drum_rack")
        self.assertEqual(plan["mode"], "dry_run")
        self.assertEqual(
            [output["source_pad"]["name"] for output in plan["output_tracks"]],
            ["Snare", "Kick", "Closed Hi Hat"],
        )
        self.assertEqual(
            [output["midi_filter"]["keep_pitch"] for output in plan["output_tracks"]],
            [38, 41, 42],
        )
        self.assertEqual(
            [output["clip_note_count"] for output in plan["output_tracks"]],
            [5, 8, 16],
        )
        self.assertIn("Skipped 13 drum pads without matching MIDI notes", plan["warnings"][0])

    def test_first_light_set_can_fake_execute_bossa_drum_rack_extraction(self) -> None:
        adapter = FakeAbletonAdapter(load_als_as_fake_state(FIRST_LIGHT_SET))

        result = adapter.handle_request(
            "workflow.execute_drum_rack_extraction",
            {"confirm": True},
        )

        self.assertEqual(
            [track["name"] for track in result["created_tracks"]],
            [
                "1-C78 Core Kit - Snare",
                "1-C78 Core Kit - Kick",
                "1-C78 Core Kit - Closed Hi Hat",
            ],
        )
        self.assertEqual(
            [track["clips"][0]["note_count"] for track in result["created_tracks"]],
            [5, 8, 16],
        )
        self.assertEqual(result["post_state"]["track_count"], 9)
        self.assertEqual(result["post_state"]["track_names"][0], "1-C78 Core Kit")
        self.assertEqual(result["post_state"]["track_names"][-3:], [
            "1-C78 Core Kit - Snare",
            "1-C78 Core Kit - Kick",
            "1-C78 Core Kit - Closed Hi Hat",
        ])


if __name__ == "__main__":
    unittest.main()
