"""Concrete ASCII ItemInfo name-hash aliases, without native/game execution."""
from uuid import UUID

import pytest

from cdmw.core.archive_format import calculate_pa_checksum, parse_archive_pamt
from cdmw.core.iteminfo_row import clone_iteminfo_row
from cdmw.domain.archives.overlay_merge import _table
from cdmw.domain.new_item.independent import IndependentItemError
from cdmw.services import independent_item_install as install
from cdmw.services.independent_item_install import (
    load_registry, prepare_install, prepare_remove, resolve_items,
)
from cdmw.services.independent_item_package import from_plan, package_bytes
from tests.test_archive_overlay_manager import Backups, shop_spec
from tests.test_independent_item_compatibility import mount_mod
from tests.test_independent_items import authored, setup_game
from tests.test_new_item_service import OTHER, _read, _table4, build_package


# Distinct canonical UUID4 identities found by a bounded, deterministic search.
# Their ASCII-lowercase names both hash to 0xab4bfdfe with the existing helper.
COLLIDING_IDS = (
    '3940d897d80049ccbbd9cf59d9cce27b',
    '71e0100e5b4c4c88a891843a775a115e',
)
COLLIDING_NAMES = tuple('CDI_' + identity for identity in COLLIDING_IDS)
STOCK_COLLISION_ID = 'e2e5d4ea3ad14dbab0c523e9f2c9189e'
STOCK_COLLISION_NAME = 'StockAlias_101450'


def _files(root):
    return {path.relative_to(root): path.read_bytes()
            for path in root.rglob('*') if path.is_file()}


def _assert_collision(detail, *owners):
    assert '0xab4bfdfe' in detail
    assert all(name in detail for name in COLLIDING_NAMES)
    assert all(owner in detail for owner in owners)


def test_observed_hash_has_a_real_generated_uuid_name_collision():
    assert len(set(COLLIDING_IDS)) == 2
    assert all(UUID(identity).version == 4 and UUID(identity).hex == identity for identity in COLLIDING_IDS)
    assert len({name.casefold() for name in COLLIDING_NAMES}) == 2
    assert {calculate_pa_checksum(name.lower().encode('ascii')) for name in COLLIDING_NAMES} == {0xab4bfdfe}


def test_non_ascii_item_names_have_no_ascii_hash_certificate():
    for name in ('CDI_\u00c4', '\u0130tem', 'Stra\u00dfe'):
        assert install._ascii_item_name_hash(name) is None


def test_ascii_item_name_hash_stops_at_the_c_string_terminator():
    assert install._ascii_item_name_hash(COLLIDING_NAMES[0] + '\0ignored') == 0xab4bfdfe
    assert install._ascii_item_name_hash(COLLIDING_NAMES[0].swapcase()) == 0xab4bfdfe


@pytest.mark.parametrize('order', [(0, 1), (1, 0)])
@pytest.mark.parametrize('target', ['archive', 'virtual'])
def test_managed_name_hash_collision_in_batch_is_refused_before_writing(tmp_path, order, target):
    packages = [authored(tmp_path / f'author{i}', identity)[1]
                for i, identity in enumerate(COLLIDING_IDS)]
    setup_game(tmp_path / 'recipient')
    root = tmp_path / 'recipient/game'
    before = _files(root)
    with pytest.raises(IndependentItemError, match='ItemInfo name hash collides') as error:
        resolve_items([package_bytes(packages[i]) for i in order], root, target=target)
    _assert_collision(str(error.value), *(f'{package.title} ({package.identity})' for package in packages))
    assert _files(root) == before


@pytest.mark.parametrize('order', [(0, 1), (1, 0)])
@pytest.mark.parametrize('state', ['active', 'disabled', 'removed'])
def test_managed_name_hash_reservation_survives_each_installation_state(tmp_path, order, state):
    packages = [authored(tmp_path / f'author{i}', identity)[1]
                for i, identity in enumerate(COLLIDING_IDS)]
    setup_game(tmp_path / 'recipient')
    root, backups = tmp_path / 'recipient/game', Backups(tmp_path)
    held, incoming = [packages[i] for i in order]
    backups.apply(prepare_install([package_bytes(held)], root).preparation)
    if state == 'disabled':
        from cdmw.services.archive_overlay_manager import prepare_overlay_enabled
        layer = load_registry(root)['items'][held.identity]['layer']
        backups.apply(prepare_overlay_enabled(root, layer, False))
    elif state == 'removed':
        backups.apply(prepare_remove(held.identity, root))
    before = _files(root)
    with pytest.raises(IndependentItemError, match='ItemInfo name hash collides') as error:
        prepare_install([package_bytes(incoming)], root)
    _assert_collision(str(error.value), *(f'{package.title} ({package.identity})' for package in packages))
    assert _files(root) == before


