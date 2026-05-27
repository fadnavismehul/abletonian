import unittest

import _bootstrap  # noqa: F401

from abletonian.als import load_als_as_fake_state


class AlsLoaderTests(unittest.TestCase):
    def test_rejects_non_gzip_als_file(self) -> None:
        with self.assertRaises(OSError):
            load_als_as_fake_state(__file__)


if __name__ == "__main__":
    unittest.main()
