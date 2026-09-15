"""Unmounted overlay recovery and install-error delivery against owned fixtures."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from dataclasses import replace
import hashlib
import html
from pathlib import Path
import threading
import time

import pytest
from PySide6.QtCore import QCoreApplication, QEvent, QThread
from PySide6.QtWidgets import QApplication, QMessageBox

from cdmw.core.pathc_format import encode_pathc, register_dds
from cdmw.domain.archives.mutation import MetaFileWrite
from cdmw.services.archive_overlay_manager import (
    INDEX_PATH, list_installed_overlays, prepare_overlay_retirement, apply_overlay_retirement,
)
from cdmw.ui.new_item.controller import NewItemStudioController
from cdmw.ui.new_item.panels_output import OutputPanel, install_result_report
from cdmw.ui.new_item.overlay_manager_dialog import OverlayManagerDialog
from tests.test_archive_overlay_manager import Backups, shop_spec, snapshot_of
from tests.test_new_item_provenance import setup_game
from tests.test_pathc_format import build_table, ICON_HEADER, ICON_BLOCKS


@pytest.fixture
def old_set(tmp_path):
    service, _snapshot, _ = setup_game(tmp_path)
    root, backups = tmp_path / "game", Backups(tmp_path)
    registry = root / "meta/0.pathc"
    baseline = build_table(headers=[ICON_HEADER], entries=[("ui/texture/base.dds", 0, ICON_BLOCKS)])
    registry.write_bytes(encode_pathc(baseline))
    mount = root / "meta/0.papgt"
    original_mount = mount.read_bytes()
    first = replace(service.plan(shop_spec("Previous"), snapshot_of(root)),
                    meta_files=(MetaFileWrite("meta/0.pathc", registry.read_bytes()),))
    service.install_overlay(first, mutation_service=backups, confirmed=True, game_running=lambda: False)
    original_inventory = list_installed_overlays(root)
    assert original_inventory[0].compatibility_status != "unmounted"
    mounted = mount.read_bytes()
    # Simulate an update resetting the mount list and replacing the texture registry.
    registry.write_bytes(encode_pathc(register_dds(baseline, "ui/texture/game_update.dds", ICON_HEADER)))
    mount.write_bytes(original_mount)
    return service, root, backups, mounted


def fingerprints(root):
    return {p.relative_to(root): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in root.rglob("*") if p.is_file()}


def drain(app, controller):
    deadline = time.monotonic() + 5
    while controller.busy and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.002)
    assert not controller.busy


@pytest.mark.parametrize("synchronous", [True, False])
def test_mounted_registry_conflict_reports_install_failure_without_writes(old_set, monkeypatch, synchronous):
    app = QApplication.instance() or QApplication([])
    service, root, backups, mounted = old_set
    inventory = list_installed_overlays(root)
    assert len(inventory) == 1
    assert inventory[0].compatibility_status == "unmounted"
    (root / "meta/0.papgt").write_bytes(mounted)
    plan = service.plan(shop_spec("NewAxe"), snapshot_of(root))
    controller = NewItemStudioController(service=service, synchronous=synchronous)
    panel = OutputPanel(controller)
    controller.plan = plan
    controller._plan_revision = controller._draft_revision
    controller.plan_ready.emit(plan)
    warnings, completed = [], []
    monkeypatch.setattr(QMessageBox, "warning", lambda parent, title, message:
                        warnings.append((parent, title, message, QThread.currentThread())))
    monkeypatch.setattr(QMessageBox, "information", lambda *_args:
                        pytest.fail("A rejected install must not show a success dialog."))
    monkeypatch.setattr("cdmw.services.new_item_service.game_is_running", lambda: False)
    controller.install_finished.connect(completed.append)
    before = fingerprints(root)
    try:
        assert controller.start_install_overlay(backups)
        drain(app, controller)
        assert completed == []
        assert len(warnings) == 1
        parent, title, message, thread = warnings[0]
        assert parent is panel and title == "Overlay installation failed"
        assert "meta/0.pathc changed outside the overlay manager" in message
        assert "Check game updates" in message and "does not repair" in message
        assert thread is app.thread()
        assert message in html.unescape(panel.busy_state.text()), "The failure must survive worker teardown."
        assert message in panel.log.toPlainText() and panel.log_toggle.isChecked()
        assert not panel.busy_bar.isVisible()
        assert controller.plan is plan and controller.has_current_plan
        assert panel.install_overlay_button.isEnabled()
        assert backups.count == 1
        assert fingerprints(root) == before
        controller.invalidate_plan()
        assert not panel.busy_state.text()
    finally:
        controller.request_shutdown()
        drain(app, controller)
        panel.deleteLater()
        controller.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


@pytest.mark.parametrize("synchronous", [True, False])
def test_install_automatically_recovers_an_unmounted_set(old_set, monkeypatch, synchronous):
    app = QApplication.instance() or QApplication([])
    service, root, backups, _ = old_set
    inventory = (root / INDEX_PATH).read_bytes()
    before = fingerprints(root)
    plan = service.plan(shop_spec("NewAxe"), snapshot_of(root))
    controller = NewItemStudioController(service=service, synchronous=synchronous)
    panel = OutputPanel(controller)
    controller.plan = plan
    controller._plan_revision = controller._draft_revision
    controller.plan_ready.emit(plan)
    completed, messages = [], []
    controller.install_finished.connect(completed.append)
    monkeypatch.setattr("cdmw.services.new_item_service.game_is_running", lambda: False)
    monkeypatch.setattr(QMessageBox, "warning", lambda *_args: pytest.fail("Recovery should finish without an error popup."))
    monkeypatch.setattr(QMessageBox, "information", lambda _parent, title, message:
                        messages.append((title, message, QThread.currentThread())))
    try:
        assert controller.start_install_overlay(backups)
        drain(app, controller)
        assert len(completed) == 1 and len(messages) == 1
        result = completed[0]
        assert result.recovered_overlays == ("Previous",)
        assert result.recovery_inventory.read_bytes() == inventory
        assert "Automatically retired" in messages[0][1]
        assert str(result.recovery_inventory) in messages[0][1]
        assert messages[0][2] is app.thread()
        assert "Preparing automatic recovery" in panel.log.toPlainText()
        assert "Automatically retired" in panel.log.toPlainText()
        assert backups.count == 2, "Recovery and install share one verified backup."
        current = list_installed_overlays(root)
        assert len(current) == 1 and current[0].label == "NewAxe"
        assert current[0].compatibility_status != "unmounted"
        assert not panel.busy_state.text()
        for path, digest in before.items():
            if path not in {Path(INDEX_PATH), Path('meta/0.papgt')}:
                assert hashlib.sha256((root / path).read_bytes()).hexdigest() == digest
    finally:
        controller.request_shutdown()
        drain(app, controller)
        panel.deleteLater()
        controller.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


@pytest.mark.parametrize("failure", ["preparation", "write", "cancel"])
def test_automatic_recovery_retries_once_and_rolls_back_with_install(old_set, monkeypatch, failure):
    from unittest.mock import Mock
    import cdmw.services.archive_overlay_manager as manager
    service, root, backups, _ = old_set
    plan = service.plan(shop_spec("NewAxe"), snapshot_of(root))
    before = fingerprints(root)
    prepare = Mock(wraps=manager.prepare_item_overlay)
    monkeypatch.setattr(manager, "prepare_item_overlay", prepare)
    stop = threading.Event()
    if failure == "preparation":
        def fail_build(*_args, **_kwargs):
            raise OSError("injected retry preparation failure")
        monkeypatch.setattr(manager, "build_overlay_archive", fail_build)
    else:
        write = manager.atomic_write_bytes
        def fail_write(path, data):
            write(path, data)
            if path.name == "0.paz":
                if failure == "cancel":
                    stop.set()
                else:
                    raise OSError("injected retry write failure")
        monkeypatch.setattr(manager, "atomic_write_bytes", fail_write)
    with pytest.raises((OSError, RuntimeError)):
        service.install_overlay(plan, mutation_service=backups, confirmed=True,
                                game_running=lambda: False, stop_event=stop)
    assert prepare.call_count == 2
    assert backups.count == (1 if failure == "preparation" else 2)
    assert fingerprints(root) == before


def test_automatic_recovery_preserves_an_explicit_old_folder(old_set):
    service, root, backups, _ = old_set
    old_folder = list_installed_overlays(root)[0].directory
    plan = service.plan(shop_spec("NewAxe"), snapshot_of(root))
    before = fingerprints(root)
    with pytest.raises(ValueError, match="Choose Auto or an unused folder"):
        service.install_overlay(plan, mutation_service=backups, confirmed=True,
                                directory_name=old_folder, game_running=lambda: False)
    assert fingerprints(root) == before and backups.count == 1


@pytest.mark.parametrize("changed", ["inventory", "mount"])
def test_automatic_recovery_pins_the_history_during_preparation(old_set, monkeypatch, changed):
    import cdmw.services.archive_overlay_manager as manager
    from cdmw.core.papgt_format import papgt_with_directory
    service, root, backups, _ = old_set
    plan = service.plan(shop_spec("NewAxe"), snapshot_of(root))
    compose = manager._compose
    def change_before_capture(*args):
        if changed == "inventory":
            index = root / INDEX_PATH
            index.write_bytes(index.read_bytes() + b"\n")
        else:
            mount = root / "meta/0.papgt"
            mount.write_bytes(papgt_with_directory(mount.read_bytes(), "0099", 0))
        return compose(*args)
    monkeypatch.setattr(manager, "_compose", change_before_capture)
    with pytest.raises(ValueError, match="overlay state changed after preparation"):
        service.install_overlay(plan, mutation_service=backups, confirmed=True, game_running=lambda: False)
    assert backups.count == 1
    assert not (root / '.cdmw/retired-overlays').exists()
    assert (root / INDEX_PATH).is_file()


def retire(prepared, backups, **kwargs):
    return apply_overlay_retirement(prepared, confirmed=True,
        backup=lambda paths, label: backups.backup_files(paths, description=label),
        restore_backup=backups.restore_backup, game_running=lambda: False, **kwargs)


def test_retirement_preserves_game_and_old_files_and_allows_fresh_install(old_set):
    service, root, backups, _ = old_set
    before = fingerprints(root)
    prepared = prepare_overlay_retirement(root)
    assert fingerprints(root) == before
    result = retire(prepared, backups)
    assert not (root / INDEX_PATH).exists()
    assert result.retired_inventory.read_bytes() == prepared.inventory_data
    assert list_installed_overlays(root) == ()
    for path, digest in before.items():
        if path != Path(INDEX_PATH):
            assert hashlib.sha256((root / path).read_bytes()).hexdigest() == digest
    title, message = install_result_report(result)
    assert title == "Start fresh with overlays" and "Retired 1" in message
    assert str(result.backup_dir) in message
    plan = service.plan(shop_spec("NewAxe"), snapshot_of(root))
    service.install_overlay(plan, mutation_service=backups, confirmed=True, game_running=lambda: False)
    fresh = list_installed_overlays(root)
    assert len(fresh) == 1 and fresh[0].label == "NewAxe"
    assert fresh[0].directory != prepared.directory_name
    assert result.retired_inventory.read_bytes() == prepared.inventory_data
    assert hashlib.sha256((root / prepared.directory_name / "0.paz").read_bytes()).hexdigest() == before[Path(prepared.directory_name) / "0.paz"]


@pytest.mark.parametrize("change", ["mounted", "inventory", "mount", "cancelled", "game_running", "unconfirmed",
                                   "missing_backup", "missing_restore"])
def test_retirement_refuses_unreviewed_state_without_writes(old_set, change):
    _service, root, backups, mounted = old_set
    prepared = prepare_overlay_retirement(root)
    stop = threading.Event()
    if change == "mounted":
        (root / "meta/0.papgt").write_bytes(mounted)
    elif change == "inventory":
        index = root / INDEX_PATH
        index.write_bytes(index.read_bytes() + b"\n")
    elif change == "mount":
        from cdmw.core.papgt_format import papgt_with_directory
        mount = root / "meta/0.papgt"
        mount.write_bytes(papgt_with_directory(mount.read_bytes(), "0099", 0))
    elif change == "cancelled":
        stop.set()
    before = fingerprints(root)
    with pytest.raises((ValueError, RuntimeError, PermissionError)):
        apply_overlay_retirement(prepared, confirmed=change != "unconfirmed",
            backup=None if change == "missing_backup" else lambda paths, label: backups.backup_files(paths, description=label),
            restore_backup=None if change == "missing_restore" else backups.restore_backup, stop_event=stop,
            game_running=lambda: change == "game_running")
    assert backups.count == 1 and fingerprints(root) == before


@pytest.mark.parametrize("failure", ["backup", "after_backup_cancel", "after_backup_change", "rename"])
def test_retirement_backup_checks_and_rollback(old_set, monkeypatch, failure):
    _service, root, backups, _ = old_set
    prepared = prepare_overlay_retirement(root)
    before = fingerprints(root)
    stop = threading.Event()
    original_rename = Path.rename

    def fail_rename(path, target):
        original_rename(path, target)
        raise OSError("injected error after retirement")

    if failure == "rename":
        monkeypatch.setattr(Path, "rename", fail_rename)

    def backup(paths, label):
        directory = backups.backup_files(paths, description=label)
        if failure == "backup":
            (directory / "backup_manifest.json").write_text('{}')
        elif failure == "after_backup_cancel":
            stop.set()
        elif failure == "after_backup_change":
            (root / INDEX_PATH).write_bytes(prepared.inventory_data + b"\n")
        return directory

    with pytest.raises((ValueError, RuntimeError, OSError)):
        apply_overlay_retirement(prepared, confirmed=True, backup=backup,
            restore_backup=backups.restore_backup, game_running=lambda: False, stop_event=stop)
    if failure == "after_backup_change":
        assert (root / INDEX_PATH).read_bytes() == prepared.inventory_data + b"\n"
        before[Path(INDEX_PATH)] = hashlib.sha256(prepared.inventory_data + b"\n").hexdigest()
    assert fingerprints(root) == before


@pytest.mark.parametrize("synchronous", [True, False])
def test_start_fresh_dialog_reviews_then_retires_unmounted_set(old_set, monkeypatch, synchronous):
    app = QApplication.instance() or QApplication([])
    _service, root, backups, _ = old_set
    controller = NewItemStudioController(synchronous=synchronous)
    dialog = OverlayManagerDialog(controller, root, backups)
    monkeypatch.setattr("cdmw.services.new_item_service.game_is_running", lambda: False)
    try:
        app.processEvents()
        drain(app, controller)
        assert dialog.table.item(0, 6).text() == "Not mounted"
        assert "not mounted by the game" in dialog.details.text()
        assert "1 recorded overlay(s); 1 not mounted" in dialog.status.text()
        assert dialog.start_fresh_button.isEnabled()
        assert not dialog.remove_button.isEnabled()
        before = fingerprints(root)
        monkeypatch.setattr(QMessageBox, "question", lambda *_args: QMessageBox.No)
        dialog.start_fresh_button.click()
        drain(app, controller)
        assert fingerprints(root) == before
        assert "cancelled" in dialog.status.text()
        confirmations = []
        def confirm(_parent, title, message, *_args):
            confirmations.append((title, message))
            return QMessageBox.Yes
        monkeypatch.setattr(QMessageBox, "question", confirm)
        dialog.start_fresh_button.click()
        drain(app, controller)
        assert str(root) in confirmations[0][1] and "Previous" in confirmations[0][1]
        assert ".cdmw/overlays.json" in confirmations[0][1]
        assert dialog.table.rowCount() == 0
        assert not dialog.start_fresh_button.isEnabled()
        assert not (root / INDEX_PATH).exists()
    finally:
        dialog.reject()
        drain(app, controller)
        controller.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
