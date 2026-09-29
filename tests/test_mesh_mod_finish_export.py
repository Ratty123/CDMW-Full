"""Finish's validated cloth edit must reach every Build Mod package through the UI."""

from __future__ import annotations

import json
import time
import zipfile
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QThread
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QApplication, QMessageBox, QPushButton

from cdmw.core.archive_extraction import read_archive_entry_data
from cdmw.core.archive_format import parse_archive_pamt
from cdmw.core.papgt_format import PAPGT_DEFAULT_FLAGS, PapgtDirectory, serialize_papgt
from cdmw.core.mod_export_history import mod_metadata_path
from cdmw.domain.mesh.cloth import PacClothRule
from cdmw.modding.pac_cloth import apply_pac_cloth_rules
from cdmw.models import ArchiveEntry
from cdmw.ui.mesh_editor.controller import MeshEditorController
from cdmw.ui.mesh_editor.mod_export_dialog import MeshModExportDialog
from cdmw.workers.mesh_rust_editor_workers import MeshRustProtocolWorker
from cdmw.workers.mesh_editor_workers import MeshDirectOutputResult
from tests.test_mesh_cloth_influence import apply_rule, cloth_session
from tests.test_mesh_rust_authoring_exact_output import _request
from tests.test_mesh_rust_editor_selection import _dispose, _tab


@pytest.fixture
def accepted_cloth_edit(cloth_session, tmp_path, monkeypatch):
    source, service, session = cloth_session
    apply_rule(session, tmp_path, PacClothRule(0))
    tab = _tab(tmp_path)
    controller = MeshEditorController(mesh_service=service)
    controller.attach_session(session.authoritative_session_id)
    tab.standalone_controller = controller
    tab.standalone_rust_target_controller = controller
    tab.standalone_rust_authoring_session = session
    entry = ArchiveEntry("owned-rust-exact.pac", tmp_path / "0009/0.pamt", tmp_path / "0009/0.paz", 0, 0, 0, 0, 0)
    entry.pamt_path.parent.mkdir()
    entry.pamt_path.write_bytes(b"owned source index")
    entry.paz_file.write_bytes(source)
    tab.current_archive_selection = entry
    request = _request(session, "finish_request", 20)
    tab.standalone_rust_protocol_request_id = 20
    tab.standalone_rust_active_event = request
    worker = MeshRustProtocolWorker(20, session, request)
    replies, errors = [], []
    worker.completed.connect(lambda *args: replies.append(args))
    worker.error.connect(lambda *args: errors.append(args))
    worker.run()
    assert not errors and len(replies) == 1
    monkeypatch.setattr(tab, "_send_rust_message", lambda _response: True)
    tab._handle_rust_protocol_completed(*replies[0])
    try:
        yield tab, service, session, entry, source
    finally:
        if tab.standalone_output_thread is not None:
            tab._cancel_mesh_direct_output_worker()
            deadline = time.monotonic() + 10
            while tab.standalone_output_thread is not None and time.monotonic() < deadline:
                QApplication.processEvents()
                time.sleep(.005)
            assert tab.standalone_output_thread is None
        tab.standalone_rust_authoring_session = None
        tab.standalone_rust_target_controller = None
        tab.standalone_controller = None
        _dispose(tab)


