--- FINAL RESPONSE CHECK {tag} ---
Return exactly one JSON object with only `canonical_markdown` and `citations`.
Inside `canonical_markdown`, copy the host-owned front matter exactly and use
exactly these {heading_count} H2 headings once, in this order: {headings}.
Add only these model-authored front-matter fields: {authored_fields}. Do not add
any other front-matter fields; `owned_object`, `schema_family`, `runtime_output`
and `canonical_filename` belong outside canonical front matter.
Include every register required by the authority.
For every citation, `matched_text` is the complete text of one evidence line,
copied character for character; that line must appear exactly once on its
cited page; the same words appear verbatim in the Markdown body after the
front matter. Cite only lines that support a claim you wrote. Valid
`source_id` values are exactly: {source_ids}, and `page` is the page shown in
that line's evidence header. Include at least one citation.
--- END FINAL RESPONSE CHECK {tag} ---
