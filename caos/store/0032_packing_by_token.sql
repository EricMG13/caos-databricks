-- Packing 2 (CF-013): a line wider than a block is cut between its tokens,
-- never inside one, so every block ends where the token index can break a
-- quote. `format_version` is the output record's format -- the tokens, and
-- the blocks cut from them -- and the output digest carries it: 1 for every
-- source admitted before this migration and for every source whose lines all
-- fit, which the two packings write identically; 2 for a source with a line
-- cut between tokens. The extraction digest's envelope is unchanged and keeps
-- its own version 1. Rows already stored keep 1 and verify as recorded.
ALTER TABLE source_extractions
    DROP CONSTRAINT source_extractions_format_version_check;
ALTER TABLE source_extractions
    ADD CONSTRAINT source_extractions_format_version_check
    CHECK (format_version IN (1, 2));
