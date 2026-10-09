"""V2 envelope admission and legacy lowering use both existing publication routes."""
from copy import deepcopy
import io
import json
import os
import zipfile

import pytest

from cdmw.domain.new_item.independent import IndependentItemError
from cdmw.domain.new_item.mod_package import UnsupportedCapability, capability_result
from cdmw.domain.virtual_loader import VirtualProfile
from cdmw.services import archive_overlay_manager as overlays
from cdmw.services.independent_item_install import load_registry, prepare_install, prepare_rebuild, prepare_remove
from cdmw.services.independent_item_package import _v1_package, canonical, digest, package_bytes, package_metadata, read_package, write_package
from cdmw.services.independent_mod_package import migrate_v1
from cdmw.services.virtual_loader_composition import prepare_profile
from cdmw.services.virtual_loader_state import load_profile, publish_profile
from tests.test_archive_overlay_manager import Backups
from tests.test_independent_items import authored, setup_game
from tests.test_independent_item_regressions import files_in
from tests.test_virtual_loader import game_bytes


def packed(meta, blobs=(), comment=b''):
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, 'w') as archive:
        archive.writestr('item.json', canonical(meta))
        for key, value in dict(blobs).items():
            archive.writestr('assets/' + key, value)
        archive.comment = comment
    return stream.getvalue()


def test_v1_migration_retains_original_identity_digest_and_unknown_metadata(tmp_path):
    _, original = authored(tmp_path)
    migrated = migrate_v1(original, release='1.0-preview', metadata={'future-author-data': {'list': [1, 'x']}})
    assert migrated.identity == original.identity
    assert migrated.digest != original.digest
    assert migrated.manifest['provenance']['source_digest'] == original.digest
    assert migrated.recipe == original.recipe and migrated.blobs == original.blobs
    before = read_package(package_bytes(original))
    assert before == original and package_metadata(before)['version'] == 1
    a = packed(migrated.manifest, migrated.blobs)
    b = packed(migrated.manifest, migrated.blobs, comment=b'different ZIP artifact, identical content')
    assert read_package(a) == read_package(b) == migrated
    assert read_package(a).artifact_digest == digest(a)
    assert read_package(a).artifact_digest != read_package(b).artifact_digest
    assert read_package(package_bytes(read_package(b))).manifest == migrated.manifest
    with pytest.raises(IndependentItemError, match='Unsupported independent item package version'):
        _v1_package(migrated.manifest, migrated.blobs)


@pytest.mark.parametrize('mutation,match', [
    ('feature', 'Unsupported required capability'), ('module', 'Unsupported required capability'),
    ('module-version', 'Unsupported required capability'), ('boolean-version', 'module type or version'),
    ('optional', 'Optional behavior'), ('duplicate', 'duplicate module'),
    ('missing-feature', 'omits its required'), ('source-digest', 'provenance'),
    ('root-field', 'v2 package fields'), ('module-field', 'v2 module fields'),
])
def test_unknown_or_malformed_required_behavior_refuses_before_game_access(tmp_path, monkeypatch, mutation, match):
    _, original = authored(tmp_path / 'author')
    meta = deepcopy(migrate_v1(original).manifest)
    module = meta['modules'][0]
    if mutation == 'feature':
        meta['requires']['runtime.arbitrary-memory'] = 1
    elif mutation == 'module':
        module['type'] = 'quest.unknown'
    elif mutation == 'module-version':
        module['version'] = 99
    elif mutation == 'boolean-version':
        module['version'] = True
    elif mutation == 'optional':
        module['required'] = False
    elif mutation == 'duplicate':
        meta['modules'].append(deepcopy(module))
    elif mutation == 'missing-feature':
        meta['requires'] = {}
    elif mutation == 'source-digest':
        meta['provenance']['source_digest'] = '0' * 64
    elif mutation == 'root-field':
        meta['ignored-behavior'] = {}
    elif mutation == 'module-field':
        module['ignored-behavior'] = {}
    import cdmw.services.independent_item_install as installer
    monkeypatch.setattr(installer, 'load_registry', lambda *args: pytest.fail('allocation must not start'))
    before = files_in(tmp_path)
    with pytest.raises(IndependentItemError, match=match):
        prepare_install([packed(meta, original.blobs)], tmp_path / 'recipient')
    assert files_in(tmp_path) == before


