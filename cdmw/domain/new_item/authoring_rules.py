"""Validation of optional New Item authoring controls."""
from cdmw.domain.new_item.rules import _issue, _U32_MAX, _I32_MIN, _I32_MAX, MAX_SOCKET_ITEMS, MAX_SHIPPED_SOCKET_SLOTS


def validate_authoring(spec):
    issues = []
    if spec.socket_slots is not None:
        if len(spec.socket_slots) > MAX_SOCKET_ITEMS:
            issues.append(_issue("slots.too_many", "socket_slots", "At most eight socket slots fit the supported row."))
        elif len(spec.socket_slots) > MAX_SHIPPED_SOCKET_SLOTS:
            issues.append(_issue("slots.experimental", "socket_slots", "More than five slots is experimental.", "warning"))
        for slot in spec.socket_slots:
            if not (0 < slot.material_key <= _U32_MAX and 0 < slot.amount <= _U32_MAX and 0 <= slot.extra <= _U32_MAX):
                issues.append(_issue("slots.range", "socket_slots", "Each slot needs an item key and positive unlock amount; values must fit u32."))
        if spec.socket_items is not None and len(spec.socket_items) > len(spec.socket_slots):
            issues.append(_issue("slots.capacity", "socket_slots", "The selected perks need more slots. Increase capacity or explicitly remove perks."))

    if spec.equipment_bonuses is not None:
        levels = [selection.level for selection in spec.equipment_bonuses]
        if len(levels) != len(set(levels)) or any(not 0 <= level < 256 for level in levels):
            issues.append(_issue("bonuses.levels", "equipment_bonuses", "Choose each enhancement level at most once."))
        for selection in spec.equipment_bonuses:
            if any(not 0 < bonus.buff_key <= _U32_MAX or not _I32_MIN <= bonus.parameter <= _I32_MAX for bonus in selection.bonuses):
                issues.append(_issue("bonuses.range", "equipment_bonuses", "Bonuses require a valid BuffInfo key and signed parameter level."))

    if spec.recipes is not None:
        recipe_keys = [choice.recipe_key for choice in spec.recipes]
        if len(recipe_keys) != len(set(recipe_keys)) or any(not 0 < key <= _U32_MAX for key in recipe_keys):
            issues.append(_issue("recipes.keys", "recipes", "Choose each valid source recipe once."))
        for recipe in spec.recipes:
            if recipe.inputs is not None and any(entry.kind not in ("item", "group") or not 1 <= entry.quantity <= 0xFFFFFFFFFFFFFFFF
                    or not 0 <= entry.key <= _U32_MAX or not 0 <= entry.coupon_quantity <= 0xFFFFFFFFFFFFFFFF
                    or not 0 <= entry.enhancement <= 65535 for entry in recipe.inputs):
                issues.append(_issue("recipes.inputs", "recipes", "Recipe inputs need a supported item or group and a positive quantity."))
            if recipe.outputs is not None and any(output.reward_index < 0 or output.entry_index < 0
                    or not 1 <= output.quantity <= (output.quantity if output.maximum is None else output.maximum) <= 0xFFFFFFFFFFFFFFFF
                    or not -1 <= output.enhancement <= 32767 for output in recipe.outputs):
                issues.append(_issue("recipes.outputs", "recipes", "Recipe outputs require valid quantities and enhancement levels."))
    for route in spec.reward_acquisitions or ():
        if route.mode not in ("insert", "swap") or not 0 < route.consumer_item_key <= _U32_MAX or route.use_index < 0 or route.entry_index < 0 or not 1 <= route.minimum <= route.maximum <= 0xFFFFFFFFFFFFFFFF or not -1 <= route.enhancement <= 32767 or (route.weight is not None and not 0 <= route.weight <= 0xFFFFFFFFFFFFFFFF):
            issues.append(_issue("rewards.route", "reward_acquisitions", "Choose a supported reward consumer, entry and quantity range."))

    for variant in spec.variants or ():
        from cdmw.domain.new_item.spec import MaterialRoute
        if variant.material_route not in {route.value for route in MaterialRoute}:
            issues.append(_issue("variant.material", "variants", "Choose a supported variant material route."))
        if (len(variant.glow_color) != 3 or any(not 0 <= value <= 1 for value in variant.glow_color)
                or not 0 <= variant.glow_intensity <= 20):
            issues.append(_issue("variant.glow", "variants", "Variant glow needs three color components and a supported intensity."))
        if variant.dyes is not None and any(len(value.slots) != 3 or any(not -1 <= slot <= 11 for slot in value.slots)
                or not value.target_submesh or not value.source_submesh for value in variant.dyes):
            issues.append(_issue("variant.dye", "variants", "Dye assignments need exact names and three supported slot indices."))

    return tuple(issues)
