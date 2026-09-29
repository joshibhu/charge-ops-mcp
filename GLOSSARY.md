# Glossary

Terminology I met while building this and `ai-sprint`. Kept as an interview
and reference aid — not a textbook. Every entry is something I actually hit,
with a note on *where*, because a term anchored to a real moment is one I can
discuss rather than recite.

**How to add an entry.** Append to the right section in this form:

```
| **Term** | One line. What I would say out loud. | D12 — the concrete moment |
```

`D1`–`D30` are sprint days. Keep the middle column to one sentence; if it needs
a paragraph, it belongs in a README day-note and this row should point at it.

---

## 1. LLM fundamentals

| Term | What it means | Where I met it |
|---|---|---|
| **Stateless API** | No server-side memory. The whole conversation is resent every turn; the message list in my process *is* the memory. | D2 — the chat REPL |
| **Context window** | Hard ceiling on history + input + output together. Exceed it and you get an error, not truncation. | D2 |
| **Token** | The billing and context unit. Roughly ¾ of a word. | D2 |
| **Input vs output tokens** | Priced separately; output costs several times more. "Be concise" is a cost control. | D2 |
| **Reasoning tokens** | Generated and billed as output, never returned, and **not** carried into the next turn's input. | D2 — 2,300 output tokens for 124 visible |
| **Quadratic cost growth** | Turn 20 re-bills turns 1–19. Cost grows with the square of conversation length. | D2 — ₹84 per 1,000 questions |
| **Temperature** | Randomness. 0 for extraction and classification; higher for copy. | D2 |
| **`max_completion_tokens`** | Ceiling on reasoning + visible output combined. The only way to bound unverifiable reasoning spend. | D2 |
| **Streaming / SSE** | A UX feature, not a speed one — it cuts time-to-first-token from ~8s to ~0.4s. | D2 |
| **`stream_options={"include_usage": True}`** | Without it, a streamed response carries no token counts at all. | D2 — the cost line was impossible until this |
| **Prompt caching** | Provider re-reads a stable prefix cheaply. Prefix match: one changed early byte invalidates everything after. | D2, mentioned |
| **System / user / assistant roles** | Standing instruction, the human, the model's earlier replies replayed back. | D2 |
| **Structured outputs** | The schema **constrains** generation. Not a better-worded request for JSON. | D3 |
| **JSON Schema** | The format describing the shape. `pydantic` generates it; MCP sends it. | D3, D8 |
| **Hallucination** | A confident, fluent, wrong answer. | D2 — it invented "FCR-A" |
| **Descriptions are prompt text** | Field descriptions, tool descriptions and docstrings all reach the model. Vague wording produces vague behaviour. | D3, D5, D6, D8, D9 — six times |

## 2. Agents and tools

| Term | What it means | Where I met it |
|---|---|---|
| **Tool calling / function calling** | The model *requests* a call. It cannot execute anything. My code decides. | D5 |
| **Tool schema (menu)** | `{name, description, parameters}` — what the model is told it may ask for. | D5 |
| **Dispatcher** | The name→function lookup. **This is the security boundary**, not the prompt. | D5, D6 |
| **Agent loop** | ask → wants a tool? → run it → feed the result back → repeat. That loop *is* the agent. | D5 |
| **Iteration cap** | Bounds a confused model. Every lap is a paid call with a growing history. | D5 — `MAX_ROUNDS = 5` |
| **Parallel tool calls** | Several requests in one assistant turn. Every one needs a matching result or the next request is rejected. | D5 — two cities at once |
| **Sequential tool chain** | Round 2's arguments come from round 1's result. Impossible without a loop. | D5 — temperature, then doubled |
| **`tool_call_id`** | Ties a result back to its request. Needed because several can be in flight. | D5 |
| **Normal exit** | The model answering in plain text is *success*, not a missing case. | D5 — beginners code this as an error |
| **Checkpointer** | Somewhere to keep the message list between calls. A dict, a file, a Postgres table. | D12 |
| **`thread_id`** | The key the stored conversation is filed under. Two users, two threads. | D12 |
| **Recursion limit** | A framework's name for MAX_ROUNDS. A ceiling, not a target. | D12 |
| **History trimming** | Drop or summarise old turns so cost stops growing. The policy is a product decision. | D12 |
| **Orphaned tool message** | A `tool` result whose assistant request was trimmed away. Rejects the WHOLE conversation with a 400. | D12 |
| **Prompt injection** | Instructions hidden in data the model reads (a document, a database row). | D6 — it was ignored, not refused |

