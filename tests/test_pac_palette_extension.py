"""Counted palette relocation and complete authored output on owned four-LOD PACs."""

import copy
from dataclasses import replace
import struct

import pytest

from cdmw.modding.mesh_parser import parse_pac, _parse_par_sections
from cdmw.modding.pac_palette_extension import extend_pac_palette, validate_palette_extension, palette_layout
from cdmw.modding.skeleton_parser import Bone, Skeleton
from cdmw.modding.pac_cloth import pac_cloth_lods
from cdmw.modding.pac_cloth_guide_builder import create_pac_cloth_guides
from cdmw.modding.pac_cloth_guides import decode_pac_cloth_guides
from cdmw.domain.mesh.cloth_guides import PacClothGuideRule
from cdmw.services.mesh_service import MeshService
from cdmw.services.mesh_replacement_import import prepare_import, compose_import, commit_replacement
from cdmw.services.mesh_replacement_output import prepare_replacement_output
from cdmw.services.mesh_replacement_draft import save_replacement_state, load_replacement_state
from tests.test_pac_cloth_guide_builder import guide_free_pac, PALETTE
from tests.test_mesh_replacement_imported_skinning import source_glb


def rig():
    return Skeleton(bone_count=10, bones=[Bone(index=i, name=f"bone{i}",
        name_hash=PALETTE[i] if i < 8 else 0xaabbcd00 + i, position=(float(i), 0., 0.)) for i in range(10)])


@pytest.mark.parametrize("guides", [False, True])
@pytest.mark.parametrize("lods", [2, 3, 4])
def test_palette_append_preserves_all_geometry_guides_and_original_slots(guides, lods):
    original = guide_free_pac(lods=lods, parts=2, flags=0x2004)
    if guides:
        original = create_pac_cloth_guides(original, {0: PacClothGuideRule(0, .5, PALETTE)})
    output, contract = extend_pac_palette(original, rig(), ("bone8", "bone9"))
    assert palette_layout(output)[3] == PALETTE + (0xaabbcd08, 0xaabbcd09)
    for a, b in zip(_parse_par_sections(original)[1:], _parse_par_sections(output)[1:], strict=True):
        assert b["offset"] == a["offset"] + 8
        assert output[b["offset"]:b["offset"]+b["size"]] == original[a["offset"]:a["offset"]+a["size"]]
    assert decode_pac_cloth_guides(original) == decode_pac_cloth_guides(output)
    assert [len(level.submeshes) for level in pac_cloth_lods(output)] == [2] * lods
    validate_palette_extension(original, output, rig(), contract)
    changed = bytearray(output)
    struct.pack_into("<I", changed, palette_layout(output)[1] + 2, 0xaabbcd09)
    with pytest.raises(ValueError):
        validate_palette_extension(original, bytes(changed), rig(), contract)


@pytest.mark.parametrize("fault", ["unknown", "ambiguous name", "ambiguous hash", "duplicate", "trailer", "pointer", "rig"])
def test_palette_extension_refuses_unproven_layouts_and_identities(fault):
    original, skeleton, names = guide_free_pac(), rig(), ("bone8",)
    if fault == "unknown":
        names = ("foreign",)
    elif fault == "ambiguous name":
        skeleton.bones[9].name = "bone8"
    elif fault == "ambiguous hash":
        skeleton.bones[9].name_hash = skeleton.bones[8].name_hash
    elif fault == "duplicate":
        names = ("bone0",)
    elif fault == "trailer":
        original = guide_free_pac(extra=b"unknown")
    elif fault == "pointer":
        data = bytearray(original)
        struct.pack_into("<I", data, 85, 0)
        original = bytes(data)
    else:
        skeleton.parser_mode = "legacy_scan"
    with pytest.raises(ValueError):
        extend_pac_palette(original, skeleton, names)


