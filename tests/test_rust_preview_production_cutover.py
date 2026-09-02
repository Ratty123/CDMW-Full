from __future__ import annotations

import ast
import hashlib
import json
import struct
from pathlib import Path

import pytest

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
    build_or_lookup_rust_preview_package,
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


def _write_schema8_preview_core_fixture(
    tmp_path: Path,
) -> tuple[Path, bytes, bytes, bytes]:
    package = tmp_path / "preview-core"
    geometry = package / "geometry"
    geometry.mkdir(parents=True)
    center = (10.0, 20.0, 30.0)
    scale = 2.0
    source_positions = (
        (11.0, 20.0, 30.0),
        (10.0, 21.0, 30.0),
        (10.0, 20.0, 31.0),
    )
    records = []
    for corner, position in enumerate(source_positions):
        normalized = tuple((position[axis] - center[axis]) * scale for axis in range(3))
        records.append(
            struct.pack(
                "<23f",
                *normalized,
                0.0,
                0.0,
                1.0,
                0.64,
                0.64,
                0.56,
                float(corner == 1),
                float(corner == 2),
                1.0,
                0.0,
                0.0,
                0.0,
                1.0,
                0.0,
                0.0,
                0.0,
                1.0,
                float(corner == 0),
                float(corner == 1),
                float(corner == 2),
            )
        )
    geometry_bytes = b"".join(records)
    identity_bytes = b"".join(
        struct.pack("<2i", 0, source_index) for source_index in (7, 8, 9)
    )
    (geometry / "batch_000.bin").write_bytes(geometry_bytes)
    (geometry / "batch_000_identity.bin").write_bytes(identity_bytes)
    texture_bytes = b"DDS " + b"X" * 1024
    texture_path = tmp_path / "helmet_base.dds"
    texture_path.write_bytes(texture_bytes)
    (package / "manifest.json").write_text(
        json.dumps(
            {
                "schema_version": 8,
                "material_semantics_version": 1,
                "material_graph_version": 1,
                "source_path": "character/helmet.pac",
                "format": "pac",
                "normalization_center": list(center),
                "normalization_scale": scale,
                "skeleton_overlay": {
                    "schema_version": 1,
                    "enabled": True,
                    "bones": [],
                },
                "batches": [
                    {
                        "index": 0,
                        "material_name": "helmet",
                        "vertex_file": "geometry/batch_000.bin",
                        "vertex_count": 3,
                        "editor_identity": {
                            "source_submesh_index": 4,
                            "source_local_submesh_index": 4,
                            "source_component_index": 0,
                            "identity_file": "geometry/batch_000_identity.bin",
                        },
                        "material_category": "metal",
                        "shader_family": "standard_v2",
                        "normal_y_policy": "preserve",
                        "alpha_mode": "opaque",
                        "roughness": 0.4,
                        "metalness": 0.8,
                        "dds_textures": {
                            "base": {
                                "slot": "base",
                                "source_path": str(texture_path),
                                "semantic_type": "albedo",
                                "shader_family": "standard_v2",
                            }
                        },
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    return package, geometry_bytes, identity_bytes, texture_bytes


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
    assert RUST_PREVIEW_CACHE_SCHEMA == 3
    assert root == tmp_path / "rust_wgpu_v1"
    assert "dotnet" not in root.name.casefold()
    assert "vortice" not in root.name.casefold()


def test_schema8_preview_core_geometry_bypasses_python_and_large_json_roundtrip(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source, geometry_bytes, identity_bytes, texture_bytes = (
        _write_schema8_preview_core_fixture(tmp_path)
    )

    def reject_python_decode(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("schema-8 preview must not decode geometry in Python")

    monkeypatch.setattr(
        "cdmw.services.mesh_rust_preview_cache.decode_dotnet_native_preview_package",
        reject_python_decode,
    )
    package = build_or_lookup_rust_preview_package(
        source,
        cache_root=tmp_path / "cache",
        archive_identity="helmet-entry",
        cache_mode="balanced",
        max_bytes=64 * 1024 * 1024,
        target_bytes=48 * 1024 * 1024,
    )
    warm = build_or_lookup_rust_preview_package(
        source,
        cache_root=tmp_path / "cache",
        archive_identity="helmet-entry",
        cache_mode="balanced",
        max_bytes=64 * 1024 * 1024,
        target_bytes=48 * 1024 * 1024,
    )

    manifest = json.loads(package.manifest_path.read_text(encoding="utf-8"))
    assert warm.package_dir == package.package_dir
    direct = manifest["preview_core_geometry"]
    assert direct["schema_version"] == 8
    assert direct["normalization_center"] == [10.0, 20.0, 30.0]
    assert direct["normalization_scale"] == 2.0
    assert len(direct["batches"]) == 1
    batch = direct["batches"][0]
    assert batch["vertex_count"] == 3
    assert batch["vertices"]["sha256"] == hashlib.sha256(
        geometry_bytes
    ).hexdigest().upper()
    assert batch["identity"]["sha256"] == hashlib.sha256(
        identity_bytes
    ).hexdigest().upper()
    assert (
        package.package_dir / batch["vertices"]["path"]
    ).read_bytes() == geometry_bytes
    assert (
        package.package_dir / batch["identity"]["path"]
    ).read_bytes() == identity_bytes
    assert len(manifest["textures"]) == 1
    texture_reference = manifest["textures"][0]["file"]
    assert texture_reference["sha256"] == hashlib.sha256(texture_bytes).hexdigest().upper()
    assert (
        package.package_dir / texture_reference["path"]
    ).read_bytes() == texture_bytes
    assert (package.package_dir / "document.json").stat().st_size < 256
    assert (package.package_dir / "channels.json").stat().st_size < 256
    scene = manifest["state"]["preview_scene"]
    assert scene["protocol_version"] == 2
    assert scene["roles"]["editable"]["submesh_indices"] == [0]
    assert scene["skeleton_overlay"] == {
        "schema_version": 1,
        "enabled": True,
        "bones": [],
    }
    assert scene["part_identities"][0][
        "source_submesh_index"
    ] == 4


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
