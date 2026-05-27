# RFC-002: Selected Rack Macro Cockpit

**Status:** Proposed  
**Created:** 2026-05-27  
**Owner:** Core Team  
**Related Docs:** [Product Vision](../../vision.md), [Design Philosophy](../../../design/philosophy.md), [Strategic Directions](../../../strategic-directions.md), [Robustness and Safety](../../../engineering/robustness-and-safety.md)  
**Implementation Status:** Not started

## Goal

Define the first generated-UI workflow for Abletonian: given the selected
Ableton Rack, generate a musician-facing Macro Cockpit from the rack's existing
mapped macros.

The cockpit should make producer-authored Ableton controls easier to understand,
perform, and reuse without requiring the user to manually design a custom panel,
write Max for Live code, or reorganize rack mappings by hand.

## Problem Statement

Ableton already has a powerful customization model through Instrument Racks,
Audio Effect Racks, Drum Racks, chains, and macros. The problem is not that Live
lacks controls. The problem is that turning those controls into a clear,
personal performance or production surface is tedious and requires deep Ableton
knowledge.

Producers can map macros today, but they still have to decide:

- which controls matter for the current sound,
- how controls should be grouped musically,
- what labels and descriptions make sense during a session,
- how a control surface should look in a cloud desktop, local panel, MCP App, or
  future in-Ableton surface,
- whether the panel should be temporary or saved for reuse.

Abletonian should let the agent curate a front end for the controls the producer
already built. The first wedge should be intentionally narrow: selected rack,
existing macros only, generated UI spec first.

## Scope

In scope:

- Generate a `MacroCockpitSpec` from the currently selected Ableton Rack or rack
  device.
- Use only existing rack macros and their current metadata/value state in V1.
- Group, label, order, describe, and annotate existing macros for musician-facing
  use.
- Treat the cockpit as temporary by default, with an explicit save action for a
  reusable sidecar artifact.
- Keep the cockpit interface-neutral so it can render in a local web panel,
  cloud desktop, MCP Apps host, or future Ableton-native surface.
- Capability-gate any live macro control through the same policy path as other
  bridge actions.
- Provide text fallback when an interactive renderer is unavailable.

Out of scope:

- Creating new rack macro mappings automatically.
- Remapping devices, chains, sends, track controls, or arbitrary plugin
  parameters.
- Whole-set command centers.
- Hard-real-time performance guarantees.
- Generating arbitrary executable UI code as the default representation.
- Installing Max for Live devices, Remote Scripts, or cloud-hosted panels from
  generated code.

## Proposal

Introduce a generated cockpit workflow with an interface-neutral data model:

```json
{
  "id": "macro-cockpit-2026-05-27-c78-core-kit",
  "schema_version": "abletonian.macro_cockpit.v1",
  "title": "C78 Core Kit Macro Cockpit",
  "mode": "temporary",
  "source": {
    "target_daw": "ableton",
    "live_version": "12.4.0",
    "track_id": "track-drums",
    "track_name": "1-C78 Core Kit",
    "device_id": "device-c78-core-kit",
    "device_name": "C78 Core Kit",
    "device_type": "drum_rack"
  },
  "permissions": {
    "read_macros": true,
    "control_macro_values": false,
    "save_sidecar": true
  },
  "groups": [
    {
      "id": "tone",
      "label": "Tone",
      "description": "Controls that shape brightness, body, and saturation.",
      "controls": ["macro-1", "macro-2"]
    }
  ],
  "controls": [
    {
      "id": "macro-1",
      "source_macro_index": 1,
      "source_name": "Macro 1",
      "label": "Brightness",
      "description": "Use for opening the kit without changing the pattern.",
      "value": 0.42,
      "value_unit": "normalized",
      "style": "knob",
      "risk": "live_parameter"
    }
  ],
  "renderer_hints": {
    "density": "compact",
    "primary_layout": "grouped_controls",
    "show_source_context": true
  }
}
```

The important decision is that the generated cockpit is a **specification**, not
a particular frontend. Renderers consume the spec. The same generated cockpit
could appear as:

- a local web panel during early prototypes,
- a cloud desktop surface,
- an MCP Apps interactive component,
- a future Max for Live or Ableton-adjacent panel,
- a saved project sidecar that can be reopened later.

### User Flow

1. The user selects an Ableton Rack.
2. The agent asks Abletonian to generate a Macro Cockpit.
3. Abletonian reads selected track/device context and existing rack macros.
4. The agent returns a `MacroCockpitSpec` plus a short explanation.
5. A renderer displays the cockpit if available.
6. The user can use it temporarily.
7. The user can explicitly save the cockpit as a sidecar artifact.

Live macro control is capability-gated:

- If the adapter only supports reading macros, the cockpit is a read-only
  preview.
- If the adapter supports setting macro values safely, renderer events can call a
  deterministic `ableton.set_rack_macro_value` action.
- Macro value changes must not involve a model loop in the performance-critical
  path.
- The UI must disclose whether controls are connected, read-only, or simulated.

### Generation Behavior

V1 generation should be conservative:

- preserve the source macro identity and index,
- never invent hidden mappings,
- never claim that a macro controls a parameter unless the adapter can report it
  or the label is clearly generated as a user-facing suggestion,
- prefer compact groups such as `Tone`, `Dynamics`, `Movement`, `Space`, and
  `Utility` only when macro names support those categories,
- leave ambiguous macros in an `Ungrouped` or `Inspect` section,
- include the selected track/device context in the cockpit header.

### Saved Cockpits

Temporary is the default. Saving is explicit.

Saved cockpits should be sidecar artifacts rather than opaque code blobs. The
sidecar can later be associated with:

- a project,
- a rack/device identity,
- a track template,
- a user profile or workspace.

The saved artifact should include enough source context to warn the user if the
selected rack has changed since the cockpit was generated.

## Alternatives Considered

### Renderer-first local web cockpit

Pros:

- Fastest way to make a demo feel tangible.
- Clear visual feedback for musicians.
- Avoids over-designing schemas too early.

Cons:

- Risks baking the first renderer's assumptions into the product model.
- Makes cloud desktop, MCP Apps, and in-Ableton surfaces feel like ports rather
  than first-class render targets.

Decision: build a local web renderer as proof, but make the spec the primitive.

### Generate new Ableton rack mappings automatically

Pros:

- More magical when a rack is poorly mapped.
- Could make weak racks immediately useful.

Cons:

- Mutates the user's Live Set and changes creative state.
- Requires deeper rack/device understanding and stronger backout behavior.
- Blurs the first product wedge.

Decision: out of scope for V1. The agent may suggest missing mappings later as a
reviewable plan.

### Whole-set generated command center

Pros:

- Strong demo surface.
- Matches the dream of project-specific control rooms.

Cons:

- Requires many more object types, permissions, and safety rules.
- Harder to explain and verify.
- More likely to become a generic dashboard.

Decision: start with the selected rack/device, then expand once the spec and
policy model are proven.

### Raw generated code or Max for Live devices

Pros:

- Potentially powerful and portable for advanced users.
- Could eventually export real personal tools.

Cons:

- Generated executable artifacts carry safety, support, and installation risks.
- Harder to review than declarative specs.

Decision: declarative cockpit specs first. Code export can be a separate,
explicit advanced workflow.

## Implementation Plan

1. Define `MacroCockpitSpec`, `MacroCockpitGroup`, and
   `MacroCockpitControl` domain models.
2. Extend adapter capability reporting with selected-rack macro read support.
3. Add a read-only selected-rack macro introspection method to the fake adapter.
4. Add the same read-only selected-rack macro shape to the Remote Script adapter
   when Live exposes enough metadata.
5. Implement cockpit generation from an adapter payload into a
   `MacroCockpitSpec`.
6. Add a text fallback renderer that summarizes groups and controls.
7. Add a minimal local web renderer that consumes the spec.
8. Add sidecar save/load for explicitly saved cockpits.
9. Add policy checks for renderer-originated macro control events.
10. Add live macro value setting only after fake tests and manual Ableton
    validation exist.

