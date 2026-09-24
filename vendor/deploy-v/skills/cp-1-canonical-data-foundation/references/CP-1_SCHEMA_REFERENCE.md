<!-- CP-1 Schema Reference (Tier 3) | 2026-06-02 | rev 2026-06-26: Markdown handoff+canonical Markdown export contract + numeric Confidence Score -->
<schema_reference module="CP-1" tier="3">
## Required Tables (19)
| ID | Name | Key Columns |
|----|------|-------------|
| T4.1 | Source Register | Source File Name, Document Type, Period Coverage, Currency, Unit, Perimeter, Accounting Basis, Evidence Quality Tier, Analytical Use, Limitations |
| T4.2 | Entity Period Key | Entity Name, Entity Role, Fiscal Year End, Reporting Currency, Reporting Unit, Consolidation Perimeter, Accounting Basis, Available Periods |
| T4.3 | Normalization Reg | Description, Source, Type, Before, After, Rationale, Periods |
| T4.4 | Income Statement | Line Item, Period 1…N |
| T4.5 | Cash Flow Statement | Line Item, Period 1…N |
| T4.6 | Balance Sheet | Line Item, Period 1…N |
| T4.7 | Normalized Financials | Line Item, Statement Source, Period 1…N |
| T4.8 | Constructed Period Reg | Metric Name, Derived Period Type, Full-Year Component, Current Stub, Prior-Year Stub, Derived Value, Calculation Status, Source Files, Limitations |
| T4.9 | Calculation Register | Metric Name, Formula, Numerator Value, Numerator Source, Denominator Value, Denominator Source, Period, Currency, Unit, Calculated Value, Calculation Status, Evidence Quality Tier, Limitations |
| T4.10 | KPI Dashboard | KPI Category, Metric Name, Period 1…N, Trend Direction, Analyst Note |
| T4.11 | Def Conflict Reg | Metric Name, Canonical Definition, Issuer-Reported Definition, Source of Conflict, Periods Affected, Materiality, Downstream Modules Affected, Resolution / Recommendation |
| T4.12 | Gaps & Warnings | Gap Description, Affected Line Item or Metric, Affected Period(s), Downstream Impact, Severity, Recommended Action |
| T4.13 | Downstream Readiness | Downstream Module, Readiness Status, Gaps or Limitations, Recommended Actions |
| T4.14 | Model Period Register | period_id, fiscal_year, fiscal_quarter, period_type, start_date, end_date, day_count, audit_status, currency, unit, accounting_basis, entity_perimeter, source_id, source_locator, component_period_ids |
| T4.15 | Model Account Register | metric_id, period_id, value, sign_convention, value_class, calculation_status, source_id, source_locator, conflict_refs, limitation_refs |
| T4.16 | Segment Revenue Schedule | segment_id, segment_name, segment_type, display_priority, period_id, revenue, status, source_id, source_locator |
| T4.17 | Adjusted EBITDA Bridge | addback_id, addback_label, addback_classification, realization_status, display_priority, period_id, value, status, source_definition, source_id, source_locator |
| T4.18 | Debt Facility Register | facility_id, facility_name, period_id, facility_type, carrying_value, principal, drawn_amount, commitment, secured_status, seniority, currency, margin_or_coupon, maturity_date, lease_classification, source_id, source_locator |
| T4.19 | Model Reconciliation Register | check_id, period_id, check_type, reported_value, calculated_value, difference, tolerance, status, explanation, source_refs |

Exact table-ID comments, row shapes, controlled IDs and CP-MODEL readiness
rules are binding per `REF_CP-1_13_ModelWorkbookInterface.md`.

## Contextual CP-MODEL Schedules

| Stable table ID | Context | Key columns |
|---|---|---|
| `cp1.operating_kpi_schedule` | Optional when issuer operating measures are applicable | kpi_id, kpi_label, business_unit, kpi_category, display_priority, period_id, value, unit, value_type, status, source_id, source_locator |
| `cp1.cp_model_segment_allocation` | Required whenever the segment schedule is non-empty — a condition on the evidence, not on the consumer | slot_id, slot_label, component_segment_ids |

Allocation rows are the stable CP-1 mapping to active `DIVISION_1..3` forecast
slots. Each row has at least one component, and each stable source segment is
allocated exactly once. The mapping assigns forecast drivers only; it must not
group, merge, reorder or suppress the separately rendered segment schedule.
Rows absent from the allocation are inactive slots, not zero-growth inputs.
Do not emit the allocation when the segment schedule is genuinely empty. CP-2G's
absence is no reason to omit it: CP-1 runs first, and CP-MODEL reads the allocation
only when CP-2G is supplied. A partially populated segment schedule is not equivalent to
an empty, undisclosed schedule and blocks CP-MODEL readiness.

Operating KPI `value_type` is `PERIOD_END`, `PERIOD_FLOW` or `RATE`. A rate is
never averaged to construct YTD/LTM; only a directly sourced exact-period
aggregate may populate a derived aggregate column.

## 17-Section Output (analysis narrative = canonical Markdown → projected Markdown handoff §3)
1. Source Register  2. Entity Period Key  3. FS Coverage  4. Normalized IS
5. Normalized BS  6. Normalized CFS  7. Normalization Register  8. Calculation Register
9. Constructed Period Register  10. KPI Dashboard  11. Definition Conflict Register
12. Gaps & Warnings  13. Downstream Readiness  14. Evidence Trace  15. QA Status
16. Limitation Flags  17. Module Handoff
> §15 QA Status carries the numeric **Confidence Score** (0–100) + derived band, `qa_status`, `committee_status` per `../../../CANON_SHARED.md § CP_CONFIDENCE_SCORE.md`; this is surfaced in the Audit Summary *before* the narrative in Markdown/export. §17 Module Handoff is the canonical `.md` envelope (YAML front-matter + canonical H2 headings), not a JSON block.

## Canonical Extraction Types (13)
sourced_fact | quoted_text | table_value | calculated_metric | analyst_inference |
upstream_artifact | user_instruction | documentary_fact | definition_conflict |
gap | source_limitation | insufficient_information | not_available

## QA Checklist (11)
- [ ] Sources classified with quality labels + tiers
- [ ] All tables present or [Insufficient Information]
- [ ] Calculations have audit trail in T4.9
- [ ] Four-category separation discipline maintained
- [ ] No M-prefix references
- [ ] Canonical Markdown valid; every the Markdown handoff passes view-appropriate parity
- [ ] numeric Confidence Score (0–100) + band in Audit Summary, before narrative
- [ ] No silent reconciliation — conflicts in T4.11
- [ ] All gaps in T4.12 + inline
- [ ] Null storage rule applied
- [ ] Def Conflict Register populated or alignment confirmed
- [ ] CP-MODEL interface tables pass stable-key and referential checks on every run
- [ ] Downstream Readiness carries a CP-MODEL row on every run, requested or not

## Export

The required analytical output and sole downstream handoff is one validated canonical Markdown file. Other analytical export formats are prohibited.

**Output order: (1) author the complete canonical Markdown handoff; (2) validate contract and identity fail-closed; (3) return concise status, limitations, recommended next command, and the Markdown link.**
