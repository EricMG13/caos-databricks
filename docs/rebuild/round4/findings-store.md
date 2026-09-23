# Round 4 — Store, worker, graph, model seam (ST)

**Scope.** Commit `653dc9ce91a73137360c43b81f14284d324de58f` (`git log --oneline -1` gives `653dc9c`), reviewed in the disposable worktree `/Users/ericguei/Documents/caos-databricks/.claude/worktrees/agent-a253f6ed29ad1aa26` (branch `worktree-agent-a253f6ed29ad1aa26`, clean at start). Reviewer: Claude Opus 5.5 (`claude-opus-5-5`) at effort max, adversarial-reviewer skill. The harness refused the report file from the subagent; the orchestrator saved this text from the reviewer's final message verbatim.

Read in full:
- `CLAUDE.md`, `docs/rebuild/decisions.md` (F27–F109), `docs/rebuild/round3/{README,decisions-mine,findings-round3}.md`, `docs/rebuild/next.md`
- `caos/store/{__init__,lakebase,work,runs,budget,outcomes,events,cases}.py` and migrations 0006, 0013, 0028
- `caos/workspace.py`, `caos/graph/{build,checkpoint,runtime,worker}.py`, and the resolution and frontier half of `caos/graph/route.py`
- `caos/models.py`, `caos/provider.py`, `caos/pricing.py`, `caos/serve.py`
- the lifespan and shutdown hooks of `caos/api/app.py`, the connection dependency in `caos/api/deps.py`, and the two store probes in `caos/api/health.py`
- the reservation and replay paths of `caos/methodology/canonical.py`
- the installed dependency code these rely on: langgraph 1.2.12, langgraph-checkpoint 4.2.0 serde, langgraph-checkpoint-postgres 3.1.2 migrations, databricks-langchain 0.20.0 `ChatDatabricks`, the databricks-openai client, databricks-sdk 0.140.0 credential types, and uvicorn 0.52.4 `Server`

Skimmed only: the other `caos/store` modules.

Existing tests run, all green:
- `tests/test_checkpoint.py tests/test_lakebase_and_blobs.py tests/test_models.py`: 32 passed.
- `tests/test_worker.py tests/graph tests/test_postgres_races.py tests/test_worker_heartbeat.py tests/test_budget.py tests/test_run_ceiling.py tests/test_call_outcomes.py tests/test_execution_billing.py tests/test_runtime.py`: 281 passed with `-n 4`.

Twelve probes are in `docs/rebuild/round4/probes/store/`. Each one's docstring gives its command.

Only disposable databases on the shared Docker Postgres were used:
- The pytest probes use the suite's own `caos_test_*` fixtures.
- The standalone probes create `r4_st_*` databases and drop them `WITH (FORCE)`. None are left.

No paid model call, no workspace, no network beyond 127.0.0.1, no secret printed.

Personas:
- Saboteur: ST-1, 4, 5, 7, 9, 10, 12, 13.
- New Hire: ST-9's tests, and the docstrings in ST-14 and ST-15.
- Security Auditor: ST-2, ST-5's fence bypass, ST-14.

ST-5 was found from two personas but is not promoted, because the ledger is unaffected.

**Verdict: CONCERNS**

## Findings

### ST-1 [WARNING] While one mint is in flight, every other caller blocks up to MINT_SECONDS, though a live credential is held
- **Where:**
  - `caos/store/lakebase.py:108-124`. The fast path at 112-113 returns only before `refresh_at`. Every later caller takes `with _MINTING:` at line 114 and waits out the join at line 165.
  - Paid on every new connection: `caos/api/deps.py:78` (one per request, unpooled), `caos/api/health.py:109,177`, `caos/graph/worker.py:459`, `caos/graph/checkpoint.py:64`.
- **Verified:** yes, with `uv run python docs/rebuild/round4/probes/store/probe_mint.py` (MINT_SECONDS 2 s, FAILURE_SECONDS 1 s, `_mint` hangs):
  ```
  waited  1.90s -> live-token   (five waiters)
  seconds left on the held token when they were blocked: 3598
  callers over 9 s: 36, blocked >= 0.5 s: 18, longest wait 2.01s (MINT_SECONDS=2.0)
  abandoned mint helper threads still alive: 4
  ```
