"""Plugin & Lifecycle Hook Pipeline for Fin Assistant Server.

Includes:
1. Natural-Language & Deterministic Approval Gate Interceptor
2. Hybrid Memory + Active Skills System Prompt Context Injector
3. Secret/PII Scrubber for Tool Outputs
4. PostgreSQL Audit Logger
5. Async Auto-Memory Fact Extractor & Chat History Persister
"""

import os
import re
import sys
import threading

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import db
import skills
from tools import execute_approved_action

_APPROVE_EXACT = {
    "yes",
    "y",
    "yep",
    "yeah",
    "yup",
    "sure",
    "ok",
    "okay",
    "approve",
    "approved",
    "confirm",
    "confirmed",
    "send",
    "send it",
    "yes send",
    "yes send it",
    "yes please",
    "go ahead",
    "do it",
    "ship it",
    "looks good",
    "looks good send it",
    "proceed",
}

_REJECT_EXACT = {
    "no",
    "n",
    "nope",
    "nah",
    "cancel",
    "cancel it",
    "reject",
    "rejected",
    "discard",
    "abort",
    "stop",
    "dont send",
    "don't send",
    "do not send",
    "nevermind",
    "never mind",
}

_APPROVE_ID_RE = re.compile(
    r"^(?:yes\s*,?\s*)?(?:approve|confirm|send|execute|run)\s+#?([0-9a-f]{4})\b",
    re.IGNORECASE,
)
_REJECT_ID_RE = re.compile(
    r"^(?:no\s*,?\s*)?(?:reject|cancel|discard|abort)\s+#?([0-9a-f]{4})\b",
    re.IGNORECASE,
)


def check_natural_language_approval(user_text):
    """If there is an active pending approval and user_text is a natural language
    confirmation or rejection, execute or cancel it deterministically and return
    the response string. Otherwise return None."""
    if not user_text:
        return None
    cleaned = re.sub(r"[.!?,]+$", "", user_text.strip()).lower()
    cleaned_norm = re.sub(r"\s+", " ", cleaned)

    # 1. Check explicit ID match in natural language (e.g. "approve a3f1" or "send #a3f1")
    m_app = _APPROVE_ID_RE.match(cleaned_norm)
    if m_app:
        aid = m_app.group(1).lower()
        rec = db.get_pending_approval(aid)
        if rec:
            return execute_approved_action(rec)
        return f"No pending approval found with ID #{aid}."

    m_rej = _REJECT_ID_RE.match(cleaned_norm)
    if m_rej:
        aid = m_rej.group(1).lower()
        rec = db.get_pending_approval(aid)
        if rec:
            db.resolve_pending_approval(aid, "rejected", "Cancelled by user.")
            db.log_audit_event("approval_gate", rec["action_type"], rec.get("payload"), "Rejected by user", status="rejected")
            return f"🚫 Cancelled pending action [#{aid}]: {rec.get('summary', '')}"
        return f"No pending approval found with ID #{aid}."

    # 2. Check conversational confirmation ("yes, send it", "approve", "go ahead", "cancel it")
    # Only triggers when there is an active pending approval in the queue.
    latest = db.get_pending_approval(None)
    if not latest:
        return None

    no_commas = re.sub(r"[,;]+", " ", cleaned_norm)
    no_commas = re.sub(r"\s+", " ", no_commas).strip()

    approve_prefixes = (
        "yes send",
        "yeah send",
        "yep send",
        "sure send",
        "ok send",
        "okay send",
        "go ahead",
        "approve",
        "confirm",
        "please send",
        "looks good send",
        "send the email",
        "send that",
    )
    reject_prefixes = (
        "no cancel",
        "no dont",
        "no don't",
        "no do not",
        "cancel",
        "reject",
        "discard",
        "abort",
        "dont send",
        "don't send",
        "do not send",
        "please cancel",
    )

    if no_commas in _APPROVE_EXACT or any(no_commas.startswith(p) for p in approve_prefixes):
        return execute_approved_action(latest)

    if no_commas in _REJECT_EXACT or any(no_commas.startswith(p) for p in reject_prefixes):
        aid = latest["id"]
        db.resolve_pending_approval(aid, "rejected", "Cancelled by user in chat.")
        db.log_audit_event("approval_gate", latest["action_type"], latest.get("payload"), "Rejected by user", status="rejected")
        return f"🚫 Cancelled pending action [#{aid}]: {latest.get('summary', '')}"

    return None


