# CCL FY2025 LITE full-credit-screen qualification set — prepared offline

Status: **OFFLINE / UNVERIFIED / NOT QUALIFIED**.

This immutable set prepares `LITE_CREDIT_22 / LITE_FULL_CREDIT_SCREEN` from
the CCL FY2025 10-K, two governing debt documents, the dated Fitch rating
action, and the RCL and NCLH FY2025 releases. Its qualification-set digest is
`4adc65e7ddb76b97758c0ad24feaec5a499df7c6a7814a2d3432a29d4ce3bef9`.

The keys bind the LITE scope, CCL liquidity, NCLH leverage, the Fitch-identified
2030 CCL note, the CCL maturity schedule, and total debt. CP-4C's QA status
remains `Restricted`; the admitted sources document no distress trigger, but
no CP-4C register key is set (see below). CP-1A, CP-2H, CP-3C, and the CP-5
gate also remain `Restricted`: the pack has no complete sponsor transaction,
all-agency rating, market/LME, or restructuring evidence.

The keys were authored from the admitted documents. No provider call, run,
snapshot, evidence record, reviewer verdict, or qualification claim exists.

## Owner ruling R26, 16 October 2026 (N128) -- the CP-4C register key is dropped

The `T4E.1` register key (`trigger` = `No documented distress trigger`, column
`status` = `Not Applicable`) is removed. Its row key is free text the module may
word differently, and the matrix compares a row key exactly, so a correct
`Not Applicable` row worded otherwise was scored missing. Nothing else in the
set moves and no document byte moves. The previous digest was
`f1647d3b593d4a3ec66a001969346f9411da30091b618383a1076b4cefda9608`; the new
digest is the one stated above. Offline edit; no provider call, run, or snapshot.
