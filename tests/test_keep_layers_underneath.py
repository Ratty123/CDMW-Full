"""Kept clothing layers: New Item receivers and the Mesh Editor Build Mod option."""
from dataclasses import replace
from types import SimpleNamespace
import hashlib
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from cdmw.core.equipment_visibility import SHRINK_PATH, VisibilityProfile, clone_shrink_rules, shrink_rule_receivers
from cdmw.core.prefab_binary import decode_prefab_binary
from cdmw.domain.new_item.body_visibility import BodyVisibilityChoice
from cdmw.domain.new_item.rules import validate_spec
from cdmw.services.mesh_layer_visibility import CLOTHING_LAYERS, prepare_layer_visibility
from cdmw.services.new_item_body_visibility import _candidate_tag
from tests.test_new_item_body_visibility import SHRINK, game, prefab, receivers
from tests.test_new_item_provenance import spec
from tests.test_new_item_service import PAC, TEMPLATE
from tests.test_new_item_variant_authoring import selections

UNDERWEAR = BodyVisibilityChoice(keep_receivers=frozenset({"Underwear"}))


def test_kept_layers_drop_only_those_receivers_and_combine_as_a_union():
    result = clone_shrink_rules(SHRINK, (VisibilityProfile("Hand", "KeptHand", UNDERWEAR),))
    assert receivers(result, "KeptHand") == {"Nude"}
    assert receivers(result, "Hand") == {"Nude", "Underwear"}
    assert shrink_rule_receivers(SHRINK, "Helm") == ("Nude", "Hair", "LongHair", "Hair_Tail", "Beard", "Underwear", "Mask")
    assert shrink_rule_receivers(SHRINK, "Missing") == ()
    merged = BodyVisibilityChoice.combine((BodyVisibilityChoice(keep_skin=True), UNDERWEAR,
                                           BodyVisibilityChoice(keep_receivers=frozenset({"Mask"}))))
    assert merged == BodyVisibilityChoice(True, False, frozenset({"Underwear", "Mask"}))
    assert merged.receiver_tags == {"Nude", "Underwear", "Mask"}
    assert merged.hidden_parts == BodyVisibilityChoice(keep_skin=True).hidden_parts


def test_profile_tags_keep_earlier_identities_and_separate_layer_choices():
    skin = BodyVisibilityChoice(keep_skin=True)
    legacy = "V" + hashlib.shake_256(b"stem|Helm|True|False|0").hexdigest(4)[:3]
    assert _candidate_tag("stem", "Helm", skin, 0) == legacy
    assert _candidate_tag("stem", "Helm", replace(skin, keep_receivers=frozenset({"Mask"})), 0) != legacy


@pytest.mark.parametrize("layers", [frozenset({"has space"}), frozenset({""}), frozenset({1}), "Underwear"])
def test_invalid_layer_names_are_validation_errors(layers):
    choice = BodyVisibilityChoice(keep_receivers=layers)
    assert any(i.code == "body_visibility.invalid" for i in validate_spec(replace(spec(), body_visibility=choice)))


def test_layer_lists_become_frozensets():
    assert BodyVisibilityChoice(keep_receivers=["Mask", "Mask"]).keep_receivers == frozenset({"Mask"})


def test_item_packages_refuse_kept_layers_but_keep_v1_skin_and_hair():
    from cdmw.domain.new_item.independent import IndependentItemError
    from cdmw.services.independent_item_codec import decode, encode
    plain = BodyVisibilityChoice(True, False)
    assert decode(encode(plain)) == plain
    with pytest.raises(IndependentItemError, match="cannot be represented by v1"):
        encode(UNDERWEAR)


def test_new_item_plan_keeps_the_layer_and_records_it(tmp_path):
    service, snapshot, _ = game(tmp_path, components=((PAC, "Hand"),))
    plan = service.plan(replace(spec(), body_visibility=UNDERWEAR), snapshot)
    records = [r for r in plan.manifest["body_visibility"]["prefabs"] if r["bindings"]]
    assert records
    for record in records:
        for component in record["components"]:
            assert receivers(plan.loose_files[SHRINK_PATH], component["profile"]) == {"Nude"}
        assert {b["model_path"]: b["keep_layers"] for b in record["bindings"]} == {
            b["model_path"]: ["Underwear"] for b in record["bindings"]}
    profiles = plan.manifest["body_visibility"]["profiles"]
    assert profiles and all(p["keep_layers"] == ["Underwear"] and not p["keep_skin"] for p in profiles)
    assert not any("does not cut" in w for w in plan.warnings)


