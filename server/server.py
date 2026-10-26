#!/usr/bin/env python3
"""Fin agent server — runs on the PC next to Ollama.

Exposes the HTTP API the Fin Android app talks to:
  GET  /health       -> {"status": "ok", "model": ..., "tools": ...}
  GET  /models       -> {"models": [...], "current": ...} (Ollama + Cloud)
  POST /api/chat     -> {"messages": [{"role": "user", "content": "..."}],
                         "model": "<optional per-request model>"}
                        replies with newline-delimited JSON:
                          {"delta": "..."} ... data: [DONE]
                        Messages starting with "/" are slash commands handled
                        deterministically on the server (see below) — no model call.
  POST /api/messages -> {"messages": [{"address","body","date","type"}]}
                        stores SMS synced from the phone, deduped
  GET  /api/messages?q=<text>&limit=20 -> stored messages, newest first

Slash commands (handled in /api/chat before LLM call):
  /help, /messages [query], /calendar [days], /gmail <query>, /models, /model <target>

Providers Supported:
  - Ollama (local default)
  - Google Gemini API (set GEMINI_API_KEY in .env)
  - OpenRouter API (set OPENROUTER_API_KEY in .env)

Auth: Authorization: Bearer <token>. The token comes from the FIN_TOKEN
environment variable (or .env), or is generated on first run and saved to
token.txt next to this file. Enter the same token in the app's settings.

Google tools (Gmail + Calendar) are optional: they activate only when
token.json exists (run auth_google.py once) and google-api-python-client
is installed. Standard library only — no pip installs needed for chat.
"""

import base64
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
    # 1. Local Ollama models
    try:
        models.extend(ollama_list_models())
    except Exception as e:
        sys.stderr.write("[models] Failed to query Ollama tags: %s\n" % e)
        models.append({"name": get_default_model(), "size": 0, "modified_at": "local"})

    # 2. Add Gemini models if key configured
    gemini_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY") or ""
    if gemini_key:
        for gm in ("gemini-2.5-flash", "gemini-2.5-pro", "gemini-2.0-flash"):
            models.append({"name": gm, "size": 0, "modified_at": "Google Gemini API"})

    # 3. Add OpenRouter models if key configured
    openrouter_key = os.environ.get("OPENROUTER_API_KEY") or ""
    if openrouter_key:
        for om in ("anthropic/claude-3.5-sonnet", "deepseek/deepseek-chat", "meta-llama/llama-3.3-70b-instruct", "openai/gpt-4o"):
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
    "computer. Be direct and concise. You help with the user's job search, "
    "schedule, messages, and everyday questions. If you don't know something, "
    "say so plainly instead of guessing.\n\n"
    "You have active tools connected to the user's Google account (Gmail and Google Calendar) "
    "and their phone SMS messages. When the user asks about emails, calendar, schedule, meetings, "
    "appointments, or text messages, always call the appropriate tool functions (gmail_search, "
    "gmail_read, calendar_list, calendar_create, messages_search) to look up or update the real data."
)


def system_message():
    now = datetime.datetime.now().astimezone()
    return {
        "role": "system",
        "content": SYSTEM_PROMPT
        + "\nCurrent date and time: "
        + now.strftime("%A, %B %d, %Y at %I:%M %p %Z")
        + ".",
    }


# ---------------------------------------------------------------------------
# SMS / message store (synced from the phone app)
# ---------------------------------------------------------------------------

MESSAGES_PATH = os.path.join(HERE, "messages.json")
_messages_lock = threading.Lock()
_MAX_STORED_MESSAGES = 5000


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
    """Append messages, deduping by (address, date, body). Returns (new, total)."""
    with _messages_lock:
        entries = _load_messages()
        seen = {e.get("id") for e in entries}
        now_iso = datetime.datetime.now().astimezone().isoformat(timespec="seconds")
        new = 0
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
            entries.append(
                {
                    "id": mid,
                    "address": address,
                    "body": body,
                    "date": date,
                    "type": str(item.get("type", "")),
                    "received_at": now_iso,
                }
            )
            new += 1
        if len(entries) > _MAX_STORED_MESSAGES:
            entries = entries[-_MAX_STORED_MESSAGES:]
        _save_messages(entries)
        return new, len(entries)


