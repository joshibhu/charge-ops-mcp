"""Curated tools: the questions an operations team asks every day.

Each answers a WHOLE question, not "read me a table". The SQL is written
here, reviewed, and tested — the model only chooses which to call.

These exist alongside run_sql, not instead of it. Common questions get a
fast, predictable, correct answer; everything else falls through to SQL.
"""

from .db import query


def network_summary() -> str:
    """How is the network doing overall?"""
    sites = query("""
        SELECT count(*)                                       AS total,
               count(*) FILTER (WHERE status = 'live')        AS live,
               count(*) FILTER (WHERE status = 'maintenance') AS maintenance,
               sum(connectors)                                AS connectors
        FROM stations
    """)[0]

    use = query("""
        SELECT count(*)                                          AS sessions,
               count(*) FILTER (WHERE payment_status = 'failed') AS failed,
               count(*) FILTER (WHERE ended_at IS NULL)          AS unfinished,
               COALESCE(round(sum(energy_kwh)::numeric / 1000, 1), 0) AS mwh,
               COALESCE(round(sum(amount_inr)::numeric, 0), 0)   AS revenue
        FROM sessions
        WHERE started_at >= now() - interval '30 days'
    """)[0]

    faults = query("""
        SELECT count(*) FILTER (WHERE resolved_at IS NULL)  AS open_now,
               count(*) FILTER (WHERE resolved_at IS NULL
                                 AND severity = 'critical') AS open_critical,
               count(*) FILTER (WHERE raised_at >= now() - interval '30 days')
                                                            AS raised_30d
        FROM faults
    """)[0]

    # Guard the division: a network with no sessions must not crash.
    failure_rate = (
        round(100 * use["failed"] / use["sessions"], 1) if use["sessions"] else 0
    )

    return (
        f"NETWORK SUMMARY (last 30 days)\n"
        f"  Sites        : {sites['total']} total, {sites['live']} live, "
        f"{sites['maintenance']} in maintenance, {sites['connectors']} connectors\n"
        f"  Sessions     : {use['sessions']} "
        f"({failure_rate}% payment failures, {use['unfinished']} never ended)\n"
        f"  Energy       : {use['mwh']} MWh\n"
        f"  Revenue      : Rs {use['revenue']:,}\n"
        f"  Faults       : {faults['open_now']} open now "
        f"({faults['open_critical']} critical), {faults['raised_30d']} raised in 30d"
    )


