"""Lower new part registrations to DMM's additive PAPPT intent contract.

The public dmm-parser PAPPT JSON shape is one record (key 0), with `primary`
and `secondary` arrays. DMM 4.4.0 added list_append for this table. Never ship
a whole part table: other mods own private heads and refitted part records.
"""
from cdmw.core.pappt_format import parse_pappt

PART_TABLE = "character/bin__/partprefabtable.pappt"


def part_operations(files, read_game):
    payload = files.get(PART_TABLE)
    if payload is None:
        return dict(files), []
    original = read_game(PART_TABLE)
    if original is None:
        raise ValueError("The game's part table is required to export new parts to DMM.")
    before, after = parse_pappt(original), parse_pappt(payload)
    old, new = before.index(), after.index()
    if len(new) != len(after.records) or len(old) != len(before.records):
        raise ValueError("Duplicate part names cannot be exported to DMM.")
    if (before.reserved != after.reserved or before.tag_prefix != after.tag_prefix
            or before.head_records != after.head_records
            or any(new.get(name) != row for name, row in old.items())):
        raise ValueError("DMM item exports can add parts, but cannot replace existing parts or private heads.")
    intents = []
    for name, row in new.items():
        if name in old:
            continue
        # A registration must belong to an actual prefab emitted by this package.
        if row.prefab_path not in files:
            raise ValueError(f"Part {name!r} has no prefab in this item export; refusing to copy another mod's registration.")
        value = dict(key_a=row.stem, key_b=row.folder, key_c=row.sockets_path,
                     bool_flag=1, asset_id=row.extra, flag=row.flag,
                     children=[dict(sub_key=part.name, sub_flag=part.flag) for part in row.parts])
        intents.append(dict(op="list_append", key=0, field="primary", new=value))
    result = {path: data for path, data in files.items() if path != PART_TABLE}
    return result, [dict(file=PART_TABLE, intents=intents)] if intents else []
