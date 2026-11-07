"""Arrangement clips and audio clip gain (issue #50), against LOM-shaped fakes.

The fakes follow the Cycling '74 LOM docs: ``Track.arrangement_clips``
(Live 11+), and ``Clip.name``, ``start_time``, ``end_time``,
``is_audio_clip``, ``muted``, ``gain`` (normalized 0..1) and
``gain_display_string``. The gain-to-dB curve below is invented; the real
one is unknown, which is why the script searches the display text instead
of computing dB. Not validated in Live.
"""

import math
import unittest

import _bootstrap  # noqa: F401
from test_live_ops import Song

from remote_scripts.Abletonian import live_ops
from remote_scripts.Abletonian.live_ops import InvalidValue, LiveOpsError, NotFound, NotSupported


def gain_text(gain):
    # Invented, non-linear: 0 shows "-inf dB", 1 shows "24.0 dB".
    if gain <= 0:
        return "-inf dB"
    return f"{-70 + 94 * math.sqrt(gain):.1f} dB"


class Clip:
    def __init__(self, name, start, end, audio=True, gain=0.5, muted=False):
        self.name = name
        self.start_time = start
        self.end_time = end
        self.is_audio_clip = audio
        self.muted = muted
        self.writes = 0
        if audio:
            self._gain = gain

    @property
    def gain(self):
        if not self.is_audio_clip:
            raise RuntimeError("MIDI clips have no gain")
        return self._gain

    @gain.setter
    def gain(self, value):
        if not self.is_audio_clip:
            raise RuntimeError("MIDI clips have no gain")
        if not 0.0 <= value <= 1.0:
            raise ValueError("gain out of range")
        self.writes += 1
        self._gain = value

    @property
    def gain_display_string(self):
        if not self.is_audio_clip:
            raise RuntimeError("MIDI clips have no gain")
        return gain_text(self._gain)


