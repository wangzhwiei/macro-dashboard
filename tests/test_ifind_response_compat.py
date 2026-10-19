import copy
import json
import unittest
from scripts.ifind_response_compat import normalize, FIELDS


def envelope(data):
    return {'ok': True, 'data': {'result': {'content': [{'text': json.dumps({'code': 1, 'data': data})}]}}}


class CompatTests(unittest.TestCase):
    def setUp(self):
        self.meta = dict(zip(FIELDS, ['沥青开工率', 'W', '%', '石油化工', '同花顺金融', '中国', '20211111', '20261015']))
        self.item = {v: self.meta[k] for k, v in FIELDS.items()}
        self.item['displayId'] = 'S019986856'
        self.answer = '|日期|沥青开工率（单位：%）|\n|---|---|\n|2026-10-15|15|\n|2026-10-08|16|'

    def run_response(self, answer=None, items=None, meta=None):
        raw = envelope({'answer': answer or self.answer, 'indicator_description': [meta or self.meta]})
        catalog = [self.item] if items is None else items
        return normalize(raw, lambda _: envelope({'data': '```json\n'+json.dumps(catalog)+'\n```'}))

    def test_valid_identity_and_preserved_answer(self):
        result = self.run_response()
        data = json.loads(result['data']['result']['content'][0]['text'])['data']
        self.assertEqual(data['answer'], self.answer)
        self.assertEqual(data['datas'][0]['extra']['index_id'], 'S019986856')
        self.assertEqual(data['datas'][0]['data']['data'], [['2026-10-08',16.0],['2026-10-15',15.0]])

    def test_every_metadata_field_must_match(self):
        for field in FIELDS.values():
            item = dict(self.item, **{field:'wrong'})
            with self.assertRaises(RuntimeError): self.run_response(items=[item])

    def test_ambiguity_and_missing_catalog(self):
        for items in ([], [self.item, self.item]):
            with self.assertRaises(RuntimeError): self.run_response(items=items)

    def test_bad_tables(self):
        for answer in (self.answer+'\n...', self.answer.replace('15|','NaN|'),
                       self.answer.replace('沥青开工率（','另一个指标（'),
                       self.answer+'\n|2026-10-15|17|', self.answer+'\n|2026-10-16|1|'):
            with self.assertRaises((RuntimeError,ValueError)): self.run_response(answer=answer)

    def test_suffix_is_expanded_once(self):
        result = self.run_response(answer=self.answer.replace('|15|','|1.5万|'))
        data = json.loads(result['data']['result']['content'][0]['text'])['data']
        self.assertEqual(data['datas'][0]['data']['data'][-1][1],15000)

    def test_old_format_unchanged(self):
        old = envelope({'datas':[{'existing': True}]})
        self.assertIs(normalize(old, lambda _: self.fail('unneeded search')), old)

    def test_saved_identity_allows_only_end_date_to_advance(self):
        old = dict(self.item, endDate='20261008')
        raw = envelope({'answer': self.answer, 'indicator_description': [self.meta]})
        result = normalize(raw, catalog=[old])
        self.assertIn('saved_provider_metadata_join', result['data']['result']['content'][0]['text'])
        for field in ('indexName', 'freq', 'unit', 'dataSource', 'country', 'node', 'startDate'):
            with self.assertRaises(RuntimeError):
                normalize(raw, catalog=[dict(old, **{field:'wrong'})])
        with self.assertRaises(RuntimeError):
            normalize(raw, catalog=[old, dict(old, displayId='S000000000')])

    def test_wrapper_never_searches(self):
        import tempfile
        from pathlib import Path
        from unittest.mock import patch
        from scripts.ifind_request_cache import wrap_ifind_call
        raw = envelope({'answer': self.answer, 'indicator_description': [self.meta]})
        calls = []
        def call(server, tool, params):
            calls.append(tool)
            return raw
        with tempfile.TemporaryDirectory() as folder, patch('scripts.ifind_request_cache.root', return_value=Path(folder)), patch('scripts.ifind_request_cache.saved_catalog', return_value=[self.item]):
            wrap_ifind_call(call)('edb', 'get_edb_data', {'query': 'test'})
        self.assertEqual(calls, ['get_edb_data'])

    def test_archival_unit_scale_does_not_change_identity_or_raw_values(self):
        meta = dict(self.meta, 单位='吨')
        item = dict(self.item, unit='万吨')
        raw = envelope({'answer': self.answer.replace('单位：%', '单位：吨'), 'indicator_description': [meta]})
        result = normalize(raw, catalog=[item])
        data = json.loads(result['data']['result']['content'][0]['text'])['data']['datas'][0]['data']
        self.assertEqual(data['attrs']['沥青开工率']['unit'], '吨')
        self.assertEqual(data['data'][-1][1], 15)
        with self.assertRaises(RuntimeError):
            normalize(raw, catalog=[dict(item, unit='亿元')])

    def test_rejected_response_retries_do_not_repeat_network(self):
        import tempfile
        from pathlib import Path
        from unittest.mock import Mock, patch
        from scripts.ifind_request_cache import wrap_ifind_call
        raw = envelope({'answer': self.answer, 'indicator_description': [self.meta]})
        call = Mock(return_value=raw)
        with tempfile.TemporaryDirectory() as folder, patch('scripts.ifind_request_cache.root', return_value=Path(folder)), patch('scripts.ifind_request_cache.saved_catalog', return_value=[]):
            wrapped = wrap_ifind_call(call)
            for _ in range(3):
                with self.assertRaises(RuntimeError):
                    wrapped('edb', 'get_edb_data', {'query': 'test'})
        self.assertEqual(call.call_count, 1)

    def test_omitted_unit_requires_archived_dimensionless_series(self):
        meta = dict(self.meta)
        del meta['单位']
        raw = envelope({'answer': self.answer.replace('（单位：%）',''), 'indicator_description': [meta]})
        normalize(raw, catalog=[dict(self.item, unit='')])
        with self.assertRaises(RuntimeError):
            normalize(raw, catalog=[self.item])

    def test_new_quota_wording_blocks_future_requests(self):
        import tempfile
        from unittest.mock import patch
        from pathlib import Path
        from scripts.ifind_request_cache import reject_quota, quota_blocked, reset_generation
        with tempfile.TemporaryDirectory() as folder, patch('scripts.ifind_request_cache.root', return_value=Path(folder)):
            with self.assertRaisesRegex(RuntimeError, '额度耗尽'):
                reject_quota(envelope({'answer': 'search_edb 已经达到用户账号权益下该工具请求次数上限'}), 'test')
            self.assertTrue(quota_blocked())
            reset_generation()
            self.assertFalse(quota_blocked())
