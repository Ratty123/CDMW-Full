"""Meshes weighted to appended PAB bones: edited rig, palette, package and composition, on owned fixtures."""

from dataclasses import replace
import hashlib
import time
from types import SimpleNamespace
from uuid import uuid4

import pytest

from cdmw.domain.archives.overlay_merge import OverlayConflict, merge_overlay_files
from cdmw.modding.pac_palette_extension import extend_pac_palette, palette_layout
from cdmw.modding.skeleton_writer import pab_bone_name_hash, read_pab_document, write_pab_document
from cdmw.services.pab_skeleton_edit_service import (
    PabAppendEdit, PabEditJsonError, SkeletonEditRecipe, apply_pab_edits, dumps_pab_edit_json, read_pab_edit_json,
)
from tests.test_new_item_model_apply import studio  # noqa: F401 - pytest fixture
from tests.test_pab_skeleton_writer import IDENTITY, pab, translated

PAB_PATH = "character/model/1_pc/1_phm/phm_01.pab"
CAPE = (PabAppendEdit("Bip01 Spine", "Cape_00", position=(0., -.2, 0.)),
        PabAppendEdit("Cape_00", "Cape_01", position=(0., -.3, 0.)))
TAIL = (PabAppendEdit("Bip01", "Tail_00", position=(-.1, 0., 0.)),)


def merged(after, current, before=None):
    before = pab() if before is None else before
    return merge_overlay_files({PAB_PATH: before}, {PAB_PATH: after}, {PAB_PATH: current})[PAB_PATH]


def added(data):
    document = read_pab_document(data)
    return {bone.name: (document.bones[bone.parent_index].name, bone.bind_matrix, bone.local_bind_matrix)
            for bone in document.bones[3:]}


def test_two_edits_compose_their_added_bones_in_either_order():
    cape, tail = (apply_pab_edits(pab(), edits).data for edits in (CAPE, TAIL))
    first, second = merged(tail, cape), merged(cape, tail)
    for result in (first, second):
        document = read_pab_document(result)
        assert [bone.name for bone in document.bones[:3]] == ["Bip01", "Bip01 Spine", "Bip01 Head"]
        assert document.bones[:3] == read_pab_document(pab()).bones[:3]
        assert added(result) == {**added(cape), **added(tail)}
        assert write_pab_document(document) == result
    assert [bone.name for bone in read_pab_document(first).bones[3:]] == ["Cape_00", "Cape_01", "Tail_00"]
    # The same bones from two items are kept once.
    assert merged(cape, cape) == cape


@pytest.mark.parametrize("fault", ["moved", "shipped"])
def test_conflicting_or_shipped_bone_edits_refuse_composition(fault):
    cape = apply_pab_edits(pab(), CAPE).data
    if fault == "moved":
        other = apply_pab_edits(pab(), (replace(CAPE[0], position=(0., -.5, 0.)),)).data
        match = "different definitions"
    else:
        document = read_pab_document(pab())
        bones = list(document.bones)
        bones[2] = replace(bones[2], position=(4., 0., 0.))
        other = write_pab_document(replace(document, bones=tuple(bones)))
        match = "changes the source skeleton"
    with pytest.raises(OverlayConflict, match=match):
        merged(other, cape)


def test_recipe_round_trips_and_checks_its_source():
    text = dumps_pab_edit_json(pab(), PAB_PATH).replace('"add_bones": []', '"add_bones": [{"parent": "Bip01 Spine", '
                                                         '"name": "Cape_00", "position": [0, -0.2, 0]}]')
    recipe = read_pab_edit_json(pab(), text, virtual_path=PAB_PATH)
    assert (recipe.path, recipe.bone_names) == (PAB_PATH, ("Cape_00",))
    assert SkeletonEditRecipe.from_dict(recipe.to_dict()) == recipe
    with pytest.raises(PabEditJsonError, match="different version"):
        read_pab_edit_json(apply_pab_edits(pab(), TAIL).data, text)
    with pytest.raises(PabEditJsonError):
        SkeletonEditRecipe.from_dict({**recipe.to_dict(), "add_bones": []})


# ---------------------------------------------------------------- New Item rig