def build_dynamic_context(user_text):
    """Assemble relevant long-term memories (PostgreSQL + pgvector), pending
    approvals, and matched SKILL.md instructions for the system prompt."""
    sections = []

    # 1. Relevant Long-Term Memories from PostgreSQL + pgvector
    memories = db.recall_memories(query=user_text or "", limit=5)
    if memories:
        mem_lines = [
            f"- [{r['category']}] {r['subject'] + ': ' if r.get('subject') else ''}{r['content']}"
            for r in memories
        ]
        sections.append("### Relevant User Memories (PostgreSQL + pgvector)\n" + "\n".join(mem_lines))

    # 2. Active Pending Approvals
    pending = db.list_pending_approvals()
    if pending:
        pend_lines = [
            f"- [#{p['id']}] ({p['action_type']}) {p['summary']}"
            for p in pending[:5]
        ]
        sections.append(
            "### Pending Actions Awaiting User Approval\n"
            + "\n".join(pend_lines)
            + "\n(The user can say 'yes, send it' / 'approve' or '/approve <id>' to execute, or 'cancel' / '/reject <id>'.)"
        )

    # 3. Matched Modular Skills (server/skills/*/SKILL.md)
    skill_block = skills.format_skills_prompt_injection(user_text)
    if skill_block:
        sections.append(skill_block.strip())

    return "\n\n" + "\n\n".join(sections) if sections else ""


def scrub_secrets(text):
    """Ensure API keys or pairing tokens never leak into tool outputs or logs."""
    if not text:
        return ""
    out = str(text)
    for env_key in ("FIN_TOKEN", "GEMINI_API_KEY", "GOOGLE_API_KEY", "OPENROUTER_API_KEY", "FIN_DB_PASSWORD"):
        secret_val = os.environ.get(env_key, "")
        if secret_val and len(secret_val) >= 8 and secret_val in out:
            out = out.replace(secret_val, f"[REDACTED_{env_key}]")
    out = re.sub(r"sk-or-v1-[0-9a-fA-F]{20,}", "[REDACTED_OPENROUTER_KEY]", out)
    return out


def post_tool_hook(tool_name, args, raw_result):
    """Scrub secrets from tool output and record execution in PostgreSQL audit_logs."""
    clean_result = scrub_secrets(raw_result)
    db.log_audit_event("llm_tool", tool_name, args, clean_result[:500], status="ok")
    return clean_result


def _auto_extract_memory_worker(user_text, assistant_text, model_name):
    """Background worker to persist chat turn and auto-extract explicit facts."""
    db.log_chat_turn(user_text, assistant_text, model_name)
    if not user_text:
        return
    # Detect explicit memory cues ("remember that ...", "my email is ...", "my phone number is ...")
    patterns = [
        (r"(?:please\s+)?remember\s+(?:that\s+)?(.{10,300})", "fact", 4),
        (r"my\s+(?:preferred\s+)?([a-zA-Z ]{3,25})\s+is\s+(.{3,200})", "preference", 3),
    ]
    for pat, cat, imp in patterns:
        m = re.search(pat, user_text.strip(), flags=re.IGNORECASE)
        if m:
            fact_text = user_text.strip()
            db.remember_fact(fact_text, category=cat, source_type="auto_chat", importance=imp)
            break


def post_response_hook(user_text, assistant_text, model_name):
    """Run non-blocking post-response persistence and memory curation."""
    t = threading.Thread(
        target=_auto_extract_memory_worker,
        args=(user_text, assistant_text, model_name),
        daemon=True,
    )
    t.start()
