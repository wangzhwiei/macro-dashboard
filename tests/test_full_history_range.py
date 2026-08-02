from __future__ import annotations

import unittest
from datetime import date, timedelta

from scripts.update_dashboard import weekly_evaluation_dates


class FullHistoryRangeTests(unittest.TestCase):
    def test_every_friday_is_included_from_2023_to_latest_complete_week(self) -> None:
        dates = weekly_evaluation_dates(date(2023, 1, 1), date(2026, 8, 2))

        self.assertEqual(dates[0], date(2023, 1, 6))
        self.assertEqual(dates[-1], date(2026, 7, 31))
        self.assertGreater(len(dates), 180)
        self.assertTrue(
            all(current - previous == timedelta(days=7) for previous, current in zip(dates, dates[1:]))
        )

    def test_invalid_range_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            weekly_evaluation_dates(date(2026, 8, 3), date(2026, 8, 2))


if __name__ == "__main__":
    unittest.main()