def needs_attention(limit: int = 8) -> str:
    """Which sites should the operations team look at today, and why?

    NOTE: the ranking below encodes a JUDGMENT about what "needs attention"
    means — a critical fault counts ten times a minor one, a live site with
    no sessions counts fifteen. Those weights are a policy decision, not a
    fact from the data, and neither the model nor the user can see them.
    Say so when the answer is presented.
    """
    # NOTE ON SHAPE: an earlier version joined stations to BOTH faults and
    # sessions in one pass. That is a fan-out bug — one fault times 628
    # sessions produced "628 open faults" for a site that had one. Aggregate
    # each side to one row per station FIRST, then join. Sanity-check totals:
    # no per-site count may exceed the table's own total.
    rows = query(
        """
        WITH fault_stats AS (
            SELECT station_id,
                   count(*) FILTER (WHERE resolved_at IS NULL)        AS open_faults,
                   count(*) FILTER (WHERE resolved_at IS NULL
                                     AND severity = 'critical')       AS open_critical
            FROM faults
            GROUP BY station_id
        ),
        session_stats AS (
            SELECT station_id,
                   count(*)                                           AS sessions_30d,
                   count(*) FILTER (WHERE payment_status = 'failed')  AS failed_30d,
                   count(*) FILTER (WHERE ended_at IS NULL)           AS unfinished_30d
            FROM sessions
            WHERE started_at >= now() - interval '30 days'
            GROUP BY station_id
        ),
        per_site AS (
            SELECT s.code, s.name, s.city, s.status,
                   COALESCE(f.open_faults, 0)     AS open_faults,
                   COALESCE(f.open_critical, 0)   AS open_critical,
                   COALESCE(x.sessions_30d, 0)    AS sessions_30d,
                   COALESCE(x.failed_30d, 0)      AS failed_30d,
                   COALESCE(x.unfinished_30d, 0)  AS unfinished_30d
            FROM stations s
            LEFT JOIN fault_stats   f ON f.station_id = s.id
            LEFT JOIN session_stats x ON x.station_id = s.id
        )
        SELECT *,
               CASE WHEN sessions_30d = 0 THEN 0
                    ELSE round(100.0 * failed_30d / sessions_30d, 1) END AS failure_pct,
               -- A weighting, not a fact. See the note in the docstring.
               (open_critical * 10)
             + (open_faults * 3)
             + (CASE WHEN status = 'live' AND sessions_30d = 0 THEN 15 ELSE 0 END)
             + (CASE WHEN sessions_30d > 20
                     THEN 20.0 * failed_30d / sessions_30d ELSE 0 END)
             + (unfinished_30d * 0.5)                                    AS score
        FROM per_site
        ORDER BY score DESC, open_critical DESC
        LIMIT %s
        """,
        (limit,),
    )

    flagged = [r for r in rows if r["score"] > 0]
    if not flagged:
        return ("Nothing needs attention: no open faults, no idle live sites, "
                "no elevated payment failures.")

    lines = []
    for r in flagged:
        reasons = []
        if r["open_critical"]:
            reasons.append(f"{r['open_critical']} CRITICAL fault(s) open")
        if r["open_faults"] - r["open_critical"] > 0:
            reasons.append(f"{r['open_faults'] - r['open_critical']} other fault(s) open")
        if r["status"] == "live" and r["sessions_30d"] == 0:
            reasons.append("live but NO sessions in 30 days")
        if r["sessions_30d"] > 20 and r["failure_pct"] >= 8:
            reasons.append(f"{r['failure_pct']}% payment failures")
        if r["unfinished_30d"] > 5:
            reasons.append(f"{r['unfinished_30d']} sessions never ended")
        lines.append(
            f"- {r['code']} {r['name']} ({r['city']}, {r['status']}): "
            + "; ".join(reasons or ["—"])
        )

    return f"{len(flagged)} sites need attention:\n" + "\n".join(lines)


def site_detail(site: str) -> str:
    """Everything about one station. Accepts a code (PNQ-002) or part of a name."""
    found = query(
        """
        SELECT id, code, name, operator, city, state, status,
               connectors, power_kw, connector_type, commissioned_on
        FROM stations
        WHERE upper(code) = upper(%s) OR name ILIKE %s
        ORDER BY (upper(code) = upper(%s)) DESC
        LIMIT 3
        """,
        (site, f"%{site}%", site),
    )
    if not found:
        return f"No station matching {site!r}. Try a code like 'PNQ-002' or a city name."
    if len(found) > 1:
        names = ", ".join(f"{r['code']} {r['name']}" for r in found)
        return f"{site!r} matches several stations: {names}. Which one?"

    s = found[0]

    use = query(
        """
        SELECT count(*)                                           AS sessions,
               count(*) FILTER (WHERE payment_status = 'failed')  AS failed,
               count(*) FILTER (WHERE ended_at IS NULL)           AS unfinished,
               COALESCE(round(sum(energy_kwh)::numeric, 0), 0)    AS kwh,
               COALESCE(round(sum(amount_inr)::numeric, 0), 0)    AS revenue,
               COALESCE(round(avg(EXTRACT(epoch FROM ended_at - started_at)/60)::numeric, 0), 0)
                                                                  AS avg_minutes
        FROM sessions
        WHERE station_id = %s AND started_at >= now() - interval '30 days'
        """,
        (s["id"],),
    )[0]

    faults = query(
        """
        SELECT code, severity, raised_at::date AS raised, resolved_at IS NULL AS open
        FROM faults WHERE station_id = %s
        ORDER BY raised_at DESC LIMIT 5
        """,
        (s["id"],),
    )

    fail_pct = round(100 * use["failed"] / use["sessions"], 1) if use["sessions"] else 0
    fault_lines = [
        f"    {f['raised']}  {f['code']:18} {f['severity']:8} "
        f"{'OPEN' if f['open'] else 'resolved'}"
        for f in faults
    ] or ["    none recorded"]

    return (
        f"{s['code']}  {s['name']}\n"
        f"  {s['city']}, {s['state']} — {s['operator']}\n"
        f"  {s['connectors']} x {s['power_kw']}kW {s['connector_type']}, "
        f"status {s['status']}, live since {s['commissioned_on']}\n"
        f"  Last 30 days: {use['sessions']} sessions, {use['kwh']} kWh, "
        f"Rs {use['revenue']:,}\n"
        f"    {fail_pct}% payment failures, {use['unfinished']} never ended, "
        f"avg {use['avg_minutes']} min\n"
        f"  Recent faults:\n" + "\n".join(fault_lines)
    )


