from __future__ import annotations

import json
import struct
from pathlib import Path

import pytest

from cdmw.domain.cancellation import RunCancelled
from cdmw.services.mesh_dotnet_reference_composite import (
    apply_dotnet_native_reference_materials,
    append_dotnet_native_reference_composite,
)
from tests.mesh_material_test_support import _mesh


def _prefab_reference_batch(normal: Path, material: Path) -> dict[str, object]:
    return {
        "index": 1,
        "material_name": "CD_PHW_00_UW_00_0001",
        "vertex_file": "geometry/batch_001.bin",
        "vertex_count": 3,
        "editor_identity": {
            "source_submesh_index": 1,
            "source_local_submesh_index": 0,
            "source_component_index": 1,
            "source_component_label": "underwear.pac",
            "prefab_component": True,
            "identity_file": "geometry/batch_001_identity.bin",
        },
        "base_color": [0.90, 0.83, 0.71],
        "base_tint_only_fallback": True,
        "roughness": 0.48,
        "metalness": 0.0,
        "specular": 0.28,
        "material_category": "cloth",
        "shader_family": "SkinnedMeshCloth_Ver2",
        "normal_y_policy": "shader_invert_legacy_compat",
        "alpha_mode": "opaque",
        "two_sided": False,
        "dds_textures": {
            "normal": {
                "slot": "normal",
                "source_path": str(normal),
                "semantic_type": "normal",
                "shader_family": "SkinnedMeshCloth_Ver2",
            },
            "material": {
                "slot": "material",
                "source_path": str(material),
                "semantic_type": "packed_material",
                "semantic_subtype": "material_mask",
                "packed_channels": "r=occlusion,g=roughness,b=metalness,a=specular_response",
                "shader_family": "SkinnedMeshCloth_Ver2",
            },
            "material_inputs": [
                {
                    "slot": "normal",
                    "source_path": str(normal),
                    "semantic_type": "normal",
                    "shader_family": "SkinnedMeshCloth_Ver2",
                },
                {
                    "slot": "material",
                    "source_path": str(material),
                    "semantic_type": "packed_material",
                    "semantic_subtype": "material_mask",
                    "packed_channels": "r=occlusion,g=roughness,b=metalness,a=specular_response",
                    "shader_family": "SkinnedMeshCloth_Ver2",
                },
            ],
        },
    }


