# Prompt-conflict review, 2026-09-23

Three read-only reviews of what each module's model is delivered (the host prompt blocks plus the vendor authority `delivered_authority` sends: `SKILL.md`, references and `CANON_SHARED.md`, never `scripts/`) against the checks its answer then meets. A conflict is an instruction, or pair of instructions, that steers a compliant model into a refused answer, a needless hold, or confusion the prompt cannot resolve. Owner request: "Review all vendor modules for instructions within the prompt which lead to similar conflicts in usability and UX."

- G1: CP-0, CP-L10, CP-5, CP-DR, CP-6, CP-8, CP-MEMO, CP-MODEL, and the host blocks.
- G2: CP-1, CP-1A, CP-1B, CP-1C, CP-1D, CP-2, CP-2A, CP-2D.
- G3: CP-2E, CP-2G, CP-2H, CP-3, CP-3C, CP-3D, CP-4, CP-4C.

Status is as of `e4e4e01`. FIXED names the entry that closed it; OPEN rows are the final sweep's to register (host rows) or wait on the owner (vendor rows, OD-8).

| ID | Module(s) | Conflict | Severity | Status |
|---|---|---|---|---|
| G1-1 | CP-0, all | Any table column headed Severity set qa_status; a CRITICAL source gap in CP-0's ledger forced Blocked and ended the run | BLOCKS | FIXED D31 (V3) |
| G1-2 | CP-5, CP-6 | CP-5's audit verdict became its own qa_status; the host's QA gate needed Passed while the vendor navigator meets it on acceptance | HOLDS | FIXED D34 (`QA_GATE_MET`) |
| G1-3 | CP-8, CP-6, CP-L10, CP-5 | The canon's placeholders and value-list labels sat in critical columns the checker disqualifies | BLOCKS | FIXED D31 (V1), D34 (one-row rule) |
| G1-4 | CP-DR | The research validator refuses the canon's null (`—`, empty); dossier refusals reached neither model nor operator | BLOCKS | Feedback FIXED D30 5th addendum; validator/canon conflict OPEN (vendor, OD-8) |
| G1-5 | CP-8, CP-6, CP-5, CP-L10 | Literal column and ID matching broken by the vendor's own examples (spacing, en dash, backticks, `T1.` caption, backticked topic IDs) | BLOCKS | FIXED D31 (V2), D34 (backticked values) |
| G1-6 | CP-0, CP-DR | On deep-research routes CP-DR must be in T8 (host) and must not be (CP-0 references); a wrong set got no feedback | BLOCKS | Feedback FIXED D30 5th addendum; vendor text OPEN (OD-8) |
| G1-7 | CP-0 | The source-preparation block's "does not attest" led CP-0 to block every consumer of a PDF pack | HOLDS | FIXED D34 (N53) |
| G1-8 | CP-0 | T8 `Source files to attach` names prepared files the host cannot match (`EVIDENCE_DEMAND_UNRESOLVED`) | HOLDS | FIXED D34 |
| G1-9 | CP-0, CP-L10 | "Reserve CONDITIONAL" read as any missing source; CP-L10 held although it completes with gaps | HOLDS | FIXED D31 (V4), D34 |
| G1-10 | CP-0 | T8 required in Analysis and in the appendix (two tables); backticked readiness refused | BLOCKS | FIXED D31 (V4) |
| G1-11 | all | Score rules in three places, one wrong (band below 40); host pointed at an undelivered script | BLOCKS | FIXED D31 (V5), D34 |
| G1-12 | CP-6 | The portfolio workbook is delivered as base64 sample data; critical cells then take a placeholder | BLOCKS | FIXED D38 (withheld; inputs from the evidence) |
| G1-13 | CP-8 | Undelivered upstreams (CP-6/6A) meant Blocked; T7.6 needs a row with fewer than 3 decisions | HOLDS | FIXED D34 (canon SEC4, one-row rule) |
| G1-14 | CP-5, CP-6 | The two modules disagree which runs first | DEGRADES | OPEN (vendor, OD-8) |
| G1-15 | all | Host blocks discouraged self-checking and named only three refusal grounds | DEGRADES | FIXED D34 |
| G1-16 | host | Feedback gaps: T8 set, dossier, `_text` limits, blocker over 512, no retry on identity/undeclared | DEGRADES | T8 set and dossier FIXED D30 5th addendum; the rest OPEN (register) |
| G1-17 | CP-5, CP-8 | Told they are FULL runs while LITE routes validate SCREENING_ONLY; scope never stated | DEGRADES | FIXED D34 (final check names permitted statuses) |
| G1-18 | CP-0, CP-L10 | No user objective delivered; five opening headings; an undelivered brief file named | DEGRADES | OPEN (minor) |
| G2-1 | all eight | The canon prescribes the exact placeholders the checker refuses | BLOCKS | FIXED D31 (V1) |
| G2-2 | all eight | Closed value lists include values the blocklist refuses (CP-2 left only Strong/Average/Weak) | BLOCKS | FIXED D31 (V1) |
| G2-3 | CP-2 | The method prescribes "Quantitative threshold not available…", a refused substring, on 8 mandatory rows | BLOCKS | FIXED D31 (V1) |
| G2-4 | CP-1, CP-1A, CP-1B, CP-2A | Any Severity column read as QA findings; one Critical ended the run | BLOCKS | FIXED D31 (V3) |
| G2-5 | all eight | "Restricted→band Low" against the validator's band-by-score | BLOCKS | FIXED D31 (V5) |
| G2-6 | CP-1, CP-1B, CP-1C | The checker's column lists differ from the method's binding specs in most registers | BLOCKS | Spelling FIXED D31 (V2), D34 (containment); differing sets OPEN (N55, bundle owner) |
| G2-7 | all eight | Register binding captured by prose mentions, reported as the wrong fault | BLOCKS | FIXED D34 (headings first) |
| G2-8 | CP-1A | The register-locating rule is not in the prompt | BLOCKS | FIXED D31 (V2 titles), D30 4th addendum (absent IDs) |
| G2-9 | CP-1A, CP-1B, CP-1C, CP-2D, CP-2A | Step gates say "skip" where the checker needs a row | BLOCKS | FIXED D34 (one-row rule) |
| G2-10 | CP-1 → CP-1D | An upstream's permitted output (empty bridge, nulls) forces a downstream refusal | BLOCKS | Partly FIXED D34 (one-row rule); OPEN (vendor) |
| G2-11 | CP-2A, CP-1C | Declared upstreams absent from the route, and the canon says stop | HOLDS | FIXED D34 (canon SEC4, canon core 4) |
| G2-12 | host | A Blocked answer from an optional-only producer ends the run | HOLDS | DECIDED keep (D34, N63) |
| G2-13 | CP-1C | Told to discover peers on the web; the host allows pinned sources only | HOLDS | FIXED D34 (host_steps: no retrieval) |
| G2-14 | CP-2D | T2E.6 is prose in the method, a register in the checker | BLOCKS | Partly FIXED D34 (one-row rule); OPEN (vendor) |
| G2-15 | CP-2 | T2.10 must hold a Positive and a Negative driver even when none is supported | BLOCKS | OPEN (vendor, OD-8) |
| G2-16 | host | The 16-line feedback cap hid the root cause | DEGRADES | FIXED D30 5th addendum |
| G2-17 | host | Operator hints give the wrong fix for `HANDOFF_INCOMPLETE` and `HANDOFF_BLOCKED` | DEGRADES | OPEN (host, register) |
| G2-18 | CP-1A, CP-2A, CP-1D, CP-1 | Absorbed phases carry contradictory headings and rules; canon `Not Reviewed` refused | DEGRADES | OPEN (vendor, minor) |
| G3-1 | all eight | A correct Blocked answer refused `HANDOFF_INCOMPLETE` | DEGRADES | FIXED D34 (Blocked before completeness) |
| G3-2 | CP-2E, CP-3, CP-3C, CP-2H, CP-4 | Vendor label lists hold blocklisted values in critical columns | BLOCKS | FIXED D31 (V1) |
| G3-3 | CP-3, CP-3C | The method prescribes a refused sentence | BLOCKS | FIXED D31 (V1) |
| G3-4 | CP-4 → CP-4C | CP-4's capacity severity read as a CRITICAL QA finding | BLOCKS | FIXED D31 (V3) |
| G3-5 | CP-2E | `Ratchet (direction; bps)` split into two columns | BLOCKS | FIXED D34 |
| G3-6 | CP-4, CP-4C | Required registers the method says to skip or blank | BLOCKS | FIXED D34 (one-row rule), D31 (V1) |
| G3-7 | CP-2E, CP-3D, CP-3C | Undelivered upstreams named; canon says stop | HOLDS | FIXED D34 (canon SEC4) |
| G3-8 | CP-2H, CP-4C | FULL dependencies on LITE routes; `UPGRADE` undefined | HOLDS | Partly FIXED D34; `UPGRADE` OPEN (vendor) |
| G3-9 | CP-2G → CP-CF | A permitted driver row breaks CP-CF; `FORECAST_DRIVER_NOT_READY` never raised; commas not parsed | HOLDS | OPEN (host, register) |
| G3-10 | host | Feedback cap dropped tail registers | BLOCKS | FIXED D30 5th addendum |
| G3-11 | CP-3, CP-4 | Retrieval instructions (Sector RV workbook, EDGAR) the host cannot honour | DEGRADES | FIXED D34 (host_steps) |
| G3-12 | all eight | Module status words have no mapping to qa_status | DEGRADES | Band FIXED D31 (V5); mapping OPEN (vendor) |
| G3-13 | CP-2G | `Analyst Judgement` vs `analyst_judgment`; exact `base`/`downside` | BLOCKS | Spelling FIXED D34; exact case values OPEN (vendor) |
| G3-14 | CP-2H | "Paraphrase triggers" against verbatim evidence-line citations | DEGRADES | OPEN (vendor/prompt) |
| G3-15 | CP-2H, CP-4 | Scripts the model is told to transcribe output refused placeholders | BLOCKS | NOT-A-DEFECT for the host (scripts are not delivered); vendor OPEN |
| G3-16 | CP-4, CP-2E | Method column spellings differ from the contract | BLOCKS | FIXED D31 (V2), D34 (containment) where spelling-only |
| G3-17 | CP-2E | Two different opening headings | DEGRADES | OPEN (vendor, warning only) |

Live evidence behind the confirmed rows is in `qualification/PROVIDER_RUNBOOK.md` (23 September sections).
