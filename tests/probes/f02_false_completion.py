"""Reproduce F02 without a provider call or a normal-suite failure.

Run from the repository root with CAOS_TEST_POSTGRES_URL set. The probe creates
and drops a UUID-named database and runs the canonical LITE route (CP-0 ->
CP-L10 -> CP-5) through the real runtime, answered by the deterministic
`CanonicalCompletions` fixture -- never a live model. CP-0's T8 register marks
CP-L10 BLOCKED, so CP-L10 is never called and the run must end BLOCKED. It
prints `stored_status=BLOCKED`; exit 1 means F02 regressed (a false COMPLETE).
"""

from __future__ import annotations

import os
import sys
import tempfile
from decimal import Decimal
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit
from uuid import uuid4

import psycopg

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "tests"))

from canonical_fixtures import (  # noqa: E402
    CATALOG,
    LITE_PROFILE,
    LITE_SELECTION,
    QUOTE,
    VENDORED,
    CanonicalCompletions,
    fields_from_prompt,
)
from conftest import approve_run, priced  # noqa: E402

from caos.blobs import BlobStore  # noqa: E402
from caos.boundary_text import BoundaryText  # noqa: E402
from caos.evidence.ingest import Document, admit_pack  # noqa: E402
from caos.graph.route import resolve_route  # noqa: E402
from caos.graph.runtime import Execution, run_route  # noqa: E402
from caos.methodology.bundle import Bundle  # noqa: E402
from caos.methodology.runner import ModuleProvider  # noqa: E402
from caos.store import RunStatus, apply_schema, connect  # noqa: E402
from caos.store.runs import create_case, run_status, start_run  # noqa: E402


def _url_for(base: str, database: str) -> str:
    return urlunsplit(urlsplit(base)._replace(path=f"/{database}"))


def main() -> None:
    base = os.environ["CAOS_TEST_POSTGRES_URL"]
    database = f"caos_test_{uuid4().hex}"
    route = resolve_route(CATALOG, LITE_PROFILE, LITE_SELECTION)

    with psycopg.connect(base, autocommit=True) as admin:
        admin.execute(f'CREATE DATABASE "{database}"')
    try:
        with (
            tempfile.TemporaryDirectory() as tmp,
            connect(_url_for(base, database)) as conn,
        ):
            apply_schema(conn)
            case_id = create_case(conn, BoundaryText.of("F02 isolated probe"))
            blobs = BlobStore(Path(tmp) / "blobs")
            [source_id] = admit_pack(
                conn,
                blobs,
                case_id=case_id,
                documents=[
                    Document(
                        filename=BoundaryText.of("f02.txt"),
                        data=QUOTE.encode() + b" was USD 1,240.0m\n",
                    )
                ],
            )
            run_id = start_run(conn, case_id)
            conn.commit()
            bundle = Bundle(VENDORED)
            approve_run(
                conn, case_id=case_id, run_id=run_id, route=route, bundle=bundle
            )

            # The answers state the price the run executes at (N15).
            price = priced(Decimal("0.01"))
            answers = CanonicalCompletions(
                source_id, readiness={"CP-L10": "BLOCKED"}, price=price
            )
            provider = ModuleProvider(conn, bundle, blobs, answers, route, run_id)
            run_route(
                conn,
                blobs,
                run_id=run_id,
                route=route,
                execution=Execution(provider, price, bundle),
            )
            status = run_status(conn, run_id)
            accepted_row = conn.execute(
                "SELECT count(*) FROM artifacts WHERE run_id = %s", (run_id,)
            ).fetchone()
            assert accepted_row is not None
            accepted = accepted_row[0]
            print(
                f"stored_status={status.value} "
                f"accepted_nodes={accepted}/{len(route.nodes)} "
                f"calls={len(answers.prompts)}"
            )
            assert status is RunStatus.BLOCKED, (
                "F02: blocked downstream nodes wrongly allowed terminal COMPLETE"
            )
            assert accepted < len(route.nodes)
            called_modules = {
                str(fields_from_prompt(prompt)["module_id"])
                for prompt in answers.prompts
            }
            assert "CP-L10" not in called_modules, (
                "F02: CP-L10 must never be called once CP-0 marks it BLOCKED"
            )
    finally:
        with psycopg.connect(base, autocommit=True) as admin:
            admin.execute(f'DROP DATABASE IF EXISTS "{database}" WITH (FORCE)')


if __name__ == "__main__":
    main()
