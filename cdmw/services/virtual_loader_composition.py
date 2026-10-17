"""Build a complete private archive view without writing the mounted installation."""
import hashlib
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
import threading
import time
from uuid import uuid4

from cdmw.core.archive_overlay import OverlayFile, build_overlay_archive
from cdmw.services.archive_overlay_install import _processed_payload
from cdmw.core.papgt_format import PAPGT_DEFAULT_FLAGS, papgt_with_directory
from cdmw.domain.cancellation import raise_if_cancelled
from cdmw.domain.new_item.compilation import compiler_stamp, compilation_record
from cdmw.domain.virtual_loader import PreparedSnapshot, VirtualLoaderError, VirtualProfile
from cdmw.services import archive_overlay_manager as overlays
from cdmw.services.independent_item_install import resolve_items
from cdmw.services.independent_mod_package import package_operations
from cdmw.services.independent_texture_package import package_texture_requirements
from cdmw.services.independent_item_package import canonical, digest, MAX_MANIFEST, MAX_TOTAL
from cdmw.services.independent_item_compatibility import compose_underlay, _external_table
from cdmw.services.mod_merge_service import _group
from cdmw.services.virtual_loader_state import FORMAT, PROFILE_PATH, target, read_optional


def hash_file(path, stop_event=None, *, on_read=None):
    result = hashlib.sha256()
    with Path(path).open('rb') as source:
        buffer = bytearray(1024 * 1024)
        view = memoryview(buffer)
        while count := source.readinto(buffer):
            raise_if_cancelled(stop_event)
            result.update(view[:count])
            if on_read:
                on_read(count)
    return result.hexdigest()


def _hash_sources(paths, stop_event=None, on_progress=None):
    """Hash every source afresh with bounded I/O; never reuse a previous digest."""
    paths = tuple(paths)
    result, sizes = {}, {}
    for path in paths:
        raise_if_cancelled(stop_event)
        try:
            sizes[path] = Path(path).stat().st_size
        except OSError as exc:
            raise VirtualLoaderError(f'Cannot read source: {path}. Apply changes again.') from exc
    total = sum(sizes.values())
    checked, last_report = 0, 0.0
    started = time.monotonic()
    abort = threading.Event()
    lock = threading.Lock()

    class Cancellation:
        def is_set(self):
            return abort.is_set() or (stop_event is not None and stop_event.is_set())

    def read_progress(path, count):
        nonlocal checked, last_report
        with lock:
            checked += count
            now = time.monotonic()
            if on_progress and (now - last_report >= 0.1 or checked >= total):
                detail = (f'Verifying sources: {min(checked, total):,} / {total:,} bytes, '
                          f'{now - started:.1f} s; {Path(path).parent.name}/{Path(path).name}')
                on_progress(min(checked, total), total, detail)
                last_report = now

    def read_source(path):
        try:
            return hash_file(path, Cancellation(), on_read=lambda count: read_progress(path, count))
        except OSError as exc:
            raise VirtualLoaderError(f'Cannot read source: {path}. Apply changes again.') from exc

    with ThreadPoolExecutor(max_workers=2, thread_name_prefix='cdmw-source-hash') as workers:
        pending = {workers.submit(read_source, path): path for path in paths}
        try:
            for future in as_completed(pending):
                raise_if_cancelled(stop_event)
                result[str(pending[future])] = future.result()
        finally:
            abort.set()
            for future in pending:
                future.cancel()
    return result


