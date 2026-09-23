# Round 4 — API edge (ED)

**Scope.** Commit `653dc9c` ("Findings round 3: 100 findings patched ..."), reviewed in the disposable worktree `/Users/ericguei/Documents/caos-databricks/.claude/worktrees/agent-a8852d8be674d9d44` (branch `worktree-agent-a8852d8be674d9d44`, clean at start). Reviewer: Claude Opus 5.5 (`claude-opus-5-5`) at effort max, adversarial-reviewer skill. The harness refused the report file from the subagent; the orchestrator saved this text from the reviewer's final message verbatim.

Files read:
- `CLAUDE.md`, `docs/rebuild/decisions.md` F71–F109, `docs/rebuild/round3/{README,findings-round3,decisions-edge}.md`, `docs/rebuild/next.md`.
- `caos/api/{edge,identity,health,stream,events,app,deps,site}.py`.
- `caos/api/commands/{_request,cases,members}.py`; the other command modules skimmed for routing and identity order.
- `caos/api/reads/{evidence,directory,model,book,qualification}.py`.
- `caos/blobs.py`, `caos/workspace.py`, `caos/serve.py`, `caos/store/{commands,audit}.py`, `caos/evidence/ingest.py::admit_prepared`, `scripts/io_budget.py`, and the tests that name these modules.

Tests run: the targeted suites `tests/test_edge.py`, `test_stream_slots.py`, `test_actor_matrix.py`, `test_edge_assertion.py`, `test_command_availability.py`, `test_identity_platform.py`, `test_health.py`, `test_case_events.py`, `test_identity_first.py`, `test_run_stream.py`, `test_site.py` and `test_api_routes.py`, with `-n 4`: **217 passed**.

Probes: 16 scripts in `docs/rebuild/round4/probes/edge/`; each prints its own evidence. The ones that need Postgres create and drop `r4_ed_*` databases, and none is left behind. No source file was edited; no paid model call was made and no real workspace was used.

**Verdict: BLOCK**

## Findings

### ED-1 [CRITICAL] A tail's stream slot is not given back when the browser goes away; only a full garbage collection returns it, so four section changes lock a user out of live updates

- **Where:**
  - `caos/api/app.py:542-575`: `take_stream_slot`, the sync `framed()` generator, `weakref.finalize`, `StreamingResponse(tail)`.
  - The claim that disconnects release the slot: `caos/api/app.py:534-541` and `caos/api/stream.py:104-116`.
  - The test that cannot see the leak: `tests/test_case_events.py:643-677` (`test_a_tail_slot_is_returned_however_the_stream_ends`), because it calls `gc.collect()`.
  - MX-2's per-actor share: `caos/api/stream.py:86`.
- **Verified:** yes. `ED_APP=site uv run python docs/rebuild/round4/probes/edge/stream_slot_gc.py` serves `caos.api.site:application` the way `caos.serve` does: `limit_concurrency=64`, the log filter installed, and the shipped poll interval (0.5 s) and deadline (300 s).

      four tails open: (4, 4)
      reopen 3 s after closing all four: HTTP/1.1 503 Service Unavailable b''
      held after closing: (4, 4); released_at=None s; refused reopen attempts meanwhile: 0
      other backends on the probe database meanwhile: 0
      automatic collections while waiting (t, generation): []
      `framed` generators still alive: 4
        referrers of one: ['frame:iterate_in_threadpool', 'tuple:']
      gc.collect() found 856 objects -> held now (0, 0)

  - With a reconnect loop (`ED_RETRY=1`, 73 refused reopens in 45 s), five automatic collections ran (`[(3.29, 0), (12.32, 1), (22.28, 0), (32.24, 0), (42.18, 0)]`). Three slots were still held at 45 s (`held after closing: (3, 3)`), so only a full collection frees them.
  - `stream_slots.py` separates the exit paths:
    - Client closes after the first frame (FIN), client resets (RST), and client closes before any response byte: all `released after None s` within the 8 s window.
    - The same actor then reopening four tails gets four `503 STREAM_LIMIT_REACHED`.
    - An exception inside the generator does release (`released after 0.22 s`), and so does the tail's own deadline (`0.7 s`).
