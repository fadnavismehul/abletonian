# Live Set Control

The Abletonian Remote Script lets an MCP client read and change the Live Set
that is open right now. Nothing is written to the `.als` file, and you do not
need to close and reopen the set. Save in Live when you like the result.

## How it works

```text
Claude Code ──stdio MCP──▶ abletonian (Python 3.10+)
                              │  length-prefixed JSON over TCP 127.0.0.1:9877
                              ▼
                   Abletonian Remote Script (inside Live, Python 3.11)
                              │  ControlSurface.schedule_message
                              ▼
                      Live main thread ──▶ Live Object Model
```

- A socket thread inside Live accepts one request at a time.
- Every request, reads included, runs on Live's main thread through
  `schedule_message`. The socket thread never touches the Live API.
- Live-side operations live in `remote_scripts/Abletonian/live_ops.py`. They
  take the `song` object and plain JSON, so they are unit-tested with fakes in
  `tests/test_live_ops.py`.

## Tools

| MCP tool | Bridge method | What it does |
| --- | --- | --- |
| `list_tracks` | `ableton.list_tracks` | Names, group parent, colour, output routing, volume, pan, sends, mute/solo, device names. Covers regular, return, and main tracks. The tool defaults to `detail="compact"` (levels as display text, no routing options), about a quarter of the size, so large sets fit; `detail="full"` adds raw values and the output routing choices. `name` keeps tracks whose name contains it. |
| `list_devices` | `ableton.list_devices` | Devices per track (or all tracks), rack chains, and every parameter with raw value, range, display text, and options. |
| `generate_macro_cockpit` | `ableton.get_selected_rack_macros` | Read the selected Rack's macros (read-only) and return a grouped Macro Cockpit spec plus a text summary. See [RFC 0002](../rfcs/0002-selected-rack-macro-cockpit.md). |
| `save_macro_cockpit` | none | Save a cockpit generated in this session as a JSON file, so it can be reopened. Cockpits are temporary until saved. |
| `list_saved_macro_cockpits` | none | List saved cockpits. |
| `open_macro_cockpit` | `ableton.get_selected_rack_macros` | Open a saved cockpit and compare it with the selected Rack; warns when the rack or its macros changed. |
| `show_macro_cockpit` | none | Write a cockpit (generated this session, or saved) as a self-contained HTML page under the cockpit folder's `views/`, and open it in the browser. Display only. |
| `set_device_parameter` | `ableton.set_device_parameter` | Set by raw value or by display text (`"-3 dB"`, `"2.5 kHz"`, `"Off"`). |
| `set_track_output_routing` | `ableton.set_track_output_routing` | Set Audio To / MIDI To by display name, such as `Main` or a group name. |
| `set_track_properties` | `ableton.set_track_properties` | Rename and recolour (`"#RRGGBB"` or a palette index). Live shows a return's letter in front of its name, so a leading `A-` is dropped when renaming return A. |
| `set_mixer` | `ableton.set_mixer` | Volume, pan, sends (by return name, letter, or index), mute, solo. |
| `insert_device` | `ableton.insert_device` | Insert a native device with `Track.insert_device` (Live 12.3+) at a chain position, and set its parameters right away. |
| `create_return_track` | `ableton.create_return_track` | Add a return track at the end (`Song.create_return_track`), with an optional name and colour. Additive. |
| `delete_device` | `ableton.delete_device` | Delete a device (`Track.delete_device`). Destructive: without `confirm=true` it only returns the device and its current settings. The tool accepts only a real boolean, so `"true"` or `1` is refused. In `apply_batch`, every delete needs `"confirm": true` or the whole batch is refused before anything runs, and delete targets refer to the set as it was before the batch, so deleting index 0 does not shift a later index 1. |
| `apply_batch` | `ableton.batch` | Run many changes as one Live undo step. Stops at the first failure. |
| `undo_last_change` | `ableton.undo` | Live Undo once. |

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
work in Live 12.4.16. When two chains share a name, `list_devices` shows the
same path for both and that path is refused as ambiguous; use the chain index
the error lists instead.

### Values by display text

Live's raw parameter values are often not in the units you see. Utility
Gain, for example, is not stored in dB. When a value is a string, the script
searches for the raw value whose display text matches, using the parameter's
own `str_for_value`. That way `"-3 dB"` or `"25L"` lands where Live shows that
number. Quantized parameters match an option name instead.

Plugin parameters can behave differently. If `str_for_value` gives the
same text at both ends of the range (issue #16), the script instead sets the
value briefly, reads `str(parameter)`, and puts the original value back
before the real change. In Live 12.4.16 this did not work for Valhalla
Supermassive: `str(parameter)` still showed an earlier value's text when
read in the same call, so LowCut "400 Hz" and Mix "30 %" were refused with
"shows ... for every value", and option names such as Mode "Andromeda" are
not recognised. The parameter is put back, but Live records the probe as a
"Custom Action" undo step. Use raw values for plugins for now.

Some API names differ from the device UI. Utility's gain knob is `Output` in
the API; `Gain` is accepted as an alias. `list_devices` shows the API names.

### Undo

`apply_batch` wraps its operations in `Song.begin_undo_step` /
`end_undo_step`. In Live 12.4.16 one Undo reverted a whole batch of mixer
changes, and a whole batch of device inserts. When the batch ended with a
parameter change on a newly inserted device, Live recorded that last change
as its own step, so expect one or two Undos per batch.

Single tool calls are not wrapped. In Live 12.4.16, separate calls made in
a row (a rename, a new return, a device insert; or a parameter change and
then a delete) were merged into one undo step, so one Undo reverted all of
them. Every step shows as "Custom Action": the Live API gives no way to
name it (issue #3).

If setting `parameters` on a newly inserted device fails, `insert_device`
deletes that device again, so a failed call leaves the track unchanged.

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
Creating tracks and saving the set are also not exposed.

## Prior art

| Project | Shape | What we took |
| --- | --- | --- |
| [LiveMCP](https://github.com/alaarab/livemcp) (`uvx livemcp --install`) | Remote Script plus TCP bridge on 9877, about 170 tools | Routing matched by display name. It runs reads on the socket thread; Abletonian keeps every Live call on the main thread instead. |
| [ahujasid/ableton-mcp](https://github.com/ahujasid/ableton-mcp) | Remote Script, unframed JSON on TCP 9877 | The `schedule_message` pattern for mutations. |
| [AbletonOSC](https://github.com/ideoforms/AbletonOSC) | Remote Script, OSC on UDP 11000/11001 | Routing by `available_output_routing_types` display names, broad LOM coverage as a reference. |

All three are MIT licensed. None of them used `Track.insert_device` at the
time of writing; they load devices through the browser. LiveMCP and
ableton-mcp also listen on port 9877, and the Abletonian Remote Script has
that port fixed, so do not enable them in Live at the same time.

## Known follow-ups

- `schedule_message` is called from the bridge thread, as in ableton-mcp and
  LiveMCP. It worked in testing, but Live does not document it as
  thread-safe. A safer design is a `queue.Queue` drained on the main thread.
