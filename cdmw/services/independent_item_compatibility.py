"""Read-only comparison of independent items with mounted and prospective mods.

Foreign files remain foreign: composition uses their current contents as the
underlay, while journals continue to own only CDMW's additions. A second,
different replacement of one file is ambiguous without its original baseline.
"""
from dataclasses import dataclass, field
from pathlib import Path
import re

from cdmw.core.papgt_format import parse_papgt
from cdmw.domain.archives.overlay_merge import OverlayConflict, _table, merge_overlay_files, owned_item_references
from cdmw.domain.cancellation import RunCancelled, raise_if_cancelled
from cdmw.services.independent_item_package import MAX_BLOB, MAX_TOTAL, _resource_path, digest, unpack_recipe
from cdmw.services.mod_merge_service import _group, _inventory
from cdmw.services.new_item_provenance import SourceTracker


@dataclass(frozen=True)
class CompatibilityFinding:
    status: str
    mods: tuple[str, ...]
    path: str
    detail: str


@dataclass(frozen=True)
class ExternalModRevision:
    """Publication guards without the comparison's large parsed working set."""
    root: Path
    source_revision: object
    archives: tuple
    inventories: tuple

    def validate(self, stop_event=None):
        self.source_revision.validate(stop_event)
        for name, expected in self.archives:
            raise_if_cancelled(stop_event)
            if tuple(sorted(path.name for path in (self.root / name).glob('*.pamt'))) != expected:
                raise OverlayConflict(f'Archive folder changed: {name}. Scan again.')
        for folder, inventory in self.inventories:
            if _inventory(folder, stop_event) != inventory:
                raise OverlayConflict(f'Mod folder changed: {folder}. Scan again.')


@dataclass
class ExternalMods:
    root: Path
    directory: str
    tracker: SourceTracker
    providers: dict = field(default_factory=dict)
    inventories: list = field(default_factory=list)
    findings: list = field(default_factory=list)
    cache: dict = field(default_factory=dict)
    total: int = 0
    archives: dict = field(default_factory=dict)
    snapshot: object = None
    merged: dict = field(default_factory=dict)

    @property
    def paths(self):
        return set(self.providers)

    def payload(self, path, stop_event=None):
        """Return one unambiguous version; never silently choose a load-order winner."""
        if path in self.merged:
            return self.merged[path]
        versions = {}
        for label, source in self.providers.get(path, ()):
            raise_if_cancelled(stop_event, 'Mod comparison cancelled.')
            key = (label, source.entry.identity if source.entry is not None else source.path)
            if key not in self.cache:
                if source.entry is not None:
                    if source.entry.orig_size > MAX_BLOB:
                        raise OverlayConflict(f'{label}: resource exceeds comparison size limit: {path}.')
                    value = self.tracker.read(source.entry)
                else:
                    self.tracker.pin_file(source.path)
                    if source.path.stat().st_size > MAX_BLOB:
                        raise OverlayConflict(f'{label}: resource exceeds comparison size limit: {path}.')
                    value = source.path.read_bytes()
                    self.tracker.pin_file(source.path)
                if len(value) > MAX_BLOB:
                    raise OverlayConflict(f'{label}: resource exceeds comparison size limit: {path}.')
                self.total += len(value)
                if self.total > MAX_TOTAL:
                    raise OverlayConflict('Mod comparison exceeds its memory limit. Compare fewer mods.')
                self.cache[key] = value
            versions.setdefault(self.cache[key], []).append(label)
        if len(versions) > 1:
            combined = self._additive_table(path, stop_event)
            if combined is not None:
                self.merged.update(combined)
                return combined[path]
            names = ', '.join(label for label, _ in self.providers[path])
            raise OverlayConflict(f'{names}: different replacements of {path}; their original baselines are required. Use Merge to compare recorded mod baselines.')
        return next(iter(versions), None)

    def _additive_table(self, path, stop_event):
        """Infer additions only when every shipped row is byte-identical and present."""
        paths = _group(path)
        if self.snapshot is None or len(paths) != 2 or not all(self.snapshot.has_entry(p) for p in paths):
            return None
        original = {p: self.snapshot.payload(p) for p in paths}
        layout, records = _table(original[paths[0]], original[paths[1]])
        baseline = dict(records)
        participants = self.labels(paths)
        current = dict(original)
        for label in participants:
            raise_if_cancelled(stop_event)
            values = {}
            for p in paths:
                sources = [source for owner, source in self.providers.get(p, ()) if owner == label]
                if len(sources) != 1:
                    return None
                source = sources[0]
                key = (label, source.entry.identity if source.entry is not None else source.path)
                if key not in self.cache:
                    # Read only this provider, without recursively resolving its peers.
                    single = ExternalMods(self.root, self.directory, self.tracker, {p: [(label, source)]})
                    self.cache[key] = single.payload(p, stop_event)
                    self.total += single.total
                    if self.total > MAX_TOTAL:
                        raise OverlayConflict('Mod comparison exceeds its memory limit. Compare fewer mods.')
                values[p] = self.cache[key]
            table, records = _table(values[paths[0]], values[paths[1]])
            present = dict(records)
            if ((table.key_width, table.header_size) != (layout.key_width, layout.header_size)
                    or any(present.get(key) != data for key, data in baseline.items())):
                return None
            current = merge_overlay_files(original, values, current)
        return current

    def labels(self, paths):
        return tuple(dict.fromkeys(label for path in paths for label, _ in self.providers.get(path, ())))

    def validate(self, stop_event=None):
        self.capture().validate(stop_event)

    def capture(self):
        return ExternalModRevision(self.root, self.tracker.capture(), tuple(self.archives.items()), tuple(self.inventories))

    def remember(self, state):
        from cdmw.services.archive_overlay_manager import _stamp
        for path, stamp in self.tracker.capture().files:
            if path.is_relative_to(self.root) and path.suffix in ('.pamt', '.paz'):
                relative = path.relative_to(self.root).as_posix()
                if stamp is None or _stamp(path) != list(stamp):
                    raise OverlayConflict(f'{relative} changed during comparison. Scan again.')
                state['sources'][relative] = list(stamp)


