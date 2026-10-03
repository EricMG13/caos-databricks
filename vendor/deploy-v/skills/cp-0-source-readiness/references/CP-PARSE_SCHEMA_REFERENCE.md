<!-- CP-PARSE Schema Reference | v2.0 | 2026-08-04 -->
<schema_reference module="CP-PARSE" tier="3">
# CP-PARSE data-preparation schema

Phase identity: `document_parse_manifest`, within owner `module_id=CP-0`, `module_name=SourceReadiness`.

## Core objects

| ID | Object | Purpose |
|---|---|---|
| P3 | Input Sources | original identity, authority, entity, period and version links |
| P5 | Parse Jobs | the host extraction's delivery, status, fidelity, coverage and limitations |

Retired: P1 Pipeline, P2 Workspace Record, P4 Triage Register, P6 Prepared Artifacts, P7 Representation Catalog and P8 Package Record. The host performs that work before the call, and its `HOST SOURCE PREPARATION` record holds it; CP-0 does not restate it.

## Representation invariants

- `PASS_THROUGH` selects the immutable original as `ACTIVE_CONTENT`.
- `COMPLETE` or `DEGRADED` parsing selects the prepared representation as `ACTIVE_CONTENT`; the original remains authority and verification provenance.
- `BLOCKED` has no active content and no silent fallback.
- `SKIP_DUPLICATE` names a valid selected source; `SKIP_LOW_VALUE` remains inventory only.
- Each retained logical source has exactly one active representation.

## Analysis sections

Preparation summary; pack inventory and version map (P3); extraction/fidelity assessment (P5); limitations; CP-0 handoff. The host's preparation record stands for triage, the representation catalog and packages.

## QA and export

The preparation registers belong inside `[IssuerID]_CP-0_[YYYYMMDD].md`, the only module handoff. Preserve the canonical YAML and six H2 sections defined by `CP_AB_EXPORT_SPEC.md`; fail closed on fidelity or Markdown validation failure.
</schema_reference>
