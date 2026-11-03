"""The per-install bridge key and the new port (RFC 0004)."""

import os
import stat
import tempfile
import unittest
from unittest.mock import patch

import _bootstrap  # noqa: F401

from abletonian.bridge.client import DEFAULT_BRIDGE_KEY_PATH
from abletonian.config import DEFAULT_BRIDGE_PORT
from remote_scripts.Abletonian import bridge_server
from remote_scripts.Abletonian.bridge_server import (
    BridgeKey,
    _decode_frame,
    _dispatch_frame,
    _encode_frame,
)


class RecordingSurface:
    """Records whether anything reached Live's main thread."""

    def __init__(self, key):
        self._bridge_key = key
        self.scheduled = 0
        self.handled = []

    def schedule_message(self, delay, callback):
        self.scheduled += 1
        callback()

    def handle_request(self, method, params):
        self.handled.append(method)
        return {"ok": True}


def frame(key=None, method="ableton.set_mixer"):
    message = {"id": "r1", "method": method, "params": {"track": 0, "mute": True}}
    if key is not None:
        message["key"] = key
    return _encode_frame(message)


class KeyFileTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = os.path.join(directory.name, ".abletonian", "bridge_key")

    def test_created_with_private_permissions(self):
        value = BridgeKey(self.path).load_or_create()
        self.assertEqual(len(value), 64)
        with open(self.path, encoding="ascii") as handle:
            self.assertEqual(handle.read().strip(), value)
        if os.name == "posix":
            self.assertEqual(stat.S_IMODE(os.stat(self.path).st_mode), 0o600)
            directory = os.path.dirname(self.path)
            self.assertEqual(stat.S_IMODE(os.stat(directory).st_mode), 0o700)

    def test_existing_key_is_kept(self):
        first = BridgeKey(self.path).load_or_create()
        self.assertEqual(BridgeKey(self.path).load_or_create(), first)

    def test_invalid_file_is_replaced(self):
        os.makedirs(os.path.dirname(self.path))
        with open(self.path, "w", encoding="ascii") as handle:
            handle.write("not a key")
        value = BridgeKey(self.path).load_or_create()
        self.assertNotEqual(value, "not a key")
        self.assertEqual(len(value), 64)

    def test_replaced_file_is_picked_up_without_restart(self):
        key = BridgeKey(self.path)
        old = key.load_or_create()
        new = "f" * 64
        with open(self.path, "w", encoding="ascii") as handle:
            handle.write(new)
        self.assertTrue(key.matches(new))
        self.assertFalse(key.matches(old))

    def test_rejects_empty_and_non_text(self):
        key = BridgeKey(self.path)
        key.load_or_create()
        for bad in (None, "", 123, ["x"], "é" * 64):
            with self.subTest(bad=bad):
                self.assertFalse(key.matches(bad))


@unittest.skipUnless(os.name == "posix", "POSIX permissions")
class PermissionTests(unittest.TestCase):
    """Review of #38: a key others could write must never be trusted."""

    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.folder = os.path.join(directory.name, ".abletonian")
        self.path = os.path.join(self.folder, "bridge_key")

    def test_open_folder_is_tightened(self):
        os.makedirs(self.folder)
        os.chmod(self.folder, 0o777)
        BridgeKey(self.path).load_or_create()
        self.assertEqual(stat.S_IMODE(os.stat(self.folder).st_mode), 0o700)

    def test_key_in_a_world_writable_folder_is_not_trusted(self):
        key = BridgeKey(self.path)
        key.load_or_create()
        planted = "e" * 64
        with open(self.path, "w", encoding="ascii") as handle:
            handle.write(planted)
        os.chmod(self.folder, 0o777)
        self.assertFalse(key.matches(planted))

    def test_key_file_others_can_read_or_write_is_not_trusted(self):
        key = BridgeKey(self.path)
        key.load_or_create()
        planted = "e" * 64
        with open(self.path, "w", encoding="ascii") as handle:
            handle.write(planted)
        os.chmod(self.path, 0o666)
        self.assertFalse(key.matches(planted))

    def test_untrusted_file_is_replaced_on_start(self):
        os.makedirs(self.folder, mode=0o700)
        with open(self.path, "w", encoding="ascii") as handle:
            handle.write("e" * 64)
        os.chmod(self.path, 0o644)
        value = BridgeKey(self.path).load_or_create()
        self.assertNotEqual(value, "e" * 64)
        self.assertEqual(stat.S_IMODE(os.stat(self.path).st_mode), 0o600)

    def test_failed_write_leaves_no_temp_file(self):
        os.makedirs(self.folder, mode=0o700)
        with patch("os.replace", side_effect=PermissionError("in use")):
            with self.assertRaises(PermissionError):
                BridgeKey(self.path).load_or_create()
        self.assertEqual(os.listdir(self.folder), [])


class DispatchKeyTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.key = BridgeKey(os.path.join(directory.name, "bridge_key"))
        self.value = self.key.load_or_create()

    def test_right_key_is_accepted(self):
        surface = RecordingSurface(self.key)
        response = _decode_frame(_dispatch_frame(surface, frame(self.value)))
        self.assertTrue(response["ok"], response)
        self.assertEqual(surface.handled, ["ableton.set_mixer"])

    def test_wrong_or_missing_key_never_reaches_live(self):
        for presented in (None, "", "0" * 64, self.value[:-1]):
            with self.subTest(presented=presented):
                surface = RecordingSurface(self.key)
                response = _decode_frame(_dispatch_frame(surface, frame(presented)))
                self.assertFalse(response["ok"])
                self.assertEqual(response["error"]["code"], "unauthorized")
                self.assertIn("nothing was changed", response["error"]["message"])
                self.assertIn("Control Surface slot", response["error"]["hint"])
                self.assertEqual(surface.scheduled, 0)
                self.assertEqual(surface.handled, [])

    def test_health_needs_the_key_too(self):
        surface = RecordingSurface(self.key)
        response = _decode_frame(_dispatch_frame(surface, frame(None, method="daw.health")))
        self.assertEqual(response["error"]["code"], "unauthorized")

    def test_surface_without_a_key_refuses_everything(self):
        surface = RecordingSurface(None)
        response = _decode_frame(_dispatch_frame(surface, frame(self.value)))
        self.assertEqual(response["error"]["code"], "unauthorized")
        self.assertEqual(surface.scheduled, 0)

    def test_key_is_not_echoed_back(self):
        surface = RecordingSurface(self.key)
        raw = _dispatch_frame(surface, frame("0" * 64)) + _dispatch_frame(
            surface, frame(self.value)
        )
        self.assertNotIn(self.value.encode(), raw)


class SharedConstantsTests(unittest.TestCase):
    def test_both_sides_agree(self):
        self.assertEqual(bridge_server.PORT, DEFAULT_BRIDGE_PORT)
        self.assertEqual(bridge_server.PORT, 39877)
        self.assertEqual(bridge_server.KEY_PATH, DEFAULT_BRIDGE_KEY_PATH)
        from abletonian.bridge.protocol import PROTOCOL_VERSION

        self.assertEqual(bridge_server.PROTOCOL_VERSION, PROTOCOL_VERSION)


if __name__ == "__main__":
    unittest.main()