def _folder_metadata(external, folder, stop_event):
    """Consume known loose indexes without treating them as game-file overrides."""
    from cdmw.core.pathc_format import parse_pathc

    def read_index(path, parser):
        raise_if_cancelled(stop_event, 'Mod comparison cancelled.')
        external.tracker.pin_file(path)
        if path.stat().st_size > MAX_BLOB:
            raise OverlayConflict(f'External package metadata exceeds its size limit: {path}.')
        data = path.read_bytes()
        external.total += len(data)
        if len(data) > MAX_BLOB or external.total > MAX_TOTAL:
            raise OverlayConflict('External package metadata exceeds the comparison size limit.')
        try:
            parser(data)
        except ValueError as exc:
            raise OverlayConflict(f'Invalid external package metadata {path}: {exc}') from exc
        external.tracker.pin_index(path, digest(data), stop_event)
        return data

    consumed, registry = set(), None
    for base in (folder, folder / 'files'):
        mount = base / 'meta/0.papgt'
        if mount.is_file():
            # Discovery reads this index for the folder's archive order. Keep its
            # original parsed digest even though it is never a deployed payload.
            read_index(mount, parse_papgt)
            consumed.add(mount)
        pathc = base / 'meta/0.pathc'
        if pathc.is_file():
            incoming = read_index(pathc, parse_pathc)
            current = external.root / 'meta/0.pathc'
            if registry is None and current.is_file():
                registry = read_index(current, parse_pathc)
            if registry is None or incoming != registry:
                raise OverlayConflict(f'{folder}: this texture registry requires recorded texture ownership. '
                    'Use Merge with the original CDMW export before selecting this folder.')
            # An exact, validated no-op registry has no replacement to publish.
            # Changed registrations must use the existing ownership-aware merger.
            consumed.add(pathc)
    return consumed


def external_mods(root, state, *, folders=(), read_entry=None, stop_event=None, snapshot=None):
    from cdmw.core.archive_extraction import read_archive_entry_data
    from cdmw.services.new_item_mod_base import ModFolderPayload, mod_folder_payloads
    from cdmw.services.archive_overlay_manager import _target
    root = Path(root).resolve()
    result = ExternalMods(root, state['directory'], SourceTracker(read_entry or (lambda entry: read_archive_entry_data(entry)[0])))
    result.snapshot = snapshot
    mount = _target(root, 'meta/0.papgt')
    result.tracker.pin_file(mount)
    records = parse_papgt(mount.read_bytes())
    result.tracker.pin_file(mount)
    for record in records:
        raise_if_cancelled(stop_event)
        name = record.name
        if not re.fullmatch(r'[A-Za-z0-9_-]+', name):
            raise OverlayConflict(f'Unsupported mounted archive folder for independent items: {name!r}.')
        shipped = len(name) == 4 and name.isascii() and name.isdigit() and int(name) < 36
        if shipped or name == result.directory:
            continue
        group = _target(root, name)
        if group.is_dir():
            result.inventories.append((group, _inventory(group, stop_event)))
        pamts = sorted(group.glob('*.pamt'))
        result.archives[name] = tuple(path.name for path in pamts)
        for pamt in pamts:
            for entry in result.tracker.parse_index(pamt, stop_event=stop_event):
                path = _resource_path(entry.path.lower())
                if not Path(entry.paz_file).resolve().is_relative_to(group):
                    raise OverlayConflict(f'Archive resource escapes its mod folder: {name}.')
                result.providers.setdefault(path, []).append((name, ModFolderPayload(entry=entry)))
    for raw in folders:
        folder = Path(raw).resolve()
        if folder.is_relative_to(root) or root.is_relative_to(folder):
            raise OverlayConflict('Select an external mod folder separate from the game installation.')
        inventory = _inventory(folder, stop_event)
        result.inventories.append((folder, inventory))
        label = str(folder)
        metadata = _folder_metadata(result, folder, stop_event)
        payloads = mod_folder_payloads(folder, stop_event=stop_event,
            parse_index=lambda path: result.tracker.parse_index(path, stop_event=stop_event))
        admitted = False
        for path, source in payloads.items():
            if path.startswith(('.cdmw/', '.cdloader/')):
                continue
            if path.startswith('meta/'):
                if source.entry is None and source.path in metadata:
                    continue
                raise OverlayConflict(f'Unsupported external package metadata: {path} in {folder}.')
            if source.entry is not None and (not Path(source.entry.pamt_path).resolve().is_relative_to(folder)
                                             or not Path(source.entry.paz_file).resolve().is_relative_to(folder)):
                raise OverlayConflict(f'Archive resource escapes its mod folder: {label}.')
            result.providers.setdefault(_resource_path(path), []).append((label, source))
            admitted = True
        # Executable mods and patch instruction formats are not final file payloads.
        unknown = [name for name, *_ in inventory if Path(name).suffix.lower() in ('.asi', '.dll', '.json', '.zip', '.rar', '.7z', '.cditem')
                   and Path(name).name.lower() not in ('manifest.json', 'modinfo.json', 'new-item.json', 'cdmw-compatibility.json', 'cdmw-baseline.zip')]
        if unknown or not admitted:
            result.findings.append(CompatibilityFinding('Unknown', (label,), '',
                'This folder contains runtime code, patch instructions or no supported file payloads. Its effects cannot be certified by a file scan.'))
    return result


def reserved_external_keys(external, snapshot, *, stop_event=None):
    """Reserve observed numeric identities even when the external archive loses priority."""
    reserved = {name: set() for name in ('iteminfo', 'multichangeinfo', 'dropsetinfo', 'effect')}
    for paths in sorted({_group(path) for path in external.paths if len(_group(path)) == 2}):
        name = paths[0].rsplit('/', 1)[-1].split('.')[0]
        if name not in reserved:
            continue
        data = _external_table(external, paths, snapshot, stop_event)
        reserved[name].update(int.from_bytes(key, 'little') for key, _ in _table(data[paths[0]], data[paths[1]])[1])
    return reserved


def _external_table(external, paths, snapshot, stop_event):
    data = {p: external.payload(p, stop_event) for p in paths}
    # Resolving the second half can compose both halves. Do not retain an
    # earlier uncomposed body when only the providers' directories differed.
    data.update({p: external.merged[p] for p in paths if p in external.merged})
    for path in paths:
        other = next(p for p in paths if p != path)
        for label, source in external.providers.get(path, ()):
            if any(owner == label for owner, _ in external.providers.get(other, ())):
                continue
            key = (label, source.entry.identity if source.entry is not None else source.path)
            if not snapshot.has_entry(path) or external.cache[key] != snapshot.payload(path):
                raise OverlayConflict('Both table files are required to verify a changed table.')
        if data[path] is None:
            if not snapshot.has_entry(path):
                raise OverlayConflict(f'{paths[0]}: incomplete external table.')
            data[path] = snapshot.payload(path)
    if paths[0].rsplit('/', 1)[-1] in ('iteminfo.staticinfobody', 'iteminfo.pabgb'):
        labels = ', '.join(external.labels(paths))
        for directory_key, raw in _table(data[paths[0]], data[paths[1]])[1]:
            raise_if_cancelled(stop_event, 'Mod comparison cancelled.')
            number = int.from_bytes(directory_key, 'little')
            if len(raw) < 4:
                raise OverlayConflict(f'{labels}: {paths[0]}: record {number} has no complete ItemInfo key.')
            record_key = int.from_bytes(raw[:4], 'little')
            if record_key != number:
                raise OverlayConflict(f'{labels}: {paths[0]}: ItemInfo directory key {number} '
                    f'differs from record key {record_key}.')
    return data


