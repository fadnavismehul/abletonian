"""Saved Macro Cockpits as readable JSON sidecar files (RFC 0002, issue #7).

Cockpits are temporary until the user saves one. A saved cockpit is the
spec's wire JSON with ``mode: "saved"``, one file per cockpit id, in a
per-user folder (see ``AbletonianConfig.resolved_cockpit_dir``). Nothing here
touches the Live Set.
"""

from __future__ import annotations

import dataclasses
import json
import os
import pathlib
import re
import tempfile
from datetime import datetime, timezone
from typing import Any

from abletonian.cockpit import CockpitError, MacroCockpitSpec

# Generated ids look like "macro-cockpit-keys-rack-1a2b3c4d". Anything else is
# refused so an id can never point outside the cockpit folder.
_SAFE_ID = re.compile(r"^[a-z0-9][a-z0-9-]{0,127}$")


class CockpitStoreError(RuntimeError):
    """Raised when a cockpit cannot be saved or loaded."""


class CockpitStore:
    """Reads and writes saved cockpits in one folder."""

    def __init__(self, root: pathlib.Path) -> None:
        self.root = pathlib.Path(root)

    def save(self, spec: MacroCockpitSpec, saved_at: str | None = None) -> MacroCockpitSpec:
        """Save a cockpit and return the saved copy.

        Saving the same cockpit id again replaces that cockpit's file; the id
        includes the rack fingerprint, so a different rack never shares a file.
        """

        path = self._path(spec.id)
        if path.exists():
            existing_id = self._read_wire(path).get("id")
            if existing_id != spec.id:
                raise CockpitStoreError(
                    f"{path.name} holds cockpit {existing_id!r}, not {spec.id!r}; not overwriting"
                )
        saved = dataclasses.replace(
            spec,
            mode="saved",
            saved_at=saved_at or datetime.now(timezone.utc).isoformat(timespec="seconds"),
        )
        self.root.mkdir(parents=True, exist_ok=True)
        _write_atomic(path, json.dumps(saved.to_wire(), indent=2, sort_keys=False) + "\n")
        return saved

    def load(self, cockpit_id: str) -> MacroCockpitSpec:
        path = self._path(cockpit_id)
        if not path.exists():
            raise CockpitStoreError(f"no saved cockpit {cockpit_id!r} in {self.root}")
        try:
            spec = MacroCockpitSpec.from_wire(self._read_wire(path))
        except CockpitError as exc:
            raise CockpitStoreError(f"{path.name} is not a valid cockpit: {exc}") from exc
        if spec.id != cockpit_id:
            raise CockpitStoreError(f"{path.name} holds cockpit {spec.id!r}, not {cockpit_id!r}")
        return spec

    def list_saved(self) -> list[dict[str, Any]]:
        """Summaries of saved cockpits, newest first. Bad files are listed with an error."""

        if not self.root.is_dir():
            return []
        entries: list[dict[str, Any]] = []
        for path in sorted(self.root.glob("*.json")):
            try:
                spec = self.load(path.stem)
            except CockpitStoreError as exc:
                entries.append({"file": path.name, "error": str(exc)})
                continue
            entries.append(
                {
                    "id": spec.id,
                    "title": spec.title,
                    "track_name": spec.source.get("track_name"),
                    "device_name": spec.source.get("device_name"),
                    "control_count": len(spec.controls),
                    "saved_at": spec.saved_at,
                    "fingerprint": spec.source.get("fingerprint"),
                }
            )
        entries.sort(key=lambda entry: entry.get("saved_at") or "", reverse=True)
        return entries

    def _path(self, cockpit_id: str) -> pathlib.Path:
        if not isinstance(cockpit_id, str) or not _SAFE_ID.match(cockpit_id):
            raise CockpitStoreError(
                f"invalid cockpit id {cockpit_id!r}; use an id from generate_macro_cockpit"
            )
        return self.root / f"{cockpit_id}.json"

    @staticmethod
    def _read_wire(path: pathlib.Path) -> dict[str, Any]:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise CockpitStoreError(f"cannot read {path.name}: {exc}") from exc
        if not isinstance(data, dict):
            raise CockpitStoreError(f"{path.name} is not a JSON object")
        return data


def _write_atomic(path: pathlib.Path, text: str) -> None:
    """Write via a temp file in the same folder, then rename over the target."""

    fd, temp_name = tempfile.mkstemp(prefix=f".{path.stem}-", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, path)
    except BaseException:
        try:
            os.unlink(temp_name)
        except OSError:
            pass
        raise
