"""Cancellable lookups for the secondary New Item catalogues."""
from cdmw.domain.cancellation import raise_if_cancelled


def perk_choices(snapshot, query, stop_event):
    if snapshot is None:
        return ()
    rows = snapshot._authoring_indexes.get("perk-search")
    if rows is None:
        english, users = snapshot.english.index(), snapshot.socket_item_users()
        prepared = []
        for index, key in enumerate(snapshot.perk_item_keys):
            if index % 64 == 0:
                raise_if_cancelled(stop_event)
            row = snapshot.rows.get(key)
            if row is None:
                continue
            internal = str(row.string_key or "")
            name = english.get(row.name_key)
            label = str(name.text) if name is not None else internal
            description = str(getattr(english.get(row.desc_key), "text", "") or "").strip()
            lowered = internal.casefold()
            kind = "Ability" if "item_skill" in lowered else "Stat perk" if "item_stat" in lowered else "Perk"
            evidence = f"Used by {users[key]} shipped item(s)." if users.get(key) else "No shipped item embeds it; treat it as experimental."
            meaning = description or "No localized description is available."
            detail = f"{kind}. {meaning} {evidence} Internal ID: {internal} ({key})."
            prepared.append((key, label, detail, f"{label} {internal} {description} {key}".casefold()))
        rows = tuple(sorted(prepared, key=lambda item: item[1].casefold()))
        raise_if_cancelled(stop_event)
        snapshot._authoring_indexes["perk-search"] = rows
    needle = query.strip().casefold()
    found = []
    for index, (key, label, detail, text) in enumerate(rows):
        if index % 128 == 0:
            raise_if_cancelled(stop_event)
        if not needle or needle in text:
            found.append((key, label, detail))
            if len(found) == 400:
                break
    return tuple(found)


def group_choices(snapshot, query, stop_event):
    if snapshot is None:
        return ()
    needle, rows = query.strip().casefold(), []
    for index, group in enumerate(snapshot.item_groups):
        if index % 128 == 0:
            raise_if_cancelled(stop_event)
        if not needle or needle in group.name.casefold():
            rows.append((group.key, group.name))
    rows.sort(key=lambda row: row[1].casefold())
    return tuple(rows[:200])


def recipe_choices(snapshot, index, template_key, inherited, query, stop_event):
    from cdmw.services.new_item_recipes import connected_recipe_keys
    if index is None or snapshot is None or template_key not in snapshot.rows:
        return ()
    raise_if_cancelled(stop_event)
    keys = connected_recipe_keys(snapshot.rows[template_key], snapshot.multichange_rows, index.recipes,
                                 index.rewards, related_keys=index.recipe_items.get(template_key, ())) if inherited else index.recipes
    needle, result = query.strip().casefold(), []
    for position, key in enumerate(keys):
        if position % 64 == 0:
            raise_if_cancelled(stop_event)
        source = index.recipes.get(key)
        name = source.name if source else snapshot.multichange_rows[key].name
        if needle and needle not in f"{key} {name}".casefold():
            continue
        supported = source is not None and all(r in index.rewards for r in source.reward_keys + source.additional_reward_keys)
        result.append((f"{name} · {key}" + ("" if supported else " · unsupported"), key))
        if len(result) == 250:
            break
    return tuple(result)


def reward_details(snapshot, index, value, stop_event):
    key, position, use_key, reward_key = value
    names = snapshot.item_names()
    rows = []
    for number, entry in enumerate(index.rewards[reward_key].entries):
        raise_if_cancelled(stop_event)
        rows.append((f"{names.get(entry.item_key,str(entry.item_key))} · {entry.minimum}–{entry.maximum} · +{entry.enhancement}", number))
    consumers = []
    for number, (item, _position, _use, reward) in enumerate(index.consumers):
        if number % 128 == 0:
            raise_if_cancelled(stop_event)
        if reward == reward_key:
            consumers.append(names.get(item, str(item)))
    records = index.uses[use_key].conditions
    details = f"Reward {reward_key} · {len(consumers)} indexed consumer(s) · {len(records)} preserved use condition(s)"
    conditions = ", ".join(record.hex(" ") for record in records) or "—"
    tooltip = (f"ItemInfo {key}, use position {position}, ItemUseInfo {use_key}. This consumer gets owned copies; other consumers keep their definitions.\n"
               f"Consumers: {', '.join(consumers)}\nUse condition records: {conditions}")
    return tuple(rows), details, tooltip
