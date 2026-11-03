"""SafetyPolicy: the one path from an MCP tool to a DawAdapter (RFC 0003).

Every tool that talks to the DAW calls ``SafetyPolicy.run`` with the name of
an operation from ``OPERATIONS``. The table holds each operation's safety
class (docs/engineering/robustness-and-safety.md), the capability the adapter
must advertise, and its confirm rule, so a new tool cannot skip them. MCP
annotations are derived from the same table.

Undo grouping is the adapter's job (the Remote Script opens one Live undo
step per call); the policy records what the adapter reports.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from typing import Any

from mcp.types import ToolAnnotations

from abletonian.adapters.base import (
    AdapterError,
    Batch,
    DawAdapter,
    DeviceDelete,
    UndoRequest,
    UnsupportedOperation,
)


class SafetyClass(str, Enum):
    READ_ONLY = "read_only"
    ADDITIVE = "additive"
    TRANSFORMATIVE = "transformative"
    DESTRUCTIVE = "destructive"
    REALTIME = "realtime"


class PolicyRefused(Exception):
    """The policy refused before anything was sent to the DAW.

    str(exc) is the text the tool returns to the client.
    """


def _no_confirm_needed(request: Any) -> str | None:
    return None


@dataclass(frozen=True)
class Operation:
    name: str
    safety_class: SafetyClass
    # The daw.health capability name the adapter must advertise.
    capability: str
    # Calling twice with the same request leaves the Set as calling once.
    repeatable: bool = False
    # Returns the refusal text when the request lacks a needed confirm.
    refuse_without_confirm: Callable[[Any], str | None] = _no_confirm_needed
    # A request that changes nothing (a delete preview) logs as read-only.
    is_preview: Callable[[Any], bool] = lambda request: False

    def annotations(self) -> ToolAnnotations:
        read_only = self.safety_class is SafetyClass.READ_ONLY
        return ToolAnnotations(
            read_only_hint=read_only,
            # MCP's destructiveHint covers overwriting values as well as deleting.
            destructive_hint=self.safety_class
            in (SafetyClass.TRANSFORMATIVE, SafetyClass.DESTRUCTIVE, SafetyClass.REALTIME),
            idempotent_hint=read_only or self.repeatable,
            open_world_hint=False,
        )


def _drum_rack_confirm(confirm: bool) -> str | None:
    if confirm is not True:
        return "workflow.execute_drum_rack_extraction requires confirm=true"
    return None


def _undo_confirm(request: UndoRequest) -> str | None:
    if request.count > 1 and request.confirm is not True:
        return (
            f"Undoing {request.count} steps needs confirm=true. Live's undo history also holds "
            "the user's own edits, so check with them first. Nothing was changed."
        )
    return None


def _batch_confirm(batch: Batch) -> str | None:
    # Same rule and wording as the Remote Script (live_ops.batch), checked here
    # first so nothing is sent.
    for position, operation in enumerate(batch.operations):
        if isinstance(operation, DeviceDelete) and operation.confirm is not True:
            return (
                f"operation {position} (ableton.delete_device) needs \"confirm\": true "
                "inside a batch; nothing was changed"
            )
    return None


_OPERATIONS = (
    Operation("list_tracks", SafetyClass.READ_ONLY, "list_tracks"),
    Operation("list_devices", SafetyClass.READ_ONLY, "list_devices"),
    Operation("get_selected_rack_macros", SafetyClass.READ_ONLY, "read_rack_macros"),
    Operation("plan_drum_rack_extraction", SafetyClass.READ_ONLY, "plan_drum_rack_extraction"),
    Operation(
        "set_device_parameter", SafetyClass.TRANSFORMATIVE, "set_device_parameter", repeatable=True
    ),
    Operation(
        "set_track_output_routing",
        SafetyClass.TRANSFORMATIVE,
        "set_track_output_routing",
        repeatable=True,
    ),
    Operation(
        "set_track_properties", SafetyClass.TRANSFORMATIVE, "set_track_properties", repeatable=True
    ),
    Operation("set_mixer", SafetyClass.TRANSFORMATIVE, "set_mixer", repeatable=True),
    Operation("insert_device", SafetyClass.ADDITIVE, "insert_device"),
    Operation("create_return_track", SafetyClass.ADDITIVE, "create_return_track"),
    # Without confirm, delete_device is a preview: Live reports what would go.
    Operation(
        "delete_device",
        SafetyClass.DESTRUCTIVE,
        "delete_device",
        is_preview=lambda request: request.confirm is not True,
    ),
    # A batch may hold deletes, so it is classed by its most dangerous member.
    Operation("batch", SafetyClass.DESTRUCTIVE, "batch", refuse_without_confirm=_batch_confirm),
    # Undo rewinds Live's history, which also holds the musician's own edits.
    Operation("undo", SafetyClass.DESTRUCTIVE, "undo", refuse_without_confirm=_undo_confirm),
    Operation(
        "execute_drum_rack_extraction",
        SafetyClass.ADDITIVE,
        "execute_drum_rack_extraction",
        refuse_without_confirm=_drum_rack_confirm,
    ),
)

OPERATIONS: dict[str, Operation] = {operation.name: operation for operation in _OPERATIONS}


@dataclass(frozen=True)
class LogEntry:
    time: float
    operation: str
    safety_class: SafetyClass
    adapter: str
    outcome: str  # "ok", "refused_by_policy", or the adapter error class name
    detail: str
    undo_steps: Any = None


class SafetyPolicy:
    """Runs adapter calls under the operation table and keeps a session log."""

    # Keep the newest entries only, so a long session does not grow without end.
    MAX_LOG_ENTRIES = 1000

    def __init__(self, adapter: DawAdapter, clock: Callable[[], float] = time.time) -> None:
        self.adapter = adapter
        self.clock = clock
        self.log: list[LogEntry] = []

    def run(self, name: str, request: Any, call: Callable[[], dict[str, Any]]) -> dict[str, Any]:
        """Check, call, and record one operation.

        Raises PolicyRefused (nothing was sent), UnsupportedOperation, or the
        adapter's own AdapterError.
        """

        operation = OPERATIONS[name]
        safety_class = (
            SafetyClass.READ_ONLY if operation.is_preview(request) else operation.safety_class
        )

        refusal = operation.refuse_without_confirm(request)
        if refusal is not None:
            self._record(operation.name, safety_class, "refused_by_policy", refusal)
            raise PolicyRefused(refusal)

        known = self._known_capabilities()
        if known is not None and operation.capability not in known:
            error = UnsupportedOperation(operation.name)
            self._record(operation.name, safety_class, type(error).__name__, str(error))
            raise error

        try:
            result = call()
        except AdapterError as exc:
            self._record(operation.name, safety_class, type(exc).__name__, str(exc))
            raise
        self._record(
            operation.name,
            safety_class,
            "ok",
            "",
            undo_steps=result.get("undo_steps", result.get("steps")),
        )
        return result

    def _known_capabilities(self) -> frozenset[str] | None:
        # Only check once health has been read some other way, so the policy
        # never adds a bridge round trip (RFC 0003 implementation notes).
        known = getattr(self.adapter, "known_capabilities", None)
        return known() if callable(known) else None

    def _record(
        self,
        operation: str,
        safety_class: SafetyClass,
        outcome: str,
        detail: str,
        undo_steps: Any = None,
    ) -> None:
        self.log.append(
            LogEntry(
                time=self.clock(),
                operation=operation,
                safety_class=safety_class,
                adapter=type(self.adapter).__name__,
                outcome=outcome,
                detail=detail,
                undo_steps=undo_steps,
            )
        )
        if len(self.log) > self.MAX_LOG_ENTRIES:
            del self.log[: len(self.log) - self.MAX_LOG_ENTRIES]
