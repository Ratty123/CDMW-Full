"""Optional equipment bonus catalogue and validated ItemInfo references."""
from dataclasses import dataclass, replace
from typing import Mapping

from cdmw.core.buffinfo_table import EquipmentBuff, BuffInfoError, parse_equipment_buff, encode_equipment_buff
from cdmw.core.structured_binary_editor import parse_pabgh_table
from cdmw.domain.cancellation import raise_if_cancelled


@dataclass(frozen=True)
class EquipmentBonusIndex:
    buffs: Mapping[int, EquipmentBuff]
    unsupported: Mapping[int, str]
    presets: tuple[tuple[int, str, tuple[tuple[int, int], ...]], ...]


def signed_parameter(raw: int) -> int:
    return raw - 0x100000000 if raw >= 0x80000000 else raw


def load_equipment_bonuses(snapshot, *, stop_event=None) -> EquipmentBonusIndex:
    cached = snapshot._authoring_indexes.get("bonuses")
    if cached is not None:
        return cached
    if snapshot.sources is None or "buffinfo" not in snapshot.sources.tables:
        raise ValueError("The active game generation has no complete BuffInfo table.")
    used = {key for row in snapshot.rows.values() if row.equip_type_key
            for level in row.enchant_levels for key in level.equip_buffs}
    body_entry, head_entry = snapshot.sources.tables["buffinfo"]
    body, head = snapshot.payload(body_entry.path), snapshot.payload(head_entry.path)
    table = parse_pabgh_table(head, payload=body)
    buffs, unsupported = {}, {}
    for row, start, end in table.row_spans(len(body)):
        raise_if_cancelled(stop_event, "Bonus index cancelled.")
        if row.row_id not in used:
            continue
        try:
            buff = parse_equipment_buff(body[start:end])
            if buff.key != row.row_id or encode_equipment_buff(buff) != body[start:end]:
                raise BuffInfoError("BuffInfo round trip failed")
            if buff.blocked:
                raise BuffInfoError("BuffInfo is blocked by the game")
            buffs[row.row_id] = buff
        except (ValueError, UnicodeError) as exc:
            unsupported[row.row_id] = str(exc)
    for key in used - buffs.keys() - unsupported.keys():
        unsupported[key] = "BuffInfo reference is missing"
    presets = []
    for row in snapshot.rows.values():
        if not row.equip_type_key:
            continue
        for level in row.enchant_levels:
            values = tuple((key, signed_parameter(value)) for key, value in zip(level.equip_buffs, level.equip_buff_extras))
            if values and all(key in buffs and buffs[key].supports(value) for key, value in values):
                presets.append((row.key, f"{snapshot.item_names().get(row.key, row.string_key)} · +{level.level}", values))
                break
    result = EquipmentBonusIndex(buffs, unsupported, tuple(presets))
    snapshot._authoring_indexes["bonuses"] = result
    return result


def apply_equipment_bonuses(levels, overrides, index):
    if overrides is None:
        return levels
    if not overrides:
        return [replace(level, equip_buffs=(), equip_buff_extras=()) for level in levels]
    result = list(levels)
    seen = set()
    for selection in overrides:
        if selection.level in seen or not 0 <= selection.level < len(result):
            raise ValueError("Bonus enhancement levels must be unique and present in the item.")
        seen.add(selection.level)
        keys = [bonus.buff_key for bonus in selection.bonuses]
        if len(keys) != len(set(keys)):
            raise ValueError("A bonus may occur only once per enhancement level.")
        for bonus in selection.bonuses:
            buff = index.buffs.get(bonus.buff_key)
            if buff is None or not buff.supports(bonus.parameter):
                raise ValueError(f"Unsupported equipment bonus or level: {bonus.buff_key}, {bonus.parameter}")
        result[selection.level] = replace(result[selection.level], equip_buffs=tuple(keys),
            equip_buff_extras=tuple(bonus.parameter & 0xFFFFFFFF for bonus in selection.bonuses))
    return result
