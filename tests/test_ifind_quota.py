import json
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch
from scripts.adapters import hybrid_adapter as a


def quota_response():
    return {'ok':True,'data':{'result':{'content':[{'text':json.dumps({'code':1,'data':{
        'answer':'当前账户MCP请求用量已耗尽，可以升级权益。'}})}]}}}


class QuotaTests(unittest.TestCase):
    def test_quota_is_not_identity_conflict(self):
        with self.assertRaisesRegex(RuntimeError,'接口额度耗尽'):
            a._extract_ifind_payload(quota_response())

    def test_empty_candidates_are_not_identity_conflict(self):
        r={'ok':True,'data':{'result':{'content':[{'text':json.dumps({'data':{'answer':'没有找到结果'}})}]}}}
        with self.assertRaisesRegex(RuntimeError,'未返回指标候选'):
            a._extract_ifind_payload(r)

    def test_exhaustion_stops_repeat_calls_and_preserves_last_verification(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(a,'CACHE_DIR',Path(tmp)), patch.object(a,'_ifind_unavailable_reason',None):
            codes=['IFIND:NANHUA_ENERGY','CJHX:ASPHALT_OPERATING_RATE']
            for c in codes:a._save_cache(c,[{'date':'2026-09-24','value':1}], '2026-09-27')
            with patch.object(a,'_ifind_call',return_value=quota_response()) as call:
                for c in codes:
                    a._fetch_ifind(c,date(2026,9,1),date(2026,9,28))
                    self.assertEqual(a._load_cache(c)[1],'2026-09-27')
                    self.assertIn('接口额度耗尽',a.SOURCE_STATUS[c]['message'])
            self.assertEqual(call.call_count,1)
