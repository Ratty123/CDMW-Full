"""Shared physical metadata preserves logical provenance and atomic recovery."""
from copy import deepcopy
import json

import pytest

from cdmw.domain.new_item.compilation import _identity, compilation_record, compiler_stamp
from cdmw.domain.new_item.compilation_storage import read_compilation, store_compilation, validate_contexts
from cdmw.domain.new_item.independent import IndependentItemError
from cdmw.services import archive_overlay_manager as overlays
from cdmw.services.independent_item_install import load_registry, prepare_install, prepare_rebuild
from cdmw.services.independent_item_package import package_bytes
from tests.test_archive_overlay_manager import Backups
from tests.test_independent_items import setup_game
from tests.test_independent_item_regressions import files_in
from tests.test_independent_package_links import pair
from tests.test_virtual_loader import game_bytes


def record(*, linked=False):
    identity = '1' * 32
    package = {'identity': identity, 'content': 'a' * 64, 'artifact': 'b' * 64,
               'retained_artifact': 'c' * 64, 'version': 1, 'features': {'item.legacy': 1},
               'modules': [{'id': 'item', 'type': 'item.legacy', 'version': 1}]}
    graph = {'providers': {identity: {'release': '1.0.0', 'content': 'a' * 64, 'exports': {}}},
             'order': [identity], 'requirements': [], 'references': []} if linked else None
    value = compilation_record(scope='archive-contribution', packages=[package], sources={'game/file': 'd' * 64},
                               allocations={identity: 'e' * 64}, order=[identity], runtime_abi=None,
                               outputs={'mod/file': 'f' * 64}, providers={'mod/file': None}, links=graph)
    value['inputs']['compiler']['revision'] = 1
    value['identity'] = _identity(value['inputs'])
    return value


@pytest.mark.parametrize('linked', [False, True])
def test_shared_storage_roundtrips_original_inputs_identity_and_historical_compiler(linked):
    original = record(linked=linked)
    other = deepcopy(original)
    other['inputs']['outputs']['mod/file'] = '0' * 64
    other['identity'] = _identity(other['inputs'])
    contexts = {}
    first = store_compilation(original, contexts)
    second = store_compilation(other, contexts)
    assert len(contexts) == 1 and first['context'] == second['context']
    assert first['identity'] != second['identity']
    assert read_compilation(first, contexts) == original
    assert read_compilation(second, contexts) == other
    assert read_compilation(original) == original  # Older inline inventories remain readable.
    assert read_compilation(first, contexts)['inputs']['compiler'] != compiler_stamp()


@pytest.mark.parametrize('field', ['allocations', 'policy', 'links'])
def test_changed_shared_inputs_get_a_new_object_and_do_not_rewrite_history(field):
    original = record(linked=True)
    changed = deepcopy(original)
    common = changed['inputs']
    if field == 'allocations':
        common[field]['1' * 32] = '0' * 64
    elif field == 'policy':
        common[field]['order'].append('external-provider')
    else:
        common[field]['providers']['1' * 32]['release'] = '2.0.0'
    changed['identity'] = _identity(common)
    contexts = {}
    first = store_compilation(original, contexts)
    prior = deepcopy(contexts)
    second = store_compilation(changed, contexts)
    assert first['context'] != second['context'] and len(contexts) == 2
    assert contexts[first['context']] == prior[first['context']]
    assert read_compilation(first, contexts) == original
    assert read_compilation(second, contexts) == changed


def test_callers_cannot_mutate_stored_contexts_through_original_or_restored_records():
    original, contexts = record(linked=True), {}
    expected = deepcopy(original)
    stored = store_compilation(original, contexts)
    original['inputs']['allocations'].clear()
    original['inputs']['packages'][0]['content'] = '0' * 64
    restored = read_compilation(stored, contexts)
    restored['inputs']['policy']['order'].clear()
    restored['inputs']['sources'].clear()
    assert read_compilation(stored, contexts) == expected


@pytest.mark.parametrize('damage', ['missing', 'context-bytes', 'rehash-context', 'shadow-common',
                                  'identity', 'own-evidence', 'reference-version', 'context-version'])
def test_missing_corrupt_or_substituted_context_never_becomes_a_valid_compilation(damage):
    contexts = {}
    stored = store_compilation(record(linked=True), contexts)
    context = contexts[stored['context']]
    if damage == 'missing':
        contexts.clear()
    elif damage in ('context-bytes', 'rehash-context'):
        context['inputs']['allocations']['1' * 32] = '0' * 64
        if damage == 'rehash-context':
            stored['context'] = _identity(context)
            contexts[stored['context']] = context
    elif damage == 'shadow-common':
        stored['inputs']['allocations'] = context['inputs']['allocations']
    elif damage == 'identity':
        stored['identity'] = '0' * 64
    elif damage == 'own-evidence':
        stored['inputs']['outputs']['mod/file'] = '0' * 64
    elif damage == 'reference-version':
        stored['compilation_format'] = 'cdmw_compilation_future'
    else:
        context['format'] = 'cdmw_compilation_context_future'
    with pytest.raises(IndependentItemError):
        read_compilation(stored, contexts)


def installed_pair(tmp_path):
    packages = pair(tmp_path)
    setup_game(tmp_path / 'recipient')
    root, backups = tmp_path / 'recipient/game', Backups(tmp_path)
    sources = [package_bytes(p) for p in packages]
    backups.apply(prepare_install(sources, root).preparation)
    return packages, root, backups, sources


