"""Recompilation bindings and exact wrapper guards on the real composition routes."""
import os
from uuid import uuid4

import pytest

from cdmw.core.mod_compatibility import SEMANTIC_EXPORT_FILE
from cdmw.domain.new_item.independent import IndependentItemError
from cdmw.domain.virtual_loader import VirtualLoaderError, VirtualProfile
from cdmw.services.independent_item_compatibility import prepare_independent_mod_merge
from cdmw.services.independent_item_install import prepare_install
from cdmw.services.independent_item_package import from_plan, package_bytes
from cdmw.services.mod_merge_service import export_merged_mod
from cdmw.services.virtual_loader_process import prepare_profile_in_subprocess
from cdmw.services.virtual_loader_state import publish_profile, load_profile
from tests.test_archive_overlay_manager import Backups, shop_spec
from tests.test_independent_item_fields import field_package
from tests.test_independent_item_regressions import files_in
from tests.test_independent_items import setup_game
from tests.test_semantic_merge_admission import exported_fields


@pytest.mark.parametrize('folder_selection', [False, True])
def test_semantic_wrapper_passes_real_virtual_preparation_process(tmp_path, folder_selection):
    folder, package, _ = exported_fields(tmp_path / 'producer', value=1)
    setup_game(tmp_path / 'recipient')
    root = tmp_path / 'recipient/game'
    wrapper = folder / SEMANTIC_EXPORT_FILE
    selection = VirtualProfile((), (folder,)) if folder_selection else VirtualProfile((wrapper,))
    prepared = prepare_profile_in_subprocess(selection, root)
    publish_profile(prepared)
    profile = load_profile(root)
    assert set(profile['items']) == {package.identity}
    assert str(wrapper) in dict(profile['sources'])


@pytest.mark.parametrize('virtual', [False, True])
def test_same_size_wrapper_change_after_review_never_publishes(tmp_path, virtual):
    from cdmw.services.virtual_loader_composition import prepare_profile
    folder, _, _ = exported_fields(tmp_path / 'producer', value=1)
    setup_game(tmp_path / 'recipient')
    root = tmp_path / 'recipient/game'
    wrapper = folder / SEMANTIC_EXPORT_FILE
    if virtual:
        prepared = prepare_profile(VirtualProfile((), (folder,)), root)
    else:
        prepared = prepare_install([wrapper], root).preparation
    before = files_in(root)
    stamp = wrapper.stat()
    data = bytearray(wrapper.read_bytes())
    data[-1] ^= 1
    wrapper.write_bytes(data)
    os.utime(wrapper, ns=(stamp.st_atime_ns, stamp.st_mtime_ns))
    with pytest.raises(ValueError, match='[Cc]hanged|[Mm]ismatch'):
        publish_profile(prepared) if virtual else Backups(tmp_path / 'recipient').apply(prepared)
    assert files_in(root) == before


def test_semantic_item_binding_collision_does_not_renumber_retired_or_live_ids(tmp_path):
    service, snapshot, _ = setup_game(tmp_path / 'producer')
    legacy = from_plan(service.plan(shop_spec('ExportedLegacy'), snapshot, capture_independent=True), uuid4().hex)
    keep = field_package(snapshot, value=1)
    root = tmp_path / 'producer/game'
    Backups(tmp_path / 'producer').apply(prepare_install([package_bytes(legacy), package_bytes(keep)], root).preparation)
    folder = export_merged_mod(prepare_independent_mod_merge(root), tmp_path / 'export').package_root
    other_service, other_snapshot, _ = setup_game(tmp_path / 'recipient')
    other = from_plan(other_service.plan(shop_spec('ReservedElsewhere'), other_snapshot, capture_independent=True), uuid4().hex)
    recipient = tmp_path / 'recipient/game'
    Backups(tmp_path / 'recipient').apply(prepare_install([package_bytes(other)], recipient).preparation)
    before = files_in(recipient)
    with pytest.raises(IndependentItemError, match='Conflicting|relocation'):
        prepare_install([folder], recipient)
    assert files_in(recipient) == before


def test_worker_cannot_promote_an_unselected_artifact_to_a_parsed_source_witness(tmp_path):
    from cdmw.services.virtual_loader_process import _revision
    root = tmp_path.resolve()
    unselected = root / 'unselected.cditem'
    value = {'files': [[str(unselected), [10, 20, 30]]], 'payloads': [],
             'indexes': [[str(unselected), '0' * 64]], 'catalogue': []}
    admitted = _revision(value, (root,), artifact_paths={unselected})
    assert admitted.indexes == ((unselected, '0' * 64),)
    with pytest.raises(VirtualLoaderError, match='invalid or incomplete'):
        _revision(value, (root,), artifact_paths={root / SEMANTIC_EXPORT_FILE})


