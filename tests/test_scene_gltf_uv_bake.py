from __future__ import annotations

import json
import math
import struct
import threading
from pathlib import Path
from unittest.mock import patch

import pytest
import numpy as np
from PIL import Image

from cdmw.domain.cancellation import RunCancelled
from cdmw.modding import mesh_native_core
from cdmw.modding.mesh_native_uv import release_native_temporary_mesh_sessions
from cdmw.modding.mesh_parser import ParsedMesh, SubMesh
from cdmw.modding.scene_gltf_uv import (
    GLTF_IDENTITY_UV_TRANSFORM,
    GltfMaterialUvPlan,
    GltfPrimitiveUvInputs,
    GltfPrimitiveUvSet,
    GltfTextureSlotUvProvenance,
)
from cdmw.modding.scene_gltf_uv_bake import (
    GltfUvPrimitiveRecord,
    _build_combined_material,
    _prepare_source_tangent_frames,
    _split_material_mesh,
    bake_general_gltf_uvs,
)
from cdmw.modding.scene_material_audit import _scene_material_slot
from cdmw.modding.scene_importer import import_scene_mesh_with_report


def _slot(
    slot_key: str,
    slot_kind: str,
    texture_index: int,
    texcoord: int,
    transform: tuple[float, float, float, float, float],
) -> GltfTextureSlotUvProvenance:
    return GltfTextureSlotUvProvenance(
        slot_key=slot_key,
        slot_kind=slot_kind,
        texture_index=texture_index,
        image_index=texture_index,
        sampler_index=-1,
        texcoord=texcoord,
        transform=transform,
        wrap_s=33071,
        wrap_t=33071,
        min_filter=9729,
        mag_filter=9729,
    )


def _triangle(name: str, x: float) -> SubMesh:
    return SubMesh(
        name=name,
        material="Shared",
        vertices=[(x, 0.0, 0.0), (x + 1.0, 0.0, 0.0), (x, 1.0, 0.0)],
        normals=[(0.0, 0.0, 1.0)] * 3,
        uvs=[(0.0, 1.0), (1.0, 1.0), (0.0, 0.0)],
        faces=[(0, 1, 2)],
        vertex_count=3,
        face_count=1,
    )


