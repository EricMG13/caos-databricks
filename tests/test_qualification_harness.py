"""The harness: a qualification set performed, not merely compared.

`docs/REBUILD_PLAN.md` Phase 10 names three things — "the qualification-set
harness, the answer keys, the matrix". The keys and the matrix landed first and
`build_matrix` had to be handed a `runs` mapping it could not produce, because
`QualificationSet` modelled only half of what `CONTEXT.md` says a set is: "the
immutable **cases** and answer keys". A case is its inputs. Without them there
is nothing to perform.

So a case now carries its documents and the route it is run under, alongside the
citations a correct run must produce, and `perform` admits each case, runs it,
and hands the matrix the mapping it used. The set's digest covers the inputs
too — two sets with identical answer keys over different documents are different
sets, and a verdict binding one must not read as binding the other.

What the harness must not become: a second execution path. It calls `run_route`
like every other caller, through the same provider seam, under the same
reservations. A qualification run that took a shortcut would be qualifying a
system nobody ships.

And what only the harness can report. `assert_orchestration_proof` proves the
artifacts a run **accepted** -- true, and narrower than "the route ran". The
harness resolved and pinned the route, so it holds the node list the proof is
silent about: a `Performed` carries the run's own status and the pinned nodes
that produced nothing. That is only observable on a run that stopped short,
which is why a case whose execution refuses is recorded rather than raised --
recorded, not swallowed, in a typed field beside the proof.
"""

from __future__ import annotations

import json
import re
import unicodedata
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field, replace
from decimal import Decimal
from pathlib import Path
from urllib.parse import urlsplit
from uuid import UUID, uuid4

import psycopg
import pytest
from canonical_fixtures import LITE_PROFILE, LITE_SELECTION, CanonicalCompletions
from conftest import every_block, priced, route_fault, tamper
from fake_chat import fake_completions
from test_gates import _approval

from caos.blobs import BlobStore
from caos.boundary_text import BoundaryText
from caos.evidence.ingest import Document
from caos.graph.route import NodeState
from caos.methodology.bundle import Bundle
from caos.provider import Completion, encode_request
from caos.qualification.harness import (
    Attempted,
    Harness,
    Performed,
    PerformedSet,
    PreparedCase,
    Unrun,
    _provider_identity,
    perform,
    prepare,
)
from caos.qualification.matrix import (
    ExpectedCitation,
    ExpectedProjection,
    ExpectedRegister,
    QualificationCase,
    QualificationSet,
    assert_measurable,
    qualification_set_digest,
)
from caos.qualification.proof import OrchestrationProof
from caos.refusals import Refusal, RefusalCode
from caos.store import RunStatus, StoreConnection
from caos.store.budget import CEILING
from caos.store.gates import Gate, approve_gate
from caos.store.members import Standing, grant
from caos.store.run_inputs import RunSubject
from caos.store.runs import run_status

REPO = Path(__file__).resolve().parents[1]
VENDORED = REPO / "vendor/deploy-v"
CATALOG = json.loads(
    (
        VENDORED / "skills/cp-os-credit-os/references"
        "/CREDIT_OS_V_MODULE_CATALOG_v2.json"
    ).read_text(encoding="utf-8")
)
PROFILE = LITE_PROFILE
SELECTION = LITE_SELECTION
SUBJECT = RunSubject("ACME", "Acme Holdings plc", "FY2026", "2026-09-13")
L10, CP5 = f"RN-{PROFILE}-{SELECTION}-02-CP-L10", f"RN-{PROFILE}-{SELECTION}-03-CP-5"


def test_gateway_qualification_identity_names_endpoint_effort_and_ceiling() -> None:
    """D8: the profile a verdict binds is the endpoint, the effort actually
    sent (`none` until N2 lands) and the completion ceiling; a double names
    its own `provider`; a bare object names nothing and is refused."""
    assert _provider_identity(fake_completions(model="m")) == "databricks/m/none/65536"
    assert _provider_identity(_Completions()) == "qualification-test"
    with pytest.raises(Refusal, match=r"^RUN_INPUT_INVALID$"):
        _provider_identity(object())


ESTIMATE = Decimal("0.50")
# Enough for any set these tests build: the per-run ceiling times ten.
SET_CEILING = CEILING * 10

# The whole report line a handoff cites (N28).
QUOTE = "Total debt at 31 December 2026 was USD 1,240.0m"
REPORT = b"""Acme Holdings plc annual report 2026
Total debt at 31 December 2026 was USD 1,240.0m
"""
OTHER = b"""Borealis Industries plc annual report 2026
Total debt at 31 December 2026 was USD 880.0m
"""


@dataclass
class _Completions:
    """Answers every module with a canonical handoff, cited to what it was given.

    Deliberately not told which source to cite: it reads the prompt the host
    built, which is what makes the run a real one rather than a rehearsal.
    """

    prompts: list[str] = field(default_factory=list)
    # How a case stops part-way. One numbered call rather than "everything
    # after n", because a `Harness` holds one provider for the whole set: a
    # refusal that latched would refuse every later case too, and a set that
    # carried on would be indistinguishable from one that stopped at the first.
    refuses_call: int | None = None

    # What the host configured; with fallbacks off it is what answers.
    model: str = "a-model/for-the-test"
    provider: str = "qualification-test"
    qa_by_module: dict[str, str] = field(default_factory=dict)

    def request_bytes(self, prompt: str, *, json_object: bool = False) -> bytes:
        return encode_request(self.model, prompt, json_object=json_object)

    def complete(self, prompt: str, *, json_object: bool = False) -> Completion:
        self.prompts.append(prompt)
        if len(self.prompts) == self.refuses_call:
            return Completion(None, None, None, RefusalCode.PROVIDER_UNAVAILABLE)
        # The evidence section is last, so its source is the last one named,
        # and the debt line it shows is the whole line the answer cites (N28).
        source_id = re.findall(r"^source_id: (\S+)$", prompt, re.MULTILINE)[-1]
        line = re.findall(r"^Total debt at 31 December 2026 .*$", prompt, re.MULTILINE)
        return CanonicalCompletions(
            UUID(source_id),
            generation_id="gen-harness-test",
            qa_by_module=self.qa_by_module,
            quotes=(),
            cited=((UUID(source_id), line[-1] if line else QUOTE),),
        ).complete(prompt, json_object=json_object)


@dataclass
class _DamagesWhatWasAccepted:
    """Corrupts the artifact the run already accepted, then stops.

    A blob damaged between two nodes rather than after the run, so the bytes
    `perform` itself reads are the damaged ones. `path_of` is public for
    exactly this: proving a mismatch refusal means damaging a blob through the
    real filesystem.
    """

    conn: StoreConnection
    blobs: BlobStore
    inner: _Completions

    @property
    def model(self) -> str:
        """Whatever it wraps. A double that invented its own identity would
        record a producer no test had asked for."""
        return self.inner.model

    @property
    def provider(self) -> str:
        return self.inner.provider

    # What to damage on the second call. Two shapes of a store that moved
    # under a running set, and `perform` must survive both.
    loses_the_pin: bool = False
    target: tuple[str, UUID] | None = None

    def request_bytes(self, prompt: str, *, json_object: bool = False) -> bytes:
        return self.inner.request_bytes(prompt, json_object=json_object)

    def complete(self, prompt: str, *, json_object: bool = False) -> Completion:
        if not self.inner.prompts:
            return self.inner.complete(prompt, json_object=json_object)
        if self.loses_the_pin:
            # Committed, because this stands for another process moving the
            # store: `perform` rolls back the transaction the refusal leaves
            # open, and an uncommitted delete would simply come back.
            assert self.target is not None
            with _without_route(self.conn, *self.target):
                pass
        else:
            for [digest] in self.conn.execute("SELECT artifact_sha256 FROM artifacts"):
                self.blobs.path_of(str(digest)).write_bytes(b"not an envelope")
            self.conn.rollback()
        return Completion(None, None, None, RefusalCode.PROVIDER_UNAVAILABLE)


