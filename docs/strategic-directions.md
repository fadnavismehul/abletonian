# Strategic Product Directions

This document explores wildly different futures for `abletonian`. It is meant to
be read as an option space, not a roadmap. The current repository is deliberately
small: a configurable MCP server, a DAW target model, a length-prefixed bridge
boundary, and starter agent-oriented tools. That is a good place to be because
it keeps several product identities open.

## Current Architecture Snapshot

Today `abletonian` has four conceptual layers:

1. **MCP layer**: exposes a small number of agent-oriented tools and resources.
2. **Intent layer**: maps musician-facing requests into DAW-neutral operations.
3. **Bridge layer**: communicates with a DAW-specific adapter using framed JSON.
4. **DAW adapter layer**: implements host-specific behavior in Ableton, REAPER,
   FL Studio, Bitwig, Cubase/Nuendo, or another DAW.

The most important architectural choice is that the MCP server does not pretend
to be Ableton. It speaks musical intent, asks adapters what they can do, and
keeps the DAW-specific surface behind a bridge. This enables multiple futures:
embedded Ableton UI, chat-native UI, headless automation, live performance
control, educational assistants, collaboration layers, and eventually non-Ableton
hosts.

The product question is therefore not "what tool should the agent expose next?"
It is "where should the musician feel the agent living?"

## Design Principles for Any Direction

These principles should survive even if the product direction changes radically.

- **Musical intent over raw control**: users should ask for grooves, structure,
  sound, energy, variation, automation shape, and performance states, not only
  low-level API calls.
- **Inspectable before destructive**: create drafts, alternatives, checkpoints,
  and previews. Treat direct mutation as an explicit escalation.
- **The DAW is still the source of truth**: project state, clip state, track
  routing, devices, and transport should be read from the host whenever possible.
- **Capabilities are negotiated**: every adapter reports what it can actually do.
  The agent must degrade gracefully.
- **Human performance matters**: latency, timing, focus, motor flow, and trust are
  product requirements, not polish.
- **Keep the core portable**: Ableton can be first-class without making the core a
  pile of Ableton-only primitives.
- **UI should be composable**: a UI surface should be declarative enough that a
  musician, an agent, or a community package can assemble workflows.
- **Local-first by default**: DAW sessions often contain unreleased music,
  purchased samples, client material, and plugin/license state. Avoid cloud
  dependency for core creative loops.

## Direction 1: Ableton Native Co-Pilot in the Left Sidebar

### Concept

`abletonian` lives inside Ableton as a native-feeling panel: a left sidebar,
floating window, Max for Live device, Remote Script surface, or hybrid of these.
The musician never thinks "I am opening Claude" or "I am using an MCP server."
They think "Ableton has a co-producer lane now."

The panel watches the Live Set, understands tracks/scenes/clips/devices, and
offers contextual operations:

- "Make three bassline variations for this clip."
- "Find the stale tracks in this arrangement."
- "Turn these reference notes into a playable rack macro map."
- "Generate a B section using only the material already in the set."
- "Show me what will change before you touch the project."

### Why This Could Be Special

This direction has the strongest musician ergonomics. A DAW is an embodied
workspace: eyes, hands, keyboard shortcuts, controller muscle memory, and audio
feedback all matter. If the agent lives beside the Session/Arrangement view, it
can become part of that loop instead of a separate chat app.

A native Ableton surface can also use DAW context that chat users often forget to
specify: selected clip, highlighted time range, armed track, currently hot device,
folded groups, locator names, scene structure, tempo, scale, and routing.

### Interface Ideas

- **Context strip**: shows what the agent is currently looking at: selected
  track, selected clip, time range, device chain, groove pool, browser focus.
- **Plan drawer**: every operation expands into a readable diff: tracks to add,
  clips to create, notes to edit, automation lanes to touch, devices to load.
- **Variation rack**: generate alternatives as lanes/cards rather than overwrite
  the clip. Users audition, commit, discard, or morph.
- **Command chips**: one-click prompts derived from selection: "humanize hats,"
  "thin low mids," "make call-and-response," "extract groove," "build riser."
- **Undo checkpoints**: explicit preflight snapshots tied to Live's undo stack or
  adapter-level project checkpoints.
