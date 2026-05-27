"""Version-aware Ableton manual lookup helpers."""

from __future__ import annotations

from typing import Any


def lookup_manual(query: str, live_version: str = "12") -> dict[str, Any]:
    """Return cited Ableton manual guidance for a supported workflow query."""

    normalized = query.lower()
    if _is_drum_rack_extraction_query(normalized):
        return _drum_rack_extraction_result(live_version)
    return {
        "status": "no_source",
        "query": query,
        "live_version": live_version,
        "citations": [],
        "summary": "No cited Ableton manual source is available for this query yet.",
        "automation": {
            "available": False,
            "reason": "manual topic is not indexed",
        },
    }


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
