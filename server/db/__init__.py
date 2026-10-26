"""PostgreSQL + pgvector relational & vector database layer for Fin Assistant."""

import datetime
import hashlib
import json
import os
import secrets
import sys
import urllib.request

try:
    import psycopg
    from psycopg.rows import dict_row
    HAS_PSYCOPG = True
except ImportError:
    psycopg = None
    dict_row = None
    HAS_PSYCOPG = False

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCHEMA_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "schema.sql")

EMBED_MODEL = os.environ.get("FIN_EMBED_MODEL", "nomic-embed-text-v2-moe:latest")
EMBED_DIM = 768


def get_db_dsn():
    dsn = os.environ.get("FIN_DB_DSN")
    if dsn:
        return dsn
    host = os.environ.get("FIN_DB_HOST", "127.0.0.1")
    port = os.environ.get("FIN_DB_PORT", "5438")
    user = os.environ.get("FIN_DB_USER", "fin")
    password = os.environ.get("FIN_DB_PASSWORD", "fin_local_secret")
    dbname = os.environ.get("FIN_DB_NAME", "fin_assistant")
    return f"postgresql://{user}:{password}@{host}:{port}/{dbname}"


def get_conn():
    """Return a psycopg connection with dict_row factory, or None if unavailable."""
    if not HAS_PSYCOPG:
        return None
    try:
        return psycopg.connect(get_db_dsn(), row_factory=dict_row, connect_timeout=3)
    except Exception as e:  # noqa: BLE001
        sys.stderr.write(f"[db] PostgreSQL connection warning: {e}\n")
        return None


def db_available():
    conn = get_conn()
    if conn is None:
        return False
    conn.close()
    return True


def init_db_schema():
    """Ensure schema.sql is applied on startup."""
    conn = get_conn()
    if conn is None:
        return False
    try:
        if os.path.exists(SCHEMA_PATH):
            with open(SCHEMA_PATH, "r", encoding="utf-8") as f:
                sql = f.read()
            with conn.cursor() as cur:
                cur.execute(sql)
            conn.commit()
        return True
    except Exception as e:  # noqa: BLE001
        sys.stderr.write(f"[db] Schema init error: {e}\n")
        return False
    finally:
        conn.close()


def compute_embedding(text, timeout=6):
    """Generate a 768-dim embedding vector using local Ollama nomic-embed-text-v2-moe."""
    if not text or not str(text).strip():
        return None
    ollama_url = os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434").rstrip("/")
    payload = {
        "model": EMBED_MODEL,
        "prompt": str(text).strip()[:4000],
    }
    req = urllib.request.Request(
        ollama_url + "/api/embeddings",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        vec = data.get("embedding")
        if isinstance(vec, list) and len(vec) == EMBED_DIM:
            return vec
    except Exception as e:  # noqa: BLE001
        sys.stderr.write(f"[embed] Embedding skipped: {e}\n")
    return None


def _vec_literal(vec):
    if not vec:
        return None
    return "[" + ",".join(f"{float(x):.6f}" for x in vec) + "]"


# ---------------------------------------------------------------------------
# Phone SMS Messages (PostgreSQL + pgvector)
# ---------------------------------------------------------------------------

def message_hash_id(address, date, body):
    key = f"{address}\0{date}\0{body}"
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]


def store_sms_in_db(items, compute_vectors=False):
    """Insert SMS messages into PostgreSQL sms_messages table. Returns (new_count, total_count)."""
    conn = get_conn()
    if conn is None:
        return None
    new_count = 0
    try:
        with conn.cursor() as cur:
            for item in items:
                if not isinstance(item, dict):
                    continue
                address = str(item.get("address", "")).strip()
                body = str(item.get("body", "")).strip()
                raw_date = item.get("date", 0)
                try:
                    msg_date = int(raw_date or 0)
                except (TypeError, ValueError):
                    msg_date = 0
                if not body:
                    continue
                mid = item.get("id") or message_hash_id(address, raw_date, body)
                msg_type = str(item.get("type", ""))
                contact_name = str(item.get("contact_name", "") or "")
                vec_str = None
                if compute_vectors:
                    vec = compute_embedding(f"SMS from {address}: {body}", timeout=3)
                    vec_str = _vec_literal(vec)
                cur.execute(
                    """
                    INSERT INTO sms_messages (id, address, contact_name, body, msg_date, msg_type, embedding)
                    VALUES (%s, %s, %s, %s, %s, %s, %s::vector)
                    ON CONFLICT (id) DO NOTHING
                    """,
                    (mid, address, contact_name, body, msg_date, msg_type, vec_str),
                )
                if cur.rowcount > 0:
                    new_count += 1
            cur.execute("SELECT COUNT(*) AS cnt FROM sms_messages")
            total = cur.fetchone()["cnt"]
        conn.commit()
        return new_count, total
    except Exception as e:  # noqa: BLE001
        sys.stderr.write(f"[db] store_sms_in_db error: {e}\n")
        return None
    finally:
        conn.close()


