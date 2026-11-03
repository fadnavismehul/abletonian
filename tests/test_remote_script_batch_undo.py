"""A per-operation batch runs each operation in its own Live callback.

In Live 12.4.16 parameter changes made in one main-thread callback merged into
one undo step even across separate begin/end_undo_step pairs, so an
``atomic=false`` batch of three volume changes undid in one press (issue #26,
step 9). These tests pin the fix: one scheduled callback per operation, each
a tick after the previous one.
"""

import unittest

import _bootstrap  # noqa: F401
from _bridge_key import TEST_KEY, StaticKey
from test_live_ops import Song

from remote_scripts.Abletonian import bridge_server
from remote_scripts.Abletonian.bridge_server import (
    AbletonianBridgeControlSurface,
    _decode_frame,
    _dispatch_frame,
    _encode_frame,
)


class SchedulingSurface(AbletonianBridgeControlSurface):
    """Runs scheduled callbacks at once and records each one."""

    def __init__(self, song):  # no socket server
        self.song = song
        self.callbacks = []
        self._bridge_key = StaticKey()

    def schedule_message(self, delay, callback):
        callback()
        self.callbacks.append((delay, list(self.song.undo_steps)))


def volumes(*values):
    return [
        {"method": "ableton.set_mixer", "params": {"track": i, "volume": value}}
        for i, value in enumerate(values)
    ]


def dispatch(surface, params):
    frame = _encode_frame(
        {"id": "r1", "method": "ableton.batch", "params": params, "key": TEST_KEY}
    )
    return _decode_frame(_dispatch_frame(surface, frame))


class PerOperationBatchTests(unittest.TestCase):
    def test_each_operation_runs_in_its_own_callback_a_tick_later(self):
        song = Song()
        surface = SchedulingSurface(song)

        response = dispatch(surface, {"atomic": False, "operations": volumes(0.5, 0.6, 0.7)})

        self.assertTrue(response["ok"], response)
        result = response["result"]
        self.assertEqual(result["undo_steps"], "per_operation")
        self.assertIsNone(result["failed"])
        self.assertEqual(len(result["completed"]), 3)
        # One callback checks the batch, then one per operation, each a tick
        # after the last and each holding exactly one begin/end pair.
        self.assertEqual(
            surface.callbacks,
            [
                (0, []),
                (1, ["begin", "end"]),
                (1, ["begin", "end"] * 2),
                (1, ["begin", "end"] * 3),
            ],
        )
        self.assertEqual(
            [track.mixer_device.volume.value for track in song.tracks], [0.5, 0.6, 0.7]
        )

    def test_failure_stops_the_batch_and_reports_what_completed(self):
        song = Song()
        surface = SchedulingSurface(song)
        operations = volumes(0.5) + [
            {"method": "ableton.set_mixer", "params": {"track": "Missing", "volume": 0.5}}
        ] + volumes(0.9)

        result = dispatch(surface, {"atomic": False, "operations": operations})["result"]

        self.assertEqual(len(result["completed"]), 1)
        self.assertEqual(result["failed"]["index"], 1)
        self.assertIn("may still count it", result["note"])
        self.assertEqual(len(surface.callbacks), 3)  # the last operation never ran
        self.assertEqual(song.tracks[0].mixer_device.volume.value, 0.5)

    def test_malformed_batch_changes_nothing(self):
        song = Song()
        surface = SchedulingSurface(song)
        operations = volumes(0.5) + [
            {"method": "ableton.delete_device", "params": {"track": 0, "device": 0}}
        ]

        response = dispatch(surface, {"atomic": False, "operations": operations})

        self.assertFalse(response["ok"])
        self.assertIn("confirm", response["error"]["message"])
        self.assertEqual(surface.callbacks, [(0, [])])
        self.assertEqual(song.undo_steps, [])

    def test_operations_after_the_deadline_are_not_run(self):
        song = Song()
        surface = SchedulingSurface(song)
        original = bridge_server.REQUEST_RUN_TIMEOUT_SECONDS
        bridge_server.REQUEST_RUN_TIMEOUT_SECONDS = -1
        try:
            result = dispatch(surface, {"atomic": False, "operations": volumes(0.5)})["result"]
        finally:
            bridge_server.REQUEST_RUN_TIMEOUT_SECONDS = original

        self.assertEqual(result["completed"], [])
        self.assertIn("not run", result["failed"]["error"])
        self.assertEqual(song.undo_steps, [])

    def test_atomic_batch_is_still_one_callback(self):
        song = Song()
        surface = SchedulingSurface(song)

        result = dispatch(surface, {"operations": volumes(0.5, 0.6)})["result"]

        self.assertEqual(result["undo_steps"], "one")
        self.assertEqual(surface.callbacks, [(0, ["begin", "end"])])


class DrumRackBackoutTests(unittest.TestCase):
    def test_backout_counts_two_undo_presses_per_created_track(self):
        # Live 12.4.16 took two presses per track (issue #26, step 11).
        text = bridge_server._undo_backout_text(3)

        self.assertTrue(text.startswith("Use Live Undo 6 times"), text)
        self.assertIn("3 new tracks", text)


if __name__ == "__main__":
    unittest.main()
