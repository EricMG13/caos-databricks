"""Completion Phase 13 Task 13.4: the edge proves each request, not itself.

`docs/DECISIONS.md` §93. The static shared secret is now the key of a
per-request HMAC assertion over the subject, the sorted groups, the method,
the target, an issued-at second and a nonce. The guard derives identity from
the verified assertion and from nothing a client could have sent through a
forwarding proxy.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import secrets
from collections.abc import Iterator
from uuid import uuid4

import httpx2 as httpx
import pytest
from fastapi.testclient import TestClient
from starlette.types import Receive, Scope, Send

from caos.api.edge import (
    ASSERTION_MAX_AGE_SECONDS,
    EDGE_ASSERTION_HEADER,
    NONCE_CAPACITY,
    PUBLIC_ORIGIN_ENV,
    EdgeGuard,
    NonceRegister,
    sign_assertion,
    verify_assertion,
)
from caos.api.identity import (
    EDGE_TOKEN_ENV,
    TRUST_SWITCH,
    GlobalRole,
    actor_from_headers,
)

PUBLIC = "https://caos.example.test"
SUBJECT = "6a0e1c2d-0000-4000-8000-00000000a001"
NOW = 1_800_000_000


class Recorder:
    def __init__(self) -> None:
        self.seen: list[list[tuple[bytes, bytes]]] = []

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        self.seen.append(list(scope["headers"]))
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"reached"})


@pytest.fixture
def key(monkeypatch: pytest.MonkeyPatch) -> Iterator[bytes]:
    minted = secrets.token_urlsafe(32)
    monkeypatch.setenv(EDGE_TOKEN_ENV, minted)
    monkeypatch.setenv(PUBLIC_ORIGIN_ENV, PUBLIC)
    monkeypatch.delenv(TRUST_SWITCH, raising=False)
    yield minted.encode()


def _assertion(  # noqa: PLR0913 -- the fields an assertion binds, each defaulted
    key: bytes,
    *,
    method: str = "GET",
    target: str = "/api/v1/cases",
    subject: str = SUBJECT,
    groups: tuple[str, ...] = ("caos-analysts",),
    issued_at: int = NOW,
) -> str:
    return sign_assertion(
        key,
        subject=subject,
        groups=groups,
        method=method,
        target=target,
        issued_at=issued_at,
        nonce=secrets.token_hex(16),
    )


def _guarded(now: int = NOW) -> tuple[Recorder, TestClient]:
    recorder = Recorder()
    return recorder, TestClient(EdgeGuard(recorder, clock=lambda: float(now)))


def _identity(seen: list[tuple[bytes, bytes]]) -> dict[str, list[str]]:
    wanted = {b"x-caos-user", b"x-forwarded-groups", b"x-caos-role"}
    found: dict[str, list[str]] = {}
    for name, value in seen:
        if name.lower() in wanted:
            found.setdefault(name.decode(), []).append(value.decode())
    return found


def _actor_of(seen: list[tuple[bytes, bytes]]) -> tuple[str, GlobalRole]:
    actor = actor_from_headers({n.decode(): v.decode() for n, v in seen})
    return str(actor.user_id), actor.role


def _refused(response: httpx.Response) -> tuple[int, str]:
    return response.status_code, response.json()["code"]


def test_a_forged_group_header_is_ignored_whatever_the_proxy_forwarded(
    key: bytes,
) -> None:
    """The Phase 13 exit check. A proxy that forwards a client's identity
    headers unsigned changes nothing: the actor is the assertion's."""
    recorder, client = _guarded()
    forged = {
        EDGE_ASSERTION_HEADER: _assertion(key),
        "x-caos-user": str(uuid4()),
        "x-forwarded-groups": "caos-admins",
        "x-caos-role": "ADMIN",
        "sec-fetch-site": "none",
    }
    response = client.get("/api/v1/cases", headers=forged)
    assert response.status_code == 200
    [seen] = recorder.seen
    assert _identity(seen) == {
        "x-caos-user": [SUBJECT],
        "x-forwarded-groups": ["caos-analysts"],
    }
    assert EDGE_ASSERTION_HEADER.encode() not in {name for name, _ in seen}
    assert _actor_of(seen) == (SUBJECT, GlobalRole.ANALYST)


def test_the_actor_carries_the_verified_subject_and_the_greatest_verified_group(
    key: bytes,
) -> None:
    recorder, client = _guarded()
    admin = _assertion(key, groups=("caos-readers", "caos-admins"))
    client.get("/api/v1/cases", headers={EDGE_ASSERTION_HEADER: admin})
    [seen] = recorder.seen
    assert _actor_of(seen) == (SUBJECT, GlobalRole.ADMIN)


