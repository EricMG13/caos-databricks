#!/usr/bin/env python3
"""The one source for the bundle's own variable defaults (N23).

`databricks.yml` states the endpoint, price, run ceiling and both group
names once, as `variables.<name>.default`; the deploy scripts and the
loopback stub read them back from here rather than repeating the values by
hand. No YAML parser: the same small, line-oriented reading
`scripts/check_gate_config.py` already uses on this file's other blocks,
so nothing here can read a default a real YAML parser would not, and
nothing new is added to the dependency closet for it.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
# The names every copy repeats, in the bundle's own spelling.
NAMES = ("model_endpoint", "model_price", "run_ceiling", "group_admin", "group_analyst")
_ENTRY = re.compile(r"  (\w+):\s*")
_DEFAULT = re.compile(r'\s+default:\s*"?([^"\n]*?)"?\s*')


def _variables(text: str) -> dict[str, str]:
    """Each `variables:` entry's own `default:`, read the way
    `check_gate_config._sync_lists` reads the bundle's other blocks: no
    nesting past one variable's scalar default, which is all any copy needs."""
    block = text.partition("\nvariables:\n")[2].partition("\nresources:\n")[0]
    found: dict[str, str] = {}
    name = ""
    for line in block.splitlines():
        if (entry := _ENTRY.fullmatch(line)) is not None:
            name = entry.group(1)
        elif name and (value := _DEFAULT.fullmatch(line)) is not None:
            found[name] = value.group(1)
            name = ""
    return found


def defaults(root: Path = REPO) -> dict[str, str]:
    """`databricks.yml`'s own defaults for every name in `NAMES` it states."""
    variables = _variables((root / "databricks.yml").read_text(encoding="utf-8"))
    return {name: variables[name] for name in NAMES if name in variables}


def main(argv: list[str] | None = None) -> int:
    """`--shell` prints each default as a bash default-assignment (`: "${NAME:=value}"`,
    upper-cased), so a wrapper can `eval` them without overriding a value the
    caller already exported; anything else prints `name=value`, one a line."""
    args = sys.argv[1:] if argv is None else argv
    shell = "--shell" in args
    for name, value in defaults().items():
        if shell:
            print(f': "${{{name.upper()}:={value}}}"')
        else:
            print(f"{name}={value}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