class LaggingClip(Clip):
    """A display that shows the gain from before the last write."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._shown = self._gain

    @Clip.gain.setter
    def gain(self, value):
        self._shown = self._gain
        self._gain = value
        self.writes += 1

    @property
    def gain_display_string(self):
        return gain_text(self._shown)


class ClipSong(Song):
    def __init__(self):
        super().__init__()
        self.signature_numerator = 4
        self.signature_denominator = 4
        bass = self.tracks[1]
        bass.arrangement_clips = (
            Clip("Bass Intro", 0.0, 16.0, gain=0.25),
            Clip("Bass Riff", 17.5, 33.0),
            Clip("Bass Riff", 64.0, 80.0, muted=True),
        )
        self.tracks[0].arrangement_clips = (Clip("Kick MIDI", 4.0, 8.0, audio=False),)


class ListClipsTests(unittest.TestCase):
    def setUp(self):
        self.song = ClipSong()

    def call(self, method, **params):
        return live_ops.handle(self.song, method, params)

    def test_lists_arrangement_clips_with_positions_and_gain(self):
        result = self.call("ableton.list_clips", track="Bass")

        self.assertEqual(result["track"], {"kind": "track", "index": 1, "name": "Bass"})
        self.assertEqual(result["time_signature"], "4/4")
        intro, riff, muted = result["clips"]
        self.assertEqual(
            intro,
            {
                "index": 0,
                "name": "Bass Intro",
                "start_beats": 0.0,
                "end_beats": 16.0,
                "length_beats": 16.0,
                "start_bar": "1.1.1",
                "end_bar": "5.1.1",
                "is_audio": True,
                "gain": 0.25,
                "gain_display": "-23.0 dB",
            },
        )
        self.assertEqual(riff["start_bar"], "5.2.3")
        self.assertNotIn("muted", riff)
        self.assertTrue(muted["muted"])

    def test_midi_clips_have_no_gain(self):
        clip = self.call("ableton.list_clips", track=0)["clips"][0]
        self.assertFalse(clip["is_audio"])
        self.assertNotIn("gain", clip)
        self.assertEqual(clip["start_bar"], "2.1.1")

    def test_bar_positions_follow_the_time_signature(self):
        self.song.signature_numerator, self.song.signature_denominator = 6, 8
        result = self.call("ableton.list_clips", track="Bass")

        self.assertEqual(result["time_signature"], "6/8")
        # A 6/8 bar is 3 quarter notes; beat 17.5 is bar 6, eighth 6, 1st sixteenth.
        self.assertEqual(result["clips"][1]["start_bar"], "6.6.1")
        del self.song.signature_numerator
        result = self.call("ableton.list_clips", track="Bass")
        self.assertIsNone(result["time_signature"])
        self.assertIsNone(result["clips"][0]["start_bar"])

    def test_listing_does_not_change_the_set(self):
        self.call("ableton.list_clips", track="Bass")

        self.assertEqual([c.writes for c in self.song.tracks[1].arrangement_clips], [0, 0, 0])
        self.assertEqual(self.song.undo_steps, [])

    def test_tracks_without_arrangement_clips(self):
        self.assertEqual(self.call("ableton.list_clips", track="A")["clips"], [])
        self.assertEqual(self.call("ableton.list_clips", track="main")["clips"], [])
        with self.assertRaises(NotSupported):
            self.call("ableton.list_clips", track="Vox")
        with self.assertRaises(NotFound):
            self.call("ableton.list_clips", track="Nope")


class SetClipGainTests(unittest.TestCase):
    def setUp(self):
        self.song = ClipSong()
        self.clips = self.song.tracks[1].arrangement_clips

    def call(self, method, **params):
        return live_ops.handle(self.song, method, params)

    def test_sets_gain_by_display_text_as_one_undo_step(self):
        result = self.call("ableton.set_clip_gain", track="Bass", clip=0, gain_db="-3 dB")

        self.assertEqual(result["clip"], {"index": 0, "name": "Bass Intro"})
        self.assertEqual(result["before"], {"gain": 0.25, "gain_display": "-23.0 dB"})
        self.assertEqual(result["after"]["gain_display"], "-3.0 dB")
        self.assertEqual(self.clips[0].gain_display_string, "-3.0 dB")
        self.assertEqual(self.song.undo_steps, ["begin", "end"])

    def test_number_of_db_and_clip_by_hash_index_or_unique_name(self):
        self.call("ableton.set_clip_gain", track=1, clip="#1", gain_db=-6)
        self.assertEqual(self.clips[1].gain_display_string, "-6.0 dB")
        self.call("ableton.set_clip_gain", track=1, clip="bass intro", gain_db=0)
        self.assertEqual(self.clips[0].gain_display_string, "0.0 dB")

    def test_minus_infinity_and_the_top_of_the_range(self):
        self.call("ableton.set_clip_gain", track=1, clip=0, gain_db="-inf dB")
        self.assertEqual(self.clips[0].gain, 0.0)
        result = self.call("ableton.set_clip_gain", track=1, clip=0, gain_db="24 dB")
        self.assertEqual(self.clips[0].gain, 1.0)
        self.assertNotIn("note", result)

    def test_gain_just_past_the_top_is_clamped_with_a_note(self):
        result = self.call("ableton.set_clip_gain", track=1, clip=0, gain_db="25 dB")

        self.assertEqual(self.clips[0].gain, 1.0)
        self.assertIn("'24.0 dB'", result["note"])

    def test_out_of_range_gain_is_refused_and_put_back(self):
        with self.assertRaises(InvalidValue) as raised:
            self.call("ableton.set_clip_gain", track=1, clip=0, gain_db=40)

        self.assertIn("put back", str(raised.exception))
        self.assertEqual(self.clips[0].gain, 0.25)

    def test_midi_clip_is_refused_without_writing(self):
        self.song.tracks[1].arrangement_clips = (Clip("Keys", 0.0, 4.0, audio=False),)
        with self.assertRaisesRegex(InvalidValue, "MIDI clip"):
            self.call("ableton.set_clip_gain", track=1, clip=0, gain_db=-3)

    def test_bad_clip_and_gain_references(self):
        with self.assertRaisesRegex(LiveOpsError, "ambiguous.*1, 2"):
            self.call("ableton.set_clip_gain", track=1, clip="Bass Riff", gain_db=-3)
        with self.assertRaisesRegex(NotFound, "out of range"):
            self.call("ableton.set_clip_gain", track=1, clip=9, gain_db=-3)
        with self.assertRaisesRegex(NotFound, "0:Bass Intro"):
            self.call("ableton.set_clip_gain", track=1, clip="Outro", gain_db=-3)
        with self.assertRaises(InvalidValue):
            self.call("ableton.set_clip_gain", track=1, clip=0, gain_db="loud")
        for bad in (True, {"raw": 0.7}, [-3], None, float("nan")):
            with self.subTest(gain_db=bad), self.assertRaises(LiveOpsError):
                self.call("ableton.set_clip_gain", track=1, clip=0, gain_db=bad)
        self.assertEqual([c.writes for c in self.clips], [0, 0, 0])

    def test_a_display_that_lags_the_write_is_refused_and_put_back(self):
        clip = LaggingClip("Lag", 0.0, 4.0, gain=0.3)
        self.song.tracks[1].arrangement_clips = (clip,)

        with self.assertRaisesRegex(LiveOpsError, "did not follow the value"):
            self.call("ableton.set_clip_gain", track=1, clip=0, gain_db=-3)
        self.assertEqual(clip._gain, 0.3)

    def test_batch_shape_checks_gain_before_anything_runs(self):
        with self.assertRaisesRegex(InvalidValue, "operation 1.*nothing was changed"):
            self.call(
                "ableton.batch",
                operations=[
                    {
                        "method": "ableton.set_clip_gain",
                        "params": {"track": 1, "clip": 0, "gain_db": "-3 dB"},
                    },
                    {
                        "method": "ableton.set_clip_gain",
                        "params": {"track": 1, "clip": 1, "gain_db": {"raw": 0.7}},
                    },
                ],
            )
        self.assertEqual([c.writes for c in self.clips], [0, 0, 0])
        self.assertEqual(self.song.undo_steps, [])

    def test_runs_inside_a_batch(self):
        result = self.call(
            "ableton.batch",
            operations=[
                {
                    "method": "ableton.set_clip_gain",
                    "params": {"track": "Bass", "clip": 0, "gain_db": "-12 dB"},
                }
            ],
        )
        self.assertIsNone(result["failed"])
        self.assertEqual(self.clips[0].gain_display_string, "-12.0 dB")


if __name__ == "__main__":
    unittest.main()
