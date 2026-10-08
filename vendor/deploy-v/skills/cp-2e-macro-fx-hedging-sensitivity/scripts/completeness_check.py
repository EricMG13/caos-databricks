#!/usr/bin/env python3
"""Check a drafted handoff against its own module's completeness contract.

Every SKILL.md carries the contract in its `## Output profile` block: which
registers are required, the exact columns of each, a minimum row count, and a
blocklist of cell values that disqualify a full run --

    - **critical_cell_values_casefold**: ; [insufficient information];
      insufficient information; n/a; tbd; unknown; not calculable from provided
      materials; not assessable; unavailable

Verifying that by reading means scanning every cell of every register against a
9-value blocklist, per run, while also holding the analysis in mind. That is the
worst possible use of attention: purely mechanical, unbounded in length, and
silently degrading -- a missed placeholder ships as a complete analysis.

The script reads the contract from the module's own SKILL.md, so it cannot
drift from it, and reports violations. It makes no analytical judgment: it
cannot tell whether a figure is RIGHT, only whether the register exists, has the
declared columns, has enough rows, and contains no disqualifying placeholder in
a column declared critical.

    python3 completeness_check.py --skill SKILL.md --handoff DRAFT.md

Exit 0 clean, 1 violations found, 2 could not run.
"""
import argparse
import os
import re
import sys

# Never leave bytecode inside a shipped skill folder. These scripts import a
# sibling (cp_tables), and Python writes __pycache__/*.pyc next to an imported
# module -- so running one from inside the distributed package pollutes the
# package itself, and any integrity check over the tree then reports drift
# against files the build never emitted. Same reason, same line, as the
# packaged CLIs (credit_os_v_cli.py, export_cp_model_v3.py).
sys.dont_write_bytecode = True

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from cp_tables import REGISTER_ID_RE, SEPARATOR_RE, TABLE_ID_RE, _row_cells, _split_row, parse_tables, read_tables  # noqa: E402
from validate_handoff import FrontmatterError, parse_restricted_frontmatter, unfenced_markdown  # noqa: E402

BULLET_RE = re.compile(r"^(?P<indent> *)- (?:\*\*(?P<key>[^*]+)\*\*:\s?)?(?P<value>.*)$")
PLACEHOLDERS = {"structured below", ""}
# An unkeyed bullet opening a nested mapping (one `semantic_rules` entry).
STRUCTURED_ITEM = "structured item"
IDENTICAL_TO_COLUMNS = "identical to columns"
# The two classes a profile's marker lists fall into. A fixture marker says the
# handoff is not real work and disqualifies a run; an evidence marker says the
# evidence is thin and is projected for a reader, never enforced here.
FIXTURE_KEYS = (
    ("fixture_limitation_flags", "fixture_flags"),
    ("fixture_validation_warnings", "fixture_warnings"),
    ("fixture_document_substrings_casefold", "fixture_substrings"),
)
EVIDENCE_KEYS = (
    ("frontmatter_limitation_flags", "evidence_flags"),
    ("frontmatter_validation_warnings", "evidence_warnings"),
    ("document_substrings_casefold", "evidence_substrings"),
)
DISQUALIFIER_BLOCKS = ("full_run_disqualifiers", "screening_run_disqualifiers")
PROJECTED_BLOCK = "projected_evidence_limitations"
SEMANTIC_RULE_KINDS = ("unique_columns", "required_values")
PROFILE_PREFIX = "## Output profile"
FENCE_RE = re.compile(r"^\s*(?:```|~~~)")


# --------------------------------------------------------------------------
# contract side: read the profile out of SKILL.md
# --------------------------------------------------------------------------

PROFILE_MODULE_RE = re.compile(
    r"^## Output profile\s*[—-]\s*binding on\s+(?P<module>CP-[A-Za-z0-9]+)", re.IGNORECASE)


def profile_bodies(skill_text):
    """{module_id_or_None: body} for every `## Output profile` section.

    One entry can carry more than one: cp-5-evidence-trace-validator serves both
    CP-5 and CP-5A and declares a profile for each, with DIFFERENT register sets
    (CP-5 owns T5B.*, CP-5A owns T5.* -- inverted from what the names suggest).

    An earlier version stopped at the first profile, so a CP-5A handoff was
    validated against CP-5's contract and reported all eight of its registers
    missing. Every CP-5A run would have failed its own QA step on a correct
    artifact.
    """
    out, module, body, capturing, in_fence = {}, None, [], False, False
    for line in skill_text.splitlines(keepends=True):
        if FENCE_RE.match(line):
            in_fence = not in_fence
        elif not in_fence and line.startswith("## "):
            if capturing:
                out[module] = "".join(body)
                body = []
            m = PROFILE_MODULE_RE.match(line.rstrip("\n"))
            capturing = line.startswith(PROFILE_PREFIX)
            module = m.group("module").upper() if (capturing and m) else None
            continue
        if capturing:
            body.append(line)
    if capturing:
        out[module] = "".join(body)
    return out


def _profile_body(skill_text, module_id=None):
    """The profile body for `module_id`, or the only one when there is one.

    With several profiles and no module_id, this raises rather than guessing:
    picking the first is exactly the bug this replaced, and silently validating
    against the wrong contract looks like a broken handoff, not a broken check.
    """
    bodies = profile_bodies(skill_text)
    if not bodies:
        return ""
    if module_id:
        key = module_id.strip().upper()
        if key in bodies:
            return bodies[key]
        raise ValueError(
            f"SKILL.md declares no `## Output profile` for {key}; it has "
            f"{sorted(k for k in bodies if k)}")
    if len(bodies) == 1:
        return next(iter(bodies.values()))
    raise ValueError(
        f"SKILL.md declares {len(bodies)} output profiles "
        f"({sorted(k for k in bodies if k)}); pass the handoff's module_id to "
        "select one -- validating against the wrong profile reports every "
        "register of the other module as missing")


