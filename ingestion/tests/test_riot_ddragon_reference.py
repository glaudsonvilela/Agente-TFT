"""The official visual catalog is pinned independently of a replay or UI layout."""
import json
from pathlib import Path
import tempfile
import unittest

from ingestion.riot_ddragon_reference import build, source_url


def snapshot(kind, rows, version="16.19.1"):
    return json.dumps({"type": kind, "version": version, "data": rows}).encode()


CHAMPIONS = snapshot("tft-champion", {
    "Maps/Shipping/Map22/Sets/TFTSet18/Shop/DA_18_Diana": {
        "id": "DA_18_Diana", "name": "Diana", "image": {"full": "DA_18_Diana.TFT_Set18.png"}},
    "Maps/Shipping/Map22/Sets/TFTSet17/Shop/TFT17_Diana": {
        "id": "TFT17_Diana", "name": "Diana", "image": {"full": "TFT17_Diana.TFT_Set17.png"}},
})
ITEMS = snapshot("tft-item", {"TFT_Item_BFSword": {
    "id": "TFT_Item_BFSword", "name": "Espada G.P.C.",
    "image": {"full": "TFT_Item_BFSword.png"}}})


class RiotReferenceTests(unittest.TestCase):
    def test_pinned_set_catalog_is_immutable_and_does_not_bind_replay(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            folder, manifest = build(CHAMPIONS, ITEMS, version="16.19.1", locale="pt_BR",
                                     set_key="TFTSet18", output_root=root)
            self.assertEqual(folder, build(CHAMPIONS, ITEMS, version="16.19.1", locale="pt_BR",
                                           set_key="TFTSet18", output_root=root)[0])
            champions = json.loads((folder / "champions.json").read_text())["entries"]
            self.assertEqual([row["id"] for row in champions], ["DA_18_Diana"])
            self.assertEqual(manifest["components"]["items"]["count"], 1)
            self.assertIsNone(manifest["tft_patch"])
            self.assertFalse(manifest["replay_binding"])
            self.assertFalse(manifest["geometry_included"])
            (folder / "items.json").write_text("{}")
            with self.assertRaisesRegex(ValueError, "changed"):
                build(CHAMPIONS, ITEMS, version="16.19.1", locale="pt_BR",
                      set_key="TFTSet18", output_root=root)

    def test_rejects_unpinned_version_wrong_payload_and_missing_set(self):
        with self.assertRaisesRegex(ValueError, "version"):
            source_url("latest", "pt_BR", "tft-item")
        with tempfile.TemporaryDirectory() as temp:
            for champion, target in ((snapshot("tft-champion", {}, "16.18.1"), "mismatch"),
                                     (CHAMPIONS, "selected set")):
                with self.assertRaisesRegex(ValueError, target):
                    build(champion, ITEMS, version="16.19.1", locale="pt_BR",
                          set_key="TFTSet19" if target == "selected set" else "TFTSet18",
                          output_root=Path(temp))


if __name__ == "__main__":
    unittest.main()
