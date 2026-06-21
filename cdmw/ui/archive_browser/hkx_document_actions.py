"""Archive HKX document export/import and placement actions."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path, PurePosixPath
from typing import Dict, List, Optional, Tuple

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
)

from cdmw.core.archive import ensure_archive_preview_source
from cdmw.core.archive_modding import (
    ArchiveLooseExportResult,
    ArchivePatchRequest,
    HkxGeometryPatchResult,
    build_hkx_descriptor_hint_from_xml_text,
    build_hkx_editable_geometry_json,
    build_hkx_editable_geometry_xml,
    build_hkx_havok_xml_view_xml,
    export_archive_payloads_to_mod_ready_loose,
)
from cdmw.models import ArchiveEntry, AssetFamilyGraph, AssetFamilyMember


class ArchiveHkxDocumentActionsMixin:
    """HKX placement, document export/import, and editor launch actions."""
    def _archive_hkx_companion_descriptor_entries(self, entry: ArchiveEntry) -> Tuple[ArchiveEntry, ...]:
        candidates: List[ArchiveEntry] = []
        seen_paths: set[str] = set()

        def add(candidate: Optional[ArchiveEntry]) -> None:
            if not isinstance(candidate, ArchiveEntry):
                return
            if str(candidate.extension or "").lower() != ".xml":
                return
            normalized = self._normalize_archive_entry_path(candidate.path)
            if not normalized or normalized in seen_paths:
                return
            seen_paths.add(normalized)
            candidates.append(candidate)

        for reference in self._current_archive_related_references_for_entry(entry):
            add(getattr(reference, "resolved_entry", None))

        normalized_entry_path = self._normalize_archive_entry_path(entry.path)
        try:
            sibling_xml = PurePosixPath(entry.path.replace("\\", "/")).with_suffix(".xml").as_posix().lower()
        except Exception:
            sibling_xml = ""
        if sibling_xml:
            for candidate in tuple(self.archive_entries_by_normalized_path.get(sibling_xml, ()) or ()):
                add(candidate)

        stem = PurePosixPath(entry.path.replace("\\", "/")).stem.lower()
        if stem:
            for basename in (f"{stem}.xml", f"{stem}.physics.xml", f"{stem}.geometry.xml"):
                for candidate in tuple(self.archive_entries_by_basename.get(basename, ()) or ()):
                    candidate_path = self._normalize_archive_entry_path(candidate.path)
                    if candidate_path == normalized_entry_path:
                        continue
                    add(candidate)

        return tuple(candidates)

    def _build_archive_hkx_companion_descriptor_hints(
        self,
        descriptor_entries: Sequence[ArchiveEntry],
        *,
        log: Optional[Callable[[str], None]] = None,
        ) -> List[Dict[str, object]]:
        hints: List[Dict[str, object]] = []
        for descriptor_entry in descriptor_entries:
            try:
                descriptor_path, _note = ensure_archive_preview_source(descriptor_entry)
                descriptor_text = descriptor_path.read_text(encoding="utf-8", errors="replace")
                hint = build_hkx_descriptor_hint_from_xml_text(descriptor_text, descriptor_entry.path)
            except Exception as exc:
                if log is not None:
                    log(f"Skipped HKX companion descriptor {descriptor_entry.path}: {exc}")
                continue
            if hint is None:
                continue
            hints.append(hint)
        if hints and log is not None:
            log(f"Attached {len(hints):,} companion descriptor hint document(s) to the HKX converter export.")
        return hints

    def _choose_archive_hkx_placement_candidate(
        self,
        source_entry: ArchiveEntry,
        candidates: Sequence[ArchiveEntry],
        ) -> Optional[ArchiveEntry]:
        ordered_candidates = tuple(candidate for candidate in candidates if self._archive_entry_is_hkx(candidate))
        if not ordered_candidates:
            return None
        if len(ordered_candidates) == 1:
            return ordered_candidates[0]

        try:
            graph, _references = self._archive_asset_family_graph_for_entry(source_entry)
        except Exception:
            graph = None
        member_by_key: Dict[Tuple[str, str, int], AssetFamilyMember] = {}
        if isinstance(graph, AssetFamilyGraph):
            for member in tuple(getattr(graph, "member_rows", ()) or ()):
                if not isinstance(member, AssetFamilyMember):
                    continue
                resolved_entry = getattr(member, "resolved_entry", None)
                if not self._archive_entry_is_hkx(resolved_entry):
                    continue
                assert isinstance(resolved_entry, ArchiveEntry)
                member_by_key[self._attachment_package_entry_key(resolved_entry)] = member

        dialog = QDialog(self)
        dialog.setWindowTitle(f"Choose HKX Placement - {source_entry.basename}")
        dialog.resize(860, 420)
        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)
        intro = QLabel(
            f"{source_entry.basename} has multiple related HKX/HKT files. Choose which one to open on the Placement view."
        )
        intro.setObjectName("HintLabel")
        intro.setWordWrap(True)
        layout.addWidget(intro)

        tree = QTreeWidget()
        tree.setColumnCount(5)
        tree.setHeaderLabels(["HKX / HKT", "Role", "Status", "Evidence", "Archive Path"])
        tree.setRootIsDecorated(False)
        tree.setAlternatingRowColors(True)
        tree.setUniformRowHeights(True)
        tree.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        tree.setEditTriggers(QAbstractItemView.NoEditTriggers)
        layout.addWidget(tree, stretch=1)

        for candidate in ordered_candidates:
            member = member_by_key.get(self._attachment_package_entry_key(candidate))
            role = str(getattr(member, "role", "") or "HKX / Physics") if isinstance(member, AssetFamilyMember) else "HKX / Physics"
            status = str(getattr(member, "status", "") or "Resolved") if isinstance(member, AssetFamilyMember) else "Resolved"
            evidence = (
                str(getattr(member, "source_evidence", "") or getattr(member, "confidence", "") or "related family HKX")
                if isinstance(member, AssetFamilyMember)
                else "related family HKX"
            )
            item = QTreeWidgetItem([candidate.basename, role, status, evidence, candidate.path])
            item.setData(0, Qt.ItemDataRole.UserRole, candidate)
            for column in range(tree.columnCount()):
                item.setToolTip(column, item.text(column))
            self._ui_style_status_columns(item, {2: status, 3: evidence})
            tree.addTopLevelItem(item)

        for column in range(tree.columnCount()):
            tree.resizeColumnToContents(column)
        if tree.topLevelItemCount() > 0:
            tree.setCurrentItem(tree.topLevelItem(0))

        button_row = QHBoxLayout()
        button_row.addStretch(1)
        cancel_button = QPushButton("Cancel")
        open_button = QPushButton("Open Placement")
        button_row.addWidget(cancel_button)
        button_row.addWidget(open_button)
        layout.addLayout(button_row)

        result: Dict[str, object] = {}

        def _accept_selected() -> None:
            item = tree.currentItem()
            selected_entry = item.data(0, Qt.ItemDataRole.UserRole) if item is not None else None
            if not self._archive_entry_is_hkx(selected_entry):
                return
            result["entry"] = selected_entry
            dialog.accept()

        tree.itemDoubleClicked.connect(lambda _item, _column: _accept_selected())
        open_button.clicked.connect(lambda _checked=False: _accept_selected())
        cancel_button.clicked.connect(dialog.reject)
        if dialog.exec() == QDialog.Accepted:
            selected = result.get("entry")
            if self._archive_entry_is_hkx(selected):
                assert isinstance(selected, ArchiveEntry)
                return selected
        return None

    def _open_archive_hkx_placement_for_entry(self, entry: Optional[ArchiveEntry]) -> None:
        if not isinstance(entry, ArchiveEntry):
            self.set_status_message("Select a model or HKX/HKT archive entry first.", error=True)
            return
        candidates = self._archive_hkx_placement_candidates_for_entry(entry)
        if not candidates:
            self.set_status_message(
                f"No related HKX/HKT placement file was resolved for {entry.basename}. Open Asset Family to inspect related files.",
                error=True,
            )
            return
        selected = self._choose_archive_hkx_placement_candidate(entry, candidates)
        if not isinstance(selected, ArchiveEntry):
            return
        if self.worker_thread is None:
            self._edit_archive_hkx_entry(selected, initial_section="Placement")
        else:
            self._edit_archive_hkx_entry_when_idle(selected, initial_section="Placement")

    def _open_current_archive_hkx_placement(self) -> None:
        self._open_archive_hkx_placement_for_entry(self._current_archive_entry())

    def _export_current_archive_hkx_document(
        self,
        *,
        entry: ArchiveEntry,
        document_label: str,
        default_target: Path,
        file_filter: str,
        default_suffix: str,
        build_document: Callable[..., str],
        editable_document: bool = True,
        ) -> None:
        selected, _selected_filter = QFileDialog.getSaveFileName(
            self,
            f"Export HKX Geometry {document_label}",
            str(default_target),
            file_filter,
        )
        if not selected:
            return

        output_path = Path(selected)
        if not output_path.suffix:
            output_path = output_path.with_name(f"{output_path.name}{default_suffix}")
        descriptor_entries = self._archive_hkx_companion_descriptor_entries(entry)

        def _task(log: Callable[[str], None]) -> Path:
            export_kind = "editable HKX geometry" if editable_document else "read-only HKX browser"
            log(f"Exporting {export_kind} {document_label} for {entry.path}...")
            source_path, _note = ensure_archive_preview_source(entry)
            descriptor_hints = self._build_archive_hkx_companion_descriptor_hints(
                descriptor_entries,
                log=log,
            )
            document_text = build_document(source_path.read_bytes(), entry.path, descriptor_hints)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(document_text, encoding="utf-8")
            return output_path

        def _handle_complete(result: object) -> None:
            exported_path = result if isinstance(result, Path) else output_path
            QMessageBox.information(
                self,
                f"HKX {document_label} Export Complete",
                (
                    f"Exported {'editable HKX geometry' if editable_document else 'read-only HKX browser'} {document_label}:\n{exported_path}\n\n"
                    + (
                        "Descriptions are included for known values. On import, only supported numeric geometry fields are applied."
                        if editable_document
                        else "This is a read-only hkpackfile/hkobject/hkparam view for browsing and comparison; use CDMW JSON/XML for imports."
                    )
                ),
            )
            self.set_status_message(f"Exported HKX geometry {document_label} for {entry.basename}.")

        self._run_utility_task(
            status_message=f"Exporting HKX geometry {document_label} for {entry.basename}...",
            task=_task,
            on_complete=_handle_complete,
            show_archive_progress=True,
        )

    def _export_current_archive_hkx_json(self) -> None:
        entry = self._current_archive_hkx_entry()
        if entry is None:
            self.set_status_message("Select a Crimson Desert .hkx/.hkt archive entry to export editable JSON.", error=True)
            return

        self._export_current_archive_hkx_document(
            entry=entry,
            document_label="JSON",
            default_target=self._default_archive_hkx_json_path(entry),
            file_filter="HKX Geometry JSON (*.geometry.json *.json);;JSON (*.json)",
            default_suffix=".geometry.json",
            build_document=build_hkx_editable_geometry_json,
        )

    def _export_current_archive_hkx_xml(self) -> None:
        entry = self._current_archive_hkx_entry()
        if entry is None:
            self.set_status_message("Select a Crimson Desert .hkx/.hkt archive entry to export editable XML.", error=True)
            return

        self._export_current_archive_hkx_document(
            entry=entry,
            document_label="XML",
            default_target=self._default_archive_hkx_xml_path(entry),
            file_filter="HKX Geometry XML (*.geometry.xml *.xml);;XML (*.xml)",
            default_suffix=".geometry.xml",
            build_document=build_hkx_editable_geometry_xml,
        )

    def _export_current_archive_hkx_havok_xml_view(self) -> None:
        entry = self._current_archive_hkx_entry()
        if entry is None:
            self.set_status_message("Select a Crimson Desert .hkx/.hkt archive entry to export a Havok XML view.", error=True)
            return

        self._export_current_archive_hkx_document(
            entry=entry,
            document_label="Havok XML View",
            default_target=self._default_archive_hkx_havok_xml_view_path(entry),
            file_filter="HKX Havok XML View (*.havok-view.xml *.xml);;XML (*.xml)",
            default_suffix=".havok-view.xml",
            build_document=build_hkx_havok_xml_view_xml,
            editable_document=False,
        )

    def _start_current_archive_hkx_document_import_content(
        self,
        *,
        entry: ArchiveEntry,
        document_text: str,
        document_source_label: str,
        document_label: str,
        apply_document: Callable[[bytes, str], HkxGeometryPatchResult],
        ) -> None:
        loose_export_settings = self._collect_archive_mod_ready_export_target(
            browse_title="Select HKX Mod-Ready Export Parent Root",
            prompt_for_metadata=True,
            initial_include_related_files=False,
            show_include_related_files_option=False,
            dialog_title="HKX Loose Mod Metadata",
            allow_dmm_texture_structure=False,
        )
        if loose_export_settings is None:
            return
        parent_root, package_info, create_no_encrypt_file, _include_related_files, export_options = loose_export_settings

        def _task(log: Callable[[str], None]) -> Dict[str, object]:
            log(f"Reading current HKX payload for {entry.path}...")
            source_path, _note = ensure_archive_preview_source(entry)
            source_data = source_path.read_bytes()
            log(f"Applying HKX {document_label} patch document from {document_source_label}...")
            patch_result = apply_document(source_data, document_text)
            for warning in patch_result.warnings:
                log(f"Warning: {warning}")
            if not patch_result.changed_fields:
                log("No supported numeric HKX differences were found; loose mod export was skipped.")
                return {"geometry_patch": patch_result, "loose_export": None}
            log(
                f"Writing {len(patch_result.changed_fields):,} changed HKX field(s) "
                "into a mod-ready loose package..."
            )
            loose_export = export_archive_payloads_to_mod_ready_loose(
                [ArchivePatchRequest(entry=entry, payload_data=patch_result.data)],
                parent_root=parent_root,
                package_info=package_info,
                export_options=export_options,
                create_no_encrypt_file=create_no_encrypt_file,
                on_log=log,
            )
            return {"geometry_patch": patch_result, "loose_export": loose_export}

        def _handle_complete(result: object) -> None:
            if not isinstance(result, dict):
                self.set_status_message(f"HKX {document_label} import finished with an unexpected result payload.", error=True)
                return
            geometry_patch = result.get("geometry_patch")
            loose_export = result.get("loose_export")
            changed_fields = (
                list(geometry_patch.changed_fields)
                if isinstance(geometry_patch, HkxGeometryPatchResult)
                else []
            )
            warnings = (
                list(geometry_patch.warnings)
                if isinstance(geometry_patch, HkxGeometryPatchResult)
                else []
            )
            warning_text = "\n".join(f"- {warning}" for warning in warnings[:10])
            if isinstance(loose_export, ArchiveLooseExportResult):
                summary = "\n".join(f"- {field}" for field in changed_fields[:12])
                if len(changed_fields) > 12:
                    summary += f"\n- ... {len(changed_fields) - 12:,} more field(s)"
                message = (
                    f"Wrote edited HKX loose mod package:\n{loose_export.package_root}\n\n"
                    f"Target entry:\n{entry.path}\n\n"
                    f"Changed fields:\n{summary}\n\n"
                    "The installed game archives were not modified."
                )
                if warning_text:
                    message += f"\n\nWarnings:\n{warning_text}"
                QMessageBox.information(self, f"HKX {document_label} Import Complete", message)
                self.set_status_message(
                    f"Wrote HKX {document_label} edits for {entry.basename} as a mod-ready loose package."
                )
                return

            message = "No supported numeric geometry differences were found. No loose mod package was written."
            if warning_text:
                message += f"\n\nWarnings:\n{warning_text}"
            QMessageBox.information(self, f"HKX {document_label} Import", message)
            self.set_status_message(f"HKX {document_label} import found no supported numeric geometry changes.")

        self._run_utility_task(
            status_message=f"Importing HKX geometry {document_label} for {entry.basename}...",
            task=_task,
            on_complete=_handle_complete,
            show_archive_progress=True,
        )

    def _start_current_archive_hkx_document_import(
        self,
        *,
        entry: ArchiveEntry,
        document_path: Path,
        document_label: str,
        apply_document: Callable[[bytes, str], HkxGeometryPatchResult],
        ) -> None:
        try:
            document_text = document_path.read_text(encoding="utf-8")
        except Exception as exc:
            QMessageBox.warning(self, f"HKX {document_label} Import", f"Could not read HKX {document_label} document:\n{exc}")
            self.set_status_message(f"HKX {document_label} import failed: {exc}", error=True)
            return

        self._start_current_archive_hkx_document_import_content(
            entry=entry,
            document_text=document_text,
            document_source_label=str(document_path),
            document_label=document_label,
            apply_document=apply_document,
        )

    def _edit_current_archive_hkx(self) -> None:
        entry = self._current_archive_hkx_entry()
        if entry is None:
            self.set_status_message("Select a Crimson Desert .hkx/.hkt archive entry to edit.", error=True)
            return
        self._edit_archive_hkx_entry(entry)

    def _edit_archive_hkx_entry(self, entry: ArchiveEntry, *, initial_section: str = "") -> None:
        descriptor_entries = self._archive_hkx_companion_descriptor_entries(entry)

        def _task(log: Callable[[str], None]) -> str:
            log(f"Building editable HKX XML for {entry.path}...")
            source_path, _note = ensure_archive_preview_source(entry)
            descriptor_hints = self._build_archive_hkx_companion_descriptor_hints(descriptor_entries, log=log)
            return build_hkx_editable_geometry_xml(source_path.read_bytes(), entry.path, descriptor_hints)

        def _handle_complete(result: object) -> None:
            if not isinstance(result, str):
                self.set_status_message("HKX editor could not build an editable XML document.", error=True)
                return
            self._open_archive_hkx_editor_dialog(entry, result, initial_section=initial_section)

        self._run_utility_task(
            status_message=f"Opening HKX editor for {entry.basename}...",
            task=_task,
            on_complete=_handle_complete,
            show_archive_progress=True,
        )

    def _edit_archive_hkx_entry_when_idle(
        self,
        entry: ArchiveEntry,
        *,
        attempt: int = 0,
        initial_section: str = "",
        ) -> None:
        if self.worker_thread is None:
            self._edit_archive_hkx_entry(entry, initial_section=initial_section)
            return
        if attempt == 0:
            self.set_status_message(f"Opening HKX editor for {entry.basename} after the preview task finishes...")
            self.append_log(f"Waiting for referenced-file preview cleanup before opening HKX editor for {entry.path}.")
        if attempt >= 100:
            message = "Could not open the HKX editor because the previous preview task did not finish cleanly."
            self.set_status_message(message, error=True)
            self.append_log(f"ERROR: {message}")
            return
        QTimer.singleShot(
            50,
            lambda current_entry=entry, next_attempt=attempt + 1, requested_section=initial_section: self._edit_archive_hkx_entry_when_idle(
                current_entry,
                attempt=next_attempt,
                initial_section=requested_section,
            ),
        )

__all__ = ["ArchiveHkxDocumentActionsMixin"]
