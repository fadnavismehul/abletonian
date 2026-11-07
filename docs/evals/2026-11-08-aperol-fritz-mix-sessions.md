# Evals pass: Aperol Fritz mix sessions, 2026-11-01 to 2026-11-06

Tracking issue: [#52](https://github.com/fadnavismehul/abletonian/issues/52).
Previous pass of the same kind: [#13](https://github.com/fadnavismehul/abletonian/issues/13)
(2026-11-01, written during the first session).

## Setup

- Set: "Aperol Fritz - Mix.als", about 30 tracks with groups, five returns,
  two Drum Racks, Valhalla Supermassive on a return, several Instrument Racks.
- Live 12.4.16 Suite, macOS 27.2. Adapter 0.6.0 on 2026-11-01, 0.6.1 from
  2026-11-03 (main at 79c6e74).
- Client: Claude Code desktop, MCP server `abletonian` registered at user
  scope. The client truncates any tool result above about 50k characters and
  writes it to a file instead.
- Five mix sessions with abletonian active: 2026-11-01, 11-03, 11-04, 11-05,
  11-06, plus one read-only subagent on 11-05. Earlier sessions (10-31, 11-01
  morning) edited the gzipped `.als` directly and are the baseline the live
  bridge replaced.

## Counts

156 abletonian tool calls, after removing one duplicated transcript.

| Outcome | Calls | Notes |
| --- | --- | --- |
| Did what was asked | 134 | |
| Result too big for the client | 15 | 12 `list_devices`, and 3 `list_tracks` in the 11-01 session before compact mode landed |
| Bridge error returned | 7 | see below |
| Batch stopped on a failed operation | 5 | the batch reported what completed and what failed |

By tool: `list_devices` 54, `apply_batch` 38, `list_tracks` 19,
`insert_device` 14, `set_device_parameter` 13, `check_bridge_health` 4,
`delete_device` 3, `plan_drum_rack_extraction` 3, `set_mixer` 3,
`create_return_track` 2, `generate_macro_cockpit` 2, `search_ableton_manual` 1.

Bridge errors, each once unless noted:

- `invalid_value`: `set_device_parameter(value="__read__")`, the agent
  wanted to read one parameter and had no tool for it (#42).
- `timeout`: "Live was busy and did not start the request; nothing changed".
  Retry worked.
- connection refused on 127.0.0.1:39877 in a subagent while Live was closed.
  The message named the port change after the upgrade, which was right.
- `not_found`: `delete_device` twice after the musician had already removed
  the device by hand. The error listed the devices on the track, which was
  enough to recover.
- `adapter_error` (0.6.0): "could not find a value of 'LowCut' that shows
  '400 Hz'; closest was '10 Hz'" on Valhalla Supermassive (#16), and
  "no device named 'Reverb' on '15-Drama Synth'" before rack paths existed
  (#17, fixed).

Batch stops: Glue Compressor `Release` by display text, three times across
two sessions (#44); Echo `L Synced` (#44); a guessed EQ Eight parameter
name "Resonance" twice (the error listed the real names and the next call
was right).

## What worked

Worth protecting in future changes.

- Display text for most stock parameters: "-3 dB", "250 Hz", "1.50 kHz",
  "High Pass 12dB", "Low Shelf", "25L", "4.00 : 1", "80.0 ms", "On". Dozens
  of EQ Eight, Compressor, Saturator and Utility settings landed first time.
- `insert_device` with `parameters` in one call, and batches of 10 to 20
  operations mixing inserts and parameter sets.
- Rack paths such as "Kit-ClassicMuffle/Snare Hit b ClassicMuffle/Snare Hit
  b ClassicMuffle" and Drum Rack return chains resolved after PR #21.
- `atomic: false` on `apply_batch` was used from 11-04 on, after the
  musician asked for per-step undo on 11-01. Each operation became its own
  undo step.
- `plan_drum_rack_extraction` warned about pads with no MIDI notes instead
  of making empty tracks.
- Error text. Every bridge error told the agent what to do next (use a raw
  value, use `list_devices`, use an index). The agent recovered in one turn
  each time except for the oversized results.
- `create_return_track` and `delete_device` with `confirm: true`, both asked
  for in #13, were used without trouble.

## Limitations found

Each one cost the musician a manual step or the agent a wasted turn.

### Reads that do not fit (#42)

`list_devices` on a track with a Drum Rack returns 1.7 to 2.5 MB; on the
whole set 3.9 MB. 12 calls overflowed. Each time the agent ran `jq` over the
saved file to find one device or one parameter, sometimes several times in
a row. There is no way to get one device's parameters without the whole
track, and no way to read one parameter at all. `include_parameters=false`
exists but was only found late.

### Raw and display confusion (#43)

`set_device_parameter(..., "2 Q A", 1)` set Q to raw 1.0, which EQ Eight
shows as 18.0. The string "1.00 " gave Q 1.00. The result showed
`after.display: "18.0"`, so the agent caught it and fixed it, but the set
was changed first.

### Stepped parameters (#44)

Glue Compressor Release shows ".1" to "A" and takes neither "Auto" nor a
number; Attack and Ratio on Glue are the same, and the agent ended up
sending raw index values. Echo "L Synced" showed "1/64" at every probe
point, so the probe could not match "1/8". The Release failure inside
`insert_device` rolled the device back and left an empty undo step, twice.

### No meters (#45)

Level matching compressors (RMS on and off, then Output) was all done by the
musician reading meters, on every track. On 11-04 the agent said the makeup
gain was not needed and was wrong, because it had no reading. On 11-03 the
guessed thresholds did not engage and the musician set them by the gain
reduction meter. Mix balance checks needed a bounce plus offline
measurement (ffmpeg ebur128, pyloudnorm).

### Hands on the mouse

- Rename a device to tell two Compressors apart (#46).
- Create a MIDI track for a synth bass, create an audio track for a
  parallel vocal chain (#47).
- Place MIDI notes: the agent wrote a `.mid` file, the musician imported it
  (#48). Drum rolls and fills were edited by hand.
- Fix a Compressor's sidechain after its source track was deleted; the
  agent could not even see the routing (#49).
- Lower one loud word by splitting a clip and dropping its clip gain (#50).
- Load a kit preset and samples onto Drum Rack pads; the agent generated an
  `.adg` by editing XML instead (#51). Related to #22 for plugins.
- Turn down a Drum Rack's Reverb macro (#8).
- Set Supermassive LowCut and HighCut (#16).
- Draw every send throw and ride as automation (#20).

### Agent-side habits worth a tool note

Not bugs, but the docstrings could prevent them:

- Guessing parameter names ("4 Resonance A") instead of reading them. A
  compact `list_devices` would make reading cheap enough to do first.
- Setting compressor thresholds blind. Until #45 lands, the docs could say
  that thresholds need the musician's meter.
- Calling `list_devices` on a Drum Rack track with parameters on. The
  docstring should warn about size.

## Automation targets

The goal is that nothing in "Hands on the mouse" stays manual. Each step,
and the tool that should take it over:

| Manual step this week | Times | Issue | Route |
| --- | --- | --- | --- |
| Export a bounce, rename it, hand it over for measurement | 7 | #55 | UI-driven (#54) |
| Press Cmd+S at the end of a session | every session | #56 | UI-driven |
| Make groups and drag tracks into them | 1 big pass | #57 | UI-driven |
| Split a clip to fix one word | 1 | #58 then #50 | UI-driven, then bridge |
| Draw send throws and rides | every session | #59 after #20 | bridge, needs RFC |
| Level-match compressors by RMS on and off | every compressor | #60 after #45 | bridge |
| Set thresholds by the GR meter | every compressor | #60 after #45 | bridge |
| Rename a device | 1 | #46 | bridge |
| Create a MIDI or audio track | 2 | #47 | bridge |
| Import a `.mid` the agent wrote | 1 | #48, interim #51 | bridge |
| Reselect a compressor's sidechain source | 1 | #49 | bridge |
| Drag an `.adg` or samples onto drum pads | 1 | #51 | bridge via browser |
| Turn down a rack macro | 1 | #8, note added | may already work |
| Set Supermassive LowCut and HighCut | 2 | #16 | bridge |

Out of reach even with the UI route: nothing on this list. Reordering
tracks by drag is the only one deferred, inside #57.

## Out of reach of the Live API

Exporting audio, saving the set, creating groups, reordering tracks and
splitting clips have no Live Object Model call. They are not bugs in the
bridge. #54 proposes driving Live's UI for them instead. Until then the
session pattern that worked was: the agent asks for one bounce, measures it
offline, and reports back.

## Method

Transcripts under the Claude Code project folder for
`/Volumes/disco/Ableton/Projects`, files modified in the eight days before
2026-11-08. A script paired every `tool_use` with its `tool_result`,
kept the `mcp__abletonian__*` calls, and classified results by whether the
client truncated them, the text started with "Bridge error", or the batch
JSON had a non-null `failed`. User messages and assistant text were then
searched for "can't", "by hand", "manually" and the tool names to find
limitations that never produced an error because the agent knew not to try.
