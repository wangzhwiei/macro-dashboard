"""Apply reviewed official releases without forging provider-response identities."""
import copy
import json
import math
from datetime import date
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]


def annotate_history(history, previous, model_key):
    old = {r['date']: r for r in previous}
    source_key = {'industrial_value': 'industrial', 'fixed_asset_investment': 'investment', 'retail': 'retail'}.get(model_key)
    sources = {}
    for p in sorted((ROOT / 'data/official-releases').glob('*.json')):
        release = json.loads(p.read_text(encoding='utf-8'))
        if release['releasedAt'] <= date.today().isoformat() and source_key in release['sources']:
            sources[release['observationDate']] = release['sources'][source_key]
    for row in history:
        prior = old.get(row['date'], {})
        if row.get('actual') is not None:
            if prior.get('forecast') is not None and (prior.get('actual') is None or prior.get('forecastKind') == 'confirmed_nowcast'):
                row['forecast'] = prior['forecast']
                row['officialRounding'] = prior.get('officialRounding')
                row['forecastKind'] = 'confirmed_nowcast'
            if row['date'] in sources:
                row['actualSourceUrl'] = sources[row['date']]
    return history


def apply_official_releases(path, payload, *, release_dir=None, as_of=None):
    path = Path(path).resolve()
    try:
        relative = path.relative_to(ROOT).as_posix()
    except ValueError:
        return payload
    output = copy.deepcopy(payload)
    today = as_of or date.today().isoformat()
    for release_path in sorted((release_dir or ROOT / 'data/official-releases').glob('*.json')):
        release = json.loads(release_path.read_text(encoding='utf-8'))
        day, published = release['observationDate'], release['releasedAt']
        date.fromisoformat(day); date.fromisoformat(published)
        if published > today:
            continue
        if day > published:
            raise ValueError('official observation is after publication')
        for key, update in release['series'].get(relative, {}).items():
            if 'consensus' in key.lower():
                raise ValueError('official actual overlays cannot modify consensus')
            item = output['series'][key]
            url = release['sources'][update['source']]
            if urlparse(url).hostname != 'www.stats.gov.cn' or item['unit'] != update['unit'] or item['frequency'] != 'M':
                raise ValueError(f'official source/unit/frequency mismatch: {key}')
            value = float(update['value'])
            if not math.isfinite(value):
                raise ValueError('nonfinite official value')
            merged = {str(d)[:10]: v for d, v in item['observations']}
            if day in merged and not math.isclose(float(merged[day]), value, rel_tol=1e-10, abs_tol=1e-6):
                raise ValueError(f'provider/official release conflict requires reconciliation: {key} {day}')
            merged[day] = value
            item['observations'] = sorted(merged.items())
            item.setdefault('observationSources', {})[day] = {
                'kind': 'official_release', 'publisher': '国家统计局',
                'url': url, 'publishedAt': published, 'providerId': None,
            }
            output.setdefault('officialReleaseOverrides', {})[key] = item['observationSources'][day]
    return output
