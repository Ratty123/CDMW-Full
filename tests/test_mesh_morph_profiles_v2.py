from __future__ import annotations

import json
from dataclasses import replace

import pytest

from cdmw.domain.mesh import (
    MESH_MORPH_PRESET_FORMAT,
    MESH_MORPH_PROFILE_FORMAT,
    MeshMorphDefinition,
    MeshMorphProfile,
    MeshMorphRule,
    MeshMorphValuePreset,
    MeshMorphVertexWeight,
    build_weighted_morph_selection,
    clamp_morph_value,
    generate_procedural_morph_fields,
    mesh_morph_driver_topology_fingerprint,
    mesh_topology_fingerprint,
    procedural_morph_pivot,
)
from cdmw.modding.mesh_parser import ParsedMesh, SubMesh
from cdmw.services.mesh_morph_profiles import (
    list_mesh_morph_presets,
    list_mesh_morph_profiles,
    mesh_morph_preset_from_payload,
    mesh_morph_preset_payload,
    mesh_morph_profile_from_payload,
    mesh_morph_profile_payload,
    save_mesh_morph_preset,
    save_mesh_morph_profile,
)


def _submesh(
    *,
    name: str = "body",
    material: str = "skin",
    vertices: list[tuple[float, float, float]] | None = None,
    faces: list[tuple[int, int, int]] | None = None,
) -> SubMesh:
    resolved_vertices = vertices or [
        (-1.0, -1.0, 0.0),
        (1.0, -1.0, 0.0),
        (-1.0, 1.0, 0.0),
        (1.0, 1.0, 0.0),
    ]
    resolved_faces = faces or [(0, 1, 2), (1, 3, 2)]
    return SubMesh(
        name=name,
        material=material,
        texture="skin.dds",
        vertices=list(resolved_vertices),
        normals=[(0.0, 0.0, 1.0)] * len(resolved_vertices),
        uvs=[(0.0, 0.0)] * len(resolved_vertices),
        faces=list(resolved_faces),
        vertex_count=len(resolved_vertices),
        face_count=len(resolved_faces),
    )


def _mesh(*submeshes: SubMesh) -> ParsedMesh:
    resolved = list(submeshes or (_submesh(),))
    return ParsedMesh(
        path="character/body.pac",
        format="pac",
        submeshes=resolved,
        total_vertices=sum(len(item.vertices) for item in resolved),
        total_faces=sum(len(item.faces) for item in resolved),
        has_uvs=True,
    )


def _definition(mesh: ParsedMesh, *, kind: str = "volume", amount: float = 0.25) -> MeshMorphDefinition:
    vertices = tuple(
        MeshMorphVertexWeight(0, index, 1.0)
        for index in range(len(mesh.submeshes[0].vertices))
    )
    return MeshMorphDefinition(
        definition_id=kind,
        label=kind.title(),
        category="Body",
        vertices=vertices,
        pivot=procedural_morph_pivot(mesh, vertices),
        local_basis=((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0)),
        rule=MeshMorphRule(kind=kind, axis="y", amount=amount, feather=0),
    )


def _profile(mesh: ParsedMesh) -> MeshMorphProfile:
    definition = _definition(mesh)
    return MeshMorphProfile(
        profile_id="body-shape",
        name="Body Shape",
        topology_fingerprint=mesh_morph_driver_topology_fingerprint(mesh, (definition,)),
        definitions=(definition,),
    )


@pytest.mark.parametrize("kind", ("volume", "scale", "move", "flatten", "taper", "twist"))
def test_every_procedural_rule_generates_deterministic_sparse_100_percent_fields(kind: str) -> None:
    mesh = _mesh()
    definition = _definition(mesh, kind=kind, amount=30.0 if kind == "twist" else 0.25)

    first = generate_procedural_morph_fields(mesh, definition)
    second = generate_procedural_morph_fields(mesh, definition)

    assert first == second
    assert len(first) == 1
    assert first[0].definition_id == kind
    assert first[0].submesh_index == 0
    assert first[0].vertex_indices == tuple(sorted(first[0].vertex_indices))
    assert first[0].vertex_indices
    assert len(first[0].vertex_indices) == len(first[0].deltas)
    assert any(any(abs(component) > 1.0e-9 for component in delta) for delta in first[0].deltas)


