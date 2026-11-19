"""Effects workspace, glow controls, and the perks and bonus editors."""

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor

from cdmw.mcp.errors import INVALID_ARGUMENTS, UNAVAILABLE, ToolError
from cdmw.mcp.names import EDIT, READ
from cdmw.mcp.new_item_workflow import (
    BOOL, INT, NUMBER, TEXT, VEC3, act, action_schema, array, available, choice, combo_choices, idle,
    json_value, read_when, required, set_control, workflow,
)
from cdmw.mcp.tools import ON_CALL, Tool, object_schema

_INDEX = {"type": "integer", "minimum": 0}
_COLOR = {"type": "string", "minLength": 1, "maxLength": 32}
_ANIMATION = {name: NUMBER for name in ("flow_u", "flow_v", "pulse_frequency", "pulse_minimum")}
_RGB = {"enabled": BOOL, "intensity": NUMBER, "reveal": NUMBER, "softness": NUMBER, "inverse": BOOL}
_ACTIONS = (
    "state", "search", "index", "pick", "layer", "placement", "look", "apply", "discard",
    "glow", "search_perks", "perks", "load_bonuses", "bonus",
)


def _click(button):
    available(button)
    button.click()


def _state(page):
    from cdmw.ui.new_item.state import EffectWorkspaceState

    draft = page.controller.draft
    editor = page._perks_panel
    workspace = editor.effects_workspace if editor is not None else None
    committed = EffectWorkspaceState.from_draft(draft)
    model = page.model_panel
    return {
        "committed": json_value(committed), "staged": json_value(workspace.staged_state if workspace else committed),
        "unapplied": workspace.has_staged_changes() if workspace else False,
        "compatibility": workspace.compatibility_label.text() if workspace else "",
        "perks": json_value(draft.socket_items), "bonuses": json_value(draft.equipment_bonuses),
        "glow": {"parts": list(draft.glow_parts), "color": list(draft.glow_color), "intensity": draft.glow_intensity,
                 "animation": json_value(draft.glow_animation), "rgb": json_value(draft.glow_rgb),
                 "available_parts": [model.glow_parts.item(i).data(Qt.ItemDataRole.UserRole)
                                     for i in range(model.glow_parts.count())]},
    }


def _editor(page):
    editor = page.perks_panel
    # This is the same header and sub-tab route that prepares the resident editor.
    page.show_step(4)
    editor.tabs.setCurrentWidget(editor.effects_workspace)
    return editor.effects_workspace


def _layer(workspace, a):
    recipe = workspace.recipe_panel
    operation = a.get("operation", "set")
    if "row" in a:
        if a["row"] >= recipe.layers.count():
            raise ValueError("There is no such effect layer.")
        recipe.layers.setCurrentRow(a["row"])
    if operation in ("add", "duplicate", "remove"):
        count = recipe.layers.count()
        {"add": recipe.add_layer, "duplicate": recipe.duplicate_layer, "remove": recipe.remove_layer}[operation]()
        if recipe.layers.count() == count:
            raise ValueError("Choose an effect first. The Layers editor supports at most 16 layers.")
    elif operation in ("up", "down"):
        recipe.move_layer(-1 if operation == "up" else 1)
    if "name" in a or "enabled" in a:
        row = recipe.layers.currentRow()
        if row < 0:
            raise ValueError("Select an effect layer.")
        if "name" in a:
            recipe.layers.item(row).setText(a["name"])
        if "enabled" in a:
            recipe.layers.item(row).setCheckState(Qt.CheckState.Checked if a["enabled"] else Qt.CheckState.Unchecked)


def _glow(panel, a):
    parts = a.get("parts")
    items = {panel.glow_parts.item(i).data(Qt.ItemDataRole.UserRole): panel.glow_parts.item(i)
             for i in range(panel.glow_parts.count())}
    if parts is not None and set(parts) - items.keys():
        raise ValueError(panel.glow_parts.toolTip())
    if "enabled" in a or parts:
        set_control(panel.glow_box, a.get("enabled", True))
    if parts is not None:
        for name, item in items.items():
            item.setCheckState(Qt.CheckState.Checked if name in parts else Qt.CheckState.Unchecked)
    if "intensity" in a:
        set_control(panel.glow_intensity, a["intensity"])
    if "color" in a:
        _click(panel.glow_color_button)
    for name, value in a.get("animation", {}).items():
        set_control(panel.glow_animation.spins[name], value)
    rgb = a.get("rgb")
    if rgb:
        editor = panel.glow_animation
        set_control(editor.rgb_box, rgb.get("enabled", True))
        if editor.rgb_box.isChecked():
            for name, value in rgb.items():
                if name == "inverse":
                    set_control(editor.rgb_inverse, value)
                elif name != "enabled":
                    set_control(editor.rgb_spins[name], value)