def _message_sort_key(entry):
    try:
        return int(entry.get("date") or 0)
    except (TypeError, ValueError):
        return 0


def search_messages(query, limit=20):
    with _messages_lock:
        entries = _load_messages()
    q = (query or "").strip().lower()
    if q:
        entries = [
            e
            for e in entries
            if q in str(e.get("address", "")).lower() or q in str(e.get("body", "")).lower()
        ]
    entries.sort(key=_message_sort_key, reverse=True)
    return entries[: max(1, min(limit, 100))], len(entries)


# ---------------------------------------------------------------------------
# Google tools (Gmail + Calendar) — optional, lazy imports only
# ---------------------------------------------------------------------------

GOOGLE_SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/calendar",
]

_google_cache = {"checked": False, "gmail": None, "calendar": None}


def _google_services():
    """Return (gmail_service, calendar_service) or (None, None)."""
    if _google_cache["checked"]:
        return _google_cache["gmail"], _google_cache["calendar"]
    _google_cache["checked"] = True
    token_path = os.path.join(HERE, "token.json")
    if not os.path.exists(token_path):
        return None, None
    try:
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from googleapiclient.discovery import build
    except ImportError:
        return None, None
    try:
        creds = Credentials.from_authorized_user_file(token_path, GOOGLE_SCOPES)
        if not creds.valid:
            if creds.expired and creds.refresh_token:
                creds.refresh(Request())
                with open(token_path, "w", encoding="utf-8") as f:
                    f.write(creds.to_json())
            else:
                return None, None
        _google_cache["gmail"] = build("gmail", "v1", credentials=creds)
        _google_cache["calendar"] = build("calendar", "v3", credentials=creds)
    except Exception:  # noqa: BLE001
        return None, None
    return _google_cache["gmail"], _google_cache["calendar"]


def _gmail_text_from_payload(payload):
    mime = payload.get("mimeType", "")
    if mime == "text/plain":
        data = payload.get("body", {}).get("data", "")
        try:
            padded = data + "=" * (-len(data) % 4)
            return base64.urlsafe_b64decode(padded).decode("utf-8", "replace")
        except Exception:  # noqa: BLE001
            return ""
    text = ""
    for part in payload.get("parts", []) or []:
        text += _gmail_text_from_payload(part)
    return text


def tool_gmail_search(args):
    gmail, _ = _google_services()
    if gmail is None:
        return "Gmail is not connected."
    query = str(args.get("query", ""))
    try:
        max_results = min(int(args.get("max_results", 10) or 10), 20)
    except (TypeError, ValueError):
        max_results = 10
    try:
        res = (
            gmail.users()
            .messages()
            .list(userId="me", q=query, maxResults=max_results)
            .execute()
        )
        ids = [m["id"] for m in res.get("messages", [])]
        if not ids:
            return "No messages matched."
        lines = []
        for mid in ids:
            m = (
                gmail.users()
                .messages()
                .get(
                    userId="me",
                    id=mid,
                    format="metadata",
                    metadataHeaders=["From", "Subject", "Date"],
                )
                .execute()
            )
            headers = {
                h["name"]: h["value"]
                for h in m.get("payload", {}).get("headers", [])
            }
            lines.append(
                "- [%s] %s | %s | %s | %s"
                % (
                    mid,
                    headers.get("Date", ""),
                    headers.get("From", ""),
                    headers.get("Subject", ""),
                    m.get("snippet", ""),
                )
            )
        return "\n".join(lines)
    except Exception as e:  # noqa: BLE001
        return "Gmail search failed: %s" % e


