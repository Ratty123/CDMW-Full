"""Owned archive fixtures and strict admission for existing-prefab packages."""
import struct
from copy import deepcopy
from pathlib import Path
from uuid import uuid4

import pytest

from cdmw.core.prefab_binary import KIND_POINTER, KIND_STRING, decode_prefab_binary
from cdmw.core.prefab_binary_edit import rewrite_prefab_paths
from cdmw.domain.new_item.independent import IndependentItemError
from cdmw.domain.new_item.mod_package import capability_result
from cdmw.domain.virtual_loader import VirtualProfile
from cdmw.services import independent_item_install as install
from cdmw.services.independent_item_install import (
    inventory,
    load_registry,
    prepare_install,
)
from cdmw.services.independent_item_package import (
    digest,
    package_bytes,
    read_package,
    stock_snapshot,
)
from cdmw.services.independent_mod_package import has_legacy_item, read_v2
from cdmw.services.independent_prefab_package import from_prefab_replacements
from cdmw.services.virtual_loader_composition import prepare_profile
from tests.test_independent_item_regressions import files_in
from tests.test_independent_texture_composition import (
    backups,
    package_paths,
    submit,
    visible_texture,
)

PREFAB_PATH = 'character/bin__/prefab/1_pc/cdmw_existing_prefab_test.prefab'
SOURCE_MESH = 'character/model/1_pc/1_phm/weapon/1_onehandweapon/cd_phm_01_sword_0016.pac'
OTHER_MESH = 'character/model/1_pc/1_phm/weapon/1_onehandweapon/cd_phm_01_sword_0109.pac'


def _text(value):
    raw = value.encode('utf-8')
    return struct.pack('<I', len(raw)) + raw


def _member(name, type_name, flags, size):
    return _text(name) + _text(type_name) + struct.pack('<HHHH', flags, size, 0, 0)


def prefab_payload(mesh=SOURCE_MESH):
    """The smallest prefab the structural decoder walks to the end: one mesh, one socket."""
    types = bytearray()
    types += _text('SceneObject') + struct.pack('<H', 2)
    types += _member('_socketName', 'IndexedStringA', KIND_STRING, 1)
    types += _member('_meshFile', 'ReflectObjectPtr', KIND_POINTER, 8)
    types += _text('ResourceReferencePath_SkinnedMesh') + struct.pack('<H', 0)
    header = bytearray(struct.pack('<HHH', 0xFFFF, 4, 0) + b'\x00' * 8)
    header += struct.pack('<I', 15) + struct.pack('<H', 2) + types
    pool = struct.pack('<I', 0)
    blob_offset = len(header) + len(pool) + 28
    blob = bytearray(struct.pack('<H', 2) + (0b11).to_bytes(6, 'little'))
    blob += _text('Pelvis_R_Socket') + struct.pack('<Q', 0xFFFFFFFFFFFFFFFF)
    blob += struct.pack('<I', blob_offset + len(blob) + 4)
    pointee = bytearray(struct.pack('<I', 0) + _text(mesh))
    blob += pointee + struct.pack('<I', len(pointee)) + b'\x00' * 5
    data_header = struct.pack('<III', 1, blob_offset + len(blob), 0) + struct.pack('<Q', 0xFFFFFFFFFFFFFFFF)
    data_header += struct.pack('<II', blob_offset, len(blob))
    return bytes(header + pool + data_header + blob)


def retargeted(mesh=OTHER_MESH, source=None):
    return rewrite_prefab_paths(source or prefab_payload(), {SOURCE_MESH: mesh}).data