- **Failure:**
  - **Mechanism.** uvicorn 0.52.4 advertises ASGI spec 2.3, so Starlette handles a disconnect by cancelling `stream_response` while it awaits `iterate_in_threadpool`. The `CancelledError` unwinds that async generator, and a reference cycle through its traceback keeps the `iterate_in_threadpool` frame alive. That frame holds the sync `framed` generator. As a result neither its `finally: slot.release()` nor the `weakref.finalize` runs until CPython does a full cyclic collection.
  - **How long.** The served process holds about 169,000 long-lived objects after import. CPython 3.13 runs a full collection only after roughly a quarter of that has been allocated and survived again, which in a quiet App can take minutes or hours.
  - **How often a slot leaks.**
    - The frontend closes and reopens its tail on every section change: the `Workspace.tsx` effect is keyed on `section`, and six sections are tailed.
    - It also does so on every case switch, reload or closed tab.
  - **Result.**
    - After four such changes the actor's `ACTOR_STREAM_LIMIT` is spent on dead tails. Every new tail then answers 503 `STREAM_LIMIT_REACHED`, and the page shows "not live" while it retries without success.
    - After 24 disconnects across users the global cap is spent too, and nobody gets live updates.
  - **Only capacity leaks.** Database connections are closed (0 backends).
  - **Why round 3 matters.** MX-2's per-actor share is what turns this leak into a lockout after four navigations.
  - **Without disconnect propagation.** If the Apps proxy does not pass the browser's close upstream, each tail is held for its full 300 s instead. That is the same lockout on a timer.
- **Fix:** stop depending on the garbage collector.
  - Wrap the response body so that cancellation itself closes the sync tail, for example: `async def body(): try: async for chunk in iterate_in_threadpool(tail): yield chunk` / `finally: tail.close()`.
  - Alternatively pass `background=BackgroundTask(slot.release)`, which Starlette runs after a disconnect.
  - The first variant, applied in-process by `ED_FIX=1` in the same probe, gives `held after closing: (0, 0); released_at=0.61 s`.
  - Pin it with a test that serves the route over uvicorn, closes the sockets of four tails under `gc.disable()`, and asserts `SLOTS.held` is empty and a fifth tail opens within a second.
  - Remove the `gc.collect()` call from the existing test.

### ED-2 [WARNING] Through the process entry, an unhandled fault answers `text/plain` "Internal Server Error", not the typed `INTERNAL_FAULT` refusal

- **Where:**
  - `caos/api/edge.py:483-487`: a scope already marked as guarded passes straight through, with no fault handling.
  - `caos/api/edge.py:510-519`: the fault handler, which only works when the guard sits inside Starlette's `ServerErrorMiddleware`.
  - `caos/api/site.py:105-115`: `application = EdgeGuard(dispatch)` wraps the FastAPI app, so the app's own guard becomes the pass-through one.
  - `tests/test_edge.py:380-400` exercises a bare `FastAPI()` with one guard, never `site.application`.
- **Verified:** yes. `unhandled_fault.py` uses a store dependency that raises `RuntimeError("secret document text")`:

      caos.api.app:app:
         status 500, content-type 'application/json'
         body '{"code":"INTERNAL_FAULT","clears":"Retry; an operator must investigate if it persists."}'
      caos.api.site:application:
         status 500, content-type 'text/plain; charset=utf-8'
         body 'Internal Server Error'

  Over real uvicorn started the way `caos.serve` starts it (`log_text.py`): `wire: 500 text/plain; charset=utf-8 'Internal Server Error'`.
- **Failure:**
  - In production every unhandled fault on `/api` reaches the browser as Starlette's plain-text 500. ED-3 and ED-6 below are examples.
  - The typed body the wire contract and CLAUDE.md require never arrives. `ServerErrorMiddleware` inside the FastAPI app answers first; the outer guard then sees the response already started and sends nothing.
  - No text leaks: the security headers are still added, and the log carries only the exception class and frame.
  - This predates round 3 (the pass-through is already in `04c10a9`), and no test covers the composition that ships.
