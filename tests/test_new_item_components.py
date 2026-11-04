"""Model & Placement component list: visible export states, reversible hiding, the
underlying-body scope, preview roles and export fidelity through the real controller."""
from dataclasses import replace
import os
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import pytest
from PySide6.QtWidgets import QApplication

from cdmw.core.equipment_visibility import SHRINK_PATH
from cdmw.core.prefab_binary import decode_prefab_binary
from cdmw.domain.new_item.body_visibility import BodyVisibilityChoice
from cdmw.domain.new_item.components import ComponentRole, ComponentSource
from cdmw.services.new_item_planning import ModelFiles
from tests.test_new_item_body_visibility import PAC, TEMPLATE, game, receivers, spec

SKIN = BodyVisibilityChoice(keep_skin=True)
STEM = PAC.removesuffix(".pac")
COMPONENTS = ((PAC, "Helm"), (STEM + "_lb.pac", "Hand"), (STEM + "_acc.pac", "Shoulder"))
WORN_PART = "cd_phm_01_sword_0109_r"
GROUND_PART = "cd_phm_01_sword_0109_l"


@pytest.fixture
def studio(tmp_path):
    from cdmw.ui.new_item.controller import NewItemStudioController
    QApplication.instance() or QApplication([])
    service, snapshot, _files = game(tmp_path, components=COMPONENTS)
    controller = NewItemStudioController(synchronous=True)
    controller.snapshot = snapshot
    controller.set_template(TEMPLATE)
    facts, _roles = controller._component_facts_for(TEMPLATE)
    # The fixture's ItemInfo row lists no prefab types; give its two prefabs the
    # shipped meanings (0 worn, 3 ground) so role scoping is exercised.
    controller._component_facts[(id(snapshot), TEMPLATE)] = (facts, {WORN_PART: 0, GROUND_PART: 3})
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


def test_rows_use_prefab_component_names_roles_and_export_states(studio):
    _service, snapshot, controller = studio
    worn = rows_by(controller)
    assert [worn[name].component_name for name in sorted(worn)] == ["CD_TestComponent_00", "CD_TestComponent_02",
                                                                    "CD_TestComponent_01"]
    assert {row.shrink_tag for row in worn.values()} == {"Helm", "Hand", "Shoulder"}
    assert {row.role for row in worn.values()} == {ComponentRole.WORN}
    assert {row.role for row in rows_by(controller, GROUND_PART).values()} == {ComponentRole.DROPPED}
    assert all(row.source is ComponentSource.TEMPLATE for row in controller.component_rows())
    target = identity(controller, "cd_phm_01_sword_0109_lb.pac")
    controller.hide_component(target)
    hidden = rows_by(controller)["cd_phm_01_sword_0109_lb.pac"]
    assert hidden.source is ComponentSource.HIDDEN and hidden.body_kept_automatically and hidden.selected
    controller.select_variant(identity(controller, "cd_phm_01_sword_0109.pac"))
    controller.set_imported_model(controller.template_primary_entry(), ModelFiles(snapshot.payload(PAC)))
    assert rows_by(controller)["cd_phm_01_sword_0109.pac"].source is ComponentSource.IMPORTED
    assert rows_by(controller)["cd_phm_01_sword_0109_lb.pac"].source is ComponentSource.HIDDEN


def test_show_in_export_restores_the_prior_model_placement_and_latest_skin_choice(studio):
    from cdmw.ui.new_item.model_import import ModelPlacement
    _service, snapshot, controller = studio
    target = identity(controller, "cd_phm_01_sword_0109.pac")
    controller.select_variant(target)
    imported = ModelFiles(snapshot.payload(PAC))
    controller.set_imported_model(controller.template_primary_entry(), imported)
    placement = ModelPlacement(offset=(0.1, 0.2, 0.3))
    controller.model_placement = placement
    controller.draft.glow_parts = ("Blade",)
    controller.draft.body_visibility = SKIN
    controller.invalidate_plan()
    assert controller.hide_component(target)
    assert controller.model_result is not imported and controller.model_placement == ModelPlacement()
    assert controller.draft.glow_parts == ()
    assert controller.draft.body_visibility == SKIN, "hiding keeps the component's skin choice"
    controller.draft.body_visibility = BodyVisibilityChoice()
    controller.invalidate_plan()
    assert controller.show_component(target)
    assert controller.model_result is imported
    assert controller.model_placement == placement
    assert controller.draft.glow_parts == ("Blade",)
    assert controller.draft.body_visibility == BodyVisibilityChoice(), "the newer skin choice wins"
    assert rows_by(controller)["cd_phm_01_sword_0109.pac"].source is ComponentSource.IMPORTED


