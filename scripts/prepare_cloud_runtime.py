import json
import os
from pathlib import Path
from adapters import hybrid_adapter as adapter

root = Path(__file__).resolve().parents[1]
settings = json.loads((root/'config/cloud-admin.json').read_text())
limit = settings['maxProviderCalls']
if type(limit) is not int or not 1 <= limit <= 100:
    raise ValueError('Invalid cloud request limit')
if os.environ.get('GITHUB_ENV'):
    with open(os.environ['GITHUB_ENV'], 'a', encoding='utf-8') as output:
        output.write(f'IFIND_MAX_CALLS={limit}\n')
cache = Path(os.environ['MACRO_DATA_CACHE_DIR'])
cache.mkdir(parents=True, exist_ok=True)
bootstrap = json.loads((root/'data/cloud-bootstrap.json').read_text(encoding='utf-8'))
allowed = {adapter._cache_path(code).name: adapter._identity(code) for code in adapter._load_ifind_map()}
for name, payload in bootstrap['caches'].items():
    if Path(name).name != name or name not in allowed or payload.get('identity') != allowed[name]:
        raise ValueError('Unsafe cache path')
    target = cache/name
    if not target.exists():
        target.write_text(json.dumps(payload, ensure_ascii=False), encoding='utf-8')
# Compatibility marker only. The client reads the real secret from environment.
(root/'scripts/cloud_runtime/mcp_config.json').write_text('{"source":"environment"}', encoding='utf-8')
print('Prepared cloud runtime from validated bootstrap; no credential file created.')
