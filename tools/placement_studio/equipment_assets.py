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
