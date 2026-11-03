"""Call one abletonian bridge method and print the JSON result.

Usage, from the repo root:
    .venv/bin/python .claude/skills/drive-live-on-mac/scripts/bridge.py \
        METHOD ['{"json":"params"}']
Prints "ERROR: <type> <message>" and exits 1 when Live refuses or is unreachable.
It reads the bridge key from ~/.abletonian/bridge_key itself; never print that file.
"""

import json
import sys

from abletonian.bridge.client import BridgeClient
from abletonian.config import AbletonianConfig


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    params = json.loads(sys.argv[2]) if len(sys.argv) > 2 else {}
    # Same host, port (39877 since RFC 0004) and key file as the MCP server.
    config = AbletonianConfig.from_env()
    client = BridgeClient(config.bridge_host, config.bridge_port, config.bridge_timeout)
    try:
        result = client.request(sys.argv[1], params)
    except Exception as exc:  # report and stop; never retry a mutation blindly
        print(f"ERROR: {type(exc).__name__} {exc}")
        return 1
    print(json.dumps(result, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