def palette_rig():
    """Eight root bones whose hashes are the owned PAC's palette, bone i bound at (i, 0, 0)."""
    from tests.test_pac_cloth_guide_builder import PALETTE
    bones = tuple((f"bone{i}", -1, translated(IDENTITY, float(i), 0.), translated(IDENTITY, -float(i), 0.),
                   translated(IDENTITY, float(i), 0.), translated(IDENTITY, -float(i), 0.),
                   (0., 0., 0., 1.), (float(i), 0., 0.)) for i in range(len(PALETTE)))
    return pab(0x17, bones=bones, hashes=PALETTE, secondary=(-1,) * len(PALETTE), core=(1,) * len(PALETTE),
               sets=((), (), ()))


# Bound at (7, 0, 0), where the authored GLB's inverse binds put a joint not named boneN.
CAPE_RIG = SkeletonEditRecipe(PAB_PATH, (PabAppendEdit("bone0", "Cape_00", position=(7., 0., 0.)),))
PAC_PATH = "character/model/1_pc/1_phm/armor/test_cape.pac"


def fake_snapshot(monkeypatch, pac):
    from cdmw.core import skeleton_resolver
    payloads = {PAC_PATH: pac, PAB_PATH: palette_rig()}
    monkeypatch.setattr(skeleton_resolver, "resolve_skeleton_for_model",
                        lambda entry, **_kwargs: (SimpleNamespace(path=PAB_PATH), None))
    return SimpleNamespace(archive_index_maps=lambda: ({}, {}), payload=payloads.__getitem__,
                           entry=lambda path: SimpleNamespace(path=path))


def test_new_item_weights_an_added_bone_through_the_edited_rig(monkeypatch, tmp_path):
    from cdmw.modding.mesh_parser import parse_pac
    from cdmw.modding.static_mesh_build import build_static_mesh_replacement
    from cdmw.modding.static_mesh_types import StaticSubmeshMapping
    from cdmw.services.mesh_replacement_output import manual_replacement_options
    from cdmw.services.mesh_skinning_preflight import prepare_new_item_skin
    from cdmw.ui.new_item.model_import import load_model_import_source
    from tests.test_mesh_replacement_imported_skinning import source_glb
    from tests.test_pac_cloth_guide_builder import PALETTE, guide_free_pac

    pac = guide_free_pac(parts=2)
    snapshot = fake_snapshot(monkeypatch, pac)
    source = load_model_import_source(source_glb(tmp_path, names=("bone2", "Cape_00")))
    try:
        with pytest.raises(ValueError, match="Cape_00"):
            prepare_new_item_skin(source.scene.mesh, snapshot, PAC_PATH)
        mapped, reports = prepare_new_item_skin(source.scene.mesh, snapshot, PAC_PATH, skeleton_edit=CAPE_RIG)
    finally:
        source.cleanup()
    extension = mapped.interchange_palette_extension
    assert extension.appended_names == ("Cape_00",)
    assert extension.appended_hashes == (pab_bone_name_hash("Cape_00"),)
    assert reports[0].required_bones == ("Cape_00", "bone2")
    # The reports name the edited rig, not the shipped one.
    assert reports[0].skeleton_sha256 != hashlib.sha256(palette_rig()).hexdigest()
    target, _ = extend_pac_palette(pac, mapped.interchange_skeleton, extension.appended_names)
    mesh = parse_pac(target, PAC_PATH)
    mappings = [StaticSubmeshMapping(i, part.name, [0] if i == 0 else [], i) for i, part in enumerate(mesh.submeshes)]
    output, report = build_static_mesh_replacement(target, mesh, mapped, manual_replacement_options(mappings))
    assert not report.errors
    assert palette_layout(output)[3] == PALETTE + (pab_bone_name_hash("Cape_00"),)
    first = parse_pac(output, PAC_PATH).submeshes[0]
    # Slot 8 is the appended Cape_00; slot 2 is bone2.
    assert dict(zip(first.bone_indices[0], first.bone_weights[0])) == pytest.approx({2: .25, 8: .75}, abs=1/255)