def _write_native_reference_composite_fixture(tmp_path: Path) -> Path:
    package_dir = tmp_path / "native_reference"
    geometry_dir = package_dir / "geometry"
    geometry_dir.mkdir(parents=True)
    center = (10.0, 20.0, 30.0)
    scale = 2.0
    source_positions = ((11.0, 20.0, 30.0), (10.0, 21.0, 30.0), (10.0, 20.0, 31.0))
    records = []
    for corner, position in enumerate(source_positions):
        normalized = tuple((position[axis] - center[axis]) * scale for axis in range(3))
        barycentric = tuple(1.0 if axis == corner else 0.0 for axis in range(3))
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
                *barycentric,
            )
        )
    (geometry_dir / "batch_001.bin").write_bytes(b"".join(records))
    (geometry_dir / "batch_000.bin").write_bytes(b"".join(records))
    (geometry_dir / "batch_001_identity.bin").write_bytes(
        b"".join(struct.pack("<2i", 1, source_vertex) for source_vertex in (7, 8, 9))
    )
    (geometry_dir / "batch_000_identity.bin").write_bytes(
        b"".join(struct.pack("<2i", 0, source_vertex) for source_vertex in (0, 1, 2))
    )
    (geometry_dir / "batch_001_cloth_particles.bin").write_bytes(
        b"".join(struct.pack("<3f", *tuple((position[axis] - center[axis]) * scale for axis in range(3))) for position in source_positions)
    )
    (geometry_dir / "batch_001_cloth_pins.bin").write_bytes(
        b"".join(struct.pack("<f", value) for value in (1.0, 0.0, 0.0))
    )
    (geometry_dir / "batch_001_cloth_constraints.bin").write_bytes(
        struct.pack("<2i2f", 0, 1, 1.0, 0.8) + struct.pack("<2i2f", 1, 2, 1.0, 0.8)
    )
    normal = tmp_path / "underwear_n.dds"
    material = tmp_path / "underwear_ma.dds"
    skin_base = tmp_path / "skin_base.dds"
    normal.write_bytes(b"normal")
    material.write_bytes(b"material")
    skin_base.write_bytes(b"skin")
    (package_dir / "manifest.json").write_text(
        json.dumps(
            {
                "normalization_center": list(center),
                "normalization_scale": scale,
                "batches": [
                    {
                        "index": 0,
                        "material_name": "material",
                        "vertex_file": "geometry/batch_000.bin",
                        "vertex_count": 3,
                        "editor_identity": {
                            "source_submesh_index": 0,
                            "source_local_submesh_index": 0,
                            "source_component_index": 0,
                            "prefab_component": False,
                            "identity_file": "geometry/batch_000_identity.bin",
                        },
                        "base_color": [0.78, 0.62, 0.44],
                        "base_tint_only_fallback": False,
                        "roughness": 0.56,
                        "metalness": 0.0,
                        "specular": 0.28,
                        "material_category": "skin",
                        "shader_family": "SkinnedMeshSkin",
                        "normal_y_policy": "shader_invert_legacy_compat",
                        "alpha_mode": "opaque",
                        "two_sided": False,
                        "dds_textures": {
                            "base": {
                                "slot": "base",
                                "source_path": str(skin_base),
                                "semantic_type": "albedo",
                                "shader_family": "SkinnedMeshSkin",
                            },
                            "material_inputs": [
                                {
                                    "slot": "base",
                                    "source_path": str(skin_base),
                                    "semantic_type": "albedo",
                                    "shader_family": "SkinnedMeshSkin",
                                }
                            ],
                        },
                    },
                    {
                        **_prefab_reference_batch(normal, material),
                        "cloth_enabled": True,
                        "cloth_particle_file": "geometry/batch_001_cloth_particles.bin",
                        "cloth_pin_file": "geometry/batch_001_cloth_pins.bin",
                        "cloth_constraint_file": "geometry/batch_001_cloth_constraints.bin",
                        "cloth_particle_count": 3,
                        "cloth_constraint_count": 2,
                        "cloth_gravity": -9.8,
                        "cloth_damping": 0.7,
                        "cloth_air_resistance": 0.9,
                        "cloth_wind_response": 0.5,
                        "cloth_solver_iterations": 24,
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    return package_dir


def test_native_reference_direct_materials_use_native_identity_and_dds(tmp_path: Path) -> None:
    package_dir = _write_native_reference_composite_fixture(tmp_path)
    reference = _mesh()

    assert apply_dotnet_native_reference_materials(reference, package_dir) == 1
    direct = reference.submeshes[0]
    assert direct.preview_sidecar_shader_family == "SkinnedMeshSkin"
    assert direct.preview_texture_dds_path == str(tmp_path / "skin_base.dds")
    assert direct.preview_native_material_overrides["material_category"] == "skin"
    assert direct.preview_native_material_overrides["metalness"] == 0.0
    assert direct.preview_color == (0.78, 0.62, 0.44)



def test_native_reference_composite_keeps_prefab_separate_and_reference_only(tmp_path: Path) -> None:
    package_dir = _write_native_reference_composite_fixture(tmp_path)
    reference = _mesh()

    assert append_dotnet_native_reference_composite(reference, package_dir) == 1
    assert len(reference.submeshes) == 2
    prefab = reference.submeshes[1]
    assert prefab.vertices == [(11.0, 20.0, 30.0), (10.0, 21.0, 30.0), (10.0, 20.0, 31.0)]
    assert prefab.faces == [(0, 1, 2)]
    assert prefab.source_vertex_map == [7, 8, 9]
    assert prefab.material == "CD_PHW_00_UW_00_0001"
    assert prefab.preview_role == "original_reference_prefab"
    assert prefab.preview_color == (0.90, 0.83, 0.71)
    assert prefab.preview_sidecar_shader_family == "SkinnedMeshCloth_Ver2"
    assert prefab.preview_native_material_overrides["material_category"] == "cloth"
    assert prefab.preview_native_material_overrides["metalness"] == 0.0



def test_native_reference_composite_cancellation_publishes_no_partial_geometry(tmp_path: Path) -> None:
    package_dir = _write_native_reference_composite_fixture(tmp_path)
    reference = _mesh()
    checks = 0

    def cancelled() -> bool:
        nonlocal checks
        checks += 1
        return checks >= 2

    assert append_dotnet_native_reference_composite(
        reference,
        package_dir,
        cancelled=cancelled,
    ) == 0
    assert len(reference.submeshes) == 1
    assert reference.total_vertices == 3
