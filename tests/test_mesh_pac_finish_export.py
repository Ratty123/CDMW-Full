"""The Finish screen exports a validated PAC directly, without package companions."""

from pathlib import Path
from types import SimpleNamespace
import time

import pytest
from PySide6.QtWidgets import QApplication, QFileDialog, QMessageBox, QPushButton

from cdmw.domain.mesh.cloth import PacClothRule
from cdmw.modding.pac_cloth import apply_pac_cloth_rules
from tests.test_mesh_mod_finish_export import accepted_cloth_edit, cloth_session


def wait_for_export(tab):
    deadline = time.monotonic() + 15
    while tab.standalone_rebuild_report_thread is not None and time.monotonic() < deadline:
        QApplication.processEvents()
        time.sleep(.005)
    assert tab.standalone_rebuild_report_thread is None


@pytest.fixture
def finished_pac(accepted_cloth_edit, monkeypatch):
    tab, *_ = accepted_cloth_edit
    warnings = []
    monkeypatch.setattr(QMessageBox, "warning", lambda _parent, title, message: warnings.append((title, message)))
    try:
        yield (*accepted_cloth_edit, warnings)
    finally:
        if tab.standalone_rebuild_report_thread is not None:
            tab._cancel_standalone_rebuild_report_worker()
            wait_for_export(tab)


def export_button(tab):
    button = tab.standalone_native_host_frame.findChild(QPushButton, "MeshEditorRustResultExportPac")
    assert button is not None and button.isEnabled() and not button.isHidden()
    return button


def test_finish_exports_only_pac_overwrites_and_remembers_full_path(finished_pac, tmp_path, monkeypatch):
    tab, service, session, entry, source, warnings = finished_pac
    output = tmp_path / "exports" / "unused-slot.pac"
    output.parent.mkdir()
    output.write_bytes(b"previous export")
    defaults = []

    def choose(_parent, title, default, file_filter):
        assert title == "Export PAC As…" and file_filter == "PAC files (*.pac)"
        defaults.append(default)
        return str(output), file_filter

    monkeypatch.setattr(QFileDialog, "getSaveFileName", choose)
    for attempt in range(2):
        export_button(tab).click()
        worker = tab.standalone_rebuild_report_worker
        assert worker is not None and worker.pac_only
        assert worker.expected_mesh_revision == service.session_view(session.authoritative_session_id).revision
        wait_for_export(tab)
        assert not warnings
        assert output.read_bytes() == apply_pac_cloth_rules(source, {0: PacClothRule(0)})
        assert list(output.parent.iterdir()) == [output]
        assert tab.settings.value("mesh_editor/last_pac_export_path") == str(output)
        assert entry.paz_file.read_bytes() == source
        if attempt == 0:
            output.write_bytes(b"replace me again")
    assert defaults[1] == str(output)


@pytest.mark.parametrize("change", ["cancel", "revision", "extension"])
def test_cancel_or_changed_request_never_writes_or_remembers(finished_pac, tmp_path, monkeypatch, change):
    tab, service, session, _entry, _source, warnings = finished_pac
    output = tmp_path / ("new.txt" if change == "extension" else "new.pac")
    tab.settings.setValue("mesh_editor/last_pac_export_path", "previous.pac")

    def choose(*args):
        if change == "revision":
            service.undo(session.authoritative_session_id)
        return ("" if change == "cancel" else str(output)), ""

    monkeypatch.setattr(QFileDialog, "getSaveFileName", choose)
    export_button(tab).click()
    assert tab.standalone_rebuild_report_worker is None
    assert not output.exists()
    assert tab.settings.value("mesh_editor/last_pac_export_path") == "previous.pac"
    assert bool(warnings) == (change != "cancel")


@pytest.mark.parametrize("blocker", ["companions", "material", "texture", "refit", "hair", "format"])
def test_blockers_explain_build_mod_before_choosing_a_file(finished_pac, monkeypatch, blocker):
    tab, service, session, _entry, _source, warnings = finished_pac
    authoritative = service._session(session.authoritative_session_id)
    if blocker == "companions":
        authoritative.replacement_state = SimpleNamespace(companion_files=(object(),), parts=())
    elif blocker == "material":
        authoritative.material_generation = 1
    elif blocker == "texture":
        authoritative.committed_texture_resources = {("part", "diffuse"): object()}
    elif blocker == "refit":
        authoritative.archive_refit_context = object()
    elif blocker == "hair":
        authoritative.hair_state = object()
    else:
        authoritative.working_mesh.format = "pam"
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *args: pytest.fail("Blocked export opened a file picker"))
    export_button(tab).click()
    assert len(warnings) == 1
    assert (".pac destination" if blocker == "format" else "Build Mod") in warnings[0][1]
    assert tab.standalone_rebuild_report_worker is None


@pytest.mark.parametrize("failure", ["companion", "source", "publish", "cancel"])
def test_worker_refusals_and_interruption_preserve_existing_file(finished_pac, tmp_path, monkeypatch, failure):
    import cdmw.core.atomic_file as atomic
    import cdmw.workers.mesh_editor_workers as workers

    tab, service, session, _entry, source, warnings = finished_pac
    output = tmp_path / "exports" / "existing.pac"
    output.parent.mkdir()
    output.write_bytes(source)
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *args: (str(output), ""))
    if failure == "companion":
        rebuild = service.rebuild_result_from_snapshot

        def with_companions(*args, **kwargs):
            result, report = rebuild(*args, **kwargs)
            return SimpleNamespace(data=result.data, companion_files=(object(),)), report

        monkeypatch.setattr(service, "rebuild_result_from_snapshot", with_companions)
    elif failure == "source":
        authoritative = service._session(session.authoritative_session_id)
        authoritative.base_mesh.path = str(output)
        authoritative.working_mesh.path = str(output)
    elif failure == "publish":
        replace = atomic.os.replace

        def fail_publish(src, dst):
            if Path(dst) == output and ".rebuild-" in Path(src).parent.name:
                raise OSError("destination locked")
            return replace(src, dst)

        monkeypatch.setattr(atomic.os, "replace", fail_publish)
    else:
        write = workers.atomic_write_bytes

        def cancel_after_staging(path, data):
            write(path, data)
            tab.standalone_rebuild_report_worker.stop()

        monkeypatch.setattr(workers, "atomic_write_bytes", cancel_after_staging)
    export_button(tab).click()
    wait_for_export(tab)
    assert output.read_bytes() == source
    assert list(output.parent.iterdir()) == [output]
    assert not tab.settings.value("mesh_editor/last_pac_export_path", "")
    assert bool(warnings) == (failure != "cancel")
    if failure == "companion":
        assert "companion files" in warnings[0][1] and "Build Mod" in warnings[0][1]
