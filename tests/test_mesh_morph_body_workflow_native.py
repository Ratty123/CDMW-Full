"""Resident proof for generated body controls and reversible fitting layers.

The owned fixture keeps every anatomical region on a distinct triangle. Body
radius changes have an independent analytic expectation, and garment snapshots
exercise the existing native refit and history paths without game assets.
"""

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
    mesh_morph_driver_topology_fingerprint,
)
from cdmw.domain.mesh.morph_layers import mesh_morph_profile_definition_fingerprint
from cdmw.modding.mesh_parser import ParsedMesh
from tests.test_mesh_body_controls_generation import (
    _mesh as _skinned_mesh,
    _palette_bytes,
    _skeleton,
)
from tests.test_mesh_morph_authoring_native import (
    _assert_positions_equal,
    _positions,
    resident,
)
from tests.test_mesh_morph_service import _author_command
from tests.test_native_mesh_editor_morph_refit import _part


_REGIONS = (
    "pelvis", "spine_lower", "spine_upper", "clavicle_l", "clavicle_r",
    "upper_arm_l", "upper_arm_r", "forearm_l", "forearm_r",
    "hip_l", "hip_r", "thigh_l", "thigh_r",
)


def _body_mesh():
    vertices, faces = [], []
    for index, _region_id in enumerate(_REGIONS):
        center = 2.0 * index
        first = len(vertices)
        vertices.extend(((center - 0.5, 0.0, 0.0), (center + 0.5, 0.0, 0.0), (center, 1.0, 0.5)))
        faces.append((first, first + 1, first + 2))
    body = _part("body", vertices, faces, material="skin", texture="skin.dds")
    garment = _part(
        "garment", [(x, y, z + 0.05) for x, y, z in vertices], faces,
        material="cloth", texture="cloth.dds",
    )
    untouched = _part(
        "untouched", [(40.0, 0.0, 0.0), (41.0, 0.0, 0.0), (40.0, 1.0, 0.0)],
        [(0, 1, 2)], material="other", texture="other.dds",
    )
    return ParsedMesh(
        path="owned-body-workflow.pac", format="pac", submeshes=[body, garment, untouched],
        total_vertices=len(vertices) * 2 + 3, total_faces=len(faces) * 2 + 1,
        has_uvs=True, has_bones=True,
    )


def _body_profile(mesh):
    definitions = tuple(
        definition
        for index, region_id in enumerate(_REGIONS)
        for definition in build_region_slider_definitions(BodyRegion(
            region_id=region_id, label=region_id, group="Body",
            parts=(BodyRegionWeights(0, tuple(range(index * 3, index * 3 + 3)), (1.0, 1.0, 1.0)),),
            axis=BodyRegionAxis(
                origin=(2.0 * index, 0.0, 0.0), direction=(0.0, 1.0, 0.0),
                length=1.0, source="bone_chain",
            ),
            vertex_count=3,
        ))
    )
    return MeshMorphProfile(
        profile_id="body_regions_native_fixture", name="Native Body Controls",
        topology_fingerprint=mesh_morph_driver_topology_fingerprint(mesh, definitions),
        definitions=definitions,
    )


def _activate(service, session_id, profile, *, bind):
    session = service._session(session_id)
    with session.export_lock:
        result, state = service._activate_morph_profile_locked(session, profile)
    assert result.ok
    assert {item.macro_id for item in state.macro_definitions} == {
        "shoulder_contour", "waist_shape", "hip_thigh_transition", "upper_body_balance",
    }
    if bind:
        assert service.set_refit_driver(session_id, (0,))[0].ok
        assert service.bind_refit(session_id, (1,))[0].ok


def _open_body(resident, *, bind=True):
    service, open_session = resident
    mesh = _body_mesh()
    profile = _body_profile(mesh)
    session_id = open_session(mesh)
    _activate(service, session_id, profile, bind=bind)
    return service, open_session, session_id, mesh, profile


def _geometry(service, session_id):
    mesh = service.working_mesh(session_id, clone=True)
    return tuple(tuple(tuple(point) for point in part.vertices) for part in mesh.submeshes)


def _assert_geometry(actual, expected):
    assert len(actual) == len(expected)
    for actual_part, expected_part in zip(actual, expected):
        _assert_positions_equal(actual_part, expected_part)