def test_capability_results_keep_adapter_and_synthetic_evidence_separate_from_game_proof():
    supported = capability_result('item.legacy', 1)
    assert supported.supported
    assert {claim.stage for claim in supported.evidence} == {'adapter', 'synthetic'}
    missing = capability_result('quest.unknown', 1)
    assert not missing.supported and not missing.evidence
    assert UnsupportedCapability(missing).result is missing


def test_physical_v2_migration_preserves_bindings_output_rebuild_and_removal(tmp_path):
    _, original = authored(tmp_path / 'author')
    setup_game(tmp_path / 'recipient')
    root = tmp_path / 'recipient/game'
    backups = Backups(tmp_path)
    backups.apply(prepare_install([package_bytes(original)], root).preparation)
    before = load_registry(root)['items'][original.identity]
    game_before = game_bytes(root)
    backups.apply(prepare_install([package_bytes(migrate_v1(original))], root).preparation)
    migrated = load_registry(root)['items'][original.identity]
    assert migrated['values'] == before['values']
    assert migrated['binding_hash'] == before['binding_hash']
    assert game_bytes(root) == game_before
    layer = next(layer for layer in overlays._load_index(root)['layers'] if layer['active'])
    inputs = layer['independent_compilation']['inputs']
    assert inputs['packages'][0]['content'] == migrate_v1(original).digest
    assert inputs['packages'][0]['artifact'] == digest((root / f'.cdmw/independent-items/{original.identity}-{migrate_v1(original).digest}.cditem').read_bytes())
    assert inputs['allocations'][original.identity] == before['binding_hash']
    assert inputs['sources'] == original.dependencies
    backups.apply(prepare_rebuild(original.identity, root).preparation)
    assert game_bytes(root) == game_before
    assert load_registry(root)['items'][original.identity]['values'] == before['values']
    backups.apply(prepare_remove(original.identity, root))
    assert not any(layer['active'] for layer in overlays._load_index(root)['layers'])
    assert load_registry(root)['items'][original.identity]['values'] == before['values']


def test_virtual_v2_lowering_preserves_exact_output_and_ids_without_game_writes(tmp_path):
    _, original = authored(tmp_path / 'author')
    setup_game(tmp_path / 'recipient')
    root = tmp_path / 'recipient/game'
    path = tmp_path / 'item.cditem'
    path.write_bytes(package_bytes(original))
    baseline = game_bytes(root)
    old_plan = prepare_profile(VirtualProfile((path,)), root)
    publish_profile(old_plan)
    before = load_registry(root)['items'][original.identity]
    path.write_bytes(package_bytes(migrate_v1(original)))
    new_plan = prepare_profile(VirtualProfile((path,)), root)
    assert dict(new_plan.files) == dict(old_plan.files)
    publish_profile(new_plan)
    after = load_registry(root)['items'][original.identity]
    assert after['values'] == before['values'] and after['binding_hash'] == before['binding_hash']
    assert load_profile(root)['items'][original.identity]['digest'] == migrate_v1(original).digest
    old_lock = json.loads(old_plan.profile)['compilation']
    new_lock = load_profile(root)['compilation']
    assert old_lock['identity'] != new_lock['identity']
    assert old_lock['inputs']['outputs'] == new_lock['inputs']['outputs']
    assert old_lock['inputs']['allocations'] == new_lock['inputs']['allocations']
    assert new_lock['inputs']['runtime_abi'] == 'CDVFS2'
    assert game_bytes(root) == baseline


def test_existing_v1_editor_cannot_silently_downgrade_a_v2_package(tmp_path):
    _, original = authored(tmp_path / 'author')
    migrated = migrate_v1(original)
    path = tmp_path / 'item.cditem'
    write_package(migrated, path)
    before = path.read_bytes()
    with pytest.raises(IndependentItemError, match='v2-aware editor'):
        write_package(original, path, expected_digest=migrated.digest)
    assert path.read_bytes() == before