def test_skeleton_edit_for_another_rig_is_refused(monkeypatch):
    from cdmw.services.mesh_skinning_preflight import template_skeleton
    from tests.test_pac_cloth_guide_builder import guide_free_pac

    snapshot = fake_snapshot(monkeypatch, guide_free_pac())
    with pytest.raises(ValueError, match="this template binds to"):
        template_skeleton(snapshot, PAC_PATH, replace(CAPE_RIG, path="character/model/1_pc/2_phw/phw_01.pab"))
    with pytest.raises(ValueError, match="cannot be applied"):
        template_skeleton(snapshot, PAC_PATH, replace(CAPE_RIG, add_bones=(PabAppendEdit("missing", "Cape_00"),)))


PHW_RIG = SkeletonEditRecipe("character/model/1_pc/2_phw/phw_01.pab", CAPE_RIG.add_bones)


def test_each_rig_takes_its_own_skeleton_edit(monkeypatch):
    from cdmw.services.mesh_skinning_preflight import template_skeleton
    from tests.test_pac_cloth_guide_builder import guide_free_pac

    snapshot = fake_snapshot(monkeypatch, guide_free_pac())
    skeleton, _data, path, edit = template_skeleton(snapshot, PAC_PATH, skeleton_edits=(PHW_RIG, CAPE_RIG))
    assert (path, edit) == (PAB_PATH, CAPE_RIG) and skeleton.bones[-1].name == "Cape_00"
    # An edit for another rig (the other variant's) is left for that variant.
    skeleton, data, _path, edit = template_skeleton(snapshot, PAC_PATH, skeleton_edits=(PHW_RIG,))
    assert edit is None and data == palette_rig() and skeleton.bones[-1].name == "bone7"


@pytest.mark.parametrize("edits, advice", [
    ((), "Cape_00: not in character/model/1_pc/1_phm/phm_01.pab. To weight to new bones, add them with Add bones"),
    ((PHW_RIG,), "Cape_00: added to character/model/1_pc/2_phw/phw_01.pab, but this model binds to "
                 "character/model/1_pc/1_phm/phm_01.pab"),
])
def test_missing_bones_say_how_to_add_them(monkeypatch, tmp_path, edits, advice):
    from cdmw.services.mesh_skinning_preflight import prepare_new_item_skin
    from cdmw.ui.new_item.model_import import load_model_import_source
    from tests.test_mesh_replacement_imported_skinning import source_glb
    from tests.test_pac_cloth_guide_builder import guide_free_pac

    snapshot = fake_snapshot(monkeypatch, guide_free_pac(parts=2))
    source = load_model_import_source(source_glb(tmp_path, names=("bone2", "Cape_00")))
    try:
        with pytest.raises(ValueError) as caught:
            prepare_new_item_skin(source.scene.mesh, snapshot, PAC_PATH, skeleton_edits=edits)
    finally:
        source.cleanup()
    assert caught.value.missing_bones == ("Cape_00",)
    assert str(caught.value).startswith("Missing equipment palette bones: Cape_00.")
    assert advice in str(caught.value)


def test_rig_glb_carries_the_added_joint_at_its_bind(monkeypatch, tmp_path):
    import json
    import struct
    from cdmw.services.mesh_skinning_preflight import export_template_rig_glb
    from tests.test_pac_cloth_guide_builder import guide_free_pac

    snapshot = fake_snapshot(monkeypatch, guide_free_pac())
    paths = export_template_rig_glb(snapshot, PAC_PATH, tmp_path, skeleton_edit=CAPE_RIG)
    data = open(paths[0], "rb").read()
    length, = struct.unpack_from("<I", data, 12)
    document = json.loads(data[20:20 + length])
    joints = {document["nodes"][index]["name"] for skin in document["skins"] for index in skin["joints"]}
    assert {"bone0", "bone7", "Cape_00"} <= joints
    assert paths[0].endswith("test_cape_edited_rig.glb")


# ---------------------------------------------------------------- package and Send

def rig_game(monkeypatch, path):
    import tests.test_new_item_provenance as provenance
    from tests.test_independent_items import imported_game
    original = provenance.current_files
    monkeypatch.setattr(provenance, "current_files", lambda: {**original(), PAB_PATH: pab()})
    return imported_game(path)


