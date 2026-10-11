"""Exact installation references, not a claim of game or save compatibility."""
from copy import deepcopy

import pytest

from cdmw.domain.new_item.independent import IndependentItemError
from cdmw.domain.new_item.package_links import contract, resolve_package_graph, validate_link_record
from cdmw.domain.virtual_loader import VirtualProfile
from cdmw.services import archive_overlay_manager as overlays
from cdmw.services.independent_item_install import load_registry, prepare_install, prepare_remove
from cdmw.services.independent_item_package import canonical, package_bytes, read_package
from cdmw.services.independent_mod_package import migrate_v1, read_v2
from cdmw.services.virtual_loader_composition import prepare_profile
from cdmw.services.virtual_loader_state import load_profile, publish_profile
from tests.test_archive_overlay_manager import Backups
from tests.test_independent_items import authored, setup_game
from tests.test_independent_item_regressions import files_in


def linked(package, providers=(), *, symbol='item', exports=()):
    base = migrate_v1(package) if not hasattr(package, 'manifest') else package
    meta = deepcopy(base.manifest)
    meta['requires']['package.links'] = 1
    meta['modules'] = [module for module in meta['modules'] if module['type'] != 'package.links']
    meta['modules'].append({'id': 'links', 'type': 'package.links', 'version': 1, 'required': True,
        'data': {'packages': [{'identity': p.identity, 'release': contract(p)['release'], 'content': p.digest} for p in providers],
                 'exports': [{'symbol': name, 'kind': 'item', 'module': 'item', 'object': 'item', 'lifetime': 'installation'} for name in exports],
                 'references': [{'id': f'uses-{index}', 'package': p.identity, 'symbol': symbol, 'kind': 'item',
                                 'ownership': 'borrowed', 'lifetime': 'installation'} for index, p in enumerate(providers)]}})
    return read_v2(meta, base.blobs)


def pair(tmp_path, *, alias=False):
    _, provider = authored(tmp_path / 'provider')
    if alias:
        provider = linked(provider, exports=('items/travel-sword',))
    _, consumer = authored(tmp_path / 'consumer')
    consumer = linked(consumer, (provider,), symbol='items/travel-sword' if alias else 'item')
    return provider, consumer


def paths_for(tmp_path, packages):
    result = []
    for index, package in enumerate(packages):
        path = tmp_path / f'selected-{index}.cditem'
        path.write_bytes(package_bytes(package))
        result.append(path)
    return tuple(result)


@pytest.mark.parametrize('virtual', [False, True])
@pytest.mark.parametrize('reverse', [False, True])
def test_exact_typed_references_bind_in_both_orders_and_routes(tmp_path, virtual, reverse):
    provider, consumer = pair(tmp_path, alias=True)
    setup_game(tmp_path / 'recipient')
    root, backups = tmp_path / 'recipient/game', Backups(tmp_path)
    selected = [provider, consumer][::-1] if reverse else [provider, consumer]
    if virtual:
        paths = paths_for(tmp_path, selected)
        publish_profile(prepare_profile(VirtualProfile(paths), root))
        lock = load_profile(root)['compilation']
    else:
        backups.apply(prepare_install([package_bytes(p) for p in selected], root).preparation)
        from cdmw.domain.new_item.compilation_storage import read_compilation
        state = overlays._load_index(root)
        layer = next(row for row in state['layers'] if row['independent_identity'] == consumer.identity)
        lock = read_compilation(layer['independent_compilation'], state['compilation_contexts'])
    assert lock['format'] == 'cdmw_compilation_v2'
    graph = validate_link_record(lock['inputs']['links'])
    assert graph['order'] == [provider.identity, consumer.identity]
    assert graph['requirements'][0]['content'] == provider.digest
    value = load_registry(root)['items'][provider.identity]['values']['iteminfo']['item']
    assert graph['providers'][provider.identity]['exports']['items/travel-sword']['value'] == value
    assert read_package(package_bytes(consumer)).manifest == consumer.manifest
    before = files_in(root)
    with pytest.raises(IndependentItemError, match='missing required package'):
        if virtual:
            prepare_profile(VirtualProfile((paths[selected.index(consumer)],)), root)
        else:
            prepare_remove(provider.identity, root)
    assert files_in(root) == before
    if virtual:
        publish_profile(prepare_profile(VirtualProfile(), root))
    else:
        backups.apply(prepare_remove(consumer.identity, root))
        backups.apply(prepare_remove(provider.identity, root))


