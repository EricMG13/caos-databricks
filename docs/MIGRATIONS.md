# Migration and recovery procedure

The declared version is always `len(server.store.MIGRATIONS)`; the registry is
the authority, so this procedure does not copy a count that can become stale.
`server/store/schema.sql` is immutable migration `0001_legacy`; its original
bytes remain unchanged. Add the next reviewed SQL file under `server/store/`
and append its stable name and UTF-8 body to `MIGRATIONS`. Do not edit, reorder,
remove, or rename applied migrations. The image copies this directory and its
runtime user only needs read access. SQL must be transactional: no COMMIT,
ROLLBACK, concurrent-index operations, or external effects.

Before upgrade, stop writers and take a consistent PostgreSQL custom-format
backup plus a copy of the matching blob root. Keep both together: database rows
reference blob SHA-256 addresses, and a database-only backup cannot recover them.
Use `pg_dump --format=custom --no-owner --no-acl --dbname "$BACKUP_URL"` with
credentials supplied securely by the operator, writing to a restricted backup
file. Record the application revision and migration history with the backup.
For a live installation, protect the backup as production data.

Start the upgraded host against its intended database; API startup calls
`apply_schema` on a fresh transactional connection before accepting requests.
Only a matching applied prefix can advance. Schema DDL/history/head commit as
one transaction. Repeat startup is a check. Do not call this helper with pending
business writes: it commits its caller transaction, preserving the legacy API.
Autocommit and incompatible history refuse. Diagnose a refusal using the
reviewed migration manifest and backup; never rewrite checksums to bypass it.

Recovery always creates a **new empty database**, then uses
`pg_restore --exit-on-error --single-transaction --no-owner --no-acl
--dbname "$RESTORE_URL" backup.dump`. Restore blobs into a new root, verify all
referenced digests with `BlobStore.get`, compare records/history, and run startup
with the appropriate application revision. Switch the application only after
verification. Never restore over an existing database or use a newer database
with an older application. There is no destructive automatic downgrade.

Concurrency is verified with the existing default **READ COMMITTED** startup
connections. Higher isolation levels and caller-owned transaction policies are
not a supported startup mode; the helper does not pre-commit to change them.

## Allocated ordinals, and two that are dead

**`0022` and `0023` are permanent gaps. Never take them.** Two concurrent
streams were allocating ordinals in September 2026: the audit remediation
reserved `0022` and `0023` for its own tasks, and the completion stream landed
`0024_reservation_price` and `0025_supersedes` before either was written. The
remediation then took `0026_case_members_by_user` and
`0027_evidence_statement_trigger`.

The gaps cannot be filled. `apply_schema` verifies an ordered immutable prefix
and `MIGRATIONS` is indexed by tuple position, so a migration inserted at
`0022` today **applies green on a fresh database** and refuses
`STORE_SCHEMA_DRIFT` only against a deployment that has already advanced past
it. That is the worst failure shape available: it passes in development and
refuses in production.

Take the next ordinal from the tail of `MIGRATIONS` in
`server/store/__init__.py`, never from a plan or a task brief. Several tracked
planning documents still describe the tree as being at `0021` with `0022` and
`0023` held; they were true when written and are not now. This paragraph is the
answer; a document dated before the migration you are about to write is not.

## Executed disposable proof

On 2026-09-12, run from the repository:

```sh
env -u OPENROUTER_API_KEY -u OPENROUTER_MODEL -u OPENROUTER_BASE_URL \
  -u OPENROUTER_PROVIDER -u OPENROUTER_REASONING_EFFORT \
  -u CAOS_REQUIRE_PROVIDER \
  DOCKER_HOST=unix:///Users/ericguei/.colima/default/docker.sock \
  .venv/bin/python tests/probes/migration_restore.py
```

The executable uses the installed Docker CLI and container tools from
`caos-workbench-dev-test-postgres-1`, using the caller's Docker environment
(the local Colima socket in this execution). It connects
only to the test admin at port 55437 and creates two UUID-named databases.
It populates the **legacy** schema with synthetic case, run, source/block,
artifact, route, audit event and billing records, dumps with `pg_dump`, restores
with `pg_restore` into the second newly created database, and upgrades that
restored legacy database to version 1. It compares every business table before
and after, copies the blob root and verifies every source/artifact reference.
This manual proof is separate from ordinary pytest and does not add a Docker
requirement to Python CI.

Result: **PASS**, custom dump 32,051 bytes, rows and referenced blobs intact.
Created and subsequently removed only:

