# Product Vision

`abletonian` is the musician-first automation layer for Ableton Live and,
eventually, other DAWs. Its job is to make tedious, high-context studio work feel
as easy as asking a careful assistant who already understands the Live Set.

The product should not feel like a macro recorder, a generic chatbot, or a pile
of raw DAW API tools. It should feel like a studio assistant that can read the
set, explain the manual, draft a plan, make reversible changes, and keep the
musician in flow.

## Problem Statement

Modern DAWs are deep enough that many useful operations are technically possible
but practically annoying. Musicians routinely lose creative momentum to
mechanical work:

- extracting Drum Rack chains into separate tracks,
- renaming and color-coding tracks after a production pass,
- creating variations without overwriting the original idea,
- routing, arming, grouping, and organizing tracks,
- finding the right manual section or workflow,
- applying the same edit across many clips, tracks, chains, or devices.

The work is not musically hard. It is stateful, repetitive, and error-prone.
That makes it ideal for agentic automation, but only if the automation is deeply
aware of Ableton's object model and respectful of the user's session.

The first product wedge is: make Ableton operations dead easy for musicians,
starting with the workflows that are painful because they cross tracks, clips,
racks, chains, devices, naming, colors, routing, and undo.

The second product wedge is: make Ableton's existing customization power feel
approachable. A producer who has a Rack with useful macros should be able to ask
Abletonian to build a clear control surface for those macros, use it
temporarily, and save it only if it becomes part of their workflow.

## Product Thesis

The product is the harness: the layer that decides what an agent may do to a
Live Set, how a change is proposed, checked, applied and undone, and how the
result is verified and recorded. That layer does not depend on which code runs
inside Live, and it is the part that would carry over to another DAW. The
bridge into Live is necessary but replaceable; in November 2026 about thirty
other projects had one (see the
[landscape review](../research/2026-11-landscape-and-direction-review.md)).

The winning shape is a hybrid:

1. **Ableton-native adapters** for reading and mutating Live Set state: the
   Remote Script today, and an Extensions SDK adapter next, behind the same
   bridge protocol and capability handshake.
2. **Musician-facing intent layer** that exposes safe workflows rather than raw
   low-level controls.
3. **RTFM/manual intelligence** that grounds operations in Ableton's documented
   workflows and vocabulary.
4. **Reviewable plans** that show what will change before the Set is touched.
5. **MCP server and local UI surfaces** so agents and humans can both use the
   same automation engine.
6. **Generated UI specs** that turn selected Ableton context into portable,
   reviewable control surfaces.

Abletonian should make a workflow like "extract this Drum Rack into separate
tracks, preserving MIDI, naming, and colors" feel like one deliberate operation
instead of twenty fragile manual steps.

## Strategic Pillars

### 1. Deep DAW Context

The DAW is the source of truth. Abletonian should inspect selected tracks,
selected clips, selected chains, device chains, Drum Rack pads, scenes, cue
points, track routing, colors, and undo state from Ableton whenever possible.

### 2. Musician Intent Over Raw Control

Users should ask for outcomes: "split these drums," "clean up this session,"
"make three variations," "route each chain to its own audio track," or "explain
what this rack is doing." Raw commands can exist for debugging and advanced
workflows, but they should not be the primary product language.

### 3. Inspectable Before Mutable

Any non-trivial operation should produce a plan before mutation. The plan should
name affected objects, proposed additions, destructive risks, and backout
strategy. Mutations should be easy to undo or revert.

### 4. RTFM as a Product Primitive

Abletonian should know the manual. A musician should be able to ask "how does
chain extraction work?" and receive the relevant manual section, version-aware
context, and a proposed automation plan. The manual becomes a grounding layer
for both the user and the agent.

### 5. Local-First Trust

Live Sets often contain unreleased music, paid samples, client sessions, plugin
state, and private creative work. Core automation must be local-first. Cloud AI
can be optional, but the DAW bridge, manual index, and safety checks should not
depend on cloud infrastructure.

## What We Are

- A safe automation layer for Ableton Live workflows.
- An MCP server that lets agents operate on a DAW through typed, reviewable
  tools.
- A DAW bridge architecture that can support Remote Scripts, the Ableton
  Extensions SDK, AbletonOSC, Max for Live as an optional sensor, and test
  adapters.
