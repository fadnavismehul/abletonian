"""Runtime configuration for abletonian."""

from __future__ import annotations

import argparse
import os
import pathlib
import sys
from dataclasses import dataclass

from abletonian.daws import DEFAULT_TARGET_DAW, SUPPORTED_DAW_SLUGS, normalize_daw_slug

DEFAULT_AGENT_NAME = "abletonian"
DEFAULT_BRIDGE_HOST = "127.0.0.1"
# Must match PORT in remote_scripts/Abletonian/bridge_server.py (RFC 0004).
DEFAULT_BRIDGE_PORT = 39877
# Longer than the Remote Script start + run limits (5 s + 25 s).
DEFAULT_BRIDGE_TIMEOUT = 35.0


@dataclass(frozen=True)
class AbletonianConfig:
    """Configuration shared by the CLI, MCP server, and DAW bridge."""

    agent_name: str = DEFAULT_AGENT_NAME
    target_daw: str = DEFAULT_TARGET_DAW
    bridge_host: str = DEFAULT_BRIDGE_HOST
    bridge_port: int = DEFAULT_BRIDGE_PORT
    bridge_timeout: float = DEFAULT_BRIDGE_TIMEOUT
    # Where explicitly saved Macro Cockpits are stored. None means
    # default_cockpit_dir().
    cockpit_dir: pathlib.Path | None = None

    @property
    def resolved_cockpit_dir(self) -> pathlib.Path:
        return self.cockpit_dir or default_cockpit_dir()

    @classmethod
    def from_env(cls) -> AbletonianConfig:
        """Build config from environment variables."""

        return cls(
            agent_name=_clean_name(os.getenv("ABLETONIAN_AGENT_NAME"), DEFAULT_AGENT_NAME),
            target_daw=_parse_target_daw(os.getenv("ABLETONIAN_TARGET_DAW")),
            bridge_host=os.getenv("ABLETONIAN_BRIDGE_HOST", DEFAULT_BRIDGE_HOST),
            bridge_port=_parse_int(os.getenv("ABLETONIAN_BRIDGE_PORT"), DEFAULT_BRIDGE_PORT),
            bridge_timeout=_parse_float(
                os.getenv("ABLETONIAN_BRIDGE_TIMEOUT"), DEFAULT_BRIDGE_TIMEOUT
            ),
            cockpit_dir=_parse_path(os.getenv("ABLETONIAN_COCKPIT_DIR")),
        )

    def with_args(self, args: argparse.Namespace) -> AbletonianConfig:
        """Return a copy with CLI argument overrides applied."""

        return AbletonianConfig(
            agent_name=_clean_name(args.agent_name, self.agent_name),
            target_daw=(
                normalize_daw_slug(args.target_daw)
                if args.target_daw is not None
                else self.target_daw
            ),
            bridge_host=args.bridge_host or self.bridge_host,
            bridge_port=args.bridge_port if args.bridge_port is not None else self.bridge_port,
            bridge_timeout=(
                args.bridge_timeout
                if args.bridge_timeout is not None
                else self.bridge_timeout
            ),
            cockpit_dir=_parse_path(args.cockpit_dir) or self.cockpit_dir,
        )


def build_parser() -> argparse.ArgumentParser:
    """Create the abletonian CLI parser."""

    parser = argparse.ArgumentParser(
        prog="abletonian",
        description="Run the abletonian DAW MCP server.",
    )
    parser.add_argument(
        "--agent-name",
        help="MCP server and agent name exposed to clients. Defaults to abletonian.",
    )
    parser.add_argument(
        "--target-daw",
        choices=SUPPORTED_DAW_SLUGS,
        help=f"DAW adapter target. Defaults to {DEFAULT_TARGET_DAW}.",
    )
    parser.add_argument(
        "--bridge-host",
        help=f"DAW bridge host. Defaults to {DEFAULT_BRIDGE_HOST}.",
    )
    parser.add_argument(
        "--bridge-port",
        type=int,
        help=f"DAW bridge port. Defaults to {DEFAULT_BRIDGE_PORT}.",
    )
    parser.add_argument(
        "--bridge-timeout",
        type=float,
        help=f"DAW bridge timeout in seconds. Defaults to {DEFAULT_BRIDGE_TIMEOUT}.",
    )
    parser.add_argument(
        "--cockpit-dir",
        help="Folder for saved Macro Cockpits. Defaults to a per-user data folder.",
    )
    return parser


def default_cockpit_dir() -> pathlib.Path:
    """Per-user folder for saved cockpits, following each platform's convention."""

    home = pathlib.Path.home()
    if sys.platform == "darwin":
        base = home / "Library" / "Application Support"
    elif sys.platform == "win32":
        base = pathlib.Path(os.getenv("APPDATA") or home / "AppData" / "Roaming")
    else:
        base = pathlib.Path(os.getenv("XDG_DATA_HOME") or home / ".local" / "share")
    return base / "abletonian" / "cockpits"


def resolve_config(argv: list[str] | None = None) -> AbletonianConfig:
    """Resolve configuration from environment variables and CLI arguments."""

    parser = build_parser()
    args = parser.parse_args(argv)
    return AbletonianConfig.from_env().with_args(args)


def _clean_name(value: str | None, default: str) -> str:
    if value is None:
        return default

    stripped = value.strip()
    return stripped or default


def _parse_target_daw(value: str | None) -> str:
    if value is None or value.strip() == "":
        return DEFAULT_TARGET_DAW
    return normalize_daw_slug(value)


def _parse_int(value: str | None, default: int) -> int:
    if value is None or value.strip() == "":
        return default
    return int(value)


def _parse_path(value: str | None) -> pathlib.Path | None:
    if value is None or value.strip() == "":
        return None
    return pathlib.Path(value.strip()).expanduser()


def _parse_float(value: str | None, default: float) -> float:
    if value is None or value.strip() == "":
        return default
    return float(value)
