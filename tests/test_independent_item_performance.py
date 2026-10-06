from collections import Counter
from dataclasses import replace
import threading

import pytest

from cdmw.core import pathc_format
from cdmw.domain.cancellation import RunCancelled
from cdmw.domain.new_item.independent import IndependentItemError
from cdmw.services import independent_item_install as owner
from cdmw.services.independent_item_package import from_plan, package_bytes
from tests.test_archive_overlay_manager import shop_spec
from tests.test_independent_items import setup_game


def test_batch_hashes_stock_catalogue_once_and_remains_read_only(tmp_path, monkeypatch):
    from cdmw.domain.new_item.spec import IconSource
    from cdmw.core.item_icon_addition import NewItemIcon, icon_string_for_stem, icon_target_path
    from cdmw.core.stringinfo_table import stringinfo_key
    from tests.test_new_item_service import _fake_dds
    service, snapshot, _ = setup_game(tmp_path)
    spec = replace(shop_spec('SameIcon'), icon=IconSource.GENERATED)
    name = icon_string_for_stem(service.allocate(spec, snapshot).stem)
    icon = NewItemIcon(name, stringinfo_key(name), icon_target_path(name), _fake_dds(), None, None)
    plan = service.plan(spec, snapshot, icon=icon, capture_independent=True)
    from uuid import uuid4
    packages = [package_bytes(from_plan(plan, uuid4().hex)) for _ in range(3)]
    seen, checksum = Counter(), pathc_format.pathc_checksum
    def count(path):
        seen[path] += 1
        return checksum(path)
    monkeypatch.setattr(pathc_format, 'pathc_checksum', count)
    result = owner.resolve_items(packages, tmp_path / 'game', target='virtual')
    # A stock table is indexed only by collision detection, not texture planning.
    path = 'gamedata/binarystaticinfo__/bin/iteminfo.staticinfobody'
    assert seen[path] == 1
    assert len(result.contributions) == 3
    assert not (tmp_path / 'game/.cdmw').exists()


def test_no_added_assets_never_hash_stock_catalogue(tmp_path, monkeypatch):
    service, snapshot, _ = setup_game(tmp_path)
    plan = service.plan(shop_spec('Template'), snapshot, capture_independent=True)
    from uuid import uuid4
    checksum = pathc_format.pathc_checksum
    def check(path):
        assert path != 'gamedata/binarystaticinfo__/bin/iteminfo.staticinfobody'
        return checksum(path)
    monkeypatch.setattr(pathc_format, 'pathc_checksum', check)
    owner.resolve_items([package_bytes(from_plan(plan, uuid4().hex))], tmp_path / 'game', target='virtual')


def test_collision_index_keeps_ambiguous_stock_hash_and_retained_reservations(monkeypatch):
    checksum = lambda path: 1 if path in ('stock/a', 'stock/b') else 2
    monkeypatch.setattr(pathc_format, 'pathc_checksum', checksum)
    index = owner._AssetHashes(iter(('stock/a', 'stock/b')))
    with pytest.raises(IndependentItemError, match='asset hash collides'):
        index.check({'stock/a'}, set())
    index = owner._AssetHashes(iter(()))
    index.check({'item/a'}, set())
    with pytest.raises(IndependentItemError, match='asset hash collides'):
        index.check({'item/b'}, set())
    with pytest.raises(IndependentItemError, match='asset hash collides'):
        owner._AssetHashes(iter(())).check({'item/b'}, {'removed/item'})


def test_catalogue_scan_can_be_cancelled(monkeypatch):
    stop = threading.Event()
    seen = []
    def checksum(path):
        seen.append(path)
        stop.set()
        return len(seen)
    monkeypatch.setattr(pathc_format, 'pathc_checksum', checksum)
    with pytest.raises(RunCancelled):
        owner._AssetHashes(map(str, range(2000))).check({'new'}, set(), stop)
    assert 0 < len(seen) <= 256
