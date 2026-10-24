"""Real package, ownership, export and deployment routes for existing textures."""
from copy import deepcopy
from pathlib import Path
from uuid import uuid4

import pytest

from cdmw.core.archive_extraction import read_archive_entry_data
from cdmw.core.archive_format import parse_archive_pamt
from cdmw.core.mod_compatibility import SEMANTIC_EXPORT_FILE, read_semantic_export
from cdmw.core.papgt_format import papgt_with_directory, parse_papgt, serialize_papgt
from cdmw.domain.virtual_loader import VirtualLoaderError, VirtualProfile
from cdmw.services import archive_overlay_manager as overlays
from cdmw.services.independent_item_compatibility import prepare_independent_mod_merge
from cdmw.services.independent_item_install import (
    inventory, load_registry, prepare_install, prepare_rebuild, prepare_remove,
)
from cdmw.services.independent_item_package import from_plan, package_bytes, package_metadata, read_package
from cdmw.services.independent_mod_package import migrate_v1, read_v2
from cdmw.services.mod_merge_service import export_merged_mod
from cdmw.services.new_item_service import NewItemService
from cdmw.services.virtual_loader_composition import prepare_profile
from cdmw.services.virtual_loader_state import generation_path, load_profile, publish_profile
from tests.test_archive_overlay_manager import Backups, shop_spec
from tests.test_independent_item_regressions import files_in
from tests.test_independent_texture_packages import (
    TEXTURE_PATH, SECOND_TEXTURE_PATH, dds_payload, texture_game, texture_package,
)


def backups(base):
    base.mkdir(parents=True, exist_ok=True)
    return Backups(base)


def package_paths(base, packages):
    base.mkdir(parents=True, exist_ok=True)
    paths = []
    for package in packages:
        path = base / f'{package.identity}-{package.digest}.cditem'
        if not path.exists():
            path.write_bytes(package_bytes(package))
        paths.append(path)
    return tuple(paths)


def submit(base, root, packages, virtual):
    if virtual:
        return publish_profile(prepare_profile(VirtualProfile(package_paths(base / 'inputs', packages)), root))
    plan = prepare_install([package_bytes(package) for package in packages], root)
    if plan.preparation is not None:
        return backups(base / uuid4().hex).apply(plan.preparation)


def visible_texture(root, path=TEXTURE_PATH, *, virtual=False):
    """Resolve the actual mounted archive order, including a private generation."""
    files = generation_path(root, load_profile(root)['generation']) / 'files' if virtual else root
    mount = files / 'meta/0.papgt'
    for record in parse_papgt(mount.read_bytes()):
        folder = files / record.name
        if not folder.is_dir():
            folder = root / record.name
        for archive in sorted(folder.glob('*.pamt')):
            entry = next((entry for entry in parse_archive_pamt(archive) if entry.path.lower() == path), None)
            if entry is not None:
                return read_archive_entry_data(entry)[0]
    pytest.fail(f'Texture disappeared from the mounted view: {path}')


@pytest.mark.parametrize('virtual', [False, True])
@pytest.mark.parametrize('reverse', [False, True])
def test_disjoint_texture_targets_compose_without_items_or_registry_edits(tmp_path, virtual, reverse):
    root, snapshot = texture_game(tmp_path)
    before_registry = (root / 'meta/0.pathc').read_bytes()
    original_item = snapshot.rows[1001295].raw
    first = texture_package(snapshot, title='First texture')
    second = texture_package(snapshot, {SECOND_TEXTURE_PATH: dds_payload(fill=2)}, title='Second texture')
    selected = [second, first] if reverse else [first, second]
    submit(tmp_path, root, selected, virtual)
    assert visible_texture(root, virtual=virtual) == dds_payload(fill=1)
    assert visible_texture(root, SECOND_TEXTURE_PATH, virtual=virtual) == dds_payload(fill=2)
    assert (root / 'meta/0.pathc').read_bytes() == before_registry
    assert all(not row['values'] and not row['paths'] and not row['stem']
               for row in load_registry(root)['items'].values())
    assert all(row[2] is None for row in inventory(root))
    from cdmw.services.independent_item_package import stock_snapshot
    assert stock_snapshot(root).rows[1001295].raw == original_item
    if virtual:
        generation = generation_path(root, load_profile(root)['generation'])
        assert (generation / 'files/meta/0.pathc').read_bytes() == before_registry