@contextmanager
def _without_route(conn: StoreConnection, database: str, run: UUID) -> Iterator[None]:
    assert database == "caos_test_" + UUID(database.removeprefix("caos_test_")).hex
    assert conn.info.transaction_status.name == "IDLE"
    query = (
        "SELECT t.tgname, t.tgenabled FROM pg_trigger t"
        " JOIN pg_constraint c ON c.oid=t.tgconstraint"
        " WHERE c.contype='f' AND c.conrelid='run_inputs'::regclass"
        " AND c.confrelid='run_routes'::regclass AND t.tgrelid=c.confrelid"
        " ORDER BY t.tgname"
    )
    with conn.transaction():
        assert conn.execute("SELECT current_database()").fetchone() == (database,)
        triggers = conn.execute(query).fetchall()
        assert len(triggers) == 2 and all(state == "O" for _, state in triggers)
        with route_fault(conn):
            for name, _ in triggers:
                conn.execute(
                    psycopg.sql.SQL("ALTER TABLE run_routes DISABLE TRIGGER {}").format(
                        psycopg.sql.Identifier(name)
                    )
                )
            assert (
                conn.execute("DELETE FROM run_routes WHERE run_id=%s", (run,)).rowcount
                == 1
            )
            yield
            for name, _ in triggers:
                conn.execute(
                    psycopg.sql.SQL("ALTER TABLE run_routes ENABLE TRIGGER {}").format(
                        psycopg.sql.Identifier(name)
                    )
                )
        assert conn.execute(query).fetchall() == triggers
        assert conn.execute(
            "SELECT tgenabled FROM pg_trigger WHERE tgrelid='run_routes'::regclass"
            " AND tgname='route_immutable'"
        ).fetchone() == ("O",)


def _approve(
    conn: StoreConnection,
    prepared: tuple[PreparedCase, ...],
    gates: tuple[Gate, ...] = tuple(Gate),
) -> tuple[UUID, ...]:
    actors = tuple(uuid4() for _ in prepared)
    for item, actor in zip(prepared, actors, strict=True):
        grant(
            conn, case_id=item.input.case_id, user_id=actor, standing=Standing.APPROVER
        )
        conn.commit()
        for gate in gates:
            approval = _approval(conn, item.input.run_id, actor, gate)
            conn.rollback()
            approve_gate(conn, approval)
    return actors


def _case(label: str, data: bytes, *, quote: str | None = None) -> QualificationCase:
    """A case keyed on the document's debt line, the whole line its answer
    cites (N28), unless told another."""
    from hashlib import sha256

    if quote is None:
        lines = [line for line in data.decode().splitlines() if "Total debt" in line]
        quote = lines[0] if lines else QUOTE

    return QualificationCase(
        label=label,
        documents=(Document(filename=BoundaryText.of("report.txt"), data=data),),
        profile_id=PROFILE,
        selection_id=SELECTION,
        expects=(
            ExpectedCitation(
                module_id="CP-0",
                document_sha256=sha256(data).hexdigest(),
                matched_text=quote,
            ),
        ),
        subject=SUBJECT,
    )


def _count(conn: StoreConnection, sql: str) -> int:
    """One number from the store. `fetchone` is nullable; a test that indexed it
    blind would crash where it meant to assert."""
    row = conn.execute(sql).fetchone()
    assert row is not None
    return int(row[0])


def _perform(
    conn: StoreConnection,
    blobs: BlobStore,
    qualification: QualificationSet,
    *,
    ceiling: Decimal = SET_CEILING,
    completions: _Completions | None = None,
) -> PerformedSet:
    harness = Harness(
        bundle=Bundle(root=VENDORED),
        catalog=CATALOG,
        completions=completions or _Completions(),
        price=priced(ESTIMATE),
        ceiling=ceiling,
    )
    prepared = prepare(conn, blobs, harness, qualification=qualification)
    _approve(conn, prepared)
    return perform(
        conn,
        blobs,
        harness,
        qualification=qualification,
        prepared=prepared,
    )


def test_the_harness_performs_every_case_and_reports_one_row_each(
    empty_database: str, tmp_path: Path
) -> None:
    """The deliverable: a set goes in, a matrix comes out, nothing in between is
    the caller's to wire.

    Two cases over different documents, so a harness that ran one and reported
    two, or admitted both into one case, fails rather than passing on a set too
    small to tell the difference.
    """
    from caos.store import apply_schema, connect

    with connect(empty_database) as conn:
        apply_schema(conn)
        conn.commit()
        blobs = BlobStore(tmp_path / "blobs")
        qualification = QualificationSet(
            cases=(_case("acme-2026", REPORT), _case("borealis-2026", OTHER))
        )

        performed = _perform(conn, blobs, qualification)
        matrix = performed.matrix
        assert matrix is not None, "a set that finished has a matrix"

        assert matrix.qualification_set_sha256 == qualification_set_digest(
            qualification
        )
        assert [row.case_label for row in matrix.rows] == [
            "acme-2026",
            "borealis-2026",
        ]
        for row in matrix.rows:
            assert row.proven is True, row.refusal
            assert row.missed == ()
            assert len(row.met) == 1
        assert [record.unrun for record in performed.performed] == [(), ()]
        # Each case is its own case row and its own run: a harness that reused
        # one would let one case's evidence answer another's key.
        assert _count(conn, "SELECT count(*) FROM cases") == 2
        runs = conn.execute("SELECT run_id FROM runs").fetchall()
        assert len(runs) == 2
        for [run_id] in runs:
            assert run_status(conn, UUID(str(run_id))) is RunStatus.COMPLETE
        assert conn.execute(
            "SELECT p.complete,count(e.evidence_sha256)"
            " FROM qualification_performed p LEFT JOIN qualification_evidence e"
            " USING (performed_sha256) GROUP BY p.complete"
        ).fetchall() == [(True, 1)]


def test_the_harness_runs_through_the_same_loop_as_everything_else(
    empty_database: str, tmp_path: Path
) -> None:
    """Not a second execution path.

    A qualification run that skipped the reservation, the attempt ledger or the
    route pin would be qualifying a system nobody ships. Each is checked by its
    own record rather than by reading the harness.
    """
    from caos.store import apply_schema, connect

    with connect(empty_database) as conn:
        apply_schema(conn)
        conn.commit()
        blobs = BlobStore(tmp_path / "blobs")

        _perform(conn, blobs, QualificationSet(cases=(_case("acme-2026", REPORT),)))

        assert _count(conn, "SELECT count(*) FROM run_routes") == 1
        # Three nodes of the pathway: an attempt, a reservation and a charge each.
        for table in ("run_attempts", "budget_reservations", "budget_ledger"):
            assert _count(conn, f"SELECT count(*) FROM {table}") == 3, table
        reserved = conn.execute("SELECT DISTINCT amount FROM budget_reservations")
        assert [row[0] for row in reserved.fetchall()] == [ESTIMATE]


