#!/usr/bin/env python3
"""Fin Assistant MCP Server (JSON-RPC 2.0 over stdio).

Exposes Fin's tools (Phone SMS, PostgreSQL + pgvector Memory, Google Drive,
Gmail, Calendar, Contacts, Tasks, Web) as a standard Model Context Protocol
server for external MCP clients (Orca, Claude Desktop, Cursor, Antigravity).
"""

import json
import os
import sys

# Ensure server dir is on sys.path
SERVER_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if SERVER_DIR not in sys.path:
    sys.path.insert(0, SERVER_DIR)

from tools import NATIVE_TOOL_DEFS, NATIVE_TOOL_FUNCS


def _mcp_tools_list():
    mcp_tools = []
    for t in NATIVE_TOOL_DEFS:
        fn = t.get("function", {})
        mcp_tools.append(
            {
                "name": fn.get("name", ""),
                "description": fn.get("description", ""),
                "inputSchema": fn.get("parameters", {"type": "object", "properties": {}}),
            }
        )
    return mcp_tools


def handle_rpc_request(req):
    req_id = req.get("id")
    method = req.get("method", "")
    params = req.get("params") or {}

    if method == "initialize":
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "fin-assistant-mcp", "version": "2.0.0"},
            },
        }
    if method == "notifications/initialized":
        return None
    if method == "tools/list":
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {"tools": _mcp_tools_list()},
        }
    if method == "tools/call":
        name = params.get("name", "")
        args = params.get("arguments") or {}
        func = NATIVE_TOOL_FUNCS.get(name)
        if func is None:
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "content": [{"type": "text", "text": f"Unknown tool: {name}"}],
                    "isError": True,
                },
            }
        try:
            text_out = str(func(args))
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {"content": [{"type": "text", "text": text_out}]},
            }
        except Exception as e:  # noqa: BLE001
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "content": [{"type": "text", "text": f"Tool {name} failed: {e}"}],
                    "isError": True,
                },
            }

    if req_id is not None:
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "error": {"code": -32601, "message": f"Method not found: {method}"},
        }
    return None


def main():
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except ValueError:
            continue
        resp = handle_rpc_request(req)
        if resp is not None:
            sys.stdout.write(json.dumps(resp) + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    main()
