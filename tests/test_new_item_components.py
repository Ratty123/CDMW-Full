"""Model & Placement components: inclusion separate from source, the underlying-body
scope, preview roles, persistence and export fidelity through the real controller."""
from dataclasses import replace
import json
import os
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from cdmw.core.equipment_visibility import SHRINK_PATH
from cdmw.core.prefab_binary import decode_prefab_binary
from cdmw.domain.new_item.body_visibility import BodyVisibilityChoice
from cdmw.domain.new_item.components import ComponentRole, ComponentSource
from cdmw.services.new_item_planning import ModelFiles
from cdmw.services.new_item_skinning import HiddenVariantRequest, is_hidden_variant_result
from tests.test_new_item_body_visibility import PAC, TEMPLATE, game, receivers, spec

SKIN = BodyVisibilityChoice(keep_skin=True)
STEM = PAC.removesuffix(".pac")
COMPONENTS = ((PAC, "Helm"), (STEM + "_lb.pac", "Hand"), (STEM + "_acc.pac", "Shoulder"))
WORN_PART = "cd_phm_01_sword_0109_r"
GROUND_PART = "cd_phm_01_sword_0109_l"
LB, ACC, MAIN = "cd_phm_01_sword_0109_lb.pac", "cd_phm_01_sword_0109_acc.pac", "cd_phm_01_sword_0109.pac"


def _roles(controller, snapshot):
    facts, _roles = controller._component_facts_for(TEMPLATE)
    # The fixture's ItemInfo row lists no prefab types; give its two prefabs the
    # shipped meanings (0 worn, 3 ground) so role scoping is exercised.
    controller._component_facts[(id(snapshot), TEMPLATE)] = (facts, {WORN_PART: 0, GROUND_PART: 3})


@pytest.fixture
def studio(tmp_path):
    from cdmw.ui.new_item.controller import NewItemStudioController
    QApplication.instance() or QApplication([])
    service, snapshot, _files = game(tmp_path, components=COMPONENTS)
    controller = NewItemStudioController(synchronous=True)
    controller.snapshot = snapshot
    controller.set_template(TEMPLATE)
    _roles(controller, snapshot)
    controller.draft.internal_name = spec().internal_name
    controller.draft.display_names = dict(spec().display_names)
    yield service, snapshot, controller
    controller.shutdown()


def rows_by(controller, part=WORN_PART):
    return {row.model_file: row for row in controller.component_rows() if row.part_stem == part}


def identity(controller, model_file, part=WORN_PART):
    return rows_by(controller, part)[model_file].identity


def plan_for(service, snapshot, controller):
    spec_value = controller.current_spec()
    models, scenes, _owners = controller.variant_plan_inputs()
    return service.plan(spec_value, snapshot, variant_models=models, variant_scenes=scenes)


def test_rows_report_names_roles_sources_and_inclusion_separately(studio):
    _service, snapshot, controller = studio
    worn = rows_by(controller)
    assert [worn[name].component_name for name in sorted(worn)] == ["CD_TestComponent_00", "CD_TestComponent_02",
                                                                    "CD_TestComponent_01"]
    assert {row.shrink_tag for row in worn.values()} == {"Helm", "Hand", "Shoulder"}
    assert {row.role for row in worn.values()} == {ComponentRole.WORN}
    assert {row.role for row in rows_by(controller, GROUND_PART).values()} == {ComponentRole.DROPPED}
    assert all(row.source is ComponentSource.TEMPLATE and row.included for row in controller.component_rows())
    lb = identity(controller, LB)
    active_before = controller.current_variant_identity()
    assert controller.set_component_included(lb, False)
    assert controller.current_variant_identity() == active_before, "ticking never selects the row"
    hidden = rows_by(controller)[LB]
    assert not hidden.included and hidden.source is ComponentSource.TEMPLATE and hidden.body_kept_automatically
    controller.select_variant(identity(controller, MAIN))
    controller.set_imported_model(controller.template_primary_entry(), ModelFiles(snapshot.payload(PAC)))
    assert rows_by(controller)[MAIN].source is ComponentSource.IMPORTED
    assert not rows_by(controller)[LB].included