def _parse_tree(lines):
    root = {}
    stack = [(-2, root, None)]
    for line in lines:
        m = BULLET_RE.match(line)
        if not m:
            continue
        indent = len(m.group("indent"))
        key = m.group("key")
        value = m.group("value").strip()
        while len(stack) > 1 and stack[-1][0] >= indent:
            stack.pop()
        parent = stack[-1][1]
        if key is None:
            if value == STRUCTURED_ITEM:
                item = {}
                parent.setdefault("_items", []).append(item)
                stack.append((indent, item, None))
            else:
                parent.setdefault("_items", []).append(value)
            continue
        node = {} if value in PLACEHOLDERS else {"_value": value}
        parent[key.strip()] = node
        stack.append((indent, node, key))
    return root


def _scalar(node):
    if not isinstance(node, dict):
        return node
    if "_value" in node:
        return node["_value"]
    items = node.get("_items")
    if items and len(items) == 1:
        return items[0]
    return None


def _list(node, *, keep_empty=False):
    raw = _scalar(node)
    if raw is None and isinstance(node, dict) and "_value" not in node and node.get("_items"):
        raw = ";".join(item for item in node.get("_items", []) if isinstance(item, str))
    if raw is None or raw.strip().casefold() == "none":
        return []
    return [p.strip() for p in raw.split(";") if keep_empty or p.strip()]


def _structured_items(node):
    """The nested mappings under a key, each opened by a `structured item` bullet."""
    if not isinstance(node, dict):
        return []
    return [item for item in node.get("_items", []) if isinstance(item, dict)]


def _semantic_rules(node):
    """`semantic_rules` as declared: one mapping per rule, list values split."""
    rules = []
    for item in _structured_items(node):
        rule = {key: _scalar(value) for key, value in item.items() if not key.startswith("_")}
        if "columns" in item:
            rule["columns"] = _list(item["columns"])
        if "values" in item:
            rule["values"] = _list(item["values"])
        rule["case_sensitive"] = str(rule.get("case_sensitive", "True")).strip().casefold() == "true"
        rules.append(rule)
    return rules


def module_id_of(handoff_text):
    """The handoff's own `module_id`, so the right profile is selected without
    the caller having to know an entry serves two modules."""
    m = re.search(r"^module_id:\s*[\"']?([A-Za-z0-9-]+)", handoff_text, re.MULTILINE)
    return m.group(1).upper() if m else None


def load_contract(skill_text, module_id=None):
    """{'registers': {id: {columns, critical_columns, min_rows, exempt}},
        'blocklist': set, 'substrings': list,
        'fixture_flags' | 'fixture_warnings' | 'fixture_substrings': list
            (the fixture markers, from every `*_disqualifiers` block; enforced),
        'evidence_flags' | 'evidence_warnings' | 'evidence_substrings': list
            (the thin-evidence markers under `projected_evidence_limitations`;
            projected for a reader and enforced by nothing here),
        'semantic_rules': [{rule_id, rule, register_id, ...}],
        'required_payload_fields': list (the payload contract's, for check_payload),
        'retired_registers': list (register IDs the module no longer writes, fork r7)}"""
    body = _profile_body(skill_text, module_id)
    if not body.strip():
        raise ValueError("SKILL.md has no `## Output profile` section")
    tree = _parse_tree(body.splitlines())
    completeness = tree.get("completeness_contract", {})
    # Beside `required_register_ids`: a register the module retired, whose
    # heading still keeps its table from prose in an older answer (fork r7).
    retired = _list(tree.get("appendix_contract", {}).get("retired_register_ids", {}))

    registers = {}
    for reg_id, node in completeness.get("required_registers", {}).items():
        if reg_id.startswith("_") or not isinstance(node, dict):
            continue
        columns = _list(node.get("columns", {}))
        crit_raw = _scalar(node.get("critical_columns", {}))
        if crit_raw and crit_raw.strip().casefold() == IDENTICAL_TO_COLUMNS:
            critical = list(columns)
        else:
            critical = _list(node.get("critical_columns", {}))
        min_rows_raw = _scalar(node.get("minimum_body_rows", {}))
        try:
            min_rows = int(min_rows_raw) if min_rows_raw else 0
        except ValueError:
            min_rows = 0
        registers[reg_id] = {
            "columns": columns,
            "critical_columns": critical,
            "minimum_body_rows": min_rows,
            "disqualifier_exempt_columns": _list(node.get("disqualifier_exempt_columns", {})),
        }

    disq = completeness.get("full_run_disqualifiers", {})
    blocklist = {v.casefold() for v in _list(disq.get("critical_cell_values_casefold", {}), keep_empty=True)}
    substrings = [v.casefold() for v in _list(disq.get("critical_cell_substrings_casefold", {}))]

    # Fixture markers from every disqualifier block the profile declares (a
    # screening-only module declares its own beside the full-run one), each
    # list de-duplicated in declaration order; substrings case-folded.
    markers = {}
    for declared, name in FIXTURE_KEYS:
        seen = []
        for block in DISQUALIFIER_BLOCKS:
            for value in _list(completeness.get(block, {}).get(declared, {})):
                value = value.casefold() if name.endswith("substrings") else value
                if value not in seen:
                    seen.append(value)
        markers[name] = seen
    projected = completeness.get(PROJECTED_BLOCK, {})
    for declared, name in EVIDENCE_KEYS:
        values = _list(projected.get(declared, {}))
        markers[name] = [v.casefold() for v in values] if name.endswith("substrings") else values

    stable_tables = _list(completeness.get("unconditional_stable_tables_cp_model", {}))
    payload = completeness.get("payload_contract", {})

    return {
        "registers": registers,
        "blocklist": blocklist,
        "substrings": substrings,
        **markers,
        "semantic_rules": _semantic_rules(completeness.get("semantic_rules", {})),
        "required_payload_fields": _list(payload.get("required_payload_fields", {})),
        "unconditional_stable_tables": stable_tables,
        "retired_registers": retired,
    }