def _required_keys(package, snapshot, changes):
    """Protect referenced records while retaining the donor's source contract."""
    from cdmw.core.iteminfo_row import parse_iteminfo_row
    from cdmw.core.stringinfo_table import stringinfo_key
    from cdmw.services.independent_mod_package import has_legacy_item
    if not has_legacy_item(package):
        return {'iteminfo': set(), 'equiptypeinfo': set(), 'statusinfo': set()}
    spec, *_ = unpack_recipe(package)
    required = {'iteminfo': set(), 'equiptypeinfo': set(), 'statusinfo': set()}
    template_key = int(spec.template_key)
    references = owned_item_references(changes)
    pending = {template_key} | references
    template = snapshot.rows.get(template_key)
    # The native name map lowercases before hashing. Its ASCII spellings are
    # supported here; an unknown name encoding keeps the original protection.
    source_name = template.string_key if template is not None else ''
    ascii_name = bool(source_name) and source_name.isascii() and '\0' not in source_name
    source_name_hash = stringinfo_key(source_name.lower()) if ascii_name else None
    source_tokens = (template_key.to_bytes(4, 'little'),
                     source_name_hash.to_bytes(4, 'little')) if ascii_name else ()
    source_pattern = re.compile(re.escape(source_name.encode('ascii')), re.IGNORECASE) if ascii_name else None

    def retains_source_identity(raw):
        return not ascii_name or any(token in raw for token in source_tokens) or source_pattern.search(raw) is not None

    added_rows = []
    retained_identity = not ascii_name
    for path, change in changes.items():
        paths = _group(path)
        if len(paths) != 2:
            if change['before'] is None and change['after'] is not None:
                retained_identity |= retains_source_identity(change['after'])
            continue
        if path != paths[0]:
            continue
        head = paths[1]
        if (head not in changes or change['before'] is None or change['after'] is None
                or changes[head]['before'] is None or changes[head]['after'] is None):
            # An absent or removed table is outside this record-copy proof.
            # Its normal owner still decides whether the change is supported.
            retained_identity = True
            continue
        old = dict(_table(change['before'], changes[head]['before'])[1])
        added = [raw for key, raw in _table(change['after'], changes[head]['after'])[1] if key not in old]
        retained_identity |= any(retains_source_identity(raw) for raw in added)
        if path.rsplit('/', 1)[-1] in ('iteminfo.staticinfobody', 'iteminfo.pabgb'):
            added_rows.extend(parse_iteminfo_row(raw) for raw in added)
    rows = list(added_rows)
    while pending:
        key = pending.pop()
        if key in required['iteminfo'] or key not in snapshot.rows:
            continue
        required['iteminfo'].add(key)
        row = snapshot.rows[key]
        rows.append(row)
        outgoing = set(row.socket_items)
        outgoing.update(key for key, _count, _extra in row.add_socket_materials)
        outgoing.update(price.item_key for price in row.price_list)
        outgoing.update(price.item_key for level in row.enchant_levels for price in level.buy_prices)
        references.update(outgoing)
        pending.update(outgoing)
        if key != template_key:
            retained_identity |= retains_source_identity(row.raw)
    for row in rows:
        if row.equip_type_key:
            required['equiptypeinfo'].add(row.equip_type_key)
        for level in row.enchant_levels:
            required['statusinfo'].update(stat.status_key for stat in level.stats)
            required['statusinfo'].update(level.level_stat_keys)
    private_name = 'CDI_' + package.identity
    private_rows = [row for row in added_rows if row.string_key == private_name
                    and row.key not in snapshot.rows]
    if (len(private_rows) == 1 and not retained_identity and template_key not in references
            and stringinfo_key(private_name.lower()) != source_name_hash):
        # This proves only the clone's distinct record identity. Keep the donor's
        # transitive equipment, stat, perk and resource guards. Exact author-source
        # hashes are still checked by check_package_dependencies.
        required['iteminfo'].discard(template_key)
    return required


def _texture_dependency_requirements(package, snapshot, *, stop_event=None):
    """Keep declared resource reads exact; scope a hybrid's adapter exception."""
    from cdmw.services.independent_texture_package import package_texture_requirements
    from cdmw.services.independent_mod_package import has_legacy_item
    required = {path: checksum for path, checksum in package.dependencies.items() if path.endswith('.dds')}
    targets = {row['path'] for row in package_texture_requirements(package)}
    if not targets:
        return required
    legacy_reads = set()
    if has_legacy_item(package):
        # Global package dependencies include the texture module's source reads.
        # Re-run only the retained legacy recipe with fresh payload tracking so
        # an unrelated texture target is not mistaken for a legacy byte consumer.
        from dataclasses import replace
        from cdmw.services.independent_item_package import unpack_recipe
        from cdmw.services.new_item_service import NewItemService
        from cdmw.services.new_item_planning import build_plan, planned_icon_string
        from cdmw.core.item_icon_addition import NewItemIcon, icon_target_path
        from cdmw.core.stringinfo_table import stringinfo_key
        view = snapshot.discovery_view()
        spec, model, variants, icon_data = unpack_recipe(package)
        allocated = NewItemService().allocate(replace(spec, internal_name='CDI_' + package.identity), view)
        icon = None
        if icon_data is not None:
            name = planned_icon_string(allocated, view)
            icon = NewItemIcon(name, stringinfo_key(name), icon_target_path(name), icon_data, None, None)
        plan = build_plan(allocated, view, model=model, variant_models=variants, icon=icon,
                          capture_independent=True, stop_event=stop_event)
        plan.source_revision.validate(stop_event)
        legacy_reads = {row.entry.path.lower() for row in plan.source_revision.payloads
                        if row.entry.path.lower().endswith('.dds')}
        if any(path not in package.dependencies for path in legacy_reads):
            raise OverlayConflict(f'{package.title}: the retained legacy resource graph is incomplete.')
    return {path: checksum for path, checksum in required.items()
            if path not in targets or path in legacy_reads}


