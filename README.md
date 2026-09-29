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

See also **[GLOSSARY.md](GLOSSARY.md)** — every term I met across both
repos, with the moment I met it. Updated as new ones turn up.

This README doubles as my learning log — what was built, the concepts worth
keeping, and the bugs worth remembering. Week 1 lives in a separate repo
(`ai-sprint`); this is Week 2.

---

## Quick start

You need Docker and an OpenAI API key. Nothing else — no Python, no Postgres.

```bash
git clone https://github.com/joshibhu/charge-ops-mcp.git
cd charge-ops-mcp
cp .env.example .env
```

Open `.env` and fill in three values:

```bash
# 1. your OpenAI key
OPENAI_API_KEY=sk-...

# 2 and 3. generate these — any random string will do
python3 -c "import secrets; print('API_TOKEN=' + secrets.token_urlsafe(32))"
python3 -c "import secrets; print('JWT_SECRET=' + secrets.token_urlsafe(32))"
```

Then:

```bash
docker compose up
```

First run takes a couple of minutes: it builds the image, starts Postgres,
creates the schema, generates 9,252 synthetic sessions, creates the read-only
role and the masked view, then starts both services.

**Open http://localhost:8080/widget** and ask:

> what needs attention today?

Things worth trying:

```
why that one?                                   # it remembers
which operator has the worst payment failure rate?   # no curated tool — writes SQL
show me driver names and phone numbers          # masked at the database
delete all the sessions                         # refused, four layers deep
```

<details>
<summary>Running the pieces directly, without Docker</summary>

For development you can run each part on the host. You need `uv` and Docker
for Postgres only.

```bash
docker compose up -d db                       # just the database
uv run python db/setup.py                     # schema, data, role, view
uv run python -m chargeops.server             # MCP server on :8765
uv run uvicorn chargeops.web:app --port 8080 --reload   # web app
uv run python scripts/chat.py                 # or the CLI instead of a browser
uv run pytest                                 # 25 tests
```

`db/setup.py` skips seeding if data is already present; `FORCE_SEED=1`
rebuilds it.

</details>

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

## Day 11 — Personal data must not reach the model

**Built:** masking at the boundary, then — when that turned out to be
defeatable — a masked view with the raw table revoked, plus 9 tests including
two that assert a database grant.

**The hole, before anything was built**

```sql
SELECT driver_name, driver_phone, driver_email, vehicle_reg FROM sessions LIMIT 3
```

Real-looking names, mobile numbers, email addresses and registrations, sent to
a third-party API. Synthetic data here; the mechanism entirely real.

**Why it matters more than it feels**

- **It left the building.** Under the DPDP Act or GDPR, *sending* customer
  personal data to a processor you have not contracted for it is the
  violation — not "the model misused it".
- **It cannot be un-sent.** Provider logs, retention windows, abuse review.
- **It lands in my own logs.** Every tool result gets logged somewhere, so
  driver phone numbers end up in the error tracker and the log aggregator —
  systems with far looser access control than the database they came from.
- **It is the first question a client asks**, and "probably not much" is not
  an answer.

**Where to mask — three candidates, one right answer**

| Place | Why it fails / works |
|---|---|
| In the SQL | `run_sql` means the MODEL writes the query. It cannot be made to remember. |
| At the chat layer | Too late — the data already crossed the boundary to reach the model. |
| At the data-access boundary | One place, covers every tool including next year's. |

So: mask in `db.query()`. Safe by **default** rather than by memory.

**Masking that keeps the data useful**

Total redaction destroys it — `***` everywhere and you can no longer tell two
sessions apart or spot one driver with forty failed payments. Keep the shape,
lose the identity:

    Divya Kulkarni              -> D*** K***
    +919572623548               -> +91*****3548      last 4 match a ticket
    divya.k15@example.com       -> d***@example.com  domain kept on purpose
    GJ01CC1814                  -> GJ01****1814      state + district survive

Edge cases fail **toward** `***`, never toward the original. `None` stays
`None` — a NULL is not personal data.

**What bit me — and it is the main lesson of the day**

The boundary masking was **completely defeated**, four ways:

    SELECT driver_name AS city          -> Diya Iyer
    SELECT upper(driver_name)           -> DIYA IYER
    SELECT driver_name || driver_phone  -> Diya Iyer +918375181648
    SELECT substring(driver_phone from 4)-> 8375181648

Masking keys on the output **column name**, and with `run_sql` the model
chooses the names. This is not a bug I could patch with more field names:

> **Any name-based control fails when the other side chooses the names.**

