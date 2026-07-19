"""Window-facing integration for v2 and shadow archive catalogue modes."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Iterable

from PySide6.QtCore import QItemSelectionModel, QModelIndex, QObject, QTimer

from cdmw.domain.archives.catalogue import (
    ArchiveChildrenResult,
    ArchiveDurableIdentity,
    ArchiveEntryDto,
    ArchiveFacetsResult,
    ArchiveQueryHandle,
    ArchiveSessionHandle,
    ArchiveViewMode,
)
from cdmw.domain.archives.filters import archive_browser_sort_is_active
from cdmw.models import ArchiveEntry
from cdmw.ui.archive_browser.remote_controller import ArchiveRemoteCatalogueController
from cdmw.ui.archive_browser.remote_model import RemoteArchiveBrowserModel
from cdmw.ui.archive_browser.remote_query import archive_query_from_browser_state


@dataclass(frozen=True, slots=True)
class ArchiveShadowComparison:
    legacy_entry_count: int
    v2_entry_count: int
    legacy_match_count: int
    v2_match_count: int
    compared_rows: int
    identity_mismatches: tuple[tuple[int, tuple[object, ...], tuple[object, ...]], ...]

    @property
    def matches(self) -> bool:
        return (
            self.legacy_entry_count == self.v2_entry_count
            and self.legacy_match_count == self.v2_match_count
            and not self.identity_mismatches
        )


class ArchiveRemoteWindowBridge(QObject):
    """Adapt remote catalogue lifecycle signals to the existing window shell."""

    def __init__(self, window: object, *, display_v2: bool, shadow: bool) -> None:
        super().__init__(window)  # type: ignore[arg-type]
        self._window = window
        self._display_v2 = bool(display_v2)
        self._shadow = bool(shadow)
        self._activate_tab_on_publish = False
        self._last_open_root = ""
        self._shadow_schedule_generation = 0
        self._shadow_reason = ""
        self._structure_rows: dict[str, list[tuple[str, int]]] = {}
        self._structure_loaded: set[str] = set()
        self._structure_requests_enabled = False
        self._model = RemoteArchiveBrowserModel(parent=self)
        self._controller = ArchiveRemoteCatalogueController(
            window.archive_catalogue_service,
            self._model,
            parent=self,
        )
        self._controller.statusChanged.connect(self._handle_status)
        self._controller.progressChanged.connect(self._handle_progress)
        self._controller.queryPublished.connect(self._handle_query_published)
        self._controller.facetsReady.connect(self._handle_facets)
        self._controller.structureChildrenReady.connect(self._handle_structure_children)
        self._controller.selectionIndexReady.connect(self._restore_selection)
        self._controller.selectionUnavailable.connect(self._selection_unavailable)
        self._controller.requestFailed.connect(self._handle_failure)
        self._controller.actionsSafeChanged.connect(self._handle_actions_safe)
        if self._display_v2:
            window.archive_tree.use_remote_model(self._model)

    @property
    def model(self) -> RemoteArchiveBrowserModel:
        return self._model

    @property
    def controller(self) -> ArchiveRemoteCatalogueController:
        return self._controller

    @property
    def displays_v2(self) -> bool:
        return self._display_v2

    @property
    def shadows_legacy(self) -> bool:
        return self._shadow

    @property
    def structure_requests_ready(self) -> bool:
        return self._display_v2 and self._structure_requests_enabled

    def open_archive(
        self,
        package_root: Path | str,
        *,
        force_refresh: bool,
        activate_tab: bool,
    ) -> None:
        self._last_open_root = str(Path(package_root))
        self._activate_tab_on_publish = bool(activate_tab)
        if self._display_v2:
            self._structure_requests_enabled = False
            self._structure_rows.clear()
            self._structure_loaded.clear()
            self._window.archive_structure_filter_children = {}
            self._window.archive_structure_filter_state = "warming"
            self._window._rebuild_archive_structure_filter_controls(defer_missing_children=True)
        state = self._window._capture_archive_filter_state()
        query = archive_query_from_browser_state("", state)
        self._begin_pending("Refreshing archive catalogue..." if force_refresh else "Loading archive catalogue...")
        self._controller.open_archive(
            package_root,
            query=query,
            force_refresh=force_refresh,
            selection_identity=self.current_selection_identity(),
        )

    def start_shadow(self, package_root: Path | str) -> None:
        if not self._shadow:
            return
        self._last_open_root = str(Path(package_root))
        state = self._window._capture_archive_filter_state()
        query = replace(
            archive_query_from_browser_state("", state),
            view_mode=ArchiveViewMode.FLAT,
        )
        self._window.append_archive_log("Archive backend shadow comparison started.", verbose=True)
        self._controller.open_archive(package_root, query=query, force_refresh=False)

    def schedule_shadow_comparison(self, reason: str, *, delay_ms: int = 0) -> None:
        if not self._shadow:
            return
        self._shadow_schedule_generation += 1
        generation = self._shadow_schedule_generation
        self._shadow_reason = str(reason or "legacy_update")
        QTimer.singleShot(
            max(0, int(delay_ms)),
            lambda generation=generation: self._run_scheduled_shadow_comparison(generation, 0),
        )

    def _run_scheduled_shadow_comparison(self, generation: int, attempt: int) -> None:
        if generation != self._shadow_schedule_generation or not self._shadow:
            return
        window = self._window
        waiting = bool(
            getattr(window, "_shutting_down", False)
            or getattr(window, "worker_thread", None) is not None
            or getattr(window, "archive_scan_finalize_pending", False)
            or getattr(window, "archive_filters_dirty", False)
            or getattr(window, "archive_startup_saved_filter_apply_pending", False)
        )
        if waiting:
            if getattr(window, "_shutting_down", False):
                return
            if attempt < 100:
                QTimer.singleShot(
                    100,
                    lambda generation=generation, attempt=attempt + 1: self._run_scheduled_shadow_comparison(
                        generation,
                        attempt,
                    ),
                )
            else:
                window.append_archive_log(
                    f"Archive backend shadow comparison skipped after waiting for {self._shadow_reason} to settle.",
                    verbose=True,
                )
            return
        package_root = str(window.archive_package_root_edit.text() or "").strip()
        if not package_root or not window.archive_entries:
            return
        self.start_shadow(package_root)

    def apply_current_query(self) -> None:
        session = self._controller.current_session
        if session is None:
            package_root = str(self._window.archive_package_root_edit.text() or "").strip()
            if package_root:
                self.open_archive(package_root, force_refresh=False, activate_tab=True)
            return
        state = self._window._capture_archive_filter_state()
        query = archive_query_from_browser_state(session.session_id, state)
        self._begin_pending("Applying archive filters...")
        self._controller.apply_query(
            query,
            selection_identity=self.current_selection_identity(),
        )

    def current_selection_identity(self) -> ArchiveDurableIdentity | None:
        if self._display_v2:
            dto = self._model.entry_for_index(self._window.archive_tree.currentIndex())
            return None if dto is None else dto.identity
        entry = self._window._current_archive_entry()
        return _legacy_identity(entry)

    def current_compatibility_entry(self) -> ArchiveEntry | None:
        return self._controller.compatibility_entry_for_index(self._window.archive_tree.currentIndex())

    def compatibility_entry_for_index(self, index: QModelIndex) -> ArchiveEntry | None:
        return self._controller.compatibility_entry_for_index(index)

    def selected_compatibility_entries(self, *, limit: int = 512) -> list[ArchiveEntry]:
        selection_model = self._window.archive_tree.selectionModel()
        if selection_model is None:
            return []
        entries: list[ArchiveEntry] = []
        seen: set[int] = set()
        for index in selection_model.selectedRows(0):
            dto = self._model.entry_for_index(index)
            if dto is None or dto.entry_id in seen:
                continue
            entries.append(self._window.archive_catalogue_service.compatibility_entry(dto))
            seen.add(dto.entry_id)
            if len(entries) >= max(1, int(limit)):
                break
        return entries

    def request_structure_children(self, parent_path: str = "") -> None:
        if not self.structure_requests_ready or self._controller.current_session is None:
            return
        parent = _normalized(parent_path)
        if parent in self._structure_loaded:
            return
        self._window.archive_structure_filter_state = "warming"
        self._controller.request_structure_children(parent)

    def _begin_pending(self, text: str) -> None:
        if self._shadow:
            return
        window = self._window
        window.archive_remote_query_pending = True
        window._update_archive_filter_button_state()
        window._set_archive_load_progress(text, phase="Catalogue")
        window._set_archive_warmup_overlay(
            True,
            "Preparing Archive Browser",
            "The standalone archive worker is validating the cache and preparing the first bounded page.",
        )
        window.set_status_message(text)
        window.append_archive_log(text)
        window.set_busy(True, build_mode=False)

    def _handle_status(self, message: str) -> None:
        if self._shadow:
            self._window.append_archive_log(f"Archive v2 shadow: {message}", verbose=True)
        else:
            self._window.set_status_message(message)

    def _handle_progress(self, kind: str, update: object) -> None:
        if self._shadow:
            return
        current = int(getattr(update, "current", 0) or 0)
        total = int(getattr(update, "total", 0) or 0)
        detail = str(getattr(update, "detail", kind) or kind)
        self._window._handle_archive_scan_progress(current, total, detail)

    def _handle_query_published(self, handle: ArchiveQueryHandle) -> None:
        if self._shadow:
            self._record_shadow_comparison(handle)
            return
        window = self._window
        window.archive_remote_query_pending = False
        window.archive_remote_total_matches = handle.total_matches
        window.archive_filters_dirty = False
        window.archive_result_filter_signature = window._current_archive_filter_signature()
        window.archive_tree.use_remote_model(self._model)
        window.archive_tree.setRootIsDecorated(self._model.view_mode.value != "flat")
        window.archive_tree.setEnabled(True)
        window._update_archive_filter_button_state()
        completion = f"Archive catalogue ready. Showing {handle.total_matches:,} entries."
        window._set_archive_list_status(completion)
        window._set_archive_warmup_overlay(False)
        window._set_archive_load_progress(completion, phase="Ready", percent=100)
        window.set_status_message(completion)
        window.append_archive_log(completion)
        if self._activate_tab_on_publish:
            window._activate_tool_widget(window.archive_browser_tab)
        self._activate_tab_on_publish = False
        window.set_busy(False, build_mode=False)
        window._write_heartbeat("running")
        window._release_startup_splash()
        self._structure_requests_enabled = True
        self.request_structure_children("")
        QTimer.singleShot(0, self._select_first_row_if_needed)

    def _handle_facets(self, facets: ArchiveFacetsResult) -> None:
        if self._shadow:
            return
        window = self._window
        window.archive_extension_counts = Counter(
            {facet.key: int(facet.count) for facet in facets.extensions if facet.key}
        )
        window.archive_filtered_dds_count = next(
            (int(facet.count) for facet in facets.extensions if facet.key.casefold() == ".dds"),
            0,
        )
        window._rebuild_archive_extension_filter_choices()

    def _handle_structure_children(self, parent_path: str, result: ArchiveChildrenResult) -> None:
        if not self._display_v2:
            return
        parent = _normalized(parent_path)
        rows = self._structure_rows.setdefault(parent, [])
        if result.offset == 0:
            rows.clear()
        folder_nodes = [child for child in result.children if child.is_folder]
        rows.extend((_normalized(child.key), int(child.match_count)) for child in folder_nodes)
        if (
            result.next_offset is not None
            and result.children
            and len(folder_nodes) == len(result.children)
        ):
            self._controller.request_structure_children(parent, offset=result.next_offset)
            return
        self._structure_loaded.add(parent)
        self._window.archive_structure_filter_children[parent] = sorted(
            dict(rows).items(),
            key=lambda item: _structure_sort_key(item[0]),
        )
        self._window.archive_structure_filter_state = "ready"
        selected = self._window._current_archive_structure_filter_value()
        self._window._rebuild_archive_structure_filter_controls(
            selected or self._window.archive_structure_filter_pending_value,
            defer_missing_children=True,
        )

    def _restore_selection(self, index: QModelIndex) -> None:
        if self._shadow or not index.isValid():
            return
        selection_model = self._window.archive_tree.selectionModel()
        if selection_model is None:
            return
        self._window.archive_tree.setCurrentIndex(index)
        selection_model.select(index, QItemSelectionModel.ClearAndSelect | QItemSelectionModel.Rows)
        self._window.archive_tree.scrollTo(index)

    def _selection_unavailable(self, _identity: object) -> None:
        if not self._shadow:
            QTimer.singleShot(0, self._select_first_row_if_needed)

    def _select_first_row_if_needed(self) -> None:
        if not self._display_v2 or self._window.archive_tree.currentIndex().isValid():
            return
        first = self._model.index(0, 0)
        if first.isValid() and self._model.entry_for_index(first) is not None:
            self._restore_selection(first)

    def _handle_failure(self, kind: str, error: object) -> None:
        detail = str(error)
        if kind.startswith("structure_"):
            if self._display_v2:
                self._window.archive_structure_filter_state = "failed"
                self._window.append_archive_log(
                    f"Warning: archive folder filters could not be loaded from the worker: {detail}"
                )
                self._window._rebuild_archive_structure_filter_controls(defer_missing_children=True)
            return
        if self._shadow:
            self._window.append_archive_log(
                f"Archive v2 shadow comparison failed ({kind}): {detail}",
                verbose=True,
            )
            self._record_runtime("archive_backend_shadow_failed", operation=kind, error=detail)
            return
        window = self._window
        window.archive_remote_query_pending = False
        window._update_archive_filter_button_state()
        window._set_archive_warmup_overlay(False)
        window.set_busy(False, build_mode=False)
        message = f"Archive backend v2 failed during {kind}: {detail}"
        window.set_status_message(message)
        window.append_archive_log(message)
        self._record_runtime("archive_backend_v2_failed", operation=kind, error=detail)

    def _handle_actions_safe(self, safe: bool) -> None:
        if not self._shadow:
            self._window.archive_remote_actions_safe = bool(safe)
        self._record_runtime("archive_backend_actions_safe", safe=bool(safe))

    def _record_shadow_comparison(self, handle: ArchiveQueryHandle) -> None:
        session = self._controller.current_session
        if session is None:
            return
        legacy_filtered_entries = self._window.archive_filtered_entries
        if not archive_browser_sort_is_active(self._window.archive_tree_sort_column):
            legacy_filtered_entries = sorted(
                legacy_filtered_entries,
                key=_base_index_identity_key,
            )
        comparison = compare_archive_shadow_page(
            self._window.archive_entries,
            legacy_filtered_entries,
            self._model,
            session,
            handle,
        )
        status = "match" if comparison.matches else "mismatch"
        self._window.append_archive_log(
            "Archive backend shadow comparison "
            f"{status}: entries legacy={comparison.legacy_entry_count:,} v2={comparison.v2_entry_count:,}; "
            f"matches legacy={comparison.legacy_match_count:,} v2={comparison.v2_match_count:,}; "
            f"page mismatches={len(comparison.identity_mismatches):,}.",
            verbose=True,
        )
        self._record_runtime(
            "archive_backend_shadow_comparison",
            reason=self._shadow_reason,
            matches=comparison.matches,
            legacy_entry_count=comparison.legacy_entry_count,
            v2_entry_count=comparison.v2_entry_count,
            legacy_match_count=comparison.legacy_match_count,
            v2_match_count=comparison.v2_match_count,
            compared_rows=comparison.compared_rows,
            identity_mismatch_count=len(comparison.identity_mismatches),
            identity_mismatches=comparison.identity_mismatches,
        )

    def _record_runtime(self, event: str, **fields: object) -> None:
        recorder = getattr(self._window, "_record_runtime_event", None)
        if callable(recorder):
            recorder(event, **fields)


def compare_archive_shadow_page(
    legacy_entries: Iterable[ArchiveEntry],
    legacy_filtered_entries: Iterable[ArchiveEntry],
    model: RemoteArchiveBrowserModel,
    session: ArchiveSessionHandle,
    handle: ArchiveQueryHandle,
    *,
    row_limit: int = 256,
) -> ArchiveShadowComparison:
    legacy_all = legacy_entries if isinstance(legacy_entries, list) else list(legacy_entries)
    legacy_filtered = (
        legacy_filtered_entries
        if isinstance(legacy_filtered_entries, list)
        else list(legacy_filtered_entries)
    )
    compared = min(max(0, int(row_limit)), len(legacy_filtered), handle.total_matches)
    mismatches: list[tuple[int, tuple[object, ...], tuple[object, ...]]] = []
    for row in range(compared):
        dto = model.entry_for_index(model.index(row, 0))
        if dto is None:
            mismatches.append((row, _legacy_identity_key(legacy_filtered[row]), ("missing",)))
            continue
        legacy_key = _legacy_identity_key(legacy_filtered[row])
        remote_key = _dto_identity_key(dto)
        if legacy_key != remote_key:
            mismatches.append((row, legacy_key, remote_key))
            if len(mismatches) >= 16:
                break
    return ArchiveShadowComparison(
        len(legacy_all),
        session.entry_count,
        len(legacy_filtered),
        handle.total_matches,
        compared,
        tuple(mismatches),
    )


def _legacy_identity(entry: ArchiveEntry | None) -> ArchiveDurableIdentity | None:
    if entry is None:
        return None
    identity = entry.identity
    return ArchiveDurableIdentity(
        identity.normalized_path,
        identity.source_pamt,
        identity.paz_index,
        identity.entry_offset,
    )


def _legacy_identity_key(entry: ArchiveEntry) -> tuple[object, ...]:
    identity = entry.identity
    return (
        _normalized(identity.normalized_path),
        _normalized(identity.source_pamt),
        int(identity.paz_index),
        int(identity.entry_offset),
    )


def _base_index_identity_key(entry: ArchiveEntry) -> tuple[object, ...]:
    identity = entry.identity
    return (
        _normalized(identity.normalized_path),
        str(identity.source_pamt).replace("\\", "/"),
        int(identity.entry_offset),
    )


def _dto_identity_key(entry: ArchiveEntryDto) -> tuple[object, ...]:
    identity = entry.identity
    return (
        _normalized(identity.normalized_path),
        _normalized(identity.source_pamt),
        int(identity.paz_index),
        int(identity.archive_offset),
    )


def _normalized(value: object) -> str:
    return str(value or "").replace("\\", "/").strip("/").casefold()


def _structure_sort_key(value: str) -> tuple[int, int, str]:
    leaf = value.rsplit("/", 1)[-1]
    return (0, int(leaf), leaf) if leaf.isdigit() else (1, 0, leaf)


__all__ = [
    "ArchiveRemoteWindowBridge",
    "ArchiveShadowComparison",
    "compare_archive_shadow_page",
]
