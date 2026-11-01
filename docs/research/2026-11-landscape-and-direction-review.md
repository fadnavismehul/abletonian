# Landscape and direction review, November 2026

**Date:** 2026-11-01
**Scope:** Is abletonian's strategic direction ("a harness for musicians working
mainly with Ableton, kept flexible for other DAWs") still right, given the
Ableton Extensions SDK, Max for Live, and the current crop of DAW MCP servers?
**Method:** Web research on 2026-11-01 (sources at the end) plus a read of this
repo at commit `ae5f909`. Facts are cited; opinions are marked as such. Several
primary sites (ableton.com, help.ableton.com, ableton.github.io,
docs.cycling74.com, news.ycombinator.com, cdm.link) could not be reached from
the research environment; where a claim rests only on search snippets or
second-hand write-ups it is marked **(unverified)**.

## 1. Summary and verdict

**The direction is sound. The premise behind it is not.** Abletonian's bet, a
small, typed, safety-first MCP surface in front of a Live bridge, with a fake
adapter for CI and an RFC process, is the right bet. But the belief that
"nobody else is building quite this" is wrong on the bridge level and only
partly right on the product level:

- On 2026-11-01 GitHub lists roughly thirty Ableton MCP servers. The largest,
  `ahujasid/ableton-mcp`, has about 3,300 stars and was still receiving commits
  in September 2026. At least eight projects already run an MCP server
  *inside* Live on the official Extensions SDK, and three of them
  (`t1merickson/next-live-mcp`, `ulm0/ableton-live-mcp`, `SamKuler/live-smith`)
  explicitly compete on the same ground abletonian claims: capability honesty,
  single-undo writes, scoped permissions, in-Live confirmation.
- No project combines everything abletonian is trying to combine: a musician
  intent layer over typed workflows (Drum Rack extraction, Macro Cockpit), a
  cited manual index, a fake adapter with golden tests, a dated Live
  validation log, and a written safety model. That combination is the
  defensible position. The Remote Script bridge is not.

**The Extensions SDK does not make the Remote Script obsolete today, but it
changes what abletonian should treat as its primary surface over the next
year.** The SDK is a Suite-only public beta, extensions are user-invoked from
context menus, and the API lacks things abletonian already ships (output
routing, track colour, transport, automation, plug-in loading). But it is the
first officially sanctioned, versioned, transactional (`withinTransaction` = one
undo step) way to edit a Live Set, and it gives extensions a webview UI, which
is exactly the in-Live surface RFC 0002 and the product vision want. The right
move is a second Ableton adapter behind the same bridge protocol, not a
rewrite, and an RFC that decides which surface becomes primary once the SDK
leaves beta.

**The DAW-abstraction boundary is in the wrong place.** `src/abletonian/server.py`
calls `bridge_client.request("ableton.list_tracks", ...)` and its siblings
directly (13 call sites); there is no adapter interface in the Python process,
`DawProfile` is static metadata, and the fake adapter implements the Drum Rack
and Macro Cockpit methods but none of the fifteen `live_ops` methods. Adding an
Extensions adapter will force this to be fixed anyway; doing it first makes the
Extensions work smaller and makes the multi-DAW claim true rather than
aspirational.

Top recommendations, in order (details in section 7):

1. Reframe the pitch around the harness (safety, workflows, grounding,
   verification), not the bridge, and say plainly that the bridge is a
   replaceable adapter even within Ableton.
2. Introduce an in-process `DawAdapter` interface with typed operations; make
   the Remote Script client and the fake adapter two implementations of it.
   Needs an RFC (it spans server, bridge, and Remote Script).
3. Write an RFC for an Extensions SDK adapter and build a read-only spike to
   measure the coverage gap against `live_ops.py` on a real Live build.
4. Harden the bridge: move off port 9877 (shared with at least two other
   projects), add a per-session token, add MCP tool annotations. Protocol
   change, so an RFC, but a short one.
5. Bring the fake adapter to parity and add golden workflow tests before
   adding more tools.
6. Plan the in-Live UI as an Extension webview, not a Max for Live device.
7. Do not start a second DAW yet. When you do, REAPER is a better second
   target than FL Studio.

## 2. The Ableton Extensions SDK

### What it is

Announced 2026-06-02 as "an experimental playground inside Live" (KVR news index
dates the announcement to 02 Jun 2026; the first community extension collection
went public on 2026-06-01). Facts gathered from the Ableton FAQ snippet, launch
coverage, and community write-ups:

