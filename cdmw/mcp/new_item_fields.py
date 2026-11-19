"""Identity, Stats & Prices, and Distribution through their page editors."""

from PySide6.QtCore import Qt

from cdmw.mcp.names import EDIT
from cdmw.mcp.new_item_workflow import (
    BOOL, INT, TEXT, act, action_schema, array, available, choice, combo_choices, idle, read_when,
    required, set_control, widget_reason, workflow,
)
from cdmw.mcp.tools import ON_CALL, Tool, object_schema

_INDEX = {"type": "integer", "minimum": 0}
_NULL_INT = {"type": ["integer", "null"]}
_TEXTS = {"type": "object", "description": "Language codes mapped to text."}
_GRID_CELL = object_schema({"level": _INDEX, "kind": choice("stat", "buy_price"), "key": INT,
                            "value": _NULL_INT}, ["level", "kind", "key", "value"])
_PRICE = object_schema({"key": INT, "value": INT}, ["key", "value"])
_INGREDIENT = object_schema({"kind": choice("item", "group"), "key": INT, "quantity": INT,
                             "level": INT, "coupon": INT}, ["kind", "key", "quantity"])
_PRODUCT = object_schema({"reward_index": _INDEX, "entry_index": _INDEX, "selected": BOOL,
                          "minimum": INT, "maximum": INT, "level": INT}, ["reward_index", "entry_index"])
_RECIPE = object_schema({
    "key": INT, "customize": BOOL, "tool": INT, "knowledge": INT,
    "ingredients": array(_INGREDIENT), "outputs": array(_PRODUCT),
}, ["key"])
_REWARD = object_schema({
    "consumer": INT, "use_index": _INDEX, "entry": _INDEX, "mode": choice("insert", "swap"),
    "minimum": INT, "maximum": INT, "level": INT, "weight": _NULL_INT,
}, ["consumer", "use_index", "entry"])
_FIELDS = {
    "internal_name": TEXT, "item_key": _NULL_INT, "stem": TEXT,
    "display_names": _TEXTS, "descriptions": _TEXTS,
    "extra_levels": _INDEX, "add_stat": object_schema({"key": INT, "value": INT}, ["key", "value"]),
    "remove_stat": INT, "grid_values": array(_GRID_CELL), "price_values": array(_PRICE),
    "include_perk_prices": BOOL, "max_stack_count": _NULL_INT, "item_tier": INT, "required_level": INT,
    "max_durability": INT, "own_enhancement_rows": BOOL, "one_copper": BOOL, "restore_stats": BOOL,
    "placement_kind": choice("none", "insert", "swap"), "store_name": TEXT, "stock_index": INT,
    "keep_requirement": BOOL, "unlimited_stock": BOOL, "stock_count": _NULL_INT,
    "shops": array(TEXT), "shop_route": choice("add", "use_current"), "remove_shop_route": _INDEX,
    "item_groups": choice("ordinary", "template", "explicit"), "explicit_item_groups": array(INT),
    "reward": _REWARD, "remove_reward": _INDEX, "recipe": _RECIPE, "recipe_connections": choice("inherit", "clear"),
}


def _button(button):
    available(button)
    button.click()


def _select_row(widget, row):
    if not 0 <= row < widget.count():
        raise ValueError("There is no such row on the page.")
    widget.setCurrentRow(row)


def _set_texts(panel, field, values):
    widget = panel.display_name if field == "display_names" else panel.description
    refused = {}
    for language, text in values.items():
        try:
            if not isinstance(text, str):
                raise ValueError("Enter text for this language.")
            set_control(panel.language, language)
            set_control(widget, text)
        except ValueError as exc:
            refused[language] = str(exc)
    return refused


def _set_identity(page, name, value):
    panel = page.identity_panel
    if name in ("display_names", "descriptions"):
        return _set_texts(panel, name, value)
    widget = getattr(panel, name)
    if name in ("item_key", "stem"):
        manual = value not in ("", None)
        if name == "item_key" and manual and not 1 <= value <= widget.maximum():
            raise ValueError(widget_reason(widget))
        if name == "stem" and manual and widget.validator().validate(value, len(value))[0] != widget.validator().State.Acceptable:
            raise ValueError(widget_reason(widget))
        set_control(getattr(panel, name + "_manual"), manual)
        if not manual:
            return None
    set_control(widget, value)
    return None