## 3. Security

| Term | What it means | Where I met it |
|---|---|---|
| **Defence in depth** | Not five locks on one door — five doors. Breaking one still leaves you outside. | D6, D10 |
| **Least privilege** | The app connects as a read-only role, never the owner. | D6 |
| **Read-only role** | Two independent mechanisms: no write GRANT *and* `default_transaction_read_only`. | D6 |
| **Allow-list vs block-list** | A block-list is a list of the attacks you happened to think of. | D10 — "no DELETE" passed `pg_authid` |
| **Parameterised query / PreparedStatement** | Values sent separately from the SQL text, never spliced in. | D6 |
| **SQL injection** | Why string formatting into SQL is never acceptable — and the attacker may be a model, not a person. | D6 |
| **AST guard** | Parse the query and inspect the *structure*. Text search cannot see a DELETE hidden in a CTE. | D10 |
| **Query rewriting** | The guard doesn't only check — it adds a missing LIMIT and lowers an excessive one. | D10 |
| **Check/execute gap** | Execute the SQL **regenerated from the inspected tree**, so validator and executor cannot disagree. | D10 |
| **Timing attack** | `secrets.compare_digest`, not `==`. A plain comparison leaks a secret one character at a time. | D8 |
| **Bearer token** | Shared secret in an `Authorization` header. Static tokens cannot be scoped, expired or revoked per client. | D8 |
| **Blast radius** | What a compromised or buggy component can reach. For an MCP client, the tool list. | D8 |
| **Any name-based control fails when the other side chooses the names** | Masking keyed on column name; `SELECT driver_name AS city` defeated it entirely. | D11 |
| **Filtering vs absence** | Don't hide the value — make it unreachable. A view plus REVOKE, not a mask. | D11 |
| **View as a permission boundary** | Grants apply to the view; the role loses the table. Column hiding, row filtering, pre-applied masking. | D11 |
| **`security_barrier`** | Postgres views are not a security barrier by default; needed when a view filters rows. | D11 |
| **Row-Level Security (RLS)** | Per-row policies on the table itself, enforced however the data is reached. The heavier tool once you have real tenants. | D11, mentioned |
| **Give the model its own schema** | Not your tables — a purpose-built view layer, safe by construction. | D11 |
| **Masking vs anonymisation** | Masking stops raw identifiers leaving the process; it does not prevent re-identification by someone holding the original. | D11 |
| **Partial masking** | Keep the shape, lose the identity: last 4 digits, the email domain, the state code. Total redaction destroys the data. | D11 |
| **DPDP Act / GDPR** | Sending customer personal data to an uncontracted processor IS the violation. | D11 |
| **Statement timeout** | A runaway query cannot pin the database. | D6 — 8s on `ops_reader` |
| **Row cap** | One careless query must not drag 9,000 rows into a model's context and your bill. | D6, D10 — 200 rows |

## 4. Data and correctness