def test_a_key_naming_a_document_the_case_does_not_carry_is_refused(
    empty_database: str, tmp_path: Path
) -> None:
    """An unanswerable key is a set defect, not a row that always misses.

    Before the cases were in the set there was no way to notice: a key could
    name any digest at all. Now the set holds both halves, so the question "can
    this case's key ever be met" has an answer, and a set that cannot be
    satisfied by any correct run is refused before a single provider call.
    """
    from caos.store import apply_schema, connect

    with connect(empty_database) as conn:
        apply_schema(conn)
        conn.commit()
        unanswerable = replace(
            _case("acme-2026", REPORT),
            expects=(
                ExpectedCitation(
                    module_id="CP-0",
                    document_sha256="c" * 64,
                    matched_text=QUOTE,
                ),
            ),
        )

        with pytest.raises(Refusal) as refused:
            _perform(
                conn,
                BlobStore(tmp_path / "blobs"),
                QualificationSet(cases=(unanswerable,)),
            )
        assert refused.value.code is RefusalCode.QUALIFICATION_KEY_UNANSWERABLE
        # Refused before anything ran, not after paying for it.
        assert _count(conn, "SELECT count(*) FROM runs") == 0


def test_a_key_naming_a_quote_its_own_document_never_carries_is_refused(
    empty_database: str, tmp_path: Path
) -> None:
    """FP-26: the document's digest being carried says nothing about whether
    its declared quote is anywhere in it. Before, a typo in an answer key was
    indistinguishable from a model that simply could not find a real quote,
    and either way the set paid for a run to discover it."""
    from caos.store import apply_schema, connect

    with connect(empty_database) as conn:
        apply_schema(conn)
        conn.commit()
        unanswerable = _case(
            "acme-2026", REPORT, quote="A sentence this report never states"
        )

        with pytest.raises(Refusal) as refused:
            _perform(
                conn,
                BlobStore(tmp_path / "blobs"),
                QualificationSet(cases=(unanswerable,)),
            )
        assert refused.value.code is RefusalCode.QUALIFICATION_KEY_UNANSWERABLE
        # Refused before anything ran, not after paying for it.
        assert _count(conn, "SELECT count(*) FROM runs") == 0


def test_a_key_naming_a_quote_its_document_actually_carries_is_answerable(
    empty_database: str, tmp_path: Path
) -> None:
    """The other half of FP-26: the new check does not refuse a real quote."""
    from caos.store import apply_schema, connect

    with connect(empty_database) as conn:
        apply_schema(conn)
        conn.commit()
        answerable = _case("acme-2026", REPORT)

        performed = _perform(
            conn, BlobStore(tmp_path / "blobs"), QualificationSet(cases=(answerable,))
        )

        assert performed.matrix is not None


# A line a sentence ends with a full stop, and a word NFC composes (R24-18).
_STOPPED = "Soci\u00e9t\u00e9 total debt at 31 December 2026 was USD 1,240.0m."


@pytest.mark.parametrize(
    ("spelling", "anchors"),
    [
        (_STOPPED, True),
        (_STOPPED.rstrip("."), True),
        (f"\u201c{_STOPPED}\u201d", True),
        (unicodedata.normalize("NFD", _STOPPED), True),
        (_STOPPED.replace("1,240.0m", "1,250.0m"), False),
        (_STOPPED.replace("total debt", "debt total"), False),
    ],
)
def test_the_pre_spend_key_check_never_refuses_what_the_answer_rule_anchors(
    case: tuple[StoreConnection, UUID],
    tmp_path: Path,
    spelling: str,
    anchors: bool,
) -> None:
    """R24-18: F228's pre-spend check compared raw tokens, stricter than the
    whole-line rule an answer's citation is anchored by, which forgives a
    sentence's full stop, quotation marks at the line's ends and NFC. So
    `assert_admissible` refused `QUALIFICATION_KEY_UNANSWERABLE` for keys a
    correct run meets. It refuses now only a key no rule could anchor -- a
    wrong figure, words out of order -- still before any call."""
    from caos.evidence.citations import WHOLE_LINE, Citation, verify_citations
    from caos.evidence.ingest import admit_pack
    from caos.qualification.harness import assert_admissible

    data = f"Acme Holdings plc annual report 2026\n{_STOPPED}\n".encode()
    conn, case_id = case
    [source_id] = admit_pack(
        conn,
        BlobStore(tmp_path / "blobs"),
        case_id=case_id,
        documents=[Document(filename=BoundaryText.of("report.txt"), data=data)],
    )
    try:
        verify_citations(
            conn,
            delivered=every_block(conn, source_id),
            citations=[Citation(source_id, 1, spelling)],
            rule=WHOLE_LINE,
        )
        anchored = True
    except Refusal as refused:
        assert refused.code is RefusalCode.CITATION_NOT_LOCATED
        anchored = False
    assert anchored is anchors
    harness = Harness(
        bundle=Bundle(root=VENDORED),
        catalog=CATALOG,
        completions=_Completions(),
        price=priced(ESTIMATE),
        ceiling=SET_CEILING,
    )
    qualification = QualificationSet(cases=(_case("acme-2026", data, quote=spelling),))
    if anchors:
        assert assert_admissible(harness, qualification=qualification)
    else:
        with pytest.raises(Refusal, match=r"^QUALIFICATION_KEY_UNANSWERABLE$"):
            assert_admissible(harness, qualification=qualification)


def test_a_set_that_could_outspend_its_ceiling_is_refused_before_it_starts(
    empty_database: str, tmp_path: Path
) -> None:
    """Invariant 8 one level up.

    Each run has its own ceiling and refuses the reservation that would breach
    it. Nothing bounded the *set*: two hundred cases were two hundred routes'
    worth of calls, each individually within budget and collectively whatever
    they happened to come to.

    Checked against the sum of the per-run ceilings, not against an estimate of
    what the set will actually cost. A ceiling is a statement about the worst
    case — one that let a set start because it would *probably* come in under
    would be a forecast, and invariant 8 is not a forecast.
    """
    from caos.store import apply_schema, connect

    with connect(empty_database) as conn:
        apply_schema(conn)
        conn.commit()

        with pytest.raises(Refusal) as refused:
            _perform(
                conn,
                BlobStore(tmp_path / "blobs"),
                QualificationSet(
                    cases=(_case("acme-2026", REPORT), _case("borealis-2026", OTHER))
                ),
                # Two cases, so two runs at `budget.CEILING` each. A set ceiling
                # of one run's worth cannot cover them.
                ceiling=CEILING,
            )

        assert refused.value.code is RefusalCode.QUALIFICATION_SET_OVER_CEILING
        assert _count(conn, "SELECT count(*) FROM cases") == 0
        assert _count(conn, "SELECT count(*) FROM runs") == 0


