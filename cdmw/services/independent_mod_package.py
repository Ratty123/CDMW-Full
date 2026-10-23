"""V2 admission and explicit v1 migration; no unsupported behavior is skipped."""
from copy import deepcopy
import math
import re

from cdmw.domain.new_item.independent import IndependentItemError, IndependentItemPackage
from cdmw.domain.new_item.mod_package import IndependentModPackage, UnsupportedCapability, capability_result


def _metadata(value, depth=0):
    if depth > 32:
        raise IndependentItemError('Optional package metadata is too deeply nested.')
    if value is None or type(value) is bool:
        return
    if type(value) is str and len(value) <= 65536 and '\0' not in value:
        return
    if type(value) is int and -(1 << 63) <= value < (1 << 64):
        return
    if type(value) is float and math.isfinite(value):
        return
    if isinstance(value, (dict, list)) and len(value) <= 10000:
        for key in value if isinstance(value, dict) else ():
            if not isinstance(key, str):
                raise IndependentItemError('Invalid optional metadata key.')
            _metadata(key, depth + 1)
        for item in value.values() if isinstance(value, dict) else value:
            _metadata(item, depth + 1)
        return
    raise IndependentItemError('Invalid optional package metadata.')


def read_v2(meta, blobs, *, stop_event=None):
    from cdmw.services.independent_item_package import FORMAT, MAX_MANIFEST, MAX_TOTAL, _package_resources, _recipe_values, _v1_package, canonical, digest
    keys = {'format', 'version', 'identity', 'title', 'release', 'requires', 'modules',
            'dependencies', 'blobs', 'provenance', 'metadata'}
    if (set(meta) != keys or meta['format'] != FORMAT or type(meta['version']) is not int
            or meta['version'] != 2 or len(canonical(meta)) > MAX_MANIFEST):
        raise IndependentItemError('Unsupported v2 package fields.')
    if not isinstance(meta['release'], str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._+-]{0,63}', meta['release']):
        raise IndependentItemError('Invalid v2 package release identity.')
    required = meta['requires']
    if not isinstance(required, dict) or len(required) > 128:
        raise IndependentItemError('Invalid required feature inventory.')
    for name, version in required.items():
        if (not isinstance(name, str) or not re.fullmatch(r'[a-z][a-z0-9.-]{0,63}', name)
                or type(version) is not int or not 1 <= version <= 0x7fffffff):
            raise IndependentItemError('Invalid required capability version.')
        result = capability_result(name, version)
        if not result.supported:
            raise UnsupportedCapability(result)
    modules = meta['modules']
    if not isinstance(modules, list) or not 1 <= len(modules) <= 128:
        raise IndependentItemError('Invalid v2 module inventory.')
    seen = set()
    for module in modules:
        if not isinstance(module, dict) or set(module) != {'id', 'type', 'version', 'required', 'data'}:
            raise IndependentItemError('Invalid v2 module fields.')
        symbol = module['id']
        if not isinstance(symbol, str) or not re.fullmatch(r'[a-z][a-z0-9_-]{0,63}', symbol) or symbol in seen:
            raise IndependentItemError('Invalid or duplicate module identity.')
        seen.add(symbol)
        if module['required'] is not True:
            raise IndependentItemError('Optional behavior requires an implemented explicit alternative; it cannot be silently omitted.')
        name, version = module['type'], module['version']
        if (not isinstance(name, str) or not re.fullmatch(r'[a-z][a-z0-9.-]{0,63}', name)
                or type(version) is not int or not 1 <= version <= 0x7fffffff):
            raise IndependentItemError('Invalid module type or version.')
        result = capability_result(name, version)
        if not result.supported:
            raise UnsupportedCapability(result)
        if required.get(name) != version:
            raise IndependentItemError(f'Module {symbol} omits its required capability {name}@{version}.')
    _package_resources(meta, blobs)
    legacy_modules = [module for module in modules if module['type'] == 'item.legacy']
    if len(legacy_modules) > 1 or legacy_modules and legacy_modules[0]['id'] != 'item':
        raise IndependentItemError('The legacy adapter permits one module named item.')
    item_properties(meta)
    from cdmw.services.independent_texture_package import read_texture_modules
    texture_keys = read_texture_modules(meta, blobs, stop_event=stop_event)
    legacy_keys = set()
    legacy = None
    if legacy_modules:
        legacy_meta = {key: meta[key] for key in ('format', 'identity', 'title', 'dependencies', 'blobs')}
        legacy_meta.update(version=1, recipe=legacy_modules[0]['data'])
        prototype = IndependentItemPackage(meta['identity'], meta['title'], legacy_meta['recipe'],
                                           meta['dependencies'], blobs, '')
        legacy_keys = _recipe_values(prototype)[-1]
        legacy_meta['blobs'] = {key: meta['blobs'][key] for key in legacy_keys}
        legacy = _v1_package(legacy_meta, {key: blobs[key] for key in legacy_keys})
    if legacy_keys | texture_keys != set(blobs):
        raise IndependentItemError('The package contains unreferenced resources.')
    from cdmw.domain.new_item.package_links import decode_links
    link_modules = [module for module in modules if module['type'] == 'package.links']
    if len(link_modules) > 1:
        raise IndependentItemError('A package permits only one package.links module.')
    if link_modules:
        if not any(module['type'] in ('item.legacy', 'item.fields', 'texture.replace') for module in modules):
            raise IndependentItemError('Package links require an implemented content module.')
        decode_links(link_modules[0]['data'], meta['identity'], legacy=legacy is not None)
    from cdmw.domain.new_item.iteminfo_operations import MAX_OPERATIONS, decode_assignment
    operation_count = 0
    for module in modules:
        if module['type'] != 'item.fields':
            continue
        data = module['data']
        if (not isinstance(data, dict) or set(data) != {'operations'} or not isinstance(data['operations'], list)
                or not data['operations']):
            raise IndependentItemError('Invalid ItemInfo field module.')
        identities = set()
        for raw in data['operations']:
            operation = decode_assignment(f'{meta["identity"]}/{module["id"]}', raw)
            if operation.identity in identities:
                raise IndependentItemError('Duplicate ItemInfo operation identity.')
            identities.add(operation.identity)
            operation_count += 1
            if operation_count > MAX_OPERATIONS:
                raise IndependentItemError('The ItemInfo operation budget is exhausted.')
    provenance = meta['provenance']
    if provenance is not None:
        if legacy is None:
            raise IndependentItemError('V1 migration provenance requires its retained legacy module.')
        expected = {'kind': 'v1-lowering', 'source_version': 1, 'source_identity': legacy.identity,
                    'source_digest': legacy.digest, 'symbols': {'item': 'item'}}
        if (not isinstance(provenance, dict) or provenance != expected
                or type(provenance.get('source_version')) is not int):
            raise IndependentItemError('The v1 migration provenance does not match the retained legacy content.')
    if not isinstance(meta['metadata'], dict):
        raise IndependentItemError('Optional metadata must be an object.')
    _metadata(meta['metadata'])
    package = IndependentModPackage(deepcopy(meta), dict(blobs), digest(canonical(meta)))
    if package_logical_size(package) > MAX_TOTAL:
        raise IndependentItemError('The logical package resource size limit is exhausted.')
    return package