def prefab_game(tmp_path, *, source=None):
    """The texture fixture's owned game plus one shipped prefab the decoder reads fully."""
    from cdmw.core.pathc_format import PathcTable, encode_pathc, register_dds
    from tests.test_new_item_provenance import current_files
    from tests.test_new_item_service import build_package
    from dataclasses import replace
    from cdmw.core.pappt_format import encode_pappt, parse_pappt
    files = current_files()
    files[PREFAB_PATH] = prefab_payload() if source is None else source
    # As in the texture fixture: a socket path New Item accepts, so an owned item can be planned here too.
    pappt_path = 'character/bin__/partprefabtable.pappt'
    pappt = parse_pappt(files[pappt_path])
    sockets = 'character/sockets/independent_prefab_test.sockets.xml'
    files[pappt_path] = encode_pappt(replace(pappt, records=tuple(
        replace(record, sockets_path=sockets) for record in pappt.records)))
    files[sockets] = b'<Sockets/>'
    from tests.test_new_item_service import PAC_XML, STEM
    from tests.test_pac_xml_standard_material import HEAD, STANDARD_SHADER, TAIL, texture, wrapper
    files[PAC_XML] = (HEAD + wrapper(STEM, STANDARD_SHADER, texture(
        '_baseColorTexture', '0', 'character/texture/1_pc/cd_phm_01_sword_0109_d.dds', 0)) + TAIL).encode()
    root = tmp_path / 'game'
    build_package(root, files)
    table = PathcTable(0, 148, (), (), (), b'')
    for path, data in sorted(files.items()):
        if path.endswith('.dds'):
            table = register_dds(table, path, data)
    (root / 'meta/0.pathc').write_bytes(encode_pathc(table))
    return root, stock_snapshot(root)


def prefab_package(snapshot, replacement=None, *, identity=None, title='Edited prefab', release='1'):
    return from_prefab_replacements(snapshot, identity or uuid4().hex,
        {PREFAB_PATH: retargeted() if replacement is None else replacement}, title=title, release=release)


def test_fixture_prefab_decodes_completely():
    assert decode_prefab_binary(prefab_payload()).walk_complete
    assert decode_prefab_binary(retargeted()).walk_complete
    assert len(retargeted()) == len(prefab_payload()), 'fixture meshes have equal-length names'
    longer = retargeted('character/model/1_pc/1_phm/weapon/1_onehandweapon/cd_phm_01_sword_0168_in.pac')
    assert decode_prefab_binary(longer).walk_complete and len(longer) > len(prefab_payload())


def test_prefab_capability_claims_adapter_and_synthetic_evidence_only():
    result = capability_result('prefab.replace', 1)
    assert result.supported
    assert {claim.stage for claim in result.evidence} == {'adapter', 'synthetic'}
    assert not capability_result('prefab.replace', 2).supported


@pytest.mark.parametrize('target', ['archive', 'virtual'])
def test_standalone_prefab_roundtrip_resolves_without_allocating_item_ids(tmp_path, monkeypatch, target):
    root, snapshot = prefab_game(tmp_path)
    original, replacement = snapshot.payload(PREFAB_PATH), retargeted()
    package = prefab_package(snapshot, replacement)
    decoded = read_package(package_bytes(package))
    assert decoded == package and not has_legacy_item(decoded)
    assert decoded.dependencies == {PREFAB_PATH: digest(original)}
    assert decoded.blobs == {digest(replacement): replacement}
    monkeypatch.setattr(install.IdentityBindings, 'allocate',
                        lambda *args: pytest.fail('Existing prefab replacement must not allocate item IDs'))
    before = files_in(root)
    resolved = install.resolve_items([package_bytes(package)], root, target=target)
    assert files_in(root) == before
    reservation = resolved.registry['items'][package.identity]
    assert reservation['values'] == {} and reservation['paths'] == [] and reservation['stem'] == ''
    retained, changes = resolved.contributions[0]
    assert retained.identity == package.identity and set(changes) == {PREFAB_PATH}
    assert changes[PREFAB_PATH]['before'] == original and changes[PREFAB_PATH]['after'] == replacement
    assert changes[PREFAB_PATH]['flags'] == snapshot.entries[PREFAB_PATH].flags


@pytest.mark.parametrize('virtual', [False, True])
def test_installed_prefab_replacement_is_what_the_game_reads(tmp_path, virtual):
    root, snapshot = prefab_game(tmp_path)
    longer = retargeted('character/model/1_pc/1_phm/weapon/1_onehandweapon/cd_phm_01_sword_0168_in.pac')
    package = prefab_package(snapshot, longer)
    submit(tmp_path, root, [package], virtual)
    assert visible_texture(root, PREFAB_PATH, virtual=virtual) == longer
    assert all(row[2] is None for row in inventory(root))
    if not virtual:
        assert load_registry(root)['items'][package.identity]['paths'] == []


