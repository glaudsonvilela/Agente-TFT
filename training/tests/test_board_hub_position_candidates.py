"""A health bar may suggest a cell, but it does not prove a grounded unit."""
import copy
import json
from pathlib import Path
import unittest

from training.board_hub_position_candidates import project


ROOT = Path(__file__).parents[2]
BOARD = json.loads((ROOT / "configs/ui/match001-board-bench-v1.json").read_text())
PROFILE = json.loads((ROOT / "configs/ui/match001-bar-to-cell-candidates-v1.json").read_text())


def marker(index, x, y, color="green"):
    return {"id": index, "color": color,
            "rect": {"x": x, "y": y, "width": 64, "height": 4}}


class PositionCandidateTests(unittest.TestCase):
    def test_board_bench_unassigned_and_collisions(self):
        read = {"profile": BOARD["id"], "projection_status": "reference_arena_match",
                "markers": [marker(0, 631, 320), marker(1, 640, 323),
                            marker(2, 1334, 576), marker(3, 364, 690),
                            marker(4, 1000, 650), marker(5, 700, 320, "red")]}
        result = project(read, PROFILE, BOARD)
        self.assertEqual([(x["zone"], x["row"], x["cell_or_slot"]) for x in result["candidates"]],
                         [("board", 0, 1), ("board", 0, 1), ("board", 3, 6), ("bench", None, 0)])
        self.assertEqual([x["status"] for x in result["candidates"][:2]],
                         ["ambiguous_collision", "ambiguous_collision"])
        self.assertEqual([x["reason"] for x in result["unassigned"]],
                         ["outside_bar_bands", "not_green_bar"])
        self.assertTrue(all(x["unit_id"] is None and x["ground_point"] is None and
                            x["occupancy"] is None for x in result["candidates"]))
        self.assertFalse(result["occupancy_established"])

    def test_unresolved_projection_abstains_and_bad_bands_fail(self):
        read = {"profile": BOARD["id"], "projection_status": "unresolved",
                "markers": [marker(0, 631, 320)]}
        self.assertEqual(project(read, PROFILE, BOARD)["candidates"], [])
        live = project(read, PROFILE, BOARD, allow_unmatched_arena=True)
        self.assertEqual(live["status"], "bar_geometry_only_unmatched_arena")
        self.assertEqual((live["candidates"][0]["zone"], live["candidates"][0]["row"]),
                         ("board", 0))
        self.assertIsNone(live["candidates"][0]["ground_point"])
        self.assertIsNone(live["candidates"][0]["occupancy"])
        self.assertFalse(live["ground_assignment_established"])
        bad = copy.deepcopy(PROFILE)
        bad["bands"][1]["min_bar_y"] = 360
        with self.assertRaisesRegex(ValueError, "overlap"):
            project(read, bad, BOARD)


if __name__ == "__main__":
    unittest.main()
