"""Archive browser asset-family and reference-pane update helpers."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import PurePosixPath
from typing import Dict, List, Optional, Tuple

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QTreeWidget, QTreeWidgetItem

from cdmw.core.archive import (
    build_archive_asset_family_graph,
    build_archive_item_icon_references_from_catalog,
    merge_archive_reference_rows,
)
from cdmw.models import (
    ArchiveEntry,
    ArchiveModelTextureReference,
    AssetFamilyGraph,
    AssetFamilyMember,
    AttachmentPlacementEvidence,
)


class ArchiveAssetFamilyPanelMixin:
    """Deferred reference-pane refresh helpers for archive previews."""

    @staticmethod
    def _archive_texture_reference_group_label(
        relation_group: str,
        reference_name: str,
        resolved_archive_path: str,
    ) -> str:
        group = str(relation_group or "").strip() or "Metadata / Other"
        if group != "Textures":
            return group
        path_text = str(resolved_archive_path or reference_name or "").replace("\\", "/").strip()
        normalized = path_text.lower().lstrip("/")
        if not normalized.startswith("leveldata/") or "/proxylod/" not in normalized:
            return group
        stem = PurePosixPath(normalized).stem
        for suffix in (
            "_normal",
            "_height",
            "_disp",
            "_diff",
            "_base",
            "_color",
            "_albedo",
            "_mask",
            "_rough",
            "_sp",
            "_ma",
            "_n",
            "_d",
        ):
            if stem.endswith(suffix):
                stem = stem[: -len(suffix)]
                break
        stem = stem.strip("_- ") or "unknown"
        return f"Proxy LOD Textures / {stem}"

    def _archive_asset_map_group_label(self, relation_group: str, entry: Optional[ArchiveEntry], reference_name: str = "") -> str:
        role = self._archive_entry_role_label(entry)
        group = str(relation_group or "").strip()
        lowered = " ".join([group, role, str(reference_name or "")]).casefold()
        if "item icon" in lowered:
            return "Item Icons"
        if "texture" in lowered:
            return "Textures"
        if "material" in lowered or "sidecar" in lowered:
            return "Material"
        extension = str(getattr(entry, "extension", "") or PurePosixPath(str(reference_name or "").replace("\\", "/")).suffix).lower()
        if extension == ".meshinfo":
            return "MeshInfo"
        if "physics" in lowered or "hkx" in lowered:
            return "Physics / HKX"
        if "skeleton" in lowered or "rig" in lowered or role == "Skeleton / Rig":
            return "Skeleton / Rig"
        if "animation" in lowered or "motion" in lowered:
            return "Animation / Motion"
        if "prefab" in lowered or "metadata" in lowered or role in {"Prefab", "Metadata", "UI"}:
            return "Prefab / Metadata"
        if role == "Mesh":
            return "Selected Model"
        return "Other"

    def _archive_reference_role_label(self, reference: ArchiveModelTextureReference) -> str:
        reference_kind = str(getattr(reference, "reference_kind", "") or "").strip().casefold()
        group = str(getattr(reference, "relation_group", "") or "").casefold()
        if reference_kind == "item_icon" or "item icon" in group:
            return "Inventory Icon"
        resolved_entry = getattr(reference, "resolved_entry", None)
        if isinstance(resolved_entry, ArchiveEntry):
            return self._archive_entry_role_label(resolved_entry)
        if "texture" in group:
            return "Texture"
        if "material" in group or "sidecar" in group:
            return "Material"
        if "skeleton" in group or "rig" in group:
            return "Skeleton / Rig"
        if "physics" in group or "hkx" in group or "animation" in group:
            return "Physics"
        return "Unknown"

    @staticmethod
    def _archive_texture_reference_status_text(reference: ArchiveModelTextureReference) -> str:
        status = str(getattr(reference, "resolution_status", "") or "").strip().lower()
        resolved_entry = getattr(reference, "resolved_entry", None)
        if status == "resolved":
            if isinstance(resolved_entry, ArchiveEntry) and resolved_entry.extension == ".dds" and resolved_entry.compression_type == 1:
                return "Resolved (Partial)"
            return "Resolved"
        if status == "technical_only":
            return "Technical only"
        return "Missing"

    @staticmethod
    def _archive_reference_display_name(reference: ArchiveModelTextureReference) -> str:
        resolved_entry = getattr(reference, "resolved_entry", None)
        if isinstance(resolved_entry, ArchiveEntry):
            return resolved_entry.basename
        resolved_archive_path = str(getattr(reference, "resolved_archive_path", "") or "").strip()
        reference_name = str(getattr(reference, "reference_name", "") or "").strip()
        if resolved_archive_path:
            return PurePosixPath(resolved_archive_path.replace("\\", "/")).name
        if reference_name:
            return PurePosixPath(reference_name.replace("\\", "/")).name or reference_name
        return "-"

    def _populate_archive_relation_tree(
        self,
        tree: QTreeWidget,
        references: Sequence[ArchiveModelTextureReference],
        *,
        source_name: str,
        reference_source: str,
    ) -> None:
        tree.clear()
        group_items: Dict[str, QTreeWidgetItem] = {}
        for index, reference in enumerate(references):
            resolved_entry = getattr(reference, "resolved_entry", None)
            role = self._archive_reference_role_label(reference)
            relation_group = self._archive_asset_map_group_label(
                str(getattr(reference, "relation_group", "") or ""),
                resolved_entry if isinstance(resolved_entry, ArchiveEntry) else None,
                str(getattr(reference, "reference_name", "") or ""),
            )
            group_item = group_items.get(relation_group)
            if group_item is None:
                group_item = QTreeWidgetItem([relation_group, "", "", "", ""])
                group_item.setFlags(Qt.ItemIsEnabled)
                group_item.setExpanded(True)
                tree.addTopLevelItem(group_item)
                group_items[relation_group] = group_item
            status_text = self._archive_texture_reference_status_text(reference)
            confidence_label = self._archive_relation_confidence_label(str(getattr(reference, "relation_confidence", "") or ""))
            reason = str(getattr(reference, "relation_reason", "") or "").strip()
            path_text = str(getattr(reference, "resolved_archive_path", "") or getattr(reference, "reference_name", "") or "").strip()
            item = QTreeWidgetItem(
                [
                    self._archive_reference_display_name(reference),
                    role,
                    status_text,
                    confidence_label or "-",
                    reason or "Indexed relationship evidence.",
                ]
            )
            item.setData(0, Qt.UserRole, (reference_source, index))
            item.setToolTip(0, "\n".join(part for part in [path_text, f"Source: {source_name}"] if part))
            item.setToolTip(4, reason or "Known from current scan/index; no live full-archive scan was run.")
            self._style_archive_role_columns(item, role, 0, 1)
            self._ui_style_status_columns(item, {3: confidence_label, 4: reason})
            group_item.addChild(item)
        for relation_group, group_item in group_items.items():
            group_item.setText(0, f"{relation_group} ({group_item.childCount()})")
        tree.expandAll()

    @staticmethod
    def _format_attachment_transform(values: Sequence[float]) -> str:
        if not values:
            return ""
        return " ".join(f"{float(value):.4g}" for value in tuple(values)[:4])

    def _populate_archive_attachment_placement_tree(
        self,
        asset_family_graph: Optional[AssetFamilyGraph],
    ) -> None:
        self.archive_asset_placement_tree.clear()
        evidence_rows = tuple(getattr(asset_family_graph, "attachment_evidence", ()) or ())
        if not evidence_rows:
            return
        for evidence_index, evidence in enumerate(evidence_rows):
            if not isinstance(evidence, AttachmentPlacementEvidence):
                continue
            title_parts = [
                str(evidence.character_socket_name or "").strip(),
                str(evidence.weapon_socket_name or "").strip(),
                PurePosixPath(str(evidence.model_path or evidence.prefab_path or evidence.socket_file_path or "").replace("\\", "/")).name,
            ]
            title = " -> ".join(part for part in title_parts if part) or f"Attachment chain {evidence_index + 1}"
            top_item = QTreeWidgetItem([title, "", str(evidence.confidence or "-"), str(evidence.reason or "")])
            top_item.setFlags(Qt.ItemIsEnabled)
            top_item.setExpanded(True)
            self.archive_asset_placement_tree.addTopLevelItem(top_item)

            rows: List[Tuple[str, str, str, str]] = [
                (
                    "Raw Model Origin",
                    PurePosixPath(str(evidence.model_path or "").replace("\\", "/")).name or "selected model origin",
                    "Base model",
                    "Shows the asset at its stored origin without applying character or weapon socket transforms.",
                )
            ]
            if evidence.character_socket_name:
                transform = self._format_attachment_transform(evidence.character_socket_translation)
                target = evidence.character_socket_name
                if evidence.character_socket_parent:
                    target = f"{target} on {evidence.character_socket_parent}"
                if transform:
                    target = f"{target} | T {transform}"
                rows.append(
                    (
                        "Character Socket",
                        target,
                        evidence.evidence or "Prefab",
                        "Character-side attachment target recovered from prefab/socket metadata.",
                    )
                )
            if evidence.weapon_socket_name:
                transform = self._format_attachment_transform(evidence.weapon_socket_translation)
                target = evidence.weapon_socket_name
                if evidence.weapon_socket_parent:
                    target = f"{target} on {evidence.weapon_socket_parent}"
                if transform:
                    target = f"{target} | T {transform}"
                rows.append(
                    (
                        "Weapon Pivot",
                        target,
                        "Socket XML" if evidence.weapon_socket_parent else evidence.evidence or "Prefab",
                        "Weapon-side child/pivot socket used to align the asset to the character socket.",
                    )
                )
            if evidence.character_socket_name and evidence.weapon_socket_name:
                rows.append(
                    (
                        "Final Attachment",
                        f"{evidence.character_socket_name} -> {evidence.weapon_socket_name}",
                        evidence.confidence or "Prefab",
                        "Preview target chain. This is read-only evidence; binary placement writes remain gated.",
                    )
                )
            if evidence.prefab_path:
                rows.append(("Prefab", evidence.prefab_path, "Prefab", "Prefab contains the recovered socket placement fields."))
            if evidence.socket_file_path:
                rows.append(("Socket XML", evidence.socket_file_path, "Socket XML", "Socket descriptor contains named socket transforms."))
            if evidence.transform_fields:
                rows.append(
                    (
                        "Transform Fields",
                        ", ".join(evidence.transform_fields),
                        "Read-only",
                        "Fields are declared in the prefab. They are not editable until exact offsets and write rules are proven.",
                    )
                )
            for row in rows:
                child = QTreeWidgetItem(list(row))
                child.setData(0, Qt.UserRole, evidence)
                child.setToolTip(1, row[1])
                child.setToolTip(3, row[3])
                self._ui_style_status_columns(child, {2: row[2], 3: row[3]})
                top_item.addChild(child)
        self.archive_asset_placement_tree.expandAll()

    def _populate_archive_asset_map_tree(
        self,
        source_entry: Optional[ArchiveEntry],
        references: Sequence[ArchiveModelTextureReference],
        asset_family_graph: Optional[AssetFamilyGraph] = None,
    ) -> None:
        self.archive_asset_map_tree.clear()
        graph = asset_family_graph
        if graph is None and isinstance(source_entry, ArchiveEntry):
            graph = build_archive_asset_family_graph(source_entry, references)
        member_rows = list(tuple(getattr(graph, "member_rows", ()) or ()))
        self.current_archive_family_member_rows = member_rows

        summary_text = str(getattr(graph, "summary", "") or "").strip() if graph is not None else ""
        self.archive_asset_family_summary_label.setText(summary_text)
        self.archive_asset_family_summary_label.setVisible(bool(summary_text))

        reference_index_by_path: Dict[str, int] = {}
        for index, reference in enumerate(references):
            resolved_path = str(getattr(reference, "resolved_archive_path", "") or "").replace("\\", "/").strip().casefold()
            if resolved_path and resolved_path not in reference_index_by_path:
                reference_index_by_path[resolved_path] = index

        if member_rows:
            group_order = (
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
            group_items: Dict[str, QTreeWidgetItem] = {}
            for group_label in group_order:
                rows = [row for row in member_rows if row.group == group_label]
                if not rows:
                    continue
                group_item = QTreeWidgetItem([group_label, "", "", "", ""])
                group_item.setFlags(Qt.ItemIsEnabled)
                group_item.setExpanded(True)
                self.archive_asset_map_tree.addTopLevelItem(group_item)
                group_items[group_label] = group_item
                for member_index, member in enumerate(member_rows):
                    if member.group != group_label:
                        continue
                    status_text = str(member.status or "-")
                    evidence_text = str(member.source_evidence or member.confidence or "-")
                    reason = str(member.reason or "Recovered family relationship evidence.")
                    item = QTreeWidgetItem(
                        [
                            str(member.role or "Related File"),
                            str(member.display_name or PurePosixPath(str(member.path or "").replace("\\", "/")).name or "-"),
                            status_text,
                            evidence_text,
                            reason,
                        ]
                    )
                    normalized_path = str(member.path or "").replace("\\", "/").strip().casefold()
                    reference_index = reference_index_by_path.get(normalized_path)
                    if reference_index is not None:
                        item.setData(0, Qt.UserRole, ("uses", reference_index))
                    else:
                        item.setData(0, Qt.UserRole, ("family", member_index))
                    if member.path:
                        item.setToolTip(1, member.path)
                    detail_lines = [
                        reason,
                        f"Include policy: {member.include_policy}" if member.include_policy else "",
                        f"Warning: {member.warning}" if member.warning else "",
                    ]
                    item.setToolTip(4, "\n".join(line for line in detail_lines if line))
                    self._style_archive_role_columns(item, str(member.role or group_label), 0, 1)
                    self._ui_style_status_columns(item, {2: status_text, 3: evidence_text, 4: reason})
                    group_item.addChild(item)
                group_item.setText(0, f"{group_label} ({group_item.childCount()})")
            self.archive_asset_map_tree.expandAll()
            return

        if isinstance(source_entry, ArchiveEntry):
            source_role = self._archive_entry_role_label(source_entry)
            source_group = QTreeWidgetItem(["Selected Model", "", "", "", ""])
            source_group.setFlags(Qt.ItemIsEnabled)
            source_group.setExpanded(True)
            self.archive_asset_map_tree.addTopLevelItem(source_group)
            source_item = QTreeWidgetItem(
                [
                    source_role,
                    source_entry.basename,
                    "Selected",
                    "Exact",
                    "The file currently selected in Archive Browser.",
                ]
            )
            source_item.setData(0, Qt.UserRole, ("family", -1))
            source_item.setToolTip(1, source_entry.path)
            self._style_archive_role_columns(source_item, source_role, 0, 1)
            source_group.addChild(source_item)

        group_items: Dict[str, QTreeWidgetItem] = {}
        for index, reference in enumerate(references):
            resolved_entry = getattr(reference, "resolved_entry", None)
            role = self._archive_reference_role_label(reference)
            group_label = self._archive_asset_map_group_label(
                str(getattr(reference, "relation_group", "") or ""),
                resolved_entry if isinstance(resolved_entry, ArchiveEntry) else None,
                str(getattr(reference, "reference_name", "") or ""),
            )
            group_item = group_items.get(group_label)
            if group_item is None:
                group_item = QTreeWidgetItem([group_label, "", "", "", ""])
                group_item.setFlags(Qt.ItemIsEnabled)
                group_item.setExpanded(True)
                self.archive_asset_map_tree.addTopLevelItem(group_item)
                group_items[group_label] = group_item
            confidence_label = self._archive_relation_confidence_label(str(getattr(reference, "relation_confidence", "") or ""))
            reason = str(getattr(reference, "relation_reason", "") or "").strip()
            status_text = self._archive_texture_reference_status_text(reference)
            item = QTreeWidgetItem(
                [
                    role,
                    self._archive_reference_display_name(reference),
                    status_text,
                    confidence_label or "-",
                    reason or "Recovered relationship evidence.",
                ]
            )
            item.setData(0, Qt.UserRole, ("uses", index))
            path_text = str(getattr(reference, "resolved_archive_path", "") or getattr(reference, "reference_name", "") or "").strip()
            item.setToolTip(1, path_text)
            item.setToolTip(4, reason or "Known from current preview relationship recovery.")
            self._style_archive_role_columns(item, role, 0, 1)
            self._ui_style_status_columns(item, {3: confidence_label, 4: reason})
            group_item.addChild(item)
        for group_label, group_item in group_items.items():
            group_item.setText(0, f"{group_label} ({group_item.childCount()})")
        self.archive_asset_map_tree.expandAll()

    def _populate_archive_texture_reference_list(
        self,
        references: Sequence[ArchiveModelTextureReference],
        asset_family_graph: Optional[AssetFamilyGraph] = None,
        *,
        enrich: bool = True,
    ) -> None:
        current_entry = self._current_archive_entry()
        base_references = list(references)
        self.current_archive_used_by_references = (
            self._archive_known_used_by_references(current_entry)
            if enrich
            else []
        )
        item_icon_references: Tuple[ArchiveModelTextureReference, ...] = ()
        if enrich and isinstance(current_entry, ArchiveEntry):
            related_for_icon_match = list(base_references)
            related_for_icon_match.extend(self.current_archive_used_by_references)
            item_icon_references = build_archive_item_icon_references_from_catalog(
                current_entry,
                tuple(getattr(self, "archive_item_asset_catalog", ()) or ()),
                archive_entries_by_normalized_path=self.archive_entries_by_normalized_path,
                archive_entries_by_basename=self.archive_entries_by_basename,
                related_references=tuple(related_for_icon_match),
            )
            if item_icon_references:
                base_references = list(merge_archive_reference_rows(base_references, item_icon_references))
        self.current_archive_model_texture_references = base_references
        asset_family_graph_for_view = asset_family_graph
        if isinstance(current_entry, ArchiveEntry) and (asset_family_graph_for_view is None or item_icon_references):
            if enrich:
                asset_family_graph_for_view = build_archive_asset_family_graph(
                    current_entry,
                    tuple(self.current_archive_model_texture_references),
                )
        if isinstance(current_entry, ArchiveEntry) and str(current_entry.extension or "").lower() == ".dds":
            if enrich:
                family_references = list(self.current_archive_model_texture_references)
                family_references.extend(self.current_archive_used_by_references)
                asset_family_graph_for_view = build_archive_asset_family_graph(current_entry, tuple(family_references))
        self.current_archive_asset_family_graph = asset_family_graph_for_view
        if isinstance(current_entry, ArchiveEntry) and isinstance(asset_family_graph_for_view, AssetFamilyGraph):
            self._remember_archive_asset_family_graph(
                current_entry,
                asset_family_graph_for_view,
                self.current_archive_model_texture_references,
            )
        asset_map_source_entry = (
            current_entry
            if enrich or isinstance(asset_family_graph_for_view, AssetFamilyGraph)
            else None
        )
        self._populate_archive_asset_map_tree(asset_map_source_entry, self.current_archive_model_texture_references, asset_family_graph_for_view)
        self._populate_archive_attachment_placement_tree(asset_family_graph_for_view)
        source_name = current_entry.basename if isinstance(current_entry, ArchiveEntry) else "selected file"
        self._populate_archive_relation_tree(
            self.archive_asset_uses_tree,
            self.current_archive_model_texture_references,
            source_name=source_name,
            reference_source="uses",
        )
        self._populate_archive_relation_tree(
            self.archive_asset_used_by_tree,
            self.current_archive_used_by_references,
            source_name=source_name,
            reference_source="used_by",
        )
        self.archive_texture_refs_tree.clear()
        group_items: Dict[str, QTreeWidgetItem] = {}
        raw_table_references = list(self.current_archive_model_texture_references)
        raw_table_sources: List[Tuple[str, int]] = [
            ("uses", index) for index in range(len(self.current_archive_model_texture_references))
        ]
        if isinstance(current_entry, ArchiveEntry) and str(current_entry.extension or "").lower() == ".dds":
            raw_table_sources.extend(("used_by", index) for index in range(len(self.current_archive_used_by_references)))
            raw_table_references.extend(self.current_archive_used_by_references)
        for index, reference in enumerate(raw_table_references):
            resolved_archive_path = str(getattr(reference, "resolved_archive_path", "") or "").strip()
            resolved_package_label = str(getattr(reference, "resolved_package_label", "") or "").strip()
            reference_name = str(getattr(reference, "reference_name", "") or "").strip()
            relation_group = self._archive_texture_reference_group_label(
                str(getattr(reference, "relation_group", "") or "").strip() or "Metadata / Other",
                reference_name,
                resolved_archive_path,
            )
            group_item = group_items.get(relation_group)
            if group_item is None:
                group_item = QTreeWidgetItem([relation_group, "", "", "", "", "", "", ""])
                group_item.setFlags(Qt.ItemIsEnabled)
                self.archive_texture_refs_tree.addTopLevelItem(group_item)
                group_item.setExpanded(True)
                group_items[relation_group] = group_item
            reference_display = reference_name or "-"
            if (
                str(getattr(reference, "relation_group", "") or "").strip() == "Textures"
                and resolved_archive_path.lower().endswith(".dds")
                and not PurePosixPath(reference_display.replace("\\", "/")).suffix
            ):
                reference_display = resolved_archive_path
            semantic_text = str(getattr(reference, "semantic_label", "") or "").strip() or "-"
            sidecar_parameter_name = str(getattr(reference, "sidecar_parameter_name", "") or "").strip()
            part_name = str(getattr(reference, "part_name", "") or "").strip()
            material_name = str(getattr(reference, "material_name", "") or "").strip()
            shader_family = str(getattr(reference, "shader_family", "") or "").strip()
            part_text = part_name or material_name or "-"
            if shader_family:
                part_text = f"{part_text} / {shader_family}" if part_text != "-" else shader_family
            visual_state = str(getattr(reference, "visualization_state", "") or "").strip()
            texture_role = str(getattr(reference, "texture_role", "") or "").strip()
            relation_confidence = str(getattr(reference, "relation_confidence", "") or "").strip()
            relation_confidence_label = self._archive_relation_confidence_label(relation_confidence)
            slot_text = texture_role or semantic_text
            if str(getattr(reference, "relation_group", "") or "").strip() == "Textures" and sidecar_parameter_name:
                slot_text = f"{slot_text} [{sidecar_parameter_name}]"
            item = QTreeWidgetItem(
                [
                    reference_display,
                    self._archive_texture_reference_status_text(reference),
                    part_text,
                    slot_text,
                    visual_state or relation_confidence_label or "-",
                    resolved_archive_path or "-",
                    resolved_package_label or "-",
                    str(max(1, int(getattr(reference, "usage_count", 0) or 0))),
                ]
            )
            if reference_name and reference_display != reference_name:
                item.setToolTip(0, f"Original reference: {reference_name}\nResolved DDS: {resolved_archive_path}")
            if material_name:
                item.setToolTip(0, "\n".join(part for part in [item.toolTip(0), f"Material: {material_name}"] if part))
            semantic_hint = str(getattr(reference, "semantic_hint", "") or "").strip()
            if semantic_hint:
                item.setToolTip(3, semantic_hint)
            linked_mesh_path = str(getattr(reference, "linked_mesh_path", "") or "").strip()
            sidecar_kind = str(getattr(reference, "sidecar_kind", "") or "").strip()
            if sidecar_kind or linked_mesh_path or shader_family:
                detail_lines = [
                    f"Sidecar: {sidecar_kind}" if sidecar_kind else "",
                    f"Linked mesh: {linked_mesh_path}" if linked_mesh_path else "",
                    f"Shader: {shader_family}" if shader_family else "",
                ]
                item.setToolTip(2, "\n".join(line for line in detail_lines if line))
            if visual_state:
                item.setToolTip(4, visual_state)
            relation_reason = str(getattr(reference, "relation_reason", "") or "").strip()
            if relation_reason or relation_confidence_label:
                reason_parts = [part for part in [relation_reason, relation_confidence_label] if part]
                item.setToolTip(0, "\n".join(part for part in [item.toolTip(0), "Why: " + " | ".join(reason_parts)] if part))
            if resolved_archive_path:
                item.setToolTip(5, resolved_archive_path)
            item.setData(0, Qt.UserRole, raw_table_sources[index] if index < len(raw_table_sources) else index)
            group_item.addChild(item)
        for relation_group, group_item in group_items.items():
            group_item.setText(0, f"{relation_group} ({group_item.childCount()})")
        has_asset_relationships = bool(
            self.current_archive_model_texture_references
            or self.current_archive_used_by_references
            or self.current_archive_family_member_rows
        )
        self.archive_texture_refs_group.setTitle("Asset Family")
        self.archive_texture_refs_group.setVisible(has_asset_relationships)
        self.archive_asset_family_button.setVisible(has_asset_relationships)
        self.archive_asset_family_button.setEnabled(has_asset_relationships)
        if hasattr(self, "archive_preview_content_splitter"):
            self.archive_preview_content_splitter.setCollapsible(1, not has_asset_relationships)
        if has_asset_relationships:
            self._refresh_archive_asset_family_panel_layout(prefer_default=True)
            self._schedule_archive_asset_family_panel_layout(prefer_default=True)
        else:
            # Preserve the user's Asset Family splitter width while loading or when a file
            # has no relationships; hiding the group is enough and avoids progressive shrink.
            pass
        self._update_archive_texture_reference_action_controls()

    def _clear_archive_texture_reference_views(self) -> None:
        self.pending_archive_texture_reference_update = None
        if hasattr(self, "archive_texture_reference_update_timer"):
            self.archive_texture_reference_update_timer.stop()
        self.current_archive_used_by_references = []
        self.current_archive_model_texture_references = []
        self.current_archive_family_member_rows = []
        self.current_archive_asset_family_graph = None
        for tree_name in (
            "archive_texture_refs_tree",
            "archive_asset_map_tree",
            "archive_asset_uses_tree",
            "archive_asset_used_by_tree",
            "archive_asset_placement_tree",
        ):
            tree = getattr(self, tree_name, None)
            if tree is not None:
                tree.clear()
        if hasattr(self, "archive_asset_family_summary_label"):
            self.archive_asset_family_summary_label.clear()
            self.archive_asset_family_summary_label.setVisible(False)
        if hasattr(self, "archive_texture_refs_group"):
            self.archive_texture_refs_group.setTitle("Asset Family")
            self.archive_texture_refs_group.setVisible(False)
        if hasattr(self, "archive_asset_family_button"):
            self.archive_asset_family_button.setVisible(False)
            self.archive_asset_family_button.setEnabled(False)
        if hasattr(self, "archive_preview_content_splitter"):
            self.archive_preview_content_splitter.setCollapsible(1, True)
        self._update_archive_texture_reference_action_controls()

    def _schedule_archive_texture_reference_update(
        self,
        references: Sequence[ArchiveModelTextureReference],
        asset_family_graph: Optional[AssetFamilyGraph],
        *,
        request_id: Optional[int] = None,
    ) -> None:
        scheduled_request_id = self.archive_preview_request_id if request_id is None else int(request_id)
        self.pending_archive_texture_reference_update = (
            scheduled_request_id,
            tuple(references or ()),
            asset_family_graph,
        )
        self.archive_texture_reference_update_timer.start()

    def _flush_archive_texture_reference_update(self) -> None:
        pending = self.pending_archive_texture_reference_update
        self.pending_archive_texture_reference_update = None
        if pending is None:
            return
        request_id, references, asset_family_graph = pending
        if int(request_id) != int(self.archive_preview_request_id):
            return
        self._populate_archive_texture_reference_list(
            references,
            asset_family_graph,
            enrich=False,
        )


__all__ = ["ArchiveAssetFamilyPanelMixin"]