@pytest.mark.parametrize('virtual', [False, True])
def test_two_packages_wanting_different_prefab_bytes_refuse(tmp_path, virtual):
    root, snapshot = prefab_game(tmp_path)
    first = prefab_package(snapshot, title='First prefab')
    second = prefab_package(snapshot, retargeted('character/model/1_pc/1_phm/weapon/1_onehandweapon/cd_phm_01_sword_0168_in.pac'),
                            title='Second prefab')
    before = files_in(root)
    with pytest.raises(ValueError, match='conflict') as error:
        if virtual:
            prepare_profile(VirtualProfile(package_paths(tmp_path / 'inputs', [first, second])), root)
        else:
            prepare_install([package_bytes(first), package_bytes(second)], root)
    assert PREFAB_PATH in str(error.value)
    assert files_in(root) == before


def test_equal_prefab_owners_compose(tmp_path):
    root, snapshot = prefab_game(tmp_path)
    first, peer = prefab_package(snapshot, title='Equal first'), prefab_package(snapshot, title='Equal peer')
    submit(tmp_path, root, [first, peer], True)
    assert visible_texture(root, PREFAB_PATH, virtual=True) == retargeted()


def test_changed_game_copy_refuses_install(tmp_path):
    _, author = prefab_game(tmp_path / 'author')
    package = prefab_package(author)
    changed_source = retargeted('character/model/1_pc/1_phm/weapon/1_onehandweapon/cd_phm_01_sword_0168_in.pac')
    root, _ = prefab_game(tmp_path / 'patched', source=changed_source)
    before = files_in(root)
    # The package-wide dependency check reaches it before the adapter's own witness.
    with pytest.raises(IndependentItemError, match='incompatible game dependency character/bin__/prefab'):
        install.resolve_items([package_bytes(package)], root, target='virtual')
    assert files_in(root) == before


def test_pointing_at_a_file_the_game_lacks_refuses_authoring(tmp_path):
    _, snapshot = prefab_game(tmp_path)
    with pytest.raises(IndependentItemError, match='nor the package contains: character/model/1_pc/missing_mesh_0001.pac'):
        prefab_package(snapshot, retargeted('character/model/1_pc/missing_mesh_0001.pac'))


@pytest.mark.parametrize('mutation', ['identical', 'truncated', 'not-shipped', 'not-prefab'])
def test_authoring_refuses_unusable_replacements(tmp_path, mutation):
    _, snapshot = prefab_game(tmp_path)
    target, replacement = PREFAB_PATH, retargeted()
    if mutation == 'identical':
        replacement = snapshot.payload(PREFAB_PATH)
    elif mutation == 'truncated':
        replacement = replacement[:40]
    elif mutation == 'not-shipped':
        target = 'character/bin__/prefab/1_pc/cdmw_not_in_this_game.prefab'
    elif mutation == 'not-prefab':
        target = SOURCE_MESH
    with pytest.raises(IndependentItemError):
        from_prefab_replacements(snapshot, uuid4().hex, {target: replacement})


def _manifest(package):
    return deepcopy(package.manifest), dict(package.blobs)


@pytest.mark.parametrize('mutation', [
    'unknown-data-field', 'empty-replacements', 'unknown-row-field', 'missing-row-field', 'uppercase',
    'parent', 'non-prefab', 'unsupported-root', 'boolean-size', 'bad-source-hash', 'missing-blob',
    'missing-dependency', 'mismatched-dependency', 'duplicate-path', 'undecodable-blob',
])
def test_malformed_prefab_contract_refuses_before_game_access(tmp_path, mutation):
    _, snapshot = prefab_game(tmp_path)
    manifest, blobs = _manifest(prefab_package(snapshot))
    data = manifest['modules'][0]['data']
    row = data['replacements'][0]
    if mutation == 'unknown-data-field':
        data['fallback'] = 'raw'
    elif mutation == 'empty-replacements':
        data['replacements'] = []
    elif mutation == 'unknown-row-field':
        row['allow_partial'] = True
    elif mutation == 'missing-row-field':
        del row['source_size']
    elif mutation in ('uppercase', 'parent', 'non-prefab', 'unsupported-root'):
        row['path'] = {'uppercase': PREFAB_PATH.upper(), 'parent': 'character/bin__/../bad.prefab',
                       'non-prefab': SOURCE_MESH, 'unsupported-root': 'mods/replacement.prefab'}[mutation]
    elif mutation == 'boolean-size':
        row['source_size'] = True
    elif mutation == 'bad-source-hash':
        row['source_sha256'] = 'G' * 64
    elif mutation == 'missing-blob':
        row['replacement'] = '0' * 64
    elif mutation == 'missing-dependency':
        manifest['dependencies'] = {}
    elif mutation == 'mismatched-dependency':
        manifest['dependencies'][PREFAB_PATH] = '0' * 64
    elif mutation == 'duplicate-path':
        data['replacements'].append(deepcopy(row))
    elif mutation == 'undecodable-blob':
        broken = b'\x00' * 64
        blobs = {digest(broken): broken}
        manifest['blobs'] = {digest(broken): len(broken)}
        row['replacement'] = digest(broken)
    with pytest.raises(IndependentItemError):
        read_v2(manifest, blobs)


