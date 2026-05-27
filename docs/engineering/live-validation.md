# Live Validation

This document records the manual validation path for real Ableton Live before
mutating adapter workflows are allowed.

## Current Scope

Current live validation is read-only:

- install the Abletonian Remote Script into the User Library,
- enable it as a Control Surface in Ableton Live,
- connect to `127.0.0.1:9877`,
- call `daw.health`,
- call `ableton.get_selected_context`,
- call `workflow.plan_drum_rack_extraction`,
- confirm the selected track/device and dry-run plan match the visible Live Set.

The Remote Script does not create tracks, duplicate tracks, edit MIDI notes, or
save Live Sets.

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
- capabilities are read-only,
- selected context reports the visible selected track and selected device,
- Drum Rack extraction planning returns a dry-run with no saved-set mutation.

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

Compatibility note:

- Live 12.4 exposes `ControlSurface.application` as a property, so the Remote
  Script resolves host objects as either methods or properties before reading
  health/context.
- The `.als` fixture loader maps Drum Rack `ReceivingNote` values to MIDI
  pitches with the same pad names reported by Live's Remote Script API.

## Mutation Gate

Do not add real mutation methods until:

- read-only health/context/planning validation is passing in Live,
- fake execution remains green against `First Light.als`,
- the real mutation method has a manual before/after checklist,
- the workflow has a backout note using Live undo and the operation manifest.
