"""Normalize the metadata+Markdown EDB response without guessing indicator IDs."""
import copy
import json
import re
from datetime import date
from decimal import Decimal

FIELDS = {"指标名称": "indexName", "频率": "freq", "单位": "unit",
          "所属节点": "node", "数据来源": "dataSource", "国家地区": "country",
          "起始日期": "startDate", "终止日期": "endDate"}

UNIT_DIMENSIONS = {'元': 'money', '万元': 'money', '亿元': 'money', '万亿元': 'money',
                   '吨': 'mass', '千吨': 'mass', '万吨': 'mass',
                   '桶': 'barrel', '千桶': 'barrel', '万桶': 'barrel',
                   '平方米': 'area', '万平方米': 'area'}


def unwrap(response):
    return json.loads(response['data']['result']['content'][0]['text'])


def parse_search(response):
    if not response.get('ok'):
        raise RuntimeError('iFinD identity search failed')
    data = unwrap(response).get('data', {})
    text = data.get('data', '')
    blocks = re.findall(r'```json\s*(.*?)\s*```', text, re.S)
    if len(blocks) != 1:
        raise RuntimeError('iFinD identity search has no unique JSON catalog')
    items = json.loads(blocks[0])
    if not isinstance(items, list):
        raise RuntimeError('iFinD identity catalog is not a list')
    return items


def bind_identity(meta, catalog, archival=False):
    if any(k not in meta or (not meta[k] and k not in ('国家地区', '单位')) for k in FIELDS):
        raise RuntimeError('iFinD metadata incomplete; cannot verify identity')
    fields = {k: v for k, v in FIELDS.items() if not (archival and k == '终止日期')}
    def equal(k, v, item):
        if archival and k == '单位':
            a, b = str(item.get(v, '')), str(meta[k])
            return a == b or (a in UNIT_DIMENSIONS and b in UNIT_DIMENSIONS and UNIT_DIMENSIONS[a] == UNIT_DIMENSIONS[b])
        return str(item.get(v, '')) == str(meta[k])
    matches = [x for x in catalog if all(equal(k, v, x) for k, v in fields.items())]
    if archival:
        matches = list({x.get('displayId'): x for x in matches}.values())
    if len(matches) != 1 or not re.fullmatch(r'[MSG]\d+', str(matches[0].get('displayId', ''))):
        raise RuntimeError('iFinD metadata does not uniquely match catalog identity')
    return matches[0]


def parse_table(answer, meta):
    lines = answer.strip().splitlines()
    if len(lines) < 3 or any(not x.startswith('|') or not x.endswith('|') for x in lines):
        raise RuntimeError('iFinD table malformed or truncated')
    cells = [[c.strip() for c in line[1:-1].split('|')] for line in lines]
    expected = f"{meta['指标名称']}（单位：{meta['单位']}）" if meta['单位'] else meta['指标名称']
    if cells[0] != ['日期', expected] or len(cells[1]) != 2 or any(not re.fullmatch(r':?-{3,}:?', c) for c in cells[1]):
        raise RuntimeError('iFinD table header differs from verified metadata')
    rows = {}
    for row in cells[2:]:
        if len(row) != 2:
            raise RuntimeError('iFinD multi-column/invalid row rejected')
        day = date.fromisoformat(row[0]).isoformat()
        compact = day.replace('-', '')
        if not str(meta['起始日期']) <= compact <= str(meta['终止日期']):
            raise RuntimeError('iFinD observation outside metadata coverage')
        if row[1] in ('--', '-', '', 'null', 'None', 'N/A'):
            continue
        match = re.fullmatch(r'([+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?)(万亿|亿|万)?', row[1])
        if not match:
            raise RuntimeError('iFinD unsupported numeric representation')
        value = Decimal(match[1]) * {'万亿': Decimal('1e12'), '亿': Decimal('1e8'), '万': Decimal('1e4'), None: Decimal(1)}[match[2]]
        if not value.is_finite() or (day in rows and rows[day] != float(value)):
            raise RuntimeError('iFinD conflicting or nonfinite observation')
        rows[day] = float(value)
    if not rows:
        raise RuntimeError('iFinD table contains no numeric observations')
    return [[d, rows[d]] for d in sorted(rows)]