The fix was not a better filter. It was moving from **filtering** to
**absence** — a view where the masking is already applied in SQL, and the raw
table revoked from `ops_reader` entirely. Then renaming a masked value just
renames a masked value; there is nothing left to unmask. Verified by
bypassing my own guard and hitting the table directly:
`permission denied for table sessions`.

**Third time this pattern has appeared**

| Day | I built a filter | What actually held |
|---|---|---|
| 6 | dispatcher rejects unknown tool names | the read-only role |
| 10 | AST guard blocks dangerous SQL | `permission denied for function pg_read_file` |
| 11 | mask personal columns by name | `permission denied for table sessions` |

Every time my Python was layer 1 and **Postgres was the layer that held.**

**Views, and why they give more control than they look like they do**

- **Not a copy — a stored query.** An `UPDATE` to the table shows in the view
  instantly; nothing to refresh. (A *materialised* view is a copy, and does.)
- **New columns are invisible.** The view names its columns explicitly, so a
  `driver_aadhaar` added later is unreachable from the moment it exists —
  safe by default, with nobody remembering anything.
- **Row filtering is a permission boundary.** A `WHERE st.operator = ...` in
  the view means one operator's assistant physically cannot see another's
  sessions. For a multi-tenant CSMS that is the difference between a
  sellable product and a liability. (Add `WITH (security_barrier = true)`
  when a view filters rows rather than just hiding columns; Postgres views
  are not a security barrier by default.)
- **The grant is what makes it real.** A view hides nothing from a role that
  can still read the underlying table.
- Postgres also refused to let me `DROP` a column the view depended on — a
  dependency safety net I did not build.

**The reframe worth keeping:** stop guarding SQL against the real schema.
**Give the model its own schema** — a purpose-built view layer, safe by
construction. Not "everything readable, guard filters" but "nothing readable,
views grant".

**The tests are the actual deliverable**

Masking code is easy. Guaranteeing nobody reopens the hole in six months is
not. Two things will realistically do it, and neither raises an error:

1. someone adds a personal column to `sessions_safe` for a report
2. a migration runs `GRANT SELECT ON ALL TABLES IN SCHEMA public`

So the suite asserts both — including **a test that asserts a database
grant**, which most codebases have no equivalent of:

```python
has_table_privilege('ops_reader', 'sessions', 'SELECT') is False
```

and a heuristic that flags any column whose *name* looks personal
(`name`, `phone`, `aadhaar`, `pan`, `dob`, ...) unless it has a masker.

**I then broke it both ways and watched the tests fail**, because a test that
has never failed is a test I cannot trust. Sabotage 1 was caught by two tests
naming the offending column; sabotage 2 by the permission test, which
suggested its own cause ("check migrations for GRANT ... ON ALL TABLES").

**What I can now say to a client**

> Driver names, phones and emails never leave our process. Not masked on the
> way out — the service's login physically cannot read those columns, and a
> test fails the build if anyone re-grants it.

A permission plus a regression test, not a policy.

**Run**

```bash
uv run pytest                          # 9 tests
uv run pytest -m "not integration"     # none yet — all 9 need the database
```

---

## Day 12 — Memory, and deciding not to use a framework

**Built:** an assistant that talks to the MCP server over HTTP, remembers the
conversation, and trims history to control cost. ~60 lines across four
modules. **Zero server changes.**

**The day started with a framework and ended without one**

The plan said LangGraph. I led with its graph model — nodes, edges, a
conditional loop — and got pushed back on: *"isn't this just persistence?
aren't we already sending the whole history every message?"*

Both true, and the second one is the insight. **LangGraph does not invent
memory.** The mechanism is the same one I built on Day 2: keep the message
list, resend it every turn. What a framework adds is a *place to keep the
list between calls* and *a key to find it by*.

Which is about fifteen lines:

```python
SESSIONS: dict[str, list[dict]] = {}          # thread_id -> messages
messages = SESSIONS.setdefault(thread_id, [system_prompt])
```

That is a checkpointer. That is a thread_id.

**Library vs framework, precisely.** A library you call; a framework calls
you. LangGraph owns the control flow — you supply nodes, it decides what
runs. Spring, not Jackson. Inversion of control. That matters because a
library can be removed in an afternoon and a framework shapes the code
around itself.

So the honest accounting:

| | Hand-rolled | Framework worth it? |
|---|---|---|
| Memory keyed by session | 15 lines | **no** |
| Durable storage in Postgres | a table, some SQL | marginal |
| Streaming intermediate steps | fiddly | maybe |
| **Pause mid-run for approval, resume later** | genuinely hard | **yes** |

Only the last needs the graph — you cannot pause a `while` loop across a web
request, but you can pause a graph, record which node it stopped at, and
resume tomorrow. **That is Day 24, not today.**

**Where Claude Code stores THIS conversation**