def test_hidden_state_and_skin_choice_survive_row_switches_and_continue(studio):
    from cdmw.ui.new_item.draft_file import decode_draft, encode_draft
    from cdmw.ui.new_item.controller import NewItemStudioController
    _service, snapshot, controller = studio
    acc = identity(controller, "cd_phm_01_sword_0109_acc.pac")
    controller.select_variant(acc)
    controller.draft.body_visibility = SKIN
    controller.invalidate_plan()
    controller.hide_component(acc)
    controller.select_variant(identity(controller, "cd_phm_01_sword_0109.pac"))
    controller.select_variant(acc)
    assert controller.draft.body_visibility == SKIN
    assert rows_by(controller)["cd_phm_01_sword_0109_acc.pac"].source is ComponentSource.HIDDEN
    hidden_bytes = controller.model_result.pac_data
    draft = decode_draft(encode_draft(controller.draft))
    # A package keeps the generated mesh but not its note: Continue reads the geometry.
    reopened = NewItemStudioController(synchronous=True)
    try:
        reopened.snapshot = snapshot
        reopened.set_template(TEMPLATE)
        reopened.restore_continued_item(SimpleNamespace(
            draft=draft, identity="", stat_edits=(), buy_price_edits=(), model=None, package_path="", icon_data=None,
            variant_models={acc: ModelFiles(hidden_bytes)}))
        row = next(r for r in reopened.component_rows() if r.identity == acc)
        assert row.source is ComponentSource.HIDDEN and row.keep_skin
    finally:
        reopened.shutdown()


def test_worn_body_action_is_scoped_to_worn_components_with_cut_rules(studio):
    _service, _snapshot, controller = studio
    assert controller.set_worn_body_visibility(SKIN) == 3
    assert all(row.keep_skin for row in rows_by(controller).values())
    assert not any(row.keep_skin for row in rows_by(controller, GROUND_PART).values())
    assert not any(row.keep_skin for row in controller.component_rows() if row.role is ComponentRole.OTHER)
    controller.select_variant(identity(controller, "cd_phm_01_sword_0109_acc.pac"))
    assert controller.draft.body_visibility == SKIN


def test_hiding_the_ground_model_leaves_worn_components_untouched(studio):
    _service, _snapshot, controller = studio
    ground = identity(controller, "cd_phm_01_sword_0109.pac", GROUND_PART)
    controller.hide_component(ground)
    assert rows_by(controller, GROUND_PART)["cd_phm_01_sword_0109.pac"].source is ComponentSource.HIDDEN
    assert all(row.source is ComponentSource.TEMPLATE for row in rows_by(controller).values())


def test_preview_entries_omit_hidden_companions(studio):
    _service, _snapshot, controller = studio
    lb = identity(controller, "cd_phm_01_sword_0109_lb.pac")
    main = identity(controller, "cd_phm_01_sword_0109.pac")
    controller.select_variant(main)
    before = [entry.path.casefold() for entry in controller.template_entries()]
    token_before = controller._template_geometry_build()[0]
    assert lb[1] in before
    controller.hide_component(lb)
    controller.select_variant(main)
    after = [entry.path.casefold() for entry in controller.template_entries()]
    assert lb[1] not in after and main[1] == after[0]
    assert controller._template_geometry_build()[0] != token_before


