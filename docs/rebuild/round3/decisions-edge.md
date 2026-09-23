# Adversarial-review findings patched in the API edge

One paragraph per finding: `ID — STATUS — what changed (files) — test name / reason`.

MX-2 / AS-3 / TM-4 — FIXED — Event-stream slots are now budgeted per actor as well as
globally. `caos/api/stream.py` gains `ACTOR_STREAM_LIMIT = 4` and a `held: dict[UUID, int]`
on `_Slots`; `take_stream_slot` takes a keyword `actor_id` and refuses the same
`STREAM_LIMIT_REACHED` when that actor already holds its share, and `StreamSlot.release`
gives the per-actor count back and drops the row at zero so the map is bounded by the tails
that are open rather than by how many people have ever watched. `caos/api/app.py`'s
`read_case_events` passes `actor_id=actor.user_id`. Both caps answer with the one code on
purpose: to the refused watcher they are the same fact, and a code that told them apart
would tell a caller how much of the fleet they had taken. Tests:
`tests/test_stream_slots.py::test_one_actor_cannot_take_every_tail_while_another_waits`,
`::test_the_global_cap_still_refuses_before_any_actor_reaches_their_share`,
`::test_a_released_tail_leaves_no_row_behind_for_its_actor`,
`::test_the_route_names_the_actor_it_takes_the_slot_for`.

AS-6 — FIXED (with a recorded residual) — The `EdgeGuard` exception handler now calls
`_logged(fault)` before it re-raises, which writes only `f"{type(fault).__name__} at
{file}:{line}"` to stderr — the exact pair `caos/graph/worker.py:198-200` writes, and never
`str(exc)` (`caos/api/edge.py`). The wire body is the unchanged constant `INTERNAL_FAULT`.
Residual: the finding's fix also said "do not re-raise into Starlette's logger", and the
re-raise is kept, so under uvicorn the message still reaches `uvicorn.error`. Removing the
re-raise would fail `tests/test_edge.py::test_an_unhandled_fault_answers_a_secured_constant_500`
(`with pytest.raises(RuntimeError): TestClient(faulty).get(...)`), and the alternative fix — a
logging filter on `uvicorn.error` — belongs in `caos/serve.py`; both files are outside this
engineer's scope. Test:
`tests/test_api_routes.py::test_an_unhandled_fault_is_logged_as_its_class_and_frame_never_its_message`.

CR-7 — FIXED — Both identity cache entries are stamped with a clock read *after* the SCIM
call returns or raises. `actor_from_token` is split (`caos/api/identity.py`): `_looked_up`
calls `_current_user` and then `_deny(key, time.monotonic())` on a refusal or
`_remember(key, actor, time.monotonic())` on success. Read before the call, a workspace that
took longer than `NEGATIVE_SECONDS` to refuse a revoked token wrote an entry that had already
expired, so every retry paid the same slow round trip. Test:
`tests/test_identity_platform.py::test_a_refused_token_is_stamped_after_the_workspace_answers`
(a 0.3 s refusal against a 0.2 s window: one round trip for three back-to-back requests).

AR-04 / N7 / EI-N4 — FIXED — `_deny` prunes expired entries and refuses to grow `_NEGATIVE`
past `CACHE_CAPACITY`, under `_CACHE_LOCK`, on every insertion (`caos/api/identity.py`).
Previously the negative cache was swept only after a *successful* uncached lookup, which a
process being handed one distinct rejected token after another never reaches. Test:
`tests/test_identity_platform.py::test_refused_tokens_are_pruned_and_bounded_as_they_arrive`
(capacity 2 against six refusals, then a zero-length window against six more).

AR-12 — FIXED — `_scim_user` validates every shape before it walks it: the body must be a
JSON object, `groups` must be a list, and every member must be a mapping, each otherwise a
typed `IDENTITY_UNAVAILABLE` (`caos/api/identity.py`). `{"id": "42", "groups": true}` used to
raise `TypeError` out of the comprehension, so an upstream answering nonsense read on the wire
as this host's own `INTERNAL_FAULT`. Test:
`tests/test_identity_platform.py::test_a_malformed_scim_answer_is_a_typed_refusal_not_a_type_error`.

