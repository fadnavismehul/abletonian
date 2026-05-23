# Engineering Robustness and Safety

Abletonian operates on creative work. A bad mutation can lose a sound, break a
session, interrupt a live set, or damage trust permanently. Robustness and safety
are therefore product requirements, not implementation polish.

## Safety Model

Classify every operation before execution.

| Class | Description | Examples | Required Guard |
| --- | --- | --- | --- |
| Read-only | Observes Live state without mutation | session summary, selected track, manual lookup | Safe by default |
| Additive | Creates new material without changing originals | create track, create clip variation | Log and report created objects |
| Transformative | Changes existing material but preserves logical object | rename track, color track, edit notes | Dry-run for batch changes |
| Destructive | Deletes, replaces, crops, clears, or removes routing/devices | delete track, clear clip notes, remove chains | Explicit confirmation and backout |
| Realtime | Affects transport or live parameter state | start playback, fire clip, remote parameter | Low-latency path and no agent loop promises |

## Core Invariants

- Preserve originals by default for multi-object workflows.
- Require dry-run plans for non-trivial mutations.
- Never expose raw bridge commands directly to model-facing MCP tools.
- Record the target Ableton version and adapter capability set with each plan.
- Treat every adapter response as untrusted until validated.
- Prefer stable canonical paths and request IDs over ephemeral indexes whenever
  the adapter can provide them.
- Keep bridge operations bounded by explicit timeouts.
- Fail closed: no partial hidden mutation when validation fails.

## Bridge Protocol Requirements

Abletonian's existing bridge protocol uses length-prefixed JSON frames with
request IDs. Preserve and extend that direction.

Required properties:

- 4-byte length prefix or equivalent unambiguous framing.
- Request IDs on every command and response.
- Structured `ok/result/error` responses.
- Adapter capability handshake.
- Adapter version, Live version, and protocol version in `daw.health`.
- Timeouts at the client and adapter levels.
- Typed errors with recoverability hints.
- No ambiguous "parse until JSON loads" stream handling.

The bridge should support both:

- one-shot request/response commands,
- event subscriptions for selected track, selected clip, transport, and project
  state changes.

## Main-Thread and Reentrancy Safety

Ableton mutations must run in the right host context. For Remote Scripts, that
usually means scheduling state-changing operations onto Live's main thread or
equivalent safe execution path. For Max for Live, Live API notifications have
their own constraints; Cycling '74 documents that changes to a Live Set cannot
be triggered directly from notifications, and recommends deferring in many
cases. See [Live API Overview](https://docs.cycling74.com/userguide/m4l/live_api_overview/).

Rules:

- Keep adapter handlers short.
- Do not block Live's UI/audio thread on network calls or model calls.
- Queue mutations and report progress.
- Reject concurrent mutations that target overlapping object sets unless a
  workflow explicitly supports them.
- Debounce observed state changes before sending them to the core.

## Undo and Backout

The Live Object Model exposes undo/redo state and functions such as `can_undo`,
`can_redo`, `undo`, and `redo` on `Song`. See [LOM Song](https://docs.cycling74.com/legacy/max8/vignettes/live_object_model?q=LOM).

Abletonian should use undo as one safety layer, not the only safety layer.

Backout strategy order:

1. Prefer additive changes that can be deleted as a group.
2. For batch workflows, create a named operation manifest listing created and
   touched objects.
3. Use Live undo for immediate user recovery.
4. Offer save-copy helpers before high-risk operations.
5. For destructive operations, require explicit confirmation and record what was
   deleted.

## Workflow Transaction Shape

Complex workflows should be represented as plans:

```json
{
  "operation": "split_drum_rack",
  "mode": "dry_run",
  "target": {
    "track": "Drums",
    "device": "Drum Rack"
  },
  "steps": [
    {"action": "duplicate_track", "count": 8},
    {"action": "filter_midi_notes", "policy": "one_note_per_track"},
    {"action": "rename_tracks", "source": "pad_or_chain_name"},
    {"action": "set_colors", "source": "role_palette"}
  ],
  "preserves": ["source_track", "source_clips"],
  "requires_confirmation": true
}
```

Execution should return:

- created object references,
- touched object references,
- skipped steps,
- warnings,
- verification summary,
- suggested manual checks.

## Testing Strategy

### Unit Tests

- Bridge frame encoding/decoding.
- Protocol version negotiation.
- Capability matching.
- Safety classification.
- Plan validation.
- RTFM indexing and citation formatting.

### Fake Adapter Tests

Build a fake Ableton adapter that models enough of Live to test workflows:

- tracks,
- clips,
- devices,
- Drum Rack pads/chains,
- colors,
- undo-like manifests.

This allows CI to verify workflow logic without launching Ableton.

### Golden Workflow Tests

Represent workflows as fixtures:

- input Live-like state,
- requested operation,
- expected dry-run plan,
- expected post-state after execution.

The first golden workflow should be Drum Rack extraction.

### Manual Ableton Verification

For every adapter workflow that mutates Live:

- run against a saved test Live Set,
- capture before/after state through the bridge,
- verify visible Ableton behavior manually,
- document the Live version and OS,
- include screenshots or logs when UI behavior matters.

### RTFM Verification

Manual references should be tested for:

- reachable URLs,
- version-specific routing,
- citation presence,
- no unsupported automation claims.

## Security Considerations

Abletonian will likely expose a local bridge. Treat it as a privileged local
control surface.

Requirements:

- Bind to `127.0.0.1` by default.
- Avoid listening on public interfaces unless explicitly configured.
- Use a per-session token or local capability secret once external clients are
  supported beyond stdio.
- Log client identity and operation IDs where possible.
- Do not allow arbitrary Python/JavaScript execution through MCP tools.
- Validate every path, object ID, and command against the adapter capability
  schema.
- Avoid sending sample paths, plugin names, or project metadata to cloud models
  unless the user explicitly opts in.

## Version Compatibility

Ableton versions matter. Remote Script Python changed between Live 10 and Live
11, and Live 12 adds MIDI Tools and newer LOM capabilities. Ableton's Remote
Script article states that Live 10 and earlier used Python 2, while Live 11 and
later require Python 3 for custom scripts. See [Installing third-party remote scripts](https://help.ableton.com/hc/en-us/articles/209072009-Installing-third-party-remote-scripts).

Adapter health should report:

- Ableton major/minor/bugfix version,
- adapter package version,
- Python runtime where available,
- Max for Live availability where available,
- supported capability list,
- known unsupported capabilities.

Never infer support from version alone when a direct capability probe is
available.

## Observability

Log high-value local events:

- bridge connect/disconnect,
- adapter health,
- dry-run plan generated,
- user approval,
- mutation started/completed/failed,
- created and touched object references,
- RTFM sources used,
- verification warnings.

Logs should avoid storing sensitive musical content unless explicitly enabled.
For example, note counts and pitch classes may be useful; complete MIDI clips or
sample paths may be sensitive.

## Failure Behavior

Failures should be boring and legible:

- If Ableton is not reachable, say how to install/enable the bridge.
- If context is ambiguous, ask for a target.
- If a capability is unsupported, say which adapter surface could support it.
- If a partial mutation occurs, return a manifest and suggested backout.
- If the manual lookup fails, do not invent documentation; return no-source
  status.

## Non-Goals for Early Robustness

- No hard-real-time performance control through model loops.
- No arbitrary plugin parameter exploration without user-visible scope.
- No offline `.als` mutation in the first implementation path.
- No UI automation as the default approach for core workflows.
