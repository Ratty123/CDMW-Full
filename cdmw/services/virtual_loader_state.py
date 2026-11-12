"""Read the profile ledgers an older CDMW's virtual loader left in ``.cdmw``.

CDMW no longer installs into the game (decision 39). The install code moved to
tests/support; Browse Archives' Remove What an Older CDMW Installed... takes an
old install out. Nothing here writes.
"""
import json
from pathlib import Path
import re

from cdmw.domain.new_item.compilation import validate_compiler_stamp, validate_compilation
from cdmw.domain.virtual_loader import VirtualLoaderError
from cdmw.services.independent_item_package import canonical, MAX_MANIFEST, package_id

PROFILE_PATH = '.cdmw/virtual-loader/profile.json'
JOURNAL_PATH = '.cdmw/virtual-loader/transaction.json'
FORMAT = 'cdmw_virtual_profile_v1'
#: Profile files under this prefix are served by game resource path inside the game's
#: package loader (`resources/character/model/.../x.pac`), not mapped over a file.
RESOURCE_PREFIX = 'resources/'
MAX_RESOURCES = 16384


def resource_path(value):
    """Whether the package loader can be asked for this path, as the runtime accepts it."""
    return (isinstance(value, str) and 0 < len(value) <= 400 and value.isascii() and value == value.lower()
            and not any(c in value for c in '\\:*?"<>|') and all(0x21 <= ord(c) <= 0x7e for c in value)
            and all(part not in ('', '.', '..') for part in value.split('/')))


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
    if not isinstance(value, dict) or set(value) - {'disabled_packages', 'disabled_mods', 'catalogue', 'build_cache', 'executable_sha256'} not in (expected, expected | {'compiler'}, expected | {'compiler', 'compilation'}) or value['format'] != FORMAT:
        raise VirtualLoaderError('Unsupported virtual profile.')
    if 'executable_sha256' in value and not (isinstance(value['executable_sha256'], str)
                                             and re.fullmatch('[a-f0-9]{64}', value['executable_sha256'])):
        raise VirtualLoaderError('Invalid virtual profile game build.')
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
        disabled = value.get('disabled_' + key, [])
        if (not isinstance(disabled, list) or len(value[key]) + len(disabled) > 128
                or any(not absolute(p) for p in disabled)
                or len({Path(p) for p in value[key] + disabled}) != len(value[key]) + len(disabled)):
            raise VirtualLoaderError('Invalid disabled virtual selection paths.')
    seen = set()
    for row in value['sources']:
        if not isinstance(row, list) or len(row) != 2 or not absolute(row[0]) or not checksum(row[1]) or row[0] in seen:
            raise VirtualLoaderError('Invalid virtual source guard.')
        seen.add(row[0])
    catalogue = value.get('catalogue', [])
    if not isinstance(catalogue, list) or len(catalogue) > 65536:
        raise VirtualLoaderError('Invalid virtual catalogue guards.')
    for row in catalogue:
        if (not isinstance(row, list) or len(row) != 2 or not absolute(row[0])
                or Path(row[0]).suffix.lower() != '.paz' or row[0] in seen
                or (row[1] is not None and (not isinstance(row[1], list) or len(row[1]) != 3
                    or any(type(n) is not int or n < 0 or n >= 2**63 for n in row[1])))):
            raise VirtualLoaderError('Invalid virtual catalogue guard.')
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
    # Either a private archive group named by a rewritten mount list, or, on games
    # that authenticate the mount list, files served by resource path and the
    # texture registry. Never both.
    if not isinstance(value['files'], dict):
        raise VirtualLoaderError('Invalid virtual file map.')
    served = [p for p in value['files'] if isinstance(p, str) and p.startswith(RESOURCE_PREFIX)]
    if not value['files'] or len(value['files']) - len(served) > 256 or len(served) > MAX_RESOURCES:
        raise VirtualLoaderError('Invalid virtual file map.')
    for logical, checksum in value['files'].items():
        if served:
            allowed = logical == 'meta/0.pathc' or (logical.startswith(RESOURCE_PREFIX) and resource_path(logical[len(RESOURCE_PREFIX):]))
        else:
            allowed = re.fullmatch(r'(?:meta/0\.(?:papgt|pathc)|[A-Za-z0-9_-]+/0\.(?:pamt|paz))', logical)
        if not allowed:
            raise VirtualLoaderError('Virtual redirection is limited to prepared archive and metadata files.')
        if not isinstance(checksum, str) or not re.fullmatch('[a-f0-9]{64}', checksum):
            raise VirtualLoaderError('Invalid virtual file checksum.')
    names = {p.casefold() for p in value['files']}
    if len(names) != len(value['files']):
        raise VirtualLoaderError('The virtual map contains a case-insensitive path collision.')
    for name in names:
        if name.endswith(('.pamt', '.paz')) and not {name.rsplit('.', 1)[0] + suffix for suffix in ('.pamt', '.paz')} <= names:
            raise VirtualLoaderError('The virtual archive is missing its metadata or payload pair.')
    if not served and 'meta/0.papgt' not in value['files']:
        raise VirtualLoaderError('The virtual mount list is missing.')
    if 'compilation' in value:
        try:
            inputs = validate_compilation(value['compilation'])
            locked = {package['identity']: package['content'] for package in inputs['packages']}
            if (inputs['scope'] != 'virtual-profile' or inputs['runtime_abi'] not in ('CDVFS2', 'CDVFS3', 'CDVFS4')
                    or inputs['compiler'] != value['compiler'] or inputs['sources'] != dict(value['sources'])
                    or inputs['outputs'] != value['files'] or inputs['providers'] != dict(value['observed'])
                    or locked != {identity: row['digest'] for identity, row in value['items'].items()}
                    or any(inputs['allocations'].get(identity) != row['binding_hash'] for identity, row in value['items'].items())):
                raise ValueError('The virtual compilation record disagrees with the profile.')
            if 'links' in inputs and set(inputs['links']['providers']) != set(value['items']):
                raise ValueError('The virtual package dependency graph disagrees with the profile.')
        except ValueError as exc:
            raise VirtualLoaderError(str(exc)) from exc
    # The removed virtual loader's build cache record was optional metadata about its
    # prepared archives; the outputs above stay authoritative. Only its shape is checked.
    if 'build_cache' in value and not isinstance(value['build_cache'], dict):
        raise VirtualLoaderError('Invalid virtual build cache record.')
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


