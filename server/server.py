#!/usr/bin/env python3
"""Fin agent server — runs on the PC next to Ollama & PostgreSQL (pgvector).

Exposes the HTTP API the Fin Android app talks to:
  GET  /health       -> {"status": "ok", "model": ..., "db": ..., "skills": ..., "tools": ...}
  GET  /models       -> {"models": [...], "current": ...} (Ollama + Cloud)
  POST /api/chat     -> {"messages": [{"role": "user", "content": "..."}],
                         "model": "<optional per-request model>"}
                        replies with newline-delimited JSON:
                          {"delta": "..."} ... data: [DONE]
                        Supports Natural-Language Approvals ("yes, send it", "cancel"),
                        deterministic slash commands, modular SKILL.md injection,
                        PostgreSQL + pgvector hybrid memory, and MCP tools.
  POST /api/messages -> {"messages": [{"address","body","date","type"}]}
                        stores SMS synced from the phone in PostgreSQL + messages.json
  GET  /api/messages?q=<text>&limit=20 -> stored messages, newest first
"""

import datetime
import hashlib
import hmac
import json
import os
import secrets
import sys
import threading
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)


def load_dotenv():
    """Tiny .env loader (stdlib only). Sets vars only if not already set.
    Secret values are never printed or logged."""
    path = os.path.join(HERE, ".env")
    if not os.path.exists(path):
        return
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, value = line.partition("=")
                key = key.strip()
                value = value.strip()
                if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
                    value = value[1:-1]
                if key and key not in os.environ:
                    os.environ[key] = value
    except OSError:
        pass


load_dotenv()

import db
import mcp_bridge
import plugins
import skills
from tools import (
    NATIVE_TOOL_DEFS,
    NATIVE_TOOL_FUNCS,
    execute_approved_action,
    format_ms_date,
    google_services,
    tool_calendar_create,
    tool_calendar_list,
    tool_drive_read,
    tool_drive_search,
    tool_gmail_prepare_send,
    tool_gmail_read,
    tool_gmail_search,
    tool_messages_recent,
    tool_messages_search,
    tool_messages_thread,
)

PORT = int(os.environ.get("FIN_PORT", "8080"))
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434").rstrip("/")
MODEL = os.environ.get("FIN_MODEL", "Fin:latest")
NUM_CTX = int(os.environ.get("FIN_NUM_CTX", "32768"))
PROVIDER = os.environ.get("FIN_PROVIDER", "ollama").strip().lower() or "ollama"
MODEL_STATE_FILE = os.path.join(HERE, "selected_model.txt")


def get_default_model():
    if os.path.exists(MODEL_STATE_FILE):
        try:
            with open(MODEL_STATE_FILE, "r", encoding="utf-8") as f:
                saved = f.read().strip()
                if saved:
                    return saved
        except OSError:
            pass
    return MODEL


def set_default_model(model_name):
    with open(MODEL_STATE_FILE, "w", encoding="utf-8") as f:
        f.write(model_name.strip() + "\n")


def resolve_provider(model_name):
    """Returns (provider, api_model_name, endpoint_url, api_key)."""
    m = model_name.strip()
    gemini_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY") or ""
    openrouter_key = os.environ.get("OPENROUTER_API_KEY") or ""

    if m.startswith("gemini/") or m.startswith("gemini-"):
        clean = m.removeprefix("gemini/")
        return (
            "gemini",
            clean,
            "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions",
            gemini_key,
        )
    if m.startswith("openrouter/"):
        clean = m.removeprefix("openrouter/")
        return (
            "openrouter",
            clean,
            "https://openrouter.ai/api/v1/chat/completions",
            openrouter_key,
        )
    if "/" in m and not m.startswith("flint") and not m.lower().startswith("fin"):
        return (
            "openrouter",
            m,
            "https://openrouter.ai/api/v1/chat/completions",
            openrouter_key,
        )
    if PROVIDER == "gemini" and gemini_key:
        return (
            "gemini",
            m,
            "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions",
            gemini_key,
        )
    if PROVIDER == "openrouter" and openrouter_key:
        return (
            "openrouter",
            m,
            "https://openrouter.ai/api/v1/chat/completions",
            openrouter_key,
        )
    return ("ollama", m, OLLAMA_URL + "/api/chat", "")


