"""Strict virtual ownership, immutable generations and recoverable ledger publication.

Only CDMW bookkeeping is published here. This module cannot publish to the game's
archive or metadata directories. A durable journal covers the two-ledger commit.
"""
import json
from pathlib import Path
import re

from cdmw.core.atomic_file import atomic_write_bytes
from cdmw.domain.cancellation import raise_if_cancelled
from cdmw.domain.new_item.compilation import validate_compiler_stamp, validate_compilation
from cdmw.domain.virtual_loader import VirtualLoaderError
from cdmw.services.application_shutdown_service import archive_write_scope
from cdmw.services.independent_item_package import canonical, digest, MAX_MANIFEST, package_id
from cdmw.services.installation_lane import installation_lane

PROFILE_PATH = '.cdmw/virtual-loader/profile.json'
JOURNAL_PATH = '.cdmw/virtual-loader/transaction.json'
FORMAT = 'cdmw_virtual_profile_v1'
REGISTRY = '.cdmw/independent-items.json'


def target(root, relative):
    root = Path(root).resolve()
    parts = relative.split('/')
    if relative.startswith('/') or any(p in ('', '.', '..') or ':' in p or '\\' in p for p in parts):
        raise VirtualLoaderError('Invalid virtual profile path.')
    path = root
    for part in parts:
        path = path / part
        if path.is_symlink() or getattr(path, 'is_junction', lambda: False)():
            raise VirtualLoaderError('Virtual profile paths cannot pass through links or junctions.')
    if not path.resolve().is_relative_to(root):
        raise VirtualLoaderError('Virtual profile path escapes the installation.')
    return path


def generation_path(root, generation):
    package_id(generation)
    return target(root, '.cdmw/virtual-loader/generations/' + generation)


def read_optional(path):
    if path.exists() and not path.is_file():
        raise VirtualLoaderError('A virtual profile file was replaced by a directory.')
    return path.read_bytes() if path.is_file() else None


def decode(data, *, limit=MAX_MANIFEST):
    if not isinstance(data, bytes) or len(data) > limit:
        raise VirtualLoaderError('Virtual profile exceeds its size limit.')
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise VirtualLoaderError('Duplicate virtual profile field.')
            result[key] = value
        return result
    try:
        return json.loads(data, object_pairs_hook=unique)
    except (ValueError, RecursionError) as exc:
        raise VirtualLoaderError('Invalid virtual profile JSON.') from exc


