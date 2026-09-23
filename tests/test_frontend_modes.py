"""The UI fixture server is explicit, and local gates say what they prove."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import check_postgres
import check_pr_size
import psycopg
import pytest

REPO = Path(__file__).resolve().parents[1]


def _read(path: str) -> str:
    return (REPO / path).read_text(encoding="utf-8")


def test_frontend_commands_separate_real_and_demo_artifacts() -> None:
    package = _read("frontend/package.json")

    assert '"dev:demo": "vite --mode demo"' in package
    assert '"build:demo": "vite build --mode demo --outDir dist-demo' in package
    assert '"preview:demo": "vite preview --mode demo --outDir dist-demo' in package
    assert '"test": "vitest run --mode demo"' in package


def test_vite_defaults_to_the_real_loopback_api() -> None:
    config = _read("frontend/vite.config.ts")

    assert 'target: "http://127.0.0.1:8000"' in config
    assert 'mode === "demo"' in config
    assert "configurePreviewServer" in config
    assert '["GET", "HEAD"].includes(req.method' in config
    assert "405," in config
    assert 'code: "READ_ONLY_DEMO"' in config


def _node_and_vite() -> str:
    node = shutil.which("node")
    if node is None or not (REPO / "frontend/node_modules/vite/bin/vite.js").is_file():
        # The backend CI job installs no Node; the frontend job builds `dist` itself.
        pytest.skip("node and frontend/node_modules are required")
    return node


# Drives the real proxy hook the dev server installs: a Node OutgoingMessage
# holds headers exactly as http-proxy's proxyReq does, without a socket.
PROXY_PROBE = """
import { OutgoingMessage } from "node:http";
import { EventEmitter } from "node:events";
const { devProxy } = await import(new URL("./vite.config.ts", `file://${process.cwd()}/`));
const env = JSON.parse(process.argv[1]);
const headers = JSON.parse(process.argv[2]);
const route = devProxy(env)["/api"];
const proxy = new EventEmitter();
route.configure(proxy, route);
const proxyReq = new OutgoingMessage();
for (const [name, value] of Object.entries(headers)) proxyReq.setHeader(name, value);
proxy.emit("proxyReq", proxyReq, { headers }, {});
const out = {};
for (const name of proxyReq.getHeaderNames()) out[name] = proxyReq.getHeader(name);
console.log(JSON.stringify({ target: route.target, headers: out }));
"""

DEV_USER = "00000000-0000-4000-8000-00000000d001"
CLIENT_HEADERS = {
    "accept": "application/json",
    "idempotency-key": "k-1",
    "x-caos-user": "11111111-1111-4111-8111-111111111111",
    "X-CAOS-ROLE": "ADMIN",
    "x-caos-edge-token": "forged",
    "x-caos-edge-assertion": "forged",
    "x_caos_user": "11111111-1111-4111-8111-111111111111",
    "x-forwarded-groups": "caos-admins",
    "x-forwarded-for": "203.0.113.9",
    "forwarded": "for=203.0.113.9",
}


def _proxied(env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            _node_and_vite(),
            "--input-type=module",
            "-e",
            PROXY_PROBE,
            json.dumps(env),
            json.dumps(CLIENT_HEADERS),
        ],
        cwd=REPO / "frontend",
        check=False,
        capture_output=True,
        text=True,
        env={"PATH": os.environ.get("PATH", "")},
    )


def test_the_dev_proxy_strips_client_identity_and_injects_the_local_actor() -> None:
    injected = _proxied({"CAOS_DEV_USER": DEV_USER})
    assert injected.returncode == 0, injected.stderr
    document = json.loads(injected.stdout)
    assert document["target"] == "http://127.0.0.1:8000"
    assert document["headers"] == {
        "accept": "application/json",
        "idempotency-key": "k-1",
        "x-caos-user": DEV_USER,
        "x-caos-role": "ANALYST",
    }

    reader = json.loads(
        _proxied({"CAOS_DEV_USER": DEV_USER, "CAOS_DEV_ROLE": "READER"}).stdout
    )
    assert reader["headers"]["x-caos-role"] == "READER"

    # No local actor: the browser's forgery is still removed, and nothing is
    # injected, so the API answers 401 rather than believing the client.
    anonymous = json.loads(_proxied({}).stdout)
    assert anonymous["headers"] == {
        "accept": "application/json",
        "idempotency-key": "k-1",
    }

    bad_actors = (
        {"CAOS_DEV_USER": "alice"},
        {"CAOS_DEV_USER": DEV_USER, "CAOS_DEV_ROLE": "ROOT"},
    )
    for bad in bad_actors:
        refused = _proxied(bad)
        assert refused.returncode != 0
        assert "alice" not in refused.stderr and "ROOT" not in refused.stderr


def test_the_dev_proxy_is_absent_from_demo_mode_and_reads_only_dev_names() -> None:
    config = _read("frontend/vite.config.ts")

    assert 'mode === "demo" || command !== "serve"' in config
    assert ": devProxy(" in config
    assert 'loadEnv(mode, REPO_ROOT, "CAOS_DEV_")' in config
    assert "VITE_CAOS" not in config
    example = _read(".env.example")
    assert f"CAOS_DEV_USER={DEV_USER}\n" in example
    assert "CAOS_DEV_ROLE=ANALYST\n" in example


def test_the_doctor_checks_the_dev_actor_without_printing_it(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "dev_doctor", REPO / "scripts/dev_doctor.py"
    )
    assert spec is not None and spec.loader is not None
    doctor = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(doctor)
    tools = [
        ("node", "24.1.0"),
        ("npm", "11.0.0"),
        ("uv", "0.12.0"),
        ("docker", "29.0.0"),
        ("docker compose", "5.2.0"),
        ("pre-commit", "4.6.2"),
        ("databricks", "v1.17.0"),
    ]
    monkeypatch.setattr(doctor, "PYTHON_VERSION", (3, 13))
    monkeypatch.setattr(doctor, "_tool_versions", lambda: tools)
    for name in doctor.REQUIRED_CONFIGURATION:
        monkeypatch.setenv(name, "configured")

    monkeypatch.delenv("CAOS_DEV_USER", raising=False)
    monkeypatch.delenv("CAOS_DEV_ROLE", raising=False)
    assert doctor.main() == 0
    assert "CAOS_DEV_USER: absent (dev UI answers 401)" in capsys.readouterr().out

    monkeypatch.setenv("CAOS_DEV_USER", DEV_USER)
    monkeypatch.setenv("CAOS_DEV_ROLE", "READER")
    assert doctor.main() == 0
    captured = capsys.readouterr()
    assert "CAOS_DEV_USER: present" in captured.out
    assert DEV_USER not in captured.out + captured.err

    monkeypatch.setenv("CAOS_DEV_USER", "alice-do-not-print")
    monkeypatch.setenv("CAOS_DEV_ROLE", "ROOT-do-not-print")
    assert doctor.main() == 1
    captured = capsys.readouterr()
    assert "CAOS_DEV_USER must be a UUID" in captured.err
    assert "CAOS_DEV_ROLE must be READER, ANALYST or ADMIN" in captured.err
    assert "do-not-print" not in captured.out + captured.err


IDENTITY_MARKERS = ("x-caos-", "CAOS_DEV_", DEV_USER)

DEMO_MARKERS = (
    "fixture=",
    "/api/sections/",
    "READ_ONLY_DEMO",
    "READ-ONLY DEMONSTRATION",
    "caos-fixtures",
    *IDENTITY_MARKERS,
)


def _demo_leaks(dist: Path) -> list[str]:
    """Every fixture file or demo marker a built export carries."""
    fixtures = {
        path.name for path in (REPO / "frontend/fixtures").rglob("*") if path.is_file()
    }
    leaks: list[str] = []
    files = [path for path in dist.rglob("*") if path.is_file()]
    if not files:
        return ["<nothing scanned>"]
    for path in files:
        if path.name in fixtures:
            leaks.append(f"{path.name}: fixture file")
        text = path.read_bytes().decode("utf-8", errors="replace")
        leaks.extend(
            f"{path.name}: {marker}" for marker in DEMO_MARKERS if marker in text
        )
    return leaks


def test_the_demo_scan_finds_fixtures_markers_and_an_empty_export(
    tmp_path: Path,
) -> None:
    assert _demo_leaks(tmp_path) == ["<nothing scanned>"]
    (tmp_path / "assets").mkdir()
    (tmp_path / "assets/index.js").write_text(
        'fetch("/x?fixture=gate")', encoding="utf-8"
    )
    (tmp_path / "directory.json").write_text("{}", encoding="utf-8")
    assert sorted(_demo_leaks(tmp_path)) == [
        "directory.json: fixture file",
        "index.js: fixture=",
    ]


def test_the_production_build_carries_no_dev_actor_or_identity_header(
    tmp_path: Path,
) -> None:
    (tmp_path / "assets").mkdir()
    (tmp_path / "assets/index.js").write_text(
        f'h.set("X-CAOS-USER", "{DEV_USER}")', encoding="utf-8"
    )
    assert _demo_leaks(tmp_path) == [f"index.js: {DEV_USER}"]
    (tmp_path / "assets/index.js").write_text(
        'h.set("x-caos-role", "ADMIN")', encoding="utf-8"
    )
    assert _demo_leaks(tmp_path) == ["index.js: x-caos-"]


def test_production_build_contains_no_fixture_or_demo_route(tmp_path: Path) -> None:
    node = _node_and_vite()
    vite = REPO / "frontend/node_modules/vite/bin/vite.js"
    out = tmp_path / "dist"
    subprocess.run(
        [
            node,
            str(vite),
            "build",
            "--outDir",
            str(out),
            "--emptyOutDir",
            "--logLevel",
            "error",
        ],
        cwd=REPO / "frontend",
        check=True,
        capture_output=True,
        # A configured local actor must not reach the export.
        env={
            "PATH": os.environ.get("PATH", ""),
            "NODE_ENV": "production",
            "CAOS_DEV_USER": DEV_USER,
            "CAOS_DEV_ROLE": "ADMIN",
        },
    )
    assert (out / "index.html").is_file()
    assert _demo_leaks(out) == []


def test_fixture_browser_launchers_never_reuse_an_unrelated_server() -> None:
    playwright = _read("frontend/playwright.config.ts")
    axe = _read("frontend/scripts/a11y-axe.mjs")

    assert 'command: "npm run preview:demo"' in playwright
    assert "reuseExistingServer: false" in playwright
    assert '"--mode",' in axe and '"demo",' in axe
    assert '"--outDir",' in axe and '"dist-demo",' in axe


def test_postgres_preflight_does_not_echo_the_connection_string() -> None:
    sentinel = "postgresql://secret:do-not-print@127.0.0.1:1/caos"
    result = subprocess.run(
        [sys.executable, str(REPO / "scripts/check_postgres.py")],
        env={"CAOS_TEST_POSTGRES_URL": sentinel},
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    assert "test PostgreSQL is not reachable" in result.stdout
    assert sentinel not in result.stdout + result.stderr


def test_postgres_preflight_main_covers_success_missing_and_failure(
    empty_database: str,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("CAOS_TEST_POSTGRES_URL", empty_database)
    assert check_postgres.main() == 0

    monkeypatch.delenv("CAOS_TEST_POSTGRES_URL")
    assert check_postgres.main() == 1
    assert "CAOS_TEST_POSTGRES_URL is required" in capsys.readouterr().out

    sentinel = "database-secret-do-not-print"
    monkeypatch.setenv("CAOS_TEST_POSTGRES_URL", sentinel)

    def refuse(*_args: object, **_kwargs: object) -> None:
        raise psycopg.OperationalError(sentinel)

    monkeypatch.setattr(psycopg, "connect", refuse)
    assert check_postgres.main() == 1
    captured = capsys.readouterr()
    assert "test PostgreSQL is not reachable" in captured.out
    assert sentinel not in captured.out + captured.err


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)


def _size_repo(tmp_path: Path, changed_lines: int) -> tuple[Path, str]:
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "config", "user.email", "test@example.invalid")
    _git(tmp_path, "config", "user.name", "Gate test")
    (tmp_path / "kept.txt").write_text("", encoding="utf-8")
    _git(tmp_path, "add", "kept.txt")
    _git(tmp_path, "commit", "-qm", "base")
    base = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    (tmp_path / "kept.txt").write_text("x\n" * changed_lines, encoding="utf-8")
    _git(tmp_path, "add", "kept.txt")
    _git(tmp_path, "commit", "-qm", "change")
    return tmp_path, base


def test_changed_lines_accepts_the_exact_threshold(tmp_path: Path) -> None:
    repo, base = _size_repo(tmp_path, 800)

    result = subprocess.run(
        [sys.executable, str(REPO / "scripts/check_pr_size.py"), base],
        cwd=repo,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    assert "changed lines: 800" in result.stdout


def test_size_gate_main_is_measured_in_process(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    repo, base = _size_repo(tmp_path, 800)
    monkeypatch.chdir(repo)
    assert check_pr_size.changed_lines(base) == 800

    monkeypatch.setattr(sys, "argv", ["check_pr_size.py", base])
    assert check_pr_size.main() == 0
    assert "changed lines: 800" in capsys.readouterr().out

    (repo / "kept.txt").write_text("x\n" * 801, encoding="utf-8")
    _git(repo, "add", "kept.txt")
    _git(repo, "commit", "-qm", "over limit")
    assert check_pr_size.main() == 1
    assert "PR too large" in capsys.readouterr().err

    monkeypatch.setattr(sys, "argv", ["check_pr_size.py"])
    assert check_pr_size.main() == 2
    assert "PR_BASE is required" in capsys.readouterr().err

    monkeypatch.setattr(sys, "argv", ["check_pr_size.py", "not-a-base"])
    assert check_pr_size.main() == 2
    assert "not-a-base" in capsys.readouterr().err

    monkeypatch.setattr(shutil, "which", lambda _name: None)
    with pytest.raises(FileNotFoundError):
        check_pr_size.changed_lines(base)


def test_size_gate_refuses_a_base_git_could_read_as_an_option(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A base starting with "-" is argument injection, not shell injection:
    the argv list already stops shell metacharacters, but git itself would
    still read `--upload-pack=...` as an option rather than a revision."""
    repo, _base = _size_repo(tmp_path, 1)
    monkeypatch.chdir(repo)
    with pytest.raises(ValueError, match="not a plain git revision"):
        check_pr_size.changed_lines("--evil")

    monkeypatch.setattr(sys, "argv", ["check_pr_size.py", "--evil"])
    assert check_pr_size.main() == 2
    assert "--evil" in capsys.readouterr().err


