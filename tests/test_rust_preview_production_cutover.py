from __future__ import annotations

import ast
import hashlib
import json
import struct
from pathlib import Path

import pytest

from cdmw.models import ModelPreviewData, ModelPreviewMesh
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
    build_or_lookup_rust_preview_package_from_model,
    rust_preview_package_cache_root,
)
from cdmw.services.mesh_rust_preview_package import (
    build_rust_preview_package,
    build_rust_preview_package_from_preview_core,
    rust_preview_package_from_path,
    semantic_initial_view,
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
                "material_semantics_version": 10,
                "material_graph_version": 4,
                "material_conservation": {
                    "schema_version": 1,
                    "declared_parameter_count": 0,
                    "transported_parameter_count": 0,
                    "resolved_texture_count": 0,
                    "unresolved_texture_count": 0,
                    "conserved": True,
                    "findings": [],
                    "parameters": [],
                },
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
                        "base_color": [0.62, 0.62, 0.62],
                        "material_layers": [
                            {
                                "owner_wrapper_item_id": "fixture-wrapper-1",
                                "material_wrapper_index": 0,
                                "layer_role": "base",
                                "mask_channel": "r",
                                "source_parameter": "_baseColorTexture",
                                "mask_parameter": "",
                                "diffuse_source": str(texture_path),
                                "diffuse_archive_path": "character/texture/helmet_base.dds",
                                "weight": 1.0,
                                "tint": [1.0, 1.0, 1.0, 1.0],
                            }
                        ],
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


def test_preview_package_carries_semantic_broadside_camera_and_fit_bounds(
    tmp_path: Path,
) -> None:
    bounds = ((-0.1, -2.0, -0.2), (0.1, 2.0, 0.2))
    initial_view = semantic_initial_view(bounds, "x")

    package = build_rust_preview_package(
        _triangle(),
        output_package_dir=tmp_path / "semantic-view",
        include_material_resources=False,
        framing_bounds=bounds,
        initial_view=initial_view,
    )

    manifest = json.loads(package.manifest_path.read_text(encoding="utf-8"))
    assert manifest["state"]["preview_scene"]["framing"]["initial_view"] == {
        "view_direction": [1.0, 0.0, 0.0],
        "screen_up_direction": [0.0, 1.0, 0.0],
        "fit_bounds": [[-0.1, -2.0, -0.2], [0.1, 2.0, 0.2]],
    }


@pytest.mark.parametrize("damage", ["delete", "changed", "escape", "missing_reference", "writable", "texture_reference"])
def test_cached_preview_rejects_incomplete_or_changed_owned_resources(tmp_path: Path, damage: str) -> None:
    package = build_rust_preview_package(_triangle(), output_package_dir=tmp_path / "package", include_material_resources=False)
    manifest = json.loads(package.manifest_path.read_text(encoding="utf-8"))
    resource = package.package_dir / manifest["document"]["path"]
    if damage == "delete":
        resource.unlink()
    elif damage == "changed":
        data = bytearray(resource.read_bytes())
        data[-2] ^= 1
        resource.write_bytes(data)
    elif damage == "escape":
        outside = tmp_path / "outside.json"
        outside.write_bytes(resource.read_bytes())
        manifest["document"]["path"] = "../outside.json"
    elif damage == "missing_reference":
        del manifest["channels"]["sha256"]
    elif damage == "writable":
        manifest["output_policy"]["archive_writes"] = True
    else:
        manifest["textures"] = [{"file": {}}]
    package.manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    assert validate_rust_preview_package(package.package_dir)


@pytest.mark.parametrize("cancel", [False, True])
def test_failed_preview_publication_removes_only_its_staging_directory(tmp_path: Path, monkeypatch, cancel: bool) -> None:
    import cdmw.services.mesh_rust_preview_package as owner
    from cdmw.domain.cancellation import RunCancelled

    unrelated = tmp_path / "keep.txt"
    unrelated.write_text("keep", encoding="utf-8")
    destination = tmp_path / "package"

    def fail_after_geometry(*args, **kwargs):
        assert not destination.exists()
        assert list(tmp_path.glob(".rust-preview-*/package/*.json"))
        raise RunCancelled("cancelled") if cancel else ValueError("injected failure")

    from cdmw.services import mesh_rust_authoring
    monkeypatch.setattr(mesh_rust_authoring, "_mesh_channel_payload", fail_after_geometry)
    with pytest.raises(RunCancelled if cancel else ValueError):
        build_rust_preview_package(_triangle(), output_package_dir=destination, include_material_resources=False)
    assert sorted(path.name for path in tmp_path.iterdir()) == ["keep.txt"]
    assert unrelated.read_text(encoding="utf-8") == "keep"


def test_preview_publication_preserves_an_existing_package(tmp_path: Path) -> None:
    destination = tmp_path / "package"
    destination.mkdir()
    marker = destination / "resident.txt"
    marker.write_text("resident", encoding="utf-8")
    with pytest.raises(FileExistsError):
        build_rust_preview_package(_triangle(), output_package_dir=destination, include_material_resources=False)
    assert marker.read_text(encoding="utf-8") == "resident"


def test_gizmo_preferences_reach_the_resident_preview_payload() -> None:
    from cdmw.models import ModelPreviewRenderSettings
    from cdmw.ui.preview.dotnet_host_render_tuning import render_tuning_payloads

    settings = ModelPreviewRenderSettings()
    settings.gizmo_size_scale = 2.0
    settings.gizmo_handle_size_pixels = 16.0
    settings.gizmo_label_size_pixels = 18.0
    settings.gizmo_line_thickness_pixels = 3.0
    settings.gizmo_x_axis_color = "#AABBCC"
    settings.gizmo_label_color = "#DDEEFF"
    quality, _ = render_tuning_payloads(settings, {})
    for key in ("gizmo_size_scale", "gizmo_handle_size_pixels", "gizmo_label_size_pixels",
                "gizmo_line_thickness_pixels", "gizmo_x_axis_color", "gizmo_y_axis_color",
                "gizmo_z_axis_color", "gizmo_label_color", "gizmo_highlight_color"):
        assert quality[key] == getattr(settings, key)


def test_effect_sprite_resources_are_hash_deduplicated_and_path_bounded(
    tmp_path: Path,
) -> None:
    texture = b"DDS " + bytes(range(124))
    digest = hashlib.sha256(texture).hexdigest()
    resources = {
        "effect/texture/fire_a.dds": texture,
        "effect/texture/fire_alias.dds": texture,
    }
    package = build_rust_preview_package(
        _triangle(),
        output_package_dir=tmp_path / "effect-package",
        include_material_resources=False,
        effects_overlay={"schema": 1, "emitters": []},
        effect_texture_resources=resources,
    )

    manifest = json.loads(package.manifest_path.read_text(encoding="utf-8"))
    references = manifest["effect_textures"]
    assert len(references) == 2
    assert {entry["archive_path"] for entry in references} == set(resources)
    assert {entry["file"]["path"] for entry in references} == {
        f"effect_textures/{digest}.dds"
    }
    assert manifest["state"]["preview_scene"]["effects_overlay"]["texture_files"] == {
        archive_path: f"effect_textures/{digest}.dds" for archive_path in resources
    }
    assert len(list((package.package_dir / "effect_textures").glob("*.dds"))) == 1
    assert validate_rust_preview_package(package.package_dir) == ()

    with pytest.raises(ValueError, match="archive path is invalid"):
        build_rust_preview_package(
            _triangle(),
            output_package_dir=tmp_path / "escaped-effect-package",
            include_material_resources=False,
            effects_overlay={"schema": 1, "emitters": []},
            effect_texture_resources={"../outside.dds": texture},
        )


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
    assert RUST_PREVIEW_CACHE_SCHEMA == 5
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
    assert direct["material_graph_version"] == 4
    assert direct["material_semantics_version"] == 10
    assert manifest["material_contract"]["graph_version"] == 4
    assert manifest["material_contract"]["semantics_version"] == 10
    assert manifest["material_contract"]["conservation"]["conserved"] is True
    graph = manifest["preview_core_material_graph"]
    assert graph["schema_version"] == 1
    assert graph["quality"] == "full"
    assert graph["resources_included"] is True
    assert graph["source_edge_count"] == 1
    assert graph["unique_resource_count"] == 1
    assert graph["copied_resource_count"] == 0
    assert graph["materials"][0]["layers"][0]["owner_wrapper_item_id"] == (
        "fixture-wrapper-1"
    )
    assert graph["materials"][0]["layers"][0]["diffuse"] == manifest["textures"][
        0
    ]["file"]
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


def test_native_source_identity_finds_the_published_full_package_before_decoding(tmp_path: Path) -> None:
    from cdmw.services.mesh_rust_preview_cache import lookup_rust_preview_package_from_preview_core_identity

    source, *_ = _write_schema8_preview_core_fixture(tmp_path)
    package = build_or_lookup_rust_preview_package(
        source,
        cache_root=tmp_path / "cache",
        archive_identity="revision-with-archive-and-render-inputs",
        cache_mode="balanced",
        max_bytes=64 * 1024 * 1024,
        target_bytes=48 * 1024 * 1024,
    )
    lookup = dict(cache_root=tmp_path / "cache", archive_identity="revision-with-archive-and-render-inputs")
    assert lookup_rust_preview_package_from_preview_core_identity(**lookup).package_dir == package.package_dir
    assert lookup_rust_preview_package_from_preview_core_identity(
        **{**lookup, "archive_identity": "another-revision"}
    ) is None
    package.manifest_path.unlink()
    assert lookup_rust_preview_package_from_preview_core_identity(**lookup) is None


@pytest.mark.parametrize("after_first_copy", ("unchanged", "changed", "cancelled"))
def test_repeated_material_sources_are_copied_once_without_reusing_changed_inputs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, after_first_copy: str,
) -> None:
    import threading
    from cdmw.domain.cancellation import RunCancelled
    from cdmw.services import mesh_rust_preview_package as owner

    source, *_ = _write_schema8_preview_core_fixture(tmp_path)
    manifest_path = source / "manifest.json"
    native = json.loads(manifest_path.read_text(encoding="utf-8"))
    batch = native["batches"][0]
    batch["material_layers"] = [dict(batch["material_layers"][0]) for _ in range(32)]
    manifest_path.write_text(json.dumps(native), encoding="utf-8")
    stop = threading.Event()
    copy_calls = []
    original = owner._copy_preview_core_material_resource

    def record_copy(*args, **kwargs):
        result = original(*args, **kwargs)
        copy_calls.append(args[1])
        if len(copy_calls) == 1:
            if after_first_copy == "changed":
                args[1].write_bytes(b"DDS " + b"changed" * 200)
            elif after_first_copy == "cancelled":
                stop.set()
        return result

    monkeypatch.setattr(owner, "_copy_preview_core_material_resource", record_copy)
    target = tmp_path / "published"
    if after_first_copy != "unchanged":
        error = RunCancelled if after_first_copy == "cancelled" else ValueError
        with pytest.raises(error, match="[Cc]ancel|changed"):
            build_rust_preview_package_from_preview_core(
                source, output_package_dir=target, cancelled=stop.is_set,
            )
        assert not target.exists()
        return

    package = build_rust_preview_package_from_preview_core(source, output_package_dir=target)
    assert len(copy_calls) == 1, "the same source was read, copied and flushed for every layer"
    assert validate_rust_preview_package(package.package_dir) == ()
    payload = json.loads(package.manifest_path.read_text(encoding="utf-8"))
    graph = payload["preview_core_material_graph"]
    assert graph["source_edge_count"] == 32
    assert graph["unique_resource_count"] == 1
    assert all(layer["diffuse"] == payload["textures"][0]["file"] for layer in graph["materials"][0]["layers"])


