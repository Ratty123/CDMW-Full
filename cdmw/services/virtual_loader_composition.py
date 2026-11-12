"""Compose item packages into one private view; Send to DMM writes the result as a mod.

Nothing here writes the installation.
"""

from cdmw.domain.cancellation import raise_if_cancelled
from cdmw.domain.virtual_loader import VirtualLoaderError
from cdmw.services import archive_overlay_manager as overlays
from cdmw.services.independent_item_install import resolve_items
from cdmw.services.independent_mod_package import package_operations
from cdmw.services.independent_texture_package import package_texture_requirements
from cdmw.services.independent_item_package import MAX_TOTAL
from cdmw.services.independent_item_compatibility import compose_underlay, _external_table
from cdmw.services.mod_merge_service import _group
from cdmw.services.virtual_loader_state import target, read_optional


def compose_packages(packages, folders, root, *, stop_event=None, on_log=None, read_entry=None, progress=None):
    """Compose resolved item packages and mod folders into final game files, without writing anything.

    Returns the resolution, the changed files by path, their archive storage flags and the
    texture registry. Apply serves these files; Send to DMM writes them as one mod.
    """
    if progress is None:
        def progress(_value, _detail):
            raise_if_cancelled(stop_event)
    resolved = resolve_items(packages, root, target='virtual', folders=folders,
                             stop_event=stop_event, on_log=on_log, read_entry=read_entry,
                             on_progress=lambda value, total, detail: progress(3 + 62 * value // max(1, total), detail))
    progress(66, 'Composing shared game records…')
    sent = {package.identity for package, _ in resolved.contributions}
    # Sent to DMM, an item's overlay left from an earlier version is replaced by the item itself.
    layers = [(layer, resolved.decoded[layer['id']]) for layer in resolved.state['layers']
              if layer.get('independent_identity') not in sent]
    # These are transient composition descriptors, never overlay ownership rows.
    virtual_layers = [({'id': package.identity, 'label': package.title, 'active': True, 'dependencies': [],
                        'item_keys': list(resolved.registry['items'][package.identity]['values'].get('iteminfo', {}).values()),
                        'independent_identity': package.identity, 'independent_digest': package.digest,
                        'independent_operations': package_operations(package),
                        'independent_textures': package_texture_requirements(package)}, changes)
                      for package, changes in resolved.contributions]
    baseline, flags, meta = {}, {}, set()
    for _layer, changes in (*layers, *virtual_layers):
        for path, change in changes.items():
            baseline.setdefault(path, change['before'])
            flags[path] = change['flags']
            if change['meta']:
                meta.add(path)
    underlay, _, _ = compose_underlay(root, resolved.state, resolved.pending, (*layers, *virtual_layers), baseline,
        stop_event=stop_event, on_log=on_log, context=(resolved.external, resolved.baseline),
        virtual_identities={package.identity for package, _ in resolved.contributions})
    current, _ = overlays.compose_layer_payloads((*layers, *virtual_layers), underlay,
                                                stop_event=stop_event, on_log=on_log)
    from cdmw.domain.archives.iteminfo_composition import required_field_files
    from cdmw.domain.archives.texture_composition import required_texture_files
    texture_paths = required_texture_files((*layers, *virtual_layers))
    required = required_field_files((*layers, *virtual_layers), current) | texture_paths
    files = {p: data for p, data in current.items() if p not in meta and data is not None and (data != underlay[p] or p in required)}
    # Selected, unmounted mod files must be present even when no item touches
    # them. Mounted foreign files remain underlay unless composition changes them.
    selected = {p for p, providers in resolved.external.providers.items() if any(label in {str(f) for f in folders} for label, _ in providers)}
    for paths in sorted({_group(p) for p in selected}):
        raise_if_cancelled(stop_event)
        values = (_external_table(resolved.external, paths, resolved.baseline, stop_event) if len(paths) == 2 else
                  {paths[0]: resolved.external.payload(paths[0], stop_event)})
        for path, data in values.items():
            if path in current:
                data = current[path]
            if data is not None:
                files[path] = data
    if sum(len(data) for data in files.values()) > MAX_TOTAL:
        raise VirtualLoaderError('The composed virtual profile exceeds its supported size.')
    # Reuse the established texture registry encoder, including its collision checks.
    pathc = current.get('meta/0.pathc', read_optional(target(root, 'meta/0.pathc')))
    # The texture adapter already verified each existing direct registry entry and
    # required an unchanged DDS descriptor. Equal loose contributors share that
    # final payload; registering it again would create an unsupported registry edit.
    textures = [p for p in selected if p.endswith('.dds') and p not in texture_paths]
    if textures:
        from cdmw.core.pathc_format import parse_pathc, register_dds, encode_pathc
        if pathc is None:
            raise VirtualLoaderError('New textures require a verified game texture registry.')
        table = parse_pathc(pathc)
        for path in sorted(textures):
            table = register_dds(table, path, files[path])
        pathc = encode_pathc(table)
    return resolved, files, flags, pathc


