# RFC 0005: Hum to MIDI, with variations to choose from

**Status:** Draft  
**Created:** 2026-11-08  
**Owner:** @fadnavismehul  
**Tracking issue:** <link once accepted>

## Summary

A musician hums a melody, and Abletonian turns it into a MIDI clip in the
open Live Set. It then builds a few playable versions of that melody, each
with its own instrument, effects and note changes, so the musician can
listen and keep the one they like. The musician speaks to an MCP client
(Claude or another agent) the whole time and never has to open the clip
editor.

Live's own "Convert Melody to New MIDI Track" cannot be called from a Remote
Script or from the Extensions SDK. So the MCP server does the conversion
itself: it reads the recorded WAV file, finds the notes, cleans them up,
and writes them into Live through new bridge methods. This is a new
workflow surface and adds bridge methods, which is why it needs an RFC
(`AGENTS.md`).

## Motivation

1. **Ideas come out of the mouth first.** Many musicians can sing or hum a
   melody faster than they can play it. Getting from a hum to a usable MIDI
   part today means recording, converting, fixing the wrong notes by hand,
   picking a sound and trying alternatives. Each step is easy and the whole
   thing breaks focus. That is the kind of work `docs/product/vision.md`
   says Abletonian is for.
2. **Musicians ask for it.** "Converting Audio to MIDI" and "creating
   variations of an existing clip" are both on Ableton's 2026 AI survey
   (`docs/ableton-survey/survey.md`). Clip variations are already on the
   vision's list.
3. **The parts mostly exist.** `create_track`, `insert_device`,
   `set_track_properties` and `apply_batch` already create tracks, add Live's
   own instruments and effects, and group the work into one undo step. What
   is missing is reading the recorded audio, finding notes, and writing a
   MIDI clip.

## Design

### The flow

1. **Record.** The musician hums into an armed audio track in Live while
   the metronome plays. In the first slice the musician presses record in
   Live; the agent does not touch the transport. A file can also be brought
   in, such as a voice memo from a phone (see `import_audio_clip`).
2. **Transcribe.** The musician says "turn that into MIDI". The server finds
   the clip, reads its file, finds the notes, snaps them to the song's grid
   and scale, and writes a new MIDI clip on a new MIDI track. One undo step.
3. **Make variations.** The server builds a small grid: one MIDI track per
   sound, and one clip slot per note change. One undo step.
4. **Choose.** The musician plays clips or scenes in Live (or asks the agent
   to), then says which to keep. The others are muted, or deleted with
   `confirm=true`.

### Bridge methods

All live in `remote_scripts/Abletonian/live_ops.py` and are listed in
`daw.health`. Live Object Model names are from the Cycling '74 LOM docs as
remembered on 2026-11-08; that site could not be reached from the session
that wrote this RFC, so each is to be rechecked in the spike (see
Verification). Items marked **guess** are not confirmed at all.

| Method | Class | Live calls | Notes |
| --- | --- | --- | --- |
| `ableton.list_clips` (extended) | read-only | `Track.clip_slots`, `ClipSlot.has_clip`, `Clip.file_path`, `Clip.warping`, `Clip.start_marker`, `Clip.end_marker`, `Clip.length` | Add `view: "arrangement" \| "session"` (default `"arrangement"`, as today) and, for audio clips, `file_path`, `warping` and the markers. Session clips report their scene index. |
| `ableton.create_midi_clip` | additive | `ClipSlot.create_clip(length)`, `Clip.add_new_notes` (Live 11+), `Clip.name` | Writes a MIDI clip with notes into an empty slot. If adding notes or naming fails, the clip is deleted again (`ClipSlot.delete_clip`). Batchable. |
| `ableton.import_audio_clip` | additive | `ClipSlot.create_audio_clip(file_path)` (**guess**: added in Live 12, version not confirmed) | Puts a WAV or AIFF file into an empty slot of an audio track. Lets a phone recording or a file from the client be used. |
| `ableton.fire_clip` | realtime, changes state | `ClipSlot.fire()`, `ClipSlot.stop()`, `Song.stop_all_clips` | For listening to variations. Starts playback, so only when the musician asks. |
| `ableton.delete_track` | destructive | `Song.delete_track` | Needs `confirm=true`. Without it, returns the track, its devices and its clips. |
| `ableton.record_take` | realtime, changes state | `Track.arm`, `Track.input_routing_type`, `Track.current_monitoring_state`, `ClipSlot.fire()`, `Song.metronome`; count in is a **guess** | Third slice only. Arms a track, records a set number of bars into an empty slot, stops, and returns the new clip. Runs as a chain of Live ticks, as `read_levels` does. |

