"""read_levels: track meters sampled over Live's timer ticks (issue #45).

The Live side is tested with LOM-shaped fakes and a scheduler that runs
callbacks on its own thread, standing in for Live's main thread. That only
proves the code matches our assumptions about Live (meter properties,
Song.is_playing, schedule_message ticks); it has not run in Live.
"""

import asyncio
import json
import math
import queue
import threading
import unittest
from typing import Any
from unittest import mock

import _bootstrap  # noqa: F401
from _bridge_key import TEST_KEY, StaticKey

from abletonian.adapters.base import AdapterRefused, LevelRead
from abletonian.adapters.fake import FakeAbletonAdapter
from abletonian.adapters.remote_script import LEVEL_READ_OVERHEAD_SECONDS, RemoteScriptAdapter
from abletonian.config import DEFAULT_BRIDGE_TIMEOUT, AbletonianConfig
from abletonian.policy import OPERATIONS, SafetyClass, SafetyPolicy
from abletonian.server import build_mcp
from remote_scripts.Abletonian import bridge_server, live_ops
from remote_scripts.Abletonian.bridge_server import (
    AbletonianBridgeControlSurface,
    _decode_frame,
    _dispatch_frame,
    _encode_frame,
)

# Fakes shaped like the Live Object Model ------------------------------------


class MeterTrack:
    """A track whose meters play back a list of (left, right, level) readings.

    Each read records the thread it ran on, so tests can check that only
    "Live's main thread" touched the track.
    """

    def __init__(self, name, readings=None, has_audio_output=True):
        self.name = name
        self.has_audio_output = has_audio_output
        self.readings = list(readings or [(0.5, 0.4, 0.6)])
        self.position = 0
        self.read_threads = set()
        self.volume = 0.85

    def _reading(self):
        self.read_threads.add(threading.get_ident())
        return self.readings[min(self.position, len(self.readings) - 1)]

    @property
    def output_meter_left(self):
        return self._reading()[0]

    @property
    def output_meter_right(self):
        return self._reading()[1]

    @property
    def output_meter_level(self):
        value = self._reading()[2]
        # The level is read last in each sample: move to the next reading.
        self.position += 1
        return value


class MeterSong:
    def __init__(self, tracks=None, returns=None, playing=True):
        self.tracks = tuple(tracks or (MeterTrack("Kick"), MeterTrack("Bass")))
        self.return_tracks = tuple(returns or (MeterTrack("A-Reverb"),))
        self.master_track = MeterTrack("Main")
        self.is_playing = playing
        self.transport_calls = []

    def start_playing(self):
        self.transport_calls.append("start_playing")

    def stop_playing(self):
        self.transport_calls.append("stop_playing")

    def continue_playing(self):
        self.transport_calls.append("continue_playing")


def plan(song, **params):
    return live_ops.prepare_level_read(song, params)


def run_window(song, seconds=1.0, tick=0.1, **params):
    """Sample like the bridge does, with a fake clock; returns the result."""

    window = live_ops.LevelWindow(plan(song, seconds=seconds, **params), 0.0)
    now = 0.0
    while True:
        now += tick
        if window.sample(song, now):
            return window.result()


def by_name(result):
    return {track["name"]: track for track in result["tracks"]}


# live_ops: request checks -----------------------------------------------------


class PrepareLevelReadTests(unittest.TestCase):
    def test_refuses_when_the_transport_is_not_playing(self):
        song = MeterSong(playing=False)
        with self.assertRaises(live_ops.TransportStopped) as caught:
            plan(song)
        self.assertEqual(caught.exception.code, "transport_stopped")
        self.assertIn("never starts or stops the transport", caught.exception.hint)
        self.assertEqual(song.transport_calls, [])

    def test_seconds_must_be_in_range(self):
        for bad in (0.4, 10.5, True, "4", float("nan"), None):
            with self.subTest(seconds=bad), self.assertRaises(live_ops.InvalidValue):
                plan(MeterSong(), seconds=bad)
        self.assertEqual(plan(MeterSong(), seconds=10)["seconds"], 10.0)

    def test_default_is_every_regular_track(self):
        targets = plan(MeterSong())["targets"]
        self.assertEqual([(k, i) for k, i, _ in targets], [("track", 0), ("track", 1)])

    def test_returns_and_main_are_added_on_request_without_duplicates(self):
        targets = plan(
            MeterSong(), tracks=["Bass", 1, "main"], include_returns=True, include_main=True
        )["targets"]
        self.assertEqual(
            [(k, i) for k, i, _ in targets], [("track", 1), ("master", 0), ("return", 0)]
        )

    def test_unknown_track_names_the_tracks(self):
        with self.assertRaises(live_ops.NotFound) as caught:
            plan(MeterSong(), tracks=["Snare"])
        self.assertIn("Kick", str(caught.exception))

    def test_track_count_is_capped(self):
        song = MeterSong(tracks=[MeterTrack(f"T{i}") for i in range(17)])
        with self.assertRaises(live_ops.InvalidValue) as caught:
            plan(song)
        self.assertIn("at most 16", str(caught.exception))
        plan(song, tracks=list(range(16)))

    def test_bad_shapes_are_refused(self):
        for params in ({"tracks": "Kick"}, {"include_returns": "yes"}, {"tracks": []}):
            with self.subTest(params=params), self.assertRaises(live_ops.InvalidValue):
                live_ops.prepare_level_read(MeterSong(), params)


