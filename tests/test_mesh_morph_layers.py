from __future__ import annotations

from dataclasses import replace
import json

import pytest

from cdmw.domain.mesh.body_region_sliders import build_region_slider_definitions
from cdmw.domain.mesh.body_regions import BodyRegion, BodyRegionAxis, BodyRegionWeights
from cdmw.domain.mesh.morph import (
    MESH_MORPH_LAYERED_PRESET_FORMAT,
    MESH_MORPH_PRESET_FORMAT,
    MeshMorphProfile,
    MeshMorphValuePreset,
    mesh_morph_driver_topology_fingerprint,
)
from cdmw.domain.mesh.morph_layers import (
    compose_mesh_morph_values,
    mesh_morph_macros,
    mesh_morph_profile_definition_fingerprint,
    mesh_morph_side_pair_limits,
    mesh_morph_side_pairs,
    update_mesh_morph_side_values,
)
from cdmw.modding.mesh_parser import ParsedMesh, SubMesh
from cdmw.services.mesh_morph_profiles import (
    list_mesh_morph_presets,
    mesh_morph_preset_from_payload,
    mesh_morph_preset_payload,
    read_mesh_morph_bundle,
    save_mesh_morph_preset,
    serialized_mesh_morph_bundle,
    validate_mesh_morph_preset,
)


def _mesh() -> ParsedMesh:
    part = SubMesh(
        name="body", material="skin", texture="",
        vertices=[(-1.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)],
        normals=[(0.0, 0.0, 1.0)] * 3,
        uvs=[(0.0, 0.0)] * 3,
        faces=[(0, 1, 2)], vertex_count=3, face_count=1,
    )
    return ParsedMesh(
        path="body.pac", format="pac", submeshes=[part],
        total_vertices=3, total_faces=1, has_uvs=True,
    )


def _profile() -> MeshMorphProfile:
    regions = (
        "pelvis", "spine_lower", "spine_upper", "clavicle_l", "clavicle_r",
        "upper_arm_l", "upper_arm_r", "forearm_l", "forearm_r",
        "hip_l", "hip_r", "thigh_l", "thigh_r",
    )
    definitions = tuple(
        definition
        for region_id in regions
        for definition in build_region_slider_definitions(BodyRegion(
            region_id=region_id, label=region_id, group="Torso",
            parts=(BodyRegionWeights(0, (0, 1, 2), (1.0, 1.0, 1.0)),),
            axis=BodyRegionAxis(
                origin=(0.0, 0.0, 0.0), direction=(0.0, 1.0, 0.0),
                length=1.0, source="bone_chain",
            ),
            vertex_count=3,
        ))
    )
    return MeshMorphProfile(
        profile_id="body_regions_fixture", name="Body controls",
        topology_fingerprint=mesh_morph_driver_topology_fingerprint(_mesh(), definitions),
        definitions=definitions,
    )


def _manual(profile: MeshMorphProfile, **overrides: float) -> dict[str, float]:
    values = {item.definition_id: item.default_percent for item in profile.definitions}
    values.update(overrides)
    return values


def _preset(
    profile: MeshMorphProfile, *, manuals: dict[str, float] | None = None,
    macros: dict[str, float] | None = None,
) -> MeshMorphValuePreset:
    manuals = _manual(profile, spine_lower_size=12.5) if manuals is None else manuals
    macros = {"waist_shape": 35.0} if macros is None else macros
    return MeshMorphValuePreset(
        preset_id="balanced", name="Balanced", profile_id=profile.profile_id,
        topology_fingerprint=profile.topology_fingerprint,
        values=tuple(compose_mesh_morph_values(profile, manuals, macros).items()),
        manual_values=tuple(manuals.items()), macro_values=tuple(macros.items()),
        profile_definition_fingerprint=mesh_morph_profile_definition_fingerprint(profile),
    )


def test_macro_catalog_requires_every_supported_generated_control() -> None:
    profile = _profile()
    assert [item.macro_id for item in mesh_morph_macros(profile)] == [
        "shoulder_contour", "waist_shape", "hip_thigh_transition", "upper_body_balance",
    ]
    missing = replace(profile, definitions=tuple(
        item for item in profile.definitions if item.definition_id != "hip_l_size"
    ))
    assert "hip_thigh_transition" not in {item.macro_id for item in mesh_morph_macros(missing)}
    changed = replace(profile, definitions=tuple(
        replace(item, rule=replace(item.rule, amount=0.99))
        if item.definition_id == "spine_lower_size" else item
        for item in profile.definitions
    ))
    assert "waist_shape" not in {item.macro_id for item in mesh_morph_macros(changed)}


