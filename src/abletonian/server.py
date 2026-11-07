"""MCP server construction for abletonian."""

from __future__ import annotations

import json
import webbrowser
from typing import Any

from mcp.server.mcpserver import MCPServer
from mcp.types import ToolAnnotations
from pydantic import StrictBool

from abletonian.adapters.base import (
    AdapterError,
    AdapterResponseError,
    Batch,
    DawAdapter,
    DeviceDelete,
    DeviceInsert,
    DeviceQuery,
    DeviceRead,
    MixerChange,
    ParameterChange,
    RackRef,
    ReturnTrackCreate,
    RoutingChange,
    TrackPropertiesChange,
    TrackQuery,
    UndoRequest,
    UnsupportedOperation,
)
from abletonian.adapters.remote_script import RemoteScriptAdapter
from abletonian.bridge.client import BridgeClient
from abletonian.cockpit import CockpitError, MacroCockpitSpec, rack_fingerprint, render_cockpit_text
from abletonian.cockpit import generate_macro_cockpit as build_macro_cockpit
from abletonian.cockpit_html import render_cockpit_html
from abletonian.cockpit_store import CockpitStore, CockpitStoreError, write_text_atomic
from abletonian.config import AbletonianConfig
from abletonian.daws import get_daw_profile, list_daw_profiles
from abletonian.manual import list_manual_editions, lookup_manual, search_manual
from abletonian.policy import OPERATIONS, PolicyRefused, SafetyPolicy


def _annotations(read_only: bool, destructive: bool, idempotent: bool) -> ToolAnnotations:
    return ToolAnnotations(
        read_only_hint=read_only,
        destructive_hint=destructive,
        idempotent_hint=idempotent,
        open_world_hint=False,
    )


# MCP tool annotations, so clients can tell reads from changes (for example
# to auto-approve reads). They are hints for the client; the confirm and undo
# rules are enforced by SafetyPolicy. Tools that reach the DAW take theirs
# from the operation table in policy.py; these two cover the rest.
# Read-only: never changes the Live Set or any file.
READ_ONLY = _annotations(read_only=True, destructive=False, idempotent=True)
# Writes a file outside the Live Set (cockpit JSON or HTML); the Set is untouched.
LOCAL_FILE = _annotations(read_only=False, destructive=False, idempotent=True)


def _op(name: str) -> ToolAnnotations:
    return OPERATIONS[name].annotations()


_BATCH_TYPES = {
    f"ableton.{kind.OPERATION}": kind
    for kind in (
        ParameterChange,
        RoutingChange,
        TrackPropertiesChange,
        MixerChange,
        DeviceInsert,
        ReturnTrackCreate,
        DeviceDelete,
    )
}


def parse_batch(operations: list[dict[str, Any]]) -> tuple[Any, ...]:
    """Turn apply_batch's {"method", "params"} dicts into typed changes.

    Raises ValueError or TypeError with the position of the bad operation.
    """

    if not operations:
        raise ValueError("batch operations must be a non-empty list")
    parsed = []
    for position, operation in enumerate(operations):
        method = operation.get("method") if isinstance(operation, dict) else None
        kind = _BATCH_TYPES.get(method) if isinstance(method, str) else None
        if kind is None:
            raise ValueError(
                f"operation {position} has unsupported method {method!r}; "
                f"allowed: {', '.join(_BATCH_TYPES)}"
            )
        params = operation.get("params") or {}
        if not isinstance(params, dict):
            raise ValueError(f"operation {position}: params must be an object")
        try:
            parsed.append(kind(**{k: v for k, v in params.items() if v is not None}))
        except TypeError as exc:
            raise ValueError(f"operation {position} ({method}): {exc}") from exc
    return tuple(parsed)


