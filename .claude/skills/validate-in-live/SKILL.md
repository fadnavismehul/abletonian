---
name: validate-in-live
description: Prepare or record a validation run of abletonian against real Ableton Live - write the step-by-step checklist for a Remote Script change, or turn a person's Live results into a validation log entry. Use after changing remote_scripts/, when asked how to test in Live, or when someone reports what happened in Live.
---

# Validate in Ableton Live

Agents cannot run Live. This skill produces the checklist a person runs, and
turns their results into a durable record.

## Write the checklist

1. Collect the assumptions about Live that the change depends on: LOM
   properties, value ranges, ordering, undo behaviour. Look in the PR, the
   RFC's implementation notes, and comments in `remote_scripts/`.
2. Pick a set. Prefer a copy of a fixture in `testing/` and say so; never
   ask anyone to save over `testing/First Light Project/First Light.als`.
3. Write numbered steps. Each step is one MCP tool call or Live action, with
   the expected result stated before it is run. Always include:
   - Setup: `.venv/bin/python -m scripts.install_remote_script`, then switch
     the Abletonian Control Surface slot to None and back.
   - `check_bridge_health`: expect the new `adapter_version` and capability.
   - One step per assumption from 1, phrased so the answer is yes or no.
   - For mutations: check Live's Undo restores the set, and say how many
     Undo presses that took.
   - For reads: confirm nothing in the set changed (and Live's Undo history
     did not grow).
   - A failure case (wrong selection, missing device) and the expected error.
4. Ask the person to report back with the "Live validation report" issue form,
   or in the PR.

## Run it yourself

When you are on the Mac with Live open and no person at Live, run the
checklist yourself with the `drive-live-on-mac` skill. It covers
screenshots, Undo, Save As and reloading the script.

## Record results

Add a dated entry to the validation log in
`docs/engineering/live-control.md` (or `live-validation.md` for workflows):

```text
### YYYY-MM-DD, Live <version> <edition>, <OS>

Set: <path or description>, saved or not saved afterwards.

- <what was called>: <what Live showed>.
- Found and fixed: <anything that differed from the assumptions>.
```

Then update the code and docs for any assumption that turned out wrong, and
remove "unverified" notes for the ones that held.