def test_inspector_export_writes_a_package_the_mods_page_can_read(tmp_path, monkeypatch):
    """Drive the Archive Browser action with the real authoring service."""
    from types import SimpleNamespace

    from cdmw.ui.archive_browser import prefab_inspector_actions as actions

    root, _snapshot = prefab_game(tmp_path)
    destination = tmp_path / 'out' / 'retargeted sword'
    monkeypatch.setattr(actions.QFileDialog, 'getSaveFileName', lambda *args, **kwargs: (str(destination), ''))
    shown = []
    monkeypatch.setattr(actions.QMessageBox, 'information', lambda *args: shown.append(args[2]))
    calls, statuses = [], []
    browser = SimpleNamespace(
        archive_package_root_edit=SimpleNamespace(text=lambda: str(root)),
        shell=SimpleNamespace(
            settings_file_path=tmp_path / 'settings.json',
            set_status_message=lambda message, error=False: statuses.append((message, error)),
            _run_utility_task_when_idle=lambda **kwargs: calls.append(kwargs),
        ),
    )
    entry = SimpleNamespace(path=PREFAB_PATH, basename=PREFAB_PATH.rsplit('/', 1)[-1])
    actions.ArchivePrefabInspectorActionsMixin._export_inspected_prefab_package(
        browser, entry, prefab_payload(), retargeted())
    assert len(calls) == 1 and calls[0]['task_accepts_cancel'] and calls[0]['show_archive_progress']
    result = calls[0]['task'](lambda _message: None, None)
    calls[0]['on_complete'](result)
    written = destination.with_name('retargeted sword.cdmw')
    assert result[0] == written and written.is_file()
    package = read_package(written)
    assert package.title == 'retargeted sword'
    assert package.manifest['requires'] == {'prefab.replace': 1}
    assert package.blobs == {digest(retargeted()): retargeted()}
    assert shown and str(written) in shown[0] and statuses[-1] == (f'Wrote prefab item package: {written}', False)


def test_an_edit_made_on_another_mods_copy_is_refused(tmp_path):
    from cdmw.services.independent_prefab_authoring import prepare_prefab_package
    root, _ = prefab_game(tmp_path)
    modded = retargeted('character/model/1_pc/1_phm/weapon/1_onehandweapon/cd_phm_01_sword_0168_in.pac')
    with pytest.raises(IndependentItemError, match="differs from the game's own copy"):
        prepare_prefab_package(root, PREFAB_PATH, retargeted(source=modded), edited_from=modded)


def test_packages_are_not_written_into_the_game_folder(tmp_path):
    from cdmw.services.independent_prefab_authoring import (
        prepare_prefab_package,
        write_prefab_package,
    )
    root, _ = prefab_game(tmp_path)
    review = prepare_prefab_package(root, PREFAB_PATH, retargeted(), edited_from=prefab_payload())
    with pytest.raises(IndependentItemError, match='outside the game archive folder'):
        write_prefab_package(review, root / 'edited.cditem')


DLC_PREFAB_PATH = 'character/bin__/prefab/1_pc/cdmw_dlc_prefab_test.prefab'


