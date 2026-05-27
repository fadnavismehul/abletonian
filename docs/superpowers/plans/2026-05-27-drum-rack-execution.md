# Drum Rack Execution Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Finish RFC-001 by turning the real Remote Script Drum Rack scaffold into confirmed execution with MIDI filtering, MCP exposure, Live validation, and RFC completion.

**Architecture:** Reuse the existing dry-run planner and scaffold workflow as the safety boundary. Execution duplicates the selected Drum Rack track per active pad, renames/colors each duplicate, removes nonmatching MIDI notes from each duplicated clip, returns a manifest, and never saves the Live Set. The original track and clips remain untouched.

**Tech Stack:** Python 3.12 tests, Ableton Live 12.4 Remote Script Python 3.11, length-prefixed bridge protocol, Cycling '74 Live Object Model Clip note APIs.

---

### Task 1: Remote Script Execution Contract

**Files:**
- Modify: `tests/test_remote_script_adapter.py`
- Modify: `src/abletonian/adapters/remote_script.py`
- Modify: `tests/test_remote_script_bridge.py`
- Modify: `remote_scripts/Abletonian/bridge_server.py`

- [x] **Step 1: Write failing adapter tests**

Add tests showing `workflow.execute_drum_rack_extraction` requires `confirm=True`, reports the capability in `daw.health`, preserves source clip notes, creates renamed tracks, and filters each duplicate clip to one pitch.

- [x] **Step 2: Verify adapter tests fail**

Run: `.venv/bin/python -m unittest discover -s tests -p 'test_remote_script_adapter.py'`
Expected: failure because the real adapter does not support `workflow.execute_drum_rack_extraction`.

- [x] **Step 3: Implement adapter execution**

Add `workflow.execute_drum_rack_extraction` dispatch. Reuse `_scaffold_drum_rack_extraction`, find each created track by ID, filter its session MIDI clips with `remove_notes_extended` or legacy `remove_notes`, rename filtered clips, and return verification with `midi_filtering_applied=True`, `saved_live_set=False`, and `mutates_real_ableton_set=True`.

- [x] **Step 4: Verify adapter tests pass**

Run: `.venv/bin/python -m unittest discover -s tests -p 'test_remote_script_adapter.py'`
Expected: OK.

- [x] **Step 5: Write failing bridge tests**

Add the same execution behavior to the self-contained bridge tests, including deep-copying fake duplicated clips so source notes remain unchanged.

- [x] **Step 6: Verify bridge tests fail**

Run: `.venv/bin/python -m unittest discover -s tests -p 'test_remote_script_bridge.py'`
Expected: failure because the self-contained bridge does not support `workflow.execute_drum_rack_extraction`.

- [x] **Step 7: Implement bridge execution**

Mirror the adapter execution helpers in `remote_scripts/Abletonian/bridge_server.py`, keeping the file importable outside Live and keeping request handling scheduled through `ControlSurface.schedule_message`.

- [x] **Step 8: Verify bridge tests pass**

Run: `.venv/bin/python -m unittest discover -s tests -p 'test_remote_script_bridge.py'`
Expected: OK.

- [x] **Step 9: Commit execution core**

Run:

```bash
git add tests/test_remote_script_adapter.py src/abletonian/adapters/remote_script.py tests/test_remote_script_bridge.py remote_scripts/Abletonian/bridge_server.py
git commit -m "feat: execute Drum Rack extraction in Live" -m "RFC: RFC-001"
```

### Task 2: MCP Execution Tool

**Files:**
- Modify: `tests/test_server.py`
- Modify: `src/abletonian/server.py`

- [x] **Step 1: Write failing MCP tool test**

Add a test for `execute_drum_rack_extraction(confirm=True)` that delegates to `workflow.execute_drum_rack_extraction` with `target_daw=ableton` and `confirm=True`.

- [x] **Step 2: Verify server test fails**

Run: `.venv/bin/python -m unittest discover -s tests -p 'test_server.py'`
Expected: failure because the MCP tool is missing.

- [x] **Step 3: Implement MCP tool**

Add a model-facing `execute_drum_rack_extraction(confirm: bool = False)` tool. It must refuse when `confirm` is not true, and only then call the bridge execution method.

- [x] **Step 4: Verify server test passes**

Run: `.venv/bin/python -m unittest discover -s tests -p 'test_server.py'`
Expected: OK.

- [x] **Step 5: Commit MCP tool**

Run:

```bash
git add tests/test_server.py src/abletonian/server.py
git commit -m "feat: expose confirmed Drum Rack execution tool" -m "RFC: RFC-001"
```

### Task 3: Live Validation and RFC Completion

**Files:**
- Modify: `docs/engineering/live-validation.md`
- Move: `docs/product/rfcs/inprogress/RFC-001-ableton-deep-integration-foundation.md` to `docs/product/rfcs/done/RFC-001-ableton-deep-integration-foundation.md`
- Modify: `docs/product/rfcs/README.md`

- [x] **Step 1: Install and restart Live**

Run `.venv/bin/python -m scripts.install_remote_script`, restart Ableton Live, open `testing/First Light Project/First Light.als`, dismiss crash recovery if present, and select the `1-C78 Core Kit` track.

- [x] **Step 2: Probe execution**

Run:

```bash
.venv/bin/python - <<'PY'
from pprint import pprint
from abletonian.bridge.client import BridgeClient

bridge = BridgeClient("127.0.0.1", 9877, 30.0)
pprint(bridge.request("workflow.execute_drum_rack_extraction", {"confirm": True}))
PY
```

Expected: created tracks for `Snare`, `Kick`, and `Closed Hi Hat`; each created track reports one retained pitch; `midi_filtering_applied=True`; `saved_live_set=False`.

- [x] **Step 3: Document validation**

Update live validation with the execution result, the note-filtering boundary, and backout guidance. Update RFC-001 implementation tracking with verification commands, commit hashes, and Live validation evidence.

- [x] **Step 4: Move RFC to done**

Set `Status: Implemented`, move the RFC file to `docs/product/rfcs/done/`, and update the RFC registry row to point at the done path.

- [x] **Step 5: Run full verification**

Run:

```bash
.venv/bin/python -m unittest discover -s tests
.venv/bin/ruff check .
.venv/bin/python -m compileall -q src tests remote_scripts scripts
git diff --check
```

Expected: all commands pass.

- [x] **Step 6: Commit docs and RFC completion**

Run:

```bash
git add docs/engineering/live-validation.md docs/product/rfcs/README.md docs/product/rfcs/done/RFC-001-ableton-deep-integration-foundation.md
git add -u docs/product/rfcs/inprogress/RFC-001-ableton-deep-integration-foundation.md
git commit -m "docs: complete RFC-001 Ableton foundation" -m "RFC: RFC-001"
```