def check_package_dependencies(package, snapshot, external, changes, *, stop_event=None, texture_dependencies=None):
    """Keep the package's game version contract; narrow only verified external overlaps."""
    from cdmw.services.independent_texture_package import package_texture_requirements
    texture_targets = {row['path']: row['sha256'] for row in package_texture_requirements(package)}
    if texture_dependencies is None:
        texture_dependencies = _texture_dependency_requirements(package, snapshot, stop_event=stop_event)
    for path, change in changes.items():
        paths = _group(path)
        if len(paths) != 2 or path != paths[0] or not external.paths.intersection(paths):
            continue
        body, head = paths
        old = dict(_table(change['before'], changes[head]['before'])[1])
        owned = set(dict(_table(change['after'], changes[head]['after'])[1])) - set(old)
        if not owned:
            continue
        current = _external_table(external, paths, snapshot, stop_event)
        overlap = owned.intersection(key for key, _ in _table(current[body], current[head])[1])
        if overlap:
            raise OverlayConflict(f'{package.title}; {", ".join(external.labels(paths))}; {body}: '
                f'owned record {int.from_bytes(sorted(overlap)[0], "little")} is also supplied by another mod.')
        if body.rsplit('/', 1)[-1] in ('iteminfo.staticinfobody', 'iteminfo.pabgb'):
            from cdmw.core.iteminfo_row import parse_iteminfo_row
            names = {parse_iteminfo_row(raw).string_key.casefold() for _, raw in _table(current[body], current[head])[1]}
            for key, raw in _table(change['after'], changes[head]['after'])[1]:
                if key in owned and parse_iteminfo_row(raw).string_key.casefold() in names:
                    raise OverlayConflict(f'{package.title}; {", ".join(external.labels(paths))}; {body}: '
                        f'owned record {int.from_bytes(key, "little")} is also supplied by another mod.')
    required = _required_keys(package, snapshot, changes)
    done = set()
    findings = []
    for path, checksum in package.dependencies.items():
        raise_if_cancelled(stop_event)
        if not snapshot.has_entry(path) or digest(snapshot.payload(path)) != checksum:
            raise OverlayConflict(f'{package.title}: incompatible game dependency {path}. Use the matching game version or an updated package.')
        if path in done or path not in external.paths:
            continue
        paths = _group(path)
        labels = external.labels(paths)
        try:
            current = (_external_table(external, paths, snapshot, stop_event) if len(paths) == 2 else
                       {path: external.payload(path, stop_event)})
            original = {p: snapshot.payload(p) for p in paths}
            if current == original:
                detail = 'Identical game data; no conflicting changes.'
            elif path in texture_targets and path not in texture_dependencies:
                if current[path] is None or digest(current[path]) != texture_targets[path]:
                    raise OverlayConflict('The texture replacement requires different final bytes.')
                detail = 'Identical required texture bytes; contributor ownership remains separate.'
            elif len(paths) == 2:
                body, head = paths
                old_table, old = _table(original[body], original[head])
                new_table, new = _table(current[body], current[head])
                if (old_table.key_width, old_table.header_size) != (new_table.key_width, new_table.header_size):
                    raise OverlayConflict('Table layout changed.')
                name = body.rsplit('/', 1)[-1].split('.')[0]
                protected = required.get(name)
                if name in ('storeinfo', 'itemgroupinfo') and body in changes:
                    # The structured merger checks existing stock/members and additions.
                    protected = set()
                present = dict(new)
                for key, raw in old:
                    number = int.from_bytes(key, 'little')
                    if (protected is None or number in protected) and present.get(key) != raw:
                        raise OverlayConflict(f'Required {name} record {number} was changed or removed.')
                detail = 'Separate records can coexist; shared output will preserve this mod.'
            else:
                # Non-table dependencies keep their complete resource contract.
                # Additive localisation/prefab records are handled below by comparison.
                _check_collection_additions(path, original[path], current[path])
                detail = 'Existing dependency records are unchanged; additions can coexist.'
            findings.append(CompatibilityFinding('Compatible', labels, paths[0], detail))
        except RunCancelled:
            raise
        except (ValueError, RuntimeError, KeyError, IndexError) as error:
            raise OverlayConflict(f'{package.title}; {", ".join(labels)}; {paths[0]}: {error}') from error
        done.update(paths)
    return findings


def _check_collection_additions(path, before, after):
    if path.endswith('.paloc'):
        from cdmw.core.paloc_format import parse_paloc
        old, new = (parse_paloc(data).index() for data in (before, after))
    elif path.endswith('.pappt'):
        from cdmw.core.pappt_format import parse_pappt
        b, a = map(parse_pappt, (before, after))
        if (b.reserved, b.tag_prefix, b.head_records) != (a.reserved, a.tag_prefix, a.head_records):
            raise OverlayConflict('Required prefab metadata changed.')
        old, new = b.index(), a.index()
    else:
        raise OverlayConflict('A required resource changed; its reference boundary is not supported for merging.')
    for key, value in old.items():
        if new.get(key) != value:
            raise OverlayConflict(f'Required record {key} was changed or removed.')


def foreign_underlay(external, baseline, snapshot, *, stop_event=None):
    result = dict(baseline)
    for path in baseline:
        raise_if_cancelled(stop_event)
        if path == 'meta/0.pathc':
            continue
        # Rebased journals may include an older foreign underlay. Always observe
        # today's shipped/mounted source so removing a mod cannot resurrect it.
        result[path] = snapshot.payload(path) if snapshot.has_entry(path) else None
        if path not in external.paths:
            continue
        if baseline[path] is None:
            raise OverlayConflict(f'{", ".join(external.labels((path,)))}: an owned asset is already supplied by another mod: {path}.')
        paths = _group(path)
        if len(paths) == 2:
            result[path] = _external_table(external, paths, snapshot, stop_event)[path]
        else:
            result[path] = external.payload(path, stop_event)
    return result