def test_leaving_out_and_including_keeps_the_source_placement_edits_and_latest_skin(studio):
    from cdmw.ui.new_item.model_import import ModelPlacement
    _service, snapshot, controller = studio
    target = identity(controller, MAIN)
    controller.select_variant(target)
    imported = ModelFiles(snapshot.payload(PAC))
    controller.set_imported_model(controller.template_primary_entry(), imported)
    placement = ModelPlacement(offset=(0.1, 0.2, 0.3))
    controller.model_placement = placement
    controller.draft.glow_parts = ("Blade",)
    controller.draft.body_visibility = SKIN
    controller.invalidate_plan()
    assert controller.hide_component(target)
    assert controller.model_result is imported and controller.model_placement == placement
    assert controller.draft.glow_parts == ("Blade",) and controller.draft.body_visibility == SKIN
    assert not rows_by(controller)[MAIN].included
    controller.draft.body_visibility = BodyVisibilityChoice()
    controller.invalidate_plan()
    assert controller.show_component(target)
    assert controller.model_result is imported and controller.model_placement == placement
    assert controller.draft.glow_parts == ("Blade",)
    assert controller.draft.body_visibility == BodyVisibilityChoice(), "the newer skin choice wins"
    row = rows_by(controller)[MAIN]
    assert row.included and row.source is ComponentSource.IMPORTED


def test_inclusion_survives_row_switches_draft_save_and_continue(studio):
    from cdmw.ui.new_item.draft_file import decode_draft, encode_draft
    from cdmw.ui.new_item.controller import NewItemStudioController
    _service, snapshot, controller = studio
    acc = identity(controller, ACC)
    controller.select_variant(acc)
    controller.draft.body_visibility = SKIN
    controller.invalidate_plan()
    controller.set_component_included(acc, False)
    controller.select_variant(identity(controller, MAIN))
    controller.select_variant(acc)
    assert controller.draft.body_visibility == SKIN and not rows_by(controller)[ACC].included
    draft = decode_draft(encode_draft(controller.draft))
    assert draft.excluded_bindings == (acc,)
    from cdmw.services.new_item_skinning import hide_variant_geometry
    placeholder = ModelFiles(hide_variant_geometry(snapshot, acc[1]).pac_data)
    # Without package models, and with the hidden placeholder a written package holds.
    for package_models in ({}, {acc: placeholder}):
        _reopen_and_retick(snapshot, draft, acc, package_models)


def _reopen_and_retick(snapshot, draft, acc, package_models):
    from cdmw.ui.new_item.controller import NewItemStudioController
    reopened = NewItemStudioController(synchronous=True)
    try:
        reopened.snapshot = snapshot
        reopened.set_template(TEMPLATE)
        _roles(reopened, snapshot)
        reopened.restore_continued_item(SimpleNamespace(
            draft=draft, identity="", stat_edits=(), buy_price_edits=(), model=None, package_path="", icon_data=None,
            variant_models=package_models))
        row = rows_by(reopened)[ACC]
        assert not row.included and row.keep_skin
        # The left-out marker in the saved variants is an export detail, not an import.
        assert row.source is ComponentSource.TEMPLATE
        models, _scenes, _owners = reopened.variant_plan_inputs()
        assert models[acc] == HiddenVariantRequest(acc[1])
        assert reopened.set_component_included(acc, True)
        assert rows_by(reopened)[ACC].source is ComponentSource.TEMPLATE
        assert acc not in reopened.variant_plan_inputs()[0]
        assert not any(v.identity == acc and v.custom_model for v in reopened.current_spec().variants or ())
    finally:
        reopened.shutdown()


def test_legacy_hidden_geometry_reads_as_left_out_and_reincludes_as_template(studio):
    from cdmw.ui.new_item.draft_file import decode_draft, encode_draft
    from cdmw.ui.new_item.controller import NewItemStudioController
    from cdmw.services.new_item_skinning import hide_variant_geometry
    _service, snapshot, controller = studio
    acc = identity(controller, ACC)
    hidden = hide_variant_geometry(snapshot, acc[1])
    # Drafts and packages from the old Hide buttons: a custom model whose mesh is the placeholder.
    controller.select_variant(acc)
    controller.set_imported_model(controller.template_primary_entry(), hidden)
    controller.select_variant(identity(controller, MAIN))
    draft = decode_draft(encode_draft(controller.draft))
    reopened = NewItemStudioController(synchronous=True)
    try:
        reopened.snapshot = snapshot
        reopened.set_template(TEMPLATE)
        _roles(reopened, snapshot)
        reopened.restore_continued_item(SimpleNamespace(
            draft=draft, identity="", stat_edits=(), buy_price_edits=(), model=None, package_path="", icon_data=None,
            variant_models={acc: ModelFiles(hidden.pac_data)}))
        assert not rows_by(reopened)[ACC].included
        assert reopened.set_component_included(acc, True)
        row = rows_by(reopened)[ACC]
        assert row.included and row.source is ComponentSource.TEMPLATE
    finally:
        reopened.shutdown()


