"""Archive browser Item Finder scope and preview helpers."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path, PurePosixPath
from typing import List, Optional, Tuple

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QMessageBox

from cdmw.constants import ARCHIVE_STRUCTURE_FILTER
from cdmw.domain.archives.constants import ARCHIVE_MESH_EXTENSIONS
from cdmw.services.archive_query_service import (
    find_archive_model_related_entries as _find_archive_model_related_entries,
    build_archive_relationship_references,
    sort_archive_entries_for_browser,
)
from cdmw.domain.archives.format import is_material_sidecar_extension as _is_material_sidecar_extension
from cdmw.services.archive_preview_service import ensure_archive_preview_source
from cdmw.domain.archives.filters import order_archive_entries_by_active_overrides
from cdmw.services.preview_workflow_service import ensure_dds_display_preview_png
from cdmw.services.texture_workflow_service import classify_texture_type
from cdmw.models import ArchiveEntry


class ArchiveAssetCatalogScopeMixin:
    """Item Finder scope resolution, thumbnail fallback, and direct Archive Browser scope."""
    def _archive_asset_catalog_row_values(self, row: Mapping[str, object], key: str) -> List[str]:
        raw = row.get(key)
        if isinstance(raw, Sequence) and not isinstance(raw, (str, bytes, bytearray)):
            return [str(value) for value in raw if str(value or "").strip()]
        return []

    def _resolve_archive_asset_catalog_path_candidates(
        self,
        value: str,
        *,
        fallback_extensions: Sequence[str] = (),
    ) -> List[ArchiveEntry]:
        normalized = str(value or "").replace("\\", "/").strip()
        if not normalized:
            return []

        candidates: List[ArchiveEntry] = []
        seen: set[Tuple[str, str, int]] = set()

        def add_entry(entry: ArchiveEntry) -> None:
            key = (entry.path.lower(), str(entry.pamt_path).lower(), int(entry.offset))
            if key not in seen:
                candidates.append(entry)
                seen.add(key)

        def add_by_path_or_basename(candidate_text: str) -> None:
            candidate = str(candidate_text or "").replace("\\", "/").strip()
            if not candidate:
                return
            candidate_lower = candidate.lower()
            for entry in self.archive_entries_by_normalized_path.get(candidate_lower, ()):
                add_entry(entry)
            basename = PurePosixPath(candidate).name.strip().lower()
            if basename:
                for entry in self.archive_entries_by_basename.get(basename, ()):
                    add_entry(entry)

        add_by_path_or_basename(normalized)
        suffix = PurePosixPath(normalized).suffix
        if not suffix:
            for extension in fallback_extensions:
                ext = str(extension or "").strip()
                if ext and not ext.startswith("."):
                    ext = f".{ext}"
                add_by_path_or_basename(f"{normalized}{ext}")
        return candidates

    def _resolve_archive_asset_catalog_scope_entries(
        self,
        row: Mapping[str, object],
        *,
        include_related: bool = True,
    ) -> Tuple[List[ArchiveEntry], int, int]:
        scoped_entries: List[ArchiveEntry] = []
        seen: set[Tuple[str, str, int]] = set()
        primary_count = 0
        related_count = 0

        def add_entry(entry: ArchiveEntry, *, primary: bool) -> bool:
            nonlocal primary_count, related_count
            key = (entry.path.lower(), str(entry.pamt_path).lower(), int(entry.offset))
            if key in seen:
                return False
            scoped_entries.append(entry)
            seen.add(key)
            if primary:
                primary_count += 1
            else:
                related_count += 1
            return True

        primary_sources: List[ArchiveEntry] = []
        for value in self._archive_asset_catalog_row_values(row, "pac_files"):
            for entry in self._resolve_archive_asset_catalog_path_candidates(
                value,
                fallback_extensions=(".pac", ".pam", ".pamlod", ".prefab", ".pact"),
            ):
                if add_entry(entry, primary=True):
                    primary_sources.append(entry)
        for value in self._archive_asset_catalog_row_values(row, "model_stems"):
            for entry in self._resolve_archive_asset_catalog_path_candidates(
                value,
                fallback_extensions=(".pac", ".pam", ".pamlod", ".prefab", ".pact"),
            ):
                if add_entry(entry, primary=True):
                    primary_sources.append(entry)
        for value in self._archive_asset_catalog_row_values(row, "icon_paths"):
            for entry in self._resolve_archive_asset_catalog_path_candidates(
                value,
                fallback_extensions=(".dds", ".png"),
            ):
                add_entry(entry, primary=True)

        if include_related:
            for source_entry in primary_sources[:24]:
                for candidate in _find_archive_model_related_entries(source_entry, self.archive_entries_by_basename):
                    add_entry(candidate, primary=False)
                for reference in build_archive_relationship_references(
                    source_entry,
                    archive_entries_by_normalized_path=self.archive_entries_by_normalized_path,
                    archive_entries_by_basename=self.archive_entries_by_basename,
                ):
                    resolved_entry = getattr(reference, "resolved_entry", None)
                    if isinstance(resolved_entry, ArchiveEntry):
                        add_entry(resolved_entry, primary=False)

            sidecar_sources = [
                entry
                for entry in scoped_entries[primary_count:]
                if _is_material_sidecar_extension(entry.extension, PurePosixPath(entry.path.replace("\\", "/")).name.lower())
            ]
            for sidecar_entry in sidecar_sources[:12]:
                for reference in build_archive_relationship_references(
                    sidecar_entry,
                    archive_entries_by_normalized_path=self.archive_entries_by_normalized_path,
                    archive_entries_by_basename=self.archive_entries_by_basename,
                ):
                    resolved_entry = getattr(reference, "resolved_entry", None)
                    if isinstance(resolved_entry, ArchiveEntry):
                        add_entry(resolved_entry, primary=False)
                if len(scoped_entries) >= 1000:
                    break
        return scoped_entries[:1000], primary_count, related_count

    def _archive_asset_catalog_preview_pixmap(
        self,
        row: Mapping[str, object],
        size: int = 72,
    ) -> Tuple[Optional[QPixmap], str]:
        def _make_pixmap(entry: ArchiveEntry, *, generated: bool) -> Tuple[Optional[QPixmap], str]:
            try:
                source_path, _note = ensure_archive_preview_source(entry)
            except Exception:
                return None, ""
            preview_path = source_path
            if entry.extension == ".dds":
                try:
                    preview_path = ensure_dds_display_preview_png(
                        source_path,
                        max_dimension=max(32, int(size)),
                        slot_kind="base",
                    )
                except Exception as exc:
                    return None, f"Recovered DDS found, but thumbnail conversion failed: {exc}"
            pixmap = QPixmap(str(preview_path))
            if pixmap.isNull():
                return None, ""
            note_prefix = "Generated thumbnail from asset texture" if generated else "Recovered icon preview"
            return (
                pixmap.scaled(size, size, Qt.KeepAspectRatio, Qt.SmoothTransformation),
                f"{note_prefix}: {entry.path}",
            )

        icon_entries: List[ArchiveEntry] = []
        for icon_path in self._archive_asset_catalog_row_values(row, "icon_paths"):
            icon_entries.extend(
                self._resolve_archive_asset_catalog_path_candidates(icon_path, fallback_extensions=(".dds", ".png"))
            )
        for entry in icon_entries[:6]:
            pixmap, note = _make_pixmap(entry, generated=False)
            if pixmap is not None:
                return pixmap, note
            if note:
                return None, note

        scoped_entries, _primary_count, _related_count = self._resolve_archive_asset_catalog_scope_entries(row)

        def _texture_thumbnail_score(entry: ArchiveEntry) -> Tuple[int, str]:
            path_lower = entry.path.replace("\\", "/").lower()
            basename_lower = PurePosixPath(path_lower).name
            texture_type = classify_texture_type(path_lower) if entry.extension == ".dds" else "color"
            score = 100
            if entry.extension in {".png", ".jpg", ".jpeg", ".tga", ".bmp"}:
                score -= 45
            if texture_type in {"color", "ui", "emissive", "impostor"}:
                score -= 40
            if any(token in basename_lower for token in ("_base", "_basecolor", "_diffuse", "_albedo", "_color", "_col", "_d.")):
                score -= 20
            if any(token in basename_lower for token in ("icon", "thumbnail", "preview")):
                score -= 25
            if texture_type in {"normal", "mask", "roughness", "height", "vector"}:
                score += 55
            if any(token in basename_lower for token in ("_n.", "_normal", "_sp.", "_m.", "_mask", "_h.", "_disp", "_rough")):
                score += 45
            return score, entry.path

        texture_entries = [
            entry
            for entry in scoped_entries
            if entry.extension in {".dds", ".png", ".jpg", ".jpeg", ".tga", ".bmp"}
        ]
        texture_entries.sort(key=_texture_thumbnail_score)
        for entry in texture_entries[:10]:
            pixmap, note = _make_pixmap(entry, generated=True)
            if pixmap is not None:
                return pixmap, note
            if note:
                return None, note
        if icon_entries:
            return None, "Recovered icon paths were found, but none could be converted into a preview."
        return None, "No inventory icon or visible texture thumbnail could be generated for this asset row."

    def _archive_asset_catalog_inventory_icon_pixmap(
        self,
        row: Mapping[str, object],
        size: int = 48,
    ) -> Tuple[Optional[QPixmap], str]:
        for icon_path in self._archive_asset_catalog_row_values(row, "icon_paths"):
            entries = self._resolve_archive_asset_catalog_path_candidates(icon_path, fallback_extensions=(".dds", ".png"))
            for entry in entries[:4]:
                try:
                    source_path, _note = ensure_archive_preview_source(entry)
                except Exception:
                    continue
                preview_path = source_path
                if entry.extension == ".dds":
                    try:
                        preview_path = ensure_dds_display_preview_png(
                            source_path,
                            max_dimension=max(32, int(size)),
                            slot_kind="base",
                        )
                    except Exception as exc:
                        return None, f"Recovered icon DDS found, but thumbnail conversion failed: {exc}"
                pixmap = QPixmap(str(preview_path))
                if pixmap.isNull():
                    continue
                return (
                    pixmap.scaled(size, size, Qt.KeepAspectRatio, Qt.SmoothTransformation),
                    f"Recovered inventory icon: {entry.path}",
                )
        return None, "No recovered inventory icon could be resolved for this row."

    def _apply_archive_direct_scope(
        self,
        entries: Sequence[ArchiveEntry],
        *,
        scope_label: str,
        placeholder_text: str,
        hint_text: str,
        progress_text: str,
        log_text: str,
        preferred_path: str = "",
    ) -> bool:
        scoped_entries: List[ArchiveEntry] = []
        seen: set[Tuple[str, str, int]] = set()
        for entry in entries:
            if not isinstance(entry, ArchiveEntry):
                continue
            key = (entry.path.lower(), str(entry.pamt_path).lower(), int(entry.offset))
            if key in seen:
                continue
            seen.add(key)
            scoped_entries.append(entry)
        if not scoped_entries:
            return False
        scoped_entries = order_archive_entries_by_active_overrides(scoped_entries)
        if self._archive_tree_sort_active():
            scoped_entries = sort_archive_entries_for_browser(
                scoped_entries,
                self.archive_tree_sort_column,
                self.archive_tree_sort_order,
                item_display_names=self.archive_item_display_names,
                item_exact_display_names=self.archive_item_exact_display_names,
                item_related_display_names=self.archive_item_related_display_names,
                archive_entries_by_normalized_path=self.archive_entries_by_normalized_path,
            )

        self.archive_active_asset_catalog_scope = scope_label
        self.archive_filter_edit.blockSignals(True)
        try:
            self.archive_filter_edit.clear()
            self.archive_filter_edit.setPlaceholderText(placeholder_text)
        finally:
            self.archive_filter_edit.blockSignals(False)
        self.archive_exclude_filter_edit.clear()
        self._set_combo_by_value(self.archive_extension_filter_combo, "*")
        self.archive_package_filter_edit.clear()
        self.archive_structure_filter_pending_value = ARCHIVE_STRUCTURE_FILTER
        self._rebuild_archive_structure_filter_controls(ARCHIVE_STRUCTURE_FILTER)
        self._set_combo_by_value(self.archive_role_filter_combo, "all")
        self.archive_min_size_spin.setValue(0)
        self.archive_previewable_only_checkbox.setChecked(False)
        self.archive_package_filter_hint_label.setText(hint_text)
        self.archive_clear_asset_scope_button.setVisible(True)
        self.archive_filtered_entries = scoped_entries
        self.archive_filtered_dds_count = sum(1 for entry in self.archive_filtered_entries if entry.extension == ".dds")
        self._rebuild_archive_browser_indexes_for_current_sort()
        self.archive_filters_dirty = False
        self._update_archive_filter_button_state()
        self._set_archive_load_progress(progress_text, phase="Ready", percent=100)
        self.append_archive_log(log_text)
        selected_path = str(preferred_path or "").strip()
        if not selected_path and self.archive_filtered_entries:
            selected_path = self.archive_filtered_entries[0].path
        self._populate_archive_tree(selected_path, rebuild_index=False)
        return True

    def _apply_archive_asset_catalog_scope(self, row: Mapping[str, object], *, include_related: bool = True) -> None:
        display_name = str(row.get("display_name", "") or row.get("internal_name", "") or "selected asset")
        scoped_entries, primary_count, related_count = self._resolve_archive_asset_catalog_scope_entries(
            row,
            include_related=include_related,
        )
        if not scoped_entries:
            QMessageBox.information(
                self,
                "Item Finder",
                f"No archive files could be resolved for {display_name}. This row only has search hints, not exact archive paths.",
            )
            return
        scope_kind = "related set" if include_related else "exact links"
        if include_related:
            if related_count:
                hint_suffix = (
                    f"Showing {primary_count:,} direct link(s) plus {related_count:,} indexed companion file(s). "
                    "Related files can include Resolved (Partial) basename/sidecar matches. "
                    "Use Clear Scope to return to normal archive filters."
                )
                log_counts = f"{primary_count:,} direct, {related_count:,} related"
            else:
                hint_suffix = (
                    f"Showing {primary_count:,} direct link(s). No indexed companion files were found, "
                    "so this scope is the same as Exact Links for this item. "
                    "Use Clear Scope to return to normal archive filters."
                )
                log_counts = f"{primary_count:,} direct, no related files found"
        else:
            hint_suffix = (
                f"Showing only {primary_count:,} direct model/icon link(s). "
                "Use Show Related Set in Item Finder to include companions when indexed relationships exist."
            )
            log_counts = f"{primary_count:,} direct only"
        preferred_entry = next(
            (
                entry
                for entry in scoped_entries[:primary_count]
                if entry.extension.casefold() in ARCHIVE_MESH_EXTENSIONS
            ),
            scoped_entries[0],
        )
        self._apply_archive_direct_scope(
            scoped_entries,
            scope_label=f"{display_name} ({scope_kind})",
            placeholder_text=f"Item Finder scope active: {display_name} [{scope_kind}]",
            hint_text=(
                f"Item Finder scope active: {display_name} [{scope_kind}]. {hint_suffix}"
            ),
            progress_text=f"Item Finder scope: {len(scoped_entries):,} indexed file(s).",
            log_text=(
                f"Item Finder scoped Archive Browser to: {display_name} "
                f"({log_counts}; no full archive scan)."
            ),
            preferred_path=preferred_entry.path,
        )



__all__ = ["ArchiveAssetCatalogScopeMixin"]
