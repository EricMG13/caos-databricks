-- D118 fix round 1: a failure the provider declared after content began is
-- its own drop kind, `declared_after_content`. It shares the node's one
-- automatic re-attempt with `declared`, but the call may have been billed
-- for what it streamed, so its row may name the stream's generation id: the
-- handle its unknown bill is reconciled by. Never a charge or a stored body.
-- Every other drop kind still names nothing. 0047 is reserved for the
-- Copilot transport (D77). The rows stay immutable (0007's triggers); both
-- checks are validated against every existing row.
ALTER TABLE call_outcomes
    DROP CONSTRAINT call_outcomes_drop_kind_check,
    ADD CONSTRAINT call_outcomes_drop_kind_check CHECK (
        drop_kind IN (
            'declared', 'declared_after_content', 'vendor', 'raised', 'escaped',
            'deadline'
        )
    ),
    DROP CONSTRAINT call_outcomes_drop_unanswered,
    ADD CONSTRAINT call_outcomes_drop_unanswered CHECK (
        drop_kind IS NULL
        OR (charged_attempt_id IS NULL AND diagnostic_sha256 IS NULL
            AND recorded_seq IS NOT NULL
            AND (generation_id IS NULL OR drop_kind = 'declared_after_content'))
    );
