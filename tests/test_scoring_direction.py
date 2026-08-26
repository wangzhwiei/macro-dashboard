from __future__ import annotations

import unittest
from datetime import date, timedelta

from scripts.update_dashboard import weekly_scores


class EconomicDirectionTests(unittest.TestCase):
    def test_future_observations_cannot_rescale_an_old_friday(self) -> None:
        start = date(2026, 1, 2)
        points = [
            (start + timedelta(days=7 * index), 100 + index)
            for index in range(10)
        ]
        snapshot = [points[5][0]]
        original, _ = weekly_scores(points[:7], snapshot, "pct_change", -1)
        revised, _ = weekly_scores(
            points + [(start + timedelta(days=70), 1000)],
            snapshot,
            "pct_change",
            -1,
        )

        self.assertEqual(original, revised)

    def test_falling_listing_price_cannot_become_bond_bearish(self) -> None:
        start = date(2026, 4, 3)
        values = [110 - index for index in range(10)] + [100.2]
        points = [
            (start + timedelta(days=7 * index), value)
            for index, value in enumerate(values)
        ]
        evaluation_dates = [point[0] for point in points[1:]]

        scores, _ = weekly_scores(
            points,
            evaluation_dates,
            "pct_change",
            bond_direction=-1,
        )

        self.assertGreater(
            scores[-1],
            15,
            "挂牌价环比下降且方向系数为-1时，债市信号必须为利多",
        )

    def test_rising_listing_price_remains_bond_bearish(self) -> None:
        start = date(2026, 4, 3)
        values = [100 + index for index in range(10)] + [109.8]
        points = [
            (start + timedelta(days=7 * index), value)
            for index, value in enumerate(values)
        ]
        evaluation_dates = [point[0] for point in points[1:]]

        scores, _ = weekly_scores(
            points,
            evaluation_dates,
            "pct_change",
            bond_direction=-1,
        )

        self.assertLess(scores[-1], -15)


if __name__ == "__main__":
    unittest.main()
