"""PostgreSQL connection helper and schema initializer."""

from db import (
    EMBED_DIM,
    EMBED_MODEL,
    HAS_PSYCOPG,
    SCHEMA_PATH,
    compute_embedding,
    db_available,
    get_conn,
    get_db_dsn,
    init_db_schema,
)

__all__ = [
    "EMBED_DIM",
    "EMBED_MODEL",
    "HAS_PSYCOPG",
    "SCHEMA_PATH",
    "compute_embedding",
    "db_available",
    "get_conn",
    "get_db_dsn",
    "init_db_schema",
]
