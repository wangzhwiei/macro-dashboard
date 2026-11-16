"""Non-publishing cloud gate: test verified TLS before sending any credential."""
import json
import socket
import ssl
from datetime import datetime, timezone
from pathlib import Path

HOST = 'api-mcp.51ifind.com'
report = {'checkedAt': datetime.now(timezone.utc).isoformat(), 'productionWrites': False}
try:
    with socket.create_connection((HOST, 8643), timeout=20) as connection:
        with ssl.create_default_context().wrap_socket(connection, server_hostname=HOST) as secured:
            report.update(tlsVerified=True, tlsVersion=secured.version())
except Exception as error:
    report.update(tlsVerified=False, errorType=type(error).__name__, error=str(error))
Path('outputs').mkdir(exist_ok=True)
Path('outputs/cloud-preflight.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
print(json.dumps(report))
if not report['tlsVerified']:
    raise SystemExit('Cloud migration blocked: trusted TLS connection unavailable; no credential sent.')