def test_existing_v1_provider_rebuild_disable_update_and_reinstall(tmp_path):
    provider, consumer = pair(tmp_path)
    setup_game(tmp_path / 'recipient')
    root, backups = tmp_path / 'recipient/game', Backups(tmp_path)
    backups.apply(prepare_install([package_bytes(provider)], root).preparation)
    backups.apply(prepare_install([package_bytes(consumer)], root).preparation)
    original = load_registry(root)
    provider_layer = original['items'][provider.identity]['layer']
    consumer_layer = original['items'][consumer.identity]['layer']
    from cdmw.services.archive_overlay_rebuild import prepare_overlay_rebuild
    backups.apply(prepare_overlay_rebuild(root))
    before = files_in(root)
    with pytest.raises(IndependentItemError, match='missing required package'):
        overlays.prepare_overlay_enabled(root, provider_layer, False)
    updated_provider = migrate_v1(provider, release='2')
    with pytest.raises(IndependentItemError, match='release/content differs'):
        prepare_install([package_bytes(updated_provider)], root)
    assert files_in(root) == before
    backups.apply(overlays.prepare_overlay_enabled(root, consumer_layer, False))
    backups.apply(prepare_remove(provider.identity, root))
    with pytest.raises(IndependentItemError, match='missing required package'):
        overlays.prepare_overlay_enabled(root, consumer_layer, True)
    backups.apply(prepare_install([package_bytes(provider)], root).preparation)
    backups.apply(overlays.prepare_overlay_enabled(root, consumer_layer, True))
    updated_consumer = linked(consumer, (updated_provider,))
    backups.apply(prepare_install([package_bytes(updated_consumer), package_bytes(updated_provider)], root).preparation)
    for identity, row in original['items'].items():
        assert load_registry(root)['items'][identity]['values'] == row['values']


def test_linked_packages_can_be_disabled_enabled_and_removed_together(tmp_path):
    provider, consumer = pair(tmp_path)
    setup_game(tmp_path / 'recipient')
    root, backups = tmp_path / 'recipient/game', Backups(tmp_path)
    backups.apply(prepare_install([package_bytes(provider), package_bytes(consumer)], root).preparation)
    registry = load_registry(root)
    layers = tuple(row['layer'] for row in registry['items'].values())
    for enabled in (False, True):
        count = backups.count
        backups.apply(overlays.prepare_overlay_enabled(root, layers, enabled))
        assert backups.count == count + 1
        assert all(row.enabled == enabled for row in overlays.list_installed_overlays(root))
    count = backups.count
    backups.apply(prepare_remove((provider.identity, consumer.identity), root))
    assert backups.count == count + 1 and not overlays.list_installed_overlays(root)
    assert load_registry(root) == registry


@pytest.mark.parametrize('virtual', [False, True])
def test_missing_provider_refuses_before_snapshot_or_allocation(tmp_path, monkeypatch, virtual):
    _, consumer = pair(tmp_path)
    setup_game(tmp_path / 'recipient')
    root = tmp_path / 'recipient/game'
    before = files_in(root)
    def forbidden(*args, **kwargs):
        raise AssertionError('Dependencies must be negotiated before reading a game snapshot.')
    monkeypatch.setattr('cdmw.services.independent_item_install.stock_snapshot', forbidden)
    with pytest.raises(IndependentItemError, match='missing required package'):
        if virtual:
            prepare_profile(VirtualProfile(paths_for(tmp_path, (consumer,))), root)
        else:
            prepare_install([package_bytes(consumer)], root)
    assert files_in(root) == before


