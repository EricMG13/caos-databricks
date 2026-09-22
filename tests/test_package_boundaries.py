"""No module reaches into another package for a private name.

A leading underscore is this tree's statement that a name is the module's own
business. When another package imports one anyway, the promise is void in both
directions: the owner cannot change it, and the importer's dependency is
invisible to anyone reading the owning module's public surface. Within one
package the convention still holds -- neighbours are written together -- so
what is refused here is the reach across a package boundary.
"""

from __future__ import annotations

import ast
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def _package(module: str) -> str:
    return module.rsplit(".", 1)[0]


def _private_cross_package_imports() -> list[str]:
    found: list[str] = []
    for path in sorted((REPO / "caos").rglob("*.py")):
        module = ".".join(path.relative_to(REPO).with_suffix("").parts)
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.ImportFrom):
                continue
            imported = node.module or ""
            if not imported.startswith("caos.") or _package(imported) == _package(
                module
            ):
                continue
            found.extend(
                f"{module}:{node.lineno}: {imported}.{alias.name}"
                for alias in node.names
                if alias.name.startswith("_")
            )
    return found


def test_no_module_imports_a_private_name_across_a_package() -> None:
    assert _private_cross_package_imports() == []


def test_the_boundary_scan_reads_the_whole_server_tree() -> None:
    """A scan that scanned nothing is a failure, not a pass."""
    assert len(list((REPO / "caos").rglob("*.py"))) > 50
