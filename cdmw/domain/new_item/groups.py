"""Conservative default memberships based on the game's explicit group taxonomy."""


def group_purpose(name: str) -> tuple[str, str, bool]:
    value = name.casefold()
    if any(word in value for word in ("quest", "special", "collection", "contribution", "visione")):
        return "Special", "May participate in quest, collection, contribution or special-item matching. Select explicitly.", False
    if value == "itemgroup_category_equipment" or value.startswith("itemgroup_subcategory_equip_"):
        return "Category", "Equipment category membership used by the game's item categorization.", True
    if value == "itemgroup_equip" or value.startswith(("itemgroup_equip_weapon", "itemgroup_equip_armor", "itemgroup_equip_all_armor",
                                                     "itemgroup_equip_human_", "itemgroup_equip_orc_", "itemgroup_equip_goblin_", "itemgroup_equip_dwarf_")):
        return "Equipment", "Equipment matching for category, character or tier. Consumers may use this group in recipes or rewards.", True
    return "Other", "Purpose is not established from the equipment taxonomy. Select explicitly after reviewing its consumers.", False


def ordinary_group(group) -> bool:
    return group_purpose(group.name)[2]
