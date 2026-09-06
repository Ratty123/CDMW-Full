"""Recipe outputs and selected reward consumers must be owned, connected and cumulative."""
from dataclasses import replace
import struct
import pytest

from cdmw.core.archive_format import parse_archive_pamt
from cdmw.core.item_recipe_table import ItemRecipe, RecipeIngredient, RecipeGroupIngredient, parse_item_recipe, encode_item_recipe
from cdmw.core.item_reward_table import ItemRewardSet, ItemReward, parse_item_reward_set, encode_item_reward_set
from cdmw.core.item_use_reward import ItemUseReward, parse_item_use_reward, encode_item_use_reward, item_use_references
from cdmw.core.iteminfo_row import parse_iteminfo_row, clone_iteminfo_row
from cdmw.core.multichangeinfo_table import find_multichange_keys
from cdmw.core.structured_binary_editor import append_table_rows, replace_table_row, parse_pabgh_table
from cdmw.domain.new_item.authoring import RecipeOverride, RecipeInput, RecipeOutput, RewardAcquisition
from cdmw.domain.new_item.spec import EnhancementRows
from cdmw.services.new_item_service import NewItemService
from cdmw.services.new_item_acquisition_index import load_acquisition_index
from cdmw.services.new_item_mod_base import build_mod_base_snapshot
from tests.test_new_item_provenance import current_files, spec
from tests.test_new_item_service import build_package, _read, TEMPLATE
from tests.test_new_item_socket_authoring import planned_row
from tests.test_multichangeinfo_table import _table

BASE = "gamedata/binarystaticinfo__/bin"


def recipe_row():
    desc = b"\x0d\xd0\0\0\0" + struct.pack("<I", 88) + struct.pack("<I", 3) + b"123"
    return ItemRecipe(1013165, "Template_0", 28001, 3, (), 44, "", b"\1\0\1\1\0",
                      (RecipeIngredient(TEMPLATE), RecipeIngredient(1, quantity=2)),
                      (), desc, bytes(38), (1009835,))


def reward_row():
    return ItemRewardSet(1009835, "Template_output", bytes(13), (ItemReward(TEMPLATE, 1000000, 0, 1, 1, 1),), bytes(10), 1000000, 0, "Item(1,1);")


def acquisition_game(tmp_path, *, next_transition=False):
    files = current_files()
    body, header = files[f"{BASE}/iteminfo.staticinfobody"], files[f"{BASE}/iteminfo.staticinfoheader"]
    item = next(parse_iteminfo_row(body[s:e]) for d, s, e in parse_pabgh_table(header, payload=body).row_spans(len(body)) if d.row_id == TEMPLATE)
    at = item.stat_block_offset - 3
    references = (1013165, 1013166) if next_transition else (1013165,)
    raw = item.raw[:at] + struct.pack("<I", len(references)) + struct.pack(f"<{len(references)}I", *references) + item.raw[at:]
    body, header = replace_table_row(body, header, item.key, raw)
    consumers = []
    for key in (777001, 777002):
        raw = clone_iteminfo_row(item, key=key, string_key=f"Gift_{key}", name_key=str(key), desc_key=str(key+10))
        parsed = parse_iteminfo_row(raw)
        at = parsed.prefix_end + 12
        raw = raw[:at] + struct.pack("<II", 1, 1000030) + raw[at+4:]
        consumers.append(raw)
    body, header = append_table_rows(body, header, consumers)
    files[f"{BASE}/iteminfo.staticinfobody"], files[f"{BASE}/iteminfo.staticinfoheader"] = body, header
    use = ItemUseReward(1000030, "Gift_use", b"\2\1" + bytes(17), (), 1009835, b"\0\x0e" + bytes(5))
    recipe_rows = [(1013165, encode_item_recipe(recipe_row()))]
    reward_rows = [(1009835, encode_item_reward_set(reward_row()))]
    if next_transition:
        recipe = replace(recipe_row(), key=1013166, name="Template_1",
                         ingredients=(RecipeIngredient(TEMPLATE, enhancement=1), RecipeIngredient(1, quantity=4)),
                         reward_keys=(1009836,))
        reward = replace(reward_row(), key=1009836, name="Template_output_2",
                         entries=(replace(reward_row().entries[0], enhancement=2),))
        recipe_rows.append((recipe.key, encode_item_recipe(recipe)))
        reward_rows.append((reward.key, encode_item_reward_set(reward)))
    for name, rows in (("multichangeinfo", recipe_rows),
                       ("dropsetinfo", reward_rows),
                       ("itemuseinfo", [(1000030, encode_item_use_reward(use))]),
                       ("knowledgeinfo", [(44, struct.pack("<II", 44, 9) + b"Knowledge")])):
        files[f"{BASE}/{name}.staticinfobody"], files[f"{BASE}/{name}.staticinfoheader"] = _table(rows)
    files[f"{BASE}/crafttoolinfo.staticinfobody"] = struct.pack("<HI", 28001, 7) + b"Enchant"
    files[f"{BASE}/crafttoolinfo.staticinfoheader"] = struct.pack("<HHI", 1, 28001, 0)
    entries = parse_archive_pamt(build_package(tmp_path / "game", files))
    service = NewItemService()
    return service, service.build_snapshot(entries, read_entry=_read)