def rig_package(monkeypatch, path, edits, name):
    from cdmw.domain.new_item.spec import ModelSource
    from cdmw.services.independent_item_package import from_plan
    from cdmw.services.new_item_planning import ModelFiles
    from tests.test_archive_overlay_manager import shop_spec
    from tests.test_new_item_service import PAC_XML, imported_pac

    service, snapshot = rig_game(monkeypatch, path)
    model = ModelFiles(imported_pac(100), {PAC_XML: snapshot.payload(PAC_XML)},
                       skeleton_edit=SkeletonEditRecipe(PAB_PATH, edits))
    plan = service.plan(replace(shop_spec(name), model_source=ModelSource.IMPORTED), snapshot,
                        model=model, capture_independent=True)
    return plan, from_plan(plan, uuid4().hex)


def test_item_packages_carry_their_bones_and_send_composes_one_rig(monkeypatch, tmp_path):
    from cdmw.services.independent_item_package import package_bytes, read_package, unpack_recipe, write_package
    from cdmw.services.virtual_loader_composition import compose_packages

    plan, cape = rig_package(monkeypatch, tmp_path / "a", CAPE, "CapeItem")
    assert plan.manifest["skeleton_edits"] == [{"path": PAB_PATH, "bones": ["Cape_00", "Cape_01"]}]
    patched = {request.entry.path.lower(): request.payload_data for request in plan.patches}
    assert added(patched[PAB_PATH]) == added(apply_pab_edits(pab(), CAPE).data)
    assert any("shared by every character" in warning for warning in plan.warnings)
    _plan, tail = rig_package(monkeypatch, tmp_path / "b", TAIL, "TailItem")
    reread = read_package(package_bytes(cape))
    _spec, primary, variants, _icon = unpack_recipe(reread)
    # The static-layout fixture plans the imported model as its primary variant.
    assert [model.skeleton_edit for model in (primary, *variants.values()) if model is not None] == [
        SkeletonEditRecipe(PAB_PATH, CAPE)]

    rig_game(monkeypatch, tmp_path / "recipient")
    root = tmp_path / "recipient/game"
    sources = []
    for package in (cape, tail):
        target = tmp_path / f"{package.identity}.cditem"
        write_package(package, target)
        sources.append(target)
    _resolved, files, _flags, _pathc = compose_packages(sources, (), root)
    assert set(added(files[PAB_PATH])) == {"Cape_00", "Cape_01", "Tail_00"}

    clash = tmp_path / "clash.cditem"
    write_package(rig_package(monkeypatch, tmp_path / "c",
                              (replace(CAPE[0], position=(0., -.9, 0.)),), "ClashItem")[1], clash)
    with pytest.raises(Exception, match="different definitions"):
        compose_packages((sources[0], clash), (), root)


# ---------------------------------------------------------------- studio wiring

