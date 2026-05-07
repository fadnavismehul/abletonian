"""Command line entry point for abletonian."""

from __future__ import annotations

from abletonian.config import resolve_config
from abletonian.server import build_mcp


def main(argv: list[str] | None = None) -> None:
    """Run the MCP server."""

    config = resolve_config(argv)
    build_mcp(config).run()


if __name__ == "__main__":
    main()
