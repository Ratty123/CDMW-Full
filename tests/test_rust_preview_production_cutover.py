from __future__ import annotations

import ast
import json
from pathlib import Path

from cdmw.modding.mesh_parser import ParsedMesh, SubMesh
from cdmw.services.mesh_rust_contract import (
    RUST_MESH_RENDERER,
    RUST_PREVIEW_BACKEND,
    RUST_PREVIEW_PACKAGE,
    RUST_PREVIEW_PROTOCOL,
    RUST_PREVIEW_REQUIRED_CAPABILITIES,
)
from cdmw.services.mesh_rust_preview_cache import (
    RUST_PREVIEW_CACHE_SCHEMA,
    rust_preview_package_cache_root,
)
from cdmw.services.mesh_rust_preview_package import (
    build_rust_preview_package,
    rust_preview_package_from_path,
    validate_rust_preview_package,
)
from cdmw.ui.preview.rust_host import RustPreviewHostFrame
from cdmw.ui.preview.rust_session import RustPreviewSessionController


ROOT = Path(__file__).resolve().parents[1]

PRODUCTION_HOST_OWNERS = (
    "cdmw/ui/archive_browser/preview_layout.py",
    "cdmw/ui/archive_browser/reference_preview.py",
    "cdmw/ui/archive_browser/material_sidecar_editor_dialog.py",
    "cdmw/ui/archive_browser/static_replacement_dialog_preview_shell.py",
    "cdmw/ui/archive_browser/attachment_safe_placement_dialog.py",
    "cdmw/ui/model_library/preview.py",
    "cdmw/ui/new_item/item_preview.py",
    "cdmw/ui/new_item/effect_placement_dialog.py",
)


def _triangle() -> ParsedMesh:
    submesh = SubMesh(
        name="triangle",
        material="test",
        vertices=[(-0.5, -0.5, 0.0), (0.5, -0.5, 0.0), (0.0, 0.5, 0.0)],
        normals=[(0.0, 0.0, 1.0)] * 3,
        uvs=[(0.0, 1.0), (1.0, 1.0), (0.5, 0.0)],
        faces=[(0, 1, 2)],
        vertex_count=3,
        face_count=1,
    )
    return ParsedMesh(
        path="fixture://rust-preview-triangle.pac",
        format="pac",
        bbox_min=(-0.5, -0.5, 0.0),
        bbox_max=(0.5, 0.5, 0.0),
        submeshes=[submesh],
        total_vertices=3,
        total_faces=1,
        has_uvs=True,
    )


def _called_names(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
    result: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if isinstance(node.func, ast.Name):
            result.add(node.func.id)
        elif isinstance(node.func, ast.Attribute):
            result.add(node.func.attr)
    return result


def test_all_eight_production_consumers_construct_only_the_rust_host() -> None:
    assert RustPreviewHostFrame.__name__ == "RustPreviewHostFrame"
    assert RustPreviewSessionController.__name__ == "RustPreviewSessionController"
    for relative in PRODUCTION_HOST_OWNERS:
        path = ROOT / relative
        calls = _called_names(path)
        assert "RustPreviewHostFrame" in calls, relative
        assert "DotNetPreviewHostFrame" not in calls, relative


def test_rust_preview_package_is_bounded_read_only_and_self_identifying(
    tmp_path: Path,
) -> None:
    package = build_rust_preview_package(
        _triangle(),
        output_package_dir=tmp_path / "package",
        include_material_resources=False,
    )
    assert validate_rust_preview_package(package.package_dir) == ()
    resolved = rust_preview_package_from_path(package.package_dir)
    assert resolved.package_dir == package.package_dir.resolve()
    manifest = json.loads(package.manifest_path.read_text(encoding="utf-8"))
    assert manifest["schema"] == RUST_PREVIEW_PACKAGE
    assert manifest["protocol"] == RUST_PREVIEW_PROTOCOL
    assert manifest["renderer"] == RUST_MESH_RENDERER
    assert manifest["edit_backend"] == RUST_PREVIEW_BACKEND
    assert manifest["interaction_profile"] == "read_only"
    assert manifest["output_policy"] == {
        "archive_writes": False,
        "policy": "read_only_preview",
    }
    assert not package.edit_operations_path.exists()


def test_static_replacement_is_the_only_mesh_input_profile(tmp_path: Path) -> None:
    package = build_rust_preview_package(
        _triangle(),
        output_package_dir=tmp_path / "static",
        include_material_resources=False,
        interaction_profile="static_replacement",
    )
    manifest = json.loads(package.manifest_path.read_text(encoding="utf-8"))
    assert manifest["interaction_profile"] == "static_replacement"
    assert manifest["output_policy"]["archive_writes"] is False


def test_rust_cache_namespace_cannot_alias_the_retired_preview_cache(
    tmp_path: Path,
) -> None:
    root = rust_preview_package_cache_root(tmp_path)
    assert RUST_PREVIEW_CACHE_SCHEMA == 2
    assert root == tmp_path / "rust_wgpu_v1"
    assert "dotnet" not in root.name.casefold()
    assert "vortice" not in root.name.casefold()


def test_compiled_preview_contract_declares_the_complete_runtime_surface() -> None:
    source = (
        ROOT / "tools/rust_mesh_lab/apps/cdmw_mesh_lab/src/cdmw_preview.rs"
    ).read_text(encoding="utf-8")
    assert '"viewport_only": true' in source
    assert '"read_only_mutations_rejected": true' in source
    for capability in RUST_PREVIEW_REQUIRED_CAPABILITIES:
        assert f'"{capability}"' in source
    for command in (
        "package_load_request",
        "presentation_state_update",
        "overlay_state_update",
        "scene_state_update",
        "material_parameter_update",
        "capture_request",
        "preview_vertex_update",
        "preview_triangle_update",
        "selection_update",
    ):
        assert f'"{command}"' in source


def test_release_paths_reject_and_never_stage_vortice_payloads() -> None:
    spec = (ROOT / "CrimsonDesertModWorkbench.spec").read_text(encoding="utf-8")
    build = (ROOT / "build_pyside6_app.ps1").read_text(encoding="utf-8")
    workflow = (ROOT / ".github/workflows/windows-build.yml").read_text(
        encoding="utf-8"
    )
    assert "Retired Vortice preview payload was collected" in spec
    assert "Vortice*.dll" not in spec  # matcher is lower-case and generic
    for retired_module in (
        "cdmw.rendering.native_preview_package",
        "cdmw.rendering.native_preview_package_writer",
        "cdmw.services.mesh_dotnet_preview_package",
        "cdmw.services.native_dotnet_preview_adapter",
    ):
        assert retired_module in spec
    for source in (build, workflow):
        assert "dotnet_mesh_editor_experiment" not in source
        assert "cdmw-mesh-dotnet-editor" not in source
        assert "D3D11MaterialShaders.hlsl" not in source


def test_active_rust_material_and_preview_paths_have_no_vortice_launcher() -> None:
    for relative in (
        "cdmw/services/mesh_rust_authoring.py",
        "cdmw/services/mesh_rust_preview_package.py",
        "cdmw/services/mesh_rust_preview_cache.py",
        "cdmw/ui/preview/dotnet_session.py",
    ):
        source = (ROOT / relative).read_text(encoding="utf-8-sig")
        assert "resolve_mesh_dotnet_experiment_editor" not in source
        assert "mesh_dotnet_experiment_command" not in source
        assert "--export-material-layer-composites" not in source
