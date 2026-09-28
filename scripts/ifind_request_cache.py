"""Shared, disk-backed iFinD request budget and cache for every pipeline process.

Cache hits never bypass caller ID/unit validation. Negative replies are cached
briefly; quota exhaustion pauses all processes until the next day or an explicit
manual reset. The ledger counts network attempts, not provider billing credits.
"""
import hashlib
import json
import os
import time
import uuid
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo


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

    def call(server, tool, params):
        if server != 'edb' or tool != 'get_edb_data':
            return raw_call(server, tool, params)
        params = dict(params)
        bypass = params.pop('_cache_bypass', False)
        identity = params.pop('_cache_identity', None)
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
            return entry['response']
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