def test_export_neutralises_hidden_cut_rules_without_changing_visible_whole_part_rules(studio):
    service, snapshot, controller = studio
    for name in ("cd_phm_01_sword_0109_lb.pac", "cd_phm_01_sword_0109_acc.pac"):
        controller.hide_component(identity(controller, name))
    controller.select_variant(identity(controller, "cd_phm_01_sword_0109.pac"))
    plan = plan_for(service, snapshot, controller)
    shrink = plan.loose_files.get(SHRINK_PATH)
    record = next(r for r in plan.manifest["body_visibility"]["prefabs"] if r["source_prefab"].endswith(WORN_PART + ".prefab"))
    assert not record["whole_part_keep_skin"], "hidden companions never change the visible garment's whole-part rules"
    hidden = {c["model_path"]: c for c in record["components"] if c.get("hidden_in_export")}
    assert set(hidden) == {STEM + "_lb.pac", STEM + "_acc.pac"}
    doc = decode_prefab_binary(plan.loose_files[record["output_prefab"]])
    tags = [dict(o.values)["_shrinkTag"].text for o in doc.objects]
    assert tags[0] == "Helm", "the visible component keeps its template cut rule"
    assert tags[1] != "Hand" and tags[2] != "Shoulder"
    assert shrink is not None
    for tag in tags[1:]:
        assert "Nude" not in receivers(shrink, tag)
    assert "Nude" in receivers(shrink, "Helm")


def test_explicit_skin_on_the_visible_import_reaches_the_export(studio):
    service, snapshot, controller = studio
    main = identity(controller, "cd_phm_01_sword_0109.pac")
    controller.select_variant(main)
    controller.set_imported_model(controller.template_primary_entry(), ModelFiles(snapshot.payload(PAC)))
    controller.draft.body_visibility = SKIN
    controller.invalidate_plan()
    for name in ("cd_phm_01_sword_0109_lb.pac", "cd_phm_01_sword_0109_acc.pac"):
        controller.hide_component(identity(controller, name))
    controller.select_variant(main)
    plan = plan_for(service, snapshot, controller)
    record = next(r for r in plan.manifest["body_visibility"]["prefabs"] if r["source_prefab"].endswith(WORN_PART + ".prefab"))
    assert record["whole_part_keep_skin"]
    doc = decode_prefab_binary(plan.loose_files[record["output_prefab"]])
    tags = [dict(o.values)["_shrinkTag"].text for o in doc.objects]
    assert all(tag not in {"Helm", "Hand", "Shoulder"} for tag in tags)
    assert all("Nude" not in receivers(plan.loose_files[SHRINK_PATH], tag) for tag in tags)


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


def test_component_list_scopes_the_editor_and_toggles_hidden_state(studio):
    from cdmw.ui.new_item.panels_model import ModelPanel
    _service, _snapshot, controller = studio
    panel = ModelPanel(controller)
    try:
        components = panel.components
        items = {components.tree.topLevelItem(i).text(3): components.tree.topLevelItem(i)
                 for i in range(components.tree.topLevelItemCount())
                 if components.tree.topLevelItem(i).data(0, 0x0100) is not None
                 and components.tree.topLevelItem(i).data(0, 0x0100)[0].endswith(WORN_PART + ".prefab")}
        groups = [components.tree.topLevelItem(i).text(0) for i in range(components.tree.topLevelItemCount())
                  if components.tree.topLevelItem(i).data(0, 0x0100) is None]
        assert groups[:2] == ["Worn components", "Ground model (when dropped)"]
        lb = next(item for name, item in items.items() if name == "cd_phm_01_sword_0109_lb.pac")
        components.tree.setCurrentItem(lb)
        assert controller.current_variant_identity() == identity(controller, "cd_phm_01_sword_0109_lb.pac")
        assert "CD_TestComponent_01" in panel.body_visibility_editor.scope.text()
        assert components.hide_button.isEnabled() and not components.show_button.isEnabled()
        components.hide_button.click()
        row = next(r for r in components.rows() if r.selected)
        assert row.source is ComponentSource.HIDDEN
        current = components.tree.currentItem()
        assert current.text(1) == "Hidden in export" and current.text(2) == "Kept (hidden)"
        assert components.show_button.isEnabled()
        components.show_button.click()
        assert next(r for r in components.rows() if r.selected).source is ComponentSource.TEMPLATE
        panel.body_visibility_editor.apply_to_worn.click()
        assert all(not row.keep_skin for row in rows_by(controller).values())
        panel.body_visibility_editor.keep_skin.setChecked(True)
        panel.body_visibility_editor.apply_to_worn.click()
        assert all(row.keep_skin for row in rows_by(controller).values())
        assert "3" in components.note.text()
    finally:
        panel.close()