# live_ops: the sampling window -----------------------------------------------


class LevelWindowTests(unittest.TestCase):
    def test_peak_rms_hold_and_count(self):
        kick = MeterTrack("Kick", [(0.2, 0.1, 0.3), (0.6, 0.8, 0.9), (0.4, 0.4, 0.9)])
        song = MeterSong(tracks=[kick])
        # Samples at 0.125, 0.25, 0.375, 0.5 s; the last reading repeats.
        result = run_window(song, seconds=0.5, tick=0.125)

        track = by_name(result)["Kick"]
        self.assertEqual(track["sample_count"], 4)
        self.assertEqual(track["peak"], 0.8)
        self.assertEqual(track["peak_left"], 0.6)
        self.assertEqual(track["peak_right"], 0.8)
        self.assertEqual(track["hold_peak"], 0.9)
        expected_rms = math.sqrt((0.2**2 + 0.8**2 + 0.4**2 + 0.4**2) / 4)
        self.assertAlmostEqual(track["rms_of_samples"], round(expected_rms, 4))
        self.assertEqual(track["meter"], "audio")
        self.assertEqual(result["scale"], "live_meter_position_0_to_1")
        self.assertIn("not dBFS", result["scale_note"])
        self.assertTrue(result["transport_playing"])
        self.assertEqual(result["window"]["samples"], 4)
        self.assertFalse(result["window"]["stopped_early"])

    def test_window_ends_when_its_time_is_up(self):
        result = run_window(MeterSong(), seconds=2.0, tick=0.1)
        self.assertEqual(result["window"]["samples"], 20)
        self.assertGreaterEqual(result["window"]["elapsed_seconds"], 2.0)

    def test_sample_count_is_capped_if_ticks_are_very_fast(self):
        result = run_window(MeterSong(), seconds=10.0, tick=0.0001)
        self.assertEqual(result["window"]["samples"], live_ops.MAX_LEVEL_SAMPLES)

    def test_transport_stopping_mid_window_is_reported(self):
        song = MeterSong()
        window = live_ops.LevelWindow(plan(song, seconds=4), 0.0)
        self.assertFalse(window.sample(song, 0.1))
        song.is_playing = False
        self.assertTrue(window.sample(song, 0.2))
        result = window.result()

        self.assertFalse(result["transport_playing"])
        self.assertTrue(result["window"]["stopped_early"])
        self.assertEqual(result["window"]["samples"], 1)
        self.assertIn("transport stopped", result["warnings"][0])

    def test_silent_tracks_are_called_out_not_returned_as_quiet_zeros(self):
        song = MeterSong(tracks=[MeterTrack("Kick"), MeterTrack("Pad", [(0.0, 0.0, 0.0)])])
        result = run_window(song)
        self.assertEqual(by_name(result)["Pad"]["peak"], 0.0)
        self.assertTrue(any("0.0 for the whole window on: Pad" in w for w in result["warnings"]))

    def test_midi_tracks_use_the_level_meter_and_say_so(self):
        song = MeterSong(tracks=[MeterTrack("Notes", [(0.9, 0.9, 0.5)], has_audio_output=False)])
        track = by_name(run_window(song))["Notes"]
        self.assertEqual(track["meter"], "midi")
        self.assertEqual(track["peak"], 0.5)
        self.assertNotIn("peak_left", track)

    def test_unreadable_or_bad_values_are_not_counted(self):
        class Gone:
            name = "Gone"
            has_audio_output = True

            @property
            def output_meter_left(self):
                raise RuntimeError("track was deleted")

            output_meter_right = output_meter_left
            output_meter_level = output_meter_left

        weird = MeterTrack("Weird", [(float("nan"), -1.0, "loud")])
        song = MeterSong(tracks=[Gone(), weird])
        result = run_window(song, seconds=0.5)
        tracks = by_name(result)
        for name in ("Gone", "Weird"):
            self.assertEqual(tracks[name]["sample_count"], 0)
            self.assertEqual(tracks[name]["missing_samples"], 5)
            self.assertIsNone(tracks[name]["peak"])
        self.assertTrue(any("No meter values" in w for w in result["warnings"]))

    def test_reading_changes_nothing(self):
        song = MeterSong()
        run_window(song, include_returns=True, include_main=True)
        self.assertEqual(song.transport_calls, [])
        self.assertTrue(song.is_playing)
        self.assertEqual([t.volume for t in song.tracks], [0.85, 0.85])

    def test_result_is_plain_json(self):
        json.dumps(run_window(MeterSong(), include_main=True))


