# Live Validation

This document records the manual validation path for real Ableton Live before
and during mutating adapter workflows.

## Current Scope

Current live validation covers read-only planning and the first additive
mutation scaffold:

- install the Abletonian Remote Script into the User Library,
- enable it as a Control Surface in Ableton Live,
- connect to `127.0.0.1:9877`,
- call `daw.health`,
- call `ableton.get_selected_context`,
- call `workflow.plan_drum_rack_extraction`,
- confirm the selected track/device and dry-run plan match the visible Live Set,
- call `workflow.scaffold_drum_rack_extraction` with `confirm=True`,
- confirm scaffold tracks are duplicated, renamed, and colored while MIDI clips
  remain unfiltered.

The Remote Script can duplicate tracks for the scaffold workflow. It does not
create empty tracks, edit MIDI notes, filter clips, or save Live Sets.

## Install

Run from the repository root:

```bash
.venv/bin/python -m scripts.install_remote_script
```

This installs:

```text
~/Music/Ableton/User Library/Remote Scripts/Abletonian/
```

Restart Ableton Live after installation if the `Abletonian` Control Surface does
not appear.

## Ableton Setup

1. Open `testing/First Light Project/First Light.als`.
2. Open Live Settings.
3. In Link, Tempo & MIDI, choose `Abletonian` as an available Control Surface.
4. Leave input and output as `None`.
5. Select the `1-C78 Core Kit` track.

## Probe

Run:

```bash
.venv/bin/python - <<'PY'
from abletonian.bridge.client import BridgeClient

bridge = BridgeClient("127.0.0.1", 9877, 2.0)
print(bridge.request("daw.health", {"target_daw": "ableton"}))
print(bridge.request("ableton.get_selected_context", {}))
print(bridge.request("workflow.plan_drum_rack_extraction", {"target_daw": "ableton"}))
PY
```

Expected:

- `daw.health` reports `adapter_type` as `ableton_remote_script`,
- protocol version is `abletonian.bridge.v1`,
- capabilities include `scaffold_drum_rack_extraction`,
- selected context reports the visible selected track and selected device,
- Drum Rack extraction planning returns a dry-run with no saved-set mutation.

To validate the additive scaffold mutation, run:

```bash
.venv/bin/python - <<'PY'
from abletonian.bridge.client import BridgeClient

bridge = BridgeClient("127.0.0.1", 9877, 30.0)
print(bridge.request("workflow.scaffold_drum_rack_extraction", {"confirm": True}))
PY
```

Expected:

- created tracks are named from the active Drum Rack pads,
- the original track remains present,
- `verification.midi_filtering_applied` is `False`,
- `verification.saved_live_set` is `False`,
- the manifest includes a Live Undo backout note.

## Validation Log

### 2026-05-27, Live 12.4.0

Validated against:

```text
testing/First Light Project/First Light.als
```

Ableton setup:

- `Abletonian` selected as Control Surface slot 2.
- Input and output left as `None`.
- Selected track: `1-C78 Core Kit`.
- Selected device: `C78 Core Kit`.

Probe result:

- `daw.health` returned `adapter_type=ableton_remote_script`,
  `protocol_version=abletonian.bridge.v1`, and `live_version=12.4.0`.
- `ableton.get_selected_context` returned track `1-C78 Core Kit` and a
  `DrumGroupDevice` named `C78 Core Kit`.
- `workflow.plan_drum_rack_extraction` returned a dry-run plan for `Snare`,
  `Kick`, and `Closed Hi Hat`, with MIDI filters for pitches `38`, `41`, and
  `42`.
- `workflow.scaffold_drum_rack_extraction` with `confirm=True` duplicated the
  selected Drum Rack track into three scaffold tracks:
  `1-C78 Core Kit - Snare`, `1-C78 Core Kit - Kick`, and
  `1-C78 Core Kit - Closed Hi Hat`.
- The scaffold manifest reported `created_track_count=3`,
  `midi_filtering_applied=False`, `saved_live_set=False`, and backout guidance
  to use Live Undo three times or close without saving.

Compatibility note:

- Live 12.4 exposes `ControlSurface.application` as a property, so the Remote
  Script resolves host objects as either methods or properties before reading
  health/context.
- The `.als` fixture loader maps Drum Rack `ReceivingNote` values to MIDI
  pitches with the same pad names reported by Live's Remote Script API.
- Live mutations are dispatched through `ControlSurface.schedule_message` so
  the socket worker does not call mutating Live APIs directly.

## Mutation Gate

Before adding the next real mutation step:

- read-only health/context/planning validation is passing in Live,
- fake execution remains green against `First Light.als`,
- the real mutation method has a manual before/after checklist,
- the workflow has a backout note using Live undo and the operation manifest,
- the Live bridge request path schedules mutating work through Live's scheduler,
- current scaffold tracks can be discarded by Live Undo or closing without
  saving.