def validate_profile(value):
    expected = {'format', 'generation', 'items', 'packages', 'mods', 'files', 'sources', 'inventories', 'observed'}
    if not isinstance(value, dict) or set(value) not in (expected, expected | {'compiler'}, expected | {'compiler', 'compilation'}) or value['format'] != FORMAT:
        raise VirtualLoaderError('Unsupported virtual profile.')
    if 'compiler' in value:
        try:
            validate_compiler_stamp(value['compiler'])
        except ValueError as exc:
            raise VirtualLoaderError(str(exc)) from exc
    package_id(value['generation'])
    if not isinstance(value['items'], dict) or len(value['items']) > 128:
        raise VirtualLoaderError('Invalid virtual ownership.')
    for identity, row in value['items'].items():
        package_id(identity)
        if not isinstance(row, dict) or set(row) != {'digest', 'binding_hash'} or any(not isinstance(v, str) or not re.fullmatch('[a-f0-9]{64}', v) for v in row.values()):
            raise VirtualLoaderError('Invalid virtual identity binding.')
    for key in ('packages', 'mods', 'sources', 'inventories', 'observed'):
        if not isinstance(value[key], list) or len(value[key]) > 65536:
            raise VirtualLoaderError('Invalid virtual profile inputs.')
    def absolute(value):
        return isinstance(value, str) and 0 < len(value) < 32768 and '\0' not in value and Path(value).is_absolute()
    def checksum(value):
        return isinstance(value, str) and re.fullmatch('[a-f0-9]{64}', value) is not None
    for key in ('packages', 'mods'):
        if len(value[key]) > 128 or any(not absolute(p) for p in value[key]) or len(set(value[key])) != len(value[key]):
            raise VirtualLoaderError('Invalid virtual selection paths.')
    seen = set()
    for row in value['sources']:
        if not isinstance(row, list) or len(row) != 2 or not absolute(row[0]) or not checksum(row[1]) or row[0] in seen:
            raise VirtualLoaderError('Invalid virtual source guard.')
        seen.add(row[0])
    allowed_observed = {'.cdmw/overlays.json', 'meta/0.papgt', 'meta/0.pathc'}
    seen = set()
    for row in value['observed']:
        if not isinstance(row, list) or len(row) != 2 or not isinstance(row[0], str) or row[0] not in allowed_observed or row[0] in seen or (row[1] is not None and not checksum(row[1])):
            raise VirtualLoaderError('Invalid virtual installation guard.')
        seen.add(row[0])
    for row in value['inventories']:
        if not isinstance(row, list) or len(row) != 2 or not absolute(row[0]) or not isinstance(row[1], list):
            raise VirtualLoaderError('Invalid virtual source inventory.')
        seen = set()
        for entry in row[1]:
            if (not isinstance(entry, list) or len(entry) != 3 or not isinstance(entry[0], str)
                    or entry[0] in seen or any(type(n) is not int or n < 0 for n in entry[1:])):
                raise VirtualLoaderError('Invalid virtual inventory entry.')
            target(Path(row[0]), entry[0])
            seen.add(entry[0])
    if not isinstance(value['files'], dict) or not value['files'] or len(value['files']) > 256:
        raise VirtualLoaderError('Invalid virtual file map.')
    for logical, checksum in value['files'].items():
        if not re.fullmatch(r'(?:meta/0\.(?:papgt|pathc)|[A-Za-z0-9_-]+/0\.(?:pamt|paz))', logical):
            raise VirtualLoaderError('Virtual redirection is limited to prepared archive and metadata files.')
        if not isinstance(checksum, str) or not re.fullmatch('[a-f0-9]{64}', checksum):
            raise VirtualLoaderError('Invalid virtual file checksum.')
    names = {p.casefold() for p in value['files']}
    if len(names) != len(value['files']):
        raise VirtualLoaderError('The virtual map contains a case-insensitive path collision.')
    for name in names:
        if name.endswith(('.pamt', '.paz')) and not {name.rsplit('.', 1)[0] + suffix for suffix in ('.pamt', '.paz')} <= names:
            raise VirtualLoaderError('The virtual archive is missing its metadata or payload pair.')
    if 'meta/0.papgt' not in value['files']:
        raise VirtualLoaderError('The virtual mount list is missing.')
    if 'compilation' in value:
        try:
            inputs = validate_compilation(value['compilation'])
            locked = {package['identity']: package['content'] for package in inputs['packages']}
            if (inputs['scope'] != 'virtual-profile' or inputs['runtime_abi'] != 'CDVFS2'
                    or inputs['compiler'] != value['compiler'] or inputs['sources'] != dict(value['sources'])
                    or inputs['outputs'] != value['files'] or inputs['providers'] != dict(value['observed'])
                    or locked != {identity: row['digest'] for identity, row in value['items'].items()}
                    or any(inputs['allocations'].get(identity) != row['binding_hash'] for identity, row in value['items'].items())):
                raise ValueError('The virtual compilation record disagrees with the profile.')
            if 'links' in inputs and set(inputs['links']['providers']) != set(value['items']):
                raise ValueError('The virtual package dependency graph disagrees with the profile.')
        except ValueError as exc:
            raise VirtualLoaderError(str(exc)) from exc
    if len(canonical(value)) > MAX_MANIFEST:
        raise VirtualLoaderError('Virtual profile exceeds its size limit.')
    return value


def load_profile(root, *, registry=None):
    if target(root, JOURNAL_PATH).exists():
        raise VirtualLoaderError('Recover the interrupted virtual profile transaction first.')
    data = read_optional(target(root, PROFILE_PATH))
    if data is None:
        return None
    profile = validate_profile(decode(data))
    manifest = target(generation_path(root, profile['generation']), 'profile.json')
    if read_optional(manifest) != data:
        raise VirtualLoaderError('The active virtual profile does not match its retained generation.')
    if registry is not None:
        for identity, binding in profile['items'].items():
            row = registry['items'].get(identity)
            if not row or row['layer'] is not None or any(row[key] != binding[key] for key in binding):
                raise VirtualLoaderError('Virtual ownership and saved item identities disagree. Recover their matching ledgers.')
        if 'links' in profile.get('compilation', {}).get('inputs', {}):
            from cdmw.domain.new_item.package_links import validate_link_bindings
            validate_link_bindings(profile['compilation']['inputs']['links'], registry['items'])
    return profile


def active_identities(root):
    profile = load_profile(root)
    return set(profile['items']) if profile else set()


def _write_optional(path, data):
    if data is None:
        path.unlink(missing_ok=True)
    else:
        atomic_write_bytes(path, data)


def _journal_value(before, after):
    value = {'format': 'cdmw_virtual_transaction_v1', 'before': before, 'after': after}
    return canonical({'data': value, 'sha256': digest(canonical(value))})