def test_a_set_within_its_ceiling_performs(empty_database: str, tmp_path: Path) -> None:
    """The other side of the refusal, so it is a ceiling and not a wall."""
    from caos.store import apply_schema, connect

    with connect(empty_database) as conn:
        apply_schema(conn)
        conn.commit()

        performed = _perform(
            conn,
            BlobStore(tmp_path / "blobs"),
            QualificationSet(
                cases=(_case("acme-2026", REPORT), _case("borealis-2026", OTHER))
            ),
            ceiling=CEILING * 2,
        )

        assert performed.matrix is not None
        assert len(performed.performed) == 2


def test_a_case_with_no_documents_is_refused(
    empty_database: str, tmp_path: Path
) -> None:
    """A case with no inputs cannot be run and cannot be cited."""
    from caos.store import apply_schema, connect

    with connect(empty_database) as conn:
        apply_schema(conn)
        conn.commit()
        with pytest.raises(Refusal) as refused:
            _perform(
                conn,
                BlobStore(tmp_path / "blobs"),
                QualificationSet(cases=(replace(_case("a", REPORT), documents=()),)),
            )
        assert refused.value.code is RefusalCode.QUALIFICATION_SET_EMPTY


def test_the_digest_covers_the_inputs_not_only_the_answers() -> None:
    """Two sets with identical keys over different documents are different sets.

    This is the hole folding the cases in closes. A verdict binds a
    qualification-set digest; if that digest ignored the documents, a signature
    given over one body of evidence would read as binding another.
    """
    base = QualificationSet(cases=(_case("acme-2026", REPORT),))
    digest = qualification_set_digest(base)

    moved = [
        QualificationSet(cases=(_case("acme-2026", OTHER),)),
        QualificationSet(
            cases=(replace(_case("acme-2026", REPORT), profile_id="OTHER_PROFILE"),)
        ),
        QualificationSet(
            cases=(replace(_case("acme-2026", REPORT), selection_id="BASELINE"),)
        ),
        QualificationSet(
            cases=(
                replace(
                    _case("acme-2026", REPORT),
                    documents=(
                        Document(filename=BoundaryText.of("renamed.txt"), data=REPORT),
                    ),
                ),
            )
        ),
    ]
    for changed in moved:
        assert qualification_set_digest(changed) != digest, changed.cases[0]


def test_the_digest_still_does_not_depend_on_the_order_of_cases() -> None:
    """Folding the inputs in must not make the set's identity an accident."""
    first, second = _case("a-case", REPORT), _case("b-case", OTHER)

    assert qualification_set_digest(
        QualificationSet(cases=(first, second))
    ) == qualification_set_digest(QualificationSet(cases=(second, first)))


def test_assert_measurable_is_the_one_place_the_rule_lives() -> None:
    """The guard is public so the harness can apply it before it spends.

    `build_matrix` refuses an unmeasurable set too, but by then a harness would
    have paid for every run in it. One exported check rather than a copy in each
    caller: two copies of a rule are two rules, and the second one drifts.
    """
    for unmeasurable in (
        QualificationSet(cases=()),
        QualificationSet(cases=(replace(_case("a", REPORT), expects=()),)),
        QualificationSet(cases=(replace(_case("a", REPORT), documents=()),)),
    ):
        with pytest.raises(Refusal) as refused:
            assert_measurable(unmeasurable)
        assert refused.value.code is RefusalCode.QUALIFICATION_SET_EMPTY

    # And says nothing about a set it can measure.
    assert_measurable(QualificationSet(cases=(_case("a", REPORT),)))


def test_a_run_that_stopped_short_is_reported_as_more_than_its_proof(
    empty_database: str, tmp_path: Path
) -> None:
    """The narrow proof, and the fact it does not carry.

    CP-0 is accepted and CP-L10 and CP-5 never run. `assert_orchestration_proof` proves
    the artifact that exists, because that is the true claim it makes from a run
    id alone -- and the matrix row it feeds reads `proven`. A reader could take
    that for "the route ran".

    The harness resolved and pinned the route, so it holds what the proof is
    silent about: the run's own status, and the pinned node that produced
    nothing with the state the route left it in. Those sit beside the proof and
    are not summed into it -- a run that stopped with a sound proof and a run
    that finished with an unprovable one are different things to a reviewer.
    """
    from caos.store import apply_schema, connect

    with connect(empty_database) as conn:
        apply_schema(conn)
        conn.commit()

        performed = _perform(
            conn,
            BlobStore(tmp_path / "blobs"),
            QualificationSet(cases=(_case("acme-2026", REPORT),)),
            completions=_Completions(refuses_call=2),
        )

        [record] = performed.performed
        assert isinstance(record, Performed)
        assert record.stopped is RefusalCode.PROVIDER_UNAVAILABLE
        assert record.status is RunStatus.RUNNING, "a run that stopped never completed"
        # The proof holds, over the one artifact there was to prove.
        assert record.refusal is None
        assert record.proof is not None
        assert record.proof.run_id == record.run_id
        assert record.proof.artifacts == 1
        # And this is what the proof could not say: CP-L10 was attempted, its
        # call was recorded with no known charge, and the producer is the one
        # the call recorded -- no generation, not a configured stand-in.
        unrun, after = record.unrun
        [attempt] = unrun.attempts
        assert isinstance(attempt, Attempted)
        assert (unrun.route_node_id, unrun.state) == (L10, NodeState.RUNNABLE)
        assert (after.route_node_id, after.state, after.attempts) == (
            CP5,
            NodeState.BLOCKED,
            (),
        )
        assert (attempt.reserved, attempt.outcome, attempt.charged) == (
            True,
            True,
            False,
        )
        assert (attempt.model, attempt.generation_id) == ("a-model/for-the-test", None)

        # A set that stopped is not a measurement: the records are kept, the
        # matrix is withheld rather than built over the cases that happened to
        # run first.
        assert performed.matrix is None
        assert conn.execute(
            "SELECT p.complete,count(e.evidence_sha256)"
            " FROM qualification_performed p LEFT JOIN qualification_evidence e"
            " USING (performed_sha256) GROUP BY p.complete"
        ).fetchall() == [(False, 1)]