Chasing "where does the history actually live" landed somewhere useful:

    ~/.claude/projects/<project>/<session-id>.jsonl      5.4 MB, 2,924 entries

A plain file on my own disk, holding every message since Day 1. Claude Code
reads it, sends the lot, appends the reply. The API is stateless (Day 2) —
the only reason it knows what we discussed last week is that it is resending
it, from a file, every time I press Enter.

    Claude Code                    what I built
    ───────────                    ────────────
    sessionId                 ≈    thread_id
    a .jsonl file             ≈    a dict (swap for Postgres)
    read file, send all       ≈    load state, send all
    append the reply          ≈    save state

Same design, different words. Also explains why sessions do not follow me to
another machine — and why syncing that directory is a bad idea: it contains
every credential that ever appeared in command output.

**Core concepts**

- **The assistant is a CLIENT.** Everything from Days 8–11 sits on the far
  side of an HTTP boundary and is unaware of it. First time I have written
  the client side.
- **Tools are fetched, not registered.** `tools/list` at startup, once. The
  word `chargeops` appears **nowhere** in the client — it connects by URL and
  a bearer token. Add a sixth tool to the server and the client sees it with
  no change. That is the JDBC property.
- **Two schema shapes for the same thing.** MCP puts it in `inputSchema` at
  the top level; OpenAI wants `parameters` nested inside a `function` object.
  `bridge.py` is eleven lines and the only file that knows both.
- **`async` is contagious.** The MCP SDK is async, so the client is, so the
  loop is, so the CLI is. Unlike a blocking call in Java, the choice
  propagates outward through every caller — an architectural decision, not a
  local one.
- **MAX_ROUNDS is a ceiling, not a target.** The loop returns the moment the
  model answers with text instead of a tool request — usually round 2. The
  cap exists for the model that ping-pongs on a bad argument, where each lap
  is a paid call with a longer history.

**The subtle bug: trimming is NOT "keep the last N"**

A `tool` message is only legal directly after an assistant message carrying
`tool_calls`. A blind slice can start the window on an orphaned tool result,
and the API rejects **the whole conversation** — the same 400 from Day 6, not
a degraded answer. So the window is walked to a legal boundary at both ends:

```python
while window and window[0].get("role") == "tool":     window.pop(0)
while window and window[-1].get("tool_calls"):        window.pop()
```

`while`, not `if` — the model can request three tools in one turn, producing
three consecutive results. An `if` would fix one and leave two, and that
version ships fine until the first multi-tool turn.

Two tests construct a slice that lands on each case deliberately.

**What bit me**

`result.isError` — **camelCase on the wire, snake_case in Python** (`is_error`).
The identical translation that bit me with `inputSchema` on Day 8, and I wrote
the wire name again.

And a worse one: I hand-rolled a list of context managers and unwound them in
a `for` loop, which produced

    RuntimeError: Attempted to exit cancel scope in a different task

Both the transport and the session are anyio task groups and must be exited in
the task that entered them. `contextlib.AsyncExitStack` is the stdlib answer to
exactly this. General rule earned: **when the stdlib has a thing for your
problem, the hand-rolled version is probably subtly wrong.**

*Also, again:* the MCP server had been running for three days and still held
the Day 10 code, which queries `FROM sessions` — a table Day 11 revoked. Every
curated tool failed over MCP while working perfectly in-process. **A
long-running process holds the code it started with**, and the error surfaces
at the call site while the cause is a timestamp. Second time this week a stale
process cost me a debugging session; `uvicorn --reload` fixes it in dev, and a
container fixes it in production.

**And one correction to my own record.** I had been citing "Day 5's agent
cannot answer 'why that one?'" as a demonstrated fact across several messages.
It was a prediction I never ran. Running it:

    Day 5:   "I'm not sure what you're referring to by 'that one'."
    Day 12:  explains BLR-001 from memory

Now it is evidence. Twelve days of "suspect the measurement" and I was still
repeating an unverified claim.

**The honest limitation**

Trimming **forgets** rather than summarises. Message 21 arrives and turn 1 is
gone. The alternatives cost more: summarise old turns (an extra model call
each time — what Claude Code does), or retrieve the relevant old turn on
demand (RAG applied to history). **Which to use is a product decision, not a
technical one** — what the assistant is allowed to forget is worth asking a
client explicitly.

**Run**

```bash
uv run python -m chargeops.server        # terminal 1
uv run python scripts/chat.py            # terminal 2

you> which site needs attention most urgently?
you> why that one?                       # only works because of memory
you> new                                 # forget the thread
```

---

## Day 13 — Streaming to a browser

**Built:** an embeddable chat widget. Short-lived browser tokens, a web app
that is *another client* of the MCP server, and answers that stream token by
token over server-sent events. **Server untouched again.**