# bridge_server: deferred dispatch over several ticks ---------------------------


class TickingSurface(AbletonianBridgeControlSurface):
    """A surface whose schedule_message queues callbacks for a "main thread".

    The pump thread runs them in order, advancing a fake clock one tick
    (``tick`` seconds) per callback scheduled with a delay.
    """

    def __init__(self, song, tick=0.1, run_ticks=True):
        self.song = song
        self._bridge_key = StaticKey()
        self.tick = tick
        self.run_ticks = run_ticks
        self.delays = []
        self.now = 0.0
        self.main_thread = None
        self._queue = queue.Queue()
        self._pump = threading.Thread(target=self._run, daemon=True)
        self._pump.start()

    def schedule_message(self, delay, callback):
        self.delays.append(delay)
        self._queue.put((delay, callback))

    def clock(self):
        return self.now

    def close(self):
        self._queue.put(None)
        self._pump.join(2.0)

    def _run(self):
        self.main_thread = threading.get_ident()
        while True:
            item = self._queue.get()
            if item is None:
                return
            delay, callback = item
            if not self.run_ticks and len(self.delays) > 1:
                continue  # Live stalls after the setup call
            self.now += self.tick * delay
            callback()


def dispatch_levels(surface, params):
    frame = _encode_frame(
        {"id": "r1", "method": "ableton.read_levels", "params": params, "key": TEST_KEY}
    )
    clock = getattr(surface, "clock", bridge_server._level_clock)
    with mock.patch.object(bridge_server, "_level_clock", clock):
        return _decode_frame(_dispatch_frame(surface, frame))