@pytest.mark.parametrize('mutation,match', [
    ('duplicate-export', 'ambiguous exported'), ('missing-owned-object', 'Only the owned'),
    ('duplicate-pin', 'duplicate required'), ('self-pin', 'self-referencing'),
    ('unpinned-reference', 'exact declared'), ('runtime-lifetime', 'Unsupported reference'),
    ('transfer-ownership', 'Unsupported reference'), ('unknown-reference-kind', 'Unsupported reference'),
    ('duplicate-reference', 'duplicate installation'), ('optional-feature', 'Optional behavior'),
    ('duplicate-module', 'only one package.links'), ('unknown-field', 'module fields'),
])
def test_malformed_link_contracts_refuse_at_envelope_admission(tmp_path, mutation, match):
    provider, consumer = pair(tmp_path, alias=True)
    meta = deepcopy(consumer.manifest)
    module = meta['modules'][-1]
    data = module['data']
    if mutation == 'duplicate-export':
        data['exports'] = [{'symbol': 'item', 'kind': 'item', 'module': 'item', 'object': 'item', 'lifetime': 'installation'}]
    elif mutation == 'missing-owned-object':
        data['exports'] = [{'symbol': 'other', 'kind': 'quest', 'module': 'item', 'object': 'quest', 'lifetime': 'installation'}]
    elif mutation == 'duplicate-pin':
        data['packages'] *= 2
    elif mutation == 'self-pin':
        data['packages'][0]['identity'] = consumer.identity
    elif mutation == 'unpinned-reference':
        data['packages'] = []
    elif mutation == 'runtime-lifetime':
        data['references'][0]['lifetime'] = 'runtime'
    elif mutation == 'transfer-ownership':
        data['references'][0]['ownership'] = 'owned'
    elif mutation == 'unknown-reference-kind':
        data['references'][0]['kind'] = 'quest'
    elif mutation == 'duplicate-reference':
        data['references'] *= 2
    elif mutation == 'optional-feature':
        module['required'] = False
    elif mutation == 'duplicate-module':
        meta['modules'].append(dict(module, id='links2'))
    else:
        data['ignored-pointers'] = []
    with pytest.raises(IndependentItemError, match=match):
        read_v2(meta, consumer.blobs)


def test_ambiguous_provider_cycle_and_missing_export_refuse(tmp_path):
    provider, consumer = pair(tmp_path)
    with pytest.raises(IndependentItemError, match='Ambiguous package provider'):
        resolve_package_graph((provider, consumer, provider))
    cyclic = linked(provider, (consumer,))
    # Cycles are diagnosed before pin comparison; no recursive content hashing
    # or fabricated mutually self-consistent digests are needed to reject them.
    with pytest.raises(IndependentItemError, match='dependency cycle'):
        resolve_package_graph((cyclic, consumer))
    missing = linked(consumer, (provider,), symbol='items/missing')
    with pytest.raises(IndependentItemError, match='missing or incompatible exported'):
        resolve_package_graph((provider, missing))


def test_graph_budget_and_cancellation(tmp_path, monkeypatch):
    import threading
    from cdmw.domain.cancellation import RunCancelled
    provider, consumer = pair(tmp_path)
    stop = threading.Event()
    stop.set()
    with pytest.raises(RunCancelled):
        resolve_package_graph((provider, consumer), stop_event=stop)
    monkeypatch.setattr('cdmw.domain.new_item.package_links.MAX_LINKS', 3)
    with pytest.raises(IndependentItemError, match='link budget'):
        resolve_package_graph((provider, consumer))


def test_virtual_links_survive_actual_preparation_process_and_refuse_cross_deployment(tmp_path):
    from cdmw.services.virtual_loader_process import prepare_profile_in_subprocess
    provider, consumer = pair(tmp_path)
    setup_game(tmp_path / 'recipient')
    root, backups = tmp_path / 'recipient/game', Backups(tmp_path)
    paths = paths_for(tmp_path, (provider, consumer))
    backups.apply(prepare_install([paths[0]], root).preparation)
    before = files_in(root)
    with pytest.raises(IndependentItemError, match='same deployment'):
        prepare_profile(VirtualProfile((paths[1],)), root)
    assert files_in(root) == before
    backups.apply(prepare_remove(provider.identity, root))
    prepared = prepare_profile_in_subprocess(VirtualProfile(paths), root)
    publish_profile(prepared)
    assert load_profile(root)['compilation']['inputs']['links']['references'][0]['package'] == provider.identity