- **Device explainer**: click any device and ask, "what is this doing in this
  mix?" The response can point to macros and automation lanes.
- **Arrangement critic**: a timeline overlay that flags energy flatlines,
  repetitive transitions, empty frequency ranges, or unresolved sections.

### Technical Shape

A likely implementation is a hybrid:

```text
Ableton UI surface
  ├─ Max for Live device, Remote Script panel, browser window, or local webview
  ├─ talks to local bridge adapter
  └─ receives streamed plans/status from abletonian core

abletonian MCP/intent core
  ├─ exposes tools/resources/prompts to external clients
  ├─ also accepts local UI requests
  └─ routes DAW-neutral intent to adapter capabilities

Ableton adapter
  ├─ Remote Script, AbletonOSC, Max for Live, or combined approach
  └─ reads/writes Live Set state safely
```

The left sidebar does not have to replace MCP. It can be another client of the
same core. The MCP server stays useful for Claude Desktop, automation, and
external agents, while the Ableton UI becomes the highest-trust musician surface.

### Risks

- Ableton UI embedding may be constrained by what Live officially exposes.
- A Max for Live UI can be powerful but may feel like a device rather than a
  first-class sidebar.
- Remote Scripts are strong for controller integration but less ideal for rich UI.
- A native-feeling panel may require platform-specific packaging and more QA.
- The more "inside Ableton" it feels, the more users will expect it to obey
  Ableton timing, undo, selection, and crash-resilience norms.

### Best First Prototype

Do not start by building the final sidebar. Start with a **local web panel** that
tracks Ableton selection via the bridge and sends dry-run plans. Make it feel
like a left sidebar in a browser window. Once the workflow is compelling, decide
whether to port it into Max for Live, a Remote Script companion, or an embedded
webview.

### Success Test

A producer can keep Ableton focused for a two-hour writing session and use
`abletonian` 20 times without switching mental contexts, losing trust, or
needing to paste screenshots into chat.

## Direction 2: MCP Apps for Chat-Native Ableton UI

### Concept

`abletonian` becomes an MCP server that returns interactive UI components to MCP
hosts that support MCP Apps. Instead of only returning text/JSON, a tool can
surface a custom clip editor, device macro board, arrangement map, variation
picker, or mix checklist directly inside Claude Desktop or another host.

The user says:

> Build me a custom interface for performing this set live.

The agent reads the Live Set and returns an interface tailored to that project:
scene launch pads, macro controls, emergency stop, arrangement markers, cue notes,
and safe buttons for pre-approved operations.

MCP Apps is an official MCP extension for interactive UI. The official docs
describe it as a way for MCP servers to deliver interactive interfaces to hosts,
with server-provided UI resources rendered by the host and bidirectional
communication between app and host over a JSON-RPC style app bridge. See the MCP
Apps docs and API reference for the current host/server/view model.

### Why This Could Be Boundary-Pushing

This is not merely "chat with Ableton." It is **agent-generated DAW tooling**.
Instead of shipping one UI, `abletonian` could help musicians generate many small
interfaces:

- a custom live-performance controller for one set;
- a drum programming grid optimized for one sample pack;
- a songwriting storyboard for one arrangement;
- a vocal comping checklist for one session;
- a macro dashboard for one artist's live rig;
- an educational overlay that explains a project as it plays.

The killer idea: **the UI becomes a project artifact**. A Live Set can carry a
companion control surface generated for that set, by that user, for that moment.

### Interface Ideas

- **Clip variation picker**: cards with MIDI/audio previews, confidence notes,
  and "commit to new scene" buttons.
- **Session map**: a high-level scene/track grid with semantic labels: intro,
  drop, breakdown, unsafe mute, unquantized launch, missing follow action.
- **Macro cockpit**: a generated dashboard for mapped macros across selected
  racks/devices, grouped by musical role rather than track order.
- **Prompt-to-panel builder**: "make a techno performance panel with only mutes,
  sends, filter macros, and scene launches."
- **Mix triage board**: agent flags issues, user approves operations one by one.
- **Practice mode**: the app listens to transport/locator state and displays
  reminders, lyrics, cues, or arrangement notes.