@pytest.mark.parametrize('virtual', [False, True])
@pytest.mark.parametrize('remove_first', [False, True])
def test_equal_texture_owners_survive_updates_disable_remove_and_reinstall(tmp_path, virtual, remove_first):
    root, snapshot = texture_game(tmp_path)
    source = snapshot.payload(TEXTURE_PATH)
    registry_bytes = (root / 'meta/0.pathc').read_bytes()
    first = texture_package(snapshot, title='Equal first')
    peer = texture_package(snapshot, title='Equal peer')
    equal_update = texture_package(snapshot, identity=first.identity, title='Equal first updated', release='2')
    conflict = texture_package(snapshot, {TEXTURE_PATH: dds_payload(fill=2)},
                               identity=first.identity, title='Conflicting update', release='3')
    upgrades = {package.identity: texture_package(snapshot, {TEXTURE_PATH: dds_payload(fill=2)},
        identity=package.identity, title=package.title, release='4') for package in (first, peer)}
    submit(tmp_path, root, [first, peer], virtual)
    initial = load_registry(root)
    assert visible_texture(root, virtual=virtual) == dds_payload(fill=1)

    if virtual:
        submit(tmp_path, root, [first, peer], True)
    else:
        assert prepare_install([package_bytes(first), package_bytes(peer)], root).preparation is None
        backups(tmp_path / 'rebuild').apply(prepare_rebuild(first.identity, root).preparation)
    assert visible_texture(root, virtual=virtual) == dds_payload(fill=1)
    before = files_in(root)
    with pytest.raises(ValueError, match='Texture conflict') as error:
        if virtual:
            prepare_profile(VirtualProfile(package_paths(tmp_path / 'inputs', [conflict, peer])), root)
        else:
            prepare_install([package_bytes(conflict)], root)
    assert first.identity in str(error.value) and peer.identity in str(error.value) and TEXTURE_PATH in str(error.value)
    assert files_in(root) == before

    submit(tmp_path, root, [equal_update, peer] if virtual else [equal_update], virtual)
    if virtual:
        submit(tmp_path, root, [peer], True)
        assert first.identity not in load_profile(root)['items']
        submit(tmp_path, root, [equal_update, peer], True)
    else:
        layer = load_registry(root)['items'][first.identity]['layer']
        backups(tmp_path / 'disable').apply(overlays.prepare_overlay_enabled(root, layer, False))
        assert visible_texture(root) == dds_payload(fill=1)
        backups(tmp_path / 'enable').apply(overlays.prepare_overlay_enabled(root, layer, True))

    removed, remaining = (equal_update, peer) if remove_first else (peer, equal_update)
    if virtual:
        submit(tmp_path, root, [remaining], True)
    else:
        backups(tmp_path / 'remove-one').apply(prepare_remove(removed.identity, root))
    assert visible_texture(root, virtual=virtual) == dds_payload(fill=1)
    submit(tmp_path, root, [upgrades[remaining.identity]], virtual)
    assert visible_texture(root, virtual=virtual) == dds_payload(fill=2)
    if virtual:
        submit(tmp_path, root, [], True)
    else:
        backups(tmp_path / 'remove-last').apply(prepare_remove(remaining.identity, root))
    assert visible_texture(root, virtual=virtual) == source
    submit(tmp_path, root, [first], virtual)
    assert visible_texture(root, virtual=virtual) == dds_payload(fill=1)
    restarted = load_registry(root)
    for identity in (first.identity, peer.identity):
        assert restarted['items'][identity]['binding_hash'] == initial['items'][identity]['binding_hash']
        assert restarted['items'][identity]['values'] == {}
    assert (root / 'meta/0.pathc').read_bytes() == registry_bytes
    retained_folder = (generation_path(root, load_profile(root)['generation']) / 'packages'
                       if virtual else root / '.cdmw/independent-items')
    retained = retained_folder / f'{first.identity}-{first.digest}.cditem'
    assert read_package(retained).identity == first.identity


@pytest.mark.parametrize('route', ['batch', 'later', 'virtual'])
@pytest.mark.parametrize('reverse', [False, True])
def test_legacy_actual_texture_reads_remain_exact_across_package_orders(tmp_path, route, reverse):
    root, snapshot = texture_game(tmp_path)
    legacy = from_plan(NewItemService().plan(shop_spec('ByteConsumer'), snapshot, capture_independent=True), uuid4().hex)
    assert TEXTURE_PATH in legacy.dependencies
    replacement = texture_package(snapshot, title='Resource writer')
    selected = [replacement, legacy] if reverse else [legacy, replacement]
    if route == 'later':
        submit(tmp_path, root, selected[:1], False)
    before = files_in(root)
    with pytest.raises(ValueError, match='complete resource unchanged') as error:
        if route == 'virtual':
            prepare_profile(VirtualProfile(package_paths(tmp_path / 'inputs', selected)), root)
        else:
            prepare_install([package_bytes(package) for package in (selected[1:] if route == 'later' else selected)], root)
    assert legacy.identity in str(error.value) and replacement.identity in str(error.value)
    assert TEXTURE_PATH in str(error.value)
    assert files_in(root) == before


