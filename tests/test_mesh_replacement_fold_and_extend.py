"""Weights on bones the target PAC's palette lacks: move them to a parent, or add the bones."""

import pytest

from cdmw.domain.mesh.skin_policy import SkinningChoice
from cdmw.modding.mesh_parser import parse_pac
from cdmw.modding.pac_palette_extension import palette_layout
from cdmw.modding.scene_importer import import_scene_mesh_with_report
from cdmw.modding.skeleton_parser import Bone, Skeleton
from cdmw.services.mesh_replacement_import import commit_replacement, compose_import, prepare_import
from cdmw.services.mesh_replacement_output import prepare_replacement_output
from cdmw.services.mesh_service import MeshService
from cdmw.services.mesh_skinning_preflight import preflight_imported_skin
from tests.test_mesh_replacement_imported_skinning import source_glb
from tests.test_pac_cloth_guide_builder import PALETTE, guide_free_pac

TARGET = "character/model/armor/target.pac"


def rig(*, parent_of_bone8=3):
    """Ten bones; the target PAC's palette lists bone0 to bone7 only."""
    return Skeleton(bone_count=10, bones=[Bone(
        index=i, name=f"bone{i}", name_hash=PALETTE[i] if i < 8 else 0xaabbcd00 + i,
        parent_index=parent_of_bone8 if i == 8 else -1,
        # Positions are local: bone8 sits at x=8 in the rig whatever its parent.
        position=(float(i - (parent_of_bone8 if i == 8 and parent_of_bone8 >= 0 else 0)), 0., 0.))
        for i in range(10)])


@pytest.fixture
def editor():
    original = guide_free_pac(parts=2)
    mesh = parse_pac(original, TARGET)
    mesh._cdmw_original_data = original
    service = MeshService()
    sid = service.open_edit_session(mesh).session_id
    service._session(sid).skeleton = rig()
    yield service, sid
    service.close_edit_session(sid)


def first_row(data):
    part = parse_pac(data, TARGET).submeshes[0]
    return dict(zip(part.bone_indices[0], part.bone_weights[0]))


def test_a_bone_outside_the_palette_offers_fold_and_extend_but_not_keep(editor, tmp_path):
    service, sid = editor
    pending = prepare_import(service.capture_export_snapshot(sid),
                             source_glb(tmp_path, names=("bone3", "bone8"), children={"bone3": ("bone8",)}))
    skin = pending.skin
    assert not skin.option("preserve").available
    assert "bone8" in skin.option("preserve").reason
    assert skin.option("fold").available and skin.option("extend").available
    assert skin.default_policy == ""
    assert "bone8" in skin.summary
    assert pending.extend_bones == ("bone8",)
    # Nothing is extended until the user chooses to.
    assert pending.state.palette_extension is None


def test_fold_moves_the_weight_to_the_nearest_palette_parent(editor, tmp_path):
    service, sid = editor
    before = service.capture_export_snapshot(sid)
    pending = prepare_import(before, source_glb(tmp_path, names=("bone3", "bone8"), children={"bone3": ("bone8",)}))
    notes = []
    mesh, state = compose_import(pending, (pending.target_part_ids[0],), skin_policy="fold", skin_notes=notes)
    assert state.palette_extension is None
    assert mesh.submeshes[0].bone_indices == [(3,)] * 3
    assert mesh.submeshes[0].bone_weights == [pytest.approx((1.0,))] * 3
    assert any("bone8 to bone3" in note for note in notes)
    commit_replacement(service, before, mesh, state, label="Import with folded weights")
    output = prepare_replacement_output(service.capture_export_snapshot(sid)).data
    assert palette_layout(output)[3] == PALETTE
    assert first_row(output) == pytest.approx({3: 1.0}, abs=1 / 255)


def test_fold_climbs_the_imported_rig_for_a_bone_the_game_skeleton_lacks(editor, tmp_path):
    service, sid = editor
    pending = prepare_import(service.capture_export_snapshot(sid),
                             source_glb(tmp_path, names=("bone3", "hair_tip"), children={"bone3": ("hair_tip",)}))
    assert pending.skin.option("fold").available
    extend = pending.skin.option("extend")
    assert not extend.available and "game skeleton, so they cannot be added: hair_tip." in extend.reason
    mesh, _state = compose_import(pending, (pending.target_part_ids[0],), skin_policy="fold")
    assert mesh.submeshes[0].bone_indices == [(3,)] * 3


