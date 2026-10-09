"""Publication may never create an overlay inventory its reader rejects."""
import pytest

from cdmw.services import archive_overlay_manager as overlays
from cdmw.services.independent_item_install import prepare_install, prepare_rebuild
from cdmw.services.independent_item_package import package_bytes
from tests.test_archive_overlay_manager import Backups
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
