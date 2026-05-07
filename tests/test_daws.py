import unittest

import _bootstrap  # noqa: F401

from abletonian.daws import get_daw_profile, list_daw_profiles, normalize_daw_slug


class DawProfileTests(unittest.TestCase):
    def test_normalizes_common_aliases(self) -> None:
        self.assertEqual(normalize_daw_slug("Ableton Live"), "ableton")
        self.assertEqual(normalize_daw_slug("FL"), "fl-studio")
        self.assertEqual(normalize_daw_slug("LogicPro"), "logic-pro")

    def test_profiles_are_json_ready(self) -> None:
        profile = get_daw_profile("reaper").to_wire()

        self.assertEqual(profile["slug"], "reaper")
        self.assertIn("transport_control", profile["capabilities"])

    def test_lists_ableton_and_fl_studio(self) -> None:
        slugs = {profile.slug for profile in list_daw_profiles()}

        self.assertIn("ableton", slugs)
        self.assertIn("fl-studio", slugs)

    def test_rejects_unknown_daw(self) -> None:
        with self.assertRaises(ValueError):
            normalize_daw_slug("tracker-that-does-not-exist")


if __name__ == "__main__":
    unittest.main()