def test_size_gate_rejects_over_limit_and_invalid_base(tmp_path: Path) -> None:
    repo, base = _size_repo(tmp_path, 801)

    over = subprocess.run(
        [sys.executable, str(REPO / "scripts/check_pr_size.py"), base],
        cwd=repo,
        check=False,
        capture_output=True,
        text=True,
    )
    invalid = subprocess.run(
        [sys.executable, str(REPO / "scripts/check_pr_size.py"), "not-a-base"],
        cwd=repo,
        check=False,
        capture_output=True,
        text=True,
    )
    missing = subprocess.run(
        [sys.executable, str(REPO / "scripts/check_pr_size.py")],
        cwd=repo,
        check=False,
        capture_output=True,
        text=True,
    )

    assert over.returncode != 0
    assert "PR too large" in over.stderr
    assert invalid.returncode != 0
    assert "not-a-base" in invalid.stderr
    assert missing.returncode != 0
    assert "PR_BASE is required" in missing.stderr


def test_a_binary_file_change_is_refused_rather_than_skipped(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """FP-10: `git diff --numstat` prints "-\\t-\\t<path>" for a binary file.
    `added != "-" and removed != "-"` silently dropped that row from the
    total rather than counting or refusing it, so a PR could add or change
    an unbounded binary blob under no line-count ceiling at all."""
    repo, base = _size_repo(tmp_path, 1)
    (repo / "blob.bin").write_bytes(b"\x00\x01binary\xffcontent" * 100)
    _git(repo, "add", "blob.bin")
    _git(repo, "commit", "-qm", "add a binary file")
    monkeypatch.chdir(repo)

    with pytest.raises(ValueError, match="binary file"):
        check_pr_size.changed_lines(base)

    monkeypatch.setattr(sys, "argv", ["check_pr_size.py", base])
    assert check_pr_size.main() == 2


def test_the_vendored_bundle_is_not_counted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`vendor/deploy-v/` is read-only and pinned; a diff that only touches it is
    not work this policy is measuring (docs/AI_CODE_QUALITY.md). Git's default
    pathspec matching needs a `/` before the name, so `**/vendor/**` alone never
    matched a root-level `vendor/...` path and the bundle was counted in full."""
    repo, base = _size_repo(tmp_path, 1)
    (repo / "vendor" / "deploy-v").mkdir(parents=True)
    (repo / "vendor" / "deploy-v" / "SKILL.md").write_text(
        "x\n" * 900, encoding="utf-8"
    )
    _git(repo, "add", "vendor")
    _git(repo, "commit", "-qm", "vendor the bundle")
    monkeypatch.chdir(repo)

    assert check_pr_size.changed_lines(base) == 1


def test_qualification_documents_are_excluded_but_manifests_are_counted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo, base = _size_repo(tmp_path, 1)
    roots = (
        repo / "qualification/ccl-fy2025-full-relative-value",
        repo / "qualification/ba-fy2025",
    )
    for root in roots:
        (root / "documents").mkdir(parents=True)
        (root / "documents/evidence.txt").write_text("x\n" * 900, encoding="utf-8")
        (root / "qualification.json").write_text("manifest\n", encoding="utf-8")
        (root / "RESULT.md").write_text("result\n", encoding="utf-8")
    _git(repo, "add", "qualification")
    _git(repo, "commit", "-qm", "add qualification evidence")
    monkeypatch.chdir(repo)

    assert check_pr_size.changed_lines(base) == 5