@pytest.mark.parametrize('name', [SEMANTIC_EXPORT_FILE, 'CrimsonDesert.exe', '0.paver'])
def test_file_witness_can_never_be_an_archive_coordinate(tmp_path, name):
    from cdmw.services.virtual_loader_process import _revision
    root = tmp_path.resolve()
    index, artifact, payload = root / '0.pamt', root / name, root / '0.paz'
    entry = {'path': 'character/test.txt', 'pamt_path': str(index), 'paz_file': str(payload),
             'offset': 0, 'comp_size': 1, 'orig_size': 1, 'flags': 0, 'paz_index': 0}
    value = {'files': [[str(index), [10, 20, 30]], [str(payload), [1, 20, 30]]],
             'payloads': [[entry, '0' * 64]], 'indexes': [[str(index), '1' * 64]], 'catalogue': []}
    admitted = _revision(value, (root,), artifact_paths={artifact})
    assert admitted.payloads[0].entry.pamt_path == index
    assert admitted.indexes == ((index, '1' * 64),)
    value['files'][0][0] = value['indexes'][0][0] = entry['pamt_path'] = str(artifact)
    with pytest.raises(VirtualLoaderError, match='invalid or incomplete'):
        _revision(value, (root,), artifact_paths={artifact})


@pytest.mark.parametrize('omit_all_guards,rebind_cache', [
    pytest.param(False, False, id='parsed-index'),
    pytest.param(True, False, id='all-stale-cache'),
    pytest.param(True, True, id='all-rebound-cache'),
])
def test_real_worker_result_cannot_omit_selected_semantic_witness(tmp_path, monkeypatch, omit_all_guards, rebind_cache):
    import json
    from pathlib import Path
    from cdmw.domain.new_item.compilation import _identity
    from cdmw.services import virtual_loader_process as owner
    from cdmw.services.virtual_loader_cache import _guard_identity, _input_identity, _key
    from cdmw.services.independent_item_package import canonical, digest
    folder, _, _ = exported_fields(tmp_path / 'producer', value=1)
    setup_game(tmp_path / 'recipient')
    root = tmp_path / 'recipient/game'
    wrapper = str(folder / SEMANTIC_EXPORT_FILE)
    before = files_in(root)

    def run(command, **kwargs):
        output = Path(command[command.index('--output') + 1])
        source = Path(command[command.index('--input') + 1])
        assert owner.run_virtual_profile_worker(source, output) == 0
        result = json.loads(output.read_bytes())
        assert wrapper in dict(result['external_source']['indexes'])
        result['external_source']['indexes'] = [row for row in result['external_source']['indexes'] if row[0] != wrapper]
        if omit_all_guards:
            result['external_source']['files'] = [row for row in result['external_source']['files'] if row[0] != wrapper]
            path = output.parent / (result['profile'][0] + '.bin')
            profile = json.loads(path.read_bytes())
            profile['sources'] = [row for row in profile['sources'] if row[0] != wrapper]
            profile['inventories'] = []
            profile['compilation']['inputs']['sources'] = dict(profile['sources'])
            profile['compilation']['identity'] = _identity(profile['compilation']['inputs'])
            if rebind_cache:
                # Keep the forged profile internally valid so the parent's
                # independently retained semantic witnesses must reject it.
                record = profile['build_cache']
                record['inputs'] = _input_identity(profile['compilation'])
                record['guards'] = _guard_identity(profile['catalogue'], profile['inventories'])
                record['key'] = _key(record)
                owner.validate_profile(profile)
            encoded = canonical(profile)
            checksum = digest(encoded)
            (output.parent / (checksum + '.bin')).write_bytes(encoded)
            result['profile'] = [checksum, len(encoded)]
        output.write_bytes(canonical(result))
        if not omit_all_guards or rebind_cache:
            # Without the parent's admission witnesses this otherwise valid
            # result passes all buffer, cache and source cross-checks.
            accepted = owner._read_result(json.loads(source.read_bytes()), output.parent, output, None)
            assert accepted.root == root
        return 0, '', ''

    monkeypatch.setattr(owner, 'run_process_with_cancellation', run)
    expected = 'Invalid virtual build cache record' if omit_all_guards and not rebind_cache else 'invalid or incomplete'
    with pytest.raises(VirtualLoaderError, match=expected):
        owner.prepare_profile_in_subprocess(VirtualProfile((), (folder,)), root)
    assert files_in(root) == before


