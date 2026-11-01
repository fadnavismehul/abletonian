import json
import tempfile
import unittest
from pathlib import Path

import _bootstrap  # noqa: F401

from abletonian.manual import list_manual_editions, lookup_manual, search_manual
from scripts.fetch_manual import chapter_markdown, chapter_slugs, edition_from_index

CHAPTER_HTML = """
<nav><h1>Not the manual</h1></nav>
<div id="chapter_content"><h1 id="routing-and-io"><span>17.</span> Routing and I/O</h1>
<p>Most routing happens in the mixer's <em>track In/Out section</em>.</p>
<figure><img alt=""><figcaption>The In/Out Section.</figcaption></figure>
<h2 id="tracks-output">17.1 Track Output</h2>
<p>Set Audio To to <strong>Main</strong> using <kbd>Ctrl</kbd><kbd>I</kbd>.</p>
<ul><li>Main sends to the main track.</li><li>Group tracks collect signals.</li></ul>
<div class="note"><p>Nested note.</p></div>
</div><footer><p>Footer text</p></footer>
"""


class ManualLookupTests(unittest.TestCase):
    def test_returns_cited_drum_rack_extraction_result(self) -> None:
        result = lookup_manual("extract drum rack chains into individual tracks", live_version="12")

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["topic"], "drum_rack_extraction")
        self.assertEqual(result["live_version"], "12")
        self.assertIn("extracting chains", result["summary"].lower())
        self.assertEqual(result["automation"]["abletonian_operation"], "split_drum_rack")
        self.assertTrue(result["automation"]["requires_dry_run"])
        self.assertGreaterEqual(len(result["citations"]), 1)
        self.assertIn("ableton.com", result["citations"][0]["url"])

    def test_returns_no_source_for_unknown_query(self) -> None:
        with tempfile.TemporaryDirectory() as empty:
            result = lookup_manual(
                "does this synth have a secret unicorn mode?",
                live_version="12",
                manual_root=Path(empty),
            )

        self.assertEqual(result["status"], "no_source")
        self.assertEqual(result["citations"], [])


class ManualFetchAndSearchTests(unittest.TestCase):
    def test_chapter_markdown_keeps_only_chapter_content(self) -> None:
        markdown = chapter_markdown(CHAPTER_HTML)

        self.assertTrue(markdown.startswith("# 17. Routing and I/O {#routing-and-io}"))
        self.assertIn("## 17.1 Track Output {#tracks-output}", markdown)
        self.assertIn("*track In/Out section*", markdown)
        self.assertIn("`Ctrl`+`I`", markdown)
        self.assertIn("- Main sends to the main track.", markdown)
        self.assertIn("*Figure: The In/Out Section.*", markdown)
        self.assertIn("Nested note.", markdown)
        self.assertNotIn("Footer", markdown)
        self.assertNotIn("Not the manual", markdown)

    def test_paragraphs_inside_list_items_and_cells_stay_inside(self) -> None:
        markdown = chapter_markdown(
            '<div id="chapter_content"><ul><li><p>Item one</p></li></ul>'
            "<table><tr><th><p>Key</p></th><th>Action</th></tr>"
            "<tr><td><p>Cmd</p></td><td>Save</td></tr></table></div>"
        )

        self.assertIn("- Item one", markdown)
        self.assertIn("| Key | Action |", markdown)
        self.assertIn("| Cmd | Save |", markdown)

    def test_index_parsing(self) -> None:
        index = (
            '<a href="/en/live-manual/12/mixing/">x</a><a href="/en/live-manual/12/mixing/#a">'
            '<a href="/en/live-manual/12/routing-and-i-o/">'
            '<a href="https://cdn/pdfs/live-manual/12/2026-10-01/live12-manual-en.pdf">'
        )

        self.assertEqual(chapter_slugs(index, "12"), ["mixing", "routing-and-i-o"])
        self.assertEqual(edition_from_index(index, "12"), "2026-10-01")

    def test_search_ranks_sections_and_cites_anchor_urls(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for edition in ("2026-05-01", "2026-10-01"):
                edition_dir = root / "12" / edition
                edition_dir.mkdir(parents=True)
                (edition_dir / "17-routing-and-i-o.md").write_text(
                    chapter_markdown(CHAPTER_HTML), encoding="utf-8"
                )
                manifest = {
                    "live_major": "12",
                    "edition": edition,
                    "chapters": [
                        {
                            "file": "17-routing-and-i-o.md",
                            "title": "17. Routing and I/O",
                            "url": "https://www.ableton.com/en/live-manual/12/routing-and-i-o/",
                        }
                    ],
                }
                (edition_dir / "manifest.json").write_text(json.dumps(manifest))

            result = search_manual("track output to Main", "12.4.16", manual_root=root)
            pinned = search_manual("output", "12", edition="2026-05-01", manual_root=root)
            editions = list_manual_editions(manual_root=root)

        self.assertEqual(result["edition"], "2026-10-01")
        self.assertEqual(result["results"][0]["section"], "17.1 Track Output")
        self.assertTrue(result["results"][0]["url"].endswith("/routing-and-i-o/#tracks-output"))
        self.assertEqual(pinned["edition"], "2026-05-01")
        self.assertEqual([e["edition"] for e in editions], ["2026-10-01", "2026-05-01"])

    def test_search_without_local_manual_explains_how_to_fetch(self) -> None:
        with tempfile.TemporaryDirectory() as empty:
            result = search_manual("routing", manual_root=Path(empty))

        self.assertEqual(result["status"], "no_source")
        self.assertIn("scripts.fetch_manual", result["reason"])
