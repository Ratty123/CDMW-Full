"""Reuse preparation work without weakening freshness or archive recovery checks."""
from collections import Counter
from pathlib import Path
import threading

import pytest

from cdmw.domain.cancellation import RunCancelled
from cdmw.services import archive_overlay_manager as owner
from cdmw.services.new_item_provenance import SourceRevision, StaleNewItemSource
from tests.test_archive_overlay_manager import Backups, shop_spec, snapshot_of
from tests.test_new_item_provenance import setup_game


def installed_first(tmp_path):
    service, snapshot, _ = setup_game(tmp_path)
    backups, root = Backups(tmp_path), tmp_path / "game"
    first = service.plan(shop_spec("Alpha"), snapshot)
    service.install_overlay(first, mutation_service=backups, confirmed=True, game_running=lambda: False)
    second = service.plan(shop_spec("Beta"), snapshot_of(root))
    return service, second, backups, root


def test_install_validates_once_and_decodes_each_journal_once(tmp_path, monkeypatch):
    service, plan, backups, root = installed_first(tmp_path)
    shipped = {path: path.read_bytes() for path in (root / "0009").glob("*") if path.is_file()}
    decoded, validations = Counter(), []
    unpack, validate = owner._unpack_changes, SourceRevision.validate

    def counted_unpack(root, layer, pending, stop):
        decoded[layer["id"]] += 1
        return unpack(root, layer, pending, stop)

    def counted_validate(revision, stop=None):
        validations.append(revision)
        return validate(revision, stop)

    monkeypatch.setattr(owner, "_unpack_changes", counted_unpack)
    monkeypatch.setattr(SourceRevision, "validate", counted_validate)
    service.install_overlay(plan, mutation_service=backups, confirmed=True, game_running=lambda: False)
    assert validations == [plan.source_revision]
    assert sorted(decoded.values()) == [1, 1]
    assert [item.label for item in owner.list_installed_overlays(root)] == ["Alpha", "Beta"]
    assert all(path.read_bytes() == data for path, data in shipped.items())


def test_reused_journal_is_still_checked_for_changes_before_composition(tmp_path, monkeypatch):
    service, plan, backups, root = installed_first(tmp_path)
    original = owner._compose
    archive_files = {p: p.read_bytes() for p in root.rglob("*") if p.suffix in {".pamt", ".paz", ".papgt"}}
    journal = root / ".cdmw/overlays" / (owner.list_installed_overlays(root)[0].id + ".zip")

    def change_after_dependency_check(*args, **kwargs):
        assert kwargs["decoded"], "exercise a previously decoded journal"
        journal.write_bytes(journal.read_bytes() + b"owned external change")
        return original(*args, **kwargs)

    monkeypatch.setattr(owner, "_compose", change_after_dependency_check)
    with pytest.raises(ValueError, match="journal.*changed"):
        service.install_overlay(plan, mutation_service=backups, confirmed=True, game_running=lambda: False)
    assert backups.count == 1
    assert all(p.read_bytes() == data for p, data in archive_files.items())


def test_cancel_after_dependency_check_stops_before_writes(tmp_path, monkeypatch):
    service, plan, backups, root = installed_first(tmp_path)
    before = {p: p.read_bytes() for p in root.rglob("*") if p.is_file()}
    stop = threading.Event()
    original = owner._uses_owned_assets

    def cancel(*args):
        result = original(*args)
        stop.set()
        return result

    monkeypatch.setattr(owner, "_uses_owned_assets", cancel)
    with pytest.raises(RunCancelled):
        service.install_overlay(plan, mutation_service=backups, confirmed=True, game_running=lambda: False, stop_event=stop)
    assert backups.count == 1
    assert all(p.read_bytes() == data for p, data in before.items())


def test_install_still_rejects_changed_plan_sources_before_backup(tmp_path):
    service, snapshot, entries = setup_game(tmp_path)
    plan, backups = service.plan(shop_spec("Alpha"), snapshot), Backups(tmp_path)
    with Path(entries[0].paz_file).open("ab") as stream:
        stream.write(b"owned source change")
    with pytest.raises(StaleNewItemSource):
        service.install_overlay(plan, mutation_service=backups, confirmed=True, game_running=lambda: False)
    assert backups.count == 0
