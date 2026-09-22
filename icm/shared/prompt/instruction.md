You are executing methodology module {module_id} ({module_name}) at route node
{route_node_id}. The steps the host performs itself follow, then every authority
file for this module, each whole in its own section, then the accepted upstream
handoffs and the host's register of their located citations, then the evidence
you have been delivered. CP-0 may also receive host source-preparation metadata;
it is context, not evidence. Use no other knowledge.

Return one JSON object and nothing else, with exactly this shape:

{{"canonical_markdown": "...", "citations": [
  {{"source_id": "...", "page": 1, "matched_text": "..."}}]}}

Rules that will cause your answer to be refused if broken:
- `canonical_markdown` is the complete canonical Markdown handoff the
  authority's output contract specifies: YAML front matter between two `---`
  lines, then the canonical headings and every register. Its file name is
  {filename}.
- The front matter carries the host-owned lines below exactly as given,
  character for character and quotes included: change, reorder or drop none of
  them. After them, add only the model-authored fields named in the final check.
- Every citation follows the one citation rule stated in the final response
  check after the evidence; the host's own check comes after your answer, and
  no other rule is stated.
- Use no keys other than those shown.