def test_a_case_that_stops_ends_the_set_without_discarding_it(
    empty_database: str, tmp_path: Path
) -> None:
    """A refusal stops the set and keeps what it already bought.

    Two failure modes sit either side of this. Raising discards every
    `Performed` and every provider call behind it — the objection to letting
    `run_route` propagate. Carrying on bets that the refusal was this case's,
    and the ones that end a run are mostly not: a missing credential, a ceiling
    reached, a moved bundle recur on the next case and cost another run, another
    reservation nothing releases, and sometimes another charge.

    So: record it, stop, return the records. Recorded, not swallowed —
    `stopped` carries the typed code.
    """
    from caos.store import apply_schema, connect

    with connect(empty_database) as conn:
        apply_schema(conn)
        conn.commit()

        completions = _Completions(refuses_call=1)
        performed = _perform(
            conn,
            BlobStore(tmp_path / "blobs"),
            QualificationSet(
                cases=(_case("acme-2026", REPORT), _case("borealis-2026", OTHER))
            ),
            completions=completions,
        )

        [record] = performed.performed
        assert record.case_label == "acme-2026", "the second case was never run"
        assert record.stopped is RefusalCode.PROVIDER_UNAVAILABLE
        assert record.status is RunStatus.RUNNING
        # Nothing was accepted, so there is nothing to prove -- the honest
        # refusal, not a proof over an empty run.
        assert record.proof is None
        assert record.refusal is RefusalCode.ORCHESTRATION_NOTHING_TO_PROVE
        assert [entry.route_node_id for entry in record.unrun] == [
            f"RN-{PROFILE}-{SELECTION}-01-CP-0",
            L10,
            CP5,
        ]
        # Attempted with unknown exposure, against never reached at all.
        gate, *later = record.unrun
        assert [(a.outcome, a.charged) for a in gate.attempts] == [(True, False)]
        assert [entry.attempts for entry in later] == [(), ()]
        assert performed.matrix is None

        # Both inputs exist; the second case purchased nothing.
        assert _count(conn, "SELECT count(*) FROM cases") == 2
        assert _count(conn, "SELECT count(*) FROM runs") == 2
        assert _count(conn, "SELECT count(*) FROM budget_reservations") == 1
        second = conn.execute(
            "SELECT run_id FROM runs WHERE run_id <> %s", (record.run_id,)
        ).fetchone()
        assert second is not None
        for table in (
            "run_attempts",
            "budget_reservations",
            "call_outcomes",
            "budget_ledger",
            "artifacts",
        ):
            assert (
                conn.execute(
                    "SELECT 1 FROM " + table + " WHERE run_id=%s", second
                ).fetchall()
                == []
            ), table
        sources = conn.execute(
            "SELECT s.source_id FROM sources s JOIN runs r USING(case_id)"
            " WHERE r.run_id=%s",
            second,
        ).fetchall()
        assert len(completions.prompts) == 1 and sources
        first_source = conn.execute(
            "SELECT s.source_id FROM sources s JOIN runs r USING(case_id)"
            " WHERE r.run_id=%s",
            (record.run_id,),
        ).fetchone()
        assert (
            first_source is not None and str(first_source[0]) in completions.prompts[0]
        )
        assert all(str(source[0]) not in completions.prompts[0] for source in sources)


def test_two_cases_under_one_label_are_refused_before_either_runs(
    empty_database: str, tmp_path: Path
) -> None:
    """`build_matrix` refuses this, once every case has been paid for.

    The module's own contract is that a set is checked whole before the first
    provider call, and label distinctness is knowable from the set alone. Every
    run the old order bought was spent to learn something the labels already
    said.
    """
    from caos.store import apply_schema, connect

    with connect(empty_database) as conn:
        apply_schema(conn)
        conn.commit()

        with pytest.raises(Refusal) as refused:
            _perform(
                conn,
                BlobStore(tmp_path / "blobs"),
                QualificationSet(cases=(_case("same", REPORT), _case("same", OTHER))),
            )

        assert refused.value.code is RefusalCode.QUALIFICATION_SET_AMBIGUOUS
        assert _count(conn, "SELECT count(*) FROM runs") == 0


def test_an_unknown_pathway_in_a_later_case_refuses_before_the_first_one_runs(
    empty_database: str, tmp_path: Path
) -> None:
    """A set is checked whole before the first provider call — routes included.

    Route resolution is pure and reads no store (invariant 10), so nothing made
    it wait until a case's turn. Resolving inside the loop meant a bad pathway
    on the last case of ten was found after nine had been admitted, run and
    paid for, and then thrown away with the refusal: the most expensive possible
    moment to learn something knowable from the catalog and the set alone.

    Every route is now resolved up front, so this costs a case row, a run and a
    provider call each of zero.
    """
    from caos.store import apply_schema, connect

    with connect(empty_database) as conn:
        apply_schema(conn)
        conn.commit()

        with pytest.raises(Refusal) as refused:
            _perform(
                conn,
                BlobStore(tmp_path / "blobs"),
                QualificationSet(
                    cases=(
                        _case("acme-2026", REPORT),
                        replace(
                            _case("borealis-2026", OTHER),
                            selection_id="NO_SUCH_PATHWAY",
                        ),
                    )
                ),
            )

        assert refused.value.code is RefusalCode.ROUTE_SELECTION_UNKNOWN
        # The first case is untouched: not admitted, not run, not charged.
        assert _count(conn, "SELECT count(*) FROM cases") == 0
        assert _count(conn, "SELECT count(*) FROM runs") == 0
        assert _count(conn, "SELECT count(*) FROM budget_reservations") == 0


def test_an_unknown_pathway_refuses_without_leaving_a_run_behind(
    empty_database: str, tmp_path: Path
) -> None:
    """Route resolution is pure, so it happens before the run exists.

    Taken after `start_run` it would leave a RUNNING run with no pin, no
    attempts and no terminal event: nothing can complete it, nothing can fail
    it, and `assert_orchestration_proof` refuses it forever.
    """
    from caos.store import apply_schema, connect

    with connect(empty_database) as conn:
        apply_schema(conn)
        conn.commit()

        with pytest.raises(Refusal) as refused:
            _perform(
                conn,
                BlobStore(tmp_path / "blobs"),
                QualificationSet(
                    cases=(
                        replace(
                            _case("acme-2026", REPORT),
                            selection_id="NO_SUCH_PATHWAY",
                        ),
                    )
                ),
            )

        assert refused.value.code is RefusalCode.ROUTE_SELECTION_UNKNOWN
        assert _count(conn, "SELECT count(*) FROM runs") == 0


def test_an_unreadable_artifact_does_not_take_the_set_down_with_it(
    empty_database: str, tmp_path: Path
) -> None:
    """The guard on the guard.

    `_unrun` reads CP-0's body out of the blob store to recover the readiness a
    soft edge turns on. Bytes that will not load raise -- and left unguarded,
    that refusal would escape from inside the very function added to stop one
    bad case from ending the set.

    Damaged between the two nodes rather than after the run, so the read that
    meets the damage is the one `perform` itself makes. Which nodes are
    COMPLETE stays exact; what is given up is the readiness that separates a
    BLOCKED node from a RESTRICTED one.
    """
    from caos.store import apply_schema, connect

    with connect(empty_database) as conn:
        apply_schema(conn)
        conn.commit()
        blobs = BlobStore(tmp_path / "blobs")

        harness = Harness(
            Bundle(VENDORED),
            CATALOG,
            _DamagesWhatWasAccepted(conn, blobs, _Completions()),
            priced(ESTIMATE),
            SET_CEILING,
        )
        qualification = QualificationSet(cases=(_case("acme-2026", REPORT),))
        prepared = prepare(conn, blobs, harness, qualification=qualification)
        _approve(conn, prepared)
        performed = perform(
            conn, blobs, harness, qualification=qualification, prepared=prepared
        )

        # It returned at all, which is the assertion.
        [record] = performed.performed
        assert record.stopped is RefusalCode.PROVIDER_UNAVAILABLE
        assert record.proof is None
        assert record.refusal is RefusalCode.ORCHESTRATION_ARTIFACT_UNREADABLE
        # CP-0 has its artifact row and stays COMPLETE; the rest never ran.
        assert [entry.route_node_id for entry in record.unrun] == [L10, CP5]