def test_new_item_reports_a_kept_layer_the_rule_never_cut(tmp_path):
    service, snapshot, _ = game(tmp_path, components=((PAC, "Hand"),))
    choice = BodyVisibilityChoice(keep_receivers=frozenset({"Lowerbody"}))
    service, snapshot, _ = game(tmp_path / "with-underwear", components=((PAC, "Hand"),))
    both = BodyVisibilityChoice(keep_receivers=frozenset({"Lowerbody", "Underwear"}))
    plan = service.plan(replace(spec(), body_visibility=both), snapshot)
    assert any("none of this equipment's shrink rules cut Lowerbody;" in w for w in plan.warnings)
    only = service.plan(replace(spec(), body_visibility=choice), snapshot)
    assert any("none of this equipment's shrink rules cut Lowerbody; keeping it changes nothing" in w for w in only.warnings)
    assert not only.manifest["body_visibility"]["profiles"]


def test_item_wide_layers_leave_components_whose_rule_does_not_cut_them(tmp_path):
    # Shoulder cuts Helm and Nude only; keeping Underwear must not retag it.
    service, snapshot, _ = game(tmp_path, components=((PAC, "Shoulder"), (PAC, "Hand")))
    plan = service.plan(replace(spec(), body_visibility=UNDERWEAR), snapshot)
    components = [c for r in plan.manifest["body_visibility"]["prefabs"] for c in r["components"]]
    shoulder = [c for c in components if c["source_tag"] == "Shoulder"]
    assert shoulder and all(c["profile"] is None and c["unchanged"] for c in shoulder)
    assert {p["source_tag"] for p in plan.manifest["body_visibility"]["profiles"]} == {"Hand"}
    assert not any("cut" in w and "changes nothing" in w for w in plan.warnings)


def test_tags_chosen_earlier_in_the_same_prefab_are_not_reused(tmp_path, monkeypatch):
    import cdmw.services.new_item_body_visibility as visibility
    real = visibility._candidate_tag
    monkeypatch.setattr(visibility, "_candidate_tag",
                        lambda stem, tag, choice, attempt: "Vaaa" if attempt == 0 else real(stem, tag, choice, attempt))
    other = PAC.removesuffix(".pac") + "_trim.pac"
    service, snapshot, _ = game(tmp_path, components=((PAC, "Hand"), (other, "Hand")))
    first = selections(snapshot)[0]
    choices = (replace(first, body_visibility=BodyVisibilityChoice(keep_skin=True)),
               replace(first, model_path=other, body_visibility=UNDERWEAR))
    plan = service.plan(replace(spec(), variants=choices), snapshot)
    tags = [p["tag"] for p in plan.manifest["body_visibility"]["profiles"]]
    assert len(tags) == 2 and len(set(tags)) == 2 and "Vaaa" in tags


def test_new_item_panel_lists_the_variants_cut_layers_and_keeps_ticked_ones(tmp_path):
    from cdmw.ui.new_item.controller import NewItemStudioController
    from cdmw.ui.new_item.panels_model import ModelPanel
    QApplication.instance() or QApplication([])
    service, snapshot, _ = game(tmp_path)
    controller = NewItemStudioController(synchronous=True)
    controller.snapshot = snapshot
    controller.set_template(TEMPLATE)
    panel = ModelPanel(controller)
    try:
        editor = panel.body_visibility_editor
        assert editor.layers.count() == 0 and editor.layers_status.text().startswith("Click Find layers")
        editor.find_layers.click()
        names = [editor.layers.item(row).text() for row in range(editor.layers.count())]
        # The Helm rule cuts skin and hair too; those have their own checkboxes.
        assert names == ["Underwear", "Mask"]
        revision = controller._draft_revision
        editor.layers.item(0).setCheckState(Qt.Checked)
        assert controller._draft_revision > revision
        assert controller.draft.body_visibility.keep_receivers == {"Underwear"}
        first, second = [v.identity for v in selections(snapshot)[:2]]
        controller.select_variant(second)
        assert controller.draft.body_visibility.keep_receivers == frozenset()
        controller.select_variant(first)
        checked = [editor.layers.item(row).text() for row in range(editor.layers.count())
                   if editor.layers.item(row).checkState() == Qt.Checked]
        assert checked == ["Underwear"]
    finally:
        panel.close()
        controller.shutdown()