def _column(grid, kind, key):
    return next((index for index, column in enumerate(grid.columns)
                 if column.kind == kind and column.key == key), -1) if grid is not None else -1


def _edit_cells(panel, edits, *, prices):
    table = panel.price_table if prices else panel.table
    grid = panel._grid
    refused = {}
    for index, edit in enumerate(edits):
        if prices:
            row = next((i for i, entry in enumerate(grid.price_items) if entry[0] == edit["key"]), -1) if grid else -1
            column = 1
        else:
            row, column = edit["level"], _column(grid, edit["kind"], edit["key"])
        item = table.item(row, column) if 0 <= row < table.rowCount() and column >= 0 else None
        if not table.isEnabled() or item is None or not item.flags() & Qt.ItemFlag.ItemIsEditable:
            refused[str(index)] = "This price or level and column is unavailable on the page."
            continue
        value = edit["value"]
        item.setText("" if value is None else str(value))
    return refused


def _set_stats(page, name, value):
    panel = page.stats_panel
    draft = page.controller.draft
    if name in ("grid_values", "price_values"):
        return _edit_cells(panel, value, prices=name == "price_values")
    if name in panel.property_controls:
        set_control(panel.property_controls[name], value)
    elif name == "max_stack_count":
        set_control(panel.max_stack, "" if value is None else str(value))
        if value is not None and not 1 <= value < 1 << 64:
            raise ValueError(widget_reason(panel.max_stack))
    elif name == "include_perk_prices":
        set_control(panel.include_perk_prices, value)
    elif name == "own_enhancement_rows":
        set_control(panel.own_rows, value)
    elif name == "extra_levels":
        from cdmw.ui.new_item.panels_stats import _MAX_EXTRA_LEVELS

        if not 0 <= value <= _MAX_EXTRA_LEVELS:
            raise ValueError(f"The page allows up to {_MAX_EXTRA_LEVELS} added levels.")
        button = panel.add_level_button if value > draft.extra_levels else panel.remove_level_button
        for _ in range(abs(value - draft.extra_levels)):
            _button(button)
    elif name == "add_stat":
        set_control(panel.new_stat, value["key"])
        set_control(panel.new_stat_value, value["value"])
        _button(panel.add_stat_button)
    elif name == "remove_stat":
        column = _column(panel._grid, "stat", value)
        if column < 0 or value not in draft.extra_stat_keys:
            raise ValueError("Only an added stat can be removed.")
        panel.table.setCurrentCell(0, column)
        _button(panel.remove_stat_button)
    elif value:
        _button(panel.one_copper_button if name == "one_copper" else panel.reset_button)
    return None


def _select_stock(panel, value):
    index = panel.old_item.findData(value, Qt.ItemDataRole.UserRole + 1)
    available(panel.old_item)
    if index < 0:
        raise ValueError(widget_reason(panel.old_item))
    panel.old_item.setCurrentIndex(index)


def _set_items_group(panel, value):
    chosen = set(value)
    items = {panel.group_list.item(i).data(Qt.ItemDataRole.UserRole): panel.group_list.item(i)
             for i in range(panel.group_list.count())}
    missing = chosen - items.keys()
    if missing:
        raise ValueError(f"Item groups {sorted(missing)} are outside the current search results.")
    available(panel.group_list)
    existing = set(panel._controller.draft.explicit_item_groups)
    if existing - items.keys() - chosen:
        raise ValueError("Search for the previously selected groups before removing them, or clear the filter.")
    for key in (chosen | existing) & items.keys():
        items[key].setCheckState(Qt.CheckState.Checked if key in chosen else Qt.CheckState.Unchecked)


