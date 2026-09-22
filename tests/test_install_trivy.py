"""The pinned Trivy installer refuses what it did not pin (docs/DECISIONS.md §90).

No network: the release location is pointed at a local directory holding an
archive of the right name and the wrong bytes, which is exactly the case the
digest exists for.
"""

from __future__ import annotations

import os
import subprocess
import tarfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "install_trivy.sh"
ASSETS = ("macOS-ARM64", "macOS-64bit", "Linux-64bit", "Linux-ARM64")


def _install(version: str, dest: Path, base: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(SCRIPT), version, str(dest)],
        env={**os.environ, "TRIVY_BASE_URL": base.as_uri()},
        capture_output=True,
        text=True,
        check=False,
    )


def test_an_archive_whose_digest_is_not_pinned_is_refused_before_extraction(
    tmp_path: Path,
) -> None:
    impostor = tmp_path / "trivy"
    impostor.write_text("#!/bin/sh\necho 'Version: 0.70.0'\n")
    impostor.chmod(0o755)
    releases = tmp_path / "releases"
    releases.mkdir()
    for asset in ASSETS:
        with tarfile.open(releases / f"trivy_0.70.0_{asset}.tar.gz", "w:gz") as tar:
            tar.add(impostor, arcname="trivy")
    dest = tmp_path / "tools"

    answered = _install("0.70.0", dest, releases)

    assert answered.returncode == 1
    assert "is not the pinned" in answered.stderr
    assert not (dest / "trivy").exists()


def test_a_version_with_no_pinned_digests_is_refused(tmp_path: Path) -> None:
    answered = _install("0.72.0", tmp_path / "tools", tmp_path)

    assert answered.returncode == 1
    assert "no pinned digests" in answered.stderr
