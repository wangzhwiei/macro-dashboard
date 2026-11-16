"""Portable EDB-only MCP client. Credentials are injected by the cloud runner."""
import json
import os
import requests

ENDPOINT = 'https://api-mcp.51ifind.com:8643/ds-mcp-servers/hexin-ifind-ds-edb-mcp'
_session = None
_sequence = 0

def _post(method, params):
    global _sequence
    _sequence += 1
    token = os.environ.get('IFIND_AUTH_TOKEN', '')
    if not token:
        raise RuntimeError('Missing IFIND_AUTH_TOKEN secret')
    headers = {'Authorization': token, 'Accept': 'application/json, text/event-stream'}
    if _session:
        headers['Mcp-Session-Id'] = _session
    body = {'jsonrpc': '2.0', 'method': method, 'params': params}
    if not method.startswith('notifications/'):
        body['id'] = _sequence
    # TLS validation is mandatory; never copy the legacy verify=False setting.
    response = requests.post(ENDPOINT, headers=headers, json=body, timeout=(15, 90))
    response.raise_for_status()
    if not response.content:
        return response, {}
    if 'text/event-stream' in response.headers.get('Content-Type', ''):
        messages = [json.loads(line[5:].strip()) for line in response.text.splitlines() if line.startswith('data:')]
        data = next((m for m in messages if m.get('id') == _sequence), {})
    else:
        data = response.json()
    return response, data

def call(server_type, tool_name, params):
    global _session
    if server_type != 'edb' or tool_name != 'get_edb_data':
        raise ValueError('Cloud runtime only allows edb/get_edb_data')
    if _session is None:
        response, result = _post('initialize', {
            'protocolVersion': '2025-03-26', 'capabilities': {},
            'clientInfo': {'name': 'macro-dashboard-cloud', 'version': '1.0.0'},
        })
        if result.get('error'):
            raise RuntimeError('MCP initialization rejected')
        _session = response.headers.get('Mcp-Session-Id')
        if not _session:
            raise RuntimeError('MCP session header absent')
        _post('notifications/initialized', {})
    response, data = _post('tools/call', {'name': tool_name, 'arguments': params})
    return {'ok': 'error' not in data, 'status_code': response.status_code, 'data': data}
