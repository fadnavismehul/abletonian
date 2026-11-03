"""Call one abletonian bridge method and print the JSON result.

Usage: .venv/bin/python .claude/skills/drive-live-on-mac/scripts/bridge.py METHOD ['{"json":"params"}']
Prints "ERROR: <type> <message>" and exits 1 when Live refuses or is unreachable.
"""

import json
import sys

from abletonian.bridge.client import BridgeClient


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    params = json.loads(sys.argv[2]) if len(sys.argv) > 2 else {}
    client = BridgeClient("127.0.0.1", 9877, 30)
    try:
        result = client.request(sys.argv[1], params)
    except Exception as exc:  # report and stop; never retry a mutation blindly
        print(f"ERROR: {type(exc).__name__} {exc}")
        return 1
    print(json.dumps(result, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
