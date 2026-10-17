"""Compiler changes can regenerate owned output without reallocating identities."""
from dataclasses import replace
import json
import struct
import threading
from uuid import uuid4

import pytest

from cdmw.domain.new_item.compilation import compiler_stamp, validate_compiler_stamp
from cdmw.domain.new_item.independent import IndependentItemError
from cdmw.services import archive_overlay_manager as overlays
from cdmw.services import independent_item_install as installer
from cdmw.services.independent_item_package import from_plan, package_bytes
from tests.test_archive_overlay_manager import Backups, shop_spec
from tests.test_independent_items import authored, imported_game, setup_game
from tests.test_independent_item_regressions import files_in


@pytest.mark.parametrize('record', ['missing', 'different'])
def test_compiler_change_requires_explicit_rebuild_with_all_bindings_retained(tmp_path, record):
    _, package = authored(tmp_path / 'author')
    setup_game(tmp_path / 'recipient')
    root, backups = tmp_path / 'recipient/game', Backups(tmp_path)
    backups.apply(installer.prepare_install([package_bytes(package)], root).preparation)
    original = installer.load_registry(root)['items'][package.identity]
    assert installer.prepare_install([package_bytes(package)], root).preparation is None
    state_path = root / overlays.INDEX_PATH
    state = json.loads(state_path.read_bytes())
    layer = next(row for row in state['layers'] if row['id'] == original['layer'])
    layer.pop('independent_compilation', None)  # A genuine older layer had no current compilation lock.
    if record == 'missing':
        del layer['independent_compiler']
    else:
        layer['independent_compiler']['revision'] += 1
    state_path.write_text(json.dumps(state), encoding='utf-8')
    before = files_in(root)
    with pytest.raises(IndependentItemError, match='Rebuild selected item'):
        installer.prepare_install([package_bytes(package)], root)
    rebuilt = installer.prepare_rebuild(package.identity, root)
    assert rebuilt.items[0][3] == 'Rebuild'
    assert files_in(root) == before
    backups.apply(rebuilt.preparation)
    current = installer.load_registry(root)['items'][package.identity]
    assert {k: v for k, v in current.items() if k != 'layer'} == {k: v for k, v in original.items() if k != 'layer'}
    assert current['layer'] != original['layer']
    state = json.loads(state_path.read_bytes())
    assert next(row for row in state['layers'] if row['active'])['independent_compiler'] == compiler_stamp()
    assert installer.prepare_install([package_bytes(package)], root).preparation is None


def test_rebuild_repairs_a_miscompiled_dx10_descriptor_from_the_retained_package(tmp_path, monkeypatch):
    from cdmw.core.pathc_format import encode_pathc, parse_pathc
    from cdmw.domain.new_item.spec import ModelSource
    from cdmw.services.new_item_planning import ModelFiles
    from tests.test_new_item_service import PAC_XML, STEM, imported_pac
    from tests.test_pathc_format import dds_header, dds_payload

    service, snapshot = imported_game(tmp_path / 'author')
    texture_path = f'character/texture/1_pc/{STEM}_d.dds'
    bc7 = dds_payload(dds_header(width=4, height=4, fourcc=b'DX10') + struct.pack('<5I', 98, 3, 0, 1, 0))
    model = ModelFiles(imported_pac(1), {PAC_XML: snapshot.payload(PAC_XML), texture_path: bc7})
    choice = replace(shop_spec('RepairTexture'), model_source=ModelSource.IMPORTED)
    package = from_plan(service.plan(choice, snapshot, model=model, capture_independent=True), uuid4().hex)
    imported_game(tmp_path / 'recipient')
    root, backups = tmp_path / 'recipient/game', Backups(tmp_path)
    real_build = installer.build_plan

    def old_compiler(*args, **kwargs):
        plan = real_build(*args, **kwargs)
        writes = []
        for write in plan.meta_files:
            table = parse_pathc(write.payload_data)
            headers = []
            for header in table.headers:
                value = bytearray(header)
                if header[84:88] == b'DX10':
                    struct.pack_into('<I', value, 128, 77)  # The old BC3-for-BC7 defect.
                headers.append(bytes(value))
            writes.append(replace(write, payload_data=encode_pathc(replace(table, headers=tuple(headers)))))
        return replace(plan, meta_files=tuple(writes))

    with monkeypatch.context() as context:
        context.setattr(installer, 'build_plan', old_compiler)
        backups.apply(installer.prepare_install([package_bytes(package)], root).preparation)
    old = installer.load_registry(root)['items'][package.identity]
    pathc_path = root / 'meta/0.pathc'
    assert any(h[84:88] == b'DX10' and struct.unpack_from('<I', h, 128)[0] == 77 for h in parse_pathc(pathc_path.read_bytes()).headers)
    before = files_in(root)
    result = installer.prepare_rebuild(package.identity, root)
    assert files_in(root) == before
    backups.apply(result.preparation)
    table = parse_pathc(pathc_path.read_bytes())
    owned_texture = next(path for path in old['paths'] if path.endswith('.dds'))
    header = table.dds_header_for(table.find(owned_texture))
    assert struct.unpack_from('<I', header, 128)[0] == 98
    assert installer.load_registry(root)['items'][package.identity]['values'] == old['values']
    assert files_in(root / '0009') == {path.relative_to('0009'): data for path, data in before.items() if path.parts[0] == '0009'}


