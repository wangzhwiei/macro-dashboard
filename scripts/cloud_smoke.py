"""One bounded real EDB request; reject any mismatched provider metadata."""
import json
from datetime import date, timedelta
from pathlib import Path
from fetch_trade_actuals import EXPECTED, fetch, load_client

spec = dict(EXPECTED['exports'])
start = (date.today()-timedelta(days=45)).strftime('%Y%m%d')
spec['query'] = f"中国:{spec['name']}（{start}-{date.today():%Y%m%d}），唯一编码{spec['id']}，月频，海关总署，非出口总值。"
rows, meta = fetch(load_client(), spec)
if not rows:
    raise RuntimeError('No verified EDB observations')
report = {'passed': True, 'providerId': meta['index_id'], 'frequency': meta['freq'],
    'unit': meta['unit'], 'rows': len(rows), 'latestDate': max(r[0] for r in rows),
    'productionWrites': False}
Path('outputs/cloud-smoke.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
print(json.dumps(report))
