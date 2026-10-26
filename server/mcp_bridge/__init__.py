"""MCP (Model Context Protocol) Client Host Bridge for Fin Assistant Server.

Supports connecting to external MCP servers configured in server/mcp_servers.json
over JSON-RPC 2.0 (stdio and HTTP), discovering tools, and enforcing Human-in-the-Loop
approvals on restricted MCP operations.
"""

import json
import os
import subprocess
import sys
import urllib.request

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import db
MCP_CONFIG_PATH = os.path.join(HERE, "mcp_servers.json")

_mcp_tool_cache = {"loaded": False, "defs": [], "routes": {}}


def load_mcp_config():
    if not os.path.exists(MCP_CONFIG_PATH):
        return {}
    try:
        with open(MCP_CONFIG_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data.get("mcpServers", {}) if isinstance(data, dict) else {}
    except Exception:  # noqa: BLE001
        return {}


def _stdio_rpc(cfg, requests_list, timeout=10):
    """Run a quick JSON-RPC session with a stdio MCP server."""
    cmd = [cfg.get("command")] + list(cfg.get("args") or [])
    env = os.environ.copy()
    for k, v in (cfg.get("env") or {}).items():
        if isinstance(v, str) and v.startswith("${") and v.endswith("}"):
            env_key = v[2:-1]
            env[k] = os.environ.get(env_key, "")
        else:
            env[k] = str(v)

    proc = subprocess.Popen(
        cmd,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        cwd=os.path.dirname(HERE),
        env=env,
    )
    try:
        input_payload = "\n".join(json.dumps(r) for r in requests_list) + "\n"
        out, _ = proc.communicate(input=input_payload, timeout=timeout)
        responses = {}
        for line in (out or "").splitlines():
            line = line.strip()
            if not line.startswith("{"):
                continue
            try:
                obj = json.loads(line)
                if "id" in obj:
                    responses[obj["id"]] = obj
            except ValueError:
                continue
        return responses
    finally:
        try:
            proc.kill()
        except Exception:  # noqa: BLE001
            pass


def _http_rpc(url, payload, timeout=10):
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def discover_mcp_tools(force_reload=False):
    """Discover tools from all enabled MCP servers in mcp_servers.json."""
    if _mcp_tool_cache["loaded"] and not force_reload:
        return _mcp_tool_cache["defs"], _mcp_tool_cache["routes"]

    _mcp_tool_cache["loaded"] = True
    _mcp_tool_cache["defs"] = []
    _mcp_tool_cache["routes"] = {}

    servers = load_mcp_config()
    for srv_name, cfg in servers.items():
        if not isinstance(cfg, dict) or not cfg.get("enabled", False):
            continue
        init_req = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "fin-server", "version": "2.0.0"},
            },
        }
        initialized_notif = {"jsonrpc": "2.0", "method": "notifications/initialized"}
        list_req = {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}}

        try:
            if cfg.get("url"):
                _http_rpc(cfg["url"], init_req)
                resp = _http_rpc(cfg["url"], list_req)
            else:
                res_map = _stdio_rpc(cfg, [init_req, initialized_notif, list_req])
                resp = res_map.get(2, {})

            tools = (resp.get("result") or {}).get("tools") or []
            req_approval = set(cfg.get("require_approval") or [])
            for t in tools:
                raw_name = t.get("name", "")
                if not raw_name:
                    continue
                namespaced = f"mcp__{srv_name.replace('-', '_')} __{raw_name}".replace(" ", "")
                schema = t.get("inputSchema") or {"type": "object", "properties": {}}
                _mcp_tool_cache["defs"].append(
                    {
                        "type": "function",
                        "function": {
                            "name": namespaced,
                            "description": f"[MCP:{srv_name}] {t.get('description', raw_name)}",
                            "parameters": schema,
                        },
                    }
                )
                _mcp_tool_cache["routes"][namespaced] = {
                    "server": srv_name,
                    "tool": raw_name,
                    "config": cfg,
                    "require_approval": raw_name in req_approval,
                }
        except Exception as e:  # noqa: BLE001
            sys.stderr.write(f"[mcp] Failed to discover tools from '{srv_name}': {e}\n")

    return _mcp_tool_cache["defs"], _mcp_tool_cache["routes"]


def execute_mcp_tool_direct(server_name, tool_name, arguments):
    """Execute an MCP tool call directly without re-staging approval."""
    servers = load_mcp_config()
    cfg = servers.get(server_name)
    if not cfg:
        return f"MCP server '{server_name}' not found."

    init_req = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "fin-server", "version": "2.0.0"},
        },
    }
    initialized_notif = {"jsonrpc": "2.0", "method": "notifications/initialized"}
    call_req = {
        "jsonrpc": "2.0",
        "id": 2,
        "method": "tools/call",
        "params": {"name": tool_name, "arguments": arguments or {}},
    }
    try:
        if cfg.get("url"):
            resp = _http_rpc(cfg["url"], call_req, timeout=20)
        else:
            res_map = _stdio_rpc(cfg, [init_req, initialized_notif, call_req], timeout=20)
            resp = res_map.get(2, {})

        result = resp.get("result") or {}
        content_list = result.get("content") or []
        texts = [c.get("text", "") for c in content_list if isinstance(c, dict) and "text" in c]
        if texts:
            return "\n".join(texts)
        return json.dumps(result)
    except Exception as e:  # noqa: BLE001
        return f"MCP tool '{server_name}/{tool_name}' failed: {e}"


def call_mcp_tool(namespaced_name, arguments):
    """Invoke a discovered MCP tool, staging for approval if configured."""
    _, routes = discover_mcp_tools()
    route = routes.get(namespaced_name)
    if not route:
        return f"Unknown MCP tool: {namespaced_name}"

    srv_name = route["server"]
    tool_name = route["tool"]
    if route.get("require_approval"):
        summary = f"MCP {srv_name}.{tool_name}({json.dumps(arguments)[:120]})"
        rec = db.create_pending_approval(
            "mcp_call",
            summary,
            {"server": srv_name, "tool": tool_name, "arguments": arguments},
        )
        aid = rec["id"] if rec else "????"
        return (
            f"🔌 PENDING MCP TOOL APPROVAL [#{aid}]\n"
            f"Server: {srv_name} | Tool: {tool_name}\n"
            f"Arguments: {json.dumps(arguments, indent=2)}\n"
            f"Ask the user to confirm in natural language ('yes, run it') or via `/approve {aid}`."
        )

    return execute_mcp_tool_direct(srv_name, tool_name, arguments)


def format_mcp_status():
    """Return status overview of configured MCP servers for /mcp."""
    servers = load_mcp_config()
    if not servers:
        return "No MCP servers configured in server/mcp_servers.json."
    defs, _ = discover_mcp_tools()
    lines = ["🔌 MCP (Model Context Protocol) Status:"]
    for name, cfg in servers.items():
        enabled = cfg.get("enabled", False)
        state = "🟢 Enabled" if enabled else "⚪ Disabled (set \"enabled\": true in server/mcp_servers.json)"
        desc = cfg.get("description", "")
        lines.append(f"- {name}: {state}" + (f" — {desc}" if desc else ""))
    lines.append(f"\nDiscovered active MCP tools: {len(defs)}")
    lines.append("Fin also exposes its own MCP server via: `python3 -m server.mcp_bridge.fin_mcp_server`")
    return "\n".join(lines)