def test_a_request_without_an_assertion_or_with_a_bad_mac_is_not_trusted(
    key: bytes,
) -> None:
    recorder, client = _guarded()
    good = _assertion(key)
    wrong_key = _assertion(b"k" * 40)
    tampered = good[:-4] + ("AAAA" if not good.endswith("AAAA") else "BBBB")
    refused = [
        client.get("/api/v1/cases"),
        client.get("/api/v1/cases", headers={EDGE_ASSERTION_HEADER: wrong_key}),
        client.get("/api/v1/cases", headers={EDGE_ASSERTION_HEADER: tampered}),
        client.get("/api/v1/cases", headers={EDGE_ASSERTION_HEADER: "v1.x.y"}),
        client.get("/api/v1/cases", headers={EDGE_ASSERTION_HEADER: ""}),
        client.get(
            "/api/v1/cases",
            headers=[(EDGE_ASSERTION_HEADER, good), (EDGE_ASSERTION_HEADER, good)],
        ),
    ]
    assert [_refused(r) for r in refused] == [(403, "EDGE_NOT_TRUSTED")] * len(refused)
    assert recorder.seen == []
    admitted = client.get("/api/v1/cases", headers={EDGE_ASSERTION_HEADER: good})
    assert admitted.is_success


def test_a_replayed_assertion_is_refused(key: bytes) -> None:
    recorder, client = _guarded()
    once = _assertion(key)
    first = client.get("/api/v1/cases", headers={EDGE_ASSERTION_HEADER: once})
    assert first.is_success
    replay = client.get("/api/v1/cases", headers={EDGE_ASSERTION_HEADER: once})
    assert _refused(replay) == (403, "EDGE_NOT_TRUSTED")
    assert len(recorder.seen) == 1
    # A fresh nonce over the same request is a new assertion.
    fresh = client.get(
        "/api/v1/cases", headers={EDGE_ASSERTION_HEADER: _assertion(key)}
    )
    assert fresh.is_success


def test_a_replay_at_exactly_the_window_edge_is_refused(key: bytes) -> None:
    recorder = Recorder()
    clock = [float(NOW)]
    client = TestClient(EdgeGuard(recorder, clock=lambda: clock[0]))
    once = _assertion(key)
    assert client.get("/api/v1/cases", headers={EDGE_ASSERTION_HEADER: once}).is_success
    clock[0] = float(NOW + ASSERTION_MAX_AGE_SECONDS)
    replay = client.get("/api/v1/cases", headers={EDGE_ASSERTION_HEADER: once})
    assert _refused(replay) == (403, "EDGE_NOT_TRUSTED")
    assert len(recorder.seen) == 1


def test_a_stale_or_future_assertion_is_refused(key: bytes) -> None:
    recorder, client = _guarded()
    stale = _assertion(key, issued_at=NOW - ASSERTION_MAX_AGE_SECONDS - 1)
    future = _assertion(key, issued_at=NOW + ASSERTION_MAX_AGE_SECONDS + 1)
    for header in (stale, future):
        refused = client.get("/api/v1/cases", headers={EDGE_ASSERTION_HEADER: header})
        assert _refused(refused) == (403, "EDGE_NOT_TRUSTED")
    assert recorder.seen == []
    at_the_bound = (
        _assertion(key, issued_at=NOW - ASSERTION_MAX_AGE_SECONDS),
        _assertion(key, issued_at=NOW + ASSERTION_MAX_AGE_SECONDS),
    )
    for header in at_the_bound:
        admitted = client.get("/api/v1/cases", headers={EDGE_ASSERTION_HEADER: header})
        assert admitted.is_success


def test_an_assertion_signed_for_another_method_or_target_is_refused(
    key: bytes,
) -> None:
    recorder, client = _guarded()
    elsewhere = (
        _assertion(key, method="POST", target="/api/v1/cases"),
        _assertion(key, method="GET", target="/api/v1/cases?run=1"),
        _assertion(key, method="GET", target="/api/v1/case"),
    )
    for header in elsewhere:
        refused = client.get("/api/v1/cases", headers={EDGE_ASSERTION_HEADER: header})
        assert _refused(refused) == (403, "EDGE_NOT_TRUSTED")
    assert recorder.seen == []
    exact = _assertion(key, method="GET", target="/api/v1/cases?run=1&x=%2F")
    admitted = client.get(
        "/api/v1/cases?run=1&x=%2F", headers={EDGE_ASSERTION_HEADER: exact}
    )
    assert admitted.is_success


