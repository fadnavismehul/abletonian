---
name: add-bridge-method
description: Add or change an Ableton bridge method (a Live capability the MCP server can call) end to end - Remote Script handler, health capability, fake adapter, MCP tool, tests, and docs. Use when a task needs abletonian to read or change something in Live that no existing ableton.* method covers.
---

# Add a bridge method

Work through these in order. Each step names the file and what "done" means.

## 0. Decide the shape

- Name it `ableton.<verb>_<noun>` (for example `ableton.get_selected_rack_macros`).
- Classify it: read-only, additive, transformative, destructive, or realtime
  (`docs/engineering/robustness-and-safety.md`). Destructive needs
  `confirm=true`. Anything mutating more than one object needs one undo step.
- List the Live Object Model properties you will use, and where you know each
  one from (Cycling '74 LOM docs, Live manual, a dated Live run). Mark guesses.
- If it changes the bridge protocol or the safety model, stop and write an RFC
  (`docs/rfcs/README.md`).

## 1. Live side: `remote_scripts/Abletonian/live_ops.py`

- Add `def <name>(song, params)` returning plain JSON (dicts, lists, str,
  numbers, bool, None). Resolve tracks and devices with `resolve_track` and
  `resolve_device` so references behave like every other tool.
- Use `_get` and `_tuple` for any Live property that may be missing.
- Raise `LiveOpsError` with a message that names the object and lists valid
  choices.
- Register it in `_HANDLERS`. If it mutates and is safe in a batch, add it to
  `BATCHABLE_METHODS`.

## 2. Capabilities: `remote_scripts/Abletonian/bridge_server.py`

- Add the capability name to the `capabilities` list in `_health`; move it
  out of `unsupported_capabilities` if it was there.
- Bump `ADAPTER_VERSION` (minor for new methods).

## 3. Python core: `src/abletonian/adapters/` and `src/abletonian/policy.py`

The MCP tools never call the bridge directly; they go through the adapter
interface and the safety policy (RFC 0003).

- `adapters/base.py`: add a frozen request dataclass whose fields match the
  bridge params, with `OPERATION = "<name>"`, and a method on `DawAdapter`.
  If it can run in a batch, add it to `Change` and `CHANGE_TYPES`.
- `adapters/remote_script.py`: implement the method with `self._send(request)`
  (or `_call` for a non-`ableton.*` method).
- `adapters/fake.py`: implement it if a workflow or tool needs it without
  Live, returning the same JSON shape as step 1, and add the capability to
  `FAKE_ADAPTER_CAPABILITIES`. Otherwise raise `UnsupportedOperation`, and
  leave the capability out.
- `policy.py`: add an `Operation` to `_OPERATIONS` with its safety class, the
  capability name from step 2, `repeatable`, and any confirm or preview rule.
  If it can be batched, add it to `_BATCH_TYPES` in `server.py` as well.

## 4. MCP tool: `src/abletonian/server.py`

Only if a musician-facing task needs it. Annotate it with
`@mcp.tool(annotations=_op("<name>"))` and call `send("<name>", Request(...))`.
Destructive confirms use `StrictBool`. The docstring is what the model sees:
say what it does, what the arguments accept, and whether it changes the Live
Set. Validate the bridge result before building on it.

## 5. Tests

- `tests/test_live_ops.py`: LOM-shaped fakes. Cover the happy path, a missing
  or wrong object, and (for reads) that nothing changed.
- `tests/test_remote_script_adapter.py`: the method sends the right bridge
  method and params.
- `tests/test_adapter_contract.py`: if the fake implements it, the fake and
  the Remote Script give the same answer for the same set.
- `tests/test_policy.py`: add the tool to `TOOL_OPERATIONS`; the annotation
  and coverage tests then check it.
- `tests/test_server.py` for step 4.
- Run `.venv/bin/python -m pytest` and
  `.venv/bin/ruff check src tests remote_scripts scripts`.

## 6. Docs

- Add a row to the tool table in `docs/engineering/live-control.md`.
- If it implements part of an RFC, add implementation notes there.

## 7. Hand-off

In the PR, list the Live assumptions from step 0 and say "not validated in
Live" unless you ran it. The `validate-in-live` skill turns those assumptions
into a checklist for whoever has Live.