def test_composition_retains_manual_values_and_zero_recovers_after_saturation() -> None:
    profile = _profile()
    manual = _manual(profile, spine_lower_size=95.0, upper_arm_l_length=33.25)
    before = dict(manual)
    macros = {"waist_shape": 100.0}
    result = compose_mesh_morph_values(profile, manual, macros)
    assert result["spine_lower_size"] == 100.0
    assert result["pelvis_size"] == 25.0
    assert result["upper_arm_l_length"] == 33.25
    assert manual == before
    assert macros == {"waist_shape": 100.0}
    assert compose_mesh_morph_values(profile, manual, {"waist_shape": 0.0}) == before


def test_multiple_controls_combine_once_and_are_order_independent() -> None:
    profile = _profile()
    manual = _manual(profile, spine_upper_size=3.0)
    macros = {"waist_shape": 50.0, "upper_body_balance": 20.0}
    first = compose_mesh_morph_values(profile, manual, macros)
    second = compose_mesh_morph_values(profile, manual, dict(reversed(tuple(macros.items()))))
    assert first == second
    assert first["spine_upper_size"] == pytest.approx(23.0)
    assert first["upper_arm_l_size"] == first["upper_arm_r_size"] == 8.0


@pytest.mark.parametrize("values", [
    {"unknown": 1.0}, {"waist_shape": float("nan")}, {"waist_shape": float("inf")},
    {"waist_shape": True}, {"waist_shape": 100.01},
    (("waist_shape", 1.0), ("waist_shape", 2.0)),
])
def test_invalid_macro_values_are_refused_without_mutation(values) -> None:
    profile = _profile()
    manual = _manual(profile)
    before = dict(manual)
    with pytest.raises(ValueError):
        compose_mesh_morph_values(profile, manual, values)
    assert manual == before


@pytest.mark.parametrize("mutation", ["missing", "unknown", "outside", "nan"])
def test_manual_values_require_exact_profile_ids_and_finite_bounded_values(mutation) -> None:
    profile = _profile()
    manual = _manual(profile)
    if mutation == "missing":
        manual.pop("pelvis_size")
    elif mutation == "unknown":
        manual["unrelated"] = 1.0
    else:
        manual["pelvis_size"] = 100.01 if mutation == "outside" else float("nan")
    with pytest.raises(ValueError):
        compose_mesh_morph_values(profile, manual, {})


def test_layered_preset_round_trips_with_retained_values_and_portable_identity(tmp_path) -> None:
    profile = _profile()
    preset = _preset(profile)
    assert preset.format == MESH_MORPH_LAYERED_PRESET_FORMAT
    payload = mesh_morph_preset_payload(preset)
    assert payload["manual_values"]["spine_lower_size"] == 12.5
    assert payload["values"]["spine_lower_size"] == 47.5
    assert mesh_morph_preset_from_payload(payload) == preset
    destination = save_mesh_morph_preset(tmp_path, preset)
    assert json.loads(destination.read_text())["format"] == MESH_MORPH_LAYERED_PRESET_FORMAT
    assert list_mesh_morph_presets(tmp_path, profile) == ((preset,), ())
    bundle = tmp_path / "portable.json"
    bundle.write_text(serialized_mesh_morph_bundle(profile, preset, max_bytes=1_000_000))
    loaded_profile, loaded_preset = read_mesh_morph_bundle(bundle, _mesh(), max_bytes=1_000_000)
    assert loaded_profile == profile
    assert loaded_preset == preset
    assert compose_mesh_morph_values(loaded_profile, loaded_preset.manual_values, {}) == dict(preset.manual_values)


def test_old_v2_presets_keep_original_format_and_have_no_layers() -> None:
    profile = _profile()
    preset = MeshMorphValuePreset(
        preset_id="manual", name="Manual", profile_id=profile.profile_id,
        topology_fingerprint=profile.topology_fingerprint,
        values=tuple(_manual(profile, pelvis_size=20.0).items()),
    )
    payload = mesh_morph_preset_payload(preset)
    assert payload["format"] == MESH_MORPH_PRESET_FORMAT
    assert "manual_values" not in payload
    assert mesh_morph_preset_from_payload(payload) == preset
    validate_mesh_morph_preset(profile, preset)


