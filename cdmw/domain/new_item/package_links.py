"""Bounded, exact installation dependencies; no inferred game-byte relocation."""
from copy import deepcopy
import heapq
import re

from cdmw.domain.cancellation import raise_if_cancelled
from cdmw.domain.new_item.independent import IndependentItemError, IndependentItemPackage, package_id

MAX_PACKAGES = 4096
MAX_LINKS = 4096


def check_graph_budget(packages, links):
    if packages > MAX_PACKAGES or links > MAX_LINKS:
        raise IndependentItemError('The active package dependency graph exceeds its package or link budget.')


def _symbol(value):
    return isinstance(value, str) and re.fullmatch(r'[a-z][a-z0-9_-]{0,63}(?:/[a-z][a-z0-9_-]{0,63}){0,3}', value) is not None


def _release(value):
    return isinstance(value, str) and re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._+-]{0,63}', value) is not None


def _checksum(value):
    return isinstance(value, str) and re.fullmatch('[0-9a-f]{64}', value) is not None


def decode_links(data, identity, *, legacy):
    if not isinstance(data, dict) or set(data) != {'packages', 'exports', 'references'}:
        raise IndependentItemError('Invalid package.links module fields.')
    for name in data:
        if not isinstance(data[name], list) or len(data[name]) > MAX_LINKS:
            raise IndependentItemError('The package dependency inventory exceeds its budget.')
    providers = set()
    for pin in data['packages']:
        if not isinstance(pin, dict) or set(pin) != {'identity', 'release', 'content'}:
            raise IndependentItemError('Invalid required package pin.')
        provider = package_id(pin['identity'])
        if provider == identity or provider in providers or not _release(pin['release']) or not _checksum(pin['content']):
            raise IndependentItemError('Invalid, self-referencing or duplicate required package pin.')
        providers.add(provider)
    exports = {'item'} if legacy else set()
    for row in data['exports']:
        if (not isinstance(row, dict) or set(row) != {'symbol', 'kind', 'module', 'object', 'lifetime'}
                or not _symbol(row['symbol']) or row['symbol'] in exports):
            raise IndependentItemError('Invalid or ambiguous exported object symbol.')
        if not legacy or (row['kind'], row['module'], row['object'], row['lifetime']) != ('item', 'item', 'item', 'installation'):
            raise IndependentItemError('Only the owned legacy item can be exported with installation lifetime.')
        exports.add(row['symbol'])
    references = set()
    for row in data['references']:
        if (not isinstance(row, dict) or set(row) != {'id', 'package', 'symbol', 'kind', 'ownership', 'lifetime'}
                or not _symbol(row['id']) or row['id'] in references or not _symbol(row['symbol'])):
            raise IndependentItemError('Invalid or duplicate installation reference.')
        provider = package_id(row['package'])
        if provider not in providers:
            raise IndependentItemError('An installation reference requires an exact declared package pin.')
        if (row['kind'], row['ownership'], row['lifetime']) != ('item', 'borrowed', 'installation'):
            raise IndependentItemError('Unsupported reference kind, ownership or lifetime.')
        references.add(row['id'])
    return deepcopy(data)


def contract(package):
    legacy = isinstance(package, IndependentItemPackage) or any(m['type'] == 'item.legacy' for m in package.manifest['modules'])
    modules = [] if isinstance(package, IndependentItemPackage) else [m for m in package.manifest['modules'] if m['type'] == 'package.links']
    if len(modules) > 1:
        raise IndependentItemError('A package permits only one package.links module.')
    links = decode_links(modules[0]['data'], package.identity, legacy=legacy) if modules else {'packages': [], 'exports': [], 'references': []}
    exports = {row['symbol']: row for row in links['exports']}
    if legacy:
        exports['item'] = {'symbol': 'item', 'kind': 'item', 'module': 'item', 'object': 'item', 'lifetime': 'installation'}
    return {'release': 'v1' if isinstance(package, IndependentItemPackage) else package.manifest['release'],
            'content': package.digest, 'exports': exports, 'links': links, 'declared': bool(modules)}


def resolve_package_graph(packages, *, bindings=None, stop_event=None):
    """Resolve one deployment's active packages before allocation, then bind IDs.

    References express admission/lifetime requirements only. No native pointers,
    resource paths or arbitrary byte offsets are synthesized from these records.
    """
    return resolve_package_contracts(((package.identity, contract(package)) for package in packages),
                                     bindings=bindings, stop_event=stop_event)