def test_schema8_preview_core_publishes_direct_then_full_material_tiers(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source, _geometry_bytes, _identity_bytes, _texture_bytes = (
        _write_schema8_preview_core_fixture(tmp_path)
    )
    from cdmw.services import mesh_rust_authoring

    original_texture_payloads = mesh_rust_authoring._mesh_texture_payloads
    synthesis_flags: list[bool] = []

    def recording_texture_payloads(*args: object, **kwargs: object):
        synthesis_flags.append(bool(kwargs.get("enable_material_synthesis", True)))
        return original_texture_payloads(*args, **kwargs)

    monkeypatch.setattr(
        mesh_rust_authoring,
        "_mesh_texture_payloads",
        recording_texture_payloads,
    )
    direct_packages = []
    full = build_or_lookup_rust_preview_package(
        source,
        cache_root=tmp_path / "cache",
        archive_identity="helmet-progressive",
        cache_mode="balanced",
        max_bytes=64 * 1024 * 1024,
        target_bytes=48 * 1024 * 1024,
        fast_package_ready=direct_packages.append,
    )

    assert synthesis_flags == [False, False]
    assert len(direct_packages) == 1
    direct = direct_packages[0]
    assert direct.package_dir != full.package_dir
    direct_manifest = json.loads(direct.manifest_path.read_text(encoding="utf-8"))
    full_manifest = json.loads(full.manifest_path.read_text(encoding="utf-8"))
    assert direct_manifest["texture_status"]["quality"] == "direct"
    assert full_manifest["texture_status"]["quality"] == "full"
    assert direct_manifest["preview_core_material_graph"]["resources_included"] is False
    assert direct_manifest["preview_core_material_graph"]["materials"][0]["layers"][0][
        "diffuse"
    ] is None
    assert full_manifest["preview_core_material_graph"]["resources_included"] is True
    assert direct_manifest["source"] == full_manifest["source"]

    warm_callbacks = []
    warm = build_or_lookup_rust_preview_package(
        source,
        cache_root=tmp_path / "cache",
        archive_identity="helmet-progressive",
        cache_mode="balanced",
        max_bytes=64 * 1024 * 1024,
        target_bytes=48 * 1024 * 1024,
        fast_package_ready=warm_callbacks.append,
    )
    assert warm.package_dir == full.package_dir
    assert warm_callbacks == []


@pytest.mark.parametrize("quality", ("direct", "full"))
@pytest.mark.parametrize("has_detail", (False, True))
def test_preview_core_preserves_untextured_base_without_a_wrapper(
    tmp_path: Path, quality: str, has_detail: bool,
) -> None:
    source, *_ = _write_schema8_preview_core_fixture(tmp_path)
    source_manifest = source / "manifest.json"
    native = json.loads(source_manifest.read_text(encoding="utf-8"))
    batch = native["batches"][0]
    detail = dict(batch["material_layers"][0], layer_role="detail")
    # make_base_material_layer emits this sentinel when all global maps are absent,
    # including models whose visible textures belong only to detail layers.
    batch["material_layers"] = [{
        "owner_wrapper_item_id": "",
        "material_wrapper_index": -1,
        "layer_role": "base",
        "mask_channel": "r",
        "source_parameter": "",
        "mask_parameter": "",
        "weight": 1.0,
        "tint": [0.2, 0.3, 0.4, 1.0],
    }]
    batch["dds_textures"] = {}
    if has_detail:
        batch["material_layers"].append(detail)
    source_manifest.write_text(json.dumps(native), encoding="utf-8")

    package = build_rust_preview_package_from_preview_core(
        source, output_package_dir=tmp_path / "package", material_quality=quality,
    )

    assert validate_rust_preview_package(package.package_dir) == ()
    manifest = json.loads(package.manifest_path.read_text(encoding="utf-8"))
    layers = manifest["preview_core_material_graph"]["materials"][0]["layers"]
    assert layers[0]["owner_wrapper_item_id"] == ""
    assert layers[0]["material_wrapper_index"] == 0
    assert layers[0]["tint"] == [0.2, 0.3, 0.4, 1.0]
    assert layers[0]["diffuse"] is None
    assert len(layers) == (2 if has_detail else 1)
    if has_detail:
        assert layers[1]["owner_wrapper_item_id"] == "fixture-wrapper-1"
        assert layers[1]["material_wrapper_index"] == 0
        assert (layers[1]["diffuse"] is not None) == (quality == "full")


@pytest.mark.parametrize("quality", ("direct", "full"))
@pytest.mark.parametrize("damage", ("missing_owner", "negative_wrapper", "missing_wrapper"))
def test_preview_core_rejects_textured_layer_without_valid_ownership(
    tmp_path: Path, quality: str, damage: str,
) -> None:
    source, *_ = _write_schema8_preview_core_fixture(tmp_path)
    source_manifest = source / "manifest.json"
    native = json.loads(source_manifest.read_text(encoding="utf-8"))
    layer = native["batches"][0]["material_layers"][0]
    if damage == "missing_owner":
        layer["owner_wrapper_item_id"] = ""
    elif damage == "negative_wrapper":
        layer["material_wrapper_index"] = -1
    else:
        del layer["material_wrapper_index"]
    source_manifest.write_text(json.dumps(native), encoding="utf-8")

    with pytest.raises(ValueError, match="identity"):
        build_rust_preview_package_from_preview_core(
            source, output_package_dir=tmp_path / "package", material_quality=quality,
        )
    assert not (tmp_path / "package").exists()


def test_preview_core_material_conservation_failure_is_not_sent_to_rust(
    tmp_path: Path,
) -> None:
    source, _geometry, _identity, _texture = _write_schema8_preview_core_fixture(
        tmp_path
    )
    source_manifest_path = source / "manifest.json"
    source_manifest = json.loads(source_manifest_path.read_text(encoding="utf-8"))
    source_manifest["material_conservation"]["conserved"] = False
    source_manifest["material_conservation"]["findings"] = [
        "cross_owner_binding:fixture"
    ]
    source_manifest_path.write_text(json.dumps(source_manifest), encoding="utf-8")

    with pytest.raises(ValueError, match="conserved Preview Core material graph"):
        build_rust_preview_package_from_preview_core(
            source,
            output_package_dir=tmp_path / "rejected",
        )


def test_python_model_preview_uses_the_same_direct_then_full_cache_contract(
    tmp_path: Path,
) -> None:
    model = ModelPreviewData(
        path="imported/model.fbx",
        format="fbx",
        meshes=[
            ModelPreviewMesh(
                material_name="imported",
                positions=[(-0.5, -0.5, 0.0), (0.5, -0.5, 0.0), (0.0, 0.5, 0.0)],
                normals=[(0.0, 0.0, 1.0)] * 3,
                texture_coordinates=[(0.0, 1.0), (1.0, 1.0), (0.5, 0.0)],
                indices=[0, 1, 2],
            )
        ],
    )
    direct_packages = []

    full = build_or_lookup_rust_preview_package_from_model(
        model,
        cache_root=tmp_path / "cache",
        archive_identity="new-item-imported",
        cache_mode="balanced",
        max_bytes=64 * 1024 * 1024,
        target_bytes=48 * 1024 * 1024,
        fast_package_ready=direct_packages.append,
    )

    assert len(direct_packages) == 1
    direct_manifest = json.loads(
        direct_packages[0].manifest_path.read_text(encoding="utf-8")
    )
    full_manifest = json.loads(full.manifest_path.read_text(encoding="utf-8"))
    assert direct_manifest["texture_status"]["quality"] == "direct"
    assert full_manifest["texture_status"]["quality"] == "full"
    assert direct_packages[0].package_dir != full.package_dir


def test_compiled_preview_contract_declares_the_complete_runtime_surface() -> None:
    source = (
        ROOT / "tools/rust_mesh_lab/apps/cdmw_mesh_lab/src/cdmw_preview.rs"
    ).read_text(encoding="utf-8")
    assert '"viewport_only": true' in source
    assert '"read_only_mutations_rejected": true' in source
    for capability in RUST_PREVIEW_REQUIRED_CAPABILITIES:
        assert f'"{capability}"' in source
    for capability in (
        "semantic_framing_v1",
        "gpu_scene_transforms_v1",
        "full_gizmo_handles_v1",
        "camera_navigator_v1",
        "lighting_presets_v1",
        "textured_effect_particles_v1",
    ):
        assert f'"{capability}"' in source
    for command in (
        "package_load_request",
        "canonical_view_request",
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