def _write_general_gltf(
    root: Path,
    *,
    multi_uv: bool,
    include_tangent: bool = True,
    shared_transform: bool = False,
) -> Path:
    chunks: list[bytes] = []
    views: list[dict[str, int]] = []
    accessors: list[dict[str, int | str]] = []

    def add(rows: list[tuple[float, ...]], kind: str) -> int:
        raw = struct.pack(f"<{sum(len(row) for row in rows)}f", *(value for row in rows for value in row))
        offset = sum(len(chunk) for chunk in chunks)
        chunks.append(raw + b"\0" * ((-len(raw)) % 4))
        views.append({"buffer": 0, "byteOffset": offset, "byteLength": len(raw)})
        accessors.append({"bufferView": len(views) - 1, "componentType": 5126, "count": len(rows), "type": kind})
        return len(accessors) - 1

    attributes = {
        "POSITION": add([(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)], "VEC3"),
        "NORMAL": add([(0.0, 0.0, 1.0)] * 3, "VEC3"),
        "TEXCOORD_0": add([(0.0, 0.0), (1.0, 0.0), (0.0, 1.0)], "VEC2"),
        "TEXCOORD_1": add([(0.25, 0.25), (0.75, 0.25), (0.25, 0.75)], "VEC2"),
    }
    if include_tangent:
        attributes["TANGENT"] = add([(1.0, 0.0, 0.0, -1.0)] * 3, "VEC4")
    index_raw = struct.pack("<3H", 0, 1, 2)
    index_offset = sum(len(chunk) for chunk in chunks)
    chunks.append(index_raw + b"\0" * ((-len(index_raw)) % 4))
    views.append({"buffer": 0, "byteOffset": index_offset, "byteLength": len(index_raw)})
    accessors.append({"bufferView": len(views) - 1, "componentType": 5123, "count": 3, "type": "SCALAR"})
    texture_transform = {"rotation": math.pi / 2.0}
    if shared_transform:
        texture_transform["scale"] = [0.5, 1.5]
    transformed = {
        "index": 1,
        "texCoord": 1 if multi_uv else 0,
        "scale": 0.5,
        "extensions": {"KHR_texture_transform": texture_transform},
    }
    base_texture = {"index": 0, "texCoord": 0}
    if shared_transform:
        base_texture["extensions"] = {"KHR_texture_transform": texture_transform}
    document = {
        "asset": {"version": "2.0"},
        "buffers": [{"uri": "mesh.bin", "byteLength": sum(len(chunk) for chunk in chunks)}],
        "bufferViews": views,
        "accessors": accessors,
        "meshes": [{"primitives": [{"attributes": attributes, "indices": len(accessors) - 1, "material": 0}]}],
        "materials": [
            {
                "name": "General",
                "pbrMetallicRoughness": {"baseColorTexture": base_texture},
                "normalTexture": transformed,
            }
        ],
        "textures": [{"source": 0}, {"source": 1}],
        "images": [{"uri": "base.png"}, {"uri": "normal.png"}],
        "nodes": [{"mesh": 0}],
        "scenes": [{"nodes": [0]}],
        "scene": 0,
    }
    (root / "mesh.bin").write_bytes(b"".join(chunks))
    Image.new("RGBA", (16, 16), (180, 90, 30, 255)).save(root / "base.png")
    source_normal = (0.6, 0.3, math.sqrt(1.0 - 0.6**2 - 0.3**2))
    encoded_normal = tuple(round((value * 0.5 + 0.5) * 255.0) for value in source_normal)
    Image.new("RGBA", (16, 16), (*encoded_normal, 255)).save(root / "normal.png")
    path = root / "general.gltf"
    path.write_text(json.dumps(document), encoding="utf-8")
    return path


@pytest.mark.parametrize("multi_uv", [False, True])
def test_general_gltf_import_bakes_different_slots_to_runtime_texcoord0(
    tmp_path: Path,
    multi_uv: bool,
) -> None:
    path = _write_general_gltf(tmp_path, multi_uv=multi_uv)
    tangent_uv_calls: list[tuple[tuple[float, float], ...]] = []

    def fake_xatlas(temporary_mesh, _indices, **kwargs):
        assert kwargs["padding"] == 8
        submesh = temporary_mesh.submeshes[0]
        submesh.uvs = [(0.0, 1.0), (1.0, 1.0), (0.0, 0.0)]
        submesh.source_vertex_map = [0, 1, 2]
        setattr(submesh, "auto_uv_report", {"unwrap_backend": "xatlas", "chart_count": 1, "topology_changed": False})
        return {0: range(3)}

    def fake_tangents(temporary_mesh, _indices, **_kwargs):
        submesh = temporary_mesh.submeshes[0]
        tangent_uv_calls.append(tuple(submesh.uvs))
        submesh.tangents = [(1.0, 0.0, 0.0)] * 3
        setattr(submesh, "tangent_signs", [-1.0] * 3)
        return {0}

    with (
        patch("cdmw.modding.scene_gltf_uv_bake.apply_native_mesh_auto_uv", side_effect=fake_xatlas),
        patch("cdmw.modding.scene_gltf_uv_bake.apply_native_mesh_generate_tangents", side_effect=fake_tangents),
    ):
        result = import_scene_mesh_with_report(path, include_external_audit=False)

    submesh = result.mesh.submeshes[0]
    inputs = {item.slot_kind: item for item in submesh.preview_material_texture_inputs}
    assert all("texcoord:" not in " ".join(item.blend_flags) for item in inputs.values())
    assert all("texture_transform" not in item.blend_flags for item in inputs.values())
    report = result.uv_bake_report
    material_report = report["materials"][0]
    assert material_report["mode"] == "xatlas_raster_bake"
    assert set(material_report["generated_texture_hashes"]) == {"base", "normal"}
    assert material_report["review_required"] is False
    generated = {row["slot_key"]: Path(row["output_path"]) for row in material_report["generated_slots"]}
    assert all(path.is_file() for path in generated.values())
    base = np.asarray(Image.open(generated["base"]).convert("RGBA"))
    assert np.max(np.abs(base.astype(int) - np.array((180, 90, 30, 255)))) <= 1
    source_encoded = np.asarray(Image.open(tmp_path / "normal.png").convert("RGBA"))[8, 8, :3].astype(float) / 255.0
    source_decoded = source_encoded * 2.0 - 1.0
    source_scaled = np.array((source_decoded[0] * 0.5, source_decoded[1] * 0.5, source_decoded[2]))
    source_scaled /= np.linalg.norm(source_scaled)
    expected = source_scaled
    normal = np.asarray(Image.open(generated["normal"]).convert("RGBA"))[8, 8, :3].astype(float) / 255.0
    decoded = normal * 2.0 - 1.0
    decoded /= np.linalg.norm(decoded)
    assert math.degrees(math.acos(float(np.clip(np.dot(decoded, expected), -1.0, 1.0)))) <= 1.0
    assert submesh.preview_normal_texture_strength == pytest.approx(1.0)
    assert len(tangent_uv_calls) == 1


