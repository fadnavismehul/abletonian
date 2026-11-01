# Ableton Validation Fixtures

This folder stores small local Ableton Live Sets used to validate Abletonian
against real `.als` files without mutating user projects.

## First Light Project

`First Light Project/First Light.als` is the first real-set fixture. It is an
Ableton Live 12.4 set with a `C78 Core Kit` Drum Rack and a `Bossa` MIDI clip.

Current validation coverage:

- load a compressed `.als` file,
- read the Ableton creator version,
- read track names and colors,
- read MIDI clip notes from Ableton `KeyTrack` lanes,
- read Drum Rack branches as pads,
- map Ableton's stored Drum Rack `ReceivingNote` values back to MIDI pitches,
- generate a dry-run extraction plan for the `Bossa` clip without mutating the
  Live Set,
- fake-execute that plan into an in-memory post-state manifest without mutating
  the Live Set.

Current dry-run output:

- `Rimshot` from MIDI note 38,
- `Tamb` from MIDI note 41,
- `Kick` from MIDI note 42.

Current fake execution creates a post-state with the six original tracks plus:

- `1-C78 Core Kit - Rimshot`,
- `1-C78 Core Kit - Tamb`,
- `1-C78 Core Kit - Kick`.

Keep this fixture small and read-only so CI-style checks stay fast and easy to
reason about. Do not save over it in Live: the integration tests in
`tests/test_als_integration.py` expect its original six tracks.

## First Light After Extraction

`First Light Project/First Light After Extraction.als` is the same set saved
after a real Drum Rack extraction in Live (`Snare`, `Kick` and `Closed Hi Hat`
tracks were added). The 2026-11-01 Live Set control validation in
`docs/engineering/live-control.md` ran against it. No automated test reads it.
