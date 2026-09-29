"""Finish's validated cloth edit must reach every Build Mod package through the UI."""

from __future__ import annotations

import json
import time
from dataclasses import replace

import pytest
from PySide6.QtWidgets import QApplication, QMessageBox, QPushButton

from cdmw.core.archive_extraction import read_archive_entry_data
from cdmw.core.archive_format import parse_archive_pamt
from cdmw.core.papgt_format import PAPGT_DEFAULT_FLAGS, PapgtDirectory, serialize_papgt
from cdmw.domain.mesh.cloth import PacClothRule
from cdmw.modding.pac_cloth import apply_pac_cloth_rules
from cdmw.models import ArchiveEntry
from cdmw.ui.mesh_editor.controller import MeshEditorController
from cdmw.ui.mesh_editor.mod_export_dialog import MeshModExportDialog
from cdmw.workers.mesh_rust_editor_workers import MeshRustProtocolWorker
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
        ("dmm_loose", "dmm", "dmm", "modinfo.json", ""),
        ("jmm_loose", "jmm", "jmm", "mod.json", ""),
        ("cdumm_loose", "cdumm", "cdumm", "modinfo.json", "files"),
        ("crimson_sharp_loose", "crimson_sharp", "crimson-sharp", "mod.json", "files"),
        ("dmm_archive", "dmm", "dmm-archive", "modinfo.json", ""),
    ],
)
def test_finish_then_build_exports_cloth_edit_for_every_manager(
    accepted_cloth_edit, tmp_path, monkeypatch, choice, profile, suffix, descriptor, wrapper,
):
    tab, service, session, entry, source = accepted_cloth_edit
    accepted_revision = service.session_view(session.authoritative_session_id).revision
    assert tab._standalone_export_validation_ok()
    assert tab.standalone_export_validation_revision == accepted_revision
    assert tab.standalone_last_export_validation_report is session.accepted_export_validation[1]
    chosen = []
    mount = None
    if choice == "dmm_archive":
        mount = serialize_papgt([PapgtDirectory("0009", PAPGT_DEFAULT_FLAGS, 0)])
        (tmp_path / "meta").mkdir()
        (tmp_path / "meta/0.papgt").write_bytes(mount)

    def choose(dialog):
        assert isinstance(dialog, MeshModExportDialog)
        assert dialog.manager.count() == 5
        assert not dialog.build_button.isEnabled()
        index = next(i for i in range(dialog.manager.count()) if dialog.manager.itemData(i)[0] == choice)
        dialog.manager.setCurrentIndex(index)
        dialog.mod_name.setText("  Stiff Canta Cloak  ")
        dialog.output_parent.setText(str(tmp_path / "exports"))
        dialog.version.setText("2.3")
        dialog.author.setText("Mesh Tester")
        dialog.description.setText("Cloth physics removed.")
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
        assert (output / ".no_encrypt").is_file() == bool(wrapper)
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
    assert "Stiff Canta Cloak" in (output / "README.txt").read_text()
    assert entry.pamt_path.read_bytes() == b"owned source index"
    assert entry.paz_file.read_bytes() == source
    assert not list(output.parent.glob(".*.staging-*"))


@pytest.mark.parametrize("change", ["cancel", "revision", "target", "controller"])
def test_build_dialog_cannot_publish_cancelled_or_changed_session(accepted_cloth_edit, tmp_path, monkeypatch, change):
    tab, service, session, entry, _source = accepted_cloth_edit
    started = []

    def choose(dialog):
        dialog.output_parent.setText(str(tmp_path / "exports"))
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