@pytest.mark.parametrize("field,value", [
    ("format", MESH_MORPH_PRESET_FORMAT),
    ("format", "cdmw.mesh_morph_value_preset.v99"),
    ("symmetry_enabled", "false"),
    ("manual_values", []),
    ("macro_values", {"waist_shape": float("nan")}),
    ("profile_definition_fingerprint", "bad"),
])
def test_layered_payload_refuses_downgrade_and_malformed_state(field, value) -> None:
    payload = mesh_morph_preset_payload(_preset(_profile()))
    payload[field] = value
    with pytest.raises(ValueError):
        mesh_morph_preset_from_payload(payload)


def test_layered_payload_requires_each_retained_field() -> None:
    payload = mesh_morph_preset_payload(_preset(_profile()))
    payload.pop("macro_values")
    with pytest.raises(ValueError, match="all retained layer fields"):
        mesh_morph_preset_from_payload(payload)


@pytest.mark.parametrize("changed_field", ["pivot", "range", "rule", "weights"])
def test_saved_layers_refuse_changed_body_definition_semantics(changed_field) -> None:
    profile = _profile()
    preset = _preset(profile)
    definition = profile.definitions[0]
    if changed_field == "pivot":
        changed = replace(definition, pivot=(0.1, 0.0, 0.0))
    elif changed_field == "range":
        changed = replace(definition, max_percent=75.0)
    elif changed_field == "rule":
        changed = replace(definition, rule=replace(definition.rule, amount=0.42))
    else:
        changed = replace(definition, vertices=tuple(
            replace(item, weight=0.5) for item in definition.vertices
        ))
    edited = replace(profile, definitions=(changed, *profile.definitions[1:]))
    with pytest.raises(ValueError, match="definition identity"):
        validate_mesh_morph_preset(edited, preset)


def test_labels_do_not_change_layer_identity_but_effective_value_tampering_is_rejected(tmp_path) -> None:
    profile = _profile()
    preset = _preset(profile)
    relabeled = replace(profile, name="Renamed", definitions=tuple(
        replace(item, label="Renamed control", category="Other") for item in profile.definitions
    ))
    validate_mesh_morph_preset(relabeled, preset)
    values = dict(preset.values)
    values["spine_lower_size"] += 1.0
    corrupted = replace(preset, values=tuple(values.items()))
    with pytest.raises(ValueError, match="effective values"):
        validate_mesh_morph_preset(profile, corrupted)
    save_mesh_morph_preset(tmp_path, corrupted)
    presets, diagnostics = list_mesh_morph_presets(tmp_path, profile)
    assert presets == ()
    assert any("effective values" in message for message in diagnostics)

def test_linking_sides_suspends_offsets_and_unlinking_recovers_them() -> None:
    profile = _profile()
    manual = _manual(profile, thigh_l_size=10.0, thigh_r_size=30.0)
    linked = compose_mesh_morph_values(
        profile, manual, {"hip_thigh_transition": 20.0}, symmetry_enabled=True,
    )
    assert linked["thigh_l_size"] == linked["thigh_r_size"] == 29.0
    unlinked = compose_mesh_morph_values(
        profile, manual, {"hip_thigh_transition": 20.0}, symmetry_enabled=False,
    )
    assert unlinked["thigh_l_size"] == 19.0
    assert unlinked["thigh_r_size"] == 39.0
    assert manual["thigh_l_size"] == 10.0
    assert manual["thigh_r_size"] == 30.0


def test_both_side_edit_preserves_asymmetry_and_reports_actual_mean_limits() -> None:
    profile = _profile()
    manual = _manual(profile, thigh_l_size=10.0, thigh_r_size=30.0)
    assert mesh_morph_side_pair_limits(profile, manual, "thigh_size") == (-90.0, 90.0)
    edited = update_mesh_morph_side_values(profile, manual, "thigh_size", 40.0)
    assert edited["thigh_l_size"] == 30.0
    assert edited["thigh_r_size"] == 50.0
    linked = compose_mesh_morph_values(profile, edited, symmetry_enabled=True)
    assert linked["thigh_l_size"] == linked["thigh_r_size"] == 40.0
    assert compose_mesh_morph_values(profile, edited)["thigh_l_size"] == 30.0
    assert manual["thigh_l_size"] == 10.0
    at_limit = update_mesh_morph_side_values(profile, manual, "thigh_size", 90.0)
    assert at_limit["thigh_l_size"] == 80.0
    assert at_limit["thigh_r_size"] == 100.0
    with pytest.raises(ValueError, match="preserves its side offsets"):
        update_mesh_morph_side_values(profile, manual, "thigh_size", 95.0)
    assert manual["thigh_r_size"] == 30.0


