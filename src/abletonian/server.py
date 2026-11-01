"""MCP server construction for abletonian."""

from __future__ import annotations

import json
from typing import Any

from mcp.server.fastmcp import FastMCP

from abletonian.bridge.client import BridgeClient, BridgeConnectionError
from abletonian.cockpit import CockpitError, render_cockpit_text
from abletonian.cockpit import generate_macro_cockpit as build_macro_cockpit
from abletonian.config import AbletonianConfig
from abletonian.daws import get_daw_profile, list_daw_profiles
from abletonian.manual import list_manual_editions, lookup_manual, search_manual


def build_mcp(config: AbletonianConfig, bridge: BridgeClient | None = None) -> FastMCP:
    """Build an MCP server named after the configured agent."""

    mcp = FastMCP(config.agent_name)
    bridge_client = bridge or BridgeClient(
        host=config.bridge_host,
        port=config.bridge_port,
        timeout=config.bridge_timeout,
    )
    target_profile = get_daw_profile(config.target_daw)

    @mcp.tool()
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

    @mcp.tool()
    def list_supported_daws() -> str:
        """List DAW targets known by abletonian and their adapter strategies."""

        return json.dumps([profile.to_wire() for profile in list_daw_profiles()], indent=2)

    @mcp.tool()
    def get_target_daw_profile() -> str:
        """Return the configured target DAW profile."""

        return json.dumps(target_profile.to_wire(), indent=2)

    @mcp.tool()
    def check_bridge_health() -> str:
        """Check whether the configured DAW bridge responds."""

        try:
            result = bridge_client.request("daw.health", {"target_daw": config.target_daw})
        except BridgeConnectionError as exc:
            return f"Bridge unavailable: {exc}"
        return json.dumps(result, indent=2)

    @mcp.tool()
    def lookup_ableton_manual(query: str, live_version: str = "12") -> str:
        """Return cited Ableton manual context for an indexed workflow query."""

        return json.dumps(lookup_manual(query, live_version), indent=2)

    @mcp.tool()
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

    @mcp.tool()
    def list_ableton_manual_editions() -> str:
        """List the Ableton manual editions fetched into this checkout."""

        return json.dumps(list_manual_editions(), indent=2)

    @mcp.tool()
    def plan_drum_rack_extraction() -> str:
        """Return a dry-run Drum Rack extraction plan from the configured bridge."""

        try:
            result = bridge_client.request(
                "workflow.plan_drum_rack_extraction",
                {"target_daw": config.target_daw},
            )
        except BridgeConnectionError as exc:
            return f"Bridge unavailable: {exc}"
        return json.dumps(result, indent=2)

    @mcp.tool()
    def execute_drum_rack_extraction(confirm: bool = False) -> str:
        """Execute Drum Rack extraction after explicit confirmation."""

        if confirm is not True:
            return "workflow.execute_drum_rack_extraction requires confirm=true"
        try:
            result = bridge_client.request(
                "workflow.execute_drum_rack_extraction",
                {"target_daw": config.target_daw, "confirm": True},
            )
        except BridgeConnectionError as exc:
            return f"Bridge unavailable: {exc}"
        return json.dumps(result, indent=2)

    def live_request(method: str, params: dict[str, Any]) -> str:
        try:
            result = bridge_client.request(method, params)
        except BridgeConnectionError as exc:
            return f"Bridge error: {exc}"
        return json.dumps(result, indent=2)

    def without_none(**params: Any) -> dict[str, Any]:
        return {key: value for key, value in params.items() if value is not None}

    @mcp.tool()
    def list_tracks(include_returns: bool = True, include_master: bool = True) -> str:
        """List tracks in the open Live Set: names, groups, colours, output routing,
        volume, pan, sends, mute/solo, and device names.

        Track references used by other tools accept an index into this list's
        regular tracks, a track name, "A"/"B"/... or "return:N" for returns, and
        "main" for the main track.
        """

        return live_request(
            "ableton.list_tracks",
            {"include_returns": include_returns, "include_master": include_master},
        )

    @mcp.tool()
    def list_devices(track: int | str | None = None, include_parameters: bool = True) -> str:
        """List devices on one track (or every track when track is omitted), with
        each parameter's raw value, range, display text, and options."""

        return live_request(
            "ableton.list_devices",
            without_none(track=track, include_parameters=include_parameters),
        )

    @mcp.tool()
    def set_device_parameter(
        track: int | str,
        device: int | str,
        parameter: int | str,
        value: float | str,
    ) -> str:
        """Set a device parameter in the open Live Set.

        value is either a raw number within the parameter's min..max, or display
        text such as "-3 dB", "2.5 kHz", "25L", or an option name like "Off".
        """

        return live_request(
            "ableton.set_device_parameter",
            {"track": track, "device": device, "parameter": parameter, "value": value},
        )

    @mcp.tool()
    def set_track_output_routing(
        track: int | str,
        routing_type: str,
        routing_channel: str | None = None,
    ) -> str:
        """Set a track's Audio To / MIDI To output by its display name, such as
        "Main" or a group track name. list_tracks shows the available names."""

        return live_request(
            "ableton.set_track_output_routing",
            without_none(track=track, routing_type=routing_type, routing_channel=routing_channel),
        )

    @mcp.tool()
    def set_track_properties(
        track: int | str,
        name: str | None = None,
        color: str | None = None,
        color_index: int | None = None,
    ) -> str:
        """Rename and/or recolour a track. color is "#RRGGBB" (Live snaps it to
        the nearest palette colour); color_index picks a palette slot directly."""

        return live_request(
            "ableton.set_track_properties",
            without_none(track=track, name=name, color=color, color_index=color_index),
        )

    @mcp.tool()
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

        return live_request(
            "ableton.set_mixer",
            without_none(
                track=track, volume=volume, panning=panning, sends=sends, mute=mute, solo=solo
            ),
        )

    @mcp.tool()
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

        return live_request(
            "ableton.insert_device",
            without_none(
                track=track, device_name=device_name, index=index, parameters=parameters
            ),
        )

    @mcp.tool()
    def apply_batch(operations: list[dict[str, Any]]) -> str:
        """Run several changes in one go, as a single Live undo step.

        Each operation is {"method": ..., "params": {...}}. Methods:
        ableton.set_device_parameter, ableton.set_track_output_routing,
        ableton.set_track_properties, ableton.set_mixer, ableton.insert_device.
        params use the same names as the matching tools. The batch stops at the
        first failure and reports what completed.
        """

        return live_request("ableton.batch", {"operations": operations})

    @mcp.tool()
    def undo_last_change() -> str:
        """Run Live's Undo once. A whole apply_batch counts as one step."""

        return live_request("ableton.undo", {})

    @mcp.tool()
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

        try:
            rack = bridge_client.request(
                "ableton.get_selected_rack_macros", without_none(track=track, device=device)
            )
        except BridgeConnectionError as exc:
            return f"Bridge error: {exc}"
        try:
            health = bridge_client.request("daw.health", {"target_daw": config.target_daw})
        except BridgeConnectionError:
            health = None
        try:
            spec = build_macro_cockpit(rack, health)
        except CockpitError as exc:
            return f"Could not build a cockpit from the rack data: {exc}"
        return json.dumps({"text": render_cockpit_text(spec), "cockpit": spec.to_wire()}, indent=2)

    @mcp.tool()
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