def test_weighted_selection_expands_by_adjacency_with_linear_and_smooth_falloff() -> None:
    mesh = _mesh(
        _submesh(
            vertices=[
                (0.0, 0.0, 0.0),
                (1.0, 0.0, 0.0),
                (0.0, 1.0, 0.0),
                (1.0, 1.0, 0.0),
                (2.0, 1.0, 0.0),
            ],
            faces=[(0, 1, 2), (2, 3, 4)],
        )
    )

    linear = build_weighted_morph_selection(mesh, {0: (0,)}, feather=2, falloff="linear")
    smooth = build_weighted_morph_selection(mesh, {0: (0,)}, feather=2, falloff="smooth")
    linear_weights = {item.vertex_index: item.weight for item in linear}
    smooth_weights = {item.vertex_index: item.weight for item in smooth}

    assert linear_weights[0] == 1.0
    assert linear_weights[1] == pytest.approx(2.0 / 3.0)
    assert linear_weights[2] == pytest.approx(2.0 / 3.0)
    assert linear_weights[3] == pytest.approx(1.0 / 3.0)
    assert linear_weights[4] == pytest.approx(1.0 / 3.0)
    assert smooth_weights[0] == 1.0
    assert smooth_weights[1] > linear_weights[1]
    assert smooth_weights[3] < linear_weights[3]


def test_strict_mirroring_adds_exact_partner_and_rejects_missing_partner() -> None:
    symmetric = _mesh(
        _submesh(
            vertices=[(-1.0, 0.0, 0.0), (1.0, 0.0, 0.0), (-1.0, 1.0, 0.0), (1.0, 1.0, 0.0)],
            faces=[(0, 1, 2), (1, 3, 2)],
        )
    )
    mirrored = build_weighted_morph_selection(symmetric, {0: (0,)}, mirror_mode="x")
    assert {(item.submesh_index, item.vertex_index) for item in mirrored} == {(0, 0), (0, 1)}

    asymmetric = _mesh(
        _submesh(
            vertices=[(-1.0, 0.0, 0.0), (1.0, 0.0, 0.0), (-0.5, 1.0, 0.0)],
            faces=[(0, 1, 2)],
        )
    )
    with pytest.raises(ValueError, match="no reflected match"):
        build_weighted_morph_selection(asymmetric, {0: (2,)}, mirror_mode="x")


def test_topology_fingerprint_is_exact_but_position_name_and_material_independent() -> None:
    original = _mesh()
    appearance_only = _mesh(
        _submesh(
            name="renamed",
            material="cloth",
            vertices=[(-5.0, -2.0, 7.0), (3.0, -2.0, 7.0), (-5.0, 8.0, 7.0), (3.0, 8.0, 7.0)],
        )
    )
    rewound = _mesh(_submesh(faces=[(0, 2, 1), (1, 3, 2)]))
    extra_vertex = _mesh(
        _submesh(
            vertices=[(-1.0, -1.0, 0.0), (1.0, -1.0, 0.0), (-1.0, 1.0, 0.0), (1.0, 1.0, 0.0), (0.0, 2.0, 0.0)],
        )
    )

    assert mesh_topology_fingerprint(original) == mesh_topology_fingerprint(appearance_only)
    assert mesh_topology_fingerprint(original) != mesh_topology_fingerprint(rewound)
    assert mesh_topology_fingerprint(original) != mesh_topology_fingerprint(extra_vertex)


def test_definition_range_clamps_values_and_rejects_invalid_local_basis() -> None:
    mesh = _mesh()
    definition = replace(_definition(mesh), min_percent=-25.0, max_percent=75.0, default_percent=10.0)

    assert clamp_morph_value(definition, -100.0) == -25.0
    assert clamp_morph_value(definition, 100.0) == 75.0
    assert clamp_morph_value(definition, object()) == 10.0
    with pytest.raises(ValueError, match="orthogonal"):
        replace(definition, local_basis=((1.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 0.0, 1.0)))


def test_v2_profile_and_value_preset_round_trip_through_atomic_settings_storage(tmp_path) -> None:
    mesh = _mesh()
    profile = _profile(mesh)
    profile_path = save_mesh_morph_profile(tmp_path, profile)
    presets_root = tmp_path / "presets" / profile.profile_id
    preset = MeshMorphValuePreset(
        preset_id="athletic",
        name="Athletic",
        profile_id=profile.profile_id,
        topology_fingerprint=profile.topology_fingerprint,
        values=(("volume", 37.5),),
    )
    preset_path = save_mesh_morph_preset(tmp_path, preset)

    assert profile_path == tmp_path / "definitions" / "body-shape.json"
    assert preset_path == presets_root / "athletic.json"
    assert not tuple(tmp_path.rglob("*.tmp"))
    assert mesh_morph_profile_from_payload(mesh_morph_profile_payload(profile)) == profile
    assert mesh_morph_preset_from_payload(mesh_morph_preset_payload(preset)) == preset
    profiles, profile_diagnostics = list_mesh_morph_profiles(tmp_path, mesh)
    presets, preset_diagnostics = list_mesh_morph_presets(tmp_path, profiles[0])
    assert profiles == (profile,)
    assert presets == (preset,)
    assert profile_diagnostics == ()
    assert preset_diagnostics == ()
    assert json.loads(profile_path.read_text(encoding="utf-8"))["format"] == MESH_MORPH_PROFILE_FORMAT
    assert json.loads(preset_path.read_text(encoding="utf-8"))["format"] == MESH_MORPH_PRESET_FORMAT


