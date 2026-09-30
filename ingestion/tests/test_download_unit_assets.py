from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from ingestion.download_unit_assets import (
    download_one,
    extension_from_url,
    preferred_asset,
    sanitize_id,
)


PNG = b"\x89PNG\r\n\x1a\n" + b"fixture"


class UnitAssetTests(unittest.TestCase):
    def test_prefers_square_icon(self):
        champion = {
            "square_icon_url": "https://example/square.png",
            "tile_icon_url": "https://example/tile.png",
            "icon_url": "https://example/icon.png",
        }
        self.assertEqual(
            preferred_asset(champion),
            "https://example/square.png",
        )

    def test_extension_is_restricted(self):
        self.assertEqual(extension_from_url("https://x/a.PNG"), ".png")
        self.assertEqual(extension_from_url("https://x/a.tex"), ".bin")

    def test_sanitize_id_removes_path_characters(self):
        self.assertEqual(sanitize_id("TFT17/A:B"), "TFT17_A_B")

    def test_download_writes_hashed_asset(self):
        with tempfile.TemporaryDirectory() as tmp:
            champion = {
                "api_name": "TFT17_A",
                "square_icon_url": "https://example.invalid/a.png",
            }
            with patch(
                "ingestion.download_unit_assets.fetch_bytes",
                return_value=PNG,
            ):
                result = download_one(
                    champion,
                    Path(tmp),
                    force=True,
                )

            self.assertEqual(result["status"], "updated")
            self.assertEqual(result["api_name"], "TFT17_A")
            self.assertTrue(Path(result["path"]).exists())
            self.assertEqual(result["size_bytes"], len(PNG))


if __name__ == "__main__":
    unittest.main()