@pytest.mark.parametrize(
    "choice,profile,suffix,descriptor,wrapper",
    [
        ("dmm_loose", "dmm", "dmm", "manifest.json", ""),
        ("jmm_loose", "jmm", "jmm", "mod.json", ""),
        ("cdumm_loose", "cdumm", "cdumm", "modinfo.json", "files"),
        ("crimson_sharp_loose", "crimson_sharp", "crimson-sharp", "mod.json", "files"),
        ("dmm_archive", "dmm", "dmm-archive", "manifest.json", ""),
    ],
)
@pytest.mark.parametrize("create_zip,open_folder", [(False, False), (True, False), (False, True), (True, True)])
def test_finish_then_build_exports_cloth_edit_for_every_manager(
    accepted_cloth_edit, tmp_path, monkeypatch, choice, profile, suffix, descriptor, wrapper, create_zip, open_folder,
):
    tab, service, session, entry, source = accepted_cloth_edit
    accepted_revision = service.session_view(session.authoritative_session_id).revision
    assert tab._standalone_export_validation_ok()
    assert tab.standalone_export_validation_revision == accepted_revision
    assert tab.standalone_last_export_validation_report is session.accepted_export_validation[1]
    chosen = []
    opened = []

    def reveal(url):
        assert QThread.currentThread() == QApplication.instance().thread()
        folder = Path(url.toLocalFile())
        assert folder.is_dir()
        if create_zip:
            assert folder.with_name(folder.name + ".zip").is_file()
        opened.append(folder)
        return True

    monkeypatch.setattr(QDesktopServices, "openUrl", reveal)
    mount = None
    if choice == "dmm_archive":
        mount = serialize_papgt([PapgtDirectory("0009", PAPGT_DEFAULT_FLAGS, 0)])
        (tmp_path / "meta").mkdir()
        (tmp_path / "meta/0.papgt").write_bytes(mount)

    def choose(dialog):
        assert isinstance(dialog, MeshModExportDialog)
        assert dialog.manager.count() == 5
        assert not dialog.build_button.isEnabled()
        assert not dialog.create_zip.isChecked() and not dialog.open_folder.isChecked()
        index = next(i for i in range(dialog.manager.count()) if dialog.manager.itemData(i)[0] == choice)
        dialog.manager.setCurrentIndex(index)
        dialog.mod_name.setText("  Stiff Canta Cloak  ")
        dialog.output_parent.setText(str(tmp_path / "exports"))
        dialog.version.setText("2.3")
        dialog.author.setText("Mesh Tester")
        dialog.description.setText("Cloth physics removed.")
        dialog.create_zip.setChecked(create_zip)
        dialog.open_folder.setChecked(open_folder)
        assert dialog.build_button.isEnabled()
        chosen.append(dialog.output_path())
        return dialog.DialogCode.Accepted

    monkeypatch.setattr(MeshModExportDialog, "exec", choose)
    messages = []
    tab.status_message_requested.connect(lambda text, error: messages.append((text, error)))
    button = tab.standalone_native_host_frame.findChild(QPushButton, "MeshEditorRustResultBuildMod")
    assert button is not None and button.isEnabled()
    button.click()
    assert chosen == [tmp_path / "exports" / f"Stiff Canta Cloak-{suffix}"]
    worker = tab.standalone_output_worker
    assert worker is not None and worker.expected_mesh_revision == accepted_revision
    deadline = time.monotonic() + 15
    while tab.standalone_output_thread is not None and time.monotonic() < deadline:
        QApplication.processEvents()
        time.sleep(.005)
    assert tab.standalone_output_thread is None
    assert not [text for text, error in messages if error], messages
    output = chosen[0]
    if choice == "dmm_archive":
        entries = parse_archive_pamt(output / "0036/0.pamt")
        exported = next(item for item in entries if item.path == entry.path)
        payload, unsupported, _reason = read_archive_entry_data(exported)
        assert not unsupported
        manifest = json.loads((output / "manifest.json").read_text())
        assert manifest["structure"] == "archive_group"
        assert manifest["archive_group"] == "0036"
        assert manifest["overrides"] == [entry.path]
        assert not (output / "meta/0.papgt").exists()
        assert "meta/0.papgt" not in json.dumps(manifest)
        assert (tmp_path / "meta/0.papgt").read_bytes() == mount
    else:
        payload = (output / wrapper / entry.path).read_bytes()
        assert (output / ".no_encrypt").is_file() == (profile == "crimson_sharp")
        if profile == "jmm":
            metadata = json.loads((output / descriptor).read_text())
            assert metadata["target"] == entry.path
            assert metadata["files"] == [entry.path]
    assert payload == apply_pac_cloth_rules(source, {0: PacClothRule(0)})
    for name in ("manifest.json", descriptor):
        if (output / name).is_file():
            metadata = json.loads((output / name).read_text())
            assert metadata.get("name", metadata.get("title")) == "Stiff Canta Cloak"
            assert metadata["version"] == "2.3"
            assert metadata["author"] == "Mesh Tester"
            assert metadata["description"] == "Cloth physics removed."
            if name == "manifest.json":
                assert metadata["manager_targets"] == [profile]
    expected_files = {"manifest.json", descriptor}
    if choice == "dmm_archive":
        expected_files.update(("0036/0.pamt", "0036/0.paz"))
    else:
        expected_files.add((Path(wrapper) / entry.path).as_posix())
        if profile == "crimson_sharp":
            expected_files.add(".no_encrypt")
        if profile in {"jmm", "cdumm"}:
            expected_files.remove("manifest.json")
    assert {p.relative_to(output).as_posix() for p in output.rglob("*") if p.is_file()} == expected_files
    for name in ("mesh-editor-session.json", "cdmw-compatibility.json", "cdmw-baseline.zip"):
        history = mod_metadata_path(output, name)
        assert history.is_file() and not history.is_relative_to(output)
    archive_path = output.with_name(output.name + ".zip")
    assert archive_path.exists() is create_zip
    if create_zip:
        with zipfile.ZipFile(archive_path) as archive:
            assert set(archive.namelist()) == expected_files
            for name in expected_files:
                assert archive.read(name) == (output / name).read_bytes()
    assert opened == ([output] if open_folder else [])
    assert entry.pamt_path.read_bytes() == b"owned source index"
    assert entry.paz_file.read_bytes() == source
    assert not list(output.parent.glob(".*.staging-*"))


