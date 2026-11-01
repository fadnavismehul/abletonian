"""Fetch the Ableton Live Reference Manual and convert it to local Markdown.

The manual is Ableton's copyrighted text, so it is not committed. This script
builds a local, versioned copy for search:

    docs/ableton-manual/<live-major>/<edition>/
        manifest.json
        01-welcome-to-live.md
        ...

The edition is the date stamp Ableton puts on the manual's PDF link, such as
``2026-10-01``. Run it again after a new edition ships; older editions stay
in place so answers can be pinned to a version.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import re
import time
import urllib.request
from datetime import datetime, timezone
from html.parser import HTMLParser

PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_ROOT = PROJECT_ROOT / "docs" / "ableton-manual"
BASE_URL = "https://www.ableton.com"
USER_AGENT = "abletonian-manual-fetch/0.1 (+https://github.com/fadnavismehul/abletonian)"


def manual_index_url(live_major: str, language: str = "en") -> str:
    return f"{BASE_URL}/{language}/live-manual/{live_major}/"


def fetch(url: str) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=30) as response:
        return response.read().decode("utf-8")


def chapter_slugs(index_html: str, live_major: str, language: str = "en") -> list[str]:
    """Return chapter slugs in the order the index links them."""

    pattern = re.compile(rf'href="/{language}/live-manual/{re.escape(live_major)}/([a-z0-9-]+)/')
    seen: list[str] = []
    for slug in pattern.findall(index_html):
        if slug not in seen:
            seen.append(slug)
    return seen


def edition_from_index(index_html: str, live_major: str) -> str:
    """Read the edition date from the PDF link, e.g. ``.../12/2026-10-01/...pdf``."""

    pattern = rf"live-manual/{re.escape(live_major)}/(\d{{4}}-\d{{2}}-\d{{2}})/"
    match = re.search(pattern, index_html)
    if match:
        return match.group(1)
    return datetime.now(timezone.utc).strftime("%Y-%m-%d") + "-fetched"


class ChapterToMarkdown(HTMLParser):
    """Convert the ``#chapter_content`` block of a manual page to Markdown."""

    BLOCKS = {"p", "figcaption", "li", "h1", "h2", "h3", "h4", "h5", "h6", "pre", "tr"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.depth = 0
        self.inside = False
        self.lines: list[str] = []
        self.buffer: list[str] = []
        self.block: str | None = None
        self.anchor: str | None = None
        self.lists: list[str] = []
        self.list_counters: list[int] = []
        self.cells: list[str] = []
        self.table_rows = 0
        self.in_cell = False
        self.skip = 0

    def _paragraph_inside_block(self, tag: str) -> bool:
        # <li><p>..</p></li> and <td><p>..</p></td> keep the outer block.
        return tag == "p" and (self.in_cell or self.block == "li")

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        if not self.inside:
            if tag == "div" and attributes.get("id") == "chapter_content":
                self.inside = True
                self.depth = 1
            return
        if tag == "div":
            self.depth += 1
        if tag in ("script", "style", "button"):
            self.skip += 1
        if self.skip:
            return
        if self._paragraph_inside_block(tag):
            self.buffer.append(" ")
            return
        if tag in ("ul", "ol"):
            self.flush()
            self.lists.append(tag)
            self.list_counters.append(0)
        elif tag == "table":
            self.flush()
            self.table_rows = 0
        elif tag in ("td", "th"):
            self.buffer = []
            self.in_cell = True
        elif tag in self.BLOCKS:
            self.flush()
            self.block = tag
            if tag.startswith("h"):
                self.anchor = attributes.get("id")
            if tag == "li" and self.list_counters:
                self.list_counters[-1] += 1
        elif tag in ("em", "i"):
            self.buffer.append("*")
        elif tag in ("strong", "b"):
            self.buffer.append("**")
        elif tag in ("kbd", "code") and self.block != "pre":
            self.buffer.append("`")
        elif tag == "br":
            self.buffer.append(" ")
        elif tag == "span" and "header-section-number" in (attributes.get("class") or ""):
            pass

    def handle_endtag(self, tag: str) -> None:
        if not self.inside:
            return
        if tag == "div":
            self.depth -= 1
            if self.depth == 0:
                self.flush()
                self.inside = False
            return
        if tag in ("script", "style", "button"):
            self.skip = max(0, self.skip - 1)
            return
        if self.skip:
            return
        if self._paragraph_inside_block(tag):
            self.buffer.append(" ")
            return
        if tag in ("ul", "ol"):
            self.flush()
            if self.lists:
                self.lists.pop()
                self.list_counters.pop()
        elif tag in ("td", "th"):
            self.cells.append(_clean("".join(self.buffer)).replace("|", "\\|"))
            self.buffer = []
            self.in_cell = False
        elif tag == "tr":
            if self.cells:
                self.lines.append("| " + " | ".join(self.cells) + " |")
                if self.table_rows == 0:
                    self.lines.append("|" + " --- |" * len(self.cells))
                self.table_rows += 1
            self.cells = []
            self.block = None
        elif tag == "table":
            self.lines.append("")
        elif tag in self.BLOCKS:
            self.flush()
        elif tag in ("em", "i"):
            self.buffer.append("*")
        elif tag in ("strong", "b"):
            self.buffer.append("**")
        elif tag in ("kbd", "code") and self.block != "pre":
            self.buffer.append("`")

    def handle_data(self, data: str) -> None:
        if self.inside and not self.skip:
            self.buffer.append(data)

    def flush(self) -> None:
        if self.block == "tr":
            return
        text = "".join(self.buffer)
        block = self.block
        self.buffer = []
        self.block = None
        if block == "pre":
            if text.strip():
                self.lines.extend(["```", text.rstrip(), "```", ""])
            return
        text = _clean(text)
        if not text:
            return
        if block and block.startswith("h"):
            level = int(block[1])
            anchor = f" {{#{self.anchor}}}" if self.anchor else ""
            self.lines.extend([f"{'#' * level} {text}{anchor}", ""])
            self.anchor = None
        elif block == "li":
            indent = "  " * max(0, len(self.lists) - 1)
            marker = f"{self.list_counters[-1]}." if self.lists and self.lists[-1] == "ol" else "-"
            self.lines.append(f"{indent}{marker} {text}")
        elif block == "figcaption":
            self.lines.extend([f"*Figure: {text}*", ""])
        else:
            if self.lines and re.match(r"\s*(-|\d+\.) ", self.lines[-1]):
                self.lines.append("")
            self.lines.extend([text, ""])

    def markdown(self) -> str:
        self.flush()
        text = "\n".join(self.lines)
        return re.sub(r"\n{3,}", "\n\n", text).strip() + "\n"


def _clean(text: str) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    return text.replace("** **", " ").replace("****", "").replace("``", "`+`")


def chapter_markdown(html: str) -> str:
    parser = ChapterToMarkdown()
    parser.feed(html)
    return parser.markdown()


def fetch_manual(
    live_major: str = "12",
    language: str = "en",
    output_root: pathlib.Path = DEFAULT_OUTPUT_ROOT,
    delay_seconds: float = 0.5,
) -> pathlib.Path:
    index_url = manual_index_url(live_major, language)
    index_html = fetch(index_url)
    edition = edition_from_index(index_html, live_major)
    slugs = chapter_slugs(index_html, live_major, language)
    if not slugs:
        raise RuntimeError(f"no chapters found at {index_url}")

    output = output_root / live_major / edition
    output.mkdir(parents=True, exist_ok=True)
    chapters = []
    for number, slug in enumerate(slugs, start=1):
        url = f"{index_url}{slug}/"
        markdown = chapter_markdown(fetch(url))
        filename = f"{number:02d}-{slug}.md"
        title = markdown.splitlines()[0].lstrip("# ").split(" {#")[0] if markdown.strip() else slug
        (output / filename).write_text(
            f"<!-- Source: {url} (edition {edition}). (c) Ableton AG. -->\n\n{markdown}",
            encoding="utf-8",
        )
        chapters.append({"file": filename, "slug": slug, "title": title, "url": url})
        print(f"{filename}  {title}")
        time.sleep(delay_seconds)

    manifest = {
        "live_major": live_major,
        "language": language,
        "edition": edition,
        "source": index_url,
        "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "chapters": chapters,
    }
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return output


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--live-major", default="12")
    parser.add_argument("--language", default="en")
    parser.add_argument("--output-root", type=pathlib.Path, default=DEFAULT_OUTPUT_ROOT)
    args = parser.parse_args()
    print(fetch_manual(args.live_major, args.language, args.output_root))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
