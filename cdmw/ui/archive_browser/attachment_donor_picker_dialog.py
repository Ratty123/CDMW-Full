"""Archive attachment placement donor picker dialog."""

from __future__ import annotations

import os
import re
import time
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path, PurePosixPath
from typing import Dict, List, Optional, Tuple

from PySide6.QtCore import QSize, Qt, QThread, QTimer
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QComboBox,
    QDialog,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListView,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QSplitter,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from cdmw.constants import DEFAULT_UI_THEME
from cdmw.core.archive_modding import ARCHIVE_MESH_EXTENSIONS
from cdmw.models import ArchiveEntry, ArchivePreviewResult, ModelPreviewData
from cdmw.services.diagnostics_service import write_ui_breadcrumb
from cdmw.ui.archive_browser.attachment_donor_picker_helpers import (
    AttachmentDonorKey,
    attachment_donor_basename_query_variants,
    attachment_donor_candidate_score,
    attachment_donor_entry_key,
    attachment_donor_evidence,
    attachment_donor_haystack,
    attachment_donor_search_terms,
    attachment_donor_type,
    make_attachment_donor_candidate_item,
)
from cdmw.ui.archive_browser.static_preview_thumbnail import render_static_model_preview_pixmap
from cdmw.ui.shell.responsiveness_controller import expand_tree_columns_to_available_width
from cdmw.ui.themes import get_theme
from cdmw.workers.archive_preview_workers import ArchivePreviewWorker


