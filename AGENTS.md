# AGENTS.md

Instructions for coding agents (and humans) working in this repo. What the
project is: see `README.md`. How contributions flow: see `CONTRIBUTING.md`.
This file covers what is not obvious from reading the code.

## Commands

```bash
python -m venv .venv && .venv/bin/python -m pip install -e '.[dev]'
.venv/bin/python -m pytest                          # all tests, no Ableton needed
.venv/bin/ruff check src tests remote_scripts scripts
.venv/bin/python -m scripts.install_remote_script   # copy the Remote Script into Live's User Library
```

CI runs the same tests and lint on Python 3.10 and 3.12. Run both before you
say a change is done.

## Two Python worlds

| Code | Runs in | Can import |
| --- | --- | --- |
| `src/abletonian/` | The MCP server, Python 3.10+ | `mcp` 2.x (`MCPServer`), stdlib |
| `remote_scripts/Abletonian/` | Inside Ableton Live's embedded Python 3.11 | stdlib and Live's own modules only |

The Remote Script cannot import `abletonian`, and the package must not import
the Remote Script (tests may). They share only the bridge protocol: 4-byte
length-prefixed JSON frames with request IDs on `127.0.0.1:9877`. Read
`remote_scripts/AGENTS.md` before editing anything under `remote_scripts/`.

`src/abletonian/adapters/remote_script.py` is an early copy of the Drum Rack
adapter that only tests use. New Live features go in `remote_scripts/Abletonian/`.

## Adding a bridge method (the common change)

A new Live capability touches, in order:

1. `remote_scripts/Abletonian/live_ops.py`: a function taking `(song, params)`
   and returning plain JSON, registered in `_HANDLERS`.
2. `remote_scripts/Abletonian/bridge_server.py`: add the capability name to
   `daw.health` and bump `ADAPTER_VERSION`.
3. `src/abletonian/adapters/fake.py`: the same method, if workflows or MCP
   tools need to run without Live.
4. `src/abletonian/server.py`: an MCP tool, only if a musician-facing task
   needs it. Do not add tools that pass raw bridge calls through.
5. Tests: `tests/test_live_ops.py` (LOM-shaped fakes), plus fake-adapter and
   server tests.
6. `docs/engineering/live-control.md`: the tool table.

The `add-bridge-method` skill in `.claude/skills/` walks through this.

## Safety rules

Abletonian edits people's music. These are not style preferences:

- Classify every operation as read-only, additive, transformative,
  destructive, or realtime (`docs/engineering/robustness-and-safety.md`).
- Reads must not change the Live Set. Say so in the tool docstring.
- Multi-step mutations run as one Live undo step (`begin_undo_step`) and
  fail closed: undo or delete partial work when a step fails.
- Destructive operations need an explicit `confirm=true` from the caller.
- Treat everything coming back over the bridge as untrusted input. Validate
  it before building on it (see `src/abletonian/cockpit.py`).

## Things that will bite you

- **Nothing here can run Live.** Tests use fakes. Any change under
  `remote_scripts/` is unverified until someone runs it in Live. Say
  "not validated in Live" in the PR, and record real runs in the validation
  log of `docs/engineering/live-control.md` or `live-validation.md`.
- **Live's API is not fully documented.** When you depend on a Live Object
  Model property, cite the source (Cycling '74 LOM docs, the Live manual, or a
  dated Live run) in code comments or docs. Mark guesses as guesses.
- **`testing/First Light Project/First Light.als` is a fixture.** Tests expect
  its original six tracks. Never save over it in Live; save a copy under a new
  name.
- **The Ableton manual is copyrighted.** `docs/ableton-manual/<major>/` is
  fetched locally by `scripts/fetch_manual.py` and must never be committed.
- **Port 9877** is also used by other Ableton MCP projects; only one can be
  enabled in Live at a time.

## Where decisions live

- Small fixes and features: an issue and a PR are enough.
- Changes to the bridge protocol, the safety model, a new DAW adapter, or a
  new workflow surface: write an RFC in `docs/rfcs/` first (see its README).
  Keep the RFC about the design; track progress in its GitHub issue.
- Musician-facing intent: `docs/product/vision.md`, `docs/design/philosophy.md`.

## Before you open a PR

- Tests and ruff pass.
- Docs that your change makes wrong are fixed in the same PR.
- The PR template is filled in, including how it was tested and whether it
  ran in Live.
- AI assistance is disclosed (`AI_POLICY.md`).
