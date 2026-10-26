"""Unified Tool Suite for Fin Assistant Server.

Includes:
- Google Drive (search, read Docs/Sheets/text, list folder, create file, approval-gated update)
- Gmail (search, read plain+HTML, create draft, approval-gated send)
- Phone SMS Messages (recent messages, hybrid FTS+vector search, chronological thread view)
- Google Calendar (list, create, approval-gated delete)
- Google Contacts (resolve names to emails & phone numbers)
- Long-Term Memory & Tasks (PostgreSQL + pgvector)
- Web Research (DuckDuckGo search + clean page text fetcher)
"""

import base64
import datetime
import email.message
import html.parser
import io
import json
import os
import re
import sys
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import db

GOOGLE_SCOPES = [
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/drive",
    "https://www.googleapis.com/auth/calendar",
    "https://www.googleapis.com/auth/contacts.readonly",
]

_google_cache = {
    "mtime": None,
    "gmail": None,
    "drive": None,
    "calendar": None,
    "people": None,
    "scopes": [],
}


class _HTMLTextExtractor(html.parser.HTMLParser):
    """Lightweight stdlib HTML-to-text converter for HTML-only emails and web pages."""

    def __init__(self):
        super().__init__()
        self._parts = []
        self._skip = False

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "head", "noscript"):
            self._skip = True
        elif tag in ("p", "br", "div", "tr", "li", "h1", "h2", "h3", "h4"):
            self._parts.append("\n")

    def handle_endtag(self, tag):
        if tag in ("script", "style", "head", "noscript"):
            self._skip = False
        elif tag in ("p", "div", "tr", "li"):
            self._parts.append("\n")

    def handle_data(self, data):
        if not self._skip and data:
            self._parts.append(data)

    def get_text(self):
        raw = "".join(self._parts)
        return re.sub(r"\n{3,}", "\n\n", raw).strip()


def html_to_text(html_str):
    parser = _HTMLTextExtractor()
    try:
        parser.feed(html_str or "")
        return parser.get_text()
    except Exception:  # noqa: BLE001
        return re.sub(r"<[^>]+>", " ", html_str or "").strip()


def google_services():
    """Return dict of {'gmail', 'drive', 'calendar', 'people', 'scopes'}.
    Automatically reloads if token.json is updated on disk."""
    token_path = os.path.join(HERE, "token.json")
    if not os.path.exists(token_path):
        return _google_cache
    try:
        mtime = os.path.getmtime(token_path)
    except OSError:
        return _google_cache

    if _google_cache["mtime"] == mtime and _google_cache["gmail"] is not None:
        return _google_cache

    _google_cache["mtime"] = mtime
    try:
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from googleapiclient.discovery import build
    except ImportError:
        return _google_cache

    try:
        # Load with existing granted scopes in token.json so refresh always works
        creds = Credentials.from_authorized_user_file(token_path)
        if not creds.valid:
            if creds.expired and creds.refresh_token:
                creds.refresh(Request())
                with open(token_path, "w", encoding="utf-8") as f:
                    f.write(creds.to_json())
            else:
                return _google_cache
        _google_cache["scopes"] = list(creds.scopes or [])
        _google_cache["gmail"] = build("gmail", "v1", credentials=creds)
        _google_cache["calendar"] = build("calendar", "v3", credentials=creds)
        _google_cache["drive"] = build("drive", "v3", credentials=creds)
        _google_cache["people"] = build("people", "v1", credentials=creds)
    except Exception:  # noqa: BLE001
        pass
    return _google_cache


def format_ms_date(raw):
    try:
        ms = int(raw)
        dt = datetime.datetime.fromtimestamp(ms / 1000.0).astimezone()
        return dt.strftime("%b %d, %Y %I:%M %p")
    except (TypeError, ValueError):
        return str(raw)


# ---------------------------------------------------------------------------
# 1. Google Drive Tools
# ---------------------------------------------------------------------------

def tool_drive_search(args):
    drive = google_services().get("drive")
    if drive is None:
        return "Google Drive is not connected. Run `python3 server/auth_google.py` to authorize Drive."
    query = str(args.get("query", "")).strip()
    file_type = str(args.get("file_type", "any")).strip().lower()
    try:
        max_results = min(int(args.get("max_results", 10) or 10), 25)
    except (TypeError, ValueError):
        max_results = 10

    q_parts = ["trashed = false"]
    if query:
        safe_q = query.replace("'", "\\'")
        q_parts.append(f"(name contains '{safe_q}' or fullText contains '{safe_q}')")
    mime_map = {
        "doc": "application/vnd.google-apps.document",
        "sheet": "application/vnd.google-apps.spreadsheet",
        "pdf": "application/pdf",
        "folder": "application/vnd.google-apps.folder",
    }
    if file_type in mime_map:
        q_parts.append(f"mimeType = '{mime_map[file_type]}'")

    try:
        res = (
            drive.files()
            .list(
                q=" and ".join(q_parts),
                pageSize=max_results,
                fields="files(id, name, mimeType, modifiedTime, webViewLink, size)",
                orderBy="modifiedTime desc",
            )
            .execute()
        )
        files = res.get("files", [])
        if not files:
            return f"No Google Drive files matched query '{query}'."
        lines = []
        for f in files:
            lines.append(
                f"- [{f.get('id')}] {f.get('name')} ({f.get('mimeType')}) | Modified: {f.get('modifiedTime', '')} | {f.get('webViewLink', '')}"
            )
        return f"Found {len(files)} Drive file(s):\n" + "\n".join(lines)
    except Exception as e:  # noqa: BLE001
        if "insufficientPermissions" in str(e) or "403" in str(e):
            return "Google Drive permission not yet granted in token.json. Run `python3 server/auth_google.py` to enable Drive access."
        return f"Google Drive search failed: {e}"


