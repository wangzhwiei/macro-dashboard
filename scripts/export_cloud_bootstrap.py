"""Export validated observations and provider identity metadata, never auth/raw replies."""
import json
from pathlib import Path
from adapters import hybrid_adapter as adapter
from ifind_response_compat import saved_catalog

catalog = saved_catalog(adapter.CACHE_DIR/'requests')
catalog = list({json.dumps(x, sort_keys=True): x for x in catalog}.values())
caches = {}
for code in adapter._load_ifind_map():
    path = adapter._cache_path(code)
    if path.exists():
        value = json.loads(path.read_text())
        if isinstance(value, dict) and value.get('identity') == adapter._identity(code):
            caches[path.name] = {k: value[k] for k in ('schema','identity','records','last_checked_date') if k in value}
payload = {'catalog': catalog, 'caches': caches}
text = json.dumps(payload, ensure_ascii=False, separators=(',',':'))
secret_path = Path.home()/'.openclaw/workspace/skills/ifind-finance-data/ifind-finance-data/mcp_config.json'
assert json.loads(secret_path.read_text())['auth_token'] not in text
out = Path(__file__).resolve().parents[1]/'data/cloud-bootstrap.json'
out.write_text(text, encoding='utf-8')
print(f'Exported {len(catalog)} provider identities and {len(caches)} validated observation caches; no credentials.')