- **Fix:** keep fault handling in the pass-through branch.
  - When `caos.edge_guarded` is already set, still wrap `self.app(...)` in the same `try`, send `INTERNAL_FAULT` if the response has not started, then re-raise.
  - The inner guard sits inside `ServerErrorMiddleware`, so it answers first.
  - Add a test that drives `caos.api.site:application` with a raising dependency and asserts the JSON body.

### ED-3 [NOTE] `DATABRICKS_HOST` values that boot accepts still reach `http.client` malformed: whitespace, and IPv6 literals without a port

- **Where:**
  - `caos/api/identity.py:401-427`: `workspace_address` returns an IPv6 host without brackets and `port=None`, and accepts a hostname containing spaces.
  - `caos/api/identity.py:453-457`: the connection is built outside `scim_me`'s `try`.
  - `caos/api/edge.py:238-239`: boot validates only through `workspace_address`.
- **Verified:** yes. `workspace_address.py`:

      'http://[::1]'          -> ... host='::1' port=None | boot accepts | would connect to host=':' port=1
      'https://[2001:db8::1]' -> ... | boot accepts | would connect to host='2001:db8:' port=1
      'https://[2001:db8::a]' -> ... | boot accepts | RAISES http.client.InvalidURL in the constructor
      'https://adb-123.net '  -> ... | boot accepts | RAISES http.client.InvalidURL in the constructor

  - `platform_headers.py` step 5: `'https://localhost ': boot -> EdgeMode(... platform=True)`, then `request -> 500 content-type='text/plain; charset=utf-8' body='Internal Server Error' retry-after=None`.
  - `identity_scim.py` step 2e: every lookup ends in `UNTYPED InvalidURL`.
- **Failure:**
  - EI-N2 says boot is where a configuration is answered.
  - A host with a trailing or inner space, or an IPv6 literal whose last group is not all digits, boots and then fails every request with an untyped `InvalidURL`. The answer is 500, not 503 `IDENTITY_UNAVAILABLE` with `Retry-After`, while the health probe reports `IDENTITY_UNAVAILABLE`.
  - An IPv6 literal whose last group is all digits silently asks SCIM at the wrong host, on port 1.
  - It is only a NOTE because on Databricks Apps the platform injects `DATABRICKS_HOST` as a plain hostname; only stand-in and local runs can meet these values.
- **Fix:**
  - Move `opener(...)` inside the `try`; its `InvalidURL` is already an `HTTPException`, which the existing clause catches.
  - In `workspace_address`, refuse hostnames containing whitespace, re-bracket IPv6 hosts, and always pass an explicit port (443 or 80).
  - Add these four values to the table in `test_a_bearer_is_never_sent_in_clear_to_anything_but_this_machine`.

### ED-4 [WARNING] The health gate's time ceiling (AR-11) lets rounds pile up over probes that are still running, and a hung probe starves the healthy ones into `PROBE_TIMEOUT`

- **Where:**
  - `caos/api/health.py:52-60`: `INFLIGHT_CEILING = PROBE_DEADLINE * 2`, justified as "longer than any probe that is really running".
  - `:308-332`: `_blocked` and the reset in `probe_once`.
  - `:282-305`: `_one`, one default-executor thread per probe.
  - The promise it breaks, in the module docstring and F47: "a round already in flight is never started twice".
- **Why the ceiling is too short:** real probes can run past 10 s.
  - `scim_me`'s 10 s socket timeout applies per operation, so connect plus read is already 20 s or more.
  - The SDK client allows 15 s per HTTP call and 30 s of retries.
  - The SDK's service-principal token POST has no timeout at all: `.venv/.../databricks/sdk/oauth.py:209`, `requests.post(token_url, params, auth=auth, headers=headers)`.
