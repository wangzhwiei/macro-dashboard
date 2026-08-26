from __future__ import annotations

import unittest

from scripts.freeze_friday_snapshot import freeze_snapshot


class FreezeFridaySnapshotTests(unittest.TestCase):
    @staticmethod
    def snapshot_fields(score: float, day: str = "2026-08-21") -> dict:
        return {
            "signal": "neutral",
            "score": score,
            "reason": "published",
            "scoreAsOf": day,
            "scoreObservationAt": day,
            "scoreChange": 0.2,
            "scoreScale": 2.5,
        }

    @staticmethod
    def weekly_fields(length: int) -> dict:
        return {
            "scoreChanges": [0.2] * length,
            "scoreScales": [2.5] * length,
            "scoreObservationDates": ["2026-08-21"] * length,
        }

    def test_published_overlap_is_frozen_without_truncating_older_history(self):
        published = {
            "dates": ["2026-08-14", "2026-08-21"],
            "indicators": [{
                "id": "demo", "history": [1.0, 2.0],
                **self.snapshot_fields(2.0),
                **self.weekly_fields(2),
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
                **self.weekly_fields(3),
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

    def test_legacy_latest_snapshot_is_recomputed_but_older_dates_stay_frozen(self):
        published = {
            "dates": ["2026-08-14", "2026-08-21"],
            "indicators": [{
                "id": "demo", "signal": "bullish", "score": 100.0,
                "reason": "legacy mismatch", "history": [1.0, 100.0],
            }],
            "categories": [{
                "id": "activity", "score": 80.0, "weeklyScores": [2.0, 80.0],
            }],
            "overall": {"score": 70.0, "weeklyScores": [3.0, 70.0]},
        }
        generated = {
            "dates": ["2026-08-07", "2026-08-14", "2026-08-21"],
            "indicators": [{
                "id": "demo", "signal": "neutral", "score": 9.0,
                "reason": "recomputed", "history": [0.5, 8.0, 9.0],
                "latest": 100.0,
                **self.snapshot_fields(9.0),
                **self.weekly_fields(3),
            }],
            "categories": [{
                "id": "activity", "score": 9.0, "weeklyScores": [0.6, 8.0, 9.0],
            }],
            "overall": {"score": 9.0, "weeklyScores": [0.7, 8.0, 9.0]},
        }

        result = freeze_snapshot(published, generated)

        self.assertEqual(result["indicators"][0]["history"], [0.5, 1.0, 9.0])
        self.assertEqual(result["indicators"][0]["score"], 9.0)
        self.assertEqual(result["categories"][0]["weeklyScores"], [0.6, 2.0, 9.0])
        self.assertEqual(result["overall"]["weeklyScores"], [0.7, 3.0, 9.0])

    def test_new_friday_keeps_old_dates_and_publishes_new_snapshot(self):
        published = {
            "dates": ["2026-08-14", "2026-08-21"],
            "indicators": [{
                "id": "demo", "history": [1.0, 2.0],
                **self.snapshot_fields(2.0),
                **self.weekly_fields(2),
            }],
            "categories": [{
                "id": "activity", "score": 3.0, "weeklyScores": [2.0, 3.0],
            }],
            "overall": {"score": 4.0, "weeklyScores": [3.0, 4.0]},
        }
        generated = {
            "dates": ["2026-08-14", "2026-08-21", "2026-08-28"],
            "indicators": [{
                "id": "demo", "signal": "bullish", "score": 9.0,
                "reason": "new friday", "history": [8.0, 8.5, 9.0],
                "latest": 101.0,
                **self.snapshot_fields(9.0, "2026-08-28"),
                **self.weekly_fields(3),
            }],
            "categories": [{
                "id": "activity", "score": 9.0, "weeklyScores": [8.0, 8.5, 9.0],
            }],
            "overall": {"score": 9.0, "weeklyScores": [8.0, 8.5, 9.0]},
        }

        result = freeze_snapshot(published, generated)

        self.assertEqual(result["indicators"][0]["history"], [1.0, 2.0, 9.0])
        self.assertEqual(result["indicators"][0]["score"], 9.0)
        self.assertEqual(result["indicators"][0]["scoreAsOf"], "2026-08-28")


if __name__ == "__main__":
    unittest.main()
