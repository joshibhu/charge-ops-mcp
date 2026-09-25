"""The run_sql tool: guard, then execute, then format."""

from .db import query
from .guard import QueryNotAllowed, safe_sql
from .settings import settings

# The model writes SQL against this. Compact on purpose — it is sent on
# every request, so every word costs tokens on every call.
SCHEMA = """
stations(id, code, name, operator, city, state, connectors,
         power_kw, connector_type, status, commissioned_on)
    status: 'live' | 'maintenance' | 'planned'

sessions(id, station_id, connector_no, started_at, ended_at,
         energy_kwh, amount_inr, payment_status,
         driver_name, driver_phone, driver_email, vehicle_reg)
    payment_status: 'paid' | 'failed' | 'pending'
    ended_at/energy_kwh/amount_inr are NULL for sessions that never finished

faults(id, station_id, connector_no, code, description,
       severity, raised_at, resolved_at)
    severity: 'critical' | 'major' | 'minor'
    resolved_at IS NULL means the fault is still open
"""


def _format(rows: list[dict]) -> str:
    """Rows as text. The model reads this, so it must be compact and clear."""
    if not rows:
        return "No rows."
    header = " | ".join(rows[0])
    lines = [
        " | ".join("" if v is None else str(v) for v in row.values())
        for row in rows
    ]
    return f"{len(rows)} rows\n{header}\n" + "\n".join(lines)


def run_sql(sql: str) -> str:
    """Run a read-only query and return the rows as text.

    Every failure is RETURNED, never raised — the model reads this string
    and can correct its query and try again. A raised exception would end
    the conversation instead of continuing it.
    """
    try:
        checked = safe_sql(sql, settings.max_rows)
    except QueryNotAllowed as refusal:
        return f"Query refused: {refusal}"

    try:
        rows = query(checked)
    except Exception as exc:
        # Syntax errors, unknown columns, timeouts. The model can fix these.
        return f"Query failed: {type(exc).__name__}: {exc}"

    return _format(rows)