def tool_drive_read(args):
    drive = google_services().get("drive")
    if drive is None:
        return "Google Drive is not connected."
    file_id = str(args.get("file_id", "")).strip()
    if not file_id:
        return "file_id is required."
    try:
        max_chars = min(int(args.get("max_chars", 8000) or 8000), 20000)
    except (TypeError, ValueError):
        max_chars = 8000

    try:
        meta = drive.files().get(fileId=file_id, fields="id, name, mimeType, modifiedTime, webViewLink").execute()
        mime = meta.get("mimeType", "")
        name = meta.get("name", "")

        if mime == "application/vnd.google-apps.document":
            raw = drive.files().export(fileId=file_id, mimeType="text/plain").execute()
            content = raw.decode("utf-8", "replace") if isinstance(raw, bytes) else str(raw)
        elif mime == "application/vnd.google-apps.spreadsheet":
            raw = drive.files().export(fileId=file_id, mimeType="text/csv").execute()
            content = raw.decode("utf-8", "replace") if isinstance(raw, bytes) else str(raw)
        elif mime == "application/vnd.google-apps.presentation":
            raw = drive.files().export(fileId=file_id, mimeType="text/plain").execute()
            content = raw.decode("utf-8", "replace") if isinstance(raw, bytes) else str(raw)
        else:
            raw = drive.files().get_media(fileId=file_id).execute()
            content = raw.decode("utf-8", "replace") if isinstance(raw, bytes) else str(raw)

        return (
            f"File: {name} [{file_id}]\n"
            f"Type: {mime} | Modified: {meta.get('modifiedTime', '')}\n"
            f"Link: {meta.get('webViewLink', '')}\n\n"
            f"{content[:max_chars]}"
        )
    except Exception as e:  # noqa: BLE001
        return f"Google Drive read failed: {e}"


def tool_drive_list_folder(args):
    drive = google_services().get("drive")
    if drive is None:
        return "Google Drive is not connected."
    folder_id = str(args.get("folder_id", "root") or "root").strip()
    try:
        max_results = min(int(args.get("max_results", 20) or 20), 50)
    except (TypeError, ValueError):
        max_results = 20
    try:
        safe_folder = folder_id.replace("'", "\\'")
        res = (
            drive.files()
            .list(
                q=f"'{safe_folder}' in parents and trashed = false",
                pageSize=max_results,
                fields="files(id, name, mimeType, modifiedTime, webViewLink)",
                orderBy="folder,modifiedTime desc",
            )
            .execute()
        )
        files = res.get("files", [])
        if not files:
            return f"Folder '{folder_id}' is empty."
        lines = [
            f"- [{f.get('id')}] {f.get('name')} ({f.get('mimeType')}) | {f.get('modifiedTime', '')}"
            for f in files
        ]
        return f"Contents of Drive folder '{folder_id}':\n" + "\n".join(lines)
    except Exception as e:  # noqa: BLE001
        return f"Google Drive folder list failed: {e}"


def tool_drive_create_file(args):
    drive = google_services().get("drive")
    if drive is None:
        return "Google Drive is not connected."
    name = str(args.get("name", "")).strip()
    content = str(args.get("content", ""))
    folder_id = str(args.get("folder_id", "")).strip()
    as_doc = bool(args.get("as_google_doc", True))
    if not name:
        return "name is required to create a Drive file."

    try:
        from googleapiclient.http import MediaIoBaseUpload

        metadata = {"name": name}
        if folder_id and folder_id != "root":
            metadata["parents"] = [folder_id]
        if as_doc:
            metadata["mimeType"] = "application/vnd.google-apps.document"
        media = MediaIoBaseUpload(
            io.BytesIO(content.encode("utf-8")),
            mimetype="text/plain",
            resumable=False,
        )
        created = (
            drive.files()
            .create(body=metadata, media_body=media, fields="id, name, webViewLink")
            .execute()
        )
        return f"Created Google Drive file '{created.get('name')}' [ID: {created.get('id')}] — {created.get('webViewLink', '')}"
    except Exception as e:  # noqa: BLE001
        return f"Google Drive file creation failed: {e}"


