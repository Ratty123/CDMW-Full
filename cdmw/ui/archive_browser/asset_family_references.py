"""Archive browser known-reference relationship helpers."""

from __future__ import annotations

import re
from pathlib import PurePosixPath
from typing import List, Optional, Sequence, Tuple

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QCheckBox, QDialog, QHBoxLayout, QLabel, QMenu, QPushButton, QTreeWidget, QTreeWidgetItem, QVBoxLayout

from cdmw.core.archive_modding import ARCHIVE_MESH_EXTENSIONS
from cdmw.core.archive import _strip_archive_model_family_variant_suffix, derive_texture_group_key
from cdmw.core.material_sidecar_editor import is_material_sidecar_entry
from cdmw.core.upscale_profiles import normalize_texture_reference_for_sidecar_lookup
from cdmw.models import ArchiveEntry, ArchiveModelTextureReference, RelationConfidence


class ArchiveAssetFamilyReferenceMixin:
    """Known used-by relationships and user-facing relation labels."""
    @staticmethod
    def _archive_family_badge(path_value: str) -> str:
        normalized = str(path_value or "").replace("\\", "/").strip().lower()
        if not normalized:
            return "Unknown"
        parts = [part for part in PurePosixPath(normalized).parts if part]
        if parts and re.fullmatch(r"\d{4}", parts[0]):
            parts = parts[1:]
        joined = "/".join(parts)
        if joined.startswith("leveldata/"):
            return "Proxy LOD" if "/proxylod/" in joined else "Leveldata"
        if joined.startswith("effect/"):
            return "Effect"
        if joined.startswith("object/"):
            return "Object"
        if joined.startswith("ui/"):
            return "UI"
        if joined.startswith("tree/"):
            return "Tree"
        if joined.startswith("character/"):
            if "/2_mon/" in joined:
                return "Monster"
            if "/4_riding/" in joined:
                return "Riding"
            if "/3_npc/" in joined:
                return "NPC"
            if "/1_pc/" in joined:
                return "Character"
            if "/6_object/" in joined:
                return "Character Object"
            return "Character"
        return "Unknown"

    @staticmethod
    def _archive_relation_confidence_label(value: str) -> str:
        normalized = str(value or "").strip().lower()
        return {
            RelationConfidence.AUTHORITATIVE.value: "Authoritative",
            RelationConfidence.EXACT_PATH.value: "Exact path",
            RelationConfidence.PATH_NORMALIZED.value: "Path normalized",
            RelationConfidence.CROSS_PACKAGE.value: "Cross-package",
            RelationConfidence.DERIVED_SAME_STEM.value: "Same basename",
            RelationConfidence.DERIVED_FAMILY_HEURISTIC.value: "Family skeleton",
        }.get(normalized, normalized.replace("_", " ").title() if normalized else "")

    def _archive_known_used_by_references(self, entry: Optional[ArchiveEntry]) -> List[ArchiveModelTextureReference]:
        if not isinstance(entry, ArchiveEntry):
            return []
        used_by: List[ArchiveModelTextureReference] = []
        seen: set[Tuple[str, str, int]] = set()

        def add(candidate: ArchiveEntry, *, reason: str, confidence: str, group: str) -> None:
            key = (candidate.path.lower(), str(candidate.pamt_path).lower(), int(candidate.offset))
            if key in seen or candidate.path == entry.path:
                return
            seen.add(key)
            used_by.append(
                ArchiveModelTextureReference(
                    reference_name=candidate.basename,
                    resolution_status="resolved",
                    resolved_archive_path=candidate.path,
                    resolved_package_label=candidate.package_label,
                    resolved_entry=candidate,
                    reference_kind="used_by",
                    relation_group=group,
                    relation_reason=reason,
                    relation_confidence=confidence,
                )
            )

        normalized_path = normalize_texture_reference_for_sidecar_lookup(entry.path)
        basename = PurePosixPath(normalized_path).name if normalized_path else entry.basename.lower()
        if entry.extension == ".dds" and normalized_path:
            texture_sidecars: List[ArchiveEntry] = []
            seen_sidecars: set[Tuple[str, str, int]] = set()
            texture_stem_candidates: List[str] = []
            seen_texture_stems: set[str] = set()

            def add_texture_stem_candidate(raw_value: str) -> None:
                raw_text = str(raw_value or "").replace("\\", "/").strip().casefold()
                if not raw_text:
                    return
                stem = PurePosixPath(raw_text).stem.casefold()
                for prefix in ("itemicon_prefab_", "itemicon_", "icon_prefab_", "icon_"):
                    if stem.startswith(prefix):
                        stripped = stem[len(prefix):].strip("_")
                        if stripped and stripped not in seen_texture_stems:
                            texture_stem_candidates.append(stripped)
                            seen_texture_stems.add(stripped)
                grouped = derive_texture_group_key(raw_text).strip().casefold()
                grouped_stem = PurePosixPath(grouped).stem.casefold() if grouped else ""
                family_stem = _strip_archive_model_family_variant_suffix(grouped_stem or stem).strip().casefold()
                for candidate_stem in (stem, grouped_stem, family_stem):
                    if candidate_stem and candidate_stem not in seen_texture_stems:
                        texture_stem_candidates.append(candidate_stem)
                        seen_texture_stems.add(candidate_stem)

            def add_model_candidates_for_stem(stem: str, *, reason: str, confidence: str) -> None:
                for extension in (".pac", ".pam", ".pamlod"):
                    for candidate in self.archive_entries_by_basename.get(f"{stem}{extension}", ()):
                        add(
                            candidate,
                            reason=reason,
                            confidence=confidence,
                            group="Used By / Model",
                        )

            def add_material_sidecar_candidates_for_stem(stem: str) -> None:
                for extension in (".pac_xml", ".pam_xml", ".pamlod_xml", ".pami"):
                    for candidate in self.archive_entries_by_basename.get(f"{stem}{extension}", ()):
                        add_texture_sidecar(
                            candidate,
                            reason=(
                                "Material sidecar shares the selected texture stem; this is an indexed same-stem hint, "
                                "not a live archive scan."
                            ),
                            confidence=RelationConfidence.DERIVED_SAME_STEM.value,
                        )

            def add_texture_sidecar(candidate: ArchiveEntry, *, reason: str, confidence: str) -> None:
                sidecar_key = (candidate.path.lower(), str(candidate.pamt_path).lower(), int(candidate.offset))
                if sidecar_key in seen_sidecars:
                    return
                seen_sidecars.add(sidecar_key)
                texture_sidecars.append(candidate)
                add(
                    candidate,
                    reason=reason,
                    confidence=confidence,
                    group="Used By / Material",
                )

            for candidate in self.archive_sidecar_entries_by_texture_path.get(normalized_path, ()):
                add_texture_sidecar(
                    candidate,
                    reason="Material sidecar references this exact texture path.",
                    confidence=RelationConfidence.EXACT_PATH.value,
                )
            for candidate in self.archive_sidecar_entries_by_texture_basename.get(basename, ()):
                add_texture_sidecar(
                    candidate,
                    reason="Material sidecar references this texture basename.",
                    confidence=RelationConfidence.PATH_NORMALIZED.value,
                )
            add_texture_stem_candidate(entry.basename)
            add_texture_stem_candidate(normalized_path)
            for texture_stem in texture_stem_candidates:
                add_material_sidecar_candidates_for_stem(texture_stem)
                add_model_candidates_for_stem(
                    texture_stem,
                    reason=(
                        "Model shares the selected texture stem in the current archive index; "
                        "shown as a same-stem relationship hint."
                    ),
                    confidence=RelationConfidence.DERIVED_SAME_STEM.value,
                )
            for sidecar_entry in texture_sidecars:
                stem = PurePosixPath(sidecar_entry.basename).stem.casefold()
                if not stem:
                    continue
                add_model_candidates_for_stem(
                    stem,
                    reason=(
                        "Model candidate shares the basename with a material sidecar that references this texture: "
                        f"{sidecar_entry.basename}."
                    ),
                    confidence=RelationConfidence.DERIVED_SAME_STEM.value,
                )
        if entry.extension in {".hkx", ".hkt"}:
            stem = PurePosixPath(entry.basename).stem.casefold()
            for extension in (".pac", ".pam", ".pamlod", ".prefab"):
                for candidate in self.archive_entries_by_basename.get(f"{stem}{extension}", ()):
                    add(
                        candidate,
                        reason="Candidate shares the HKX basename in the current archive index.",
                        confidence=RelationConfidence.DERIVED_SAME_STEM.value,
                        group="Used By / Model" if extension in {".pac", ".pam", ".pamlod"} else "Used By / Metadata",
                    )
        if is_material_sidecar_entry(entry):
            stem = PurePosixPath(entry.basename).stem.casefold()
            for extension in (".pac", ".pam", ".pamlod"):
                for candidate in self.archive_entries_by_basename.get(f"{stem}{extension}", ()):
                    add(
                        candidate,
                        reason="Model candidate shares the material sidecar basename in the current archive index.",
                        confidence=RelationConfidence.DERIVED_SAME_STEM.value,
                        group="Used By / Model",
                    )
        if entry.extension in {".pac", ".pam", ".pamlod"}:
            stem = PurePosixPath(entry.basename).stem.casefold()
            for extension in (".prefab", ".prefabdata_xml", ".prefabdata.xml"):
                for candidate in self.archive_entries_by_basename.get(f"{stem}{extension}", ()):
                    add(
                        candidate,
                        reason="Prefab/metadata candidate shares the model basename in the current archive index.",
                        confidence=RelationConfidence.DERIVED_SAME_STEM.value,
                        group="Used By / Metadata",
                    )
        return used_by





    def _scope_archive_asset_family_for_entry(self, entry: ArchiveEntry, *, include_hints: bool = False) -> None:
        graph, _references = self._archive_asset_family_graph_for_entry(entry)
        entries = self._archive_entries_from_asset_family_graph(graph, include_hints=include_hints)
        if not entries:
            self.set_status_message("No resolved family entries are available to scope.", error=True)
            return
        suffix = " + hints" if include_hints else ""
        self._scope_archive_reference_entries(entries, scope_label=f"Asset family for {entry.basename}{suffix}")

    def _export_archive_asset_family_for_entry(self, entry: ArchiveEntry, *, include_hints: bool = False) -> None:
        graph, _references = self._archive_asset_family_graph_for_entry(entry)
        entries = self._archive_entries_from_asset_family_graph(graph, include_hints=include_hints)
        if not entries:
            self.set_status_message("No resolved family entries are available to export.", error=True)
            return
        self._export_archive_reference_entries_to_folder(
            entries,
            title=f"Export Asset Family - {entry.basename}",
        )

    def _current_archive_texture_reference(self) -> Optional[ArchiveModelTextureReference]:
        tab_tree = self.archive_asset_map_tabs.currentWidget() if hasattr(self, "archive_asset_map_tabs") else None
        candidate_items: List[Optional[QTreeWidgetItem]] = []
        if isinstance(tab_tree, QTreeWidget):
            candidate_items.append(tab_tree.currentItem())
        candidate_items.append(self.archive_texture_refs_tree.currentItem())
        for tree in (
            getattr(self, "archive_asset_map_tree", None),
            getattr(self, "archive_asset_uses_tree", None),
            getattr(self, "archive_asset_used_by_tree", None),
        ):
            if isinstance(tree, QTreeWidget):
                candidate_items.append(tree.currentItem())
        for current_item in candidate_items:
            reference = self._archive_reference_from_item(current_item)
            if reference is not None:
                return reference
        return None

    def _archive_reference_from_item(self, item: Optional[QTreeWidgetItem]) -> Optional[ArchiveModelTextureReference]:
        if item is None:
            return None
        raw_index = item.data(0, Qt.UserRole)
        if isinstance(raw_index, tuple) and len(raw_index) == 2:
            source, value = raw_index
            try:
                index = int(value)
            except (TypeError, ValueError):
                return None
            if source == "uses" and 0 <= index < len(self.current_archive_model_texture_references):
                return self.current_archive_model_texture_references[index]
            if source == "used_by" and 0 <= index < len(self.current_archive_used_by_references):
                return self.current_archive_used_by_references[index]
            if source == "family":
                current_entry = self._current_archive_entry()
                if index == -1 and isinstance(current_entry, ArchiveEntry):
                    return ArchiveModelTextureReference(
                        reference_name=current_entry.basename,
                        semantic_label=self._archive_entry_role_label(current_entry),
                        resolution_status="resolved",
                        resolved_archive_path=current_entry.path,
                        resolved_package_label=current_entry.package_label,
                        resolved_entry=current_entry,
                        reference_kind="source",
                        relation_group="Selected Model",
                        relation_reason="The file currently selected in Archive Browser.",
                        relation_confidence=RelationConfidence.AUTHORITATIVE.value,
                    )
                if 0 <= index < len(self.current_archive_family_member_rows):
                    member = self.current_archive_family_member_rows[index]
                    resolved_entry = getattr(member, "resolved_entry", None)
                    if not isinstance(resolved_entry, ArchiveEntry):
                        return None
                    return ArchiveModelTextureReference(
                        reference_name=member.display_name or resolved_entry.basename,
                        semantic_label=member.role,
                        resolution_status="resolved" if str(member.status or "").casefold() in {"model ok", "selected", "resolved", "partial", "context"} else "missing",
                        resolved_archive_path=member.path or resolved_entry.path,
                        resolved_package_label=resolved_entry.package_label,
                        resolved_entry=resolved_entry,
                        reference_kind=member.role,
                        relation_group=member.group,
                        relation_reason=member.reason,
                        relation_confidence=member.confidence,
                    )
            return None
        try:
            index = int(raw_index)
        except (TypeError, ValueError):
            return None
        if 0 <= index < len(self.current_archive_model_texture_references):
            return self.current_archive_model_texture_references[index]
        return None

    def _selected_archive_texture_references(self) -> List[ArchiveModelTextureReference]:
        selected_references: List[ArchiveModelTextureReference] = []
        seen_keys: set[Tuple[str, int]] = set()
        selected_items: List[QTreeWidgetItem] = []
        for tree in (
            getattr(self, "archive_asset_map_tree", None),
            getattr(self, "archive_asset_uses_tree", None),
            getattr(self, "archive_asset_used_by_tree", None),
            self.archive_texture_refs_tree,
        ):
            if isinstance(tree, QTreeWidget):
                selected_items.extend(tree.selectedItems())
        for item in selected_items:
            raw_index = item.data(0, Qt.UserRole)
            source = "uses"
            value = raw_index
            if isinstance(raw_index, tuple) and len(raw_index) == 2:
                source, value = raw_index
            try:
                index = int(value)
            except (TypeError, ValueError):
                continue
            key = (str(source), index)
            if key in seen_keys:
                continue
            seen_keys.add(key)
            if source == "used_by" and 0 <= index < len(self.current_archive_used_by_references):
                selected_references.append(self.current_archive_used_by_references[index])
            elif source == "family":
                reference = self._archive_reference_from_item(item)
                if reference is not None:
                    selected_references.append(reference)
            elif 0 <= index < len(self.current_archive_model_texture_references):
                selected_references.append(self.current_archive_model_texture_references[index])
        return selected_references

    def _resolved_archive_reference_entries(
        self,
        references: Sequence[ArchiveModelTextureReference],
    ) -> List[ArchiveEntry]:
        resolved_entries: List[ArchiveEntry] = []
        seen_paths: set[str] = set()
        for reference in references:
            resolved_entry = getattr(reference, "resolved_entry", None)
            if not isinstance(resolved_entry, ArchiveEntry):
                continue
            normalized_path = resolved_entry.path.replace("\\", "/").strip().lower()
            if not normalized_path or normalized_path in seen_paths:
                continue
            seen_paths.add(normalized_path)
            resolved_entries.append(resolved_entry)
        return resolved_entries

    def _scope_archive_reference_entries(
        self,
        entries: Sequence[ArchiveEntry],
        *,
        scope_label: str,
    ) -> None:
        if not entries:
            self.set_status_message("No resolved referenced files are available to show in Archive Browser.", error=True)
            return
        resolved_count = len(entries)
        applied = self._apply_archive_direct_scope(
            entries,
            scope_label=scope_label,
            placeholder_text=f"File set scope active: {scope_label}",
            hint_text=(
                f"File set scope active: {scope_label}. Showing {resolved_count:,} resolved archive file(s) "
                "from the current Referenced Files panel. Use Clear Scope to return to normal archive filters."
            ),
            progress_text=f"File set scope: {resolved_count:,} indexed file(s).",
            log_text=f"Referenced file set scoped Archive Browser to: {scope_label} ({resolved_count:,} file(s); no full archive scan).",
        )
        if applied:
            self.set_status_message(f"Showing file set in Archive Browser: {scope_label}.")

    def _scope_selected_archive_texture_references(self) -> None:
        selected_entries = self._resolved_archive_reference_entries(self._selected_archive_texture_references())
        if not selected_entries:
            self.set_status_message("Select one or more resolved referenced files first.", error=True)
            return
        current_entry = self._current_archive_entry()
        source_label = current_entry.basename if isinstance(current_entry, ArchiveEntry) else "selected asset"
        self._scope_archive_reference_entries(
            selected_entries,
            scope_label=f"Selected references for {source_label}",
        )

    def _scope_all_archive_texture_references(self) -> None:
        entries: List[ArchiveEntry] = []
        current_entry = self._current_archive_entry()
        if isinstance(current_entry, ArchiveEntry):
            entries.append(current_entry)
        entries.extend(self._resolved_archive_reference_entries(self.current_archive_model_texture_references))
        if not entries:
            self.set_status_message("No resolved referenced files are available to show in Archive Browser.", error=True)
            return
        source_label = current_entry.basename if isinstance(current_entry, ArchiveEntry) else "current asset"
        self._scope_archive_reference_entries(entries, scope_label=f"File set for {source_label}")

    def _scope_current_archive_entry_only(self) -> None:
        current_entry = self._current_archive_entry()
        if not isinstance(current_entry, ArchiveEntry):
            self.set_status_message("Select one archive file first.", error=True)
            return
        self._apply_archive_direct_scope(
            [current_entry],
            scope_label=f"{current_entry.basename} only",
            placeholder_text=f"Single-file scope active: {current_entry.basename}",
            hint_text=(
                f"Single-file scope active: {current_entry.basename}. Showing only this resolved archive entry. "
                "Use Clear Scope to return to normal archive filters."
            ),
            progress_text="Single-file scope: 1 indexed file.",
            log_text=f"Single-file scoped Archive Browser to: {current_entry.path} (no full archive scan).",
        )

    def _current_archive_asset_set_entries(self, *, include_used_by: bool = False, include_hints: bool = False) -> List[ArchiveEntry]:
        entries: List[ArchiveEntry] = []
        seen: set[Tuple[str, str, int]] = set()

        def add(entry: Optional[ArchiveEntry]) -> None:
            if not isinstance(entry, ArchiveEntry):
                return
            key = (entry.path.lower(), str(entry.pamt_path).lower(), int(entry.offset))
            if key in seen:
                return
            seen.add(key)
            entries.append(entry)

        family_rows = list(self.current_archive_family_member_rows)
        if family_rows:
            for member in family_rows:
                policy = str(getattr(member, "include_policy", "") or "").strip().casefold()
                status = str(getattr(member, "status", "") or "").strip().casefold()
                if status == "missing" or policy == "unresolved":
                    continue
                if include_hints or policy in {"required", "recommended"}:
                    add(getattr(member, "resolved_entry", None))
        else:
            add(self._current_archive_entry())
            for entry in self._resolved_archive_reference_entries(self.current_archive_model_texture_references):
                add(entry)
        if include_used_by:
            for entry in self._resolved_archive_reference_entries(self.current_archive_used_by_references):
                add(entry)
        return entries

    def _scope_current_archive_asset_set(self, *, include_used_by: bool = False, include_hints: bool = False) -> None:
        entries = self._current_archive_asset_set_entries(include_used_by=include_used_by, include_hints=include_hints)
        if not entries:
            self.set_status_message("No resolved asset-set files are available to show.", error=True)
            return
        current_entry = self._current_archive_entry()
        source_label = current_entry.basename if isinstance(current_entry, ArchiveEntry) else "current asset"
        suffix_parts = []
        if include_hints:
            suffix_parts.append("hints")
        if include_used_by:
            suffix_parts.append("used-by candidates")
        suffix = f" plus {', '.join(suffix_parts)}" if suffix_parts else ""
        self._scope_archive_reference_entries(entries, scope_label=f"Asset family for {source_label}{suffix}")

    def _prompt_archive_asset_set_export_entries(self) -> Optional[List[ArchiveEntry]]:
        current_entry = self._current_archive_entry()
        default_entries = self._current_archive_asset_set_entries(include_used_by=False, include_hints=False)
        used_by_entries = self._resolved_archive_reference_entries(self.current_archive_used_by_references)
        if not default_entries:
            self.set_status_message("No resolved asset-set files are available to export.", error=True)
            return None
        hint_entries = self._current_archive_asset_set_entries(include_used_by=False, include_hints=True)
        hint_only_count = max(0, len(hint_entries) - len(default_entries))
        if not used_by_entries and hint_only_count <= 0:
            return default_entries

        dialog = QDialog(self)
        dialog.setWindowTitle("Export Asset Family")
        dialog.setModal(True)
        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)
        source_label = current_entry.basename if isinstance(current_entry, ArchiveEntry) else "selected asset"
        intro = QLabel(
            f"Export {source_label} with {len(default_entries):,} resolved family file(s)."
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)
        include_hints_checkbox = QCheckBox(
            f"Include {hint_only_count:,} weak hint candidate(s)"
        )
        include_hints_checkbox.setEnabled(hint_only_count > 0)
        include_hints_checkbox.setToolTip(
            "Hint candidates are resolved files found through same-stem/name evidence. "
            "They are useful for context, but are not treated as required by default."
        )
        layout.addWidget(include_hints_checkbox)
        include_used_by_checkbox = QCheckBox(
            f"Include {len(used_by_entries):,} indexed Used By candidate(s)"
        )
        include_used_by_checkbox.setEnabled(bool(used_by_entries))
        include_used_by_checkbox.setToolTip(
            "Used By candidates are known from current indexes and cached relationship evidence. "
            "They are useful for context, but are not required by the selected file in every case."
        )
        layout.addWidget(include_used_by_checkbox)
        button_row = QHBoxLayout()
        button_row.addStretch(1)
        cancel_button = QPushButton("Cancel")
        export_button = QPushButton("Export")
        export_button.setDefault(True)
        button_row.addWidget(cancel_button)
        button_row.addWidget(export_button)
        layout.addLayout(button_row)
        cancel_button.clicked.connect(dialog.reject)
        export_button.clicked.connect(dialog.accept)
        if dialog.exec() != QDialog.Accepted:
            return None
        return self._current_archive_asset_set_entries(
            include_used_by=include_used_by_checkbox.isChecked(),
            include_hints=include_hints_checkbox.isChecked(),
        )

    def _export_current_archive_asset_set(self) -> None:
        entries = self._prompt_archive_asset_set_export_entries()
        if entries is None:
            return
        current_entry = self._current_archive_entry()
        source_label = current_entry.basename if isinstance(current_entry, ArchiveEntry) else "current asset"
        self._export_archive_reference_entries_to_folder(
            entries,
            title=f"Export Asset Family - {source_label}",
        )

    def _scope_current_archive_used_by_entries(self) -> None:
        entries = self._resolved_archive_reference_entries(self.current_archive_used_by_references)
        if not entries:
            self.set_status_message("No indexed Used By files are available for the current selection.", error=True)
            return
        current_entry = self._current_archive_entry()
        source_label = current_entry.basename if isinstance(current_entry, ArchiveEntry) else "current asset"
        self._scope_archive_reference_entries(entries, scope_label=f"Used by {source_label}")

    def _scope_current_archive_role_references(self, role: str, *, scope_label: str) -> None:
        normalized_role = str(role or "").casefold()
        references = list(self.current_archive_model_texture_references)
        references.extend(self.current_archive_used_by_references)
        entries = [
            entry
            for entry in self._resolved_archive_reference_entries(references)
            if normalized_role in self._archive_entry_role_label(entry).casefold()
        ]
        if not entries:
            self.set_status_message(f"No resolved {role.lower()} references are available.", error=True)
            return
        self._scope_archive_reference_entries(entries, scope_label=scope_label)

    def _show_archive_smart_actions_menu(self) -> None:
        current_entry = self._current_archive_entry()
        if not isinstance(current_entry, ArchiveEntry):
            self.set_status_message("Select one archive file first.", error=True)
            return
        role = self._archive_entry_role_label(current_entry)
        menu = QMenu(self)
        if hasattr(menu, "setToolTipsVisible"):
            menu.setToolTipsVisible(True)
        preview_action = menu.addAction("Open Preview")
        preview_action.triggered.connect(lambda _checked=False, entry=current_entry: self._render_archive_preview(entry))
        show_only_action = menu.addAction("Show Only This File")
        show_only_action.triggered.connect(lambda _checked=False: self._scope_current_archive_entry_only())

        if role == "Mesh":
            export_mesh_action = menu.addAction("Export Mesh...")
            export_mesh_action.triggered.connect(lambda _checked=False: self._export_current_archive_model())
            modify_original_action = menu.addAction("Modify Original...")
            modify_original_action.triggered.connect(
                lambda _checked=False, entry=current_entry: self._mesh_editor_modify_original_requested(entry)
            )
            import_mesh_preview_action = menu.addAction("Import Mesh Preview...")
            import_mesh_preview_action.triggered.connect(lambda _checked=False: self._preview_current_archive_mesh_import())
            show_hkx_action = menu.addAction("Show Related HKX/Physics")
            show_hkx_action.triggered.connect(
                lambda _checked=False, label=current_entry.basename: self._scope_current_archive_role_references(
                    "Physics",
                    scope_label=f"Related physics for {label}",
                )
            )
        elif role == "Texture":
            texture_editor_action = menu.addAction("Open Texture Editor...")
            texture_editor_action.triggered.connect(
                lambda _checked=False, entry=current_entry: self._open_archive_entry_in_texture_editor(entry)
            )
            used_by_action = menu.addAction("Show Materials Using This")
            used_by_action.triggered.connect(lambda _checked=False: self._scope_current_archive_used_by_entries())
        elif role in {"Physics", "HKX"}:
            edit_hkx_action = menu.addAction("Edit HKX...")
            edit_hkx_action.triggered.connect(lambda _checked=False: self._edit_current_archive_hkx())
            export_xml_action = menu.addAction("Export HKX XML...")
            export_xml_action.triggered.connect(lambda _checked=False: self._export_current_archive_hkx_xml())
            show_models_action = menu.addAction("Show Linked Models")
            show_models_action.triggered.connect(
                lambda _checked=False, label=current_entry.basename: self._scope_current_archive_role_references(
                    "Mesh",
                    scope_label=f"Linked models for {label}",
                )
            )
        elif role == "Material":
            edit_material_action = menu.addAction("Edit Material Values...")
            edit_material_action.triggered.connect(lambda _checked=False: self._edit_current_archive_material_sidecar())
            show_textures_action = menu.addAction("Show Used Textures")
            show_textures_action.triggered.connect(
                lambda _checked=False, label=current_entry.basename: self._scope_current_archive_role_references(
                    "Texture",
                    scope_label=f"Textures used by {label}",
                )
            )
        elif role in {"Prefab", "Metadata"}:
            related_action = menu.addAction("Show Related Files")
            related_action.triggered.connect(lambda _checked=False: self._scope_current_archive_asset_set(include_used_by=True))

        if not menu.isEmpty():
            menu.addSeparator()
        if hasattr(menu, "setToolTipsVisible"):
            menu.setToolTipsVisible(True)
        show_asset_set_action = menu.addAction("Filter to Family")
        show_asset_set_action.setToolTip("Filter Archive Files to the required/recommended files in this Asset Family.")
        show_asset_set_action.triggered.connect(lambda _checked=False: self._scope_current_archive_asset_set(include_used_by=False))
        if any(str(getattr(row, "include_policy", "") or "").casefold() == "manual" for row in self.current_archive_family_member_rows):
            show_asset_set_hints_action = menu.addAction("Show Family + Hints")
            show_asset_set_hints_action.triggered.connect(
                lambda _checked=False: self._scope_current_archive_asset_set(include_hints=True)
            )
        if self.current_archive_used_by_references:
            show_asset_set_used_by_action = menu.addAction("Show Family + Used By")
            show_asset_set_used_by_action.triggered.connect(
                lambda _checked=False: self._scope_current_archive_asset_set(include_used_by=True)
            )
        export_asset_set_action = menu.addAction("Export Family...")
        export_asset_set_action.triggered.connect(lambda _checked=False: self._export_current_archive_asset_set())
        if current_entry.extension not in ARCHIVE_MESH_EXTENSIONS:
            source_mix_action = menu.addAction("Build Loose Package From Sources...")
            source_mix_action.triggered.connect(
                lambda _checked=False, entry=current_entry: self._open_archive_source_mix_package_dialog(entry)
            )
        self.archive_texture_smart_actions_button.setMenu(menu)
        menu.exec(self.archive_texture_smart_actions_button.mapToGlobal(self.archive_texture_smart_actions_button.rect().bottomLeft()))

__all__ = ["ArchiveAssetFamilyReferenceMixin"]
