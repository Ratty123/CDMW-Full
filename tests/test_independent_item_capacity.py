"""Publication may never create an overlay inventory its reader rejects."""
import json
from uuid import uuid4
import pytest

from cdmw.services import archive_overlay_manager as overlays
from cdmw.services.independent_item_install import prepare_install, prepare_rebuild
from cdmw.services.independent_item_package import from_plan, package_bytes
from tests.test_archive_overlay_manager import Backups, shop_spec
from tests.test_independent_item_fields import field_package
from tests.test_independent_items import setup_game
from tests.test_independent_item_regressions import files_in


@pytest.mark.parametrize('installed', [False, True])
def test_oversized_history_refuses_preparation_and_preserves_previous_state(tmp_path, monkeypatch, installed):
    _, snapshot, _ = setup_game(tmp_path)
    package = field_package(snapshot)
    root, backups = tmp_path / 'game', Backups(tmp_path)
    prepared = prepare_install([package_bytes(package)], root).preparation
    size = len(dict(prepared.writes)[overlays.INDEX_PATH])
    if installed:
        backups.apply(prepared)
    monkeypatch.setattr(overlays, '_MAX_STATE_BYTES', size + 128 if installed else size - 128)
    before = files_in(root)
    with pytest.raises(ValueError, match='overlay history exceeds'):
        if installed:
            prepare_rebuild(package.identity, root)
        else:
            prepare_install([package_bytes(package)], root)
    assert files_in(root) == before and backups.count == int(installed)


def test_apply_rechecks_the_inventory_capacity_before_backup(tmp_path, monkeypatch):
    _, snapshot, _ = setup_game(tmp_path)
    root, backups = tmp_path / 'game', Backups(tmp_path)
    prepared = prepare_install([package_bytes(field_package(snapshot))], root).preparation
    monkeypatch.setattr(overlays, '_MAX_STATE_BYTES', len(dict(prepared.writes)[overlays.INDEX_PATH]) - 1)
    before = files_in(root)
    with pytest.raises(ValueError, match='overlay history exceeds'):
        backups.apply(prepared)
    assert files_in(root) == before and backups.count == 0


@pytest.mark.parametrize('stage', ['metadata', 'publication'])
def test_capacity_refusal_precedes_journal_or_archive_work(tmp_path, monkeypatch, stage):
    _, snapshot, _ = setup_game(tmp_path)
    root = tmp_path / 'game'
    source = package_bytes(field_package(snapshot))
    monkeypatch.setattr(overlays.time, 'time', lambda: 1_700_000_000.0)
    prepared = prepare_install([source], root).preparation
    inventory = dict(prepared.writes)[overlays.INDEX_PATH]
    state = json.loads(inventory)
    minimum = json.dumps({**state, 'sources': {}, 'published': {}}, ensure_ascii=False, separators=(',', ':')).encode() + b'\n'
    limit = len(minimum) - 1 if stage == 'metadata' else len(inventory) - 1
    assert len(minimum) < len(inventory)
    calls = []
    for name in ('_read_journal', '_processed_payload', 'build_overlay_archive'):
        original = getattr(overlays, name)
        def record(*args, _name=name, _original=original, **kwargs):
            calls.append(_name)
            return _original(*args, **kwargs)
        monkeypatch.setattr(overlays, name, record)
    before = files_in(root)
    monkeypatch.setattr(overlays, '_MAX_STATE_BYTES', limit)
    with pytest.raises(ValueError, match=f'limit {limit:,} bytes'):
        prepare_install([source], root)
    assert '_processed_payload' not in calls and 'build_overlay_archive' not in calls
    if stage == 'metadata':
        assert '_read_journal' not in calls
    assert files_in(root) == before


@pytest.mark.parametrize('operation', ['install', 'disable', 'remove'])
def test_capacity_boundary_accepts_exact_fit_and_shrinking_publication(tmp_path, monkeypatch, operation):
    service, snapshot, _ = setup_game(tmp_path)
    root, backups = tmp_path / 'game', Backups(tmp_path)
    plan = service.plan(shop_spec('CapacityBoundary'), snapshot, capture_independent=True)
    package = from_plan(plan, uuid4().hex, title='Räv 装備')
    source = package_bytes(package)
    monkeypatch.setattr(overlays.time, 'time', lambda: 1_700_000_000.0)
    original = prepare_install([source], root).preparation
    inventory = dict(original.writes)[overlays.INDEX_PATH]
    assert len(inventory) > len(inventory.decode('utf-8'))
    if operation != 'install':
        backups.apply(original)
    # The installed state must remain readable, but obsolete published hashes
    # must not make disabling/removing it fail a limit the installed state meets.
    monkeypatch.setattr(overlays, '_MAX_STATE_BYTES', len(inventory))
    if operation == 'install':
        prepared = prepare_install([source], root).preparation
        assert len(dict(prepared.writes)[overlays.INDEX_PATH]) == len(inventory)
    else:
        identity = overlays.list_installed_overlays(root)[0].id
        prepared = (overlays.prepare_overlay_enabled(root, identity, False) if operation == 'disable'
                    else overlays.prepare_overlay_removal(root, identity))
        result = dict(prepared.writes)[overlays.INDEX_PATH]
        assert len(result) < len(inventory)
        assert all(value is None for value in json.loads(result)['published'].values())
    backups.apply(prepared)
    installed = overlays.list_installed_overlays(root)
    if operation == 'remove':
        assert not installed
    else:
        assert len(installed) == 1 and installed[0].enabled == (operation == 'install')