def tool_drive_update_file(args):
    """Approval-gated Drive file update."""
    file_id = str(args.get("file_id", "")).strip()
    new_content = str(args.get("new_content", ""))
    if not file_id:
        return "file_id is required."
    summary = f"Update Google Drive file [{file_id}] ({len(new_content)} chars)"
    rec = db.create_pending_approval(
        "drive_update",
        summary,
        {"file_id": file_id, "new_content": new_content},
    )
    if not rec:
        return "Failed to stage Drive update approval."
    aid = rec["id"]
    return (
        f"📝 PENDING DRIVE UPDATE APPROVAL [#{aid}]\n"
        f"Target File ID: {file_id}\n"
        f"Content Preview:\n{new_content[:400]}{'...' if len(new_content) > 400 else ''}\n\n"
        f"Ask the user to confirm in natural language (e.g. 'yes, update it') or reply `/approve {aid}` (or `/reject {aid}`)."
    )


# ---------------------------------------------------------------------------
# 2. Gmail Read, Draft & Approval-Gated Send Tools
# ---------------------------------------------------------------------------

def _extract_email_body(payload):
    mime = payload.get("mimeType", "")
    data = (payload.get("body") or {}).get("data", "")
    if data and mime in ("text/plain", "text/html"):
        try:
            padded = data + "=" * (-len(data) % 4)
            decoded = base64.urlsafe_b64decode(padded).decode("utf-8", "replace")
            return decoded if mime == "text/plain" else html_to_text(decoded)
        except Exception:  # noqa: BLE001
            return ""
    plain_parts = []
    html_parts = []
    for part in payload.get("parts", []) or []:
        pmime = part.get("mimeType", "")
        if pmime == "text/plain":
            plain_parts.append(_extract_email_body(part))
        elif pmime == "text/html":
            html_parts.append(_extract_email_body(part))
        else:
            sub = _extract_email_body(part)
            if sub:
                plain_parts.append(sub)
    if any(plain_parts):
        return "\n".join(p for p in plain_parts if p)
    return "\n".join(h for h in html_parts if h)


def _list_attachments(payload):
    files = []
    filename = payload.get("filename")
    if filename:
        size = (payload.get("body") or {}).get("size", 0)
        files.append(f"{filename} ({size} bytes)")
    for part in payload.get("parts", []) or []:
        files.extend(_list_attachments(part))
    return files


