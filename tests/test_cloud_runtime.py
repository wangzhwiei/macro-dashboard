import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

PATH=Path(__file__).resolve().parents[1]/'scripts/cloud_runtime/call.py'

class CloudRuntimeTests(unittest.TestCase):
    def client(self):
        spec=importlib.util.spec_from_file_location('test_cloud_client',PATH)
        module=importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_disallows_unapproved_tools(self):
        with self.assertRaises(ValueError):
            self.client().call('edb','search_edb',{})

    def test_budget_stops_before_network(self):
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ, {'MACRO_DATA_CACHE_DIR':folder,'IFIND_MAX_CALLS':'1','GITHUB_RUN_ID':'test','GITHUB_RUN_ATTEMPT':'1'}):
            Path(folder,'cloud-run-budget.json').write_text(json.dumps({'runId':'test:1','used':1}))
            client=self.client()
            with patch.object(client.requests,'post') as post:
                with self.assertRaisesRegex(RuntimeError,'budget reached'):
                    client.call('edb','get_edb_data',{'query':'test'})
                post.assert_not_called()

    def test_credential_not_embedded_and_tls_never_disabled(self):
        client=self.client()
        with patch.dict(os.environ, {'IFIND_AUTH_TOKEN':''}), patch.object(client.requests,'post') as post:
            with self.assertRaisesRegex(RuntimeError,'Missing IFIND_AUTH_TOKEN'):
                client._post('initialize',{})
            post.assert_not_called()
        with patch.dict(os.environ, {'IFIND_AUTH_TOKEN':'dummy-test-only'}), patch.object(client.requests,'post') as post:
            post.return_value.content=b''
            post.return_value.text=''
            client._post('initialize',{})
            self.assertTrue(post.call_args.kwargs.get('verify',True))

if __name__=='__main__':
    unittest.main()