def _perks(panel, a):
    if "customize" in a:
        set_control(panel.own_perks, a["customize"])
    if "experimental" in a:
        set_control(panel.experimental_perks, a["experimental"])
    for row in sorted(set(a.get("remove_rows", [])), reverse=True):
        if row >= panel.chosen.count():
            raise ValueError("There is no such selected perk.")
        panel.chosen.setCurrentRow(row)
        _click(panel.remove_button)
    for key in a.get("add_perks", []):
        set_control(panel.catalogue, key)
        _click(panel.add_button)


def _bonus(editor, a):
    if "customize" in a:
        set_control(editor.customize, a["customize"])
    if "level" in a:
        set_control(editor.level, a["level"])
    if "preset_row" in a:
        if a["preset_row"] >= editor.presets.count():
            raise ValueError("There is no such equipment preset.")
        editor.presets.setCurrentIndex(a["preset_row"])
        _click(editor.use_preset)
    if "key" in a:
        def position():
            return next((row for row, bonus in enumerate(editor._selections().get(editor.level.currentData(), ()))
                         if bonus.buff_key == a["key"]), -1)

        row = position()
        if a.get("remove"):
            if row < 0:
                raise ValueError("That bonus is not selected at this level.")
            editor.values.setCurrentCell(row, 0)
            _click(editor.remove)
        else:
            if row < 0:
                set_control(editor.advanced, a["key"])
                _click(editor.add)
                row = position()
            if "parameter" in a:
                set_control(editor.values.cellWidget(row, 1), a["parameter"])
    if a.get("all_levels"):
        _click(editor.apply_all)


def _search(call, action):
    context = call.context
    capture = {}

    def start():
        page = workflow(context)
        panel = page.perks_panel
        text = call.arguments.get("text", "")
        if action == "search_perks":
            # The available choices load through the same filter even while the
            # template perks are inherited and its visible editor is collapsed.
            panel.perk_filter.setText(text)
            capture.update(panel=panel)
        elif action == "load_bonuses":
            editor = panel.bonus_editor
            if editor.index is None:
                idle(page)
                _click(editor.load)
            capture.update(bonus=editor)
        else:
            workspace = _editor(page)
            set_control(workspace.search, text)
            capture.update(workspace=workspace)
        capture["controller"] = page.controller
        return {}

    result = act(call, start)
    if result:
        return result

    def read():
        if action == "search_perks":
            panel = capture["panel"]
            return None if panel._perk_lookup.busy else combo_choices(panel.catalogue)
        if action == "load_bonuses":
            editor = capture["bonus"]
            if capture["controller"].busy or editor._lookup.busy:
                return None
            return {"choices": combo_choices(editor.advanced), "presets": combo_choices(editor.presets),
                    "levels": combo_choices(editor.level), "status": editor.state.text()}
        from cdmw.ui.new_item.effect_library_model import EffectLibraryModel

        workspace = capture["workspace"]
        if workspace._library_build_lane.busy or workspace._library_search_lane.busy or workspace._library_timer.isActive():
            return None
        model = workspace.library_model
        return {"count": model.rowCount(), "choices": [
            {"stem": model.index(i, 0).data(EffectLibraryModel.StemRole), "label": model.index(i, 0).data()}
            for i in range(min(200, model.rowCount()))
        ]}

    return read_when(call, read) or {"loading": True}