# --------------------------------------------------------------------------
# artifact side: find registers in the drafted handoff
# --------------------------------------------------------------------------


# A heading whose first word is a register ID ("#### T4.7 Normalized
# Financials", "### **T4.7** ..."), fork r7.
LEADING_ID_RE = re.compile(r"#+\s*[*_]*\s*([PT][0-9][A-Za-z0-9.]*?|TL[0-9]+\.[0-9]+)\.?(?![A-Za-z0-9]|\.[A-Za-z0-9])")


def find_registers(handoff_text, register_ids=None, retired_ids=()):
    """{register_id: (header, [rows])} for pipe tables labelled with an ID.

    A register is located by its ID appearing in a heading or caption line
    within the few lines above the table -- which is how these artifacts are
    actually written ("### T4C.4 — Covenant headroom"). Where none of those
    four lines names a register, the nearest heading above the table, with no
    other table between, still does, at any distance (fork r6) -- but only for
    an ID no heading binds the near way.

    In the four-line window the table goes to a line that opens with an ID
    before one that only mentions one (fork r13), and within each, to the
    nearest heading before the nearest prose line (fork r2): under
    "**T4.4 — Income Statement**" and "Figures reconcile to T4.5." the table
    is T4.4.

    The first table bound keeps the ID, a near heading's before a distant
    one's, with one exception (fork r12, widened in r13): a table under a
    heading or caption that opens with the ID ("#### T4.4 — Income
    Statement", "**T4.4 — Income Statement**", or a snake_case register's
    title on a heading) takes it from a table bound by a line that only
    mentions the ID, prose ("The compact table below summarizes T4.4 ...")
    or heading ("### Bridge T4.4 to T4.5"), whatever their order. A table
    bound by a line that opens with the ID is never displaced, and a line
    that only mentions the ID displaces nothing.
    """
    return {reg_id: (header, rows) for reg_id, (header, rows, _) in
            _locate_registers(handoff_text, register_ids, retired_ids).items()}


def _locate_registers(handoff_text, register_ids=None, retired_ids=()):
    """`find_registers`, each table with its rows' own cell counts:
    {register_id: (header, [rows], [cell count per row])} (fork r13)."""
    id_re = REGISTER_ID_RE
    titles, title_re = {}, None
    if register_ids is not None:
        unique_ids = sorted(set(register_ids), key=lambda value: (-len(value), value))
        if not unique_ids:
            return {}
        alternatives = "|".join(
            re.escape(reg_id)
            for reg_id in unique_ids
        )
        # A sentence's full stop after an ID ("### T1. Input gate") ends it;
        # only a dot that continues the ID ("T1.2") does not (fork r1).
        id_re = re.compile(
            rf"(?<![A-Za-z0-9_.])({alternatives})(?![A-Za-z0-9_]|\.[A-Za-z0-9])"
        )
        titles = {
            reg_id.replace("_", " ").casefold(): reg_id
            for reg_id in unique_ids
            if "_" in reg_id and "." not in reg_id
        }
        if titles:
            # A snake_case register written under its title on a heading line
            # ("#### Company description" for company_description), fork r1.
            title_re = re.compile(
                r"(?<![A-Za-z0-9])("
                + "|".join(re.escape(title) for title in sorted(titles, key=len, reverse=True))
                + r")(?![A-Za-z0-9])",
                re.IGNORECASE,
            )
    retired_ids = set(retired_ids)

    def retired(head):
        led = LEADING_ID_RE.match(head)
        return bool(led) and led.group(1) in retired_ids

    title_of = {reg_id: title for title, reg_id in titles.items()}

    def opens_with(line, reg_id, marks):
        # The line's first word, past heading marks and `marks`, is the ID or,
        # on a heading, a snake_case register's title (fork r12).
        rest = re.sub(r"^#*\s*" + marks + r"*\s*", "", line)
        if re.match(re.escape(reg_id) + r"\.?(?![A-Za-z0-9_]|\.[A-Za-z0-9])", rest):
            return True
        title = title_of.get(reg_id) if line.startswith("#") else None
        return bool(title) and re.match(re.escape(title) + r"(?![A-Za-z0-9])", rest, re.IGNORECASE) is not None

    def led(line, reg_id):
        # A heading or caption opening with the ID past emphasis or a backtick
        # (fork r13: one test for both, as a caption's was in r12).
        return opens_with(line, reg_id, "[*_`]")

    def label_id(label):
        match = id_re.search(label)
        if match:
            return match.group(1)
        titled = title_re.search(label) if title_re and label.startswith("#") else None
        return titles[titled.group(1).casefold()] if titled else None

    lines = unfenced_markdown(handoff_text).splitlines()
    out, recent, heading, distant = {}, [], None, []
    mentioned = set()  # IDs held by a table a mere mention bound (fork r12, r13)

    def claim(reg_id, line, table):
        if reg_id not in out:
            out[reg_id] = table
            if not led(line, reg_id):
                mentioned.add(reg_id)
        elif reg_id in mentioned and led(line, reg_id):
            out[reg_id] = table
            mentioned.discard(reg_id)

    i = 0
    while i < len(lines):
        s = lines[i].strip()
        if s.startswith("|") and s.count("|") >= 2 and not SEPARATOR_RE.match(s):
            header = _split_row(s)
            j = i + 1
            if j < len(lines) and SEPARATOR_RE.match(lines[j].strip()) and "|" in lines[j]:
                j += 1
            rows, widths = [], []
            while j < len(lines):
                t = lines[j].strip()
                if not t.startswith("|"):
                    break
                # Split as the interface reader splits it (fork r6): an escaped
                # `\|` never shifts a cell into or out of a critical column.
                cells = _row_cells(t, len(header))
                widths.append(len(cells))
                cells += [""] * (len(header) - len(cells))
                rows.append(dict(zip(header, cells[:len(header)])))
                j += 1
            # A heading binds before a prose line that merely mentions an ID
            # ("reconciles to the T4.4 revenue base" under "### T4.5"), fork r2.
            heads = [s for s in reversed(recent) if s.startswith("#")]
            # A heading led by one of the module's retired IDs (CP-1's
            # "#### T4.7 Normalized Financials") is that register's: a prose
            # line never claims its table (fork r7). Any other heading,
            # whatever IDs it names ("Inputs (CP-1 T4.6)", "#### T4.18 Debt
            # (from CP-1)" in CP-1B, "### T4 — Statements"), leaves the prose.
            prose = [] if any(map(retired, heads)) else [s for s in reversed(recent) if not s.startswith("#")]
            named = [s for s in heads + prose if label_id(s)]
            # A line opening with its ID first, then the nearest heading
            # before the nearest prose line (fork r2, r13).
            line = next((s for s in named if led(s, label_id(s))), named[0] if named else None)
            table = (header, rows, widths)
            if line:
                claim(label_id(line), line, table)
            elif heading is not None and heading not in recent and label_id(heading):
                distant.append((label_id(heading), heading, table))
            i = j
            recent, heading = [], None
            continue
        if s:
            recent.append(s)
            recent = recent[-4:]
            heading = s if s.startswith("#") else heading
        i += 1
    for reg_id, line, table in distant:
        claim(reg_id, line, table)
    return out