def _recipe(editor, value):
    set_control(editor.recipe, value["key"])
    if not editor.customize.isEnabled():
        raise ValueError(editor.state.text())
    set_control(editor.customize, value.get("customize", True))
    if not editor.customize.isChecked():
        return
    if "tool" in value:
        set_control(editor.tool, value["tool"])
    if "knowledge" in value:
        set_control(editor.knowledge, str(value["knowledge"]))
    if "ingredients" in value:
        ingredients = value["ingredients"]
        while editor.inputs.rowCount() > len(ingredients):
            editor.inputs.setCurrentCell(editor.inputs.rowCount() - 1, 0)
            _button(editor.remove)
        for row, ingredient in enumerate(ingredients):
            if editor.inputs.rowCount() <= row:
                _button(editor.add)
            fields = (ingredient["kind"], ingredient["key"], ingredient["quantity"],
                      ingredient.get("level", 0), ingredient.get("coupon", 0))
            for column, entry in enumerate(fields):
                editor.inputs.item(row, column).setText(str(entry))
    if "outputs" in value:
        rows = {tuple(editor.outputs.item(row, 0).data(Qt.ItemDataRole.UserRole)): row
                for row in range(editor.outputs.rowCount())}
        for output in value["outputs"]:
            row = rows.get((output["reward_index"], output["entry_index"]))
            if row is None:
                raise ValueError("There is no such recipe output on the page.")
            values = list(enumerate(("minimum", "maximum", "level"), 1))
            for column, key in values:
                if key in output:
                    editor.outputs.item(row, column).setText(str(output[key]))
            if "selected" in output:
                editor.outputs.item(row, 0).setCheckState(Qt.CheckState.Checked if output["selected"]
                                                           else Qt.CheckState.Unchecked)
    problem = editor.controller.draft.authoring_errors.get("recipes")
    if problem:
        raise ValueError(problem)


def _set_distribution(page, name, value):
    panel = page.placement_panel
    if name == "placement_kind":
        set_control({"none": panel.no_store, "insert": panel.insert, "swap": panel.swap}[value], True)
    elif name == "shops":
        available(panel.choose_store_button)
        unknown = [store for store in value if not page.controller.has_store(store)]
        if unknown or not value:
            raise ValueError(f"Choose existing shops. Unavailable: {unknown}.")
        if len(value) > 1 and not panel.insert.isChecked():
            raise ValueError(panel.choose_store_button.toolTip())
        panel.apply_shop_selection(value)
    elif name == "store_name":
        set_control(panel.store, value)
    elif name == "stock_index":
        _select_stock(panel, value)
    elif name in ("keep_requirement", "unlimited_stock", "stock_count"):
        set_control(getattr(panel, name), 0 if value is None else value)
    elif name in ("shop_route", "remove_shop_route"):
        editor = panel.shop_routes
        if name == "remove_shop_route":
            _select_row(editor.routes, value)
            _button(editor.remove)
        elif value == "add":
            before = page.controller.draft.shop_placements
            _button(editor.add)
            if before == page.controller.draft.shop_placements:
                raise ValueError(editor.state.text())
        else:
            _button(editor.single)
    elif name == "item_groups":
        set_control(panel.explicit, value == "explicit")
        if value != "explicit":
            set_control(panel.inherit_all, value == "template")
    elif name == "explicit_item_groups":
        _set_items_group(panel, value)
    elif name == "recipe":
        _recipe(page.stats_panel.recipes, value)
    elif name == "recipe_connections":
        editor = page.stats_panel.recipes
        _button(editor.reset if value == "inherit" else editor.clear)
    elif name == "remove_reward":
        editor = panel.rewards
        _select_row(editor.routes, value)
        _button(editor.remove)
    return None


def _reward(call, editor, value):
    def select():
        for row in range(editor.consumer.count()):
            data = editor.consumer.itemData(row)
            if data and tuple(data[:2]) == (value["consumer"], value["use_index"]):
                available(editor.consumer)
                editor.consumer.setCurrentIndex(row)
                return {}
        raise ValueError(editor.state.text() if editor.index is None else "The reward consumer is outside the loaded choices.")

    def apply():
        selected = editor.consumer.currentData()
        if selected is None or tuple(selected[:2]) != (value["consumer"], value["use_index"]):
            raise ValueError("The selected reward consumer changed while its details loaded.")
        set_control(editor.entry, value["entry"])
        for name in ("mode", "minimum", "maximum", "level", "weight"):
            if name in value:
                entry = value[name]
                set_control(getattr(editor, name), ("" if entry is None else str(entry)) if name == "weight" else entry)
        before = editor.routes.count()
        _button(editor.add)
        if before == editor.routes.count():
            raise ValueError(editor.state.text())
        return {}

    def checked(fn):
        try:
            return fn()
        except ValueError as exc:
            return {"refused": str(exc)}

    result = act(call, lambda: checked(select))
    if result:
        return result
    if read_when(call, lambda: True if not editor._details_lookup.busy else None) is None:
        return {"refused": "Reward details are still loading."}
    return act(call, lambda: checked(apply))