@archive_write_scope()
def recover_profile(root):
    with installation_lane(root, recovery=True):
        journal = target(root, JOURNAL_PATH)
        wrapper = decode(journal.read_bytes(), limit=MAX_MANIFEST * 8)
        value = wrapper.get('data', {})
        if wrapper.get('sha256') != digest(canonical(value)) or value.get('format') != 'cdmw_virtual_transaction_v1':
            raise VirtualLoaderError('Virtual recovery material failed validation.')
        if set(value) != {'format', 'before', 'after'} or any(set(value[key]) != {REGISTRY, PROFILE_PATH} for key in ('before', 'after')):
            raise VirtualLoaderError('Invalid virtual recovery targets.')
        from cdmw.services.independent_item_install import _validate_registry
        for side in ('before', 'after'):
            for relative, text in value[side].items():
                if text is not None:
                    obj = decode(text.encode())
                    (_validate_registry if relative == REGISTRY else validate_profile)(obj)
        encoded = {side: {p: text.encode() if text is not None else None for p, text in value[side].items()} for side in ('before', 'after')}
        actual = {p: read_optional(target(root, p)) for p in encoded['before']}
        if any(actual[p] not in (encoded['before'][p], encoded['after'][p]) for p in actual):
            raise VirtualLoaderError('An interrupted profile was changed externally; automatic recovery is refused.')
        selected = 'after' if actual == encoded['after'] else 'before'
        for relative, data in encoded[selected].items():
            if read_optional(target(root, relative)) != data:
                _write_optional(target(root, relative), data)
        # Preserve the complete verified journal as recovery evidence.
        archive = target(root, '.cdmw/virtual-loader/recovery/' + digest(journal.read_bytes()) + '.json')
        atomic_write_bytes(archive, journal.read_bytes())
        journal.unlink()
        return selected


@archive_write_scope()
def publish_profile(prepared, *, stop_event=None):
    from cdmw.services.independent_item_install import _validate_registry
    from cdmw.services.archive_overlay_manager import _verify_observed_state
    from cdmw.services.new_item_service import game_is_running
    root = prepared.root
    with installation_lane(root):
        if game_is_running():
            raise VirtualLoaderError('Close Crimson Desert before publishing a virtual profile.')
        prepared.source_revision.validate(stop_event)
        prepared.external.validate(stop_event)
        _verify_observed_state(root, prepared.observed, 'after virtual preparation')
        profile = validate_profile(decode(prepared.profile))
        registry = _validate_registry(decode(prepared.registry))
        if 'links' in profile.get('compilation', {}).get('inputs', {}):
            from cdmw.domain.new_item.package_links import validate_link_bindings
            validate_link_bindings(profile['compilation']['inputs']['links'], registry['items'])
        if prepared.generation != profile['generation'] or len(prepared.files) != len(dict(prepared.files)):
            raise VirtualLoaderError('Prepared generation or file identities disagree.')
        for identity, binding in profile['items'].items():
            row = registry['items'].get(identity)
            if not row or row['layer'] is not None or any(row[key] != binding[key] for key in binding):
                raise VirtualLoaderError('Prepared ownership does not match its identity reservations.')
        if set(profile['files']) != set(dict(prepared.files)) or any(digest(data) != profile['files'][p] for p, data in prepared.files):
            raise VirtualLoaderError('Prepared virtual files failed validation.')
        directory = generation_path(root, prepared.generation)
        if directory.exists():
            raise VirtualLoaderError('The prepared generation already exists; prepare a fresh profile.')
        directory.mkdir(parents=True)
        # An interrupted/unreferenced generation is harmless and retained for diagnosis.
        for relative, data in prepared.files:
            raise_if_cancelled(stop_event)
            atomic_write_bytes(target(directory, 'files/' + relative), data)
            from cdmw.services.virtual_loader_composition import hash_file
            if hash_file(target(directory, 'files/' + relative), stop_event) != profile['files'][relative]:
                raise VirtualLoaderError('A staged snapshot file failed readback.')
        for name, data in prepared.retained_packages:
            if not re.fullmatch(r'[0-9a-f]{32}-[0-9a-f]{64}\.cditem', name):
                raise VirtualLoaderError('Invalid retained virtual package name.')
            raise_if_cancelled(stop_event)
            atomic_write_bytes(target(directory, 'packages/' + name), data)
        atomic_write_bytes(directory / 'profile.json', prepared.profile)
        prepared.source_revision.validate(stop_event)
        prepared.external.validate(stop_event)
        _verify_observed_state(root, prepared.observed, 'before virtual publication')
        raise_if_cancelled(stop_event)
        after = {REGISTRY: prepared.registry.decode(), PROFILE_PATH: prepared.profile.decode()}
        before = {p: data.decode() if data is not None else None for p in after for data in (read_optional(target(root, p)),)}
        recovery_data = _journal_value(before, after)
        backup = target(root, '.cdmw/virtual-loader/recovery/' + prepared.generation + '.json')
        atomic_write_bytes(backup, recovery_data)
        if backup.read_bytes() != recovery_data:
            raise VirtualLoaderError('Virtual recovery material failed readback.')
        atomic_write_bytes(target(root, JOURNAL_PATH), recovery_data)
        try:
            # No cancellation inside this two-ledger commit. Launch refuses any
            # surviving journal; recovery is idempotent after process death.
            for relative, data in after.items():
                atomic_write_bytes(target(root, relative), data.encode())
            target(root, JOURNAL_PATH).unlink()
        except Exception:
            recover_profile(root)
            raise
        return profile