The transcriber also needs `Song.tempo`, `Song.signature_numerator`,
`Song.signature_denominator`, `Song.root_note` and `Song.scale_name` (the
last two from Live 12). They come from one small read-only method,
`ableton.get_song_info`.

### Note data shape

The same shape crosses the bridge in both directions and is what the
transcriber produces:

```json
{"pitch": 62, "start": 1.5, "duration": 0.5, "velocity": 96}
```

`pitch` is a MIDI note number 0 to 127, `start` and `duration` are in beats
from the clip start, `velocity` is 1 to 127. The Remote Script checks every
field and range before calling `add_new_notes`, and refuses more than 2,000
notes in one clip.

### Transcription, in the MCP server

New module `src/abletonian/audio/transcribe.py`. Input: a file path, the
song tempo, time signature, root note and scale, and the clip's start
offset. Output: notes in the shape above, plus a summary for the agent.

1. Load the file as mono at 22,050 Hz (`soundfile`).
2. Track pitch with pYIN (`librosa.pyin`). It handles one voice, which is
   what humming is.
3. Turn the pitch curve into notes: merge frames that stay within half a
   semitone, drop notes shorter than a 1/32 note, take velocity from the
   note's loudness.
4. Snap to the song's scale when Live has one set; otherwise snap to
   semitones. Snap start times to a grid (1/16 by default) with a strength
   from 0 to 1, so the musician can ask for "tighter" or "looser".
5. Return the notes, the range, the share of frames where pitch was found,
   and warnings such as "fewer than four notes found" or "pitch was found in
   only 30 percent of the take".

The audio never leaves the computer. The tools return notes and a summary,
never audio, so an agent cannot send the recording anywhere by accident.

These libraries are heavy, so they go in an optional extra,
`abletonian[audio]` (numpy, librosa, soundfile). Without it, the tools
refuse with a message that names the install command. The base install and
the Remote Script do not change.

### Variations, in the MCP server

New module `src/abletonian/variations.py`, plain functions from a note list
to a note list, so they are easy to test:

| Name | What it does |
| --- | --- |
| `original` | The transcription as it is. |
| `tight` | Full grid snap and equal note lengths. |
| `octave_up`, `octave_down` | Move every note by 12. |
| `harmony` | Add a note a third above, kept in the song's scale. |
| `half_time`, `double_time` | Stretch or squeeze timing by 2. |
| `simple` | Merge short repeated notes into longer ones. |
| `arpeggio` | Spread each long note into a rising pattern. |

Sounds are a small table of Live's own devices, in names `insert_device`
already accepts, for example a pad (Drift and Reverb), a pluck (Operator and
Echo) and a bass (Analog). The table is code, not a preset file, so it can
be tested. Loading the musician's own presets from Live's browser is out of
scope here.

The grid is built by one `apply_batch`: `create_track` for each sound,
`insert_device` for its chain, `set_track_properties` for name and colour,
and `create_midi_clip` for each variation in scene order. New tracks have an
empty slot in every existing scene. If the set has fewer scenes than
variations, the server asks for fewer variations rather than creating
scenes, so the layout of the musician's set is not changed.

### MCP tools

Musician facing, annotated with `_op(...)`, each through `SafetyPolicy`:

| Tool | Class | What it does |
| --- | --- | --- |
| `transcribe_clip` | additive | Turn an audio clip (by track and slot, or "the newest") into a MIDI clip on a new MIDI track. Takes `grid`, `strength` and `use_song_scale`. Returns the notes summary and warnings. |
| `import_recording` | additive | Bring an audio file into an audio track, then optionally transcribe it. |
| `make_variations` | additive | Build the sound and variation grid from a MIDI clip. Takes the sound and variation names, or picks three of each. |
| `play_variation` | realtime | Fire one clip or stop all clips. |
| `keep_variation` | transformative, or destructive with `confirm=true` | Rename and keep one variation; mute the other variation tracks, or delete them when confirmed. |
| `record_idea` | realtime | Third slice: arm, count in, record a number of bars, then transcribe. |