def dlc_prefab_game(tmp_path):
    """The prefab fixture plus a `dlc/dlc_01` layer that ships its own prefab."""
    from tests.test_new_item_service import build_package
    root, _ = prefab_game(tmp_path)
    build_package(root / 'dlc/dlc_01', {DLC_PREFAB_PATH: prefab_payload()})
    return root, stock_snapshot(root)


@pytest.mark.parametrize('target', ['archive', 'virtual'])
def test_a_dlc_prefab_can_be_replaced(tmp_path, target):
    root, snapshot = dlc_prefab_game(tmp_path)
    assert 'dlc_01' in Path(snapshot.entries[DLC_PREFAB_PATH].pamt_path).parts
    package = from_prefab_replacements(snapshot, uuid4().hex, {DLC_PREFAB_PATH: retargeted()})
    assert package.dependencies == {DLC_PREFAB_PATH: digest(prefab_payload())}
    resolved = install.resolve_items([package_bytes(package)], root, target=target)
    _, changes = resolved.contributions[0]
    assert changes[DLC_PREFAB_PATH]['after'] == retargeted()


def test_a_prefab_in_another_mods_numbered_group_is_refused(tmp_path):
    from tests.test_new_item_service import build_package
    root, _ = prefab_game(tmp_path)
    build_package(root / 'mods/dlc_01', {DLC_PREFAB_PATH: prefab_payload()})
    snapshot = stock_snapshot(root)
    with pytest.raises(IndependentItemError):
        from_prefab_replacements(snapshot, uuid4().hex, {DLC_PREFAB_PATH: retargeted()})


def owned_item(snapshot, name='PrefabOwner'):
    """A legacy item with its own imported mesh, and the .pac path it adds."""
    from dataclasses import replace
    from cdmw.domain.new_item.spec import ModelSource
    from cdmw.services.independent_item_package import from_plan
    from cdmw.services.new_item_planning import ModelFiles
    from cdmw.services.new_item_service import NewItemService
    from tests.test_archive_overlay_manager import shop_spec
    from tests.test_new_item_service import PAC_XML, imported_pac
    model = ModelFiles(imported_pac(1), {PAC_XML: snapshot.payload(PAC_XML)})
    plan = NewItemService().plan(replace(shop_spec(name), model_source=ModelSource.IMPORTED), snapshot,
                                 model=model, capture_independent=True)
    mesh = next(request.path.lower() for request in plan.additions if request.path.lower().endswith('.pac'))
    return from_plan(plan, uuid4().hex), mesh


@pytest.mark.parametrize('target', ['archive', 'virtual'])
def test_a_prefab_edit_can_point_at_the_packages_own_new_mesh(tmp_path, target):
    from cdmw.services.independent_prefab_package import with_prefab_replacements
    root, snapshot = prefab_game(tmp_path)
    item, mesh = owned_item(snapshot)
    assert not snapshot.has_entry(mesh)
    combined = with_prefab_replacements(item, snapshot, {PREFAB_PATH: retargeted(mesh)}, release='2')
    assert has_legacy_item(combined) and combined.identity == item.identity
    assert combined.manifest['requires'] == {'item.legacy': 1, 'prefab.replace': 1}
    assert read_package(package_bytes(combined)) == combined
    resolved = install.resolve_items([package_bytes(combined)], root, target=target)
    _, changes = resolved.contributions[0]
    assert changes[PREFAB_PATH]['after'] == retargeted(mesh)
    assert changes[mesh]['before'] is None and changes[mesh]['after'] is not None


def test_an_installed_combined_package_rebuilds_and_the_game_reads_the_edit(tmp_path):
    from cdmw.services.independent_prefab_package import with_prefab_replacements
    root, snapshot = prefab_game(tmp_path)
    item, mesh = owned_item(snapshot)
    combined = with_prefab_replacements(item, snapshot, {PREFAB_PATH: retargeted(mesh)}, release='2')
    submit(tmp_path, root, [combined], False)
    assert visible_texture(root, PREFAB_PATH) == retargeted(mesh)
    # Rebuilding re-checks the retained package against its layer, including the new mesh.
    backups(tmp_path / 'rebuild').apply(install.prepare_rebuild(combined.identity, root).preparation)
    assert visible_texture(root, PREFAB_PATH) == retargeted(mesh)


