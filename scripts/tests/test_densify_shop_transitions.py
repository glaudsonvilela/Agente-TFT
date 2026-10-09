from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from densify_shop_transitions import windows_for


class DenseShopWindowTests(unittest.TestCase):
    def test_merges_nearby_valid_events_without_crossing_source(self):
        rows = [
            {"source_id": "youtube:a", "before_seconds": 10, "after_seconds": 12},
            {"source_id": "youtube:a", "before_seconds": 15, "after_seconds": 17},
            {"source_id": "youtube:b", "before_seconds": 50, "after_seconds": 52},
            {"source_id": "youtube:a", "before_seconds": 40, "after_seconds": 50},
        ]
        self.assertEqual(windows_for(rows, "youtube:a", 100), [(6, 21)])

    def test_clamps_boundaries_and_rejects_invalid_time_ranges(self):
        rows = [
            {"source_id": "youtube:a", "before_seconds": 0, "after_seconds": 2},
            {"source_id": "youtube:a", "before_seconds": 98, "after_seconds": 100},
            {"source_id": "youtube:a", "before_seconds": 20, "after_seconds": 23},
            {"source_id": "youtube:a", "before_seconds": 30, "after_seconds": 30},
            {"source_id": "youtube:a", "before_seconds": "40", "after_seconds": 41},
        ]
        self.assertEqual(windows_for(rows, "youtube:a", 100), [(0, 6), (94, 100)])


if __name__ == "__main__":
    unittest.main()