# Contract column names as the host's models write them (fork r1): the same
# label up to case, emphasis, dash variants and spacing around "/", and a
# template column ("Period 1…N", "issuer-specific …") standing for the
# header cells no other contract column claims.
TEMPLATE_COLUMN_RE = re.compile(r"(?:\s1\s*(?:…|\.\.\.)\s*N\b|^issuer-specific\s)", re.IGNORECASE)


def _column_key(label):
    label = label.replace("`", "").replace("*", "")
    label = re.sub("[\u2012-\u2015\u2212]", "-", label)
    label = re.sub(r"\s*/\s*", "/", label)
    return re.sub(r"\s+", " ", label).strip().casefold()


def _resolve_columns(columns, header):
    """{contract column: [header cells]}; an empty list is a missing column."""
    keys = {}
    for cell in header:
        keys.setdefault(_column_key(cell), cell)
    resolved, claimed = {}, set()
    for column in columns:
        if TEMPLATE_COLUMN_RE.search(column):
            continue
        cell = column if column in header else keys.get(_column_key(column))
        if cell is None:
            cell = _containing_cell(column, header, claimed)
        resolved[column] = [cell] if cell is not None else []
        claimed.update(resolved[column])
    extra = [cell for cell in header if cell not in claimed]
    for column in columns:
        if TEMPLATE_COLUMN_RE.search(column):
            resolved[column] = extra
    return resolved


def _containing_cell(column, header, claimed):
    """The one unclaimed header cell whose words contain the contract column's
    words in order ("Source File Name" for "File Name"), or None when none or
    several do (fork r2): the method files spell many columns longer than the
    contract does."""
    words = _column_key(column).split()
    found = []
    for cell in header:
        if cell in claimed:
            continue
        have = _column_key(cell).split()
        if any(have[i:i + len(words)] == words for i in range(len(have) - len(words) + 1)):
            found.append(cell)
    return found[0] if len(found) == 1 else None


def _cell_violations(contract, reg_id, n, col, value):
    cell = value.casefold().strip()
    if cell in contract["blocklist"]:
        return [
            f"{reg_id} row {n}: critical column {col!r} holds a "
            f"disqualifying placeholder {value!r}"
        ]
    for sub in contract["substrings"]:
        if sub and sub in cell:
            return [
                f"{reg_id} row {n}: critical column {col!r} contains "
                f"disqualifying text {sub!r}"
            ]
    return []


def _padded(header, width, column):
    """Whether a row of `width` cells left `column` empty only by being short:
    the row's dict holds the value of the column's last header position."""
    return width < len(header) and len(header) - 1 - header[::-1].index(column) >= width


def _short_row(reg_id, n, col, width, columns):
    """The message for a critical cell a short row left empty (fork r13,
    N154): the row's cell count against the header's, so the model looks for
    the missing cell, not at a cell it did fill (LCR4 and LCR6 CP-3C were told
    "'Source Trace' holds a disqualifying placeholder ''" for a row whose
    source trace sat one column to the left)."""
    return (f"{reg_id} row {n}: critical column {col!r} is empty because the "
            f"row has {width} cells under a {columns}-cell header")


def _cell(row, column):
    """A row's cell for a contract column name, matched as `_column_key` does."""
    if column in row:
        return row[column]
    key = _column_key(column)
    return next((value for name, value in row.items() if _column_key(name) == key), "")


def check(skill_text, handoff_text, module_id=None):
    contract = load_contract(skill_text, module_id or module_id_of(handoff_text))
    located = _locate_registers(handoff_text, contract["registers"], contract["retired_registers"])
    present = {reg_id: (header, rows) for reg_id, (header, rows, _) in located.items()}
    violations = []

    for reg_id, spec in sorted(contract["registers"].items()):
        if reg_id not in present:
            violations.append(f"{reg_id}: required register missing from the handoff")
            continue
        header, rows, widths = located[reg_id]
        resolved = _resolve_columns(spec["columns"], header)
        if spec["columns"]:
            missing = [c for c in spec["columns"] if not resolved[c]]
            if missing:
                violations.append(f"{reg_id}: missing column(s) {missing}")
        if len(rows) < spec["minimum_body_rows"]:
            violations.append(
                f"{reg_id}: {len(rows)} body row(s), contract requires "
                f"{spec['minimum_body_rows']}"
            )
        exempt = set(spec["disqualifier_exempt_columns"])
        for n, (row, width) in enumerate(zip(rows, widths), 1):
            for col in spec["critical_columns"]:
                if col in exempt:
                    continue
                for actual in resolved.get(col) or ([col] if col in row else []):
                    found = _cell_violations(contract, reg_id, n, actual, row[actual])
                    if found and _padded(header, width, actual):
                        found = [_short_row(reg_id, n, actual, width, len(header))]
                    violations.extend(found)

    violations.extend(_semantic_violations(contract["semantic_rules"], present, contract["blocklist"]))
    violations.extend(_fixture_violations(contract, handoff_text))

    # Each malformed interface table is named alone, and the others are still
    # read (fork r6): one short row used to report every one of them missing.
    stable_tables, table_errors = read_tables(handoff_text)
    violations.extend(table_errors.values())
    titled = _register_titles(handoff_text, present)
    tagged = {m.group(1) for m in TABLE_ID_RE.finditer(handoff_text)}
    for table_id in contract["unconditional_stable_tables"]:
        if table_id not in stable_tables and table_id not in table_errors:
            violations.append(_missing_interface(table_id, titled, tagged))

    return violations, contract, present


