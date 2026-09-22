"""A live run, end to end: documents admitted, modules run, citations re-located.

Every link of this chain has its own test -- admission, route resolution, the
frontier loop, the provider, the proof -- and the live provider has answered a
single module (`test_module_execution.py`). Nothing drove the whole chain
against a model that really answers, so nothing showed the application working.
This does, with the provider built the way the application builds it: from the
environment: the price and ceiling from the worker's names, the model from
the test-only OpenRouter adapter (spec section 3.4), through the same
`caos.models.completions` seam production fills with the gateway.

Two documents, one per extractor, so the case holds a PDF as well as text. The
pathway is `LITE_EARNINGS_UPDATE` on `LITE_CREDIT_22` -- CP-0, CP-L10, CP-5 --
the canonical route (§41, §42): each module answers a vendor-validated Markdown
handoff for the host-owned subject `approve_run` pins, and the host anchors its
citations. Three calls, because a nightly job exists to prove the canonical
chain, not the catalog. `CAOS_LIVE_PROFILE` and `CAOS_LIVE_PATHWAY` name
another route on demand.

What is asserted is what the host can prove, never the model's wording: the run
finished, every pinned node was accepted with its host record, and the proof
re-derived every record and citation against the documents
(`caos/qualification/proof.py`). It skips with its reason without a
credential, and `CAOS_REQUIRE_PROVIDER=1` turns the skip into a failure.
"""

from __future__ import annotations

import json
import os
from decimal import Decimal, InvalidOperation
from pathlib import Path
from uuid import UUID

import pytest
from conftest import approve_run
from openrouter_adapter import KEY_ENV, MODEL, openrouter_chat_model
from test_pdf_extraction import minimal_pdf

from caos.blobs import BlobStore
from caos.boundary_text import BoundaryText
from caos.evidence.ingest import Document, admit_pack
from caos.graph.route import resolve_route
from caos.graph.runtime import Execution, run_route
from caos.methodology.bundle import Bundle
from caos.methodology.runner import ModuleProvider
from caos.models import completions
from caos.pricing import ModelPrice, price_from_environment
from caos.qualification.proof import assert_orchestration_proof
from caos.refusals import Refusal, RefusalCode
from caos.store import RunStatus, StoreConnection
from caos.store.budget import validate_spend
from caos.store.runs import run_status, start_run

VENDORED = Path(__file__).resolve().parents[1] / "vendor/deploy-v"
CATALOG = (
    VENDORED / "skills/cp-os-credit-os/references/CREDIT_OS_V_MODULE_CATALOG_v2.json"
)
PROFILE = os.environ.get("CAOS_LIVE_PROFILE", "LITE_CREDIT_22")
PATHWAY = os.environ.get("CAOS_LIVE_PATHWAY", "LITE_EARNINGS_UPDATE")
MODEL_PRICE = "CAOS_MODEL_PRICE"
LIVE_BUDGET_CEILING = "CAOS_LIVE_BUDGET_CEILING"

PROVIDER_REQUIRED = os.environ.get("CAOS_REQUIRE_PROVIDER") == "1"
_NO_CREDENTIAL = f"{KEY_ENV} is unset: there is no live provider"

# One line per block, so a quote is a phrase on one line of one block.
REPORT = b"""Acme Holdings plc annual report 2026
Revenue for the year ended 31 December 2026 was USD 2,815.0m
EBITDA for the year was USD 412.3m
Total debt at 31 December 2026 was USD 1,240.0m
Cash and equivalents stood at USD 310.5m
The revolving credit facility of USD 500.0m matures in June 2029
"""
STATEMENT = minimal_pdf(
    [
        "Acme Holdings plc lender update Q4 2026",
        "Net leverage fell to 2.3x from 2.9x a year earlier",
        "Interest cover was 5.1x for the year",
    ]
)


