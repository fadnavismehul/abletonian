# Design Philosophy

Abletonian should feel like a careful studio assistant living beside the music,
not a separate productivity app dropped into a creative session.

The product design target is simple: keep musicians in flow while giving them
more leverage over Ableton's deep structure.

## Principles

### 1. The Music Stays Central

The interface should not compete with Ableton. It should help the user act on
the Set they are already hearing and seeing. Prefer context-aware commands,
small review surfaces, and progress feedback over large standalone dashboards.

### 2. Plans Before Changes

Non-trivial operations should have a visible plan:

- what will be read,
- what will be created,
- what will be renamed or recolored,
- what will be deleted or muted,
- how to undo or back out.

This is especially important because DAW mistakes are emotional. Losing a sound,
a groove, or a late-night arrangement state feels worse than a normal software
bug.

### 3. Make Batch Work Feel Human

Batch operations should expose musical intent. "Color all extracted drum tracks
by role" is better than "set color index for tracks 4-12." The interface should
show meaningful object names: Kick, Snare, Closed Hat, Crash, Bass Group, Verse
Scene.

### 4. Preserve Originals by Default

The safest default is additive:

- duplicate before destructive edits,
- create new tracks or clips instead of overwriting,
- mute/archive originals instead of deleting,
- keep the user one undo away from safety.

Destructive operations can exist, but they should be explicit and named.

### 5. Context Is an Affordance

Abletonian should always communicate what it is looking at:

- selected track,
- selected clip,
- selected chain,
- selected device,
- highlighted clip slot,
- arrangement selection when available,
- target Live version and bridge capabilities.

If the context is ambiguous, the product should ask a focused question rather
than guessing.

### 6. Natural Language Is an Entry Point, Not the Whole UI

Chat is good for intent. Review, approval, and repeated use often need structured
controls. A good workflow may start with text and then become a reusable action
with toggles, checkboxes, previews, and remembered defaults.

Generated UI should be treated as structured product output, not decoration. If
Abletonian creates a control surface for a selected Rack, the surface should be
backed by a readable spec that names its source, permissions, controls, grouping,
and saved/temporary state.

### 7. RTFM Should Be Helpful, Not Snarky

RTFM is a grounding tool. It should cite the manual, explain concepts clearly,
and connect documentation to action. The tone should feel like a trusted Ableton
friend saying, "Here is the relevant bit, and here is what we can automate."

### 8. Latency Shapes Trust

Musicians expect near-immediate feedback for transport and performance controls,
but can tolerate slower planning for batch edits. The product should separate:

- live-control operations,
- project-structure operations,
- analysis/documentation operations,
- AI-assisted planning operations.

Do not make hard-real-time promises through an agent loop.

## Interaction Patterns

### Dry-Run Plan

Use for any operation that touches multiple objects or can alter existing
material.

The plan should be concise and actionable:

```text
Split selected Drum Rack into 8 tracks

Will create:
- Kick
- Snare
- Closed Hat
- Open Hat

Will preserve:
- Original Drum Rack track
- Original MIDI clips

Needs confirmation:
- Filter duplicated MIDI clips to one note per track
- Assign track colors by drum role
```

### Reviewable Diff

For complex changes, show before/after state:

- track count,
- affected clips,
- device movement,
- routing changes,
- color changes,
- naming changes.

### Recipe Surface

Once a workflow proves useful, turn it into a recipe:

- "Split Drum Rack"
- "Clean Session Names"
- "Create Clip Variations"
- "Build Return Tracks"
- "Explain Selected Rack"

Recipes should have stable options and predictable behavior.

### Macro Cockpit

Use for selected Racks that already expose useful macros.

The cockpit should:

- show the selected track and rack/device context,
- use existing rack macros only unless the user explicitly approves a remapping
  workflow,
- preserve source macro names and indexes,
- group controls by musical role when the source labels support it,
- mark ambiguous controls clearly,
- disclose whether controls are read-only, connected, or simulated,
- start temporary and become saved only through an explicit user action.

The cockpit should not hide generated code or arbitrary bridge calls behind a
pretty UI. Renderer actions are requests that must pass through policy and
capability checks.

### Context Strip

Every UI surface should include a compact context strip:

```text
Ableton Live 12.1 | Selected: Drums / Drum Rack | Bridge: Remote Script | Mode: Dry run
```

## Visual Direction

The visual design should be quiet, dense, and work-focused. Ableton is already a
serious creative tool; Abletonian should fit that world.

Prefer:

- compact panels,
- clear object lists,
- status indicators,
- restrained color,
- readable monospace for paths and IDs,
- semantic color only when it maps to tracks/clips/chains.
- generated control surfaces that can be scanned and performed without reading
  long prose.

Avoid:

- marketing-style hero layouts inside the product,
- decorative visual noise,
- giant chat bubbles for structured workflow review,
- hiding risky actions behind friendly language.

## Trust Language

Use direct verbs:

- "Create"
- "Duplicate"
- "Rename"
- "Color"
- "Mute"
- "Delete"
- "Filter MIDI"

Avoid vague verbs for mutations:

- "Improve"
- "Clean up"
- "Optimize"
- "Fix"

Those can be user intents, but the plan must translate them into specific
actions before execution.