- **Generative constraint UI**: sliders/buttons for density, syncopation,
  register, velocity range, call-and-response, tension, and motif reuse.

### Technical Shape

```text
MCP host with Apps support
  ├─ chat/model conversation
  ├─ renders ui:// resources in sandboxed views
  └─ mediates tool calls and app-host communication

abletonian MCP server
  ├─ tools return text plus app metadata/UI resource references
  ├─ resources expose Live Set state, generated UI specs, previews, and diffs
  └─ validates every UI-originated action through policy/capability checks

Ableton bridge adapter
  ├─ reads project state
  ├─ applies approved mutations
  └─ streams events/status where supported
```

This direction pushes `abletonian` toward a **UI compiler**: natural language +
Live Set context + safety policy in, project-specific interface out.

### Required Product Constraints

- Every generated UI needs a **permission model**: read-only, draft-only,
  non-destructive writes, destructive writes, export/render, transport control.
- Every button should explain what it will do before it mutates the Live Set.
- The UI must degrade to text when the MCP host does not support Apps.
- The UI should not hide arbitrary tool calls behind pretty buttons. Treat app
  events as untrusted requests that go back through the same validation path as
  model-originated tools.
- Generated UIs should be serializable and reviewable. Store them as JSON specs
  or project companion files, not opaque code blobs by default.

### Risks

- MCP Apps host support is emerging; relying on it too early may narrow the user
  base.
- The security model is subtle: a generated UI that can call tools is powerful
  enough to become dangerous.
- Users may confuse chat-host UI latency with DAW/control latency. It should not
  be used for hard realtime performance until proven.
- A host-rendered iframe UI may never feel as immediate as an in-DAW panel for
  transport and performance use.

### Best First Prototype

Build one MCP App: **Action Plan Review**.

Flow:

1. User asks for a musical change.
2. Tool returns a dry-run plan and an interactive review UI.
3. UI shows each proposed change with approve/skip/edit controls.
4. Approved steps are sent back through existing MCP tools.
5. The system returns a textual fallback for non-App hosts.

This validates MCP Apps without needing a full custom Ableton UI generator.

### Success Test

A user can ask Claude Desktop to create a project-specific control panel, inspect
what it is allowed to do, use it safely, and save/reopen the panel later.

## Direction 3: A Local-First Music Operating System Layer

### Concept

`abletonian` becomes a local daemon that indexes a musician's creative world:
Live Sets, stems, MIDI clips, samples, presets, references, notes, lyrics,
exports, plugin chains, and arrangement versions. The DAW bridge is one input and
one output; the bigger product is a **music workspace intelligence layer**.

Instead of only controlling Ableton, it answers:

- "Find all unfinished ideas in D minor around 128 BPM."
- "Show me tracks where I used this vocal chop."
- "Which projects have drops but no intro?"
- "Make a release checklist for the EP from these sessions."
- "Extract the best eight-bar loops from last month's sketches."

### Why This Could Be Special

Most music tools are session-bound. A musician's actual creative memory spans
folders, exports, references, notes, bounced stems, abandoned projects, and
versions. An agent that understands that corpus can help with taste, continuity,
finishing, and catalog management.

This could be the most defensible long-term layer because it compounds over time.
Every session makes the local creative graph richer.

### Interface Ideas

- **Project memory**: per-track/per-clip notes generated over time.
- **Sample provenance**: where a sample came from, where it is used, and what
  licenses/credits are attached.
- **Idea rescue**: surface forgotten sketches that match the current project.
- **Reference alignment**: compare current arrangement energy with reference
  tracks using locally computed descriptors.
- **Finish mode**: convert messy project state into a checklist with specific
  DAW actions.
- **Stem librarian**: automatically tag, summarize, and group bounced stems.
- **Version graph**: explain what changed between exported mix versions.

### Technical Shape

```text
Local index daemon
  ├─ file watchers for projects, exports, samples, notes
  ├─ metadata DB and embedding/vector index
  ├─ optional audio analysis workers
  └─ privacy/local-first policy

MCP server
  ├─ resources expose project/library context
  ├─ tools retrieve, compare, summarize, tag, and plan
  └─ prompts encode production workflows

DAW bridge
  ├─ reads current session state
  └─ applies selected actions back into the DAW
```