- `caos_restore_3bd972559aee4bba8461451295232ba5`
- `caos_restore_a30a9710c5ae41048052b070b3b3d009`

Temporary synthetic blobs were removed with the probe's temporary directory.
Dev port 55436, existing databases, containers and volumes were untouched.
These deleted synthetic targets can be regenerated by rerunning the proof.

## Version 2 extraction provenance proof — 2026-09-12

`0002_extraction` adds provenance without changing original business columns.
Legacy sources have no provenance row (UNKNOWN), retain readable blocks/tokens,
and require explicit readmission/re-extraction before future executable source
sets can use known provenance. See DECISIONS §33 for the versioned hash format.

The same owned-disposable probe was rerun against version 2 with caller-supplied
Docker configuration. It now populates legacy tokens as well as blocks, snapshots
the explicit original table/column set, preserves every original row and source/
artifact blob reference, and checks UNKNOWN provenance and live evidence reads.
The ordinary PostgreSQL regression also proves fresh/upgraded schema equivalence,
repeat startup, and known admission after legacy upgrade.

Result: **PASS**, custom dump **32,189 bytes**; version **2**; rows/blobs intact.
Created and removed only `caos_restore_d079c3f869124d7e873b31de73b5203b` and
`caos_restore_0b643d0975734a6a8303bb5b24f781ff`. Temporary synthetic blobs were
removed with the probe temporary directory. Existing databases, dev blobs,
containers and volumes were unchanged.

## Version 3 immutable source-set proof — 2026-09-12

`0003_source_sets` adds explicit versions/members and a case/source unique key.
Real PostgreSQL tests compare original named columns, all rows and blobs through
both legacy and Task7a upgrades and repeated startup. Fresh/legacy-upgraded
catalogs match columns, defaults, constraints, indexes, triggers, functions and
views. The existing synthetic migration failure/tail/concurrency proofs remain.

The same owned probe passed: custom dump **32,192 bytes**, restored legacy
database upgraded to version **3**, original rows/blobs intact and legacy
provenance still UNKNOWN. Only `caos_restore_dc2c638667404644816d53d28bb7d6a8`
and `caos_restore_f1317d3de09b4b42a7fa38330be247a7` were created and removed;
temporary synthetic blobs were removed. No development data was changed.

## Version 4 stored route integrity proof — 2026-09-12

`0004_route_integrity` appends native UPDATE/DELETE and TRUNCATE guards to
`run_routes`, including a truncation reached through CASCADE. No original SQL,
column, row or stored route JSON is rewritten. Existing malformed route rows
remain preserved but are refused by the verified reader; the migration does
not guess complete run inputs or repair historical identity.

Real PostgreSQL tests preserve every original named column, row and referenced
blob from legacy and versions 2/3, compare fresh/upgraded native catalogs, and
verify repeat/concurrent application and full native-catalog rollback on failure.
Concurrent populated version-3 startup is covered explicitly.

The executable restore probe now runs two independent scenarios: an original
legacy backup restored and upgraded to version 4, and an already migrated
version-4 backup restored with its native functions/triggers intact. Both compare
the exact native catalog immediately after restore, original rows and source/
artifact blobs, and version-4 migration history after startup. Each scenario
creates and removes only its own two UUID databases and temporary synthetic
blob directories on the dedicated test service at port 55437.

Implementer execution with the command above: **PASS** twice. Legacy dump
**32,199 bytes**, `caos_restore_c746cbaccc984563a64f15799aa99834` restored into
`caos_restore_5fd3499ad60242639286e53fc851c514`; migrated dump **47,349 bytes**,
`caos_restore_01aa990371a84fc1b2c58a41dfcf460b` restored into
`caos_restore_36b3959acb644bf0bc23c8c3d49e7547`. All four owned databases and
temporary blobs were removed; rows/blobs remained intact and legacy provenance
stayed UNKNOWN. No existing development database, blob, service or volume was
changed. The synthetic records can be regenerated by rerunning the probe.

The root independently reran the final source in **0.91s**, also **PASS**:
legacy dump **32,186 bytes** and migrated dump **47,351 bytes**, both version 4
with native catalogs, rows and blobs preserved. Its four separately owned
databases (`caos_restore_20a970c548fd4ea68c10fa0b2f6b4df2`,
`caos_restore_f8798e3b5a024a38841d9c2652032b91`,
`caos_restore_a09b6ddde0e44ce0be5155e16f77fdd7`,
`caos_restore_8e5104a3823447b1b0082bd6fff7e49a`) and temporary synthetic blobs
were removed. This is root-reported independent evidence, separate from the
implementer's execution above; neither used development data.

