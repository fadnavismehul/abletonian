"""Abletonian Remote Script entrypoint."""

from __future__ import annotations

import importlib

from . import bridge_server, live_ops


def create_instance(c_instance):
    """Create the Abletonian control surface instance for Ableton Live.

    Live caches this package, so the submodules are reloaded here. After
    reinstalling the script, switching the Control Surface to None and back
    to Abletonian picks up the new code without restarting Live.
    """

    importlib.reload(live_ops)
    importlib.reload(bridge_server)
    return bridge_server.AbletonianBridgeControlSurface(c_instance)