def test_cancelled_or_stale_rebuild_never_publishes(tmp_path):
    _, package = authored(tmp_path / 'author')
    setup_game(tmp_path / 'recipient')
    root, backups = tmp_path / 'recipient/game', Backups(tmp_path)
    backups.apply(installer.prepare_install([package_bytes(package)], root).preparation)
    before = files_in(root)
    stop = threading.Event()
    stop.set()
    with pytest.raises(RuntimeError):
        installer.prepare_rebuild(package.identity, root, stop_event=stop)
    assert files_in(root) == before
    result = installer.prepare_rebuild(package.identity, root)
    path = root / f'.cdmw/independent-items/{package.identity}-{package.digest}.cditem'
    path.write_bytes(path.read_bytes() + b'changed after review')
    changed = files_in(root)
    with pytest.raises(ValueError, match='changed'):
        backups.apply(result.preparation)
    assert files_in(root) == changed


def test_failed_rebuild_restores_previous_artifacts_compiler_and_identity(tmp_path, monkeypatch):
    _, package = authored(tmp_path / 'author')
    setup_game(tmp_path / 'recipient')
    root, backups = tmp_path / 'recipient/game', Backups(tmp_path)
    backups.apply(installer.prepare_install([package_bytes(package)], root).preparation)
    before = files_in(root)
    result = installer.prepare_rebuild(package.identity, root)
    write = overlays.atomic_write_bytes

    def fail(path, data):
        write(path, data)
        if path.name == 'independent-items.json':
            raise OSError('injected rebuild publication failure')

    monkeypatch.setattr(overlays, 'atomic_write_bytes', fail)
    with pytest.raises(OSError, match='injected rebuild'):
        backups.apply(result.preparation)
    assert files_in(root) == before
    assert installer.inventory(root)[0][3] == 'Installed'


@pytest.mark.parametrize('record', ['missing', 'different'])
def test_virtual_profile_with_unknown_compiler_requires_reapply_without_renumbering(tmp_path, monkeypatch, record):
    from cdmw.domain.virtual_loader import VirtualProfile
    from cdmw.services.virtual_loader_composition import prepare_profile
    from cdmw.services.virtual_loader_state import PROFILE_PATH, generation_path, load_profile, publish_profile
    from cdmw.services.virtual_loader_runtime import _snapshot_preflight, runtime_status
    from tests.test_virtual_loader import packages, game_bytes

    # This profile belongs to the temporary fixture, independently of host processes.
    monkeypatch.setattr('cdmw.services.new_item_service.game_is_running', lambda: False)
    root, selected = packages(tmp_path)
    before_game = game_bytes(root)
    publish_profile(prepare_profile(VirtualProfile(selected), root))
    before_registry = installer.load_registry(root)
    profile = load_profile(root)
    profile.pop('compilation', None)
    profile.pop('build_cache', None)
    if record == 'missing':
        del profile['compiler']
    else:
        profile['compiler']['revision'] += 1
    data = json.dumps(profile).encode('utf-8')
    (root / PROFILE_PATH).write_bytes(data)
    (generation_path(root, profile['generation']) / 'profile.json').write_bytes(data)
    assert load_profile(root, registry=before_registry) == profile
    status = runtime_status(root)
    assert status.state == 'blocked' and 'Apply changes again' in status.detail
    with pytest.raises(ValueError, match='Apply changes again'):
        _snapshot_preflight(root)
    publish_profile(prepare_profile(VirtualProfile(selected), root))
    assert installer.load_registry(root) == before_registry
    assert load_profile(root)['compiler'] == compiler_stamp()
    assert game_bytes(root) == before_game


@pytest.mark.parametrize('field,value', [('revision', True), ('revision', 0), ('adapters', {}),
                                        ('adapters', {'unknown': -1}), ('wire_schema', 'invalid'),
                                        ('format', 'unknown')])
def test_malformed_compiler_records_cannot_claim_compatibility(field, value):
    stamp = compiler_stamp()
    stamp[field] = value
    with pytest.raises(IndependentItemError, match='compiler record'):
        validate_compiler_stamp(stamp)