_IDENTITY = ("internal_name", "item_key", "stem", "display_names", "descriptions")
_STATS = (
    "restore_stats", "one_copper", "extra_levels", "add_stat", "remove_stat", "grid_values", "price_values",
    "include_perk_prices", "max_stack_count", "item_tier", "required_level", "max_durability", "own_enhancement_rows",
)
_DISTRIBUTION = (
    "placement_kind", "store_name", "shops", "stock_index", "keep_requirement", "unlimited_stock", "stock_count",
    "shop_route", "remove_shop_route", "item_groups", "explicit_item_groups", "recipe_connections", "recipe",
    "remove_reward",
)


def _set(call):
    action = call.arguments["action"]
    if action != "set":
        return _look_up(call, action)
    required(call.arguments, "fields")
    values = call.arguments["fields"]
    applied, refused = [], {}

    def edit():
        page = workflow(call.context)
        idle(page)
        for names, handler in ((_IDENTITY, _set_identity), (_STATS, _set_stats), (_DISTRIBUTION, _set_distribution)):
            for name in names:
                if name not in values:
                    continue
                try:
                    problems = handler(page, name, values[name])
                    if problems:
                        refused[name] = problems
                    else:
                        applied.append(name)
                except ValueError as exc:
                    refused[name] = str(exc)
        for name in values.keys() - _FIELDS.keys():
            refused[name] = "There is no typed field by this name on these steps."
        # Some edits are accepted by the control but are still blocking plan validation.
        issues = page.controller.validate() if page.controller.ready else ()
        return {"applied": applied, "refused": refused,
                "issues": [{"field": issue.field, "message": issue.message} for issue in issues if issue.is_error]}

    result = act(call, edit)
    if "reward" in values and "applied" in result:
        editor = call.context.ui_call(lambda: workflow(call.context).placement_panel.rewards)
        outcome = _reward(call, editor, values["reward"])
        if outcome:
            result["refused"]["reward"] = outcome.get("refused", outcome)
        else:
            result["applied"].append("reward")
    return result


def _look_up(call, action):
    capture = {}

    def start():
        page = workflow(call.context)
        search = call.arguments.get("text", "")
        if action == "search_stats":
            return combo_choices(page.stats_panel.new_stat)
        if action == "search_groups":
            panel = page.placement_panel
            set_control(panel.group_filter, search)
            capture.update(editor=panel, lanes=(panel._group_lookup,))
        else:
            editor = page.stats_panel.recipes if action == "load_recipes" else page.placement_panel.rewards
            capture.update(editor=editor, lanes=(editor._lookup, editor._tool_lookup) if action == "load_recipes"
                           else (editor._lookup, editor._details_lookup))
            if editor.index is None:
                idle(page)
                _button(editor.load)
            if action == "load_recipes":
                set_control(editor.inherited, call.arguments.get("template_only", True))
                set_control(editor.search, search)
                editor._choices()  # Same handler as the search box's debounce timer.
        capture["controller"] = page.controller
        return {}

    result = act(call, start)
    if result or not capture:
        return result

    def read():
        if capture["controller"].busy or any(lane.busy for lane in capture["lanes"]):
            return None
        editor = capture["editor"]
        if action == "search_groups":
            return {"choices": [{"value": editor.group_list.item(i).data(Qt.ItemDataRole.UserRole),
                                  "label": editor.group_list.item(i).text()}
                                 for i in range(min(200, editor.group_list.count()))],
                    "count": editor.group_list.count()}
        result = {"status": editor.state.text()}
        if action == "load_recipes":
            result.update(recipes=combo_choices(editor.recipe), tools=combo_choices(editor.tool))
        else:
            result.update(consumers=combo_choices(editor.consumer), entries=combo_choices(editor.entry))
        return result

    return read_when(call, read) or {"loading": True}


def field_tool():
    fields_schema = {**object_schema(_FIELDS), "additionalProperties": True}
    return Tool(name="new_item.set", family="new_item", title="Set New Item fields by name",
                description="Change Identity, Stats & Prices and Distribution using their editors. "
                            "Load recipe and reward choices, search groups, or list addable stats first. "
                            "The result lists applied fields and any refusals by field.",
                input_schema=action_schema(("set", "load_rewards", "load_recipes", "search_groups", "search_stats"),
                                           {"fields": fields_schema, "text": TEXT, "template_only": BOOL}, default="set"),
                effect=EDIT, route="ui:IdentityPanel,StatsPanel,PlacementPanel", handler=_set, runs_on=ON_CALL)
