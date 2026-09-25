"""Decide whether a model-written query is safe to run.

Parses the SQL and inspects the STRUCTURE. Never searches the text — a
text search is only as good as the list of bad words you thought of.

This is one layer. Underneath it the ops_reader role cannot write at all,
so a bug here is not the end of the story.
"""

import sqlglot
from sqlglot import exp

DIALECT = "postgres"

# The only tables a query may touch. An ALLOW-list: anything not named here
# is refused, including pg_authid, pg_class and every other system table.
ALLOWED_TABLES = {"stations", "sessions", "faults"}

# Statement types that change data or reach outside it. This is a block-list,
# which I argued against — but it is over sqlglot's CLOSED set of known node
# types, not over free text, and the table allow-list above plus the read-only
# role are the primary controls. This is defence in depth, not the defence.
FORBIDDEN_NODES = (
    exp.Insert, exp.Update, exp.Delete, exp.Drop, exp.Create,
    exp.Alter, exp.TruncateTable, exp.Merge, exp.Into,
    exp.Command,          # anything sqlglot does not model: GRANT, COPY, ...
)


# Functions sqlglot does not model are refused by default. Add a name here
# only when a legitimate query genuinely needs it.
ALLOWED_EXTRA_FUNCTIONS: set[str] = set()


class QueryNotAllowed(ValueError):
    """The query failed the guard. The message is written FOR THE MODEL —
    it must be specific enough for the model to fix its query and retry."""


def check(sql: str) -> exp.Expression:
    """Return the parsed query if it is safe. Raise QueryNotAllowed if not."""

    # 1. Exactly one statement. Kills "SELECT 1; DROP TABLE faults".
    try:
        statements = sqlglot.parse(sql, dialect=DIALECT)
    except Exception as exc:
        raise QueryNotAllowed(f"Could not parse that SQL: {exc}") from exc

    if len(statements) != 1:
        raise QueryNotAllowed(f"Send exactly one statement; got {len(statements)}.")

    tree = statements[0]
    if tree is None:
        raise QueryNotAllowed("Empty query.")

    # 2. The top-level statement must be a SELECT.
    if not isinstance(tree, (exp.Select, exp.Union, exp.Subquery)):
        raise QueryNotAllowed(
            f"Only SELECT is allowed; this is a {type(tree).__name__.upper()}."
        )

    # 3. Nothing anywhere in the tree may write. Catches the CTE trick, where
    #    the root IS a Select but a DELETE hides inside it.
    for node in tree.walk():
        if isinstance(node, FORBIDDEN_NODES):
            raise QueryNotAllowed(
                f"{type(node).__name__.upper()} is not allowed anywhere in a query."
            )

    # 4. Every table must be on the allow-list.
    for table in tree.find_all(exp.Table):
        if table.name.lower() not in ALLOWED_TABLES:
            raise QueryNotAllowed(
                f"Table {table.name!r} is not available. "
                f"You may query: {', '.join(sorted(ALLOWED_TABLES))}."
            )

    # 5. Only functions sqlglot RECOGNISES may be used. Every standard
    #    aggregate and date function is modelled (Count, Sum, TimestampTrunc,
    #    ...); an unrecognised one arrives as Anonymous and is refused. That
    #    is how pg_read_file, pg_ls_dir and dblink are caught — they have no
    #    FROM clause, so check 4 never sees them.
    #
    #    Strict on purpose: an exotic but legitimate function is refused too.
    #    The cost of a false refusal is one line in ALLOWED_EXTRA_FUNCTIONS.
    #    The cost of a false allow is reading files off the server.
    for node in tree.find_all(exp.Anonymous):
        name = str(node.this).lower()
        if name not in ALLOWED_EXTRA_FUNCTIONS:
            raise QueryNotAllowed(
                f"Function {name!r} is not available. Use standard SQL "
                f"aggregates and date functions."
            )

    return tree


def enforce_limit(tree: exp.Expression, max_rows: int) -> exp.Expression:
    """Make sure the query returns at most max_rows. Rewrites the tree."""
    existing = tree.args.get("limit")

    if existing is None:
        return tree.limit(max_rows)        # no LIMIT -> add one

    # A LIMIT is present. Lower it if the model asked for more than we allow.
    try:
        asked = int(existing.expression.this)
    except (AttributeError, TypeError, ValueError):
        return tree.limit(max_rows)        # unparseable -> replace it

    return tree if asked <= max_rows else tree.limit(max_rows)


def safe_sql(sql: str, max_rows: int) -> str:
    """Check a query and return the SQL that is actually safe to run.

    Note what is returned: the SQL REGENERATED from the checked tree, not
    the string the model sent. So what executes is exactly what was
    inspected — there is no gap between the two for anything to slip
    through.
    """
    tree = check(sql)
    return enforce_limit(tree, max_rows).sql(dialect=DIALECT)
