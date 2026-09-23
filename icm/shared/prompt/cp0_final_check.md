--- CP-0 FINAL CHECK {tag} ---
For CP-0, include P1-P8 and T1-T8. The T8 header must be exactly:
{t8_header}
T8 appears once, as its table in the analytical appendix; the Analysis names it
without repeating the table. In `Source files to attach`, name only filenames
listed in the host source-preparation block.
Your source-readiness verdicts are about sources. SKILL.md states: "Source
readiness does not assert that upstream analytical handoffs already exist:
navigation checks those separately." A module whose only outstanding condition
is that a predecessor has not run yet is not CONDITIONAL and not BLOCKED on
that ground: the dependency plan sequences it, and this run pins its own route.
Reserve CONDITIONAL and BLOCKED for a source the evidence set does not carry
and the module cannot run without, and state that source in the blocker; a
module that can complete with the gap recorded is READY_WITH_LIMITATIONS, with
the gap in its row.
--- END CP-0 FINAL CHECK {tag} ---
