"""Version-aware Ableton manual lookup helpers."""

from __future__ import annotations

import json
import math
import os
import re
from pathlib import Path
from typing import Any

DEFAULT_MANUAL_ROOT = Path(__file__).resolve().parents[2] / "docs" / "ableton-manual"
STOPWORDS = frozenset(
    "a an and are as at be by can do does for from how i in into is it its of on or "
    "the this to what when where which with you your".split()
)


def lookup_manual(
    query: str,
    live_version: str = "12",
    manual_root: Path | None = None,
) -> dict[str, Any]:
    """Return cited Ableton manual guidance for a query.

    Curated workflow topics answer first; anything else falls back to a search
    of the locally fetched manual (see ``scripts/fetch_manual.py``).
    """

    normalized = query.lower()
    if _is_drum_rack_extraction_query(normalized):
        return _drum_rack_extraction_result(live_version)
    search = search_manual(query, live_version, manual_root=manual_root)
    if search["status"] == "ok" and search["results"]:
        return search
    return {
        "status": "no_source",
        "query": query,
        "live_version": live_version,
        "citations": [],
        "summary": "No cited Ableton manual source is available for this query yet.",
        "automation": {
            "available": False,
            "reason": search.get("reason", "manual topic is not indexed"),
        },
    }


def default_manual_root() -> Path:
    return Path(os.getenv("ABLETONIAN_MANUAL_DIR", str(DEFAULT_MANUAL_ROOT)))


def list_manual_editions(manual_root: Path | None = None) -> list[dict[str, Any]]:
    """List locally fetched manual editions, newest first within each Live version."""

    root = manual_root or default_manual_root()
    editions = []
    for manifest_path in sorted(root.glob("*/*/manifest.json"), reverse=True):
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        editions.append(
            {
                "live_major": manifest["live_major"],
                "edition": manifest["edition"],
                "fetched_at": manifest.get("fetched_at"),
                "chapter_count": len(manifest.get("chapters", [])),
                "path": str(manifest_path.parent),
            }
        )
    return editions


def search_manual(
    query: str,
    live_version: str = "12",
    edition: str | None = None,
    limit: int = 5,
    manual_root: Path | None = None,
) -> dict[str, Any]:
    """Rank manual sections against a query and return cited snippets."""

    live_major = str(live_version).split(".")[0]
    root = manual_root or default_manual_root()
    edition_dir = _edition_dir(root, live_major, edition)
    if edition_dir is None:
        return {
            "status": "no_source",
            "query": query,
            "live_version": live_major,
            "results": [],
            "citations": [],
            "reason": (
                f"no local Live {live_major} manual"
                + (f" edition {edition}" if edition else "")
                + "; run: python -m scripts.fetch_manual"
            ),
        }

    manifest = json.loads((edition_dir / "manifest.json").read_text(encoding="utf-8"))
    terms = _terms(query)
    phrase = " ".join(query.lower().split())
    scored = []
    for chapter in manifest["chapters"]:
        text = (edition_dir / chapter["file"]).read_text(encoding="utf-8")
        for section in _sections(text):
            score = _score(section, terms, phrase)
            if score > 0:
                scored.append((score, chapter, section))
    scored.sort(key=lambda item: item[0], reverse=True)

    results = []
    for score, chapter, section in scored[: max(1, limit)]:
        url = chapter["url"] + (f"#{section['anchor']}" if section["anchor"] else "")
        results.append(
            {
                "chapter": chapter["title"],
                "section": section["heading"],
                "url": url,
                "score": round(score, 2),
                "snippet": _snippet(section["body"], terms),
            }
        )
    return {
        "status": "ok",
        "query": query,
        "live_version": live_major,
        "edition": manifest["edition"],
        "results": results,
        "citations": [
            {"title": f"Ableton Live {live_major} Manual: {r['section']}", "url": r["url"]}
            for r in results
        ],
    }


def _edition_dir(root: Path, live_major: str, edition: str | None) -> Path | None:
    version_dir = root / live_major
    if edition:
        candidate = version_dir / edition
        return candidate if (candidate / "manifest.json").exists() else None
    editions = sorted(p for p in version_dir.glob("*") if (p / "manifest.json").exists())
    return editions[-1] if editions else None


_HEADING = re.compile(r"^(#{1,6}) (.+?)(?: \{#([^}]+)\})?$")


def _sections(text: str) -> list[dict[str, str]]:
    sections: list[dict[str, str]] = []
    current = {"heading": "", "anchor": "", "body": ""}
    lines: list[str] = []
    for line in text.splitlines():
        match = _HEADING.match(line)
        if match:
            if lines or current["heading"]:
                current["body"] = "\n".join(lines).strip()
                sections.append(current)
            current = {"heading": match.group(2), "anchor": match.group(3) or "", "body": ""}
            lines = []
        elif not line.startswith("<!--"):
            lines.append(line)
    current["body"] = "\n".join(lines).strip()
    sections.append(current)
    return [section for section in sections if section["heading"] or section["body"]]


def _terms(query: str) -> list[str]:
    words = re.findall(r"[a-z0-9]+", query.lower())
    return [word for word in words if word not in STOPWORDS and len(word) > 1] or words


def _score(section: dict[str, str], terms: list[str], phrase: str) -> float:
    heading = section["heading"].lower()
    body = section["body"].lower()
    words = re.findall(r"[a-z0-9]+", body)
    if not words:
        return 0.0
    score = 0.0
    matched = 0
    for term in terms:
        count = sum(1 for word in words if word.startswith(term))
        in_heading = term in heading
        if count or in_heading:
            matched += 1
        score += math.log1p(count) + (3.0 if in_heading else 0.0)
    if matched == 0:
        return 0.0
    score *= matched / len(terms)
    if len(terms) > 1 and phrase in body:
        score += 4.0
    return score


def _snippet(body: str, terms: list[str], width: int = 600) -> str:
    paragraphs = [p for p in body.split("\n\n") if p.strip() and not p.startswith("*Figure")]
    if not paragraphs:
        return ""
    best = max(paragraphs, key=lambda p: sum(p.lower().count(term) for term in terms))
    best = " ".join(best.split())
    return best if len(best) <= width else best[: width - 1].rsplit(" ", 1)[0] + "…"


def _is_drum_rack_extraction_query(query: str) -> bool:
    return (
        "drum rack" in query
        and ("extract" in query or "split" in query)
        and ("chain" in query or "track" in query or "pad" in query)
    )


def _drum_rack_extraction_result(live_version: str) -> dict[str, Any]:
    return {
        "status": "ok",
        "topic": "drum_rack_extraction",
        "live_version": live_version,
        "summary": (
            "Ableton documents extracting chains from Instrument, Drum, and Effect "
            "Racks. For Abletonian, this maps to a dry-run split_drum_rack "
            "workflow that preserves the source track and plans one output track "
            "per meaningful pad or chain."
        ),
        "concepts": [
            "Drum Rack",
            "drum pad",
            "chain",
            "MIDI note filtering",
            "track duplication",
        ],
        "automation": {
            "available": True,
            "abletonian_operation": "split_drum_rack",
            "requires_dry_run": True,
            "current_stage": "fake_adapter_dry_run",
        },
        "citations": [
            {
                "title": "Ableton Live Manual: Extracting Chains",
                "url": "https://www.ableton.com/en/live-manual/11/instrument-drum-and-effect-racks/#extracting-chains",
            },
            {
                "title": "Ableton Live Manual: Welcome to Live",
                "url": f"https://www.ableton.com/en/live-manual/{live_version}/welcome-to-live/",
            },
        ],
    }
