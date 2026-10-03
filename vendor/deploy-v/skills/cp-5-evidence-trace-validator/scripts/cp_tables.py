#!/usr/bin/env python3
"""Parse the tagged Markdown tables that carry data between CP modules.

Canon bans JSON as an analytical artifact (CP_AB_EXPORT_SPEC gate E4: "No
lettered appendices, embedded JSON, export manifest, extraction envelope,
JSONL, database"), so every handoff is Markdown. That is not an obstacle to
scripting it: registers are pipe tables with locked column orders, and the ones
consumed downstream carry an explicit identity comment:

    <!-- table-id: cp1.model_period_register -->
    | period_id | period_type | ... |
    | --- | --- | ... |
    | FY2024 | fiscal_year | ... |

This module is the read side of that contract. It uses only stdlib and the
sibling handoff validator shipped with every consuming skill.

Null discipline matches canon: a missing value is None, never 0 and never "".
Canon is explicit that null is not zero, and the whole point of moving
arithmetic into scripts is lost if the parser quietly coerces an absent figure
into a number that then flows into a ratio.
"""
import math
import re
import sys

sys.dont_write_bytecode = True
from validate_handoff import unfenced_markdown

TABLE_ID_RE = re.compile(r"<!--\s*table-id:\s*([A-Za-z0-9_.]+)\s*-->")
SEPARATOR_RE = re.compile(r"^[\s:\-|]+$")
# A separator cell is one or more hyphens, optionally colon-aligned (fork r6:
# it was three or more, which GitHub's own tables do not require).
SEPARATOR_CELL_RE = re.compile(r":?-+:?")
# A heading (### to ######) between a tag and its table, fork r6.
TAG_HEADING_RE = re.compile(r"#{3,6}(?:\s.*)?")

# Cell spellings that mean "no value". Canon's own vocabulary, casefolded.
NULL_CELLS = {
    "", "-", "\u2014", "\u2013", "n/a", "na", "none", "null", "not applicable",
    "not disclosed", "not assessable", "not calculable", "tbd", "unknown",
    "insufficient information", "[insufficient information]",
    "not calculable from provided materials", "unavailable",
}


def _split_row(line):
    return [c.strip() for c in line.strip().removeprefix("|").removesuffix("|").split("|")]


def _escaped_row(line):
    """A row split only at a `|` not escaped as `\\|`, each `\\|` read as `|`,
    as the handoff validator's `_table_cells` splits it."""
    stripped = line.strip().removeprefix("|")
    if stripped.endswith("|") and not stripped.endswith("\\|"):
        stripped = stripped[:-1]
    return [c.strip().replace("\\|", "|") for c in re.split(r"(?<!\\)\|", stripped)]


def _row_cells(line, width):
    """A tagged table's body row: split at every `|` as before, or, only when
    that gives a width other than the header's, at the unescaped ones (fork
    r6). A row read before is read the same."""
    cells = _split_row(line)
    if len(cells) == width:
        return cells
    escaped = _escaped_row(line)
    return escaped if len(escaped) == width else cells


def is_null(cell):
    return cell is None or str(cell).strip().casefold() in NULL_CELLS


class AmbiguousFigure(ValueError):
    """A figure whose decimal separator cannot be determined from the text."""


def _finite_figure(value, where):
    try:
        number = float(value)
    except (ValueError, OverflowError) as exc:
        raise ValueError(f"{where}: value must be a finite number") from exc
    if not math.isfinite(number):
        raise ValueError(f"{where}: value must be a finite number")
    return number


# `1,234.56` (Anglo) and `1.234,56` (continental) are both unambiguous: the
# separator that appears LAST is the decimal one. `5,2` is not -- it is 5.2 in
# continental notation and a malformed thousands group in Anglo notation, and
# the two readings differ by 10x.
_ANGLO_THOUSANDS = re.compile(r"^\d{1,3}(,\d{3})+(\.\d+)?$")
_CONTINENTAL = re.compile(r"^\d{1,3}(\.\d{3})+(,\d+)?$")
_AMBIGUOUS_COMMA = re.compile(r"^\d+,\d{1,2}$")
# The spaces a figure may carry between digit groups, each stripped alike.
_DIGIT_GROUP_SPACES = str.maketrans("", "", "\u00a0\u2009\u202f ")