def _name_key(words):
    """Letters and digits only, casefolded: `addback_validation_register` and
    `Add-Back Validation Register` are one key."""
    return "".join(re.findall(r"[0-9a-z]+", words.casefold()))


def _register_titles(handoff_text, present):
    """{title key: register ID} for each located register whose heading is led
    by its ID: "#### T4.12 — Model Comparator Register" is
    `modelcomparatorregister` (fork r11). A trailing parenthetical is not part
    of the title; the first heading of a key is kept."""
    out = {}
    for line in unfenced_markdown(handoff_text).splitlines():
        led = LEADING_ID_RE.match(line.strip())
        if not led or led.group(1) not in present:
            continue
        key = _name_key(re.sub(r"\([^()]*\)\s*$", "", line.strip()[led.end():]))
        if key:
            out.setdefault(key, led.group(1))
    return out


def _missing_interface(table_id, titled, tagged):
    """The message for an interface table no tag binds (fork r11). Where the
    handoff writes the register the table-id names -- its name part,
    `model_comparator_register`, is the title of a heading led by the
    register's ID, "T4.12 — Model Comparator Register" -- and the
    `<!-- table-id: -->` comment appears nowhere in it, the comment is what is
    missing, and the message says so: R1b's CP-1B was told four tables it had
    written were missing. With no such heading, or with the comment written
    but bound to no table, the table is missing."""
    reg_id = titled.get(_name_key(table_id.partition(".")[2]))
    if reg_id and table_id not in tagged:
        return f"`<!-- table-id: {table_id} -->` comment not found above the {reg_id} table"
    return (
        f"{table_id}: CP-MODEL interface table missing -- it is emitted on "
        "every run, not only when CP-MODEL was requested"
    )


def _leads_with(cell, value):
    """Whether `value` is `cell`'s leading word: `base case` and `base (lender
    view)` lead with `base`; `baseline` does not."""
    return bool(value) and re.match(rf"{re.escape(value)}(?:[\s(\-–—]|$)", cell) is not None


def _semantic_violations(rules, present, blocklist=frozenset()):
    """The profile's `semantic_rules`, each over one located register.

    The five kinds the profiles declare: `unique_columns` (no value repeats in
    any named column); `required_values` (every declared value appears in the
    column); `allowed_values` (every cell of the column is a declared value);
    `exact_values` (the column holds each declared value exactly once and
    nothing else); `at_least_one_row_populates` (some row fills every named
    column with a value that is not a disqualifying placeholder). Comparison
    is case-sensitive unless the rule says otherwise. A `required_values` rule
    declaring `match: leading_word` also finds a value as a cell's leading
    word, as the method writes it (`Base case` holds `base`), fork r3. A
    register the handoff lacks is already a violation above and is not judged
    twice; a rule kind this script does not implement is a violation, never a
    silent pass.
    """
    out = []
    for rule in rules:
        reg_id, rule_id, kind = rule.get("register_id"), rule.get("rule_id"), rule.get("rule")
        if reg_id not in present:
            continue
        _, rows = present[reg_id]
        # A value written in backticks or bold is the same value (fork r2).
        fold = (lambda v: v.strip().strip("`*").strip()) if rule.get("case_sensitive", True) else (lambda v: v.strip().strip("`*").strip().casefold())
        col = rule.get("column")
        values = [fold(v) for v in rule.get("values", [])]
        cells = [fold(_cell(row, col)) for row in rows] if col else []
        if kind == "unique_columns":
            for column in rule.get("columns", []):
                seen = set()
                for row in rows:
                    cell = fold(_cell(row, column))
                    if cell in seen:
                        out.append(f"{reg_id}: {rule_id} -- column {column!r} repeats {cell!r}")
                        break
                    seen.add(cell)
        elif kind == "required_values":
            leading = str(rule.get("match", "")).strip().casefold() == "leading_word"
            for value in rule.get("values", []):
                want = fold(value)
                if not any(cell == want or (leading and _leads_with(cell, want)) for cell in cells):
                    out.append(f"{reg_id}: {rule_id} -- column {col!r} lacks {value!r}")
        elif kind == "allowed_values":
            for n, cell in enumerate(cells, 1):
                if cell not in values:
                    out.append(f"{reg_id} row {n}: {rule_id} -- column {col!r} holds "
                               f"{cell!r}, not one of the allowed values")
                    break
        elif kind == "exact_values":
            if sorted(cells) != sorted(values):
                out.append(f"{reg_id}: {rule_id} -- column {col!r} must hold exactly "
                           f"{rule.get('values', [])!r} once each")
        elif kind == "at_least_one_row_populates":
            columns = rule.get("columns", [])
            if not any(all(_cell(row, c).strip() and _cell(row, c).strip().casefold() not in blocklist
                           for c in columns) for row in rows):
                out.append(f"{reg_id}: {rule_id} -- no row populates every one of {columns!r}")
        else:
            out.append(f"{reg_id}: {rule_id} -- semantic rule kind {kind!r} is not implemented")
    return out