def package_logical_size(package):
    """Keep repeated target writes within the existing logical package budget."""
    from cdmw.services.independent_item_package import _recipe_values, canonical, package_metadata
    from cdmw.services.independent_texture_package import texture_modules
    modules = texture_modules(package)
    size = len(canonical(package_metadata(package)))
    if not modules:
        return size + sum(map(len, package.blobs.values()))
    if has_legacy_item(package):
        size += sum(len(package.blobs[key]) for key in _recipe_values(package)[-1])
    return size + sum(len(package.blobs[row['replacement']])
                      for module in modules for row in module['data']['replacements'])


def has_legacy_item(package):
    return isinstance(package, IndependentItemPackage) or any(module['type'] == 'item.legacy' for module in package.manifest['modules'])


def item_properties(manifest):
    """Admit a single closed override module attached to the owned item."""
    modules = manifest['modules']
    properties = [module for module in modules if module['type'] == 'item.properties']
    if not properties:
        return {}
    if len(properties) != 1 or not any(module['type'] == 'item.legacy' for module in modules):
        raise IndependentItemError('Item properties require one module and its owned legacy item.')
    from cdmw.domain.new_item.item_properties import checked_properties
    try:
        return checked_properties(properties[0]['data'])
    except ValueError as exc:
        raise IndependentItemError(str(exc)) from exc


def package_operations(package):
    if isinstance(package, IndependentItemPackage):
        return []
    return [{'owner': f'{package.identity}/{module["id"]}', 'operations': module['data']['operations']}
            for module in package.manifest['modules'] if module['type'] == 'item.fields']


def retained_active_packages(root, layers, pending, *, exclude=(), stop_event=None, package_cache=None):
    """Read exact active providers before allocating any selected package."""
    from cdmw.services.archive_overlay_manager import _target
    from cdmw.services.independent_item_package import read_package
    from cdmw.domain.cancellation import raise_if_cancelled
    for layer in layers:
        identity = layer.get('independent_identity')
        if not layer['active'] or not identity or identity in exclude:
            continue
        raise_if_cancelled(stop_event)
        relative = f'.cdmw/independent-items/{identity}-{layer["independent_digest"]}.cditem'
        package = read_package(pending[relative] if relative in pending else _target(root, relative),
                               stop_event=stop_event, cache=package_cache)
        if package.identity != identity or package.digest != layer['independent_digest']:
            raise IndependentItemError('A retained package provider disagrees with its ownership history.')
        yield package


def migrate_v1(package, *, release='1', metadata=None):
    """Explicit migration retains UUID, original digest and logical item symbol."""
    from cdmw.services.independent_item_package import _package, package_metadata
    if not isinstance(package, IndependentItemPackage):
        raise IndependentItemError('Select an original v1 package for migration.')
    source = package_metadata(package)
    verified = _package(source, package.blobs)
    if verified.digest != package.digest:
        raise IndependentItemError('The v1 source content no longer matches its digest.')
    result = {key: source[key] for key in ('format', 'identity', 'title', 'dependencies', 'blobs')}
    result.update(version=2, release=release, requires={'item.legacy': 1},
        modules=[{'id': 'item', 'type': 'item.legacy', 'version': 1, 'required': True, 'data': source['recipe']}],
        provenance={'kind': 'v1-lowering', 'source_version': 1, 'source_identity': package.identity,
                    'source_digest': package.digest, 'symbols': {'item': 'item'}},
        metadata={} if metadata is None else metadata)
    return read_v2(result, package.blobs)