@pytest.mark.parametrize("change", ["cancel", "revision", "target", "controller"])
def test_build_dialog_cannot_publish_cancelled_or_changed_session(accepted_cloth_edit, tmp_path, monkeypatch, change):
    tab, service, session, entry, _source = accepted_cloth_edit
    started = []

    def choose(dialog):
        dialog.output_parent.setText(str(tmp_path / "exports"))
        dialog.create_zip.setChecked(True)
        dialog.open_folder.setChecked(True)
        if change == "cancel":
            return dialog.DialogCode.Rejected
        if change == "revision":
            service.undo(session.authoritative_session_id)
        elif change == "target":
            tab.current_archive_selection = replace(entry, path="another.pac")
        elif change == "controller":
            tab.standalone_controller = MeshEditorController(mesh_service=service)
        return dialog.DialogCode.Accepted

    monkeypatch.setattr(MeshModExportDialog, "exec", choose)
    monkeypatch.setattr(tab, "_start_mesh_direct_output_worker", lambda *args, **kwargs: started.append(kwargs))
    tab._start_mesh_mod_build_requested()
    assert not started
    assert not (tmp_path / "exports").exists()


def test_finish_report_cannot_authorize_a_later_revision(accepted_cloth_edit):
    tab, service, session, _entry, _source = accepted_cloth_edit
    assert tab._standalone_export_validation_ok()
    service.undo(session.authoritative_session_id)
    tab._refresh_after_rust_finish({})
    assert not tab._standalone_export_validation_ok()


def test_build_explains_invalid_validation_in_a_dialog(accepted_cloth_edit, monkeypatch):
    tab, service, session, _entry, _source = accepted_cloth_edit
    service.undo(session.authoritative_session_id)
    warnings = []
    monkeypatch.setattr(QMessageBox, "warning", lambda _parent, title, message: warnings.append((title, message)))
    monkeypatch.setattr(MeshModExportDialog, "exec", lambda _dialog: pytest.fail("Unvalidated export opened"))
    tab._start_mesh_mod_build_requested()
    assert warnings == [("Build Mod", "Run validation successfully before building a mesh mod.")]


def test_finish_report_cannot_authorize_a_different_session(accepted_cloth_edit):
    tab, service, session, _entry, _source = accepted_cloth_edit
    mesh = service.working_mesh(session.authoritative_session_id, clone=True)
    tab.standalone_controller.open_mesh(mesh, session_id="different-mesh")
    try:
        tab.standalone_last_export_validation_report = None
        tab.standalone_export_validation_revision = None
        tab._refresh_after_rust_finish({})
        assert tab.standalone_last_export_validation_report is None
        assert not tab._standalone_export_validation_ok()
    finally:
        service.close_edit_session("different-mesh", force_without_saving=True)


@pytest.mark.parametrize("failure", ["zip", "cancel", "publish", "claimed_zip", "raced_zip", "history", "history_cancel"])
def test_failed_or_cancelled_zip_never_publishes_partial_output_or_opens_folder(
    accepted_cloth_edit, tmp_path, monkeypatch, failure,
):
    import cdmw.core.mod_export_history as history
    import cdmw.core.mod_package as package

    tab, _service, _session, entry, _source = accepted_cloth_edit
    root = tmp_path / "exports" / "Cloak v1.2-dmm"
    zip_path = root.with_name(root.name + ".zip")
    opened, messages, reached = [], [], []
    monkeypatch.setattr(QDesktopServices, "openUrl", lambda url: opened.append(url))
    tab.status_message_requested.connect(lambda text, error: messages.append((text, error)))
    write_zip = package._write_package_zip
    save_history = history.atomic_publish_directory
    rename = Path.rename

    def interrupted_zip(staging, **kwargs):
        reached.append(failure)
        result = write_zip(staging, **kwargs)
        if failure == "cancel":
            kwargs["stop_event"].set()
        else:
            raise OSError("ZIP write failed")
        return result

    def interrupted_history(staging, target):
        reached.append(failure)
        if failure == "history":
            raise OSError("History storage unavailable")
        result = save_history(staging, target)
        tab.standalone_output_worker.stop()
        return result

    def interrupted_publish(staged, target):
        if Path(target) == zip_path and failure == "publish":
            reached.append(failure)
            raise OSError("ZIP publication failed")
        if Path(target) == zip_path and failure == "raced_zip":
            reached.append(failure)
            zip_path.write_bytes(b"another export")
        result = rename(staged, target)
        if Path(target) == root and failure == "claimed_zip":
            reached.append(failure)
            zip_path.write_bytes(b"another export")
        return result

    if failure in {"zip", "cancel"}:
        monkeypatch.setattr(package, "_write_package_zip", interrupted_zip)
    elif failure in {"history", "history_cancel"}:
        monkeypatch.setattr(history, "atomic_publish_directory", interrupted_history)
    else:
        monkeypatch.setattr(Path, "rename", interrupted_publish)
    assert tab._start_mesh_direct_output_worker(
        "loose_mod", entry, output_path=root, create_zip=True, open_folder=True,
    )
    deadline = time.monotonic() + 15
    while tab.standalone_output_thread is not None and time.monotonic() < deadline:
        QApplication.processEvents()
        time.sleep(.005)
    assert tab.standalone_output_thread is None
    assert not root.exists()
    if failure in {"claimed_zip", "raced_zip"}:
        assert zip_path.read_bytes() == b"another export"
    else:
        assert not zip_path.exists()
    assert not opened
    assert reached == [failure]
    assert not any("output ready" in text for text, _error in messages)
    assert any("cancelled" in text.lower() or error for text, error in messages), messages
    assert not list(root.parent.glob(".*.staging-*"))
    assert not list(history._history_root().glob(".history-*"))


