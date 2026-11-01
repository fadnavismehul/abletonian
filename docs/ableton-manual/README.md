# Ableton manual (local copy)

This folder holds Markdown copies of the Ableton Live Reference Manual made by
`scripts/fetch_manual.py`. The manual text is (c) Ableton AG, so the copies
are gitignored and stay on your machine.

```bash
.venv/bin/python -m scripts.fetch_manual --live-major 12
```

Layout:

```text
docs/ableton-manual/
  12/
    2026-10-01/          # edition date from Ableton's PDF link
      manifest.json      # edition, fetch time, chapter titles and source URLs
      01-welcome-to-live.md
      ...
```

The MCP tools `search_ableton_manual` and `list_ableton_manual_editions` read
from here. Set `ABLETONIAN_MANUAL_DIR` to keep the copies somewhere else.
