# RFC-001: Ableton Deep Integration Foundation

**Status:** Implemented
**Created:** 2026-05-23  
**Owner:** Core Team  
**Related Docs:** [Product Vision](../../vision.md), [Design Philosophy](../../../design/philosophy.md), [Integration Options](../../../engineering/integration-options.md), [Robustness and Safety](../../../engineering/robustness-and-safety.md)  
**Implementation Status:** Implemented: fake adapter health/execution, framed
bridge dispatch, RTFM lookup, MCP planning and confirmed execution tools, real
Remote Script selected-context reads, Drum Rack dry-run planning, scaffold track
duplication, MIDI note filtering on duplicated clips, and manual Live 12.4
validation are complete for the foundation workflow.

## Goal

Establish the first implementation direction for deeply integrated Ableton
automation in `abletonian`.

The foundation should make it possible to build safe, musician-facing workflows
such as "split this Drum Rack into separate tracks" without exposing raw DAW
internals directly to an AI agent or forcing users through brittle UI
automation.

## Problem Statement

Abletonian currently has a strong conceptual shape: MCP layer, intent layer,
bridge layer, and DAW adapter layer. It does not yet have a real Ableton bridge
or a concrete workflow that proves the architecture.

Existing projects such as `ableton-mcp` prove that a Remote Script can connect
Claude/Cursor to Ableton, but they tend to expose low-level tools with limited
safety, weak protocol framing, and little product design around musician trust.

Abletonian needs a more deliberate first path:

- deep enough to operate on tracks, clips, devices, racks, chains, and colors,
- safe enough for valuable Live Sets,
- testable without launching Ableton,
- grounded in Ableton's manual and Live Object Model,
- compatible with future in-Ableton UI surfaces.

## Scope

In scope:

- Define the preferred integration architecture.
- Define the first adapter capabilities.
- Define bridge and safety requirements.
- Define the first proving workflow: Drum Rack extraction planning and eventual
  execution.
- Define how RTFM/manual grounding participates in workflows.
- Define verification expectations before implementation begins.

Out of scope:

- Further bridge hardening beyond the first local Remote Script bridge.
- Shipping a Max for Live UI.
- Supporting non-Ableton DAWs.
- Offline `.als` mutation.
- Hard-real-time performance control through an AI loop.

## Proposal

Use a hybrid architecture:

1. **Abletonian core** remains outside Live and owns MCP, intent mapping, RTFM,
   planning, safety policy, and workflow orchestration.
2. **Framed bridge protocol** remains the boundary between the core and adapters,
   using length-prefixed JSON frames, request IDs, and typed responses.
3. **Remote Script adapter** becomes the first high-authority Ableton adapter for
   structural automation.
4. **Max for Live companion** is a future UI/context surface, not the first hard
   dependency.
5. **AbletonOSC adapter** may be used as a reference or optional adapter, but not
   as the product's safety and intent layer.
6. **Fake adapter** is required early so workflow logic is testable in CI.
7. **RTFM/manual index** becomes a read-only resource that grounds workflow
   explanations and maps Ableton concepts to automation capabilities.

The first workflow target is Drum Rack extraction because it exercises the
important surfaces:

- selected track/device context,
- Drum Rack pads/chains,
- device and chain metadata,
- clip MIDI note filtering,
- track duplication/creation,
- naming,
- color,
- safety plan,
- preservation of original material.

## Alternatives Considered

### Use ableton-mcp as the foundation

Pros:

- Already controls Ableton through a Remote Script.
- Simple and popular.
- Good proof that the basic architecture can work.

Cons:

- Protocol is raw JSON over sockets without robust framing.
- Tools are low-level and mostly string-returning.
- No tests or fake adapter.
- No first-class safety model.
- Current implementation has feature drift and unimplemented claims.

Decision: use it as inspiration and cautionary reference, not as the foundation.

### Build only on AbletonOSC

Pros:

- Existing mature Remote Script bridge.
- Broad OSC command surface.
- Good for quick prototyping.

Cons:

- OSC API is not a musician-facing intent layer.
- Safety and dry-run planning would still need to be built separately.
- Workflow-specific typed capability contracts would be easier in Abletonian's
  bridge protocol.

Decision: support as optional adapter/reference later, not the core foundation.

### Build only as Max for Live

Pros:

- Official Live API route.
- Strong in-Ableton presence.
- Good access to selected objects and observability.

Cons:

- Max for Live availability and packaging constraints.
- Not ideal as the only MCP/agent bridge.
- Some project-wide operations are more naturally handled by a Remote Script
  bridge and external core.

Decision: use Max for Live as companion surface and workflow-specific tool, not
the first sole implementation surface.

### Use UI automation

Pros:

- Can reach workflows not exposed by APIs.
- May mimic exactly what users do manually.

Cons:

- Brittle, focus-sensitive, hard to test, hard to localize.
- Poor trust foundation for valuable Live Sets.

Decision: reserve for last-resort gaps behind explicit confirmation.

## Implementation Plan

Implementation should happen through follow-up RFCs or by moving this RFC to
`inprogress` and tracking staged work.

1. Define adapter capability schema for Ableton.
2. Extend `daw.health` to report Ableton version, adapter version, protocol
   version, and capability list.
3. Build fake adapter state model for tracks, clips, devices, Drum Rack pads,
   chains, colors, and undo-like manifests.
4. Add workflow plan model and safety classification.
5. Add RTFM resource shape for manual lookup with citations.
6. Prototype read-only Ableton Remote Script adapter.
7. Add selected-context read APIs.
8. Add additive write APIs only after fake adapter tests exist.
9. Implement Drum Rack extraction as dry-run first.
10. Implement execution only after manual Ableton verification plan is written.

## Acceptance Criteria

Foundation acceptance:

- RFC process is present and documented.
- Product/design/engineering docs explain the integration strategy and safety
  posture.
- A future implementation can point to this RFC before editing bridge or adapter
  code.

Implementation acceptance, once work begins:

- `python -m unittest discover -s tests` passes.
- Fake adapter can run a Drum Rack extraction dry-run fixture.
- Bridge protocol tests cover framing, request IDs, invalid frames, and typed
  errors.
- `daw.health` reports protocol version, adapter type, and capabilities.
- RTFM lookup returns at least one cited Ableton manual section for Drum Rack
  extraction.
- No workflow execution mutates multiple objects without a dry-run plan.
- Manual Ableton verification is documented before marking the RFC done.

## Risks and Mitigations

| Risk | Mitigation |
| --- | --- |
| Remote Script API changes across Ableton versions | Version and capability handshake; keep adapter small; document tested versions |
| Accidental destructive mutation | Preserve originals by default; dry-run plans; operation manifests; explicit destructive confirmation |
| Bridge hangs Live or blocks UI | Keep adapter operations short; schedule mutations safely; timeouts; no model calls inside Live |
| Tests require Ableton | Fake adapter for CI; manual Live verification only for adapter-specific behavior |
| RTFM gets stale | Version-aware manual sources; cite URLs; no-source failure instead of invented answers |
| Max for Live availability varies | Treat M4L as companion surface, not core dependency |

## Rollout and Backout

Rollout:

1. Land docs and RFC process.
2. Build fake adapter and bridge tests.
3. Add read-only real adapter.
4. Add additive write capabilities.
5. Add workflow dry-run.
6. Add workflow execution behind explicit confirmation.

Backout:

- Keep experimental adapters opt-in.
- Preserve original Live Set material by default.
- Disable mutating tools independently from read-only tools.
- For a failing workflow, return the operation manifest and recommended Live undo
  or cleanup steps.

## Open Questions

- Should the first real adapter be a custom Remote Script, an AbletonOSC adapter,
  or both in parallel?
