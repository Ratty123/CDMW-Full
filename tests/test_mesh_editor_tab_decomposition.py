from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

from cdmw.ui.mesh_editor.tab import MeshEditorTab
from cdmw.ui.mesh_editor.tab_actions import MeshEditorActionsMixin
from cdmw.ui.mesh_editor.tab_dotnet_protocol import MeshEditorDotNetProtocolMixin
from cdmw.ui.mesh_editor.tab_interaction import MeshEditorInteractionMixin
from cdmw.ui.mesh_editor.tab_native_preview import MeshEditorNativePreviewMixin
from cdmw.ui.mesh_editor.tab_reports import MeshEditorReportsMixin
from cdmw.ui.mesh_editor.tab_session_runtime import MeshEditorSessionMixin
from cdmw.ui.mesh_editor.tab_shell import MeshEditorTabShellMixin


REPO_ROOT = Path(__file__).resolve().parents[1]


def test_mesh_editor_tab_keeps_public_methods_on_bounded_owners() -> None:
    owners = (
        (MeshEditorTabShellMixin, "_build_empty_state"),
        (MeshEditorNativePreviewMixin, "write_standalone_native_preview_package"),
        (MeshEditorDotNetProtocolMixin, "_handle_dotnet_protocol_event"),
        (MeshEditorReportsMixin, "_save_standalone_rebuild_report_requested"),
        (MeshEditorSessionMixin, "open_mesh_file_session_async"),
        (MeshEditorInteractionMixin, "_standalone_native_mesh_edit_stroke_command"),
        (MeshEditorActionsMixin, "apply_texture_editor_dds_preview"),
    )
    for owner, name in owners:
        assert getattr(MeshEditorTab, name) is getattr(owner, name), name


def test_mesh_editor_tab_owners_obey_size_caps() -> None:
    owner_root = REPO_ROOT / "cdmw" / "ui" / "mesh_editor"
    facade = owner_root / "tab.py"
    assert len(facade.read_text(encoding="utf-8").splitlines()) <= 400
    for path in sorted(owner_root.glob("tab_*.py")):
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source)
        assert len(source.splitlines()) <= 800, path
        sizes = (
            int(node.end_lineno or node.lineno) - node.lineno + 1
            for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        )
        assert max(sizes, default=0) <= 150, path


def test_mesh_editor_owner_first_import_keeps_method_identity() -> None:
    script = (
        "from cdmw.ui.mesh_editor.tab_interaction import MeshEditorInteractionMixin as owner; "
        "from cdmw.ui.mesh_editor.tab import MeshEditorTab as facade; "
        "assert facade._standalone_native_mesh_edit_stroke_command is "
        "owner._standalone_native_mesh_edit_stroke_command"
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


def test_native_mesh_availability_is_lightweight_and_identity_stable() -> None:
    script = """
import sys
from cdmw.modding import mesh_native_availability as owner
from cdmw.services import mesh_workflow_service
from cdmw.ui.mesh_editor import tab
assert "cdmw.modding.mesh_native_core" not in sys.modules
assert mesh_workflow_service.native_mesh_core_available is owner.native_mesh_core_available
assert tab.native_mesh_core_available is owner.native_mesh_core_available
from cdmw.modding import mesh_native_core
assert mesh_native_core.native_mesh_core_available is owner.native_mesh_core_available
assert mesh_native_core.find_native_mesh_core_binary is owner.find_native_mesh_core_binary
"""
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout


def test_embedded_dotnet_ready_refreshes_controls_and_replays_parameters_once() -> None:
    calls = {"controls": 0, "parameters": 0}
    builder = SimpleNamespace(
        _mesh_editor_embedded_dotnet_active=False,
        _mesh_editor_embedded_resident_material_parameters_supported=lambda: True,
        _refresh_material_authority_live_control_states=lambda: calls.update(controls=calls["controls"] + 1),
        _replay_resident_material_authority_parameters=lambda: calls.update(parameters=calls["parameters"] + 1),
    )
    shell = SimpleNamespace(
        standalone_dotnet_embedded_state="launching",
        active_builder=lambda: builder,
    )

    MeshEditorTabShellMixin._set_embedded_dotnet_state(shell, "ready", active=True)
    MeshEditorTabShellMixin._set_embedded_dotnet_state(shell, "ready", active=True)
    MeshEditorTabShellMixin._set_embedded_dotnet_state(shell, "closed", active=False)

    assert calls == {"controls": 3, "parameters": 1}
    assert builder._mesh_editor_embedded_dotnet_state == "closed"
    assert not builder._mesh_editor_embedded_dotnet_active