def test_joint_rebuild_reuses_context_without_losing_retired_layers_or_changing_outputs(tmp_path):
    _, root, backups, sources = installed_pair(tmp_path)
    original = overlays._load_index(root)
    before = game_bytes(root)
    bindings = load_registry(root)
    assert original['format'] == 'cdmw_owned_overlays_v2'
    assert len(original['compilation_contexts']) == 1
    backups.apply(prepare_install(sources, root, rebuild=True).preparation)
    state = overlays._load_index(root)
    assert len(state['layers']) == 4 and sum(layer['active'] for layer in state['layers']) == 2
    assert state['compilation_contexts'] == original['compilation_contexts']
    assert state['layers'][:2] == [{**layer, 'active': False, 'disabled': False} for layer in original['layers']]
    assert game_bytes(root) == before
    current = load_registry(root)
    for identity, previous in bindings['items'].items():
        assert {k: v for k, v in current['items'][identity].items() if k != 'layer'} == {
            k: v for k, v in previous.items() if k != 'layer'}


@pytest.mark.parametrize('failed_publication', [False, True])
def test_legacy_inline_history_converts_only_on_publication_and_keeps_old_validation(tmp_path, monkeypatch, failed_publication):
    packages, root, backups, sources = installed_pair(tmp_path)
    path = root / overlays.INDEX_PATH
    state = json.loads(path.read_bytes())
    original = {}
    for layer in state['layers']:
        lock = read_compilation(layer['independent_compilation'], state['compilation_contexts'])
        lock['inputs']['compiler']['revision'] = 1
        lock['identity'] = _identity(lock['inputs'])
        layer['independent_compiler'] = deepcopy(lock['inputs']['compiler'])
        layer['independent_compilation'] = lock
        original[layer['id']] = deepcopy(lock)
    state['format'] = 'cdmw_owned_overlays_v1'
    del state['compilation_contexts']
    path.write_text(json.dumps(state), encoding='utf-8')
    before = files_in(root)
    load_registry(root)
    consumer = next(layer for layer in state['layers'] if layer['independent_identity'] == packages[1].identity)
    prepared = overlays.prepare_overlay_enabled(root, consumer['id'], False)
    assert files_in(root) == before
    if failed_publication:
        write = overlays.atomic_write_bytes
        def fail_after_inventory_write(destination, data):
            write(destination, data)
            if destination == path:
                raise OSError('injected inventory publication failure')
        monkeypatch.setattr(overlays, 'atomic_write_bytes', fail_after_inventory_write)
        with pytest.raises(OSError, match='injected inventory'):
            backups.apply(prepared)
        assert files_in(root) == before
        assert overlays._load_index(root)['format'] == 'cdmw_owned_overlays_v1'
    else:
        backups.apply(prepared)
        stored = overlays._load_index(root)
        assert stored['format'] == 'cdmw_owned_overlays_v2'
        for layer in stored['layers']:
            assert read_compilation(layer['independent_compilation'], stored['compilation_contexts']) == original[layer['id']]
        with pytest.raises(IndependentItemError, match='Rebuild selected item'):
            prepare_install([sources[0]], root)


@pytest.mark.parametrize('damage', ['missing-context', 'context-bytes', 'duplicate-json', 'old-inventory-version'])
def test_inventory_reader_and_rebuild_refuse_broken_shared_storage_without_writing(tmp_path, damage):
    packages, root, _, _ = installed_pair(tmp_path)
    path = root / overlays.INDEX_PATH
    state = json.loads(path.read_bytes())
    context = next(iter(state['compilation_contexts'].values()))
    if damage == 'missing-context':
        state['compilation_contexts'].clear()
    elif damage == 'context-bytes':
        context['inputs']['policy']['order'].reverse()
    elif damage == 'old-inventory-version':
        state['format'] = 'cdmw_owned_overlays_v1'
    payload = json.dumps(state)
    if damage == 'duplicate-json':
        payload = payload.replace('"compilation_contexts": {', '"compilation_contexts": {}, "compilation_contexts": {', 1)
    path.write_text(payload, encoding='utf-8')
    before = files_in(root)
    with pytest.raises(ValueError):
        overlays.list_installed_overlays(root)
    with pytest.raises(ValueError):
        prepare_rebuild(packages[1].identity, root)
    assert files_in(root) == before


@pytest.mark.parametrize('field', ['allocations', 'links'])
def test_rehashed_shared_record_still_has_to_match_owned_bindings(tmp_path, field):
    packages, root, _, _ = installed_pair(tmp_path)
    path = root / overlays.INDEX_PATH
    state = json.loads(path.read_bytes())
    layer = next(row for row in state['layers'] if row['independent_identity'] == packages[1].identity)
    lock = read_compilation(layer['independent_compilation'], state['compilation_contexts'])
    if field == 'allocations':
        lock['inputs']['allocations'][packages[1].identity] = '0' * 64
    else:
        lock['inputs']['links']['providers'][packages[0].identity]['exports']['item']['value'] += 1
    lock['identity'] = _identity(lock['inputs'])
    layer['independent_compilation'] = store_compilation(lock, state['compilation_contexts'])
    validate_contexts(state['compilation_contexts'])
    path.write_text(json.dumps(state), encoding='utf-8')
    before = files_in(root)
    with pytest.raises(IndependentItemError, match='ownership layer|retained identity bindings'):
        load_registry(root)
    assert files_in(root) == before