def tool_gmail_read(args):
    gmail, _ = _google_services()
    if gmail is None:
        return "Gmail is not connected."
    message_id = str(args.get("message_id", ""))
    if not message_id:
        return "No message_id given."
    try:
        m = gmail.users().messages().get(userId="me", id=message_id, format="full").execute()
        headers = {
            h["name"]: h["value"] for h in m.get("payload", {}).get("headers", [])
        }
        body = _gmail_text_from_payload(m.get("payload", {}))
        return "From: %s\nSubject: %s\nDate: %s\n\n%s" % (
            headers.get("From", ""),
            headers.get("Subject", ""),
            headers.get("Date", ""),
            body[:8000],
        )
    except Exception as e:  # noqa: BLE001
        return "Gmail read failed: %s" % e


def tool_calendar_list(args):
    _, calendar = _google_services()
    if calendar is None:
        return "Calendar is not connected."
    try:
        days = min(int(args.get("days", 7) or 7), 31)
    except (TypeError, ValueError):
        days = 7
    try:
        now = datetime.datetime.now(datetime.timezone.utc)
        res = (
            calendar.events()
            .list(
                calendarId="primary",
                timeMin=now.isoformat(),
                timeMax=(now + datetime.timedelta(days=days)).isoformat(),
                singleEvents=True,
                orderBy="startTime",
            )
            .execute()
        )
        events = res.get("items", [])
        if not events:
            return "No events in the next %d day(s)." % days
        lines = []
        for ev in events:
            start = ev.get("start", {}).get("dateTime") or ev.get("start", {}).get("date", "")
            end = ev.get("end", {}).get("dateTime") or ev.get("end", {}).get("date", "")
            lines.append("- %s to %s | %s" % (start, end, ev.get("summary", "(no title)")))
        return "\n".join(lines)
    except Exception as e:  # noqa: BLE001
        return "Calendar list failed: %s" % e


def tool_calendar_create(args):
    _, calendar = _google_services()
    if calendar is None:
        return "Calendar is not connected."
    title = str(args.get("title", "")).strip()
    start = str(args.get("start", "")).strip()
    end = str(args.get("end", "")).strip()
    if not title or not start or not end:
        return "calendar_create needs title, start and end (ISO date-time)."
    body = {
        "summary": title,
        "start": {"dateTime": start},
        "end": {"dateTime": end},
    }
    if args.get("description"):
        body["description"] = str(args["description"])
    try:
        ev = calendar.events().insert(calendarId="primary", body=body).execute()
        return "Created event: %s (%s to %s), id %s" % (
            title,
            start,
            end,
            ev.get("id", ""),
        )
    except Exception as e:  # noqa: BLE001
        return "Calendar create failed: %s" % e


def tool_messages_search(args):
    query = str(args.get("query", ""))
    try:
        limit = min(int(args.get("limit", 10) or 10), 20)
    except (TypeError, ValueError):
        limit = 10
    results, total = search_messages(query, limit)
    if not results:
        if total == 0:
            return "No SMS messages have been synced from the phone app yet. If the user meant emails, use gmail_search instead."
        return "No stored SMS messages matched the query '%s'." % query
    lines = [
        "- %s | %s | %s" % (e.get("date", ""), e.get("address", ""), e.get("body", "")[:300])
        for e in results
    ]
    return "%d matching message(s):\n%s" % (total, "\n".join(lines))


TOOL_DEFS = [
    {
        "type": "function",
        "function": {
            "name": "gmail_search",
            "description": "Search the user's Gmail. Returns sender, subject, date, snippet and message id for each match.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Gmail search query, e.g. 'from:payit subject:interview'"},
                    "max_results": {"type": "integer", "description": "Max results, default 10"},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "gmail_read",
            "description": "Read the full text of one Gmail message by its id.",
            "parameters": {
                "type": "object",
                "properties": {
                    "message_id": {"type": "string", "description": "Gmail message id from gmail_search"},
                },
                "required": ["message_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "calendar_list",
            "description": "List upcoming Google Calendar events.",
            "parameters": {
                "type": "object",
                "properties": {
                    "days": {"type": "integer", "description": "How many days ahead, default 7"},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "calendar_create",
            "description": "Create a Google Calendar event.",
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "start": {"type": "string", "description": "ISO date-time with offset, e.g. 2026-10-26T09:00:00-05:00"},
                    "end": {"type": "string", "description": "ISO date-time with offset"},
                    "description": {"type": "string"},
                },
                "required": ["title", "start", "end"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "messages_search",
            "description": "Search SMS/text messages synced from the user's phone.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Text to find in the sender or message body"},
                    "limit": {"type": "integer", "description": "Max results, default 10"},
                },
                "required": ["query"],
            },
        },
    },
]

TOOL_FUNCS = {
    "gmail_search": tool_gmail_search,
    "gmail_read": tool_gmail_read,
    "calendar_list": tool_calendar_list,
    "calendar_create": tool_calendar_create,
    "messages_search": tool_messages_search,
}


def tools_available():
    gmail, calendar = _google_services()
    return gmail is not None or calendar is not None


_FALLBACK = object()  # sentinel: tools unsupported, use v1 chat path


# ---------------------------------------------------------------------------
# Deterministic slash commands — handled server-side, no model call.
# ---------------------------------------------------------------------------

SLASH_HELP = (
    "Fin commands:\n"
    "/help — show this list\n"
    "/messages [query] — search texts synced from your phone (no search = 5 most recent)\n"
    "/calendar [days] — upcoming calendar events (default 7 days)\n"
    "/gmail <query> — search your Gmail\n"
    "/models — show available models and active selection\n"
    "/model <name|number> — switch active model"
)

_GOOGLE_NOT_CONNECTED = (
    "%s isn't connected yet — run python auth_google.py on the PC "
    "(see SETUP-GUIDE.md)."
)


def _format_message_date(entry):
    raw = entry.get("date", "")
    try:
        ms = int(raw)
        dt = datetime.datetime.fromtimestamp(ms / 1000.0).astimezone()
        return dt.strftime("%b %d, %I:%M %p")
    except (TypeError, ValueError):
        return str(raw)


def _cmd_messages(query):
    if query:
        results, _ = search_messages(query, 10)
        if not results:
            return "No messages found for '%s'." % query
    else:
        results, _ = search_messages("", 5)
        if not results:
            return "No messages stored yet — sync messages from the Fin app first."
    lines = [
        "From %s — %s: %s" % (e.get("address", ""), _format_message_date(e), e.get("body", ""))
        for e in results
    ]
    return "\n".join(lines)


def _cmd_calendar(arg):
    _, calendar = _google_services()
    if calendar is None:
        return _GOOGLE_NOT_CONNECTED % "Calendar"
    try:
        days = int(arg) if arg else 7
    except ValueError:
        days = 7
    return tool_calendar_list({"days": days})


def _cmd_gmail(query):
    gmail, _ = _google_services()
    if gmail is None:
        return _GOOGLE_NOT_CONNECTED % "Gmail"
    if not query:
        return "Usage: /gmail <search words> — e.g. /gmail interview"
    return tool_gmail_search({"query": query, "max_results": 10})


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
    """Return a reply string if text is a slash command, else None."""
    stripped = (text or "").lstrip()
    if not stripped.startswith("/"):
        return None
    parts = stripped[1:].split(None, 1)
    cmd = parts[0].lower() if parts else ""
    arg = parts[1].strip() if len(parts) > 1 else ""
    if cmd == "help":
        return SLASH_HELP
    if cmd == "messages":
        return _cmd_messages(arg)
    if cmd == "calendar":
        return _cmd_calendar(arg)
    if cmd == "gmail":
        return _cmd_gmail(arg)
    if cmd == "models":
        return _cmd_models()
    if cmd == "model":
        return _cmd_switch_model(arg)
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
    func = TOOL_FUNCS.get(name)
    if func is None:
        result = "Unknown tool: %s" % name
    else:
        try:
            sys.stderr.write("[tools] Executing %s: %s\n" % (name, json.dumps(args)))
            result = func(args)
            sys.stderr.write("[tools] Result from %s: %s\n" % (name, str(result)[:100]))
        except Exception as e:  # noqa: BLE001
            result = "Tool %s failed: %s" % (name, e)
            sys.stderr.write("[tools] %s failed: %s\n" % (name, e))
    return name, result


