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

## 3. Fake adapter: `src/abletonian/adapters/fake.py`

Only if an MCP tool or workflow needs it without Live. Return the same JSON
shape as step 1, and add the capability to `FAKE_ADAPTER_CAPABILITIES`.

## 4. MCP tool: `src/abletonian/server.py`

Only if a musician-facing task needs it. Use `live_request` and
`without_none`. The docstring is what the model sees: say what it does, what
the arguments accept, and whether it changes the Live Set. Validate the bridge
result before building on it.

## 5. Tests

- `tests/test_live_ops.py`: LOM-shaped fakes. Cover the happy path, a missing
  or wrong object, and (for reads) that nothing changed.
- `tests/test_fake_adapter.py` or a feature test file for step 3.
- `tests/test_server.py` for step 4 (`FakeAdapterBridge` runs the fake
  adapter behind the tool).
- Run `.venv/bin/python -m pytest` and
  `.venv/bin/ruff check src tests remote_scripts scripts`.

## 6. Docs

- Add a row to the tool table in `docs/engineering/live-control.md`.
- If it implements part of an RFC, add implementation notes there.

## 7. Hand-off

In the PR, list the Live assumptions from step 0 and say "not validated in
Live" unless you ran it. The `validate-in-live` skill turns those assumptions
into a checklist for whoever has Live.