OTHER_PAC = "character/model/1_pc/1_phm/armor/9_upperbody/cd_phm_00_ub_0001.pac"


def mesh_entries(files):
    entries = {path.casefold(): SimpleNamespace(path=path, orig_size=len(data)) for path, data in files.items()}
    return entries, lambda entry: files[entry.path]


def mesh_files():
    root = "character/bin__/prefab/1_pc/test/"
    return {
        SHRINK_PATH: SHRINK,
        root + "garment.prefab": prefab(((PAC, "Hand"),)),
        root + "garment_set.prefab": prefab(((OTHER_PAC, "Helm"), (PAC, "Hand"))),
        root + "unrelated.prefab": prefab(((OTHER_PAC, "Hand"),)),
    }


def test_mesh_output_retags_every_prefab_binding_the_mesh_and_clones_the_rule():
    files = mesh_files()
    entries, read = mesh_entries(files)
    out = prepare_layer_visibility(PAC, ("Underwear",), entries, read)
    patched = {entry.path: data for entry, data in out.patches}
    assert set(patched) == {SHRINK_PATH, "character/bin__/prefab/1_pc/test/garment.prefab",
                            "character/bin__/prefab/1_pc/test/garment_set.prefab"}
    profile, = out.record["profiles"]
    assert profile["source_tag"] == "Hand" and len(profile["tag"]) == len("Hand")
    assert receivers(patched[SHRINK_PATH], profile["tag"]) == {"Nude"}
    assert receivers(patched[SHRINK_PATH], "Hand") == {"Nude", "Underwear"}
    for path in ("character/bin__/prefab/1_pc/test/garment.prefab", "character/bin__/prefab/1_pc/test/garment_set.prefab"):
        assert len(patched[path]) == len(files[path])
        tags = [dict(o.values)["_shrinkTag"].text for o in decode_prefab_binary(patched[path]).objects]
        assert tags[-1] == profile["tag"]
    set_tags = [dict(o.values)["_shrinkTag"].text for o in decode_prefab_binary(patched["character/bin__/prefab/1_pc/test/garment_set.prefab"]).objects]
    assert set_tags[0] == "Helm"
    # The same input plans the same names.
    again = prepare_layer_visibility(PAC, ("Underwear",), entries, read)
    assert again.record == out.record
    assert any("ships its own partshrinkdesc.xml" in note for note in out.notes)


def test_mesh_output_refuses_without_layers_or_a_binding_prefab():
    entries, read = mesh_entries(mesh_files())
    with pytest.raises(ValueError, match="at least one layer"):
        prepare_layer_visibility(PAC, (), entries, read)
    with pytest.raises(ValueError, match="No prefab binds"):
        prepare_layer_visibility("character/model/none.pac", ("Underwear",), entries, read)
    without = {k: v for k, v in mesh_entries(mesh_files())[0].items() if k != SHRINK_PATH}
    with pytest.raises(ValueError, match="has no character/descriptors/partshrinkdesc.xml"):
        prepare_layer_visibility(PAC, ("Underwear",), without, read)


def test_mesh_output_names_layers_the_rule_never_cut_last():
    entries, read = mesh_entries(mesh_files())
    out = prepare_layer_visibility(PAC, ("Underwear", "Lowerbody"), entries, read)
    # The status bar keeps the last message; it must be the one about this mesh.
    assert "none of this equipment's shrink rules cut Lowerbody;" in out.notes[-1]
    with pytest.raises(ValueError, match="do not cut Lowerbody; there is nothing to change"):
        prepare_layer_visibility(PAC, ("Lowerbody",), entries, read)


def test_mesh_output_matches_the_rules_spelling_of_a_layer():
    files = mesh_files()
    files[SHRINK_PATH] = SHRINK.replace(b"<Shrink>Underwear</Shrink></ShrinkTag>\n</Shrink>",
                                        b"<Shrink>Underwear</Shrink><Shrink>Shoulder_belt</Shrink></ShrinkTag>\n</Shrink>")
    assert shrink_rule_receivers(files[SHRINK_PATH], "Hand") == ("Nude", "Underwear", "Shoulder_belt")
    entries, read = mesh_entries(files)
    out = prepare_layer_visibility(PAC, ("Shoulder_Belt",), entries, read)
    shrink = dict((entry.path, data) for entry, data in out.patches)[SHRINK_PATH]
    profile, = out.record["profiles"]
    assert receivers(shrink, profile["tag"]) == {"Nude", "Underwear"}
    assert not any("changes nothing" in note for note in out.notes)