- **Verified:** yes. `health_inflight.py`, with the shipped ratios scaled down (deadline 0.1 s, ceiling 0.2 s, interval 0.1 s):

      A. a 1.0 s store probe under a 0.2 s ceiling: peak concurrent store probes = 5
      C. identity probe that never returns, executor of 4: 15 rounds
         first rounds: ['OK', 'OK', 'OK', 'OK']
         last rounds:  ['PROBE_TIMEOUT', 'PROBE_TIMEOUT', 'PROBE_TIMEOUT', 'PROBE_TIMEOUT']
         healthy store probe's code at the end: PROBE_TIMEOUT; bundle PROBE_TIMEOUT; executor threads alive 4

- **Failure:**
  - At shipped values a round starts about every 15 s.
  - A probe that takes 30 s now has two or three copies running against a dependency that is already struggling; examples are a Lakebase mint abandoned at 30 s, a slow SCIM, or the SDK's retry budget. That is the pile-up F47 was written to forbid.
  - A probe that never returns, such as the untimed token POST, leaves one thread per round in the loop's default executor, which holds at most `min(32, cpu + 4)` threads.
  - Once the executor is full, every probe queues behind the hung ones and reports `PROBE_TIMEOUT`, including a healthy store and bundle, until the hung calls end.
  - This is a regression introduced by AR-11's round-3 fix.
- **Fix:**
  - Give each probe kind its own "running" flag, set when its thread starts and cleared in its `finally`.
  - While a probe's previous run is still alive, skip that probe and keep its last code (or report `PROBE_TIMEOUT`), rather than letting the gate expire on a timer.
  - Run the probes on a small dedicated executor so a hung one cannot starve the others.
  - Test with a probe that runs for 5× the deadline (at most one copy alive) and one that never returns (the other probes stay `OK`).

### ED-5 [WARNING] F104/DL-7 is not fixed on the only production path: `POST /sources` uploads every document while holding the case row and the audit chain head

- **Where:**
  - `caos/api/commands/cases.py:222-244`: the `write` passed to `governed` (lines 237-242) calls `admit_prepared(unit, blobs, case_id, pack)`.
  - `caos/store/audit.py:80-84`: `governed_write` takes `lock_case` and `_lock_head` before it calls `write`.
  - `caos/evidence/ingest.py:185-208`: the puts happen before `admit_prepared`'s own `lock_case`, which is only the second lock in the same transaction.
  - `tests/test_admission_limits.py:146-180` calls `admit_prepared` on a bare connection, so its `["put", "put", "lock"]` never sees the route's lock.
- **Verified:** yes. `admission_lock.py` makes a case through `POST /api/v1/cases`, then admits two documents; during each `put` a second connection asks for the rows with `FOR UPDATE NOWAIT`:

      admission: 201 {... 'source_ids': [...2 ids...]}
         put: cases row LOCKED by the request
         put: audit_chain_heads row LOCKED by the request
         put: cases row LOCKED by the request
         put: audit_chain_heads row LOCKED by the request

- **Failure:**
  - On Databricks each put is a Files API upload.
  - An admission of up to fifty documents holds `cases ... FOR UPDATE` and the audit chain head for the whole upload.
  - Every fenced write of every run in the case, and every governed command on the case, waits behind those uploads.
  - That is exactly the DL-7 defect F104 records as fixed.
- **Fix:**
  - Do the puts in the route, before `governed(...)`. They are content-addressed, and an orphan left by a refused unit is already accepted.
  - Give the unit a lock-only insert that takes the digests.
  - Add a route-level test that drives `POST /sources` and asserts, from a second connection during the put, that the case row is free.

### ED-6 [WARNING] F85 did not cover the blob backend's own calls: an expired service-principal token with a failing token endpoint escapes `BlobStore` as an untyped `ValueError`/`NotImplementedError`

- **Where:**
  - `caos/blobs.py:71-94`: `VolumeBackend.upload`, `download` and `probe` catch `OSError` only.
  - `caos/workspace.py:48-60` maps `ValueError` only when the client is constructed.
  - The SDK's per-request token refresh raises `ValueError` for a non-2xx token answer and `NotImplementedError` for a malformed one (`.venv/.../databricks/sdk/oauth.py:216-229`).