def _chat_with_tools(messages, model):
    """Agentic loop with tools (supports Ollama, Gemini, OpenRouter)."""
    provider, clean_model, endpoint_url, api_key = resolve_provider(model)

    for round_idx in range(3):
        if provider == "ollama":
            payload = {
                "model": clean_model,
                "messages": messages,
                "stream": False,
                "tools": TOOL_DEFS,
                "options": {"num_ctx": NUM_CTX},
            }
        else:
            payload = {
                "model": clean_model,
                "messages": messages,
                "stream": False,
                "tools": TOOL_DEFS,
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

        sys.stderr.write("[tools] Round %d: calls=%d, content=%r\n" % (round_idx + 1, len(calls), content[:80] if content else ""))
        if not calls:
            return content

        if provider == "ollama":
            messages.append({"role": "assistant", "content": content, "tool_calls": calls})
            for call in calls:
                _, result = _execute_tool_call(call)
                messages.append({"role": "tool", "content": str(result)[:8000]})
        else:
            messages.append({"role": "assistant", "content": content or "", "tool_calls": calls})
            for call in calls:
                call_id = call.get("id", "call_1")
                name, result = _execute_tool_call(call)
                messages.append({
                    "role": "tool",
                    "tool_call_id": call_id,
                    "name": name,
                    "content": str(result)[:8000],
                })

    return "I tried to use tools multiple times without finishing — please try rephrasing that."


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
            self._send_json(
                200,
                {
                    "status": "ok",
                    "model": cur_model,
                    "provider": provider,
                    "tools": tools_available(),
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

        # Per-request model selection (client sends "model"; default is get_default_model()).
        req_model = data.get("model")
        if not isinstance(req_model, str) or not req_model.strip():
            active_model = get_default_model()
        else:
            active_model = req_model.strip()

        # Deterministic slash commands — answered here, no model call.
        user_text = _last_user_text(messages)
        slash_reply = handle_slash_command(user_text)
        if slash_reply is not None:
            self.log_message("Executed slash command from prompt: %r", user_text[:80])
            self._send_ndjson_done(slash_reply)
            return

        # Prepend system prompt
        if messages[0].get("role") != "system":
            messages = [system_message()] + messages
        else:
            messages[0] = {
                "role": "system",
                "content": system_message()["content"] + "\n\n" + str(messages[0].get("content", "")),
            }

        provider, clean_model, endpoint_url, api_key = resolve_provider(active_model)
        self.log_message("Chat request using [%s] %s (prompt: %r)", provider, clean_model, user_text[:60])

        # --- Tool path: only when Google tools are configured ---
        if tools_available():
            try:
                final_text = _chat_with_tools(messages, active_model)
            except _ToolsUnsupported:
                final_text = _FALLBACK
            if final_text is None:
                self._send_json(502, {"error": "cannot reach LLM provider (%s)" % provider})
                return
            if final_text is not _FALLBACK:
                self._send_ndjson_done(final_text)
                return

        # --- Streaming path (no tools or tools fallback) ---
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
                                self.wfile.write((json.dumps({"delta": delta}) + "\n").encode("utf-8"))
                                self.wfile.flush()
                        except ValueError:
                            continue
            self.wfile.write(b"data: [DONE]\n")
            self.wfile.flush()
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
    print("Google tools: %s" % ("enabled" if tools_available() else "off (run auth_google.py to enable)"))
    print("Pairing token (enter this in the Fin app settings): %s" % TOKEN)
    print("Token also saved to %s" % os.path.join(HERE, "token.txt"))
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping.")


if __name__ == "__main__":
    main()