def test_appended_slots_survive_replacement_apply_history_output_and_draft(tmp_path):
    original = guide_free_pac(parts=2)
    mesh = parse_pac(original, "character/model/armor/target.pac")
    mesh._cdmw_original_data = original
    service = MeshService()
    sid = service.open_edit_session(mesh).session_id
    service._session(sid).skeleton = rig()
    try:
        snapshot = service.capture_export_snapshot(sid)
        pending = prepare_import(snapshot, source_glb(tmp_path, names=("bone8", "bone9")),
                                 palette_extension_bones=("bone8", "bone9"))
        candidate, state = compose_import(pending, (pending.target_part_ids[0],))
        assert snapshot.original_data == original
        commit_replacement(service, snapshot, candidate, state, label="Owned palette experiment")
        result = prepare_replacement_output(service.capture_export_snapshot(sid)).data
        assert palette_layout(result)[3] == PALETTE + (0xaabbcd08, 0xaabbcd09)
        for level in pac_cloth_lods(result):
            for part in level.submeshes:
                assert all(index < 10 for row in part.bone_indices for index in row)
        first = parse_pac(result).submeshes[0]
        assert dict(zip(first.bone_indices[0], first.bone_weights[0])) == pytest.approx({8:.25,9:.75}, abs=1/255)
        service.undo(sid)
        assert service.capture_export_snapshot(sid).replacement_state is None
        service.redo(sid)
        assert service.capture_export_snapshot(sid).replacement_state.palette_extension == state.palette_extension
        generation = tmp_path / "generation"
        generation.mkdir()
        saved = save_replacement_state(state, tmp_path, generation)
        assert saved["version"] == 16
        assert load_replacement_state(saved, tmp_path) == state
        saved["palette_extension"]["appended_names"] = ["foreign"]
        with pytest.raises(ValueError):
            load_replacement_state(saved, tmp_path)
    finally:
        service.close_edit_session(sid)


def test_new_item_variant_keeps_equality_guard_unless_exact_contract_is_present():
    from cdmw.services.new_item_variants import validate_variant_rig
    from cdmw.modding.skeleton_parser import parse_pab
    from tests.test_new_item_variant_rig import _snapshot_files
    from tests.test_release_inspired_improvements import _pab_payload
    model = "character/model/1_pc/2_phw/armor/9_upperbody/test.pac"
    pab_path = "character/model/1_pc/2_phw/phw_01.pab"
    skeleton_data = bytearray(_pab_payload()[:22])
    struct.pack_into("<H", skeleton_data, 20, 10)
    for index in range(10):
        skeleton_data.extend(_pab_payload(f"bone{index}", 0xaabbcd00+index)[22:])
    skeleton = parse_pab(bytes(skeleton_data),pab_path)
    original = guide_free_pac(parts=2)
    output, contract = extend_pac_palette(original,skeleton,("bone8","bone9"))
    snapshot = _snapshot_files({model:original,pab_path:bytes(skeleton_data)})
    with pytest.raises(ValueError,match="palette differs"):
        validate_variant_rig(snapshot,model,output)
    assert validate_variant_rig(snapshot,model,output,palette_extension=contract) == pab_path
    with pytest.raises(ValueError):
        validate_variant_rig(snapshot,model,original,palette_extension=contract)


def test_explicit_body_donor_keeps_bones_in_the_approved_extended_palette():
    from cdmw.domain.mesh.skin_policy import SkinningChoice
    from cdmw.modding.mesh_parser import ParsedMesh, SubMesh
    from cdmw.modding.mesh_skinning import pack_pac_skin_weights
    from cdmw.modding.skeleton_parser import parse_pab
    from cdmw.services.mesh_skinning_preflight import prepare_new_item_skin
    from tests.test_new_item_variant_rig import _snapshot_files
    from tests.test_release_inspired_improvements import _pab_payload

    model = "character/model/1_pc/2_phw/armor/9_upperbody/test.pac"
    pab_path = "character/model/1_pc/2_phw/phw_01.pab"
    body_path = "character/model/1_pc/2_phw/nude/cd_phw_00_nude_00_0001.pac"
    skeleton_data = bytearray(_pab_payload()[:22])
    struct.pack_into("<H", skeleton_data, 20, 10)
    for index in range(10):
        skeleton_data.extend(_pab_payload(f"bone{index}", 0xaabbcd00 + index)[22:])
    skeleton = parse_pab(bytes(skeleton_data), pab_path)
    original = guide_free_pac(parts=2)
    body, _contract = extend_pac_palette(original, skeleton, ("bone8",))
    data = bytearray(body)
    for level in pac_cloth_lods(body):
        for part in level.submeshes:
            for offset in part.source_vertex_offsets:
                record = bytearray(data[offset:offset + 40])
                pack_pac_skin_weights(record, (8,), (1.,), context="extended donor fixture")
                data[offset:offset + 40] = record
    donor = parse_pac(bytes(data)).submeshes[0]
    source = ParsedMesh(submeshes=[SubMesh(name="garment", vertices=list(donor.vertices),
        faces=list(donor.faces), uvs=list(donor.uvs))])
    snapshot = _snapshot_files({model: original, pab_path: bytes(skeleton_data), body_path: bytes(data)})
    mapped, reports = prepare_new_item_skin(source, snapshot, model,
        choices=(SkinningChoice(0, "body_transfer"),), palette_extension_bones=("bone8",))
    assert mapped.submeshes[0].bone_indices == [(8,)] * len(donor.vertices)
    assert reports[0].donor_path == body_path
    assert mapped.interchange_palette_extension.appended_names == ("bone8",)


