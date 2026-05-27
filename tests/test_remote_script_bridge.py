import unittest

import _bootstrap  # noqa: F401

from remote_scripts.Abletonian.bridge_server import (
    AbletonianBridgeControlSurface,
    _live_object,
)


class RemoteScriptBridgeTests(unittest.TestCase):
    def test_health_accepts_application_property(self) -> None:
        class Application:
            def get_major_version(self):
                return 12

            def get_minor_version(self):
                return 4

            def get_bugfix_version(self):
                return 0

        class Surface:
            application = Application()

        health = AbletonianBridgeControlSurface._health(Surface(), {"target_daw": "ableton"})

        self.assertEqual(health["live_version"], "12.4.0")

    def test_live_object_accepts_method_or_property(self) -> None:
        expected = object()

        class MethodSurface:
            def song(self):
                return expected

        class PropertySurface:
            song = expected

        self.assertIs(_live_object(MethodSurface(), "song"), expected)
        self.assertIs(_live_object(PropertySurface(), "song"), expected)


if __name__ == "__main__":
    unittest.main()
