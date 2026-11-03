#!/bin/zsh
# Drive Ableton Live's UI on macOS for validation runs.
# Every input command first brings Live to the front and refuses to send
# anything if another app is frontmost, so keystrokes never land elsewhere.
#
#   live.sh shot [full]        bring Live forward, screenshot, print the PNG
#                              path (default: crop to Session view + Undo
#                              History; set LIVE_SHOT_CROP for other screens)
#   live.sh undo [N]           press Cmd+Z N times (default 1), then shot
#   live.sh cmd KEY [shift]    Cmd+KEY (Cmd+Shift+KEY with "shift")
#   live.sh type TEXT          type literal text
#   live.sh key CODE...        key codes: 36 Return, 53 Escape, 123 Left,
#                              124 Right, 125 Down, 126 Up
#   live.sh click X Y          real mouse click at screen points
#   live.sh dims               print main screen size in points
set -u
HERE=${0:A:h}
CROP=${LIVE_SHOT_CROP:-"970 1390 30 480"}   # height width offsetY offsetX (pixels)

front() {
  osascript -e 'tell application "Live" to activate' >/dev/null
  sleep 0.5
  local f
  f=$(osascript -e 'tell application "System Events" to get name of first process whose frontmost is true') || {
    echo "osascript failed: grant Accessibility to this terminal app" >&2; exit 3; }
  [ "$f" = "Live" ] || { echo "refusing to send input: frontmost app is '$f'" >&2; exit 4; }
}

shot() {
  local f=/tmp/live-$(date +%s)-$RANDOM.png
  screencapture -x "$f" || { echo "screencapture failed: grant Screen Recording to this terminal app" >&2; exit 3; }
  if [ "${1:-}" = "full" ]; then echo "$f"; return; fi
  local c=(${=CROP})
  sips -c $c[1] $c[2] --cropOffset $c[3] $c[4] "$f" --out "${f%.png}-c.png" >/dev/null && echo "${f%.png}-c.png"
}

sys() { osascript -e "tell application \"System Events\" to $1" >/dev/null || exit 3; }

case "${1:-}" in
  shot) osascript -e 'tell application "Live" to activate' >/dev/null; sleep 0.5; shot "${2:-}" ;;
  undo)
    for _ in $(seq 1 "${2:-1}"); do front; sys 'keystroke "z" using command down'; sleep 0.6; done
    sleep 0.4; shot ;;
  cmd)
    front
    if [ "${3:-}" = "shift" ]; then sys "keystroke \"$2\" using {command down, shift down}"
    else sys "keystroke \"$2\" using command down"; fi ;;
  type)
    t=${2//\\/\\\\}; t=${t//\"/\\\"}   # escape \ and " for AppleScript
    front; sys "keystroke \"$t\"" ;;
  key) shift; for k in "$@"; do front; sys "key code $k"; sleep 0.3; done ;;
  click)
    BIN=/tmp/abletonian-live-click
    [ -x $BIN ] || swiftc -O "$HERE/click.swift" -o $BIN || exit 3
    front; $BIN "$2" "$3" ;;
  dims) osascript -e 'tell application "Finder" to get bounds of window of desktop' ;;
  *) sed -n 2,16p "$0"; exit 2 ;;
esac