def _assert_body_sizes(service, session_id, original, **sizes):
    expected = []
    for index, region_id in enumerate(_REGIONS):
        center = 2.0 * index
        scale = 1.0 + 0.30 * sizes.get(region_id, 0.0) / 100.0
        for x, y, z in original.submeshes[0].vertices[index * 3:index * 3 + 3]:
            expected.append((center + (x - center) * scale, y, z * scale))
    _assert_positions_equal(_positions(service, session_id, 0), expected)


def _layers(state):
    return state.values, state.manual_values, state.macro_values, state.symmetry_enabled


def _snapshot(service, session_id):
    state = service.cached_morph_state(session_id)
    return _layers(state), state.profile_id, state.preset_id, _geometry(service, session_id)


def _assert_snapshot(service, session_id, snapshot):
    state = service.cached_morph_state(session_id)
    assert _layers(state) == snapshot[0]
    assert (state.profile_id, state.preset_id) == snapshot[1:3]
    _assert_geometry(_geometry(service, session_id), snapshot[3])


def _set_asymmetric_layers(service, session_id):
    assert service.set_morph_side_value(session_id, "thigh_size", 10.0, side="left")[0].ok
    assert service.set_morph_side_value(session_id, "thigh_size", 30.0, side="right")[0].ok
    assert service.set_morph_macro(session_id, "hip_thigh_transition", 20.0)[0].ok
    assert service.set_morph_symmetry(session_id, True)[0].ok


def test_macro_composes_with_manual_geometry_and_reset_recovers_the_fitted_manual_shape(resident):
    service, _open_session, session_id, mesh, _profile = _open_body(resident)
    neutral = _geometry(service, session_id)
    assert service.set_morph_value(session_id, "spine_lower_size", 12.5)[0].ok
    assert service.set_morph_value(session_id, "forearm_l_size", -10.0)[0].ok
    manual = _geometry(service, session_id)

    changed, state = service.set_morph_macro(session_id, "waist_shape", 40.0)

    assert changed.ok
    assert dict(state.manual_values)["spine_lower_size"] == 12.5
    assert dict(state.values)["spine_lower_size"] == 52.5
    assert dict(state.macro_values) == {"waist_shape": 40.0}
    _assert_body_sizes(service, session_id, mesh, pelvis=10.0, spine_lower=52.5, spine_upper=8.0, forearm_l=-10.0)
    assert _positions(service, session_id, 1) != manual[1]
    _assert_positions_equal(_positions(service, session_id, 2), neutral[2])

    reset, state = service.reset_morph_macros(session_id)

    assert reset.ok and state.macro_values == ()
    assert dict(state.values)["spine_lower_size"] == 12.5
    assert dict(state.values)["forearm_l_size"] == -10.0
    _assert_geometry(_geometry(service, session_id), manual)
    assert manual[0] != neutral[0] and manual[1] != neutral[1]

    assert service.set_morph_macro(session_id, "waist_shape", 40.0)[0].ok
    changed, state = service.set_morph_value(session_id, "spine_lower_size", 25.0)
    assert changed.ok
    assert dict(state.manual_values)["spine_lower_size"] == 25.0
    assert dict(state.values)["spine_lower_size"] == 65.0
    assert dict(state.macro_values) == {"waist_shape": 40.0}
    _assert_body_sizes(service, session_id, mesh, pelvis=10.0, spine_lower=65.0, spine_upper=8.0, forearm_l=-10.0)


def test_linking_is_reversible_and_both_moves_the_mean_without_losing_side_offsets(resident):
    service, _open_session, session_id, mesh, _profile = _open_body(resident)
    assert service.set_morph_side_value(session_id, "thigh_size", 10.0, side="left")[0].ok
    assert service.set_morph_side_value(session_id, "thigh_size", 30.0, side="right")[0].ok
    asymmetric = _geometry(service, session_id)

    result, state = service.set_morph_symmetry(session_id, True)

    assert result.ok and state.symmetry_enabled
    assert dict(state.manual_values)["thigh_l_size"] == 10.0
    assert dict(state.manual_values)["thigh_r_size"] == 30.0
    assert dict(state.values)["thigh_l_size"] == dict(state.values)["thigh_r_size"] == 20.0
    _assert_body_sizes(service, session_id, mesh, thigh_l=20.0, thigh_r=20.0)
    assert service.set_morph_symmetry(session_id, False)[0].ok
    _assert_geometry(_geometry(service, session_id), asymmetric)

    result, state = service.set_morph_side_value(session_id, "thigh_size", 40.0, side="both")

    assert result.ok
    assert dict(state.manual_values)["thigh_l_size"] == 30.0
    assert dict(state.manual_values)["thigh_r_size"] == 50.0
    _assert_body_sizes(service, session_id, mesh, thigh_l=30.0, thigh_r=50.0)
    shifted = _geometry(service, session_id)
    assert service.set_morph_symmetry(session_id, True)[0].ok
    _assert_body_sizes(service, session_id, mesh, thigh_l=40.0, thigh_r=40.0)
    assert service.set_morph_symmetry(session_id, False)[0].ok
    _assert_geometry(_geometry(service, session_id), shifted)

    before = _snapshot(service, session_id)
    history_length = len(service._session(session_id).undo_stack)
    with pytest.raises(ValueError, match="preserves its side offsets"):
        service.set_morph_side_value(session_id, "thigh_size", 95.0, side="both")
    assert len(service._session(session_id).undo_stack) == history_length
    _assert_snapshot(service, session_id, before)


def test_layer_history_restores_metadata_and_native_body_and_garment_geometry(resident):
    service, _open_session, session_id, _mesh, _profile = _open_body(resident)
    assert service.set_morph_side_value(session_id, "thigh_size", 10.0, side="left")[0].ok
    assert service.set_morph_side_value(session_id, "thigh_size", 30.0, side="right")[0].ok
    assert service.set_morph_macro(session_id, "hip_thigh_transition", 20.0)[0].ok
    before_link = _snapshot(service, session_id)
    assert service.set_morph_symmetry(session_id, True)[0].ok
    linked = _snapshot(service, session_id)

    assert service.undo(session_id).ok
    _assert_snapshot(service, session_id, before_link)
    assert service.redo(session_id).ok
    _assert_snapshot(service, session_id, linked)

    assert service.set_morph_side_value(session_id, "thigh_size", 40.0, side="both")[0].ok
    shifted = _snapshot(service, session_id)
    assert service.undo(session_id).ok
    _assert_snapshot(service, session_id, linked)
    assert service.redo(session_id).ok
    _assert_snapshot(service, session_id, shifted)

    assert service.reset_morph_macros(session_id)[0].ok
    reset = _snapshot(service, session_id)
    assert dict(reset[0][1])["thigh_l_size"] == 30.0
    assert dict(reset[0][1])["thigh_r_size"] == 50.0
    assert reset[0][2] == () and reset[0][3]
    assert service.undo(session_id).ok
    _assert_snapshot(service, session_id, shifted)
    assert service.redo(session_id).ok
    _assert_snapshot(service, session_id, reset)
    state = service.cached_morph_state(session_id)
    assert state.driver_submesh_indices == (0,)
    assert state.refit.garment_submesh_indices == (1,)


def test_save_preset_persists_unsaved_generated_profile_and_reopens_retained_layers(resident, tmp_path):
    service, open_session, session_id, _mesh, profile = _open_body(resident)
    _set_asymmetric_layers(service, session_id)
    expected_layers = _layers(service.cached_morph_state(session_id))
    expected_geometry = _geometry(service, session_id)
    definition_path = tmp_path / "mesh_slider_profiles" / "definitions" / f"{profile.profile_id}.json"
    assert not definition_path.exists()

    preset = service.save_morph_preset(session_id, "balanced", "Balanced Body")

    assert preset.format == MESH_MORPH_LAYERED_PRESET_FORMAT
    assert preset.manual_values is not None and preset.symmetry_enabled
    assert definition_path.is_file()
    preset_path = tmp_path / "mesh_slider_profiles" / "presets" / profile.profile_id / "balanced.json"
    payload = json.loads(preset_path.read_text())
    assert payload["format"] == MESH_MORPH_LAYERED_PRESET_FORMAT
    assert payload["manual_values"]["thigh_l_size"] == 10.0
    assert payload["values"]["thigh_l_size"] == 29.0

    reopened = open_session(_body_mesh())
    assert service.activate_morph_profile(reopened, profile.profile_id)[0].ok
    assert service.set_refit_driver(reopened, (0,))[0].ok
    assert service.bind_refit(reopened, (1,))[0].ok
    result, state = service.apply_morph_preset(reopened, preset.preset_id)
    assert result.ok and _layers(state) == expected_layers
    _assert_geometry(_geometry(service, reopened), expected_geometry)
    assert service.set_morph_symmetry(reopened, False)[0].ok
    state = service.cached_morph_state(reopened)
    assert dict(state.values)["thigh_l_size"] == 19.0
    assert dict(state.values)["thigh_r_size"] == 39.0


def test_portable_layers_survive_controlled_profile_id_collision_and_import_history(resident, tmp_path):
    service, open_session, session_id, _mesh, profile = _open_body(resident, bind=False)
    _set_asymmetric_layers(service, session_id)
    expected_layers = _layers(service.cached_morph_state(session_id))
    expected_geometry = _geometry(service, session_id)
    bundle = service.export_morph_preset(session_id, str(tmp_path / "portable.json"), "Portable Body")

    collision = replace(
        profile, name="Existing Local Profile",
        definitions=tuple(
            replace(item, rule=replace(item.rule, amount=0.07))
            if item.definition_id == "pelvis_shift" else item
            for item in profile.definitions
        ),
    )
    assert mesh_morph_profile_definition_fingerprint(collision) != mesh_morph_profile_definition_fingerprint(profile)
    target = open_session(_body_mesh())
    _activate(service, target, collision, bind=False)
    service.save_active_morph_profile(target)
    original_path = tmp_path / "mesh_slider_profiles" / "definitions" / f"{profile.profile_id}.json"
    original_bytes = original_path.read_bytes()
    before_import = _snapshot(service, target)
    history_length = len(service._session(target).undo_stack)

    state = service.import_morph_preset(target, bundle)

    assert state.profile_id != profile.profile_id and state.profile_id.startswith("import-")
    assert _layers(state) == expected_layers
    assert len(service._session(target).undo_stack) == history_length + 1
    assert service._morph_sessions[target].known_profiles[profile.profile_id] == collision
    assert original_path.read_bytes() == original_bytes
    _assert_geometry(_geometry(service, target), expected_geometry)
    imported = _snapshot(service, target)
    imported_profile_id, imported_preset_id = state.profile_id, state.preset_id
    assert service.undo(target).ok
    _assert_snapshot(service, target, before_import)
    assert original_path.read_bytes() == original_bytes
    assert service.redo(target).ok
    _assert_snapshot(service, target, imported)

    reopened = open_session(_body_mesh())
    assert service.activate_morph_profile(reopened, imported_profile_id)[0].ok
    result, state = service.apply_morph_preset(reopened, imported_preset_id)
    assert result.ok and _layers(state) == expected_layers
    _assert_geometry(_geometry(service, reopened), expected_geometry)


def test_legacy_custom_sliders_keep_direct_values_and_v2_presets(resident):
    service, open_session = resident
    session_id = open_session()
    neutral = _geometry(service, session_id)
    assert service.apply_command(session_id, _author_command()).ok
    assert service.set_refit_driver(session_id, (0, 1))[0].ok
    assert service.bind_refit(session_id, (2,))[0].ok
    result, state = service.set_morph_value(session_id, "volume", 50.0)
    assert result.ok
    assert state.values == (("volume", 50.0),)
    assert state.macro_definitions == () and state.side_pairs == ()
    expected = _geometry(service, session_id)
    for original, moved in zip(neutral[0], expected[0]):
        assert moved == pytest.approx((original[0], original[1], original[2] + 0.5), abs=1e-6)
    preset = service.save_morph_preset(session_id, "legacy", "Legacy Values")
    assert preset.format == MESH_MORPH_PRESET_FORMAT
    assert preset.manual_values is None and preset.macro_values == ()
    with pytest.raises(ValueError, match="unavailable"):
        service.set_morph_macro(session_id, "waist_shape", 40.0)
    assert service.reset_morph_macros(session_id)[0].status == "noop"
    _assert_geometry(_geometry(service, session_id), expected)
    assert service.reset_morph(session_id)[0].ok
    _assert_geometry(_geometry(service, session_id), neutral)
    assert service.apply_morph_preset(session_id, preset.preset_id)[0].ok
    _assert_geometry(_geometry(service, session_id), expected)


def test_resident_generation_uses_assigned_body_subset_and_keeps_existing_binding_and_profile(resident, tmp_path):
    service, open_session = resident
    skeleton = _skeleton()
    mesh = _skinned_mesh()
    mesh.path = str(tmp_path / "owned-body.pac")
    mesh._cdmw_original_data = _palette_bytes(skeleton)
    for part in mesh.submeshes:
        part.normals = [(1.0, 0.0, 0.0)] * 3
        part.uvs = [(0.0, 0.0), (1.0, 0.0), (0.0, 1.0)]
        part.tangents = [(0.0, 1.0, 0.0)] * 3
    session_id = open_session(mesh)
    service._session(session_id).skeleton = skeleton
    assert service.apply_command(session_id, _author_command()).ok
    old_profile = service._morph_sessions[session_id].profile
    assert service.set_refit_driver(session_id, (1,))[0].ok
    assert service.bind_refit(session_id, (2,))[0].ok
    neutral = _geometry(service, session_id)
    before = _snapshot(service, session_id)
    history_length = len(service._session(session_id).undo_stack)

    result, state = service.generate_body_morph_controls(session_id)

    assert result.ok and result.action == "morph_generate_body_controls"
    assert state.profile_id != old_profile.profile_id
    assert len(service._session(session_id).undo_stack) == history_length + 1
    assert state.driver_submesh_indices == (1,)
    assert state.refit.garment_submesh_indices == (2,)
    assert {row.submesh_index for item in state.definitions for row in item.vertices} == {1}
    assert {item.definition_id for item in state.definitions} == {
        "forearm_l_size", "forearm_l_length", "forearm_l_taper", "forearm_l_flatten", "forearm_l_shift",
    }
    assert all(value == 0.0 for _key, value in state.values)
    assert service._morph_sessions[session_id].known_profiles[old_profile.profile_id] == old_profile
    _assert_geometry(_geometry(service, session_id), neutral)
    generated = _snapshot(service, session_id)
    assert service.undo(session_id).ok
    _assert_snapshot(service, session_id, before)
    assert service.redo(session_id).ok
    _assert_snapshot(service, session_id, generated)
    assert service.set_morph_value(session_id, "forearm_l_size", 50.0)[0].ok
    assert _positions(service, session_id, 1)[1][1] == pytest.approx(1.15, abs=1e-6)
    _assert_positions_equal(_positions(service, session_id, 0), neutral[0])


def test_delete_active_layered_profile_restores_complete_state_on_undo(resident, tmp_path):
    service, _open_session, session_id, _mesh, profile = _open_body(resident)
    neutral = _geometry(service, session_id)
    _set_asymmetric_layers(service, session_id)
    service.save_morph_preset(session_id, "retained", "Retained Layers")
    profile_path = tmp_path / "mesh_slider_profiles" / "definitions" / f"{profile.profile_id}.json"
    profile_bytes = profile_path.read_bytes()
    before = _snapshot(service, session_id)
    history_length = len(service._session(session_id).undo_stack)

    assert service.delete_morph_profile(session_id, profile.profile_id)

    state = service.cached_morph_state(session_id)
    assert state.profile_id == "" and state.definitions == ()
    assert _layers(state) == ((), (), (), False)
    assert profile.profile_id not in service._morph_sessions[session_id].known_profiles
    assert not profile_path.exists()
    assert len(service._session(session_id).undo_stack) == history_length + 1
    _assert_geometry(_geometry(service, session_id), neutral)
    deleted = _snapshot(service, session_id)

    assert service.undo(session_id).ok
    _assert_snapshot(service, session_id, before)
    assert profile_path.read_bytes() == profile_bytes
    restored = service.cached_morph_state(session_id)
    assert restored.driver_submesh_indices == (0,)
    assert restored.refit.garment_submesh_indices == (1,)
    assert service.redo(session_id).ok
    _assert_snapshot(service, session_id, deleted)
    assert not profile_path.exists()


@pytest.mark.parametrize("method_name,keep_shape", [("bake_morph", True), ("reset_morph", False)], ids=["bake", "reset"])
def test_bake_and_reset_clear_layers_with_complete_undo_recovery(resident, method_name, keep_shape):
    service, _open_session, session_id, _mesh, profile = _open_body(resident)
    neutral = _geometry(service, session_id)
    _set_asymmetric_layers(service, session_id)
    before = _snapshot(service, session_id)
    history_length = len(service._session(session_id).undo_stack)

    result, state = getattr(service, method_name)(session_id)

    assert result.ok and state.profile_id == profile.profile_id
    assert all(value == 0.0 for _key, value in state.values)
    assert all(value == 0.0 for _key, value in state.manual_values)
    assert state.macro_values == () and not state.symmetry_enabled
    assert not state.unbaked
    assert len(service._session(session_id).undo_stack) == history_length + 1
    _assert_geometry(_geometry(service, session_id), before[3] if keep_shape else neutral)
    cleared = _snapshot(service, session_id)

    assert service.undo(session_id).ok
    _assert_snapshot(service, session_id, before)
    restored = service.cached_morph_state(session_id)
    assert restored.driver_submesh_indices == (0,)
    assert restored.refit.garment_submesh_indices == (1,)
    assert service.redo(session_id).ok
    _assert_snapshot(service, session_id, cleared)
