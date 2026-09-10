from __future__ import annotations

import time
from pathlib import Path
from unittest.mock import patch

from PySide6.QtGui import QImage
from PySide6.QtCore import QEventLoop, QObject, QTimer, Qt, Signal
from PySide6.QtWidgets import QApplication, QDialog, QLabel, QPushButton, QWidget

from cdmw.domain.archives.catalogue import (
    ArchiveDurableIdentity,
    ArchiveEntryDto,
    ArchiveEntryRole,
    ArchivePage,
    ArchiveQueryHandle,
    ArchiveSessionHandle,
    ArchiveSortField,
)
from cdmw.domain.archives.replace_from_archive import (
    ReplaceFromArchiveActionKind,
    ReplaceFromArchiveFileAction,
    ReplaceFromArchivePlan,
    ReplaceFromArchiveRequest,
)
from cdmw.models import ArchiveEntry
from cdmw.ui.archive_browser.workflow_dependencies import (
    ArchiveWorkflowDependencyContext,
)
from cdmw.ui.archive_browser.remote_preview_dependencies import ArchivePreviewDependencySet
from cdmw.ui.mesh_editor.replace_from_archive_dialog import (
    ReplaceFromArchivePickerDialog,
    ReplaceFromArchiveReviewDialog,
    _ArchivePreviewLane,
)
from tests.test_mesh_pac_topology_serializer import _pac_fixture


class _Catalogue(QObject):
    batch_ready = Signal(str, str, object)
    result_ready = Signal(str, str, object)
    request_failed = Signal(str, object)
    request_cancelled = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self.queries = []
        self.page_requests = []
        self.cancelled = []
        self._next = 0

    def _request_id(self, prefix: str) -> str:
        self._next += 1
        return f"{prefix}-{self._next}"

    def create_query(self, query, *, ui_generation: int) -> str:
        request_id = self._request_id("query")
        self.queries.append((request_id, query, ui_generation))
        return request_id

    def fetch_page(self, request, *, ui_generation: int) -> str:
        request_id = self._request_id("page")
        self.page_requests.append((request_id, request, ui_generation))
        return request_id

    def cancel(self, request_id: str) -> bool:
        self.cancelled.append(request_id)
        return True

    @staticmethod
    def compatibility_entry(dto: ArchiveEntryDto) -> ArchiveEntry:
        return ArchiveEntry(
            path=dto.path,
            pamt_path=Path(dto.source_pamt),
            paz_file=Path(dto.paz_file),
            offset=dto.offset,
            comp_size=dto.stored_size,
            orig_size=dto.original_size,
            flags=dto.flags,
            paz_index=dto.paz_index,
        )


def _entry(path: str, offset: int) -> ArchiveEntry:
    entry = ArchiveEntry(
        path=path,
        pamt_path=Path("0.pamt"),
        paz_file=Path("0.paz"),
        offset=offset,
        comp_size=4,
        orig_size=4,
        flags=0,
        paz_index=0,
    )
    entry.prepared_path = Path(__file__)
    return entry


def _dto(path: str, entry_id: int, offset: int) -> ArchiveEntryDto:
    return ArchiveEntryDto(
        session_id="session",
        entry_id=entry_id,
        identity=ArchiveDurableIdentity(path.casefold(), "0.pamt", 0, offset),
        path=path,
        source_pamt="0.pamt",
        paz_file="0.paz",
        paz_index=0,
        offset=offset,
        stored_size=4,
        original_size=4,
        flags=0,
        extension=Path(path).suffix.casefold(),
        package="0",
        role=ArchiveEntryRole.MODEL,
        category="model",
        is_previewable=True,
        known_name="Known item",
        exact_name="Exact item",
        override_state="base",
        type_display="Mesh",
    )