- **Availability.** Live 12 **Suite** beta 12.4.5 or later. The FAQ says
  Extensions are not available in Standard, Intro, or Lite **(FAQ reached only
  via search snippets)**. Beta release notes for 12.4.5b11 (2026-08-12) still
  list Extensions SDK fixes; one recent extension requires 12.4.15b5. Whether
  Extensions are enabled in a *stable* Live build on 2026-11-01 could not be
  confirmed; a search snippet of Wikipedia gives 12.4.5 (2026-08-26) as the
  stable release, and abletonian's own validation log records Live 12.4.16.
- **Runtime and language.** TypeScript/JavaScript on Node.js 24 inside an
  "Extension Host" process that Live owns. One community reference describes
  it as full Node (`node:fs`, `node:child_process`, outbound HTTPS all work,
  "not a sandboxed JS dialect"); another project page says the host is a V8
  context without web globals such as `fetch`. Treat the permission model as
  **undocumented** until the official docs are read.
- **Packaging.** `npm run package` produces an `.ablx` archive; users drag it
  onto Settings > Extensions. Unsigned extensions need Developer Mode. There is
  no official marketplace; a community directory (liveextensions.dev) exists
  **(unverified)**.
- **Lifecycle.** An extension exports `activate()`, calls `initialize()`, and
  registers commands plus context-menu actions. Ableton's framing is "run when
  the user invokes it"; extensions cannot trigger on launch or on Live events.
  In practice several projects start an HTTP server at activation and it keeps
  running while Live is open, so a long-lived MCP endpoint inside the host is
  possible, but it is an unofficial pattern and may not survive the beta.

### What the API exposes (as documented second-hand)

From a community skill that mirrors the SDK's TypeDoc reference
(`Ronvaknins/ableton-extensions-skill`, `reference/api.md`), API version 1.0.0:

| Area | Exposed |
| --- | --- |
| Song | `tracks`, `returnTracks`, `mainTrack`, `scenes`, `cuePoints`, `tempo`, scale, grid; `createAudioTrack`, `createMidiTrack`, `createScene`, `deleteTrack`, `deleteScene`, `duplicateTrack`, `duplicateScene` |
| Track | `name`, `arm`, `mute`, `solo`, `groupTrack`, `mixer`, `devices`, `clipSlots`, `arrangementClips`, `takeLanes`; `insertDevice(name, index)`, `duplicateDevice`, `deleteDevice`, `deleteClip`, `clearClipsInRange`; `MidiTrack.createMidiClip`, `AudioTrack.createAudioClip` |
| Clips | name, colour, loop/markers, `MidiClip.notes` (whole-array get/set), `AudioClip` warp mode and markers |
| Devices | `Device.parameters`, `RackDevice.chains`, `DrumRack`, `Chain.devices`/`mixer`, `DeviceParameter.getValue/setValue` with `valueItems` |
| Transactions | `context.withinTransaction(fn)`: one undo step, nested calls collapse |
| UI | `registerContextMenuAction(scope, ...)`, `showModalDialog(url, w, h)` (webview; `data:` or `http://localhost` URLs), `withinProgressDialog` with abort |
| Files/audio | `importIntoProject`, `renderPreFxAudio(track, start, end)` to WAV |
| Selection | context-menu scopes for clips, tracks, clip slots, scenes, samples, Simpler, Drum Rack, arrangement and clip-slot selections |

Consistently reported as **missing** across the projects that have shipped on
it: transport and clip launching, input/output routing, track colour (one
project), automation envelopes and clip envelopes, loading third-party VST/AU
or browser presets (native devices by exact name only), Live's browser, hardware
control surfaces, real-time audio or MIDI, and anything that runs without a
user gesture. Object handles are invalidated by deletes and moves, so clients
must re-list after structural edits.

### Implications for abletonian

Comparison with what abletonian's Remote Script already does
(`remote_scripts/Abletonian/live_ops.py`, adapter 0.4.1):

| abletonian capability today | Remote Script | Extensions SDK |
| --- | --- | --- |
| list tracks with routing, sends, colours | yes | partial (no routing; colour unclear) |
| list devices with parameters, rack chains, Drum Rack return chains | yes | yes (chains, parameters) |
| set parameter by display text (`str_for_value`) | yes | `valueItems` for quantized only; display-text matching would need re-implementing |
| set output routing | yes | **no** |
| rename/recolour track | yes | rename yes; colour unverified |
| mixer volume/pan/sends/mute/solo | yes | `TrackMixer` exists; detail undocumented here |
| insert native device at position | yes (Live 12.3+) | yes |
| create return track | yes | not listed (audio/MIDI tracks only) |
| delete device with confirm | yes | yes |
| batch as one undo step | yes (`begin_undo_step`) | yes (`withinTransaction`) |
| undo | yes (`Song.undo`) | not exposed |
| selected track/device context | yes | only via context-menu scope at invocation |
| Drum Rack extraction (duplicate track, filter notes) | yes | plausible (`duplicateTrack`, `MidiClip.notes`) |
| Macro Cockpit read | yes | plausible (`RackDevice` parameters) |
| works on Live Standard/Intro | yes | **no** |
| official, versioned API | no | yes |
| in-Live UI | no | webview dialogs |

