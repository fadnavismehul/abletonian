---
name: drive-live-on-mac
description: Use when an agent on the Mac must run a Live validation checklist itself (no person at Live), needs to see or operate Ableton Live's UI (Undo History, Save As, Settings, browser, track selection), reload the Abletonian Remote Script, or sees keystrokes land in the wrong app, clicks do nothing in Live, "could not create image from display", or "osascript is not allowed to send keystrokes".
---

# Drive Live on the Mac

Use this to run a `validate-in-live` checklist yourself. The bridge changes
the set and reads it. Live's UI shows what the bridge cannot, such as Undo
History, so read it from screenshots. **Every yes/no answer must come from a
bridge result or a screenshot, never from what the code is meant to do.**

Tools are in `scripts/` (run from the repo root):

| Need | Command |
| --- | --- |
| Call the bridge | `.venv/bin/python .claude/skills/drive-live-on-mac/scripts/bridge.py ableton.list_tracks '{"detail":"compact"}'` |
| Screenshot (Session view + Undo History crop) | `zsh .claude/skills/drive-live-on-mac/scripts/live.sh shot`, then Read the PNG |
| Press Undo N times, then screenshot | `live.sh undo N` |
| Keys, text, Cmd shortcuts | `live.sh key 125 36`, `live.sh type "Name"`, `live.sh cmd s shift` |
| Real mouse click (screen points) | `live.sh click X Y` |

`live.sh` brings Live to the front and refuses to send input if another app
is still in front. Never send keystrokes with a bare `osascript`. Without
that check, text and Return go into whatever app is in front, for example
the chat you are working in.

**If `live.sh` exits 4** ("frontmost app is ..."), another app took focus
back. The message names that app; usually it is the chat app redrawing.
Nothing was sent. Retry once. If it fails again, stop and tell the
person which app keeps taking focus. Never fall back to a bare `osascript`.

**Coordinates:** take them from `live.sh shot full`. If the PNG width is not
the width that `live.sh dims` prints, divide by the ratio (2 on Retina). The
default crop in `shot` fits a 2560x1440 screen. Set `LIVE_SHOT_CROP` (height,
width, offsetY, offsetX in pixels) for other screens; `undo` uses it too.
Use `shot full` to read the title bar.

## Before the first change

1. Check permissions once. Run `live.sh shot` and `live.sh key 53` (Escape).
   If either fails with a Screen Recording or Accessibility error, tell the
   person which app to allow (the one running this session) and stop.
2. Read the title bar. If it shows "First Light", run `live.sh cmd s shift`,
   take a screenshot to confirm the Save dialog is open, then
   `live.sh cmd a`, `live.sh type "First Light <purpose> check"` and
   `live.sh key 36`. If a "replace" prompt appears, the name already
   exists. Press `live.sh key 53` and pick a new name, and never replace
   anything named `First Light.als`. Confirm the new title and that
   `git status` shows the fixture unchanged. Never commit the copy; it may
   stay untracked or be deleted after the run.
3. Open Undo History (View menu) if it is not visible. It is the evidence
   for every undo step.

## Reload the Remote Script yourself

Run `.venv/bin/python -m scripts.install_remote_script`, then:

1. `live.sh cmd ,` opens Settings. If it is not on the Link, Tempo & MIDI
   tab, click that tab. Find the Abletonian slot in `live.sh shot full`.
2. `live.sh click X Y` on the slot's menu, then take a screenshot of the
   open list. Clicks inside the list do not register, so move with keys:
   126 is Up and 125 is Down, then 36 (Return). Choose None, which is the
   first entry; from Abletonian it is usually one Up.
3. Click the menu again, take a screenshot, and move to Abletonian. Then
   `live.sh key 53` closes Settings.
4. `bridge.py daw.health` must report the `adapter_version` that
   `ADAPTER_VERSION` in `remote_scripts/Abletonian/bridge_server.py` says.

## Operating Live

- **Select a track:** `live.sh click` on its header. Selecting adds no
  undo step: the redo rows stay (checked 2026-11-03).
- **Drum Rack workflow:** `workflow.plan_drum_rack_extraction` is a read;
  `workflow.scaffold_drum_rack_extraction` and
  `workflow.execute_drum_rack_extraction` need `{"confirm": true}`. All
  three act on the **selected** track, and Undo often moves the selection.
  Run `bridge.py ableton.get_selected_context` before each call. Its
  `track.name` and `device.class_name` (`DrumGroupDevice`) must be what you
  expect.
- **Arrow keys stop moving the selection** after a browser search, because
  the browser keeps keyboard focus. Click a track header instead.
- **Load a plugin:** `insert_device` only finds Live's own devices. Use
  `live.sh cmd f`, `live.sh type "<name>"`, `live.sh key 125 36`.
- **Count undo steps:** take a screenshot before and after, and count the
  new Undo History rows. Then run `live.sh undo 1` in a loop, reading the
  state from the bridge after each press. `undo N` takes a screenshot only
  at the end. A greyed row is a redo entry. Any new step removes all redo
  rows, so a call that leaves them in place added no step.

## What Live 12.4.16 does with undo (2026-11-03)

- Separate bridge requests are separate steps.
- Parameter changes, shown as `Change "<name>"`, are a separate step from
  other changes, shown as "Custom Action", even inside one begin/end pair.
- Parameter changes in one main-thread callback merge into one step.
- Each track the Drum Rack workflow creates takes 2 steps in total:
  "Duplicate Track(s)", then one for its name and colour. Clip filtering
  joins the last step.

## Finish

Undo everything, or confirm the set matches the start. Write the dated
validation log entry (see `validate-in-live`), and give a step-by-step
pass/fail with the evidence for each.
