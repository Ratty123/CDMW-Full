"""Mounted barber icon precedence, decoding, and page lifetime."""
from dataclasses import replace
from pathlib import Path
import threading
from types import SimpleNamespace

import pytest
from PySide6.QtCore import Signal, Qt
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication

from cdmw.domain.archives.catalogue import ArchiveLookupKind, ArchiveLookupResult
from cdmw.ui.mesh_editor.hair_icon_preparation import HairIconPreparation
from cdmw.ui.mesh_editor.hair_reference_picker import HairReferencePickerDialog
from cdmw.workers import hair_catalogue_icons as worker
from tests.test_archive_remote_preview_dependencies import _dto
from tests.test_character_finder_dialog import Service, row, detail
from tests.test_hair_workflow import owner
from tests.test_mesh_hair_authoring import dds


ICON = "ui/texture/image/customizeimage/barber_hair.dds"


class IconService(Service):
    batch_ready = Signal(str, str, object)
    request_cancelled = Signal(str)

    def resolve_entries(self, request, **kwargs):
        return self._call("icons", request, **kwargs)


def test_icon_lookup_retains_streamed_active_override_and_rejects_stale_work(owner, monkeypatch):
    service = owner.archive_catalogue_service = IconService()
    tasks, ready = [], []
    owner._run_utility_task_when_idle = lambda **kwargs: tasks.append(kwargs)
    preparation = HairIconPreparation(owner)
    decoded = []
    def decode(entries, stop):
        decoded.extend(entries)
        return {ICON: QImage(4, 4, QImage.Format_RGBA8888)}
    monkeypatch.setattr(worker, "prepare_hair_icons", decode)
    preparation.ready.connect(lambda *args: ready.append(args))
    preparation.start("session-a", (ICON,), 3)
    token, request, _ = service.calls[-1]
    assert request.kind is ArchiveLookupKind.EXACT_PATHS and request.values == (ICON,)
    shadowed = replace(_dto(1, ICON), override_state="Shadowed original")
    active = replace(_dto(2, ICON), is_active_override=True, override_state="Active mod")
    service.batch_ready.emit(token, "resolve_entries", ArchiveLookupResult("session-a", (shadowed, active), 2, False))
    service.result_ready.emit(token, "resolve_entries", ArchiveLookupResult("session-a", (), 2, False))
    assert len(tasks) == 1 and not ready
    # The first decode can finish after the user changes page; it cannot publish.
    preparation.start("session-a", (ICON,), 4)
    tasks[0]["on_complete"]({ICON: QImage(4, 4, QImage.Format_RGBA8888)})
    assert not ready
    token = service.calls[-1][0]
    service.result_ready.emit(token, "resolve_entries", ArchiveLookupResult("session-a", (active,), 1, False))
    images = tasks[-1]["task"](lambda _: None)
    assert len(decoded) == 1 and decoded[0].offset == active.offset
    tasks[-1]["on_complete"](images)
    assert ready == [(4, images)]
    preparation.cancel()


@pytest.mark.parametrize("kind", ["missing", "ambiguous", "truncated", "oversized", "cancelled"])
def test_unusable_icon_lookup_falls_back_without_preparing_assets(owner, kind):
    service = owner.archive_catalogue_service = IconService()
    tasks, ready = [], []
    owner._run_utility_task_when_idle = lambda **kwargs: tasks.append(kwargs)
    preparation = HairIconPreparation(owner)
    preparation.ready.connect(lambda *args: ready.append(args))
    preparation.start("session-a", (ICON,), 1)
    token = service.calls[-1][0]
    values = (_dto(1, ICON),)
    if kind == "missing": values = ()
    if kind == "ambiguous": values += (_dto(2, ICON),)
    if kind == "oversized": values = (replace(values[0], original_size=3 * 1024 * 1024),)
    if kind == "cancelled":
        service.request_cancelled.emit(token)
    else:
        service.result_ready.emit(token, "resolve_entries", ArchiveLookupResult("session-a", values, len(values), kind == "truncated"))
    assert not tasks and ready == [(1, {})]
    preparation.cancel()


