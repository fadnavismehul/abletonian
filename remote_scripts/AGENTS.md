# AGENTS.md: Remote Script

Code here runs inside Ableton Live as a Control Surface script. Live loads it
from the User Library copy that `scripts/install_remote_script.py` makes, not
from this checkout.

## Constraints

- **Live's embedded Python 3.11, stdlib only.** No `pip` packages, and no
  imports from `abletonian`. Keep code importable outside Live: the
  `ControlSurface` fallback in `bridge_server.py` exists so tests can import it.
- **Every Live API call runs on Live's main thread.** The socket thread only
  frames bytes; `_call_surface` hands each request to `schedule_message`.
  Never touch `song`, tracks, or devices from the socket thread, and never
  block the main thread on the network.
- **Requests have deadlines.** A request not started within
  `REQUEST_START_TIMEOUT_SECONDS` is cancelled unrun, so a client that gave
  up never sees a late mutation. Keep handlers short.
- **Read Live objects defensively.** Properties differ across Live versions
  and device types; use `_get` (returns a default instead of raising) for
  anything that might be missing, and `_tuple` for Live's vector types.
- **Errors are messages for musicians.** Raise `LiveOpsError` with text that
  names the track/device and lists valid choices.

## Where things go

- `live_ops.py`: Live Set operations. Each takes `(song, params)` and returns
  plain JSON. Register new ones in `_HANDLERS`; add mutating ones that are safe
  to batch to `BATCHABLE_METHODS`.
- `bridge_server.py`: socket server, framing, main-thread dispatch, `daw.health`,
  and the Drum Rack workflow. Bump `ADAPTER_VERSION` and update the
  capability lists in `_health` when behaviour changes.
- `__init__.py`: entrypoint. It reloads submodules so switching the Control
  Surface slot to None and back picks up a reinstalled script. Add any new
  module to that reload list.

## Testing

`tests/test_live_ops.py` and `tests/test_remote_script_bridge.py` use
`SimpleNamespace` and small classes shaped like the Live Object Model. A fake
only proves your code matches your assumptions about Live. Write down the
assumptions (in the PR and, if they matter later, the RFC or engineering docs)
so the next Live run can check them.

To try a change in Live: run `.venv/bin/python -m scripts.install_remote_script`,
switch the Abletonian Control Surface slot to None and back, then call the
bridge through the MCP tools. The `validate-in-live` skill has the checklist.
