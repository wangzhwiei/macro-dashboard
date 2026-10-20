import copy
import json
import unittest
from pathlib import Path
from scripts.ifind_response_compat import normalize, unwrap

ROOT = Path(__file__).resolve().parents[1]

class TaiwanIdentityTests(unittest.TestCase):
    def setUp(self):
        self.catalog=json.loads((ROOT/'data/trade-model/fixed_factor_provider_catalog.json').read_text())['catalog']
        self.response=json.loads((ROOT/'data/trade-model/taiwan-refresh-evidence.json').read_text())

    def test_verified_monthly(self):
        data=unwrap(normalize(self.response,catalog=self.catalog))['data']['datas'][0]['data']
        self.assertEqual(data['attrs'][data['columns'][1]]['index_id'],'G002610107')
        self.assertEqual(dict(data['data'])['2026-08-31'],12544080000)

    def test_same_name_annual_rejected(self):
        response=copy.deepcopy(self.response)
        payload=unwrap(response)
        payload['data']['indicator_description'][0]['频率']='Y'
        response['data']['result']['content'][0]['text']=json.dumps(payload)
        with self.assertRaises(RuntimeError): normalize(response,catalog=self.catalog)

    def test_no_query_id_guess(self):
        with self.assertRaises(RuntimeError): normalize(self.response,catalog=[])

    def test_published_forecasts_and_retrospective_labels_preserved(self):
        from scripts.publish_fixed_trade_forecasts import augment_payload
        before=json.loads((ROOT/'public/data/forecasts.json').read_text())
        after=augment_payload(copy.deepcopy(before))
        for key in ('exports','imports'):
            updated={row['date']:row for row in after['history'][key]}
            for row in before['history'][key]:
                if row['forecast'] is not None:
                    self.assertEqual(updated[row['date']]['forecast'],row['forecast'])
                if row.get('forecastKind')=='retrospective_reconstruction':
                    self.assertEqual(updated[row['date']]['forecastKind'],row['forecastKind'])
