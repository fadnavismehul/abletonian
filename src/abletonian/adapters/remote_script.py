"""DawAdapter for the Abletonian Remote Script running inside Live (RFC 0003).

Each method sends the same ``ableton.*`` bridge method and params that the
MCP tools in ``server.py`` send today, so moving a tool onto this adapter
does not change what reaches Live. The wire protocol and the Remote Script
are unchanged.
"""

from __future__ import annotations

from typing import Any, Protocol

from abletonian.adapters.base import (
    AdapterHealth,
    AdapterRefused,
    AdapterUnavailable,
    Batch,
    DeviceDelete,
    DeviceInsert,
    DeviceQuery,
    MixerChange,
    ParameterChange,
    RackRef,
    ReturnTrackCreate,
    RoutingChange,
    TrackPropertiesChange,
    TrackQuery,
    UndoRequest,
)
from abletonian.bridge.client import BridgeConnectionError, BridgeRefusedError

# Shown when an older Remote Script ignores a newer request field. Same text
# the tools return today.
OLD_SCRIPT_BATCH_WARNING = (
    "The Remote Script in Live is older and ran this batch as one undo "
    "step. Reinstall it to get one step per operation."
)
OLD_SCRIPT_UNDO_WARNING = (
    "The Remote Script in Live is older and undid only one step. "
    "Reinstall it to undo several at once."
)


class BridgeLike(Protocol):
    def request(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]: ...


class RemoteScriptAdapter:
    """Talks to the Remote Script over the framed bridge protocol."""

    def __init__(self, bridge: BridgeLike, target_daw: str = "ableton") -> None:
        self.bridge = bridge
        self.target_daw = target_daw
        self._health: AdapterHealth | None = None

    # Health and capabilities.

    def health(self) -> AdapterHealth:
        """Read daw.health now and remember it for capabilities()."""

        self._health = AdapterHealth.from_wire(
            self._call("daw.health", {"target_daw": self.target_daw})
        )
        return self._health

    def capabilities(self) -> frozenset[str]:
        """Capabilities from the last health read; reads health once if needed."""

        if self._health is None:
            self.health()
        assert self._health is not None
        return self._health.capabilities

    def known_capabilities(self) -> frozenset[str] | None:
        """Capabilities if health was already read, else None. Never calls Live."""

        return self._health.capabilities if self._health is not None else None

    def forget_health(self) -> None:
        """Drop the remembered health, for example after Live restarted."""

        self._health = None

    # Read-only.

    def list_tracks(self, query: TrackQuery) -> dict[str, Any]:
        return self._send(query)

    def list_devices(self, query: DeviceQuery) -> dict[str, Any]:
        return self._send(query)

    def get_selected_rack_macros(self, ref: RackRef) -> dict[str, Any]:
        return self._send(ref)

    def plan_drum_rack_extraction(self) -> dict[str, Any]:
        return self._call("workflow.plan_drum_rack_extraction", {"target_daw": self.target_daw})

    # Changes to the Set.

    def set_device_parameter(self, change: ParameterChange) -> dict[str, Any]:
        return self._send(change)

    def set_track_output_routing(self, change: RoutingChange) -> dict[str, Any]:
        return self._send(change)

    def set_track_properties(self, change: TrackPropertiesChange) -> dict[str, Any]:
        return self._send(change)

    def set_mixer(self, change: MixerChange) -> dict[str, Any]:
        return self._send(change)

    def insert_device(self, change: DeviceInsert) -> dict[str, Any]:
        return self._send(change)

    def create_return_track(self, change: ReturnTrackCreate) -> dict[str, Any]:
        return self._send(change)

    def delete_device(self, change: DeviceDelete) -> dict[str, Any]:
        return self._send(change)

    def apply_batch(self, batch: Batch) -> dict[str, Any]:
        params: dict[str, Any] = {
            "operations": [
                {"method": _method(operation.OPERATION), "params": operation.params()}
                for operation in batch.operations
            ]
        }
        if not batch.atomic:
            params["atomic"] = False
        result = self._call("ableton.batch", params)
        # An older script ignores atomic=false and leaves out undo_steps.
        if not batch.atomic and "undo_steps" not in result:
            result = {**result, "warning": OLD_SCRIPT_BATCH_WARNING}
        return result

    def undo(self, request: UndoRequest) -> dict[str, Any]:
        params: dict[str, Any] = {}
        if request.count > 1:
            # Live's history also holds the musician's own edits. Refuse here
            # rather than rely on the Remote Script to refuse.
            if request.confirm is not True:
                raise AdapterRefused(
                    f"undoing {request.count} steps needs confirm=true",
                    code="confirmation_required",
                )
            params = {"count": request.count, "confirm": True}
        result = self._call("ableton.undo", params)
        # An older script ignores count and reports no steps.
        if request.count > 1 and "steps" not in result:
            result = {**result, "steps": 1, "warning": OLD_SCRIPT_UNDO_WARNING}
        return result

    def execute_drum_rack_extraction(self) -> dict[str, Any]:
        return self._call(
            "workflow.execute_drum_rack_extraction",
            {"target_daw": self.target_daw, "confirm": True},
        )

    # Transport.

    def _send(self, request: Any) -> dict[str, Any]:
        return self._call(_method(request.OPERATION), request.params())

    def _call(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        try:
            return self.bridge.request(method, params)
        except BridgeRefusedError as exc:
            # Keep the client's text exactly: it is what tools show today.
            raise AdapterRefused(
                exc.message or "unknown bridge error",
                code=exc.code or "bridge_error",
                hint=exc.hint,
                text=str(exc),
            ) from exc
        except BridgeConnectionError as exc:
            self._health = None
            raise AdapterUnavailable(str(exc)) from exc


def _method(operation: str) -> str:
    return f"ableton.{operation}"