## Version 5 complete run-input proof — 2026-09-12

`0005_run_inputs` adds one complete immutable input row per run, composite
run/case, source-version/fingerprint and route/digest foreign keys, UPDATE/DELETE/
TRUNCATE guards, and the INPUT_PINNED event name. Existing migration bytes and
all legacy/current-prefix rows remain intact; no complete pins are backfilled.
The populated-prefix upgrade regression now includes version 4 explicitly;
concurrent startup begins from a populated version 4. Fresh and legacy-upgraded
catalog parity, repeat application and native-catalog failure rollback continue
to run against real disposable PostgreSQL. Focused storage/schema: **94 passed
in 11.64s**, before the final route-FK regression update and full backend gates.

The existing owned restore probe was extended to include a second, known source,
captured source version, verified route, complete input and INPUT_PINNED event
in the migrated backup. It compares every original column/row and native catalog
after restore, reads the complete pin through the verified loader, preserves
UNKNOWN legacy provenance, and compares each copied blob with its original
bytes. It uses only UUID-named temporary databases and synthetic blob roots.

Executed with the provider-scrubbed command above against test port 55437:
**PASS** twice, both upgrading/verifying migration version **5**. Legacy dump
**32,193 bytes**, `caos_restore_9d4e71b1c8f6421cb70f42a937a95268` restored into
`caos_restore_35311207fd9f4039b4790cc9b97dfd48`; migrated complete-input dump
**54,694 bytes**, `caos_restore_4c66734eac704e64899b6eaa22b27874` restored into
`caos_restore_47f3896a12c7445c900229dad9d7457e`. All four owned databases and
temporary synthetic blob roots were removed and can be regenerated. Existing
development databases, containers, volumes and blobs were untouched.

## Versions 9 and 10 — accepted owner and blocked runs — 2026-09-13

Version 9 (`0009_accepted_owner`) records each artifact's route node and makes
`(run_id, route_node_id)` unique. A populated database that already holds two
accepted artifacts for one run node cannot satisfy that constraint: the upgrade
rolls back whole and startup refuses `STORE_SCHEMA_DRIFT`, which does not name
the cause. To diagnose, on a restored copy, list the duplicates with
`SELECT a.run_id, t.route_node_id, count(*) FROM artifacts a JOIN run_attempts t
USING (attempt_id) GROUP BY 1, 2 HAVING count(*) > 1`. Which artifact is the
authoritative owner is an analytical decision about that run, not a migration
step; no automatic cleanup exists, and nothing may be deleted from a production
store without its own authorized, backed-up change. Version 10
(`0010_blocked_runs`) only widens two CHECK constraints and cannot refuse
existing rows. The restore probe (`tests/probes/migration_restore.py`) passes in
all three modes at version 10.

## Version 11 — run subject and attempt ordinal — 2026-09-13

Version 11 (`0011_run_subject`) is additive. It adds five nullable columns to
`run_inputs` (`issuer_id`, `issuer_name`, `reporting_period`, `analysis_date`,
`cos_run_id`) and replaces the `format_version = 1` CHECK with one that ties the
columns to the format: version 1 rows hold all five NULL, version 2 rows hold
all five, shape-checked. Nothing is backfilled, so every version-1 row, its
input fingerprint and its gate preview keep their exact bytes, and the
immutability trigger (UPDATE/DELETE/TRUNCATE only) never fires. It also adds
`run_attempts.ordinal` (1–256) with `UNIQUE (run_id, route_node_id, ordinal)`;
attempts written before it keep a NULL ordinal, which no canonical handoff can
name, and later attempts are numbered after them. No existing row can violate
either constraint, so the upgrade cannot refuse a populated store. The restore
probe passes in all three modes at version 11, its prefix-seven mode now
carrying a pre-ordinal attempt and its reservation across restore and upgrade.


## Version 12 — artifact record — 2026-09-13

Version 12 (`0012_artifact_record`) is additive. It adds one nullable column,
`artifacts.record_sha256`, shape-checked as a lowercase SHA-256 address of the
host record blob a canonical handoff is accepted with (`docs/DECISIONS.md`
§41.2). Nothing is backfilled: every artifact accepted before it, and every
artifact of a `claims-json-v1` run, keeps NULL, so no existing row can violate
the CHECK and the upgrade cannot refuse a populated store. The database does
not decide when the column is required; acceptance does, under the run lock,
from the run's pinned adapter (§42.1), and the accept replay compares it with
the other stored facts. Readers that refuse a NULL record arrive with slice
f-1. The restore probe carries only claims-route artifacts, whose record stays
NULL across restore and upgrade.