### Risks

- Audio/project indexing gets complex quickly across DAWs and proprietary file
  formats.
- Users may be sensitive about unreleased music and local scanning.
- This can become a generic asset manager unless it stays tightly tied to action:
  retrieve something useful, then do something musical with it.

### Best First Prototype

Create a local **session notebook** resource: every time the user asks for a plan
or runs a tool, append structured notes to a per-project sidecar file. Then add
retrieval: "what were we trying to do in this set?"

### Success Test

A user reopens a project after a month and `abletonian` can accurately explain
what the project is, what was unfinished, and what the next three useful actions
are.

## Direction 4: The DAW Adapter Standard, Not the App

### Concept

`abletonian` becomes the open standard adapter layer for AI-assisted DAWs. The
primary artifact is not a polished app, but a stable protocol, capability model,
test suite, and reference adapters. Other agents, UIs, hardware controllers, and
DAW scripts build on top of it.

In this future, the repo is closer to "JACK/OSC/MIDI for agentic music tools"
than a single assistant.

### Why This Could Be Special

Music AI tooling is fragmented. Every project writes one-off glue for Live,
REAPER, OSC, MIDI, Max, Python scripts, or plugin APIs. A clean DAW capability
protocol could become valuable infrastructure:

- one way to describe DAW capabilities;
- one way to read session state;
- one safe action/diff model;
- one test harness for fake DAWs;
- one bridge protocol for multiple agents and UIs.

### Interface Ideas

This direction may not have one UI. It has many:

- a CLI inspector;
- MCP server;
- web dashboard;
- Max for Live panel;
- community controller scripts;
- plugin wrappers;
- CI fake DAW harness.

### Technical Shape

```text
abletonian-core
  ├─ DAW-neutral schema
  ├─ capability vocabulary
  ├─ action/diff/checkpoint protocol
  ├─ fake DAW simulator
  └─ conformance tests

adapters
  ├─ ableton-remote-script
  ├─ ableton-osc
  ├─ reaper-reascript
  ├─ bitwig-extension
  └─ fl-studio-midi-script

frontends
  ├─ MCP server
  ├─ MCP Apps UI
  ├─ web dashboard
  └─ DAW-native panels
```

### Risks

- Infrastructure is harder to market than a magical product demo.
- Standards work can become abstract and slow.
- The project needs real adapter depth to avoid being a beautiful vocabulary with
  shallow host integrations.

### Best First Prototype

Build a **fake DAW adapter** and conformance suite. If an external contributor
can implement a new adapter by making tests pass, the architecture is real.

### Success Test

A third-party developer can build a basic REAPER or Bitwig adapter without
changing the MCP server or intent layer.

## Direction 5: Generative Instrument and Performance Companion

### Concept

`abletonian` focuses less on arranging/editing and more on live interaction. It
acts as an improvising bandmate, performance safety layer, and controller brain.
The DAW is the sound engine; `abletonian` is the musical decision layer.

Examples:

- generate fills at scene boundaries;
- listen to clip launches and prepare compatible next scenes;
- transform a MIDI controller into a context-aware instrument;
- map one knob to musically meaningful macro changes across the set;
- create emergency fallback states for live performance.

### Why This Could Be Special

Most AI music tools are offline: generate a loop, stem, or song. Performance is
more interesting because the musician remains present. The agent can become a
responsive collaborator rather than a vending machine.

### Interface Ideas

- **Live set copilot**: suggests next scene, transition, mute, or fill based on
  current transport and energy.
- **Smart controller mapping**: "make my 8 knobs control the most important
  things in this set."
- **Improviser lane**: agent prepares clips but only launches when confirmed.
- **Risk monitor**: warns about unmuted channels, missing warp markers, dangerous
  feedback routes, or CPU-heavy devices before performance.
- **Setlist state machine**: formalize performance states: intro, build, drop,
  breakdown, emergency loop, encore.

### Technical Shape

This direction needs event streaming and strict separation between realtime and
non-realtime paths.

