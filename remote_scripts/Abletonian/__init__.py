"""Abletonian read-only Remote Script entrypoint."""

from __future__ import annotations

from .bridge_server import AbletonianBridgeControlSurface


def create_instance(c_instance):
    """Create the Abletonian control surface instance for Ableton Live."""

    return AbletonianBridgeControlSurface(c_instance)