def _validate_composition_packages(root, pending, layers, snapshot, external, *, stop_event=None, on_log=None,
                                   virtual_identities=(), export_requirements=None):
    """Validate retained intent and the whole active graph for every output route."""
    from cdmw.services.independent_item_package import read_package
    from cdmw.domain.new_item.package_links import contract, resolve_package_contracts, check_graph_budget
    protected, operations = {}, []
    texture_reads, texture_writes = {}, {}
    findings = []
    active_packages, link_budgets, linked_groups = {False: [], True: []}, {False: 0, True: 0}, set()
    for layer, changes in layers:
        identity = layer.get('independent_identity')
        if not identity or not (layer['active'] or layer.get('disabled')):
            continue
        path = f'.cdmw/independent-items/{identity}-{layer["independent_digest"]}.cditem'
        source = pending[path] if path in pending else Path(root) / path
        if path not in pending:
            snapshot.provenance.pin_file(source)
        package = read_package(source, stop_event=stop_event)
        if path not in pending:
            snapshot.provenance.pin_file(source)
        if package.identity != identity or package.digest != layer['independent_digest']:
            raise OverlayConflict('The retained independent package does not match its ownership history.')
        from cdmw.services.independent_mod_package import package_operations
        declared = package_operations(package)
        from cdmw.services.independent_texture_package import lower_texture_operations, package_texture_requirements
        textures = package_texture_requirements(package)
        if layer.get('independent_textures', []) != textures:
            raise OverlayConflict('The retained package texture requirements disagree with its ownership layer.')
        texture_changes = lower_texture_operations(package, snapshot, {}, stop_event=stop_event)
        if any(changes.get(path) != change for path, change in texture_changes.items()):
            raise OverlayConflict(f'{package.title}: the texture journal differs from its witnessed original and replacement.')
        texture_dependencies = _texture_dependency_requirements(package, snapshot, stop_event=stop_event)
        if layer.get('independent_operations', []) != declared:
            raise OverlayConflict('The retained package field operations disagree with its ownership layer.')
        if layer['active']:
            package_contract = contract(package)
            if export_requirements is not None and (declared or textures or package_contract['declared']):
                export_requirements.append(package.title)
            virtual = package.identity in virtual_identities
            active_packages[virtual].append((package.identity, package_contract))
            link_budgets[virtual] += len(package_contract['exports']) + len(package_contract['links']['packages']) + len(package_contract['links']['references'])
            if package_contract['declared']:
                linked_groups.add(virtual)
            if virtual in linked_groups:
                check_graph_budget(len(active_packages[virtual]), link_budgets[virtual])
            operations.extend((row['owner'], row['operations']) for row in declared)
            for row in textures:
                texture_writes.setdefault(row['path'], []).append((row['sha256'], f'{package.title} ({row["owner"]})'))
            for path, checksum in texture_dependencies.items():
                texture_reads.setdefault(path, []).append((checksum, f'{package.title} ({package.identity})'))
            for key in _required_keys(package, snapshot, changes)['iteminfo']:
                protected.setdefault(key, []).append(package.identity)
        package_findings = check_package_dependencies(package, snapshot, external, changes, stop_event=stop_event,
                                                       texture_dependencies=texture_dependencies)
        findings.extend(package_findings)
        if on_log:
            for finding in package_findings:
                on_log(f'{package.title}: {", ".join(finding.mods)}: {finding.path}: {finding.detail}')
    for path, writes in texture_writes.items():
        for checksum, owner in writes:
            for required, consumer in texture_reads.get(path, ()):
                if checksum != required:
                    raise OverlayConflict(f'Texture conflict at {path}: {owner}; {consumer} requires the complete resource unchanged.')
    for virtual in (False, True):
        resolve_package_contracts(active_packages[virtual], stop_event=stop_event)
    if operations:
        from cdmw.domain.new_item.iteminfo_operations import compile_assignments
        compile_assignments(operations, {key: row.raw for key, row in snapshot.rows.items()}, protected=protected, stop_event=stop_event)
    return findings


def compose_underlay(root, state, pending, layers, baseline, *, stop_event=None, on_log=None, context=None, virtual_identities=()):
    """Called by the existing overlay composer, including removal and recovery."""
    from cdmw.services.independent_item_package import stock_snapshot
    external, snapshot = context if context is not None else (
        external_mods(root, state, stop_event=stop_event),
        stock_snapshot(root, stop_event=stop_event, overlay_changes=(changes for _, changes in layers)))
    external.snapshot = snapshot
    _validate_composition_packages(root, pending, layers, snapshot, external,
        stop_event=stop_event, on_log=on_log, virtual_identities=virtual_identities)
    current = foreign_underlay(external, baseline, snapshot, stop_event=stop_event)
    revision = snapshot.provenance.capture()
    revision.validate(stop_event)
    from cdmw.services.independent_item_install import _game_source_stamps
    state['sources'].update(_game_source_stamps(Path(root), revision))
    external.validate(stop_event)
    external.remember(state)
    return current, tuple(external.archives.items()), (revision, external.capture())


@dataclass(frozen=True)
class IndependentCompatibilityReport:
    root: Path
    findings: tuple[CompatibilityFinding, ...]
    folders: tuple[Path, ...] = ()
    virtual_profile: bool = False

    @property
    def compatible(self):
        return not any(row.status in ('Conflict', 'Unknown') for row in self.findings)

    def text(self):
        lines = ['Compatible shared files can be composed.' if self.compatible else 'Review the conflicts or unsupported data before merging.']
        if self.virtual_profile:
            lines.extend(('', 'This scan includes the saved virtual profile. Use Apply changes in Mods to update its shared files.'))
        for row in self.findings:
            names = ', '.join(row.mods)
            lines.append('')
            if row.status == 'Compatible':
                lines.append(f'Compatible: {names}')
            elif row.status == 'Conflict':
                lines.append(f'Conflict: {names}')
            elif row.status == 'Unknown':
                lines.append(f'Unknown: {names}')
            elif row.status == 'Merge available':
                lines.append(f'Merge available: {names}')
            else:
                lines.append(f'No overlap: {names}')
            lines.extend((row.path, row.detail))
        lines.extend(('', 'This compares file data and recorded dependencies. Runtime plugins and in-game behaviour are not verified.'))
        return '\n'.join(lines)


def _semantic_layer(package, changes, registry):
    from cdmw.services.independent_mod_package import package_operations
    from cdmw.services.independent_texture_package import package_texture_requirements
    return ({'id': package.identity, 'label': package.title, 'active': True, 'dependencies': [],
             'item_keys': list(registry['items'][package.identity]['values'].get('iteminfo', {}).values()),
             'independent_identity': package.identity, 'independent_digest': package.digest,
             'independent_operations': package_operations(package),
             'independent_textures': package_texture_requirements(package)}, changes)