def test_a_run_whose_pin_is_gone_reports_no_pinned_nodes(
    empty_database: str, tmp_path: Path
) -> None:
    """No pin, no pinned nodes -- the literal reading, and the only honest one.

    `_unrun` re-reads the pin rather than trusting the object this module
    resolved, for the reason `proof.py` and `matrix.py` both do: the host owns
    identity (invariant 3). What that costs is a run whose pin has gone, and
    the answer is to name nothing rather than to invent a node list. The signal
    is not lost -- the proof refuses the same run for the same reason, and
    `refusal` carries it.
    """
    from caos.store import apply_schema, connect

    with connect(empty_database) as conn:
        apply_schema(conn)
        conn.commit()
        blobs = BlobStore(tmp_path / "blobs")

        provider = _DamagesWhatWasAccepted(
            conn, blobs, _Completions(), loses_the_pin=True
        )
        harness = Harness(
            Bundle(VENDORED), CATALOG, provider, priced(ESTIMATE), SET_CEILING
        )
        qualification = QualificationSet(cases=(_case("acme-2026", REPORT),))
        prepared = prepare(conn, blobs, harness, qualification=qualification)
        _approve(conn, prepared)
        provider.target = (
            urlsplit(empty_database).path.lstrip("/"),
            prepared[0].input.run_id,
        )
        performed = perform(
            conn, blobs, harness, qualification=qualification, prepared=prepared
        )

        [record] = performed.performed
        assert record.stopped is RefusalCode.PROVIDER_UNAVAILABLE
        assert record.refusal is RefusalCode.ORCHESTRATION_ROUTE_NOT_PINNED
        assert record.unrun == ()