def tool_gmail_search(args):
    gmail = google_services().get("gmail")
    if gmail is None:
        return "Gmail is not connected."
    query = str(args.get("query", ""))
    try:
        max_results = min(int(args.get("max_results", 10) or 10), 25)
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
            return f"No Gmail messages matched query '{query}'."
        lines = []
        for mid in ids:
            m = (
                gmail.users()
                .messages()
                .get(
                    userId="me",
                    id=mid,
                    format="metadata",
                    metadataHeaders=["From", "To", "Subject", "Date"],
                )
                .execute()
            )
            headers = {
                h["name"]: h["value"]
                for h in m.get("payload", {}).get("headers", [])
            }
            lines.append(
                "- [%s] %s | From: %s | Subject: %s | %s"
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
        return f"Gmail search failed: {e}"


def tool_gmail_read(args):
    gmail = google_services().get("gmail")
    if gmail is None:
        return "Gmail is not connected."
    message_id = str(args.get("message_id", "")).strip()
    if not message_id:
        return "No message_id given."
    try:
        m = gmail.users().messages().get(userId="me", id=message_id, format="full").execute()
        payload = m.get("payload", {})
        headers = {
            h["name"]: h["value"] for h in payload.get("headers", [])
        }
        body = _extract_email_body(payload)
        attachments = _list_attachments(payload)
        att_line = f"\nAttachments: {', '.join(attachments)}" if attachments else ""
        return (
            f"Message ID: {message_id} (Thread: {m.get('threadId', '')})\n"
            f"From: {headers.get('From', '')}\n"
            f"To: {headers.get('To', '')}\n"
            f"Cc: {headers.get('Cc', '')}\n"
            f"Subject: {headers.get('Subject', '')}\n"
            f"Date: {headers.get('Date', '')}"
            f"{att_line}\n\n"
            f"{body[:10000]}"
        )
    except Exception as e:  # noqa: BLE001
        return f"Gmail read failed: {e}"


def _build_raw_mime_message(to_addr, subject, body, cc="", reply_to_message_id=""):
    gmail = google_services().get("gmail")
    msg = email.message.EmailMessage()
    msg["To"] = to_addr
    if cc:
        msg["Cc"] = cc
    msg["Subject"] = subject
    thread_id = None
    if reply_to_message_id and gmail is not None:
        try:
            orig = (
                gmail.users()
                .messages()
                .get(
                    userId="me",
                    id=reply_to_message_id,
                    format="metadata",
                    metadataHeaders=["Message-ID", "References", "Subject"],
                )
                .execute()
            )
            thread_id = orig.get("threadId")
            hdrs = {h["name"]: h["value"] for h in orig.get("payload", {}).get("headers", [])}
            orig_mid = hdrs.get("Message-ID")
            if orig_mid:
                msg["In-Reply-To"] = orig_mid
                refs = hdrs.get("References", "")
                msg["References"] = (refs + " " + orig_mid).strip()
        except Exception:  # noqa: BLE001
            pass
    msg.set_content(body)
    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode("ascii")
    body_obj = {"raw": raw}
    if thread_id:
        body_obj["threadId"] = thread_id
    return body_obj


def tool_gmail_create_draft(args):
    """Create a Gmail draft without sending."""
    gmail = google_services().get("gmail")
    if gmail is None:
        return "Gmail is not connected."
    to_addr = str(args.get("to", "")).strip()
    subject = str(args.get("subject", "")).strip()
    body = str(args.get("body", ""))
    cc = str(args.get("cc", "")).strip()
    reply_to = str(args.get("reply_to_message_id", "")).strip()
    if not to_addr or not subject:
        return "Both 'to' and 'subject' are required to create a draft."
    try:
        msg_obj = _build_raw_mime_message(to_addr, subject, body, cc, reply_to)
        draft = gmail.users().drafts().create(userId="me", body={"message": msg_obj}).execute()
        return f"Created Gmail draft [Draft ID: {draft.get('id')}] to {to_addr} with subject '{subject}'."
    except Exception as e:  # noqa: BLE001
        if "insufficientPermissions" in str(e) or "403" in str(e):
            return (
                "Gmail token currently has read-only scope. Run `python3 server/auth_google.py` "
                "once on the PC to grant draft/send permissions."
            )
        return f"Failed to create Gmail draft: {e}"


def tool_gmail_prepare_send(args):
    """Draft an email and stage it in the Human-in-the-Loop Approval Queue.
    Never sends until the user approves via natural language ('yes, send it') or '/approve <id>'."""
    to_addr = str(args.get("to", "")).strip()
    subject = str(args.get("subject", "")).strip()
    body = str(args.get("body", ""))
    cc = str(args.get("cc", "")).strip()
    reply_to = str(args.get("reply_to_message_id", "")).strip()
    if not to_addr or not subject or not body:
        return "'to', 'subject', and 'body' are required to prepare an email for sending."

    # Also attempt to save as a Gmail Draft if scopes allow
    draft_id = None
    gmail = google_services().get("gmail")
    if gmail is not None:
        try:
            msg_obj = _build_raw_mime_message(to_addr, subject, body, cc, reply_to)
            draft = gmail.users().drafts().create(userId="me", body={"message": msg_obj}).execute()
            draft_id = draft.get("id")
        except Exception:  # noqa: BLE001
            draft_id = None

    summary = f"Send email to {to_addr} — Subject: {subject}"
    payload = {
        "to": to_addr,
        "cc": cc,
        "subject": subject,
        "body": body,
        "reply_to_message_id": reply_to,
        "draft_id": draft_id,
    }
    rec = db.create_pending_approval("gmail_send", summary, payload)
    if not rec:
        return "Error staging email in approval queue."
    aid = rec["id"]
    draft_note = f" (Saved to Gmail Drafts as #{draft_id})" if draft_id else ""
    return (
        f"📧 EMAIL READY FOR APPROVAL [#{aid}]{draft_note}\n"
        f"To: {to_addr}\n"
        + (f"Cc: {cc}\n" if cc else "")
        + f"Subject: {subject}\n"
        f"---\n{body}\n---\n"
        f"Present this draft clearly to the user. They can approve sending it in natural language "
        f"(e.g. 'yes, send it' or 'approve') or with `/approve {aid}` (or cancel with 'cancel' / `/reject {aid}`)."
    )


# ---------------------------------------------------------------------------
# 3. Phone SMS / Text Message Read Tools (Always Active)
# ---------------------------------------------------------------------------

def tool_messages_recent(args):
    """Read the most recent SMS messages synced from the phone without needing a search query."""
    try:
        limit = min(int(args.get("limit", 15) or 15), 50)
    except (TypeError, ValueError):
        limit = 15
    direction = str(args.get("direction", "all") or "all").strip().lower()
    res = db.query_recent_sms(limit=limit, direction=direction)
    if not res:
        return "Database unavailable for SMS query."
    rows, total = res
    if not rows:
        return "No phone SMS messages have been synced yet."
    lines = [
        f"- [{format_ms_date(r.get('date'))}] {r.get('address')}{(' (' + r['contact_name'] + ')') if r.get('contact_name') else ''}: {r.get('body')}"
        for r in rows
    ]
    return f"Showing {len(rows)} most recent phone message(s) (out of {total} total):\n" + "\n".join(lines)


def tool_messages_search(args):
    """Search phone SMS messages using hybrid Full-Text + pgvector semantic similarity."""
    query = str(args.get("query", "")).strip()
    try:
        limit = min(int(args.get("limit", 15) or 15), 50)
    except (TypeError, ValueError):
        limit = 15
    if not query:
        return tool_messages_recent({"limit": limit})
    res = db.search_sms_db(query, limit=limit)
    if not res:
        return "Database unavailable for SMS search."
    rows, count = res
    if not rows:
        return f"No stored phone SMS messages matched '{query}'."
    lines = [
        f"- [{format_ms_date(r.get('date'))}] {r.get('address')}: {r.get('body')}"
        for r in rows
    ]
    return f"{count} matching phone SMS message(s) for '{query}':\n" + "\n".join(lines)


def tool_messages_thread(args):
    """Read chronological SMS conversation history with a specific phone number or contact."""
    target = str(args.get("address_or_name", "")).strip()
    if not target:
        return "address_or_name is required."
    try:
        limit = min(int(args.get("limit", 25) or 25), 100)
    except (TypeError, ValueError):
        limit = 25
    rows = db.query_sms_thread(target, limit=limit)
    if not rows:
        return f"No SMS thread found matching '{target}'."
    lines = []
    for r in rows:
        who = "Sent" if str(r.get("type")) in ("2", "sent") else f"From {r.get('address')}"
        lines.append(f"[{format_ms_date(r.get('date'))}] {who}: {r.get('body')}")
    return f"SMS conversation thread for '{target}' ({len(rows)} messages):\n" + "\n".join(lines)


# ---------------------------------------------------------------------------
# 4. Google Calendar & Contacts Tools
# ---------------------------------------------------------------------------

def tool_calendar_list(args):
    calendar = google_services().get("calendar")
    if calendar is None:
        return "Calendar is not connected."
    try:
        days = min(int(args.get("days", 7) or 7), 60)
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
            return f"No calendar events in the next {days} day(s)."
        lines = []
        for ev in events:
            start = ev.get("start", {}).get("dateTime") or ev.get("start", {}).get("date", "")
            end = ev.get("end", {}).get("dateTime") or ev.get("end", {}).get("date", "")
            lines.append(f"- [{ev.get('id', '')}] {start} to {end} | {ev.get('summary', '(no title)')}")
        return "\n".join(lines)
    except Exception as e:  # noqa: BLE001
        return f"Calendar list failed: {e}"


def tool_calendar_create(args):
    calendar = google_services().get("calendar")
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
        return f"Created event: {title} ({start} to {end}), id {ev.get('id', '')}"
    except Exception as e:  # noqa: BLE001
        return f"Calendar create failed: {e}"


def tool_calendar_delete(args):
    """Approval-gated calendar event deletion."""
    event_id = str(args.get("event_id", "")).strip()
    title = str(args.get("title", "")).strip() or event_id
    if not event_id:
        return "event_id is required."
    summary = f"Delete calendar event '{title}' [{event_id}]"
    rec = db.create_pending_approval("calendar_delete", summary, {"event_id": event_id, "title": title})
    if not rec:
        return "Failed to stage calendar deletion approval."
    aid = rec["id"]
    return (
        f"🗑️ PENDING CALENDAR DELETION [#{aid}]\n"
        f"Event: {title} (ID: {event_id})\n"
        f"Ask the user to confirm in natural language ('yes, delete it') or via `/approve {aid}`."
    )


def tool_contacts_search(args):
    """Search Google Contacts + PostgreSQL memory for a person's email/phone."""
    query = str(args.get("query", "")).strip()
    if not query:
        return "query is required."
    matches = []
    # 1. Check PostgreSQL long-term memory for contact info
    mem_rows = db.recall_memories(query, category="contact", limit=5)
    for r in mem_rows:
        matches.append(f"[Memory] {r.get('subject') or ''}: {r.get('content')}")

    # 2. Check Google Contacts (People API) if available
    people = google_services().get("people")
    if people is not None:
        try:
            res = (
                people.people()
                .searchContacts(
                    query=query,
                    readMask="names,emailAddresses,phoneNumbers,organizations",
                    pageSize=10,
                )
                .execute()
            )
            for item in res.get("results", []) or []:
                person = item.get("person", {})
                names = [n.get("displayName", "") for n in person.get("names", [])]
                emails = [e.get("value", "") for e in person.get("emailAddresses", [])]
                phones = [p.get("value", "") for p in person.get("phoneNumbers", [])]
                name_str = names[0] if names else "(unnamed)"
                matches.append(
                    f"[Google Contacts] {name_str} | Emails: {', '.join(emails) or 'none'} | Phones: {', '.join(phones) or 'none'}"
                )
        except Exception:  # noqa: BLE001
            pass

    if not matches:
        return f"No contacts found matching '{query}'."
    return "\n".join(matches)


# ---------------------------------------------------------------------------
# 5. Long-Term Memory, Tasks & Web Tools
# ---------------------------------------------------------------------------

def tool_memory_remember(args):
    content = str(args.get("content", "")).strip()
    category = str(args.get("category", "general") or "general").strip().lower()
    subject = str(args.get("subject", "") or "").strip()
    importance = args.get("importance", 3)
    if not content:
        return "content is required."
    row = db.remember_fact(content, category=category, subject=subject, source_type="tool", importance=importance)
    if not row:
        return "Failed to save memory to PostgreSQL."
    return f"Saved to long-term memory [#{row['id']}] ({row['category']}): {row['content']}"


def tool_memory_recall(args):
    query = str(args.get("query", "")).strip()
    category = str(args.get("category", "") or "").strip().lower() or None
    limit = args.get("limit", 8)
    rows = db.recall_memories(query=query, category=category, limit=limit)
    if not rows:
        return f"No stored memories matched '{query}'."
    lines = [
        f"- [#{r['id']}] ({r['category']}) {r['subject'] + ': ' if r.get('subject') else ''}{r['content']}"
        for r in rows
    ]
    return "Recalled memories:\n" + "\n".join(lines)


def tool_memory_forget(args):
    target = str(args.get("target", "")).strip()
    if not target:
        return "target (memory ID or text) is required."
    deleted = db.forget_memory(target)
    return f"Deleted {deleted} matching memory record(s)."


def tool_task_add(args):
    title = str(args.get("title", "")).strip()
    notes = str(args.get("notes", "") or "").strip()
    category = str(args.get("category", "general") or "general").strip()
    due_at = args.get("due_at") or None
    if not title:
        return "title is required."
    row = db.add_task(title, notes=notes, category=category, due_at=due_at)
    if not row:
        return "Failed to create task."
    return f"Added task [#{row['id']}] ({row['category']}): {row['title']}"


def tool_task_list(args):
    status = str(args.get("status", "open") or "open").strip()
    category = str(args.get("category", "") or "").strip() or None
    rows = db.list_tasks(status=status, category=category)
    if not rows:
        return f"No {status} tasks."
    lines = [
        f"- [#{r['id']}] ({r['category']}) {r['title']}"
        + (f" — {r['notes']}" if r.get("notes") else "")
        + (f" [Due: {r['due_at']}]" if r.get("due_at") else "")
        for r in rows
    ]
    return f"{len(rows)} {status} task(s):\n" + "\n".join(lines)


def tool_task_complete(args):
    task_id = args.get("task_id")
    if not task_id:
        return "task_id is required."
    ok = db.complete_task(task_id)
    return f"Task #{task_id} marked complete." if ok else f"Task #{task_id} not found."


def tool_web_search(args):
    query = str(args.get("query", "")).strip()
    if not query:
        return "query is required."
    url = "https://html.duckduckgo.com/html/?" + urllib.parse.urlencode({"q": query})
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) FinAssistant/2.0"},
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            raw_html = resp.read().decode("utf-8", "replace")
        # Extract result titles and snippets from DuckDuckGo HTML
        snippets = re.findall(
            r'<a class="result__snippet"[^>]*>(.*?)</a>', raw_html, flags=re.DOTALL
        )
        titles = re.findall(
            r'<a rel="nofollow" class="result__a" href="([^"]+)"[^>]*>(.*?)</a>',
            raw_html,
            flags=re.DOTALL,
        )
        results = []
        for idx, (href, title_html) in enumerate(titles[:6]):
            clean_title = html_to_text(title_html)
            clean_snip = html_to_text(snippets[idx]) if idx < len(snippets) else ""
            results.append(f"- {clean_title}\n  URL: {href}\n  {clean_snip}")
        if not results:
            return html_to_text(raw_html)[:3000]
        return f"Web results for '{query}':\n" + "\n".join(results)
    except Exception as e:  # noqa: BLE001
        return f"Web search failed: {e}"