# What a line may carry around a fixture marker written alone on it: heading,
# quote and list marks before it, emphasis or a backtick around it, and a
# closing full stop, colon, semicolon or exclamation mark (fork r13).
FIXTURE_LINE_MARKS_RE = re.compile(r"^(?:[#>\s]+|[-*+](?=\s)|[0-9]+[.)](?=\s))*")


def _bare_line(line):
    """A line as a fixture marker written alone on it reads: its marks, its
    emphasis and its closing punctuation dropped, spacing collapsed,
    casefolded."""
    text = FIXTURE_LINE_MARKS_RE.sub("", line.strip()).strip("*_` \t")
    text = text.rstrip(".:;!").strip("*_` \t")
    return re.sub(r"\s+", " ", text).casefold()


def _front_matter_text(value):
    """Every string value of the front matter, list items and nested values
    included, one per line."""
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        value = list(value.values())
    if isinstance(value, list):
        return "\n".join(_front_matter_text(item) for item in value)
    return ""


def _fixture_violations(contract, handoff_text):
    """The fixture markers: a front-matter flag or warning naming one, or one
    of the declared substrings in a front-matter value or written alone on an
    unfenced line ("Integration fixture.", "- **synthetic test input**").

    Fork r13: a substring anywhere in the body no longer counts, so prose that
    denies it ("not an integration fixture or synthetic test input") is not a
    marker.

    The front matter is read with the shared restricted parser; a handoff with
    none (or one the parser refuses, which validate_handoff.py reports on its
    own) declares no flags and is judged on its lines alone.
    """
    out = []
    try:
        fields, _ = parse_restricted_frontmatter(handoff_text)
    except FrontmatterError:
        fields = {}
    for field, name in (("limitation_flags", "fixture_flags"),
                        ("validation_warnings", "fixture_warnings")):
        declared = fields.get(field)
        for flag in (declared if isinstance(declared, list) else []):
            if isinstance(flag, str) and flag in contract[name]:
                out.append(f"{field} declares the fixture marker {flag!r}")
    declared = _front_matter_text(fields).casefold()
    lines = {_bare_line(line) for line in unfenced_markdown(handoff_text).splitlines()}
    for sub in contract["fixture_substrings"]:
        if sub and (sub in declared or sub in lines):
            out.append(f"document contains the fixture marker text {sub!r}")
    return out


def check_payload(skill_text, payload, module_id=None):
    """Violations of the profile's `payload_contract.required_payload_fields`
    over a module's JSON payload object: every declared field must be present
    under `runtime_output`. The canonical Markdown handoff carries no payload,
    so this judges the payload alone and never the Markdown."""
    contract = load_contract(skill_text, module_id or (payload or {}).get("module_id"))
    runtime = payload.get("runtime_output") if isinstance(payload, dict) else None
    if not contract["required_payload_fields"]:
        return []
    if not isinstance(runtime, dict):
        return ["payload has no runtime_output object"]
    return [f"runtime_output lacks the required payload field {field!r}"
            for field in contract["required_payload_fields"] if field not in runtime]


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--skill", default="SKILL.md", help="the module's SKILL.md (the contract)")
    ap.add_argument("--handoff", required=True, help="the drafted canonical Markdown handoff")
    ap.add_argument("--module", help="module_id to select an output profile; only needed when the "
                                     "entry serves several and the handoff omits module_id")
    args = ap.parse_args(argv)

    try:
        with open(args.skill, encoding="utf-8") as fh:
            skill_text = fh.read()
        with open(args.handoff, encoding="utf-8") as fh:
            handoff_text = fh.read()
        violations, contract, present = check(skill_text, handoff_text, args.module)
    except (OSError, ValueError) as exc:
        print(f"completeness_check: cannot run -- {exc}", file=sys.stderr)
        return 2

    if not contract["registers"]:
        print("completeness_check: contract declares no registers -- nothing verified",
              file=sys.stderr)
        return 2

    if violations:
        print(f"completeness_check: FAIL ({len(violations)})")
        for v in violations:
            print(f"  - {v}")
        return 1
    print(f"completeness_check: PASS ({len(contract['registers'])} registers, "
          f"{len(present)} found in handoff)")
    return 0