- A product that turns manual workflows into reusable, inspectable recipes.
- A product that can generate project-specific UI surfaces from existing Ableton
  controls.
- A documentation-grounded assistant that can answer "what does Ableton say?"
  before taking action.

## What We Are Not

- Not a music generator that replaces the producer.
- Not a brittle UI macro recorder as the primary architecture.
- Not a cloud-only assistant.
- Not a giant bag of raw Ableton API endpoints exposed directly to musicians.
- Not a generator of arbitrary DAW-control code as the default UI strategy.
- Not a real-time performance control surface until latency and failure behavior
  are explicitly designed and tested.
- Not a replacement for Ableton's manual; RTFM should cite, summarize, and route
  users to the right source.

## First Wedge: Drum Rack Extraction

The first serious workflow should be concrete enough to prove depth:

> Given a selected Drum Rack track, split each meaningful pad or chain into its
> own track, preserving musical material, names, colors, and reviewability.

This workflow exercises the core product promise:

- read selected track and device state,
- understand Drum Rack pads and chains,
- create or duplicate tracks,
- transform MIDI clips safely,
- rename and color-code outputs,
- keep the original material untouched unless explicitly approved,
- provide a dry-run plan and backout path.

Ableton's manual documents Drum Rack chain extraction as a real user workflow,
including the distinction that dragging a drum chain from the mixer creates a
new track with devices and MIDI data, while dragging from the chain list extracts
devices only. See [Instrument, Drum and Effect Racks](https://www.ableton.com/en/live-manual/11/instrument-drum-and-effect-racks/#extracting-chains).

## RTFM Product Mode

RTFM should answer questions with:

- version-aware manual sections,
- direct citations,
- short workflow summaries,
- relevant Ableton concepts,
- whether Abletonian can automate the workflow today,
- a dry-run plan when automation is available.

Example:

```text
rtfm("extract drum rack chains into individual tracks", live_version="12")
```

Expected output:

- the relevant manual sections on Drum Racks and extracting chains,
- the manual's distinction between mixer extraction and chain-list extraction,
- a proposed Abletonian operation,
- safety notes about preserving the original track.

## Roadmap Horizon

### Phase 1: Foundation

- RFC-driven development process.
- Deep integration decision record.
- Read-only Ableton bridge health and project state.
- Version-aware RTFM/manual index.
- Fake adapter for tests.

### Phase 2: Safe Write Path

- Create/duplicate tracks.
- Create clips and write MIDI notes.
- Rename and color tracks, clips, and chains.
- Inspect and act on selected track/clip/device context.
- Dry-run plans and acceptance-gated mutation.

### Phase 3: Workflow Recipes

- Drum Rack extraction.
- Selected Rack Macro Cockpit from existing rack macros.
- Session cleanup.
- Clip variation creation.
- Batch rename/color/routing operations.
- Device/rack explanation from project context plus manual references.

### Phase 4: In-Ableton Presence

- An Ableton Extension that adds context-menu actions ("review plan",
  "cockpit for this rack") and shows abletonian's HTML in a Live dialog
  (`showModalDialog`). This needs Live Suite; the local browser page stays the
  fallback for other editions. Max for Live is kept for audio observation
  (meters, spectrum), not as the main UI.
- Context strip for selected track, clip, chain, and device.
- Plan review UI.
- Quick actions derived from selection.
- Generated cockpit renderer for saved or temporary rack macro surfaces.

### Phase 5: Multi-DAW Framework

- Start only after two Ableton adapters (Remote Script and Extension) run
  behind one in-process adapter interface, so the capability vocabulary is not
  designed from a single adapter.
- REAPER before FL Studio: it has a deep documented scripting API, runs on
  Linux, and has the largest non-Ableton MCP community.
- Keep Ableton first-class without hardcoding the whole product to Ableton.
- Let other DAW adapters advertise real capabilities and constraints.
- Preserve the same intent, safety, and RFC discipline across adapters.

## Success Signals

- A musician can complete a tedious Ableton workflow in one reviewed operation.
- Users describe Abletonian as "safe" before they describe it as "powerful."
- Repeated workflows become recipes instead of one-off prompts.
- Engineering can add a workflow by extending typed adapter capabilities, not by
  stapling a chat prompt to a UI macro.
- The assistant cites Ableton's manual when explaining how a workflow maps to
  Live.
