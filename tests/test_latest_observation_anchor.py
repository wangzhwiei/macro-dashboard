from __future__ import annotations

import unittest
from datetime import date, timedelta

from scripts.update_dashboard import weekly_scores


class LatestObservationAnchorTests(unittest.TestCase):
    def test_missing_release_does_not_overwrite_last_direction_with_zero(self) -> None:
        start = date(2026, 4, 3)
        values = [110 - index for index in range(10)] + [100.2]
        points = [
            (start + timedelta(days=7 * index), value)
            for index, value in enumerate(values)
        ]
        evaluation_dates = [point[0] for point in points[1:]] + [
            points[-1][0] + timedelta(days=7),
            points[-1][0] + timedelta(days=14),
        ]

        scores, _ = weekly_scores(
            points,
            evaluation_dates,
            "pct_change",
            bond_direction=-1,
        )

        self.assertEqual(scores[-1], scores[-2])
        self.assertEqual(scores[-1], scores[-3])
        self.assertGreater(scores[-1], 15)


if __name__ == "__main__":
    unittest.main()