- What is the minimum Live version target for the first release?
- Should Max for Live be required for the first in-Ableton UI, or should the
  first UI be a local browser panel?
- How much manual content should be indexed locally versus fetched on demand?
- What is the right user-facing name for RTFM?

## References

- [Ableton Live Manual: Welcome to Live](https://www.ableton.com/en/live-manual/12/welcome-to-live/)
- [Ableton Live Manual: Extracting Chains](https://www.ableton.com/en/live-manual/11/instrument-drum-and-effect-racks/#extracting-chains)
- [Ableton Help: Installing third-party remote scripts](https://help.ableton.com/hc/en-us/articles/209072009-Installing-third-party-remote-scripts)
- [Ableton Help: Controlling Live using Max for Live](https://help.ableton.com/hc/en-us/articles/5402681764242-Controlling-Live-using-Max-for-Live)
- [Cycling '74: Live API Overview](https://docs.cycling74.com/userguide/m4l/live_api_overview/)
- [Cycling '74: Live Object Model](https://docs.cycling74.com/legacy/max8/vignettes/live_object_model?q=LOM)
- [Cycling '74: Clip Live Object Model](https://docs.cycling74.com/apiref/lom/clip/)
- [AbletonOSC](https://github.com/ideoforms/AbletonOSC)
- [ableton-mcp](https://github.com/ahujasid/ableton-mcp)

## Implementation Tracking

- **Lifecycle folder:** `done/`
- **Code entry points:**
  - `src/abletonian/als.py`
  - `src/abletonian/adapters/fake.py`
  - `src/abletonian/adapters/remote_script.py`
  - `src/abletonian/bridge/client.py`
  - `src/abletonian/bridge/dispatcher.py`
  - `src/abletonian/bridge/protocol.py`
  - `src/abletonian/manual.py`
  - `src/abletonian/server.py`
  - `remote_scripts/Abletonian/`
  - `scripts/install_remote_script.py`
  - `docs/engineering/live-validation.md`
  - `tests/test_als.py`
  - `tests/test_als_integration.py`
  - `tests/test_bridge_client.py`
  - `tests/test_bridge_dispatcher.py`
  - `tests/test_fake_adapter.py`
  - `tests/test_manual.py`
  - `tests/test_protocol.py`
  - `tests/test_remote_script_bridge.py`
  - `tests/test_remote_script_adapter.py`
  - `tests/test_remote_script_install.py`
  - `tests/test_server.py`
- **Verification:**
  - `python3 -m unittest discover -s tests -p 'test_fake_adapter.py'`
  - `.venv/bin/python -m unittest discover -s tests`
  - `.venv/bin/ruff check .`
  - `.venv/bin/python -m compileall -q src tests remote_scripts scripts`
  - `git diff --check`
  - `testing/First Light Project/First Light.als` validates a real Ableton Live
    12.4 Drum Rack dry-run: `Snare`, `Kick`, and `Closed Hi Hat` are extracted
    from the `Bossa` MIDI clip plan.
  - The same First Light fixture validates fake execution into an in-memory
    post-state with filtered output clips and no real Live Set mutation.
  - `.venv/bin/python -m scripts.install_remote_script` installs the read-only
    `Abletonian` Remote Script for manual Live validation.
  - 2026-05-27 Live validation passed against `First Light.als` on Ableton Live
    12.4.0: `daw.health` returned `adapter_type=ableton_remote_script` and
    `ableton.get_selected_context` returned track `1-C78 Core Kit` with
    `DrumGroupDevice` `C78 Core Kit`.
  - 2026-05-27 Live validation passed for real
    `workflow.plan_drum_rack_extraction`: the Remote Script returned output pads
    `Snare`, `Kick`, and `Closed Hi Hat` with MIDI filters `38`, `41`, and `42`.
  - 2026-05-27 Live validation passed for real
    `workflow.scaffold_drum_rack_extraction` with `confirm=True`: the Remote
    Script duplicated the selected Drum Rack track into
    `1-C78 Core Kit - Snare`, `1-C78 Core Kit - Kick`, and
    `1-C78 Core Kit - Closed Hi Hat`; the manifest reported
    `created_track_count=3`, `midi_filtering_applied=False`, and
    `saved_live_set=False`.
  - 2026-05-27 Live validation passed for real
    `workflow.execute_drum_rack_extraction` with `confirm=True`: the Remote
    Script duplicated and filtered the selected Drum Rack track into
    `1-C78 Core Kit - Snare`, `1-C78 Core Kit - Kick`, and
    `1-C78 Core Kit - Closed Hi Hat`; created clips were renamed
    `Bossa - Snare`, `Bossa - Kick`, and `Bossa - Closed Hi Hat` and retained
    only pitches `38`, `41`, and `42`; the manifest reported
    `created_track_count=3`, `midi_filtering_applied=True`, and
    `saved_live_set=False`.
- **Commit tags:**
  - `7ec0d37 feat: start Ableton integration foundation`
  - `977b48e feat: add read-only Ableton remote script`
  - `9e47455 fix: validate Ableton remote script in Live`
  - `f6d9662 feat: plan Drum Rack extraction through Live`
  - `06b9385 feat: scaffold Drum Rack extraction tracks`
  - `038a934 docs: plan Drum Rack execution completion`
  - `e8daddd feat: execute Drum Rack extraction in Live`
  - `38c3dc5 feat: expose confirmed Drum Rack execution tool`
- **Open follow-ups:** none for RFC-001 acceptance. Broader cleanup/undo
  automation, arbitrary MIDI note writing, and generated UI surfaces should be
  handled by follow-up RFCs.
- **Deviations from proposal:**
  - 2026-05-27: started with an in-process fake adapter rather than a networked
    fake bridge server so Drum Rack workflow logic can be tested before bridge
    server packaging exists.
  - 2026-05-27: started the Remote Script path as a dependency-injected
    read-only adapter core so CI can validate health and selected-context
    behavior without importing Ableton's host-only Python modules.
  - 2026-05-27: added a read-only `.als` loader for local validation fixtures.
    This does not mutate `.als` files and does not change the RFC's non-goal of
    avoiding offline `.als` mutation.
  - 2026-05-27: extended the `.als` loader to read MIDI clip notes and Drum Rack
    branches for real-set dry-run validation. This remains read-only validation,
    not offline Live Set mutation.
  - 2026-05-27: added fake Drum Rack extraction execution that returns an
    in-memory manifest and post-state snapshot. This validates workflow
    transformation logic without changing Ableton or saved `.als` files.
  - 2026-05-27: added a self-contained read-only Remote Script package and
    installer. It intentionally exposes only health and selected-context reads.
  - 2026-05-27: Live 12.4 exposed `ControlSurface.application` as a property, so
    the Remote Script now resolves Live host objects as either properties or
    methods before reading health/context.
  - 2026-05-27: corrected the read-only `.als` Drum Rack receiving-note mapping
    to match Live's Remote Script pad names before comparing fake and real plans.
  - 2026-05-27: added read-only real Remote Script Drum Rack extraction planning.
    It reports a dry-run plan only; execution remains unsupported by the real
    adapter.
  - 2026-05-27: added additive real Remote Script scaffold execution before MIDI
    filtering. The workflow duplicates and renames tracks only, returns an
    operation manifest, and leaves the Live Set unsaved.
  - 2026-05-27: the first live scaffold attempt exposed that mutating Live APIs
    must not run directly on the socket worker thread. The bridge now dispatches
    requests through `ControlSurface.schedule_message` when Live provides it.
  - 2026-05-27: finished real Drum Rack extraction by filtering duplicated
    Session MIDI clips with Live's note-removal APIs. This intentionally keeps
    arbitrary MIDI note writing unsupported while supporting the narrower,
    plan-derived one-pitch-per-output workflow.
