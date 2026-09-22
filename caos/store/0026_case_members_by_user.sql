-- The directory lists a caller's cases by joining from `case_members` on the
-- user id (`cases_for_member`). The table's primary key leads with `case_id`,
-- so it serves that predicate only as a scan of every membership row.
-- Partial on live standing because a revoked membership lists nothing: the
-- index then holds exactly the rows the directory reads.
CREATE INDEX case_members_by_user ON case_members (user_id)
    WHERE revoked_at IS NULL;