def test_shared_transform_without_authored_tangents_keeps_raw_source_mikk_frame(
    tmp_path: Path,
) -> None:
    path = _write_general_gltf(
        tmp_path,
        multi_uv=False,
        include_tangent=False,
        shared_transform=True,
    )
    native_uv_calls: list[tuple[tuple[float, float], ...]] = []

    def fake_tangents(temporary_mesh, _indices, **_kwargs):
        output = temporary_mesh.submeshes[0]
        native_uv_calls.append(tuple(output.uvs))
        output.tangents = [(1.0, 0.0, 0.0)] * 3
        setattr(output, "tangent_signs", [1.0] * 3)
        return {0}

    with patch(
        "cdmw.modding.scene_gltf_uv_bake.apply_native_mesh_generate_tangents",
        side_effect=fake_tangents,
    ):
        result = import_scene_mesh_with_report(path, include_external_audit=False)

    submesh = result.mesh.submeshes[0]
    assert native_uv_calls == [((0.0, 0.0), (1.0, 0.0), (0.0, 1.0))]
    assert submesh.uvs != [(0.0, 1.0), (1.0, 1.0), (0.0, 0.0)]
    assert submesh.tangents == [(1.0, 0.0, 0.0)] * 3
    assert submesh.tangent_signs == [1.0] * 3

    source_encoded = np.asarray(Image.open(tmp_path / "normal.png").convert("RGBA"))[8, 8, :3].astype(float) / 255.0
    tangent_normal = source_encoded * 2.0 - 1.0
    tangent_normal[:2] *= 0.5
    tangent_normal /= np.linalg.norm(tangent_normal)
    normal = np.asarray(submesh.normals[0], dtype=np.float64)
    tangent = np.asarray(submesh.tangents[0], dtype=np.float64)
    bitangent = np.cross(normal, tangent) * submesh.tangent_signs[0]
    object_normal = tangent * tangent_normal[0] + bitangent * tangent_normal[1] + normal * tangent_normal[2]
    object_normal /= np.linalg.norm(object_normal)
    expected = tangent_normal
    assert math.degrees(math.acos(float(np.clip(np.dot(object_normal, expected), -1.0, 1.0)))) <= 1.0

    with (
        patch("cdmw.modding.scene_gltf_uv_bake.apply_native_mesh_generate_tangents", return_value=None),
        pytest.raises(ValueError, match="could not generate source TEXCOORD_0 MikkTSpace tangents"),
    ):
        import_scene_mesh_with_report(path, include_external_audit=False)