- **Failure:**
  - The held credential passes `refresh_at` (14 min) while the token endpoint hangs.
  - Every API request, both health probes, the worker's reconnect and the checkpoint pool block for up to 30 s. They then get the live token the server would have accepted all along.
  - After FAILURE_SECONDS the next caller mints again. At production numbers, new connections are stalled for 30 s out of every 35 s, and the 5 s health probe fails.
  - Meanwhile a credential valid for about 45 more minutes sits in memory.
  - F88/DL-4 ("a held token is reused … when a fresh one cannot be had") holds only for the caller that mints.
- **Fix:** when `held.expires_at > now`, call `_MINTING.acquire(blocking=False)`. The caller that gets the lock mints; every other caller returns `held.token` at once. Block only when there is no live token. Test: with a hung mint and a live cache, five concurrent callers return within 0.1 s.

### ST-2 [WARNING] A refused credential is dropped by the worker and the checkpoint pool, but not by the API or the health probes
- **Where:**
  - `caos/api/deps.py:77-82`: `except OperationalError: conn = None`, with no `note_connect_failure`.
  - `caos/api/health.py:112-114, 180-182`, and the lifespan's connect at `caos/api/app.py:400`.
  - Compare `caos/store/lakebase.py:95-105`, whose only two callers are `caos/graph/worker.py:315` and `caos/graph/checkpoint.py:63-67`.
- **Verified:** yes, with `probe_refused_credential.py` (PG* pointed at the local server; the cached made-up token is one the server refuses):
  ```
  API request 1: STORE_UNAVAILABLE; cached token now: revoked-token; mints so far: 0
  API request 3: STORE_UNAVAILABLE; cached token now: revoked-token; mints so far: 0
  health probe_store: STORE_UNAVAILABLE; cached token now: revoked-token
  health probe_workers: STORE_UNAVAILABLE; cached token now: revoked-token
  checkpoint pool connect: OperationalError; cached token now: None
  next API request: STORE_UNAVAILABLE; mints so far: 1
  ```
- **Failure:**
  - A credential is revoked or rotated early (the AR-02 case).
  - The API and health refuse STORE_UNAVAILABLE with the dead credential for up to 14 min. That ends only if the worker or the checkpoint pool opens a connection first, and the in-process worker keeps one long session, so it doesn't.
  - F86's "any connection failure drops the cached credential" holds on two of the five connection paths, and not on the busiest one.
- **Fix:** call `note_connect_failure` inside `caos.store.connect` when it catches `OperationalError`. Test: after one refused API connect, `_CACHED` is None.

### ST-3 [NOTE] Credential cache expiry handling
- **Where:** `caos/store/lakebase.py`:
  - 112-113: the fast path checks only `refresh_at`.
  - 148: `refresh_at` is set without `expires_at`.
  - 199: reads `expiration_time`, but the autoscaling `postgres.DatabaseCredential` names it `expire_time` (a protobuf `Timestamp`).
  - 121-123: the fallback uses the snapshot taken before the mint.
- **Verified:** yes, with `probe_mint.py` parts B, D and E:
  ```
  E: server says it lives 3600s, the cache gives it 840s (= TOKEN_SECONDS 840)
  B: now - expires_at = +0.50s (expired) ... second: short-lived-token mints: 1
     a token stated to expire in 5 min: ... handed out for 600s past its stated expiry
  D: cache after the refusal was noted: None / the minting caller was handed: 'refused-by-the-server'
  ```
- **Failure:**
  - A credential stated to live under 15 min (the autoscaling TTL can be 300 s; clock skew has the same effect) is used up to 10 min past its stated expiry.
  - On the autoscaling branch the DL-4 fallback can never apply. N13 defers that deploy path, not this code.
  - A credential that another path just reported as refused is returned to the caller whose mint then fails.
- **Fix:**
  - Set `refresh_at = min(minted + TOKEN_SECONDS, expires_at)`.
  - Read `expire_time.ToDatetime()` for the autoscaling form.
  - After a failed mint, fall back to a fresh read of the cache.
  - Test: the three probe parts.

### ST-4 [WARNING] Checkpoint set-up waits with no deadline on any older snapshot, before uvicorn binds; a process that gives up never gets a worker
- **Where:**
  - `caos/graph/checkpoint.py:79-102`: no statement or lock timeout around `saver.setup()`, whose migrations run `CREATE INDEX CONCURRENTLY` (langgraph `postgres/base.py:82-88`).
  - Reached through `caos/graph/worker.py:413-422`, inside `start_in_process` (482-502), which `caos/serve.py:68` calls before `uvicorn.run`.
  - `worker.py:490-497` returns None on failure, and nothing retries it.
  - `databricks.yml:27-29` defaults the database to the instance's shared `databricks_postgres`.
