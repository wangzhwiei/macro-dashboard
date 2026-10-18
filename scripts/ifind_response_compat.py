"""Normalize the metadata+Markdown EDB response without guessing indicator IDs."""
import copy
import json
import re
from datetime import date
from decimal import Decimal

FIELDS = {"指标名称": "indexName", "频率": "freq", "单位": "unit",
          "所属节点": "node", "数据来源": "dataSource", "国家地区": "country",
          "起始日期": "startDate", "终止日期": "endDate"}


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


def bind_identity(meta, catalog):
    if any(k not in meta or (not meta[k] and k != '国家地区') for k in FIELDS):
        raise RuntimeError('iFinD metadata incomplete; cannot verify identity')
    matches = [x for x in catalog if all(str(x.get(v, '')) == str(meta[k]) for k, v in FIELDS.items())]
    if len(matches) != 1 or not re.fullmatch(r'[MS]\d+', str(matches[0].get('displayId', ''))):
        raise RuntimeError('iFinD metadata does not uniquely match catalog identity')
    return matches[0]


def parse_table(answer, meta):
    lines = answer.strip().splitlines()
    if len(lines) < 3 or any(not x.startswith('|') or not x.endswith('|') for x in lines):
        raise RuntimeError('iFinD table malformed or truncated')
    cells = [[c.strip() for c in line[1:-1].split('|')] for line in lines]
    expected = f"{meta['指标名称']}（单位：{meta['单位']}）"
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


def normalize(response, search):
    if not response.get('ok'):
        return response
    parsed = unwrap(response)
    data = parsed.get('data', {})
    if data.get('datas') or not data.get('indicator_description'):
        return response
    descriptions = data['indicator_description']
    if len(descriptions) != 1:
        raise RuntimeError('iFinD multi-indicator text response rejected')
    meta = descriptions[0]
    catalog = parse_search(search(meta))
    identity = bind_identity(meta, catalog)
    rows = parse_table(data.get('answer', ''), meta)
    attr = {'index_id': identity['displayId'], 'freq': meta['频率'], 'unit': meta['单位'],
            'start_time': meta['起始日期'], 'end_time': meta['终止日期'], 'data_source': meta['数据来源']}
    data['datas'] = [{'data': {'attrs': {meta['指标名称']: attr}, 'data': rows},
                      'extra': {'index_id': identity['displayId']}}]
    data['identityVerification'] = {'method': 'exact_catalog_metadata_join', 'catalog': identity,
                                  'note': 'ID verified via search metadata, not returned directly by get_edb_data'}
    result = copy.deepcopy(response)
    result['data']['result']['content'][0]['text'] = json.dumps(parsed, ensure_ascii=False)
    return result