def test_fold_refuses_a_bone_with_no_parent_in_the_palette(tmp_path):
    original = guide_free_pac(parts=2)
    mesh = parse_pac(original, TARGET)
    mesh._cdmw_original_data = original
    service = MeshService()
    sid = service.open_edit_session(mesh).session_id
    service._session(sid).skeleton = rig(parent_of_bone8=-1)
    try:
        pending = prepare_import(service.capture_export_snapshot(sid), source_glb(tmp_path, names=("bone3", "bone8")))
        fold = pending.skin.option("fold")
        assert not fold.available and "bone8 has no parent bone" in fold.reason
        with pytest.raises(ValueError, match="no parent bone"):
            compose_import(pending, (pending.target_part_ids[0],), skin_policy="fold")
    finally:
        service.close_edit_session(sid)


def test_extend_keeps_the_weights_exactly_and_appends_the_bone(editor, tmp_path):
    service, sid = editor
    before = service.capture_export_snapshot(sid)
    pending = prepare_import(before, source_glb(tmp_path, names=("bone3", "bone8"), children={"bone3": ("bone8",)}))
    notes = []
    mesh, state = compose_import(pending, (pending.target_part_ids[0],), skin_policy="extend", skin_notes=notes)
    assert state.palette_extension is not None and state.palette_extension.appended_names == ("bone8",)
    assert any("Added bone8" in note and "Experimental" in note for note in notes)
    commit_replacement(service, before, mesh, state, label="Import with added bones")
    output = prepare_replacement_output(service.capture_export_snapshot(sid)).data
    assert palette_layout(output)[3] == PALETTE + (0xaabbcd08,)
    assert first_row(output) == pytest.approx({3: .25, 8: .75}, abs=1 / 255)


def test_a_second_extend_keeps_the_first_import_slots(editor, tmp_path):
    service, sid = editor
    first = tmp_path / "first"
    first.mkdir()
    before = service.capture_export_snapshot(sid)
    pending = prepare_import(before, source_glb(first, names=("bone3", "bone8"), children={"bone3": ("bone8",)}))
    mesh, state = compose_import(pending, (pending.target_part_ids[0],), skin_policy="extend")
    commit_replacement(service, before, mesh, state, label="First")
    second = tmp_path / "second"
    second.mkdir()
    before = service.capture_export_snapshot(sid)
    pending = prepare_import(before, source_glb(second, names=("bone2", "bone9")),
                             target_part_ids=(before.replacement_state.parts[1].part_id,))
    assert pending.extend_bones == ("bone9",)
    mesh, state = compose_import(pending, (pending.target_part_ids[0],), skin_policy="extend")
    assert state.palette_extension.appended_names == ("bone8", "bone9")
    commit_replacement(service, before, mesh, state, label="Second")
    output = prepare_replacement_output(service.capture_export_snapshot(sid)).data
    assert palette_layout(output)[3] == PALETTE + (0xaabbcd08, 0xaabbcd09)
    assert first_row(output) == pytest.approx({3: .25, 8: .75}, abs=1 / 255)


def test_every_bone_in_the_palette_needs_no_fold_or_extend(editor, tmp_path):
    service, sid = editor
    pending = prepare_import(service.capture_export_snapshot(sid), source_glb(tmp_path, names=("bone3", "bone2")))
    assert pending.skin.default_policy == "preserve"
    assert not pending.skin.option("fold").available
    assert not pending.skin.option("extend").available
    assert pending.extend_bones == ()


def test_new_item_preflight_folds_on_request_and_still_refuses_keep(tmp_path):
    skeleton = rig()
    target = guide_free_pac(parts=2)
    mesh = import_scene_mesh_with_report(
        source_glb(tmp_path, names=("bone3", "bone8"), children={"bone3": ("bone8",)}),
        preserve_skinning=True).mesh
    with pytest.raises(ValueError, match="Missing equipment palette bones: bone8"):
        preflight_imported_skin(mesh, target, skeleton, TARGET)
    mapped, reports = preflight_imported_skin(mesh, target, skeleton, TARGET, choices=(SkinningChoice(0, "fold"),))
    assert mapped.submeshes[0].bone_indices[0] == (3,)
    assert "bone8 to bone3" in reports[0].summary()