```text
Realtime-safe path
  ├─ controller input
  ├─ precomputed mappings/states
  ├─ local bridge messages with low latency expectations
  └─ no network/model dependency during critical performance moments

Non-realtime agent path
  ├─ analyzes set
  ├─ proposes mappings/scenes/fills
  ├─ generates alternatives before the show
  └─ updates performance plan between sections
```

### Risks

- Models and MCP hosts are not reliable realtime systems.
- Live performance has a very low tolerance for surprise.
- Safety UX matters more than breadth of features.

### Best First Prototype

Build **Performance Prep Mode**, not realtime improvisation. It reads the set and
creates a performance checklist plus suggested controller mappings. Later, add
runtime monitoring.

### Success Test

A live performer trusts `abletonian` enough to use its generated controller map
on stage, because every control is labeled, reversible, and bounded.

## Direction 6: Educational Studio Mentor

### Concept

`abletonian` becomes a teacher inside a real project. It does not just do tasks;
it explains why. It watches a user's Ableton session and gives coaching:
arrangement, harmony, rhythm, mixing, sound design, workflow, and genre
conventions.

### Why This Could Be Special

Music education often happens in generic tutorials detached from the learner's
actual project. A project-aware mentor can say:

- "Your kick and bass are masking around this range."
- "This 16-bar loop has no contrast because every track enters at once."
- "Here are three ways to make this chord progression less static."
- "This rack has macros, but none are automated. Try automating macro 2 during
  the build."

### Interface Ideas

- **Explain selected clip**: harmony, rhythm, groove, density, motif reuse.
- **Before/after lesson**: agent creates a non-destructive duplicate with changes
  and explains each one.
- **Genre coach**: compares arrangement roles to a selected style.
- **Practice exercises**: create small tasks from current project weaknesses.
- **Socratic mode**: ask the user to make a choice before suggesting changes.
- **Plugin/device tutor**: explain parameters in the context of the current sound.

### Technical Shape

This direction emphasizes read operations, resources, analysis, and prompts more
than write tools. It can ship earlier because it can be useful with limited DAW
mutation support.

### Risks

- Bad music advice can be worse than no advice.
- Genre norms must not flatten user taste.
- The product should offer options, not authority.

### Best First Prototype

Implement **Project Critique as Dry Run**: read a fake or real session summary,
return an annotated improvement plan, and optionally create duplicate clips or
tracks only after approval.

### Success Test

A beginner learns faster without feeling the tool is taking authorship away.

## Direction 7: Collaborative Producer Workspace

### Concept

`abletonian` becomes the shared layer between collaborators. It tracks intent,
changes, notes, bounces, review comments, stems, and alternate directions across
people and tools.

It answers:

- "What did Sam change in the chorus?"
- "Make a revision package for the vocalist."
- "Create three tasks for the mix engineer from the current rough mix."
- "Compare these two bounces and summarize audible differences."

### Why This Could Be Special

Collaboration in music is still messy: screenshots, bounced MP3s, Dropbox links,
voice notes, DAW project copies, and vague feedback. An agent that understands
project state and human intent could make collaboration less lossy.

### Interface Ideas

- **Revision digest**: summarize changes between project saves/bounces.
- **Feedback-to-actions**: turn notes like "chorus needs lift" into candidate DAW
  edits.
- **Stem package builder**: prepare exports with naming, tempo/key metadata, and
  notes.
- **Approval board**: collaborators approve/discuss proposed changes before they
  are applied.
- **Credit/provenance notes**: track samples, collaborators, and generated parts.

### Technical Shape

```text
Local project sidecars
  ├─ structured notes
  ├─ action history
  ├─ generated plans
  ├─ review comments
  └─ export manifests

Optional sync layer
  ├─ encrypted collaboration workspace
  ├─ identity and permissions
  └─ project/package exchange
```

### Risks

- Collaboration features imply identity, storage, permissions, and maybe cloud.
- Legal/credit/provenance claims must be careful.
- DAW project diffs are hard; sidecar-first may be more tractable.

### Best First Prototype

Start with **export manifests and review notes**. Do not diff proprietary project
files first. Record what `abletonian` knows and what it did.

### Success Test

A collaborator can open a shared folder and understand the state of the song
without a long call or scattered chat history.

## Direction 8: Agent-Generated Micro-Tools and Personal DAW Mods