def test_a_mesh_the_package_does_not_add_is_still_refused(tmp_path):
    from cdmw.services.independent_prefab_package import with_prefab_replacements
    root, snapshot = prefab_game(tmp_path)
    item, _mesh = owned_item(snapshot)
    combined = with_prefab_replacements(item, snapshot, {PREFAB_PATH: retargeted('character/model/1_pc/elsewhere_0001.pac')},
                                        release='2')
    with pytest.raises(IndependentItemError, match='neither this game nor the package'):
        install.resolve_items([package_bytes(combined)], root, target='virtual')


def test_the_inspector_route_adds_the_edit_to_an_existing_item_package(tmp_path):
    from cdmw.services.independent_item_package import write_package
    from cdmw.services.independent_prefab_authoring import prepare_prefab_package, write_prefab_package
    root, snapshot = prefab_game(tmp_path)
    item, mesh = owned_item(snapshot)
    path = tmp_path / 'packages' / 'owner.cditem'
    write_package(item, path)
    review = prepare_prefab_package(root, PREFAB_PATH, retargeted(mesh), edited_from=prefab_payload(), add_to=path)
    assert review.update is not None and review.package.identity == item.identity
    write_prefab_package(review)
    updated = read_package(path)
    assert updated.identity == item.identity and updated.manifest['release'] == '2'
    assert has_legacy_item(updated)
    assert {row['path'] for module in updated.manifest['modules'] if module['type'] == 'prefab.replace'
            for row in module['data']['replacements']} == {PREFAB_PATH}
    # A second edit of the same prefab replaces the row and drops the bytes nobody uses.
    again = prepare_prefab_package(root, PREFAB_PATH, retargeted(), edited_from=prefab_payload(), add_to=path)
    write_prefab_package(again)
    final = read_package(path)
    assert final.manifest['release'] == '3' and digest(retargeted(mesh)) not in final.blobs


@pytest.mark.parametrize('release, expected', [('1', '2'), ('1.9', '1.10'), ('beta', 'beta.1'), ('2a', '2a.1')])
def test_release_bump(release, expected):
    from cdmw.services.independent_prefab_package import next_release
    assert next_release(release) == expected


@pytest.mark.parametrize('changes', [True, False])
def test_prefab_edit_json_import_offers_the_same_outputs_as_the_inspector(tmp_path, monkeypatch, changes):
    from types import SimpleNamespace
    from cdmw.ui.archive_browser import prefab_json_actions as actions

    document = tmp_path / 'sword.prefab-edit.json'
    document.write_text('{}', encoding='utf-8')
    monkeypatch.setattr(actions.QFileDialog, 'getOpenFileName', lambda *args, **kwargs: (str(document), ''))
    monkeypatch.setattr(actions, 'read_archive_entry_data', lambda entry: (prefab_payload(), False, ''))
    patched = retargeted() if changes else prefab_payload()
    monkeypatch.setattr(actions, 'apply_prefab_edit_json', lambda data, text, virtual_path: patched)
    calls, offered, loose = [], [], []
    entry = SimpleNamespace(path=PREFAB_PATH, basename=PREFAB_PATH.rsplit('/', 1)[-1])
    browser = SimpleNamespace(
        shell=SimpleNamespace(set_status_message=lambda *args, **kwargs: None,
                              settings_file_path=tmp_path / 'settings.json',
                              _run_utility_task_when_idle=lambda **kwargs: calls.append(kwargs)),
        _current_archive_prefab_entry=lambda: entry,
        _default_archive_prefab_edit_json_path=lambda entry: document,
        _offer_prefab_export=lambda *args: offered.append(args),
        _export_inspected_prefab=lambda *args: loose.append(args),
    )
    actions.ArchivePrefabJsonActionsMixin._import_current_archive_prefab_edit_json(browser)
    assert len(calls) == 1 and calls[0]['show_archive_progress']
    calls[0]['on_complete'](calls[0]['task'](lambda _message: None))
    if changes:
        assert offered and offered[0][:3] == (entry, prefab_payload(), retargeted()) and not loose
    else:
        assert loose and loose[0][:2] == (entry, prefab_payload()) and not offered