def resolve_package_contracts(contracts, *, bindings=None, stop_event=None):
    """Keep only bounded declarations, never the providers' resource blobs."""
    inventory, declared, budget = {}, False, 0
    for identity, row in contracts:
        raise_if_cancelled(stop_event)
        if identity in inventory:
            raise IndependentItemError(f'Ambiguous package provider {identity}.')
        inventory[identity] = row
        declared |= row['declared']
        budget += len(row['exports']) + len(row['links']['packages']) + len(row['links']['references'])
        if declared:
            check_graph_budget(len(inventory), budget)
    if not declared:
        return None
    edges = {identity: set() for identity in inventory}
    dependents = {identity: [] for identity in inventory}
    requirements, references = [], []
    for identity, row in inventory.items():
        raise_if_cancelled(stop_event)
        for pin in row['links']['packages']:
            provider = pin['identity']
            if provider not in inventory:
                raise IndependentItemError(f'{identity}: missing required package {provider}; select its exact release in the same deployment.')
            edges[identity].add(provider)
            dependents[provider].append(identity)
            requirements.append({'owner': identity, 'package': provider, 'release': pin['release'], 'content': pin['content']})
        references.extend({'owner': identity, **reference} for reference in row['links']['references'])
    counts = {identity: len(providers) for identity, providers in edges.items()}
    ready = [identity for identity, count in counts.items() if not count]
    heapq.heapify(ready)
    order = []
    while ready:
        raise_if_cancelled(stop_event)
        identity = heapq.heappop(ready)
        order.append(identity)
        for dependent in dependents[identity]:
            counts[dependent] -= 1
            if not counts[dependent]:
                heapq.heappush(ready, dependent)
    if len(order) != len(inventory):
        raise IndependentItemError('Forbidden package dependency cycle: ' + ', '.join(sorted(key for key, count in counts.items() if count)))
    for pin in requirements:
        supplied = inventory[pin['package']]
        if any(pin[key] != supplied[key] for key in ('release', 'content')):
            raise IndependentItemError(f'{pin["owner"]}: required package {pin["package"]} release/content differs from its exact pin.')
    for reference in references:
        exported = inventory[reference['package']]['exports'].get(reference['symbol'])
        if exported is None or any(exported[key] != reference[key] for key in ('kind', 'lifetime')):
            raise IndependentItemError(f'{reference["owner"]}/{reference["id"]}: missing or incompatible exported object '
                                       f'{reference["package"]}/{reference["symbol"]}.')
    providers = {}
    for identity in sorted(inventory):
        row = inventory[identity]
        exports = {}
        for symbol in sorted(row['exports']):
            exports[symbol] = {'kind': 'item', 'lifetime': 'installation', 'value': None}
        providers[identity] = {'release': row['release'], 'content': row['content'], 'exports': exports}
    graph = {'providers': providers, 'requirements': sorted(requirements, key=lambda row: (row['owner'], row['package'])),
             'references': sorted(references, key=lambda row: (row['owner'], row['id'])), 'order': order}
    return bind_package_graph(graph, bindings) if bindings is not None else graph


def bind_package_graph(graph, bindings):
    if graph is None:
        return None
    graph = deepcopy(graph)
    for identity, provider in graph['providers'].items():
        for symbol, exported in provider['exports'].items():
            value = bindings.get(identity, {}).get('values', {}).get('iteminfo', {}).get('item')
            if type(value) is not int or not 1 <= value <= 0xffffffff:
                raise IndependentItemError(f'{identity}/{symbol}: exported item has no verified identity binding.')
            exported['value'] = value
    return validate_link_record(graph)


def validate_link_bindings(graph, bindings):
    if bind_package_graph(graph, bindings) != graph:
        raise IndependentItemError('The compiled package dependency graph disagrees with retained identity bindings.')


def validate_link_record(value):
    """Validate a resolved compilation lock, including its typed reference closure."""
    def fail():
        raise IndependentItemError('Invalid compiled package dependency graph.')
    if (not isinstance(value, dict) or set(value) != {'providers', 'requirements', 'references', 'order'}
            or not isinstance(value['providers'], dict) or not 1 <= len(value['providers']) <= MAX_PACKAGES
            or not isinstance(value['order'], list) or len(value['order']) != len(value['providers'])
            or any(not isinstance(key, str) for key in value['order'])
            or set(value['order']) != set(value['providers'])):
        fail()
    for identity, row in value['providers'].items():
        package_id(identity)
        if (not isinstance(row, dict) or set(row) != {'release', 'content', 'exports'} or not _release(row['release'])
                or not _checksum(row['content']) or not isinstance(row['exports'], dict) or len(row['exports']) > MAX_LINKS + 1):
            fail()
        for symbol, exported in row['exports'].items():
            if (not _symbol(symbol) or not isinstance(exported, dict) or set(exported) != {'kind', 'lifetime', 'value'}
                    or exported['kind'] != 'item' or exported['lifetime'] != 'installation'
                    or type(exported['value']) is not int or not 1 <= exported['value'] <= 0xffffffff):
                fail()
    if (any(not isinstance(value[key], list) for key in ('requirements', 'references'))
            or len(value['requirements']) + len(value['references']) + sum(len(row['exports']) for row in value['providers'].values()) > MAX_LINKS):
        fail()
    positions = {identity: index for index, identity in enumerate(value['order'])}
    edges = set()
    for row in value['requirements']:
        if not isinstance(row, dict) or set(row) != {'owner', 'package', 'release', 'content'}:
            fail()
        owner, provider = package_id(row['owner']), package_id(row['package'])
        supplied = value['providers'].get(provider)
        if (owner not in positions or supplied is None or positions[provider] >= positions[owner]
                or (owner, provider) in edges or any(row[key] != supplied[key] for key in ('release', 'content'))):
            fail()
        edges.add((owner, provider))
    seen = set()
    for row in value['references']:
        if (not isinstance(row, dict) or set(row) != {'owner', 'id', 'package', 'symbol', 'kind', 'ownership', 'lifetime'}
                or not _symbol(row['id']) or not _symbol(row['symbol'])):
            fail()
        owner, provider = package_id(row['owner']), package_id(row['package'])
        exported = value['providers'].get(provider, {}).get('exports', {}).get(row['symbol'])
        if ((owner, provider) not in edges or (owner, row['id']) in seen or exported is None
                or row['ownership'] != 'borrowed' or any(row[key] != exported[key] for key in ('kind', 'lifetime'))):
            fail()
        seen.add((owner, row['id']))
    return value
