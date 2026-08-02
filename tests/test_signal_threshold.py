from __future__ import annotations

import unittest

from scripts.update_dashboard import signal_from_score


class DisplayThresholdTests(unittest.TestCase):
    def test_signal_uses_the_integer_strength_shown_on_page(self) -> None:
        self.assertEqual(signal_from_score(14.7, 15), "bullish")
        self.assertEqual(signal_from_score(-14.7, 15), "bearish")
        self.assertEqual(signal_from_score(14.4, 15), "neutral")


if __name__ == "__main__":
    unittest.main()