def decoded(plan, name, parser):
    body, header = plan.loose_files[f"{BASE}/{name}.staticinfobody"], plan.loose_files[f"{BASE}/{name}.staticinfoheader"]
    return {d.row_id: parser(body[s:e]) for d,s,e in parse_pabgh_table(header,payload=body).row_spans(len(body))}


def test_recipe_reward_and_use_shapes_round_trip():
    recipe = replace(recipe_row(), craft_tag="tag", group_ingredients=(RecipeGroupIngredient(23, 4, 2),))
    assert parse_item_recipe(encode_item_recipe(recipe)) == recipe
    reward = reward_row().with_entries((ItemReward(1, 500000, 0, 2, 4, -1), ItemReward(2, 1000000, 0, 1, 1, 3)))
    assert parse_item_reward_set(encode_item_reward_set(reward)) == reward
    raw = bytearray(encode_item_reward_set(reward))
    at = 9 + len(reward.name) + 17 + 5
    raw[at] = 1
    with pytest.raises(ValueError, match="not decoded"):
        parse_item_reward_set(raw)


def test_owned_recipe_repoints_input_and_output_and_preserves_template(tmp_path):
    service, snapshot = acquisition_game(tmp_path)
    plan = service.plan(replace(spec(), recipes=(RecipeOverride(1013165,
        inputs=(RecipeInput(0,1), RecipeInput(1,7)), knowledge_key=0,
        outputs=(RecipeOutput(0,0,2,3),)),)), snapshot)
    recipes = decoded(plan, "multichangeinfo", parse_item_recipe)
    rewards = decoded(plan, "dropsetinfo", parse_item_reward_set)
    assert recipes[1013165] == recipe_row()
    assert rewards[1009835] == reward_row()
    new = recipes[plan.manifest["recipes"][0]["key"]]
    assert new.ingredients[0].item_key == plan.spec.item_key
    assert new.ingredients[1].quantity == 7 and new.knowledge_key == 0
    output = rewards[new.reward_keys[0]].entries[0]
    assert (output.item_key, output.minimum, output.enhancement) == (plan.spec.item_key, 2, 3)
    assert find_multichange_keys(planned_row(snapshot,plan), recipes) == (new.key,)


def test_reward_route_changes_one_consumer_and_aggregates_recipe_outputs(tmp_path):
    service, snapshot = acquisition_game(tmp_path)
    plan = service.plan(replace(spec(), enhancement=EnhancementRows.OWN,
        reward_acquisitions=(RewardAcquisition(777001,0,0,minimum=2,maximum=3),)), snapshot)
    uses = decoded(plan, "itemuseinfo", parse_item_use_reward)
    rewards = decoded(plan, "dropsetinfo", parse_item_reward_set)
    items = decoded(plan, "iteminfo", parse_iteminfo_row)
    first = item_use_references(items[777001], uses)[1][0]
    other = item_use_references(items[777002], uses)[1][0]
    assert other == 1000030 and first != other
    assert uses[other].reward_key == 1009835
    assert rewards[1009835] == reward_row()
    assert rewards[uses[first].reward_key].entries[-1].item_key == plan.spec.item_key
    assert len(rewards) == 3
    folder = tmp_path / "first"
    service.export_loose(plan, folder, manager="JMM")
    base = build_mod_base_snapshot(service, snapshot, folder, read_entry=_read)
    second = service.plan(replace(spec("Second"), enhancement=EnhancementRows.OWN), base)
    assert plan.spec.item_key in decoded(second, "iteminfo", parse_iteminfo_row)
    assert set(rewards).issubset(decoded(second,"dropsetinfo",parse_item_reward_set))


