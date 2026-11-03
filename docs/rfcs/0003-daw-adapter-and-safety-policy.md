# RFC 0003: DawAdapter interface and SafetyPolicy in the Python core

**Status:** Accepted  
**Created:** 2026-11-03  
**Owner:** @fadnavismehul  
**Tracking issue:** [#28](https://github.com/fadnavismehul/abletonian/issues/28)

## Summary

Put an interface between the MCP tools and the code that talks to Live. Today
the tools in `src/abletonian/server.py` send `ableton.*` bridge methods by
name. This RFC adds a `DawAdapter` protocol with one typed method per Live
operation, makes the Remote Script client and the fake adapter two
implementations of it, and routes every tool that changes the Set through one
`SafetyPolicy` object. Musicians see no change: tool names, parameters and
results stay the same. Contributors get a boundary that a second Ableton
adapter (the Extensions SDK) and, later, another DAW can plug into, and a
safety layer a new tool cannot skip.

This is recommendation P1 of the
[landscape review](../research/2026-11-landscape-and-direction-review.md).

## Motivation

1. **The boundary is the wire.** The tools call `bridge_client.request(...)`
   with literal method names, from 17 places (directly or through
   `live_request`). An adapter that cannot do
   `ableton.set_track_output_routing`, such as an Extension, has nowhere to say
   so except an error at call time. `DawProfile` is static text; nothing
   routes on it.
2. **The fake adapter lags.** `FakeAbletonAdapter` answers health, selected
   context, rack macros and the Drum Rack workflow, but none of the eleven mix
   operations (`list_tracks` through `batch` and `undo`). Those are tested only through
   LOM-shaped fakes in `tests/test_live_ops*.py`, never from the MCP tool
   down.
3. **Safety lives in each tool.** Confirm checks, the undo count guard and
   old-script warnings are written per tool in `server.py`. The annotation
   constants (`READ_ONLY`, `DESTRUCTIVE`, ...) are assigned by hand and can
   disagree with what a tool does.

Doing this before the Extensions spike makes that work smaller, and it is the
first step that makes the multi-DAW claim true.

## Design

### Layers

```text
MCP tools (server.py)          names, params, docstrings: unchanged
      |
SafetyPolicy                   class, confirm, capability check, session log
      |
DawAdapter (protocol)          typed methods + capabilities()
   |                 |
RemoteScriptAdapter  FakeAbletonAdapter     (later: ExtensionAdapter)
   |
BridgeClient -> framed TCP -> Remote Script in Live   (unchanged)
```

New code lives in `src/abletonian/adapters/`: `base.py` (protocol, request
and result types, errors), `remote_script.py` (wire translation), and the
existing `fake.py`. `policy.py` holds `SafetyPolicy` and the operation table.

### DawAdapter

A `typing.Protocol`, synchronous like `BridgeClient` today:

```python
class DawAdapter(Protocol):
    def health(self) -> AdapterHealth: ...
    def capabilities(self) -> frozenset[str]: ...

    # read-only
    def list_tracks(self, q: TrackQuery) -> dict: ...
    def list_devices(self, q: DeviceQuery) -> dict: ...
    def get_selected_rack_macros(self, ref: RackRef) -> dict: ...
    def plan_drum_rack_extraction(self) -> dict: ...

    # changes the Set
    def set_device_parameter(self, c: ParameterChange) -> dict: ...
    def set_track_output_routing(self, c: RoutingChange) -> dict: ...
    def set_track_properties(self, c: TrackPropertiesChange) -> dict: ...
    def set_mixer(self, c: MixerChange) -> dict: ...
    def insert_device(self, c: DeviceInsert) -> dict: ...
    def create_return_track(self, c: ReturnTrackCreate) -> dict: ...
    def delete_device(self, c: DeviceDelete) -> dict: ...
    def apply_batch(self, b: Batch) -> dict: ...
    def undo(self, u: UndoRequest) -> dict: ...
    def execute_drum_rack_extraction(self) -> dict: ...
```

1. **Inputs are typed.** Each request is a frozen dataclass with the same
   fields as today's tool parameters (`track: int | str`, `value: float |
   str`, ...). Tools build them; adapters translate them. A `Batch` holds a
   list of these change objects instead of `{"method", "params"}` dicts, so a
   batch is checked the same way single calls are.
2. **Results stay JSON objects for now.** Each adapter method returns the
   validated result dict. Validation is a small per-method check of the keys
   the server relies on (for example `undo_steps`, `steps`, `deleted`),
   raising `AdapterResponseError` when they are missing or the wrong type.
   Typing every result field is left for later (see Unresolved questions);
   the musician-facing text is built from these dicts today and should not
   change in this RFC.
3. **Capabilities are the fine-grained names `daw.health` already reports**
   (`list_tracks`, `set_mixer`, `undo_count`, `batch_per_operation_undo`,
   ...). The coarse vocabulary in `daw-targets.md` stays for the profile
   page only.
4. **Errors.** `AdapterUnavailable` (could not reach the DAW; replaces
   `BridgeConnectionError` at this layer), `AdapterRefused` (the DAW said no,
   with the bridge error code and hint), `UnsupportedOperation` (the adapter
   does not advertise the capability), `AdapterResponseError`.

### RemoteScriptAdapter

Holds a `BridgeClient`. Each method turns its request into today's
`ableton.*` params and calls `request()`. It reads `daw.health` once per
session (and again after a connection error) to fill `capabilities()`. The
old-script fallbacks now in the tools (batch without `undo_steps`, undo
without `steps`) move here, keyed on capabilities rather than on missing
result keys. **The wire protocol and the Remote Script do not change.**

### FakeAbletonAdapter

Implements `DawAdapter` directly on its in-memory state, with every method
above. It keeps `handle_request` so `dispatch_frame` and the bridge tests
still work, by mapping wire methods onto the typed methods. Reaching full
parity is Linear MEH-21; this RFC only requires that the fake satisfies the
protocol, raising `UnsupportedOperation` for methods not built yet and
leaving them out of `capabilities()`.

### SafetyPolicy

One table describes every operation:

```python
@dataclass(frozen=True)
class Operation:
    name: str              # "set_mixer"
    safety_class: SafetyClass  # READ_ONLY, ADDITIVE, TRANSFORMATIVE, DESTRUCTIVE, REALTIME
    capability: str        # what the adapter must advertise
    needs_confirm: Callable[[Request], bool]  # e.g. delete always; undo when count > 1
    repeatable: bool       # drives idempotentHint
```

`SafetyPolicy.run(operation, request, call)` is the only path from a tool to
an adapter method:

1. Refuse with a clear message if the adapter does not advertise the
   capability. Nothing is sent.
2. If `needs_confirm(request)` and the request has no `confirm=True`, return
   the refusal text the tool returns today. For `delete_device` the adapter is
   still called without confirm, because the preview of what would be deleted
   comes from Live; the policy marks that call as read-only.
3. Call the adapter, mapping adapter errors to the messages tools return now
   ("Bridge error: ...").
4. Append an entry to an in-memory session log: time, operation, class,
   request summary, adapter type and version, ok or error, and reported undo
   steps. A read-only `get_session_log` tool is out of scope here; the log
   exists so the plan/manifest work can build on it.

Undo grouping stays the adapter's job (the Remote Script uses
`begin_undo_step`, an Extension would use `withinTransaction`). The policy
does not open undo steps; it records what the adapter reports.

MCP annotations are derived from the table (`READ_ONLY` and friends become a
function of `safety_class` and `repeatable`), so a tool's hints cannot drift
from its class. A test asserts that every registered tool that can change the
Set is in the table and goes through `run`.

### What does not change

Tool names, parameters, docstrings and result text; the bridge protocol;
`remote_scripts/`; the cockpit modules, which receive the same rack dict.

## Safety and backout

This is a refactor with no change in what reaches Live. The risk is that a
check is lost in the move. Mitigations:

1. Existing `tests/test_server.py` expectations stay as they are; they now
   run with a `RemoteScriptAdapter` over the current recording bridges.
2. The refactor lands in small PRs (below), each green on its own and easy to
   revert.
3. Nothing under `remote_scripts/` changes, so there is no new Live
   validation burden. Each PR still says "not validated in Live".

## Verification

1. Unit tests for `SafetyPolicy`: missing capability, confirm rules (delete,
   undo count, batch containing a delete), error mapping, log entries.
2. A test that every mutating tool is in the operation table and that each
   tool's annotations match its class.
3. **Contract tests** run the same cases against two adapters:
   `FakeAbletonAdapter`, and `RemoteScriptAdapter` wired through
   `dispatch_frame` to `remote_scripts/Abletonian/live_ops.py` on LOM-shaped
   fakes (tests may import the Remote Script). Where both implement an
   operation, they must give the same result shape and the same refusals.
   This is how the fake stays honest.
4. Python 3.10 and 3.12, ruff, as in CI.

## Rollout

1. `adapters/base.py` with request types and the protocol; no callers yet.
2. `RemoteScriptAdapter`; `build_mcp` takes `adapter: DawAdapter | None`,
   keeping `bridge=` for one release so tests and callers move gradually.
3. `policy.py` and the operation table; move tools over in groups (reads,
   then mixer and track changes, then insert/create/delete, then batch and
   undo).
4. Fake adapter implements the protocol; contract tests start.
5. Remove `bridge=` from `build_mcp`; update `docs/exploration/architecture.md`
   and `AGENTS.md` ("Adding a bridge method" gains a step for `base.py` and
   the operation table) and the `add-bridge-method` skill.

## Alternatives

1. **Bring the fake to parity on the wire only (P4 alone).** Cheaper now, but
   it keeps method names as the boundary, and the fake would be redone once
   an Extension adapter needs the interface anyway.
2. **Generate adapters from a schema (JSON Schema or similar).** More
   machinery than ten operations need, and it does not by itself give a place
   for the safety checks.
3. **Adopt another project's abstraction.** The review found no multi-DAW
   project with a credible shared capability model.
4. **Put the policy in the Remote Script.** It would have to be written again
   for each adapter, and it could not refuse before anything is sent.

## Unresolved questions

1. Whether results should become typed dataclasses too, and when. Typing them
   would let the server stop trusting dict keys, but it touches every result
   text. Proposed: after this RFC, one operation at a time.
2. Whether the session log is written to disk (with the cockpit store) or
   kept in memory. Proposed: memory until the plan/manifest format exists.
3. How the server chooses between two adapters that both answer. Out of
   scope; that belongs in the Extensions adapter RFC, which this RFC unblocks.
4. Sync or async. The MCP server can call sync adapters from async tools;
   the Extensions adapter may want async I/O. Proposed: sync now, and revisit
   in the Extensions RFC.

## Implementation notes

Code: `src/abletonian/adapters/base.py` (step 1), `adapters/remote_script.py`
(step 2). Progress is tracked in #28.

- 2026-11-03: The old-script warnings in `RemoteScriptAdapter` are keyed on
  the result (no `undo_steps`, no `steps`), as the tools do today, rather than
  on capabilities. The result shows what Live actually did, even when the
  health read is stale.
- 2026-11-03: `build_mcp(adapter=...)` moves from step 2 to step 3, so it
  arrives together with the first tools that use it.
- 2026-11-03: `BridgeClient` raises `BridgeRefusedError`, a subclass of
  `BridgeConnectionError` carrying the bridge's code, message and hint, so
  the adapter can tell a refusal from an unreachable Live. Existing callers
  are unaffected.
- 2026-11-03 (step 3): The policy checks a capability only when the adapter
  already knows its capabilities (`known_capabilities()`, filled by any
  health read such as `check_bridge_health`). Reading health before every
  first call would add a bridge round trip and change the wire traffic the
  tests pin. Until health is read, Live's own refusal still applies.
- 2026-11-03 (step 3): `apply_batch` parses its `{"method", "params"}` dicts
  into typed changes. An unknown method or parameter is now refused locally
  with the operation's position and "Nothing was changed", and an
  unconfirmed delete in a batch is refused before anything is sent.
- 2026-11-03 (step 3): `check_bridge_health` validates the health answer and
  says so when it is unusable, instead of printing whatever came back.