def test_general_bake_aggregates_one_xatlas_layout_and_splits_primitives(tmp_path: Path) -> None:
    source_path = tmp_path / "mesh.gltf"
    source_path.write_text("{}", encoding="utf-8")
    base_path = tmp_path / "base.png"
    mask_path = tmp_path / "mask.png"
    Image.new("RGBA", (16, 16), (220, 80, 20, 255)).save(base_path)
    Image.new("RGBA", (8, 8), (20, 80, 220, 255)).save(mask_path)
    mesh = ParsedMesh(
        path=str(source_path),
        format="gltf",
        submeshes=[_triangle("left", 0.0), _triangle("right", 2.0)],
        total_vertices=6,
        total_faces=2,
        has_uvs=True,
    )
    plan = GltfMaterialUvPlan(
        material_index=0,
        material_name="Shared",
        slots=(
            _slot("base", "base", 0, 0, GLTF_IDENTITY_UV_TRANSFORM),
            _slot("material", "material", 1, 1, (0.25, 0.0, 0.5, 1.0, 0.0)),
        ),
        source_texcoord=0,
        transform=GLTF_IDENTITY_UV_TRANSFORM,
    )
    uv0 = ((0.0, 0.0), (1.0, 0.0), (0.0, 1.0))
    uv1 = ((0.0, 0.0), (1.0, 0.0), (0.0, 1.0))
    records = [
        GltfUvPrimitiveRecord(
            material_index=0,
            submesh_index=index,
            primitive_label=f"primitive:{index}",
            uv_inputs=GltfPrimitiveUvInputs(
                primitive_label=f"primitive:{index}",
                sets=(GltfPrimitiveUvSet(0, 0, uv0), GltfPrimitiveUvSet(1, 1, uv1)),
            ),
        )
        for index in range(2)
    ]
    material_slots = {
        0: {
            "base": _scene_material_slot("base", base_path.as_posix()),
            "material": _scene_material_slot("material", mask_path.as_posix()),
        }
    }
    native_calls: list[int] = []

    def fake_xatlas(temporary_mesh, indices, **kwargs):
        assert indices == {0}
        assert kwargs["allow_topology_change"] is True
        assert kwargs["padding"] == 16
        assert len(temporary_mesh.submeshes) == 1
        submesh = temporary_mesh.submeshes[0]
        native_calls.append(len(submesh.faces))
        submesh.uvs = [(0.0, 1.0), (0.5, 1.0), (0.0, 0.0), (0.5, 1.0), (1.0, 1.0), (0.5, 0.0)]
        submesh.source_vertex_map = list(range(6))
        setattr(submesh, "auto_uv_report", {"unwrap_backend": "xatlas", "chart_count": 2, "topology_changed": False})
        return {0: range(6)}

    def fake_tangents(temporary_mesh, indices, **kwargs):
        assert indices == {0}
        submesh = temporary_mesh.submeshes[0]
        submesh.tangents = [(1.0, 0.0, 0.0)] * len(submesh.vertices)
        setattr(submesh, "tangent_signs", [-1.0] * len(submesh.vertices))
        return {0}

    with (
        patch("cdmw.modding.scene_gltf_uv_bake.apply_native_mesh_auto_uv", side_effect=fake_xatlas),
        patch("cdmw.modding.scene_gltf_uv_bake.apply_native_mesh_generate_tangents", side_effect=fake_tangents),
    ):
        outcome = bake_general_gltf_uvs(
            mesh,
            {0: plan},
            records,
            material_slots,
            source_path,
        )

    assert native_calls == [2]
    assert len(outcome.generated_paths) == 2
    assert all(path.is_file() for path in outcome.generated_paths)
    assert all(len(submesh.uvs) == len(submesh.vertices) == 3 for submesh in mesh.submeshes)
    assert max(uv[0] for uv in mesh.submeshes[0].uvs) <= 0.5
    assert min(uv[0] for uv in mesh.submeshes[1].uvs) >= 0.5
    assert material_slots[0]["base"].texcoord == 0
    assert material_slots[0]["base"].transform == ()
    assert material_slots[0]["base"].source == "gltf_uv_bake"
    report = outcome.material_reports[0]
    assert report["layout"]["chart_count"] == 2
    assert report["layout"]["requested_padding"] == 8
    assert report["layout"]["effective_padding"] == 16
    assert report["layout"]["effective_padding"] / report["layout"]["resolution"] * 8 >= 8
    assert set(report["generated_texture_hashes"]) == {"base", "material"}


