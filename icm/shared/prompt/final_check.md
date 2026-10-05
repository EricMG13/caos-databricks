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
evidence line too. For every citation, `matched_text` copies an exact
excerpt of one evidence line, character for character: at least 8
consecutive words, or the whole line if it has fewer, including any leading
bullet or footnote marker and any trailing `|`. The excerpt stays within
that one line and appears exactly once on its cited page. The excerpt lives
only in `citations`: the Markdown body quotes no source text and cites by
marker, `[C1]` for the first citation in the list, `[C2]` for the second,
`[C2, C5]` for several, beside the statement each supports. Give each
material figure and each statement that a register row or conclusion rests
on a marker, at least one citation in all, and cite only excerpts that
support a claim you wrote. A marker never goes inside a figure, status or
other value cell: put it in the row's source or evidence column if it has
one, otherwise in the prose or the Evidence Trace row. Evidence Trace is a
short locator table, no quotes: each row gives a claim, its marker, the
document and the page, with any column your authority requires there.
`[C<n>]` is only ever this answer's citation: label your own conflicts and
rows otherwise (for example `CF-1`). An upstream handoff's marker is shown
as `[CP-1 C3]`: keep that form if you carry it over, never `[C3]`, and cite
the excerpt yourself to rest a claim of yours on it. A marker that names no
citation refuses the answer. A citation the host cannot locate is kept as
unverified and shown to the reader as such; it does not refuse the answer.
Valid `source_id` values are exactly: {source_ids}, and `page` is the page in
the nearest evidence header above that line.
{host_text}--- END FINAL RESPONSE CHECK {tag} ---
