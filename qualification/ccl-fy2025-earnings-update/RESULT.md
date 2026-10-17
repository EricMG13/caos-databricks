# CCL FY2025 FULL earnings-update qualification set — prepared offline

This set is prepared offline for `FULL_CREDIT_32 / EARNINGS_UPDATE`; it does
not record or claim qualification. Its qualification-set digest is
`36aafade247e6c98811e23be6a5c9ccb6bd17c975b77075b6a7d58a62012be61`.

## Corpus and key provenance

- CCL FY2025 10-K SHA-256:
  `8fa7fceda34be50b3b9b5406e0c9269b5269870d1cd8c2bdafb682755a1c88e6`
- Human answer key:
  `/Users/ericguei/Documents/Co-Pilot Agents/assessment_3issuer_20260719/corpus/ANSWER_KEY_3ISSUER.md`
- Provenance-file SHA-256:
  `5be464735d2794c0ef832dd4f2d739cf270e95cf17c522473f95466b5719c376`

The answer key is provenance only and was never admitted into this set. The
source uniquely anchors FY2025/FY2024 revenue `26,622 / 25,021`, operating
income `4,483 / 3,574`, operating cash flow `6,218 / 5,923`, capex
`3,611 / 4,626`, and balance-sheet debt net of issuance costs and discounts
`26,640 / 27,475`. CP-1B's declared T4.12 comparator keys bind revenue, EBIT,
operating cash flow, capex and total debt without substituting the filing's
gross principal schedule for canonical debt. The respective changes are
`+1,601`, `+909`, `+295`, `+1,015` on canonical negative-outflow capex, and
`-835`.

## Still required

The owner must confirm the FY2024 comparatives and calculated deltas, and give
fresh authorization naming the provider, model, endpoint, reasoning level,
spend ceiling, and run window before any live qualification. No provider run,
snapshot, evidence record, signed verdict, or qualification exists.

## Owner ruling R29, 16 October 2026 (N54) -- the set is keyed to the gate's verdict

The analysis date is 2026-09-19, nine months after the FY2025 year end, with no
FY2026 10-Q in the pack, so CP-0 holds CP-1, CP-1B and CP-2 CONDITIONAL (D1).
The owner ruled the set is keyed to that verdict. Following
`ccl-fy2025-portfolio` (`expects_blocked`, `docs/DECISIONS.md` §99):

- Removed: `expects_ready`, all five citation keys, the CP-5 `decision_scope`
  projection key and the ten `T4.12` register keys. Each asks something of a
  handoff that a refused CP-1, CP-1B or CP-2 never produces, and CP-5 sits
  behind them. The figures in "Corpus and key provenance" stay true of the
  source; they are no longer keyed.
- Added: `expects_blocked: ["CP-1", "CP-1B", "CP-2"]`, met when CP-0's T8 verdict
  for each is `BLOCKED` or `CONDITIONAL`; a met key waives the run-COMPLETE
  requirement only for a run that ended BLOCKED.
- Previous set digest:
  `36aafade247e6c98811e23be6a5c9ccb6bd17c975b77075b6a7d58a62012be61`; the new
  digest is the one stated above.

No document byte moves. Offline edit; no provider call, run, or snapshot.

## Owner ruling F709, 18 October 2026 -- the strict keys are restored for Sol

Live runs now use Sol only (owner, 18 October 2026), so the set is keyed to the
modules READY again rather than held CONDITIONAL by CP-0's gate (R29 above
records the Luna-era key and stays as history). Every key R29 removed is
restored byte for byte: `expects_ready` for CP-1, CP-1B, CP-2 and CP-5; the five
citation keys; the CP-5 `decision_scope` FULL projection; the ten `T4.12`
register keys. `expects_blocked` is removed. CP-5 sits on the route and its keys
had been dropped only because Luna's CP-0 held the modules upstream. The digest is
back to `36aafade247e6c98811e23be6a5c9ccb6bd17c975b77075b6a7d58a62012be61`
(the one stated at the top; R29's `ffbd83e7...` is superseded). Offline edit; no
provider call, run, or snapshot.