def parse_figure(cell, where="value"):
    """Parse a figure, or return None for a recognised null.

    Raises AmbiguousFigure rather than guessing when the decimal separator is
    undeterminable. A credit package covering EUR issuers will meet `5,2` meaning
    5.2x; stripping commas as thousands separators turns that into 52.0 -- a 10x
    error, on a leverage multiple, that looks like an ordinary number. Refusing
    is the only safe reading: the caller knows the source's notation and this
    function does not.

    Percent convention: a trailing `%` is stripped and the figure stays in
    percentage points -- `10.4%` reads 10.4, never 0.104. CP-MODEL's `_number`
    (cp-model/scripts/validate_cp_model_inputs.py) reads the same cell as 0.104,
    a fraction; the two readers are not interchangeable and neither is changed
    while their callers disagree. The scripts that take a fraction here
    (covenant_headroom `percentage`, rate_fx_sensitivity `adverse_move_pct`,
    bond_analytics `recovery_assumption`) refuse a value above 1, so a `%` cell
    reaches them as a refusal, not a 100x misreading.

    Digit-group spaces -- the no-break space U+00A0, the thin space U+2009 and
    the narrow no-break space U+202F -- are stripped like an ordinary space
    (deployment fork r3: the thin space was the one left in). A nonzero figure
    whose exponent is outside float's normal range (`1e-400`) is refused rather
    than underflowed to 0.0 or a denormal.
    """
    if is_null(cell):
        return None
    if isinstance(cell, bool):
        raise ValueError(f"{where}: boolean is not a figure")
    if isinstance(cell, (int, float)):
        return _finite_figure(cell, where)

    s = str(cell).strip()
    negative = s.startswith("(") and s.endswith(")")
    if negative:
        s = s[1:-1].strip()
    # Strip only KNOWN decorations -- currency symbols, thin/non-breaking
    # spaces, a multiple's trailing x, a trailing percent. Deliberately not
    # "remove every non-digit": that turns prose like "roughly 5" or "5 to 6"
    # into a confident 5.0, which is worse than refusing the cell.
    core = s.translate(_DIGIT_GROUP_SPACES)
    core = re.sub(r"^[€$£¥₹]|[€$£¥₹]$", "", core)
    core = re.sub(r"[xX]$", "", core)
    core = re.sub(r"%$", "", core)
    if not re.fullmatch(r"[-+]?[0-9][0-9.,]*(?:[eE][-+]?[0-9]+)?", core):
        raise ValueError(f"{where}: {cell!r} is not a figure")
    if core.count(",") and core.count("."):
        if core.rfind(",") > core.rfind("."):
            if not _CONTINENTAL.match(core.lstrip("-+")):
                raise AmbiguousFigure(f"{where}: {cell!r} mixes ',' and '.' in an unrecognised pattern")
            core = core.replace(".", "").replace(",", ".")
        else:
            if not _ANGLO_THOUSANDS.fullmatch(core.lstrip("-+")):
                raise AmbiguousFigure(f"{where}: {cell!r} mixes ',' and '.' in an unrecognised pattern")
            core = core.replace(",", "")
    elif "," in core:
        body = core.lstrip("-+")
        if _AMBIGUOUS_COMMA.match(body):
            raise AmbiguousFigure(
                f"{where}: {cell!r} is ambiguous -- ',' before 1-2 digits is a decimal "
                "separator in continental notation (5,2 = 5.2) and a malformed thousands "
                "group in Anglo notation (5,2 -> 52). Supply the figure as a number, or "
                "normalise the notation at the source"
            )
        if _ANGLO_THOUSANDS.match(body):
            core = core.replace(",", "")
        else:
            raise AmbiguousFigure(f"{where}: {cell!r} uses ',' in an unrecognised pattern")

    value = _finite_figure(core, where)
    if abs(value) < sys.float_info.min and re.search(r"[1-9]", re.split(r"[eE]", core)[0]):
        raise ValueError(f"{where}: {cell!r} has an exponent outside the range a figure is read in")
    return -value if negative else value


def to_number(cell):
    """Lenient wrapper: returns None where parse_figure would raise on shape,
    but still refuses to guess an ambiguous decimal separator."""
    try:
        return parse_figure(cell)
    except AmbiguousFigure:
        raise
    except ValueError:
        return None


class Table:
    __slots__ = ("table_id", "columns", "rows")

    def __init__(self, table_id, columns, rows):
        self.table_id = table_id
        self.columns = columns
        self.rows = rows  # list of dict: column -> raw cell string

    def column(self, name):
        return [r.get(name) for r in self.rows]

    def numbers(self, name):
        return [to_number(r.get(name)) for r in self.rows]

    def __len__(self):
        return len(self.rows)

    def __repr__(self):
        return f"<Table {self.table_id} cols={len(self.columns)} rows={len(self.rows)}>"


def parse_tables(text):
    """{table_id: Table} for every `<!-- table-id: -->`-tagged pipe table.

    A tag binds to the next pipe table that follows it. Untagged tables are
    ignored -- they are presentation tables, not the machine interface. Any
    malformed tagged table refuses the whole document (ValueError naming the
    first): a reader of the interface never gets a partial set.
    """
    tables, errors = read_tables(text)
    if errors:
        raise ValueError(next(iter(errors.values())))
    return tables


