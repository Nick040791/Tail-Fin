# Fin agent server

Runs on the PC next to Ollama. Single file, Python standard library only for chat.

## Run

```bash
python server.py
```

Listens on port 8080. First run prints a pairing token and saves it to
`token.txt` — enter that token in the Fin app's settings.

## Model Switching & Providers

### Chat Slash Commands:
- Send `/models` to display all available local Ollama and cloud models with index numbers.
- Send `/model <number>` (e.g. `/model 3`) or `/model <name>` (e.g. `/model gemini-2.5-flash`) to switch active models instantly.

### Supported Providers:
1. **Ollama (Local Default)** — any model pulled into Ollama (`flint`, `gemma4`, `nemotron`, etc.).
2. **Google Gemini API** — set `GEMINI_API_KEY=AIza...` in `.env`.
3. **OpenRouter API** — set `OPENROUTER_API_KEY=sk-or-...` in `.env`.

## REST API

- `GET /health` → `{"status": "ok", "model": "...", "provider": "...", "tools": true}`
- `GET /api/models` → lists active and available models
- `POST /api/models` → `{"model": "<name or number>"}` switches active model
- `POST /api/chat` with `Authorization: Bearer <token>` and body
  `{"messages": [{"role": "user", "content": "..."}]}` → newline-delimited
  JSON: `{"delta": "..."}` chunks, then `data: [DONE]`.
- `POST /api/messages` → syncs SMS text messages
- `GET /api/messages?q=query` → searches synced SMS text messages

## Config (`.env` file or environment variables)

- `FIN_PORT` — default `8080`
- `FIN_TOKEN` — pairing token (generated + saved to `token.txt` if unset)
- `OLLAMA_URL` — default `http://127.0.0.1:11434`
- `FIN_MODEL` — default `flint:40b-a2b-qat-int4`
- `FIN_NUM_CTX` — context cap, default `32768`
- `GEMINI_API_KEY` — API key for Google Gemini models
- `OPENROUTER_API_KEY` — API key for OpenRouter models

Full setup is in `../SETUP-GUIDE.md`.
