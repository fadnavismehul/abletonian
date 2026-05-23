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

## Product Thesis

The winning shape is a hybrid:

1. **Ableton-native bridge** for reading and mutating Live Set state.
2. **Musician-facing intent layer** that exposes safe workflows rather than raw
   low-level controls.
3. **RTFM/manual intelligence** that grounds operations in Ableton's documented
   workflows and vocabulary.
4. **Reviewable plans** that show what will change before the Set is touched.
5. **MCP server and local UI surfaces** so agents and humans can both use the
   same automation engine.

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
- A DAW bridge architecture that can support Remote Scripts, Max for Live,
  AbletonOSC, and test adapters.
- A product that turns manual workflows into reusable, inspectable recipes.
- A documentation-grounded assistant that can answer "what does Ableton say?"
  before taking action.

## What We Are Not

- Not a music generator that replaces the producer.
- Not a brittle UI macro recorder as the primary architecture.
- Not a cloud-only assistant.
- Not a giant bag of raw Ableton API endpoints exposed directly to musicians.
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
- Session cleanup.
- Clip variation creation.
- Batch rename/color/routing operations.
- Device/rack explanation from project context plus manual references.

### Phase 4: In-Ableton Presence

- Max for Live companion device or local panel.
- Context strip for selected track, clip, chain, and device.
- Plan review UI.
- Quick actions derived from selection.

### Phase 5: Multi-DAW Framework

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
