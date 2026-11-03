"""Bridge errors carry a code and a hint that fit the error (Linear MEH-25).

Before, every error was "adapter_error" with the hint "Check daw.health
capabilities before retrying.", which fits almost none of them (found in the
2026-11-03 Live run, issue #26).
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

OLD_HINT = "Check daw.health capabilities before retrying."


class Surface(AbletonianBridgeControlSurface):
    """The real Remote Script request handling on a fake Live Set."""

    def __init__(self, song=None):  # no socket server
        self.song = song or Song()
        self._bridge_key = StaticKey()


def error_for(method, params=None, surface=None):
    frame = _encode_frame(
        {"id": "r1", "method": method, "params": params or {}, "key": TEST_KEY}
    )
    response = _decode_frame(_dispatch_frame(surface or Surface(), frame))
    assert not response["ok"], response
    return response["error"]


class ErrorHintTests(unittest.TestCase):
    def assert_error(self, error, code, hint_contains):
        self.assertEqual(error["code"], code, error)
        self.assertIn(hint_contains, error.get("hint") or "", error)
        self.assertNotEqual(error.get("hint"), OLD_HINT)

    def test_missing_track(self):
        error = error_for("ableton.set_mixer", {"track": "Drums", "mute": True})
        self.assert_error(error, "not_found", "list_tracks")
        self.assertIn("Tracks: Kick, Bass, Vox", error["message"])

    def test_track_index_out_of_range(self):
        error = error_for("ableton.set_mixer", {"track": 9, "mute": True})
        self.assert_error(error, "not_found", "list_tracks")

    def test_missing_device(self):
        error = error_for(
            "ableton.set_device_parameter",
            {"track": 0, "device": "Reverb", "parameter": "Gain", "value": 0.5},
        )
        self.assert_error(error, "not_found", "list_devices")

    def test_missing_parameter(self):
        surface = Surface()
        error_for_insert = _dispatch_frame(
            surface,
            _encode_frame(
                {
                    "id": "r0",
                    "method": "ableton.insert_device",
                    "params": {"track": 0, "device_name": "Utility"},
                    "key": TEST_KEY,
                }
            ),
        )
        self.assertTrue(_decode_frame(error_for_insert)["ok"])
        error = error_for(
            "ableton.set_device_parameter",
            {"track": 0, "device": 0, "parameter": "Cutoff", "value": 0.5},
            surface,
        )
        self.assert_error(error, "not_found", "list_devices")

    def test_value_out_of_range(self):
        error = error_for("ableton.set_mixer", {"track": 0, "volume": 5.0})
        self.assert_error(error, "invalid_value", "range")

    def test_unknown_method_points_to_an_old_script(self):
        error = error_for("ableton.make_coffee")
        self.assert_error(error, "not_supported", "Reinstall")

    def test_undo_of_several_steps_needs_confirmation(self):
        error = error_for("ableton.undo", {"count": 2})
        self.assert_error(error, "confirmation_required", "confirm=true")

    def test_unconfirmed_delete_in_a_batch_needs_confirmation(self):
        error = error_for(
            "ableton.batch",
            {
                "operations": [
                    {"method": "ableton.delete_device", "params": {"track": 0, "device": 0}}
                ]
            },
        )
        self.assert_error(error, "confirmation_required", "confirm=true")

    def test_wrapped_batch_errors_keep_their_kind(self):
        error = error_for(
            "ableton.batch",
            {
                "operations": [
                    {
                        "method": "ableton.delete_device",
                        "params": {"track": "Nope", "device": 0, "confirm": True},
                    }
                ]
            },
        )
        self.assert_error(error, "not_found", "list_tracks")
        self.assertIn("operation 0", error["message"])

    def test_batch_failure_carries_the_failed_operation_hint(self):
        surface = Surface()
        frame = _encode_frame(
            {
                "id": "r1",
                "method": "ableton.batch",
                "params": {
                    "operations": [
                        {"method": "ableton.set_mixer", "params": {"track": 0, "mute": True}},
                        {"method": "ableton.set_mixer", "params": {"track": "X", "mute": True}},
                    ]
                },
                "key": TEST_KEY,
            }
        )
        result = _decode_frame(_dispatch_frame(surface, frame))["result"]
        self.assertEqual(result["failed"]["index"], 1)
        self.assertEqual(result["failed"]["code"], "not_found")
        self.assertIn("list_tracks", result["failed"]["hint"])

    def test_a_plain_error_gets_no_hint_rather_than_a_wrong_one(self):
        class Broken(Surface):
            def handle_request(self, method, params):
                raise RuntimeError("something odd")

        error = error_for("daw.health", surface=Broken())
        self.assertEqual(error["code"], "adapter_error")
        self.assertNotIn("hint", error)


class TimeoutHintTests(unittest.TestCase):
    def test_not_started_says_nothing_changed(self):
        class Busy(Surface):
            def schedule_message(self, delay, callback):
                pass  # Live never runs it

        original = bridge_server.REQUEST_START_TIMEOUT_SECONDS
        bridge_server.REQUEST_START_TIMEOUT_SECONDS = 0.01
        try:
            error = error_for("ableton.list_tracks", surface=Busy())
        finally:
            bridge_server.REQUEST_START_TIMEOUT_SECONDS = original
        self.assertEqual(error["code"], "timeout")
        self.assertIn("nothing was changed", error["hint"])

    def test_not_finished_says_live_may_still_apply_it(self):
        import threading

        release = threading.Event()

        class Slow(Surface):
            def schedule_message(self, delay, callback):
                threading.Thread(target=callback, daemon=True).start()

            def handle_request(self, method, params):
                release.wait(2)
                return {}

        original = bridge_server.REQUEST_RUN_TIMEOUT_SECONDS
        bridge_server.REQUEST_RUN_TIMEOUT_SECONDS = 0.05
        try:
            error = error_for("ableton.set_mixer", {"track": 0, "mute": True}, Slow())
        finally:
            bridge_server.REQUEST_RUN_TIMEOUT_SECONDS = original
            release.set()
        self.assertEqual(error["code"], "timeout")
        self.assertIn("may still apply", error["hint"])


if __name__ == "__main__":
    unittest.main()
