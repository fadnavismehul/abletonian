"""Install the Abletonian Remote Script into Ableton's User Library."""

from __future__ import annotations

import argparse
import pathlib
import shutil

REMOTE_SCRIPT_NAME = "Abletonian"
PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]
REMOTE_SCRIPT_SOURCE = PROJECT_ROOT / "remote_scripts" / REMOTE_SCRIPT_NAME
DEFAULT_TARGET_ROOT = (
    pathlib.Path.home() / "Music" / "Ableton" / "User Library" / "Remote Scripts"
)


def install_remote_script(
    target_root: pathlib.Path = DEFAULT_TARGET_ROOT,
    source: pathlib.Path = REMOTE_SCRIPT_SOURCE,
) -> pathlib.Path:
    """Copy the Abletonian Remote Script package into a Remote Scripts folder."""

    if not source.exists():
        raise FileNotFoundError(f"remote script source does not exist: {source}")

    destination = target_root / REMOTE_SCRIPT_NAME
    if destination.exists():
        shutil.rmtree(destination)
    target_root.mkdir(parents=True, exist_ok=True)
    shutil.copytree(
        source,
        destination,
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
    )
    return destination


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Install the Abletonian Remote Script for Ableton Live.",
    )
    parser.add_argument(
        "--target-root",
        type=pathlib.Path,
        default=DEFAULT_TARGET_ROOT,
        help=f"Remote Scripts folder. Defaults to {DEFAULT_TARGET_ROOT}.",
    )
    args = parser.parse_args()
    installed = install_remote_script(target_root=args.target_root)
    print(installed)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
