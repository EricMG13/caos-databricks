<!-- CP-1B Schema Reference (T3) | 2026-06-02 -->
`cp1b.cp_model_snapshot_fields` contains the single source-grounded
`historical_performance` workbook field on every run.

## CP-MODEL projection profile

The CP-MODEL profile, emitted on every run, comprises
`cp1b.model_comparator_register`, `cp1b.model_validation_register`,
`cp1b.addback_validation_register`, `cp1b.model_readiness` and
`cp1b.cp_model_snapshot_fields`. The snapshot columns are `field_id | value |
status | source_id | source_locator | as_of` and contain exactly one `READY`
`historical_performance` row. These projections validate and interpret CP-1;
they never overwrite CP-1 numeric authority or substitute for the 15 required
analytical tables.

## Required Tables (15)
| ID | Table | Key Columns |
|----|-------|-------------|
| T4.1 | Source Classification Register | Source File Name, Document Type, Period Coverage, Evidence Quality Tier, Analytical Use, Limitations |
| T4.2 | Definition Inheritance | Metric Name, CP-1 Definition, CP-1 Formula, EBITDA Def in Use, Inheritance Status, Conflict Note |
| T4.3 | Summary / Top-Sheet | Row Label, Value / Observation |
| T4.4 | Financial Performance | Line Item, Period 1…N, YoY Change (Abs), YoY Change (%), Analyst Note |
| T4.5 | KPI Dashboard | KPI Category, Metric Name, Period 1…N, YoY Change, Trend Direction, Calculation Status, Analyst Note |
| T4.6 | Variance Register | Metric, Comparison Basis, Prior Value, Current Value, Abs Change, % Change, Mgmt Driver, Analyst Driver, Credit Implication |
| T4.7 | Corporate Actions | Event, Date, Description, Impact, Comparability Effect, Credit Implication, Source |
| T4.8 | Comparative Evaluation | Metric, Benchmark Source, Benchmark Type, Expected Value, Actual Value, Variance, Credit Implication |
| T4.9 | Conflict Log | Conflict Description, Source(s), Metric(s), Period(s), Materiality, Resolution Status, Downstream Impact |
| T4.10 | Monitoring Assessment | Signal Type, Metric/Indicator, Evidence, Severity, Credit Implication, Recommended Action |
| T4.11 | Gaps & Limitations | Gap Description, Affected Metric/Section, Affected Period(s), Downstream Impact, Severity, Recommended Action |
| T4.12 | Model Comparator Register | metric_id, current_period_id, reference_period_id, comparison_basis, current_value, reference_value, absolute_change, percentage_change, calculation_status, restatement_flag, basis_change_flag, perimeter_change_flag, definition_change_flag, values, changes |
| T4.13 | Model Validation Register | metric_id, period_id, cp1_value, cp1b_comparison_value, difference, tolerance, status, explanation, source_or_conflict_ref |
| T4.14 | Add-back Validation Register | addback_id, period_id, cp1_value, cp1b_comparison_value, difference, tolerance, status, label_match, definition_change_flag, explanation, source_or_conflict_ref |
| T4.15 | Model Readiness | downstream_module, status, blocking_metric_ids, blocking_period_ids, conflict_refs, explanation |

## QA Checklist
- [ ] CP-1 defs inherited/confirmed  - [ ] All 15 tables present on every run  - [ ] Calcs traceable  - [ ] Content distinctions maintained  - [ ] No def switching  - [ ] Variance bases explicit  - [ ] Gaps cumulative in T4.11  - [ ] CP-1/CP-1B keyed values and issuer-specific add-backs validated without override  - [ ] Numeric Confidence Score (0–100) + band emitted per CP_CONFIDENCE_SCORE.md  - [ ] Canonical Markdown valid; the Markdown handoff pass view-appropriate parity  - [ ] Null ≠ zero

## Export

The required analytical output and sole downstream handoff is one validated canonical Markdown file. Other analytical export formats are prohibited.

**Output order: (1) author the complete canonical Markdown handoff; (2) validate contract and identity fail-closed; (3) return concise status, limitations, recommended next command, and the Markdown link.**
