# charge-ops-mcp

An **MCP server** that answers operational questions about an EV charging
network — in English, over a guarded read-only database.

Ask it *"what needs attention today?"* or *"which operator has the worst
payment failure rate?"* and it answers from real data. Any MCP client can use
it: Claude Code, Claude Desktop, or your own app.

All data is **synthetic**. Cities are real; operators, sites and drivers are
invented.

```
32 stations · 9,252 sessions · 86 faults · 8 cities
```

This README doubles as my learning log — what was built, the concepts worth
keeping, and the bugs worth remembering. Week 1 lives in a separate repo
(`ai-sprint`); this is Week 2.

---

## Quick start

```bash
docker compose up -d                      # Postgres on 5434
uv run python db/seed.py                  # schema + synthetic data
docker compose exec -T db psql -U ops_owner -d chargeops -f - < db/02_readonly_role.sql

cp .env.example .env                      # then fill in API_TOKEN:
python -c "import secrets; print(secrets.token_urlsafe(32))"

uv run python -m chargeops.server         # HTTP on 127.0.0.1:8765
```

Register it with Claude Code:

```bash
TOKEN=$(grep '^API_TOKEN=' .env | cut -d= -f2)
claude mcp add --scope user --transport http chargeops http://127.0.0.1:8765/mcp \
  --header "Authorization: Bearer $TOKEN"
```

---

## Architecture

```
  any MCP client  ──HTTP + bearer token──▶  chargeops server
                                                  │
                        ┌─────────────────────────┴──────────────────┐
                        │                                            │
                  CURATED TOOLS                              run_sql (raw)
           network_summary, needs_attention,                        │
           site_detail, city_breakdown                        AST guard
                        │                                     5 checks
                        └─────────────────────────┬──────────────────┘
                                                  ▼
                                    ops_reader — SELECT only,
                                    8s timeout, 200-row cap
                                                  ▼
                                          stations · sessions · faults
```

---

## Day 8 — MCP, and what changes when the transport does

**Built:** the server. First over stdio, then switched to HTTP with
bearer-token auth.

**Core concepts**

- MCP is a **standard way to expose tools so any AI client can use them**. The
  technology is unremarkable — JSON-RPC over a pipe or HTTP. The value is that
  everyone agreed on it. The closest analogue is **JDBC**: it did not invent
  database access, it standardised it, and that changed everything.
- The consumer is a **model, not a programmer**. So every tool ships with a
  plain-English description, and that description *is* the prompt. Nobody
  writes integration code; the model reads the list and decides.
- `tools/list` returns `{name, description, inputSchema}` — **the same three
  fields I hand-wrote as a dict in Week 1**. MCP is that menu, sent down a pipe.
- The schema is **generated, not written**. `def add(a: float, b: float)` plus
  a docstring becomes the whole contract, read by reflection at request time.
  It exists nowhere on disk. Which means a **missing type hint is a missing
  schema** — type hints are decorative in normal Python and load-bearing here.
- **The transport changes the trust boundary, and that is the whole lesson:**

  |                  | stdio                        | HTTP                    |
  |------------------|------------------------------|-------------------------|
  | Who starts it    | the client, as a subprocess  | **me**, as a service    |
  | Clients          | one                          | many                    |
  | Reachable from   | this machine only            | wherever it is exposed   |
  | **Auth**         | none needed                  | **mandatory**            |

  With a pipe, only a local process could talk to it. Over HTTP I proved the
  server answered a complete stranger with no credentials — so a bearer token
  is not optional. `secrets.compare_digest`, not `==`: a plain comparison
  returns early on a mismatch and leaks the token to anyone timing responses.
- Registrations have a **scope**. `--scope local` (the default) works only in
  the directory it was registered from; `--scope user` works everywhere. This
  is the commonest reason a server "does not work" — it cost me a session
  restart to find.

**What bit me**

`FastMCP` no longer exists — mcp 2.x renamed it `MCPServer`. My first import
came from a stale memory and failed immediately. **Read the installed SDK, not
a tutorial.**

Worse, and silent: I built the `run_sql` tool description by setting
`__doc__` *after* the `@mcp.tool()` line. A decorator **runs immediately** and
captured the docstring at that moment, so the schema never reached the model.
The tool would have worked, the model would have written SQL against tables it
could not see, and every query would have failed on unknown columns — looking
like a model problem rather than a wiring one. Fixed by passing
`description=` to the decorator. (In Java an annotation is inert metadata read
later; a Python decorator has already run.)

---

## Day 9 — Curated tools that answer whole questions

**Built:** `network_summary`, `needs_attention`, `site_detail`,
`city_breakdown`.

**Core concepts**

- A curated tool **answers a question**, not "reads a table". `city_breakdown`
  returns *sessions per connector*, not raw counts — the ratio is the insight,
  and it is what shows Bengaluru has the highest utilisation on the fewest
  connectors.
- `count(*) FILTER (WHERE ...)` gets several conditional counts from **one
  pass** over the table.
- `sum()` returns **NULL**, not zero, when there are no rows. Without
  `COALESCE` a quiet month prints `None MWh`.
- Guard every division. One site has zero sessions in 30 days, so
  `failed / sessions` is a `ZeroDivisionError` waiting in a tool.