def test_partial_authored_tangent_accessor_uses_one_generated_mikk_frame() -> None:
    submesh = _triangle("partial", 0.0)
    submesh.tangents = [(1.0, 0.0, 0.0), (math.nan, 0.0, 0.0), (1.0, 0.0, 0.0)]
    setattr(submesh, "tangent_signs", [-1.0, -1.0, -1.0])
    mesh = ParsedMesh(submeshes=[submesh])
    rows = ((0.0, 0.0), (1.0, 0.0), (0.0, 1.0))
    record = GltfUvPrimitiveRecord(
        0,
        0,
        "partial",
        GltfPrimitiveUvInputs("partial", (GltfPrimitiveUvSet(0, 0, rows),)),
    )
    plan = GltfMaterialUvPlan(
        0,
        "Shared",
        (_slot("normal", "normal", 0, 0, GLTF_IDENTITY_UV_TRANSFORM),),
        0,
        GLTF_IDENTITY_UV_TRANSFORM,
    )
    combined = _build_combined_material(mesh, plan, [record])
    calls = 0

    def fake_tangents(temporary_mesh, _indices, **_kwargs):
        nonlocal calls
        calls += 1
        output = temporary_mesh.submeshes[0]
        output.tangents = [(0.0, 1.0, 0.0)] * 3
        setattr(output, "tangent_signs", [1.0] * 3)
        return {0}

    with patch("cdmw.modding.scene_gltf_uv_bake.apply_native_mesh_generate_tangents", side_effect=fake_tangents):
        _prepare_source_tangent_frames(combined, [0], stop_event=None)

    assert calls == 1
    assert combined.source_tangent_frames[0] == ([(0.0, 1.0, 0.0)] * 3, [1.0] * 3)


def test_downscaled_general_bake_requires_review(tmp_path: Path) -> None:
    source_path = tmp_path / "mesh.gltf"
    source_path.write_text("{}", encoding="utf-8")
    base_path = tmp_path / "wide.png"
    mask_path = tmp_path / "mask.png"
    Image.new("RGBA", (4097, 1), (200, 100, 50, 255)).save(base_path)
    Image.new("RGBA", (4, 4), (10, 20, 30, 255)).save(mask_path)
    mesh = ParsedMesh(submeshes=[_triangle("one", 0.0)], total_vertices=3, total_faces=1, has_uvs=True)
    plan = GltfMaterialUvPlan(
        0,
        "Shared",
        (
            _slot("base", "base", 0, 0, GLTF_IDENTITY_UV_TRANSFORM),
            _slot("material", "material", 1, 1, GLTF_IDENTITY_UV_TRANSFORM),
        ),
        0,
        GLTF_IDENTITY_UV_TRANSFORM,
    )
    rows = ((0.0, 0.0), (1.0, 0.0), (0.0, 1.0))
    records = [
        GltfUvPrimitiveRecord(
            0,
            0,
            "one",
            GltfPrimitiveUvInputs(
                "one",
                (GltfPrimitiveUvSet(0, 0, rows), GltfPrimitiveUvSet(1, 1, rows)),
            ),
        )
    ]
    slots = {
        0: {
            "base": _scene_material_slot("base", base_path.as_posix()),
            "material": _scene_material_slot("material", mask_path.as_posix()),
        }
    }

    def fake_xatlas(temporary_mesh, _indices, **kwargs):
        assert kwargs["padding"] == 32768
        submesh = temporary_mesh.submeshes[0]
        submesh.uvs = [(0.0, 1.0), (1.0, 1.0), (0.0, 0.0)]
        submesh.source_vertex_map = [0, 1, 2]
        setattr(submesh, "auto_uv_report", {"unwrap_backend": "xatlas", "chart_count": 1})
        return {0: range(3)}

    def fake_tangents(temporary_mesh, _indices, **_kwargs):
        submesh = temporary_mesh.submeshes[0]
        submesh.tangents = [(1.0, 0.0, 0.0)] * 3
        setattr(submesh, "tangent_signs", [-1.0] * 3)
        return {0}

    with (
        patch("cdmw.modding.scene_gltf_uv_bake.apply_native_mesh_auto_uv", side_effect=fake_xatlas),
        patch("cdmw.modding.scene_gltf_uv_bake.apply_native_mesh_generate_tangents", side_effect=fake_tangents),
    ):
        outcome = bake_general_gltf_uvs(mesh, {0: plan}, records, slots, source_path)

    report = outcome.material_reports[0]
    base = next(row for row in report["generated_slots"] if row["slot_key"] == "base")
    assert base["source_dimensions"] == [4097, 1]
    assert base["output_dimensions"] == [4096, 1]
    assert base["downscaled"] is True
    assert report["warnings"]
    assert report["review_required"] is True