def ollama_list_models():
    """GET Ollama /api/tags -> list of {name, size, modified_at}."""
    req = urllib.request.Request(OLLAMA_URL + "/api/tags", method="GET")
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    models = []
    for m in data.get("models", []) or []:
        models.append(
            {
                "name": m.get("name", ""),
                "size": m.get("size", 0),
                "modified_at": m.get("modified_at", ""),
            }
        )
    return models


def provider_list_models():
    """List models available for the app's selector (Ollama + configured cloud)."""
    models = []
    try:
        models.extend(ollama_list_models())
    except Exception as e:
        sys.stderr.write("[models] Failed to query Ollama tags: %s\n" % e)
        models.append({"name": get_default_model(), "size": 0, "modified_at": "local"})

    gemini_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY") or ""
    if gemini_key:
        for gm in ("gemini-2.5-flash", "gemini-2.5-pro", "gemini-2.0-flash"):
            models.append({"name": gm, "size": 0, "modified_at": "Google Gemini API"})

    openrouter_key = os.environ.get("OPENROUTER_API_KEY") or ""
    if openrouter_key:
        for om in (
            "anthropic/claude-3.5-sonnet",
            "deepseek/deepseek-chat",
            "meta-llama/llama-3.3-70b-instruct",
            "openai/gpt-4o",
        ):
            models.append({"name": om, "size": 0, "modified_at": "OpenRouter API"})

    return models


def load_token():
    token = os.environ.get("FIN_TOKEN")
    if token:
        return token
    token_path = os.path.join(HERE, "token.txt")
    if os.path.exists(token_path):
        with open(token_path, "r", encoding="utf-8") as f:
            return f.read().strip()
    token = secrets.token_urlsafe(32)
    with open(token_path, "w", encoding="utf-8") as f:
        f.write(token + "\n")
    return token


TOKEN = load_token()

SYSTEM_PROMPT = (
    "You are Fin, a personal AI assistant running locally on the user's own "
    "computer. Be direct, helpful, and concise. You help with the user's job search, "
    "documents, emails, schedule, phone text messages, long-term memory, and everyday questions. "
    "If you don't know something, say so plainly instead of guessing.\n\n"
    "You have active tools connected to:\n"
    "- Google Drive (`drive_search`, `drive_read`, `drive_list_folder`, `drive_create_file`, `drive_update_file`)\n"
    "- Gmail (`gmail_search`, `gmail_read`, `gmail_create_draft`, `gmail_prepare_send`)\n"
    "- Phone SMS Messages (`messages_recent`, `messages_search`, `messages_thread`)\n"
    "- Google Calendar & Contacts (`calendar_list`, `calendar_create`, `calendar_delete`, `contacts_search`)\n"
    "- PostgreSQL + pgvector Memory & Tasks (`memory_remember`, `memory_recall`, `memory_forget`, `task_add`, `task_list`, `task_complete`)\n"
    "- Web Research (`web_search`, `web_fetch`)\n\n"
    "IMPORTANT RULES:\n"
    "1. When the user asks about their recent texts/SMS, call `messages_recent` or `messages_search` or `messages_thread`.\n"
    "2. When the user asks about files, resumes, docs, or spreadsheets, call `drive_search` and `drive_read`.\n"
    "3. When the user asks to send or reply to an email, ALWAYS call `gmail_prepare_send`. "
    "Never claim an email has already been sent until the user approves the staged draft (they can say 'yes, send it' in natural language or '/approve <id>')."
)


def system_message(user_text=""):
    now = datetime.datetime.now().astimezone()
    base = (
        SYSTEM_PROMPT
        + "\nCurrent date and time: "
        + now.strftime("%A, %B %d, %Y at %I:%M %p %Z")
        + "."
    )
    dynamic_ctx = plugins.build_dynamic_context(user_text)
    return {
        "role": "system",
        "content": base + dynamic_ctx,
    }