def test_worn_body_action_is_scoped_to_worn_components_with_cut_rules(studio):
    _service, _snapshot, controller = studio
    assert controller.set_worn_body_visibility(SKIN) == 3
    assert all(row.keep_skin for row in rows_by(controller).values())
    assert not any(row.keep_skin for row in rows_by(controller, GROUND_PART).values())
    assert not any(row.keep_skin for row in controller.component_rows() if row.role is ComponentRole.OTHER)
    controller.select_variant(identity(controller, ACC))
    assert controller.draft.body_visibility == SKIN


def test_leaving_out_the_ground_model_leaves_worn_components_untouched(studio):
    _service, _snapshot, controller = studio
    controller.set_component_included(identity(controller, MAIN, GROUND_PART), False)
    assert not rows_by(controller, GROUND_PART)[MAIN].included
    assert all(row.included for row in rows_by(controller).values())


def test_preview_entries_omit_left_out_companions(studio):
    _service, _snapshot, controller = studio
    lb, main = identity(controller, LB), identity(controller, MAIN)
    controller.select_variant(main)
    before = [entry.path.casefold() for entry in controller.template_entries()]
    token_before = controller._template_geometry_build()[0]
    assert lb[1] in before
    controller.set_component_included(lb, False)
    after = [entry.path.casefold() for entry in controller.template_entries()]
    assert lb[1] not in after and main[1] == after[0]
    assert controller._template_geometry_build()[0] != token_before


def test_a_component_unticked_before_any_row_is_selected_is_left_out_of_preview_and_plan(studio):
    """Ticking never selects a row, so the first untick can arrive with no active binding."""
    service, snapshot, controller = studio
    lb, main = identity(controller, LB), identity(controller, MAIN)
    assert controller._active_variant is None
    assert lb[1] in [entry.path.casefold() for entry in controller.template_entries()]
    assert controller.set_component_included(lb, False)
    assert controller.current_variant_identity() == main, "the row shown as selected is the one in effect"
    shown = [entry.path.casefold() for entry in controller.template_entries()]
    assert lb[1] not in shown and main[1] == shown[0]
    plan = plan_for(service, snapshot, controller)
    assert isinstance(controller.variant_plan_inputs()[0][lb], HiddenVariantRequest)
    record = next(r for r in plan.manifest["body_visibility"]["prefabs"] if r["source_prefab"].endswith(WORN_PART + ".prefab"))
    assert {c["model_path"] for c in record["components"] if c.get("hidden_in_export")} == {STEM + "_lb.pac"}
    written = [data for path, data in plan.loose_files.items() if path.endswith(".pac") and "sword" in path]
    assert sum(is_hidden_variant_result(ModelFiles(data)) for data in written) == 1
    # Ticking it back in, still with no row selected, exports the whole template again.
    assert controller.set_component_included(lb, True)
    assert lb[1] in [entry.path.casefold() for entry in controller.template_entries()]
    again = plan_for(service, snapshot, controller)
    assert not any(is_hidden_variant_result(ModelFiles(data)) for path, data in again.loose_files.items()
                   if path.endswith(".pac") and "sword" in path)


def test_export_uses_unticked_rows_without_a_preview_refresh(studio):
    from cdmw.services.new_item_skinning import HiddenVariantRequest, is_hidden_variant_result
    service, snapshot, controller = studio
    main = identity(controller, MAIN)
    controller.select_variant(main)
    controller.set_imported_model(controller.template_primary_entry(), ModelFiles(snapshot.payload(PAC)))
    controller.draft.body_visibility = SKIN
    controller.invalidate_plan()
    for name in (LB, ACC):
        controller.set_component_included(identity(controller, name), False)
    models, _scenes, _owners = controller.variant_plan_inputs()
    assert isinstance(models[identity(controller, LB)], HiddenVariantRequest), "no geometry work on the UI thread"
    plan = plan_for(service, snapshot, controller)
    record = next(r for r in plan.manifest["body_visibility"]["prefabs"] if r["source_prefab"].endswith(WORN_PART + ".prefab"))
    assert record["whole_part_keep_skin"]
    hidden = {c["model_path"] for c in record["components"] if c.get("hidden_in_export")}
    assert hidden == {STEM + "_lb.pac", STEM + "_acc.pac"}
    doc = decode_prefab_binary(plan.loose_files[record["output_prefab"]])
    tags = [dict(o.values)["_shrinkTag"].text for o in doc.objects]
    assert all(tag not in {"Helm", "Hand", "Shoulder"} for tag in tags)
    assert all("Nude" not in receivers(plan.loose_files[SHRINK_PATH], tag) for tag in tags)
    owned = {v["model_path"]: v["appearance"] for v in plan.manifest["variants"] if WORN_PART in v["prefab_path"]}
    assert set(owned) >= {PAC, STEM + "_lb.pac", STEM + "_acc.pac"}
    written = {path: data for path, data in plan.loose_files.items() if path.endswith(".pac") and "sword" in path}
    assert sum(is_hidden_variant_result(ModelFiles(data)) for data in written.values()) >= 2
    assert any(not is_hidden_variant_result(ModelFiles(data)) for data in written.values()), "the import stays visible"


