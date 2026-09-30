from __future__ import annotations

import unittest

from ingestion.metatft.browser_collector import (
    due_for_capture,
    slug_for_url,
    validate_public_url,
)


class MetaTftBrowserCollectorTests(unittest.TestCase):
    def test_allows_known_public_paths(self):
        self.assertEqual(
            validate_public_url("https://www.metatft.com/comps"),
            "https://www.metatft.com/comps",
        )
        self.assertEqual(
            validate_public_url("https://www.metatft.com/leaderboard/br"),
            "https://www.metatft.com/leaderboard/br",
        )

    def test_rejects_non_metatft_and_unlisted_paths(self):
        with self.assertRaises(ValueError):
            validate_public_url("https://example.com/comps")
        with self.assertRaises(ValueError):
            validate_public_url("https://www.metatft.com/account/private")

    def test_capture_interval_is_respected(self):
        manifest = {
            "captures": {
                "https://www.metatft.com/comps": {
                    "captured_at_epoch": 1000,
                }
            }
        }
        self.assertFalse(
            due_for_capture(
                manifest,
                "https://www.metatft.com/comps",
                now_epoch=1200,
                min_interval_seconds=900,
            )
        )
        self.assertTrue(
            due_for_capture(
                manifest,
                "https://www.metatft.com/comps",
                now_epoch=2000,
                min_interval_seconds=900,
            )
        )

    def test_slug_is_stable_and_filename_safe(self):
        value = slug_for_url(
            "https://www.metatft.com/traits/void?set=TFTSet18"
        )
        self.assertNotIn("/", value)
        self.assertEqual(
            value,
            slug_for_url(
                "https://www.metatft.com/traits/void?set=TFTSet18"
            ),
        )


if __name__ == "__main__":
    unittest.main()
