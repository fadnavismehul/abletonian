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
is literally named `N`. Not yet run in Live.

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

Some API names differ from the device UI. Utility's gain knob is `Output` in
the API; `Gain` is accepted as an alias. `list_devices` shows the API names.

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

### Errors

Every error from the Remote Script has a `code` and, where one fits, a
`hint` with the next step (adapter 0.6.1, Linear MEH-25). The message
names the object and lists the choices; the hint says what to do.

| Code | When | Hint, in short |
| --- | --- | --- |
| `not_found` | No such track, device, chain, parameter, return, routing or selection | Which list to check: `list_tracks`, or `list_devices` on that track |
| `invalid_value` | A value is out of range, not an option, or badly formed | See the parameter's range and display text, or send a raw number |
| `not_supported` | Live or this Remote Script cannot do it | What to do instead, such as reinstalling an older Remote Script |
| `confirmation_required` | A delete or multi-step undo without `confirm=true` | Ask the user first |
| `timeout` | Live did not start, or did not finish, in time | Whether the change may still happen, and to check before retrying |
| `unauthorized` | Wrong or missing bridge key (RFC 0004) | Same user for Live and abletonian; switch the slot |
| `adapter_error` | Anything else | None, rather than a wrong one |

A failed operation in `apply_batch` reports its `code` and `hint` under
`failed`.

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
Creating tracks and saving the set are also not exposed.

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
