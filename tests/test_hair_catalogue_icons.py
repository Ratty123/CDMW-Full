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
from tests.test_character_finder_dialog import Service
from tests.test_hair_workflow import owner
from tests.test_character_finder_dialog import row, detail
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
