"""Build a complete private archive view without writing the mounted installation."""
import hashlib
from pathlib import Path
from uuid import uuid4

from cdmw.core.archive_overlay import OverlayFile, build_overlay_archive
from cdmw.services.archive_overlay_install import _processed_payload
from cdmw.core.papgt_format import PAPGT_DEFAULT_FLAGS, papgt_with_directory
from cdmw.domain.cancellation import raise_if_cancelled
from cdmw.domain.virtual_loader import PreparedSnapshot, VirtualLoaderError, VirtualProfile
from cdmw.services import archive_overlay_manager as overlays
from cdmw.services.independent_item_install import resolve_items
from cdmw.services.independent_item_package import canonical, digest, MAX_TOTAL
from cdmw.services.independent_item_compatibility import compose_underlay, _external_table
from cdmw.services.mod_merge_service import _group
from cdmw.services.virtual_loader_state import FORMAT, PROFILE_PATH, target, read_optional


def hash_file(path, stop_event=None):
    result = hashlib.sha256()
    with Path(path).open('rb') as source:
        while chunk := source.read(1024 * 1024):
            raise_if_cancelled(stop_event)
            result.update(chunk)
    return result.hexdigest()


def prepare_profile(profile: VirtualProfile, root, *, stop_event=None, on_log=None, read_entry=None):
    root = Path(root).resolve()
    if len(profile.mods) > 128:
        raise VirtualLoaderError('Select at most 128 external mod folders.')
    packages = tuple(Path(path).resolve() for path in profile.packages)
    folders = tuple(Path(path).resolve() for path in profile.mods)
    if len(set(packages)) != len(packages) or len(set(folders)) != len(folders):
        raise VirtualLoaderError('The virtual selection contains duplicate paths.')
    original_packages = tuple((str(path), hash_file(path, stop_event)) for path in packages)
    profile_before = read_optional(target(root, PROFILE_PATH))
    resolved = resolve_items(packages, root, target='virtual', folders=folders,
                             stop_event=stop_event, on_log=on_log, read_entry=read_entry)
    layers = [(layer, resolved.decoded[layer['id']]) for layer in resolved.state['layers']]
    # These are transient composition descriptors, never overlay ownership rows.
    virtual_layers = [({'id': package.identity, 'label': package.title, 'active': True, 'dependencies': [],
                        'item_keys': list(resolved.registry['items'][package.identity]['values']['iteminfo'].values())}, changes)
                      for package, changes in resolved.contributions]
    baseline, flags, meta = {}, {}, set()
    for _layer, changes in (*layers, *virtual_layers):
        for path, change in changes.items():
            baseline.setdefault(path, change['before'])
            flags[path] = change['flags']
            if change['meta']:
                meta.add(path)
    underlay, _ = compose_underlay(root, resolved.state, resolved.pending, layers, baseline,
        stop_event=stop_event, on_log=on_log, context=(resolved.external, resolved.baseline))
    current, _ = overlays.compose_layer_payloads((*layers, *virtual_layers), underlay,
                                                stop_event=stop_event, on_log=on_log)
    files = {p: data for p, data in current.items() if p not in meta and data is not None and data != underlay[p]}
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
    textures = [p for p in selected if p.endswith('.dds')]
    if textures:
        from cdmw.core.pathc_format import parse_pathc, register_dds, encode_pathc
        if pathc is None:
            raise VirtualLoaderError('New textures require a verified game texture registry.')
        table = parse_pathc(pathc)
        for path in sorted(textures):
            table = register_dds(table, path, files[path])
        pathc = encode_pathc(table)
    mount = target(root, 'meta/0.papgt').read_bytes()
    name = resolved.state['directory']
    output = {'meta/0.papgt': mount}
    if files:
        entries = [OverlayFile(path, _processed_payload(data, compression_type=flags.get(path, 0) & 15,
                      encrypted=bool(flags.get(path, 0) >> 4), basename=path.rsplit('/', 1)[-1]), len(data), flags.get(path, 0))
                   for path, data in sorted(files.items())]
        archive = build_overlay_archive(entries, stop_event=stop_event, on_log=on_log)
        output.update({name + '/0.pamt': archive.pamt_bytes, name + '/0.paz': archive.paz_bytes,
                       'meta/0.papgt': papgt_with_directory(mount, name, archive.pamt_checksum, flags=PAPGT_DEFAULT_FLAGS, first=True)})
    if pathc is not None:
        output['meta/0.pathc'] = pathc
    from cdmw.services.new_item_provenance import SourceRevision
    revisions = (resolved.baseline.provenance.capture(), *resolved.revisions)
    payloads = {p.entry.identity: p for r in revisions for p in r.payloads}
    pinned = {p: stamp for r in revisions for p, stamp in r.files}
    revision = SourceRevision(tuple(payloads.values()), tuple(pinned.items()), revisions[0].reader)
    revision.validate(stop_event)
    resolved.external.validate(stop_event)
    # Persistent hashes permit complete revalidation after restart; no author IDs
    # or stale source stamps are accepted as launch authority.
    source_paths = dict.fromkeys(path for path, stamp in (*revision.files, *resolved.external.tracker.capture().files) if stamp is not None)
    sources = {str(path): hash_file(path, stop_event) for path in source_paths}
    sources.update(original_packages)
    observed = (*resolved.observed, (PROFILE_PATH, profile_before))
    generation = uuid4().hex
    data = {'format': FORMAT, 'generation': generation,
            'items': {package.identity: {k: resolved.registry['items'][package.identity][k] for k in ('digest', 'binding_hash')}
                      for package, _ in resolved.contributions},
            'packages': [str(p) for p in packages], 'mods': [str(f) for f in folders],
            'files': {p: digest(raw) for p, raw in output.items()},
            'sources': sorted(sources.items()),
            'inventories': [(str(folder), inventory) for folder, inventory in resolved.external.inventories],
            'observed': [(p, digest(raw) if raw is not None else None) for p, raw in resolved.observed
                         if p not in ('.cdmw/independent-items.json', PROFILE_PATH)]}
    for path, expected in original_packages:
        if hash_file(path, stop_event) != expected:
            raise VirtualLoaderError('A selected package changed during preparation.')
    revision.validate(stop_event)
    resolved.external.validate(stop_event)
    overlays._verify_observed_state(root, observed, 'during virtual preparation')
    summary = (*resolved.summary, *(f'{title}: item {key}' for _, title, key, _ in resolved.rows),
               f'{len(folders)} external mod folder(s); {len(files)} composed game file(s).',
               'Original game archives will not be changed. Launch remains subject to runtime validation.')
    retained = tuple((p.rsplit('/', 1)[1], value) for p, value in resolved.pending.items() if p.endswith('.cditem'))
    return PreparedSnapshot(root, generation, tuple(output.items()), canonical(resolved.registry), canonical(data),
                            observed, revision, resolved.external, summary, retained)