def _table_lines(lines, i):
    """The index past the pipe lines that start at `i`."""
    while i < len(lines) and lines[i].strip().startswith("|"):
        i += 1
    return i


def _read_table(table_id, lines, i):
    """(Table or None, error or None, index past the table) for the table
    whose header row is `lines[i]`, its separator the next line and its body
    the pipe lines after that. A malformed table's pipe lines are consumed
    too, so none is left over for the next tag."""
    header = _split_row(lines[i])
    if not all(header) or len(header) != len(set(header)):
        return None, f"{table_id}: table columns must be nonempty and unique", _table_lines(lines, i)
    if i + 1 >= len(lines) or len(_split_row(lines[i + 1])) != len(header) or not all(
        SEPARATOR_CELL_RE.fullmatch(cell) for cell in _split_row(lines[i + 1])
    ):
        return None, f"{table_id}: missing or malformed table separator", _table_lines(lines, i)
    end = _table_lines(lines, i + 2)
    rows, bad = [], []
    for n, line in enumerate(lines[i + 2:end], 1):
        cells = _row_cells(line, len(header))
        if len(cells) != len(header):
            bad.append((n, cells))
            continue
        rows.append(dict(zip(header, cells)))
    if bad:
        n, cells = bad[0]
        more = f"; {len(bad) - 1} more row(s) differ" if len(bad) > 1 else ""
        return None, (
            f"{table_id}: row {n} (first cell `{cells[0][:40]}`) has {len(cells)} cells, "
            f"header has {len(header)} -- table row width differs from its header{more}"
        ), end
    return Table(table_id, header, rows), None, end


def read_tables(text):
    """({table_id: Table}, {table_id: error}) -- `parse_tables`, reporting.

    Each malformed tagged table is named once, with its first fault, and left
    out; every other tagged table is still read (fork r6: one short row used
    to void all of them, so a checker reported every interface table missing).
    The binding is `parse_tables`'s: a tag binds to the next pipe table, across
    blank and comment lines; a heading line (### to ######) between them is
    crossed too (fork r6), but only as a tolerance -- a tag bound across a
    heading binds only a well-formed table, never an id another tag binds or
    a second tag crosses to, and is otherwise dropped as before, so every
    document read before reads the same. Any other line between a tag and a table breaks the bind;
    better to report the table as absent than to attach the tag to an
    unrelated table further down.
    """
    lines = unfenced_markdown(text).splitlines()
    strict, crossed_reads, errors = {}, {}, {}
    pending_id, crossed = None, False
    i = 0
    while i < len(lines):
        stripped = lines[i].strip()
        m = TABLE_ID_RE.fullmatch(stripped)
        if m:
            if pending_id is not None and not crossed:
                errors.setdefault(pending_id, f"{pending_id}: table-id has no following table")
            pending_id, crossed = m.group(1), False
            if pending_id in strict:
                errors.setdefault(pending_id, f"{pending_id}: duplicate table-id")
                pending_id = None
            i += 1
            continue
        if pending_id and stripped.startswith("|") and stripped.count("|") >= 2:
            table, error, i = _read_table(pending_id, lines, i)
            if not crossed:
                if error:
                    errors.setdefault(pending_id, error)
                else:
                    strict[pending_id] = (i, table)
            elif table is not None:
                # Two tags crossing to two tables of one id bind neither.
                crossed_reads[pending_id] = None if pending_id in crossed_reads else (i, table)
            pending_id = None
            continue
        if pending_id and TAG_HEADING_RE.fullmatch(stripped):
            crossed = True
        elif stripped and not stripped.startswith("<!--"):
            pending_id = pending_id if stripped.startswith("|") else None
        i += 1
    if pending_id is not None and not crossed:
        errors.setdefault(pending_id, f"{pending_id}: table-id has no following table")
    found = dict(strict)
    for table_id, read in crossed_reads.items():
        if read is not None and table_id not in strict and table_id not in errors:
            found[table_id] = read
    in_order = sorted(found.items(), key=lambda item: item[1][0])
    return {table_id: table for table_id, (_, table) in in_order}, errors


def read_frontmatter(text):
    """The YAML envelope as a flat {key: raw string}. Deliberately not a YAML
    parser: the envelope is flat scalars and simple lists, and taking a
    dependency for that would stop these scripts being drop-in."""
    if not text.startswith("---"):
        return {}
    end = text.find("\n---", 3)
    if end == -1:
        return {}
    out = {}
    for line in text[3:end].splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if ":" not in line or line.startswith((" ", "\t", "-")):
            continue
        key, _, value = line.partition(":")
        out[key.strip()] = value.strip().strip('"').strip("'")
    return out
