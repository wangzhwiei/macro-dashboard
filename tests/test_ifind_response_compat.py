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