def migrate_json_messages(json_path):
    """Migrate existing messages.json into PostgreSQL on startup."""
    if not os.path.exists(json_path):
        return 0
    try:
        with open(json_path, "r", encoding="utf-8") as f:
            items = json.load(f)
        if isinstance(items, list) and items:
            res = store_sms_in_db(items, compute_vectors=False)
            return res[0] if res else 0
    except Exception as e:  # noqa: BLE001
        sys.stderr.write(f"[db] migrate_json_messages warning: {e}\n")
    return 0


def query_recent_sms(limit=15, direction="all"):
    """Return newest SMS messages without requiring a search query."""
    conn = get_conn()
    if conn is None:
        return None
    try:
        limit = max(1, min(int(limit or 15), 100))
        with conn.cursor() as cur:
            if direction == "inbox":
                cur.execute(
                    "SELECT id, address, contact_name, body, msg_date AS date, msg_type AS type "
                    "FROM sms_messages WHERE msg_type IN ('1', 'inbox', '') ORDER BY msg_date DESC LIMIT %s",
                    (limit,),
                )
            elif direction == "sent":
                cur.execute(
                    "SELECT id, address, contact_name, body, msg_date AS date, msg_type AS type "
                    "FROM sms_messages WHERE msg_type IN ('2', 'sent') ORDER BY msg_date DESC LIMIT %s",
                    (limit,),
                )
            else:
                cur.execute(
                    "SELECT id, address, contact_name, body, msg_date AS date, msg_type AS type "
                    "FROM sms_messages ORDER BY msg_date DESC LIMIT %s",
                    (limit,),
                )
            rows = cur.fetchall()
            cur.execute("SELECT COUNT(*) AS cnt FROM sms_messages")
            total = cur.fetchone()["cnt"]
        return rows, total
    except Exception as e:  # noqa: BLE001
        sys.stderr.write(f"[db] query_recent_sms error: {e}\n")
        return None
    finally:
        conn.close()


