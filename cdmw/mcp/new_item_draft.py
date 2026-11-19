"""Workflow navigation and a typed view of the Create New Item draft."""

from dataclasses import fields

from cdmw.mcp.errors import UNAVAILABLE, ToolError
from cdmw.mcp.names import EDIT, READ
from cdmw.mcp.new_item_workflow import STEPS, act, choice, combo_choices, json_value, workflow
from cdmw.mcp.tools import ON_CALL, ON_UI, Tool, object_schema
from cdmw.mcp.ui_actions import ANSWERS_SCHEMA

_DRAFT_FIELDS = {
    "template": "template_key",
    "identity": "internal_name display_names descriptions stem item_key independent_identity",
    "model": (
        "model_source material_route sheathed_model keep_template_physics icon icon_source_path socket_slots "
        "variants translucency template_transform shader_controls body_visibility surface_settings excluded_bindings"
    ),
    "stats": (
        "grid_values extra_levels extra_stat_keys price_values include_perk_prices max_stack_count item_tier "
        "required_level max_durability item_settings stat_settings inventory_settings definition_settings "
        "behavior_settings table_edits own_enhancement_rows"
    ),
    "effects": (
        "glow_parts glow_color glow_intensity glow_animation glow_rgb socket_items equipment_bonuses "
        "effect_stem effect_scale effect_offset effect_rotation effect_color effect_intensity effect_size "
        "effect_rate effect_lifetime effect_emitter_edits effect_emitter_order effect_layers"
    ),
    "distribution": (
        "placement_kind store_name old_item_name keep_requirement unlimited_stock stock_count stock_index "
        "shop_placements item_groups explicit_item_groups recipes reward_acquisitions authoring_errors"
    ),
    "output": "manager export_root mod_name",
}


def _step_info(page, row):
    item = page.steps.item(row)
    return {"id": STEPS[row], "index": row, "name": item.text(), "state": item.state().value,
            "reason": item.toolTip()}


def _step(call):
    from cdmw.ui.new_item.workflow_header import WorkflowStepState

    row = STEPS.index(call.arguments["step"])

    def move():
        page = workflow(call.context)
        target = page.steps.item(row)
        if target.state() is WorkflowStepState.BLOCKED or not target.button.isEnabled():
            raise ToolError(UNAVAILABLE, target.toolTip(), {"step": _step_info(page, row)})
        target.button.click()
        actual = page.pages.currentIndex()
        if actual != row:
            raise ToolError(UNAVAILABLE, page.steps.item(actual).toolTip(), {"step": _step_info(page, actual)})
        return {"step": _step_info(page, actual)}

    return act(call, move, message_boxes={"new_item_staged_effect": call.arguments.get("staged", "stay")})


def _choices(page):
    from PySide6.QtCore import Qt

    from cdmw.domain.new_item.spec import IconSource, ItemGroupsChoice, MaterialRoute, ModelSource, PlacementKind, SheathedModel
    from cdmw.ui.new_item.panels_stats import _MAX_EXTRA_LEVELS

    controller = page.controller
    identity = page.identity_panel
    model = page.model_panel
    grid = controller.stat_grid()
    allowed = {
        "template_key": {"tool": "new_item_search", "selection_tool": "new_item_pick"},
        "internal_name": {"pattern": identity.internal_name.validator().regularExpression().pattern()},
        "stem": {"pattern": identity.stem.validator().regularExpression().pattern(), "automatic": ""},
        "item_key": {"minimum": 1, "maximum": identity.item_key.maximum(), "automatic": None},
        "display_names": combo_choices(identity.language),
        "descriptions": combo_choices(identity.language),
        "extra_levels": {"minimum": 0, "maximum": _MAX_EXTRA_LEVELS},
        "extra_stat_keys": {"tool": "new_item_set", "action": "search_stats"},
        "effect_stem": {"tool": "new_item_effects", "action": "search"},
        "socket_items": {"tool": "new_item_effects", "action": "search_perks"},
        "socket_slots": {"minimum_slots": 0, "maximum_slots": 8, "experimental_above": 5},
        "recipes": {"tool": "new_item_set", "action": "load_recipes"},
        "reward_acquisitions": {"tool": "new_item_set", "action": "load_rewards"},
        "explicit_item_groups": {"tool": "new_item_set", "action": "search_groups"},
        "max_stack_count": {"minimum": 1, "maximum": (1 << 64) - 1, "inherit": None},
        "glow_color": {"channels": 3, "minimum": 0, "maximum": 1},
        "glow_intensity": _range(model.glow_intensity),
        "glow_parts": {"choices": [model.glow_parts.item(i).data(Qt.ItemDataRole.UserRole)
                                   for i in range(model.glow_parts.count())]},
        "glow_animation": {name: _range(control) for name, control in model.glow_animation.spins.items()},
        "glow_rgb": {name: _range(control) for name, control in model.glow_animation.rgb_spins.items()},
        "icon_source_path": {"kind": "image file or folder"},
        "shader_controls": combo_choices(model.shader_controls_editor.part),
        "translucency": {"parts": [model.translucency_editor.parts.item(i).data(Qt.ItemDataRole.UserRole)
                                    for i in range(model.translucency_editor.parts.count())]},
        "body_visibility": {"layers": [model.body_visibility_editor.layers.item(i).data(Qt.ItemDataRole.UserRole)
                                       for i in range(model.body_visibility_editor.layers.count())]},
        "variants": {"choices": [list(row.identity) for row in model.components.rows()]},
        "excluded_bindings": {"choices": [list(row.identity) for row in model.components.rows()]},
        "effect_layers": {"maximum_layers": 16, "tool": "new_item_effects", "action": "layer"},
        "equipment_bonuses": {"tool": "new_item_effects", "action": "load_bonuses"},
        "shop_placements": {"tool": "new_item_set", "actions": ["shops", "shop_route", "remove_shop_route"]},
        "export_root": {"kind": "existing folder outside the game"},
        "manager": combo_choices(page.output_panel.manager),
        "store_name": {"choices": list(controller.store_names())},
    }
    for name, kind in {
        "model_source": ModelSource, "material_route": MaterialRoute, "sheathed_model": SheathedModel,
        "icon": IconSource, "placement_kind": PlacementKind, "item_groups": ItemGroupsChoice,
    }.items():
        allowed[name] = {"choices": [option.value for option in kind]}
    if grid is not None:
        allowed["grid_values"] = {"columns": json_value(grid.columns), "template_values": json_value(grid.template_values),
                                  "level_count": grid.level_count + controller.draft.extra_levels}
        allowed["price_values"] = {"currencies": json_value(grid.price_items)}
    stats, distribution = page._stats_panel, page._placement_panel
    if stats is not None:
        for name, control in stats.property_controls.items():
            allowed[name] = _range(control)
    else:
        for name, maximum in (("item_tier", 255), ("required_level", 0xffffffff), ("max_durability", 65535)):
            allowed[name] = {"minimum": 0, "maximum": maximum}
    if distribution is not None:
        allowed["old_item_name"] = combo_choices(distribution.old_item)
        allowed["stock_index"] = {"choices": [distribution.old_item.itemData(row, Qt.ItemDataRole.UserRole + 1)
                                              for row in range(distribution.old_item.count())]}
        allowed["stock_count"] = _range(distribution.stock_count)
    workspace = page._perks_panel.effects_workspace if page._perks_panel else None
    if workspace is not None and workspace.placement is not None:
        placement = workspace.placement
        allowed["effect_scale"] = _range(placement.scale_spin)
        allowed["effect_offset"] = [_range(spin) for spin in placement.offset_spins]
        allowed["effect_rotation"] = [_range(spin) for spin in placement.rotation_spins]
        for name, control in (("intensity", "intensity"), ("size", "particle_size"),
                              ("rate", "spawn_rate"), ("lifetime", "lifetime")):
            allowed["effect_" + name] = _range(placement.look_spins[control])
    return allowed


