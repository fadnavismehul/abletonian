import asyncio
import json
import os
import pathlib
import tempfile
import unittest
from unittest.mock import patch

import _bootstrap  # noqa: F401

from abletonian.adapters.fake import (
    FakeAbletonAdapter,
    FakeAbletonState,
    FakeRackDevice,
    FakeRackMacro,
    FakeTrack,
)
from abletonian.cockpit import generate_macro_cockpit
from abletonian.cockpit_store import CockpitStore, CockpitStoreError
from abletonian.config import AbletonianConfig, default_cockpit_dir, resolve_config
from abletonian.server import build_mcp

MACROS = (FakeRackMacro(1, "Cutoff", 100.0), FakeRackMacro(2, "Drive", 20.0))


def adapter(macros=MACROS, rack_name="Keys Rack") -> FakeAbletonAdapter:
    return FakeAbletonAdapter(
        FakeAbletonState(
            live_version="12.4.16",
            tracks=(
                FakeTrack(id="t0", name="Keys", devices=(FakeRackDevice("r", rack_name, macros),)),
            ),
            selected_track_id="t0",
        )
    )


def spec_from(fake: FakeAbletonAdapter):
    return generate_macro_cockpit(
        fake.handle_request("ableton.get_selected_rack_macros"),
        fake.handle_request("daw.health"),
        created_at="2026-11-01T00:00:00+00:00",
    )


class SwitchableBridge:
    """Bridge whose fake adapter (the open Live Set) can be swapped mid-test."""

    def __init__(self, fake: FakeAbletonAdapter) -> None:
        self.fake = fake

    def request(self, method, params=None):
        return self.fake.handle_request(method, params)


class CockpitStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = pathlib.Path(self.tmp.name) / "cockpits"
        self.store = CockpitStore(self.root)
        self.spec = spec_from(adapter())

    def test_save_writes_readable_json_and_loads_it_back(self) -> None:
        saved = self.store.save(self.spec, saved_at="2026-11-02T10:00:00+00:00")

        path = self.root / f"{self.spec.id}.json"
        on_disk = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(on_disk["mode"], "saved")
        self.assertEqual(on_disk["saved_at"], "2026-11-02T10:00:00+00:00")
        self.assertEqual(self.store.load(self.spec.id), saved)
        self.assertEqual(self.spec.mode, "temporary")  # the original is untouched
        self.assertEqual([p.name for p in self.root.iterdir()], [path.name])  # no temp files left

    def test_list_summarises_newest_first_and_reports_bad_files(self) -> None:
        other = spec_from(adapter(rack_name="Bass Rack"))
        self.store.save(self.spec, saved_at="2026-11-01T10:00:00+00:00")
        self.store.save(other, saved_at="2026-11-02T10:00:00+00:00")
        (self.root / "broken.json").write_text("{not json", encoding="utf-8")

        entries = self.store.list_saved()

        good = [e for e in entries if "id" in e]
        self.assertEqual(
            [e["title"] for e in good], ["Bass Rack Macro Cockpit", "Keys Rack Macro Cockpit"]
        )
        self.assertEqual(good[1]["control_count"], 2)
        self.assertEqual([e["file"] for e in entries if "error" in e], ["broken.json"])

    def test_list_is_empty_when_folder_does_not_exist(self) -> None:
        self.assertEqual(self.store.list_saved(), [])

    def test_rejects_corrupt_and_hand_edited_files(self) -> None:
        self.store.save(self.spec)
        path = self.root / f"{self.spec.id}.json"
        wire = json.loads(path.read_text(encoding="utf-8"))
        wire["groups"][0]["controls"].append("macro-9")
        path.write_text(json.dumps(wire), encoding="utf-8")

        with self.assertRaisesRegex(CockpitStoreError, "not a valid cockpit"):
            self.store.load(self.spec.id)

    def test_never_overwrites_a_file_holding_another_cockpit(self) -> None:
        self.root.mkdir(parents=True)
        other = json.loads(json.dumps(self.spec.to_wire()))
        other["id"] = "macro-cockpit-someone-else"
        (self.root / f"{self.spec.id}.json").write_text(json.dumps(other), encoding="utf-8")

        with self.assertRaisesRegex(CockpitStoreError, "not overwriting"):
            self.store.save(self.spec)

    def test_ids_cannot_escape_the_folder(self) -> None:
        for bad in ("../secrets", "a/b", "", "UPPER", ".hidden"):
            with (
                self.subTest(bad=bad),
                self.assertRaisesRegex(CockpitStoreError, "invalid cockpit id"),
            ):
                self.store.load(bad)

    def test_missing_cockpit_is_a_clear_error(self) -> None:
        with self.assertRaisesRegex(CockpitStoreError, "no saved cockpit"):
            self.store.load("macro-cockpit-nope")