def test_mesh_output_refuses_a_prefab_it_cannot_read_exactly():
    files = mesh_files()
    files["character/bin__/prefab/1_pc/test/broken.prefab"] = b"garbage " + PAC.rsplit("/", 1)[-1].encode()
    entries, read = mesh_entries(files)
    with pytest.raises(ValueError, match="broken.prefab mentions this mesh but cannot be read exactly"):
        prepare_layer_visibility(PAC, ("Underwear",), entries, read)


def test_new_item_layer_lookup_recovers_after_cancel(tmp_path, monkeypatch):
    from cdmw.models import RunCancelled
    from cdmw.ui.new_item.controller import NewItemStudioController
    from cdmw.ui.new_item.panels_model import ModelPanel
    QApplication.instance() or QApplication([])

    def cancel(*_args):
        raise RunCancelled("stop")

    monkeypatch.setattr("cdmw.services.new_item_body_visibility.available_layers", cancel)
    service, snapshot, _ = game(tmp_path)
    controller = NewItemStudioController(synchronous=True)
    controller.snapshot = snapshot
    controller.set_template(TEMPLATE)
    panel = ModelPanel(controller)
    try:
        editor = panel.body_visibility_editor
        editor.find_layers.click()
        assert editor.find_layers.isEnabled()
        assert editor.layers_status.text().startswith("Click Find layers")
    finally:
        panel.close()
        controller.shutdown()


def test_build_mod_worker_refuses_to_patch_a_file_the_mod_already_writes(monkeypatch):
    import cdmw.services.mesh_layer_visibility as layers
    from cdmw.domain.archives.mutation import ArchivePatchRequest
    from cdmw.workers.mesh_editor_workers import MeshDirectOutputWorker
    files = mesh_files()
    entries, read = mesh_entries(files)
    monkeypatch.setattr(layers, "mounted_entries", lambda *_a, **_k: entries)
    monkeypatch.setattr("cdmw.workers.mesh_editor_workers.archive_entry_game_root", lambda _entry: "game")
    monkeypatch.setattr("cdmw.core.archive_extraction.read_archive_entry_data", lambda entry, _stop=None: (read(entry), False, ""))
    entry = SimpleNamespace(path=PAC)
    worker = MeshDirectOutputWorker(1, None, "s", entry, kind="loose_mod", keep_layers=("Underwear",))
    requests = []
    out = worker._layer_visibility(requests, [])
    assert {request.entry.path for request in requests} == {entry.path for entry, _ in out.patches}
    taken = [ArchivePatchRequest(entries[SHRINK_PATH.casefold()], SHRINK)]
    with pytest.raises(ValueError, match="already part of this mod"):
        worker._layer_visibility(taken, [])
    with pytest.raises(ValueError, match="only to Build Mod"):
        MeshDirectOutputWorker(1, None, "s", entry, kind="archive_result", keep_layers=("Underwear",))


def test_build_mod_dialog_returns_ticked_layers_only_when_enabled(tmp_path):
    from cdmw.ui.mesh_editor.mod_export_dialog import MeshModExportDialog
    QApplication.instance() or QApplication([])
    dialog = MeshModExportDialog(None, title="Coat", description="d", output_parent=str(tmp_path),
                                 output_choice="", manager_profile="dmm")
    try:
        assert dialog.kept_layers() == () and not dialog.layers.isEnabled()
        assert [dialog.layers.item(r).text() for r in range(dialog.layers.count())] == list(CLOTHING_LAYERS)
        dialog.keep_layers.setChecked(True)
        assert dialog.layers.isEnabled() and not dialog.build_button.isEnabled()
        row = CLOTHING_LAYERS.index("Lowerbody")
        dialog.layers.item(row).setCheckState(Qt.Checked)
        assert dialog.kept_layers() == ("Lowerbody",) and dialog.build_button.isEnabled()
        dialog.keep_layers.setChecked(False)
        assert dialog.kept_layers() == () and dialog.build_button.isEnabled()
    finally:
        dialog.deleteLater()