- **Verified:** yes. `volume_auth_fault.py` uses the real SDK client from `caos.workspace.workspace_client()`, with oauth-m2m against a loopback stand-in whose token endpoint is switched after the first mint:

      token endpoint 'ok': read 20 bytes
      token endpoint 'down': UNTYPED builtins.ValueError escapes BlobStore.get
      token endpoint 'garbled': UNTYPED builtins.NotImplementedError escapes BlobStore.get

- **Failure:**
  - On Databricks Apps the app's service principal re-mints its token every hour.
  - If the workspace's token endpoint answers 503 at that moment, every read that touches the volume fails as an unhandled 500. That covers evidence-page reads, the Analysis, Model and Book reads, and admissions.
  - Because of ED-2 that 500 is plain text, not a 503 `STORE_UNAVAILABLE` with `Retry-After`.
  - F85 says the SDK's `ValueError`, which "escaped ... the blob backend", was mapped; only the construction path was.
- **Fix:**
  - In `VolumeBackend`, catch `(OSError, ValueError, NotImplementedError)` around each SDK call and raise `Refusal(STORE_UNAVAILABLE) from None`.
  - Add the probe's stand-in token endpoint to `tests/test_lakebase_and_blobs.py`, which also covers the gap noted in N7.

### ED-7 [WARNING] Declared I/O budgets are not bounds, blob reads are budgeted nowhere, and `io_budget.py --assert` cannot tell

- **Where:**
  - `caos/api/reads/analysis.py:64-75`: `IO_BUDGET = FIXED_IO + LITE_NODES * PER_HANDOFF_IO = 37`, "declared for a LITE run of three".
  - `caos/api/stream.py:52-58` (`IO_BUDGET = CONNECT_IO + POLL_IO = 4`) and `caos/api/app.py:96-97` (`EVENTS_IO_BUDGET = 7`).
  - `scripts/io_budget.py:40-85`: checks only that a non-negative count is declared, never what a path costs.
  - This is not covered by N9, which names different modules (model, qualification, members).
- **Verified:** yes. `CAOS_TEST_POSTGRES_URL=... CAOS_REQUIRE_POSTGRES=1 PYTHONPATH=tests uv run pytest --no-cov -p no:cacheprovider -p conftest -s docs/rebuild/round4/probes/edge/test_probe_io_budget.py`, on the suite's completed ten-node forecast run:

      analysis: 20 distinct blobs among 91 reads; most repeated [(16, '39930f103958'), (13, '36ae85dc2a46'), (6, 'd4a19be57fab')]
         readers: [(31, 'stored_lineage.<locals>.chain <- _or_refuse'), (28, 'read_record.<locals>.read <- _or_refuse'), (28, '_read <- verify_accepted'), (4, 'upstream_markdown.<locals>.read <- ...')]
      analysis: 149 store round trips, 91 blob reads, 10 handoffs; declared analysis.IO_BUDGET = 37
      model:    150 store round trips, 91 blob reads; declared model.IO_BUDGET = 150
      scripts/io_budget.py --assert -> exit 0: all 26 route module(s) declare IO_BUDGET

  For the stream, `tests/test_case_events.py::test_the_event_stream_costs_its_declared_budget` (which passed) pins `len(log) == 2 + CONNECT_IO + 1 + polls * POLL_IO + named`. So:
  - The generator's own connect plus first poll is 5 statements, against a declared `stream.IO_BUDGET = 4`.
  - One poll carrying full pages of named frames (`ACTIONS_PAGE` and `RUN_PAGE`, 500 each) runs up to about 1,003 standing rechecks, against the route's declared 7.
- **Failure:**
  - One `GET /analysis` on the longest pinned route costs 4× its module's declared round trips.
  - It also downloads 91 blobs of which only 20 are distinct. The same record is fetched up to 16 times, by `stored_lineage`, `read_record` and `verify_accepted` in turn.
  - On Databricks each fetch is a Files API download plus a SHA-256 of the bytes.
  - `GET /book` multiplies this by up to four credits, about 364 downloads per page.
  - The gate that exists to stop excessive I/O still passes, because it never measures anything and no budget has a blob dimension.
