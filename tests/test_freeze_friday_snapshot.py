from __future__ import annotations

import unittest

from scripts.freeze_friday_snapshot import freeze_snapshot


class FreezeFridaySnapshotTests(unittest.TestCase):
    def test_published_overlap_is_frozen_without_truncating_older_history(self):
        published = {
            "dates": ["2026-08-14", "2026-08-21"],
            "indicators": [{
                "id": "demo", "signal": "neutral", "score": 2.0,
                "reason": "published", "history": [1.0, 2.0],
            }],
            "categories": [{
                "id": "activity", "score": 3.0, "weeklyScores": [2.0, 3.0],
            }],
            "overall": {"score": 4.0, "weeklyScores": [3.0, 4.0]},
        }
        generated = {
            "dates": ["2026-08-07", "2026-08-14", "2026-08-21"],
            "indicators": [{
                "id": "demo", "signal": "bullish", "score": 9.0,
                "reason": "recomputed", "history": [0.5, 8.0, 9.0],
                "latest": 100.0,
            }],
            "categories": [{
                "id": "activity", "score": 9.0, "weeklyScores": [0.6, 8.0, 9.0],
            }],
            "overall": {"score": 9.0, "weeklyScores": [0.7, 8.0, 9.0]},
        }

        result = freeze_snapshot(published, generated)

        self.assertEqual(result["dates"], generated["dates"])
        self.assertEqual(result["indicators"][0]["history"], [0.5, 1.0, 2.0])
        self.assertEqual(result["indicators"][0]["score"], 2.0)
        self.assertEqual(result["indicators"][0]["latest"], 100.0)
        self.assertEqual(result["categories"][0]["weeklyScores"], [0.6, 2.0, 3.0])
        self.assertEqual(result["overall"]["weeklyScores"], [0.7, 3.0, 4.0])


if __name__ == "__main__":
    unittest.main()