def test_partial_recipe_override_owns_the_remaining_refinement_chain(tmp_path):
    service, snapshot = acquisition_game(tmp_path, next_transition=True)
    original = load_acquisition_index(snapshot)
    plan = service.plan(replace(spec(), recipes=(RecipeOverride(1013165,
        inputs=(RecipeInput(0, 1), RecipeInput(1, 7))),)), snapshot)
    recipes = decoded(plan, "multichangeinfo", parse_item_recipe)
    rewards = decoded(plan, "dropsetinfo", parse_item_reward_set)
    owned = {entry["source_key"]: recipes[entry["key"]] for entry in plan.manifest["recipes"]}
    assert set(owned) == {1013165, 1013166}
    assert find_multichange_keys(planned_row(snapshot, plan), recipes) == tuple(r.key for r in owned.values())
    for level, source_key in enumerate((1013165, 1013166)):
        recipe = owned[source_key]
        assert recipes[source_key] == original.recipes[source_key]
        assert recipe.ingredients[0].item_key == plan.spec.item_key
        assert recipe.ingredients[0].enhancement == level
        assert recipe.ingredients[1].quantity == (7 if level == 0 else 4)
        assert recipe.tool_key == original.recipes[source_key].tool_key
        assert recipe.knowledge_key == original.recipes[source_key].knowledge_key
        output = rewards[recipe.reward_keys[0]].entries[0]
        assert (output.item_key, output.enhancement) == (plan.spec.item_key, level + 1)
        old_reward = original.recipes[source_key].reward_keys[0]
        assert rewards[old_reward] == original.rewards[old_reward]


def test_current_default_inherits_costs_but_owns_refinement_references(tmp_path):
    service, snapshot = acquisition_game(tmp_path, next_transition=True)
    original = load_acquisition_index(snapshot)
    assert spec().enhancement is EnhancementRows.TEMPLATE and spec().recipes is None
    plan = service.plan(spec(), snapshot)
    assert len(plan.manifest["recipes"]) == 2
    recipes = decoded(plan, "multichangeinfo", parse_item_recipe)
    rewards = decoded(plan, "dropsetinfo", parse_item_reward_set)
    for record in plan.manifest["recipes"]:
        source, owned = original.recipes[record["source_key"]], recipes[record["key"]]
        assert owned.ingredients == tuple(replace(value, item_key=plan.spec.item_key)
            if value.item_key == TEMPLATE else value for value in source.ingredients)
        assert all(entry.item_key == plan.spec.item_key for entry in rewards[owned.reward_keys[0]].entries)
        assert recipes[source.key] == source


def test_partial_recipe_override_refuses_unsupported_inherited_transition(tmp_path):
    service, snapshot = acquisition_game(tmp_path, next_transition=True)
    original = load_acquisition_index(snapshot)
    snapshot._authoring_indexes["acquisition"] = replace(original,
        recipes={key: value for key, value in original.recipes.items() if key != 1013166},
        unsupported={**original.unsupported, "multichangeinfo": {1013166: "unproven transition"}})
    with pytest.raises(ValueError, match="Recipe 1013166 cannot be authored: unproven transition"):
        service.plan(replace(spec(), recipes=(RecipeOverride(1013165),)), snapshot)


def test_explicit_empty_recipe_selection_clears_connections(tmp_path):
    service, snapshot = acquisition_game(tmp_path)
    plan = service.plan(replace(spec(), recipes=()), snapshot)
    assert find_multichange_keys(planned_row(snapshot,plan), snapshot.multichange_rows) == ()


def test_recipe_and_reward_widgets_write_drafts_and_reject_invalid_inputs(tmp_path):
    from PySide6.QtWidgets import QApplication
    from cdmw.ui.new_item.controller import NewItemStudioController
    from cdmw.ui.new_item.recipe_editor import RecipeEditor
    from cdmw.ui.new_item.reward_editor import RewardEditor
    app = QApplication.instance() or QApplication([])
    _, snapshot = acquisition_game(tmp_path)
    controller = NewItemStudioController(synchronous=True)
    controller.snapshot = snapshot
    controller.set_template(TEMPLATE)
    recipes, rewards = RecipeEditor(controller), RewardEditor(controller)
    recipes.load.click()
    assert recipes.index is not None and rewards.consumer.count() == 2
    recipes.customize.setChecked(True)
    recipes.inputs.item(1,2).setText("9")
    assert controller.draft.recipes[0].inputs[1].quantity == 9
    recipes.inputs.item(1,2).setText("invalid")
    assert "recipes" in controller.draft.authoring_errors
    with pytest.raises(ValueError, match="invalid"):
        controller.current_spec()
    recipes.inputs.item(1,2).setText("10")
    assert not controller.draft.authoring_errors
    rewards.add.click()
    assert controller.draft.reward_acquisitions[0].consumer_item_key == 777001
    recipes.reset.click()
    assert controller.draft.recipes is None
    recipes.close()
    rewards.close()
    controller.shutdown()