- **Fix:**
  - Declare `analysis.IO_BUDGET` for the longest pinned route, as `model.py` does, and measure it on the forecast harness.
  - Put a request-scoped, digest-keyed memo in front of `BlobStore.get` (bytes verified against their digest never change), and assert a `BLOB_BUDGET` in the same tests.
  - Either make `io_budget.py` refuse a module whose declared number a registered measurement exceeds, or say in its docstring that it only checks declarations.
  - Make `stream.IO_BUDGET` count the cursor recheck.

### ED-8 [WARNING] SCIM waits are bounded per socket operation, not per lookup, and every waiter holds a worker thread: one slow or trickling lookup stalls unrelated callers

- **Where:**
  - `caos/api/identity.py:227-234`: `SCIM_TIMEOUT_SECONDS = 10` and `SHARED_WAIT_SECONDS = 20`, justified as "the wait ends because the lookup ended".
  - `:323-332`: `_shared` blocks on a `threading.Event`.
  - `:453-468`: the timeout applies to each connect or receive, not to the whole exchange.
  - `caos/api/deps.py:94-112`: `actor_from_request` is a sync dependency, so every request, leader or waiter, runs in one of AnyIO's 40 threads, fewer than `LIMIT_CONCURRENCY = 64`.
- **Verified:** yes.
  - `identity_scim.py` step 2b, with the socket timeout scaled to 1 s and a stand-in whose 200 body trickles one byte every 0.4 s:

        leader: actor ANALYST after 23.0 s
        six later requests (one every 2.5 s) while it trickles: [('IDENTITY_UNAVAILABLE', 2.0), ... x6]
        SCIM calls for that token: 1

  - `identity_threads.py`, real uvicorn in platform mode, with one token answered in 3 s:

        a cached caller's directory read: 0.06 s alone; 5.53 s while 45 requests wait on one cold token's 3 s SCIM lookup

- **Failure:**
  - A lookup that keeps receiving a byte inside each socket timeout holds its flight open indefinitely. So does one stalled in DNS, which the socket timeout does not cover.
  - Every request for that token joins the flight, waits 20 s, answers `IDENTITY_UNAVAILABLE`, and never retries until the leader returns.
  - Each waiter meanwhile occupies a worker thread. A burst of cold requests during a SCIM slowdown therefore delays callers whose identity is already cached: 0.06 s became 5.5 s.
  - Waiting in a thread does not deliver EI-W3's stated reason, sparing the process's concurrency.
  - `/api/health` is async and keeps answering `ready` throughout.
- **Fix:**
  - Put a total deadline on the SCIM exchange: check a monotonic deadline around `read`, or run it on a bounded executor with `future.result(timeout=...)`.
  - Make identity an async dependency whose waiters await an `asyncio.Event` or future instead of holding a thread, and cap waiters per flight.
  - Test with the trickling stand-in (the leader ends at the deadline) and with the burst (a cached caller stays fast).

### ED-9 [NOTE] A SCIM `200` without a usable `id` is answered "sign in" and remembered as a refused token

- **Where:**
  - `caos/api/identity.py:490-492` answers `NOT_AUTHENTICATED` for a missing or non-string `id`.
  - That contradicts `:484-497`, where AR-12 makes every other malformed shape `IDENTITY_UNAVAILABLE`.
  - `:346-348` then caches the refusal for `NEGATIVE_SECONDS`.
- **Verified:** yes. `identity_scim.py` step 3b, for a `200 {}`: `NOT_AUTHENTICATED NOT_AUTHENTICATED calls 1 negative entries 1`.
- **Failure:**
  - A `200 {}` or `{"id": 5}` from the workspace or something in between is a malformed answer, not a refused token.
  - The browser is still told 401 "Sign in".
  - The token stays refused from the cache for 5 s after the workspace recovers.