def build_mcp(
    config: AbletonianConfig,
    bridge: Any | None = None,
    cockpit_store: CockpitStore | None = None,
    open_url: Any = webbrowser.open,
    adapter: DawAdapter | None = None,
) -> MCPServer:
    """Build an MCP server named after the configured agent.

    adapter is the DAW connection. bridge is kept for one release: when given
    (and adapter is not), it is wrapped in a RemoteScriptAdapter.
    """

    mcp = MCPServer(config.agent_name)
    if adapter is None:
        bridge_client = bridge or BridgeClient(
            host=config.bridge_host,
            port=config.bridge_port,
            timeout=config.bridge_timeout,
        )
        adapter = RemoteScriptAdapter(bridge_client, target_daw=config.target_daw)
    daw: DawAdapter = adapter
    policy = SafetyPolicy(daw)
    target_profile = get_daw_profile(config.target_daw)
    store = cockpit_store or CockpitStore(config.resolved_cockpit_dir)
    # Cockpits generated in this session, so the user can choose to save one.
    recent_cockpits: dict[str, MacroCockpitSpec] = {}

    @mcp.tool(annotations=READ_ONLY)
    def get_agent_profile() -> str:
        """Return the configured abletonian agent profile."""

        profile: dict[str, Any] = {
            "agent_name": config.agent_name,
            "default_agent_name": "abletonian",
            "target_daw": target_profile.to_wire(),
            "bridge": {
                "host": config.bridge_host,
                "port": config.bridge_port,
                "timeout": config.bridge_timeout,
            },
            "stance": "safe, musician-facing DAW automation",
        }
        return json.dumps(profile, indent=2)

    @mcp.tool(annotations=READ_ONLY)
    def list_supported_daws() -> str:
        """List DAW targets known by abletonian and their adapter strategies."""

        return json.dumps([profile.to_wire() for profile in list_daw_profiles()], indent=2)

    @mcp.tool(annotations=READ_ONLY)
    def get_target_daw_profile() -> str:
        """Return the configured target DAW profile."""

        return json.dumps(target_profile.to_wire(), indent=2)

    @mcp.tool(annotations=READ_ONLY)
    def check_bridge_health() -> str:
        """Check whether the configured DAW bridge responds."""

        try:
            health = daw.health()
        except AdapterResponseError as exc:
            return f"Bridge answered, but its health report is not usable: {exc}"
        except AdapterError as exc:
            return f"Bridge unavailable: {exc}"
        return json.dumps(dict(health.raw), indent=2)

    @mcp.tool(annotations=READ_ONLY)
    def lookup_ableton_manual(query: str, live_version: str = "12") -> str:
        """Return cited Ableton manual context for an indexed workflow query."""

        return json.dumps(lookup_manual(query, live_version), indent=2)

    @mcp.tool(annotations=READ_ONLY)
    def search_ableton_manual(
        query: str,
        live_version: str = "12",
        edition: str | None = None,
        limit: int = 5,
    ) -> str:
        """Search the locally fetched Ableton Live Reference Manual.

        Returns ranked sections with snippets and ableton.com citation links.
        edition pins a manual edition date (see list_ableton_manual_editions);
        the newest local edition is used by default.
        """

        return json.dumps(search_manual(query, live_version, edition, limit), indent=2)

    @mcp.tool(annotations=READ_ONLY)
    def list_ableton_manual_editions() -> str:
        """List the Ableton manual editions fetched into this checkout."""

        return json.dumps(list_manual_editions(), indent=2)

    @mcp.tool(annotations=_op("plan_drum_rack_extraction"))
    def plan_drum_rack_extraction() -> str:
        """Return a dry-run Drum Rack extraction plan from the configured bridge."""

        return run(
            "plan_drum_rack_extraction",
            None,
            daw.plan_drum_rack_extraction,
            prefix="Bridge unavailable",
        )

    @mcp.tool(annotations=_op("execute_drum_rack_extraction"))
    def execute_drum_rack_extraction(confirm: StrictBool = False) -> str:
        """Execute Drum Rack extraction after explicit confirmation."""

        return run(
            "execute_drum_rack_extraction",
            confirm,
            daw.execute_drum_rack_extraction,
            prefix="Bridge unavailable",
        )

    def run(
        name: str, request: Any, call: Any, prefix: str = "Bridge error"
    ) -> str:
        """Run one DAW operation through the policy and format the result."""

        try:
            result = policy.run(name, request, call)
        except PolicyRefused as exc:
            return str(exc)
        except UnsupportedOperation as exc:
            return (
                f"Not supported: {exc}, according to its last health report. Nothing was "
                "sent. If the Remote Script in Live was updated since, run "
                "check_bridge_health and try again."
            )
        except AdapterError as exc:
            return f"{prefix}: {exc}"
        return json.dumps(result, indent=2)

    def send(name: str, request: Any) -> str:
        return run(name, request, lambda: getattr(daw, name)(request))

    @mcp.tool(annotations=_op("list_tracks"))
    def list_tracks(
        include_returns: bool = True,
        include_master: bool = True,
        detail: str = "compact",
        name: str | None = None,
    ) -> str:
        """List tracks in the open Live Set: names, groups, colours, output routing,
        volume, pan, sends, mute/solo, and device names. Read-only.

        detail "compact" (default) gives levels as display text and leaves out
        routing options, so large sets fit; use "full" (ideally with name) for
        raw values and the available output routing choices. name keeps tracks
        whose name contains it.

        Track references used by other tools accept an index into this list's
        regular tracks, a track name, "A"/"B"/... or "return:N" for returns, and
        "main" for the main track.
        """

        return send(
            "list_tracks",
            TrackQuery(
                include_returns=include_returns,
                include_master=include_master,
                detail=detail,
                name=name,
            ),
        )

    @mcp.tool(annotations=_op("list_devices"))
    def list_devices(
        track: int | str | None = None,
        detail: str = "compact",
        include_parameters: bool | None = None,
        max_depth: int | None = None,
    ) -> str:
        """List devices on one track (or every track when track is omitted).
        Read-only: never changes the Live Set.

        detail "compact" (default) gives each device's name, path, class and
        on/off state, and each rack chain's name and device count, with no
        parameters. Devices inside racks are listed under their chains (and
        Drum Rack return chains) with a "path" that get_device,
        set_device_parameter and delete_device accept. To read parameters, use
        get_device on one path (optionally with a parameter name filter).

        detail "full" (or include_parameters=true) adds every parameter of
        every device with raw value, range, display text and options. That is
        large: a track with a Drum Rack can reach megabytes (2.5 MB seen), so
        start with compact.

        max_depth (0-4, default 4) is how many rack levels have their chains
        expanded. max_depth=0 lists a Drum Rack's chains by index, name and
        device count only ("truncated": true), without their devices.
        """

        if detail not in ("compact", "full"):
            return f"detail must be 'compact' or 'full', got '{detail}'. Nothing was read."
        if include_parameters is None:
            include_parameters = detail == "full"
        return send(
            "list_devices",
            DeviceQuery(track=track, include_parameters=include_parameters, max_depth=max_depth),
        )

    @mcp.tool(annotations=_op("get_device"))
    def get_device(
        track: int | str,
        device: int | str,
        parameters: str | list[str] | None = None,
    ) -> str:
        """Read one device's parameters: raw value, display text, min/max range,
        and options for switches and menus. Read-only: never changes the Live
        Set.

        device is an index, a device name, or a path from list_devices, the
        same as set_device_parameter takes (for example "Drum Rack/Kick/Simpler"
        or "Drum Rack/4/Guiro Short"). parameters keeps only parameters whose
        name contains it (case-insensitive), or any of a list of names; omit it
        for all of them. Use this to check one value before or after setting
        it. Rack chains are listed by name and device count only.
        """

        wanted = tuple(parameters) if isinstance(parameters, list) else parameters
        return send("get_device", DeviceRead(track=track, device=device, parameters=wanted))

    @mcp.tool(annotations=_op("set_device_parameter"))
    def set_device_parameter(
        track: int | str,
        device: int | str,
        parameter: int | str,
        value: float | str,
    ) -> str:
        """Set a device parameter in the open Live Set.

        device is an index, a device name, or a path to a device inside racks
        from list_devices, such as "Instrument Rack/Piano/Reverb" or
        "Drum Rack/returns/0/Limiter". value is either a raw number within the
        parameter's min..max, or display text such as "-3 dB", "2.5 kHz",
        "25L", or an option name like "Off".
        """

        return send(
            "set_device_parameter",
            ParameterChange(track=track, device=device, parameter=parameter, value=value),
        )

    @mcp.tool(annotations=_op("set_track_output_routing"))
    def set_track_output_routing(
        track: int | str,
        routing_type: str,
        routing_channel: str | None = None,
    ) -> str:
        """Set a track's Audio To / MIDI To output by its display name, such as
        "Main" or a group track name. list_tracks shows the available names."""

        return send(
            "set_track_output_routing",
            RoutingChange(track=track, routing_type=routing_type, routing_channel=routing_channel),
        )

    @mcp.tool(annotations=_op("set_track_properties"))
    def set_track_properties(
        track: int | str,
        name: str | None = None,
        color: str | None = None,
        color_index: int | None = None,
    ) -> str:
        """Rename and/or recolour a track. color is "#RRGGBB" (Live snaps it to
        the nearest palette colour); color_index picks a palette slot directly."""

        return send(
            "set_track_properties",
            TrackPropertiesChange(track=track, name=name, color=color, color_index=color_index),
        )

    @mcp.tool(annotations=_op("set_mixer"))
    def set_mixer(
        track: int | str,
        volume: float | str | None = None,
        panning: float | str | None = None,
        sends: dict[str, float | str] | None = None,
        mute: bool | None = None,
        solo: bool | None = None,
    ) -> str:
        """Set a track's mixer: volume ("-6 dB" or raw 0..1), panning ("25L",
        "C", or raw -1..1), sends keyed by return name, letter, or index
        ({"A": "-12 dB"}), mute, and solo."""

        return send(
            "set_mixer",
            MixerChange(
                track=track, volume=volume, panning=panning, sends=sends, mute=mute, solo=solo
            ),
        )

    @mcp.tool(annotations=_op("insert_device"))
    def insert_device(
        track: int | str,
        device_name: str,
        index: int | None = None,
        parameters: dict[str, float | str] | None = None,
    ) -> str:
        """Insert a native Live device (for example "Utility", "EQ Eight",
        "Glue Compressor") by its browser name, using Track.insert_device
        (Live 12.3+). index is the chain position; omit it to append at the end.
        parameters are set on the new device right away, e.g. {"Gain": "-3 dB"}."""

        return send(
            "insert_device",
            DeviceInsert(
                track=track, device_name=device_name, index=index, parameters=parameters
            ),
        )

    @mcp.tool(annotations=_op("create_return_track"))
    def create_return_track(name: str | None = None, color: str | None = None) -> str:
        """Add a return track after the existing ones, optionally named and
        coloured ("#RRGGBB"). Additive. Every track gets a send to the new
        return; tell the user to check send levels. Live adds the letter
        itself, so pass "Room" (or "E-Room") for "E-Room"."""

        return send("create_return_track", ReturnTrackCreate(name=name, color=color))

    @mcp.tool(annotations=_op("delete_device"))
    def delete_device(track: int | str, device: int | str, confirm: StrictBool = False) -> str:
        """Delete a device from a track, or from inside a rack by its path
        (see list_devices). Destructive.

        Without confirm=true nothing changes: it returns the device and its
        current settings so you can show the user what would be removed. Only
        pass confirm=true after the user agrees. Live's Undo brings it back."""

        return send("delete_device", DeviceDelete(track=track, device=device, confirm=confirm))

    @mcp.tool(annotations=_op("batch"))
    def apply_batch(operations: list[dict[str, Any]], atomic: StrictBool = True) -> str:
        """Run several changes in one go.

        Each operation is {"method": ..., "params": {...}}. Methods:
        ableton.set_device_parameter, ableton.set_track_output_routing,
        ableton.set_track_properties, ableton.set_mixer, ableton.insert_device,
        ableton.create_return_track, ableton.delete_device (needs "confirm": true).
        params use the same names as the matching tools. The batch stops at the
        first failure and reports what completed.

        With atomic true (default) the whole batch is one Live undo step. With
        atomic false each operation is its own undo step, so the user can undo
        them one at a time (undo_last_change with a count).
        """

        try:
            batch = Batch(operations=parse_batch(operations), atomic=atomic)
        except (TypeError, ValueError) as exc:
            return f"{exc}. Nothing was changed."
        return run("batch", batch, lambda: daw.apply_batch(batch))

    @mcp.tool(annotations=_op("undo"))
    def undo_last_change(count: int = 1, confirm: StrictBool = False) -> str:
        """Run Live's Undo count times (1 to 20, default 1).

        With Remote Script 0.5.0 or later, each tool call that changes the Set
        is meant to be one undo step, and so is a whole apply_batch unless it
        ran with atomic false. That is not exact: Live may split a call (an
        insert_device with parameters can become two steps), a failed call
        that was put back may still leave a step, and the musician's own edits
        in Live share the same history. Live labels every step "Custom
        Action", so it cannot say what each one was.

        So prefer count 1 and check the result with list_tracks or
        list_devices. count above 1 needs confirm=true, after telling the user
        it may also undo their own recent edits. Reports how many steps were
        undone.
        """

        if count < 1 or count > UndoRequest.MAX_COUNT:
            return f"count must be from 1 to {UndoRequest.MAX_COUNT}"
        request = UndoRequest(count=count, confirm=confirm)
        return send("undo", request)

    @mcp.tool(annotations=_op("get_selected_rack_macros"))
    def generate_macro_cockpit(
        track: int | str | None = None,
        device: int | str | None = None,
    ) -> str:
        """Generate a read-only Macro Cockpit for the selected Rack.

        Reads the rack's existing macros (never changes the Live Set) and
        returns a MacroCockpitSpec that groups and labels them, plus a text
        summary to show the user. Unmapped macros are left out. The cockpit is
        temporary. track and device pick a rack explicitly; by default the
        selected track's selected Rack (or its first Rack) is used.
        """

        ref = RackRef(track=track, device=device)
        try:
            rack = policy.run(
                "get_selected_rack_macros", ref, lambda: daw.get_selected_rack_macros(ref)
            )
        except AdapterError as exc:
            return f"Bridge error: {exc}"
        try:
            health: dict[str, Any] | None = dict(daw.health().raw)
        except AdapterError:
            health = None
        try:
            spec = build_macro_cockpit(rack, health)
        except CockpitError as exc:
            return f"Could not build a cockpit from the rack data: {exc}"
        recent_cockpits[spec.id] = spec
        return json.dumps({"text": render_cockpit_text(spec), "cockpit": spec.to_wire()}, indent=2)

    @mcp.tool(annotations=LOCAL_FILE)
    def save_macro_cockpit(cockpit_id: str) -> str:
        """Save a Macro Cockpit generated in this session so it can be reopened later.

        Only call this when the user asks to keep the cockpit; cockpits are
        temporary by default. cockpit_id is the "id" from generate_macro_cockpit.
        Writes a JSON file in the cockpit folder; does not change the Live Set.
        """

        spec = recent_cockpits.get(cockpit_id)
        if spec is None:
            return (
                f"No cockpit {cockpit_id!r} was generated in this session. "
                "Generate it with generate_macro_cockpit, then save it."
            )
        try:
            saved = store.save(spec)
        except (CockpitStoreError, OSError) as exc:
            return f"Could not save the cockpit: {exc}"
        recent_cockpits[cockpit_id] = saved
        return json.dumps(
            {"saved": True, "id": saved.id, "saved_at": saved.saved_at, "folder": str(store.root)},
            indent=2,
        )

    @mcp.tool(annotations=READ_ONLY)
    def list_saved_macro_cockpits() -> str:
        """List saved Macro Cockpits (id, title, track, device, saved time)."""

        return json.dumps({"folder": str(store.root), "cockpits": store.list_saved()}, indent=2)

    @mcp.tool(annotations=_op("get_selected_rack_macros"))
    def open_macro_cockpit(cockpit_id: str, check_rack: bool = True) -> str:
        """Open a saved Macro Cockpit.

        With check_rack, the selected Rack is read (never changed) and compared
        with the rack the cockpit was made from. If they differ, the saved
        cockpit is returned with rack_matches false and a warning: tell the
        user, and offer to generate a fresh cockpit instead.
        """

        try:
            spec = store.load(cockpit_id)
        except CockpitStoreError as exc:
            return f"Could not open the cockpit: {exc}"
        result: dict[str, Any] = {"rack_matches": None, "warnings": []}
        if check_rack:
            try:
                rack = policy.run(
                    "get_selected_rack_macros",
                    RackRef(),
                    lambda: daw.get_selected_rack_macros(RackRef()),
                )
            except AdapterError as exc:
                result["warnings"].append(f"Could not read the selected rack to compare: {exc}")
            else:
                matches = rack_fingerprint(rack) == spec.source.get("fingerprint")
                result["rack_matches"] = matches
                if not matches:
                    device = (rack.get("device") or {}).get("name")
                    result["warnings"].append(
                        f"The selected rack ({device!r}) does not match this cockpit, which was "
                        f"made from {spec.source.get('device_name')!r} on "
                        f"{spec.source.get('track_name')!r}, or its macros changed since. "
                        "Values shown are from when it was saved."
                    )
        recent_cockpits[spec.id] = spec
        text = render_cockpit_text(spec)
        if result["warnings"]:
            text += "\n" + "\n".join(f"Warning: {w}" for w in result["warnings"])
        return json.dumps({"text": text, **result, "cockpit": spec.to_wire()}, indent=2)

    @mcp.tool(annotations=LOCAL_FILE)
    def show_macro_cockpit(cockpit_id: str, open_in_browser: bool = True) -> str:
        """Show a Macro Cockpit as a local web page.

        Works for a cockpit generated in this session or a saved one. Writes a
        self-contained HTML file next to the saved cockpits and, by default,
        opens it in the user's browser. The page only displays values; it does
        not read or change the Live Set.
        """

        spec = recent_cockpits.get(cockpit_id)
        if spec is None:
            try:
                spec = store.load(cockpit_id)
            except CockpitStoreError as exc:
                return f"Could not find the cockpit: {exc}"
        path = store.root / "views" / f"{spec.id}.html"
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            write_text_atomic(path, render_cockpit_html(spec))
        except OSError as exc:
            return f"Could not write the cockpit page: {exc}"
        opened = bool(open_url(path.resolve().as_uri())) if open_in_browser else False
        return json.dumps({"path": str(path), "opened_in_browser": opened}, indent=2)

    @mcp.tool(annotations=READ_ONLY)
    def draft_action_plan(goal: str) -> str:
        """Draft a non-destructive DAW action plan for a musical goal."""

        plan = {
            "goal": goal,
            "agent_name": config.agent_name,
            "target_daw": config.target_daw,
            "capabilities": list(target_profile.capabilities),
            "constraints": list(target_profile.constraints),
            "mode": "dry_run",
            "steps": [
                "Read the current project state before making changes.",
                "Check the target DAW capabilities before selecting tools.",
                "Create new tracks, clips, or patterns rather than overwriting existing material.",
                "Name generated material clearly so the user can inspect it.",
                "Ask for confirmation before destructive edits, exports, or device replacement.",
            ],
        }
        return json.dumps(plan, indent=2)

    return mcp
