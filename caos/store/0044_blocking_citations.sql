-- D106: a validated Blocked answer's citations, judged as any answer's --
-- its anchored ones with their lines and its unverified ones -- so the
-- blocked view can show each quote verified or unverified. A Blocked answer
-- writes no record, and the run's blocking verdict is the one row that
-- names it, so the blob holding them (`handoff.blocked_citations_bytes`) is
-- addressed from that row, written in the same insert that ends the run.
-- The row stays immutable (0021's triggers); a verdict recorded before this
-- column, or one `block_run` was given no citations for, holds NULL.
ALTER TABLE run_blocking_verdicts
    ADD COLUMN citations_sha256 text CHECK (citations_sha256 ~ '^[0-9a-f]{64}$');
