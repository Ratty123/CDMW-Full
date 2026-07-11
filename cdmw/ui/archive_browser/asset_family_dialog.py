"""Archive browser Asset Family graph cache and dialog-tree helpers."""

from __future__ import annotations

import re
from collections import OrderedDict
from collections.abc import Sequence
from pathlib import PurePosixPath
from typing import Dict, List, Optional, Tuple

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QAbstractItemView, QDialog, QHBoxLayout, QLabel, QPushButton, QTreeWidget, QTreeWidgetItem, QVBoxLayout

from cdmw.services.archive_query_service import (
    build_archive_asset_family_graph,
    build_archive_item_icon_references_from_catalog,
    build_archive_relationship_references,
    merge_archive_reference_rows,
)
from cdmw.models import (
    ArchiveEntry,
    ArchiveModelTextureReference,
    AssetFamilyGraph,
    AssetFamilyMember,
    AttachmentPlacementEvidence,
)


class ArchiveAssetFamilyDialogMixin:
    """Asset Family graph caching and workspace dialog tree population."""

    def _archive_has_asset_family_workspace(self) -> bool:
        return bool(
            self.current_archive_model_texture_references
            or self.current_archive_used_by_references
            or self.current_archive_family_member_rows
        )

    def _clear_archive_asset_family_cache(self) -> None:
        self.archive_asset_family_cache.clear()

    def _archive_asset_family_cache_key(self, entry: ArchiveEntry) -> Tuple[str, str, int, int, int]:
        return (
            str(getattr(entry, "path", "") or "").replace("\\", "/").casefold(),
            str(getattr(entry, "pamt_path", "") or "").replace("\\", "/").casefold(),
            int(getattr(entry, "offset", 0) or 0),
            int(getattr(self, "archive_sidecar_generation", 0) or 0),
            len(getattr(self, "archive_item_asset_catalog", ()) or ()),
        )

    def _remember_archive_asset_family_graph(
        self,
        entry: ArchiveEntry,
        graph: AssetFamilyGraph,
        references: Sequence[ArchiveModelTextureReference],
    ) -> None:
        cache = getattr(self, "archive_asset_family_cache", None)
        if not isinstance(cache, OrderedDict):
            return
        key = self._archive_asset_family_cache_key(entry)
        cache[key] = (graph, tuple(references))
        cache.move_to_end(key)
        limit = max(1, int(getattr(self, "archive_asset_family_cache_limit", 512) or 512))
        while len(cache) > limit:
            cache.popitem(last=False)

    def _archive_asset_family_graph_for_entry(
        self,
        entry: ArchiveEntry,
    ) -> Tuple[AssetFamilyGraph, Tuple[ArchiveModelTextureReference, ...]]:
        current_entry = self._current_archive_entry()
        current_graph = getattr(self, "current_archive_asset_family_graph", None)
        if (
            isinstance(current_entry, ArchiveEntry)
            and self._same_archive_entry(current_entry, entry)
            and isinstance(current_graph, AssetFamilyGraph)
        ):
            return current_graph, tuple(self.current_archive_model_texture_references)
        cache = getattr(self, "archive_asset_family_cache", None)
        cache_key = self._archive_asset_family_cache_key(entry)
        if isinstance(cache, OrderedDict) and cache_key in cache:
            graph, cached_references = cache[cache_key]
            cache.move_to_end(cache_key)
            self.append_archive_log(
                f"Asset family cache hit: {entry.path}",
                verbose=True,
            )
            return graph, tuple(cached_references)
        self.append_archive_log(
            f"Asset family cache miss; rebuilding: {entry.path}",
            verbose=True,
        )
        references = build_archive_relationship_references(
            entry,
            archive_entries_by_normalized_path=self.archive_entries_by_normalized_path,
            archive_entries_by_basename=self.archive_entries_by_basename,
        )
        combined_references = list(references)
        if str(entry.extension or "").lower() == ".dds":
            combined_references.extend(self._archive_known_used_by_references(entry))
        item_icon_references = build_archive_item_icon_references_from_catalog(
            entry,
            tuple(getattr(self, "archive_item_asset_catalog", ()) or ()),
            archive_entries_by_normalized_path=self.archive_entries_by_normalized_path,
            archive_entries_by_basename=self.archive_entries_by_basename,
            related_references=tuple(combined_references),
        )
        if item_icon_references:
            combined_references = list(merge_archive_reference_rows(combined_references, item_icon_references))
        graph = build_archive_asset_family_graph(entry, tuple(combined_references))
        self._remember_archive_asset_family_graph(entry, graph, combined_references)
        return graph, tuple(combined_references)

    @staticmethod
    def _archive_entries_from_asset_family_graph(
        graph: AssetFamilyGraph,
        *,
        include_hints: bool = False,
    ) -> List[ArchiveEntry]:
        entries: List[ArchiveEntry] = []
        seen: set[Tuple[str, str, int]] = set()
        for member in tuple(getattr(graph, "member_rows", ()) or ()):
            if not isinstance(member, AssetFamilyMember):
                continue
            status = str(getattr(member, "status", "") or "").strip().casefold()
            policy = str(getattr(member, "include_policy", "") or "").strip().casefold()
            entry = getattr(member, "resolved_entry", None)
            if not isinstance(entry, ArchiveEntry):
                continue
            if status == "missing" or policy == "unresolved":
                continue
            if not include_hints and policy not in {"required", "recommended"}:
                continue
            key = (entry.path.lower(), str(entry.pamt_path).lower(), int(entry.offset))
            if key in seen:
                continue
            seen.add(key)
            entries.append(entry)
        return entries

    def _populate_asset_family_dialog_tree(
        self,
        tree: QTreeWidget,
        graph: AssetFamilyGraph,
    ) -> None:
        tree.clear()
        group_items: Dict[str, QTreeWidgetItem] = {}
        order = (
            "Selected Model",
            "Attachment / Placement",
            "Material",
            "Textures",
            "Item Icons",
            "Physics / HKX",
            "MeshInfo",
            "Prefab / Metadata",
            "Skeleton / Rig",
            "Animation / Motion",
            "Other",
        )
        rows = tuple(getattr(graph, "member_rows", ()) or ())
        for group_label in order:
            group_rows = [row for row in rows if isinstance(row, AssetFamilyMember) and row.group == group_label]
            if not group_rows:
                continue
            group_item = QTreeWidgetItem([f"{group_label} ({len(group_rows)})", "", "", "", ""])
            group_item.setFlags(Qt.ItemIsEnabled)
            group_item.setExpanded(True)
            tree.addTopLevelItem(group_item)
            group_items[group_label] = group_item
            for member in group_rows:
                child = QTreeWidgetItem(
                    [
                        str(member.role or "Related File"),
                        str(member.display_name or PurePosixPath(str(member.path or "").replace("\\", "/")).name or "-"),
                        str(member.status or "-"),
                        str(member.source_evidence or member.confidence or "-"),
                        str(member.reason or "Recovered relationship evidence."),
                    ]
                )
                child.setData(0, Qt.UserRole, member)
                child.setToolTip(1, str(member.path or ""))
                child.setToolTip(4, "\n".join(part for part in (str(member.reason or ""), str(member.warning or "")) if part))
                self._style_archive_role_columns(child, str(member.role or member.group), 0, 1)
                self._ui_style_status_columns(
                    child,
                    {2: member.status, 3: member.source_evidence or member.confidence, 4: member.reason},
                )
                group_item.addChild(child)
        tree.expandAll()

    @staticmethod
    def _attachment_family_skeleton_paths(
        graph: AssetFamilyGraph,
        evidence: Optional[AttachmentPlacementEvidence] = None,
    ) -> Tuple[str, ...]:
        paths: List[str] = []
        seen: set[str] = set()

        def add_path(raw_path: object) -> None:
            path = str(raw_path or "").replace("\\", "/").strip()
            key = path.casefold()
            if path and key not in seen:
                paths.append(path)
                seen.add(key)

        if isinstance(evidence, AttachmentPlacementEvidence):
            add_path(evidence.skeleton_path)
        for member in tuple(getattr(graph, "member_rows", ()) or ()):
            if not isinstance(member, AssetFamilyMember):
                continue
            group = str(member.group or "").casefold()
            role = str(member.role or "").casefold()
            status = str(member.status or "").casefold()
            ext = PurePosixPath(str(member.path or "").replace("\\", "/")).suffix.casefold()
            if status == "missing":
                continue
            if group == "skeleton / rig" or "skeleton" in role or "rig" in role or ext == ".pab":
                add_path(member.path)
        return tuple(paths)

    def _open_archive_asset_family_workspace_dialog(
        self,
        entry: Optional[ArchiveEntry] = None,
    ) -> None:
        source_entry = entry if isinstance(entry, ArchiveEntry) else self._current_archive_entry()
        if not isinstance(source_entry, ArchiveEntry):
            self.set_status_message("Select an archive file first.", error=True)
            return
        graph, _references = self._archive_asset_family_graph_for_entry(source_entry)
        if not tuple(getattr(graph, "member_rows", ()) or ()):
            self.set_status_message("No asset family evidence is available for this file yet.", error=True)
            return

        dialog = QDialog(self)
        dialog.setWindowTitle(f"Asset Family - {source_entry.basename}")
        dialog.resize(980, 680)
        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)
        summary = QLabel(str(getattr(graph, "summary", "") or "Recovered asset family relationships."))
        summary.setObjectName("HintLabel")
        summary.setWordWrap(True)
        layout.addWidget(summary)
        tree = QTreeWidget()
        tree.setColumnCount(5)
        tree.setHeaderLabels(["Role", "File", "Status", "Evidence", "Why"])
        tree.setRootIsDecorated(True)
        tree.setAlternatingRowColors(True)
        tree.setUniformRowHeights(True)
        tree.setSelectionMode(QAbstractItemView.SingleSelection)
        self._install_tree_horizontal_wheel_guard(tree)
        self._populate_asset_family_dialog_tree(tree, graph)
        header = tree.header()
        header.setStretchLastSection(True)
        header.resizeSection(0, 140)
        header.resizeSection(1, 240)
        header.resizeSection(2, 110)
        header.resizeSection(3, 120)
        layout.addWidget(tree, stretch=1)

        button_row = QHBoxLayout()
        button_row.setContentsMargins(0, 0, 0, 0)
        preview_button = QPushButton("Preview Selected")
        placement_button = QPushButton("Weapon Placement Studio (Disabled - WIP)")
        placement_button.setToolTip("Disabled - WIP. Weapon Placement Studio is paused until the preview/export flow is ready again.")
        scope_button = QPushButton("Filter to Family")
        scope_button.setToolTip("Filter Archive Files to the required/recommended files in this Asset Family.")
        export_button = QPushButton("Export Family...")
        close_button = QPushButton("Close")
        button_row.addWidget(preview_button)
        button_row.addWidget(placement_button)
        button_row.addWidget(scope_button)
        button_row.addWidget(export_button)
        button_row.addStretch(1)
        button_row.addWidget(close_button)
        layout.addLayout(button_row)

        def selected_member_entry() -> Optional[ArchiveEntry]:
            item = tree.currentItem()
            member = item.data(0, Qt.UserRole) if item is not None else None
            if isinstance(member, AssetFamilyMember) and isinstance(member.resolved_entry, ArchiveEntry):
                return member.resolved_entry
            return None

        def preview_selected() -> None:
            selected_entry = selected_member_entry()
            if not isinstance(selected_entry, ArchiveEntry):
                self.set_status_message("Select a resolved family file first.", error=True)
                return
            self._open_archive_reference_preview_entry(selected_entry)

        def scope_family() -> None:
            entries = self._archive_entries_from_asset_family_graph(graph, include_hints=False)
            if not entries:
                self.set_status_message("No resolved family entries are available to scope.", error=True)
                return
            self._scope_archive_reference_entries(entries, scope_label=f"Asset family for {source_entry.basename}")

        def export_family() -> None:
            entries = self._archive_entries_from_asset_family_graph(graph, include_hints=False)
            if not entries:
                self.set_status_message("No resolved family entries are available to export.", error=True)
                return
            self._export_archive_reference_entries_to_folder(
                entries,
                title=f"Export Asset Family - {source_entry.basename}",
            )

        preview_button.clicked.connect(lambda _checked=False: preview_selected())
        placement_button.setEnabled(False)
        scope_button.clicked.connect(lambda _checked=False: scope_family())
        export_button.clicked.connect(lambda _checked=False: export_family())
        close_button.clicked.connect(dialog.accept)
        tree.itemDoubleClicked.connect(lambda _item, _column: preview_selected())
        dialog.exec()

    def _populate_attachment_placement_dialog_tree(
        self,
        tree: QTreeWidget,
        graph: AssetFamilyGraph,
    ) -> None:
        tree.clear()
        evidence_rows = tuple(getattr(graph, "attachment_evidence", ()) or ())
        if not evidence_rows:
            top = QTreeWidgetItem(["No placement chain", "-", "-", "No prefab/socket evidence", "Read-only"])
            top.setFlags(Qt.ItemIsEnabled)
            top.setToolTip(
                3,
                "HKX can show collision/physics context, but in-game placement needs prefab and socket descriptor evidence.",
            )
            tree.addTopLevelItem(top)
            return
        for evidence_index, evidence in enumerate(evidence_rows):
            if not isinstance(evidence, AttachmentPlacementEvidence):
                continue
            skeleton_paths = self._attachment_family_skeleton_paths(graph, evidence)
            skeleton_text = "; ".join(skeleton_paths) if skeleton_paths else "-"
            skeleton_evidence = "Skeleton" if evidence.skeleton_path else "Family skeleton" if skeleton_paths else "Skeleton"
            chain_name = " -> ".join(
                part
                for part in (
                    str(evidence.character_socket_name or "").strip(),
                    str(evidence.weapon_socket_name or "").strip(),
                    PurePosixPath(str(evidence.model_path or "").replace("\\", "/")).name,
                )
                if part
            ) or f"Attachment chain {evidence_index + 1}"
            top = QTreeWidgetItem(
                [
                    chain_name,
                    str(evidence.model_path or "-"),
                    self._format_attachment_transform(evidence.character_socket_translation),
                    str(evidence.confidence or "Path hint"),
                    "Read-only placement evidence",
                ]
            )
            top.setFlags(Qt.ItemIsEnabled)
            top.setData(0, Qt.UserRole, evidence)
            top.setExpanded(True)
            tree.addTopLevelItem(top)
            rows = [
                ("Target asset", str(evidence.model_path or "-"), "", str(evidence.evidence or "-"), "Visible model path recovered from prefab or family evidence."),
                ("Prefab", str(evidence.prefab_path or "-"), "", "Prefab", "Prefab fields drive attachment names and file references when present."),
                (
                    "Character socket",
                    str(evidence.character_socket_name or "-"),
                    self._format_attachment_transform(evidence.character_socket_translation),
                    "Socket XML" if evidence.character_socket_parent else str(evidence.evidence or "Prefab"),
                    f"Parent bone: {evidence.character_socket_parent}" if evidence.character_socket_parent else "Character-side socket name.",
                ),
                (
                    "Weapon pivot",
                    str(evidence.weapon_socket_name or "-"),
                    self._format_attachment_transform(evidence.weapon_socket_translation),
                    "Socket XML" if evidence.weapon_socket_parent else str(evidence.evidence or "Prefab"),
                    f"Parent bone: {evidence.weapon_socket_parent}" if evidence.weapon_socket_parent else "Weapon-side child/pivot socket name.",
                ),
                ("Socket XML", str(evidence.socket_file_path or "-"), "", "Socket XML", "Socket descriptor path recovered from prefab or same-family evidence."),
                (
                    "Skeleton",
                    skeleton_text,
                    "",
                    skeleton_evidence,
                    "Skeleton path from the placement chain when present; otherwise resolved from the asset family skeleton/rig companions.",
                ),
                (
                    "Transform fields",
                    ", ".join(tuple(evidence.transform_fields or ())) or "-",
                    "",
                    "Prefab fields",
                    "Declared placement fields are displayed; only proven same-length socket-name prefab rewrites are exportable.",
                ),
            ]
            for row in rows:
                item = QTreeWidgetItem(list(row))
                item.setData(0, Qt.UserRole, evidence)
                item.setToolTip(1, row[1])
                item.setToolTip(4, row[4])
                self._ui_style_status_columns(item, {3: row[3], 4: row[4]})
                top.addChild(item)
        tree.expandAll()

    def _attachment_socket_entry_from_selection(
        self,
        graph: AssetFamilyGraph,
        tree: Optional[QTreeWidget] = None,
    ) -> Optional[ArchiveEntry]:
        candidate_paths: List[str] = []
        if tree is not None:
            item = tree.currentItem()
            while item is not None:
                evidence = item.data(0, Qt.UserRole)
                if isinstance(evidence, AttachmentPlacementEvidence) and evidence.socket_file_path:
                    candidate_paths.append(evidence.socket_file_path)
                item = item.parent()
        for evidence in tuple(getattr(graph, "attachment_evidence", ()) or ()):
            if isinstance(evidence, AttachmentPlacementEvidence) and evidence.socket_file_path:
                candidate_paths.append(evidence.socket_file_path)
        for member in tuple(getattr(graph, "member_rows", ()) or ()):
            if not isinstance(member, AssetFamilyMember):
                continue
            if member.group == "Attachment / Placement" and "socket" in str(member.display_name or member.path or "").casefold():
                candidate_paths.append(member.path)
        seen_paths: set[str] = set()
        for candidate_path in candidate_paths:
            normalized = str(candidate_path or "").replace("\\", "/").strip().lower()
            if not normalized or normalized in seen_paths:
                continue
            seen_paths.add(normalized)
            entry = self._find_archive_entry_by_virtual_path(normalized)
            if not isinstance(entry, ArchiveEntry):
                continue
            basename = PurePosixPath(entry.path.replace("\\", "/")).name.casefold()
            if str(entry.extension or "").lower() == ".xml" and ("socket" in basename or basename.endswith(".sockets.xml")):
                return entry
        return None

    @staticmethod
    def _parse_attachment_transform_values(raw_value: str, expected_count: int) -> Tuple[float, ...]:
        values: List[float] = []
        for token in re.split(r"[\s,;]+", str(raw_value or "").strip()):
            if not token:
                continue
            try:
                values.append(float(token))
            except ValueError:
                return ()
        if len(values) != expected_count:
            return ()
        return tuple(values)

    @staticmethod
    def _format_attachment_transform_values(values: Sequence[float]) -> str:
        formatted: List[str] = []
        for value in tuple(values or ()):
            text = f"{float(value):.6f}".rstrip("0").rstrip(".")
            formatted.append(text if text and text != "-0" else "0")
        return " ".join(formatted)
