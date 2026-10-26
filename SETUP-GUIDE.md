# Fin — PC setup guide

What you're building: your own assistant. The brain runs on your PC
(Ollama + Flint + a small server). Your phone just talks to it over
Tailscale. Nothing is exposed to the internet, and your Google
credentials never go inside the APK.

```
Phone (Fin APK) --Tailscale--> PC (Tailscale) --> Fin server :8080 --> Ollama :11434 --> Flint 40B
```

## What you need

- Your PC: Windows, 64GB RAM (Flint runs on CPU — no GPU needed)
- Your Android phone with the Fin APK installed
- About 30GB free disk on the PC (23GB model download + Ollama)
- A Tailscale account (free for personal use)

## Step 1 — Tailscale (PC + phone)

1. On the PC: install Tailscale from tailscale.com, sign in, and leave it running.
2. On the phone: install the Tailscale app from the Play Store, sign in with the
   same account, and connect.
3. On the PC, find its Tailscale address: open a terminal and run
   `tailscale ip` — it looks like `100.x.x.x`. Write it down; the app needs it.
   (You can also use the PC's MagicDNS name, e.g. `mypc.tailnet.ts.net`.)

## Step 2 — Ollama + Flint (PC)

1. Install Ollama from ollama.com (Windows installer).
2. Pull the model — this downloads ~23GB, so give it time:
   ```
   ollama run flint:40b-a2b-qat-int4
   ```
   Type a test message at the prompt to confirm it answers, then `/bye` to exit.
3. Ollama only listens on localhost by default. To let the Fin server reach it
   from the Tailscale network, set the environment variable:
   ```
   OLLAMA_HOST=0.0.0.0:11434
   ```
   On Windows: Settings → System → About → Advanced system settings →
   Environment Variables → New (user variable). Restart Ollama after setting it
   (right-click the Ollama tray icon → Quit, then launch it again).
4. Leave Ollama running. It starts automatically with Windows by default.

## Step 3 — Fin server (PC)

1. Install Python 3.12 from python.org (check "Add python.exe to PATH"
   during install).
2. Copy the `server` folder from this project onto the PC (anywhere, e.g.
   `C:\fin-server`).
3. Open a terminal in that folder and run:
   ```
   python server.py
   ```
   First run prints a pairing token and saves it to `token.txt` in the same
   folder. **Copy that token — the app needs it.**
4. Windows Firewall will ask whether to allow Python through — allow it
   (Private networks is enough; Tailscale counts as private).
5. Leave the terminal window open while you use Fin, or run it in the
   background. To run it on startup later, a scheduled task or a shortcut in
   the Startup folder both work.

The server is a single file, standard library only — no pip installs
for chat. It listens on port 8080, checks the Bearer token on every request, and
forwards chat to Ollama with context capped at 32K tokens (so the KV cache
doesn't eat the RAM the weights need). Optional extras live in the same
folder: `.env` for settings, `auth_google.py` for Gmail/Calendar, and a
message store the phone app syncs to — see Phase 2 below.

## Step 4 — Fin app (phone)

1. Make sure Tailscale is connected on the phone.
2. Open Fin → Settings (gear icon).
3. Server URL: `http://100.x.x.x:8080` — using the PC's Tailscale address
   from Step 1. (Use `http`, not `https` — it's your private network.)
4. Pairing token: paste the token from Step 3.
5. Save, go back, and send a message.

## Step 5 — Test it

- In the app, send "Hello". First reply is slow — Flint is running on CPU,
  and the first tokens take a while. After that it streams.
- If the app says it can't reach the server: check Tailscale is connected on
  both ends, the URL has the right `100.x` address, the server terminal is
  still running on the PC, and the token matches `token.txt` exactly.
- From the PC itself you can test with:
  ```
  curl http://127.0.0.1:8080/health
  ```

## What works now (v1 + Phase 2)

- Chat with Flint, streaming replies, conversation history in the app.
- The server injects the current date/time so Fin knows what day it is.
- **`.env` settings file** — copy `.env.example` to `.env` in the server
  folder to set `FIN_PORT`, `FIN_TOKEN`, `OLLAMA_URL`, `FIN_MODEL`,
  `FIN_NUM_CTX`, or future API keys. Values already set in the environment
  win. Never share your `.env`.
- **Phone messages store** — the Fin app syncs SMS to the server
  (`POST /api/messages`, same Bearer token). Messages are saved in
  `messages.json` next to `server.py`, duplicates are ignored, and Fin can
  search them once tools are enabled (below). Search them directly with
  `GET /api/messages?q=mom&limit=20` using the token.
- **Gmail + Calendar tools** — see Phase 2 below.

## Phase 3 — Slash commands (no model call needed)

Some things shouldn't depend on the model choosing the right tool. These
commands are answered by the server itself, before Ollama is involved —
type them as a message in the app:

- `/help` — list all commands
- `/messages <search>` — search the texts synced from your phone
  (e.g. `/messages interview`). With no search words it shows the 5 most
  recent. Works with no Google setup at all.
- `/calendar [days]` — upcoming events (default 7 days, e.g. `/calendar 3`)
- `/gmail <search>` — search Gmail (e.g. `/gmail interview`)

If Google tools aren't connected, `/calendar` and `/gmail` tell you so and
point at `auth_google.py` instead of failing. Any message that doesn't
start with `/` goes through Flint as normal.

**Why Fin couldn't read your messages:** the phone texts were already
synced to the server, but answering a question about them required Flint
to pick the `messages_search` tool on its own — and it doesn't always do
that. `/messages` skips the model entirely and searches the store
directly, so it always works.

**Switching models:** the server exposes `GET /models` (same Bearer
token), which lists every model Ollama has installed plus the current
default. The app uses it for the model selector, and each chat request
can pick a model — pull another one with `ollama pull <name>` and it
shows up. No server restart needed.

## Phase 2 — Gmail + Calendar tools (do this on the PC)

Fin can search and read your Gmail and list/create calendar events once
you connect your Google account. Do these steps in order:

1. **Create a Google Cloud project**: go to console.cloud.google.com,
   create a new project (any name, e.g. "Fin").
2. **Enable the APIs**: in the project, go to APIs & Services → Library,
   enable **Gmail API** and **Google Calendar API**.
3. **Create OAuth credentials**: APIs & Services → Credentials → Create
   Credentials → OAuth client ID → application type **Desktop app** → Create.
   Download the JSON file.
4. **Save it as `credentials.json`** in the server folder (same folder as
   `server.py`). It stays on your PC — never put it in the APK or share it.
5. **Install the Google libraries** (in the server folder):
   ```
   pip install -r requirements-google.txt
   ```
6. **Sign in once**:
   ```
   python auth_google.py
   ```
   A browser window opens for the Google sign-in. Pick the account, allow
   Gmail (read-only) and Calendar access. This saves `token.json` in the
   server folder.
7. **Restart the server** (`python server.py`). It prints
   `Google tools: enabled`. If it still says off, check that `token.json`
   exists and the sign-in step completed.
8. **Test it from the app**: ask "check my email about interviews" or
   "what's on my calendar this week" — Fin will use the tools and answer
   from your real mail and calendar. To add an event: "add a dentist
   appointment Tuesday at 9am" (give a date and time).

What Fin can do with the tools: `gmail_search` (find mail),
`gmail_read` (read one message), `calendar_list` (upcoming events),
`calendar_create` (add an event), and `messages_search` (search synced
phone texts). Tool failures never crash a chat — Fin just says the tool
didn't work and carries on.

**How Fin reads your mobile messages — no Google API involved:** SMS
lives only on your phone, and Google has no API for it. Instead the Fin
app itself reads your texts on-device (it will ask for SMS permission)
and syncs them to the server's `messages.json` store over Tailscale.
Gmail/Outlook mail is different — that goes through the Google tools
above, because mail lives on Google's servers.

## Still to come

- **Proactive stuff** (reminders, scheduled checks): needs a scheduler on the
  PC, e.g. a small script that calls the server on a timer.

## Troubleshooting

- **"Can't reach the server" in the app**: Tailscale disconnected, wrong IP,
  server not running, or Windows Firewall blocking Python.
- **Ollama errors / model not found**: run `ollama list` — if Flint isn't
  there, re-run the pull in Step 2.
- **Very slow replies**: expected on CPU (single-digit tokens/sec). Shorter
  replies help. If you ever add a 24GB GPU, switch the model to Muse Glimmer.
- **Token rejected**: tokens are case-sensitive; copy from `token.txt`, don't
  retype it. To reset, delete `token.txt` and restart the server.
