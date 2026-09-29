"""One-shot database setup, in order. Runs once, exits.

    schema + synthetic data  ->  read-only role  ->  masked view + REVOKE

Deliberately NOT "the app seeds itself on startup": that re-runs on every
restart, which is harmless against synthetic data and a disaster anywhere
near real data.

Pure psycopg, no psql — adding postgresql-client to the image would bloat
every service to help one.
"""

import os
import sys
from pathlib import Path

import psycopg

HERE = Path(__file__).resolve().parent
OWNER_DSN = os.environ.get(
    "OWNER_DSN",
    "postgresql://ops_owner:dev_only_not_a_secret@localhost:5434/chargeops",
)


def run_sql_file(name: str) -> None:
    with psycopg.connect(OWNER_DSN, autocommit=True) as conn:
        conn.execute((HERE / name).read_text())


def already_seeded() -> bool:
    """True if the stations table exists and has rows."""
    try:
        with psycopg.connect(OWNER_DSN) as conn:
            row = conn.execute("SELECT count(*) FROM stations").fetchone()
            return bool(row and row[0])
    except psycopg.errors.UndefinedTable:
        return False


def main() -> None:
    # Compose runs this on every `up`. Regenerating 9,252 rows each time is
    # wasteful and surprising, so skip unless explicitly forced. Steps 2 and 3
    # still run: they are idempotent, and they are the security posture — the
    # read-only role and the REVOKE should be reasserted every start.
    if already_seeded() and not os.environ.get("FORCE_SEED"):
        print("1/3  data already present — skipping (set FORCE_SEED=1 to rebuild)",
              flush=True)
    else:
        seed_data()

    print("2/3  read-only role", flush=True)
    run_sql_file("02_readonly_role.sql")

    print("3/3  masked view, and REVOKE on the raw table", flush=True)
    run_sql_file("03_safe_views.sql")

    print("done.", flush=True)


def seed_data() -> None:
    print("1/3  schema + synthetic data", flush=True)
    sys.path.insert(0, str(HERE))
    os.environ.setdefault("SEED_DSN", OWNER_DSN)
    import seed                       # noqa: PLC0415 — after the DSN is set
    seed.main()


if __name__ == "__main__":
    main()
