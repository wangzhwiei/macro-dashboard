import copy
import json
import unittest
from scripts.official_release_overlay import ROOT, apply_official_releases, annotate_history


class OfficialReleaseTests(unittest.TestCase):
    def setUp(self):
        self.path = ROOT / 'data/industrial-value-model/targets_consensus.json'
        self.payload = json.loads(self.path.read_text(encoding='utf-8'))

    def test_append_with_separate_provenance_and_preserve_provider_snapshot(self):
        before = copy.deepcopy(self.payload)
        result = apply_official_releases(self.path, self.payload, as_of='2026-10-19')
        self.assertEqual(self.payload, before)
        item = result['series']['actualMonthly']
        self.assertEqual(dict(item['observations'])['2026-09-30'], 5.5)
        self.assertIsNone(item['observationSources']['2026-09-30']['providerId'])
        self.assertEqual(result['series']['consensus'], before['series']['consensus'])

    def test_no_release_before_publication(self):
        self.assertEqual(apply_official_releases(self.path, self.payload, as_of='2026-10-18'), self.payload)

    def test_unit_mismatch_and_conflict_rejected(self):
        self.payload['series']['actualMonthly']['unit'] = '亿元'
        with self.assertRaises(ValueError):
            apply_official_releases(self.path, self.payload, as_of='2026-10-19')
        self.payload['series']['actualMonthly']['unit'] = '%'
        self.payload['series']['actualMonthly']['observations'].append(['2026-09-30', 99])
        with self.assertRaises(ValueError):
            apply_official_releases(self.path, self.payload, as_of='2026-10-19')

    def test_preserve_published_forecast_after_actual_arrives(self):
        old = [{'date':'2026-09-30','forecast':4.7,'actual':None,'officialRounding':4.7}]
        rows = [{'date':'2026-09-30','forecast':5.4,'actual':5.5}]
        result = annotate_history(rows, old, 'industrial_value')
        self.assertEqual(result[0]['forecast'], 4.7)
        self.assertEqual(result[0]['forecastKind'], 'confirmed_nowcast')
        self.assertIn('stats.gov.cn', result[0]['actualSourceUrl'])

    def test_retail_pending_is_not_a_numeric_forecast(self):
        page = json.loads((ROOT / 'public/data/forecasts.json').read_text(encoding='utf-8'))
        model = page['models']['retail']
        if model['status'] == 'WAITING_FOR_MONTHLY_FACTORS':
            self.assertIsNone(page['history']['retail'][-1]['forecast'])
            self.assertIn(model['forecastMonth'], model['availabilityNote'])
            self.assertNotIn('earliestForecastDate', model)
