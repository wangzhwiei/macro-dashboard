import csv
import json
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch
from scripts.adapters import hybrid_adapter as a


def response(code, freq, points):
    return {'ok': True, 'data': {'result': {'content': [{'text': json.dumps({'data': {'datas': [
        {'data': {'attrs': {'南华期货:能化指数': {'index_id': code, 'freq': freq, 'unit': ''}}, 'data': points}}
    ]}})}]}}}


class NanhuaIdentityTests(unittest.TestCase):
    def test_daily_and_weekly_same_name_must_not_mix(self):
        daily = a._extract_ifind_payload(response('S004094484','D',[['2026-09-24',2030.59]]))
        weekly = a._extract_ifind_payload(response('S004094490','W',[['2026-09-25',2030.59]]))
        daily['datas'].extend(weekly['datas'])
        rows = a._parse_ifind_records(daily,'S004094484',date(2026,9,1),date(2026,9,27),'指数','D')
        self.assertEqual(rows,[{'date':'2026-09-24','value':2030.59}])

    def test_ambiguous_response_retries_daily_and_preserves_identity(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(a,'CACHE_DIR',Path(tmp)):
            weekly=response('S004094490','W',[['2026-09-25',2030.59]])
            daily=response('S004094484','D',[['2026-09-24',2030.59]])
            with patch.object(a,'_ifind_call',side_effect=[weekly,daily]) as call:
                rows=a._fetch_ifind('IFIND:NANHUA_ENERGY',date(2026,9,1),date(2026,9,27))
            self.assertEqual(call.call_count,2)
            self.assertTrue(all('日频' in c.args[2]['query'] for c in call.call_args_list))
            self.assertEqual(rows[-1]['date'],'2026-09-24')
            self.assertEqual(a.SOURCE_STATUS['IFIND:NANHUA_ENERGY']['status'],'verified')

    def test_provider_catalogs_match_all_ifind_codes(self):
        catalog=json.loads((a.ROOT/'config/provider-code-map.json').read_text())
        for code, metadata in a._load_ifind_map().items():
            self.assertEqual(catalog[code]['provider_code'],'iFinD:'+metadata['provider_id'])
        energy=a._load_ifind_map()['IFIND:NANHUA_ENERGY']
        self.assertEqual((energy['provider_id'],energy['frequency'],energy['query_hint']),('S004094484','D','日频'))

