from __future__ import annotations

import os
import threading
import time
import inspect
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QEventLoop, QObject, QThread, QTimer, Qt, Signal, Slot
from PySide6.QtWidgets import QApplication
from shiboken6 import isValid as qt_wrapper_is_valid

from cdmw.models import ArchiveEntry, ArchiveEntryIdentity, RunCancelled
from cdmw.ui.archive_browser.controller import ArchiveBrowserRowPayloadMixin
from cdmw.ui.archive_browser.mesh_modify_original import ArchiveMeshModifyOriginalMixin
from cdmw.ui.archive_browser.scan_lifecycle import ArchiveScanLifecycleMixin
from cdmw.ui.archive_browser.virtual_path_lookup import ArchiveVirtualPathLookupMixin
from cdmw.domain.archives.lightweight_lookup import build_archive_lightweight_lookup_indexes


_APP = QApplication.instance() or QApplication([])


class _IndexEntry:
    __slots__ = ("path", "extension", "pamt_path", "offset", "paz_index")

    def __init__(self, path: str, extension: str, offset: int) -> None:
        self.path = path
        self.extension = extension
        self.pamt_path = Path("0009/0.pamt")
        self.offset = offset
        self.paz_index = 0

    @property
    def identity(self) -> ArchiveEntryIdentity:
        return ArchiveEntryIdentity(
            self.path.casefold(),
            str(self.pamt_path).replace("\\", "/").casefold(),
            self.paz_index,
            self.offset,
        )


def test_lightweight_indexes_keep_500k_entry_work_off_heartbeat_thread() -> None:
    entries = [_IndexEntry(f"object/model/{index}.bin", ".bin", index) for index in range(499_998)]
    pam = _IndexEntry("character/model/body.pam", ".pam", 499_998)
    pamlod = _IndexEntry("character/model/body.pamlod", ".pamlod", 499_999)
    entries.extend((pam, pamlod))
    result: list[object] = []
    failure: list[BaseException] = []

    def build() -> None:
        try:
            result.append(build_archive_lightweight_lookup_indexes(entries))  # type: ignore[arg-type]
        except BaseException as exc:
            failure.append(exc)

    worker = threading.Thread(target=build)
    worker.start()
    heartbeat_gaps: list[float] = []
    previous = time.perf_counter()
    while worker.is_alive():
        time.sleep(0.005)
        current = time.perf_counter()
        heartbeat_gaps.append(current - previous)
        previous = current
    worker.join()

    assert not failure
    extension_index, extension_counts, mesh_path_index, companion_index = result[0]  # type: ignore[misc]
    assert extension_counts[".bin"] == 499_998
    assert mesh_path_index["character/model/body.pam"] == [pam]
    assert companion_index[pam.identity] is pamlod
    assert companion_index[pamlod.identity] is pam
    assert max(heartbeat_gaps, default=0.0) < 0.2
    assert len(extension_index[".bin"]) == 499_998


def test_lightweight_index_build_honors_cancellation() -> None:
    stop_event = threading.Event()
    stop_event.set()
    with pytest.raises(RunCancelled):
        build_archive_lightweight_lookup_indexes(
            [_IndexEntry("character/model/body.pam", ".pam", 1)],  # type: ignore[list-item]
            stop_event=stop_event,
        )










def test_mesh_lookup_and_companion_use_bounded_entry_adapters() -> None:
    pam = ArchiveEntry("character/model/body.pam", Path("0009/0.pamt"), Path("0009/0.paz"), 1, 1, 1, 0, 0)
    pamlod = ArchiveEntry("character/model/body.pamlod", Path("0009/0.pamt"), Path("0009/0.paz"), 2, 1, 1, 0, 0)

    class Owner:
        _find_archive_entry_by_virtual_path = ArchiveVirtualPathLookupMixin._find_archive_entry_by_virtual_path
        _find_archive_preview_companion_entry = ArchiveBrowserRowPayloadMixin._find_archive_preview_companion_entry
        _normalize_archive_entry_path = staticmethod(ArchiveBrowserRowPayloadMixin._normalize_archive_entry_path)

        def __init__(self) -> None:
            self.shell = self
            self.archive = self
            self.textures = self
            self.archive_entries = [pam, pamlod]
            self.archive_entries_by_normalized_path = {}
            self.archive_mesh_entries_by_normalized_path = {
                pam.path.casefold(): [pam],
                pamlod.path.casefold(): [pamlod],
            }
            self.archive_mesh_companion_by_identity = {pam.identity: pamlod, pamlod.identity: pam}
            self.ensure_calls = 0

        def _archive_catalogue_lookup_pending(self) -> None:
            self.ensure_calls += 1

    owner = Owner()
    assert owner._find_archive_entry_by_virtual_path(pam.path) is pam
    assert owner._find_archive_preview_companion_entry(pam) is pamlod
    assert owner.ensure_calls == 0


def test_modify_original_supplemental_scan_is_bounded_and_cancellable(tmp_path: Path) -> None:
    referenced = tmp_path / "referenced_files"
    referenced.mkdir()
    wanted = referenced / "character" / "body.pac_xml"
    wanted.parent.mkdir()
    wanted.write_text("x", encoding="utf-8")
    (referenced / "ignore.bin").write_bytes(b"x")

    result = ArchiveMeshModifyOriginalMixin._modify_original_workspace_supplemental_files(tmp_path)
    assert result == (wanted,)

    stop_event = threading.Event()
    stop_event.set()
    with pytest.raises(RunCancelled):
        ArchiveMeshModifyOriginalMixin._modify_original_workspace_supplemental_files(
            tmp_path,
            stop_event=stop_event,
        )


def test_attachment_loose_recursive_scan_is_worker_owned() -> None:
    loose_source = Path("cdmw/ui/archive_browser/attachment_loose_files.py").read_text(encoding="utf-8")
    dialog_source = Path("cdmw/ui/archive_browser/attachment_placement_diff_dialog.py").read_text(encoding="utf-8")
    plan_source = Path("cdmw/ui/archive_browser/attachment_plan.py").read_text(encoding="utf-8")
    worker_source = Path("cdmw/workers/attachment_loose_workers.py").read_text(encoding="utf-8")
    assert 'files_root.rglob("*")' not in loose_source
    assert '.rglob("*")' not in dialog_source
    assert "prepare_attachment_loose_targets(" in plan_source
    assert "def prepare_attachment_loose_targets(" in worker_source
    assert "raise_if_cancelled(stop_event" in worker_source