def _context(entry: ArchiveEntry) -> ArchiveWorkflowDependencyContext:
    return ArchiveWorkflowDependencyContext(
        selected_entry=entry,
        entries=(entry,),
        entries_by_normalized_path={entry.path.casefold(): (entry,)},
        entries_by_basename={entry.basename.casefold(): (entry,)},
        remote=True,
    )


def _session() -> ArchiveSessionHandle:
    return ArchiveSessionHandle("session", "archive", "fingerprint", 10, 2, True)


def test_picker_uses_remote_paging_global_sort_and_target_exclusion() -> None:
    app = QApplication.instance() or QApplication([])
    service = _Catalogue()
    target = _entry("character/model/target.pac", 1)
    with patch(
        "cdmw.ui.mesh_editor.replace_from_archive_dialog._ArchivePreviewLane.start"
    ):
        dialog = ReplaceFromArchivePickerDialog(
            service,  # type: ignore[arg-type]
            _session(),
            target_entry=target,
            target_dependencies=_context(target),
        )
        app.processEvents()
        query_request, query, generation = service.queries[-1]
        assert query.extensions == (".pac", ".pam", ".pamlod")
        assert query.exclude_text == target.path
        assert query.sort_field is ArchiveSortField.PATH

        handle = ArchiveQueryHandle("session", "query-handle", 7, 1)
        service.result_ready.emit(query_request, "create_query", handle)
        for _ in range(3):
            app.processEvents()
        assert dialog.status_label.text() == (
            "1 archive mesh entry matches. Rows load incrementally as you scroll."
        )
        assert service.page_requests
        page_request, fetch, page_generation = service.page_requests[-1]
        assert page_generation == generation

        source = _dto("character/model/source.pac", 2, 2)
        service.result_ready.emit(
            page_request,
            "fetch_page",
            ArchivePage("session", "query-handle", 7, 1, fetch.page_start, (source,)),
        )
        app.processEvents()
        assert dialog.model.entry_for_index(dialog.model.index(0, 0)) == source

        dialog._sort_requested(1)
        assert service.queries[-1][1].sort_field is ArchiveSortField.KNOWN_NAME
        assert service.queries[-1][1].sort_descending is False
        dialog._sort_requested(1)
        assert service.queries[-1][1].sort_descending is True
        dialog.reject()
        assert service.cancelled
        dialog.deleteLater()
        app.processEvents()


def test_character_picker_requires_an_explicit_identity_choice() -> None:
    app = QApplication.instance() or QApplication([])
    service = _Catalogue()
    target = _entry("character/model/1_pc/1_phm/body/target.pac", 1)
    source = _entry("character/model/1_pc/2_phw/body/source.pac", 2)
    with patch(
        "cdmw.ui.mesh_editor.replace_from_archive_dialog._ArchivePreviewLane.start"
    ):
        dialog = ReplaceFromArchivePickerDialog(
            service,  # type: ignore[arg-type]
            _session(),
            target_entry=target,
            target_dependencies=_context(target),
        )
        dialog.selected_entry = source
        dialog.selected_dependencies = _context(source)
        dialog._source_lane.settled = True
        dialog._update_character_mode_visibility(source)
        dialog._update_choose_state()
        assert dialog.character_mode_combo.isVisibleTo(dialog)
        assert not dialog.choose_button.isEnabled()
        dialog.character_mode_combo.setCurrentIndex(1)
        dialog._update_choose_state()
        assert dialog.choose_button.isEnabled()
        dialog.reject()
        dialog.deleteLater()
        app.processEvents()