class DeferredDispatchTests(unittest.TestCase):
    def surface(self, song, **kwargs):
        surface = TickingSurface(song, **kwargs)
        self.addCleanup(surface.close)
        return surface

    def test_samples_on_successive_ticks_then_answers(self):
        song = MeterSong()
        surface = self.surface(song, tick=0.125)

        response = dispatch_levels(surface, {"seconds": 1.0})

        self.assertTrue(response["ok"], response)
        result = response["result"]
        # A first sample at 0 s, then one per tick up to 1 s.
        self.assertEqual(result["window"]["samples"], 9)
        self.assertEqual(result["window"]["elapsed_seconds"], 1.0)
        self.assertEqual(result["window"]["tick_delay"], bridge_server.LEVEL_SAMPLE_TICK_DELAY)
        self.assertEqual([t["name"] for t in result["tracks"]], ["Kick", "Bass"])
        # The setup call, the first sample, then one reschedule per tick.
        self.assertEqual(surface.delays, [0, 0] + [1] * 8)
        self.assertEqual(song.transport_calls, [])

    def test_meters_are_read_only_on_the_main_thread(self):
        song = MeterSong()
        surface = self.surface(song)
        self.assertTrue(dispatch_levels(surface, {"seconds": 0.5})["ok"])
        for track in song.tracks:
            self.assertEqual(track.read_threads, {surface.main_thread})
        self.assertNotEqual(surface.main_thread, threading.get_ident())

    def test_stopped_transport_is_refused_with_a_hint(self):
        song = MeterSong(playing=False)
        surface = self.surface(song)

        response = dispatch_levels(surface, {})

        self.assertFalse(response["ok"])
        self.assertEqual(response["error"]["code"], "transport_stopped")
        self.assertIn("Start playback", response["error"]["hint"])
        self.assertEqual(surface.delays, [0])  # only the setup call ran
        self.assertEqual(song.transport_calls, [])

    def test_bad_request_is_refused_before_sampling(self):
        surface = self.surface(MeterSong())
        response = dispatch_levels(surface, {"seconds": 30})
        self.assertEqual(response["error"]["code"], "invalid_value")
        self.assertEqual(surface.delays, [0])

    def test_transport_stopping_mid_read_ends_the_window(self):
        song = MeterSong()
        surface = self.surface(song)

        original = live_ops.LevelWindow.sample

        def stop_after_three(window, song_, now):
            if window.samples == 3:
                song_.is_playing = False
            return original(window, song_, now)

        with mock.patch.object(live_ops.LevelWindow, "sample", stop_after_three):
            response = dispatch_levels(surface, {"seconds": 4})

        result = response["result"]
        self.assertTrue(result["window"]["stopped_early"])
        self.assertEqual(result["window"]["samples"], 3)
        self.assertFalse(result["transport_playing"])

    def test_live_that_stops_ticking_times_out_and_changes_nothing(self):
        song = MeterSong()
        surface = self.surface(song, run_ticks=False)

        with mock.patch.object(bridge_server, "LEVEL_READ_GRACE_SECONDS", 0.05):
            response = dispatch_levels(surface, {"seconds": 0.5})

        self.assertFalse(response["ok"])
        self.assertEqual(response["error"]["code"], "timeout")
        self.assertIn("nothing was changed", response["error"]["hint"])

    def test_an_abandoned_read_does_not_reschedule(self):
        # After the socket thread gives up, a late tick must end the chain.
        song = MeterSong()
        callbacks = []

        class Surface(AbletonianBridgeControlSurface):
            def __init__(self):
                self.song = song
                self._bridge_key = StaticKey()

            def schedule_message(self, delay, callback):
                if callbacks or delay:
                    callbacks.append(callback)  # held back, like a stalled Live
                else:
                    callbacks.append(None)
                    callback()  # the setup call runs

        surface = Surface()
        with mock.patch.object(bridge_server, "LEVEL_READ_GRACE_SECONDS", 0.01):
            response = dispatch_levels(surface, {"seconds": 0.5})
        self.assertEqual(response["error"]["code"], "timeout")
        late_tick = callbacks[-1]
        count = len(callbacks)
        late_tick()
        self.assertEqual(len(callbacks), count)
        self.assertTrue(all(t.position == 0 for t in song.tracks))

    def test_without_live_timer_it_is_not_supported(self):
        class Surface(AbletonianBridgeControlSurface):
            def __init__(self):
                self.song = MeterSong()
                self._bridge_key = StaticKey()

        response = dispatch_levels(Surface(), {})
        self.assertEqual(response["error"]["code"], "not_supported")

    def test_health_lists_the_capability(self):
        surface = AbletonianBridgeControlSurface.__new__(AbletonianBridgeControlSurface)
        surface.application = None
        health = surface._health({})
        self.assertIn("read_levels", health["capabilities"])


# Python side: request, adapter, policy, tool ---------------------------------


