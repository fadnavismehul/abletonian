# RFC 0002: Selected Rack Macro Cockpit

**Status:** Accepted  
**Created:** 2026-05-27  
**Owner:** @fadnavismehul  
**Tracking issue:** [#4](https://github.com/fadnavismehul/abletonian/issues/4)  
**Related Docs:** [Product Vision](../product/vision.md), [Design Philosophy](../design/philosophy.md), [Strategic Directions](../exploration/strategic-directions.md), [Robustness and Safety](../engineering/robustness-and-safety.md)  

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

- [Abletonian Product Vision](../product/vision.md)
- [Abletonian Design Philosophy](../design/philosophy.md)
- [Abletonian Strategic Directions](../exploration/strategic-directions.md)
- [Engineering Robustness and Safety](../engineering/robustness-and-safety.md)
- [Ableton Live Manual: Instrument, Drum and Effect Racks](https://www.ableton.com/en/live-manual/12/instrument-drum-and-effect-racks/)

## Implementation Notes

Progress is tracked in the tracking issue. This section records where the
code lives and decisions made while building it.

- **Code entry points:**
  - `src/abletonian/cockpit.py`: `MacroCockpitSpec`, `MacroCockpitGroup`,
    `MacroCockpitControl`, `generate_macro_cockpit`, `rack_fingerprint`,
    `render_cockpit_text`, and `MacroCockpitSpec.from_wire` for loading.
  - `src/abletonian/adapters/fake.py`: `FakeRackDevice`, `FakeRackMacro`,
    `FakePlainDevice`, macros on `FakeDrumRackDevice`, and
    `ableton.get_selected_rack_macros`.
  - `remote_scripts/Abletonian/live_ops.py`: `get_selected_rack_macros`
    (read-only, runs on Live's main thread like every bridge call).
  - `remote_scripts/Abletonian/bridge_server.py`: adapter 0.3.0 advertises
    `read_rack_macros` and lists `set_rack_macro_value` as unsupported.
  - `src/abletonian/server.py`: MCP tool `generate_macro_cockpit`.
  - `tests/test_cockpit.py`, `tests/test_live_ops.py` (`RackMacroTests`),
    `tests/test_server.py`.
- **Verification:**
  - 2026-11-01: `.venv/bin/python -m unittest discover -s tests` passed
    (101 tests); `.venv/bin/ruff check src tests remote_scripts` passed.
  - Not yet validated in Ableton Live.
- **Status as of 2026-11-01** (live progress is in #4):
  - Done: spec generation without mutating the Live Set (fake and LOM-shaped
    fakes); spec carries source context, controls, groups, labels,
    descriptions, permissions, and renderer hints; temporary by default; text
    fallback; no macros are created, removed, or remapped; unit tests for
    schema validation and for named, unnamed, unmapped, and missing macros.
  - Pending: Remote Script read validation in Live (record Live version,
    selected rack, macro names, values, capability list); local web renderer
    and its tests; explicit sidecar save/load; policy-gated
    `ableton.set_rack_macro_value` with manual validation.
- **Open follow-ups:**
  - Confirm in Live what `DeviceParameter.name` reports for a macro that is
    mapped but not renamed. If Live shows the mapped parameter's name, those
    macros land in a named group rather than `Inspect`, which is acceptable.
  - Confirm that `macros_mapped` and `visible_macro_count` exist on Live
    12.4 racks and that macros are `parameters[1:17]` in order.
  - `src/abletonian/adapters/remote_script.py` (the in-package copy of the
    early Remote Script adapter) does not have the macro read; the code that
    runs inside Live is `remote_scripts/Abletonian/`.
- **Deviations from proposal:**
  - 2026-11-01: V1 labels keep the macro name exactly as Live reports it.
    The RFC example relabels `Macro 1` as `Brightness`; generating new labels
    needs model assistance, which is an open question, so the rule-based V1
    does not invent labels.
  - 2026-11-01: Unmapped macros are left out of the controls and listed in
    `omitted_macros`, so the cockpit never shows a knob that does nothing.
  - 2026-11-01: The spec adds `connection` (`simulated`, `read_only`, or
    `connected`) so renderers can disclose control state, a `fingerprint` in
    `source` (hash of rack class, name, chains, and macro layout, not values)
    for stale-sidecar detection, and `normalized_value` per control. Values
    are reported raw with `min`/`max` rather than as `value_unit:
    normalized`.
  - 2026-11-01: When the selected device is not a Rack, the first Rack on the
    selected track is used and the cockpit carries a warning. `track` and
    `device` arguments pick a rack explicitly.