def test_general_bake_fails_closed_and_preserves_cancellation(tmp_path: Path) -> None:
    source_path = tmp_path / "mesh.gltf"
    source_path.write_text("{}", encoding="utf-8")
    base_path = tmp_path / "base.png"
    Image.new("RGBA", (4, 4), (255, 255, 255, 255)).save(base_path)
    mesh = ParsedMesh(path=str(source_path), format="gltf", submeshes=[_triangle("one", 0.0)])
    plan = GltfMaterialUvPlan(
        0,
        "Shared",
        (
            _slot("base", "base", 0, 0, GLTF_IDENTITY_UV_TRANSFORM),
            _slot("material", "material", 0, 1, GLTF_IDENTITY_UV_TRANSFORM),
        ),
        0,
        GLTF_IDENTITY_UV_TRANSFORM,
    )
    inputs = GltfPrimitiveUvInputs(
        "one",
        (
            GltfPrimitiveUvSet(0, 0, ((0.0, 0.0), (1.0, 0.0), (0.0, 1.0))),
            GltfPrimitiveUvSet(1, 1, ((0.0, 0.0), (1.0, 0.0), (0.0, 1.0))),
        ),
    )
    records = [GltfUvPrimitiveRecord(0, 0, "one", inputs)]
    slots = {
        0: {
            "base": _scene_material_slot("base", base_path.as_posix()),
            "material": _scene_material_slot("material", base_path.as_posix()),
        }
    }

    with (
        patch("cdmw.modding.scene_gltf_uv_bake.apply_native_mesh_auto_uv", return_value=None),
        pytest.raises(ValueError, match="could not create the bundled xatlas layout"),
    ):
        bake_general_gltf_uvs(mesh, {0: plan}, records, slots, source_path)

    stop_event = threading.Event()
    stop_event.set()
    with pytest.raises(RunCancelled, match="cancelled before material conversion"):
        bake_general_gltf_uvs(mesh, {0: plan}, records, slots, source_path, stop_event=stop_event)