### Concept

`abletonian` becomes a factory for small, personal music tools. The user does not
only ask it to edit a song; they ask it to build workflows:

- "Make me a one-button resampling workflow for this template."
- "Create a chord substitution palette for neo-soul writing."
- "Build a cleanup tool for my podcast editing template."
- "Make a controller page for my Push/User Mode layout."
- "Generate a Max for Live prototype that randomizes these macros safely."

### Why This Could Be Special

Every serious producer has weird personal workflows. Most never become software
because building DAW tools is too technical. An agent that can create constrained,
reviewable micro-tools could unlock a huge amount of personal workflow design.

This is adjacent to the MCP Apps direction, but broader. Outputs could be:

- MCP App panels;
- Max for Live device prototypes;
- Remote Script snippets;
- REAPER scripts;
- Bitwig controller extensions;
- local web dashboards;
- Ableton template sidecars;
- hardware controller maps.

### Technical Shape

This requires a strict distinction between **generated specification** and
**generated executable code**.

Safer default:

```text
Natural language request
  -> validated workflow spec
  -> UI/action graph generated from safe primitives
  -> user approval
  -> saved personal tool
```

Riskier advanced mode:

```text
Natural language request
  -> generated code/plugin/script
  -> sandbox/test harness
  -> explicit install step
```

### Risks

- Generated scripts can break projects, leak data, or behave unpredictably.
- Cross-DAW code generation is a large scope.
- Tool versioning and support can become complex.

### Best First Prototype

Create a **workflow spec DSL** backed by existing safe primitives. Let the agent
generate dashboards and action graphs, not arbitrary code. Later, allow advanced
users to export to Max for Live, Remote Script, or REAPER script.

### Success Test

A musician creates a personal utility in ten minutes that would previously have
required a weekend of scripting.

## Comparative Matrix

| Direction | Magic | Feasibility | Differentiation | Risk | Best early wedge |
| --- | --- | --- | --- | --- | --- |
| Ableton left sidebar | Very high | Medium | High | UI/API constraints | Local web panel pretending to be sidebar |
| MCP Apps UI | Very high | Medium | Very high | Host support/security | Action Plan Review app |
| Local music OS | High | Medium | Very high | Indexing/privacy | Session notebook sidecar |
| Adapter standard | Medium | High | Medium/high | Abstract infra trap | Fake DAW conformance suite |
| Performance companion | Very high | Low/medium | High | Realtime trust | Performance Prep Mode |
| Educational mentor | High | High | Medium | Advice quality | Project Critique dry run |
| Collaboration workspace | Medium/high | Medium | Medium/high | Sync/legal/product scope | Export manifests/review notes |
| Micro-tool factory | Extremely high | Medium | Very high | Generated code safety | Safe workflow spec DSL |

## Recommended Portfolio Strategy

The best path may be to avoid choosing one identity too early. Instead, build a
thin vertical slice that keeps multiple futures alive.

### Slice 1: Project State Resource

Expose a normalized, read-only project/session summary as an MCP resource. Even a
fake adapter can provide this. Almost every direction depends on reliable context.

### Slice 2: Dry-Run Action Plan With Diffs

Make `draft_action_plan` evolve from prose into a typed action graph with:

- required capabilities;
- risk level;
- affected tracks/clips/devices;
- reversible/non-reversible flag;
- preview text;
- confirmation requirements.

This becomes the foundation for native UI, MCP Apps, education, collaboration,
and micro-tools.

### Slice 3: Fake DAW Adapter and Conformance Tests

Create a fake session with tracks, clips, notes, devices, and scenes. Every UI and
agent flow can be tested against it in CI before touching Ableton.

### Slice 4: One Interactive Review Surface

Build one review UI twice:

1. as a local web panel that could later become an Ableton sidebar;
2. as an MCP App for chat-native hosts.

This intentionally compares Direction 1 and Direction 2 with the same underlying
core.

### Slice 5: Sidecar Memory

Store plans, approvals, generated UI specs, and session notes in project sidecar
files. This unlocks local music OS, collaboration, education, and reproducibility
without needing proprietary project file diffs.

## Architecture Changes to Consider Next

### 1. Introduce a Typed Domain Model