@pytest.mark.parametrize('virtual', [False, True])
@pytest.mark.parametrize('borrowed', [False, True])
def test_hybrid_legacy_recipe_and_texture_module_use_the_actual_read_boundary(tmp_path, virtual, borrowed):
    root, snapshot = texture_game(tmp_path)
    original = from_plan(NewItemService().plan(shop_spec('HybridConsumer'), snapshot, capture_independent=True), uuid4().hex)
    target = TEXTURE_PATH if borrowed else SECOND_TEXTURE_PATH
    texture = texture_package(snapshot, {target: dds_payload(fill=1)})
    manifest = deepcopy(package_metadata(migrate_v1(original)))
    manifest['provenance'] = None  # A newly authored mixed v2 envelope, not a claimed unchanged v1 lowering.
    manifest['requires']['texture.replace'] = 1
    manifest['modules'].extend(deepcopy(texture.manifest['modules']))
    manifest['dependencies'].update(texture.dependencies)
    blobs = dict(original.blobs, **texture.blobs)
    manifest['blobs'] = {key: len(data) for key, data in blobs.items()}
    hybrid = read_v2(manifest, blobs)
    before = files_in(root)
    if borrowed:
        with pytest.raises(ValueError, match='complete resource unchanged'):
            submit(tmp_path, root, [hybrid], virtual)
        assert files_in(root) == before
        return
    submit(tmp_path, root, [hybrid], virtual)
    assert visible_texture(root, SECOND_TEXTURE_PATH, virtual=virtual) == dds_payload(fill=1)
    assert visible_texture(root, TEXTURE_PATH, virtual=virtual) == snapshot.payload(TEXTURE_PATH)
    assert load_registry(root)['items'][hybrid.identity]['values']['iteminfo']['item']


@pytest.mark.parametrize('virtual', [False, True])
@pytest.mark.parametrize('reverse', [False, True])
def test_source_equal_texture_requirement_survives_actual_semantic_export(tmp_path, virtual, reverse):
    producer, source = texture_game(tmp_path / 'producer')
    package = texture_package(source, {TEXTURE_PATH: source.payload(TEXTURE_PATH)}, title='Keep original texture')
    submit(tmp_path / 'producer', producer, [package], False)
    exported = export_merged_mod(prepare_independent_mod_merge(producer), tmp_path / 'export')
    wrapper = exported.package_root / SEMANTIC_EXPORT_FILE
    assert wrapper.is_file()
    root, snapshot = texture_game(tmp_path / 'recipient')
    conflicting = texture_package(snapshot, title='Require changed texture')
    paths = [wrapper, *package_paths(tmp_path / 'inputs', [conflicting])]
    if reverse:
        paths.reverse()
    if virtual:
        publish_profile(prepare_profile(VirtualProfile((wrapper,)), root))
    else:
        backups(tmp_path / 'recipient/initial').apply(prepare_install([wrapper], root).preparation)
    before = files_in(root)
    with pytest.raises(ValueError, match='Texture conflict') as error:
        if virtual:
            prepare_profile(VirtualProfile(tuple(paths)), root)
        else:
            prepare_install(paths, root)
    assert package.identity in str(error.value) and conflicting.identity in str(error.value)
    assert TEXTURE_PATH in str(error.value)
    assert files_in(root) == before


def test_real_virtual_worker_retains_texture_registry_digest(tmp_path):
    from cdmw.services.virtual_loader_process import prepare_profile_in_subprocess
    from cdmw.services.independent_item_package import digest
    root, snapshot = texture_game(tmp_path)
    package = texture_package(snapshot)
    paths = package_paths(tmp_path / 'inputs', [package])
    prepared = prepare_profile_in_subprocess(VirtualProfile(paths), root)
    expected = digest((root / 'meta/0.pathc').read_bytes())
    assert dict(prepared.source_revision.indexes)[root / 'meta/0.pathc'] == expected
    publish_profile(prepared)
    assert dict(load_profile(root)['sources'])[str(root / 'meta/0.pathc')] == expected
    assert visible_texture(root, virtual=True) == dds_payload(fill=1)


