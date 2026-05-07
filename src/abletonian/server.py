"""MCP server construction for abletonian."""

from __future__ import annotations

import json
from typing import Any

from mcp.server.fastmcp import FastMCP

from abletonian.bridge.client import BridgeClient, BridgeConnectionError
from abletonian.config import AbletonianConfig
from abletonian.daws import get_daw_profile, list_daw_profiles


def build_mcp(config: AbletonianConfig) -> FastMCP:
    """Build an MCP server named after the configured agent."""

    mcp = FastMCP(config.agent_name)
    bridge = BridgeClient(
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
            result = bridge.request("daw.health", {"target_daw": config.target_daw})
        except BridgeConnectionError as exc:
            return f"Bridge unavailable: {exc}"
        return json.dumps(result, indent=2)

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