@pytest.mark.parametrize('field', ['content', 'value', 'lifetime', 'order', 'reference', 'extra-provider'])
def test_compiled_graph_tampering_refuses(tmp_path, field):
    from cdmw.domain.new_item.compilation import validate_compilation, _identity
    from cdmw.services.virtual_loader_state import validate_profile
    provider, consumer = pair(tmp_path)
    setup_game(tmp_path / 'recipient')
    root = tmp_path / 'recipient/game'
    import json
    prepared = prepare_profile(VirtualProfile(paths_for(tmp_path, (provider, consumer))), root)
    profile = json.loads(prepared.profile)
    lock = profile['compilation']
    graph = lock['inputs']['links']
    if field == 'content':
        graph['providers'][provider.identity]['content'] = 'f' * 64
    elif field == 'value':
        graph['providers'][provider.identity]['exports']['item']['value'] = True
    elif field == 'lifetime':
        graph['providers'][provider.identity]['exports']['item']['lifetime'] = 'save'
    elif field == 'order':
        graph['order'].reverse()
    elif field == 'reference':
        graph['references'][0]['symbol'] = 'missing'
    else:
        identity = 'd' * 32
        graph['providers'][identity] = {'release': '1', 'content': 'd' * 64, 'exports': {}}
        graph['order'].append(identity)
    # Invalid closure refuses even with a recomputed checksum. A checksum is
    # provenance, not permission to fabricate a graph or expand the profile.
    lock['identity'] = _identity(lock['inputs'])
    with pytest.raises(ValueError, match='graph|compilation'):
        validate_profile(profile) if field == 'extra-provider' else validate_compilation(lock)


def test_retained_provider_changed_after_review_cannot_publish_consumer(tmp_path):
    import os
    provider, consumer = pair(tmp_path)
    setup_game(tmp_path / 'recipient')
    root, backups = tmp_path / 'recipient/game', Backups(tmp_path)
    backups.apply(prepare_install([package_bytes(provider)], root).preparation)
    prepared = prepare_install([package_bytes(consumer)], root).preparation
    retained = root / f'.cdmw/independent-items/{provider.identity}-{provider.digest}.cditem'
    stamp = retained.stat()
    data = retained.read_bytes()
    retained.write_bytes(data[:-1] + bytes([data[-1] ^ 1]))
    os.utime(retained, ns=(stamp.st_atime_ns, stamp.st_mtime_ns))
    before = files_in(root)
    with pytest.raises(ValueError, match='[Ss]ource'):
        backups.apply(prepared)
    assert files_in(root) == before and backups.count == 1


@pytest.mark.parametrize('virtual', [False, True])
def test_graph_publication_failure_preserves_previous_profile(tmp_path, monkeypatch, virtual):
    from cdmw.services import virtual_loader_state as virtual_state
    provider, consumer = pair(tmp_path)
    setup_game(tmp_path / 'recipient')
    root, backups = tmp_path / 'recipient/game', Backups(tmp_path)
    paths = paths_for(tmp_path, (provider, consumer))
    if virtual:
        publish_profile(prepare_profile(VirtualProfile((paths[0],)), root))
        prepared = prepare_profile(VirtualProfile(paths), root)
        owner = virtual_state
    else:
        backups.apply(prepare_install([paths[0]], root).preparation)
        prepared = prepare_install(paths, root).preparation
        owner = overlays
    original_registry = load_registry(root)
    original_profile = load_profile(root)
    write = owner.atomic_write_bytes
    def fail(path, data):
        if path.name == ('profile.json' if virtual else 'independent-items.json') and path.parent == root / ('.cdmw/virtual-loader' if virtual else '.cdmw'):
            raise OSError('injected graph publication failure')
        write(path, data)
    monkeypatch.setattr(owner, 'atomic_write_bytes', fail)
    with pytest.raises(OSError, match='injected graph'):
        publish_profile(prepared) if virtual else backups.apply(prepared)
    assert load_registry(root) == original_registry
    assert load_profile(root) == original_profile


def test_compiled_reference_cannot_claim_another_retained_item_id(tmp_path):
    import json
    from dataclasses import replace
    from cdmw.domain.new_item.compilation import _identity
    provider, consumer = pair(tmp_path)
    setup_game(tmp_path / 'recipient')
    root = tmp_path / 'recipient/game'
    prepared = prepare_profile(VirtualProfile(paths_for(tmp_path, (provider, consumer))), root)
    profile = json.loads(prepared.profile)
    lock = profile['compilation']
    providers = lock['inputs']['links']['providers']
    providers[provider.identity]['exports']['item']['value'] = providers[consumer.identity]['exports']['item']['value']
    lock['identity'] = _identity(lock['inputs'])
    before = files_in(root)
    with pytest.raises(IndependentItemError, match='retained identity bindings'):
        publish_profile(replace(prepared, profile=canonical(profile)))
    assert files_in(root) == before
