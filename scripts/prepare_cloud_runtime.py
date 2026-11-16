import json
import os
from pathlib import Path

root = Path(__file__).resolve().parents[1]
cache = Path(os.environ['MACRO_DATA_CACHE_DIR'])
cache.mkdir(parents=True, exist_ok=True)
bootstrap = json.loads((root/'data/cloud-bootstrap.json').read_text(encoding='utf-8'))
for name, payload in bootstrap['caches'].items():
    if Path(name).name != name or not name.startswith('IFIND_') or not name.endswith('.json'):
        raise ValueError('Unsafe cache path')
    target = cache/name
    if not target.exists():
        target.write_text(json.dumps(payload, ensure_ascii=False), encoding='utf-8')
# Compatibility marker only. The client reads the real secret from environment.
(root/'scripts/cloud_runtime/mcp_config.json').write_text('{"source":"environment"}', encoding='utf-8')
print('Prepared cloud runtime from validated bootstrap; no credential file created.')