def validate_semantic_recomposition(exports, compiled, registry, *, stop_event=None, package_cache=None):
    """Compare the artifact with its retained recipes, including no-op intent."""
    from cdmw.services import archive_overlay_manager as overlays
    from cdmw.services.independent_item_package import read_package
    for semantic in exports:
        semantic.validate(stop_event)
        layers, baseline, flags = [], {}, {}
        for raw in semantic.packages:
            package = read_package(raw, stop_event=stop_event, cache=package_cache)
            supplied, changes = compiled[package.identity]
            if supplied.digest != package.digest:
                raise OverlayConflict('A semantic export contributor changed during compilation.')
            expected = semantic.bindings['items'][package.identity]
            actual = registry['items'][package.identity]
            if actual['binding_hash'] != expected['binding_hash']:
                raise OverlayConflict(f'{package.identity}: semantic export relocation is unsupported.')
            layers.append(_semantic_layer(package, changes, registry))
            for path, change in changes.items():
                if path in baseline and baseline[path] != change['before']:
                    raise OverlayConflict(f'{path}: semantic export recipes disagree on their original baseline.')
                baseline[path] = change['before']
                flags[path] = change['flags']
        current, _ = overlays.compose_layer_payloads(layers, baseline, stop_event=stop_event)
        expected_files = tuple((path, data, flags[path]) for path, data in sorted(current.items()) if data is not None)
        if baseline != semantic.originals or expected_files != semantic.files:
            raise OverlayConflict('Semantic export payloads, flags or original baselines disagree with retained package recompilation.')
        semantic.validate(stop_event)


def _semantic_export_plan(root, folders, layers, snapshot, registry, pending, external, *,
                          observed=(), stop_event=None, on_log=None):
    """Export independently removable contributors through the existing compiler."""
    from copy import deepcopy
    from cdmw.core.mod_compatibility import SemanticExport, game_identity, hash_file
    from cdmw.domain.new_item.compilation import compiler_stamp
    from cdmw.services import archive_overlay_manager as overlays
    from cdmw.services.independent_item_package import read_package
    from cdmw.services.mod_merge_service import ModMergePlan

    active = [(layer, changes) for layer, changes in layers if layer['active']]
    if (not active or any(not layer.get('independent_identity') for layer, _ in active)
            or external.paths):
        raise OverlayConflict('Semantic export requires retained .cditem contributors for every payload. '
                              'Mixed foreign or untyped overlay exports remain unsupported.')
    _validate_composition_packages(root, pending, active, snapshot, external,
                                   stop_event=stop_event, on_log=on_log)
    baseline, flags, packages, bindings, loose_hashes = {}, {}, [], {}, []
    for layer, changes in active:
        raise_if_cancelled(stop_event)
        if layer.get('independent_compiler', compiler_stamp()) != compiler_stamp():
            raise OverlayConflict('Rebuild the installed package with the current compiler before semantic export.')
        identity = layer['independent_identity']
        relative = f'.cdmw/independent-items/{identity}-{layer["independent_digest"]}.cditem'
        path = root / relative
        if relative in pending:
            raw = pending[relative]
        else:
            snapshot.provenance.pin_file(path)
            raw = path.read_bytes()
            snapshot.provenance.pin_index(path, digest(raw), stop_event)
            loose_hashes.append((path, digest(raw)))
        package = read_package(raw, stop_event=stop_event)
        if (package.identity, package.digest) != (identity, layer['independent_digest']):
            raise OverlayConflict('Retained semantic export package disagrees with its ownership.')
        packages.append(raw)
        bindings[identity] = dict(deepcopy(registry['items'][identity]), layer=None)
        for dependency in package.dependencies:
            snapshot.payload(dependency)
        for path, change in changes.items():
            if path in baseline and baseline[path] != change['before']:
                raise OverlayConflict(f'{path}: semantic export contributors require different source baselines.')
            baseline[path] = change['before']
            flags[path] = change['flags']
        if 'sha256' in layer:
            journal = root / overlays.overlay_journal_path(layer)
            snapshot.provenance.pin_file(journal)
            loose_hashes.append((journal, hash_file(journal, stop_event)))
    original = foreign_underlay(external, baseline, snapshot, stop_event=stop_event)
    if original != baseline:
        raise OverlayConflict('Semantic export requires recompilation against the current witnessed baseline.')
    current, _ = overlays.compose_layer_payloads(active, original, stop_event=stop_event, on_log=on_log)
    files = tuple((path, data, flags[path]) for path, data in sorted(current.items()) if data is not None)
    # Read each witnessed source before capturing. Newly owned payloads have an
    # explicit null baseline; metadata uses its exact journal source bytes.
    for path, data in original.items():
        if data is not None and path != 'meta/0.pathc':
            if not snapshot.has_entry(path) or snapshot.payload(path) != data:
                raise OverlayConflict(f'{path}: semantic export has no matching original source witness.')
    external_revision = external.tracker.capture()
    for path, checksum in external_revision.indexes:
        snapshot.provenance.pin_index(path, checksum, stop_event)
    for path, _ in external_revision.files:
        snapshot.provenance.pin_file(path)
        if path.is_file():
            loose_hashes.append((path, hash_file(path, stop_event)))
    for relative, data in observed:
        path = root / relative
        snapshot.provenance.pin_file(path)
        if data is not None:
            loose_hashes.append((path, digest(data)))
    captured = snapshot.provenance.capture()
    witnesses = {
        'payloads': [{'path': row.entry.path.lower(), 'size': len(snapshot.payload(row.entry.path)),
                      'sha256': row.sha256} for row in captured.payloads],
        'indexes': [{'path': path.resolve().relative_to(root).as_posix().lower(),
                     'size': path.stat().st_size, 'sha256': checksum}
                    for path, checksum in captured.indexes
                    if path.suffix.lower() == '.pamt' and path.resolve().is_relative_to(root)]}
    witnesses['payloads'].sort(key=lambda row: row['path'])
    witnesses['indexes'].sort(key=lambda row: row['path'])
    semantic = SemanticExport(tuple(packages), files, original,
        {'format': registry['format'], 'items': bindings}, compiler_stamp(), witnesses,
        target_game=game_identity(root, stop_event))
    semantic.validate_source(snapshot, root, stop_event)
    if any('sha256' in layer for layer, _ in active):
        # Installed journals are recovery evidence, not a replacement for the
        # authored recipes. Recompile before exporting their current payloads.
        from cdmw.services.independent_item_install import resolve_items
        rebuilt = resolve_items(tuple(packages), root, rebuild=True, stop_event=stop_event,
                                on_log=on_log, read_entry=snapshot.provenance.reader)
        validate_semantic_recomposition((semantic,),
            {package.identity: (package, changes) for package, changes in rebuilt.contributions},
            rebuilt.registry, stop_event=stop_event)
    plan = ModMergePlan(tuple(folders), root, files, (), (),
        tuple({'item_key': key} for layer, _ in active for key in layer['item_keys']),
        tuple(path for path, _, _ in files if path.endswith('.dds') and not snapshot.has_entry(path)),
        '', snapshot.provenance.capture(), tuple(external.inventories),
        tuple(dict(loose_hashes).items()), semantic_export=semantic)
    plan.validate(stop_event)
    overlays._verify_observed_state(root, observed, 'during semantic export')
    return plan