def _forged(key: bytes, payload: object) -> bytes:
    """A correctly keyed assertion over any payload: the MAC binds the bytes,
    and the shape is what the verifier must still refuse."""
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    mac = hmac.new(key, b"caos-edge-assertion-v1\n" + canonical, hashlib.sha256)

    def b64(raw: bytes) -> str:
        return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()

    return f"v1.{b64(canonical)}.{b64(mac.digest())}".encode()


def test_the_verifier_refuses_a_payload_outside_its_closed_shape(key: bytes) -> None:
    """A key holder's malformed payload must not become a malformed identity
    header: every field is typed, bounded and in canonical order."""
    base: dict[str, object] = {
        "subject": SUBJECT,
        "groups": ["caos-analysts"],
        "method": "GET",
        "target": "/api/v1/cases",
        "issued_at": NOW,
        "nonce": "ab" * 16,
    }
    bad: list[object] = [
        {**base, "extra": 1},
        {k: v for k, v in base.items() if k != "nonce"},
        {**base, "groups": "caos-analysts"},
        {**base, "groups": ["caos-analysts", 1]},
        {**base, "groups": ["caos,admins"]},
        {**base, "groups": ["b", "a"]},  # unsorted: not the canonical form
        {**base, "groups": ["a", "a"]},  # repeated: not the canonical form
        {**base, "subject": "not\na subject"},
        {**base, "subject": ""},
        {**base, "issued_at": "1"},
        {**base, "issued_at": True},
        {**base, "issued_at": 1.5},
        {**base, "nonce": "short"},
        {**base, "nonce": "zz" * 16},
        {**base, "method": "get"},
        [1, 2],
    ]
    for payload in bad:
        verdict = verify_assertion(
            key,
            _forged(key, payload),
            method="GET",
            target="/api/v1/cases",
            now=float(NOW),
            nonces=NonceRegister(),
        )
        assert verdict is None, payload
    asserted = verify_assertion(
        key,
        _forged(key, base),
        method="GET",
        target="/api/v1/cases",
        now=float(NOW),
        nonces=NonceRegister(),
    )
    assert asserted is not None
    assert (asserted.subject, asserted.groups) == (SUBJECT, ("caos-analysts",))


def test_the_nonce_register_is_bounded_and_forgets_only_expired_nonces() -> None:
    register = NonceRegister(capacity=2)
    assert register.admit("a", expires_at=NOW + 10, now=NOW)
    assert register.admit("b", expires_at=NOW + 20, now=NOW)
    assert not register.admit("a", expires_at=NOW + 10, now=NOW + 5), "replay"
    assert not register.admit("c", expires_at=NOW + 30, now=NOW + 5), "full"
    # "a" expires; "c" fits; "a" may be reused only once it has expired.
    assert register.admit("c", expires_at=NOW + 30, now=NOW + 11)
    assert not register.admit("b", expires_at=NOW + 20, now=NOW + 11)
    assert not register.admit("a", expires_at=NOW + 40, now=NOW + 12), "full again"
    assert register.admit("a", expires_at=NOW + 40, now=NOW + 21), "b expired"
    assert NONCE_CAPACITY >= 1024


def test_the_edge_key_and_the_assertion_never_reach_the_app_a_log_or_a_refusal(
    key: bytes, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    recorder, client = _guarded()
    good = _assertion(key, target="/anything")
    client.get("/anything", headers={EDGE_ASSERTION_HEADER: good})
    [seen] = recorder.seen
    assert EDGE_ASSERTION_HEADER.encode() not in {name for name, _ in seen}
    wrong = client.get("/anything", headers={EDGE_ASSERTION_HEADER: good + "!"})
    for secret in (key.decode(), good):
        assert secret not in wrong.text and secret not in str(wrong.headers)
        assert secret not in caplog.text


def test_dev_mode_ignores_an_assertion_and_keeps_the_role_header_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(EDGE_TOKEN_ENV, raising=False)
    monkeypatch.setenv(TRUST_SWITCH, "1")
    recorder, client = _guarded()
    subject = str(uuid4())
    response = client.get(
        "/api/v1/cases",
        headers={
            EDGE_ASSERTION_HEADER: "v1.not.checked",
            "x-caos-user": subject,
            "x-caos-role": "ADMIN",
        },
    )
    assert response.status_code == 200
    [seen] = recorder.seen
    assert EDGE_ASSERTION_HEADER.encode() not in {name for name, _ in seen}
    assert _actor_of(seen) == (subject, GlobalRole.ADMIN)