- **Verified:** yes, with `probe_setup_lock.py` part C (SETUP_LOCK_SECONDS 3 s; one REPEATABLE READ session open in the same fresh database):
  ```
  second process after 5.1s: STORE_UNAVAILABLE
  first process after 20.1s: still inside checkpointer()
  the first process's statement: [('Lock', 'virtualxid', '\n    CREATE INDEX CONCURRENTLY IF NOT EXISTS checkpoints_thr'), ...]
  advisory lock held meanwhile: 1
  after the reader ended: first process ['ok'] at 20.2s
  ```
- **Failure:**
  - At first boot (or the first boot after a LangGraph index migration), any snapshot-holding session or long statement in the same database blocks set-up indefinitely: a backup, a BI or federation query, an analyst.
  - The first process hangs holding the lock and never binds its port, so the deploy fails.
  - The other processes give up after 120 s and serve with no worker for their whole life.
  - R3-1 fixed the deadlock; this wait sits outside the lock.
- **Fix:**
  - Put a statement and lock timeout on the set-up session, and refuse with a typed code when it trips.
  - Build the checkpointer inside the worker thread under its back-off, so boot never blocks and a failed set-up is retried.
  - Consider a plain index build on empty tables.
  - Test: part C as a test.

### ST-5 [WARNING] `_forget` deletes the checkpoint thread of the worker that now holds the run
- **Where:**
  - `caos/graph/worker.py:226-262`: `_refused` answers True after `_settle(stop)` at 261-262, whatever `stop` did. `stop` is fenced and does nothing for a lost lease (`caos/store/work.py:177-189`).
  - The same shape in the Exception branch, at 210-211.
  - The unconditional delete at 215-223.
  - The trigger: NODE_ALREADY_ACCEPTED from `check_attempt` (`outcomes.py:117-119`), which `record_refusal` drops without asking for the lease (`outcomes.py:276-277`).
- **Verified:** yes, with `pytest --no-cov -p no:cacheprovider -s docs/rebuild/round4/probes/store/probe_forget_other_holder.py`:
  ```
  A's lease while it called CP-0:        ('CLAIMED', 1, 'worker-a')
  B's lease when B paused at CP-L10:      ('CLAIMED', 2, 'worker-b')
  thread rows (B's position) before A:    6
  run_work after A (B still holds it):    ('CLAIMED', 2, 'worker-b')
  thread rows after A's _forget:          0
  run status after C:                     COMPLETE
  ```
- **Failure:**
  - A's lease runs out during its call. B claims the run, calls CP-0 itself, has it accepted, and moves on.
  - A's answer comes back: billed, refused NODE_ALREADY_ACCEPTED, and its `stop` fenced out. `_refused` still answers True, so A deletes the thread B is driving under lease 2.
  - That is a D3 fence bypass on the checkpoint store.
  - The ledger stays right: C re-derived the position and completed. So this is not CRITICAL.
- **Fix:** have `_settle` return the write's bool. `_refused` should answer True, and the Exception branch should forget, only when this worker's `stop` or `cancel_run` actually moved the row. Test: the probe, asserting B's rows survive.

### ST-6 [WARNING] A cancel acknowledged during a Blocked last call is lost; the run ends BLOCKED
- **Where:**
  - `caos/store/runs.py:461-467`: the AR-13 refusal fires only when moving to COMPLETE.
  - Reached from `caos/graph/runtime.py:635` (`_end_blocked`), from `_terminal_move` when `finish()` decides BLOCKED, and from the replayed-BLOCKED branch of `_settle`.
- **Verified:** yes, with `probe_cancel_and_ratelimit.py::test_1`:
  ```
  cancel acknowledged during CP-5's call: [True]
  run status afterwards: BLOCKED; work row: ('DONE', None, None, True)
  last events: [('RUN_BLOCKED',), ('CALL_OUTCOME_RECORDED',)]; cancel_requested_at set: (True,)
  ```
- **Failure:**
  - The user's cancel is acknowledged, then the run ends BLOCKED.
  - BLOCKED is a recoverable status that a successor run may answer (§72), so the cancel is ignored.
  - AR-13 fixed exactly this for COMPLETE only.
