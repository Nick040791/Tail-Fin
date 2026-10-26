#!/usr/bin/env python3
"""Built-in MCP Server for Local Workspace & PC System Status (JSON-RPC 2.0 over stdio).

Provides sandboxed local document access and system telemetry via the Model Context Protocol.
"""

import json
import os
import platform
import shutil
import sys

WORKSPACE_ROOT = os.path.expanduser(os.environ.get("FIN_WORKSPACE_DIR", "~/Documents"))

MCP_TOOLS = [
    {
        "name": "system_status",
        "description": "Check PC system status (CPU load, RAM, disk space, OS).",
        "inputSchema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "workspace_list_files",
        "description": "List files inside the local Documents workspace directory.",
        "inputSchema": {
            "type": "object",
            "properties": {
                " subpath": {"type": "string", "description": "Optional relative subdirectory"}
            },
            "required": [],
        },
    },
    {
        "name": "workspace_read_file",
        "description": "Read a text or markdown file from the local Documents workspace.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "filename": {"type": "string", "description": "Relative filename in Documents"}
            },
            "required": ["filename"],
        },
    },
    {
        "name": "workspace_write_file",
        "description": "Write or update a text/markdown file in the local Documents workspace (requires user approval).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "filename": {"type": "string", "description": "Relative filename in Documents"},
                "content": {"type": "string", "description": "Text content to write"},
            },
            "required": ["filename", "content"],
        },
    },
]


def _safe_path(rel_path):
    os.makedirs(WORKSPACE_ROOT, exist_ok=True)
    base = os.path.realpath(WORKSPACE_ROOT)
    target = os.path.realpath(os.path.join(base, (rel_path or "").lstrip("/")))
    if not (target == base or target.startswith(base + os.sep)):
        raise ValueError("Path is outside the allowed Documents workspace.")
    return target


def _run_tool(name, args):
    if name == "system_status":
        load1, load5, load15 = os.getloadavg()
        total_d, used_d, free_d = shutil.disk_usage("/")
        mem_info = {}
        if os.path.exists("/proc/meminfo"):
            with open("/proc/meminfo", "r", encoding="utf-8") as f:
                for line in f:
                    parts = line.split(":")
                    if len(parts) == 2:
                        mem_info[parts[0].strip()] = parts[1].strip()
        return (
            f"Host: {platform.node()} ({platform.system()} {platform.release()})\n"
            f"Load Average: {load1:.2f}, {load5:.2f}, {load15:.2f}\n"
            f"Memory Total: {mem_info.get('MemTotal', 'unknown')} | Available: {mem_info.get('MemAvailable', 'unknown')}\n"
            f"Disk Free: {free_d // (1024**3)} GB / {total_d // (1024**3)} GB"
        )
    if name == "workspace_list_files":
        target = _safe_path(args.get("subpath", ""))
        if not os.path.isdir(target):
            return f"Directory not found: {target}"
        entries = sorted(os.listdir(target))[:50]
        return f"Workspace ({target}):\n" + ("\n".join(f"- {e}" for e in entries) if entries else "(empty)")
    if name == "workspace_read_file":
        target = _safe_path(args.get("filename", ""))
        if not os.path.isfile(target):
            return f"File not found: {target}"
        with open(target, "r", encoding="utf-8", errors="replace") as f:
            return f.read(10000)
    if name == "workspace_write_file":
        target = _safe_path(args.get("filename", ""))
        os.makedirs(os.path.dirname(target), exist_ok=True)
        content = str(args.get("content", ""))
        with open(target, "w", encoding="utf-8") as f:
            f.write(content)
        return f"Saved {len(content)} characters to {target}"
    return f"Unknown workspace MCP tool: {name}"


def main():
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except ValueError:
            continue
        req_id = req.get("id")
        method = req.get("method", "")
        params = req.get("params") or {}

        if method == "initialize":
            resp = {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {"tools": {}},
                    "serverInfo": {"name": "fin-workspace-mcp", "version": "2.0.0"},
                },
            }
        elif method == "notifications/initialized":
            continue
        elif method == "tools/list":
            resp = {"jsonrpc": "2.0", "id": req_id, "result": {"tools": MCP_TOOLS}}
        elif method == "tools/call":
            try:
                out = _run_tool(params.get("name", ""), params.get("arguments") or {})
                resp = {"jsonrpc": "2.0", "id": req_id, "result": {"content": [{"type": "text", "text": out}]}}
            except Exception as e:  # noqa: BLE001
                resp = {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {"content": [{"type": "text", "text": f"Error: {e}"}], "isError": True},
                }
        elif req_id is not None:
            resp = {"jsonrpc": "2.0", "id": req_id, "error": {"code": -32601, "message": "Method not found"}}
        else:
            continue

        sys.stdout.write(json.dumps(resp) + "\n")
        sys.stdout.flush()


if __name__ == "__main__":
    main()