- A curated tool can **embed policy invisibly**. `needs_attention` weights a
  critical fault ten times a minor one and a zero-usage live site fifteen —
  numbers I chose, not facts from the data, and neither the model nor the user
  can see them. The tool description now says so.

**What bit me**

**The fan-out bug.** My first `needs_attention` joined `stations` to *both*
`faults` and `sessions` in one query and reported **"628 open faults"** at a
site that had one. Joining one row to two independent one-to-many tables
multiplies them: 1 fault × 628 sessions = 628 rows, and `count(f.id)` counted
that single fault once per session.

The tell was a number that **could not be true** — the whole table holds 86
faults. The fix is to aggregate each side to one row per station in its own
CTE *before* joining.

The sanity check I skipped takes thirty seconds: **no per-site count may
exceed the table's own total.** `city_breakdown` now passes it exactly —
518+575+464+391+286+298+255+239 = 3,026, which is what the table says.

And the uncomfortable part: **a model writing that query with `run_sql` would
make the same mistake**, and the guard would not catch it, because the query is
legal and safe — just wrong. That is the real argument for curated tools, and
it is not safety. It is that a bug found once stays fixed.

*One more thing worth noticing:* `site_detail` on BLR-001 shows an open
EMERGENCY_STOP and zero sessions, side by side. The causal story writes itself
— and the dates do not support it. **Adjacency reads as causation** in any
summary tool, and nobody checks the timeline.

---

## Day 10 — Letting the model write SQL

Arrived two days early, because writing a function per question is obviously
unsustainable and I said so before the plan got there.

**Core concepts**

- Two ways to give a model database access:
  - **curated** — I write the SQL, the model supplies a parameter. It never
    sees SQL and does not know my table names.
  - **raw** — the model writes the query. Enormously more capable, and the
    model's output becomes an instruction.
- **A block-list is a list of the attacks you happened to think of.** "Must
  start with SELECT, must not contain DELETE" passes
  `SELECT rolname, rolpassword FROM pg_authid` and
  `SELECT pg_read_file('/etc/hosts')` — both genuinely SELECT statements. And
  the CTE trick `WITH gone AS (DELETE ... RETURNING *) SELECT ...` parses with
  a `Select` at its root.
- So **parse, do not pattern-match.** `sqlglot` turns the SQL into a tree and
  the tree can be asked questions text cannot answer: what is the root node,
  does anything anywhere write, exactly which tables and functions are used.
- The five checks: one statement · root is SELECT · no write node *anywhere* ·
  tables on an allow-list · **functions must be ones sqlglot recognises**.
  That last one is a true allow-list — every standard aggregate is modelled,
  so an unrecognised function is refused by default, which is how
  `pg_read_file` and `dblink` are caught.
- The guard **rewrites** rather than only checking: no `LIMIT` gets one,
  `LIMIT 100000` is quietly lowered to 200. Refuse what is dangerous; correct
  what is merely excessive.
- What executes is the SQL **regenerated from the inspected tree**, not the
  string the model sent. There is no gap between what was checked and what
  ran — which removes a whole class of validator/executor disagreement.
- Refusals are **returned as text, never raised**. The model reads
  *"Table 'pg_authid' is not available. You may query: faults, sessions,
  stations."* and corrects itself inside the same turn.

**What bit me**

**My guard had a hole.** `SELECT pg_read_file('/etc/hosts')` passed every
check, because it has no `FROM` clause — so no `Table` node — and I had only
thought about tables. Found in thirty seconds by testing attacks rather than
reviewing my own design.

Postgres refused it anyway: *permission denied for function pg_read_file*.
`ops_reader` has no rights to it. **The layer I would trust on a bad day is
the one I did not write.** That is the honest case for defence in depth — not
"I will be careful", but *"I will get something wrong, so nothing may depend
on me being right."*

I closed it regardless, because relying on one layer is the thing I keep
arguing against.

*Also:* my auth test reported 401 for a correct token. The code was fine — my
`curl` had an unquoted `Accept` header that word-split on a comma. Before
that, all three cases returned 200 because a **stale server from the previous
run still held the port**, so I was testing an unauthenticated process. Twice
in twenty minutes the *test* was wrong rather than the code. **When a result
looks impossible, suspect the measurement first.**

---

## How the model chooses a tool

It does not see servers. It sees one flat list where the server is a **name
prefix** — `mcp__chargeops__run_sql` sits alongside `Bash` with no more
structure than that. It picks on the **description**, exactly as a
hand-written agent loop does.

Observed, not theorised:

- *"What needs attention today?"* → matched `needs_attention`, whose
  description contains that phrase.
- *"Which operator has the worst payment failure rate?"* → no curated tool
  fits, so it fell through to `run_sql`, routed by the one sentence
  *"use this for any question the other tools do not cover"*.

**The protocol contributes nothing to that decision.** MCP standardises
transport, discovery and naming. Descriptions do the routing — which makes
that sentence the most load-bearing line in the server.

---

## Known gaps

- **`run_sql` will return `driver_name`, `driver_phone` and `driver_email` to
  a model.** Personal data, straight out of the boundary. Day 11.
- A **static** bearer token: it cannot be scoped, expired or revoked per
  client. Real deployments use OAuth, which MCP supports.
- No tests yet.
- A model given a 200-row cap may report a truncated result as complete.
  Untested.

---

*Days 11–14 to follow.*