def prepare_semantic_mod_merge(roots, game_root, entries=None, *, read_entry=None,
                               on_log=None, stop_event=None, include_installed=False):
    """Generic Merge admission for opaque exports; always regenerate originals."""
    from cdmw.services import archive_overlay_manager as overlays
    from cdmw.services.independent_item_install import _semantic_inputs, resolve_items
    from cdmw.services.independent_item_package import package_bytes, read_package
    from cdmw.services.independent_mod_package import retained_active_packages
    from cdmw.domain.new_item.package_links import resolve_package_graph

    root = Path(game_root).resolve()
    roots = tuple(Path(path).resolve() for path in roots)
    expanded, _, semantic = _semantic_inputs(roots, stop_event=stop_event)
    if len(semantic) != len(roots):
        raise OverlayConflict('Combining semantic exports with unannotated mod folders is unsupported; retain the original .cditem contributors.')
    sources = list(roots)
    packages = {package.identity: package for package in
                (read_package(raw, stop_event=stop_event) for raw in expanded)}
    if include_installed:
        state = overlays._load_index(root)
        if any(layer['active'] and not layer.get('independent_identity') for layer in (state or {}).get('layers', ())):
            raise OverlayConflict('An untyped installed overlay cannot be included in a semantic export.')
        retained = tuple(retained_active_packages(root, (state or {}).get('layers', ()), {},
                                                  exclude=packages, stop_event=stop_event))
        sources.extend(package_bytes(package, stop_event=stop_event) for package in retained)
        packages.update((package.identity, package) for package in retained)
    # The exported package set must itself be closed, irrespective of providers
    # installed in the recipient but omitted from this selected export.
    resolve_package_graph(packages.values(), stop_event=stop_event)
    resolved = resolve_items(tuple(sources), root, rebuild=True, stop_event=stop_event,
                             on_log=on_log, read_entry=read_entry)
    layers = [_semantic_layer(package, changes, resolved.registry)
              for package, changes in resolved.contributions]
    return _semantic_export_plan(root, roots, layers, resolved.baseline, resolved.registry,
        resolved.pending, resolved.external, observed=resolved.observed, stop_event=stop_event, on_log=on_log)