def test_individual_side_edit_preserves_the_other_side() -> None:
    profile = _profile()
    manual = _manual(profile, thigh_l_size=10.0, thigh_r_size=30.0)
    left = update_mesh_morph_side_values(profile, manual, "thigh_size", -60.0, side="left")
    right = update_mesh_morph_side_values(profile, left, "thigh_size", 70.0, side="right")
    assert right["thigh_l_size"] == -60.0
    assert right["thigh_r_size"] == 70.0
    assert mesh_morph_side_pair_limits(profile, right, "thigh_size") == (-35.0, 35.0)
    assert mesh_morph_side_pair_limits(profile, right, "thigh_size", side="left") == (-100.0, 100.0)


@pytest.mark.parametrize("pair_id,side,value", [
    ("unknown", "both", 0.0), ("thigh_size", "invalid", 0.0),
    ("thigh_size", "left", float("nan")), ("thigh_size", "right", 100.01),
    ("thigh_size", "both", True),
])
def test_side_edits_refuse_unknown_controls_and_invalid_values(pair_id, side, value) -> None:
    profile = _profile()
    manual = _manual(profile)
    with pytest.raises(ValueError):
        update_mesh_morph_side_values(profile, manual, pair_id, value, side=side)
    assert manual == _manual(profile)


def test_side_catalog_requires_matching_generated_rule_signatures() -> None:
    profile = _profile()
    assert any(pair.pair_id == "thigh_length" for pair in mesh_morph_side_pairs(profile))
    changed = replace(profile, definitions=tuple(
        replace(item, mirror_mode="x") if item.definition_id == "thigh_l_length" else item
        for item in profile.definitions
    ))
    assert "thigh_length" not in {pair.pair_id for pair in mesh_morph_side_pairs(changed)}


def test_linked_preset_keeps_asymmetric_manual_values_after_serialization() -> None:
    profile = _profile()
    manual = _manual(profile, thigh_l_size=-25.0, thigh_r_size=65.0)
    preset = _preset(profile, manuals=manual, macros={})
    preset = replace(
        preset, symmetry_enabled=True,
        values=tuple(compose_mesh_morph_values(profile, manual, symmetry_enabled=True).items()),
    )
    restored = mesh_morph_preset_from_payload(mesh_morph_preset_payload(preset))
    validate_mesh_morph_preset(profile, restored)
    assert restored.symmetry_enabled
    assert dict(restored.values)["thigh_l_size"] == 20.0
    assert dict(restored.manual_values)["thigh_l_size"] == -25.0
    assert dict(restored.manual_values)["thigh_r_size"] == 65.0


def test_controlled_profile_id_rename_preserves_layers_only_when_pair_ids_agree() -> None:
    profile = _profile()
    preset = _preset(profile)
    renamed = replace(profile, profile_id="imported-distinct-profile")
    assert mesh_morph_profile_definition_fingerprint(renamed) == mesh_morph_profile_definition_fingerprint(profile)
    with pytest.raises(ValueError, match="identity"):
        validate_mesh_morph_preset(renamed, preset)
    aligned = replace(preset, profile_id=renamed.profile_id)
    validate_mesh_morph_preset(renamed, aligned)
    assert dict(aligned.manual_values) == dict(preset.manual_values)


@pytest.mark.parametrize("left,right", [(-19.3, 65.9), (0.1, 0.2), (99.9, -100.0)])
def test_displayed_both_limits_are_usable_for_fractional_side_offsets(left, right) -> None:
    profile = _profile()
    manual = _manual(profile, thigh_l_size=left, thigh_r_size=right)
    limits = mesh_morph_side_pair_limits(profile, manual, "thigh_size")
    for value in limits:
        edited = update_mesh_morph_side_values(profile, manual, "thigh_size", value)
        assert -100.0 <= edited["thigh_l_size"] <= 100.0
        assert -100.0 <= edited["thigh_r_size"] <= 100.0
        assert edited["thigh_r_size"] - edited["thigh_l_size"] == pytest.approx(right - left)
