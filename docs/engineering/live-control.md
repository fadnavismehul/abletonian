# Live Set Control

The Abletonian Remote Script lets an MCP client read and change the Live Set
that is open right now. Nothing is written to the `.als` file, and you do not
need to close and reopen the set. Save in Live when you like the result.

## How it works

```text
Claude Code ──stdio MCP──▶ abletonian (Python 3.10+)
                              │  length-prefixed JSON over TCP 127.0.0.1:39877
                              ▼
                   Abletonian Remote Script (inside Live, Python 3.11)
                              │  ControlSurface.schedule_message
                              ▼
                      Live main thread ──▶ Live Object Model
```

- A socket thread inside Live accepts one request at a time.
- Each request carries the per-install key from `~/.abletonian/bridge_key`,
  which the Remote Script creates the first time it starts. A request with a
  wrong or missing key is refused on the socket thread, before anything
  reaches Live (RFC 0004).
- Every request, reads included, runs on Live's main thread through
  `schedule_message`. The socket thread never touches the Live API.
  `read_levels` runs as a chain of callbacks, one per Live tick, and answers
  when its window is over ([Reading levels](#reading-levels)).
- Live-side operations live in `remote_scripts/Abletonian/live_ops.py`. They
  take the `song` object and plain JSON, so they are unit-tested with fakes in
  `tests/test_live_ops.py`.

## Tools

| MCP tool | Bridge method | What it does |
| --- | --- | --- |
| `list_tracks` | `ableton.list_tracks` | Names, group parent, colour, output routing, volume, pan, sends, mute/solo, device names. Covers regular, return, and main tracks. The tool defaults to `detail="compact"` (levels as display text, no routing options), about a quarter of the size, so large sets fit; `detail="full"` adds raw values and the output routing choices. `name` keeps tracks whose name contains it. |
| `list_devices` | `ableton.list_devices` | Devices per track (or all tracks) with name, path, class and on/off, and rack chains with index, name and device count. Devices whose sidechain input Live exposes (Compressor) also show `sidechain: {"on", "from", "channel"}`; see [Sidechain](#sidechain). The tool defaults to `detail="compact"` (no parameters; issue #42, a full dump of one Drum Rack track reached 2.5 MB). `detail="full"` or `include_parameters=true` adds every parameter with raw value, range, display text, and options. `max_depth` (0-4, default 4) limits how many rack levels have their chains expanded; `max_depth=0` lists a Drum Rack's chains by name and device count only (`"truncated": true`). Without `detail` or `include_parameters` the bridge keeps its old default (full for one track, compact for all tracks); the tool always sends `include_parameters`. Read-only. |
| `get_device` | `ableton.get_device` | One device, by the same index, name or path the write tools take, with its parameters (raw value, display text, min/max, options, original name). `parameters` keeps only those whose name or original name contains it (case-insensitive; Utility's `Gain` alias works), or any of a list. A rack's chains are listed by name and device count only. Use it to read one value instead of a whole `list_devices` dump. Read-only. |
| `list_clips` | `ableton.list_clips` | A track's Arrangement View clips (`Track.arrangement_clips`, Live 11+): index, name, start/end/length in beats, start/end as `bar.beat.sixteenth` from the song's time signature, audio or MIDI, muted, and for audio clips `gain` (0..1) and `gain_display`. Read-only. Session View clips are not listed. Checked in Live 12.4.16 on 2026-11-08 (issue #50). |
| `read_levels` | `ableton.read_levels` | Realtime read (issue #45): sample track output meters for `seconds` (0.5 to 10, default 4) while Live plays, for up to 16 tracks (`tracks`, default every regular track; `include_returns`, `include_main`). Per track: `peak`, `rms_of_samples`, `hold_peak`, left/right peaks, `sample_count`. Meter positions 0..1, not dBFS. Never starts or stops the transport; refuses with `transport_stopped` when Live is not playing. See [Reading levels](#reading-levels). |
| `generate_macro_cockpit` | `ableton.get_selected_rack_macros` | Read the selected Rack's macros (read-only) and return a grouped Macro Cockpit spec plus a text summary. See [RFC 0002](../rfcs/0002-selected-rack-macro-cockpit.md). |
| `save_macro_cockpit` | none | Save a cockpit generated in this session as a JSON file, so it can be reopened. Cockpits are temporary until saved. |
| `list_saved_macro_cockpits` | none | List saved cockpits. |
| `open_macro_cockpit` | `ableton.get_selected_rack_macros` | Open a saved cockpit and compare it with the selected Rack; warns when the rack or its macros changed. |
| `show_macro_cockpit` | none | Write a cockpit (generated this session, or saved) as a self-contained HTML page under the cockpit folder's `views/`, and open it in the browser. Display only. |
| `set_device_parameter` | `ableton.set_device_parameter` | Set by display text (`"-3 dB"`, `"2.5 kHz"`, `"1.00"`), option or step name (`"Off"`, `"Auto"`, `"1/8"`), or raw value (`{"raw": 0.5}`). A bare number is raw unless that is ambiguous; see "How a value is read" below. The result says how the value was read (`read_as`) and may carry a `note`. |
| `set_track_output_routing` | `ableton.set_track_output_routing` | Set Audio To / MIDI To by display name, such as `Main` or a group name. |
| `set_device_sidechain` | `ableton.set_device_sidechain` | Point a Compressor's sidechain input at a source by display name (`from_track`, such as `"2-32 Pad Kit Jazz"` or just `"32 Pad Kit Jazz"` when unique) and an optional `channel` (`"Post FX"`). Transformative, one undo step, batchable. Only the routing: "S/C On" is set with `set_device_parameter`. Checked in Live 12.4.16 on 2026-11-08 (issue #49); there only Compressor exposes a sidechain, not Glue Compressor or Gate. |
| `set_clip_gain` | `ableton.set_clip_gain` | Set an arrangement audio clip's Gain in dB (`-3`, `"-3 dB"`, `"-inf dB"`). `clip` is the `list_clips` index (`0` or `"#0"`) or a unique clip name. Transformative, one undo step, batchable. See [Clips](#clips). Checked in Live 12.4.16 on 2026-11-08 (issue #50). |
| `set_track_properties` | `ableton.set_track_properties` | Rename and recolour (`"#RRGGBB"` or a palette index). Live shows a return's letter in front of its name, so a leading `A-` is dropped when renaming return A. |
| `set_device_properties` | `ableton.set_device_properties` | Rename a device (`Device.name`), at the top of a track or inside racks by its path. Transformative. Returns the name and printed path before and after; renaming can change the device's own path and a same-named sibling's (issue #46). |
| `set_chain_properties` | `ableton.set_chain_properties` | Rename a rack chain (`Chain.name`). `chain` is the rack's path plus the chain's name or index: `"Vocal Rack/Main"`, `"Drum Rack/returns/0"`. Transformative. Returns the name and path before and after. |
| `set_mixer` | `ableton.set_mixer` | Volume, pan, sends (by return name, letter, or index), mute, solo. Values are read like `set_device_parameter` values; each changed value carries `read_as` and may carry a `note`. |
| `insert_device` | `ableton.insert_device` | Insert a native device with `Track.insert_device` (Live 12.3+) at a chain position, optionally `name` it, and set its parameters right away, read as in `set_device_parameter`. Value shapes are checked before inserting; names and display text after, and a failure removes the device again. |
| `create_return_track` | `ableton.create_return_track` | Add a return track at the end (`Song.create_return_track`), with an optional name and colour. Additive. |
| `create_track` | `ableton.create_track` | Add an empty MIDI or audio track (`Song.create_midi_track(index)` / `Song.create_audio_track(index)`; index -1 or omitted appends). Optional `name`, `color` and `color_index`; if they cannot be set, the new track is deleted again (`Song.delete_track`). Returns the track as compact `list_tracks` shows it, and a note when later tracks moved down one index. Additive. Groups are not created. |
| `delete_device` | `ableton.delete_device` | Delete a device (`Track.delete_device`). Destructive: without `confirm=true` it only returns the device and its current settings. The tool accepts only a real boolean, so `"true"` or `1` is refused. In `apply_batch`, every delete needs `"confirm": true` or the whole batch is refused before anything runs, and delete targets refer to the set as it was before the batch, so deleting index 0 does not shift a later index 1. |
| `apply_batch` | `ableton.batch` | Run many changes as one Live undo step (two when it mixes parameter changes with other changes), or one step per operation with `atomic=false`. Stops at the first failure. |
| `undo_last_change` | `ableton.undo` | Live Undo, `count` times (default 1, at most 20; more than 1 needs `confirm=true`). |

Every tool carries MCP annotations (`readOnlyHint`, `destructiveHint`,
`idempotentHint`) derived from its safety class, so a client can tell reads
from changes, for example to approve reads without asking. They are hints;
`confirm=true` and the undo rules are enforced by `SafetyPolicy`, which every
tool that reaches Live goes through. Both come from the operation table in
`src/abletonian/policy.py` (RFC 0003).

### Track references

Every `track` argument accepts:

- an integer index into the regular tracks (`0` is the first track),
- a track name, matched exactly first and then case-insensitively,
- `"A"`, `"B"`, ... or `"return:0"` for return tracks,
- `"main"` or `"master"` for the main track.

Ambiguous names return an error listing the matching indexes.

### Devices inside racks

`device` arguments also take a path through racks, as `list_devices`
shows it: `"Instrument Rack/Piano/Reverb"` (rack, chain, device, repeated
for racks inside racks) or `"Drum Rack/returns/0/Limiter"` for a Drum Rack
return chain. Each part can be a name or an index. A top-level device whose
whole name matches is used first, so names that contain `/` still work.
`list_devices` lists chain devices four racks deep. Drum Rack return chains
work in Live 12.4.16. Every path `list_devices` (and the set and delete
tools) prints is checked to resolve back to that same device, and is `null`
in the rare case none does. When two siblings share a name (two Drum Rack
chains both called "Guiro Short", issue #24), that part of the path is the
index instead, as in `C78 Core Kit/4/Guiro Short`. Chain and device names
that would be misread also get the index: names that are only digits, a
chain named "returns", names with leading or trailing spaces, and names
containing `/`. For the top-level device, `#N` always means index N, even
if a device is named `#N`; it is printed instead of `N` when another device
is literally named `N`. In Live 12.4.16 (2026-11-08) all 43 paths
`list_devices` printed for First Light, including `C78 Core Kit/4/Guiro Short`,
resolved through `get_device` to the same device.

### Sidechain

Since Live 11 a Compressor is a `Live.CompressorDevice.CompressorDevice` with
`available_input_routing_types`, `available_input_routing_channels`,
`input_routing_type` and `input_routing_channel` (Cycling '74 LOM docs). The
script detects these by attribute, not by class name, so any device that has
them gets a `sidechain` entry in `list_devices` and can be set with
`set_device_sidechain`. Checked in Live 12.4.16 on 2026-11-08 (issue #49):

- Glue Compressor and Gate do not expose these properties, so they have no
  `sidechain` entry and `set_device_sidechain` refuses them with
  `not_supported`. Their sidechain can only be set in Live's UI.
- A source's `display_name` reads with the track number in front
  (`"1-C78 Core Kit"`), and the bare name (`"C78 Core Kit"`) also matched.
  The choices were the other audio tracks, the returns, Main and "No Input";
  the MIDI track without an instrument was not offered.
- The sidechain switch is a parameter named `S/C On`; it is the "External"
  button in Live's Compressor.
- Each call is one undo step. Setting the source it already has added none.

Still a guess: what `input_routing_type` reads when the source track was
deleted.

A channel that does not exist for the new source puts the old source back,
as with output routing. A wrong source or channel lists every choice Live
offers in the error itself; `list_devices` shows only the current source.

`daw.health` lists `read_device_sidechain` although no tool needs it as a
capability: it tells a client that `list_devices` reports `sidechain`, so a
device without that entry from this script has no sidechain input Live
exposes, rather than coming from an older script that never looked.

### Clips

`list_clips` reads `Track.arrangement_clips` (Live 11+) and, per clip,
`name`, `start_time`, `end_time`, `is_audio_clip`, `muted`, `gain` and
`gain_display_string` (Cycling '74 LOM docs). Times are in beats (quarter
notes). `start_bar` and `end_bar` use `Song.signature_numerator` and
`signature_denominator`, so they are off after a time signature change in
the arrangement. Return, main and group tracks list no clips. Splitting a
clip is not possible: the LOM has no call for it.

`Clip.gain` is normalized 0..1, not dB, and Live offers no conversion:
`gain_display_string` only shows the current gain. So `set_clip_gain` uses
the same display-text search as parameters, except that each probe writes
`Clip.gain` and reads `gain_display_string` back (about 130 writes for one
call, all inside the call's undo step). On a clip that is playing, those
writes may be audible as a brief jump in its level; set the gain while the
clip is not playing if that matters. Before searching it writes 0, 1, 1, 0
and refuses unless both writes of the same end show the same text and the
two ends differ, so a display that lags one write behind is caught whatever
the starting gain. On any failure the original gain is put back; if putting
it back fails too, the error says so. Text a little past either end (such as
`"25 dB"` when the top shows `24.0 dB`) is set to that end with a `note`.
Checked in Live 12.4.16 on 2026-11-08:

- `gain_display_string` changes at once after a write: `-3`, `"-6 dB"`,
  `"-inf dB"`, `"+3"` and `0` each landed on that display (`-3.00 dB` and so
  on), and `"25 dB"` was set to the top, `24.0 dB`, with a note.
- Each call is one undo step; the probe writes leave no extra ones.
- A refused value (`-200`) puts the gain back, but its probe writes still
  leave one undo step that changes nothing.
- `arrangement_clips` is an empty list on tracks without clips. A clip at
  beat 8 in 4/4 starts at `3.1.1`, so bar 1 starts at beat 0.
- `gain_db` accepts only a number with an optional `dB`, or `-inf`. Before
  this run, `"#0"` (meant as a clip reference) was read as 0 dB.
Renaming a device or chain (`set_device_properties`, `set_chain_properties`,
`insert_device` with `name`) works out the printed path again after the
rename and returns it. `Device.name` and `Chain.name` are read/write in the
Cycling '74 LOM docs. Checked in Live 12.4.16 on 2026-11-08: Live shows and
reads back the written name; renaming the chain `C78 Core Kit/4` to
"Guiro A" made the other "Guiro Short" chain's path `C78 Core Kit/Guiro Short`;
a Drum Rack chain's pad shows the new chain name. Renaming the Instrument
Rack inside a Drum Rack chain ("Snare" to "Snare X") also renamed that chain
and its pad. The returned path already shows this
(`C78 Core Kit/Snare X/Snare X`), so use the path from the result, not the
old chain name. Each rename is one undo step.

### Values by display text

Live's raw parameter values are often not in the units you see. Utility
Gain, for example, is not stored in dB. When a value is a string, the script
searches for the raw value whose display text matches, using the parameter's
own `str_for_value`. That way `"-3 dB"` or `"25L"` lands where Live shows that
number. Quantized parameters match an option name instead.

Plugin parameters can behave differently. For Valhalla Supermassive in Live
12.4.16, `str_for_value` returned the current value's text whatever value it
was given (issue #16), so display text cannot be matched. The script used to
work around this by setting the value briefly and reading `str(parameter)`,
but in Live that read still showed an earlier value, and the probe left a
"Custom Action" in the undo history. The probe is gone: matching display text
now only reads `str_for_value` and never writes the parameter. When a
plugin's display does not change across the range, or the text is an option
name the parameter does not list (Mode "Andromeda"), the call is refused with
the display at both ends and the raw range. Use raw values for plugins.

#### How a value is read (issues #43, #44)

All of this reads `str_for_value` and never writes the parameter, so a
refused value changes nothing. `DeviceParameter.str_for_value(value)`,
`is_quantized` and `value_items` ("only valid for quantized parameters") are
from the Cycling '74 LOM docs.

- **`{"raw": n}`** sets raw `n`, range-checked. This is how a caller asks
  for a raw value without any interpretation.
- **A string** is display text or an option name.
- **A bare number** (JSON number) is the raw value, except:
  - if Live shows that raw value as the same number (a 0..127 parameter
    showing `64` at raw 64), raw and display agree and it is simply set;
  - if the parameter shows plain numbers with no unit (EQ Eight Q, raw 0..1
    showing `0.10` to `18.00`) or is stepped with numbered steps (Glue
    Compressor Attack), and the number is also a display value at another
    raw value, the call is refused as ambiguous. The error names both
    readings ("1 is ambiguous for '2 Q A': as a raw value it shows as
    '18.00', but '1.00' is raw 0.443403") and the hint says to send `"1"` for the
    display value or `{"raw": 1}` for the raw one;
  - for those same parameters, a number outside the raw range is read as
    display text (Q `3` sets Q 3.00), and the result's `note` says so;
  - a parameter that shows units or option names keeps the raw reading
    (Track Volume `0.85`, Device On `0`). When Live shows something other
    than the number, the result's `note` says what it shows. A number out of
    range is refused, and the hint names the display reading.

  Issue #43 was EQ Eight Q set to raw 1.0 (showing 18.0) when the musician
  meant Q 1.00. Reading bare numbers as display text everywhere was not
  chosen: it would change what Track Volume `0.85` means for existing
  callers. Refusing only where both readings are plausible keeps those
  callers working and makes the dangerous case ask.

**Stepped parameters.** A parameter is stepped when Live marks it
`is_quantized`, or (a guess, issue #44) when it has an integer raw range of
2 to 64 whose half step shows the text of a neighbouring step. Each step `i`
is raw `min + i`. Its options are `value_items` when Live gives them, else
the `str_for_value` text of each step (up to 128 steps), and `list_devices`
lists them under `options`. Text matches a step by name (either list, case
ignored), then by number at the display's resolution (`"0.1"` matches
`.1`, `"1"` matches `1.00`, `"1 s"` matches `1000 ms`), then as the
start of exactly one step's text (`"Sp"` matches `Sparse`). Live's
abbreviations are read only through a fixed alias list: `"Auto"` matches a
step shown as `A` (Glue Compressor Release), but `"Attack"` or `"Au"` do
not. `"1/8"` is matched as text, never as the number 1.

In Live 12.4.16 Glue Compressor Release refused `"Auto"` with "does not show
numeric values (it shows '.1' to 'A')", and Attack and Ratio behaved the
same, so Live gave no `value_items` for them (or does not mark them
quantized). Either way they now resolve through their step texts. Not yet
checked in Live.

**Other parameters.** When both ends show distinct numbers, a bisection
finds the raw value (as before). Text a little past either end (within 5%,
such as `"36 dB"` on a knob that stops at 35 dB) is set to that end rather
than refused, and the result's `note` says so and quotes what Live shows
there; text further out is refused. Otherwise the script samples every integer
step of the raw range (up to 256) plus 33 evenly spaced points, matches the
text against the distinct display texts it saw, and lists them when nothing
matches. If every sample shows the same text, as Echo "L Synced" did
(`'1/64'` for every value, Live 12.4.16), the error says so: `str_for_value`
may only format the current value, or the display may depend on another
parameter such as Echo's sync mode. Which of the two applies to Echo is not
known; check in Live by reading `str_for_value` for each step with L Sync on
and off.

Some API names differ from the device UI. Utility's gain knob is `Output` in
the API; `Gain` is accepted as an alias. `list_devices` with `detail="full"`
and `get_device` show the API names; `get_device` also shows each
parameter's `original_name` (`DeviceParameter.original_name`, Cycling '74
LOM docs).

### Undo

Checked in Live 12.4.16 on 2026-11-03 (issue #26, validation log below):

- Every `ableton.*` call that changes the Set runs in its own
  `Song.begin_undo_step` / `end_undo_step` pair (since adapter 0.5.0), and
  separate calls stay separate steps: a rename followed by a volume change,
  or a new return followed by a parameter change, each took one Undo.
- Live keeps parameter value changes apart from other changes even inside one
  begin/end pair. Undo History names them `Change "<parameter>"` (for example
  `Change "Track Volume"`), and everything else "Custom Action" (or
  "Insert Device", "Duplicate Track(s)" when Live does it itself). So an
  `insert_device` with `parameters` is two steps, and so is an `apply_batch`
  that mixes parameter changes (volume, pan, sends, device parameters) with
  other changes (renames, inserts, deletes, new returns). A batch of only one
  kind is one step.
- Live merges parameter changes made in the same main-thread callback into
  one step, even across separate begin/end pairs. With adapter 0.5.0 an
  `apply_batch` with `atomic=false` of three volume changes was one step.
  Since adapter 0.5.1 the bridge runs each operation of such a batch in its
  own callback, one Live tick after the previous one finished, so Undo steps
  back through it one change at a time. The batch is still checked in full
  before anything runs, and operations not started within 25 seconds are not
  run and are reported as failed.
- Reads and `delete_device` previews (no `confirm=true`) add nothing to
  Undo History.
- The Drum Rack workflow methods (`workflow.scaffold_*` and
  `workflow.execute_*`) are not wrapped. Each created track takes two steps:
  "Duplicate Track(s)", then one for its name and colour. Execute's clip
  filtering joins the last of those. Their backout text says so (since
  0.5.1; before, it said one Undo per track).

Before adapter 0.5.0, single tool calls were not wrapped, and in Live 12.4.16
separate calls made in a row were merged into one undo step (issue #3).
Community reports (for example adamjmurray/producer-pal#1209) say begin/end
steps do not nest, so a batch never wraps its operations twice.

Expect the count to be off sometimes. A call that fails after writing and
puts things back (an `insert_device` whose `parameters` fail, an output type
restored after a bad channel) leaves a step that changes nothing: Undo
History showed one "Custom Action", and pressing Undo on it left the track as
it was. And the musician's own edits share the same history.

`undo_last_change` takes a `count` (1 to 20) and reports how many steps it
undid, stopping early when `Song.can_undo` is false. A count above 1 needs
`confirm=true` (checked by both the MCP tool and the Remote Script), because
it can reach the musician's own edits. Undo History names a step "Custom
Action" or `Change "<parameter>"`; the Live API gives no way to name it.

If setting `parameters` on a newly inserted device fails, `insert_device`
deletes that device again, so a failed call leaves the track unchanged.
Value shapes (a number, a string, or `{"raw": n}`) are checked before
inserting, so a malformed value changes nothing. Parameter names, options and
display text only exist on the inserted device, so they are checked after:
all names are resolved before any value is written, and values are then
resolved and set in the order given (one parameter's display can depend on
another). The error keeps its code and its hint suggests inserting without
parameters and reading `list_devices` first.

The insert-and-delete still leaves one "Custom Action" step that changes
nothing. The LOM's `Song` offers `begin_undo_step`, `end_undo_step` and
`undo`, but nothing to discard or rename a step (Cycling '74 LOM docs).
Calling `undo` would move the step to the redo list and, since Live merges
steps made close together (issue #3, #26), could revert the musician's own
edit. So the empty step is left and the error says so.

### Reading levels

`read_levels` (issue #45, checked in Live 12.4.16 on 2026-11-08) is the first realtime read:
it takes wall-clock time and its answer depends on what is playing, but it
changes neither the Set nor the transport and adds nothing to Undo History.

How it runs, all on Live's main thread:

1. One `schedule_message` callback checks the request, resolves the tracks
   and checks `Song.is_playing`. A stopped transport is refused with
   `transport_stopped`, so a read never returns a window of zeros as if the
   tracks were silent.
2. A sampling callback reads each track's meters, then schedules itself
   again one Live tick later (`LEVEL_SAMPLE_TICK_DELAY`). It ends when the
   window's time is up, after 400 samples, or when the transport stops
   (the result then says `stopped_early` and warns). If the transport
   stopped before the first sample, the read is refused with
   `transport_stopped` instead of answering with empty readings. If five
   ticks in a row run with the clock moving less than 10 ms (callbacks run
   in the same pass, not on Live's timer; a guess at a failure not seen in
   Live), or Live will not schedule the next tick, the read ends with an
   error.
3. The socket thread only waits for the last callback, up to the window plus
   5 s (`LEVEL_READ_GRACE_SECONDS`), then sends the answer. If Live is too
   busy it answers `timeout`; the next tick ends the chain, and since nothing
   was changed nothing needs putting back. If the bridge stops during the
   read (the Control Surface is reloaded or disconnected), it answers at once
   that nothing was changed, and the next tick ends the chain.

Nothing sleeps or loops on the main thread. While a read runs, the bridge's
single socket thread is busy, so other tool calls wait for it (at most about
20 s). abletonian refuses a read before sending it if its bridge timeout
(35 s by default) is shorter than the window plus 12 s.

Per track the result gives `peak` (the highest momentary reading, the
louder of left and right), `peak_left`, `peak_right`, `hold_peak` (the
highest `output_meter_level`), `rms_of_samples` (the root mean square of the
momentary readings: a rough loudness average at about the tick rate, not a
true signal RMS), and `sample_count`. Warnings name tracks that read 0.0 for
the whole window, tracks where only `hold_peak` caught a level, tracks that
could not be read, and MIDI tracks, and say so when fewer than 2 samples per
second were taken (stalled or skipped ticks). In Live 12.4.16 a one-shot clap
fell between samples: `peak` was 0.0 while `hold_peak` was 0.40, so short
sounds are better judged by `hold_peak`.
If abletonian's bridge client times out waiting for a read, its error says
that nothing was changed.

Live Object Model assumptions, from the Cycling '74 LOM docs (Track, Song)
as recalled. In Live 12.4.16 (2026-11-08) the meters read sensibly (the
playing drum track about 0.84, silent tracks 0.0), a stopped transport was
refused, and stopping it during a read gave `stopped_early`:

- `Track.output_meter_left` / `output_meter_right`: momentary peak per
  channel, 0.0 to 1.0, for tracks with audio output.
- `Track.output_meter_level`: hold peak of the meter, 0.0 to 1.0; for MIDI
  tracks a MIDI meter. A track with `has_audio_output` false is reported with
  `"meter": "midi"`.
- `Song.is_playing`: whether the transport runs.
- The values are meter positions, not dBFS. Live does not document the
  mapping to dB, so none is reported. That 1.0 is near 0 dBFS is a guess.
- Live's timer runs about 10 ticks a second (community knowledge, not in the
  LOM docs; in Live 12.4.16 a 4 s window took 39 samples), so a 4 s window
  gives about 40 samples. The result
  reports the real sample count and elapsed time.
- Gain reduction per device (compressors, limiters) is out of scope. It is
  probably not exposed to Remote Scripts (a guess; not checked).

### Errors

Every error from the Remote Script has a `code` and, where one fits, a
`hint` with the next step (adapter 0.6.1, Linear MEH-25). The message
names the object and lists the choices; the hint says what to do.

| Code | When | Hint, in short |
| --- | --- | --- |
| `not_found` | No such track, device, chain, parameter, return, routing or selection | Which list to check: `list_tracks`, or `list_devices` on that track |
| `invalid_value` | A value is out of range, not an option, ambiguous, or badly formed | See the parameter's range, display text and options, or send `{"raw": n}`; an ambiguous bare number names both readings |
| `not_supported` | Live or this Remote Script cannot do it | What to do instead, such as reinstalling an older Remote Script |
| `confirmation_required` | A delete or multi-step undo without `confirm=true` | Ask the user first |
| `timeout` | Live did not start, or did not finish, in time | Whether the change may still happen, and to check before retrying |
| `transport_stopped` | `read_levels` while Live's transport is not playing | Start playback (the tool never does), then read again |
| `unauthorized` | Wrong or missing bridge key (RFC 0004) | Same user for Live and abletonian; switch the slot |
| `adapter_error` | Anything else | None, rather than a wrong one |

A failed operation in `apply_batch` reports its `code` and `hint` under
`failed`. `read_levels` can also be refused by abletonian itself, before
anything is sent, with `bridge_timeout_too_short` when the configured
bridge timeout is shorter than the window plus 12 s.

Checked in Live 12.4.16 on 2026-11-03 (PR #40, validation log below).

## Setup

1. Install the package and the Remote Script:

   ```bash
   cd path/to/abletonian
   python -m venv .venv && .venv/bin/python -m pip install -e '.[dev]'
   .venv/bin/python -m scripts.install_remote_script
   ```

2. In Live, open Settings > Link, Tempo & MIDI and pick `Abletonian` in a
   free Control Surface slot. Leave Input and Output as `None`.

3. After reinstalling a newer script, switch that slot to `None` and back to
   `Abletonian`. The entrypoint reloads its modules, so Live picks up the new
   code without a restart. The very first upgrade from 0.1.0 needs a Live
   restart, because 0.1.0 did not have the reload.

4. Register the MCP server with Claude Code. For every project, run this
   from the abletonian checkout:

   ```bash
   claude mcp add abletonian --scope user -- "$PWD/.venv/bin/abletonian"
   ```

   Or only for your Ableton projects folder, run this from that folder, with
   the full path to your checkout:

   ```bash
   claude mcp add abletonian --scope project -- /path/to/abletonian/.venv/bin/abletonian
   ```

   The project scope writes `.mcp.json` in that folder. Check it with
   `claude mcp list`, then start a new Claude Code session.

## Example requests

- "List the tracks and where each one is routed."
- "Add a Utility at the end of every track and set its gain to -3 dB."
  Claude calls `apply_batch` with one `ableton.insert_device` per track and
  `parameters: {"Gain": "-3 dB"}`.
- "Route Kick, Snare, Bass and Vox to Main."
- "Colour the drum tracks red and rename track 4 to Lead Vox."
- "Set the Vox send to Reverb at -12 dB."
- "Put a Glue Compressor first on the Drums group."
- "Make me a macro cockpit for the selected rack." Claude calls
  `generate_macro_cockpit`; the macros are read, never changed. "Save it"
  calls `save_macro_cockpit`. Saved cockpits are JSON files in
  `~/Library/Application Support/abletonian/cockpits` on macOS,
  `%APPDATA%\abletonian\cockpits` on Windows, and
  `~/.local/share/abletonian/cockpits` on Linux, unless
  `ABLETONIAN_COCKPIT_DIR` or `--cockpit-dir` says otherwise. "Show it"
  calls `show_macro_cockpit`, which opens a local page with the grouped
  macros. The page has no running scripts and loads nothing from the network.

## Validation log

### 2026-11-08 (PR #61), Live 12.4.16 Suite, macOS 27.2

Remote Script 0.7.1 from the PR branch, installed and reloaded by switching
the Control Surface slot to None and back. Run by an agent on the Mac with
the `drive-live-on-mac` skill. Set: `First Light 061 check.als`, a Save As
copy of First Light, not saved after the run; every change was undone and
Live's Edit menu showed "Nothing to Undo" at the end.

- `daw.health`: adapter 0.7.1 with the new capabilities.
- `list_devices` with `max_depth` 0 listed the 16 Drum Rack chains as
  truncated. All 43 printed paths resolved through `get_device` (#24, #42).
- EQ Eight `1 Q A` (#43): bare `1` refused as ambiguous naming both
  readings, `"1"` set 1.00, `{"raw": 1}` set 18.0, bare `3` set 3.00 with a
  note. Nothing changed on the refusal.
- Glue Compressor (#44): options listed as Live shows them (Release `.1` to
  `A`). `"Auto"` set Release to A; `"Attack"` and `"Au"` were refused;
  `"0.4"`, Attack `"1"` and `"0.1"`, Ratio `"4"` and `10` all set.
- `insert_device` with a name (#46): one undo step for insert and name.
  Chain and device renames showed in Live and moved paths as expected;
  renaming the rack inside a Drum Rack chain also renamed the chain.
- `set_device_sidechain` (#49): Compressor set to C78 Core Kit Post FX, then
  A-Reverb; Live's Compressor showed External, A-Reverb, Post FX. Glue
  Compressor and Gate refused with `not_supported`.
- `create_track` (#47): MIDI at index 1 and audio at the end, each one undo
  step; group kind, index 99 and a bad colour refused with nothing created.
- `list_clips` and `set_clip_gain` (#50), on a clap sample dragged into
  Arrangement View: all values landed; one undo step each.
- `read_levels` (#45): refused while stopped; 39 samples in 4 s while a
  Session clip played; returns and Main included on request; stopping the
  transport after 2.5 s of a 6 s read gave `stopped_early`.
- Found and fixed: `gain_db` `"#0"` was read as 0 dB, the out-of-range clip
  gain error told the caller to send a raw value, and `read_levels` called a
  track silent when only `hold_peak` had caught its short hit. The first two
  fixes were rerun in Live; the `read_levels` warning change is unit tested
  only. These fixes are adapter 0.7.2.
- Not checked: `create_track` inside a group, the fail-closed delete, and a
  sidechain source that was deleted.

### 2026-11-03 (MEH-25, PR #40), Live 12.4.16 Suite, macOS 27.2

Checklist for clearer bridge errors (Remote Script 0.6.1). Run by an agent
on the Mac with the `drive-live-on-mac` skill; nobody was at Live. The
Remote Script was installed from this branch and reloaded by switching the
Control Surface slot to None and back in Settings. Set: a new Untitled Live
Set (not First Light). Calls went through the skill's `bridge.py`. Each
answer comes from the bridge result or a screenshot of Undo History. Before
the run, Undo History showed "New Live Set" with one greyed redo row
("Custom Action"); a new undo step would have removed that row. No error
carried the old hint "Check daw.health capabilities before retrying."

1. `daw.health`: adapter_version 0.6.1, Live 12.4.16, Python 3.11.6,
   protocol `abletonian.bridge.v2`. Before the reload it said 0.6.0. Pass.
2. a. `set_mixer` on "No Such Track": `not_found`, message lists the
   tracks, hint "Use list_tracks to see track names and indexes." Pass.
3. b. `set_device_parameter` on `A-Reverb`, device "No Such Device":
   `not_found`, message lists "Reverb", hint "Use list_devices on that
   track to see its devices, paths and parameters." Pass.
4. c. `set_device_parameter` Reverb "Decay Time" value 5: `invalid_value`,
   "value 5.0 is outside 'Decay Time' range 0.0..1.0", hint points to
   `list_devices` for the range and display text. Pass.
5. d. `set_device_parameter` Reverb "Density" (quantized) value "Ultra":
   `invalid_value`, "Options: Sparse, Low, Mid, High", hint "Use one of the
   options listed, spelled as shown." Pass.
6. e. `ableton.make_coffee`: `not_supported`, hint says to reinstall the
   Remote Script and switch the slot to None and back. Pass.
7. f. `ableton.undo` count 2 without confirm: `confirmation_required`,
   "Nothing was changed", hint "Show the user what would change and ask
   them." Pass.
8. h. `insert_device` "Flux Capacitor 9000" on `3-Audio`: `not_found`,
   "Live could not insert 'Flux Capacitor 9000': Device Flux Capacitor 9000
   not found", hint names Live's own devices ('EQ Eight', 'Utility') and
   says third-party plugins cannot be inserted yet. The device list on
   `3-Audio` was empty before and after. Pass.
9. After a to f and h, Undo History was unchanged: "New Live Set" current
   and the greyed redo row still there, so no step was added. Pass.
10. g. `ableton.batch` (atomic) with `set_mixer` `3-Audio` volume "-6 dB"
    and `set_mixer` "No Such Track": the first completed (-6.0 dB), and
    `failed` held index 1, code `not_found` and the `list_tracks` hint. Undo
    History gained one row, `Change "Track Volume"`. One Cmd+Z set
    `3-Audio` back to 0.0 dB and left "New Live Set" current. Pass.

### 2026-11-03 (RFC 0004, PR #38), Live 12.4.16 Suite, macOS 27.2

Checklist for the bridge port and per-install key (Remote Script 0.6.0,
issue #37). Live was not running at the start, so it was opened after the
Remote Script was installed and loaded the new script at startup. Set: a new
Untitled Live Set (not First Light); the one change was undone. Calls went
through `BridgeClient` from this branch, plus raw frames for the refusals.
Each answer comes from bridge results, `lsof -nP -iTCP -sTCP:LISTEN`, `stat`,
and screenshots of Undo History. The key was never printed.

1. Before install, `~/.abletonian` did not exist. After Live started with the
   new script, it held `bridge_key`.
2. Live (the `Live` process) listens on `127.0.0.1:39877`; nothing listens on
   9877. Pass.
3. `~/.abletonian` is mode 700 and `bridge_key` is mode 600, both owned by
   mehul. Pass.
4. `daw.health`: adapter_version 0.6.0, protocol_version
   `abletonian.bridge.v2`, Live 12.4.16, Python 3.11.6. Pass.
5. A raw frame with no `key`, and a `set_mixer` frame (volume 0.3, mute on
   `1-MIDI`) with a wrong key, both returned error code `unauthorized`. Undo
   History showed only "New Live Set" before and after; `1-MIDI` stayed at
   0.0 dB and unmuted. Pass.
6. `set_track_properties` rename of `1-MIDI` to "Key Check": one "Custom
   Action" entry. One Cmd+Z restored "1-MIDI". Pass.
7. With `bridge_key` moved to `bridge_key.bak`, `daw.health` failed in the
   client with "no bridge key found at ...". After the slot was switched to
   None and back (done through Settings by the agent), a new `bridge_key`
   existed, mode 600, different from the old one; `daw.health` worked, and
   the old key got `unauthorized`. A second run with one long-running
   `BridgeClient` process polling `daw.health` once a second went ok, then
   "no bridge key found", then ok again after the slot switch, with no
   restart. Pass.
8. `build_mcp(AbletonianConfig()).call_tool("check_bridge_health")` returned
   the 0.6.0 health result. Pass.
9. Other projects' Remote Scripts on 9877: not checked, because no other
   script is installed in the User Library.

- Found, not changed: an MCP server process started before the upgrade keeps
  the old port (9877) until it is restarted. The `check_bridge_health` tool
  in such a process said "could not connect to 127.0.0.1:9877". Restarting
  the MCP client after upgrading is enough.

### 2026-11-03, Live 12.4.16 Suite, macOS 27.2

Checklist from issue #26 (Remote Script 0.5.0: undo steps, device paths,
plugin display text). Set: a copy of `First Light.als` saved as
`First Light 050 check.als` in the same folder, not committed; every change
was undone. Calls went straight to the bridge (`BridgeClient`), and each
yes/no answer comes from bridge results plus screenshots of Live's Undo
History. Undo was pressed with Cmd+Z in Live.

1. Installed the Remote Script and switched the slot to None and back.
2. `daw.health`: adapter 0.5.0 with `undo_count`,
   `batch_per_operation_undo` and `single_call_undo_steps`. Pass.
3. Rename then volume on another track: two entries ("Custom Action",
   `Change "Track Volume"`). One Undo reverted only the volume. Pass.
4. `create_return_track("Check")` then Reverb Predelay: two entries. One
   Undo reverted only Predelay; "C-Check" stayed. Pass.
5. `insert_device` Utility with Gain "-3 dB": two entries ("Custom Action",
   `Change "Output Gain"`). It took **2** Undo presses to remove it.
6. `insert_device` with "No Such Param": error says the Utility was removed
   again; one new "Custom Action"; Undo on it left the track empty. Pass.
7. `delete_device` preview: no new entry (the redo list was kept). Pass.
8. Atomic batch of three volume changes: `undo_steps: "one"`, one entry, one
   Undo reverted all three. Pass.
9. Same batch with `atomic=false`: `undo_steps: "per_operation"`, but **one**
   entry, and one Undo reverted all three. **Fail** with 0.5.0. Experiments:
   two separate volume calls made two entries; a mixed batch (rename, volume,
   Predelay) made two entries, the volume and Predelay changes sharing one.
   Cause: Live merges parameter changes made in one main-thread callback,
   even across begin/end pairs. Fixed in 0.5.1 (each operation runs in its
   own callback). Rerun on 0.5.1: three entries; each Undo reverted one
   volume, in reverse order. Pass. Step 8 rerun on 0.5.1 also passed.
10. `undo` with `count=2` and no `confirm`: refused, nothing changed. With
    `confirm=true` after a rename and a volume change: `steps: 2`, both
    reverted. Pass.
11. Drum Rack scaffold and execute on `1-C78 Core Kit`: each made **6**
    entries ("Duplicate Track(s)" plus one more per track), but the backout
    text said "Use Live Undo 3 times". Three presses left one and a half
    extra tracks. **Fail** with 0.5.0. Fixed in 0.5.1: the backout text says
    6 times (two per track). Rerun on 0.5.1: execute said 6; six presses
    restored the set, and a new plan showed the source clip unchanged (5, 8
    and 16 notes). Pass.
12. `list_devices` on `1-C78 Core Kit` (the original track, which has the
    same Drum Rack as the "- Snare" copy the checklist names): the Guiro
    Short chains show as `C78 Core Kit/4/Guiro Short` and
    `C78 Core Kit/6/Guiro Short`. Setting "Device On" Off by each path
    turned off only that device (checked across all 41 devices in the rack);
    two Undos restored both. Pass.
13. Two EQ Eights on `3-Audio` listed as paths `"0"` and `"1"`. Device On
    Off on `"1"` changed only index 1; `delete_device` previews of `"0"`
    and `"1"` reached index 0 and 1 and added no entry. Pass.
14. Valhalla Supermassive (VST3 4.0.0), loaded from Live's browser because
    `insert_device` only finds Live's own devices. LowCut `"400 Hz"`:
    refused, naming "10 Hz" and the raw range 0.0 to 1.0; value unchanged;
    no new entry. Mode `"Andromeda"`: refused, naming the raw range. Raw
    `0.2`: LowCut showed 410 Hz, one `Change "LowCut"` entry. Pass.
15. `device="C78 Core Kit/Nope/X"`: "no chain 'Nope' in 'C78 Core Kit'"
    with all 16 chains listed. Pass.

- Found and fixed (0.5.1): steps 9 and 11, above.
- Found, not changed: an atomic batch that mixes parameter changes with
  other changes is two undo steps (see Undo above); this is how Live
  records them. Every bridge error ends with the hint "Check daw.health
  capabilities before retrying.", which does not fit errors such as a
  missing parameter.

### 2026-11-01 (after PR #21), Live 12.4.16 Suite, macOS

Set: `testing/First Light Project/First Light.als` as it was open in Live
(an earlier version of the file, before main replaced it), not saved
afterwards. Calls went through the MCP tools from main, in process, over the
real bridge.

- `daw.health` reported adapter 0.4.0, then 0.4.1 with this fix.
- `list_tracks` compact output was 3.3 KB against 9.2 KB for `detail="full"`;
  `name="kick"` and `name="Reverb"` matched case-insensitively.
- `set_track_properties` renamed return A to "A-Room"; it showed "A-Room".
- `create_return_track` added "C-Test Return"; every send to it started at
  -inf dB.
- `delete_device` refused `"true"` and `1` for `confirm` at the tool layer.
- Found and fixed: with adapter 0.4.0 every `delete_device`, even the
  preview, failed with "is no longer there". Live hands out a new Python
  wrapper for a device on each read, so the `is` check never matched. Live
  objects are now compared by `_live_ptr`.
- With the fix: a preview left the Utility in place; confirm deleted it; one
  Undo restored it with Output -7.00 dB and Stereo Width 50 %. The same held
  for Redux inside the Audio Effect Rack on Drum Rack return chain "a Mix
  Bus", reached by path. That Undo also reverted a Reverb Dry/Wet change made
  in an earlier, separate call (see Undo above).
- `set_device_parameter` set Reverb Dry/Wet on return chain "b Reverb" by
  path and by `returns/1`.
- `apply_batch` deleting index 0 then index 1 on [Utility, Glue Compressor,
  Utility] left the last Utility. A batch with an unconfirmed delete was
  refused and changed nothing.
- Display text on Valhalla Supermassive failed (see Values by display text).

### 2026-11-01, Live 12.4.16 Suite, macOS

Set: `testing/First Light Project/First Light After Extraction.als` (the
First Light set after a real Drum Rack extraction), not saved afterwards.

- `daw.health` reported adapter 0.2.0 on Live 12.4.16, Python 3.11.6.
- `list_tracks` returned 7 tracks, 2 returns, and Main with routing, levels,
  sends, and devices. `available_output_routing_types` listed `Ext. Out`,
  `Main`, the audio tracks, and `Sends Only`.
- `insert_device` put Utility at the end of `6-Audio`, then EQ Eight at
  index 0 ahead of it. An unknown name returned Live's
  "Device ... not found" error.
- `list_devices` returned all 12 Utility parameters with options.
- `set_device_parameter` set Utility Output to -6, -3, +2.5, -inf, and
  12 dB by display text, and Mono to On by option name.
- `set_track_output_routing` routed `7-Audio` to `6-Audio` and back to
  `Main`. An unknown target listed the available names.
- `set_track_properties` renamed `7-Audio` and set its colour by hex and by
  palette index.
- `set_mixer` set volume -6 dB, pan 25L, send A -12 dB, send B raw 0.2,
  and mute. Main volume -1 dB.
- `apply_batch` inserted a Utility with Output -3 dB on all 7 tracks,
  including a MIDI track without an instrument.
- `undo` stepped the set back to its starting state.
- Found and fixed: Utility gain is `Output` in the API, and a failed
  parameter step used to leave the inserted device behind.

## Not supported yet

Live's Python API has no call to create a group from tracks, and none to
reorder tracks. Creating group buses therefore still needs Live's UI
(select tracks, Cmd+G). Once the groups exist, these tools can colour and
name them, route tracks into them, and insert a Glue Compressor on them.
Saving the set is also not exposed.

`create_track` (issue #47) was checked in Live 12.4.16 on 2026-11-08: a MIDI
track created at index 1 landed there, an audio track without an index went
to the end, and each create with its name and colour was one undo step. A
bad colour or index is refused before anything is created. Live picked the
palette colour `#5480E4` for `"#3366FF"`, and the next track created without
a colour showed the same colour, so whether the colour was applied or is
Live's default is not settled. Not checked: an index inside a folded or
unfolded group (a guess: Live may put the track into the group), and the
fail-closed `Song.delete_track`.

## Prior art

| Project | Shape | What we took |
| --- | --- | --- |
| [LiveMCP](https://github.com/alaarab/livemcp) (`uvx livemcp --install`) | Remote Script plus TCP bridge on 9877, about 170 tools | Routing matched by display name. It runs reads on the socket thread; Abletonian keeps every Live call on the main thread instead. |
| [ahujasid/ableton-mcp](https://github.com/ahujasid/ableton-mcp) | Remote Script, unframed JSON on TCP 9877 | The `schedule_message` pattern for mutations. |
| [AbletonOSC](https://github.com/ideoforms/AbletonOSC) | Remote Script, OSC on UDP 11000/11001 | Routing by `available_output_routing_types` display names, broad LOM coverage as a reference. |

All three are MIT licensed. None of them used `Track.insert_device` at the
time of writing; they load devices through the browser. LiveMCP and
ableton-mcp listen on port 9877. Since adapter 0.6.0 Abletonian listens on
39877 and checks a per-install key on every request (RFC 0004), so they can
be enabled in Live at the same time.

## Known follow-ups

- `schedule_message` is called from the bridge thread, as in ableton-mcp and
  LiveMCP. It worked in testing, but Live does not document it as
  thread-safe. A safer design is a `queue.Queue` drained on the main thread.