@pytest.mark.parametrize('route', ['selected', 'active', 'disabled'])
@pytest.mark.parametrize('rebind_cache', [False, True], ids=['stale-cache', 'bound-cache'])
def test_worker_cannot_omit_the_required_texture_registry_witness(tmp_path, monkeypatch, route, rebind_cache):
    import json
    from cdmw.domain.new_item.compilation import _identity
    from cdmw.services import virtual_loader_process as owner
    from cdmw.services.virtual_loader_cache import _input_identity, _key
    from cdmw.services.independent_item_package import canonical, digest
    root, snapshot = texture_game(tmp_path)
    package = texture_package(snapshot)
    paths = package_paths(tmp_path / 'inputs', [package])
    if route != 'selected':
        submit(tmp_path, root, [package], False)
        if route == 'disabled':
            layer = load_registry(root)['items'][package.identity]['layer']
            backups(tmp_path / 'disable-for-worker').apply(overlays.prepare_overlay_enabled(root, layer, False))
        paths = ()
    registry = str(root / 'meta/0.pathc')
    before = files_in(root)

    def run(command, **kwargs):
        output = Path(command[command.index('--output') + 1])
        source = Path(command[command.index('--input') + 1])
        assert owner.run_virtual_profile_worker(source, output) == 0
        result = json.loads(output.read_bytes())
        for key in ('source', 'external_source'):
            result[key]['indexes'] = [row for row in result[key]['indexes'] if row[0] != registry]
            result[key]['files'] = [row for row in result[key]['files'] if row[0] != registry]
        profile = json.loads((output.parent / (result['profile'][0] + '.bin')).read_bytes())
        profile['sources'] = [row for row in profile['sources'] if row[0] != registry]
        profile['compilation']['inputs']['sources'] = dict(profile['sources'])
        profile['compilation']['identity'] = _identity(profile['compilation']['inputs'])
        if rebind_cache:
            # Preserve internal cache consistency so the retained parent-side
            # registry witness, rather than an unrelated cache error, refuses.
            record = profile['build_cache']
            record['inputs'] = _input_identity(profile['compilation'])
            record['key'] = _key(record)
            owner.validate_profile(profile)
        encoded = canonical(profile)
        checksum = digest(encoded)
        (output.parent / (checksum + '.bin')).write_bytes(encoded)
        result['profile'] = [checksum, len(encoded)]
        output.write_bytes(canonical(result))
        if rebind_cache:
            accepted = owner._read_result(json.loads(source.read_bytes()), output.parent, output, None)
            assert accepted.root == root
        return 0, '', ''

    monkeypatch.setattr(owner, 'run_process_with_cancellation', run)
    expected = 'invalid or incomplete' if rebind_cache else 'Invalid virtual build cache record'
    with pytest.raises(VirtualLoaderError, match=expected):
        owner.prepare_profile_in_subprocess(VirtualProfile(paths), root)
    assert files_in(root) == before