def query_sms_thread(address_query, limit=30):
    """Return chronological SMS conversation thread matching an address or contact name."""
    conn = get_conn()
    if conn is None:
        return None
    try:
        limit = max(1, min(int(limit or 30), 100))
        q = f"%{address_query.strip()}%"
        # Normalize digits if phone number
        digits = "".join(ch for ch in address_query if ch.isdigit())
        digit_pattern = f"%{digits[-7:]}%" if len(digits) >= 7 else q
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, address, contact_name, body, msg_date AS date, msg_type AS type
                FROM sms_messages
                WHERE address ILIKE %s OR contact_name ILIKE %s OR address ILIKE %s
                ORDER BY msg_date DESC
                LIMIT %s
                """,
                (q, q, digit_pattern, limit),
            )
            rows = cur.fetchall()
        rows.reverse()  # Chronological order for reading a thread
        return rows
    except Exception as e:  # noqa: BLE001
        sys.stderr.write(f"[db] query_sms_thread error: {e}\n")
        return None
    finally:
        conn.close()


def search_sms_db(query, limit=20):
    """Hybrid search across SMS messages (FTS + ILIKE + pgvector semantic similarity)."""
    if not query or not str(query).strip():
        return query_recent_sms(limit=limit)
    conn = get_conn()
    if conn is None:
        return None
    q = str(query).strip()
    limit = max(1, min(int(limit or 20), 100))
    vec = compute_embedding(q, timeout=3)
    vec_str = _vec_literal(vec)
    try:
        with conn.cursor() as cur:
            if vec_str:
                cur.execute(
                    """
                    SELECT id, address, contact_name, body, msg_date AS date, msg_type AS type,
                           (CASE WHEN address ILIKE %s OR body ILIKE %s THEN 1.0 ELSE 0.0 END)
                           + ts_rank_cd(tsv, websearch_to_tsquery('english', %s))
                           + COALESCE(1 - (embedding <=> %s::vector), 0.0) AS score
                    FROM sms_messages
                    WHERE address ILIKE %s
                       OR contact_name ILIKE %s
                       OR body ILIKE %s
                       OR tsv @@ websearch_to_tsquery('english', %s)
                       OR (embedding IS NOT NULL AND (1 - (embedding <=> %s::vector)) > 0.55)
                    ORDER BY score DESC, msg_date DESC
                    LIMIT %s
                    """,
                    (f"%{q}%", f"%{q}%", q, vec_str, f"%{q}%", f"%{q}%", f"%{q}%", q, vec_str, limit),
                )
            else:
                cur.execute(
                    """
                    SELECT id, address, contact_name, body, msg_date AS date, msg_type AS type
                    FROM sms_messages
                    WHERE address ILIKE %s
                       OR contact_name ILIKE %s
                       OR body ILIKE %s
                       OR tsv @@ websearch_to_tsquery('english', %s)
                    ORDER BY msg_date DESC
                    LIMIT %s
                    """,
                    (f"%{q}%", f"%{q}%", f"%{q}%", q, limit),
                )
            rows = cur.fetchall()
        return rows, len(rows)
    except Exception as e:  # noqa: BLE001
        sys.stderr.write(f"[db] search_sms_db error: {e}\n")
        return None
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Long-Term Hybrid Memory (PostgreSQL + pgvector)
# ---------------------------------------------------------------------------

def remember_fact(content, category="general", subject="", source_type="chat", importance=3):
    """Store or update a memory in PostgreSQL with its 768-dim pgvector embedding."""
    content = (content or "").strip()
    if not content:
        return None
    conn = get_conn()
    if conn is None:
        return None
    importance = max(1, min(int(importance or 3), 5))
    vec = compute_embedding(f"{subject}: {content}" if subject else content, timeout=5)
    vec_str = _vec_literal(vec)
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO memories (category, subject, content, source_type, importance, embedding)
                VALUES (%s, %s, %s, %s, %s, %s::vector)
                ON CONFLICT (content) DO UPDATE
                  SET category = EXCLUDED.category,
                      subject = EXCLUDED.subject,
                      importance = GREATEST(memories.importance, EXCLUDED.importance),
                      embedding = COALESCE(EXCLUDED.embedding, memories.embedding),
                      last_accessed_at = NOW()
                RETURNING id, category, subject, content, importance
                """,
                (category, subject, content, source_type, importance, vec_str),
            )
            row = cur.fetchone()
        conn.commit()
        return row
    except Exception as e:  # noqa: BLE001
        sys.stderr.write(f"[db] remember_fact error: {e}\n")
        return None
    finally:
        conn.close()