N6 / EI-N3 — FIXED — The `http://` branch is reachable only for `127.0.0.1`, `::1` and
`localhost`. `workspace_address` in `caos/api/identity.py` is the one parser for
`DATABRICKS_HOST`; it returns `None` for any other `http` host (and for credentials embedded
in the URL), which `scim_me` answers `IDENTITY_UNAVAILABLE` and `resolve_mode` answers
`EDGE_CONFIG_INVALID`. No new refusal code was needed. Test:
`tests/test_identity_platform.py::test_a_bearer_is_never_sent_in_clear_to_anything_but_this_machine`.

EI-N2 — FIXED — `resolve_mode`'s platform branch was extracted into `_platform_mode`
(`caos/api/edge.py`) and now validates `DATABRICKS_HOST` through `workspace_address` when it
is set, refusing `EDGE_CONFIG_INVALID` at boot instead of letting `urlsplit(...).port` raise an
untyped `ValueError` on the first request and answer 500. An absent host is left to the
request path, which answers `IDENTITY_UNAVAILABLE`, so a deployment that does not use platform
identity still boots. The extraction also took `resolve_mode` from complexity 15 to 5. Test:
`tests/test_identity_platform.py::test_an_unreachable_workspace_is_refused_at_boot_and_at_the_request`.

EI-W3 — FIXED — SCIM lookups are single-flight per token digest. `_INFLIGHT: dict[str, _Flight]`
holds one `_Flight` (a `threading.Event` plus the actor or refusal code it found) per digest;
`_flight` hands the first caller the lead and every later caller the same object, and `_shared`
waits `SHARED_WAIT_SECONDS` (twice the socket timeout) and returns what the one round trip
found, or `IDENTITY_UNAVAILABLE` if it never settled (`caos/api/identity.py`). The per-operation
`SCIM_TIMEOUT_SECONDS` is unchanged. Tests:
`tests/test_identity_platform.py::test_requests_arriving_together_for_one_cold_token_make_one_round_trip`
(eight threads, one call) and `::test_a_refusal_shared_by_a_burst_is_the_workspace_s_own_refusal`.

EI-W4 / AR-11 — FIXED — The health `inflight` gate is now bounded in time as well as in count.
`ProbeState` gains `inflight_since` and `inflight_ceiling` (module constant
`INFLIGHT_CEILING = PROBE_DEADLINE * 2`), `_blocked` holds a round back only while the oldest
in-flight probe is younger than the ceiling, and `probe_once` forgets a count still raised past
it so the gate holds again for the new round (`caos/api/health.py`). A job the executor never
started — `wait_for` cancelled it while it was still queued — never runs its own accounting, and
one such cancellation used to close the gate for the life of the process. Test:
`tests/test_health.py::test_a_probe_the_executor_never_started_does_not_stall_every_round`
(a deliberately occupied one-worker executor; the count stays raised and a later round runs
anyway).

EI-W1 — FIXED — `probe_identity` now goes down `caos.api.identity.scim_me`, the very path a
request takes, carrying the `Authorization` header the SDK mints for this process
(`workspace_client().config.authenticate()`); only the credential still comes from the SDK
(`caos/api/health.py`). `scim_me` was factored out of `_current_user` and takes the whole
header rather than a token, so any scheme the SDK mints works. A host the request parser
rejects, a SCIM path that moved, or a scope the workspace refuses now fails the probe instead of
leaving health `ready` while every request answered 401. Test:
`tests/test_health.py::test_the_identity_probe_asks_the_workspace_the_way_a_request_asks_it`.

EI-W5 — FIXED — The untested SCIM mapping and the F45 edge branches are covered. A stand-in
workspace over `http.client` drives 401/403 → `NOT_AUTHENTICATED`, 404/429/500/503 →
`IDENTITY_UNAVAILABLE`, an oversized body, `OSError` and `HTTPException`, the socket being
closed on every way out, the HTTPS branch and the header passed through
(`tests/test_identity_platform.py::test_the_status_the_workspace_answers_decides_the_refusal`,
`::test_a_workspace_is_asked_over_tls_and_the_header_is_passed_through`). Bad JSON and pruning
are covered by the AR-12 and AR-04 tests above. `edge.py`'s `_origin_allowed` doubled-header
branch and `_names_host`'s "not one host" and `ValueError` branches are covered by
`::test_the_origin_rules_refuse_a_doubled_or_unparsable_header`.

EI-W6 — FIXED — Dead documentation references replaced. `caos/api/edge.py`, `caos/api/identity.py`
and `caos/api/health.py` now cite `docs/rebuild/2026-09-22-caos-databricks-spec.md` and
`docs/rebuild/decisions.md` in place of `docs/DECISIONS.md`, `docs/COMPLETION_PLAN.md`,
`SYSTEM_SPEC.md` and "CLAUDE.md's ledger". Docstrings only; no behaviour. Covered by the
existing suites for each module.

