import json
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch
from scripts.adapters import hybrid_adapter as a


def response(points, provider='S019986856', freq='W'):
    return {'ok': True, 'data': {'result': {'content': [{'text': json.dumps({'data': {
        'datas': [{'data': {'attrs': {'asphalt': {'index_id': provider, 'unit': '%', 'freq': freq}},
                             'data': points}}]}})}]}}}


class SourceReconciliationTests(unittest.TestCase):
    def test_corrected_source_unfreezes_affected_scores(self):
        from copy import deepcopy
        from scripts.freeze_friday_snapshot import freeze_snapshot
        published={'dates':['2026-09-04','2026-09-11'], 'indicators':[{
            'id':'asphalt','history':[1,2], 'signal':'neutral','score':2,'reason':'old',
            'scoreAsOf':'2026-09-11','scoreObservationAt':'2026-09-10','scoreChange':0,
            'scoreScale':1,'scoreChanges':[0,0],'scoreScales':[1,1],
            'scoreObservationDates':['2026-09-03','2026-09-10'],
            'series':[{'date':'2026-09-03','value':14},{'date':'2026-09-09','value':17.5},
                      {'date':'2026-09-10','value':14}]}],
            'categories':[{'id':'activity','score':2,'weeklyScores':[1,2]}],
            'overall':{'score':2,'weeklyScores':[1,2]}}
        generated=deepcopy(published)
        generated['indicators'][0]['series'].pop(1)
        generated['indicators'][0].update(history=[9,8],score=8)
        generated['categories'][0].update(weeklyScores=[9,8],score=8)
        generated['overall'].update(weeklyScores=[9,8],score=8)
        out=freeze_snapshot(published,generated)
        self.assertEqual(out['indicators'][0]['history'],[1,8])
        self.assertEqual(out['overall']['weeklyScores'],[1,8])

    def test_replacement_removes_ghost_but_preserves_outside_coverage(self):
        old = [{'date': d, 'value': v} for d,v in [('2026-08-01',13),('2026-09-03',14),
            ('2026-09-09',17.5),('2026-09-10',14),('2026-09-26',18)]]
        fresh = [{'date':'2026-09-03','value':14}, {'date':'2026-09-10','value':14}]
        self.assertEqual([x['date'] for x in a._reconcile_records(old,fresh)],
                         ['2026-08-01','2026-09-03','2026-09-10','2026-09-26'])

    def test_legacy_cache_rechecked_and_ghost_archived(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(a,'CACHE_DIR',Path(tmp)):
            code='CJHX:ASPHALT_OPERATING_RATE'
            a._cache_path(code).write_text(json.dumps({'last_checked_date':'2026-09-27','records':[
                {'date':'2026-09-03','value':14},{'date':'2026-09-09','value':17.5},
                {'date':'2026-09-10','value':14}]}))
            with patch.object(a,'_ifind_call',return_value=response([['2026-09-03',14],['2026-09-10',14]])) as call:
                rows=a._fetch_ifind(code,date(2026,8,1),date(2026,9,27))
            self.assertEqual(call.call_count,2)
            self.assertNotIn('2026-09-09',[x['date'] for x in rows])
            self.assertTrue(list(Path(tmp).glob('evidence/*/cache-before-*.json')))
            self.assertEqual(a.SOURCE_STATUS[code]['status'],'verified')

    def test_inconsistent_confirmation_never_deletes(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(a,'CACHE_DIR',Path(tmp)), patch.object(a.time,'sleep'):
            code='CJHX:ASPHALT_OPERATING_RATE'
            old=[{'date':'2026-09-09','value':17.5}]
            a._save_cache(code,old)
            first=response([['2026-09-03',14],['2026-09-10',14]])
            second=response([['2026-09-03',14]])
            with patch.object(a,'_ifind_call',side_effect=[first,second]*3):
                rows=a._fetch_ifind(code,date(2026,8,1),date(2026,9,27))
            self.assertEqual(rows,old)
            self.assertIsNone(a._load_cache(code)[1])
            self.assertEqual(a.SOURCE_STATUS[code]['status'],'warning')

    def test_changed_identity_rejected(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(a,'CACHE_DIR',Path(tmp)):
            code='CJHX:ASPHALT_OPERATING_RATE'
            a._save_cache(code,[], '2026-09-27')
            payload=json.loads(a._cache_path(code).read_text())
            payload['identity']['provider_id']='WRONG'
            a._cache_path(code).write_text(json.dumps(payload))
            with self.assertRaisesRegex(RuntimeError,'身份变更'):a._load_cache(code)

    def test_frequency_and_conflicting_duplicates_rejected(self):
        for payload in [response([['2026-09-03',14]],freq='D'),
                        response([['2026-09-03',14],['2026-09-03',17.5]])]:
            with self.assertRaises(RuntimeError):
                a._parse_ifind_records(a._extract_ifind_payload(payload),'S019986856',
                    date(2026,9,1),date(2026,9,27),'%','W')