def scan_independent_conflicts(root, *, folders=(), stop_event=None, on_log=None, _export=False, _semantic=False):
    """Compare installed and saved virtual items with mounted and selected mods."""
    from cdmw.services import archive_overlay_manager as overlays
    from cdmw.services.independent_item_install import load_registry, resolve_items
    from cdmw.services.independent_item_package import stock_snapshot
    from cdmw.services.virtual_loader_state import load_profile, generation_path
    raise_if_cancelled(stop_event, 'Mod comparison cancelled.')
    root, folders = Path(root).resolve(), tuple(Path(p).resolve() for p in folders)
    observed = overlays._observe_state(root)
    registry = load_registry(root)
    profile = load_profile(root, registry=registry)
    virtual = bool(profile and (profile['items'] or profile['mods']))
    if virtual and _export:
        raise OverlayConflict('Use Apply changes in Mods to update the virtual profile. Archive export cannot include its shared files.')
    from cdmw.core.mod_compatibility import semantic_export_path
    if not virtual and any(semantic_export_path(folder) is not None for folder in folders):
        try:
            plan = prepare_semantic_mod_merge(folders, root, include_installed=True,
                                             stop_event=stop_event, on_log=on_log)
        except RunCancelled:
            raise
        except (ValueError, RuntimeError, KeyError, IndexError) as error:
            if _export:
                raise
            return IndependentCompatibilityReport(root, (CompatibilityFinding(
                'Conflict', tuple(map(str, folders)), '', str(error)),), folders)
        if _export:
            return plan
        return IndependentCompatibilityReport(root, (CompatibilityFinding(
            'Compatible', tuple(map(str, folders)), '', 'Retained typed requirements and package dependencies compose.'),), folders)
    pending, virtual_identities, revisions = {}, set(), ()
    if virtual:
        # Compare the applied package versions, even if the original downloads
        # have moved or now contain an unapplied edit. Never publish a new profile.
        directory = generation_path(root, profile['generation'])
        retained = SourceTracker(None)
        retained.pin_file(directory / 'profile.json')
        sources = tuple(directory / 'packages' / f'{identity}-{binding["digest"]}.cditem'
                        for identity, binding in profile['items'].items())
        labels = tuple(registry['items'][identity]['title'] for identity in profile['items'])
        selected = tuple(dict.fromkeys((*map(Path, profile['mods']), *folders)))
        try:
            for source in sources:
                retained.pin_file(source)
            resolved = resolve_items(sources, root, target='virtual', folders=selected,
                                     stop_event=stop_event, on_log=on_log)
            packages = {package.identity: package for package, _ in resolved.contributions}
            for identity, binding in profile['items'].items():
                package = packages.get(identity)
                if (package is None or package.digest != binding['digest']
                        or resolved.registry['items'][identity]['binding_hash'] != binding['binding_hash']):
                    raise OverlayConflict('The retained virtual package does not match the saved profile and item identities.')
            revisions = (retained.capture(), *resolved.revisions)
            layers = [(layer, resolved.decoded[layer['id']]) for layer in resolved.state['layers']]
            layers.extend(_semantic_layer(package, changes, resolved.registry) for package, changes in resolved.contributions)
            pending, snapshot, external = resolved.pending, resolved.baseline, resolved.external
            virtual_identities = set(packages)
        except RunCancelled:
            raise
        except (OSError, ValueError, RuntimeError, KeyError, IndexError) as error:
            return IndependentCompatibilityReport(root, (CompatibilityFinding(
                'Unknown' if isinstance(error, OSError) else 'Conflict', labels + tuple(map(str, selected)), '', str(error)),), folders, True)
    else:
        state = overlays._load_index(root)
        if state is None or not any(layer.get('independent_identity') and layer['active'] for layer in state['layers']):
            return IndependentCompatibilityReport(root, (CompatibilityFinding('Unknown', (), '', 'Install an independent item before comparing other mods.'),), folders)
        layers = [(layer, overlays._unpack_changes(root, layer, {}, stop_event)) for layer in state['layers']]
        snapshot = stock_snapshot(root, overlay_changes=(changes for _, changes in layers), stop_event=stop_event, on_log=on_log)
        external = external_mods(root, state, folders=folders, stop_event=stop_event, snapshot=snapshot)
    findings = list(external.findings)
    if 'meta/0.pathc' in external.paths:
        registry = root / 'meta/0.pathc'
        if not registry.is_file() or external.payload('meta/0.pathc', stop_event) != registry.read_bytes():
            findings.append(CompatibilityFinding('Unknown', external.labels(('meta/0.pathc',)), 'meta/0.pathc',
                'This external texture registry needs recorded texture ownership. Use Merge with a supported exported package.'))
    baseline, flags = {}, {}
    for layer, changes in layers:
        for path, change in changes.items():
            baseline.setdefault(path, change['before'])
            flags[path] = change['flags']
    # Admit and compose the complete active graph once. File-by-file byte diffs
    # cannot represent explicit source-equal assignments or disjoint row fields.
    output, export_requirements = {}, []
    try:
        findings.extend(_validate_composition_packages(root, pending, layers, snapshot, external,
            stop_event=stop_event, on_log=on_log, virtual_identities=virtual_identities,
            export_requirements=export_requirements if _export else None))
        current = foreign_underlay(external, baseline, snapshot, stop_event=stop_event)
        output, _ = overlays.compose_layer_payloads(layers, current, stop_event=stop_event, on_log=on_log)
    except RunCancelled:
        raise
    except (ValueError, RuntimeError, KeyError, IndexError) as error:
        labels = tuple(layer['label'] for layer, _ in layers if layer['active']) + external.labels(baseline)
        findings.append(CompatibilityFinding('Conflict', tuple(dict.fromkeys(labels)), '', str(error)))
    else:
        if virtual:
            findings.append(CompatibilityFinding('Compatible',
                tuple(layer['label'] for layer, _ in layers if layer['active']) or tuple(map(str, selected)), '',
                'The saved virtual profile and installed items can share these files.'))
        for paths in sorted({_group(path) for path in baseline}):
            raise_if_cancelled(stop_event)
            labels = external.labels(paths)
            if labels:
                findings.append(CompatibilityFinding('Merge available', labels, paths[0],
                    'CDMW can preserve the external data and add the installed items in one shared output.'))
    touched = set(baseline)
    dependency_paths = {row.path for row in findings if row.path}
    for path in sorted(external.paths - touched):
        if path in dependency_paths or any(path in _group(p) for p in dependency_paths):
            continue
        if len(external.providers[path]) > 1:
            try:
                external.payload(path, stop_event)
            except RunCancelled:
                raise
            except (ValueError, RuntimeError) as error:
                findings.append(CompatibilityFinding('Conflict', external.labels((path,)), path, str(error)))
    if not findings:
        findings.append(CompatibilityFinding('No overlap', (), '', 'No external file overlaps with the installed independent items were found.'))
    snapshot.provenance.capture().validate(stop_event)
    for revision in revisions:
        revision.validate(stop_event)
    external.validate(stop_event)
    overlays._verify_observed_state(root, observed, 'during comparison')
    report = IndependentCompatibilityReport(root, tuple(dict.fromkeys(findings)), folders, virtual)
    if not _export:
        return report
    if not report.compatible:
        raise OverlayConflict(report.text())
    if export_requirements or _semantic:
        return _semantic_export_plan(root, folders, layers, snapshot, load_registry(root), {}, external,
                                     observed=observed, stop_event=stop_event, on_log=on_log)
    # Build a portable merged copy through the existing exporter. This is an
    # explicit folder export, never a write to a foreign archive or source mod.
    from cdmw.services.mod_merge_service import ModMergePlan
    from cdmw.core.mod_compatibility import compatibility_from_payloads, game_identity, hash_file
    for path in sorted(external.paths):
        raise_if_cancelled(stop_event)
        if path == 'meta/0.papgt':
            continue
        if path.startswith('meta/') and path != 'meta/0.pathc':
            raise OverlayConflict(f'Unsupported metadata in merged output: {path}.')
        if path not in output:
            output[path] = external.payload(path, stop_event)
            source = external.providers[path][0][1]
            flags[path] = source.entry.flags if source.entry is not None else 0
    files = {p: data for p, data in output.items() if data is not None}
    # Preserve guards for both the loaded ownership journals and external inputs.
    for relative, _data in observed:
        snapshot.provenance.pin_file(root / relative)
    for layer, _ in layers:
        snapshot.provenance.pin_file(root / overlays.overlay_journal_path(layer))
    external_revision = external.tracker.capture()
    for path, checksum in external_revision.indexes:
        snapshot.provenance.pin_index(path, checksum, stop_event)
    for source in external_revision.payloads:
        snapshot.provenance.read(source.entry)
    loose_hashes = []
    for path, _stamp in external_revision.files:
        snapshot.provenance.pin_file(path)
        if path.is_file():
            loose_hashes.append((path, hash_file(path, stop_event)))
    evidence = compatibility_from_payloads(files, {p: snapshot.payload(p) if snapshot.has_entry(p) else baseline.get(p) for p in files},
                                          target_game=game_identity(root, stop_event))
    plan = ModMergePlan(folders, root, tuple((p, data, flags.get(p, 0)) for p, data in sorted(files.items())), (), (),
        tuple({'item_key': key} for layer, _ in layers if layer['active'] for key in layer['item_keys']),
        tuple(p for p in files if p.endswith('.dds') and not snapshot.has_entry(p)), '', snapshot.provenance.capture(),
        tuple(external.inventories), tuple(loose_hashes), evidence)
    plan.validate(stop_event)
    overlays._verify_observed_state(root, observed, 'during comparison')
    return plan


def prepare_independent_mod_merge(root, *, folders=(), stop_event=None, on_log=None, dmm_v3=False):
    return scan_independent_conflicts(root, folders=folders, stop_event=stop_event, on_log=on_log,
                                     _export=True, _semantic=dmm_v3)
