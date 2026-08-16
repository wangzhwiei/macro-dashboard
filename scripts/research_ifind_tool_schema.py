#!/usr/bin/env python3
"""Print the iFinD EDB MCP tool schema without exposing credentials."""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path


skill = Path(os.environ["IFIND_SKILL_DIR"])
sys.path.insert(0, str(skill))
previous = Path.cwd()
os.chdir(skill)
try:
    import call as ifind
finally:
    os.chdir(previous)

if "edb" not in ifind._sessions:
    init_payload = {
        "jsonrpc": "2.0", "id": ifind._next_id("edb"), "method": "initialize",
        "params": {"protocolVersion": "2025-03-26", "capabilities": {},
                   "clientInfo": {"name": "trade-research", "version": "1.0"}},
    }
    last_error = None
    for attempt in range(5):
        try:
            response, data = ifind._post("edb", init_payload, timeout=45)
            response.raise_for_status()
            session = response.headers.get("Mcp-Session-Id")
            if not session:
                raise RuntimeError(f"missing MCP session: {data}")
            ifind._sessions["edb"] = session
            try:
                ifind._post("edb", {"jsonrpc": "2.0", "method": "notifications/initialized"}, timeout=15)
            except Exception:
                pass
            break
        except Exception as error:
            last_error = error
            time.sleep(2 ** attempt)
    else:
        raise last_error
payload = {
    "jsonrpc": "2.0",
    "id": ifind._next_id("edb"),
    "method": "tools/list",
    "params": {},
}
response, data = ifind._post("edb", payload)
response.raise_for_status()
print(json.dumps(data, ensure_ascii=False, indent=2))
