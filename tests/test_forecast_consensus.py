import unittest

from scripts.fetch_forecast_consensus import CONFIG, parse_consensus


class ForecastConsensusTests(unittest.TestCase):
    def test_parser_uses_survey_consensus_and_excludes_te_forecast(self) -> None:
        html = """
        <table><tr data-id="403203" data-country="China" data-category="Inflation Rate">
        <td>2026-08-09</td><td>01:30 AM</td><td><div>Inflation Rate YoY</div></td>
        <td>Jul</td><td>0.5%</td><td>1%</td><td>0.8%</td><td>0.9%</td></tr></table>
        """
        records = parse_consensus(html, CONFIG["cpi"], "2026-08-09T12:00:00+08:00")
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["date"], "2026-07-31")
        self.assertEqual(records[0]["value"], .8)
        self.assertNotEqual(records[0]["value"], .9)
        self.assertEqual(records[0]["eventId"], "403203")

    def test_parser_rejects_fuzzy_event_match(self) -> None:
        html = """
        <table><tr data-id="1" data-country="China" data-category="Business Confidence">
        <td>2026-07-31</td><td>01:30 AM</td><td>Manufacturing PMI Expectations</td>
        <td>Jul</td><td>50</td><td>49</td><td>48</td><td>47</td></tr></table>
        """
        self.assertEqual(parse_consensus(html, CONFIG["pmi"], "now"), [])


if __name__ == "__main__":
    unittest.main()