def test_package_artifact_is_deterministic_across_export_times(tmp_path, monkeypatch):
    import time
    _, original = authored(tmp_path)
    original = migrate_v1(original)
    monkeypatch.setattr(zipfile.time, 'localtime', lambda *args: time.struct_time((2001, 1, 1, 1, 1, 1, 0, 1, -1)))
    first = package_bytes(original)
    monkeypatch.setattr(zipfile.time, 'localtime', lambda *args: time.struct_time((2030, 12, 20, 10, 10, 10, 0, 1, -1)))
    assert package_bytes(original) == first


def test_same_size_same_mtime_source_change_cannot_claim_an_artifact_identity(tmp_path, monkeypatch):
    _, original = authored(tmp_path / 'author')
    path = tmp_path / 'item.cditem'
    path.write_bytes(packed(migrate_v1(original).manifest, original.blobs, comment=b'first!'))
    stamp = path.stat()
    original_read = zipfile.ZipExtFile.read
    changed = False

    def change_after_read(member, *args, **kwargs):
        nonlocal changed
        result = original_read(member, *args, **kwargs)
        if member.name == 'item.json' and not changed:
            with path.open('r+b') as file:
                file.seek(-6, 2)
                file.write(b'second')
            os.utime(path, ns=(stamp.st_atime_ns, stamp.st_mtime_ns))
            changed = True
        return result

    monkeypatch.setattr(zipfile.ZipExtFile, 'read', change_after_read)
    with pytest.raises(IndependentItemError, match='changed while it was being read'):
        read_package(path)
    assert changed and path.stat().st_size == stamp.st_size and path.stat().st_mtime_ns == stamp.st_mtime_ns


@pytest.mark.parametrize('target', ['compiler', 'features', 'allocations', 'sources', 'order', 'runtime', 'outputs', 'artifact'])
def test_compilation_identity_covers_each_semantic_input(tmp_path, target):
    from cdmw.domain.new_item.compilation import compilation_record, validate_compilation
    _, original = authored(tmp_path)
    from cdmw.services.independent_item_compilation import package_record
    inputs = dict(scope='virtual-profile', packages=[package_record(migrate_v1(original), package_bytes(migrate_v1(original)))],
                  sources={'game/file': '1' * 64}, allocations={original.identity: '2' * 64},
                  order=[original.identity], runtime_abi='CDVFS2', outputs={'meta/0.papgt': '3' * 64}, providers={})
    record = compilation_record(**inputs)
    changed = deepcopy(record)
    body = changed['inputs']
    if target == 'compiler':
        body['compiler']['revision'] += 1
    elif target == 'features':
        body['packages'][0]['features']['future.feature'] = 1
    elif target == 'allocations':
        body['allocations'][original.identity] = '4' * 64
    elif target == 'sources':
        body['sources']['game/file'] = '4' * 64
    elif target == 'order':
        body['policy']['order'].append('external-provider')
    elif target == 'runtime':
        body['runtime_abi'] = None
    elif target == 'outputs':
        body['outputs']['meta/0.papgt'] = '4' * 64
    elif target == 'artifact':
        body['packages'][0]['artifact'] = '4' * 64
    with pytest.raises(IndependentItemError, match='compilation record'):
        validate_compilation(changed)


def test_v2_survives_real_preparation_process_and_publication(tmp_path):
    from cdmw.services.virtual_loader_process import prepare_profile_in_subprocess
    _, original = authored(tmp_path / 'author')
    setup_game(tmp_path / 'recipient')
    root, path = tmp_path / 'recipient/game', tmp_path / 'item.cditem'
    path.write_bytes(package_bytes(migrate_v1(original)))
    prepared = prepare_profile_in_subprocess(VirtualProfile((path,)), root)
    publish_profile(prepared)
    assert load_profile(root)['compilation']['inputs']['packages'][0]['version'] == 2
