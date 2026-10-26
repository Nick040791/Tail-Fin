"""Configuration loader, constants, and LLM provider resolution for Fin Server."""

import os
import secrets

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
EMBED_MODEL = os.environ.get("FIN_EMBED_MODEL", "nomic-embed-text-v2-moe:latest")
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
