-- W1 (review 3): the audit package a filing's receipt pins, stored at filing.
-- The receipt names the renderer that filed it (`renderer_sha256`), and a
-- package built later packed whatever renderer was deployed by then, so a
-- revision filed under an earlier one was served an archive its own verifier
-- refuses. Filing now builds the package once, in the unit that writes the
-- receipt, puts it in the blob store and names its digest here; the download
-- serves exactly those bytes. NULL is a filing made before this migration:
-- it has no stored package, and its download is refused rather than served
-- unverifiable. Nothing is backfilled.
ALTER TABLE deliverable_receipts ADD COLUMN package_sha256 text
    CHECK (package_sha256 ~ '^[0-9a-f]{64}$');