def test_hidden_components_alone_keep_visible_whole_part_rules(studio):
    service, snapshot, controller = studio
    for name in (LB, ACC):
        controller.set_component_included(identity(controller, name), False)
    controller.select_variant(identity(controller, MAIN))
    plan = plan_for(service, snapshot, controller)
    record = next(r for r in plan.manifest["body_visibility"]["prefabs"] if r["source_prefab"].endswith(WORN_PART + ".prefab"))
    assert not record["whole_part_keep_skin"]
    doc = decode_prefab_binary(plan.loose_files[record["output_prefab"]])
    tags = [dict(o.values)["_shrinkTag"].text for o in doc.objects]
    assert tags[0] == "Helm" and tags[1] != "Hand" and tags[2] != "Shoulder"
    assert "Nude" in receivers(plan.loose_files[SHRINK_PATH], "Helm")


def test_item_package_leaves_out_components_but_keeps_the_shared_cut_rules(studio, monkeypatch):
    import cdmw.core.pac_xml_references as references
    import cdmw.services.new_item_resource_copies as copies
    import cdmw.services.independent_item_package as packages
    from cdmw.core.equipment_visibility import POSTFIX_PATH
    from cdmw.services.new_item_planning import NewItemPlanError
    # The fixture's material files are stand-ins that package mode cannot parse.
    monkeypatch.setattr(references, "parse_pac_xml_references", lambda data, check=None: SimpleNamespace(
        rewrite_textures=lambda mapping, check=None: data))
    monkeypatch.setattr(copies, "copy_material_textures", lambda planner, material, mapping: (material, []))
    # Its stand-in side files also fail the full package audit; the descriptor rule is asserted below.
    monkeypatch.setattr(packages, "audit_plan", lambda plan, snapshot, stop_event=None: None)
    service, snapshot, controller = studio

    def package_plan():
        controller.invalidate_plan()
        models, scenes, _owners = controller.variant_plan_inputs()
        return service.plan(controller.current_spec(), snapshot, variant_models=models, variant_scenes=scenes,
                            capture_independent=True)

    lb = identity(controller, LB)
    controller.select_variant(lb)
    controller.draft.body_visibility = SKIN  # a left-out row's own choice waits until it is ticked again
    for name in (LB, ACC):
        controller.set_component_included(identity(controller, name), False)
    controller.select_variant(identity(controller, MAIN))
    assert rows_by(controller)[LB].body_kept_automatically
    controller.independent_mode = True  # the rows say so for item package output
    assert not rows_by(controller)[LB].body_kept and not rows_by(controller)[ACC].body_kept
    controller.independent_mode = False
    # A .cdmw cannot carry shared descriptors: the hidden geometry is written, the cut rules stay.
    plan = package_plan()
    assert SHRINK_PATH not in plan.loose_files and POSTFIX_PATH not in plan.loose_files
    assert any("left-out component(s) keep the template's body-cut rule" in w for w in plan.warnings)
    written = [data for path, data in plan.loose_files.items() if path.endswith(".pac") and "sword" in path]
    assert sum(is_hidden_variant_result(ModelFiles(data)) for data in written) == 2
    # The DMM mod route drops their cuts, still without the left-out row's own choice.
    record = next(r for r in plan_for(service, snapshot, controller).manifest["body_visibility"]["prefabs"]
                  if r["source_prefab"].endswith(WORN_PART + ".prefab"))
    assert not record["whole_part_keep_skin"] and len(record["bindings"]) == 2
    # Keeping the skin under a visible component is refused plainly in a package.
    controller.draft.body_visibility = SKIN
    with pytest.raises(NewItemPlanError, match=r"package \(\.cdmw\) cannot carry"):
        package_plan()


