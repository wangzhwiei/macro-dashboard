"""Shared, disk-backed iFinD request budget and cache for every pipeline process.

Cache hits never bypass caller ID/unit validation. Negative replies are cached
briefly; quota exhaustion pauses all processes until the next day or an explicit
manual reset. The ledger counts network attempts, not provider billing credits.
"""
import hashlib
import json
import os
import re
import time
import uuid
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
try:
    from scripts.ifind_response_compat import normalize, parse_search, bind_identity
except ModuleNotFoundError:
    from ifind_response_compat import normalize, parse_search, bind_identity


def root():
    base = os.environ.get('MACRO_DATA_CACHE_DIR')
    return (Path(base) if base else Path(__file__).resolve().parents[1] / 'data_cache') / 'requests'


def today():
    return datetime.now(ZoneInfo('Asia/Shanghai')).date().isoformat()


def read(path):
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return {}


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    tmp.write_text(json.dumps(value, ensure_ascii=False), encoding='utf-8')
    tmp.replace(path)


def reset_generation():
    # Invalidate only this application's request cache, without deleting history.
    write(root() / 'generation.json', {'value': uuid.uuid4().hex})
    write(root() / 'quota.json', {})


def quota_blocked():
    return read(root() / 'quota.json').get('day') == today()


def reject_quota(response, key):
    answer = str(payload(response).get('answer', ''))
    if any(term in answer for term in ('用量已耗尽', '额度已耗尽', '请求次数上限')):
        write(root() / 'quota.json', {'day': today()})
        ledger('quota_exhausted', key)
        raise RuntimeError('iFinD接口额度耗尽（包括目录搜索工具）：暂停新增调用，恢复额度后重试')


def ledger(event, key, identity=None):
    path = root() / 'usage.jsonl'
    path.parent.mkdir(parents=True, exist_ok=True)
    row = {'time': datetime.now(ZoneInfo('Asia/Shanghai')).isoformat(),
           'event': event, 'request_key': key, 'provider_id': (identity or {}).get('id'),
           'consumer': os.environ.get('IFIND_CONSUMER', 'direct')}
    with path.open('a', encoding='utf-8') as handle:
        handle.write(json.dumps(row, ensure_ascii=False) + '\n')


def payload(result):
    try:
        return json.loads(result['data']['result']['content'][0]['text']).get('data', {})
    except (KeyError, IndexError, TypeError, ValueError):
        return {}


def matches(data, identity):
    if not identity or not identity.get('id') or not identity.get('frequency'):
        return False
    datasets = data.get('datas', [])
    if len(datasets) != 1:
        return False
    table = datasets[0].get('data', {})
    attrs = list(table.get('attrs', {}).values())
    return (len(attrs) == 1 and attrs[0].get('index_id') == identity['id']
            and attrs[0].get('freq') == identity['frequency'] and bool(table.get('data')))


def wrap_ifind_call(raw_call):
    if getattr(raw_call, '_shared_cache', False) is True:
        return raw_call

    def compatible(result, expected_id=None):
        def search(meta):
            tag = hashlib.sha256(json.dumps([today(), meta, expected_id, read(root() / 'generation.json').get('value', '')], sort_keys=True).encode()).hexdigest()
            path = root() / 'identity' / (tag + '.json')
            # A catalog search often returns several indicators. Reuse any
            # prior catalog with an exact eight-field match, including end date.
            for saved in (root() / 'identity').glob('*.json'):
                prior = read(saved)
                try:
                    matched = bind_identity(meta, parse_search(prior))
                    if expected_id and matched['displayId'] != expected_id:
                        continue
                    ledger('identity_cache_hit', tag)
                    return prior
                except (RuntimeError, KeyError, ValueError, TypeError):
                    continue
            cached = read(path)
            if cached:
                reject_quota(cached, tag)
                return cached
            if quota_blocked():
                raise RuntimeError('iFinD接口额度耗尽：暂停目录搜索')
            ledger('identity_search_attempt', tag)
            query = f"指标编码{expected_id}，{meta['指标名称']}" if expected_id else meta['指标名称']
            response = raw_call('edb', 'search_edb', {'query': query})
            write(path, response)
            reject_quota(response, tag)
            return response
        return normalize(result, search)

    def call(server, tool, params):
        if server != 'edb' or tool != 'get_edb_data':
            return raw_call(server, tool, params)
        params = dict(params)
        bypass = params.pop('_cache_bypass', False)
        identity = params.pop('_cache_identity', None)
        ids = re.findall(r'(?<![A-Za-z0-9])[MS]\d{8,}(?![A-Za-z0-9])', str(params.get('query', '')))
        expected_id = (identity or {}).get('id') or (ids[0] if len(set(ids)) == 1 else None)
        day = today()
        epoch = read(root() / 'generation.json').get('value', '')
        key = hashlib.sha256(json.dumps([server, tool, params, day, epoch], sort_keys=True).encode()).hexdigest()
        exact = root() / 'exact' / (key + '.json')
        entry = read(exact)
        # Only successful raw datasets get the day cache; failures expire after 15m.
        if not bypass and entry.get('expires', 0) > time.time():
            ledger('cache_hit', key, identity)
            if 'error' in entry:
                raise RuntimeError(entry['error'])
            return compatible(entry['response'], expected_id)
        shared_path = None
        if identity and identity.get('start') and identity.get('end'):
            tag = [identity['id'], identity['frequency'], day, epoch]
            shared_path = root() / 'series' / (hashlib.sha256(json.dumps(tag).encode()).hexdigest() + '.json')
            shared = read(shared_path)
            if (not bypass and shared.get('start', '9999') <= identity['start']
                    and shared.get('end', '') >= identity['end']
                    and matches(payload(shared.get('response', {})), identity)):
                ledger('series_cache_hit', key, identity)
                return shared['response']
        if quota_blocked():
            ledger('quota_skip', key, identity)
            raise RuntimeError('iFinD接口额度耗尽：全流程暂停取数；恢复额度后请选择强制重新取数')
        ledger('network_attempt', key, identity)
        try:
            result = raw_call(server, tool, params)
        except Exception as error:
            # Transport failures retain the caller's bounded retry behavior.
            ledger('transport_error', key, identity)
            raise
        data = payload(result)
        answer = str(data.get('answer', ''))
        if '用量已耗尽' in answer or '额度已耗尽' in answer:
            write(root() / 'quota.json', {'day': day})
            ledger('quota_exhausted', key, identity)
            raise RuntimeError('iFinD接口额度耗尽：全流程暂停取数；恢复额度后请选择强制重新取数')
        # Preserve the original answer as evidence, even when normalization fails.
        write(root() / 'raw' / (key + '.json'), result)
        result = compatible(result, expected_id)
        data = payload(result)
        reject_quota(result, key)
        good = bool(result.get('ok') and data.get('datas'))
        # Wrong candidates must not poison a same-day identity cache.
        accepted = good and (not identity or matches(data, identity))
        write(exact, {'response': result, 'expires': time.time() + (86400 if accepted else 900)})
        if accepted and shared_path:
            write(shared_path, {'response': result, 'start': identity['start'], 'end': identity['end']})
        ledger('network_success' if accepted else 'unvalidated_response', key, identity)
        return result
    call._shared_cache = True
    return call