| Term | What it means | Where I met it |
|---|---|---|
| **One run is not a measurement** | The single most important rule in this field. | D3 — 10/10 then 9/10 on identical input |
| **Non-determinism** | Same input, different output. A passing run means a passing run. | D3, D5 |
| **Intermittent failure** | Worse than a consistent one: it passes the test, the demo and the pilot. | D5 — the tool fired 0/5 vs 5/5 |
| **Silent failure** | Valid shape, wrong value, no error anywhere. | D3 — a typed invoice naming the customer as vendor |
| **Valid shape ≠ correct answer** | Structured output guarantees the shape and nothing about the truth. | D3 |
| **Ground truth** | The known-correct answers a score is measured against. Without it, no score exists. | D3 |
| **Overfitting** | Tune on all ten documents, reach 10/10, learn nothing. Marking your own homework with the answer sheet open. | D3 |
| **Train/test split** | Hold data back, or the score isn't a prediction. | D3 |
| **Tests vs evals** | Tests: my code, pass/fail, milliseconds. Evals: model behaviour, a **rate**, minutes and money. | D7 |
| **Per-field vs per-document accuracy** | Four fields at 95% each is 81% per document. Report both — they answer different questions. | D3 |
| **Human-in-the-loop / confidence routing** | Target 100% **safety** with a high automation rate, not 100% accuracy. | D3 |
| **Suspect the measurement first** | When a result looks impossible, the instrument is usually wrong. | D7 curly apostrophe · D9 impossible count · D10 stale server, unquoted curl |
| **Benchmark validity** | A 10/10 on an easy benchmark measures the sample set, not the system. | D3 — 300-char synthetic PDFs |
| **Fan-out (cartesian product)** | Joining one row to two independent one-to-many tables multiplies them. | D9 — "628 open faults" at a site with 1 |
| **Sanity check** | No per-site count may exceed the table's own total. Thirty seconds. | D9 |
| **CTE** | Aggregate each side to one row *before* joining. The fan-out fix. | D9 |
| **`FILTER (WHERE ...)`** | Several conditional counts from one pass over the table. | D9 |
| **`COALESCE`** | `sum()` returns NULL, not zero, on no rows. | D9 |
| **Adjacency reads as causation** | Two facts side by side invite a causal story nobody checks the dates on. | D9 — open fault next to zero sessions |
| **A test that asserts a database grant** | `has_table_privilege(...) is False` — fails the build when a migration widens access. | D11 |
| **A test that has never failed cannot be trusted** | Sabotage it deliberately and watch it catch the thing. | D11 — two sabotages |
| **Safe by default vs safe by vigilance** | A new column invisible unless exposed, beats a new column leaking unless remembered. | D11 |
| **Idempotent transform** | `mask()` leaves an already-masked value alone, so layers compose instead of mangling. | D11 |
| **Invisible policy** | A curated tool can embed a judgment (weights, a hardcoded filter) that neither model nor user can see. | D6, D9 |

## 5. MCP

| Term | What it means | Where I met it |
|---|---|---|
| **MCP** | A standard for exposing tools so any AI client can use them. JDBC, not a breakthrough — the value is the agreement. | D8 |
| **JSON-RPC 2.0** | The wire format underneath. Request/response with an `id`. | D8 |
| **stdio transport** | The client launches the server as a subprocess and talks over pipes. One client, no auth needed. | D8 |
| **streamable-http transport** | The server is a service you run. Many clients, and auth becomes mandatory. | D8 |
| **The transport changes the trust boundary** | A pipe needs no credential; a port does. | D8 — the server answered a stranger |
| **`initialize` / `notifications/initialized`** | The handshake, once per session. | D8 |
| **`tools/list`** | Discovery. Returns `{name, description, inputSchema}` — the same dict I hand-wrote on D5. | D8 |
| **`tools/call`** | Invocation. Result comes back as a list of content blocks, not a bare string. | D8 |
| **`inputSchema`** | Generated from type hints by reflection at request time. Exists nowhere on disk. | D8 |
| **Tools are fetched, not registered** | The client asks `tools/list` at startup. The server's name appears nowhere in the client — only a URL and a token. | D12 |
| **Server scope** | `--scope local` works only in the directory it was registered from; `--scope user` everywhere. | D8 — commonest "it doesn't work" |
| **Tool name prefix** | `mcp__chargeops__run_sql`. Prevents collisions; does nothing for *semantic* overlap. | D8 |
| **Descriptions do the routing** | The model sees one flat list and picks on description. The protocol contributes nothing to that choice. | D10 — `run_sql` fired on "any question the other tools do not cover" |
| **Curated vs raw tools** | Curated: I write the SQL, reviewed and testable. Raw: the model writes it, for the long tail. Both, not either. | D6, D9, D10 |

## 6. Python and general engineering