Reading of this (opinion):

- **Do not migrate now.** Abletonian would lose routing, undo, return-track
  creation, selection polling, and every non-Suite user, in exchange for an
  API that is still changing between betas.
- **Do not ignore it either.** It is the only route Ableton has blessed, the
  only one with a transaction primitive designed for exactly abletonian's
  "one undo step, fail closed" rule, and the only one that gives a UI without
  Max for Live. Two of the best-engineered competitors (`next-live-mcp`,
  `ulm0/ableton-live-mcp`) chose it.
- **Run both, behind one protocol.** The bridge protocol is transport-agnostic
  JSON frames; an Extension can open the same TCP listener (or abletonian's
  client can speak HTTP to it) and answer the same `daw.health` with its own
  capability list. The capability handshake abletonian already has is the
  right mechanism for letting the server pick or combine adapters. `ntworm/
  ableton-mcp-server` and `pnomolos/live-wire` already run a Remote Script and
  an Extension side by side; abletonian can do it more cleanly because the
  protocol is designed for it.
- **The Extension is the right home for the UI.** RFC 0002's Macro Cockpit
  page and the vision's "plan review" and "context strip" fit
  `showModalDialog` plus a context-menu action ("Abletonian: review plan for
  this track") better than a Max for Live device, and without the Max for Live
  dependency the vision already tries to avoid.

## 3. Max for Live

Facts (Cycling '74 docs reachable only via snippets, plus older forum threads):

- M4L reaches Live through the Live Object Model via `live.object`,
  `live.path`, `live.observer`, `live.remote~`, and the JavaScript `LiveAPI`
  object. It is officially documented and stable across Live versions. It is
  limited to what the LOM document lists; Remote Scripts can reach a larger,
  undocumented Python surface (for example `str_for_value`, which abletonian
  relies on for display-text matching).
- `live.remote~` is the one path with audio-rate parameter control; everything
  else runs at low priority, like a Remote Script.
- Several MCP projects use an M4L device as an audio tap or analyser
  (`dreamrec/LivePilot`, `bschoepke/ableton-live-mcp`, `pnomolos/live-wire`),
  because neither Remote Scripts nor the Extensions SDK can read live audio
  (the SDK can only render pre-FX audio to a file).

Opinion: M4L is a complement, not a bridge candidate. It requires Suite like
the SDK, it has to be dragged onto a track, its UI is a device panel rather
than a dialog, and it adds a third runtime (Max/JS) to maintain. Its unique
value for abletonian is audio observation (meters, spectrum) for a future
"did that change make it louder?" loop. That is a Phase 4+ concern; it should
be an optional sensor behind the same capability handshake, not a dependency.
The vision's Phase 4 ("Max for Live companion device or local panel") should
be rewritten with the Extension webview as the default.

## 4. Competitive landscape

Stars and last-push dates are from the GitHub search API on 2026-11-01.
Tool counts and safety claims are from each project's README as read that day.

### Ableton

| Project | Bridge | Stars / last push | Scope | Safety approach | License |
| --- | --- | --- | --- | --- | --- |
| `ahujasid/ableton-mcp` | Remote Script, TCP JSON (unframed), port 9877 | 3,285 / 2026-09-22 | tracks, clips, notes, browser loading, transport | version handshake; telemetry (README says on by default; a Sep 2026 commit says "opt in"); no undo grouping or confirm | MIT |
| forks: `vittorfp`, `waltzforvenus` (86 tools), `ringo380` (191), `LofiFren`, `kovtun-oleksii` | same | low stars, active 2026 | more tools | `vittorfp`: two-step guarded delete, undo preview | MIT |
| `uisato/ableton-mcp-extended` | Remote Script | 280 / 2026-05-07 | broad | not documented | MIT |
| `bschoepke/ableton-live-mcp` | Remote Script + M4L audio tap | 236 / 2026-10-06 | arbitrary Python eval in Live | "back up your set first" | MIT |
| `wstierhout/ableton-live-mcp` | Remote Script, **port 9877**, 156 tools, offline `.als` | 65 / 2026-10-23 | very broad | no arbitrary code, read-only/destructive hints, batch = one undo step, warns no auth | MIT |
| `dreamrec/LivePilot` | Remote Script (9878) + optional M4L analyser | 91 / 2026-10-29 | 474 tools, device atlas, Splice | plans before execution, dry-run defaults | **BSL 1.1** |
| `jpoindexter/ableton-mcp` | Remote Script + M4L + REST | 60 / 2026-05-01 | 200+ tools | not documented | MIT |
| `OthmanAdi/loophole` | **Extensions SDK**, HTTP+SSE, bearer token | 22 / 2026-10-11 | 12 tools + 5 workflows | zod validation, opaque handles, serialised writes, opt-in deletes | MIT |
| `jasper-zheng/ableton-sdk-mcp` | Extensions SDK, WebSocket, `run_code` | 19 / 2026-06-15 | reads + arbitrary TS | in-Live confirm dialog per edit | not stated |
| `SamKuler/live-smith` | Extensions SDK, in-Live chat assistant | 11 / 2026 | full assistant, optional MCP server | edit scopes, approval modes, plan validation, re-check state | not stated |
| `ulm0/ableton-live-mcp` | Extensions SDK, Streamable HTTP | 1 / 2026-10-31 | tracks, scenes, clips, notes, devices, racks, mixer, render | loopback + Host/Origin checks, token, read-only mode, MCP annotations, batch = one undo step, `show_dialog` confirm | MIT |
| `idx3d/ableton-mcp-extension`, `t1merickson/next-live-mcp` | Extensions SDK | 2 / 0 stars, active to 2026-09 | 21-23 tools | named undo step per write, all-or-nothing batch, structured errors, `ableton://capabilities` resource with "evidence level" | MIT |
| `ntworm/ableton-mcp-server` | Remote Script (9888) **and** Extension Host (9889) | 4 / 2026 | 97 tools | verification after write, structured errors | MIT |
| `pnomolos/live-wire` | Extension + M4L LOM proxy | 7 / 2026-06 | general LOM | none documented | GPL-3.0 |
| `ideoforms/AbletonOSC` / `pylive` | Remote Script, OSC 11000/11001 | 839 / 632 | near-full LOM | none (control protocol) | MIT |
| `nozomi-koborinai/ableton-osc-mcp` | AbletonOSC | 15 / 2026-10-24 | OSC passthrough | none | MIT |
| **abletonian** | Remote Script, framed TCP, port 9877 | 0 / 2026-11-01 | 26 tools, 2 workflows, manual search | classified ops, confirm=true, batch = one undo step, fail closed, dated Live validation log | MIT |

Also relevant: Anthropic shipped an official "Ableton Live" connector on
2026-04-28. It grounds answers in Ableton's Live and Push documentation and
does not control Live (anthropic.com/news/claude-for-creative-work). That is a
direct, first-party overlap with abletonian's RTFM pillar, though abletonian's
version is local, edition-pinned, and tied to "can we automate this?".

### Other DAWs

| DAW | Strongest community servers (stars / push) | Bridge used | Note |
| --- | --- | --- | --- |
| REAPER | `bonfire-systems/reaper-mcp` 175, `dschuler36` 135 (file-only, read-only), `xDarkzx/Reaper-MCP` 112 (181 tools), `TwelveTake` 102, `shiehn/total-reaper-mcp` 87 | reapy/distant API, Lua file IPC, ReaScript | deepest scripting API of any DAW; several mature projects |
| FL Studio | `karl-andres/fl-studio-mcp` 249, `rosasynthesiz` 119 | JSON files + virtual MIDI trigger + keystrokes | fragile by design. FL Studio 2026 (July 2026) ships **Gopher**, a built-in AI assistant that can control the project |
| Logic Pro | `MongLong0214/logic-pro-mcp` 165 (4,262 commits, "fail-closed", 7 macOS channels), `koltyj` 131 | AppleScript, Accessibility, MCU, CoreMIDI | no public API; impressive but inherently brittle |
| Bitwig | `WeModulate` 77 (stale), `fabb/WigAI` 62 (archived), `Evreke/maestro-bridge` 166 tools | Java controller extension | official extension API, small AI community |
| Pro Tools | `skrul/protools-mcp-server` 21 | PTSL gRPC | read-only by default, write groups by risk |
| Cubase | `muhwagwa0112/cubase-complete-mcp`, `yoka-cubase-mcp` | MIDI Remote API / Mackie Control | controller-grade only |
| Studio One | `NeanderthalMan/studio-one-mcp` 12 | `.song` files + commands | early |
| Multi-DAW | `user1303836/kumi` 24 (Live, REAPER, Renoise; writes per-DAW scripts), `ptaczek/daw-mcp` 22 (Bitwig + Ableton, MIDI clips only), `ryurikoneko/DAWLoop` 17 (VST3 plugin bridge) | mixed | nobody has a credible shared capability model yet |

### Where abletonian is differentiated, and where it overlaps

Differentiated (nobody else has all of these; only `next-live-mcp` and
`live-smith` have more than one):

- Written safety classification with required guards per class, enforced in
  code (`StrictBool` confirm, refusal of unconfirmed deletes in a batch,
  rollback of failed inserts).
- Musician workflows as the product unit (Drum Rack extraction, Macro Cockpit)
  instead of tool count. Most competitors advertise 100-474 tools.
- Manual index pinned to Ableton's published edition, with citations.
- Fake adapter plus LOM-shaped unit tests plus a dated validation log that
  records what actually happened in Live, including failures (Valhalla
  display text, undo merging).
- RFC process, AI-assistance disclosure, contribution path for non-coders.

Overlapping (abletonian is not ahead here, and sometimes behind):

- The Remote Script bridge itself: `wstierhout` and `ahujasid` cover far more
  of the LOM on the same port. `LivePilot` has capability tiers by Live
  version, which abletonian's `daw.health` only approximates.
- Transport security: `ulm0`, `idx3d`, `loophole` have loopback plus token plus
  Host/Origin checks; abletonian has loopback only.
- MCP tool annotations (`readOnlyHint`, `destructiveHint`): `ulm0` and
  `wstierhout` ship them; abletonian documents classes in prose.
- Capability honesty as a *resource* the client can read:
  `next-live-mcp` exposes `ableton://capabilities` with evidence levels;
  abletonian has `check_bridge_health` as a tool.

## 5. Architecture review

What exists (from the code, not the docs):

- `server.py` builds 26 MCP tools and calls `BridgeClient.request()` with
  literal `ableton.*` method names. The `DawProfile` in `daws.py` is
  descriptive metadata returned by `get_target_daw_profile`; nothing routes on
  it. `--target-daw fl-studio` changes a string in responses, not behaviour.
- The bridge protocol (`bridge/protocol.py`) is clean: framed JSON, request
  IDs, `ok/result/error`, typed error payloads with hints. `dispatcher.py`
  lets any object with `handle_request` serve it, which is how the fake
  adapter and the Remote Script are tested the same way.
- The Remote Script runs every request on Live's main thread via
  `schedule_message`, with a start deadline so a client that gave up never
  sees a late mutation. This is better than most competitors, several of which
  touch the LOM from the socket thread.
- `FakeAbletonAdapter` implements health, selected context, rack macros, and
  the Drum Rack plan/execute. It does not implement `list_tracks`,
  `set_mixer`, `insert_device`, `delete_device`, `batch`, or `undo`, so the
  tools that musicians actually use today are tested only through LOM-shaped
  fakes in `tests/test_live_ops.py`, not end to end.
- `adapters/remote_script.py` is a 580-line early copy used only by tests
  (AGENTS.md says so). It is dead weight that confuses the adapter story.

Is the shape right? Mostly yes:

- Server outside Live, thin in-Live agent, framed protocol, fake adapter: this
  is the shape that both the Remote Script and Extensions SDK ecosystems are
  converging on, and it is the only shape that survives a change of bridge.
- The safety model is the right unit of design. Its weakness is that it lives
  in prose and in per-tool code rather than in a reusable layer; a new tool
  can forget it.

Is the DAW-abstraction boundary in the right place? No:

- The abstraction boundary today is the *wire* (method names). That couples
  the MCP tools to one adapter's vocabulary. Adding an Extensions adapter that
  cannot do `ableton.set_track_output_routing` has nowhere to say so except by
  returning an error at call time.
- The right boundary is an in-process `DawAdapter` protocol with typed
  operations (`list_tracks() -> TrackList`, `set_mixer(ref, MixerChange)`,
  etc.) and a `capabilities()` method. `RemoteScriptAdapter` and
  `ExtensionAdapter` translate to their own wire methods; `FakeAdapter`
  implements the protocol directly; the MCP tools and workflows depend only on
  the protocol and on a `SafetyPolicy` that wraps every mutating call
  (classification, confirm, undo grouping, manifest). This is also where
  "advertise what the adapter can actually do" becomes real.
- The shared capability vocabulary in `daw-targets.md`
  (`track_management`, `mixer_control`, ...) is too coarse to drive this. The
  Remote Script's `daw.health` list (`set_mixer`, `insert_device`, ...) is the
  right granularity; the coarse list is fine for the profile page.

Concrete risks, ordered by how soon they bite:

1. **Port 9877 collision.** `ahujasid/ableton-mcp` and `wstierhout/ableton-live-mcp`
   both listen on 9877 inside Live. A user with either installed gets
   confusing failures, and if their server is the one running, abletonian's
   client will send framed bytes to an unframed JSON server. Pick a new default
   and have `daw.health` identify the adapter before anything else is sent
   (the client already checks `protocol_version`; make a mismatch a clear
   "another Ableton MCP script is on this port" message).
2. **No authentication on the bridge.** Any local process can edit the user's
   set. Competitors on the SDK ship a per-install token. The safety doc already
   calls for one "once external clients are supported beyond stdio"; the
   Remote Script *is* an external listener now.
3. **Fake adapter drift.** The tools most used in the validation log have no
   fake, so workflow-level regressions reach Live before anyone notices.
4. **Undocumented LOM dependencies.** Display-text matching through
   `str_for_value`, `_live_ptr` identity, and `Track.insert_device` are all
   undocumented or recent. The validation log is the mitigation; an Extensions
   adapter that uses `valueItems` would be the escape hatch for one of them.
5. **Validation bottleneck.** One maintainer with one Live build on macOS is
   the only verification path. The project cannot credibly claim multi-DAW
   when it cannot yet claim multi-OS for one DAW.
6. **Suite-only drift.** If Ableton's next move is to make the Extensions SDK
   the only sanctioned path and to tighten Remote Script loading (no evidence
   of this; opinion), abletonian's non-Suite users are stranded either way.
   This is a reason to keep both adapters, not to pick one.

## 6. Is the "harness" framing right?

Opinion: yes, and it should be stated more sharply, because it is the only
framing under which abletonian is not one of thirty.

A harness in this sense is the layer that decides what an agent may do to a
Live Set, how a change is proposed, checked, applied, and undone, and how the
result is verified and recorded. That layer is independent of whether the
hands inside Live are a Remote Script, an Extension, or an OSC bridge, and it
is the layer the fast-moving tool-count projects do not have. It also happens
to be the layer that transfers to another DAW; a REAPER adapter would reuse
the safety policy, the plan format, the manifest, and the validation log
format even though none of the Live code transfers.

The owner's instinct that there is room for multiple tools is right too, but
with a sharper reason: the bridge market will consolidate around whatever
Ableton ships (as Blender's did when an official MCP arrived, per 2026
coverage, **unverified**), while the harness market is open because it is a
product question, not an API question.

## 7. Recommendations

Each entry says why, what it costs, and whether AGENTS.md requires an RFC.

### P0. Reframe the docs around the harness. No RFC.

Update `README.md`, `docs/product/vision.md`, and `integration-options.md` to
say: the product is the safety and workflow layer; the Remote Script is the
first of at least two Ableton adapters; the Extensions SDK is the second;
other DAWs come after the second Ableton adapter proves the boundary. Add a
short "related projects" section (section 4 of this review) so contributors
and users can see what abletonian is and is not. Cost: a day.

### P1. Introduce `DawAdapter` and `SafetyPolicy` in the Python core. RFC.

Define a protocol with typed operations matching today's `live_ops` methods
plus `capabilities()`. Move the `ableton.*` wire calls into
`RemoteScriptAdapter`. Make `FakeAbletonAdapter` implement the same protocol
with full parity. Route every mutating tool through one `SafetyPolicy` object
that applies classification, confirm, undo grouping, and manifest recording,
so a new tool cannot skip the rules. Delete `adapters/remote_script.py` or
turn it into the new adapter. This is the refactor "that spans the MCP server,
the bridge, and the Remote Script", so it needs an RFC (0003). Cost: one to
two weeks; the Remote Script barely changes.

### P2. Extensions SDK adapter: spike, then RFC. RFC.

Before writing the RFC, build a throwaway read-only extension that answers
`daw.health`, `list_tracks`, and `list_devices` over the existing framed
protocol from inside the Extension Host, and run it against the same First
Light set. Record, per `live_ops` method, whether the SDK can do it, cannot,
or can do it differently (for example `valueItems` instead of `str_for_value`).
That table is the heart of RFC 0004, which should decide: (a) the Extension is
a second adapter with its own capability list; (b) which adapter the server
prefers when both answer; (c) whether the Extension also hosts the UI
(section 2); (d) what happens on Live Standard. Prerequisites: a Suite beta
licence and Node 24 on the validation machine. Cost: spike one week, RFC one
week, adapter several weeks. Do not start the adapter before P1.

### P3. Bridge hardening. Short RFC (protocol change).

Change the default port away from 9877 (document the collision), add a
per-install token written to the user data folder by the installer and
checked by the Remote Script, make `daw.health` the mandatory first frame and
reject anything else before it, and add MCP tool annotations
(`readOnlyHint`, `destructiveHint`, `idempotentHint`) derived from the safety
classification so clients can auto-approve reads. Cost: a few days.

### P4. Fake adapter parity and golden workflow tests. No RFC.

For every `live_ops` method, a fake implementation and at least one golden
test (input state, operation, expected plan, expected post-state) as
`robustness-and-safety.md` already prescribes. Gate new tools on "fake first".
Cost: ongoing; a week to catch up.

### P5. In-Live UI as an Extension webview. RFC (new user-facing surface).

Replace the Phase 4 "Max for Live companion" with an Extension that adds
context-menu actions ("Abletonian: review plan", "Abletonian: cockpit for this
rack") and shows the existing cockpit HTML in `showModalDialog`. RFC 0002's
renderer already produces self-contained HTML with no scripts, which is
exactly what a `data:` URL dialog wants. Depends on P2's findings about dialog
limits (modal; cannot be closed from code). Cost: after P2.

### P6. Second DAW: not yet, and REAPER before FL Studio. RFC when started.

`daw-targets.md` lists FL Studio as the second target. On the evidence, REAPER
is better: a deep, documented scripting API, Linux support (which would also
unblock CI-style validation), and the largest non-Ableton MCP community to
learn from. FL Studio bridges rely on virtual MIDI triggers and keystrokes, and
Image-Line now ships its own assistant. Either way, do not start until P1 has
been exercised by two Ableton adapters; a capability vocabulary designed from
one adapter will be wrong.

### P7. Interoperate rather than compete on coverage. No RFC.

Abletonian will not out-tool `LivePilot` or `wstierhout`. Consider: accepting
AbletonOSC as a read-only adapter for users who already have it; publishing
the plan/manifest JSON format so other servers could emit it; and reviewing
`next-live-mcp`'s capabilities resource and `live-smith`'s edit scopes for
ideas worth adopting (both are MIT or unstated; check before copying code).

## 8. Open questions for the owner

1. Do you have, or can you get, a Live 12 Suite beta licence plus Node 24 on
   the validation machine? Without it P2 and P5 cannot start.
2. Is Live Standard/Intro support a requirement? If yes, the Remote Script
   stays primary indefinitely and the Extension is UI plus a secondary
   adapter. If no, the Extension could become primary once stable.
3. How much do you want to compete on the RTFM pillar now that Anthropic
   ships an official documentation connector? The local, edition-pinned,
   "can we automate this?" angle is still unique, but the plain Q&A part is
   not.
4. Is BSL-style source-available licensing (as `LivePilot` chose) something you
   want to rule out explicitly? The MIT choice is a differentiator; say so if
   it is deliberate.
5. Who else can run validations? The single-validator bottleneck is the
   project's biggest practical risk; a "run this checklist in your Live and
   file a report" issue template would widen it.
6. Are you willing to change the default port? It breaks existing installs
   (there may be none yet), which is the best time to do it.
7. Which second DAW matters to *you*? The REAPER recommendation is on
   technical merit; if your users are FL Studio producers, that changes the
   answer even though the bridge is worse.

## 9. Claims that could not be verified

- Exact contents of the Ableton Extensions FAQ, the official SDK docs, and the
  Live 12.4.x release notes (ableton.com, help.ableton.com, ableton.github.io
  unreachable). The API table in section 2 is from a community mirror of the
  TypeDoc reference and may lag the SDK.
- Whether Extensions are enabled in a stable (non-beta) Live build as of
  2026-11-01, and whether "Live 12.4.16" in abletonian's validation log is a
  beta.
- The Extension Host permission model (full Node vs restricted V8); sources
  conflict.
- Whether `ahujasid/ableton-mcp` telemetry is currently on or off by default;
  README and a September 2026 commit message disagree.
- Blender shipping an official MCP server in 5.1, and the existence of a
  liveextensions.dev directory; both from search snippets only.
- Cycling '74 Max for Live documentation (docs.cycling74.com unreachable);
  M4L statements rest on older forum threads and this repo's existing docs.
- Licences for `jasper-zheng/ableton-sdk-mcp` and `SamKuler/live-smith` (not
  stated on their README pages).

## 10. Sources

All accessed 2026-11-01. Pages marked "snippet" were seen only through search
result summaries because the host was unreachable from the research
environment.

Ableton Extensions SDK

- Ableton, "Introducing Extensions SDK" blog post, https://www.ableton.com/en/blog/introducing-extensions-sdk/ (snippet)
- Ableton, Extensions SDK page, https://www.ableton.com/en/live/extensions/ (snippet)
- Ableton, Extensions FAQ, https://help.ableton.com/hc/en-us/articles/27303428331420-Ableton-Extensions-FAQ (snippet)
- Ableton, Live 12 beta release notes, https://www.ableton.com/en/release-notes/live-12-beta/ (snippet)
- chris-arsenault, SDK notes, https://github.com/chris-arsenault/ableton-extensions/blob/main/docs/extensions-sdk.md
- Ronvaknins, ableton-extensions-skill README and `reference/api.md`, https://github.com/Ronvaknins/ableton-extensions-skill
- federico-pepe, ableton-live-extensions, https://github.com/federico-pepe/ableton-live-extensions
- KVR news index entries for 2026-06-02 (SDK announcement) and 2026-05-06 (Live 12.4), https://www.kvraudio.com/ (snippet)
- CDM, "Ableton Extensions will let you code your own tools", https://cdm.link/ableton-extensions-beta/ (snippet); "There are already some great uses of Ableton Extensions", https://cdm.link/first-ableton-extensions-arriving/ (snippet)
- Isotonik Studios, "Ableton Extensions Explained", https://isotonikstudios.com/ableton-extensions-explained-what-they-are-and-how-to-try-them-free/ (snippet)

Ableton MCP servers and bridges

- https://github.com/ahujasid/ableton-mcp and its commit log
- https://github.com/vittorfp/ableton-mcp
- https://github.com/uisato/ableton-mcp-extended
- https://github.com/bschoepke/ableton-live-mcp
- https://github.com/wstierhout/ableton-live-mcp
- https://github.com/dreamrec/LivePilot
- https://github.com/OthmanAdi/loophole
- https://github.com/jasper-zheng/ableton-sdk-mcp
- https://github.com/SamKuler/live-smith
- https://github.com/ulm0/ableton-live-mcp
- https://github.com/idx3d/ableton-mcp-extension
- https://github.com/t1merickson/next-live-mcp
- https://github.com/ntworm/ableton-mcp-server
- https://github.com/pnomolos/live-wire
- https://github.com/ideoforms/AbletonOSC
- https://github.com/ideoforms/pylive
- GitHub search API, queries "ableton mcp", "ableton extension sdk mcp", "ableton extensions", sorted by stars, 2026-11-01

Other DAWs and industry

- https://github.com/bonfire-systems/reaper-mcp
- https://github.com/dschuler36/reaper-mcp-server
- https://github.com/xDarkzx/Reaper-MCP
- https://github.com/fabb/WigAI
- https://github.com/karl-andres/fl-studio-mcp
- https://github.com/MongLong0214/logic-pro-mcp
- https://github.com/skrul/protools-mcp-server
- https://github.com/user1303836/kumi
- https://github.com/ptaczek/daw-mcp
- https://github.com/ryurikoneko/DAWLoop
- GitHub search API, queries "bitwig mcp", "fl studio mcp", "logic pro mcp", "pro tools mcp", "studio one mcp", "cubase mcp", 2026-11-01
- Anthropic, "Claude for creative work" (2026-04-28), https://www.anthropic.com/news/claude-for-creative-work
- RouteNote, "FL Studio 2026 turns Gopher into your AI production assistant", https://routenote.com/blog/fl-studio-2026-gopher-ai-production-assistant/ (snippet)
- Sound On Sound, "Bitwig Studio 6 launches", https://www.soundonsound.com/news/bitwig-studio-6-launches (snippet)
- MIDI Association, MIDI 2.0 developer resources, https://midi.org/curated-midi-2-0-resources-for-developers (snippet)
- Cycling '74, Live API overview and Max for Live limitations, https://docs.cycling74.com/userguide/m4l/live_api_overview/ and https://docs.cycling74.com/userguide/m4l/live_limitations (snippet); forum threads "Controller python script or M4L?" and "searching for a device displaying parameter value", https://cycling74.com/forums/ (snippet)
