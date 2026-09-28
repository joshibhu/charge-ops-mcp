"""Assertions that keep personal data inside this process.

The masking code is easy. Guaranteeing nobody reopens the hole in six
months is the hard part, and that is what these tests are for.

Two things will realistically reopen it, and neither raises an error:
  1. someone adds a personal column to sessions_safe
  2. a migration runs GRANT SELECT ON ALL TABLES IN SCHEMA public
"""

import pytest

from chargeops.db import healthy, query
from chargeops.masking import PERSONAL_FIELDS
from chargeops.sql_tool import run_sql

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not healthy(), reason="database not reachable"),
]

# Name fragments that mean "this column is probably personal". A column
# matching any of these must be either absent from sessions_safe, or present
# in PERSONAL_FIELDS with a masker. Deliberately broad: a false alarm costs
# one line here, a miss costs a data leak.
PERSONAL_HINTS = (
    "name", "phone", "mobile", "email", "address", "aadhaar", "pan",
    "dob", "birth", "gender", "passport", "licence", "license",
    "card", "account", "ip_", "lat", "lon",
)

# Raw values seeded by db/seed.py. If any of these reaches a tool result,
# the boundary has failed.
RAW_SHAPES = ("@example.com",)


def test_the_app_role_cannot_read_the_raw_sessions_table():
    """The control that actually holds.

    Layers above this are my code and can be worked around — Piece 2's
    name-based masking was defeated by `SELECT driver_name AS city`. This
    one is Postgres refusing. If a migration widens access, the build fails.
    """
    granted = query(
        "SELECT has_table_privilege('ops_reader','sessions','SELECT') AS can_read"
    )[0]["can_read"]
    assert granted is False, (
        "ops_reader can read the raw sessions table. Something re-granted it — "
        "check migrations for GRANT ... ON ALL TABLES."
    )


def test_the_app_role_can_read_the_safe_view():
    """The other half: the revoke must not have taken away what we need."""
    assert query(
        "SELECT has_table_privilege('ops_reader','sessions_safe','SELECT') AS ok"
    )[0]["ok"] is True


def test_every_personal_column_in_the_view_has_a_masker():
    """Catches a personal column added to sessions_safe without masking.

    This is the test that survives me forgetting. Someone needing
    driver_aadhaar for a report six months from now will add it to the
    view; this fails until they add a masker too.
    """
    columns = [
        r["column_name"]
        for r in query(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = 'sessions_safe'"
        )
    ]
    assert columns, "sessions_safe not found — has db/03_safe_views.sql been run?"

    for column in columns:
        if any(hint in column.lower() for hint in PERSONAL_HINTS):
            assert column.lower() in PERSONAL_FIELDS, (
                f"{column!r} looks personal, is exposed by sessions_safe, and has "
                f"no masker in masking.PERSONAL_FIELDS. Add one, or drop the "
                f"column from the view."
            )


def test_the_view_actually_masks():
    """A spot check, in case the view is rebuilt without the masking."""
    row = query(
        "SELECT driver_name, driver_phone, driver_email, vehicle_reg "
        "FROM sessions_safe WHERE driver_name IS NOT NULL LIMIT 1"
    )[0]
    for field, value in row.items():
        assert "*" in str(value), f"{field} came back unmasked: {value!r}"


@pytest.mark.parametrize(
    "sql",
    [
        # The four bypasses that defeated name-based masking in Piece 2.
        "SELECT driver_name AS city FROM sessions_safe LIMIT 3",
        "SELECT upper(driver_name) AS x FROM sessions_safe LIMIT 3",
        "SELECT driver_name || driver_phone AS blob FROM sessions_safe LIMIT 3",
        "SELECT substring(driver_phone from 4) AS d FROM sessions_safe LIMIT 3",
        # And the raw table, which must be refused outright.
        "SELECT driver_name FROM sessions LIMIT 3",
    ],
)
def test_no_bypass_returns_a_raw_value(sql):
    """Renaming a masked value just renames a masked value."""
    result = run_sql(sql)
    for shape in RAW_SHAPES:
        assert shape not in result, f"raw value leaked via: {sql}"
    # An email domain is the easiest raw shape to spot; also assert that any
    # driver-ish output carries a mask marker.
    if "refused" not in result.lower() and "failed" not in result.lower():
        assert "*" in result, f"no masking marker in output of: {sql}"