| Term | What it means | Where I met it |
|---|---|---|
| **Decorator** | An annotation that has **already run** and may replace the function. `@x` is `f = x(f)`. | D8 — set `__doc__` after it, too late |
| **Reflection** | How type hints and docstrings become a JSON schema. | D8 |
| **Library vs framework** | A library you call; a framework calls you. Inversion of control — Jackson vs Spring, OpenAI SDK vs LangGraph. | D12 |
| **`async` is contagious** | One async dependency makes every caller async. An architectural choice, not a local one. | D12 |
| **`AsyncExitStack`** | Enter several context managers dynamically and unwind them correctly. Hand-rolling it broke anyio's task scoping. | D12 |
| **`__aenter__` / `__aexit__`** | The `async with` protocol. Python's try-with-resources. | D12 |
| **Spike** | A throwaway program that answers "will this work?", then gets deleted. XP term. | D12 |
| **A long-running process holds the code it started with** | Three-day-old server still ran Day 10 code against a table Day 11 revoked. | D12 |
| **`uv`** | Maven/Gradle. `uv add` to install, `uv run` to execute. Never `pip install`. | D1 |
| **`pydantic`** | Jackson + Bean Validation in one. Validates and coerces at construction. | D1 |
| **`pydantic-settings`** | `@ConfigurationProperties` bound to env vars. Fails at startup, not mid-request. | D1 |
| **src layout** | Forces imports through the *installed* package, so tests exercise what ships. | D1, D8 |
| **Relative import** | `from .settings import settings`. Works under `python -m`, fails when running the file directly. | D1 |
| **Type hints are not enforced** | The interpreter ignores them; the IDE and linters don't. In MCP they are load-bearing. | D1, D8 |
| **Provider seam** | One file imports the vendor SDK. Everything else calls my function. | D1 — held across five days of features |
| **Event loop / async vs sync** | A blocking call in an `async` handler stalls the whole server, not one request. | D4 |
| **Liveness vs readiness** | "The process answers" vs "the provider is reachable". | D4 — `/health` vs `/ready` |
| **Connection pool** | HikariCP. Built once, reused; here opened lazily so imports don't need a live database. | D6 |
| **Fake / stub** | Replace a collaborator you don't own so tests are fast and deterministic. | D7 — a scripted model |
| **Fixture** | JUnit `@BeforeEach` plus parameter injection. | D7 |
| **Integration marker** | `pytest -m "not integration"` — skipped, not failed, when Docker is down. | D7 |
| **Over-specified assertion** | A test that asserts more than the behaviour you care about, and fails on correct code. | D7 — compared a header that echoes input |
| **List comprehension** | `stream().map().toList()`. | D6 |
| **`"".join(parts)`** | String concat in a loop is O(n²). `StringBuilder`'s reason. | D2 |
| **View vs materialised view** | A view is a stored query (always live); a materialised view is a copy and needs refreshing. | D11 |
| **View dependency** | Postgres refuses to drop a column a view uses — a safety net you get for free. | D11 |
| **No opt-out parameter** | An `unmasked=True` flag gets copied around and becomes the default by accident. Add a separate explicit function instead. | D11 |
| **ASGI middleware** | Wraps the app to check auth before anything reaches it. | D8 |

---

## The five worth leading with

Anyone can define the terms above. These come from having been wrong, which is
what makes them convincing.

**1. "One run is not a measurement."**
10/10 then 9/10 on identical input. And a single-run experiment that gave the
**opposite** conclusion from five runs of the same thing.

**2. "Valid shape ≠ correct answer."**
A perfectly typed, fully validated invoice where the vendor was the customer.
Nothing in the code caught it. Only the ground-truth file did.

**3. "Safety is the dispatcher and the database role, never the prompt."**
A prompt-injection attempt was *ignored*, not refused — there was no delete
tool to be tricked into calling. You cannot jailbreak a capability that does
not exist.

**4. "The layer I'd trust on a bad day is the one I didn't write."**
My AST guard let `pg_read_file` through. Postgres refused it anyway.

**5. "Suspect the measurement before the thing measured."**
Four times in ten days: a curly apostrophe that matched nothing, a count that
could not be true, a stale server still holding the port, an unquoted curl
header.