def prepare_profile(profile: VirtualProfile, root, *, stop_event=None, on_log=None, read_entry=None, on_progress=None):
    def progress(value, detail):
        raise_if_cancelled(stop_event)
        if on_progress:
            on_progress(value, 100, detail)
    progress(0, 'Checking item packages…')
    root = Path(root).resolve()
    if len(profile.mods) > 128:
        raise VirtualLoaderError('Select at most 128 external mod folders.')
    packages = tuple(Path(path).resolve() for path in profile.packages)
    folders = tuple(Path(path).resolve() for path in profile.mods)
    disabled_packages = tuple(Path(path).resolve() for path in profile.disabled_packages)
    disabled_mods = tuple(Path(path).resolve() for path in profile.disabled_mods)
    if any(len(paths) > 128 for paths in (packages + disabled_packages, folders + disabled_mods)):
        raise VirtualLoaderError('Select at most 128 item packages and 128 mod folders, including disabled entries.')
    if any(len(set(paths)) != len(paths) for paths in (packages + disabled_packages, folders + disabled_mods)):
        raise VirtualLoaderError('The virtual selection contains duplicate paths.')
    original_packages = tuple((str(path), hash_file(path, stop_event)) for path in packages)
    profile_before = read_optional(target(root, PROFILE_PATH))
    resolved = resolve_items(packages, root, target='virtual', folders=folders,
                             stop_event=stop_event, on_log=on_log, read_entry=read_entry,
                             on_progress=lambda value, total, detail: progress(3 + 62 * value // max(1, total), detail))
    progress(66, 'Composing shared game records…')
    layers = [(layer, resolved.decoded[layer['id']]) for layer in resolved.state['layers']]
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
    mount = target(root, 'meta/0.papgt').read_bytes()
    name = resolved.state['directory']
    from cdmw.services.virtual_loader_sources import profile_revision, catalogue_records
    revision = profile_revision(resolved)
    revision.validate(stop_event)
    resolved.external.validate(stop_event)
    # Persistent hashes permit complete revalidation after restart; no author IDs
    # or stale source stamps are accepted as launch authority.
    source_paths = dict.fromkeys(path for path, stamp in (*revision.content_files, *resolved.external.tracker.capture().content_files) if stamp is not None)
    progress(70, 'Verifying source file integrity…')
    sources = _hash_sources(source_paths, stop_event,
        lambda value, total, detail: progress(70 + 16 * value // max(1, total), detail))
    for path, checksum in (*revision.indexes, *resolved.external.tracker.capture().indexes):
        if sources.get(str(path)) != checksum:
            raise VirtualLoaderError(f'Source index changed since parsing: {path}.')
    sources.update(original_packages)
    # Cache lookup happens only after current source verification. Its key omits
    # outputs, which have not been built, and includes the complete compiler,
    # package, binding, provider, ordering, runtime and dependency inputs.
    from cdmw.services.independent_item_compilation import package_record
    from cdmw.services.virtual_loader_cache import make_cache_record, load_previous_cache
    observed_hashes = [(p, digest(raw) if raw is not None else None) for p, raw in resolved.observed
                       if p not in ('.cdmw/independent-items.json', PROFILE_PATH)]
    catalogue = catalogue_records(revision)
    inventories = [(str(folder), inventory) for folder, inventory in resolved.external.inventories]
    compilation_args = dict(scope='virtual-profile',
        packages=[package_record(package, resolved.pending[f'.cdmw/independent-items/{package.identity}-{package.digest}.cditem'])
                  for package, _ in resolved.contributions], sources=sources,
        allocations={identity: row['binding_hash'] for identity, row in resolved.registry['items'].items()},
        order=[layer.get('independent_identity', layer['id']) for layer in resolved.state['layers'] if layer['active']]
              + [package.identity for package, _ in resolved.contributions] + [str(f) for f in folders],
        runtime_abi='CDVFS3', providers=dict(observed_hashes), links=resolved.links)
    cache_record = make_cache_record(compilation_record(**compilation_args, outputs={}),
        directory=name, files=files, flags=flags, mount=mount, pathc=pathc,
        catalogue=catalogue, inventories=inventories,
        resource_digests=getattr(resolved, 'resource_digests', None), stop_event=stop_event)
    progress(87, 'Checking the previous private view…')
    cache = (load_previous_cache(root, profile_before, current_record=cache_record, stop_event=stop_event, on_log=on_log)
             if cache_record is not None else None)
    output = cache.whole_output(cache_record, mount=mount, pathc=pathc, stop_event=stop_event) if cache else None
    reused, cache_summary = 0, ()
    if output is not None:
        cache_summary = (f'Reused verified private archives for {len(files)} unchanged game file(s).',)
        progress(97, 'Reused the verified private view.')
    else:
        output = {'meta/0.papgt': mount}
        progress(89, 'Building private game archives…')
        if files:
            entries = []
            for path, raw in sorted(files.items()):
                raise_if_cancelled(stop_event)
                file_flags = flags.get(path, 0)
                transformed = bool(file_flags >> 4) or (file_flags & 15) == 2
                payload = (cache.resource_payload(path, cache_record['resources'][path], stop_event=stop_event)
                           if cache and transformed else None)
                if payload is None:
                    payload = _processed_payload(raw, compression_type=file_flags & 15,
                        encrypted=bool(file_flags >> 4), basename=path.rsplit('/', 1)[-1])
                else:
                    reused += 1
                entries.append(OverlayFile(path, payload, len(raw), file_flags))
            archive = build_overlay_archive(entries, stop_event=stop_event, on_log=on_log)
            output.update({name + '/0.pamt': archive.pamt_bytes, name + '/0.paz': archive.paz_bytes,
                           'meta/0.papgt': papgt_with_directory(mount, name, archive.pamt_checksum,
                                                             flags=PAPGT_DEFAULT_FLAGS, first=True)})
        if pathc is not None:
            output['meta/0.pathc'] = pathc
        if reused:
            cache_summary = (f'Reused verified processed data for {reused} of {len(files)} game file(s).',)
    observed = (*resolved.observed, (PROFILE_PATH, profile_before))
    generation = uuid4().hex
    data = {'format': FORMAT, 'generation': generation, 'compiler': compiler_stamp(),
            'items': {package.identity: {k: resolved.registry['items'][package.identity][k] for k in ('digest', 'binding_hash')}
                      for package, _ in resolved.contributions},
            'packages': [str(p) for p in packages], 'mods': [str(f) for f in folders],
            'files': {p: digest(raw) for p, raw in output.items()},
            'sources': sorted(sources.items()),
            'catalogue': catalogue, 'inventories': inventories, 'observed': observed_hashes}
    if disabled_packages or disabled_mods:
        data['disabled_packages'] = [str(path) for path in disabled_packages]
        data['disabled_mods'] = [str(path) for path in disabled_mods]
    data['compilation'] = compilation_record(**compilation_args, outputs=dict(data['files']))
    if cache_record is not None:
        data['build_cache'] = cache_record
        if len(canonical(data)) > MAX_MANIFEST:
            del data['build_cache']
    progress(98, 'Rechecking preparation inputs…')
    for path, expected in original_packages:
        if hash_file(path, stop_event) != expected:
            raise VirtualLoaderError(f'A selected package changed during preparation: {path}. Apply changes again.')
    revision.validate(stop_event)
    resolved.external.validate(stop_event)
    overlays._verify_observed_state(root, observed, 'during virtual preparation')
    summary = (*resolved.summary, *(f'{title}: item {key}' if key is not None else f'{title}: existing records' for _, title, key, _ in resolved.rows),
               f'{len(folders)} external mod folder(s); {len(files)} composed game file(s).',
               *cache_summary,
               'Original game archives will not be changed. Launch remains subject to runtime validation.')
    retained = tuple((p.rsplit('/', 1)[1], value) for p, value in resolved.pending.items() if p.endswith('.cditem'))
    progress(100, 'Virtual profile prepared.')
    return PreparedSnapshot(root, generation, tuple(output.items()), canonical(resolved.registry), canonical(data),
                            observed, revision, resolved.external, summary, retained)