- **Fix:** refuse RUN_CANCEL_REQUESTED at any move by the holder other than CANCELLED. Test: test_1 asserting CANCELLED.

### ST-7 [WARNING] The 429 back-off re-sends a paid request after a cancel, after SIGTERM, and after lease loss
- **Where:**
  - `caos/models.py:148-165`, with the sleep at line 157. `ChatCompletions` holds no connection, lease, cancel flag or stop event.
  - `caos/graph/worker.py:101-119`: `_Stoppable` looks at `stopping` only in `check_context`.
- **Verified:** yes, with `probe_cancel_and_ratelimit.py::test_2`:
  ```
  cancel recorded: True
  slept 3.0s; stopping set: True
  chat calls in all: 2 (the second one after the cancel)
  artifacts accepted: 1
  charges billed: 1
  ```
- **Failure:**
  - During the Retry-After wait (up to 20 s), the user's cancel is acknowledged, or SIGTERM sets `stopping`, or the lease is lost.
  - After the wait a new paid call is sent anyway, then billed and accepted.
  - Under SIGTERM that new call outlives the 12 s join, so the process dies mid-call and the answer is lost.
  - Invariant 8 holds (the retry rides the existing reservation). The cancel and the stop do not.
- **Fix:**
  - Pass a `proceed()` check into `complete`, or move the retry into `execute_handoff`.
  - Before each re-send, re-check `stopping`, `_lease_seen` and `cancel_requested_at`, and refuse with a typed code instead.
  - Test: test_2 asserting one call.

### ST-8 [WARNING] Untyped exceptions escape `ChatCompletions.complete`
- **Where:**
  - `caos/models.py:233-241`: NaN survives `min(max(...))`, and `time.sleep(nan)` raises ValueError inside the handler at 151-158, where the sibling `except` at line 160 cannot catch it.
  - Line 160 catches only `OSError`, `ValueError`, `RuntimeError` and `LangChainException` from `invoke`, so `IndexError` from `ChatDatabricks` escapes.
- **Verified:** yes, with `probe_cancel_and_ratelimit.py::test_3`, and `probe_count.py` part D (real `ChatDatabricks` against `tests/workspace_stub.py`):
  ```
  ChatCompletions.complete raised ValueError (untyped) on Retry-After: nan
  stderr: 'ValueError at .../caos/models.py:157'; work row: ('STOPPED', 'INTERNAL_FAULT', None, True)
  choices: []   via ChatDatabricks (1 gateway call): raised IndexError out of complete()
  ```
- **Failure:**
  - A NaN Retry-After turns a transient rate limit into an INTERNAL_FAULT stop.
  - A delivered, billed answer with empty `choices` escapes before `record_outcome`. There is no call outcome, the run is parked INTERNAL_FAULT, and the requeue pays again.
- **Fix:**
  - Treat a non-finite Retry-After as the default wait.
  - Once the request may have been sent, catch any `Exception` and answer PROVIDER_UNAVAILABLE.
  - Test: both inputs.

### ST-9 [WARNING] One attempt can hold its call past the 600 s lease and the 300 s stale threshold; the tests ignore it
- **Where:**
  - `caos/models.py:61-66` (3 tries, 20 s cap) and `caos/provider.py:26-30` (240 s).
  - `models.py:99-108`: the 240 s goes to the OpenAI client as httpx's per-operation timeout.
  - `caos/store/work.py:29` (600 s) and 267 (300 s); the worker beats only at node start (`runtime.py:178`).
  - The tests: `tests/test_worker.py:354-357` and `tests/test_worker_heartbeat.py:114-116`.
- **Verified:** yes, with `probe_cancel_and_ratelimit.py::test_4` and `probe_timeout_is_per_read.py`:
  ```
  tries=3 timeout=240.0s cap=20.0s -> one complete() held 760s against LEASE_SECONDS=600
  client timeout=2.0s, server dripped for ~7.5s: answered (stop) after 7.6s
  ```
- **Failure:**
  - One attempt can hold its call for 760 s past the last lease renewal. Any byte drip under 240 s keeps it open with no limit, because 240 s bounds each read, not the call.
  - The lease expires mid-call, a second worker pays for the node again, and ST-5 follows.
  - Health reports WORKERS_STALE for a worker that is working, which brings back AR-24.
  - Both tests check against a single try and prove nothing about this worst case.