@pytest.mark.parametrize('virtual', [False, True])
def test_texture_removal_and_reviewed_retirement_preserve_current_shipped_baseline(tmp_path, virtual):
    from cdmw.services.independent_item_package import stock_snapshot
    from cdmw.services.archive_overlay_rebuild import prepare_overlay_rebuild

    root, snapshot = texture_game(tmp_path / 'original')
    package = texture_package(snapshot)
    submit(tmp_path, root, [package], virtual)
    original_bindings = load_registry(root)['items'][package.identity]['binding_hash']

    # A synthetic game update changes the shipped archive while this owner is installed.
    updated_root, _updated_snapshot = texture_game(tmp_path / 'updated', source=dds_payload(fill=3))
    assert (updated_root / 'meta/0.pathc').read_bytes() == (root / 'meta/0.pathc').read_bytes()
    for path in (updated_root / '0009').iterdir():
        (root / '0009' / path.name).write_bytes(path.read_bytes())
    checksum = parse_papgt((updated_root / 'meta/0.papgt').read_bytes())[0].pamt_checksum
    mount = root / 'meta/0.papgt'
    mount.write_bytes(papgt_with_directory(mount.read_bytes(), '0009', checksum))
    updated_shipped = files_in(root / '0009')
    if virtual:
        submit(tmp_path, root, [], True)
    else:
        before_review = files_in(root)
        with pytest.raises(ValueError, match='baselines need review before removal'):
            prepare_remove(package.identity, root)
        with pytest.raises(ValueError, match='changed|source|match'):
            prepare_overlay_rebuild(root)
        assert files_in(root) == before_review

        # The existing explicit recovery route retires an unmounted stale set.
        state = overlays._load_index(root)
        current_mount = mount.read_bytes()
        mount.write_bytes(serialize_papgt(
            [row for row in parse_papgt(current_mount) if row.name != state['directory']],
            header=current_mount[:12]))
        retained = files_in(root)
        retirement = overlays.prepare_overlay_retirement(root)
        recovery = backups(tmp_path / 'retire-updated-source')
        result = overlays.apply_overlay_retirement(retirement, confirmed=True,
            backup=lambda paths, label: recovery.backup_files(paths, description=label),
            restore_backup=recovery.restore_backup, game_running=lambda: False)
        assert result.retired_inventory.read_bytes() == retirement.inventory_data
        assert result.backup_dir.is_dir()
        assert all((root / path).read_bytes() == data for path, data in retained.items()
                   if path != Path(overlays.INDEX_PATH))

    assert visible_texture(root, virtual=virtual) == dds_payload(fill=3)
    assert files_in(root / '0009') == updated_shipped
    assert load_registry(root)['items'][package.identity]['binding_hash'] == original_bindings
    before = files_in(root)
    with pytest.raises(ValueError, match='changed|match|source'):
        submit(tmp_path, root, [package], virtual)
    assert files_in(root) == before

    # Reauthoring against that current source keeps the owner and restores to the new bytes.
    rebuilt = texture_package(stock_snapshot(root), identity=package.identity, release='2')
    submit(tmp_path, root, [rebuilt], virtual)
    assert visible_texture(root, virtual=virtual) == dds_payload(fill=1)
    if virtual:
        submit(tmp_path, root, [], True)
    else:
        backups(tmp_path / 'remove-reauthored').apply(prepare_remove(package.identity, root))
    assert visible_texture(root, virtual=virtual) == dds_payload(fill=3)
    assert files_in(root / '0009') == updated_shipped


@pytest.mark.parametrize('virtual', [False, True])
@pytest.mark.parametrize('remove_first', [False, True])
def test_changed_texture_export_reimport_preserves_independent_equal_owners(tmp_path, virtual, remove_first):
    producer, source = texture_game(tmp_path / 'producer')
    first, peer = texture_package(source, title='Changed first'), texture_package(source, title='Changed peer')
    packages = (first, peer)
    submit(tmp_path / 'producer', producer, packages, False)
    exported = export_merged_mod(prepare_independent_mod_merge(producer), tmp_path / 'export')
    bundle = read_semantic_export(exported.package_root)
    assert set(bundle.packages) == {package_bytes(package) for package in packages}
    assert {path: data for path, data, _flags in bundle.files}[TEXTURE_PATH] == dds_payload(fill=1)
    assert bundle.originals[TEXTURE_PATH] == dds_payload()

    root, snapshot = texture_game(tmp_path / 'recipient')
    upgrades = {package.identity: texture_package(snapshot, {TEXTURE_PATH: dds_payload(fill=2)},
        identity=package.identity, title=package.title, release='2') for package in packages}

    def import_folder():
        if virtual:
            publish_profile(prepare_profile(VirtualProfile((), (exported.package_root,)), root))
        else:
            prepared = prepare_install([exported.package_root], root)
            if prepared.preparation is not None:
                backups(tmp_path / uuid4().hex).apply(prepared.preparation)

    import_folder()
    assert visible_texture(root, virtual=virtual) == dds_payload(fill=1)
    registry = load_registry(root)
    assert set(registry['items']) == {first.identity, peer.identity}
    removed, remaining = (first, peer) if remove_first else (peer, first)
    if virtual:
        submit(tmp_path, root, [remaining], True)
    else:
        backups(tmp_path / 'remove-exported-one').apply(prepare_remove(removed.identity, root))
    assert visible_texture(root, virtual=virtual) == dds_payload(fill=1)

    submit(tmp_path, root, [upgrades[remaining.identity]], virtual)
    assert visible_texture(root, virtual=virtual) == dds_payload(fill=2)
    if virtual:
        submit(tmp_path, root, [], True)
    else:
        backups(tmp_path / 'remove-exported-last').apply(prepare_remove(remaining.identity, root))
    assert visible_texture(root, virtual=virtual) == dds_payload()
    import_folder()
    assert visible_texture(root, virtual=virtual) == dds_payload(fill=1)
    for package in packages:
        assert load_registry(root)['items'][package.identity]['binding_hash'] == (
            registry['items'][package.identity]['binding_hash'])
