"""The bundle's own handoff validators, run from verified bytes (§29, §41).

Deploy V ships standard-library Python that decides whether a canonical Markdown
handoff conforms: the restricted front-matter parser, the six-heading and
register checks, and the routed-invocation envelope. The vendor code is the
conformance authority, so the host calls it rather than re-implementing it.

It is loaded from `verified_bytes`, never imported from the tree: an ordinary
import would read whatever sits on disk now, add the scripts directory to
`sys.path` (two vendor modules do so at import), and write `__pycache__` into
the vendored bundle. Each load compiles the verified bytes into fresh, privately
named modules whose `import` statements resolve only to one another; `sys` is a
shim, so the vendor's own path and bytecode settings touch nothing global. The
private names are present in `sys.modules` only while a load runs, because
`dataclasses` reads a class's module there.

Vendor messages can quote the document; callers map results to typed refusal
codes and never pass a vendor message on.
"""

from __future__ import annotations

import builtins
import json
import re
import sys
import threading
import types
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any
from uuid import uuid4

from caos.methodology.bundle import Bundle, verified_bytes
from caos.refusals import Refusal, RefusalCode

VENDOR_MODULE = "CP-OS"
MODULE_CATALOG = "references/CREDIT_OS_V_MODULE_CATALOG_v2.json"
_AUTHORITY_BUNDLE = "references/CREDIT_OS_V_AUTHORITY_BUNDLE_v2.json"
_SCRIPTS = "scripts/"
_FILES = {
    "validate_handoff": "validate_handoff.py",
    "cp_tables": "cp_tables.py",
    "completeness_check": "completeness_check.py",
    "credit_os": "credit_os/__init__.py",
    "credit_os.identity": "credit_os/identity.py",
    "credit_os_v": "credit_os_v/__init__.py",
    "credit_os_v.identity": "credit_os_v/identity.py",
    "credit_os_v.envelope": "credit_os_v/envelope.py",
    "credit_os_v.routing": "credit_os_v/routing.py",
    "credit_os_v.research": "credit_os_v/research.py",
    "credit_os_v.handoffs": "credit_os_v/handoffs.py",
    "credit_os_v.navigation": "credit_os_v/navigation.py",
}
# One load at a time: the private names briefly occupy `sys.modules`.
_LOCK = threading.Lock()


@dataclass(frozen=True, slots=True)
class VendorContract:
    """The vendor modules the adapter calls, each from verified bytes."""

    validate_handoff: Any
    completeness_check: Any
    envelope: Any
    navigation: Any
    routing: Any
    # `credit_os_v.research`: the brief validator and the dossier validator
    # (§96). The host binds a brief and hands it over; it re-implements no rule.
    research: Any
    # `cp_tables`: the reader of a handoff's tagged tables, the one the
    # completeness checker imports, and the figure and null rules its cells
    # are read by (`caos.methodology.tables`).
    cp_tables: Any


# One compiled contract per manifest, shared by every caller of `cached_contract`.
_CONTRACTS: dict[str, VendorContract] = {}
_CONTRACTS_LOCK = threading.Lock()


class _Sys:
    """`sys` as vendor code sees it: its own path and flags, everything else real."""

    def __init__(self) -> None:
        self.path: list[str] = []
        self.dont_write_bytecode = True

    # ponytail: `modules`, `meta_path` and the rest stay real. The loaded files
    # touch only `path` and the bytecode flag; `credit_os_v/reconcile.py` calls
    # `importlib` and so must never join `_FILES`.
    def __getattr__(self, name: str) -> object:
        return getattr(sys, name)