Add Python models or dataclasses for:

- `DawSession`
- `Track`
- `Clip`
- `Device`
- `Scene`
- `ArrangementRange`
- `Capability`
- `ActionPlan`
- `ActionStep`
- `RiskLevel`
- `ApprovalPolicy`

The current JSON strings are fine for a scaffold, but deep UI and multi-adapter
work need typed internal models.

### 2. Split Server Tools From Domain Services

Keep MCP decorators thin. Put musical planning, capability matching, bridge
requests, and serialization into domain services that can be reused by:

- CLI;
- MCP server;
- local web UI;
- MCP Apps;
- tests;
- future DAW-native panel.

### 3. Add Resources, Not Just Tools

For MCP clients, project/session state should often be a resource. Tools do work;
resources provide context. Candidate resources:

- `abletonian://agent/profile`
- `abletonian://daw/target`
- `abletonian://daw/session/current`
- `abletonian://plans/recent`
- `abletonian://ui/panels/{panel_id}`

### 4. Treat UI as Data

Represent UI panels as specs:

```json
{
  "id": "performance-panel-2026-05-07",
  "title": "Live Set Performance Panel",
  "permissions": ["read_session", "transport_control", "launch_scene"],
  "widgets": [
    {"type": "scene_button", "scene_id": "scene-1", "label": "Intro"},
    {"type": "macro_slider", "track_id": "bass", "device_id": "filter", "macro": 1}
  ]
}
```

A spec can render in an MCP App, local web panel, or DAW-native adapter. This is
how custom interfaces become portable.

### 5. Build a Policy Engine

Every action should pass through policy:

- Is this read-only?
- Does the adapter report the capability?
- Is the action destructive?
- Does it require user confirmation?
- Is the transport playing?
- Is this allowed from generated UI?
- Is this allowed from a remote host?

The policy engine is what lets wild interfaces remain trustworthy.

### 6. Add Event Streams Carefully

Many of the best ideas need events: selected track changed, clip launched,
transport moved, device parameter changed, plan applied. But event streams can
become noisy and host-specific. Start with low-rate semantic events, not raw DAW
telemetry.

### 7. Separate Realtime and Agentic Paths

Do not put model calls in any path that must be musically realtime. Use models to
prepare states, plans, variations, mappings, and explanations. Use deterministic
local code for performance-critical execution.

## Possible North Stars

These are product slogans that imply different companies/projects.

1. **"Cursor for Ableton"**: edit a Live Set with agentic plans, diffs, and
   project-aware commands.
2. **"Figma plugins for music workflows"**: users generate and share custom DAW
   panels and micro-tools.
3. **"A local AI memory for your music"**: every project, sample, bounce, and idea
   becomes searchable/actionable.
4. **"The open DAW bridge for agents"**: infrastructure others build on.
5. **"An AI bandmate that never takes the wheel without asking"**: performance
   preparation, improvisation, and safe live control.
6. **"A mentor inside your actual session"**: project-aware teaching and guided
   improvement.

## My Bias

The most exciting path is a hybrid of **Direction 1**, **Direction 2**, and
**Direction 8**:

> A local-first Ableton-aware core that can generate safe, project-specific UI
> surfaces: sometimes inside Ableton, sometimes inside Claude/MCP Apps, sometimes
> as reusable personal micro-tools.

That is more boundary-pushing than a chat bot and more defensible than a single
sidebar. It lets musicians create their own Ableton interfaces without requiring
them to become Max for Live developers, Remote Script authors, or web engineers.

The first demo should be humble but revealing:

1. read or simulate a Live Set;
2. draft a musical action plan;
3. render an interactive approval UI;
4. apply approved non-destructive changes through the bridge;
5. save the generated panel/plan as a sidecar artifact.

If that feels magical, the project has a center of gravity.

## External References

- MCP Apps official docs: <https://modelcontextprotocol.io/docs/extensions/apps>
- MCP Apps announcement: <https://blog.modelcontextprotocol.io/posts/2026-01-26-mcp-apps/>
- MCP Apps API reference: <https://apps.extensions.modelcontextprotocol.io/api/>
- MCP architecture overview: <https://modelcontextprotocol.io/docs/learn/architecture>