def normalize(response, search=None, catalog=None):
    if not response.get('ok'):
        return response
    parsed = unwrap(response)
    data = parsed.get('data', {})
    if data.get('datas') or not data.get('indicator_description'):
        return response
    descriptions = data['indicator_description']
    if len(descriptions) != 1:
        raise RuntimeError('iFinD multi-indicator text response rejected')
    meta = dict(descriptions[0])
    # Dimensionless indices omit the unit field in the new format. They only
    # bind when the archived provider catalog also explicitly has an empty unit.
    if catalog is not None and '单位' not in meta:
        meta['单位'] = ''
    archival = catalog is not None
    catalog = catalog if archival else parse_search(search(meta))
    identity = bind_identity(meta, catalog, archival=archival)
    rows = parse_table(data.get('answer', ''), meta)
    attr = {'index_id': identity['displayId'], 'freq': meta['频率'], 'unit': meta['单位'],
            'start_time': meta['起始日期'], 'end_time': meta['终止日期'], 'data_source': meta['数据来源'],
            'country': meta['国家地区'], 'node': meta['所属节点']}
    data['datas'] = [{'data': {'columns': ['日期', meta['指标名称']], 'attrs': {meta['指标名称']: attr}, 'data': rows},
                      'extra': {'index_id': identity['displayId']}}]
    data['identityVerification'] = {'method': 'saved_provider_metadata_join' if archival else 'exact_catalog_metadata_join', 'catalog': identity,
                                  'note': 'ID matched against previously returned provider metadata, not echoed from the query; observation end date may advance'}
    result = copy.deepcopy(response)
    result['data']['result']['content'][0]['text'] = json.dumps(parsed, ensure_ascii=False)
    return result


def saved_catalog(cache_root):
    """Read old provider-issued IDs; never infer an ID from a query or name."""
    output = []
    from pathlib import Path
    archive = Path(__file__).resolve().parents[1] / 'data/trade-model/fixed_factor_provider_catalog.json'
    if archive.exists():
        output.extend(json.loads(archive.read_text(encoding='utf-8'))['catalog'])
    # These provider attrs were saved only after the original trade fetcher
    # checked returned name, ID, frequency, unit, country and source exactly.
    from pathlib import Path
    trade_meta = Path(__file__).resolve().parents[1] / 'data/trade-model/trade_targets_ifind.meta.json'
    if trade_meta.exists():
        for entry in json.loads(trade_meta.read_text(encoding='utf-8-sig')).get('series', {}).values():
            a = entry.get('attrs', {})
            output.append({'displayId': a.get('index_id'), 'indexName': entry.get('query'),
                           'freq': a.get('freq'), 'unit': a.get('unit'), 'node': a.get('node'),
                           'country': a.get('country'), 'dataSource': a.get('data_source'),
                           'startDate': a.get('start_time'), 'endDate': a.get('end_time')})
    for folder in ('exact', 'identity'):
        for path in (cache_root / folder).glob('*.json'):
            try:
                entry = json.loads(path.read_text(encoding='utf-8'))
                response = entry.get('response', entry)
                data = unwrap(response).get('data', {})
                if folder == 'identity':
                    output.extend(parse_search(response))
                    continue
                if data.get('identityVerification'):
                    continue
                for item in data.get('datas', []):
                    for name, attr in item.get('data', {}).get('attrs', {}).items():
                        if not attr.get('index_id'):
                            continue
                        output.append({'displayId': attr['index_id'], 'indexName': name,
                                       'freq': attr.get('freq'), 'unit': attr.get('unit'),
                                       'node': attr.get('node'), 'country': attr.get('country'),
                                       'dataSource': attr.get('data_source'),
                                       'startDate': attr.get('start_time'), 'endDate': attr.get('end_time')})
            except (ValueError, KeyError, TypeError, RuntimeError, OSError, IndexError):
                continue
    return output