class RecordingBridge:
    def __init__(self, timeout: float | None = DEFAULT_BRIDGE_TIMEOUT) -> None:
        self.timeout = timeout
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def request(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        self.calls.append((method, params or {}))
        return {"tracks": [], "window": {}}


class LevelReadRequestTests(unittest.TestCase):
    def test_limits_match_the_remote_script(self):
        self.assertEqual(LevelRead.MIN_SECONDS, live_ops.LEVEL_MIN_SECONDS)
        self.assertEqual(LevelRead.MAX_SECONDS, live_ops.LEVEL_MAX_SECONDS)
        self.assertEqual(LevelRead.MAX_TRACKS, live_ops.MAX_LEVEL_TRACKS)
        self.assertEqual(LevelRead().seconds, live_ops.LEVEL_DEFAULT_SECONDS)

    def test_bad_requests_are_refused(self):
        for kwargs in (
            {"seconds": 0.1},
            {"seconds": 11},
            {"seconds": True},
            {"seconds": float("nan")},
            {"tracks": ()},
            {"tracks": tuple(range(17))},
        ):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                LevelRead(**kwargs)

    def test_params(self):
        self.assertEqual(
            LevelRead(tracks=["Kick", 2], seconds=2, include_main=True).params(),
            {"tracks": ["Kick", 2], "seconds": 2, "include_returns": False, "include_main": True},
        )


class TimeoutBudgetTests(unittest.TestCase):
    def test_overhead_covers_the_remote_script_waits(self):
        self.assertGreater(
            LEVEL_READ_OVERHEAD_SECONDS,
            bridge_server.REQUEST_START_TIMEOUT_SECONDS + bridge_server.LEVEL_READ_GRACE_SECONDS,
        )

    def test_default_client_timeout_outlasts_the_longest_read(self):
        self.assertGreaterEqual(
            DEFAULT_BRIDGE_TIMEOUT, LevelRead.MAX_SECONDS + LEVEL_READ_OVERHEAD_SECONDS
        )
        self.assertLessEqual(
            LevelRead.MAX_SECONDS + bridge_server.LEVEL_READ_GRACE_SECONDS,
            bridge_server.REQUEST_RUN_TIMEOUT_SECONDS,
        )


class LevelAdapterTests(unittest.TestCase):
    def test_sends_the_bridge_method(self):
        bridge = RecordingBridge()
        RemoteScriptAdapter(bridge).read_levels(LevelRead(tracks=("Kick",), seconds=1))
        self.assertEqual(
            bridge.calls,
            [
                (
                    "ableton.read_levels",
                    {
                        "tracks": ["Kick"],
                        "seconds": 1,
                        "include_returns": False,
                        "include_main": False,
                    },
                )
            ],
        )

    def test_short_client_timeout_is_refused_before_sending(self):
        bridge = RecordingBridge(timeout=10.0)
        with self.assertRaises(AdapterRefused) as caught:
            RemoteScriptAdapter(bridge).read_levels(LevelRead(seconds=4))
        self.assertEqual(caught.exception.code, "bridge_timeout_too_short")
        self.assertIn("ABLETONIAN_BRIDGE_TIMEOUT", str(caught.exception))
        self.assertEqual(bridge.calls, [])

    def test_bridge_without_a_timeout_attribute_is_sent(self):
        bridge = RecordingBridge(timeout=None)
        RemoteScriptAdapter(bridge).read_levels(LevelRead())
        self.assertEqual(len(bridge.calls), 1)


class LevelPolicyTests(unittest.TestCase):
    def test_realtime_read_is_annotated_read_only(self):
        operation = OPERATIONS["read_levels"]
        self.assertIs(operation.safety_class, SafetyClass.REALTIME)
        annotations = operation.annotations()
        self.assertTrue(annotations.read_only_hint)
        self.assertFalse(annotations.destructive_hint)

    def test_logged_as_realtime(self):
        bridge = RecordingBridge()
        adapter = RemoteScriptAdapter(bridge)
        policy = SafetyPolicy(adapter, clock=lambda: 1.0)
        request = LevelRead()
        policy.run("read_levels", request, lambda: adapter.read_levels(request))
        self.assertIs(policy.log[-1].safety_class, SafetyClass.REALTIME)


def call_tool(adapter_or_bridge: Any, args: dict[str, Any], fake: bool = False) -> str:
    if fake:
        mcp = build_mcp(AbletonianConfig(), adapter=adapter_or_bridge)
    else:
        mcp = build_mcp(AbletonianConfig(), bridge=adapter_or_bridge)
    result = asyncio.run(mcp.call_tool("read_levels", args))
    return result.content[0].text  # type: ignore[attr-defined, no-any-return]


class LevelToolTests(unittest.TestCase):
    def test_tool_sends_the_request(self):
        bridge = RecordingBridge()
        call_tool(bridge, {"tracks": ["Kick", 0], "seconds": 2.5, "include_returns": True})
        self.assertEqual(
            bridge.calls,
            [
                (
                    "ableton.read_levels",
                    {
                        "tracks": ["Kick", 0],
                        "seconds": 2.5,
                        "include_returns": True,
                        "include_main": False,
                    },
                )
            ],
        )

    def test_out_of_range_seconds_are_refused_locally(self):
        bridge = RecordingBridge()
        text = call_tool(bridge, {"seconds": 60})
        self.assertIn("seconds must be from 0.5 to 10.0", text)
        self.assertIn("Nothing was read.", text)
        self.assertEqual(bridge.calls, [])

    def test_fake_adapter_says_it_cannot(self):
        text = call_tool(FakeAbletonAdapter(), {}, fake=True)
        self.assertIn("cannot read levels", text)


if __name__ == "__main__":
    unittest.main()