# ---------------------------------------------------------------------------
# SMS / message store (PostgreSQL + messages.json backup)
# ---------------------------------------------------------------------------

MESSAGES_PATH = os.path.join(HERE, "messages.json")
_messages_lock = threading.Lock()
_MAX_STORED_MESSAGES = 5000

# Initialize PostgreSQL schema & migrate existing messages.json on import/start
db.init_db_schema()
db.migrate_json_messages(MESSAGES_PATH)


def _message_id(address, date, body):
    key = "%s\0%s\0%s" % (address, date, body)
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]


def _load_messages():
    try:
        with open(MESSAGES_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except (OSError, ValueError):
        return []


def _save_messages(entries):
    tmp = MESSAGES_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(entries, f, ensure_ascii=False)
    os.replace(tmp, MESSAGES_PATH)


def store_messages(items):
    """Store SMS messages in PostgreSQL (with pgvector embeddings) and messages.json backup."""
    with _messages_lock:
        entries = _load_messages()
        seen = {e.get("id") for e in entries}
        now_iso = datetime.datetime.now().astimezone().isoformat(timespec="seconds")
        new = 0
        new_items = []
        for item in items:
            if not isinstance(item, dict):
                continue
            address = str(item.get("address", ""))
            body = str(item.get("body", ""))
            date = item.get("date", "")
            if not body:
                continue
            mid = _message_id(address, date, body)
            if mid in seen:
                continue
            seen.add(mid)
            entry = {
                "id": mid,
                "address": address,
                "body": body,
                "date": date,
                "type": str(item.get("type", "")),
                "received_at": now_iso,
            }
            entries.append(entry)
            new_items.append(entry)
            new += 1
        if len(entries) > _MAX_STORED_MESSAGES:
            entries = entries[-_MAX_STORED_MESSAGES:]
        _save_messages(entries)

    # Sync new messages into PostgreSQL
    db_res = db.store_sms_in_db(new_items if new_items else items, compute_vectors=True)
    if db_res is not None:
        return db_res
    return new, len(entries)


def _message_sort_key(entry):
    try:
        return int(entry.get("date") or 0)
    except (TypeError, ValueError):
        return 0


def search_messages(query, limit=20):
    """Search SMS messages in PostgreSQL first, falling back to messages.json."""
    q = (query or "").strip()
    if not q:
        db_res = db.query_recent_sms(limit=limit)
    else:
        db_res = db.search_sms_db(q, limit=limit)
    if db_res is not None:
        return db_res

    with _messages_lock:
        entries = _load_messages()
    q_low = q.lower()
    if q_low:
        entries = [
            e
            for e in entries
            if q_low in str(e.get("address", "")).lower() or q_low in str(e.get("body", "")).lower()
        ]
    entries.sort(key=_message_sort_key, reverse=True)
    return entries[: max(1, min(limit, 100))], len(entries)


def tools_available():
    """Local tools (SMS, PostgreSQL Memory, Tasks, Web, Skills, MCP) are always active."""
    return True


def get_all_tool_defs():
    mcp_defs, _ = mcp_bridge.discover_mcp_tools()
    return NATIVE_TOOL_DEFS + mcp_defs


TOOL_DEFS = NATIVE_TOOL_DEFS
TOOL_FUNCS = NATIVE_TOOL_FUNCS

_FALLBACK = object()  # sentinel: tools unsupported, use v1 chat path


# ---------------------------------------------------------------------------
# Deterministic slash commands — handled server-side, no model call.
# ---------------------------------------------------------------------------

SLASH_HELP = (
    "Fin commands:\n"
    "/help — show this list\n"
    "/pending — list actions awaiting your approval (staged emails, Drive edits)\n"
    "/approve [id] — approve & send/execute a pending action (or just say 'yes, send it')\n"
    "/reject [id] — cancel a pending action (or just say 'cancel')\n"
    "/messages [query] — read recent phone texts or search SMS history\n"
    "/drive <query> — search your Google Drive documents & spreadsheets\n"
    "/gmail <query> — search your Gmail\n"
    "/calendar [days] — upcoming calendar events (default 7 days)\n"
    "/memory [query] — list or search PostgreSQL + pgvector long-term memories\n"
    "/remember <fact> — save a fact into PostgreSQL + pgvector memory\n"
    "/tasks — list open tasks, reminders, and job applications\n"
    "/skills — list installed modular assistant skills (/briefing, /triage, /jobs)\n"
    "/mcp — show Model Context Protocol (MCP) server status\n"
    "/models — show available models and active selection\n"
    "/model <name|number> — switch active model"
)

_GOOGLE_NOT_CONNECTED = (
    "%s isn't connected yet — run python auth_google.py on the PC "
    "(see SETUP-GUIDE.md)."
)


def _cmd_messages(query):
    if query:
        results, _ = search_messages(query, 10)
        if not results:
            return "No messages found for '%s'." % query
    else:
        results, _ = search_messages("", 10)
        if not results:
            return "No messages stored yet — sync messages from the Fin app first."
    lines = [
        "From %s — %s: %s" % (e.get("address", ""), format_ms_date(e.get("date", "")), e.get("body", ""))
        for e in results
    ]
    return "\n".join(lines)


def _cmd_calendar(arg):
    if google_services().get("calendar") is None:
        return _GOOGLE_NOT_CONNECTED % "Calendar"
    try:
        days = int(arg) if arg else 7
    except ValueError:
        days = 7
    return tool_calendar_list({"days": days})


def _cmd_gmail(query):
    if google_services().get("gmail") is None:
        return _GOOGLE_NOT_CONNECTED % "Gmail"
    if not query:
        return "Usage: /gmail <search words> — e.g. /gmail interview"
    return tool_gmail_search({"query": query, "max_results": 10})


def _cmd_drive(query):
    if google_services().get("drive") is None:
        return _GOOGLE_NOT_CONNECTED % "Google Drive"
    if not query:
        return tool_drive_search({"query": "", "max_results": 10})
    return tool_drive_search({"query": query, "max_results": 10})


def _cmd_pending():
    items = db.list_pending_approvals()
    if not items:
        return "✅ No pending approvals in queue."
    lines = ["⏳ Pending Approvals:"]
    for p in items:
        lines.append(f"- [#{p['id']}] ({p['action_type']}) {p['summary']}")
    lines.append("\nReply 'yes, send it' or `/approve <id>` to execute, or 'cancel' / `/reject <id>`.")
    return "\n".join(lines)


def _cmd_approve(arg):
    aid = (arg or "").strip().lstrip("#").lower() or None
    rec = db.get_pending_approval(aid)
    if not rec:
        return "No matching pending approval found." if aid else "No pending approvals waiting in queue."
    return execute_approved_action(rec)


def _cmd_reject(arg):
    aid = (arg or "").strip().lstrip("#").lower() or None
    rec = db.get_pending_approval(aid)
    if not rec:
        return "No matching pending approval found." if aid else "No pending approvals waiting in queue."
    db.resolve_pending_approval(rec["id"], "rejected", "Rejected via /reject command")
    db.log_audit_event("slash_cmd", rec["action_type"], rec.get("payload"), "Rejected via /reject", status="rejected")
    return f"🚫 Cancelled pending action [#{rec['id']}]: {rec.get('summary', '')}"


def _cmd_memory(query):
    rows = db.recall_memories(query=query or "", limit=15)
    if not rows:
        return "No memories stored yet. Use `/remember <fact>` or tell Fin to remember something."
    lines = ["🧠 Stored Memories (PostgreSQL + pgvector):"]
    for r in rows:
        subj = f"{r['subject']}: " if r.get("subject") else ""
        lines.append(f"- [#{r['id']}] ({r['category']}) {subj}{r['content']}")
    return "\n".join(lines)


def _cmd_remember(fact):
    if not fact:
        return "Usage: /remember <fact to store in long-term memory>"
    row = db.remember_fact(fact, category="fact", source_type="slash_cmd", importance=4)
    if not row:
        return "Failed to store memory in PostgreSQL."
    return f"🧠 Saved to PostgreSQL + pgvector memory [#{row['id']}]: {row['content']}"


def _cmd_tasks():
    rows = db.list_tasks(status="open", limit=25)
    if not rows:
        return "No open tasks or reminders."
    lines = ["✅ Open Tasks & Reminders:"]
    for r in rows:
        notes = f" — {r['notes']}" if r.get("notes") else ""
        lines.append(f"- [#{r['id']}] ({r['category']}) {r['title']}{notes}")
    return "\n".join(lines)


def _cmd_models():
    current = get_default_model()
    provider, _, _, _ = resolve_provider(current)
    models = provider_list_models()
    lines = [
        "🧠 Available Models:",
        "Active: %s (%s)\n" % (current, provider),
    ]
    for idx, m in enumerate(models, 1):
        name = m.get("name", "")
        star = " ★ Active" if name == current else ""
        note = m.get("modified_at", "")
        lines.append("[%d] %s%s (%s)" % (idx, name, star, note))
    lines.extend([
        "\nTo switch, type: /model <number> or /model <name>",
    ])
    return "\n".join(lines)


def _cmd_switch_model(target):
    target = (target or "").strip()
    if not target:
        return _cmd_models()
    models = provider_list_models()
    chosen_name = None
    if target.isdigit():
        idx = int(target)
        if 1 <= idx <= len(models):
            chosen_name = models[idx - 1].get("name")
    else:
        for m in models:
            if m.get("name", "").lower() == target.lower():
                chosen_name = m.get("name")
                break
        if not chosen_name:
            chosen_name = target

    provider, _, _, key = resolve_provider(chosen_name)
    if provider == "gemini" and not key:
        return "Cannot switch to %s: GEMINI_API_KEY is not set in server/.env." % chosen_name
    if provider == "openrouter" and not key:
        return "Cannot switch to %s: OPENROUTER_API_KEY is not set in server/.env." % chosen_name

    set_default_model(chosen_name)
    return "✅ Switched active model to: %s (%s)" % (chosen_name, provider)


def _last_user_text(messages):
    for m in reversed(messages):
        if m.get("role") == "user" and isinstance(m.get("content"), str):
            return m["content"]
    return ""


def handle_slash_command(text):
    """Return a reply string if text is a deterministic slash command, else None.
    Skill slash commands (/briefing, /triage, /jobs, /research, /schedule) return None
    so they pass through to the LLM with their SKILL.md instructions injected."""
    stripped = (text or "").lstrip()
    if not stripped.startswith("/"):
        return None
    parts = stripped[1:].split(None, 1)
    cmd = parts[0].lower() if parts else ""
    arg = parts[1].strip() if len(parts) > 1 else ""
    if cmd == "help":
        return SLASH_HELP
    if cmd == "pending":
        return _cmd_pending()
    if cmd == "approve":
        return _cmd_approve(arg)
    if cmd == "reject":
        return _cmd_reject(arg)
    if cmd == "messages":
        return _cmd_messages(arg)
    if cmd == "calendar":
        return _cmd_calendar(arg)
    if cmd == "gmail":
        return _cmd_gmail(arg)
    if cmd == "drive":
        return _cmd_drive(arg)
    if cmd == "memory":
        return _cmd_memory(arg)
    if cmd == "remember":
        return _cmd_remember(arg)
    if cmd == "tasks":
        return _cmd_tasks()
    if cmd == "skills":
        return skills.format_skills_list()
    if cmd == "mcp":
        if arg.lower() == "reload":
            mcp_bridge.discover_mcp_tools(force_reload=True)
        return mcp_bridge.format_mcp_status()
    if cmd == "models":
        return _cmd_models()
    if cmd == "model":
        return _cmd_switch_model(arg)
    # Allow skill slash commands (/briefing, /triage, /jobs, /research, /schedule) to invoke LLM
    if cmd in ("briefing", "triage", "jobs", "research", "schedule"):
        return None
    return "Unknown command '/%s'. Try /help." % cmd


# ---------------------------------------------------------------------------
# LLM Provider Callers (Ollama, Gemini, OpenRouter)
# ---------------------------------------------------------------------------


def _llm_post(provider, endpoint_url, api_key, payload):
    headers = {"Content-Type": "application/json"}
    if provider in ("gemini", "openrouter") and api_key:
        headers["Authorization"] = "Bearer " + api_key
    if provider == "openrouter":
        headers["HTTP-Referer"] = "https://tailfin.local"
        headers["X-Title"] = "Fin Assistant"

    req = urllib.request.Request(
        endpoint_url,
        data=json.dumps(payload).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    return urllib.request.urlopen(req, timeout=600)


class _ToolsUnsupported(Exception):
    """Model/provider rejected the tools parameter."""


def _execute_tool_call(call):
    fn = (call or {}).get("function", {}) or {}
    name = fn.get("name", "")
    args = fn.get("arguments", {})
    if isinstance(args, str):
        try:
            args = json.loads(args)
        except ValueError:
            args = {}
    if not isinstance(args, dict):
        args = {}

    func = NATIVE_TOOL_FUNCS.get(name)
    try:
        sys.stderr.write("[tools] Executing %s: %s\n" % (name, json.dumps(args)))
        if func is not None:
            raw_result = func(args)
        elif name.startswith("mcp__"):
            raw_result = mcp_bridge.call_mcp_tool(name, args)
        else:
            raw_result = "Unknown tool: %s" % name
        result = plugins.post_tool_hook(name, args, raw_result)
        sys.stderr.write("[tools] Result from %s: %s\n" % (name, str(result)[:120]))
    except Exception as e:  # noqa: BLE001
        result = "Tool %s failed: %s" % (name, e)
        sys.stderr.write("[tools] %s failed: %s\n" % (name, e))
    return name, result


def _chat_with_tools(messages, model):
    """Multi-round agentic loop with native & MCP tools (supports Ollama, Gemini, OpenRouter)."""
    provider, clean_model, endpoint_url, api_key = resolve_provider(model)
    active_tool_defs = get_all_tool_defs()

    for round_idx in range(6):
        if provider == "ollama":
            payload = {
                "model": clean_model,
                "messages": messages,
                "stream": False,
                "tools": active_tool_defs,
                "options": {"num_ctx": NUM_CTX},
            }
        else:
            payload = {
                "model": clean_model,
                "messages": messages,
                "stream": False,
                "tools": active_tool_defs,
            }

        try:
            resp = _llm_post(provider, endpoint_url, api_key, payload)
            data = json.loads(resp.read().decode("utf-8"))
            resp.close()
        except urllib.error.HTTPError as e:
            sys.stderr.write("[tools] LLM HTTPError: %s %s\n" % (e.code, e.read().decode("utf-8", "replace")[:300]))
            raise _ToolsUnsupported()
        except Exception as e:  # noqa: BLE001
            sys.stderr.write("[tools] LLM connection error: %s\n" % e)
            return None

        if provider == "ollama":
            msg = data.get("message", {}) or {}
            calls = msg.get("tool_calls") or []
            content = msg.get("content", "")
        else:
            choice = (data.get("choices") or [{}])[0]
            msg = choice.get("message", {}) or {}
            calls = msg.get("tool_calls") or []
            content = msg.get("content", "")

        sys.stderr.write(
            "[tools] Round %d: calls=%d, content=%r\n"
            % (round_idx + 1, len(calls), content[:80] if content else "")
        )
        if not calls:
            return content

        if provider == "ollama":
            messages.append({"role": "assistant", "content": content, "tool_calls": calls})
            for call in calls:
                _, result = _execute_tool_call(call)
                messages.append({"role": "tool", "content": str(result)[:10000]})
        else:
            messages.append({"role": "assistant", "content": content or "", "tool_calls": calls})
            for call in calls:
                call_id = call.get("id", "call_1")
                name, result = _execute_tool_call(call)
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": call_id,
                        "name": name,
                        "content": str(result)[:10000],
                    }
                )

    return "I ran multiple tool steps and reached the turn limit — please let me know how you'd like to proceed."


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *args):
        sys.stderr.write("[%s] %s\n" % (datetime.datetime.now().isoformat(timespec="seconds"), args[0] % args[1:]))

    def _send_json(self, status, payload):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def _check_auth(self):
        auth = self.headers.get("Authorization", "")
        if not auth.startswith("Bearer "):
            return False
        return hmac.compare_digest(auth[7:].strip(), TOKEN)

    def _read_json_body(self):
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            length = 0
        raw = self.rfile.read(length) if length > 0 else b"{}"
        try:
            data = json.loads(raw.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return None
        return data if isinstance(data, dict) else None

    def _send_ndjson_done(self, text):
        """Send final text as delta chunks + done marker, then close."""
        self.send_response(200)
        self.send_header("Content-Type", "application/x-ndjson")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Connection", "close")
        self.end_headers()
        self.close_connection = True
        try:
            for i in range(0, len(text), 400):
                self.wfile.write(
                    (json.dumps({"delta": text[i : i + 400]}) + "\n").encode("utf-8")
                )
                self.wfile.flush()
            self.wfile.write(b"data: [DONE]\n")
            self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            pass

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Authorization, Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        if path in ("/", "/health"):
            cur_model = get_default_model()
            provider, _, _, _ = resolve_provider(cur_model)
            if path == "/":
                body = (
                    b"<html><body><h1>Fin agent server</h1>"
                    b"<p>Running. Use the Fin Android app to chat.</p></body></html>"
                )
                self.send_response(200)
                self.send_header("Content-Type", "text/html")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            g_svcs = google_services()
            self._send_json(
                200,
                {
                    "status": "ok",
                    "model": cur_model,
                    "provider": provider,
                    "tools": tools_available(),
                    "tool_count": len(get_all_tool_defs()),
                    "db_connected": db.db_available(),
                    "google_connected": g_svcs.get("gmail") is not None or g_svcs.get("drive") is not None,
                    "skills_loaded": len(skills.load_all_skills()),
                },
            )
            return

        if path == "/api/messages":
            if not self._check_auth():
                self._send_json(401, {"error": "unauthorized"})
                return
            params = urllib.parse.parse_qs(parsed.query)
            query = params.get("q", [""])[0]
            try:
                limit = int(params.get("limit", ["20"])[0])
            except ValueError:
                limit = 20
            results, total = search_messages(query, limit)
            self._send_json(200, {"messages": results, "total": total})
            return

        if path in ("/models", "/api/models"):
            if not self._check_auth():
                self._send_json(401, {"error": "unauthorized"})
                return
            models = provider_list_models()
            cur_model = get_default_model()
            self._send_json(200, {"models": models, "current": cur_model})
            return

        self._send_json(404, {"error": "not found"})

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path

        if path == "/api/messages":
            if not self._check_auth():
                self._send_json(401, {"error": "unauthorized"})
                return
            data = self._read_json_body()
            if data is None:
                self._send_json(400, {"error": "invalid JSON"})
                return
            items = data.get("messages")
            if not isinstance(items, list):
                self._send_json(400, {"error": "messages must be a list"})
                return
            stored, total = store_messages(items)
            self._send_json(200, {"stored": stored, "total": total})
            return

        if path != "/api/chat":
            self._send_json(404, {"error": "not found"})
            return

        if not self._check_auth():
            self._send_json(401, {"error": "unauthorized"})
            return

        data = self._read_json_body()
        if data is None:
            self._send_json(400, {"error": "invalid JSON"})
            return

        messages = data.get("messages")
        if not isinstance(messages, list) or not messages:
            self._send_json(400, {"error": "messages must be a non-empty list"})
            return
        messages = [m for m in messages if isinstance(m, dict) and "content" in m]
        if not messages:
            self._send_json(400, {"error": "messages must contain non-empty content"})
            return

        req_model = data.get("model")
        if not isinstance(req_model, str) or not req_model.strip():
            active_model = get_default_model()
        else:
            active_model = req_model.strip()

        user_text = _last_user_text(messages)

        # 1. Natural-Language Approval Gate Interceptor ("yes, send it", "approve", "cancel")
        nl_approval_reply = plugins.check_natural_language_approval(user_text)
        if nl_approval_reply is not None:
            self.log_message("Executed natural-language approval action from: %r", user_text[:80])
            self._send_ndjson_done(nl_approval_reply)
            return

        # 2. Deterministic slash commands — answered here, no model call.
        slash_reply = handle_slash_command(user_text)
        if slash_reply is not None:
            self.log_message("Executed slash command from prompt: %r", user_text[:80])
            self._send_ndjson_done(slash_reply)
            return

        # 3. Prepend system prompt + PostgreSQL/pgvector memory + matched SKILL.md instructions
        sys_msg = system_message(user_text)
        if messages[0].get("role") != "system":
            messages = [sys_msg] + messages
        else:
            messages[0] = {
                "role": "system",
                "content": sys_msg["content"] + "\n\n" + str(messages[0].get("content", "")),
            }

        provider, clean_model, endpoint_url, api_key = resolve_provider(active_model)
        self.log_message("Chat request using [%s] %s (prompt: %r)", provider, clean_model, user_text[:60])

        # --- Tool path: always active for local + Google + MCP tools ---
        if tools_available():
            try:
                final_text = _chat_with_tools(messages, active_model)
            except _ToolsUnsupported:
                final_text = _FALLBACK
            if final_text is None:
                self._send_json(502, {"error": "cannot reach LLM provider (%s)" % provider})
                return
            if final_text is not _FALLBACK:
                plugins.post_response_hook(user_text, final_text, active_model)
                self._send_ndjson_done(final_text)
                return

        # --- Streaming path (fallback for models that do not support tools) ---
        if provider == "ollama":
            payload = {
                "model": clean_model,
                "messages": messages,
                "stream": True,
                "options": {"num_ctx": NUM_CTX},
            }
        else:
            payload = {
                "model": clean_model,
                "messages": messages,
                "stream": True,
            }

        try:
            resp = _llm_post(provider, endpoint_url, api_key, payload)
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", "replace")[:500]
            self._send_json(502, {"error": "%s error: %s" % (provider, detail)})
            return
        except Exception as e:  # noqa: BLE001
            self._send_json(502, {"error": "cannot reach %s: %s" % (provider, e)})
            return

        self.send_response(200)
        self.send_header("Content-Type", "application/x-ndjson")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Connection", "close")
        self.end_headers()
        self.close_connection = True

        full_streamed = []
        try:
            for line in resp:
                line = line.strip()
                if not line:
                    continue
                if provider == "ollama":
                    try:
                        chunk = json.loads(line.decode("utf-8"))
                    except ValueError:
                        continue
                    text = (chunk.get("message") or {}).get("content", "")
                    if text:
                        full_streamed.append(text)
                        self.wfile.write((json.dumps({"delta": text}) + "\n").encode("utf-8"))
                        self.wfile.flush()
                    if chunk.get("done"):
                        break
                else:
                    raw_str = line.decode("utf-8", "replace")
                    if raw_str.startswith("data: "):
                        data_part = raw_str[6:].strip()
                        if data_part == "[DONE]":
                            break
                        try:
                            chunk = json.loads(data_part)
                            delta = (chunk.get("choices") or [{}])[0].get("delta", {}).get("content", "")
                            if delta:
                                full_streamed.append(delta)
                                self.wfile.write((json.dumps({"delta": delta}) + "\n").encode("utf-8"))
                                self.wfile.flush()
                        except ValueError:
                            continue
            self.wfile.write(b"data: [DONE]\n")
            self.wfile.flush()
            plugins.post_response_hook(user_text, "".join(full_streamed), active_model)
        except (BrokenPipeError, ConnectionResetError):
            pass
        finally:
            resp.close()


def main():
    server = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    active = get_default_model()
    provider, clean_m, _, _ = resolve_provider(active)
    print("Fin agent server listening on port %d" % PORT)
    print("Provider: %s — Model: %s  (Ollama at %s)" % (provider, clean_m, OLLAMA_URL))
    print("PostgreSQL + pgvector memory: %s" % ("connected" if db.db_available() else "offline"))
    print("Skills loaded: %d | Tools registered: %d" % (len(skills.load_all_skills()), len(get_all_tool_defs())))
    print("Pairing token (enter this in the Fin app settings): %s" % TOKEN)
    print("Token also saved to %s" % os.path.join(HERE, "token.txt"))
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping.")


if __name__ == "__main__":
    main()
