"""Static HTML renderer for Macro Cockpit specs (RFC 0002, issue #5).

One self-contained HTML file: inline CSS, no scripts that run, no network,
and no build step. It renders only from the spec, never from Live.

Every string in a spec can come from the Live Set (track, device, and macro
names) and is untrusted, so all of it is HTML-escaped. The spec is also
embedded as inert JSON (``<script type="application/json">``) so a later
interactive renderer can read it without re-parsing the markup.
"""

from __future__ import annotations

import json
from html import escape

from abletonian.cockpit import MacroCockpitControl, MacroCockpitSpec

_CONNECTION_TEXT = {
    "read_only": ("Read-only preview", "Controls show values from Live but cannot move them yet."),
    "connected": ("Connected to Live", "Moving a control changes the rack macro in Live."),
    "simulated": ("Simulated", "Made from the fake adapter, not a running Live Set."),
}

_CSS = """
:root {
  --bg: #f7f7f5; --panel: #ffffff; --text: #1d1d1b; --muted: #6b6b66;
  --line: #e2e1dc; --track: #ecebe6; --fill: #3f6bd8; --warn-bg: #fff4d6;
  --warn-text: #6b4e00; --badge: #ecebe6;
}
@media (prefers-color-scheme: dark) {
  :root {
    --bg: #161615; --panel: #20201e; --text: #ecebe6; --muted: #a3a29b;
    --line: #34332f; --track: #34332f; --fill: #7b9cf0; --warn-bg: #3a3014;
    --warn-text: #f3d98a; --badge: #34332f;
  }
}
* { box-sizing: border-box; }
body {
  margin: 0; padding: 24px 16px 48px; background: var(--bg); color: var(--text);
  font: 15px/1.45 system-ui, -apple-system, "Segoe UI", sans-serif;
}
main { max-width: 960px; margin: 0 auto; }
header h1 { font-size: 22px; margin: 0 0 4px; overflow-wrap: anywhere; }
.source { color: var(--muted); margin: 0 0 12px; overflow-wrap: anywhere; }
.badges { display: flex; flex-wrap: wrap; gap: 8px; margin: 0 0 8px; }
.badge {
  background: var(--badge); border-radius: 999px; padding: 2px 10px; font-size: 13px;
}
.status-note { color: var(--muted); font-size: 13px; margin: 0 0 16px; }
.notes {
  background: var(--warn-bg); color: var(--warn-text); border-radius: 8px;
  padding: 10px 14px; margin: 0 0 20px;
}
.notes p { margin: 4px 0; }
.groups {
  display: grid; gap: 16px; grid-template-columns: repeat(auto-fill, minmax(260px, 1fr));
}
section.group {
  background: var(--panel); border: 1px solid var(--line); border-radius: 10px; padding: 14px;
}
section.group h2 { font-size: 16px; margin: 0; }
section.group > p { color: var(--muted); font-size: 13px; margin: 2px 0 12px; }
.control { margin: 0 0 14px; }
.control:last-child { margin-bottom: 0; }
.control-head { display: flex; justify-content: space-between; gap: 8px; }
.label { font-weight: 600; overflow-wrap: anywhere; }
.display { font-variant-numeric: tabular-nums; white-space: nowrap; }
.meta { color: var(--muted); font-size: 12px; overflow-wrap: anywhere; }
.bar { height: 8px; background: var(--track); border-radius: 4px; margin: 6px 0 2px; }
.bar > span { display: block; height: 100%; background: var(--fill); border-radius: 4px; }
.omitted { color: var(--muted); font-size: 13px; margin-top: 20px; }
.empty { color: var(--muted); }
"""


def render_cockpit_html(spec: MacroCockpitSpec) -> str:
    """Return a complete, self-contained HTML page for the cockpit."""

    source = spec.source
    connection_label, connection_note = _CONNECTION_TEXT.get(
        spec.connection, (spec.connection, "")
    )
    saved = f"Saved {spec.saved_at}" if spec.mode == "saved" else "Temporary (not saved)"
    parts = [
        "<!doctype html>",
        '<html lang="en">',
        "<head>",
        '<meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width, initial-scale=1">',
        '<meta name="color-scheme" content="light dark">',
        # Block scripts, remote loads, and form posts even if escaping ever fails.
        '<meta http-equiv="Content-Security-Policy" '
        "content=\"default-src 'none'; style-src 'unsafe-inline'; form-action 'none'\">",
        f"<title>{_e(spec.title)}</title>",
        f"<style>{_CSS}</style>",
        "</head>",
        "<body>",
        "<main>",
        "<header>",
        f"<h1>{_e(spec.title)}</h1>",
        '<p class="source">'
        f"Track {_e(source.get('track_name'))} · {_e(source.get('device_name'))} "
        f"({_e(source.get('device_type'))}) · Live {_e(source.get('live_version'))}</p>",
        '<div class="badges">',
        f'<span class="badge" data-connection="{_e(spec.connection)}">'
        f"{_e(connection_label)}</span>",
        f'<span class="badge" data-mode="{_e(spec.mode)}">{_e(saved)}</span>',
        "</div>",
        f'<p class="status-note">{_e(connection_note)}</p>',
        "</header>",
    ]
    if spec.warnings:
        parts.append('<div class="notes" role="note">')
        parts.extend(f"<p>{_e(warning)}</p>" for warning in spec.warnings)
        parts.append("</div>")
    if spec.groups:
        parts.append('<div class="groups">')
        for group in spec.groups:
            parts.append(f'<section class="group" data-group="{_e(group.id)}">')
            parts.append(f"<h2>{_e(group.label)}</h2>")
            parts.append(f"<p>{_e(group.description)}</p>")
            parts.extend(_control_html(spec.control(cid)) for cid in group.controls)
            parts.append("</section>")
        parts.append("</div>")
    else:
        parts.append('<p class="empty">This cockpit has no controls.</p>')
    if spec.omitted_macros:
        names = ", ".join(
            f"{m.get('source_macro_index')} {m.get('source_name')}" for m in spec.omitted_macros
        )
        parts.append(f'<p class="omitted">Left out (unmapped): {_e(names)}</p>')
    parts.extend(
        [
            "</main>",
            f'<script type="application/json" id="cockpit-spec">{_json_for_html(spec)}</script>',
            "</body>",
            "</html>",
        ]
    )
    return "\n".join(parts) + "\n"


def _control_html(control: MacroCockpitControl) -> str:
    percent = round(max(0.0, min(1.0, control.normalized_value)) * 100, 1)
    display = control.display or f"{control.value:g}"
    renamed = (
        f" · was {control.original_name}"
        if control.original_name and control.original_name != control.source_name
        else ""
    )
    return (
        f'<div class="control" data-control="{_e(control.id)}">'
        '<div class="control-head">'
        f'<span class="label">{_e(control.label)}</span>'
        f'<span class="display">{_e(display)}</span>'
        "</div>"
        f'<div class="bar" role="meter" aria-label="{_e(control.label)}" '
        f'aria-valuemin="{control.min:g}" aria-valuemax="{control.max:g}" '
        f'aria-valuenow="{control.value:g}" aria-valuetext="{_e(display)}">'
        f'<span style="width: {percent}%"></span></div>'
        f'<div class="meta">Macro {control.source_macro_index}{_e(renamed)}</div>'
        "</div>"
    )


def _e(value: object) -> str:
    return escape("" if value is None else str(value), quote=True)


def _json_for_html(spec: MacroCockpitSpec) -> str:
    # Inside <script>, only "</" (and "<!--") can end the element early.
    text = json.dumps(spec.to_wire(), ensure_ascii=True)
    return text.replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
