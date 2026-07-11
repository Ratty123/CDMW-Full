from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path

from cdmw.ui.mesh_editor.workspace import MeshEditorWorkspace, MeshUvCanvas
from cdmw.ui.mesh_editor.workspace_interaction import WorkspaceInteractionMixin
from cdmw.ui.mesh_editor.workspace_panel_builder import WorkspacePanelBuilderMixin
from cdmw.ui.mesh_editor.workspace_reports import WorkspaceReportMixin
from cdmw.ui.mesh_editor.workspace_shell_builder import WorkspaceShellBuilderMixin
from cdmw.ui.mesh_editor.workspace_skeleton_state import WorkspaceSkeletonStateMixin
from cdmw.ui.mesh_editor.workspace_state import WorkspaceStateMixin
from cdmw.ui.mesh_editor.workspace_views import MeshUvCanvas as OwnedMeshUvCanvas


REPO_ROOT = Path(__file__).resolve().parents[1]


def test_workspace_facade_reuses_owner_methods_and_view() -> None:
    owners = (
        (WorkspaceStateMixin, "update_workspace_summary"),
        (WorkspaceSkeletonStateMixin, "update_skeleton_summary"),
        (WorkspaceShellBuilderMixin, "_build_preview_area"),
        (WorkspacePanelBuilderMixin, "_build_skeleton_panel"),
        (WorkspaceReportMixin, "update_export_validation"),
        (WorkspaceInteractionMixin, "_sync_skeleton_pose_controls"),
    )
    for owner, name in owners:
        assert getattr(MeshEditorWorkspace, name) is getattr(owner, name), name
    assert MeshUvCanvas is OwnedMeshUvCanvas


def test_workspace_owners_obey_size_caps() -> None:
    owner_root = REPO_ROOT / "cdmw" / "ui" / "mesh_editor"
    facade = owner_root / "workspace.py"
    assert len(facade.read_text(encoding="utf-8").splitlines()) <= 300
    for path in sorted(owner_root.glob("workspace_*.py")):
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source)
        assert len(source.splitlines()) <= 800, path
        sizes = (
            int(node.end_lineno or node.lineno) - node.lineno + 1
            for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        )
        assert max(sizes, default=0) <= 150, path


def test_workspace_owner_first_import_keeps_method_identity() -> None:
    script = (
        "from cdmw.ui.mesh_editor.workspace_skeleton_state import WorkspaceSkeletonStateMixin as owner; "
        "from cdmw.ui.mesh_editor.workspace import MeshEditorWorkspace as facade; "
        "assert facade.update_skeleton_summary is owner.update_skeleton_summary"
    )
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout
