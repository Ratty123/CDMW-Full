"""DCC bone-axis changes must not become pose bakes or arbitrary rig retargeting."""

from dataclasses import replace
import math
import re
import struct

import numpy as np
import pytest

from cdmw.modding.mesh_parser import parse_mesh
from cdmw.modding.scene_gltf_import import _read_glb
from cdmw.services.mesh_replacement_import import (
    prepare_import, compose_import, initial_replacement_state, mesh_with_part_ids,
)
from cdmw.services.mesh_replacement_output import prepare_replacement_output
from tests.test_mesh_neutral_face_editing import _appearance
from tests.test_mesh_replacement_imported_skinning import editor, source_glb
from tests.test_scene_importer_gltf import _write_glb


@pytest.fixture
def rig_editor(editor):
    service, sid, order = editor
    bones = service._session(sid).skeleton.bones
    points = [(0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 0, 1),
              (0, 1, 1), (2, 1, 1), (-1, 0, 0), (-1, 1, 0)]
    parents = [-1, 0, 1, 0, 3, 4, 0, 6]
    for bone, point, parent in zip(bones, points, parents):
        bind = np.eye(4)
        bind[:3, 3] = point
        bone.bind_matrix = tuple(bind.T.flat)
        bone.parent_index = parent
    yield service, sid, order, points, parents


def changed_basis_glb(tmp_path, points, parents, *, single_used=False, altered_rest=False,
                      altered_hierarchy=False, degenerate=False, reflected=False, altered_index=7):
    path = source_glb(tmp_path, names=tuple(f"bone{i}" for i in range(8)))
    document, raw = _read_glb(path)
    binary = bytearray(raw)
    transform = np.array(((0., -2., 0., 3.), (2., 0., 0., 4.), (0., 0., 2., 5.), (0., 0., 0., 1.)))
    if reflected:
        transform[0, :3] *= -1
    transform_inverse = np.linalg.inv(transform)
    accessor = document["accessors"][document["skins"][0]["inverseBindMatrices"]]
    view = document["bufferViews"][accessor["bufferView"]]
    for index, point in enumerate(points):
        source_point = (transform_inverse @ np.array((*point, 1.)))[:3]
        if altered_rest is not False and index == altered_index:
            # Unused known bone must still be checked. A number is the offset itself.
            source_point[1] += .1 if altered_rest is True else float(altered_rest)
        if degenerate:
            source_point = np.array((float(index), 0., 0.))
        angle = .2 + index * .31
        bone = np.array(((math.cos(angle), -math.sin(angle), 0., source_point[0]),
                         (math.sin(angle), math.cos(angle), 0., source_point[1]),
                         (0., 0., 1., source_point[2]), (0., 0., 0., 1.)))
        inverse = np.linalg.inv(bone)
        struct.pack_into("<16f", binary, view["byteOffset"] + index * 64, *inverse.T.flat)
        parent = parents[index]
        if altered_hierarchy and index == 7:
            parent = 1
        if parent >= 0:
            document["nodes"][parent + 1].setdefault("children", []).append(index + 1)
    document["scenes"][0]["nodes"] = [0, 1]
    if single_used:
        attributes = document["meshes"][0]["primitives"][0]["attributes"]
        weights_accessor = document["accessors"][attributes["WEIGHTS_0"]]
        weights_view = document["bufferViews"][weights_accessor["bufferView"]]
        struct.pack_into("<12f", binary, weights_view["byteOffset"], *((1., 0., 0., 0.) * 3))
    _write_glb(path, document, bytes(binary))
    return path, transform


@pytest.mark.parametrize("neutral", [False, True])
@pytest.mark.parametrize("single_used", [False, True])
def test_changed_bone_bases_preserve_bind_geometry_and_serialized_weights(rig_editor, tmp_path, neutral, single_used):
    service, sid, order, points, parents = rig_editor
    snapshot = service.capture_export_snapshot(sid)
    if neutral:
        appearance = replace(_appearance(), bone_palette=order)
        matrices = list(appearance.skin_matrices)
        matrices[0], matrices[1] = matrices[3], matrices[7]
        appearance = replace(appearance, skin_matrices=tuple(matrices))
        state = replace(initial_replacement_state(snapshot), neutral_appearance=appearance, neutral_coordinates=True)
        snapshot = replace(snapshot, mesh=appearance.to_neutral(mesh_with_part_ids(snapshot, state)), replacement_state=state)
    path, transform = changed_basis_glb(tmp_path, points, parents, single_used=single_used)
    pending = prepare_import(snapshot, path)
    mesh, state = compose_import(pending, (pending.target_part_ids[0],))
    written = parse_mesh(prepare_replacement_output(replace(snapshot, mesh=mesh, replacement_state=state)).data, state.target_path)
    expected = [(transform @ np.array((*point, 1.)))[:3] for point in ((0., 0., 0.), (1., 0., 0.), (0., 1., 0.))]
    for vertex, point in zip(written.submeshes[0].vertices, expected):
        assert vertex == pytest.approx(point, abs=.002)
    weights = dict(zip(written.submeshes[0].bone_indices[0], written.submeshes[0].bone_weights[0]))
    assert weights == pytest.approx({3: 1.} if single_used else {3: .25, 4: .75}, abs=1 / 255)


@pytest.mark.parametrize("options,reason", [
    ({"altered_rest": True}, "Rest-joint positions"),
    ({"altered_hierarchy": True}, "hierarchy differs"),
    ({"degenerate": True}, "centers are degenerate"),
    ({"reflected": True}, "Rest-joint positions"),
])
def test_changed_bases_refuse_unproven_rigs_without_publishing(rig_editor, tmp_path, options, reason):
    service, sid, _order, points, parents = rig_editor
    snapshot = service.capture_export_snapshot(sid)
    path, _transform = changed_basis_glb(tmp_path, points, parents, **options)
    # The mapping step says why Keep is unavailable; Keep itself is refused.
    pending = prepare_import(snapshot, path)
    keep = pending.skin.option("preserve")
    assert not keep.available and re.search(reason, keep.reason)
    assert pending.skin.default_policy == ""
    with pytest.raises(ValueError, match=reason):
        compose_import(pending, (pending.target_part_ids[0],), skin_policy="preserve")
    with pytest.raises(ValueError, match="Choose how to handle the imported weights"):
        compose_import(pending, (pending.target_part_ids[0],))
    assert service.capture_export_snapshot(sid).mesh_revision == snapshot.mesh_revision
    assert service.capture_export_snapshot(sid).replacement_state is None


def test_rest_pose_refusal_names_the_worst_bone(rig_editor, tmp_path):
    service, sid, _order, points, parents = rig_editor
    path, _transform = changed_basis_glb(tmp_path, points, parents, altered_rest=True)
    pending = prepare_import(service.capture_export_snapshot(sid), path)
    with pytest.raises(ValueError, match=r"the worst, bone7, by [0-9.]+ \([0-9.]+% of the rig size\)"):
        compose_import(pending, (pending.target_part_ids[0],), skin_policy="preserve")


def test_export_rounding_on_a_far_bone_still_reads_as_the_game_rig(rig_editor, tmp_path):
    # A tester's Blender export left two toe bones 0.01% of the rig size off.
    # 1e-4 here is 2e-4 in game units on a rig about 1.8 across: the same share.
    service, sid, _order, points, parents = rig_editor
    snapshot = service.capture_export_snapshot(sid)
    path, transform = changed_basis_glb(tmp_path, points, parents, altered_rest=1e-4)
    pending = prepare_import(snapshot, path)
    mesh, _state = compose_import(pending, (pending.target_part_ids[0],))
    expected = (transform @ np.array((0., 0., 0., 1.)))[:3]
    assert mesh.submeshes[0].vertices[0] == pytest.approx(expected, abs=.002)


def test_a_one_percent_offset_on_a_weighted_bone_is_still_a_different_rig(rig_editor, tmp_path):
    service, sid, _order, points, parents = rig_editor
    path, _transform = changed_basis_glb(tmp_path, points, parents, altered_rest=.01, altered_index=1)
    with pytest.raises(ValueError, match=r"matching bones are off; the worst, bone[01], by [0-9.]+ \(0\.[0-9]+% of the rig size\)"):
        prepare_import(service.capture_export_snapshot(sid), path)


def test_a_small_offset_on_a_bone_the_mesh_does_not_use_is_noted_not_refused(rig_editor, tmp_path):
    # A tester's GLB carried a face rig a game update had moved: B_Tongue_01 0.16% off.
    from cdmw.modding.mesh_glb_assets import skeleton_skin
    from cdmw.services.mesh_replacement_skinning import _target_bind_frame
    from cdmw.ui.new_item.model_import import load_model_import_source

    service, sid, _order, points, parents = rig_editor
    snapshot = service.capture_export_snapshot(sid)
    path, _transform = changed_basis_glb(tmp_path, points, parents, altered_rest=.005)
    prepare_import(snapshot, path)  # bone7 carries no weight in this mesh (joints 0 and 1 do)
    source = load_model_import_source(path)
    try:
        skin = source.scene.mesh.submeshes[0].interchange_skin
        used = {joint for row in source.scene.mesh.submeshes[0].bone_indices for joint in row}
        notes = []
        _target_bind_frame(skin, skeleton_skin(snapshot.mesh.interchange_skeleton), used, notes)
        assert len(notes) == 1 and "worst bone7" in notes[0] and "move no vertex" in notes[0]
        with pytest.raises(ValueError, match="Rest-joint positions"):
            _target_bind_frame(skin, skeleton_skin(snapshot.mesh.interchange_skeleton))  # every bone counts
    finally:
        source.cleanup()


def test_transfer_uses_a_foreign_rig_model_as_authored(rig_editor, tmp_path):
    from cdmw.domain.mesh.skin_policy import SkinningChoice
    from cdmw.services.mesh_skinning_preflight import preflight_imported_skin
    from cdmw.ui.new_item.model_import import load_model_import_source

    service, sid, _order, points, parents = rig_editor
    snapshot = service.capture_export_snapshot(sid)
    path, _transform = changed_basis_glb(tmp_path, points, parents, altered_rest=True)
    source = load_model_import_source(path)
    try:
        authored = list(source.scene.mesh.submeshes[0].vertices)
        skeleton = snapshot.mesh.interchange_skeleton
        with pytest.raises(ValueError, match="Rest-joint positions"):
            preflight_imported_skin(source.scene.mesh, snapshot.original_data, skeleton, snapshot.mesh.path)
        mapped, reports = preflight_imported_skin(source.scene.mesh, snapshot.original_data, skeleton,
                                                  snapshot.mesh.path, choices=(SkinningChoice(0, "transfer"),))
    finally:
        source.cleanup()
    part = mapped.submeshes[0]
    assert part.vertices == authored
    assert part.bone_weights and not part.interchange_skin
    assert "used as authored" in reports[0].summary() and "bone7" in reports[0].summary()