def test_unrelated_crafting_preset_remains_editable_until_an_output_is_selected(tmp_path):
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication
    from cdmw.ui.new_item.controller import NewItemStudioController
    from cdmw.ui.new_item.recipe_editor import RecipeEditor
    app = QApplication.instance() or QApplication([])
    _, snapshot = acquisition_game(tmp_path)
    index = load_acquisition_index(snapshot)
    reward = replace(index.rewards[1009835], entries=(replace(reward_row().entries[0], item_key=1, minimum=2, maximum=4),))
    index = replace(index, rewards={1009835: reward})
    controller = NewItemStudioController(synchronous=True)
    controller.snapshot = snapshot
    controller.set_template(TEMPLATE)
    editor = RecipeEditor(controller)
    try:
        editor._ready("acquisition", index)
        revision = controller._draft_revision
        editor.customize.setChecked(True)
        assert editor.customize.isChecked() and editor.outputs.isEnabled()
        assert "recipes" in controller.draft.authoring_errors
        editor.outputs.item(0, 0).setCheckState(Qt.Checked)
        assert not controller.draft.authoring_errors
        editor.outputs.item(0, 2).setText("7")
        output = controller.draft.recipes[0].outputs[0]
        assert (output.quantity, output.maximum) == (2, 7)
        assert controller._draft_revision > revision
    finally:
        editor.close()
        controller.shutdown()


def test_recipe_customize_preserves_placeholders_and_variable_inherited_output(tmp_path):
    from PySide6.QtWidgets import QApplication
    from cdmw.ui.new_item.controller import NewItemStudioController
    from cdmw.ui.new_item.recipe_editor import RecipeEditor
    app = QApplication.instance() or QApplication([])
    _, snapshot = acquisition_game(tmp_path)
    index = load_acquisition_index(snapshot)
    recipe = replace(recipe_row(), ingredients=recipe_row().ingredients + (RecipeIngredient(0, quantity=0),))
    reward = replace(reward_row(), entries=(replace(reward_row().entries[0], maximum=4),))
    index = replace(index, recipes={recipe.key: recipe}, rewards={reward.key: reward})
    controller = NewItemStudioController(synchronous=True)
    controller.snapshot = snapshot
    controller.set_template(TEMPLATE)
    editor = RecipeEditor(controller)
    try:
        editor._ready("acquisition", index)
        editor.customize.setChecked(True)
        assert not controller.draft.authoring_errors
        assert editor.inputs.rowCount() == 2
        assert controller.draft.recipes == (RecipeOverride(recipe.key),)
        assert editor.outputs.item(0, 2).text() == "4"
    finally:
        editor.close()
        controller.shutdown()


def test_recipe_owns_additional_output_list_and_preserves_conditions(tmp_path):
    service, snapshot = acquisition_game(tmp_path)
    index = load_acquisition_index(snapshot)
    recipe = replace(recipe_row(), additional_reward_keys=(1009835,))
    reward = replace(reward_row(), entries=(replace(reward_row().entries[0], condition_references=(77, 88, 0, 0)),), original_string="")
    snapshot._authoring_indexes["acquisition"] = replace(index, recipes={recipe.key: recipe}, rewards={reward.key: reward})
    plan = service.plan(replace(spec(), recipes=(RecipeOverride(recipe.key, outputs=(RecipeOutput(1, 0, 2, 3, 5),)),)), snapshot)
    recipes = decoded(plan, "multichangeinfo", parse_item_recipe)
    rewards = decoded(plan, "dropsetinfo", parse_item_reward_set)
    owned = recipes[plan.manifest["recipes"][0]["key"]]
    assert len(owned.reward_keys) == len(owned.additional_reward_keys) == 1
    assert owned.reward_keys[0] != owned.additional_reward_keys[0]
    product = rewards[owned.additional_reward_keys[0]].entries[0]
    assert (product.item_key, product.minimum, product.maximum) == (plan.spec.item_key, 2, 5)
    assert product.condition_references == (77, 88, 0, 0)
    assert rewards[owned.reward_keys[0]].entries[0].item_key == TEMPLATE