def recall_memories(query="", category=None, limit=8):
    """Hybrid RRF search over memories using pgvector cosine similarity + PostgreSQL FTS."""
    conn = get_conn()
    if conn is None:
        return []
    limit = max(1, min(int(limit or 8), 50))
    q = (query or "").strip()
    try:
        with conn.cursor() as cur:
            if not q:
                if category:
                    cur.execute(
                        "SELECT id, category, subject, content, importance, created_at "
                        "FROM memories WHERE category = %s ORDER BY importance DESC, created_at DESC LIMIT %s",
                        (category, limit),
                    )
                else:
                    cur.execute(
                        "SELECT id, category, subject, content, importance, created_at "
                        "FROM memories ORDER BY importance DESC, created_at DESC LIMIT %s",
                        (limit,),
                    )
                return cur.fetchall()

            vec = compute_embedding(q, timeout=4)
            vec_str = _vec_literal(vec)
            cat_filter = "AND category = %s" if category else ""
            params = []
            if vec_str:
                sql = f"""
                    SELECT id, category, subject, content, importance, created_at,
                           (COALESCE(1 - (embedding <=> %s::vector), 0.0) * 0.65)
                           + (ts_rank_cd(tsv, websearch_to_tsquery('english', %s)) * 0.35)
                           + (CASE WHEN content ILIKE %s OR subject ILIKE %s THEN 0.35 ELSE 0.0 END)
                           + (importance * 0.04) AS hybrid_score
                    FROM memories
                    WHERE (
                        (embedding IS NOT NULL AND (1 - (embedding <=> %s::vector)) > 0.42)
                        OR tsv @@ websearch_to_tsquery('english', %s)
                        OR content ILIKE %s
                        OR subject ILIKE %s
                    )
                    {cat_filter}
                    ORDER BY hybrid_score DESC, importance DESC
                    LIMIT %s
                """
                params = [vec_str, q, f"%{q}%", f"%{q}%", vec_str, q, f"%{q}%", f"%{q}%"]
                if category:
                    params.append(category)
                params.append(limit)
                cur.execute(sql, params)
            else:
                sql = f"""
                    SELECT id, category, subject, content, importance, created_at
                    FROM memories
                    WHERE (tsv @@ websearch_to_tsquery('english', %s) OR content ILIKE %s OR subject ILIKE %s)
                    {cat_filter}
                    ORDER BY importance DESC, created_at DESC
                    LIMIT %s
                """
                params = [q, f"%{q}%", f"%{q}%"]
                if category:
                    params.append(category)
                params.append(limit)
                cur.execute(sql, params)
            rows = cur.fetchall()
            if rows:
                ids = [r["id"] for r in rows]
                cur.execute("UPDATE memories SET last_accessed_at = NOW() WHERE id = ANY(%s)", (ids,))
                conn.commit()
            return rows
    except Exception as e:  # noqa: BLE001
        sys.stderr.write(f"[db] recall_memories error: {e}\n")
        return []
    finally:
        conn.close()


def forget_memory(target):
    """Delete a memory by ID or matching substring."""
    conn = get_conn()
    if conn is None:
        return 0
    try:
        with conn.cursor() as cur:
            if str(target).strip().isdigit():
                cur.execute("DELETE FROM memories WHERE id = %s", (int(str(target).strip()),))
            else:
                cur.execute("DELETE FROM memories WHERE content ILIKE %s OR subject ILIKE %s", (f"%{target}%", f"%{target}%"))
            deleted = cur.rowcount
        conn.commit()
        return deleted
    except Exception as e:  # noqa: BLE001
        sys.stderr.write(f"[db] forget_memory error: {e}\n")
        return 0
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Human-in-the-Loop Pending Approvals Queue
# ---------------------------------------------------------------------------

def create_pending_approval(action_type, summary, payload):
    """Stage an action (e.g., gmail_send, drive_update, calendar_delete) for user approval."""
    conn = get_conn()
    if conn is None:
        return None
    approval_id = secrets.token_hex(2)  # 4-char hex ID like 'e4a1'
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO pending_approvals (id, action_type, summary, payload, status)
                VALUES (%s, %s, %s, %s::jsonb, 'pending')
                RETURNING id, action_type, summary, payload, status, created_at, expires_at
                """,
                (approval_id, action_type, summary, json.dumps(payload)),
            )
            row = cur.fetchone()
        conn.commit()
        return row
    except Exception as e:  # noqa: BLE001
        sys.stderr.write(f"[db] create_pending_approval error: {e}\n")
        return None
    finally:
        conn.close()


def list_pending_approvals():
    """Return all active pending approvals, newest first."""
    conn = get_conn()
    if conn is None:
        return []
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, action_type, summary, payload, status, created_at, expires_at
                FROM pending_approvals
                WHERE status = 'pending' AND expires_at > NOW()
                ORDER BY created_at DESC
                """
            )
            return cur.fetchall()
    except Exception as e:  # noqa: BLE001
        sys.stderr.write(f"[db] list_pending_approvals error: {e}\n")
        return []
    finally:
        conn.close()


