"""Database access: one pool, one query function, parameterised always."""

from typing import Any

from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from .settings import settings

# open=False so importing this never needs a live database (tests, linting).
pool = ConnectionPool(settings.database_url, min_size=1, max_size=5, open=False)


def _ensure_open() -> None:
    if pool.closed:
        pool.open(wait=True, timeout=10.0)


def query(sql: str, params: tuple = ()) -> list[dict[str, Any]]:
    """Run a SELECT. Params are sent separately — never spliced into the SQL."""
    _ensure_open()
    with pool.connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        cur.execute(sql, params)
        return cur.fetchmany(settings.max_rows)


def healthy() -> bool:
    try:
        return query("SELECT 1 AS ok")[0]["ok"] == 1
    except Exception:
        return False
