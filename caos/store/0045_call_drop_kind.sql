-- D110: how a call that got no answer ended (F513's kind), so the ledger --
-- not the frame that saw the drop -- says whether a node has earned its one
-- automatic re-attempt of a drop the provider declared. A drop has no
-- answer: no charge, no generation, no stored body, whoever writes the row.
-- NULL for an answered call and for every outcome recorded before this
-- column; the row stays immutable (0007's triggers).
ALTER TABLE call_outcomes
    ADD COLUMN drop_kind text
        CHECK (drop_kind IN ('declared', 'vendor', 'raised', 'escaped', 'deadline')),
    ADD CONSTRAINT call_outcomes_drop_unanswered CHECK (
        drop_kind IS NULL
        OR (charged_attempt_id IS NULL AND generation_id IS NULL
            AND diagnostic_sha256 IS NULL)
    );
