# CCL FY2025 LITE full-credit-screen qualification set — prepared offline

Status: **OFFLINE / UNVERIFIED / NOT QUALIFIED**.

This immutable set prepares `LITE_CREDIT_22 / LITE_FULL_CREDIT_SCREEN` from
the CCL FY2025 10-K, two governing debt documents, the dated Fitch rating
action, and the RCL and NCLH FY2025 releases. Its qualification-set digest is
`d2c64e4db9419eb1754ebf10f7fee7caeff498b3a149bf64a2d4bb66226febac` (was
`1ce7cf99711b1e6c1da60fb54481ed8cead5033119f86a6ffaeb3ab0027b1b7e` on the base after fork r17 split
CP-1C T4.5's packed leverage column and the NCLH key was re-keyed, N192, and
`f1647d3b593d4a3ec66a001969346f9411da30091b618383a1076b4cefda9608` with the CP-4C `T4E.1` key restored (F709), before the two were merged).

The keys bind the LITE scope, CCL liquidity, NCLH leverage, the Fitch-identified
2030 CCL note, the CCL maturity schedule, and total debt. CP-4C's QA status
remains `Restricted`; the admitted sources document no distress trigger, and
the CP-4C `T4E.1` register key is set again (see the F709 ruling below). CP-1A, CP-2H, CP-3C, and the CP-5
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

## Owner ruling F709, 18 October 2026 -- the strict keys are restored for Sol

Live runs now use Sol only (owner, 18 October 2026), so the `T4E.1` register key
(`trigger` = `No documented distress trigger`, column `status` = `Not
Applicable`) that R26 dropped to fit Luna's wording is restored, byte for byte.
The R26 section above stays as the record of why it was dropped. The digest is
back to `f1647d3b593d4a3ec66a001969346f9411da30091b618383a1076b4cefda9608`;
the digest stated at the top is the current one. Offline edit; no provider call,
run, or snapshot.