def _self_check():
    skill = """
## Output profile — binding on CP-X's canonical Markdown

- **completeness_contract**: structured below
  - **full_run_disqualifiers**: structured below
    - **critical_cell_substrings_casefold**: source-limited; integration fixture
    - **critical_cell_values_casefold**: ; n/a; tbd; unknown
  - **required_registers**: structured below
    - **T1.1**: structured below
      - **columns**: Item; Value; Evidence ID
      - **critical_columns**: identical to columns
      - **disqualifier_exempt_columns**: none
      - **minimum_body_rows**: 2
  - **unconditional_stable_tables_cp_model**: cpx.model_register

## Companions
"""
    good = """
### T1.1 — Findings
| Item | Value | Evidence ID |
| --- | --- | --- |
| Leverage | 4.2x | E1 |
| Coverage | 2.1x | E2 |

<!-- table-id: cpx.model_register -->
| a |
| --- |
| 1 |
"""
    v, contract, _ = check(skill, good)
    assert v == [], v
    assert contract["registers"]["T1.1"]["critical_columns"] == ["Item", "Value", "Evidence ID"]

    # a blocklisted placeholder in a critical column
    bad = good.replace("| 4.2x |", "| tbd |")
    v, _, _ = check(skill, bad)
    assert any("disqualifying placeholder" in x for x in v), v

    # a short row names its width, not only the critical cell it left empty (fork r13)
    v, _, _ = check(skill, good.replace("| Coverage | 2.1x | E2 |", "| Coverage | 2.1x |"))
    assert v == ["T1.1 row 2: critical column 'Evidence ID' is empty because the row has 2 cells "
                 "under a 3-cell header"], v
    v, _, _ = check(skill, good.replace("| Coverage | 2.1x | E2 |", "| Coverage | 2.1x | |"))
    assert v == ["T1.1 row 2: critical column 'Evidence ID' holds a disqualifying placeholder ''"], v

    # too few rows
    v, _, _ = check(skill, good.replace("| Coverage | 2.1x | E2 |\n", ""))
    assert any("body row" in x for x in v), v

    # missing column
    v, _, _ = check(skill, good.replace("| Item | Value | Evidence ID |",
                                        "| Item | Value |", 1))
    assert any("missing column" in x for x in v), v

    # missing register entirely
    v, _, _ = check(skill, "no tables here\n")
    assert any("required register missing" in x for x in v), v

    # CP-MODEL interface table absent
    v, _, _ = check(skill, good.replace("<!-- table-id: cpx.model_register -->", ""))
    assert any("CP-MODEL interface table missing" in x for x in v), v

    # substring disqualifier
    v, _, _ = check(skill, good.replace("| 4.2x |", "| source-limited estimate |"))
    assert any("disqualifying text" in x for x in v), v

    # the fixture markers disqualify; the thin-evidence markers are projected only
    split = skill.replace(
        "    - **critical_cell_values_casefold**: ; n/a; tbd; unknown\n",
        "    - **critical_cell_values_casefold**: ; n/a; tbd; unknown\n"
        "    - **fixture_document_substrings_casefold**: integration fixture\n"
        "    - **fixture_limitation_flags**: INTEGRATION_FIXTURE_ONLY\n"
        "    - **fixture_validation_warnings**: PRESENTATION_FIXTURE\n"
        "  - **projected_evidence_limitations**: structured below\n"
        "    - **document_substrings_casefold**: source-limited\n"
        "    - **frontmatter_limitation_flags**: SOURCE_LIMITED_NOT_COMMITTEE_READY\n"
        "    - **frontmatter_validation_warnings**: structured below\n"
        "      - FULL_UNDERWRITING_SOURCE_SET_NOT_RETAINED\n",
    )
    c = load_contract(split)
    assert c["fixture_flags"] == ["INTEGRATION_FIXTURE_ONLY"], c
    assert c["fixture_warnings"] == ["PRESENTATION_FIXTURE"], c
    assert c["fixture_substrings"] == ["integration fixture"], c
    assert c["evidence_flags"] == ["SOURCE_LIMITED_NOT_COMMITTEE_READY"], c
    assert c["evidence_warnings"] == ["FULL_UNDERWRITING_SOURCE_SET_NOT_RETAINED"], c
    assert c["evidence_substrings"] == ["source-limited"], c
    honest = ("---\nmodule_id: CP-X\nlimitation_flags:\n  - SOURCE_LIMITED_NOT_COMMITTEE_READY\n"
              "validation_warnings: []\n---\nA source-limited screen.\n" + good)
    v, _, _ = check(split, honest)
    assert v == [], v
    fixture = honest.replace("SOURCE_LIMITED_NOT_COMMITTEE_READY", "INTEGRATION_FIXTURE_ONLY")
    v, _, _ = check(split, fixture)
    assert v == ["limitation_flags declares the fixture marker 'INTEGRATION_FIXTURE_ONLY'"], v
    v, _, _ = check(split, honest.replace("validation_warnings: []", "validation_warnings:\n  - PRESENTATION_FIXTURE"))
    assert v == ["validation_warnings declares the fixture marker 'PRESENTATION_FIXTURE'"], v
    # a marker written alone on a line, or in a front-matter value; prose that
    # only names it is not one (fork r13)
    marker = ["document contains the fixture marker text 'integration fixture'"]
    for line in ("Integration fixture.", "> **Integration Fixture**", "- `integration fixture`"):
        v, _, _ = check(split, honest.replace("A source-limited screen.", line))
        assert v == marker, (line, v)
    v, _, _ = check(split, honest.replace("validation_warnings: []",
                                          'validation_warnings: []\nnotes: "Built from an Integration Fixture pack."'))
    assert v == marker, v
    for line in ("An Integration Fixture.", "The pack is issuer filings, not an integration fixture."):
        v, _, _ = check(split, honest.replace("A source-limited screen.", line))
        assert v == [], (line, v)
    v, _, _ = check(split, honest.replace("A source-limited screen.", "```\nintegration fixture\n```"))
    assert v == [], v

    # semantic rules over a located register; an unknown kind never passes silently
    ruled = skill.replace(
        "  - **unconditional_stable_tables_cp_model**: cpx.model_register\n",
        "  - **semantic_rules**: structured below\n"
        "    - structured item\n"
        "      - **columns**: Item\n"
        "      - **register_id**: T1.1\n"
        "      - **rule**: unique_columns\n"
        "      - **rule_id**: cpx.items_unique\n"
        "    - structured item\n"
        "      - **case_sensitive**: True\n"
        "      - **column**: Item\n"
        "      - **register_id**: T1.1\n"
        "      - **rule**: required_values\n"
        "      - **rule_id**: cpx.coverage_present\n"
        "      - **values**: Leverage; Coverage\n"
        "  - **unconditional_stable_tables_cp_model**: cpx.model_register\n",
    )
    c = load_contract(ruled)
    assert [r["rule_id"] for r in c["semantic_rules"]] == ["cpx.items_unique", "cpx.coverage_present"], c
    assert c["semantic_rules"][1]["values"] == ["Leverage", "Coverage"], c
    v, _, _ = check(ruled, good)
    assert v == [], v
    v, _, _ = check(ruled, good.replace("| Coverage | 2.1x | E2 |", "| Leverage | 2.1x | E2 |"))
    assert v == ["T1.1: cpx.items_unique -- column 'Item' repeats 'Leverage'",
                 "T1.1: cpx.coverage_present -- column 'Item' lacks 'Coverage'"], v
    v, _, _ = check(ruled, good.replace("| Coverage |", "| coverage |"))
    assert v == ["T1.1: cpx.coverage_present -- column 'Item' lacks 'Coverage'"], v
    # a rule declaring `match: leading_word` finds its value as a cell's leading word (fork r3)
    leading = ruled.replace("      - **case_sensitive**: True\n      - **column**: Item\n",
                            "      - **case_sensitive**: False\n      - **column**: Item\n      - **match**: leading_word\n")
    assert leading != ruled
    v, _, _ = check(leading, good.replace("| Leverage |", "| Leverage ratio |")
                    .replace("| Coverage |", "| coverage (interest) |"))
    assert v == [], v
    v, _, _ = check(leading, good.replace("| Coverage |", "| Coverages |"))
    assert v == ["T1.1: cpx.coverage_present -- column 'Item' lacks 'Coverage'"], v
    v, _, _ = check(ruled.replace("      - **rule**: unique_columns\n", "      - **rule**: novel_rule\n"), good)
    assert v == ["T1.1: cpx.items_unique -- semantic rule kind 'novel_rule' is not implemented"], v
    assert load_contract(skill)["semantic_rules"] == []
    enumerated = skill.replace(
        "  - **unconditional_stable_tables_cp_model**: cpx.model_register\n",
        "  - **semantic_rules**: structured below\n"
        "    - structured item\n"
        "      - **case_sensitive**: True\n"
        "      - **column**: Item\n"
        "      - **register_id**: T1.1\n"
        "      - **rule**: exact_values\n"
        "      - **rule_id**: cpx.items_exact\n"
        "      - **values**: structured below\n"
        "        - Leverage\n"
        "        - Coverage\n"
        "    - structured item\n"
        "      - **case_sensitive**: False\n"
        "      - **column**: Evidence ID\n"
        "      - **register_id**: T1.1\n"
        "      - **rule**: allowed_values\n"
        "      - **rule_id**: cpx.evidence_enum\n"
        "      - **values**: e1; e2\n"
        "    - structured item\n"
        "      - **columns**: Item; Value\n"
        "      - **register_id**: T1.1\n"
        "      - **rule**: at_least_one_row_populates\n"
        "      - **rule_id**: cpx.has_valued_row\n"
        "  - **unconditional_stable_tables_cp_model**: cpx.model_register\n",
    )
    assert load_contract(enumerated)["semantic_rules"][0]["values"] == ["Leverage", "Coverage"]
    v, _, _ = check(enumerated, good)
    assert v == [], v
    v, _, _ = check(enumerated, good.replace("| Coverage | 2.1x | E2 |", "| Coverage | 2.1x | E2 |\n| Margin | 3 | E1 |"))
    assert v == ["T1.1: cpx.items_exact -- column 'Item' must hold exactly ['Leverage', 'Coverage'] once each"], v
    v, _, _ = check(enumerated, good.replace("| E2 |", "| E9 |"))
    assert v == ["T1.1 row 2: cpx.evidence_enum -- column 'Evidence ID' holds 'e9', not one of the allowed values"], v
    v, _, _ = check(enumerated, good.replace("| 4.2x |", "| tbd |").replace("| 2.1x |", "| n/a |"))
    assert "T1.1: cpx.has_valued_row -- no row populates every one of ['Item', 'Value']" in v, v

    # the payload contract is judged over a payload object, never the Markdown
    paid = skill.replace(
        "  - **unconditional_stable_tables_cp_model**: cpx.model_register\n",
        "  - **payload_contract**: structured below\n"
        "    - **required_payload_fields**: structured below\n"
        "      - screen_status\n"
        "      - upgrade_plan\n"
        "  - **unconditional_stable_tables_cp_model**: cpx.model_register\n",
    )
    assert load_contract(paid)["required_payload_fields"] == ["screen_status", "upgrade_plan"]
    assert check_payload(paid, {"runtime_output": {"screen_status": 1, "upgrade_plan": 2}}) == []
    assert check_payload(paid, {"runtime_output": {"screen_status": 1}}) == [
        "runtime_output lacks the required payload field 'upgrade_plan'"]
    assert check_payload(paid, {}) == ["payload has no runtime_output object"]
    assert check_payload(skill, {}) == []
    v, _, _ = check(paid, good)
    assert v == [], v

    # an entry serving two modules: the profile is chosen by the handoff's own
    # module_id, and an ambiguous request raises instead of picking the first
    two = """
## Output profile — binding on CP-5's canonical Markdown

- **completeness_contract**: structured below
  - **required_registers**: structured below
    - **T5B.1**: structured below
      - **columns**: A; B
      - **minimum_body_rows**: 1
  - **full_run_disqualifiers**: structured below
    - **critical_cell_values_casefold**: ; tbd

## Output profile — binding on CP-5A's canonical Markdown

- **completeness_contract**: structured below
  - **required_registers**: structured below
    - **T5.1**: structured below
      - **columns**: A; B
      - **minimum_body_rows**: 1
  - **full_run_disqualifiers**: structured below
    - **critical_cell_values_casefold**: ; tbd

## Companions
"""
    assert sorted(k for k in profile_bodies(two)) == ["CP-5", "CP-5A"], profile_bodies(two)
    assert sorted(load_contract(two, "CP-5")["registers"]) == ["T5B.1"]
    assert sorted(load_contract(two, "CP-5A")["registers"]) == ["T5.1"]
    try:
        load_contract(two)
    except ValueError as exc:
        assert "select one" in str(exc), exc
    else:
        raise AssertionError("ambiguous profile must raise, not pick the first")

    cp5a_handoff = ("---\nmodule_id: CP-5A\n---\n\n### T5.1 — r\n\n| A | B |\n"
                    "| --- | --- |\n| x | y |\n")
    assert module_id_of(cp5a_handoff) == "CP-5A"
    v, c, _ = check(two, cp5a_handoff)
    assert sorted(c["registers"]) == ["T5.1"], c["registers"]
    assert v == [], v

    print("completeness_check self-check: OK")


if __name__ == "__main__":
    if "--self-check" in sys.argv:
        _self_check()
    else:
        raise SystemExit(main())