def test_ascii_stock_name_hash_collision_uses_the_matching_game_baseline(tmp_path):
    assert calculate_pa_checksum(('CDI_' + STOCK_COLLISION_ID).lower().encode('ascii')) == 0x50034b30
    assert calculate_pa_checksum(STOCK_COLLISION_NAME.lower().encode('ascii')) == 0x50034b30
    service, snapshot, _ = setup_game(tmp_path / 'recipient')
    root = tmp_path / 'recipient/game'
    body, head = snapshot.iteminfo.payload_entry.path, snapshot.iteminfo.header_entry.path
    donor = snapshot.rows[OTHER]
    stock_key = 1234567
    renamed = clone_iteminfo_row(donor, key=stock_key, string_key=STOCK_COLLISION_NAME,
                                name_key=donor.name_key, desc_key=donor.desc_key)
    files = {path: snapshot.payload(path) for path in snapshot.entries}
    rows = [(int.from_bytes(key, 'little'), raw)
            for key, raw in _table(files[body], files[head])[1]]
    files[body], files[head] = _table4([*rows, (stock_key, renamed)])
    entries = parse_archive_pamt(build_package(root, files))
    matching = service.build_snapshot(entries, read_entry=_read)
    plan = service.plan(shop_spec('MatchingStock'), matching, capture_independent=True)
    package = from_plan(plan, STOCK_COLLISION_ID)
    before = _files(root)
    with pytest.raises(IndependentItemError, match='ItemInfo name hash collides') as error:
        prepare_install([package_bytes(package)], root)
    detail = str(error.value)
    assert all(value in detail for value in ('0x50034b30', 'CDI_' + STOCK_COLLISION_ID,
                                            STOCK_COLLISION_NAME, f'stock game ItemInfo record {stock_key}'))
    assert _files(root) == before


@pytest.mark.parametrize('first', [True, False])
def test_ascii_external_name_hash_collision_is_refused_at_either_mount_priority(tmp_path, first):
    _, package = authored(tmp_path / 'author', COLLIDING_IDS[0])
    _, snapshot, _ = setup_game(tmp_path / 'recipient')
    root = tmp_path / 'recipient/game'
    body, head = snapshot.iteminfo.payload_entry.path, snapshot.iteminfo.header_entry.path
    original = [(int.from_bytes(key, 'little'), raw)
                for key, raw in _table(snapshot.payload(body), snapshot.payload(head))[1]]
    row = clone_iteminfo_row(snapshot.rows[OTHER], key=1990099, string_key=COLLIDING_NAMES[1],
                            name_key='998877', desc_key='998878')
    payload, header = _table4([*original, (1990099, row)])
    mount_mod(root, tmp_path / 'foreign', {body: payload, head: header}, first=first)
    before = _files(root)
    with pytest.raises(IndependentItemError, match='ItemInfo name hash collides') as error:
        prepare_install([package_bytes(package)], root)
    _assert_collision(str(error.value), 'foreign', body, 'record 1990099')
    assert _files(root) == before


def test_same_managed_name_owner_can_reinstall_and_update(tmp_path):
    _, package = authored(tmp_path / 'author', COLLIDING_IDS[0])
    setup_game(tmp_path / 'recipient')
    root, backups = tmp_path / 'recipient/game', Backups(tmp_path)
    backups.apply(prepare_install([package_bytes(package)], root).preparation)
    old = load_registry(root)['items'][package.identity]
    assert prepare_install([package_bytes(package)], root).preparation is None
    _, update = authored(tmp_path / 'updated', package.identity, 'UpdatedTitle')
    backups.apply(prepare_install([package_bytes(update)], root).preparation)
    assert load_registry(root)['items'][package.identity]['values'] == old['values']
