import asyncio
import json
import pathlib
import tempfile
import unittest
from html.parser import HTMLParser

import _bootstrap  # noqa: F401

from abletonian.adapters.fake import (
    FakeAbletonAdapter,
    FakeAbletonState,
    FakeRackDevice,
    FakeRackMacro,
    FakeTrack,
)
from abletonian.cockpit import MacroCockpitSpec, generate_macro_cockpit
from abletonian.cockpit_html import render_cockpit_html
from abletonian.cockpit_store import CockpitStore
from abletonian.config import AbletonianConfig
from abletonian.server import build_mcp

HOSTILE = '</script><script>alert("x")</script><img src=x onerror=alert(1)>'


def spec_for(*macros, track="Keys", rack="Keys Rack") -> MacroCockpitSpec:
    fake = FakeAbletonAdapter(
        FakeAbletonState(
            live_version="12.4.16",
            tracks=(FakeTrack(id="t", name=track, devices=(FakeRackDevice("r", rack, macros),)),),
            selected_track_id="t",
        )
    )
    return generate_macro_cockpit(
        fake.handle_request("ableton.get_selected_rack_macros"),
        fake.handle_request("daw.health"),
        created_at="2026-11-01T00:00:00+00:00",
    )


class Page(HTMLParser):
    """Collects the structure the tests assert on."""

    def __init__(self, html: str) -> None:
        super().__init__()
        self.tags: list[tuple[str, dict[str, str | None]]] = []
        self.scripts: list[tuple[dict[str, str | None], str]] = []
        self.text: list[str] = []
        self._script_attrs: dict[str, str | None] | None = None
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        self.tags.append((tag, dict(attrs)))
        if tag == "script":
            self._script_attrs = dict(attrs)

    def handle_endtag(self, tag):
        if tag == "script":
            self._script_attrs = None

    def handle_data(self, data):
        if self._script_attrs is not None:
            self.scripts.append((self._script_attrs, data))
        else:
            self.text.append(data)

    def attrs_with(self, name: str) -> list[str | None]:
        return [attrs[name] for _tag, attrs in self.tags if name in attrs]


class CockpitHtmlTests(unittest.TestCase):
    def test_renders_groups_controls_and_state(self) -> None:
        spec = spec_for(
            FakeRackMacro(1, "Cutoff", 63.5),
            FakeRackMacro(2, "Reverb", 0.0),
            FakeRackMacro(3, "Macro 3", 127.0),
        )

        page = Page(render_cockpit_html(spec))

        self.assertEqual(page.attrs_with("data-group"), ["tone", "space", "inspect"])
        self.assertEqual(page.attrs_with("data-control"), ["macro-1", "macro-2", "macro-3"])
        self.assertEqual(page.attrs_with("data-connection"), ["simulated"])
        self.assertEqual(page.attrs_with("data-mode"), ["temporary"])
        meters = [attrs for tag, attrs in page.tags if attrs.get("role") == "meter"]
        self.assertEqual(meters[0]["aria-valuenow"], "63.5")
        self.assertEqual(meters[0]["aria-label"], "Cutoff")
        self.assertIn("width: 50.0%", page.attrs_with("style"))
        text = " ".join(page.text)
        self.assertIn("Temporary (not saved)", text)
        self.assertIn("Track Keys", text)

    def test_page_runs_no_scripts_and_loads_nothing_remote(self) -> None:
        html = render_cockpit_html(spec_for(FakeRackMacro(1, "Cutoff")))
        page = Page(html)

        self.assertEqual([attrs.get("type") for attrs, _ in page.scripts], ["application/json"])
        self.assertIn("default-src 'none'", html)
        self.assertNotIn("http://", html.replace("http-equiv", ""))
        self.assertNotIn("https://", html)

    def test_names_from_the_live_set_are_escaped(self) -> None:
        spec = spec_for(FakeRackMacro(1, HOSTILE), track=HOSTILE, rack=HOSTILE)

        html = render_cockpit_html(spec)
        page = Page(html)

        self.assertNotIn("<img", html)
        self.assertNotIn("<script>alert", html)
        executable = [attrs for attrs, _ in page.scripts if attrs.get("type") != "application/json"]
        self.assertEqual(executable, [])
        self.assertIn(HOSTILE, " ".join(page.text))  # shown as text, not markup

    def test_embedded_spec_round_trips(self) -> None:
        spec = spec_for(FakeRackMacro(1, HOSTILE), FakeRackMacro(2, "Drive", 10.0))

        page = Page(render_cockpit_html(spec))
        (embedded,) = [data for attrs, data in page.scripts if attrs.get("id") == "cockpit-spec"]

        self.assertEqual(MacroCockpitSpec.from_wire(json.loads(embedded)), spec)

    def test_empty_cockpit_and_unmapped_macros(self) -> None:
        spec = spec_for(FakeRackMacro(1, "Macro 1", is_mapped=False))

        text = " ".join(Page(render_cockpit_html(spec)).text)

        self.assertIn("This cockpit has no controls.", text)
        self.assertIn("Left out (unmapped): 1 Macro 1", text)
        self.assertIn("no mapped macros", text)


class ShowMacroCockpitToolTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = CockpitStore(pathlib.Path(self.tmp.name))
        self.opened: list[str] = []
        fake = FakeAbletonAdapter(
            FakeAbletonState(
                live_version="12.4.16",
                tracks=(
                    FakeTrack(
                        id="t",
                        name="Keys",
                        devices=(FakeRackDevice("r", "Keys Rack", (FakeRackMacro(1, "Cutoff"),)),),
                    ),
                ),
                selected_track_id="t",
            )
        )
        bridge = type(
            "Bridge", (), {"request": lambda _self, m, p=None: fake.handle_request(m, p)}
        )()
        self.mcp = build_mcp(
            AbletonianConfig(),
            bridge=bridge,
            cockpit_store=self.store,
            open_url=lambda url: self.opened.append(url) or True,
        )

    def call(self, tool, **args):
        text = asyncio.run(self.mcp.call_tool(tool, args)).content[0].text
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return text

    def test_writes_the_page_and_opens_it(self) -> None:
        cockpit_id = self.call("generate_macro_cockpit")["cockpit"]["id"]

        result = self.call("show_macro_cockpit", cockpit_id=cockpit_id)

        path = pathlib.Path(result["path"])
        self.assertEqual(path.parent, pathlib.Path(self.tmp.name) / "views")
        self.assertIn("Keys Rack Macro Cockpit", path.read_text(encoding="utf-8"))
        self.assertTrue(result["opened_in_browser"])
        self.assertEqual(self.opened, [path.resolve().as_uri()])
        self.assertEqual(self.store.list_saved(), [])  # showing is not saving

    def test_can_skip_the_browser_and_show_saved_cockpits(self) -> None:
        cockpit_id = self.call("generate_macro_cockpit")["cockpit"]["id"]
        self.call("save_macro_cockpit", cockpit_id=cockpit_id)
        fresh = build_mcp(AbletonianConfig(), cockpit_store=self.store, open_url=self.opened.append)

        text = (
            asyncio.run(
                fresh.call_tool(
                    "show_macro_cockpit", {"cockpit_id": cockpit_id, "open_in_browser": False}
                )
            )
            .content[0]
            .text
        )

        self.assertFalse(json.loads(text)["opened_in_browser"])
        self.assertEqual(self.opened, [])

    def test_unknown_cockpit(self) -> None:
        self.assertIn(
            "Could not find", self.call("show_macro_cockpit", cockpit_id="macro-cockpit-x")
        )


if __name__ == "__main__":
    unittest.main()