def city_breakdown() -> str:
    """Compare cities: sites, usage, revenue and faults.

    Three separate aggregates joined at the end — never one query joining
    stations to both sessions and faults, which fans out (see needs_attention).
    """
    rows = query("""
        WITH session_stats AS (
            SELECT s.city,
                   count(*)                                          AS sessions,
                   count(*) FILTER (WHERE x.payment_status='failed') AS failed,
                   COALESCE(sum(x.energy_kwh), 0)                    AS kwh,
                   COALESCE(sum(x.amount_inr), 0)                    AS revenue
            FROM sessions x JOIN stations s ON s.id = x.station_id
            WHERE x.started_at >= now() - interval '30 days'
            GROUP BY s.city
        ),
        fault_stats AS (
            SELECT s.city,
                   count(*) FILTER (WHERE f.resolved_at IS NULL) AS open_faults
            FROM faults f JOIN stations s ON s.id = f.station_id
            GROUP BY s.city
        ),
        site_stats AS (
            SELECT city, count(*) AS sites, sum(connectors) AS connectors
            FROM stations GROUP BY city
        )
        SELECT t.city, t.sites, t.connectors,
               COALESCE(u.sessions, 0)                        AS sessions,
               COALESCE(round(u.kwh::numeric/1000, 1), 0)     AS mwh,
               COALESCE(round(u.revenue::numeric, 0), 0)      AS revenue,
               CASE WHEN COALESCE(u.sessions,0) = 0 THEN 0
                    ELSE round(100.0*u.failed/u.sessions, 1) END AS failure_pct,
               COALESCE(f.open_faults, 0)                     AS open_faults,
               CASE WHEN t.connectors = 0 THEN 0
                    ELSE round(COALESCE(u.sessions,0)::numeric/t.connectors, 1)
               END                                            AS sessions_per_connector
        FROM site_stats t
        LEFT JOIN session_stats u ON u.city = t.city
        LEFT JOIN fault_stats   f ON f.city = t.city
        ORDER BY revenue DESC
    """)

    header = (f"{'City':<12}{'Sites':>6}{'Conn':>6}{'Sessions':>10}"
              f"{'/conn':>7}{'MWh':>7}{'Revenue':>12}{'Fail%':>7}{'Open':>6}")
    lines = [
        f"{r['city']:<12}{r['sites']:>6}{r['connectors']:>6}{r['sessions']:>10}"
        f"{r['sessions_per_connector']:>7}{r['mwh']:>7}"
        f"{'Rs '+format(int(r['revenue']), ','):>12}"
        f"{r['failure_pct']:>7}{r['open_faults']:>6}"
        for r in rows
    ]
    return "CITY BREAKDOWN (last 30 days)\n" + header + "\n" + "\n".join(lines)
