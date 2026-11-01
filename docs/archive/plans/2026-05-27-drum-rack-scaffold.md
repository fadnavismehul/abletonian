# Drum Rack Scaffold Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add the first real mutating Live workflow slice: duplicate selected Drum Rack tracks into named per-pad scaffold tracks without filtering MIDI or saving the set.

**Architecture:** Reuse the existing real `workflow.plan_drum_rack_extraction` output as the source of truth. Add `workflow.scaffold_drum_rack_extraction` to both the testable `RemoteScriptAdapter` core and the self-contained Ableton Remote Script, requiring `confirm=True` and returning a manifest of created tracks plus backout guidance.

**Tech Stack:** Python 3.12 tests, Ableton Live Remote Script Python 3.11 runtime, length-prefixed Abletonian bridge protocol, Cycling '74 Live Object Model `Song.duplicate_track(index)`.

---

### Task 1: Adapter Scaffold Contract

**Files:**
- Modify: `tests/test_remote_script_adapter.py`
- Modify: `src/abletonian/adapters/remote_script.py`

- [x] **Step 1: Write the failing confirmation test**

```python
with self.assertRaisesRegex(Exception, "requires confirmation"):
    adapter.handle_request("workflow.scaffold_drum_rack_extraction", {})
```

- [x] **Step 2: Write the failing manifest test**

```python
result = adapter.handle_request(
    "workflow.scaffold_drum_rack_extraction",
    {"confirm": True},
)
self.assertEqual(result["mode"], "scaffold_tracks")
self.assertEqual([track["name"] for track in result["created_tracks"]], ["Drums - Kick", "Drums - Snare"])
self.assertFalse(result["verification"]["midi_filtering_applied"])
```

- [x] **Step 3: Run adapter tests to verify red**

Run: `.venv/bin/python -m unittest discover -s tests -p 'test_remote_script_adapter.py'`
Expected: failure because `workflow.scaffold_drum_rack_extraction` is unsupported.

- [x] **Step 4: Implement minimal adapter support**

Add method dispatch, require `confirm=True`, call the existing planner, duplicate source or previous scaffold tracks with `song.duplicate_track(index)`, rename/color each created track, and return a manifest. Do not filter clips or save the set.

- [x] **Step 5: Run adapter tests to verify green**

Run: `.venv/bin/python -m unittest discover -s tests -p 'test_remote_script_adapter.py'`
Expected: OK.

### Task 2: Self-Contained Remote Script Support

**Files:**
- Modify: `tests/test_remote_script_bridge.py`
- Modify: `remote_scripts/Abletonian/bridge_server.py`

- [x] **Step 1: Write the failing bridge test**

```python
result = surface.handle_request("workflow.scaffold_drum_rack_extraction", {"confirm": True})
self.assertEqual(result["created_tracks"][0]["name"], "Drums - Kick")
```

- [x] **Step 2: Run bridge tests to verify red**

Run: `.venv/bin/python -m unittest discover -s tests -p 'test_remote_script_bridge.py'`
Expected: failure because the self-contained script does not support the scaffold method.

- [x] **Step 3: Mirror the adapter implementation**

Add the same dispatch and helper functions to `remote_scripts/Abletonian/bridge_server.py`, keeping it importable outside Live.

- [x] **Step 4: Run bridge tests to verify green**

Run: `.venv/bin/python -m unittest discover -s tests -p 'test_remote_script_bridge.py'`
Expected: OK.

### Task 3: Live Validation and Docs

**Files:**
- Modify: `docs/engineering/live-validation.md`
- Modify: `docs/product/rfcs/inprogress/RFC-001-ableton-deep-integration-foundation.md`

- [x] **Step 1: Install and restart**

Run: `.venv/bin/python -m scripts.install_remote_script`, restart Live, and open `testing/First Light Project/First Light.als`.

- [x] **Step 2: Probe scaffold**

Run:

```bash
.venv/bin/python - <<'PY'
from abletonian.bridge.client import BridgeClient
bridge = BridgeClient("127.0.0.1", 9877, 4.0)
print(bridge.request("workflow.scaffold_drum_rack_extraction", {"confirm": True}))
PY
```

Expected: created scaffold tracks for `Snare`, `Kick`, and `Closed Hi Hat`; `midi_filtering_applied` is `False`; no Live Set save occurs.

- [x] **Step 3: Document result**

Record the validation result, backout note, and mutation boundary in the live validation doc and RFC tracking section.

- [x] **Step 4: Full verification**

Run:

```bash
.venv/bin/python -m unittest discover -s tests
.venv/bin/ruff check .
.venv/bin/python -m compileall -q src tests remote_scripts scripts
git diff --check
```

Expected: all commands pass.

Live validation note: the first direct socket-thread mutation attempt wedged the
bridge during `Song.duplicate_track(index)`. The bridge now schedules request
handling through `ControlSurface.schedule_message` when Live provides it, and the
confirmed scaffold probe passed against `First Light.als`.