class CockpitDirConfigTests(unittest.TestCase):
    def test_env_and_cli_override_the_default(self) -> None:
        with patch.dict(os.environ, {"ABLETONIAN_COCKPIT_DIR": "/tmp/env-cockpits"}, clear=True):
            self.assertEqual(
                AbletonianConfig.from_env().resolved_cockpit_dir, pathlib.Path("/tmp/env-cockpits")
            )
            config = resolve_config(["--cockpit-dir", "/tmp/cli-cockpits"])
        self.assertEqual(config.resolved_cockpit_dir, pathlib.Path("/tmp/cli-cockpits"))

    def test_default_is_a_per_user_folder(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(AbletonianConfig().resolved_cockpit_dir, default_cockpit_dir())
        self.assertEqual(default_cockpit_dir().parts[-2:], ("abletonian", "cockpits"))


class CockpitToolTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = CockpitStore(pathlib.Path(self.tmp.name))
        self.bridge = SwitchableBridge(adapter())
        self.mcp = build_mcp(AbletonianConfig(), bridge=self.bridge, cockpit_store=self.store)

    def call(self, tool, **args):
        result = asyncio.run(self.mcp.call_tool(tool, args))
        text = result.content[0].text
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return text

    def test_generate_save_list_and_open_with_matching_rack(self) -> None:
        cockpit_id = self.call("generate_macro_cockpit")["cockpit"]["id"]

        saved = self.call("save_macro_cockpit", cockpit_id=cockpit_id)
        listed = self.call("list_saved_macro_cockpits")
        opened = self.call("open_macro_cockpit", cockpit_id=cockpit_id)

        self.assertTrue(saved["saved"])
        self.assertEqual([c["id"] for c in listed["cockpits"]], [cockpit_id])
        self.assertTrue(opened["rack_matches"])
        self.assertEqual(opened["warnings"], [])
        self.assertEqual(opened["cockpit"]["mode"], "saved")
        self.assertIn("saved 20", opened["text"])

    def test_open_warns_when_the_rack_changed(self) -> None:
        cockpit_id = self.call("generate_macro_cockpit")["cockpit"]["id"]
        self.call("save_macro_cockpit", cockpit_id=cockpit_id)
        self.bridge.fake = adapter(macros=(FakeRackMacro(1, "Cutoff"), FakeRackMacro(2, "Wobble")))

        opened = self.call("open_macro_cockpit", cockpit_id=cockpit_id)

        self.assertFalse(opened["rack_matches"])
        self.assertIn("does not match this cockpit", opened["warnings"][0])
        self.assertIn("Warning:", opened["text"])
        # The saved cockpit is returned as saved, not merged with the new rack.
        self.assertEqual(opened["cockpit"]["controls"][1]["source_name"], "Drive")

    def test_save_requires_a_cockpit_generated_this_session(self) -> None:
        self.assertIn("No cockpit", self.call("save_macro_cockpit", cockpit_id="macro-cockpit-x"))
        self.assertEqual(list(pathlib.Path(self.tmp.name).iterdir()), [])

    def test_open_reports_unknown_ids(self) -> None:
        self.assertIn(
            "Could not open", self.call("open_macro_cockpit", cockpit_id="macro-cockpit-x")
        )


if __name__ == "__main__":
    unittest.main()
