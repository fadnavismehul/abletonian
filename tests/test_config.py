import os
import unittest
from unittest.mock import patch

import _bootstrap  # noqa: F401

from abletonian.config import AbletonianConfig, resolve_config


class ConfigTests(unittest.TestCase):
    def test_defaults_to_abletonian(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            config = AbletonianConfig.from_env()

        self.assertEqual(config.agent_name, "abletonian")
        self.assertEqual(config.target_daw, "ableton")
        self.assertEqual(config.bridge_host, "127.0.0.1")
        self.assertEqual(config.bridge_port, 9877)

    def test_env_agent_name_can_override_default(self) -> None:
        with patch.dict(os.environ, {"ABLETONIAN_AGENT_NAME": "live-room"}, clear=True):
            config = AbletonianConfig.from_env()

        self.assertEqual(config.agent_name, "live-room")

    def test_cli_agent_name_takes_precedence(self) -> None:
        with patch.dict(os.environ, {"ABLETONIAN_AGENT_NAME": "env-name"}, clear=True):
            config = resolve_config(["--agent-name", "cli-name"])

        self.assertEqual(config.agent_name, "cli-name")

    def test_env_target_daw_can_override_default(self) -> None:
        with patch.dict(os.environ, {"ABLETONIAN_TARGET_DAW": "FL Studio"}, clear=True):
            config = AbletonianConfig.from_env()

        self.assertEqual(config.target_daw, "fl-studio")

    def test_cli_target_daw_takes_precedence(self) -> None:
        with patch.dict(os.environ, {"ABLETONIAN_TARGET_DAW": "reaper"}, clear=True):
            config = resolve_config(["--target-daw", "bitwig"])

        self.assertEqual(config.target_daw, "bitwig")

    def test_blank_agent_name_falls_back(self) -> None:
        with patch.dict(os.environ, {"ABLETONIAN_AGENT_NAME": "   "}, clear=True):
            config = AbletonianConfig.from_env()

        self.assertEqual(config.agent_name, "abletonian")


if __name__ == "__main__":
    unittest.main()