def _range(control):
    return {"minimum": control.minimum(), "maximum": control.maximum(), "enabled": control.isEnabled()}


def _draft(call):
    from cdmw.ui.new_item.tab import _workflow_step_for_issue

    page = workflow(call.context)
    controller = page.controller
    draft = controller.draft
    types = {field.name: field.type for field in fields(draft)}
    allowed = _choices(page)
    issues = controller.validate() if controller.ready else ()
    selection = call.arguments.get("step")
    steps = []
    for row, key in enumerate(STEPS):
        if selection and key != selection:
            continue
        step = _step_info(page, row)
        step["issues"] = [json_value(issue) for issue in issues if _workflow_step_for_issue(issue) == row]
        values = {}
        for name in _DRAFT_FIELDS[key].split():
            value = getattr(draft, name)
            encoded = ({"entries": [{"level": level, "column": column, "value": cell}
                                    for (level, column), cell in sorted(value.items())]}
                       if name == "grid_values" else json_value(value))
            rule = allowed.get(name, {"type": str(types[name])})
            if types[name] in (bool, "bool"):
                rule = {"choices": [False, True]}
            values[name] = {"value": encoded, "allowed": rule}
        step["fields"] = values
        if key == "model":
            step["placement"] = json_value(controller.model_placement)
            model = page.model_panel
            step["placement_allowed"] = {name: [_range(spin) for spin in controls] for name, controls in (
                ("offset", model.offset_spins), ("rotation", model.rotation_spins), ("scale", model.scale_spins))}
            source = controller.model_import
            step["import"] = None if source is None else {
                "label": source.label, "skinning": json_value(source.skinning_choices),
                "applied": controller.model_result is not None,
            }
        if key == "effects" and page._perks_panel is not None:
            workspace = page._perks_panel.effects_workspace
            step["staged"] = json_value(workspace.staged_state)
            step["unapplied"] = workspace.has_staged_changes()
        steps.append(step)
    return {"step": STEPS[page.pages.currentIndex()], "ready": controller.ready, "busy": controller.busy,
            "steps": steps}


def draft_tools():
    return [
        Tool(name="new_item.step", family="new_item", title="Go to a New Item step",
             description="Click a workflow step and report its state or the page's blocker. "
                         "When leaving Effects, set staged to apply, discard or stay.",
             input_schema=object_schema({"step": choice(*STEPS), "staged": choice("apply", "discard", "stay"),
                                         "answers": ANSWERS_SCHEMA}, ["step"]),
             effect=EDIT, route="ui:WorkflowHeader.stepButton", handler=_step, runs_on=ON_CALL),
        Tool(name="new_item.draft", family="new_item", title="Read the New Item draft",
             description="Read the current values, choices, validation issues and state by workflow step. "
                         "Embedded mask data is represented by its dimensions and byte count.",
             input_schema=object_schema({"step": choice(*STEPS)}),
             effect=READ, route="ui:NewItemStudioTab", handler=_draft, runs_on=ON_UI),
    ]