No tool passes raw bridge calls through.

## Safety and backout

1. `transcribe_clip`, `import_recording` and `make_variations` are each one
   Live undo step. They only add tracks and clips; the recording itself is
   never changed or deleted. If any step fails, the batch fails closed and
   deletes what it created, as `create_track` and `insert_device` already do.
2. `keep_variation` with deletion needs `confirm=true`, previews what would
   go without it, and only deletes tracks that `make_variations` created in
   this session (tracked by name and by the order they were created). It
   never deletes the original recording or the first transcription.
3. `play_variation` and `record_idea` start the transport. Their docstrings
   say to use them only when the musician asks. `record_idea` also needs
   `confirm=true`, because it opens the microphone and monitoring can feed
   back through speakers.
4. To turn the feature off, leave out the `audio` extra; the tools then
   refuse. A Remote Script without the new capabilities makes the tools
   refuse with `not_supported`, as for any missing capability.

## Verification

1. **Unit tests, no Live.** Transcription is tested on generated audio: sine
   tones at known pitches and times, with added vibrato and noise, checked
   for the right notes within a tolerance. Variations are tested as pure
   functions. `create_midi_clip`, `import_audio_clip`, `delete_track` and the
   extended `list_clips` get LOM shaped fakes in `tests/test_live_ops*.py`,
   plus adapter, contract, policy and server tests. CI installs the `audio`
   extra in at least one job.
2. **Spike in Live first (about a day).** On a copy of the First Light
   fixture, never the fixture itself: record a hummed take into a Session
   slot, read `Clip.file_path`, `warping` and the markers through the bridge,
   run the transcriber, and compare its notes with Live's own Convert Melody
   to New MIDI Track on the same clip. Also check: whether `create_audio_clip`
   exists on `ClipSlot` in Live 12.4.16, whether a recorded Session clip's
   file starts exactly at its start marker, and what `add_new_notes` does
   with notes that run past the clip end. Record the results in the
   validation log in `docs/engineering/live-control.md`.
3. **Live run for each slice**, written as a checklist with the
   `validate-in-live` skill: transcribe, undo once and see everything gone,
   build variations, undo once, keep one variation with and without
   `confirm=true`.

## Alternatives

1. **Click Live's own converter through the Mac's UI** (the
   `drive-live-on-mac` skill). It uses Ableton's converter, but it depends on
   window layout and focus, cannot be tested without Live, and gives the
   agent no way to clean up the result. Kept as a manual comparison in the
   spike only.
2. **A Max for Live device that records and converts.** Max can record, but
   it cannot call Live's converter either, and it adds a device the musician
   has to install and keep in the set.
3. **basic-pitch (Spotify) instead of pYIN.** Better on chords and dense
   audio, but it needs an ML runtime and is more than a hummed line needs.
   The transcriber keeps one function boundary so it can be added later as a
   second engine.
4. **Record in the MCP server with the computer's microphone** instead of in
   Live. It would let the musician hum without touching Live, but the take
   would not follow Live's tempo or metronome, and it adds an audio input
   dependency to the server. `import_recording` covers the case where the
   take is made elsewhere.

## Unresolved questions

1. Where the musician records: the Mac's microphone through Live, or a phone.
   If a phone, `import_audio_clip` moves into the first slice.
2. Whether `record_idea` should exist at all, or whether pressing record in
   Live is good enough.
3. Whether the variation grid should use new tracks per sound (as proposed)
   or one track with a Rack whose chains are the sounds, which would keep the
   set smaller.
4. Whether the song's scale should be used by default, or only when the
   musician asks.

## Implementation notes

Suggested order, each its own PR linked to the tracking issue:

1. Spike in Live (Verification step 2).
2. Extended `list_clips`, `create_midi_clip`, the transcriber and
   `transcribe_clip`.
3. `import_audio_clip` and `import_recording`.
4. Variations, `make_variations`, `play_variation`, `delete_track` and
   `keep_variation`.
5. `record_take` and `record_idea`, if still wanted.