def test_archive_refit_picker_selects_character_assets_without_replacement_identity_mode() -> None:
    app = QApplication.instance() or QApplication([])
    service = _Catalogue()
    target = _entry("character/model/1_pc/1_phm/body/target.pac", 1)
    source = _entry("character/model/1_pc/2_phw/body/source.pac", 2)
    with patch("cdmw.ui.mesh_editor.replace_from_archive_dialog._ArchivePreviewLane.start"):
        dialog = ReplaceFromArchivePickerDialog(
            service, _session(), target_entry=target, target_dependencies=_context(target), refit_role="armor",
        )
        app.processEvents()
        dialog.selected_entry = source
        dialog.selected_dependencies = _context(source)
        dialog._source_lane.settled = True
        dialog._update_character_mode_visibility(source)
        dialog._update_choose_state()
        assert dialog.windowTitle() == "Choose Refit Armor from Archive"
        assert dialog.choose_button.text() == "Load Armor"
        assert not dialog.character_mode_combo.isVisibleTo(dialog)
        assert dialog.choose_button.isEnabled()
        dialog._accept_current()
        assert dialog.result() == QDialog.Accepted
        assert dialog.selected_entry is source
        assert service.cancelled
        dialog.deleteLater()
        app.processEvents()


def test_review_uses_build_anyway_for_warnings_and_blocks_fatal_plans() -> None:
    app = QApplication.instance() or QApplication([])
    target = _entry("character/model/target.pac", 1)
    source = _entry("character/model/source.pac", 2)
    action = ReplaceFromArchiveFileAction(
        role="Model",
        kind=ReplaceFromArchiveActionKind.COPY,
        source_entry=source,
        target_entry=target,
    )
    warning_plan = ReplaceFromArchivePlan(
        ReplaceFromArchiveRequest(target, source),
        actions=(action,),
        warnings=("Placement could not be proven.",),
    )
    review = ReplaceFromArchiveReviewDialog(warning_plan)
    build_anyway = next(
        button
        for button in review.findChildren(QPushButton)
        if button.text() == "Build Anyway"
    )
    assert build_anyway.isEnabled()
    review.deleteLater()

    blocked_plan = ReplaceFromArchivePlan(
        ReplaceFromArchiveRequest(target, source),
        actions=(action,),
        blockers=("Unreadable model payload.",),
    )
    blocked = ReplaceFromArchiveReviewDialog(blocked_plan)
    build_mod = next(
        button
        for button in blocked.findChildren(QPushButton)
        if button.text() == "Build Mod"
    )
    assert not build_mod.isEnabled()
    blocked.deleteLater()
    app.processEvents()


def test_preview_lane_latest_wins_cancel_returns_immediately_and_tears_down(
    tmp_path: Path,
) -> None:
    app = QApplication.instance() or QApplication([])
    parent = QWidget()
    image = QLabel(parent)
    status = QLabel(parent)
    lane = _ArchivePreviewLane(image, status, parent)
    first = _entry("character/model/first.pac", 1)
    second = _entry("character/model/second.pac", 2)
    for entry in (first, second):
        prepared = tmp_path / entry.basename
        prepared.write_bytes(b"invalid-mesh")
        entry.prepared_path = prepared
        entry.comp_size = prepared.stat().st_size
        entry.orig_size = prepared.stat().st_size

    lane.start(first, _context(first))
    workers = [next(iter(lane._jobs.values()))[0]]
    lane.start(second, _context(second))
    workers.append(next(reversed(lane._jobs.values()))[0])
    returned_to_ui_thread: list[bool] = []

    def _record_worker_affinity() -> None:
        for worker in workers:
            try:
                returned_to_ui_thread.append(worker.thread() is app.thread())
            except RuntimeError:
                pass

    lane.idle.connect(_record_worker_affinity)
    started = time.perf_counter()
    lane.cancel()
    assert time.perf_counter() - started < 0.2

    if lane.has_live_workers:
        loop = QEventLoop()
        lane.idle.connect(loop.quit)
        QTimer.singleShot(2_000, loop.quit)
        loop.exec()
    assert not lane.has_live_workers
    assert returned_to_ui_thread
    assert all(returned_to_ui_thread)
    parent.deleteLater()
    app.processEvents()