- **Fix:** one monotonic deadline for the whole of `complete()`, and a total deadline on the call (or streaming with an idle deadline, N14). Assert the lease and stale thresholds against that computed worst case.

### ST-10 [WARNING] An exhausted rate limit keeps its reservation and parks the run
- **Where:**
  - `caos/models.py:156-159`: after the last 429, it maps through TRANSIENT to PROVIDER_UNAVAILABLE.
  - `caos/provider.py:40-42`, `caos/store/budget.py:19-23`, and the stop at `caos/graph/worker.py:261`.
- **Verified:** yes, with `probe_cancel_and_ratelimit.py::test_5`:
  ```
  episode 1: gateway calls 3 (all 429); work row ('STOPPED', 'PROVIDER_UNAVAILABLE', None, True); remaining 4.90000000000000000 of ceiling 5.00
  episode 2: gateway calls 3 (all 429); work row ('STOPPED', 'PROVIDER_UNAVAILABLE', None, True); remaining 4.80000000000000000 of ceiling 5.00
  ```
- **Failure:**
  - The code's own premise is that a 429 reached no model. Yet after the third one, the reservation is held for good and the run is parked.
  - The gateway limits per minute, and the wait is 2 s when no Retry-After is sent.
  - Each episode therefore costs one priced request (about 1.6–6.9 at the default price) with no model reached, until BUDGET_CEILING_REACHED.
  - F94 made DP-5 rarer, not gone.
- **Fix:** record the final 429 as a known zero, count a known charge in `_remaining` rather than `greatest(...)`, and release the run with back-off instead of parking it. Test: test_5.

### ST-11 [WARNING] Usage accounting records guessed or impossible charges as known money
- **Where:**
  - `caos/models.py:204-226`, and 69-71 (`Context(prec=60)`, Inexact not trapped).
  - `databricks_langchain/chat_models.py:651-652, 678-679`, where `completion_tokens or 0` supplies the zero.
- **Verified:** yes, with `probe_count.py`:
  ```
  completion_tokens: null    via ChatDatabricks (1 gateway call): refusal None, charge 0.000020
  completion_tokens absent   via ChatDatabricks (1 gateway call): refusal None, charge 0.000020
  output_tokens=1000000000: charge 25000.005000 vs the reservation for a 4 KiB request 1.658880
  traps Inexact: False; precision 60 / charged == exact: False; exact has 65 digits, the charge 60
  _count(10**100) -> 10**100
  ```
- **Failure:**
  - A null or missing output count is billed as zero, so the ledger under-records spend, and AR-14's refusal never sees it.
  - An impossible count is billed as stated: 25,000 against a 1.66 reservation, written into the immutable ledger.
  - The charge is rounded silently, although `caos/provider.py` says "never a guess".