def test_xatlas_seam_remap_and_duplicate_face_accounting_are_exact() -> None:
    quad = SubMesh(
        name="quad",
        material="Shared",
        vertices=[(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (1.0, 1.0, 0.0), (0.0, 1.0, 0.0)],
        normals=[(0.0, 0.0, 1.0)] * 4,
        uvs=[(0.0, 1.0), (1.0, 1.0), (1.0, 0.0), (0.0, 0.0)],
        faces=[(0, 1, 2), (0, 2, 3)],
        vertex_count=4,
        face_count=2,
    )
    mesh = ParsedMesh(submeshes=[quad], total_vertices=4, total_faces=2, has_uvs=True)
    plan = GltfMaterialUvPlan(
        0,
        "Shared",
        (
            _slot("base", "base", 0, 0, GLTF_IDENTITY_UV_TRANSFORM),
            _slot("material", "material", 1, 1, GLTF_IDENTITY_UV_TRANSFORM),
        ),
        0,
        GLTF_IDENTITY_UV_TRANSFORM,
    )
    rows = ((0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0))
    record = GltfUvPrimitiveRecord(
        0,
        0,
        "quad",
        GltfPrimitiveUvInputs("quad", (GltfPrimitiveUvSet(0, 0, rows), GltfPrimitiveUvSet(1, 1, rows))),
    )

    combined = _build_combined_material(mesh, plan, [record])
    output = combined.mesh.submeshes[0]
    remap = [0, 1, 2, 0, 2, 3]
    output.vertices = [output.vertices[index] for index in remap]
    output.normals = [output.normals[index] for index in remap]
    output.uvs = [(0.0, 1.0), (0.5, 1.0), (0.5, 0.5), (0.5, 0.5), (1.0, 0.5), (0.5, 0.0)]
    output.tangents = [(1.0, 0.0, 0.0)] * 6
    output.source_vertex_map = remap
    output.faces = [(0, 1, 2), (3, 4, 5)]
    setattr(output, "tangent_signs", [-1.0] * 6)

    _split_material_mesh(mesh, combined)
    assert mesh.submeshes[0].source_vertex_map == remap
    assert mesh.submeshes[0].source_vertex_map_authority == "topology"
    assert len(mesh.submeshes[0].vertices) == 6

    invalid = _build_combined_material(ParsedMesh(submeshes=[quad]), plan, [record])
    invalid_output = invalid.mesh.submeshes[0]
    invalid_output.uvs = [(0.0, 0.0)] * 4
    invalid_output.tangents = [(1.0, 0.0, 0.0)] * 4
    invalid_output.source_vertex_map = [0, 1, 2, 3]
    invalid_output.faces = [(0, 1, 2), (0, 1, 2)]
    setattr(invalid_output, "tangent_signs", [1.0] * 4)
    with pytest.raises(ValueError, match="no longer maps to an input triangle"):
        _split_material_mesh(ParsedMesh(submeshes=[quad]), invalid)


def test_real_native_xatlas_mikk_temp_sessions_do_not_grow(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("CDMW_DISABLE_NATIVE_MESH_CORE", raising=False)
    monkeypatch.delenv("CDMW_DISABLE_NATIVE_MESH_CORE_SERVICE", raising=False)
    binary = mesh_native_core.find_native_mesh_core_binary()
    if binary is None:
        pytest.skip("native mesh core is not built")

    def session_count() -> int:
        report = mesh_native_core._run_native_mesh_core_service_job(
            binary,
            "mesh-session-json",
            {
                "version": 1,
                "backend": "cdmw_mesh_core_0.1",
                "operation": "clear",
                "session_id": "uv-bake-session-count-probe",
            },
            timeout_seconds=5.0,
        )
        assert report is not None
        return int(report["native_session_count"])

    baseline = session_count()
    mesh = ParsedMesh(
        path="native.gltf",
        format="gltf",
        submeshes=[_triangle("native", 0.0)],
        total_vertices=3,
        total_faces=1,
        has_uvs=True,
    )
    try:
        changed = mesh_native_core.apply_native_mesh_auto_uv(
            mesh,
            {0},
            resolution=64,
            padding=8,
            allow_topology_change=True,
        )
        assert changed is not None
        assert mesh.submeshes[0].auto_uv_report["unwrap_backend"] == "xatlas"
        assert mesh_native_core.apply_native_mesh_generate_tangents(mesh, {0}) is not None
        tangent_report = mesh.submeshes[0].tangent_face_corner_report
        assert str(tangent_report["backend"]).startswith("mikktspace")
        assert len(mesh.submeshes[0].tangent_signs) == len(mesh.submeshes[0].vertices)
    finally:
        release_native_temporary_mesh_sessions(mesh, {0})
    assert session_count() == baseline

    path = _write_general_gltf(tmp_path, multi_uv=True)
    for _index in range(3):
        result = import_scene_mesh_with_report(path, include_external_audit=False)
        material_report = result.uv_bake_report["materials"][0]
        assert material_report["layout"]["backend"] == "xatlas"
        assert len(result.mesh.submeshes[0].tangent_signs) == len(result.mesh.submeshes[0].vertices)
        assert session_count() == baseline
