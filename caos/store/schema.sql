-- The declared schema. Applied in full at startup (docs/REBUILD_PLAN.md Phase 1).
--
-- A table arrives here in the phase that first writes it; the tables of phases
-- not yet reached are not here (SYSTEM_SPEC.md section 2). Phase 1 writes a case
-- and the run that belongs to it.
--
-- Every statement in this file is applied once, as one transaction, against a
-- database no schema has been applied to. There is no `IF NOT EXISTS` here on
-- purpose: re-applying is not how this schema changes, and a statement that
-- silently does nothing is how a missing column reaches production. The digest
-- of this text is what server/store/__init__.py records and re-checks.

CREATE TABLE cases (
    case_id    uuid PRIMARY KEY,
    title      text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE runs (
    run_id     uuid PRIMARY KEY,
    case_id    uuid NOT NULL REFERENCES cases (case_id),
    status     text NOT NULL,
    -- Invariant 8's number. A run without a ceiling is the invariant with the
    -- figure left out, so every run carries one from the moment it starts.
    budget_ceiling numeric NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    -- The set is closed in the database as well as in RunStatus: a status the
    -- host does not know is a status no reader can act on.
    CONSTRAINT runs_status_is_known CHECK (status IN ('RUNNING', 'COMPLETE', 'FAILED'))
);

CREATE INDEX runs_by_case ON runs (case_id);

-- One row per node per try. Append-only (SYSTEM_SPEC.md section 2), which is why
-- acceptance is not a column here: an accepted attempt is one that has an
-- artifacts row, so recovery reads acceptance rather than a flag someone had to
-- remember to set.
CREATE TABLE run_attempts (
    attempt_id    uuid PRIMARY KEY,
    run_id        uuid NOT NULL REFERENCES runs (run_id),
    route_node_id text NOT NULL,
    started_at    timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX run_attempts_by_run ON run_attempts (run_id);

-- The accepted output of one attempt. `attempt_id` is the key rather than the
-- digest: it is what makes a replayed completion land on the row it already
-- wrote instead of a second one.
CREATE TABLE artifacts (
    attempt_id      uuid PRIMARY KEY REFERENCES run_attempts (attempt_id),
    artifact_sha256 text NOT NULL,
    run_id          uuid NOT NULL REFERENCES runs (run_id),
    case_id         uuid NOT NULL REFERENCES cases (case_id),
    -- Who produced it. `model` is the host's own configuration, not the
    -- provider's report of itself (invariant 3); `generation_id` is the
    -- provider's handle for the call, kept for reconciling a bill against a
    -- run. NOT NULL because both are known at the moment the row is written,
    -- and an artifact whose producer is unknown is what this column exists to
    -- make impossible (`docs/DECISIONS.md` §25).
    model           text NOT NULL,
    generation_id   text NOT NULL,
    created_at      timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX artifacts_by_run ON artifacts (run_id);

-- Append-only, per-run monotonic `seq`, allocated under the run row lock. The
-- primary key is the second half of that guarantee: were the lock ever dropped,
-- two events claiming one position would fail rather than both be stored.
CREATE TABLE run_events (
    run_id uuid NOT NULL REFERENCES runs (run_id),
    seq    bigint NOT NULL,
    name   text NOT NULL,
    at     timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (run_id, seq),
    CONSTRAINT run_events_seq_is_positive CHECK (seq > 0),
    CONSTRAINT run_events_name_is_known CHECK (
        name IN ('ROUTE_PINNED', 'ATTEMPT_STARTED', 'ATTEMPT_ACCEPTED',
                 'RUN_COMPLETE', 'RUN_FAILED')
    )
);

-- What a run was charged. `amount` is numeric and reaches Python as Decimal:
-- invariant 7 is that no money path is ever a float. One charge per attempt,
-- enforced here rather than argued from the caller.
CREATE TABLE budget_ledger (
    attempt_id uuid PRIMARY KEY REFERENCES run_attempts (attempt_id),
    run_id     uuid NOT NULL REFERENCES runs (run_id),
    amount     numeric NOT NULL,
    charged_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX budget_ledger_by_run ON budget_ledger (run_id);

-- Evidence. Ingestion is the only way bytes enter a case (SYSTEM_SPEC.md 5), so
-- there is exactly one table bytes are named from and no path that writes it
-- except server/evidence/ingest.py.
CREATE TABLE sources (
    source_id       uuid PRIMARY KEY,
    case_id         uuid NOT NULL REFERENCES cases (case_id),
    document_sha256 text NOT NULL,
    filename        text NOT NULL,
    admitted_at     timestamptz NOT NULL DEFAULT now(),
    -- Invariant 1's second half. Withdrawal hides a source; it never deletes
    -- one, because a run that already cited it has to stay explicable. The full
    -- contract -- refused at every use, re-opening the plan gate -- is owed by
    -- Phase 6 with its own named test (docs/REBUILD_PLAN.md).
    withdrawn_at    timestamptz
);

CREATE INDEX sources_by_case ON sources (case_id);

-- How sources are read (docs/DECISIONS.md section 45, adopted with Phase 2).
-- A view rather than a WHERE clause every caller has to remember.
CREATE VIEW live_sources AS
    SELECT source_id, case_id, document_sha256, filename, admitted_at
    FROM sources
    WHERE withdrawn_at IS NULL;

-- The unit read_evidence returns. One row per block, never a JSON column on the
-- source row: that column is the ~8x read defect docs/AI_CODE_QUALITY.md
-- section 1 measures, because reading one block parsed every block.
CREATE TABLE source_blocks (
    source_id uuid NOT NULL REFERENCES sources (source_id),
    block_id  text NOT NULL,
    page      integer NOT NULL,
    text      text NOT NULL,
    PRIMARY KEY (source_id, block_id)
);

-- The coordinate index behind invariant 11. Never returned to a module: tokens
-- exist so the host can re-locate a quote and refuse one it cannot. `region_id`
-- is the column or paragraph a line belongs to, and is what stops a quote being
-- assembled across a column gutter.
CREATE TABLE source_tokens (
    source_id uuid NOT NULL REFERENCES sources (source_id),
    token_id  bigint NOT NULL,
    page      integer NOT NULL,
    region_id integer NOT NULL,
    line_id   integer NOT NULL,
    text      text NOT NULL,
    x0        double precision NOT NULL,
    y0        double precision NOT NULL,
    x1        double precision NOT NULL,
    y1        double precision NOT NULL,
    PRIMARY KEY (source_id, token_id)
);

CREATE INDEX source_tokens_by_page ON source_tokens (source_id, page, token_id);

-- The pin. Invariant 10: the route is resolved once, digested at the plan gate,
-- and execution reads only this row. `resolved` is the whole route as resolved,
-- so a replay reads what was pinned rather than re-deriving it from a catalog
-- that may have moved.
CREATE TABLE run_routes (
    run_id       uuid PRIMARY KEY REFERENCES runs (run_id),
    profile_id   text NOT NULL,
    selection_id text NOT NULL,
    route_digest text NOT NULL,
    resolved     jsonb NOT NULL,
    pinned_at    timestamptz NOT NULL DEFAULT now()
);

-- What a run has set aside, taken before each provider call and never released.
-- An indeterminate call may have reached the provider and may be billed
-- (docs/DECISIONS.md section 16), so releasing its reservation would let the
-- retry spend money the run has already committed. Append-only: a retry is a new
-- attempt and a new row.
CREATE TABLE budget_reservations (
    attempt_id  uuid PRIMARY KEY REFERENCES run_attempts (attempt_id),
    run_id      uuid NOT NULL REFERENCES runs (run_id),
    amount      numeric NOT NULL CHECK (amount >= 0),
    reserved_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX budget_reservations_by_run ON budget_reservations (run_id);

-- Tenancy. Case standing and global role are separate (SYSTEM_SPEC.md 8); this
-- is the case half. A revoked membership keeps its row: a run that already
-- cited this actor's approval has to stay explicable.
CREATE TABLE case_members (
    case_id    uuid NOT NULL REFERENCES cases (case_id),
    user_id    uuid NOT NULL,
    standing   text NOT NULL,
    granted_at timestamptz NOT NULL DEFAULT now(),
    revoked_at timestamptz,
    PRIMARY KEY (case_id, user_id),
    CONSTRAINT case_members_standing_is_known CHECK (
        standing IN ('READER', 'WRITER', 'APPROVER', 'ADMIN')
    )
);

-- Append-only, hash-chained per case. The chain has no external anchor, so what
-- it gives is detection: an entry edited in place no longer hashes to what the
-- next one says came before it.
CREATE TABLE audit_events (
    case_id         uuid NOT NULL REFERENCES cases (case_id),
    seq             bigint NOT NULL,
    actor_id        uuid NOT NULL,
    action          text NOT NULL,
    -- The digest, never the payload. An audit event records that a decision was
    -- made and what it bound to, not the document behind it.
    payload_sha256  text NOT NULL,
    previous_sha256 text NOT NULL,
    entry_sha256    text NOT NULL,
    at              timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (case_id, seq),
    CONSTRAINT audit_events_seq_is_positive CHECK (seq > 0)
);

-- One row per case: the lock two governed writes contend on, and the head a
-- retained package is compared against.
CREATE TABLE audit_chain_heads (
    case_id     uuid PRIMARY KEY REFERENCES cases (case_id),
    seq         bigint NOT NULL,
    head_sha256 text NOT NULL
);

-- A human gate, and the content it was released over. Invariant 5: approval
-- binds the exact reviewed content, so the row keeps the fingerprint the
-- approver saw. A gate whose current fingerprint differs is open again -- which
-- is how a withdrawal reopens one without anything going looking for approvals
-- to cancel.
CREATE TABLE run_gates (
    run_id            uuid NOT NULL REFERENCES runs (run_id),
    gate              text NOT NULL,
    preview_sha256    text NOT NULL,
    input_fingerprint text NOT NULL,
    approved_by       uuid NOT NULL,
    approved_at       timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (run_id, gate),
    CONSTRAINT run_gates_gate_is_known CHECK (
        gate IN ('SOURCE_SET', 'RESEARCH_PLAN')
    )
);

-- The analyst's signature on one exact revision. Append-only (SYSTEM_SPEC.md 2):
-- an opinion that could be edited is not a signature.
-- Keyed by case first: a revision id is the case's own label (`rev_3` is every
-- case's third revision), never a key this host minted.
CREATE TABLE deliverable_opinions (
    revision_id    text NOT NULL,
    case_id        uuid NOT NULL REFERENCES cases (case_id),
    payload_sha256 text NOT NULL,
    signed_by      uuid NOT NULL,
    signed_at      timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (case_id, revision_id, signed_by, signed_at)
);

-- The freeze, and the filing that follows it. One row per revision of a case: a
-- revision frozen twice would have two sets of bytes claiming to be the same
-- document. Per case, for the reason above -- keyed on the id alone, the first
-- case to freeze `rev_3` took that name from every other case.
CREATE TABLE deliverable_publications (
    revision_id    text NOT NULL,
    case_id        uuid NOT NULL REFERENCES cases (case_id),
    payload_sha256 text NOT NULL,
    frozen_by      uuid NOT NULL,
    frozen_at      timestamptz NOT NULL DEFAULT now(),
    -- Filing is a separate act by a separate person (APPROVER_NOT_INDEPENDENT),
    -- so it is null until someone independent performs it.
    filed_by       uuid,
    filed_at       timestamptz,
    PRIMARY KEY (case_id, revision_id)
);
