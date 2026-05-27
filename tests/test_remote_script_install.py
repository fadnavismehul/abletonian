import pathlib
import tempfile
import unittest

import _bootstrap  # noqa: F401

from scripts.install_remote_script import install_remote_script


class RemoteScriptInstallTests(unittest.TestCase):
    def test_installs_abletonian_remote_script_package(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target_root = pathlib.Path(tmp) / "User Library" / "Remote Scripts"

            installed = install_remote_script(target_root=target_root)

            self.assertEqual(installed, target_root / "Abletonian")
            self.assertTrue((installed / "__init__.py").exists())
            self.assertTrue((installed / "bridge_server.py").exists())
            self.assertFalse((installed / "__pycache__").exists())

    def test_replaces_existing_installation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target_root = pathlib.Path(tmp) / "Remote Scripts"
            old_file = target_root / "Abletonian" / "old.py"
            old_file.parent.mkdir(parents=True)
            old_file.write_text("old", encoding="utf-8")

            installed = install_remote_script(target_root=target_root)

            self.assertEqual(installed, target_root / "Abletonian")
            self.assertFalse(old_file.exists())


if __name__ == "__main__":
    unittest.main()
