"""The argument-count suppressions are a budget, and a budget only falls (W11).

`# noqa: PLR0913` is the one lint suppression this tree hands out for width,
and each is a function whose parameter list nobody has yet found the type for.
What the budget counts is the *positional* ones: a caller can transpose two
neighbouring arguments of the same type silently, and that is the defect this
rule exists to keep a lid on. A suppressed function whose extra parameters are
keyword-only cannot be called wrongly that way, so it is recorded here and not
charged.

**The unit changed on 17 September 2026, by the owner's decision, and the old
one is stated here so nobody has to reconstruct it.** The budget used to count
raw markers, capped at 52. Integrating wave 3 of the audit remediation took
that count to 53: one marker left `caos/methodology/canonical.py`, and two
arrived with functions that each replaced several copies of themselves -- the
shared verification reader, and the one governed envelope that five routes had
been spelling inline while a module-local helper served the rest. So the raw
count rose by one while the tree lost about 346 lines of duplication, because
the copies it removed were never suppressed and so had never been counted.
A ceiling that punishes concentrating a suppression into one shared helper is
measuring the
wrong thing, and raising it to 53 would have been a threshold moved to obtain
a pass. Two other units were measured and rejected before this one: counting
markers outside the shared helpers rose 47 -> 49, because consolidating
callers drains *other* helpers' caller counts and pushes them across the
threshold; and any unit over raw markers rises here by construction.

**The scan widened on 17 September 2026, at Completion Phase 12's confidence
review, and this is the seventh instance of the class `CLAUDE.md` names.** The
count above was over *marked* functions only -- the scan returned early unless
a file carried `noqa: PLR0913`, and skipped any function whose own line lacked
it. Its axis was therefore **marker presence**, not width. Ruff does not raise
`PLR0913` for a dummy-named (leading-underscore) parameter, and this layer's
own convention is to name an unused dependency `_standing` and an unused body
`_body` -- so a handler at seven positional parameters carried no marker, and a
gate keyed on the marker could not see it. Three of Completion Phase 12's own
handlers were exactly that shape, and the true count went 24 -> 27 while this
file read 22 -> 22. The cheapest evasion of the old rule was to drop the
marker, which makes the code no better and the gate blind; the cheapest evasion
of this one is to make the surplus keyword-only, which is the fix.

So the scan now reads **every** module-level function under the scanned roots
and charges on positional width whether or not a marker is present. The number
is 24, measured on 2026-09-17 at both `1b1ffcd` (the phase's base) and its
integrated head -- so the phase added none, once its three handlers were made
keyword-only. It is a wider measurement than the 22 above, not a raised
ceiling: the two numbers count different sets, and the old one is stated here
so nobody reads the change as a threshold moved to obtain a pass.

The criterion that picked this unit, stated once rather than three times: two
of the three units considered were gameable in the direction of making the
code *worse* -- the caller-count one rewarded the consolidation it meant to
punish, and a count of named parameters would have let `(a, b, *rest)` go from
charged to clear while becoming unbounded. This one is the one where gaming it
is the fix.
"""

from __future__ import annotations

import ast
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
MARKER = "noqa: PLR0913"
CEILING = 24
POSITIONAL_LIMIT = 5


def _functions(path: Path) -> list[tuple[str, int, int, bool]]:
    """Every function in `path`: name, positional width, total, marked.

    A method's receiver is not an argument its caller passes, and ruff does not
    count it either, so `self` and `cls` are dropped. `*args` is unbounded
    positional width, which a count of named parameters would read as none, so
    it is charged outright.

    Read whether or not the file carries a marker: a function ruff declines to
    flag -- which it does for a dummy-named parameter -- is still one a caller
    can pass two same-typed arguments to in the wrong order.
    """
    source = path.read_text(encoding="utf-8")
    lines = source.splitlines()
    tree = ast.parse(source)
    receivers = {
        body
        for node in ast.walk(tree)
        if isinstance(node, ast.ClassDef)
        for body in node.body
        if isinstance(body, ast.FunctionDef | ast.AsyncFunctionDef)
    }
    found = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            continue
        arguments = node.args
        named = arguments.posonlyargs + arguments.args
        bound = node in receivers and bool(named) and named[0].arg in ("self", "cls")
        positional = len(named) - (1 if bound else 0)
        if arguments.vararg is not None:
            positional = max(positional, POSITIONAL_LIMIT + 1)
        found.append(
            (
                node.name,
                positional,
                positional + len(arguments.kwonlyargs),
                MARKER in lines[node.lineno - 1],
            )
        )
    return found


def test_positional_argument_suppressions_only_fall() -> None:
    """24 measured on 2026-09-17 at `1b1ffcd` and at Completion Phase 12's
    integrated head, so the phase added none. Lower this number when you narrow
    a function; never raise it.

    The 24 is over **positional width**, marked or not -- the widening the
    module docstring records. The older 22 counted marked functions only and is
    a different set; the analysis below was written for it and is kept because
    the concentration it describes is still the finding, but the eighteen and
    the twenty-two are that older census, taken before this phase made
    `members.py`'s three handlers keyword-only.

    A suppression is charged when the function takes more than five positional
    parameters -- ruff's own ceiling, counted the way a caller meets them.
    Making the surplus keyword-only clears the charge, which is not an evasion:
    that is the fix. Every suppression is still read, so a marker on a function
    that no longer needs one cannot hide behind the keyword rule.

    The 22 are not scattered, and that is the finding the number hides:
    eighteen are under `caos/api/` -- the command handlers and the section
    reads -- at six to nine positional parameters, and twenty-one of the
    twenty-two declare no keyword-only parameter at all. The other four are
    the proof and deliverable constructors, `store/runs.py`'s `_transition`
    and `evidence/page.py`'s `_frame`. So the charge points at one
    architectural layer that takes its arguments positionally, and at a fix
    that layer could take.

    The file floor is 80 against 102 scanned today: enough that a scan of the
    wrong directory or an empty one still fails, and enough headroom that
    deleting a handful of modules cannot turn a suppression budget red for a
    reason unrelated to suppressions."""
    files = [
        *(REPO / "caos").rglob("*.py"),
        *(REPO / "scripts").rglob("*.py"),
    ]
    # A scanner that scanned nothing is a failure, not a pass.
    assert len(files) >= 80, len(files)

    functions = [entry for path in files for entry in _functions(path)]
    assert functions, "no function was read at all"
    assert any(marked for *_, marked in functions), "no suppression was read at all"

    # A marker ruff would not raise is one nobody needs, and the keyword rule
    # below must not become somewhere for it to hide.
    stale = [
        name
        for name, _, total, marked in functions
        if marked and total <= POSITIONAL_LIMIT
    ]
    assert stale == [], stale

    # Charged on width alone. A marked function that made its surplus
    # keyword-only is uncharged, and an unmarked one that did not is charged --
    # which is the whole point of the widening recorded above.
    charged = [
        name for name, positional, _, _ in functions if positional > POSITIONAL_LIMIT
    ]
    assert len(charged) <= CEILING, (len(charged), sorted(charged))