- **Fix:**
  - Answer `IDENTITY_UNAVAILABLE`, uncached, for a missing or malformed `id`; keep `NOT_AUTHENTICATED` for 401 and 403.
  - Add the case to `test_a_malformed_scim_answer_is_a_typed_refusal_not_a_type_error`.

## What held up

- **Idempotency under concurrency** (`idempotency_race.py`, real uvicorn):
  - Same actor, key and body sent eight times at once: one 201, seven `idempotency-replayed: true`, one case created.
  - Same key with eight different bodies: one 201, seven 409 `IDEMPOTENCY_KEY_REUSED`, one case created.
  - Eight actors sharing one key: eight cases, because the primary key includes `actor_id`.
  - Refused first attempts (a bidi override, an over-long title) do not burn the key.
  - Eight concurrent case-scoped grants with one key write one `STANDING_GRANTED`.
  - Reusing a key for a different command answers 409.
- **Identity headers in platform mode** (`platform_headers.py`):
  - None of these changed the served role or subject: `x-forwarded-email`, `x-forwarded-user`, `x-forwarded-preferred-username`, `x-forwarded-groups`, `x-databricks-*`, `x-real-ip`, `forwarded`, `x-forwarded-for`, `x-forwarded-proto`, `x-forwarded-host`, `x-caos-user`, `x-caos-role`, or a bogus edge assertion.
  - A duplicated token header answers 401, and the underscore lookalike header is ignored.
  - Platform mode combined with the dev trust switch or an edge key answers 403 `EDGE_NOT_TRUSTED`.
  - `caos/serve.py` runs uvicorn with `proxy_headers=False`.
- **Single flight and negative cache** (`identity_scim.py`):
  - Eight concurrent requests for one cold token make one SCIM call.
  - When the leader gets a 500, its waiters get `IDENTITY_UNAVAILABLE`, and the failure is not cached.
  - Two users resolved at the same time do not share outcomes; the cache key is `sha256(token)`.
  - Only 401 and 403 are cached as refusals, stamped after the call returns.
  - A user added after a refusal is admitted 5.1 s later.
  - Both caches stay bounded at capacity.
- **`workspace_address` refusals:** boot refuses userinfo (including an empty `@`), non-https schemes, clear-text `http` to a non-loopback host, bad or out-of-range ports, and `https:host`.
- **Stream slots:**
  - A tail that raises (released in 0.22 s) or reaches its deadline (0.7 s) gives its slot back.
  - The global cap of 24 and the per-actor cap of 4 both refuse with 503 and `Retry-After`.
  - Shutdown with 24 tails open completes in about 2.2 s.
- **Logs:**
  - `caos.serve`'s `_NoExceptionText` filter survives uvicorn's `dictConfig`, and the server output carries no exception text (`log_text.py`).
  - The guard prints only the exception class and frame.
- **FastAPI's echoing 422 is unreachable:** every path and query parameter is `str`, and every body goes through `json_body` (`routes_params.py`).
- **Static export** (`site_paths.py`) refuses:
  - `..` and URL-encoded `..` paths.
  - Symlinked files and directories.
  - `/api/..` prefix confusion.
  - Methods other than GET.

## Not covered

- **The real Databricks Apps proxy.** No workspace was available, so three things were not checked:
  - whether it passes a browser's close upstream (if not, ED-1 holds each slot for 300 s instead of until the next full garbage collection);
  - whether it rewrites `Host`;
  - whether it strips `sec-fetch-*`.
- **Edge (HMAC) mode** was covered only by the existing suites (`test_edge.py`, `test_edge_assertion.py`, `test_actor_matrix.py`, all passing); removing that mode is deferred as N12.
- **Worker handling of ED-6:** how `caos/graph/worker.py` treats ED-6's `ValueError` from blob calls inside a node; that is outside this section.
- **Files API latency:** the real latency behind ED-7's 91 reads was not measured.
- **Frontend modes:** `test_frontend_modes.py` needs a frontend build, which was not made.
- **Probe hygiene:** the probe scripts are review artifacts. They are ruff-formatted but not lint-clean (they fail the ANN and BLE rules), so keep them out of any commit that has to pass `ruff check .`.
