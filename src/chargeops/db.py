"""Database access: one pool, one query function, parameterised always."""

from typing import Any

from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from .masking import mask_value
from .settings import settings

# open=False so importing this never needs a live database (tests, linting).
pool = ConnectionPool(settings.database_url, min_size=1, max_size=5, open=False)


def _ensure_open() -> None:
    if pool.closed:
        pool.open(wait=True, timeout=10.0)


def query(sql: str, params: tuple = ()) -> list[dict[str, Any]]:
    """Run a SELECT. Params are sent separately — never spliced into the SQL.

    Personal fields are MASKED here, at the data-access boundary, not in the
    tools. Nothing downstream can see a real phone number — not a new tool,
    not a log line, not a traceback. A tool written next year is safe by
    default rather than by memory.

    There is deliberately no opt-out parameter. The day something genuinely
    needs a raw value (sending an SMS to a driver), add a separate explicit
    function for it. An `unmasked=True` flag would get copied around and
    become the default by accident.
    """
    _ensure_open()
    with pool.connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        cur.execute(sql, params)
        rows = cur.fetchmany(settings.max_rows)

    return [
        {field: mask_value(field, value) for field, value in row.items()}
        for row in rows
    ]


def healthy() -> bool:
    try:
        return query("SELECT 1 AS ok")[0]["ok"] == 1
    except Exception:
        return False