def test_import_build_stage_derives_palette_without_replacing_source_witness(tmp_path,monkeypatch):
    from types import SimpleNamespace
    from cdmw.core.archive_mesh_import_build_stages import load_mesh_import_sources
    from cdmw.core import archive_mesh_import_preview as public
    from cdmw.modding.scene_import_result_ops import SceneImportResult
    from cdmw.modding.mesh_parser import ParsedMesh
    from tests.test_release_inspired_improvements import _entry
    original = guide_free_pac(parts=2)
    output, contract = extend_pac_palette(original,rig(),("bone8","bone9"))
    baseline = SimpleNamespace(data=original,message="owned source")
    monkeypatch.setattr(public,"read_archive_entry_baseline_data",lambda *_a,**_k:baseline)
    state = SimpleNamespace(entry=_entry("target.pac"),obj_path=tmp_path/"source.glb",stop_event=None,
        scene_import_result=SceneImportResult(mesh=ParsedMesh()),texture_entries_by_basename=None,
        palette_extension=contract,palette_skeleton=rig())
    load_mesh_import_sources(state)
    assert state.original_baseline.data == original
    assert state.original_data == output
    state.palette_skeleton.bones[0].position = (9.,9.,9.)
    with pytest.raises(ValueError,match="no longer matches"):
        load_mesh_import_sources(state)


@pytest.mark.parametrize("editor_roundtrip", [False, True])
def test_new_item_placement_keeps_the_palette_contract_through_mesh_copies(tmp_path, monkeypatch, editor_roundtrip):
    from types import SimpleNamespace
    from cdmw.services.mesh_skinning_preflight import preflight_imported_skin
    from cdmw.ui.new_item.model_import import ModelPlacement, build_placed_import, load_model_import_source
    from tests.test_release_inspired_improvements import _entry

    original = guide_free_pac(parts=2)
    source = load_model_import_source(source_glb(tmp_path, names=("bone8", "bone9")))
    try:
        mapped, reports = preflight_imported_skin(source.scene.mesh, original, rig(), "target.pac",
                                                  palette_extension_bones=("bone8", "bone9"))
        contract = mapped.interchange_palette_extension
        if editor_roundtrip:
            service = MeshService()
            sid = service.open_edit_session(mapped).session_id
            try:
                mapped = service.working_mesh(sid, clone=True)
                assert mapped.interchange_palette_extension == contract
                assert mapped.interchange_skeleton == rig()
            finally:
                service.close_edit_session(sid)
        source.scene = replace(source.scene, mesh=mapped)
        source.preview_mesh = mapped
        source.skinning_reports, source.skinning_target = reports, "target.pac"
        source.set_bake(ModelPlacement(offset=(.2, .3, .4), rotation=(15., 20., 30.)))
        captured = {}

        def build(*args, **kwargs):
            captured.update(kwargs)
            return SimpleNamespace(summary_lines=[])

        monkeypatch.setattr("cdmw.services.preview_workflow_service.build_mesh_import_preview", build)
        build_placed_import(_entry("target.pac"), source, ModelPlacement(offset=(1., 0., 0.)))
        assert captured["palette_extension"] == contract
        derived, rebuilt_contract = extend_pac_palette(original, captured["palette_skeleton"], contract.appended_names)
        assert rebuilt_contract == contract
        assert palette_layout(derived)[3] == contract.original_hashes + contract.appended_hashes
        built_mesh = captured["scene_import_result"].mesh
        assert built_mesh is not mapped
        assert built_mesh.submeshes[0].bone_indices == mapped.submeshes[0].bone_indices
        assert {joint for row in built_mesh.submeshes[0].bone_indices for joint in row} == {8, 9}
    finally:
        source.cleanup()