def test_refit_picker_renders_both_prepared_pac_previews_without_a_renderer_package(tmp_path, monkeypatch):
    from tests.test_archive_mesh_comparison import _PreviewHost
    monkeypatch.setattr("cdmw.ui.mesh_editor.archive_mesh_comparison.RustPreviewHostFrame", _PreviewHost)
    app = QApplication.instance() or QApplication([])
    target = _entry("character/model/body.pac", 1)
    source = _entry("character/model/armor.pac", 2)
    source_bytes = _pac_fixture(skinned=True)
    for entry in (target, source):
        prepared = tmp_path / entry.basename
        prepared.write_bytes(source_bytes)
        entry.prepared_path = prepared
        entry.prepared_size = entry.orig_size = entry.comp_size = len(source_bytes)

    from cdmw.workers import archive_preview_workers
    build_preview = archive_preview_workers.build_archive_preview_result
    reads = []

    def track_reads(*args, **kwargs):
        reads.append(args)
        return build_preview(*args, **kwargs)

    monkeypatch.setattr(archive_preview_workers, "build_archive_preview_result", track_reads)

    dialog = ReplaceFromArchivePickerDialog(
        _Catalogue(), _session(), target_entry=target,
        target_dependencies=_context(target), refit_role="armor",
    )

    def wait_for_previews():
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            app.processEvents()
            if not dialog.has_live_preview_workers:
                break
            time.sleep(0.005)
        assert not dialog.has_live_preview_workers

    try:
        dialog.setAttribute(Qt.WA_DontShowOnScreen, True)
        dialog.show()
        app.processEvents()  # Start the real current-target preview worker.
        context = _context(source)
        dialog._dependencies_ready(
            dialog._selection_generation,
            ArchivePreviewDependencySet(
                "session", 2, context.entries, context.entries_by_normalized_path,
                context.entries_by_basename, 1, False,
            ),
        )
        wait_for_previews()
        for lane, label, status in (
            (dialog._target_lane, dialog._target_image, dialog._target_status),
            (dialog._source_lane, dialog._source_image, dialog._source_status),
        ):
            assert lane.settled
            assert isinstance(lane.image, QImage), label.text()
            assert not lane.image.isNull()
            assert not label.pixmap().isNull()
            assert "vertices" in status.text() and "faces" in status.text()
            # Check geometry pixels inside the image, away from its text and grid.
            image = lane.image
            background = image.pixel(0, 0)
            assert any(
                image.pixel(x, y) != background
                for x in range(image.width() // 3, image.width() * 2 // 3, 8)
                for y in range(image.height() // 3, image.height() * 2 // 3, 8)
            )
        comparison = dialog._comparison_preview
        assert dialog._content_splitter.orientation() == Qt.Horizontal
        assert dialog._content_splitter.widget(0).geometry().right() < comparison.geometry().left()
        assert dialog.search_edit.parent() is dialog.table.parent()
        assert comparison.viewport.height() > 320
        assert comparison.target_mode_combo.currentText() == "Solid"
        assert comparison.source_mode_combo.currentText() == "Wire"
        assert comparison.viewport.loads
        before_mode_change = comparison.viewport.loads[-1][0]
        read_count = len(reads)
        assert read_count == 2
        comparison.source_mode_combo.setCurrentIndex(0)
        wait_for_previews()
        assert comparison.viewport.loads[-1][0] != before_mode_change
        assert not comparison.viewport.loads[-1][1]["reset_view"]
        assert len(reads) == read_count  # View changes reuse the decoded meshes.
        before_resize = comparison.viewport.size()
        package_count = len(comparison.viewport.loads)
        dialog.resize(dialog.width() + 100, dialog.height() + 100)
        wait_for_previews()
        assert comparison.viewport.size() != before_resize
        assert len(comparison.viewport.loads) == package_count
        assert len(reads) == read_count
        assert dialog.choose_button.isEnabled()
        assert target.prepared_path.read_bytes() == source_bytes
        assert source.prepared_path.read_bytes() == source_bytes
    finally:
        dialog.reject()
        wait_for_previews()
        dialog.deleteLater()
        app.processEvents()