def get_pending_approval(approval_id=None):
    """Get a specific pending approval by ID, or the most recent pending approval if ID is None."""
    conn = get_conn()
    if conn is None:
        return None
    try:
        with conn.cursor() as cur:
            if approval_id:
                cur.execute(
                    """
                    SELECT id, action_type, summary, payload, status, created_at
                    FROM pending_approvals
                    WHERE id = %s AND status = 'pending' AND expires_at > NOW()
                    """,
                    (str(approval_id).strip().lower(),),
                )
            else:
                cur.execute(
                    """
                    SELECT id, action_type, summary, payload, status, created_at
                    FROM pending_approvals
                    WHERE status = 'pending' AND expires_at > NOW()
                    ORDER BY created_at DESC
                    LIMIT 1
                    """
                )
            return cur.fetchone()
    except Exception as e:  # noqa: BLE001
        sys.stderr.write(f"[db] get_pending_approval error: {e}\n")
        return None
    finally:
        conn.close()


def resolve_pending_approval(approval_id, status, result_text=""):
    """Update approval status to 'approved', 'rejected', or 'failed'."""
    conn = get_conn()
    if conn is None:
        return False
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE pending_approvals
                SET status = %s, result_text = %s, resolved_at = NOW()
                WHERE id = %s
                """,
                (status, str(result_text)[:2000], str(approval_id).strip().lower()),
            )
        conn.commit()
        return True
    except Exception as e:  # noqa: BLE001
        sys.stderr.write(f"[db] resolve_pending_approval error: {e}\n")
        return False
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Tasks, Reminders & Job Tracker
# ---------------------------------------------------------------------------

def add_task(title, notes="", category="general", due_at=None):
    conn = get_conn()
    if conn is None:
        return None
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO tasks (title, notes, category, due_at)
                VALUES (%s, %s, %s, %s)
                RETURNING id, title, notes, category, status, due_at, created_at
                """,
                (title.strip(), notes.strip(), category.strip(), due_at),
            )
            row = cur.fetchone()
        conn.commit()
        return row
    except Exception as e:  # noqa: BLE001
        sys.stderr.write(f"[db] add_task error: {e}\n")
        return None
    finally:
        conn.close()


def list_tasks(status="open", category=None, limit=25):
    conn = get_conn()
    if conn is None:
        return []
    try:
        with conn.cursor() as cur:
            if category:
                cur.execute(
                    "SELECT id, title, notes, category, status, due_at, created_at "
                    "FROM tasks WHERE status = %s AND category = %s ORDER BY created_at DESC LIMIT %s",
                    (status, category, limit),
                )
            else:
                cur.execute(
                    "SELECT id, title, notes, category, status, due_at, created_at "
                    "FROM tasks WHERE status = %s ORDER BY created_at DESC LIMIT %s",
                    (status, limit),
                )
            return cur.fetchall()
    except Exception as e:  # noqa: BLE001
        sys.stderr.write(f"[db] list_tasks error: {e}\n")
        return []
    finally:
        conn.close()


def complete_task(task_id):
    conn = get_conn()
    if conn is None:
        return False
    try:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE tasks SET status = 'done', completed_at = NOW() WHERE id = %s",
                (int(task_id),),
            )
            updated = cur.rowcount > 0
        conn.commit()
        return updated
    except Exception as e:  # noqa: BLE001
        sys.stderr.write(f"[db] complete_task error: {e}\n")
        return False
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Audit Logging & Chat Persistence
# ---------------------------------------------------------------------------

def log_audit_event(actor, tool_name, arguments, result_preview, status="ok"):
    conn = get_conn()
    if conn is None:
        return
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO audit_logs (actor, tool_name, arguments, result_preview, status)
                VALUES (%s, %s, %s::jsonb, %s, %s)
                """,
                (
                    str(actor),
                    str(tool_name),
                    json.dumps(arguments if isinstance(arguments, dict) else {}),
                    str(result_preview)[:500],
                    str(status),
                ),
            )
        conn.commit()
    except Exception:  # noqa: BLE001
        pass
    finally:
        conn.close()


def log_chat_turn(user_text, assistant_text, model_name):
    conn = get_conn()
    if conn is None:
        return
    try:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO chat_sessions (title, model) VALUES (%s, %s) RETURNING id",
                ((user_text or "Chat")[:80], model_name),
            )
            sid = cur.fetchone()["id"]
            cur.execute(
                "INSERT INTO chat_messages (session_id, role, content) VALUES (%s, 'user', %s), (%s, 'assistant', %s)",
                (sid, user_text or "", sid, assistant_text or ""),
            )
        conn.commit()
    except Exception:  # noqa: BLE001
        pass
    finally:
        conn.close()
