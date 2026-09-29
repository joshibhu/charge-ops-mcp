"""MCP server for charging network operations.

Two kinds of tool, deliberately:

  CURATED   network_summary, needs_attention, site_detail, city_breakdown
            The SQL is written here, reviewed and tested. Fast, predictable,
            and a bug found once is fixed forever.

  RAW SQL   run_sql
            For the long tail nobody anticipated. Guarded by guard.py and,
            underneath that, a read-only Postgres role.

Descriptions are passed to the decorator, not left as docstrings — a
decorator captures __doc__ at decoration time, so editing it afterwards is
too late and the text silently never reaches the model.
"""

from mcp.server.mcpserver import MCPServer
from mcp.server.transport_security import TransportSecuritySettings

from .auth import BearerTokenMiddleware
from .ops_tools import (
    city_breakdown as _city_breakdown,
    needs_attention as _needs_attention,
    network_summary as _network_summary,
    site_detail as _site_detail,
)
from .settings import settings
from .sql_tool import SCHEMA, run_sql as _run_sql

mcp = MCPServer("chargeops")


@mcp.tool(description=(
    "Overall health of the charging network: site counts, sessions, energy, "
    "revenue and open faults for the last 30 days. Use for any broad 'how is "
    "the network doing' question, or when no city or station is named."
))
def network_summary() -> str:
    return _network_summary()


@mcp.tool(description=(
    "Sites the operations team should look at today, ranked, with the reason "
    "each is flagged: open faults, live sites with no usage, elevated payment "
    "failures, sessions that never ended. Use for 'what needs attention', "
    "'what is broken', 'where should we send an engineer'. The ranking uses a "
    "fixed weighting that is a policy choice, not a fact — say so if asked why "
    "one site outranks another."
))
def needs_attention(limit: int = 8) -> str:
    return _needs_attention(limit)


@mcp.tool(description=(
    "Everything about ONE station: location, hardware, 30-day usage and "
    "revenue, and its recent fault history. Accepts a station code such as "
    "'PNQ-002' or part of a site name. Use whenever a question is about a "
    "single named site."
))
def site_detail(site: str) -> str:
    return _site_detail(site)


@mcp.tool(description=(
    "Every city compared: sites, connectors, sessions, sessions per connector, "
    "energy, revenue, payment failure rate and open faults. Use for comparisons "
    "across cities, 'which city performs best', or utilisation questions."
))
def city_breakdown() -> str:
    return _city_breakdown()


RUN_SQL_DESCRIPTION = (

    "Run a read-only SQL query against the charging network database.\n\n"
    "Use this for any question the other tools do not cover: aggregates, "
    "comparisons, time series, joins, or anything ad hoc. Prefer a more "
    "specific tool when one fits — it is cheaper and cannot be got wrong.\n\n"
    "PostgreSQL. SELECT only, one statement, at most 200 rows returned.\n"
    "Tables:\n" + SCHEMA
)


@mcp.tool(description=RUN_SQL_DESCRIPTION)
def run_sql(sql: str) -> str:
    return _run_sql(sql)


def build_app():
    """The ASGI app, with auth wrapped around it.

    Fails to start rather than serving an unprotected database — the most
    likely accident is forgetting the token, and the most expensive one is
    forgetting it while bound to 0.0.0.0.
    """
    if not settings.api_token:
        raise SystemExit(
            "CHARGEOPS_API_TOKEN is not set. Generate one with:\n"
            "  python -c \"import secrets; print(secrets.token_urlsafe(32))\"\n"
            "and put it in .env as CHARGEOPS_API_TOKEN=..."
        )
    hosts = [h.strip() for h in settings.allowed_hosts.split(",") if h.strip()]
    return BearerTokenMiddleware(
        mcp.streamable_http_app(
            transport_security=TransportSecuritySettings(allowed_hosts=hosts)
        ),
        settings.api_token,
    )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        build_app(),
        host=settings.host,
        port=settings.port,
        log_level="warning",
    )