def _live_configuration(model: str) -> tuple[ModelPrice, Decimal]:
    """The live test uses the worker's dated price and an explicit run ceiling."""
    price = price_from_environment(model, os.environ.get(MODEL_PRICE, ""))
    try:
        ceiling = Decimal(os.environ.get(LIVE_BUDGET_CEILING, ""))
    except InvalidOperation:
        raise Refusal(RefusalCode.MONEY_INVALID) from None
    validate_spend(ceiling)
    if not ceiling:
        raise Refusal(RefusalCode.MONEY_INVALID)
    return price, ceiling


def test_live_configuration_uses_the_configured_price_and_ceiling(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        "CAOS_MODEL_PRICE", "a-model/for-the-test,0.000001,0.000004,2026-09-15"
    )
    monkeypatch.setenv("CAOS_LIVE_BUDGET_CEILING", "22.00")

    price, ceiling = _live_configuration("a-model/for-the-test")

    assert price.model == "a-model/for-the-test"
    assert ceiling == Decimal("22.00")


def test_live_configuration_refuses_a_zero_ceiling(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        "CAOS_MODEL_PRICE", "a-model/for-the-test,0.000001,0.000004,2026-09-15"
    )
    monkeypatch.setenv("CAOS_LIVE_BUDGET_CEILING", "0")

    with pytest.raises(Refusal, match=r"^MONEY_INVALID$"):
        _live_configuration("a-model/for-the-test")


@pytest.mark.live_provider
def test_a_live_run_admits_documents_and_completes_its_route(
    case: tuple[StoreConnection, UUID], tmp_path: Path
) -> None:
    try:
        chat = openrouter_chat_model()
    except RuntimeError:
        if PROVIDER_REQUIRED:
            pytest.fail(_NO_CREDENTIAL)
        pytest.skip(_NO_CREDENTIAL)

    conn, case_id = case
    price, ceiling = _live_configuration(MODEL)
    live = completions(price, chat=chat, endpoint=MODEL)
    blobs = BlobStore(tmp_path / "blobs")
    bundle = Bundle(root=VENDORED)
    catalog = json.loads(CATALOG.read_text(encoding="utf-8"))
    route = resolve_route(catalog, PROFILE, PATHWAY)

    # One pack: each document is read by the extractor its bytes call for.
    text = Document(filename=BoundaryText.of("report.txt"), data=REPORT)
    pdf = Document(filename=BoundaryText.of("statement.pdf"), data=STATEMENT)
    admit_pack(conn, blobs, case_id=case_id, documents=[text, pdf])
    run_id = start_run(conn, case_id, budget_ceiling=ceiling)
    conn.commit()
    approve_run(conn, case_id=case_id, run_id=run_id, route=route, bundle=bundle)
    conn.rollback()

    module_provider = ModuleProvider(
        conn=conn,
        bundle=bundle,
        blobs=blobs,
        completions=live,
        route=route,
        run_id=run_id,
    )
    run_route(
        conn,
        blobs,
        run_id=run_id,
        route=route,
        execution=Execution(
            module_provider,
            price,
            bundle,
        ),
    )

    assert run_status(conn, run_id) is RunStatus.COMPLETE
    # COMPLETE now means every pinned node was accepted (§39); the count says so
    # again from the proof's side.
    proof = assert_orchestration_proof(conn, blobs, bundle, run_id=run_id)
    assert proof.artifacts == len(route.nodes)

    producers = conn.execute(
        "SELECT model, generation_id, record_sha256 FROM artifacts WHERE run_id = %s",
        (run_id,),
    ).fetchall()
    assert {row[0] for row in producers} == {live.model}
    assert all(row[1] for row in producers), "a call left no handle for the bill"
    assert all(row[2] for row in producers), "an accepted node has no record"

    charges = conn.execute(
        "SELECT amount FROM budget_ledger WHERE run_id = %s", (run_id,)
    ).fetchall()
    assert len(charges) == len(route.nodes)
    assert all(isinstance(row[0], Decimal) and row[0] >= 0 for row in charges)