```
browser (widget.html)
    |  JWT — 15 minutes, chat scope, visible in the page
    v
web app :8080          <- holds the real API_TOKEN
    |  Bearer API_TOKEN
    v
MCP server :8765       <- guard, allow-list, LIMIT rewriting
    |  ops_reader
    v
Postgres :5434         <- read-only role, masked view
```

**Core concepts**

- **You cannot put a credential in a browser.** `view source` is all it
  takes. So the browser never sees `API_TOKEN` — it gets a *different*
  credential entirely:

  |                | API_TOKEN            | browser token       |
  |----------------|----------------------|---------------------|
  | Lifetime       | forever              | 15 minutes          |
  | Scope          | every tool incl. SQL | `chat` only         |
  | Lives in       | `.env`, server-side  | the page, and that is fine |
  | If stolen      | the database         | 15 min of questions |

  The design is not "hide it well" but **"make the exposed one worthless."**

- **A JWT is SIGNED, not encrypted.** Anyone can decode the payload — that is
  expected, and a test pins it so nobody ever puts a secret in one. What they
  cannot do is change it: alter the expiry and the signature stops matching.
  The library enforces `exp`, so "we forgot to check the expiry" is not a bug
  that can happen.

- **A different secret from API_TOKEN.** Tempting to reuse — one fewer line in
  `.env`. Don't: one is a bearer credential clients present, the other a
  signing key only the server uses. Reuse them and anyone holding the API
  token can forge browser sessions.

- **SSE, not WebSocket.** A chat answer flows one way, so:

  |              | SSE            | WebSocket            |
  |--------------|----------------|----------------------|
  | Direction    | server → client | both                |
  | Protocol     | plain HTTP     | its own upgrade      |
  | Reconnects   | automatically  | you write it         |
  | Through proxies | usually fine | often blocked       |

  And SSE is a *text format*, not a protocol: `data: {...}` followed by a
  blank line. No handshake, no library.

- **The web app is another MCP client.** Same `McpToolbox` the CLI uses. One
  connection for the whole app (tool calls carry no per-user state, so it is a
  connection pool), and one `Conversations` holding many threads. **Shared
  connection, per-user state** — the distinction that makes a web app work.

- **`thread_id` turned out to be the session key.** Day 12 built it for a CLI;
  it is exactly what a web session needs. Proven: same token across two
  separate HTTP requests remembers; a different token asking the same
  follow-up says "I'm not sure which item you're referring to."

- **CORS.** A browser refuses a cross-origin call unless the server says yes,
  via a preflight `OPTIONS`. Without those headers the console blames CORS
  while the network tab shows nothing was ever sent — which confuses everyone
  once. `allow_origins=["*"]` is acceptable here only because the sole way in
  is a token this app minted; production lists the customer's domains.

**What bit me**

**You cannot send a 500 once streaming has started.** The status line and
headers are already gone. A failure mid-answer can only be reported as another
event — `{"type": "error"}` — and the client has to know to handle it. That is
a real departure from request/response, and it gets discovered in production
when a tool times out halfway through an answer and the browser just stops.

**`EventSource` cannot do this job.** The browser's built-in SSE client only
issues GET and cannot set headers, so it cannot carry an Authorization token
or a POST body. `fetch()` plus a stream reader is the way. People who do not
know this work around it badly — putting the token in the query string, where
it lands in every access log.

**A network chunk can split an SSE event in half.** Works locally, where
chunks happen to align; breaks under real conditions. The client splits on the
blank line, processes complete events and **keeps the remainder**:

```javascript
const events = buffer.split("\n\n");
buffer = events.pop();          // the incomplete tail
```

**`X-Accel-Buffering: no`.** nginx buffers responses by default, collecting the
entire stream and delivering it in one lump — streaming that is not. A
one-line header fixing a bug that only appears once deployed behind a proxy.

**Streaming every round, not just the last.** You cannot know which round is
last until you have seen it, so the loop streams all of them — which means
reassembling `tool_call` fragments as well as text. The model sends a tool
name and its arguments **in pieces, indexed, across many chunks**.

**Run**

```bash
docker compose up -d                                            # database
uv run python -m chargeops.server                               # MCP  :8765
uv run uvicorn chargeops.web:app --port 8080 --reload            # web  :8080
open http://127.0.0.1:8080/widget
```

**Known gaps**

- `POST /session` has **no auth and no rate limit**. Anyone reachable can mint
  tokens, and every token costs money to use.
- `allow_origins=["*"]` — fine for a demo, wrong for production.
- Sessions live in memory: a restart forgets every conversation.

---

*Day 14 to follow.*