EI-N5 / EI-N6 — FIXED — `_rewritten`'s `platform=` parameter is now `edged=`, because the caller
passes True behind the platform, in edge mode *and* under a configuration that would not
resolve (`caos/api/edge.py`); `edge.PLATFORM_ENV` is re-exported from `caos/api/identity.py`
rather than spelled twice, so the mode the guard decides and the mode identity decides cannot
become two variables. The identity module docstring no longer claims "the group list is the
*only* thing this reads in production", and the `IO_BUDGET` comment now says it counts store
round trips and that platform mode makes one SCIM call. Tests:
`tests/test_identity_platform.py::test_a_platform_request_from_any_peer_reaches_the_api_without_forged_headers`
(the renamed keyword) and the existing platform-mode suite.

EI-W2 — FIXED (minimally) — Edge mode no longer hard-codes `caos-admins`. `_GROUPS` and
`_platform_role` were replaced by one `role_from_groups(groups)` that reads `CAOS_GROUP_ADMIN`
and `CAOS_GROUP_ANALYST` (defaults `GROUP_ADMIN_DEFAULT` / `GROUP_ANALYST_DEFAULT`) and is
called from both `_from_groups` (edge mode) and `_looked_up` (platform mode)
(`caos/api/identity.py`). The configured group now grants in both modes and the literal grants
nothing when a name is configured. Test:
`tests/test_identity_platform.py::test_the_configured_group_names_are_read_in_every_mode`.

SI-2 / EI-N7 — DEFERRED — Removing the HMAC edge-assertion mode fans out well past
`edge.py`, `identity.py`, `tests/test_edge_assertion.py` and a few fixture lines, which is the
condition the brief set for doing it here. Measured: `tests/test_edge.py` (459 lines, 22
references — the whole dev-mode/edge-mode split is built on signed assertions),
`tests/test_actor_matrix.py` (11 references including three whole test functions and a
7-case parametrisation), `tests/test_edge_assertion.py` (342 lines), plus
`tests/test_command_availability.py:279`, `tests/test_frontend_modes.py:78,80`,
`tests/conftest.py:72` and `tests/platform_app.py:41`. Four of those test files are outside
this engineer's scope and two carry live test bodies rather than fixture lines. EI-W2 was fixed
minimally instead (above), which removes the security consequence — the hard-coded group — and
leaves the dead mode itself for one owner of all eight files. EI-N7 (`NonceRegister.admit`'s
O(n) sweep) is deferred with it: it is reachable only from that mode.

EI-N1 — NOTED, no code change — The 300 s actor cache keeps a role after the group membership
or the token is revoked, and there is no way to invalidate one entry. F13 accepted the TTL; the
consequence is now written beside `CACHE_SECONDS` in `caos/api/identity.py` so the next reader
finds it. Changing it would trade one SCIM call per token per five minutes for one per request,
which is the cost F43 exists to avoid.

EI-N8 — NOTED, no code change — `/api/health` being unauthenticated and carrying
`python_version` and `build_id` is what spec §3.1 asks the health document to report, and the
route is what a load balancer reads before any identity exists.

EI-N9 — NOTED, no code change — Platform mode trusting that only the Apps proxy reaches the
port is the platform's boundary, not this process's; CAN_USE (F50) is enforced there. Nothing
in this repository can verify or replace that isolation.

AR-24 — FIXED — `WORKER_STALE_AFTER` in `caos/store/work.py` goes from 30.0 to 300.0, which is
`caos.provider.TIMEOUT_SECONDS` (240 s after the concurrent raise from 120) plus a minute of
margin. A worker beats once per node and never during the node's model call, so at 30 s every
call longer than half a minute reported `WORKERS_STALE` for a worker doing exactly what it
exists to do, while its run's lease — the real liveness — stayed held. A literal with the rule
named in the comment rather than an import, so the store does not depend on the provider seam.
`tests/test_health.py` needed no change (its worker cases use substituted probes); the store
tests already used the symbol. Test:
`tests/test_worker_heartbeat.py::test_the_staleness_threshold_covers_one_whole_provider_call`
asserts `WORKER_STALE_AFTER >= TIMEOUT_SECONDS + 60`, so raising the provider deadline again
cannot silently uncover the defect.