## Version 13 — run work, lease tokens and attempt refusals — 2026-09-14

Version 13 (`0013_run_work`) is additive. It creates two empty tables --
`run_work`, one row per enqueued run with its state, fencing `lease_token`,
lease and cancel request, and `attempt_refusals`, write-once (triggers refuse
UPDATE, DELETE and TRUNCATE) -- adds a nullable `run_attempts.lease_token`,
and widens the `runs` status and `run_events` name CHECKs to admit
`CANCELLED`/`RUN_CANCELLED` (`docs/DECISIONS.md` §49). Existing attempts keep
NULL and existing rows satisfy the wider CHECKs, so the upgrade cannot refuse a
populated store; `test_version_thirteen_adds_empty_work_and_keeps_attempts_unleased`
advances a version-12 store and proves it.

## Version 14 — command receipts — 2026-09-14

Version 14 (`0014_command_requests`) is additive. It creates one empty table,
`command_requests`, keyed by `(actor_id, scope, idempotency_key)`, with CHECKs
on the command name, the lowercase SHA-256 `request_sha256`, a success status
(200, 201 or 202) and a receipt of at most 65,536 bytes, and two triggers that
refuse UPDATE, DELETE and TRUNCATE (`docs/DECISIONS.md` §51.3). No existing
table is altered and nothing is backfilled, so the upgrade cannot refuse a
populated store; `test_version_fourteen_adds_empty_command_requests_to_a_populated_store`
advances a version-13 store and finds the table empty. Rows are written only
by a committed command and no code path removes one.

## Version 15 — immutable saved revisions — 2026-09-14

`0015_revisions` adds immutable host-UUID revision metadata. Payload bytes live
in the blob store and must be backed up together with these rows. Composite
case/revision foreign keys on new opinions and publications reference a
generated canonical text form of the UUID. They are `NOT VALID`: old text-label
history stays readable without fabricated saved payloads; new writes must name
a saved revision of the same case. The populated version-14 migration test
preserves a legacy signature and refuses a new detached signature.

## Versions 16 and 17 — filing receipts and the sealed legacy boundary — 2026-09-15

`0016_filed_receipts` adds immutable exact receipts for every new filed
deliverable. It deliberately backfills nothing: earlier digest-only filings
remain historical and cannot be represented as newly created receipt bytes.

`0017_legacy_filing_events` snapshots every receiptless `DELIVERABLE_FILED`
hash only when it follows `0016` in the same atomic upgrade from a pre-0016
prefix. It seals that set with foreign-key and no-mutation guards, and makes
audit events update/delete/truncate immutable. A store already at version 16
that contains any receiptless filing refuses version 17 as ambiguous: an
operator must recover or validate it rather than silently blessing a missing
current receipt. Readers trust the sealed set, never a live event timestamp,
so a post-cutover receipt cannot be bypassed by backdating. The receipt
migration regressions prove both legacy preservation and the ambiguous-prefix
refusal.

## Versions 18–20 — qualification evidence, performed snapshots and one current verdict

`0018_qualification_verdicts` adds global immutable qualification evidence and
authenticated reviewer verdicts. Qualification sets can span cases, so these
rows deliberately do not use the case-scoped governed-write tables. Migration
19 makes one evidence identity resolve to exactly one reviewer decision; a
reader cannot select a convenient verdict by row order. Migration 20 adds the
immutable performed snapshot that supplies the evidence digest and binds its
set, build, adapter, provider and model identities. New evidence rows refuse
unless that exact snapshot already exists; a detached performed hash cannot be
reviewed or shown as qualified. Partial snapshots remain auditable but cannot
receive or read as a current verdict.
Migration 20 deliberately does not backfill old evidence: rows without a
snapshot remain audit history but cannot read as qualified.

The owned restore probe now writes one synthetic current verdict over exact set,
performed, build, adapter, provider, and model identities into its current
backup. After restoring into a newly created database and copied blob root, it
reads that same verdict through `current_verdict` at the recorded clock. This
proves migration history, immutable qualification rows, and the current-reader
binding survive the same-revision restore; it does not perform a provider call.
