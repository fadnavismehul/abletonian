# End-to-end user journeys against real Ableton Live

Status: design, awaiting review. Date: 2026-11-01.

## Why

Abletonian's tests use fakes shaped like the Live Object Model. They prove
the code matches our assumptions about Live, not that Live behaves that way.
The 2026-11-01 Live check after PR #21 showed the gap. The fakes passed, but
in Live every `delete_device` call failed (fixed in #23). Separate tool calls
also merged into one undo step (#3), and plugin display text did not work
(#16). That check was run by hand and cannot be repeated exactly.

We want a repeatable set of musician-facing journeys that run against real
Live and give a ground truth:

1. **Scripted mode** (built first): a harness runs each journey's tool calls
   and checks exactly what changed in the Live Set.
2. **Agent-eval mode** (built later): an agent gets the journey's
   natural-language prompt and the abletonian tools. Its result is graded
   against the same expected changes.

A fix session can then take the failing journeys, change the code, and show
that the journeys pass with nothing else broken.

## What we decided

- Both modes, layered: scripted runs define the expected changes; agent
  evals reuse them.
- Every journey starts from a fresh copy of a fixture set, opened in Live by
  the harness.
- Journeys are data files, and expectations are diffs between state
  snapshots (approach A). Expectations can be drafted by recording a run,
  then reviewed by a person.
- v1 uses Ableton's own devices only. Plugin journeys wait for #16 and #22.

## Components

```text
journeys/
  fixtures.yaml               # fixture name -> .als path under testing/, baseline facts
  J01-find-your-way.yaml      # one journey per file
  ...
src/abletonian/e2e/
  live_session.py             # copy fixture to a scratch folder, open it in Live, wait for it
  snapshot.py                 # one normalised JSON view of the Set
  diff.py                     # path-level diff of two snapshots
  journey.py                  # load and validate journey files
  runner.py                   # scripted mode
  report.py                   # Markdown + JSON results, capability map
scripts/run_journeys.py       # CLI
tests/test_e2e_*.py           # unit tests with fakes; CI never needs Live
```

- **Fixtures** stay in `testing/` and are never opened in place. v1 uses
  `First Light.als` and `First Light After Extraction.als`.
- **Tool calls** go through `build_mcp(config).call_tool(...)` in process,
  so they cover the MCP layer (argument validation, formatting) and the real
  bridge to Live. This is how the 2026-11-01 check ran.
- **Dependencies:** `pyyaml` goes into a new `e2e` optional extra. The
  server's runtime dependencies do not change.
- Agent-eval mode will be a second runner that reuses everything except the
  step source.

### live_session

1. Copy the fixture's project folder to `runs/<timestamp>/sets/<journey>/`.
2. Open the copy with `open -a <Live app> <path.als>`. The Live app path is
   found automatically or set with `--live-app`.
3. Poll `daw.health` and `list_tracks` until the track names match the
   fixture's baseline, or time out after 60 s.
4. If Live shows "Save changes?", ask the person in the terminal to click
   "Don't Save". The harness never saves a set.
5. Refuse to start if the open set's track names do not match the fixture
   baseline. This keeps the harness away from real mixes.

### snapshot

A snapshot is built only from read tools: `list_tracks(detail="full")` and
`list_devices(include_parameters=true)`. It is keyed by names:

```text
tracks/<name>/{color, output, volume, pan, mute, solo, sends/<return>}
returns/<name>/...
main/...
tracks/<name>/devices/<device>/params/<param> -> {raw, display}
tracks/<name>/devices/<rack>/chains/<chain>/devices/<device>/...
tracks/<name>/devices/<rack>/returns/<chain>/devices/<device>/...
```

When two siblings share a name, the second and later get `#2`, `#3` in list
order. Volatile fields are dropped: meter levels, the selected track and
device, and anything listed under `ignore`. Two snapshots taken with no
change in between must be identical. A spike checks this first.

### diff

`diff(before, after)` returns three lists: `added`, `removed` and `changed`
(with `from` and `to`). Raw values compare with a tolerance of 1e-6. Display
text compares exactly.

## Journey format

```yaml
id: J07-delete-and-undo
title: Remove a device, change your mind
tags: [devices, destructive, undo]
fixture: first-light
prompt: >
  Take the Utility off 6-Audio. Actually, put it back.
setup:                      # brings the fixture to the journey's start; not judged
  - insert_device: {track: 6-Audio, device_name: Utility, parameters: {Gain: -7 dB}}
steps:
  - id: preview
    delete_device: {track: 6-Audio, device: Utility}
    expect: {changes: []}
  - id: delete
    delete_device: {track: 6-Audio, device: Utility, confirm: true}
    expect:
      changes:
        - removed: tracks/6-Audio/devices/Utility
  - id: undo
    undo_last_change: {}
    expect: {state_equals: before:delete}
  - id: bad-confirm
    delete_device: {track: 6-Audio, device: Utility, confirm: "true"}
    expect: {error: "valid boolean", changes: []}
ignore: []
human_checks:
  - after: delete
    ask: Undo History shows exactly one new entry for the delete
known_issues:
  - step: undo
    issue: 3
```

Rules:

- Each step is one MCP tool call: the key is the tool name, the value its
  arguments.
- `expect.changes` lists every change the step should make. Entries are
  `added: <path>`, `removed: <path>`, or `changed: <path>` with `to:` (and
  optionally `from:`). A `to:` value matches the display text if it is a
  string, the raw value if it is a number.
- **Any change not listed fails the step** as an unexpected change. This is
  the main safety check.
- `expect.state_equals: before:<step id>` passes when the snapshot equals
  the one taken before that step.
- `expect.error: <text>` passes when the tool call fails and its message
  contains the text. `changes: []` with it means the failure changed nothing.
- `expect.output` (optional) holds JSON paths in the tool's own output that
  must match, for journeys that are not about Set state (manual search,
  cockpits, plans).
- `human_checks` are asked in the terminal after the named step (y / n /
  skip). With `--no-human` they are recorded as unchecked.
- `known_issues` link a step to an open GitHub issue.

### Results

Each step gets one result:

| Result | Meaning |
|---|---|
| `pass` | Expectations met, no unexpected change |
| `fail` | An expectation was not met, or there was an unexpected change |
| `known-fail` | Failed, and the step is linked to an open issue |
| `fixed?` | Passed, but the step is linked to an issue; check and close it |
| `error` | Harness or Live trouble (timeout, bridge down); not a product verdict |

A journey's result is its worst step result.

### Recording

`--record` runs the steps and writes each step's observed diff into a draft
copy of the journey (`J07-delete-and-undo.recorded.yaml`). A person reviews
the draft and copies the parts that are right into the real file. A recorded
expectation is never ground truth until a person has reviewed it.

## v1 journeys

| # | Journey | Tools | Known issue |
|---|---|---|---|
| J01 | Find your way around the set (read-only: no diff, no new undo entry) | check_bridge_health, list_tracks (compact, full, name filter), list_devices | |
| J02 | Tidy names and colours, including return names | set_track_properties | |
| J03 | Quick mix pass by display text: dB, pan, sends, mute, solo, Main | set_mixer | |
| J04 | Set up a new reverb return and send to it; new sends start at -inf dB | create_return_track, insert_device, set_mixer | |
| J05 | Route a track to another track and back; unknown target | set_track_output_routing | |
| J06 | Build an FX chain at given positions; a bad parameter rolls the insert back; unknown device | insert_device, set_device_parameter | |
| J07 | Delete a device, then Undo, at top level and inside a rack chain; non-boolean confirm | delete_device, undo_last_change | #19, #23 |
| J08 | Reach devices inside Drum Rack chains and return chains; duplicate chain names | list_devices, set_device_parameter | #24 |
| J09 | One gesture, many changes: a batch, a failure partway through, deletes by index | apply_batch | |
| J10 | Separate edits, then Undo each one | mutating tools, undo_last_change | #3 |
| J11 | Drum Rack extraction: plan, then execute | plan_drum_rack_extraction, execute_drum_rack_extraction | |
| J12 | Macro Cockpit: generate, save, reopen, show | cockpit tools | |
| J13 | Ask the manual (needs the local manual fetched) | search_ableton_manual, lookup_ableton_manual | |
| J14 | Ask for something unsupported: group tracks, create a track | draft_action_plan, check_bridge_health | |

- J11 to J14 are judged mainly with `expect.output`, because snapshots do
  not include clip contents, files or manual text. J11 also checks the new
  track names in the snapshot.
- Not in v1: plugins (#16, #22), a large set and group tracks. These need a
  new fixture made by hand in Live, since the API cannot create tracks.

## Running and reports

```bash
.venv/bin/python -m scripts.run_journeys                # all journeys
.venv/bin/python -m scripts.run_journeys --only J07     # one journey
.venv/bin/python -m scripts.run_journeys --tag undo     # by tag
.venv/bin/python -m scripts.run_journeys --record       # draft expectations
.venv/bin/python -m scripts.run_journeys --no-human     # skip terminal questions
```

- Needs Live open with the Abletonian Control Surface enabled, and the
  Remote Script installed from the same checkout.
- Each run writes `runs/<timestamp>/report.md` and `results.json`.
  `runs/` is gitignored. For every step these record the result, the diff,
  the tool output, and the time taken.
- `--publish` writes the capability map (tool × journey with the latest
  result) to `docs/engineering/capability-map.md`, to commit by hand.

## Handoff to fix sessions

A fix session gets the latest `report.md` and the list of `fail` and
`known-fail` steps with their issues. A fix is done when its steps become
`fixed?` and then `pass`, and the rest of the run has no new failures or
unexpected changes.

## Agent-eval mode (later)

- Same journeys, fixtures, snapshots and diffs.
- The agent gets `prompt` and the abletonian tools, not `steps`.
- Grading compares the final snapshot to the combined expected changes of
  all steps:
  - expected changes achieved (recall);
  - unexpected changes made (penalty);
  - for journeys that should be refused (J14), whether the agent said
    plainly that it could not do it.
- Undo steps in a prompt ("actually, put it back") are judged by the final
  state.

## Risks and the first spike

Before the main build, a spike answers two questions in Live:

1. Does `open -a <Live> copy.als` switch Live to the copy reliably? How does
   the "Save changes?" dialog behave, and how long does the switch take?
2. Are snapshots stable: are two snapshots with no edits in between
   identical?

If (1) fails, `live_session` falls back to asking the person to open the
copy, and checks the baseline before starting.

## Testing the harness

- `snapshot`, `diff`, `journey` validation and result judging get unit
  tests with the existing Live-shaped fakes, run in CI.
- One end-to-end test runs a small journey through `runner` with a bridge
  that passes requests to `live_ops.handle` on the Live-shaped fakes in
  `tests/test_live_ops.py`. That covers the runner logic without Live.