def tool_web_fetch(args):
    url = str(args.get("url", "")).strip()
    if not url.startswith(("http://", "https://")):
        return "Valid http:// or https:// url is required."
    try:
        max_chars = min(int(args.get("max_chars", 6000) or 6000), 15000)
    except (TypeError, ValueError):
        max_chars = 6000
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) FinAssistant/2.0"},
    )
    try:
        with urllib.request.urlopen(req, timeout=12) as resp:
            raw = resp.read().decode("utf-8", "replace")
        text = html_to_text(raw)
        return f"Content from {url}:\n\n{text[:max_chars]}"
    except Exception as e:  # noqa: BLE001
        return f"Web fetch failed: {e}"


# ---------------------------------------------------------------------------
# 6. Execute Approved Action (Called when user approves via NL or /approve)
# ---------------------------------------------------------------------------

def execute_approved_action(approval_record):
    """Execute a pending approval record and mark it resolved in PostgreSQL."""
    if not approval_record:
        return "No pending approval found."
    aid = approval_record["id"]
    action_type = approval_record["action_type"]
    payload = approval_record.get("payload") or {}
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except ValueError:
            payload = {}

    try:
        if action_type == "gmail_send":
            gmail = google_services().get("gmail")
            if gmail is None:
                return f"❌ Cannot send email #{aid}: Gmail is not connected."
            draft_id = payload.get("draft_id")
            if draft_id:
                sent = gmail.users().drafts().send(userId="me", body={"id": draft_id}).execute()
            else:
                msg_obj = _build_raw_mime_message(
                    payload.get("to", ""),
                    payload.get("subject", ""),
                    payload.get("body", ""),
                    payload.get("cc", ""),
                    payload.get("reply_to_message_id", ""),
                )
                sent = gmail.users().messages().send(userId="me", body=msg_obj).execute()
            msg = f"✅ Approved & Sent Email [#{aid}] to {payload.get('to')} (Subject: '{payload.get('subject')}', Message ID: {sent.get('id', '')})."
            db.resolve_pending_approval(aid, "approved", msg)
            db.log_audit_event("approval_gate", "gmail_send", payload, msg, status="approved")
            return msg

        if action_type == "drive_update":
            drive = google_services().get("drive")
            if drive is None:
                return f"❌ Cannot update Drive file #{aid}: Google Drive is not connected."
            from googleapiclient.http import MediaIoBaseUpload

            media = MediaIoBaseUpload(
                io.BytesIO(str(payload.get("new_content", "")).encode("utf-8")),
                mimetype="text/plain",
                resumable=False,
            )
            updated = (
                drive.files()
                .update(fileId=payload.get("file_id"), media_body=media, fields="id, name, webViewLink")
                .execute()
            )
            msg = f"✅ Approved & Updated Drive file '{updated.get('name')}' [#{aid}]."
            db.resolve_pending_approval(aid, "approved", msg)
            db.log_audit_event("approval_gate", "drive_update", payload, msg, status="approved")
            return msg

        if action_type == "calendar_delete":
            calendar = google_services().get("calendar")
            if calendar is None:
                return f"❌ Cannot delete Calendar event #{aid}: Calendar is not connected."
            calendar.events().delete(calendarId="primary", eventId=payload.get("event_id")).execute()
            msg = f"✅ Approved & Deleted Calendar event '{payload.get('title')}' [#{aid}]."
            db.resolve_pending_approval(aid, "approved", msg)
            db.log_audit_event("approval_gate", "calendar_delete", payload, msg, status="approved")
            return msg

        if action_type == "mcp_call":
            from mcp_bridge import execute_mcp_tool_direct

            res = execute_mcp_tool_direct(payload.get("server"), payload.get("tool"), payload.get("arguments") or {})
            msg = f"✅ Approved & Executed MCP tool {payload.get('tool')} [#{aid}]:\n{res}"
            db.resolve_pending_approval(aid, "approved", msg)
            db.log_audit_event("approval_gate", "mcp_call", payload, msg, status="approved")
            return msg

        return f"Unknown approval action type: {action_type}"
    except Exception as e:  # noqa: BLE001
        err_str = str(e)
        if "insufficientPermissions" in err_str or "403" in err_str:
            return (
                f"⚠️ Approval #{aid} stays pending: Google token needs updated permissions "
                f"(Gmail Send / Drive). Run `python3 server/auth_google.py` once on the PC, then approve again."
            )
        db.resolve_pending_approval(aid, "failed", err_str)
        return f"❌ Execution of approved action #{aid} failed: {e}"