def test_mismatched_profile_and_preset_fingerprints_are_omitted_with_diagnostics(tmp_path) -> None:
    mesh = _mesh()
    profile = _profile(mesh)
    mismatched = replace(profile, topology_fingerprint="0" * 64)
    save_mesh_morph_profile(tmp_path, mismatched)

    profiles, diagnostics = list_mesh_morph_profiles(tmp_path, mesh)

    assert profiles == ()
    assert any("topology does not match" in item for item in diagnostics)

    save_mesh_morph_profile(tmp_path, profile)
    save_mesh_morph_preset(
        tmp_path,
        MeshMorphValuePreset(
            preset_id="wrong",
            name="Wrong",
            profile_id=profile.profile_id,
            topology_fingerprint="f" * 64,
            values=(("volume", 10.0),),
        ),
    )
    presets, preset_diagnostics = list_mesh_morph_presets(tmp_path, profile)
    assert presets == ()
    assert any("driver identity" in item for item in preset_diagnostics)


def test_profile_compatibility_fingerprints_only_definition_driver_submeshes(tmp_path) -> None:
    body = _submesh()
    garment = _submesh(name="shirt", material="cloth")
    mesh = _mesh(body, garment)
    profile = _profile(mesh)
    save_mesh_morph_profile(tmp_path, profile)
    changed_garment = _submesh(
        name="other-shirt",
        material="other-cloth",
        vertices=[(-1.0, -1.0, 2.0), (1.0, -1.0, 2.0), (-1.0, 1.0, 2.0), (1.0, 1.0, 2.0), (0.0, 2.0, 2.0)],
        faces=[(0, 1, 2), (1, 3, 2), (2, 3, 4)],
    )

    compatible, diagnostics = list_mesh_morph_profiles(tmp_path, _mesh(_submesh(), changed_garment))
    incompatible, mismatch_diagnostics = list_mesh_morph_profiles(
        tmp_path,
        _mesh(_submesh(faces=[(0, 2, 1), (1, 3, 2)]), changed_garment),
    )

    assert compatible == (profile,)
    assert diagnostics == ()
    assert incompatible == ()
    assert any("driver topology does not match" in item for item in mismatch_diagnostics)


def test_compatible_v1_region_migrates_in_memory_target_slider_is_omitted_and_explicit_save_writes_v2(tmp_path) -> None:
    mesh = _mesh()
    legacy_root = tmp_path / "legacy-body"
    legacy_root.mkdir()
    region_path = legacy_root / "volume.region.json"
    region_path.write_text(
        json.dumps(
            {
                "selected_vertices_by_submesh": {"0": [0, 1]},
                "feather": 1,
                "amount": 0.2,
            }
        ),
        encoding="utf-8",
    )
    signature = {
        "submesh_count": 1,
        "submeshes": [
            {
                "name": "body",
                "material": "skin",
                "vertex_count": 4,
                "face_count": 2,
                "faces": [[0, 1, 2], [1, 3, 2]],
            }
        ],
    }
    profile_path = legacy_root / "profile.json"
    profile_path.write_text(
        json.dumps(
            {
                "format": "cdmw.mesh_morph_slider_profile.v1",
                "name": "Legacy Body",
                "topology_signature": signature,
                "sliders": [
                    {
                        "id": "volume",
                        "label": "Volume",
                        "type": "region_volume",
                        "region_path": region_path.name,
                        "min_percent": -50,
                        "max_percent": 125,
                    },
                    {
                        "id": "target-shape",
                        "label": "Target Shape",
                        "type": "morph_target",
                        "target_path": "target.obj",
                    },
                ],
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    original_legacy_bytes = profile_path.read_bytes()

    profiles, diagnostics = list_mesh_morph_profiles(tmp_path, mesh)

    assert len(profiles) == 1
    migrated = profiles[0]
    assert migrated.migrated_from_version == 1
    assert migrated.requires_v2_save is True
    assert tuple(item.definition_id for item in migrated.definitions) == ("volume",)
    assert migrated.definitions[0].rule.kind == "volume"
    assert any("target-based v1 sliders are unsupported" in item for item in diagnostics)
    assert any("in memory" in item for item in diagnostics)
    assert profile_path.read_bytes() == original_legacy_bytes
    assert not (tmp_path / "definitions").exists()

    saved = save_mesh_morph_profile(tmp_path, migrated)

    assert saved.is_file()
    assert profile_path.read_bytes() == original_legacy_bytes
    saved_payload = json.loads(saved.read_text(encoding="utf-8"))
    assert saved_payload["format"] == MESH_MORPH_PROFILE_FORMAT
    assert "target_path" not in saved.read_text(encoding="utf-8")