def test_add_bones_button_edits_the_variant_rig_and_the_next_import_binds_to_it(studio, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QDialog
    from cdmw.modding.skeleton_parser import parse_pab
    from cdmw.ui.archive_browser import pab_bone_editor_dialog
    from tests.test_mesh_replacement_imported_skinning import source_glb
    from tests.test_new_item_model_apply import _finish

    app, tab = studio
    controller, panel = tab.controller, tab.model_panel
    monkeypatch.setattr("cdmw.services.mesh_skinning_preflight.template_skeleton",
                        lambda _snapshot, _path, edit=None, **_kwargs: (parse_pab(pab()), pab(), PAB_PATH, None))
    opened, answers = [], []

    class Dialog:
        """Stands in for the Add Bones dialog: records how it was opened, answers in turn."""

        def __init__(self, data, path, parent, **kwargs):
            opened.append((data, path, kwargs))

        def exec(self):
            self._answer = answers.pop(0)
            return QDialog.DialogCode.Accepted if self._answer is not None else QDialog.DialogCode.Rejected

        def edits(self):
            return self._answer

        def deleteLater(self):
            pass

    monkeypatch.setattr(pab_bone_editor_dialog, "PabBoneEditorDialog", Dialog)

    def settle():
        """Wait until idle across an event pass: the dialog opens, and weighting again
        starts, from queued events after the reading task ends."""
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            app.processEvents()
            if not controller.busy:
                app.processEvents()
                if not controller.busy:
                    return
            time.sleep(.005)
        raise AssertionError(f"still busy with {controller._lane}")

    def add_bones(answer):
        answers.append(answer)
        panel.add_bones_button.click()
        settle()

    cape = (PabAppendEdit("Bip01 Spine", "Cape_00"),)
    add_bones(cape)
    data, path, options = opened[-1]
    assert (data, path, options["initial_edits"]) == (pab(), PAB_PATH, ())
    assert options["accept_text"] == "Use These Bones"
    first, = controller.skeleton_edits
    assert first == SkeletonEditRecipe(PAB_PATH, cape)
    assert "phm_01.pab + 1 added bone(s)" in panel.rig_summary.text()
    assert "Cape_00" in panel.rig_summary.toolTip() and not panel.clear_skeleton_edit_button.isHidden()

    calls = []
    def prepare(mesh, _snapshot, _path, *, choices=(), stop_event=None, skeleton_edits=(), **_kwargs):
        calls.append(skeleton_edits)
        mesh.interchange_skeleton_edit = skeleton_edits[0] if skeleton_edits else None
        return mesh, ()
    monkeypatch.setattr("cdmw.services.mesh_skinning_preflight.prepare_new_item_skin", prepare)
    assert controller.start_model_import(source_glb(tmp_path))
    settle()
    assert calls == [(first,)] and controller.model_import.skeleton_edit is first

    # Reopening starts from the bones added before; changing them weights the rigged import again.
    add_bones((PabAppendEdit("Bip01 Spine", "Cape_99"),))
    assert opened[-1][2]["initial_edits"] == cape
    second, = controller.skeleton_edits
    assert second.bone_names == ("Cape_99",)
    assert calls[-1] == (second,) and controller.model_import.skeleton_edit is second

    # Cancel keeps the edit; accepting no bones removes it.
    add_bones(None)
    assert controller.skeleton_edits == (second,)
    add_bones(())
    assert controller.skeleton_edits == () and panel.rig_summary.text() == "Template skeleton"
    assert calls[-1] == () and controller.model_import.skeleton_edit is None

    add_bones(cape)
    panel.clear_skeleton_edit_button.click()
    settle()
    assert controller.skeleton_edits == () and panel.clear_skeleton_edit_button.isHidden()


def test_add_bones_dialog_opens_a_draft_saved_with_a_byte_order_mark(studio, tmp_path, monkeypatch):
    from cdmw.ui.archive_browser import pab_bone_editor_dialog
    from cdmw.ui.archive_browser.pab_bone_editor_dialog import PabBoneEditorDialog

    draft = tmp_path / "phm_01.skeleton-edit.json"
    draft.write_text(dumps_pab_edit_json(pab(), PAB_PATH, add_bones=CAPE), encoding="utf-8-sig")
    monkeypatch.setattr(pab_bone_editor_dialog.QFileDialog, "getOpenFileName",
                        staticmethod(lambda *_args, **_kwargs: (str(draft), "")))
    def refuse(_parent, _title, text, *_args):
        raise AssertionError(text)
    monkeypatch.setattr(pab_bone_editor_dialog.QMessageBox, "warning", staticmethod(refuse))
    dialog = PabBoneEditorDialog(pab(), PAB_PATH, accept_text="Use These Bones", accept_tooltip="")
    try:
        dialog._open_draft()
        assert dialog.edits() == CAPE
        assert dialog.save_mod_button.text() == "Use These Bones"
    finally:
        dialog.deleteLater()


# ---------------------------------------------------------------- plan and package rig checks

PHW_MODEL = "character/model/1_pc/2_phw/armor/9_upperbody/test.pac"
PHW_PAB = "character/model/1_pc/2_phw/phw_01.pab"


def extended_on_edited_rig():
    """A skinned template, the shipped rig, and the template's palette extended with Cape_00."""
    from cdmw.modding.skeleton_parser import parse_pab
    from tests.test_new_item_variant_rig import _snapshot_files
    from tests.test_pac_cloth_guide_builder import guide_free_pac

    recipe = SkeletonEditRecipe(PHW_PAB, CAPE_RIG.add_bones)
    original = guide_free_pac(parts=2)
    edited = recipe.apply(palette_rig()).data
    output, contract = extend_pac_palette(original, parse_pab(edited, PHW_PAB), ("Cape_00",))
    return recipe, edited, output, contract, _snapshot_files({PHW_MODEL: original, PHW_PAB: palette_rig()})


def test_plan_and_package_checks_bind_the_model_to_the_rig_the_item_ships():
    from cdmw.modding.skeleton_writer import merge_appended_bones
    from cdmw.services.new_item_variants import validate_variant_rig

    _recipe, edited, output, contract, snapshot = extended_on_edited_rig()
    # The shipped rig cannot resolve Cape_00, with or without the import's contract.
    with pytest.raises(ValueError):
        validate_variant_rig(snapshot, PHW_MODEL, output, palette_extension=contract)
    with pytest.raises(ValueError, match="palette differs"):
        validate_variant_rig(snapshot, PHW_MODEL, output)
    # Plan time: the contract is checked against the rig the import was weighted to.
    assert validate_variant_rig(snapshot, PHW_MODEL, output, palette_extension=contract,
                                rigs={PHW_PAB: edited}) == PHW_PAB
    # Package time: the planned rig may also carry other models' bones.
    other = apply_pab_edits(palette_rig(), (PabAppendEdit("bone1", "Tail_00"),)).data
    planned = merge_appended_bones(palette_rig(), other, edited)
    assert validate_variant_rig(snapshot, PHW_MODEL, output, rigs={PHW_PAB: planned}) == PHW_PAB
    # A rig without the bone the palette adds still refuses.
    with pytest.raises(ValueError):
        validate_variant_rig(snapshot, PHW_MODEL, output, rigs={PHW_PAB: other})


def test_variant_preparation_checks_against_the_models_edited_rig(monkeypatch):
    from cdmw.services import new_item_variants
    from cdmw.services.new_item_planning import ModelFiles
    from tests.test_new_item_armour_import import _body_transfer_request

    snapshot, appearance, result, _scene, _body = _body_transfer_request()
    seen = {}
    monkeypatch.setattr(new_item_variants, "validate_variant_rig",
                        lambda *_args, rigs=None, **_kwargs: seen.setdefault("rigs", rigs))
    recipe = SimpleNamespace(path="character/model/1_pc/1_phm/phm_01.pab",
                             apply=lambda data: SimpleNamespace(data=b"edited " + data[:4]))
    model = ModelFiles(result.rebuilt_data, material_route="builder", skeleton_edit=recipe)
    spec = SimpleNamespace(template_key=1, variants=(appearance,))
    new_item_variants.prepare_variant_models(spec, snapshot, {appearance.identity: model}, {})
    rig = snapshot.payload(recipe.path)
    assert seen["rigs"] == {recipe.path: b"edited " + rig[:4]}


def test_only_kept_nonzero_weights_bring_an_added_bone_into_the_palette():
    from cdmw.domain.mesh.skin_policy import SkinningChoice
    from cdmw.services.mesh_skinning_preflight import used_added_bones

    skin = {"nodes": [{"name": "bone0"}, {"name": "Cape_00"}, {"name": "Cape_01"}], "joints": [0, 1, 2]}
    part = SimpleNamespace(interchange_skin=skin, bone_indices=[(0, 1, 2)], bone_weights=[(.5, .5, 0.)])
    mesh = SimpleNamespace(submeshes=[part])
    recipe = SkeletonEditRecipe(PAB_PATH, CAPE)
    # Cape_01 is a zero-weight padding influence.
    assert used_added_bones(mesh, recipe) == ("Cape_00",)
    assert used_added_bones(mesh, recipe, (SkinningChoice(0, "transfer"),)) == ()


@pytest.mark.parametrize("path", ["Character/Model/1_pc/1_phm/phm_01.pab", r"character\model\1_pc\1_phm\phm_01.pab",
                                  "character/model/1_pc/1_phm/phm_01.pac"])
def test_packages_refuse_a_non_canonical_skeleton_edit_path(path):
    from cdmw.domain.new_item.independent import IndependentItemError
    from cdmw.services.independent_item_codec import encode
    from cdmw.services.independent_item_package import _prepared_spec, _recipe_values
    from tests.test_new_item_provenance import spec

    def package(skeleton_path):
        raw = {"pac": "a", "side_files": {}, "material_route": "", "skeleton_edit": {
            "path": skeleton_path, "add_bones": SkeletonEditRecipe(PAB_PATH, CAPE).to_dict()["add_bones"]}}
        return SimpleNamespace(recipe={"spec": encode(_prepared_spec(spec("Rig"))), "model": raw, "variants": [],
                                       "icon": None}, blobs={"a": b""})

    assert _recipe_values(package(PAB_PATH))[1].skeleton_edit == SkeletonEditRecipe(PAB_PATH, CAPE)
    with pytest.raises(IndependentItemError, match="resource path|skeleton edit"):
        _recipe_values(package(path))


# ---------------------------------------------------------------- release review findings

def dialog_on(rig=None, **options):
    from cdmw.ui.archive_browser.pab_bone_editor_dialog import PabBoneEditorDialog
    return PabBoneEditorDialog(pab() if rig is None else rig, PAB_PATH, **options)


def test_default_bone_names_start_with_the_item_name(studio):
    named, plain = dialog_on(name_stem="Ice Cape!"), dialog_on()
    try:
        for dialog in (named, plain):
            dialog._selected = "Bip01 Spine"
            dialog._add_child()
        assert named.edits()[-1].name == "Ice_Cape_NewBone_00"
        assert named._default_name("Cape") == "Ice_Cape_Cape"
        assert plain.edits()[-1].name == "NewBone_00" and plain._default_name("Cape") == "Cape"
    finally:
        named.deleteLater()
        plain.deleteLater()


def test_a_refused_rename_moves_no_children(studio):
    dialog = dialog_on(initial_edits=(PabAppendEdit("Bip01", "NewBone_00"), PabAppendEdit("Bip01 Head", "Hat_00"),
                                      PabAppendEdit("NewBone_00", "Tip_00")))
    try:
        before = dialog.edits()
        dialog._selected = "NewBone_00"
        dialog._load_form()
        for taken in ("Bip01 Head", "Hat_00", "", "Café"):
            dialog.name_edit.setText(taken)
            dialog._rename_selected()
            assert dialog.edits() == before and dialog.name_edit.text() == "NewBone_00"
        assert dialog.status_label.text()
        dialog.name_edit.setText("Collar_00")
        dialog._rename_selected()
        assert [(edit.parent, edit.name) for edit in dialog.edits()] == [
            ("Bip01", "Collar_00"), ("Bip01 Head", "Hat_00"), ("Collar_00", "Tip_00")]
    finally:
        dialog.deleteLater()


def test_reopened_bones_come_back_bit_for_bit(studio):
    from cdmw.services.pab_skeleton_edit_service import euler_degrees_to_quaternion
    turned = PabAppendEdit("Bip01 Spine", "Cape_00", position=(0.012345678, -0.2, 0.0301),
                           rotation=euler_degrees_to_quaternion(30.123456, -45.0, 120.0), scale=(1.0, 0.98765, 1.0),
                           core_flag=1)
    plain = PabAppendEdit("Cape_00", "Cape_01", position=(0.0, -0.3, 0.0))
    dialog = dialog_on(initial_edits=(turned, plain))
    try:
        assert dialog.edits() == (turned, plain)
        # Changing one vector of one bone leaves its other vectors and the other bone exact.
        dialog._selected = "Cape_01"
        dialog._load_form()
        dialog.scale_boxes[0].setValue(1.5)
        assert dialog.edits()[0] == turned
        assert dialog.edits()[1] == replace(plain, scale=(1.5, 1.0, 1.0))
    finally:
        dialog.deleteLater()


def test_enter_in_a_field_does_not_accept_the_dialog(studio):
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    app, _tab = studio
    dialog = dialog_on(initial_edits=CAPE, accept_text="Use These Bones")
    accepted = []
    dialog.accepted.connect(lambda: accepted.append(True))
    try:
        dialog.show()
        app.processEvents()
        for field in (dialog.name_edit, dialog.position_boxes[0]):
            QTest.keyClick(field, Qt.Key_Return)
            app.processEvents()
        assert not accepted and dialog.isVisible()
    finally:
        dialog.close()
        dialog.deleteLater()


def test_an_unused_skeleton_edit_leaves_the_palette_contract_on_the_shipped_rig(monkeypatch, tmp_path):
    from cdmw.modding.pac_palette_extension import validate_palette_extension
    from cdmw.modding.skeleton_parser import parse_pab
    from cdmw.services.mesh_skinning_preflight import prepare_new_item_skin
    from cdmw.ui.new_item.model_import import load_model_import_source
    from tests.test_mesh_replacement_imported_skinning import source_glb
    from tests.test_pac_cloth_guide_builder import PALETTE, guide_free_pac

    # A shipped bone8 that the template's palette does not list.
    bones = tuple((f"bone{i}", -1, translated(IDENTITY, float(i), 0.), translated(IDENTITY, -float(i), 0.),
                   translated(IDENTITY, float(i), 0.), translated(IDENTITY, -float(i), 0.),
                   (0., 0., 0., 1.), (float(i), 0., 0.)) for i in range(9))
    shipped = pab(0x17, bones=bones, hashes=PALETTE + (0xaabbcd08,), secondary=(-1,) * 9, core=(1,) * 9,
                  sets=((), (), ()))
    pac = guide_free_pac(parts=2)
    snapshot = fake_snapshot(monkeypatch, pac)
    snapshot.payload = {PAC_PATH: pac, PAB_PATH: shipped}.__getitem__
    source = load_model_import_source(source_glb(tmp_path, names=("bone2", "bone8")))
    try:
        mapped, _reports = prepare_new_item_skin(source.scene.mesh, snapshot, PAC_PATH,
                                                 skeleton_edits=(CAPE_RIG,), palette_extension_bones=("bone8",))
    finally:
        source.cleanup()
    assert mapped.interchange_skeleton_edit is None
    contract = mapped.interchange_palette_extension
    output, _ = extend_pac_palette(pac, parse_pab(shipped, PAB_PATH), ("bone8",))
    # Before, the contract named the edited rig and this check refused at Build plan.
    validate_palette_extension(pac, output, parse_pab(shipped, PAB_PATH), contract)


def test_build_plan_names_variants_weighted_to_different_bone_versions():
    from cdmw.services.new_item_planning import ModelFiles, NewItemPlanError, _Planner

    older = SkeletonEditRecipe(PAB_PATH, (PabAppendEdit("Bip01 Spine", "Cape_00", position=(0., -.2, 0.)),))
    newer = SkeletonEditRecipe(PAB_PATH, (PabAppendEdit("Bip01 Spine", "Cape_00", position=(0., -.4, 0.)),))
    planner = SimpleNamespace(
        model=None, manifest={}, warnings=[],
        variant_models={("a.prefab", "male.pac"): ModelFiles(b"", skeleton_edit=older),
                        ("b.prefab", "female.pac"): ModelFiles(b"", skeleton_edit=newer)},
        snapshot=SimpleNamespace(entry=lambda path: path, payload=lambda path: pab()))
    with pytest.raises(NewItemPlanError) as caught:
        _Planner.plan_skeleton_edits(planner)
    message = str(caught.value)
    assert "the variant male.pac" in message and "the variant female.pac" in message
    assert "different versions" in message and "give the bones different names" in message


def test_selecting_a_variant_weighted_to_older_bones_weights_it_again(studio, monkeypatch):
    from pathlib import Path as _Path
    from cdmw.domain.new_item.spec import ModelSource
    from cdmw.modding.mesh_parser import ParsedMesh, SubMesh
    from cdmw.modding.scene_import_result_ops import SceneImportResult
    from cdmw.ui.new_item.model_import import ModelImportSource

    _app, tab = studio
    controller = tab.controller
    choices = [identity for identity, _label in controller.variant_choices()]
    assert len(choices) >= 2
    first, second = choices[:2]
    older = SkeletonEditRecipe(PAB_PATH, (PabAppendEdit("Bip01 Spine", "Cape_00", position=(0., -.2, 0.)),))
    controller.select_variant(second)
    mesh = ParsedMesh(path="cape.glb", format="glb", submeshes=[SubMesh(
        name="cape", vertices=[(0., 0., 0.), (1., 0., 0.), (0., 1., 0.)], faces=[(0, 1, 2)])],
        total_vertices=3, total_faces=1)
    controller.model_import = ModelImportSource(_Path("cape.glb"), _Path("cape.glb"), SceneImportResult(mesh=mesh),
                                                None, None, skeleton_edit=older)
    controller.draft.model_source = ModelSource.IMPORTED
    controller.select_variant(first)
    controller.skeleton_edits = (replace(older, add_bones=(replace(older.add_bones[0], position=(0., -.4, 0.)),)),)
    calls = []
    monkeypatch.setattr(controller, "_reweight_for_skeleton_edits", lambda: calls.append(True) or True)
    controller.select_variant(second)
    assert calls == [True] and controller.model_import.skeleton_edit is older