def test_build_avoids_existing_zip_and_keeps_dots_in_folder_name(accepted_cloth_edit, tmp_path, monkeypatch):
    tab, _service, _session, _entry, _source = accepted_cloth_edit
    existing = tmp_path / "Cloak v1.2-dmm.zip"
    existing.write_bytes(b"existing ZIP")
    started = []

    def choose(dialog):
        dialog.mod_name.setText("Cloak v1.2")
        dialog.output_parent.setText(str(tmp_path))
        dialog.create_zip.setChecked(True)
        return dialog.DialogCode.Accepted

    monkeypatch.setattr(MeshModExportDialog, "exec", choose)
    monkeypatch.setattr(tab, "_start_mesh_direct_output_worker", lambda *args, **kwargs: started.append(kwargs))
    tab._start_mesh_mod_build_requested()
    assert len(started) == 1 and started[0]["create_zip"]
    output = started[0]["output_path"]
    assert output != existing.with_suffix("")
    assert not output.with_name(output.name + ".zip").exists()
    assert existing.read_bytes() == b"existing ZIP"


def test_late_result_cannot_open_export_folder(accepted_cloth_edit, tmp_path, monkeypatch):
    tab, _service, _session, _entry, _source = accepted_cloth_edit
    opened = []
    monkeypatch.setattr(QDesktopServices, "openUrl", lambda url: opened.append(url))
    result = MeshDirectOutputResult("loose_mod", tmp_path, zip_path=tmp_path / "mod.zip")
    tab._handle_mesh_direct_output_completed(tab.standalone_output_request_id - 1, result, open_folder=True)
    assert not opened


@pytest.mark.parametrize("busy", [False, True])
@pytest.mark.parametrize("confirm", [False, True])
def test_queued_completion_preserves_overlay_confirmation_and_cleanup_order(
    accepted_cloth_edit, tmp_path, monkeypatch, busy, confirm,
):
    tab, _service, _session, entry, _source = accepted_cloth_edit
    preparation = SimpleNamespace(
        requested_paths=(entry.path,), carried_forward_paths=(), backup_targets=(),
        mount_list_before=("0009",), mount_list_after=("0009", "0042"), directory=tmp_path / "0042",
    )
    mutation_service = object()
    calls, prompts = [], []

    def question(*args):
        prompts.append(args)
        assert QThread.currentThread() == QApplication.instance().thread()
        return QMessageBox.Yes if confirm else QMessageBox.No

    monkeypatch.setattr(QMessageBox, "question", question)
    monkeypatch.setattr(tab, "_mesh_direct_output_busy", lambda: busy)
    monkeypatch.setattr(tab, "_start_mesh_overlay_operation_worker", lambda worker, **kwargs: calls.append((worker, kwargs)))
    result = MeshDirectOutputResult("overlay_prepare", None, overlay_preparation=preparation)
    tab._handle_mesh_direct_output_completed(
        tab.standalone_output_request_id, result, mutation_service=mutation_service,
    )
    assert len(prompts) == 1
    assert len(calls) == int(confirm and not busy)
    assert tab.standalone_pending_overlay_apply == ((preparation, mutation_service) if confirm and busy else None)
    tab.standalone_pending_overlay_apply = None