def test_icon_worker_preserves_alpha_limits_decode_and_obeys_cancellation(tmp_path, monkeypatch):
    data = dds()
    entry = SimpleNamespace(orig_size=len(data), path=ICON)
    reads, jobs = [], []
    def read(value, stop):
        reads.append(value)
        return data, ""
    def decode(values, **kwargs):
        jobs.extend(values)
        output = tmp_path / "icon.png"
        image = QImage(256, 256, QImage.Format_RGBA8888)
        image.fill(Qt.transparent)
        image.setPixelColor(128, 128, Qt.red)
        assert image.save(str(output))
        assert Path(values[0]["dds_path"]).read_bytes() == data
        return {values[0]["dds_path"]: output}
    monkeypatch.setattr(worker, "read_archive_entry_data", read)
    monkeypatch.setattr(worker, "ensure_directxtex_dds_preview_pngs", decode)
    result = worker.prepare_hair_icons((entry, SimpleNamespace(orig_size=3*1024*1024, path=ICON)), threading.Event())
    assert reads == [entry] and len(jobs) == 1
    assert result[ICON].width() == 140 and result[ICON].hasAlphaChannel()
    assert result[ICON].pixelColor(0, 0).alpha() == 0
    assert not Path(jobs[0]["dds_path"]).exists()  # Temporary DDS is released.
    stopped = threading.Event(); stopped.set()
    with pytest.raises(RuntimeError, match="cancelled"):
        worker.prepare_hair_icons((entry,), stopped)
    assert reads == [entry]


def test_registered_icon_replaces_grid_rendering_and_keeps_selected_3d_preview(owner):
    service = owner.archive_catalogue_service = IconService()
    from cdmw.domain.archives.catalogue import ArchiveSessionHandle
    service.current_session = ArchiveSessionHandle("session-a", "C:/game", "fp", 10, 3, True)
    tasks = []
    owner._run_utility_task_when_idle = lambda **kwargs: tasks.append(kwargs)
    second_icon = ICON.replace("barber_hair", "barber_second")
    dialog = HairReferencePickerDialog(owner, "hair", styles=((0, "style"), (1, "second")),
        icons={"style": ICON, "second": second_icon})
    QApplication.processEvents()
    icon_token = next(token for token, _, _ in service.calls if token.startswith("icons"))
    token, request, _ = next(call for call in service.calls if call[0].startswith("detail"))
    selected = row(key=request.key, path=request.key.removeprefix("asset:"))
    service.result_ready.emit(token, "get_character_catalog_detail", detail(selected))
    second_token, second_request, _ = next(call for call in service.calls
        if call[0].startswith("detail") and call[0] != token)
    second_row = row(2, key=second_request.key, path=second_request.key.removeprefix("asset:"))
    service.result_ready.emit(second_token, "get_character_catalog_detail", detail(second_row))
    assert dialog._preview.visible_rows == (dialog._rows[selected.key],) and dialog._preview.selected
    service.result_ready.emit(icon_token, "resolve_entries",
        ArchiveLookupResult("session-a", (_dto(1, ICON), _dto(2, second_icon)), 2, False))
    image = QImage(4, 4, QImage.Format_RGBA8888); image.fill(Qt.red)
    tasks[0]["on_complete"]({ICON: image, second_icon: image})
    assert all(not dialog.grid.item(i).icon().isNull() for i in range(2))
    assert dialog._preview.visible_rows == (dialog._rows[selected.key],)
    dialog._search()
    dialog._registered_icons(dialog._generation - 1, {ICON: image})
    assert not dialog._icon_images
    dialog._registered_icons(dialog._generation, {})
    assert not dialog._pending_icon_keys  # Missing icons allow rendered thumbnails.
    token, request, _ = next(call for call in reversed(service.calls)
        if call[0].startswith("detail") and call[1].key == selected.key)
    service.result_ready.emit(token, "get_character_catalog_detail", detail(selected))
    assert dialog._preview.visible_rows == (dialog._rows[selected.key],)
    dialog.reject()
