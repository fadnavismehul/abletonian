# abletonian Vision

`abletonian` should feel like a careful studio assistant, not an unsafe macro
recorder. Ableton is the first target, but the project should stay useful as a
multi-DAW framework.

## Product Stance

- The agent should understand musical intent before mutating the set.
- Destructive edits should be rare, explicit, and undoable.
- Session state should be inspectable as structured context.
- Users should be able to run multiple named agents against different local
  bridge instances.
- FOSS contributors should be able to add adapters without rewriting the MCP
  layer.
- DAW-specific differences should be explicit, visible, and testable.

## Agent Identity

The default agent name is `abletonian`, matching the repo and package. It can be
parameterised so a user can run variants such as:

- `abletonian`
- `arrangement-assistant`
- `live-set-tech`
- `studio-copilot`

The configured agent name is the MCP server name exposed to clients.

## Target DAW

The default target DAW is `ableton`, but users can choose another adapter:

```bash
abletonian --target-daw reaper
```

The target DAW is not part of the agent identity. A user can run an agent named
`abletonian` against FL Studio, or an agent named `live-set-tech` against
Ableton.

## First Useful Milestones

1. Read-only bridge: connection health, DAW version, project summary, track list.
2. Safe write path: create a MIDI/instrument track, create a named clip/pattern,
   write notes where the target DAW supports it.
3. Browser/device adapter: search/load instruments and effects through stable IDs
   where available.
4. Agent workflows: draft drums, harmonise clip, sketch arrangement sections.
5. Safety layer: dry-run plans, undo checkpoints, save-copy helpers.