def test_installed_export_recompiles_legacy_intent_before_publishing(tmp_path):
    from cdmw.core.iteminfo_row import parse_iteminfo_row, set_max_stack_count
    from cdmw.domain.archives.iteminfo_composition import replace_rows, rows_of
    from cdmw.services import archive_overlay_manager as overlays
    from cdmw.services.independent_item_install import load_registry
    from cdmw.services.independent_item_package import digest
    service, snapshot, _ = setup_game(tmp_path)
    legacy = from_plan(service.plan(shop_spec('WitnessedLegacy'), snapshot, capture_independent=True), uuid4().hex)
    keep = field_package(snapshot, value=1)
    root = tmp_path / 'game'
    Backups(tmp_path).apply(prepare_install([package_bytes(legacy), package_bytes(keep)], root).preparation)
    registry = load_registry(root)
    state = overlays._load_index(root)
    layer = next(row for row in state['layers'] if row.get('independent_identity') == legacy.identity)
    changes = overlays._unpack_changes(root, layer, {}, None)
    body, head = snapshot.iteminfo.payload_entry.path, snapshot.iteminfo.header_entry.path
    key = registry['items'][legacy.identity]['values']['iteminfo']['item']
    row = parse_iteminfo_row(rows_of(changes[body]['after'], changes[head]['after'])[key])
    changes[body]['after'] = replace_rows(changes[body]['after'], changes[head]['after'],
                                          {key: set_max_stack_count(row, 9)})
    journal = overlays._pack_changes(changes)
    (root / overlays.overlay_journal_path(layer)).write_bytes(journal)
    layer['sha256'] = digest(journal)
    (root / overlays.INDEX_PATH).write_bytes(overlays._inventory_bytes(state))
    before = files_in(root)
    with pytest.raises(ValueError, match='recompilation'):
        prepare_independent_mod_merge(root)
    assert files_in(root) == before


@pytest.mark.parametrize('name', [SEMANTIC_EXPORT_FILE, 'CrimsonDesert.exe'])
def test_exact_file_witness_does_not_authorize_a_subtree(tmp_path, name):
    from cdmw.services.virtual_loader_process import _revision
    root, artifact = tmp_path / 'game', tmp_path / 'selected' / name
    value = {'files': [[str(artifact), [10, 20, 30]]], 'payloads': [],
             'indexes': [[str(artifact), '0' * 64]], 'catalogue': []}
    revision = _revision(value, (root,), artifact_paths={artifact})
    assert revision.indexes == ((artifact, '0' * 64),)
    child = artifact / 'subtree/0.pamt'
    value['files'][0][0] = str(child)
    value['indexes'][0][0] = str(child)
    with pytest.raises(VirtualLoaderError, match='invalid or incomplete'):
        _revision(value, (root,), artifact_paths={artifact})


def test_real_worker_result_cannot_omit_earlier_executable_absence(tmp_path, monkeypatch):
    import json
    from pathlib import Path
    from cdmw.services import virtual_loader_process as owner
    from cdmw.services.independent_item_package import canonical
    producer = tmp_path / 'producer'
    producer.mkdir()
    (producer / 'CrimsonDesert.exe').write_bytes(b'known-build-1')
    folder, _, _ = exported_fields(producer, value=1)
    setup_game(tmp_path / 'recipient')
    root = tmp_path / 'recipient/game'
    (root.parent / 'CrimsonDesert.exe').write_bytes(b'known-build-1')
    absent = root.parent / 'bin64/CrimsonDesert.exe'
    assert not absent.exists()
    before = files_in(root)

    def run(command, **kwargs):
        output = Path(command[command.index('--output') + 1])
        source = Path(command[command.index('--input') + 1])
        assert owner.run_virtual_profile_worker(source, output) == 0
        result = json.loads(output.read_bytes())
        assert [str(absent), None] in result['source']['files']
        for key in ('source', 'external_source'):
            result[key]['files'] = [row for row in result[key]['files'] if row[0] != str(absent)]
        output.write_bytes(canonical(result))
        return 0, '', ''

    monkeypatch.setattr(owner, 'run_process_with_cancellation', run)
    with pytest.raises(ValueError, match='invalid or incomplete'):
        owner.prepare_profile_in_subprocess(VirtualProfile((), (folder,)), root)
    assert files_in(root) == before