- **Fix:**
  - Refuse zero output tokens for non-empty content.
  - Bound the counts by the request (`MAX_COMPLETION_TOKENS` and the request's bytes).
  - Compute the charge in pricing's exact context.
  - Test: the probe's inputs.

### ST-12 [WARNING] A transient store fault at the billing write loses a paid answer, and the node is paid for again
- **Where:**
  - `caos/methodology/canonical.py:220-236`: `record_outcome` is tried once.
  - `caos/graph/worker.py:258-260` releases the run.
  - `replay_billed` and `unexplained_charge` both need the outcome row that was never written.
- **Verified:** yes, with `probe_lost_bill.py`:
  ```
  first claim raised STORE_UNAVAILABLE; provider calls 1
    work row ('QUEUED', None, None, True); attempts 1, reservations 1, call outcomes 0, charges 0
  second claim: provider calls 4 (2 of them for CP-0); attempts 4, reservations 4, charges 3
  ```
- **Failure:** a failover lands between the call and its one billing write. The next claim pays for CP-0 again, which bypasses D7 ("never paid for again") and the operator decision that `unexplained_charge` is meant to require. The budget holds.
- **Fix:** retry `record_outcome` (an exact replay is already a no-op) on a fresh connection, bounded, within the lease. Test: the probe asserting one CP-0 call.

### ST-13 [WARNING] The non-Lakebase checkpointer never reconnects
- **Where:** `caos/graph/checkpoint.py:113-124` holds one connection for the life of the process. `caos/graph/worker.py:196-198` releases the run and 335-336 reopens only the store connection.
- **Verified:** yes, with `probe_local_saver_reconnect.py`:
  ```
  claim 1: raised STORE_UNAVAILABLE; work row ('QUEUED', None, None, True); saver connection closed: True
  claim 2: raised STORE_UNAVAILABLE; ...  claim 3: raised STORE_UNAVAILABLE; ...
  ```
- **Failure:** with `CAOS_DATABASE_URL` (local, CI, any non-Lakebase Postgres), one ended session makes every later claim fail and requeue at the head, forever. The platform's pooled path is not affected.
- **Fix:** use a small pool with `check=` on the local path too. Test: the probe asserting the second claim progresses.

### ST-14 [NOTE] The serializer is not "exactly RunState", and exception text reaches Lakebase
- **Where:**
  - `caos/graph/checkpoint.py:14-17, 48-49, 70-72`.
  - LangGraph writes `repr(exc)` into `caos_graph.checkpoint_writes`.
  - The thread is kept on the release and store-fault paths: `worker.py:194-198, 258-260`.
- **Verified:** yes, with `probe_serializer.py`:
  ```
  __error__ write persisted: 'ValueError("EBITDA of USD 1,240.0m per page 3 of the borrower\'s accounts")'
  msgpack ctor os.system -> str: 'true' / safe re.compile -> Pattern / safe langgraph Command -> Command
  json lc:1 PromptTemplate -> langchain_core.prompts.prompt.PromptTemplate
  ```
- **Failure:**
  - A crafted row still makes the loader construct LangGraph's safe types, and langchain_core objects through `json` rows. Types outside the list come back as raw data rather than being refused.
  - Document text in exception messages is persisted, despite the worker's promise that the message "is never written".
- **Fix:**
  - A serializer that raises for anything outside the allowlist and refuses `json` rows.
  - Re-raise message-free exceptions from nodes.

### ST-15 [NOTE] The drain runs twice under SIGINT, and two docstrings are wrong
- **Where:** `caos/serve.py:78-89`, `caos/graph/worker.py:8-11`, `caos/provider.py:27-28` (which says "300 s lease"; the lease is 600 s).
- **Verified:** yes, with `probe_drain_signals.py`:
  ```
  SIGTERM   drains=1 exit=-15 / SIGINT drains=2 exit=0 / SIGINT x2 drains=2 / SIGTERM x2 drains=1
  ```
- **Failure:**
  - SIGTERM drains once, so DP-4 holds.
  - SIGINT joins a worker that is mid-call twice (24 s at production settings).
  - worker.py claims SIGTERM lets the call in flight be billed. With a 12 s join against a 240 s call, it is abandoned, as serve.py itself says.
- **Fix:** an idempotent drain, or drop the `finally`; correct the two docstrings.

## What held up
- **F84 serializer:** every value the graph writes round-trips, including a resume after a failed node, and crafted callables stay inert.
- **R3-1 lock:** four concurrent set-ups succeed on both the local and the pooled path in 0.7 s, and a failing set-up releases the lock.
- **Terminal moves:** exactly once, never backwards. AR-13 works for COMPLETE, and a cancel on a QUEUED or STOPPED run ends it in one unit.
- **Ledger fencing by token:** holds end to end.
- **Invariant 8:** the only model path besides the smoke re-checks a reservation priced on the rebuilt request.
- **Invariant 7:** no float touches money, and `_count` refuses negative, bool, float, str, None and Decimal values.
- **Mint failures:** a failed mint poisons callers only for FAILURE_SECONDS, and waiters never wait longer than MINT_SECONDS.
- **Route length:** the longest route (21 nodes) is within LangGraph's step limit.

## Not covered
- The other store modules (`commands`, `gates`, `members`, `routes`, `run_inputs`, `source_sets`, `audit`, `extraction_integrity`) and most migrations.
- Real platform behaviour: token lifetimes, whether the gateway sends Retry-After, real usage shapes, the Apps grace period. `tests/test_platform_boot.py` was not run.
- Not forced: a pooled connection keeping a leaked session lock after a failed unlock; `connect()` with no `connect_timeout` against a blackholed host; PID-based worker ids colliding across containers.
- One observation: `tests/test_models.py::test_the_chat_model_carries_the_socket_deadline_and_never_retries` takes 304 s. Its unbounded `WorkspaceClient`, pointed at a closed port, runs down the SDK's 5-minute retry budget.