## Acceptance Criteria

Product acceptance:

- Given a selected rack with existing macros, Abletonian can generate a
  `MacroCockpitSpec` without mutating the Live Set.
- The spec includes source context, macro controls, grouping, labels,
  descriptions, permissions, and renderer hints.
- The generated cockpit is temporary by default.
- The user can explicitly save the cockpit as a sidecar artifact.
- The cockpit can degrade to a text summary when no interactive renderer exists.
- The cockpit does not create, remove, or remap macros in V1.

Implementation acceptance:

- Unit tests cover schema validation and generation from fake rack macro state.
- Fake adapter tests cover selected rack with named macros, unnamed macros, and
  no macros.
- Local renderer tests or snapshots prove the spec can be rendered without
  Ableton.
- Remote Script read-only validation records Ableton version, selected rack,
  macro names, macro values, and capability list before any live macro write is
  enabled.
- `python -m unittest discover -s tests` passes.
- `git diff --check` passes.

Manual Ableton validation, before live connected controls:

- Select a Rack with mapped macros in a saved test Live Set.
- Generate a cockpit.
- Confirm the source rack, macro count, macro names, and current values match
  Ableton.
- Confirm no Live Set mutation occurs during generation.
- If macro value setting is enabled, move one cockpit control and confirm the
  corresponding Ableton macro moves, no other macro changes, and Live undo or a
  documented reset path is available.

## Risks and Mitigations

| Risk | Mitigation |
| --- | --- |
| Generated labels misrepresent what a macro does | Preserve source macro names, mark inferred descriptions as generated, prefer ambiguity over false certainty |
| Users think temporary panels are saved | Show temporary/saved state clearly and require explicit save |
| Renderer events mutate Live unexpectedly | Treat UI events as untrusted, route through policy and adapter capability checks |
| Cloud desktop latency is mistaken for performance safety | State that V1 is not hard realtime and keep model calls out of the control path |
| Generated specs become opaque or stale | Store sidecars as readable JSON with source rack/device fingerprints |
| Whole-set scope creeps into V1 | Keep V1 selected rack/device and rack macros only |

## Rollout and Backout

Rollout:

1. Ship read-only spec generation against fake adapter fixtures.
2. Render specs as text fallback.
3. Add local web rendering for generated cockpits.
4. Add explicit sidecar save/load.
5. Validate selected-rack macro reads against Ableton.
6. Add live macro control only behind capability and policy gates.

Backout:

- Disable interactive renderer actions while keeping read-only spec generation.
- Delete or ignore saved sidecar artifacts without touching the Live Set.
- If a live macro value change behaves incorrectly, disable
  `control_macro_values` capability and fall back to read-only cockpits.

## Open Questions

- What rack/device fingerprint is stable enough to warn when a saved cockpit no
  longer matches the selected rack?
- Should saved cockpits live beside project sidecars, user profile state, or
  both?
- How much semantic grouping should be generated by rules versus model
  assistance?
- Should macro descriptions cite Ableton/manual concepts, user-provided notes,
  or observed mapped parameters when available?
- What is the first renderer target after local web: cloud desktop, MCP Apps, or
  Max for Live companion?

## References

- [Abletonian Product Vision](../../vision.md)
- [Abletonian Design Philosophy](../../../design/philosophy.md)
- [Abletonian Strategic Directions](../../../strategic-directions.md)
- [Engineering Robustness and Safety](../../../engineering/robustness-and-safety.md)
- [Ableton Live Manual: Instrument, Drum and Effect Racks](https://www.ableton.com/en/live-manual/12/instrument-drum-and-effect-racks/)

## Implementation Tracking

- **Lifecycle folder:** `proposed/`
- **Code entry points:** not started
- **Verification:** not started
- **Commit tags:** none yet
- **Open follow-ups:** all acceptance criteria are pending
- **Deviations from proposal:** none
