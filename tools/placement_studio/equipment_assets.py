"""Explicit prefab mesh/socket associations, independent of filename conventions."""
from dataclasses import dataclass, replace

from cdmw.core.prefab_binary import decode_prefab_binary


@dataclass(frozen=True)
class EquipmentModel:
    mesh: str
    sockets: str
    prefab: str
    shrink_tag: str = ''


def prefab_models(data, path=''):
    doc = decode_prefab_binary(data)
    if not doc.walk_complete or doc.inferred_objects:
        raise ValueError(doc.walk_note or 'Prefab component identity is unresolved')
    result = []
    for obj in doc.objects:
        if obj.component_type != 'SkinnedMeshComponent':
            continue
        values = {k: v.text.replace('\\', '/').lower() for k, v in obj.values}
        mesh = values.get('_skinnedMeshFile', values.get('_skinnedMeshFileName', ''))
        sockets = values.get('_socketFileName', '')
        if mesh.endswith('.pac') and sockets.endswith('.sockets.xml'):
            authored = {k:v.text for k,v in obj.values}
            result.append(EquipmentModel(mesh, sockets, path, authored.get('_shrinkTag','')))
    return tuple(result)


def model_variants(weapons, models):
    """Retain a socket template while giving every explicitly bound mesh its own row."""
    by_socket = {}
    for model in models:
        by_socket.setdefault(model.sockets, {})[model.mesh] = model
    result = []
    for weapon in weapons:
        variants = by_socket.get(weapon.game_path, {})
        if not variants:
            result.append(weapon)
            continue
        for path, model in sorted(variants.items()):
            identity = path.rsplit('/', 1)[-1].removesuffix('.pac')
            # Preserve the socket's authored hand/case; the mesh path stays explicit.
            suffix = '_in' if weapon.is_case else ''
            stem = weapon.weapon_id.removesuffix('_in')
            if stem.endswith(('_r', '_l')):
                suffix = stem[-2:] + suffix
            if suffix and not identity.endswith(suffix):
                identity += suffix
            result.append(replace(weapon, weapon_id=identity, mesh_path=path, prefab_path=model.prefab, shrink_tag=model.shrink_tag))
    return sorted(result, key=lambda w: w.weapon_id)


# ── which rows and models read one socket file ───────────────────────

#: What the user calls a weapon type whose every model reads one shared socket file. All round
#: shields read `cd_phm_03_shield_0001`, all tower shields `cd_phm_03_towershield_0001` and all
#: kite shields `cd_phm_03_kiteshield_0001`, so a change to one file moves every model of it.
TYPE_LABELS = {
    'shield': 'round shield',
    'towershield': 'tower shield',
    'kiteshield': 'kite shield',
}


def socket_file_kind(game_path):
    """`.../cd_phm_03_towershield_0001.sockets.xml` -> `towershield`, or '' when unnamed.

    The kind is the token after the two-digit category, the same token the slot picker matches
    on (`cd_phw_01_sword_0001` -> `sword`).
    """
    name = str(game_path or '').replace('\\', '/').rsplit('/', 1)[-1].lower()
    stem = name.removesuffix('.sockets.xml')
    tokens = stem.split('_')
    if len(tokens) > 3 and tokens[0] == 'cd' and len(tokens[2]) == 2 and tokens[2].isdigit():
        return tokens[3]
    return ''


def type_label(game_path):
    """`tower shield` for the tower shields' file; otherwise the file's kind, or ''."""
    kind = socket_file_kind(game_path)
    return TYPE_LABELS.get(kind, kind)


def _hands_of_file(game_path):
    path = str(game_path or '').lower()
    if '1_onehandweapon' in path:
        return '1h'
    if '2_twohandweapon' in path:
        return '2h'
    return ''


def rows_reading_file(game_path, rows):
    """Of `rows` (descriptor rows naming one child socket), the ones that read this file.

    A child socket is looked up in the socket file of the item that hangs, so two rows naming
    `Spine2_B_Shield_ChildSocket` share nothing when one hangs round shields and the other
    tower shields. A row reads a file when it agrees with it on:

    * case: an `_in` file is the sheath or case, read by an `_IN` row, and only by one;
    * hands: a `1_onehandweapon` file by a one-hand row, `2_twohandweapon` by a two-hand row;
    * kind: the row's weapon type is the file's kind (`TowerShield` reads `towershield`), or
      the end of it when no row names the kind itself (`Shield` reads `kiteshield`).

    Each rule only narrows. When a rule would leave no row, the rows before it are kept, so a
    file the rules cannot place counts every row that names the socket, as before: counting
    too many costs a clone, counting too few moves somebody else's item.
    """
    rows = list(rows)
    path = str(game_path or '')
    stem = path.replace('\\', '/').rsplit('/', 1)[-1].lower().removesuffix('.sockets.xml')
    is_case = stem.endswith('_in')
    hands = _hands_of_file(path)
    kind = socket_file_kind(path)

    def narrowed(current, keep):
        kept = [row for row in current if keep(row)]
        return kept or current

    current = narrowed(rows, lambda row: row.is_case_row == is_case)
    if hands:
        wanted = {'1h': 'main_weapon', '2h': 'two_hand_weapon'}[hands]
        current = narrowed(current, lambda row: row.category in (wanted, 'tool', 'other'))
    if kind:
        exact = [row for row in current if row.weapon_type.lower() == kind]
        if exact:
            current = exact
        else:
            endings = [row for row in current
                       if row.weapon_type and kind.endswith(row.weapon_type.lower())]
            if endings:
                longest = max(len(row.weapon_type) for row in endings)
                current = [row for row in endings if len(row.weapon_type) == longest]
    return tuple(dict.fromkeys(row.part_name for row in current))


def models_reading_file(models, game_path):
    """The distinct meshes whose prefab names this socket file, from `prefab_models`."""
    wanted = str(game_path or '').replace('\\', '/').lower()
    return tuple(sorted({model.mesh for model in models if model.sockets == wanted}))
