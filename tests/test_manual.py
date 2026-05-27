import unittest

import _bootstrap  # noqa: F401

from abletonian.manual import lookup_manual


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
        result = lookup_manual("does this synth have a secret unicorn mode?", live_version="12")

        self.assertEqual(result["status"], "no_source")
        self.assertEqual(result["citations"], [])
