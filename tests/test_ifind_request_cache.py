import json
import os
import tempfile
import unittest
from unittest.mock import Mock, patch
from scripts import ifind_request_cache as c


def response(code='FIXED', frequency='D'):
    return {'ok':True,'data':{'result':{'content':[{'text':json.dumps({'data':{'datas':[{'data':{
        'attrs':{'series':{'index_id':code,'freq':frequency,'unit':'%'}},
        'data':[['2026-09-24',17.0]]}}]}})}]}}}


class SharedCacheTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.env=patch.dict(os.environ,{'MACRO_DATA_CACHE_DIR':self.temp.name})
        self.env.start()
    def tearDown(self):
        self.env.stop();self.temp.cleanup()
    def test_exact_success_reused_by_another_client(self):
        raw=Mock(return_value=response())
        for _ in range(2):c.wrap_ifind_call(raw)('edb','get_edb_data',{'query':'same'})
        self.assertEqual(raw.call_count,1)
    def test_canonical_series_shared_across_different_queries(self):
        raw=Mock(return_value=response())
        identity={'id':'FIXED','frequency':'D','start':'2026-08-01','end':'2026-09-28'}
        for query in ['dashboard query','forecast query']:
            c.wrap_ifind_call(raw)('edb','get_edb_data',{'query':query,'_cache_identity':identity})
        self.assertEqual(raw.call_count,1)
        self.assertNotIn('_cache_identity',raw.call_args.args[2])
    def test_wrong_identity_not_shared(self):
        raw=Mock(return_value=response('OTHER'))
        identity={'id':'FIXED','frequency':'D','start':'2026-08-01','end':'2026-09-28'}
        for query in ['first','second']:
            c.wrap_ifind_call(raw)('edb','get_edb_data',{'query':query,'_cache_identity':identity})
        self.assertEqual(raw.call_count,2)
    def test_failed_entry_does_not_refetch_successes(self):
        raw=Mock(side_effect=[response(),{'ok':False}])
        call=c.wrap_ifind_call(raw)
        for query in ['success','failure','success','failure']:call('edb','get_edb_data',{'query':query})
        self.assertEqual(raw.call_count,2)
    def test_quota_shared_and_manual_reset(self):
        quota={'ok':True,'data':{'result':{'content':[{'text':json.dumps({'data':{'answer':'当前账户MCP请求用量已耗尽'}})}]}}}
        raw=Mock(return_value=quota)
        for query in ['hf','forecast','consensus']:
            with self.assertRaisesRegex(RuntimeError,'额度耗尽'):
                c.wrap_ifind_call(raw)('edb','get_edb_data',{'query':query})
        self.assertEqual(raw.call_count,1)
        c.reset_generation();self.assertFalse(c.quota_blocked())
        raw.return_value=response()
        c.wrap_ifind_call(raw)('edb','get_edb_data',{'query':'hf'})
        self.assertEqual(raw.call_count,2)
    def test_confirmation_bypasses_cache(self):
        raw=Mock(return_value=response());call=c.wrap_ifind_call(raw)
        call('edb','get_edb_data',{'query':'a'})
        call('edb','get_edb_data',{'query':'a','_cache_bypass':True})
        self.assertEqual(raw.call_count,2)
        self.assertNotIn('_cache_bypass',raw.call_args.args[2])
    def test_force_generation_invalidates_success(self):
        raw=Mock(return_value=response());call=c.wrap_ifind_call(raw)
        call('edb','get_edb_data',{'query':'a'});c.reset_generation()
        call('edb','get_edb_data',{'query':'a'})
        self.assertEqual(raw.call_count,2)
    def test_next_day_does_not_reuse_previous_day(self):
        raw=Mock(return_value=response());call=c.wrap_ifind_call(raw)
        for day in ['2026-09-27','2026-09-28']:
            with patch.object(c,'today',return_value=day):call('edb','get_edb_data',{'query':'a'})
        self.assertEqual(raw.call_count,2)
