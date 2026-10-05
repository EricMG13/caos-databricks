--- FINAL RESPONSE CHECK {tag} ---
Return exactly one JSON object with only `citations` and `canonical_markdown`,
`citations` first, then `canonical_markdown`.
Inside `canonical_markdown`, copy the host-owned front matter exactly and use
exactly these {heading_count} H2 headings once, in this order: {headings}.
Add only these model-authored front-matter fields: {authored_fields}. Do not add
any other front-matter fields; `owned_object`, `schema_family`, `runtime_output`
and `canonical_filename` belong outside canonical front matter.
Include every register required by the authority. `committee_status` must be
one of {committee_statuses}: what this pathway's decision scope
({decision_scope}) permits.
An evidence line is all the text between two blank lines in the EVIDENCE
section, other than an evidence header (its `source_id:` and `page:` lines);
it may be a whole paragraph or a whole table row. The section's last line,
directly above its END EVIDENCE marker with no blank line between, is an
evidence line too. For every citation,
`matched_text` copies one entire evidence line character for character,
including any leading bullet or footnote marker and any trailing `|`, never
only a sentence of it; that line must appear exactly once on its cited page;
the same words appear verbatim in the Markdown body after the front matter, in
the source's own wording ("we", "our", "us"), never rephrased into the third
person. Cite the evidence line behind each material figure and each
statement that a register row or conclusion rests on, at least one citation in
all, and only lines that support a claim you wrote; the cited lines may be
quoted together in one evidence section of the body. Valid `source_id` values
are exactly: {source_ids}, and `page` is the page in the nearest evidence
header above that line.
{host_text}--- END FINAL RESPONSE CHECK {tag} ---