# ---------------------------------------------------------------------------
# Tool Definitions Schema & Function Map
# ---------------------------------------------------------------------------

NATIVE_TOOL_DEFS = [
    {
        "type": "function",
        "function": {
            "name": "drive_search",
            "description": "Search the user's Google Drive files and folders by name or full-text content.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search keywords for file name or document text"},
                    "file_type": {
                        "type": "string",
                        "description": "Optional filter: 'any', 'doc', 'sheet', 'pdf', or 'folder'",
                    },
                    "max_results": {"type": "integer", "description": "Max files to return, default 10"},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "drive_read",
            "description": "Read the full text content of a Google Drive file (Google Doc, Sheet, or text file) by file_id.",
            "parameters": {
                "type": "object",
                "properties": {
                    "file_id": {"type": "string", "description": "Google Drive file ID from drive_search or drive_list_folder"},
                    "max_chars": {"type": "integer", "description": "Max characters to return, default 8000"},
                },
                "required": ["file_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "drive_list_folder",
            "description": "List files and folders inside a Google Drive folder (default 'root').",
            "parameters": {
                "type": "object",
                "properties": {
                    "folder_id": {"type": "string", "description": "Folder ID, or 'root' for top-level Drive"},
                    "max_results": {"type": "integer", "description": "Max items, default 20"},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "drive_create_file",
            "description": "Create a new Google Doc or text file in the user's Google Drive.",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Document title / filename"},
                    "content": {"type": "string", "description": "Text content of the document"},
                    "folder_id": {"type": "string", "description": "Optional parent folder ID"},
                    "as_google_doc": {"type": "boolean", "description": "Create as Google Doc (default true)"},
                },
                "required": ["name", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "drive_update_file",
            "description": "Stage an update to an existing Google Drive file (requires user approval before overwriting).",
            "parameters": {
                "type": "object",
                "properties": {
                    "file_id": {"type": "string", "description": "Drive file ID to update"},
                    "new_content": {"type": "string", "description": "New text content"},
                },
                "required": ["file_id", "new_content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "gmail_search",
            "description": "Search the user's Gmail. Returns sender, subject, date, snippet and message id for each match.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Gmail search query, e.g. 'from:payit is:unread'"},
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
            "description": "Read the full body, headers, and attachment list of a Gmail message by its message_id.",
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
            "name": "gmail_create_draft",
            "description": "Save a draft email in the user's Gmail Drafts folder without sending it.",
            "parameters": {
                "type": "object",
                "properties": {
                    "to": {"type": "string", "description": "Recipient email address"},
                    "subject": {"type": "string", "description": "Email subject line"},
                    "body": {"type": "string", "description": "Plain text email body"},
                    "cc": {"type": "string", "description": "Optional CC email addresses"},
                    "reply_to_message_id": {"type": "string", "description": "Optional Gmail message_id being replied to"},
                },
                "required": ["to", "subject", "body"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "gmail_prepare_send",
            "description": "Draft an email and stage it for sending with user approval. Always use this when the user asks to send or reply to an email.",
            "parameters": {
                "type": "object",
                "properties": {
                    "to": {"type": "string", "description": "Recipient email address"},
                    "subject": {"type": "string", "description": "Email subject line"},
                    "body": {"type": "string", "description": "Full email body text"},
                    "cc": {"type": "string", "description": "Optional CC email addresses"},
                    "reply_to_message_id": {"type": "string", "description": "Optional Gmail message_id being replied to"},
                },
                "required": ["to", "subject", "body"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "messages_recent",
            "description": "Read the most recent SMS/text messages synced from the user's phone (no search query required).",
            "parameters": {
                "type": "object",
                "properties": {
                    "limit": {"type": "integer", "description": "Number of recent messages to read, default 15"},
                    "direction": {"type": "string", "description": "'all', 'inbox', or 'sent'"},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "messages_search",
            "description": "Search SMS/text messages from the user's phone by keyword, sender, or semantic meaning.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Text, topic, or sender to search for"},
                    "limit": {"type": "integer", "description": "Max results, default 15"},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "messages_thread",
            "description": "Read the chronological SMS conversation thread with a specific phone number or contact.",
            "parameters": {
                "type": "object",
                "properties": {
                    "address_or_name": {"type": "string", "description": "Phone number or contact name"},
                    "limit": {"type": "integer", "description": "Max messages in thread, default 25"},
                },
                "required": ["address_or_name"],
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
            "name": "calendar_delete",
            "description": "Stage deletion of a Google Calendar event (requires user approval).",
            "parameters": {
                "type": "object",
                "properties": {
                    "event_id": {"type": "string", "description": "Event ID from calendar_list"},
                    "title": {"type": "string", "description": "Event title for confirmation display"},
                },
                "required": ["event_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "contacts_search",
            "description": "Search Google Contacts and stored memory to find a person's email address or phone number.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Person's name, company, or handle"},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "memory_remember",
            "description": "Save an important fact, user preference, contact, or project detail into PostgreSQL + pgvector long-term memory.",
            "parameters": {
                "type": "object",
                "properties": {
                    "content": {"type": "string", "description": "Clear, self-contained fact to remember"},
                    "category": {
                        "type": "string",
                        "description": "'preference', 'fact', 'contact', 'project', 'job_search', or 'general'",
                    },
                    "subject": {"type": "string", "description": "Short topic or person name"},
                    "importance": {"type": "integer", "description": "1 (low) to 5 (critical), default 3"},
                },
                "required": ["content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "memory_recall",
            "description": "Search PostgreSQL + pgvector long-term memory for stored facts, preferences, contacts, or past discussions.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Question or topic to search for in memory"},
                    "category": {"type": "string", "description": "Optional category filter"},
                    "limit": {"type": "integer", "description": "Max results, default 8"},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "memory_forget",
            "description": "Delete an outdated or incorrect fact from long-term memory by ID or keyword.",
            "parameters": {
                "type": "object",
                "properties": {
                    "target": {"type": "string", "description": "Memory ID number or text to remove"},
                },
                "required": ["target"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "task_add",
            "description": "Create a persistent task, reminder, or job application tracker entry in PostgreSQL.",
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "Task or reminder title"},
                    "notes": {"type": "string", "description": "Additional details"},
                    "category": {"type": "string", "description": "'general', 'reminder', 'job_application', or 'followup'"},
                    "due_at": {"type": "string", "description": "Optional ISO due date/time"},
                },
                "required": ["title"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "task_list",
            "description": "List open or completed tasks, reminders, and job applications.",
            "parameters": {
                "type": "object",
                "properties": {
                    "status": {"type": "string", "description": "'open' or 'done', default 'open'"},
                    "category": {"type": "string", "description": "Optional category filter"},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "task_complete",
            "description": "Mark a task or reminder as completed by its task_id.",
            "parameters": {
                "type": "object",
                "properties": {
                    "task_id": {"type": "integer", "description": "Task ID number"},
                },
                "required": ["task_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": "Search the web for current information, companies, documentation, or news.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search query"},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "web_fetch",
            "description": "Fetch and read the text content of a web page URL.",
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "Full http/https URL"},
                    "max_chars": {"type": "integer", "description": "Max characters to read, default 6000"},
                },
                "required": ["url"],
            },
        },
    },
]

NATIVE_TOOL_FUNCS = {
    "drive_search": tool_drive_search,
    "drive_read": tool_drive_read,
    "drive_list_folder": tool_drive_list_folder,
    "drive_create_file": tool_drive_create_file,
    "drive_update_file": tool_drive_update_file,
    "gmail_search": tool_gmail_search,
    "gmail_read": tool_gmail_read,
    "gmail_create_draft": tool_gmail_create_draft,
    "gmail_prepare_send": tool_gmail_prepare_send,
    "messages_recent": tool_messages_recent,
    "messages_search": tool_messages_search,
    "messages_thread": tool_messages_thread,
    "calendar_list": tool_calendar_list,
    "calendar_create": tool_calendar_create,
    "calendar_delete": tool_calendar_delete,
    "contacts_search": tool_contacts_search,
    "memory_remember": tool_memory_remember,
    "memory_recall": tool_memory_recall,
    "memory_forget": tool_memory_forget,
    "task_add": tool_task_add,
    "task_list": tool_task_list,
    "task_complete": tool_task_complete,
    "web_search": tool_web_search,
    "web_fetch": tool_web_fetch,
}