def _effects(call):
    a, context = call.arguments, call.context
    action = a["action"]
    if action == "state":
        return context.ui_call(lambda: _state(workflow(context)))
    if action in ("search", "search_perks", "load_bonuses"):
        return _search(call, action)
    if "color" in a and not QColor(a["color"]).isValid():
        raise ToolError(INVALID_ARGUMENTS, "Enter a valid colour, for example #ff8844.")

    if action in ("layer", "placement", "look"):
        def open_editor():
            _editor(workflow(context))
            return {}

        result = act(call, open_editor)
        if result:
            return result
        wait = read_when(call, lambda: True if workflow(context).perks_panel.effects_workspace.placement is not None else None,
                         timeout=5)
        if wait is None:
            raise ToolError(UNAVAILABLE, context.ui_call(
                lambda: workflow(context).perks_panel.effects_workspace.placeholder.text()))
    if action == "apply":
        def compatibility():
            page = workflow(context)
            workspace = page.perks_panel.effects_workspace
            checks = [page.controller.effect_target_compatibility(layer.stem)
                      for layer in workspace.staged_state.resolved_layers() if layer.enabled]
            return True if all(check is not None for check in checks) else None

        if read_when(call, compatibility) is None:
            raise ToolError(UNAVAILABLE, context.ui_call(
                lambda: workflow(context).perks_panel.effects_workspace.compatibility_label.text()))

    def change():
        page = workflow(context)
        idle(page)
        if action == "glow":
            _glow(page.model_panel, a)
            return _state(page)
        panel = page.perks_panel
        workspace = panel.effects_workspace
        if action == "index":
            _click(panel.index_button)
        elif action == "pick":
            from cdmw.ui.new_item.effect_library_model import EffectLibraryModel

            required(a, "stem")
            workspace = _editor(page)
            stem = a["stem"]
            index = workspace.library_model.index_for_stem(stem)
            if stem and not index.isValid():
                raise ValueError("Find the effect in the library first with the search action.")
            if index.isValid() and index != workspace.library_view.currentIndex():
                workspace.library_view.setCurrentIndex(index)
            elif not stem or workspace.staged_state.stem != index.data(EffectLibraryModel.StemRole):
                workspace.choose_effect(stem)
        elif action == "layer":
            if workspace.recipe_panel is None:
                raise ValueError("The Layers editor is not ready.")
            _layer(workspace, a)
        elif action == "placement":
            placement = workspace.placement
            for name in ("offset", "rotation"):
                for spin, value in zip(getattr(placement, name + "_spins"), a.get(name, ())):
                    set_control(spin, value)
            if "scale" in a:
                set_control(placement.scale_spin, a["scale"])
        elif action == "look":
            placement = workspace.placement
            for name, control in (("intensity", "intensity"), ("size", "particle_size"),
                                  ("rate", "spawn_rate"), ("lifetime", "lifetime")):
                if name in a:
                    set_control(placement.look_spins[control], a[name])
            if "shipped_color" in a or "color" in a:
                set_control(placement.colour_as_shipped, a.get("shipped_color", False))
                if "color" in a:
                    _click(placement.guided_colour_button)
        elif action == "apply":
            if not panel.apply_staged_effect():
                raise ValueError(workspace.compatibility_label.text() or "The staged effect could not be applied.")
        elif action == "discard":
            panel.discard_staged_effect()
        elif action == "perks":
            _perks(panel, a)
        elif action == "bonus":
            _bonus(panel.bonus_editor, a)
        return _state(page)

    def checked():
        try:
            return change()
        except ValueError as exc:
            raise ToolError(UNAVAILABLE, str(exc)) from None

    return act(call, checked, answers={"color": a["color"]} if "color" in a else None)


def effects_tool():
    return Tool(
        name="new_item.effects", family="new_item", title="Edit New Item effects and perks",
        description="Find and stage effects, edit layers, placement and look, then apply or discard like the "
                    "Effects page. Also edits model glow, glow animation, perks and inherent bonuses.",
        input_schema=action_schema(_ACTIONS, {
            "text": TEXT, "stem": TEXT, "row": _INDEX, "operation": choice("add", "duplicate", "remove", "up", "down", "set"),
            "name": {"type": "string", "maxLength": 128}, "enabled": BOOL, "offset": VEC3, "rotation": VEC3,
            "scale": NUMBER, "intensity": NUMBER, "size": NUMBER, "rate": NUMBER, "lifetime": NUMBER,
            "color": _COLOR, "shipped_color": BOOL, "parts": array(TEXT), "animation": object_schema(_ANIMATION),
            "rgb": object_schema(_RGB), "customize": BOOL, "experimental": BOOL, "add_perks": array(INT, limit=8),
            "remove_rows": array(_INDEX, limit=8), "level": INT, "key": INT, "parameter": INT, "remove": BOOL,
            "preset_row": _INDEX, "all_levels": BOOL,
        }, default="state"),
        effect=EDIT, effect_of=lambda call: READ if call.arguments["action"] == "state" else EDIT,
        route="ui:PerksPanel,GuidedEffectsWorkspace,GlowAnimationEditor", handler=_effects, runs_on=ON_CALL,
    )
