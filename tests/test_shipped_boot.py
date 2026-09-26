"""The file set a stand-in deployment ships, as `tests/shipped_boot.py` lays
it out before booting it (CF-001, N47): exactly what the last deployment's
source path holds, nothing from this checkout, and nothing outside the tree."""

from __future__ import annotations

from pathlib import Path

import pytest
from shipped_boot import shipped_tree
from workspace_stub import WorkspaceStub

SOURCE = "/Workspace/caos-bundle/dev/files"


def test_the_tree_is_the_last_deployment_s_files_and_nothing_else(
    tmp_path: Path,
) -> None:
    stub = WorkspaceStub()
    stub.deployments = ["/Workspace/caos-bundle/old/files", SOURCE]
    stub.workspace_files = {
        f"{SOURCE}/caos/serve.py": b"print('served')\n",
        f"{SOURCE}/app.yaml": b"command: []\n",
        "/Workspace/caos-bundle/old/files/caos/serve.py": b"stale",
        "/Workspace/caos-bundle/dev/state/deploy.lock": b"lock",
    }
    assert shipped_tree(stub, tmp_path / "tree") == 2
    written = sorted(
        path.relative_to(tmp_path / "tree").as_posix()
        for path in (tmp_path / "tree").rglob("*")
        if path.is_file()
    )
    assert written == ["app.yaml", "caos/serve.py"]
    assert (tmp_path / "tree" / "caos" / "serve.py").read_bytes() == (
        b"print('served')\n"
    )


@pytest.mark.parametrize(
    "files",
    [{}, {"/Workspace/elsewhere/app.yaml": b"x"}, {f"{SOURCE}/../../x": b"x"}],
    ids=["nothing-synced", "nothing-under-the-source", "a-path-that-leaves"],
)
def test_no_deployment_an_empty_one_or_a_path_outside_the_tree_is_refused(
    tmp_path: Path, files: dict[str, bytes]
) -> None:
    stub = WorkspaceStub()
    with pytest.raises(ValueError):
        shipped_tree(stub, tmp_path / "tree")  # no deployment at all
    stub.deployments = [SOURCE]
    stub.workspace_files = files
    with pytest.raises(ValueError):
        shipped_tree(stub, tmp_path / "tree")