def test_an_import_finishing_after_another_row_is_selected_stays_with_its_row(studio, tmp_path, monkeypatch):
    from copy import deepcopy
    from PIL import Image
    from tests.test_scene_importer_gltf import _triangle_payload
    import cdmw.ui.new_item.controller_model_mixin as mixin
    _service, _snapshot, controller = studio
    binary, document = _triangle_payload()
    (tmp_path / "source.bin").write_bytes(binary)
    document["buffers"][0]["uri"] = "source.bin"
    path = tmp_path / "source.gltf"
    path.write_text(json.dumps(document), encoding="utf-8")
    main, acc = identity(controller, MAIN), identity(controller, ACC)
    controller.select_variant(main)
    real = mixin.load_model_import_source

    def switching(*args, **kwargs):
        result = real(*args, **kwargs)
        controller.select_variant(acc)  # the user clicked another row meanwhile
        return result

    monkeypatch.setattr(mixin, "load_model_import_source", switching)
    assert controller.start_model_import(path)
    assert controller.current_variant_identity() == acc and controller.model_import is None
    row = rows_by(controller)[MAIN]
    assert row.source is ComponentSource.IMPORTED and row.source_name == "source.gltf"
    # Unapplied, so the plan asks for its placement; left out, it needs none.
    unapplied = {"variant_placement_not_applied", "model_placement_not_applied"}
    assert {issue.code for issue in controller.validate()} & unapplied
    controller.set_component_included(main, False)
    assert not {issue.code for issue in controller.validate()} & unapplied
    controller.select_variant(main)
    assert not {issue.code for issue in controller.validate()} & unapplied
    controller.set_component_included(main, True)
    assert "model_placement_not_applied" in {issue.code for issue in controller.validate()}
    assert controller.model_import is not None and controller.model_import.chosen_path == path


def test_old_hidden_results_without_notes_are_recognised_and_real_models_are_not():
    from cdmw.services.new_item_skinning import hide_variant_geometry, is_hidden_variant_result
    from tests.test_pac_cloth_guide_builder import guide_free_pac
    raw = guide_free_pac(parts=2)
    files = {"selected.pac": raw}
    snapshot = SimpleNamespace(payload=files.__getitem__, has_entry=lambda path: path in files)
    hidden = hide_variant_geometry(snapshot, "selected.pac")
    assert is_hidden_variant_result(hidden)
    assert is_hidden_variant_result(ModelFiles(hidden.pac_data))
    assert not is_hidden_variant_result(ModelFiles(raw))
    assert not is_hidden_variant_result(None)


def test_component_list_checkboxes_selection_and_explicit_preview_refresh(studio):
    from cdmw.ui.new_item.panels_model import ModelPanel
    _service, _snapshot, controller = studio
    panel = ModelPanel(controller)
    try:
        components = panel.components
        tree = components.tree
        groups = [tree.topLevelItem(i).text(0) for i in range(tree.topLevelItemCount())
                  if tree.topLevelItem(i).data(0, Qt.UserRole) is None]
        assert groups[:2] == ["Worn components", "Ground model (when dropped)"]
        assert tree.columnCount() == 3, "model paths live in the tooltip, not a wide column"
        lb, main = identity(controller, LB), identity(controller, MAIN)
        item = components.item_for(lb)
        assert item.checkState(0) == Qt.CheckState.Checked and "Model:" in item.toolTip(0)
        calls = []
        panel.preview.show = lambda *a, **k: calls.append("show")
        panel.preview.show_placement = lambda *a, **k: calls.append("placement")
        panel.show()
        QApplication.processEvents()
        calls.clear()
        tree.setCurrentItem(item)
        QApplication.processEvents()
        assert controller.current_variant_identity() == lb
        assert "CD_TestComponent_01" in panel.editing_label.text()
        assert "CD_TestComponent_01" in panel.body_visibility_editor.scope.text()
        assert calls == [] and panel._preview_stale and panel.preview_stale_label.isVisibleTo(panel)
        assert not panel.capture_inline_button.isEnabled()
        components.item_for(main).setCheckState(0, Qt.CheckState.Unchecked)
        assert main in controller.draft.excluded_bindings and controller.current_variant_identity() == lb
        assert components.item_for(main).checkState(0) == Qt.CheckState.Unchecked
        assert calls == []
        panel.refresh_preview_button.click()
        assert len(calls) == 1 and not panel._preview_stale
        components.item_for(main).setCheckState(0, Qt.CheckState.Checked)
        assert main not in controller.draft.excluded_bindings
        panel.body_visibility_editor.keep_skin.setChecked(True)
        panel.body_visibility_editor.apply_to_worn.click()
        assert all(row.keep_skin for row in rows_by(controller).values())
    finally:
        panel.close()
