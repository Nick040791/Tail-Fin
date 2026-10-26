# Fin Agent Server

Runs on the PC next to Ollama and the `fin-postgres` (`pgvector`) Docker container.

## Run

```bash
# 1. Start PostgreSQL + pgvector container
docker compose up -d

# 2. Start Fin Agent Server
python3 server.py
```

Listens on port `8080`. First run prints a pairing token and saves it to `token.txt` — enter that token in the Fin app's settings.

## Core Capabilities

### 1. Tools (`server/tools/`)
- **Google Drive**: `drive_search`, `drive_read` (exports Google Docs to Markdown/plain text, Sheets to CSV, reads text files), `drive_list_folder`, `drive_create_file`, and approval-gated `drive_update_file`.
- **Gmail Read, Draft & Approval-Gated Send**:
  - `gmail_search`, `gmail_read` (plain text + HTML-to-text fallback + attachment list).
  - `gmail_create_draft`: Saves a draft in Gmail Drafts without sending.
  - `gmail_prepare_send`: Stages an email in PostgreSQL's `pending_approvals` queue (and Gmail Drafts). **Never sends without your confirmation** — say *"yes, send it"* / *"approve"* in natural language or run `/approve <id>` (or *"cancel"* / `/reject <id>`).
- **Phone SMS / Text Messages**:
  - `messages_recent`: Read newest phone texts without needing a keyword query.
  - `messages_search`: Hybrid PostgreSQL Full-Text + `pgvector` semantic similarity search across synced phone texts.
  - `messages_thread`: Read chronological conversation history with a contact or phone number.
- **Google Calendar & Contacts**: `calendar_list`, `calendar_create`, approval-gated `calendar_delete`, and `contacts_search`.
- **PostgreSQL + `pgvector` Memory & Tasks**: `memory_remember`, `memory_recall`, `memory_forget`, `task_add`, `task_list`, `task_complete`.
- **Web Research**: `web_search` and `web_fetch`.

### 2. Modular Skills (`server/skills/`)
- `daily-briefing` (`/briefing`) — Executive summary of Calendar, unread Gmail, recent SMS, and open tasks.
- `inbox-triage` (`/triage`) — Prioritizes unread Gmail & recent SMS and drafts replies.
- `job-hunt-assistant` (`/jobs`) — Resume/cover-letter lookup in Drive, recruiter emails, and application tracking.
- `document-researcher` (`/research`) — Deep search across Google Drive, memory, and web.
- `schedule-coordinator` (`/schedule`) — Conflict detection and meeting coordination.
- `memory-curator` (`/memory`) — Curates persistent user facts and preferences in PostgreSQL + `pgvector`.

### 3. Memory — PostgreSQL + `pgvector` (`server/db/`)
- Powered by `pgvector/pgvector:pg17` (`fin-postgres` container on `127.0.0.1:5438`) and local Ollama embeddings (`nomic-embed-text-v2-moe:latest`, 768 dimensions).
- Combines relational SQL tables (`chat_sessions`, `chat_messages`, `sms_messages`, `memories`, `pending_approvals`, `tasks`, `audit_logs`) with HNSW vector cosine similarity and GIN full-text search.

### 4. MCP (Model Context Protocol) Bridge (`server/mcp_bridge/`)
- **MCP Client Host**: Connects to external MCP servers configured in `server/mcp_servers.json` (`stdio` and `http`) and enforces approval gates on restricted tools.
- **Fin MCP Server**: Exposes Fin's tools and memory as an MCP server for desktop/agent hosts:
  ```bash
  python3 -m server.mcp_bridge.fin_mcp_server
  ```

## Slash Commands
- `/help` — Show all commands
- `/pending` — List actions awaiting approval
- `/approve [id]` / `/reject [id]` — Approve or cancel pending actions (or use natural language: *"yes, send it"*, *"cancel"*)
- `/messages [query]` — Recent phone texts or hybrid SMS search
- `/drive <query>` — Search Google Drive
- `/gmail <query>` — Search Gmail
- `/calendar [days]` — Upcoming calendar events
- `/memory [query]` & `/remember <fact>` — Search or store PostgreSQL + `pgvector` memories
- `/tasks` — List open tasks and reminders
- `/skills` — List installed modular skills
- `/mcp [reload]` — View MCP servers and discovered tools
- `/models` & `/model <name|number>` — View and switch active LLM models

## REST API
- `GET /health` → `{"status": "ok", "model": "...", "provider": "...", "tools": true, "tool_count": 24, "db_connected": true, "skills_loaded": 6}`
- `GET /api/models` → lists active and available models
- `POST /api/chat` with `Authorization: Bearer <token>` and body `{"messages": [{"role": "user", "content": "..."}]}` → newline-delimited JSON: `{"delta": "..."}` chunks, then `data: [DONE]`.
- `POST /api/messages` → syncs SMS text messages to PostgreSQL + `messages.json`
- `GET /api/messages?q=query` → searches synced SMS text messages