def test_a_late_invalid_pin_clears_proof_and_preserves_the_stopped_record(
    empty_database: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from caos.qualification import harness as subject
    from caos.store import apply_schema, connect

    with connect(empty_database) as conn:
        apply_schema(conn)
        conn.commit()
        blobs = BlobStore(tmp_path / "blobs")
        original = subject._unrun

        def corrupt(
            c: StoreConnection, b: BlobStore, bundle: Bundle, run: UUID
        ) -> tuple[Unrun, ...]:
            with route_fault(c):
                c.execute(
                    "UPDATE run_routes SET resolved = '{}' WHERE run_id = %s",
                    (run,),
                )
            c.commit()
            return original(c, b, bundle, run)

        monkeypatch.setattr(subject, "_unrun", corrupt)
        [record] = _perform(
            conn,
            blobs,
            QualificationSet(cases=(_case("invalid-pin", REPORT),)),
            completions=_Completions(refuses_call=2),
        ).performed
        assert record.stopped is RefusalCode.PROVIDER_UNAVAILABLE
        assert record.refusal is RefusalCode.ROUTE_IDENTITY_INVALID
        assert record.proof is None and record.unrun == ()

        def unavailable(*_args: object) -> None:
            raise Refusal(RefusalCode.STORE_UNAVAILABLE)

        monkeypatch.setattr(subject, "_unrun", unavailable)
        # A store fault mid-set no longer discards the paid runs before it
        # (FP-07): with the connection still open the case is recorded as
        # stopped by that fault, on a clean transaction.
        [again] = _perform(
            conn,
            blobs,
            QualificationSet(cases=(_case("store-down", REPORT),)),
            completions=_Completions(refuses_call=2),
        ).performed
        assert again.stopped is RefusalCode.PROVIDER_UNAVAILABLE
        assert again.refusal is RefusalCode.STORE_UNAVAILABLE
        assert again.proof is None


def test_a_performed_set_concludes_nothing() -> None:
    """The line this package holds, from the harness's side.

    `QUALIFIED` is the reviewer's word (`caos/qualification/__init__.py`). The
    matrix already refuses to carry a field that reads as one; a record of what
    a run did must not smuggle one back in under a different name.

    A property of the classes, so it provisions nothing: a database and a
    provider call would only give it ways to fail that are not its subject.
    """
    forbidden = {"qualified", "verdict", "passed", "score", "assurance"}
    for holder in (PerformedSet, Performed):
        named = {name.lower() for name in holder.__dataclass_fields__}
        assert not (named & forbidden), f"{holder.__name__} concludes: {named}"
        assert not hasattr(holder, "assurance")


def test_unrun_attempts_separate_possible_spend_from_no_call_and_known_charge(
    empty_database: str, tmp_path: Path
) -> None:
    """Every kind of attempt a stopped node can hold, read back from the store."""
    from conftest import reserve_at as reserve

    from caos.qualification.harness import _unrun
    from caos.store import apply_schema, connect
    from caos.store.outcomes import CallOutcome, execution_reads, record_outcome
    from caos.store.runs import start_attempt

    with connect(empty_database) as conn:
        apply_schema(conn)
        conn.commit()
        blobs = BlobStore(tmp_path / "blobs")
        [record] = _perform(
            conn,
            blobs,
            QualificationSet(cases=(_case("acme-2026", REPORT),)),
            completions=_Completions(refuses_call=2),
        ).performed
        node = L10
        # Reserved and never recorded: the call may have happened.
        reserve(conn, start_attempt(conn, record.run_id, node), ESTIMATE)
        # Never reserved: no call was possible.
        start_attempt(conn, record.run_id, node)
        # A known charge recorded with no producer, and no artifact.
        charged = start_attempt(conn, record.run_id, node)
        reserve(conn, charged, ESTIMATE)
        record_outcome(
            conn, attempt_id=charged, outcome=CallOutcome(Decimal("0.01"), None, None)
        )
        with execution_reads(conn):
            unrun, _ = _unrun(conn, blobs, Bundle(VENDORED), record.run_id)

    assert [
        (a.reserved, a.outcome, a.charged, a.model, a.generation_id)
        for a in unrun.attempts
    ] == [
        (True, True, False, "a-model/for-the-test", None),
        (True, False, False, None, None),
        (False, False, False, None, None),
        (True, True, True, None, None),
    ]


def test_a_case_that_declared_the_block_it_expected_is_signable(
    empty_database: str, tmp_path: Path
) -> None:
    """The deliberately restricted case, built from a run rather than a dataclass.

    `docs/REPAIR_PLAN.md` Phase 6 asks for a case whose expected result is that
    the evidence does not support the work. Until now no run could answer one:
    `expected_refusal_met` read only the proof's refusal, and a validated
    Blocked handoff leaves a sound proof and writes no `attempt_refusals` row,
    while `complete` demanded every run reach COMPLETE -- which a blocked run
    never does. Both halves are read from the run here.
    """
    from caos.qualification.store import performed_evidence
    from caos.store import apply_schema, connect

    with connect(empty_database) as conn:
        apply_schema(conn)
        conn.commit()
        case = replace(
            _case("restricted-2026", REPORT),
            expects=(),
            expected_refusal=RefusalCode.HANDOFF_BLOCKED,
        )
        qualification = QualificationSet(cases=(case,))
        blobs = BlobStore(tmp_path / "blobs")
        harness = Harness(
            bundle=Bundle(root=VENDORED),
            catalog=CATALOG,
            completions=_Completions(qa_by_module={"CP-5": "Blocked"}),
            price=priced(ESTIMATE),
            ceiling=SET_CEILING,
        )
        prepared = prepare(conn, blobs, harness, qualification=qualification)
        _approve(conn, prepared)
        performed = perform(
            conn, blobs, harness, qualification=qualification, prepared=prepared
        )

        [record] = performed.performed
        assert record.status is RunStatus.BLOCKED
        assert performed.matrix is not None
        [row] = performed.matrix.rows
        assert row.expected_refusal_met is True, "the run refused as declared"

        snapshot = performed_evidence(prepared=prepared, performed=performed)
        assert snapshot.complete is True, "a blocked run may answer a blocked key"


def test_a_blocked_qa_verdict_ends_the_case_blocked_and_the_matrix_still_scores(
    empty_database: str, tmp_path: Path
) -> None:
    """A validated CP-5 `Blocked` is the route's own rule applied, not a stop.

    The run ends BLOCKED with CP-5 unrun and attempted; the proof holds over what
    was accepted, and the matrix scores those proven records -- CP-L10's quote is
    met, the CP-5 key missed.
    """
    from hashlib import sha256

    from caos.store import apply_schema, connect

    with connect(empty_database) as conn:
        apply_schema(conn)
        conn.commit()
        document = sha256(REPORT).hexdigest()
        keys = tuple(
            ExpectedCitation(module, document, QUOTE) for module in ("CP-L10", "CP-5")
        )
        case = replace(_case("blocked-2026", REPORT), expects=keys)
        performed = _perform(
            conn,
            BlobStore(tmp_path / "blobs"),
            QualificationSet(cases=(case,)),
            completions=_Completions(qa_by_module={"CP-5": "Blocked"}),
        )

        [record] = performed.performed
        assert (record.status, record.stopped, record.refusal) == (
            RunStatus.BLOCKED,
            None,
            None,
        )
        assert record.proof is not None and record.proof.artifacts == 2
        [unrun] = record.unrun
        assert unrun.route_node_id == CP5 and len(unrun.attempts) == 1
        assert performed.matrix is not None
        [row] = performed.matrix.rows
        assert (row.proven, row.met, row.missed) == (True, keys[:1], keys[1:])


# CP-0's T8 row for CP-5 says READY in every handoff `_Completions` writes, so a
# key saying BLOCKED is one the run answers wrongly.
_WRONG_T8 = ExpectedRegister(
    module_id="CP-0",
    register_id="T8",
    row_key=(("Module", "CP-5"),),
    column="Readiness",
    expected="BLOCKED",
)


def _restricted(
    conn: StoreConnection,
    blobs: BlobStore,
    root: Path,
    label: str,
    case: QualificationCase,
) -> tuple[tuple[PreparedCase, ...], PerformedSet]:
    """`case`, declaring HANDOFF_BLOCKED, performed under the bundle at `root`."""
    qualification = QualificationSet(
        cases=(
            replace(
                case,
                label=label,
                expects=(),
                expected_refusal=RefusalCode.HANDOFF_BLOCKED,
            ),
        )
    )
    harness = Harness(
        bundle=Bundle(root=root),
        catalog=CATALOG,
        completions=_Completions(qa_by_module={"CP-5": "Blocked"}),
        price=priced(ESTIMATE),
        ceiling=SET_CEILING,
    )
    prepared = prepare(conn, blobs, harness, qualification=qualification)
    _approve(conn, prepared)
    return prepared, perform(
        conn, blobs, harness, qualification=qualification, prepared=prepared
    )


def test_a_declared_key_the_matrix_could_not_measure_blocks_signing(
    empty_database: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """DQ-1: `_guarded` answered `None` for a key whose reader refused, and
    `_answered` reads `None` as "not declared". Beside a met HANDOFF_BLOCKED a
    wrong register key read as waived when a vendored file moved during
    scoring, so the snapshot was recorded complete and could be signed.
    The reader now answers `False`, the row keeps the reader's code, and the
    stored document re-derives as incomplete."""
    import shutil

    from caos.qualification import matrix
    from caos.qualification.store import document_complete, performed_evidence
    from caos.store import apply_schema, connect

    root = tmp_path / "bundle"
    shutil.copytree(VENDORED, root)
    target = root / "skills/cp-os-credit-os/scripts/credit_os_v/research.py"
    wrong = replace(_case("wrong", REPORT), expects_register=(_WRONG_T8,))
    with connect(empty_database) as conn:
        apply_schema(conn)
        conn.commit()
        blobs = BlobStore(tmp_path / "blobs")
        prepared, control = _restricted(conn, blobs, root, "control", wrong)
        assert control.matrix is not None
        [row] = control.matrix.rows
        assert row.registers_met is False
        assert not performed_evidence(prepared=prepared, performed=control).complete

        original = matrix._cited

        def cited_then_move(
            conn_: StoreConnection, run_id: UUID, *, proof: OrchestrationProof | None
        ) -> set[tuple[str, str, str]]:
            cited = original(conn_, run_id, proof=proof)
            target.write_bytes(target.read_bytes() + b"\n# moved\n")
            return cited

        monkeypatch.setattr(matrix, "_cited", cited_then_move)
        prepared, faulted = _restricted(conn, blobs, root, "faulted", wrong)
        assert faulted.matrix is not None
        [row] = faulted.matrix.rows
        assert row.expected_refusal_met is True
        assert (row.refusal, row.registers_met) == (
            RefusalCode.AUTHORITY_BYTES_MISMATCH,
            False,
        )
        snapshot = performed_evidence(prepared=prepared, performed=faulted)
        assert snapshot.complete is False
        stored = conn.execute(
            "SELECT complete, performed_json FROM qualification_performed"
            " WHERE performed_sha256=%s",
            (snapshot.evidence.performed_sha256,),
        ).fetchone()
        conn.rollback()
        assert stored is not None
        assert stored[0] is False
        assert document_complete(stored[1]) is False


def test_keys_whose_pin_stopped_reading_are_not_waived_beside_a_met_refusal(
    empty_database: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """DQ-1's second shape: the readers round 3 newly guarded. A pin corrupted
    after the proof read it made the projection and block readers refuse
    ROUTE_IDENTITY_INVALID, and both wrong keys read as waived."""
    from caos.qualification import matrix
    from caos.qualification.store import performed_evidence
    from caos.store import apply_schema, connect

    wrong = replace(
        _case("wrong", REPORT),
        expects_projection=(ExpectedProjection("CP-0", "qa_status", "Restricted"),),
        expects_blocked=("CP-5",),
    )
    with connect(empty_database) as conn:
        apply_schema(conn)
        conn.commit()
        blobs = BlobStore(tmp_path / "blobs")
        original = matrix._cited

        def cited_then_unpin(
            conn_: StoreConnection, run_id: UUID, *, proof: OrchestrationProof | None
        ) -> set[tuple[str, str, str]]:
            cited = original(conn_, run_id, proof=proof)
            with connect(empty_database) as other, route_fault(other):
                other.execute(
                    "UPDATE run_routes SET resolved='{}' WHERE run_id=%s", (run_id,)
                )
            return cited

        monkeypatch.setattr(matrix, "_cited", cited_then_unpin)
        prepared, faulted = _restricted(conn, blobs, VENDORED, "unpinned", wrong)
        assert faulted.matrix is not None
        [row] = faulted.matrix.rows
        assert row.refusal is RefusalCode.ROUTE_IDENTITY_INVALID
        assert (row.projections_met, row.blocked_met) == (False, False)
        assert not performed_evidence(prepared=prepared, performed=faulted).complete


def test_a_refusal_no_run_can_end_in_is_not_declarable(
    empty_database: str, tmp_path: Path
) -> None:
    """DQ-2: a node refusal is explained against its attempt and leaves the run
    RUNNING, so a case declaring CITATION_NOT_LOCATED was prepared, paid for on
    every retry and never answerable. Only HANDOFF_BLOCKED, the one refusal a
    run ends in, is declarable, and the rest are refused before any write."""
    from caos.qualification.matrix import DECLARABLE_REFUSALS
    from caos.store import apply_schema, connect

    assert frozenset({RefusalCode.HANDOFF_BLOCKED}) == DECLARABLE_REFUSALS
    declared = replace(
        _case("declared-refusal", REPORT),
        expects=(),
        expected_refusal=RefusalCode.CITATION_NOT_LOCATED,
    )
    harness = Harness(
        bundle=Bundle(root=VENDORED),
        catalog=CATALOG,
        completions=_Completions(),
        price=priced(ESTIMATE),
        ceiling=SET_CEILING,
    )
    with connect(empty_database) as conn:
        apply_schema(conn)
        conn.commit()
        with pytest.raises(Refusal, match=r"^QUALIFICATION_KEY_UNANSWERABLE$"):
            prepare(
                conn,
                BlobStore(tmp_path / "blobs"),
                harness,
                qualification=QualificationSet(cases=(declared,)),
            )
        assert _count(conn, "SELECT count(*) FROM runs") == 0


def test_the_last_attempt_is_the_last_by_ordinal_not_by_clock(
    empty_database: str, tmp_path: Path
) -> None:
    """DQ-2's second half: `_refusal_met` chose the node's last attempt by
    `started_at` and a random id, so a retry whose clock read earlier let the
    stale refusal of an earlier attempt match. The run lock numbers attempts."""
    from caos.qualification.matrix import _refusal_met
    from caos.store import apply_schema, connect
    from caos.store.runs import fail_run, start_attempt

    no_quote = b"Acme Holdings plc annual report 2026\nRevenue grew in the year\n"
    with connect(empty_database) as conn:
        apply_schema(conn)
        conn.commit()
        performed = _perform(
            conn,
            BlobStore(tmp_path / "blobs"),
            # FP-26: the grading key's own quote must be one `no_quote` really
            # carries, or `_answerable` refuses before any run starts. The
            # model still cites the module's usual QUOTE regardless of the
            # key, and this document never carries that one -- which is the
            # real, run-time CITATION_NOT_LOCATED this test is about.
            QualificationSet(
                cases=(_case("stale", no_quote, quote="Revenue grew in the year"),)
            ),
        )
        [record] = performed.performed
        assert record.stopped is RefusalCode.CITATION_NOT_LOCATED
        row = conn.execute(
            "SELECT route_node_id FROM run_attempts WHERE run_id=%s",
            (record.run_id,),
        ).fetchone()
        assert row is not None
        retry = start_attempt(conn, record.run_id, str(row[0]))
        tamper(
            conn,
            "UPDATE run_attempts SET started_at = started_at - interval '1 hour'"
            " WHERE attempt_id=%s",
            (retry,),
        )
        assert fail_run(conn, record.run_id)
        conn.commit()
        met = _refusal_met(conn, record.run_id, RefusalCode.CITATION_NOT_LOCATED, None)
        assert met is False


def test_a_matrix_refused_after_the_runs_keeps_the_performed_snapshot(
    empty_database: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """DQ-5 (MAX-10): the matrix re-reads the manifest after every proof, and a
    manifest that moved then raised out of `perform` before `_persist_performed`
    ran -- three paid calls, no snapshot. The set is kept as a stopped set is,
    with no matrix and so never signable, and the refusal still reaches the
    caller."""
    import shutil

    from caos.qualification import matrix
    from caos.store import apply_schema, connect

    root = tmp_path / "bundle"
    shutil.copytree(VENDORED, root)
    manifest = root / "DEPLOY_V_INTEGRITY_v1.json"
    qualification = QualificationSet(cases=(_case("moved-manifest", REPORT),))
    harness = Harness(
        bundle=Bundle(root=root),
        catalog=CATALOG,
        completions=_Completions(),
        price=priced(ESTIMATE),
        ceiling=SET_CEILING,
    )
    with connect(empty_database) as conn:
        apply_schema(conn)
        conn.commit()
        blobs = BlobStore(tmp_path / "blobs")
        prepared = prepare(conn, blobs, harness, qualification=qualification)
        _approve(conn, prepared)
        original = matrix._cited

        def cited_then_move(
            conn_: StoreConnection, run_id: UUID, *, proof: OrchestrationProof | None
        ) -> set[tuple[str, str, str]]:
            cited = original(conn_, run_id, proof=proof)
            manifest.write_bytes(manifest.read_bytes() + b" ")
            return cited

        monkeypatch.setattr(matrix, "_cited", cited_then_move)
        with pytest.raises(Refusal, match=r"^AUTHORITY_BYTES_MISMATCH$"):
            perform(
                conn, blobs, harness, qualification=qualification, prepared=prepared
            )
        conn.rollback()
        rows = conn.execute(
            "SELECT complete, performed_json->'matrix' FROM qualification_performed"
        ).fetchall()
        conn.rollback()
        assert rows == [(False, None)]


def test_every_check_prepare_makes_before_writing_is_one_function(
    empty_database: str, tmp_path: Path
) -> None:
    """DQ-12: `scripts/qualify.py` asks `assert_admissible` before it creates a
    database, so it must refuse what `prepare` would, and write nothing."""
    from caos.qualification.harness import assert_admissible
    from caos.store import apply_schema, connect

    two = QualificationSet(
        cases=(_case("acme-2026", REPORT), _case("borealis-2026", OTHER))
    )
    unaffordable = Harness(
        bundle=Bundle(root=VENDORED),
        catalog=CATALOG,
        completions=_Completions(),
        price=priced(ESTIMATE),
        ceiling=CEILING,
    )
    with pytest.raises(Refusal, match=r"^QUALIFICATION_SET_OVER_CEILING$"):
        assert_admissible(unaffordable, qualification=two)
    affordable = replace(unaffordable, ceiling=SET_CEILING)
    routes = assert_admissible(affordable, qualification=two)
    assert [(route.profile_id, route.selection_id) for route in routes] == [
        (PROFILE, SELECTION),
        (PROFILE, SELECTION),
    ]
    with connect(empty_database) as conn:
        apply_schema(conn)
        conn.commit()
        blobs = BlobStore(tmp_path / "blobs")
        with pytest.raises(Refusal, match=r"^QUALIFICATION_SET_OVER_CEILING$"):
            prepare(conn, blobs, unaffordable, qualification=two)
        assert _count(conn, "SELECT count(*) FROM cases") == 0