class ArchiveAttachmentDonorPickerDialogMixin:
    """Placement-source picker for archive attachment workflows."""

    def _open_archive_attachment_donor_picker_dialog(
        self,
        parent: QWidget,
        target_entry: ArchiveEntry,
    ) -> Optional[ArchiveEntry]:
        if not isinstance(target_entry, ArchiveEntry):
            return None
        picker = QDialog(parent)
        picker.setWindowTitle(f"Choose Placement Source - {target_entry.basename}")
        picker.setWindowFlags(
            picker.windowFlags()
            | Qt.WindowMaximizeButtonHint
            | Qt.WindowMinimizeButtonHint
        )
        picker.setSizeGripEnabled(True)
        picker.resize(1180, 720)
        layout = QVBoxLayout(picker)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)
        intro = QLabel(
            "Choose the weapon/model that supplies placement values only. The opened target keeps its own model, textures, icon, prefab, and physics. "
            "Pick the visible .pac when possible; CDMW resolves the matching placement evidence before showing the package plan."
        )
        intro.setObjectName("HintLabel")
        intro.setWordWrap(True)
        layout.addWidget(intro)
        target_label = QLabel(f"Target to change: {target_entry.path}")
        target_label.setObjectName("HintLabel")
        target_label.setWordWrap(True)
        target_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(target_label)
        search_row = QHBoxLayout()
        search_edit = QLineEdit()
        search_edit.setPlaceholderText("Type placement-source weapon/model name, folder, or id (example: cd_phm_02_sword)")
        search_button = QPushButton("Search Index")
        item_finder_button = QPushButton("Pick From Item Finder...")
        item_finder_button.setToolTip(
            "Open the visual Item Finder, choose an item by icon/name, then pick one of its resolved model/placement files as the placement source."
        )
        item_finder_button.setEnabled(bool(self.archive_item_asset_catalog))
        loose_folder_button = QPushButton("Add Loose Donor Folder...")
        loose_folder_button.setToolTip(
            "Pick a loose mod folder. CDMW maps any .pac/.prefab/.hkx/socket files back to archive entries by basename."
        )
        search_row.addWidget(search_edit, 1)
        search_row.addWidget(search_button)
        search_row.addWidget(item_finder_button)
        search_row.addWidget(loose_folder_button)
        layout.addLayout(search_row)
        guidance = QLabel(
            "Direction example: if this target is 2H and you choose a 1H source, the 2H target is built to use the 1H placement. "
            "Recommended pick: .pac model. Direct placement pick: .prefab. HKX is only physics context, but it can still work when the family resolves. "
            "The comparison step verifies the source placement values; source mesh, textures, icon, and physics stay out unless explicitly enabled in advanced legacy options."
        )
        guidance.setObjectName("HintLabel")
        guidance.setWordWrap(True)
        layout.addWidget(guidance)
        tree = QTreeWidget()
        tree.setColumnCount(5)
        tree.setHeaderLabels(["Placement Source Pick", "What It Means", "Placement Evidence", "Resolved Archive Path", "Index Source"])
        tree.setRootIsDecorated(False)
        tree.setAlternatingRowColors(True)
        tree.setUniformRowHeights(True)
        tree.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        tree.setEditTriggers(QAbstractItemView.NoEditTriggers)
        tree.header().setStretchLastSection(False)
        tree.header().resizeSection(0, 230)
        tree.header().resizeSection(1, 190)
        tree.header().resizeSection(2, 250)
        tree.header().resizeSection(3, 390)
        tree.header().resizeSection(4, 180)
        placement_source_splitter = QSplitter(Qt.Horizontal)
        placement_source_splitter.setChildrenCollapsible(False)
        placement_source_splitter.addWidget(tree)
        placement_source_preview_panel = QWidget()
        placement_source_preview_layout = QVBoxLayout(placement_source_preview_panel)
        placement_source_preview_layout.setContentsMargins(8, 0, 0, 0)
        placement_source_preview_layout.setSpacing(6)
        placement_source_preview_title = QLabel("Source Model Preview")
        placement_source_preview_title.setObjectName("HintLabel")
        placement_source_preview_layout.addWidget(placement_source_preview_title)
        placement_source_preview_widget = QLabel("Select a .pac/.pam/.pamlod placement source to preview it.")
        placement_source_preview_widget.setAlignment(Qt.AlignmentFlag.AlignCenter)
        placement_source_preview_widget.setWordWrap(True)
        placement_source_preview_widget.setFrameShape(QFrame.Shape.StyledPanel)
        placement_source_preview_widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        placement_source_preview_widget.setMinimumWidth(320)
        placement_source_preview_widget.setMinimumHeight(260)
        placement_source_preview_layout.addWidget(placement_source_preview_widget, 1)
        placement_source_preview_status = QLabel(
            "Static geometry thumbnail only in this picker; textures and live texture uploads are skipped here to keep placement browsing stable."
        )
        placement_source_preview_status.setObjectName("HintLabel")
        placement_source_preview_status.setWordWrap(True)
        placement_source_preview_layout.addWidget(placement_source_preview_status)
        placement_source_splitter.addWidget(placement_source_preview_panel)
        placement_source_splitter.setCollapsible(0, False)
        placement_source_splitter.setCollapsible(1, False)
        placement_source_splitter.setStretchFactor(0, 3)
        placement_source_splitter.setStretchFactor(1, 2)
        placement_source_splitter.setSizes([720, 420])
        layout.addWidget(placement_source_splitter, 1)
        status = QLabel(
            "Type at least 2 characters. Search uses the already-built Archive Browser indexes and Item Finder cache; it does not scan every file."
        )
        status.setObjectName("HintLabel")
        status.setWordWrap(True)
        layout.addWidget(status)
        donor_search_progress = QProgressBar()
        donor_search_progress.setTextVisible(True)
        donor_search_progress.setVisible(False)
        layout.addWidget(donor_search_progress)
        button_row = QHBoxLayout()
        button_row.addStretch(1)
        cancel_button = QPushButton("Cancel")
        compare_button = QPushButton("Compare Placement")
        compare_button.setEnabled(False)
        button_row.addWidget(cancel_button)
        button_row.addWidget(compare_button)
        layout.addLayout(button_row)

        allowed_extensions = {
            ".pac",
            ".pam",
            ".pamlod",
            ".prefab",
            ".hkx",
            ".hkt",
            ".paa",
            ".paa_metabin",
            ".motionblending",
            ".xml",
            ".prefabdata_xml",
            ".prefabdata.xml",
            ".pappt",
        }
        max_results = 600
        target_key = target_entry.path.replace("\\", "/").strip().casefold()
        target_folder = PurePosixPath(target_entry.path.replace("\\", "/")).parent.as_posix().casefold()
        if target_folder == ".":
            target_folder = ""
        result: Dict[str, object] = {}
        loose_donor_candidates: List[Tuple[ArchiveEntry, Path, str]] = []
        debounce_timer = QTimer(picker)
        debounce_timer.setSingleShot(True)
        debounce_timer.setInterval(220)
        search_step_timer = QTimer(picker)
        search_step_timer.setSingleShot(True)
        search_step_timer.setInterval(0)
        search_generation = {"value": 0}
        search_state: Dict[str, object] = {}

        def _write_ui_breadcrumb(payload: Mapping[str, object]) -> None:
            write_ui_breadcrumb(
                self.crash_reports_dir,
                payload,
                session_id=self._session_id,
                pid=os.getpid(),
            )

        _write_heartbeat = self._write_heartbeat

        def _placement_source_preview_entry(candidate: object) -> Optional[ArchiveEntry]:
            if not isinstance(candidate, ArchiveEntry):
                return None
            if str(candidate.extension or "").lower() in ARCHIVE_MESH_EXTENSIONS:
                return candidate
            try:
                graph, _references = self._archive_asset_family_graph_for_entry(candidate)
                model_entry = self._attachment_visual_model_entry(candidate, graph)
            except Exception:
                model_entry = None
            return model_entry if isinstance(model_entry, ArchiveEntry) else None

        def _set_placement_source_preview_message(preview_label: QLabel, message: str) -> None:
            preview_label.clear()
            preview_label.setText(str(message or ""))

        def _make_placement_source_preview_controller(
            preview_widget: QLabel,
            status_label: QLabel,
        ) -> Tuple[Callable[[object], None], Callable[[bool], None]]:
            preview_state: Dict[str, object] = {"request_id": 0, "worker": None, "thread": None, "closed": False}
            preview_cache: Dict[Tuple[str, str, int], ArchivePreviewResult] = {}

            def _cache_key(entry: ArchiveEntry) -> Tuple[str, str, int]:
                return attachment_donor_entry_key(entry)

            def _stop_preview_worker(wait: bool = False) -> None:
                preview_state["request_id"] = int(preview_state.get("request_id", 0) or 0) + 1
                worker = preview_state.get("worker")
                thread = preview_state.get("thread")
                if isinstance(worker, ArchivePreviewWorker):
                    worker.stop()
                if isinstance(thread, QThread):
                    thread.quit()
                    if wait:
                        thread.wait(1200)
                preview_state["worker"] = None
                preview_state["thread"] = None

            def _show_preview_result(entry: ArchiveEntry, result_payload: ArchivePreviewResult) -> None:
                if bool(preview_state.get("closed")):
                    return
                preview_model = getattr(result_payload, "preview_model", None)
                if preview_model is None:
                    _set_placement_source_preview_message(
                        preview_widget,
                        f"No renderable model preview was recovered for {entry.basename}.",
                    )
                    status_label.setText(f"{entry.basename}: no renderable model preview recovered.")
                    return
                prepared_preview = getattr(result_payload, "prepared_preview_model", None)
                mesh_count = len(getattr(preview_model, "meshes", ()) or ()) if isinstance(preview_model, ModelPreviewData) else 0
                vertex_count = int(getattr(preview_model, "vertex_count", 0) or 0)
                face_count = int(getattr(preview_model, "face_count", 0) or 0)
                _write_ui_breadcrumb(
                    {
                        "phase": "placement_source_preview_apply",
                        "target_path": target_entry.path,
                        "source_path": entry.path,
                        "has_prepared_preview": prepared_preview is not None,
                        "static_preview": True,
                        "mesh_count": mesh_count,
                        "vertex_count": vertex_count,
                        "face_count": face_count,
                    }
                )
                try:
                    preview_theme = get_theme(str(getattr(self, "current_theme_key", DEFAULT_UI_THEME) or DEFAULT_UI_THEME))
                    pixmap = render_static_model_preview_pixmap(
                        preview_model,
                        width=preview_widget.width(),
                        height=preview_widget.height(),
                        text_color=str(preview_theme.get("text_muted", "#8b949e")),
                    )
                    if pixmap is None:
                        _set_placement_source_preview_message(
                            preview_widget,
                            f"No renderable geometry was recovered for {entry.basename}.",
                        )
                    else:
                        preview_widget.clear()
                        preview_widget.setPixmap(pixmap)
                except Exception as exc:
                    _set_placement_source_preview_message(
                        preview_widget,
                        f"Could not show source preview for {entry.basename}.",
                    )
                    status_label.setText(f"Preview display failed for {entry.basename}: {exc}")
                    _write_ui_breadcrumb(
                        {
                            "phase": "placement_source_preview_apply_error",
                            "target_path": target_entry.path,
                            "source_path": entry.path,
                            "error": str(exc),
                        }
                    )
                    return
                status_label.setText(
                    f"Previewing placement source geometry: {entry.path} | {mesh_count} mesh(es), {vertex_count:,} vertices, {face_count:,} faces"
                )
                _write_ui_breadcrumb(
                    {
                        "phase": "placement_source_preview_applied",
                        "target_path": target_entry.path,
                        "source_path": entry.path,
                        "static_preview": True,
                    }
                )

            def _handle_preview_ready(request_id: int, payload: object) -> None:
                if bool(preview_state.get("closed")) or request_id != int(preview_state.get("request_id", 0) or 0):
                    return
                if not isinstance(payload, ArchivePreviewResult):
                    return
                entry = preview_state.get("entry")
                if not isinstance(entry, ArchiveEntry):
                    return
                preview_cache[_cache_key(entry)] = payload
                _write_heartbeat("running")
                _write_ui_breadcrumb(
                    {
                        "phase": "placement_source_preview_ready",
                        "target_path": target_entry.path,
                        "source_path": entry.path,
                    }
                )
                _show_preview_result(entry, payload)

            def _handle_preview_error(request_id: int, message: str) -> None:
                if bool(preview_state.get("closed")) or request_id != int(preview_state.get("request_id", 0) or 0):
                    return
                entry = preview_state.get("entry")
                label = entry.basename if isinstance(entry, ArchiveEntry) else "selected source"
                _set_placement_source_preview_message(preview_widget, f"Could not build preview for {label}.")
                status_label.setText(f"Preview failed for {label}: {message}")
                _write_heartbeat("running")
                _write_ui_breadcrumb(
                    {
                        "phase": "placement_source_preview_error",
                        "target_path": target_entry.path,
                        "source_path": entry.path if isinstance(entry, ArchiveEntry) else "",
                        "error": str(message),
                    }
                )

            def _clear_worker_ref(request_id: int) -> None:
                if request_id == int(preview_state.get("request_id", 0) or 0):
                    preview_state["worker"] = None
                    preview_state["thread"] = None

            def _show_candidate(candidate: object) -> None:
                preview_entry = _placement_source_preview_entry(candidate)
                if not isinstance(preview_entry, ArchiveEntry):
                    _stop_preview_worker()
                    _set_placement_source_preview_message(
                        preview_widget,
                        "Select a model-like placement source to preview it.",
                    )
                    status_label.setText("This placement source has no resolved visible model preview.")
                    _write_heartbeat("running")
                    return
                key = _cache_key(preview_entry)
                cached = preview_cache.get(key)
                if cached is not None:
                    _stop_preview_worker()
                    preview_state["entry"] = preview_entry
                    _show_preview_result(preview_entry, cached)
                    return
                _stop_preview_worker()
                request_id = int(preview_state.get("request_id", 0) or 0) + 1
                preview_state["request_id"] = request_id
                preview_state["entry"] = preview_entry
                _set_placement_source_preview_message(preview_widget, f"Loading preview for {preview_entry.basename}...")
                status_label.setText(f"Building geometry preview for {preview_entry.path}...")
                _write_heartbeat("placement_source_preview")
                _write_ui_breadcrumb(
                    {
                        "phase": "placement_source_preview_start",
                        "target_path": target_entry.path,
                        "source_path": preview_entry.path,
                        "source_extension": preview_entry.extension,
                    }
                )
                texconv_text = self.texconv_path_edit.text().strip()
                texconv_path = Path(texconv_text).expanduser() if texconv_text else None
                preview_settings = self._current_model_preview_render_settings()
                worker = ArchivePreviewWorker(
                    request_id,
                    texconv_path,
                    preview_entry,
                    self._find_archive_preview_companion_entry(preview_entry),
                    self.archive_entries_by_normalized_path,
                    self.archive_entries_by_basename,
                    self.archive_sidecar_entries_by_texture_path,
                    self.archive_sidecar_entries_by_texture_basename,
                    self._collect_archive_preview_loose_roots(),
                    visible_texture_mode=preview_settings.visible_texture_mode,
                    support_texture_slots=(),
                    render_settings=preview_settings,
                    include_loose_preview_assets=False,
                    sidecar_generation=self.archive_sidecar_generation,
                    attach_preview_images=False,
                )
                thread = QThread(self)
                worker.moveToThread(thread)
                thread.started.connect(worker.run)
                worker.completed.connect(_handle_preview_ready)
                worker.error.connect(_handle_preview_error)
                worker.finished.connect(thread.quit)
                worker.finished.connect(worker.deleteLater)
                thread.finished.connect(thread.deleteLater)
                thread.finished.connect(lambda rid=request_id: _clear_worker_ref(rid))
                preview_state["worker"] = worker
                preview_state["thread"] = thread
                thread.start()

            def _close_controller(wait: bool = False) -> None:
                preview_state["closed"] = True
                _stop_preview_worker(wait)
                _write_heartbeat("running")

            return _show_candidate, _close_controller

        update_source_preview, close_source_preview = _make_placement_source_preview_controller(
            placement_source_preview_widget,
            placement_source_preview_status,
        )

        def _candidate_allowed(candidate: object) -> bool:
            if not isinstance(candidate, ArchiveEntry):
                return False
            if self._same_archive_entry(candidate, target_entry):
                return False
            candidate_path = str(candidate.path or "").replace("\\", "/")
            candidate_key = candidate_path.strip().casefold()
            if not candidate_key or candidate_key == target_key:
                return False
            ext = str(candidate.extension or "").lower()
            if ext not in allowed_extensions:
                return False
            return True

        def _candidate_matches(candidate: object, terms: Sequence[str]) -> bool:
            if not _candidate_allowed(candidate) or not isinstance(candidate, ArchiveEntry):
                return False
            haystack = attachment_donor_haystack(
                candidate,
                role_label=self._archive_entry_role_label,
                item_name_match=self._archive_entry_item_name_match,
            )
            return all(term in haystack for term in terms)

        def _add_candidate(
            candidates: Dict[AttachmentDonorKey, Tuple[int, ArchiveEntry, str, str]],
            candidate: ArchiveEntry,
            *,
            source: str,
            note: str = "",
        ) -> None:
            if not _candidate_allowed(candidate):
                return
            key = attachment_donor_entry_key(candidate)
            score = attachment_donor_candidate_score(candidate, source)
            existing = candidates.get(key)
            if existing is not None and existing[0] >= score:
                return
            candidates[key] = (score, candidate, source, note)

        def _render_candidate(candidate: ArchiveEntry, *, source: str, note: str = "") -> None:
            evidence_text = attachment_donor_evidence(candidate, target_folder)
            if note:
                evidence_text = f"{evidence_text}; {note}"
            item = make_attachment_donor_candidate_item(
                candidate,
                donor_type=attachment_donor_type(candidate, self._archive_entry_role_label),
                evidence_text=evidence_text,
                source=source,
            )
            tree.addTopLevelItem(item)

        def _refresh_compare_button() -> None:
            item = tree.currentItem()
            compare_button.setEnabled(isinstance(item.data(0, Qt.UserRole), ArchiveEntry) if item is not None else False)

        def _set_search_busy(active: bool) -> None:
            search_button.setEnabled(not active)
            item_finder_button.setEnabled(not active and bool(self.archive_item_asset_catalog))
            loose_folder_button.setEnabled(not active)
            search_button.setText("Searching..." if active else "Search Index")
            donor_search_progress.setVisible(active)
            if active:
                donor_search_progress.setFormat("%p%")

        def _render_index_search_results(
            collected: Dict[AttachmentDonorKey, Tuple[int, ArchiveEntry, str, str]],
            *,
            search_note: str,
        ) -> None:
            tree.setUpdatesEnabled(False)
            try:
                tree.clear()
                ordered = sorted(collected.values(), key=lambda item: (-item[0], item[1].path.casefold()))
                for _score, entry, source, note in ordered[:max_results]:
                    _render_candidate(entry, source=source, note=note)
            finally:
                tree.setUpdatesEnabled(True)
            expand_tree_columns_to_available_width(tree)
            if tree.topLevelItemCount() > 0:
                tree.setCurrentItem(tree.topLevelItem(0))
            else:
                update_source_preview(None)
            _refresh_compare_button()
            shown_count = tree.topLevelItemCount()
            clipped = " Results are capped; narrow the search for more exact matches." if shown_count >= max_results else ""
            status.setText(
                f"{shown_count:,} donor candidate(s) shown. {search_note}{clipped} "
                "Select a row, then Compare Placement to verify the package plan."
            )

        def _finish_index_search() -> None:
            state = dict(search_state)
            search_state.clear()
            search_step_timer.stop()
            _set_search_busy(False)
            donor_search_progress.setVisible(False)
            collected = state.get("collected")
            if not isinstance(collected, dict):
                return
            scanned_keys = int(state.get("scanned_keys", 0) or 0)
            if scanned_keys:
                search_note = f"Checked cached basename keys only ({scanned_keys:,}); no file payload scan."
            else:
                search_note = "Used exact basename, Item Finder, loose-folder, and current Archive Browser caches; no full file scan."
            _render_index_search_results(collected, search_note=search_note)

        def _advance_index_search_phase(state: Dict[str, object]) -> None:
            phase = str(state.get("phase") or "")
            if phase == "loose":
                state["phase"] = "basename_exact"
            elif phase == "basename_exact":
                state["phase"] = "catalog" if state.get("terms") else "filtered"
            elif phase == "catalog":
                state["phase"] = "filtered"
            elif phase == "filtered":
                state["phase"] = "basename_contains" if state.get("scan_basename_contains") else "done"
            else:
                state["phase"] = "done"

        def _continue_index_search() -> None:
            if not search_state:
                return
            generation = int(search_state.get("generation", 0) or 0)
            if generation != search_generation["value"]:
                search_state.clear()
                return
            collected = search_state.get("collected")
            if not isinstance(collected, dict):
                search_state.clear()
                return
            query = str(search_state.get("query") or "")
            terms = tuple(search_state.get("terms") or ())
            deadline = time.perf_counter() + 0.018
            while time.perf_counter() < deadline and len(collected) < max_results:
                phase = str(search_state.get("phase") or "")
                if phase == "loose":
                    index = int(search_state.get("loose_index", 0) or 0)
                    if index >= len(loose_donor_candidates):
                        _advance_index_search_phase(search_state)
                        continue
                    entry, local_path, note = loose_donor_candidates[index]
                    search_state["loose_index"] = index + 1
                    search_state["work_done"] = int(search_state.get("work_done", 0) or 0) + 1
                    if not terms or _candidate_matches(entry, terms) or all(term in str(local_path).casefold() for term in terms):
                        _add_candidate(collected, entry, source="Loose donor folder", note=note)
                elif phase == "basename_exact":
                    variants = tuple(search_state.get("basename_variants") or ())
                    index = int(search_state.get("basename_variant_index", 0) or 0)
                    if index >= len(variants):
                        _advance_index_search_phase(search_state)
                        continue
                    basename = str(variants[index])
                    search_state["basename_variant_index"] = index + 1
                    search_state["work_done"] = int(search_state.get("work_done", 0) or 0) + 1
                    for entry in self.archive_entries_by_basename.get(basename, ()):
                        _add_candidate(collected, entry, source="Basename index", note="exact filename match")
                        if len(collected) >= max_results:
                            break
                elif phase == "catalog":
                    catalog_rows = search_state.get("catalog_rows") or ()
                    index = int(search_state.get("catalog_index", 0) or 0)
                    if index >= len(catalog_rows):  # type: ignore[arg-type]
                        _advance_index_search_phase(search_state)
                        continue
                    row = catalog_rows[index]  # type: ignore[index]
                    search_state["catalog_index"] = index + 1
                    search_state["work_done"] = int(search_state.get("work_done", 0) or 0) + 1
                    if not isinstance(row, Mapping):
                        continue
                    catalog_text = self._archive_asset_catalog_text(row)
                    if terms and not all(term in catalog_text for term in terms):
                        continue
                    scoped_entries, _primary_count, _related_count = self._resolve_archive_asset_catalog_scope_entries(
                        row,
                        include_related=True,
                    )
                    display_name = str(row.get("display_name") or row.get("internal_name") or "").strip()
                    note = f"Item Finder match: {display_name}" if display_name else "Item Finder match"
                    for entry in scoped_entries:
                        _add_candidate(collected, entry, source="Item Finder cache", note=note)
                        if len(collected) >= max_results:
                            break
                elif phase == "filtered":
                    filtered_entries = search_state.get("filtered_entries") or ()
                    index = int(search_state.get("filtered_index", 0) or 0)
                    limit = int(search_state.get("filtered_limit", 0) or 0)
                    if index >= limit:
                        _advance_index_search_phase(search_state)
                        continue
                    entry = filtered_entries[index]  # type: ignore[index]
                    search_state["filtered_index"] = index + 1
                    search_state["work_done"] = int(search_state.get("work_done", 0) or 0) + 1
                    if _candidate_matches(entry, terms):
                        _add_candidate(collected, entry, source="Current Archive Browser results", note="matched existing filtered list")
                elif phase == "basename_contains":
                    iterator = search_state.get("basename_iterator")
                    if iterator is None:
                        search_state["phase"] = "done"
                        continue
                    try:
                        basename, entries = next(iterator)  # type: ignore[misc]
                    except StopIteration:
                        search_state["phase"] = "done"
                        continue
                    search_state["work_done"] = int(search_state.get("work_done", 0) or 0) + 1
                    search_state["scanned_keys"] = int(search_state.get("scanned_keys", 0) or 0) + 1
                    normalized_basename = str(basename or "").casefold()
                    query_lower = query.strip().casefold()
                    if query_lower not in normalized_basename and not all(term in normalized_basename for term in terms):
                        continue
                    for entry in entries:
                        _add_candidate(collected, entry, source="Basename index", note="cached filename contains search text")
                        if len(collected) >= max_results:
                            break
                else:
                    break
            total_work = max(1, int(search_state.get("work_total", 1) or 1))
            work_done = min(total_work, int(search_state.get("work_done", 0) or 0))
            donor_search_progress.setRange(0, total_work)
            donor_search_progress.setValue(work_done)
            status.setText(
                f"Searching cached indexes... {len(collected):,} candidate(s) found so far. "
                f"Phase: {str(search_state.get('phase') or 'done').replace('_', ' ')}."
            )
            if str(search_state.get("phase") or "") == "done" or len(collected) >= max_results:
                _finish_index_search()
            else:
                search_step_timer.start(0)

        def _collect_indexed_candidates(query: str, terms: Sequence[str]) -> None:
            generation = search_generation["value"] + 1
            search_generation["value"] = generation
            search_step_timer.stop()
            tree.clear()
            compare_button.setEnabled(False)
            update_source_preview(None)
            filtered_entries = self.archive_filtered_entries or ()
            basename_scan_enabled = len(query.strip()) >= 3 and bool(terms)
            catalog_rows = self.archive_item_asset_catalog or ()
            basename_variants = attachment_donor_basename_query_variants(query)
            work_total = (
                len(loose_donor_candidates)
                + len(basename_variants)
                + (len(catalog_rows) if terms else 0)
                + (min(len(filtered_entries), 10000) if terms else 0)
                + (len(self.archive_entries_by_basename) if basename_scan_enabled else 0)
            )
            search_state.clear()
            search_state.update(
                {
                    "generation": generation,
                    "query": query,
                    "terms": tuple(terms),
                    "phase": "loose",
                    "collected": {},
                    "loose_index": 0,
                    "basename_variants": basename_variants,
                    "basename_variant_index": 0,
                    "catalog_rows": catalog_rows,
                    "catalog_index": 0,
                    "filtered_entries": filtered_entries,
                    "filtered_limit": min(len(filtered_entries), 10000) if terms else 0,
                    "filtered_index": 0,
                    "scan_basename_contains": basename_scan_enabled,
                    "basename_iterator": iter(self.archive_entries_by_basename.items()) if basename_scan_enabled else None,
                    "scanned_keys": 0,
                    "work_done": 0,
                    "work_total": max(1, work_total),
                }
            )
            donor_search_progress.setRange(0, max(1, work_total))
            donor_search_progress.setValue(0)
            _set_search_busy(True)
            status.setText("Searching cached indexes... 0 candidate(s) found so far.")
            search_step_timer.start(0)

        def _start_scan() -> None:
            query = search_edit.text().strip()
            terms = attachment_donor_search_terms(query)
            search_generation["value"] += 1
            search_step_timer.stop()
            search_state.clear()
            _set_search_busy(False)
            tree.clear()
            compare_button.setEnabled(False)
            update_source_preview(None)
            if len(query) < 2 and not loose_donor_candidates:
                donor_search_progress.setVisible(False)
                status.setText(
                    "Type at least 2 characters, or add a loose donor folder. Indexed search starts from cached names and Item Finder rows."
                )
                return
            _collect_indexed_candidates(query, terms)

        def _open_item_finder_donor_picker() -> None:
            if not self.archive_item_asset_catalog:
                QMessageBox.information(
                    picker,
                    "Item Finder",
                    "No Item Finder index is available yet. Scan or refresh archives so the item index can be built.",
                )
                return
            _write_heartbeat("placement_item_finder")
            _write_ui_breadcrumb(
                {
                    "phase": "placement_item_finder_open",
                    "target_path": target_entry.path,
                    "catalog_rows": len(self.archive_item_asset_catalog),
                }
            )
            finder = QDialog(picker)
            finder.setWindowTitle("Item Finder - Choose Placement Source")
            finder.resize(1180, 740)
            finder_layout = QVBoxLayout(finder)
            finder_layout.setContentsMargins(12, 12, 12, 12)
            finder_layout.setSpacing(8)
            finder_intro = QLabel(
                "Search or browse Item Finder visually, then choose the resolved .pac/.prefab/.hkx/socket file to use as the placement source. "
                "The target opened in Placement Swap is the asset that will be packaged with this source placement."
            )
            finder_intro.setObjectName("HintLabel")
            finder_intro.setWordWrap(True)
            finder_layout.addWidget(finder_intro)
            finder_controls = QHBoxLayout()
            finder_controls.setSpacing(8)
            finder_category = QComboBox()
            finder_category.addItem("All categories", "")
            for category in self._archive_asset_catalog_categories():
                finder_category.addItem(category, category)
            finder_search = QLineEdit()
            finder_search.setPlaceholderText("Search item name, model id, category, or recovered file path")
            finder_search.setText(search_edit.text().strip())
            finder_clear_button = QPushButton("Clear")
            finder_controls.addWidget(finder_category)
            finder_controls.addWidget(finder_search, 1)
            finder_controls.addWidget(finder_clear_button)
            finder_layout.addLayout(finder_controls)

            finder_splitter = QSplitter(Qt.Horizontal)
            item_grid = QListWidget()
            item_grid.setViewMode(QListView.ViewMode.IconMode)
            item_grid.setResizeMode(QListView.ResizeMode.Adjust)
            item_grid.setSelectionMode(QAbstractItemView.SingleSelection)
            item_grid.setIconSize(QSize(78, 78))
            item_grid.setGridSize(QSize(166, 136))
            item_grid.setSpacing(8)
            item_grid.setWordWrap(True)
            item_grid.setWrapping(True)
            item_grid.setUniformItemSizes(True)
            item_grid.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
            finder_splitter.addWidget(item_grid)

            detail_panel = QWidget()
            detail_layout = QVBoxLayout(detail_panel)
            detail_layout.setContentsMargins(8, 0, 0, 0)
            detail_layout.setSpacing(8)
            item_detail = QLabel("Select an item to see resolved placement-source candidates.")
            item_detail.setObjectName("HintLabel")
            item_detail.setWordWrap(True)
            item_detail.setMinimumHeight(72)
            item_detail.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Minimum)
            item_detail.setTextInteractionFlags(Qt.TextSelectableByMouse)
            detail_layout.addWidget(item_detail)
            candidate_tree = QTreeWidget()
            candidate_tree.setColumnCount(5)
            candidate_tree.setHeaderLabels(["Placement Source File", "What It Means", "Placement Evidence", "Resolved Archive Path", "Index Source"])
            candidate_tree.setRootIsDecorated(False)
            candidate_tree.setAlternatingRowColors(True)
            candidate_tree.setUniformRowHeights(True)
            candidate_tree.setSelectionMode(QAbstractItemView.SingleSelection)
            candidate_tree.header().setStretchLastSection(False)
            detail_splitter = QSplitter(Qt.Vertical)
            detail_splitter.setChildrenCollapsible(False)
            detail_splitter.addWidget(candidate_tree)
            finder_source_detail_panel = QWidget()
            finder_source_detail_layout = QVBoxLayout(finder_source_detail_panel)
            finder_source_detail_layout.setContentsMargins(0, 0, 0, 0)
            finder_source_detail_layout.setSpacing(4)
            finder_source_detail_title = QLabel("Candidate Source")
            finder_source_detail_title.setObjectName("HintLabel")
            finder_source_detail_layout.addWidget(finder_source_detail_title)
            finder_source_detail = QLabel("Select an Item Finder row to resolve placement-source files.")
            finder_source_detail.setObjectName("HintLabel")
            finder_source_detail.setWordWrap(True)
            finder_source_detail.setTextInteractionFlags(Qt.TextSelectableByMouse)
            finder_source_detail_layout.addWidget(finder_source_detail, 1)
            finder_source_status = QLabel(
                "3D preview is skipped in this nested picker so Item Finder browsing stays stable."
            )
            finder_source_status.setObjectName("HintLabel")
            finder_source_status.setWordWrap(True)
            finder_source_detail_layout.addWidget(finder_source_status)
            detail_splitter.addWidget(finder_source_detail_panel)
            detail_splitter.setStretchFactor(0, 3)
            detail_splitter.setStretchFactor(1, 2)
            detail_splitter.setSizes([330, 260])
            detail_layout.addWidget(detail_splitter, 1)
            finder_splitter.addWidget(detail_panel)
            finder_splitter.setStretchFactor(0, 1)
            finder_splitter.setStretchFactor(1, 1)
            finder_splitter.setSizes([560, 560])
            finder_layout.addWidget(finder_splitter, 1)

            finder_status = QLabel("")
            finder_status.setObjectName("HintLabel")
            finder_status.setWordWrap(True)
            finder_status.setMinimumHeight(38)
            finder_status.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Minimum)
            finder_layout.addWidget(finder_status)
            finder_buttons = QHBoxLayout()
            use_recommended_button = QPushButton("Use Recommended Source")
            use_candidate_button = QPushButton("Use Selected Source")
            finder_cancel_button = QPushButton("Cancel")
            use_recommended_button.setEnabled(False)
            use_candidate_button.setEnabled(False)
            finder_buttons.addStretch(1)
            finder_buttons.addWidget(use_recommended_button)
            finder_buttons.addWidget(use_candidate_button)
            finder_buttons.addWidget(finder_cancel_button)
            finder_layout.addLayout(finder_buttons)
            finder_filter_timer = QTimer(finder)
            finder_filter_timer.setSingleShot(True)
            finder_filter_timer.setInterval(180)
            finder_icon_timer = QTimer(finder)
            finder_icon_timer.setSingleShot(True)
            finder_icon_visible_timer = QTimer(finder)
            finder_icon_visible_timer.setSingleShot(True)
            finder_icon_visible_timer.setInterval(80)
            finder_icon_queue: List[QListWidgetItem] = []
            finder_result: Dict[str, object] = {}

            def _selected_item_finder_row() -> Optional[Dict[str, object]]:
                item = item_grid.currentItem()
                if item is None:
                    return None
                raw = item.data(Qt.UserRole)
                return dict(raw) if isinstance(raw, Mapping) else None

            def _item_finder_row_display_name(row: Mapping[str, object]) -> str:
                return str(row.get("display_name", "") or row.get("internal_name", "") or "selected item").strip()

            def _item_finder_donor_candidates(row: Mapping[str, object]) -> Tuple[Tuple[int, ArchiveEntry, str, str], ...]:
                display_name = _item_finder_row_display_name(row)
                scoped_entries, _primary_count, _related_count = self._resolve_archive_asset_catalog_scope_entries(
                    row,
                    include_related=True,
                )
                collected: Dict[AttachmentDonorKey, Tuple[int, ArchiveEntry, str, str]] = {}
                for entry in scoped_entries:
                    if not _candidate_allowed(entry):
                        continue
                    key = attachment_donor_entry_key(entry)
                    score = attachment_donor_candidate_score(entry, "Item Finder visual pick")
                    existing = collected.get(key)
                    if existing is not None and existing[0] >= score:
                        continue
                    collected[key] = (score, entry, "Item Finder visual pick", f"selected item: {display_name}")
                ordered = sorted(collected.values(), key=lambda item: (-item[0], item[1].path.casefold()))
                return tuple(ordered[:200])

            def _queue_item_finder_donor_icons_for_visible_rows() -> None:
                viewport_rect = item_grid.viewport().rect().adjusted(-180, -220, 220, 560)
                visible_candidates: List[QListWidgetItem] = []
                for row_index in range(item_grid.count()):
                    item = item_grid.item(row_index)
                    if item is None:
                        continue
                    row = item.data(Qt.UserRole)
                    if not isinstance(row, Mapping):
                        continue
                    if not self._archive_asset_catalog_row_values(row, "icon_paths"):
                        continue
                    if item.data(Qt.UserRole + 1) in {"thumb_loaded", "thumb_missing", "thumb_pending"}:
                        continue
                    item_rect = item_grid.visualItemRect(item)
                    if item_rect.isValid() and item_rect.intersects(viewport_rect):
                        visible_candidates.append(item)
                    elif not item_rect.isValid() and row_index < 80:
                        visible_candidates.append(item)
                    if len(visible_candidates) >= 100:
                        break
                visible_ids = {id(item) for item in visible_candidates}
                if finder_icon_queue:
                    retained_queue: List[QListWidgetItem] = []
                    for item in finder_icon_queue:
                        if id(item) in visible_ids:
                            retained_queue.append(item)
                        elif item_grid.row(item) >= 0 and item.data(Qt.UserRole + 1) == "thumb_pending":
                            item.setData(Qt.UserRole + 1, "fallback")
                    finder_icon_queue[:] = retained_queue
                queued_ids = {id(item) for item in finder_icon_queue}
                for item in visible_candidates:
                    if id(item) in queued_ids:
                        continue
                    item.setData(Qt.UserRole + 1, "thumb_pending")
                    finder_icon_queue.append(item)
                self._queue_archive_asset_catalog_icon_warmup_rows(
                    [
                        item.data(Qt.UserRole)
                        for item in visible_candidates
                        if isinstance(item.data(Qt.UserRole), Mapping)
                    ],
                    front=True,
                    user_visible=True,
                    delay_ms=0,
                )
                if finder_icon_queue and not finder_icon_timer.isActive():
                    finder_icon_timer.start(1)

            def _queue_item_finder_donor_icons_coalesced(delay_ms: int = 80) -> None:
                if not finder.isVisible():
                    return
                finder_icon_visible_timer.start(max(0, int(delay_ms)))

            def _load_next_item_finder_donor_icon() -> None:
                if finder_icon_queue:
                    _write_ui_breadcrumb(
                        {
                            "phase": "placement_item_finder_icon_batch",
                            "target_path": target_entry.path,
                            "queued_icons": len(finder_icon_queue),
                        }
                    )
                loaded_count = 0
                while finder_icon_queue:
                    item = finder_icon_queue.pop(0)
                    if item_grid.row(item) < 0:
                        continue
                    item_rect = item_grid.visualItemRect(item)
                    active_rect = item_grid.viewport().rect().adjusted(-220, -260, 260, 640)
                    if item_rect.isValid() and not item_rect.intersects(active_rect):
                        if item.data(Qt.UserRole + 1) == "thumb_pending":
                            item.setData(Qt.UserRole + 1, "fallback")
                        continue
                    row = item.data(Qt.UserRole)
                    if not isinstance(row, Mapping):
                        continue
                    pixmap, note = self._cached_archive_asset_catalog_inventory_icon_pixmap(
                        row,
                        78,
                        allow_sync_prepare=False,
                    )
                    if pixmap is not None and not pixmap.isNull():
                        item.setIcon(QIcon(pixmap))
                        if note:
                            item.setToolTip(f"{item.toolTip()}\n{note}" if item.toolTip() else note)
                        item.setData(Qt.UserRole + 1, "thumb_loaded")
                    elif "warming" in str(note).lower():
                        item.setData(Qt.UserRole + 1, "fallback")
                        if not finder_icon_visible_timer.isActive():
                            finder_icon_visible_timer.start(160)
                    else:
                        if note:
                            item.setToolTip(f"{item.toolTip()}\n{note}" if item.toolTip() else note)
                        item.setData(Qt.UserRole + 1, "thumb_missing")
                    loaded_count += 1
                    if loaded_count >= 10:
                        break
                if finder_icon_queue:
                    finder_icon_timer.start(3)

            def _handle_item_finder_donor_icon_prepared(prepared_key: Tuple[Tuple[str, ...], str]) -> None:
                if not finder.isVisible():
                    return
                icon_paths, texconv_key = prepared_key
                if texconv_key != self.texconv_path_edit.text().strip():
                    return
                active_rect = item_grid.viewport().rect().adjusted(-220, -260, 260, 640)
                matched_items: List[QListWidgetItem] = []
                for row_index in range(item_grid.count()):
                    item = item_grid.item(row_index)
                    if item is None:
                        continue
                    row = item.data(Qt.UserRole)
                    if not isinstance(row, Mapping):
                        continue
                    if tuple(self._archive_asset_catalog_row_values(row, "icon_paths")) != icon_paths:
                        continue
                    item_rect = item_grid.visualItemRect(item)
                    if item_rect.isValid() and not item_rect.intersects(active_rect):
                        continue
                    item.setData(Qt.UserRole + 1, "fallback")
                    matched_items.append(item)
                    if len(matched_items) >= 16:
                        break
                if matched_items:
                    finder_icon_queue[0:0] = matched_items
                    finder_icon_timer.start(0)

            def _populate_item_finder_grid() -> None:
                finder_icon_timer.stop()
                finder_icon_queue.clear()
                query = finder_search.text().strip().casefold()
                query_tokens = tuple(re.findall(r"[a-z0-9]+", query))
                selected_category = str(finder_category.currentData() or "")
                _write_ui_breadcrumb(
                    {
                        "phase": "placement_item_finder_populate",
                        "target_path": target_entry.path,
                        "query": query,
                        "category": selected_category,
                        "catalog_rows": len(self.archive_item_asset_catalog),
                    }
                )
                item_grid.setUpdatesEnabled(False)
                try:
                    item_grid.clear()
                    shown = 0
                    matched = 0
                    for row in self.archive_item_asset_catalog:
                        category = str(row.get("category", "") or "Item")
                        if selected_category and category != selected_category:
                            continue
                        haystack = self._archive_asset_catalog_text(row)
                        if query_tokens and not all(token in haystack for token in query_tokens):
                            continue
                        matched += 1
                        display_name = _item_finder_row_display_name(row)
                        group = str(row.get("group", "") or "Unclassified")
                        table_labels = self._archive_asset_catalog_table_evidence_labels(row)
                        compatibility_tags = self._archive_asset_catalog_row_values(row, "compatibility_tags")
                        item = QListWidgetItem(display_name)
                        item.setIcon(self._build_archive_asset_catalog_icon(category, display_name))
                        item.setSizeHint(QSize(158, 128))
                        item.setData(Qt.UserRole, dict(row))
                        item.setData(Qt.UserRole + 1, "fallback")
                        tooltip_lines = [
                            display_name,
                            f"Category: {category} / {group}",
                            f"Internal: {str(row.get('internal_name', '') or '-')}",
                        ]
                        if table_labels:
                            tooltip_lines.append(
                                "Table fields: "
                                + ", ".join(table_labels[:6])
                                + (" ..." if len(table_labels) > 6 else "")
                            )
                        if compatibility_tags:
                            tooltip_lines.append(
                                "Compatibility: "
                                + ", ".join(compatibility_tags[:6])
                                + (" ..." if len(compatibility_tags) > 6 else "")
                            )
                        item.setToolTip("\n".join(tooltip_lines))
                        item_grid.addItem(item)
                        shown += 1
                        if shown >= 1500:
                            break
                finally:
                    item_grid.setUpdatesEnabled(True)
                if item_grid.count() > 0:
                    item_grid.setCurrentRow(0)
                else:
                    candidate_tree.clear()
                    item_detail.setText("No Item Finder rows match this filter.")
                    use_recommended_button.setEnabled(False)
                    use_candidate_button.setEnabled(False)
                    finder_source_detail.setText("No placement-source candidates are visible for this filter.")
                    finder_source_status.setText("Change the search or category filter to browse more Item Finder rows.")
                finder_status.setText(
                    f"{item_grid.count():,} Item Finder row(s) shown. Select an item, then choose one of its resolved placement-source files."
                )
                _write_ui_breadcrumb(
                    {
                        "phase": "placement_item_finder_populated",
                        "target_path": target_entry.path,
                        "query": query,
                        "category": selected_category,
                        "shown": item_grid.count(),
                        "matched": matched,
                    }
                )
                QTimer.singleShot(140, _queue_item_finder_donor_icons_for_visible_rows)

            def _refresh_item_finder_candidates() -> None:
                row = _selected_item_finder_row()
                candidate_tree.clear()
                use_recommended_button.setEnabled(False)
                use_candidate_button.setEnabled(False)
                if row is None:
                    item_detail.setText("Select an item to see resolved placement-source candidates.")
                    finder_source_detail.setText("Select an Item Finder row to resolve placement-source files.")
                    finder_source_status.setText("3D preview is skipped in this nested picker so Item Finder browsing stays stable.")
                    return
                display_name = _item_finder_row_display_name(row)
                category = str(row.get("category", "") or "Item")
                group = str(row.get("group", "") or "Unclassified")
                _write_ui_breadcrumb(
                    {
                        "phase": "placement_item_finder_resolve_candidates",
                        "target_path": target_entry.path,
                        "item": display_name,
                        "category": category,
                        "group": group,
                    }
                )
                candidates = _item_finder_donor_candidates(row)
                item_detail.setText(
                    f"{display_name}\n{category} / {group}\n"
                    f"{len(candidates):,} placement donor candidate(s) resolved from direct links and related files."
                )
                for _score, entry, source, note in candidates:
                    evidence_text = attachment_donor_evidence(entry, target_folder)
                    if note:
                        evidence_text = f"{evidence_text}; {note}"
                    item = make_attachment_donor_candidate_item(
                        entry,
                        donor_type=attachment_donor_type(entry, self._archive_entry_role_label),
                        evidence_text=evidence_text,
                        source=source,
                    )
                    for column in range(candidate_tree.columnCount()):
                        item.setToolTip(column, item.text(column))
                    candidate_tree.addTopLevelItem(item)
                for column in range(candidate_tree.columnCount()):
                    candidate_tree.resizeColumnToContents(column)
                expand_tree_columns_to_available_width(candidate_tree)
                _write_ui_breadcrumb(
                    {
                        "phase": "placement_item_finder_candidates_resolved",
                        "target_path": target_entry.path,
                        "item": display_name,
                        "candidate_count": len(candidates),
                    }
                )
                if candidate_tree.topLevelItemCount() > 0:
                    candidate_tree.setCurrentItem(candidate_tree.topLevelItem(0))
                    use_recommended_button.setEnabled(True)
                else:
                    finder_source_detail.setText(f"{display_name}\nNo placement-source files were resolved for this item.")
                    finder_source_status.setText("Try a different item or use Search Index from the placement source dialog.")
                _refresh_candidate_button()

            def _refresh_candidate_button() -> None:
                item = candidate_tree.currentItem()
                entry = item.data(0, Qt.UserRole) if item is not None else None
                use_candidate_button.setEnabled(isinstance(entry, ArchiveEntry))
                if isinstance(entry, ArchiveEntry):
                    finder_source_detail.setText(
                        "\n".join(
                            (
                                entry.basename,
                                attachment_donor_type(entry, self._archive_entry_role_label),
                                entry.path,
                            )
                        )
                    )
                    finder_source_status.setText("Use Selected Source or Use Recommended Source to continue.")
                else:
                    finder_source_detail.setText("Select a resolved placement-source file.")
                    finder_source_status.setText("3D preview is skipped in this nested picker so Item Finder browsing stays stable.")

            def _choose_item_finder_candidate(*, recommended: bool) -> None:
                item = candidate_tree.topLevelItem(0) if recommended else candidate_tree.currentItem()
                entry = item.data(0, Qt.UserRole) if item is not None else None
                if not isinstance(entry, ArchiveEntry):
                    QMessageBox.information(finder, "Item Finder", "Select a resolved placement-source file first.")
                    return
                finder_result["donor"] = entry
                finder.accept()

            finder_filter_timer.timeout.connect(_populate_item_finder_grid)
            finder_icon_timer.timeout.connect(_load_next_item_finder_donor_icon)
            finder_icon_visible_timer.timeout.connect(_queue_item_finder_donor_icons_for_visible_rows)
            finder_search.textChanged.connect(lambda _text: finder_filter_timer.start())
            finder_category.currentIndexChanged.connect(lambda _index: _populate_item_finder_grid())
            finder_clear_button.clicked.connect(finder_search.clear)
            item_grid.verticalScrollBar().valueChanged.connect(lambda _value: _queue_item_finder_donor_icons_coalesced(80))
            item_grid.itemSelectionChanged.connect(_refresh_item_finder_candidates)
            item_grid.itemDoubleClicked.connect(lambda _item: _choose_item_finder_candidate(recommended=True))
            candidate_tree.currentItemChanged.connect(lambda _current, _previous: _refresh_candidate_button())
            candidate_tree.itemDoubleClicked.connect(lambda _item, _column: _choose_item_finder_candidate(recommended=False))
            use_recommended_button.clicked.connect(lambda _checked=False: _choose_item_finder_candidate(recommended=True))
            use_candidate_button.clicked.connect(lambda _checked=False: _choose_item_finder_candidate(recommended=False))
            finder_cancel_button.clicked.connect(finder.reject)
            self.archive_item_icon_prepared_callbacks.append(_handle_item_finder_donor_icon_prepared)
            _populate_item_finder_grid()
            try:
                if finder.exec() == QDialog.Accepted:
                    donor = finder_result.get("donor")
                    if isinstance(donor, ArchiveEntry):
                        result["donor"] = donor
                        picker.accept()
            finally:
                try:
                    self.archive_item_icon_prepared_callbacks.remove(_handle_item_finder_donor_icon_prepared)
                except ValueError:
                    pass
                finder_icon_timer.stop()
                finder_icon_visible_timer.stop()
                finder_icon_queue.clear()
                _write_ui_breadcrumb({"phase": "placement_item_finder_closed", "target_path": target_entry.path})
                _write_heartbeat("running")

        def _map_loose_file_to_archive_entries(path: Path) -> Tuple[ArchiveEntry, ...]:
            basename = path.name.strip().casefold()
            candidates: List[ArchiveEntry] = []
            seen: set[AttachmentDonorKey] = set()
            for entry in self.archive_entries_by_basename.get(basename, ()):
                if not _candidate_allowed(entry):
                    continue
                key = attachment_donor_entry_key(entry)
                if key in seen:
                    continue
                seen.add(key)
                candidates.append(entry)
            candidates.sort(
                key=lambda entry: (
                    0 if "/weapon/" in str(entry.path or "").replace("\\", "/").casefold() else 1,
                    0 if str(entry.extension or "").lower() in {".pac", ".prefab"} else 1,
                    str(entry.path or "").casefold(),
                )
            )
            return tuple(candidates[:4])

        def _add_loose_donor_folder() -> None:
            folder_text = QFileDialog.getExistingDirectory(
                picker,
                "Choose Loose Donor Folder",
                str(Path.home()),
            )
            if not folder_text:
                return
            folder = Path(folder_text)
            files_root = folder / "files" if (folder / "files").is_dir() else folder
            local_suffixes = (
                ".pac",
                ".pam",
                ".pamlod",
                ".prefab",
                ".hkx",
                ".hkt",
                ".paa",
                ".motionblending",
                ".sockets.xml",
                ".pac_xml",
                ".prefabdata_xml",
                ".prefabdata.xml",
            )
            mapped = 0
            existing_keys = {attachment_donor_entry_key(entry) for entry, _path, _note in loose_donor_candidates}
            try:
                local_files = list(files_root.rglob("*"))
            except OSError as exc:
                QMessageBox.warning(picker, "Loose Donor Folder", f"Could not read loose donor folder:\n{exc}")
                return
            for local_path in local_files:
                if not local_path.is_file():
                    continue
                lower_name = local_path.name.casefold()
                if not any(lower_name.endswith(suffix) for suffix in local_suffixes):
                    continue
                for entry in _map_loose_file_to_archive_entries(local_path):
                    key = attachment_donor_entry_key(entry)
                    if key in existing_keys:
                        continue
                    existing_keys.add(key)
                    loose_donor_candidates.append(
                        (
                            entry,
                            local_path,
                            f"mapped from {local_path.name}",
                        )
                    )
                    mapped += 1
                if mapped >= 800:
                    break
            status.setText(
                f"Added {mapped:,} archive-mapped donor candidate(s) from {folder}. "
                "Loose files can be selected by their .pac/.prefab/.hkx names; CDMW resolves the archive placement family for comparison. "
                "These files are placement sources only; the opened target remains the asset being changed."
            )
            _start_scan()

        def _accept_current() -> None:
            item = tree.currentItem()
            if item is None:
                return
            donor = item.data(0, Qt.UserRole)
            if not isinstance(donor, ArchiveEntry):
                return
            result["donor"] = donor
            picker.accept()

        def _handle_source_picker_selection_changed(current: Optional[QTreeWidgetItem], _previous: Optional[QTreeWidgetItem]) -> None:
            _refresh_compare_button()
            entry = current.data(0, Qt.UserRole) if current is not None else None
            update_source_preview(entry)

        debounce_timer.timeout.connect(_start_scan)
        search_step_timer.timeout.connect(_continue_index_search)
        search_edit.textChanged.connect(lambda _text: debounce_timer.start())
        search_edit.returnPressed.connect(_start_scan)
        search_button.clicked.connect(lambda _checked=False: _start_scan())
        item_finder_button.clicked.connect(lambda _checked=False: _open_item_finder_donor_picker())
        loose_folder_button.clicked.connect(lambda _checked=False: _add_loose_donor_folder())
        tree.currentItemChanged.connect(_handle_source_picker_selection_changed)
        tree.itemDoubleClicked.connect(lambda _item, _column: _accept_current())
        compare_button.clicked.connect(lambda _checked=False: _accept_current())
        cancel_button.clicked.connect(picker.reject)
        search_edit.setFocus(Qt.FocusReason.OtherFocusReason)

        picker_layout_state = {"mode": ""}

        def _apply_picker_responsive_layout(*, force_sizes: bool = False) -> None:
            width = max(1, int(picker.width()))
            compact = width < 980
            mode = "compact" if compact else "wide"
            mode_changed = str(picker_layout_state.get("mode") or "") != mode
            picker_layout_state["mode"] = mode
            if compact:
                if placement_source_splitter.orientation() != Qt.Vertical:
                    placement_source_splitter.setOrientation(Qt.Vertical)
                placement_source_preview_widget.setMinimumWidth(0)
                if force_sizes or mode_changed:
                    placement_source_splitter.setSizes([360, 280])
            else:
                if placement_source_splitter.orientation() != Qt.Horizontal:
                    placement_source_splitter.setOrientation(Qt.Horizontal)
                placement_source_preview_widget.setMinimumWidth(320)
                if force_sizes or mode_changed:
                    placement_source_splitter.setSizes([max(560, int(width * 0.62)), max(320, int(width * 0.32))])

        previous_picker_resize_event = picker.resizeEvent

        def _responsive_picker_resize_event(event: object) -> None:
            previous_picker_resize_event(event)
            QTimer.singleShot(0, _apply_picker_responsive_layout)

        picker.resizeEvent = _responsive_picker_resize_event  # type: ignore[method-assign]

        def _fit_picker_to_screen() -> None:
            screen = picker.screen() or self.screen() or QApplication.primaryScreen()
            if screen is None:
                _apply_picker_responsive_layout(force_sizes=True)
                return
            available = screen.availableGeometry()
            max_width = min(max(760, int(float(available.width()) * 0.92)), max(640, available.width() - 24))
            max_height = min(max(540, int(float(available.height()) * 0.88)), max(420, available.height() - 24))
            picker.resize(min(max_width, max(980, picker.sizeHint().width())), min(max_height, max(620, picker.sizeHint().height())))
            _apply_picker_responsive_layout(force_sizes=True)
            frame = picker.frameGeometry()
            frame.moveCenter(available.center())
            left = max(available.left(), min(frame.left(), available.right() - frame.width() + 1))
            top = max(available.top(), min(frame.top(), available.bottom() - frame.height() + 1))
            picker.move(left, top)

        _fit_picker_to_screen()
        QTimer.singleShot(0, _fit_picker_to_screen)
        try:
            if picker.exec() == QDialog.Accepted:
                donor = result.get("donor")
                if isinstance(donor, ArchiveEntry):
                    return donor
        finally:
            close_source_preview(wait=True)
        return None


__all__ = ["ArchiveAttachmentDonorPickerDialogMixin"]
