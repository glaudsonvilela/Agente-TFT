import unittest

from hm.unit_gallery import rank_gallery
from hm.equipment_identity import item_candidate, associate_equipment


class GalleryContracts(unittest.TestCase):
    def test_competing_classes_not_duplicate_views_determine_margin(self):
        rows = rank_gallery(
            [[1.0, 0.0]], [[1.0, 0.0], [0.99, 0.01], [0.0, 1.0]], ["a", "a", "b"]
        )
        self.assertEqual(rows[0]["candidate_id"], "a")
        self.assertFalse(rows[0]["identity_verified"])
        self.assertEqual(len(rows[0]["candidates"]), 2)

    def test_conflict_unknown_and_bad_embeddings_cannot_confirm(self):
        self.assertIsNone(
            rank_gallery([[1.0, 1.0]], [[1.0, 0.0], [0.0, 1.0]], ["a", "b"])[0][
                "candidate_id"
            ]
        )
        self.assertIsNone(
            rank_gallery([[1.0, 0.0]], [[1.0, 0.0], [0.0, 1.0]], ["__unknown__", "b"])[
                0
            ]["candidate_id"]
        )
        for vector in ([[0.0, 0.0]], [[float("nan"), 0.0]], [[1.0, 2.0, 3.0]]):
            with self.assertRaises(ValueError):
                rank_gallery(vector, [[1.0, 0.0], [0.0, 1.0]], ["a", "b"])

    def test_similarity_does_not_depend_on_embedding_magnitude(self):
        result = rank_gallery([[5.0, 0.0]], [[0.1, 0.0], [0.0, 10.0]], ["a", "b"])
        self.assertAlmostEqual(result[0]["candidates"][0]["similarity"], 1)


class EquipmentContracts(unittest.TestCase):
    def slot(self):
        return dict(
            slot=0,
            status="icon_candidate",
            candidates=[
                dict(
                    rms=18.0,
                    catalog_options=[
                        dict(
                            visual_id="season_alias",
                            attribute_id=None,
                            attribute_binding="visual_name_only",
                            name="Sword",
                        ),
                        dict(
                            visual_id="item_sword",
                            attribute_id="item_sword",
                            attribute_binding="exact_api_name",
                            name="Sword",
                        ),
                    ],
                ),
                dict(rms=54.0, catalog_options=[]),
            ],
        )

    def test_artwork_alias_can_resolve_only_one_active_attribute_id(self):
        slot = self.slot()
        result = item_candidate(slot)
        self.assertEqual(result["candidate_id"], "item_sword")
        self.assertFalse(result["identity_verified"])
        slot["candidates"][0]["catalog_options"][0].update(
            attribute_id="different_item", attribute_binding="exact_api_name"
        )
        self.assertIsNone(item_candidate(slot)["candidate_id"])

    def test_incomplete_empty_and_close_alternatives_remain_unknown(self):
        for status in ("empty_appearance", "unknown", "incomplete_catalog"):
            slot = self.slot()
            slot["status"] = status
            self.assertIsNone(item_candidate(slot)["candidate_id"])
        for rms in (20.0, float("nan")):
            slot = self.slot()
            slot["candidates"][1]["rms"] = rms
            self.assertIsNone(item_candidate(slot)["candidate_id"])

    def test_frame_local_pairing_does_not_transfer_between_units(self):
        markers = [dict(marker_id=7, equipped_slots=[self.slot()])]
        identities = {8: dict(candidate_id="champion_a")}
        result = associate_equipment(markers, identities)
        self.assertIsNone(result[0]["unit_candidate"])
        identities = {7: dict(candidate_id="champion_b")}
        result = associate_equipment(markers, identities)
        self.assertEqual(result[0]["unit_candidate"]["candidate_id"], "champion_b")
        self.assertFalse(result[0]["association_verified"])
        self.assertEqual(associate_equipment([], identities), [])


if __name__ == "__main__":
    unittest.main()
