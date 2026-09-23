-- When a qualification verdict was written. `decided_at` is the reviewer's own
-- word about when they decided, and nothing recorded when the row was signed:
-- the true time survived only in `command_requests.created_at`, and only for a
-- signature made through the API (DQ-13).
--
-- Added without a default first, so every row already signed keeps NULL --
-- unknown -- rather than the moment this migration ran, which would be a false
-- signing time. The default then applies to every row written from now on.
ALTER TABLE qualification_verdicts ADD COLUMN recorded_at timestamptz;
ALTER TABLE qualification_verdicts ALTER COLUMN recorded_at SET DEFAULT now();