class _Loader:
    def __init__(self, bundle: Bundle) -> None:
        self.bundle = bundle
        self.prefix = f"_caos_vendor_{uuid4().hex}"
        self.modules: dict[str, types.ModuleType] = {}
        self.sys = _Sys()

    def load(self, name: str) -> types.ModuleType:
        if name in self.modules:
            return self.modules[name]
        if name not in _FILES:
            raise ImportError(name)
        relative = _SCRIPTS + _FILES[name]
        source = verified_bytes(self.bundle, VENDOR_MODULE, relative)
        package = name if relative.endswith("__init__.py") else name.rpartition(".")[0]
        module = types.ModuleType(f"{self.prefix}.{name}")
        path = str(self.bundle.root / "skills/cp-os-credit-os" / relative)
        module.__dict__.update(
            __file__=path,
            __package__=package,
            __builtins__={**builtins.__dict__, "__import__": self._import},
        )
        if package == name:
            module.__path__ = []
        self.modules[name] = module
        sys.modules[module.__name__] = module
        code = compile(source, path, "exec", dont_inherit=True)
        exec(code, module.__dict__)  # nosec B102
        if "." in name:
            parent, _, child = name.rpartition(".")
            setattr(self.load(parent), child, module)
        return module

    def _import(
        self,
        name: str,
        globals: Mapping[str, Any] | None = None,
        locals: Mapping[str, Any] | None = None,
        fromlist: tuple[str, ...] | list[str] = (),
        level: int = 0,
    ) -> object:
        if level:
            base = str((globals or {}).get("__package__") or "")
            for _ in range(level - 1):
                base = base.rpartition(".")[0]
            name = f"{base}.{name}" if name else base
        elif name == "sys":
            return self.sys
        elif name.split(".")[0] not in {n.split(".")[0] for n in _FILES}:
            return builtins.__import__(name, globals, locals, fromlist, level)
        parts = name.split(".")
        for index in range(1, len(parts) + 1):
            self.load(".".join(parts[:index]))
        leaf = self.modules[name]
        for item in fromlist or ():
            if f"{name}.{item}" in _FILES:
                self.load(f"{name}.{item}")
        return leaf if fromlist or level else self.modules[parts[0]]


def catalog(bundle: Bundle) -> dict[str, Any]:
    """The bundle's verified module catalog, or `AUTHORITY_BYTES_MISMATCH`.

    Here rather than beside either caller: the run command resolves its route
    from this catalog and the canonical adapter executes against it, and a copy
    each is two readings of the one authority invariant 4 names. The command
    may not import the adapter at all
    (`test_command_modules_import_no_runtime_provider_or_transport`), so the
    shared reading lives with the bytes it verifies.
    """
    try:
        loaded = json.loads(verified_bytes(bundle, VENDOR_MODULE, MODULE_CATALOG))
    except ValueError:
        loaded = None
    if not isinstance(loaded, dict):
        raise Refusal(RefusalCode.AUTHORITY_BYTES_MISMATCH)
    return loaded


def load_vendor_contract(bundle: Bundle) -> VendorContract:
    """The vendor validators from this bundle's verified bytes.

    Refuses `AUTHORITY_BYTES_MISMATCH` (through `verified_bytes`) when any vendor
    file has moved. Leaves `sys.path`, `sys.modules`, the import hooks and the
    bytecode flag exactly as it found them.
    """
    loader = _Loader(bundle)
    with _LOCK:
        try:
            return VendorContract(
                validate_handoff=loader.load("validate_handoff"),
                completeness_check=loader.load("completeness_check"),
                envelope=loader.load("credit_os_v.envelope"),
                navigation=loader.load("credit_os_v.navigation"),
                routing=loader.load("credit_os_v.routing"),
                research=loader.load("credit_os_v.research"),
                cp_tables=loader.load("cp_tables"),
            )
        finally:
            for module in loader.modules.values():
                sys.modules.pop(module.__name__, None)


def cached_contract(bundle: Bundle) -> VendorContract:
    """`load_vendor_contract`, compiled once per manifest digest for the process.

    The manifest pins every vendor file's hash, so one manifest names one
    contract; a file changed on disk under an unchanged manifest is the case
    the ledger records (the executor's prompt still reads every delivered byte).
    """
    key = bundle.manifest_sha256
    with _CONTRACTS_LOCK:
        if key not in _CONTRACTS:
            _CONTRACTS[key] = load_vendor_contract(bundle)
        return _CONTRACTS[key]


def authority_bundle_sha256(bundle: Bundle) -> str:
    """The vendor's own authority digest, the value its envelopes are built over.

    Distinct from the host's `authority_digest`: this is the identity the vendor
    declares for its bundle, read from verified bytes, never computed here.
    """
    try:
        declared = json.loads(verified_bytes(bundle, VENDOR_MODULE, _AUTHORITY_BUNDLE))
        value = declared["authority_bundle_sha256"]
    except (ValueError, KeyError, TypeError):
        value = None
    if not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{64}", value) is None:
        raise Refusal(RefusalCode.AUTHORITY_BYTES_MISMATCH)
    return value
