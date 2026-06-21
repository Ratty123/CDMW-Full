"""Archive in-game mesh swap scope dialog."""
from __future__ import annotations

import re
from collections.abc import Callable, Sequence
from pathlib import PurePosixPath
from typing import Dict, List, Optional

from PySide6.QtCore import Qt
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
)

from cdmw.core.archive import read_archive_entry_data, try_decode_text_like_archive_data
from cdmw.core.archive_relationships import (
    ARCHIVE_REL_INCLUDE_RECOMMENDED,
    ARCHIVE_REL_INCLUDE_REQUIRED,
    SWAP_SCOPE_BODY_HEAD,
    ArchiveRelationEdge,
    build_character_swap_plan,
)
from cdmw.domain.mesh.session import InGameMeshSwapScopeSelection
from cdmw.models import ArchiveEntry


class ArchiveMeshSwapScopeDialogMixin:
    def _prompt_archive_in_game_mesh_swap_scope(
        self,
        target_entry: ArchiveEntry,
        source_entry: ArchiveEntry,
    ) -> Optional[InGameMeshSwapScopeSelection]:
        source_related_entries_by_key: Dict[str, ArchiveEntry] = {}
        relationship_edges_by_key: Dict[str, ArchiveRelationEdge] = {}
        unresolved_relationship_edges: List[ArchiveRelationEdge] = []
        allow_character_scope = self._archive_entries_allow_character_swap_scope(target_entry, source_entry)
        item_family_scope = bool(
            not allow_character_scope
            and (
                self._archive_entry_is_equipment_model_for_swap(target_entry)
                or self._archive_entry_is_equipment_model_for_swap(source_entry)
            )
        )

        def _weapon_folder_segment(entry: ArchiveEntry) -> str:
            parts = list(PurePosixPath(str(entry.path or "").replace("\\", "/")).parts)
            lowered = [part.lower() for part in parts]
            try:
                weapon_index = lowered.index("weapon")
                return parts[weapon_index + 1].lower()
            except (ValueError, IndexError):
                return ""

        target_weapon_folder = _weapon_folder_segment(target_entry)
        source_weapon_folder = _weapon_folder_segment(source_entry)
        same_weapon_folder = bool(target_weapon_folder and source_weapon_folder and target_weapon_folder == source_weapon_folder)
        if allow_character_scope:
            try:
                character_relationship_plan = build_character_swap_plan(
                    target_entry,
                    source_entry,
                    self.archive_entries,
                    swap_scope=SWAP_SCOPE_BODY_HEAD,
                )
            except Exception:
                character_relationship_plan = None
        else:
            character_relationship_plan = None

        def _add_related_entry(entry: ArchiveEntry) -> None:
            key = self._archive_entry_identity_key(entry)
            if key and key not in source_related_entries_by_key:
                source_related_entries_by_key[key] = entry

        def _add_relationship_edge(edge: ArchiveRelationEdge) -> None:
            if edge.unresolved:
                unresolved_relationship_edges.append(edge)
                return
            entry = edge.related_entry
            if not isinstance(entry, ArchiveEntry):
                return
            key = self._archive_entry_identity_key(entry)
            if not key:
                return
            _add_related_entry(entry)
            current = relationship_edges_by_key.get(key)
            current_rank = 0
            if current is not None:
                current_rank = 3 if current.include_policy == ARCHIVE_REL_INCLUDE_REQUIRED else 2 if current.include_policy == ARCHIVE_REL_INCLUDE_RECOMMENDED else 1
            rank = 3 if edge.include_policy == ARCHIVE_REL_INCLUDE_REQUIRED else 2 if edge.include_policy == ARCHIVE_REL_INCLUDE_RECOMMENDED else 1
            if current is None or rank > current_rank:
                relationship_edges_by_key[key] = edge

        for related_entry in self._archive_model_related_entries_for_swap(source_entry):
            _add_related_entry(related_entry)
        if allow_character_scope:
            for edge in tuple(getattr(character_relationship_plan, "edges", ()) or ()):
                _add_relationship_edge(edge)
            for related_entry in self._archive_character_app_graph_entries_for_swap(source_entry):
                _add_related_entry(related_entry)
            for texture_entry in self._archive_character_app_graph_texture_entries_for_swap(source_entry):
                _add_related_entry(texture_entry)
        for texture_entry in self._archive_model_source_texture_entries_for_swap(source_entry):
            _add_related_entry(texture_entry)
        source_related_entries = list(source_related_entries_by_key.values())
        source_sidecar_entries_for_contract = tuple(self._archive_model_sidecar_entries_for_swap(source_entry))
        target_sidecar_entries_for_contract = tuple(self._archive_model_sidecar_entries_for_swap(target_entry))
        source_sidecar_paths = {entry.path for entry in source_sidecar_entries_for_contract}
        source_appearance_paths = (
            {entry.path for entry in self._archive_character_appearance_entries_for_swap(source_entry)}
            if allow_character_scope
            else set()
        )
        for related_entry in source_related_entries:
            if self._archive_entry_is_material_sidecar(related_entry):
                source_sidecar_paths.add(related_entry.path)
            if self._archive_entry_is_appearance_descriptor(related_entry):
                source_appearance_paths.add(related_entry.path)
        if item_family_scope:
            source_stem = PurePosixPath(source_entry.path.replace("\\", "/")).stem.lower()

            def _is_item_family_related_entry(entry: ArchiveEntry) -> bool:
                normalized_path = entry.path.replace("\\", "/").strip().lower()
                basename = PurePosixPath(normalized_path).name.lower()
                extension = str(entry.extension or "").strip().lower()
                if extension == ".dds":
                    return True
                if self._archive_entry_is_material_sidecar(entry) and entry.path in source_sidecar_paths:
                    return True
                if source_stem and source_stem in basename:
                    return True
                return False

            source_related_entries = [
                entry
                for entry in source_related_entries
                if _is_item_family_related_entry(entry)
            ]
        source_related_entries.sort(
            key=lambda entry: (
                self._archive_entry_swap_companion_group(entry),
                entry.path.replace("\\", "/").casefold(),
            )
        )

        def _is_source_item_meshphysics(entry: ArchiveEntry) -> bool:
            normalized_path = entry.path.replace("\\", "/").strip().lower()
            basename = PurePosixPath(normalized_path).name.lower()
            source_stem = PurePosixPath(source_entry.path.replace("\\", "/")).stem.lower()
            return bool(
                str(entry.extension or "").strip().lower() in {".hkx", ".hkt"}
                and "meshphysics" in normalized_path
                and source_stem
                and source_stem in basename
            )

        def _is_source_physics_companion(entry: ArchiveEntry) -> bool:
            return str(entry.extension or "").strip().lower() in {".hkx", ".hkt"}

        def _material_contract_stats(entries: Sequence[ArchiveEntry]) -> Dict[str, object]:
            wrapper_count = 0
            pbd_names: List[str] = []
            pbd_hits = 0
            for sidecar_entry in entries:
                try:
                    sidecar_data, _decompressed, _note = read_archive_entry_data(sidecar_entry)
                    sidecar_text = try_decode_text_like_archive_data(sidecar_data) or sidecar_data.decode(
                        "utf-8",
                        errors="replace",
                    )
                except Exception:
                    continue
                wrapper_count += len(
                    re.findall(r"<\s*SkinnedMeshMaterialWrapper\b", sidecar_text, flags=re.IGNORECASE)
                )
                pbd_names.extend(
                    value.strip()
                    for value in re.findall(
                        r"_pbdSimulationMaterialName\s*=\s*\"([^\"]+)\"",
                        sidecar_text,
                        flags=re.IGNORECASE,
                    )
                    if value.strip()
                )
                pbd_hits += len(
                    re.findall(
                        r"_pbdSimulationMaterialName|<\s*OverridedPbdMaterialProperty\b|\bpbd\b",
                        sidecar_text,
                        flags=re.IGNORECASE,
                    )
                )
            unique_pbd_names = tuple(dict.fromkeys(pbd_names))
            return {
                "wrappers": wrapper_count,
                "pbd_hits": pbd_hits,
                "pbd_names": unique_pbd_names,
            }

        source_contract_stats = _material_contract_stats(source_sidecar_entries_for_contract)
        target_contract_stats = _material_contract_stats(target_sidecar_entries_for_contract)
        source_wrapper_count = int(source_contract_stats.get("wrappers") or 0)
        target_wrapper_count = int(target_contract_stats.get("wrappers") or 0)
        source_has_pbd_contract = int(source_contract_stats.get("pbd_hits") or 0) > 0
        source_has_larger_material_contract = bool(
            source_wrapper_count > 0
            and target_wrapper_count > 0
            and source_wrapper_count > target_wrapper_count
        )
        preserve_source_contract_default = bool(
            item_family_scope and (source_has_pbd_contract or source_has_larger_material_contract)
        )
        complete_swap_scope_default = True

        dialog = QDialog(self)
        dialog.setWindowTitle("In-Game Mesh Swap Scope")
        dialog.setMinimumSize(980, 620)
        layout = QVBoxLayout(dialog)
        intro = QLabel(
            "Choose what to include with this swap. "
            "Checked rows are written as loose replacement payloads at the target path shown. "
            "For weapon/item swaps, source family files can be retargeted to the target family paths. "
            "Skeleton and animation files remain manual because replacing .pab/.hkx can break assets that do not share the same rig or physics contract."
        )
        intro.setWordWrap(True)
        intro.setObjectName("HintLabel")
        layout.addWidget(intro)

        if preserve_source_contract_default:
            pbd_names = tuple(source_contract_stats.get("pbd_names") or ())
            contract_reason_parts: List[str] = []
            if source_has_pbd_contract:
                pbd_preview = ", ".join(str(name) for name in pbd_names[:3]) if pbd_names else "PBD/cloth metadata"
                contract_reason_parts.append(f"source material sidecar has cloth/PBD simulation ({pbd_preview})")
            if source_has_larger_material_contract:
                contract_reason_parts.append(
                    f"source has {source_wrapper_count} material wrapper(s), target has {target_wrapper_count}"
                )
                contract_warning = QLabel(
                    "Donor material contract warning: "
                    + "; ".join(contract_reason_parts)
                + ". Defaulting to Complete In-Game Swap through the placement workflow. "
                "This keeps transform/removal review, routes source-owned materials, and auto-selects source physics with a crash-risk warning."
            )
            contract_warning.setWordWrap(True)
            contract_warning.setStyleSheet("color: #fdd663;")
            layout.addWidget(contract_warning)

        complete_swap_checkbox = QCheckBox("Complete In-Game Swap (source mesh/material/textures/physics)")
        complete_swap_checkbox.setChecked(bool(complete_swap_scope_default))
        complete_swap_checkbox.setToolTip(
            "Recommended default. Uses placement/rebuild so offsets, transforms, and removed parts still apply, "
            "then enables complete source-owned material routing and includes source DDS plus HKX/HKT physics rows."
        )
        generated_sidecar_checkbox = QCheckBox("Default to generated/retargeted material sidecar in Mesh Replacement Alignment")
        generated_sidecar_checkbox.setChecked(True)
        generated_sidecar_checkbox.setToolTip(
            "This preselects the alignment option that patches the target material sidecar from the mapping/texture plan."
        )
        direct_source_model_checkbox = QCheckBox("Use source model payload directly instead of rebuilding target geometry")
        direct_source_model_checkbox.setChecked(False)
        direct_source_model_checkbox.setToolTip(
            "Writes the selected source .pac/.pam/.pamlod bytes to the target model path. "
            "This best preserves source material/physics contracts, but the alignment transform is not applied."
        )
        retarget_source_family_checkbox = QCheckBox("Retarget selected source item-family files to target paths")
        retarget_source_family_checkbox.setChecked(bool(item_family_scope))
        retarget_source_family_checkbox.setToolTip(
            "For weapon/item swaps, copy selected source sidecar, physics, and prefab files onto matching target-family paths. "
            "Source DDS textures stay at source texture paths because source sidecars reference them there."
        )
        replace_source_sidecar_checkbox = QCheckBox("Replace target material sidecar with selected source sidecar payload")
        replace_source_sidecar_checkbox.setChecked(False)
        replace_source_sidecar_checkbox.setToolTip(
            "Copies selected source .pac_xml/.pami/.xml bytes into the target material sidecar path. Review carefully."
        )
        replace_source_appearance_checkbox = QCheckBox("Replace target appearance descriptor with selected source .app_xml")
        replace_source_appearance_checkbox.setChecked(False)
        replace_source_appearance_checkbox.setToolTip(
            "Experimental character swap path. Copies the selected source Appearance XML into the matching target Appearance XML path, "
            "so the game can follow source prefab, customization, scale, skeleton-variation, and socket references."
        )
        character_swap_plan_checkbox = QCheckBox("Use Character Swap Plan (experimental)")
        character_swap_plan_checkbox.setChecked(bool(allow_character_scope and getattr(character_relationship_plan, "patched_target_app_xml", b"")))
        character_swap_plan_checkbox.setToolTip(
            "Builds a surgical target appearance patch from the selected source: body/head by default, while preserving target hair, armor, skeleton, and physics."
        )
        if not allow_character_scope:
            replace_source_appearance_checkbox.setChecked(False)
            replace_source_appearance_checkbox.setEnabled(False)
            replace_source_appearance_checkbox.setToolTip("Disabled for weapon/item swaps; character appearance graphs are not used for this source.")
            character_swap_plan_checkbox.setChecked(False)
            character_swap_plan_checkbox.setEnabled(False)
            character_swap_plan_checkbox.setToolTip("Disabled for weapon/item swaps; this avoids pulling unrelated head/hair/beard appearance files.")
        if not item_family_scope:
            retarget_source_family_checkbox.setEnabled(False)
            retarget_source_family_checkbox.setToolTip("Available for weapon/item model swaps.")
        complete_swap_warning = QLabel(
            "Complete swap auto-selects source DDS textures and all source HKX/HKT physics rows. "
            "Physics overrides can crash when source and target do not share the same runtime contract; skeleton rows remain manual."
        )
        complete_swap_warning.setWordWrap(True)
        complete_swap_warning.setStyleSheet("color: #fdd663;")
        complete_swap_warning.setVisible(bool(complete_swap_checkbox.isChecked()))
        layout.addWidget(complete_swap_checkbox)
        layout.addWidget(complete_swap_warning)
        layout.addWidget(generated_sidecar_checkbox)
        layout.addWidget(direct_source_model_checkbox)
        layout.addWidget(retarget_source_family_checkbox)
        layout.addWidget(replace_source_sidecar_checkbox)
        layout.addWidget(replace_source_appearance_checkbox)
        layout.addWidget(character_swap_plan_checkbox)
        scope_help_row = QHBoxLayout()
        scope_help_row.setContentsMargins(0, 0, 0, 0)
        scope_help_button = QPushButton("Help: what should I choose?")
        scope_help_button.setToolTip("Explain the swap-scope options and safe defaults.")
        scope_help_row.addWidget(scope_help_button)
        scope_help_row.addStretch(1)
        layout.addLayout(scope_help_row)

        companion_label = QLabel("Source companion files")
        companion_label.setObjectName("SectionTitle")
        layout.addWidget(companion_label)

        companion_tree = QTreeWidget()
        companion_tree.setColumnCount(5)
        companion_tree.setHeaderLabels(["Include", "Type", "What this row means", "Source path", "Target path"])
        companion_tree.setRootIsDecorated(False)
        companion_tree.setAlternatingRowColors(True)
        companion_tree.setSelectionMode(QAbstractItemView.ExtendedSelection)
        companion_tree.header().resizeSection(0, 82)
        companion_tree.header().resizeSection(1, 130)
        companion_tree.header().resizeSection(2, 300)
        companion_tree.header().resizeSection(3, 360)
        layout.addWidget(companion_tree, 1)

        entries_by_key: Dict[str, ArchiveEntry] = {}

        def _entry_key(entry: ArchiveEntry) -> str:
            normalized_path = entry.path.replace("\\", "/")
            return f"{entry.pamt_path.resolve()}::{normalized_path}"

        def _behavior_text(entry: ArchiveEntry) -> str:
            edge = relationship_edges_by_key.get(_entry_key(entry))
            if edge is not None:
                if edge.risk:
                    label = "Manual/risky"
                elif edge.include_policy == ARCHIVE_REL_INCLUDE_REQUIRED:
                    label = "Planned output"
                elif edge.include_policy == ARCHIVE_REL_INCLUDE_RECOMMENDED:
                    label = "Detected reference"
                else:
                    label = "Manual option"
                return f"{label}: {edge.reason or edge.relation_kind}."
            if self._archive_entry_is_material_sidecar(entry):
                target_path, _target_sidecar = self._target_sidecar_path_for_source_sidecar(target_entry, entry)
                return f"Can replace target sidecar: {target_path}"
            if self._archive_entry_is_appearance_descriptor(entry):
                target_path, _target_appearance = self._target_appearance_path_for_source_appearance(target_entry, entry)
                if target_path:
                    return f"Can replace target appearance descriptor: {target_path}"
                return "Source appearance descriptor; no matching target appearance XML was found automatically"
            if self._archive_entry_is_prefab_descriptor(entry):
                return "Prefab metadata referenced by appearance XML; copy only when the source asset is not already available in game"
            if entry.extension == ".dds":
                return "Override DDS at this archive path while the mod is enabled"
            if entry.extension in {".hkx", ".hkt"} and item_family_scope and not same_weapon_folder:
                return (
                    "Risky physics override: source and target are different weapon folders. "
                    "Complete swap selects this row, but it can crash if the runtime physics contracts do not match."
                )
            if entry.extension in {".pab", ".pabc", ".pabv", ".hkx", ".hkt"}:
                return "REPLACES this game file while enabled; rig/physics-sensitive"
            return "Override companion at this archive path while enabled"

        def _target_path_for_scope_row(entry: ArchiveEntry) -> str:
            if retarget_source_family_checkbox.isChecked():
                target_path, _target_entry = self._target_family_path_for_source_companion(
                    target_entry,
                    source_entry,
                    entry,
                )
                return target_path
            if self._archive_entry_is_material_sidecar(entry) and replace_source_sidecar_checkbox.isChecked():
                target_path, _target_entry = self._target_sidecar_path_for_source_sidecar(target_entry, entry)
                return target_path
            if self._archive_entry_is_appearance_descriptor(entry) and replace_source_appearance_checkbox.isChecked():
                target_path, _target_entry = self._target_appearance_path_for_source_appearance(target_entry, entry)
                return target_path
            return entry.path.replace("\\", "/")

        for related_entry in source_related_entries:
            key = _entry_key(related_entry)
            entries_by_key[key] = related_entry
            item = QTreeWidgetItem(
                [
                    "",
                    self._archive_entry_swap_companion_group(related_entry),
                    _behavior_text(related_entry),
                    related_entry.path.replace("\\", "/"),
                    _target_path_for_scope_row(related_entry),
                ]
            )
            item.setData(0, Qt.UserRole, key)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            default_checked = False
            edge = relationship_edges_by_key.get(key)
            if edge is not None and edge.include_policy in {ARCHIVE_REL_INCLUDE_REQUIRED, ARCHIVE_REL_INCLUDE_RECOMMENDED} and not edge.risk:
                # Safe graph rows are selected only when the surgical character plan is active.
                default_checked = bool(character_swap_plan_checkbox.isChecked()) and related_entry.extension == ".dds"
            if complete_swap_scope_default:
                default_checked = bool(
                    related_entry.extension == ".dds"
                    or _is_source_physics_companion(related_entry)
                )
            elif item_family_scope and retarget_source_family_checkbox.isChecked():
                default_checked = (
                    related_entry.extension == ".dds"
                    or (
                        preserve_source_contract_default
                        and related_entry.path in source_sidecar_paths
                        and self._archive_entry_is_material_sidecar(related_entry)
                    )
                )
            elif related_entry.path in source_sidecar_paths and self._archive_entry_is_material_sidecar(related_entry):
                default_checked = False
            if related_entry.path in source_appearance_paths and self._archive_entry_is_appearance_descriptor(related_entry):
                default_checked = False
            item.setCheckState(0, Qt.Checked if default_checked else Qt.Unchecked)
            if related_entry.extension in {".pab", ".pabc", ".pabv", ".hkx", ".hkt"}:
                item.setForeground(1, QBrush(QColor("#facc15")))
            if self._archive_entry_is_appearance_descriptor(related_entry):
                item.setForeground(1, QBrush(QColor("#79c0ff")))
            companion_tree.addTopLevelItem(item)

        for edge in unresolved_relationship_edges[:48]:
            item = QTreeWidgetItem(
                [
                    "",
                    "Unresolved",
                    edge.reason or "Referenced file was not found in the loaded archive indexes.",
                    edge.related_path,
                    "",
                ]
            )
            item.setFlags(item.flags() & ~Qt.ItemIsUserCheckable)
            item.setForeground(1, QBrush(QColor("#facc15")))
            companion_tree.addTopLevelItem(item)

        if companion_tree.topLevelItemCount() == 0:
            empty_item = QTreeWidgetItem(["", "None", "No source companion files were detected.", "", ""])
            empty_item.setFlags(empty_item.flags() & ~Qt.ItemIsEnabled)
            companion_tree.addTopLevelItem(empty_item)

        helper = QLabel(
            "For weapon/item swaps, source material sidecar + source DDS is the safest default donor contract. "
            "Complete In-Game Swap auto-selects source DDS and all source HKX/HKT physics rows, with a visible warning because cross-family physics can crash in game. "
            "The direct source model option preserves that contract best, but it skips alignment transforms. "
            "Appearance descriptors are separate from material sidecars: for character body swaps they can redirect the target character to source prefabs, "
            "customization metadata, scale values, skeleton variations, sockets, and prefabdata references. "
            ".pab/.pabc skeleton and .hkx/.hkt physics rows are not merged or transformed: if checked, the mod overrides that target archive file while enabled. "
            "For full character swaps this may be required, but it should be tested in game."
        )
        helper.setWordWrap(True)
        helper.setObjectName("HintLabel")
        layout.addWidget(helper)

        button_row = QHBoxLayout()
        select_item_family_button = QPushButton("Select Item Family")
        select_item_family_button.setToolTip(
            "Select source sidecar and source DDS textures for weapon/item swaps. "
            "Use Complete In-Game Swap or Select Physics when source HKX/HKT should replace target physics; prefab/socket rows stay manual."
        )
        select_textures_button = QPushButton("Select Textures")
        select_sidecars_button = QPushButton("Select Sidecars")
        select_physics_button = QPushButton("Select Physics")
        select_physics_button.setToolTip(
            "Select all source HKX/HKT rows. Physics contracts can differ across one-hand, two-hand, ranged, and accessory assets, so test in game."
        )
        select_appearance_button = QPushButton("Select Graph Textures")
        select_appearance_button.setToolTip(
            "Select only the safe DDS texture rows resolved from the character appearance graph. Risky app, sidecar, skeleton, and physics rows remain manual."
        )
        clear_button = QPushButton("Clear")
        button_row.addWidget(select_item_family_button)
        button_row.addWidget(select_textures_button)
        button_row.addWidget(select_sidecars_button)
        button_row.addWidget(select_physics_button)
        button_row.addWidget(select_appearance_button)
        button_row.addWidget(clear_button)
        button_row.addStretch(1)
        cancel_button = QPushButton("Cancel")
        continue_button = QPushButton("Continue")
        continue_button.setDefault(True)
        button_row.addWidget(cancel_button)
        button_row.addWidget(continue_button)
        layout.addLayout(button_row)

        def _set_checked_by_predicate(predicate: Callable[[ArchiveEntry], bool], checked: bool) -> None:
            for index in range(companion_tree.topLevelItemCount()):
                item = companion_tree.topLevelItem(index)
                if item is None or not (item.flags() & Qt.ItemIsUserCheckable):
                    continue
                entry = entries_by_key.get(str(item.data(0, Qt.UserRole) or ""))
                if entry is not None and predicate(entry):
                    item.setCheckState(0, Qt.Checked if checked else Qt.Unchecked)

        def _refresh_scope_target_paths() -> None:
            for index in range(companion_tree.topLevelItemCount()):
                item = companion_tree.topLevelItem(index)
                if item is None:
                    continue
                entry = entries_by_key.get(str(item.data(0, Qt.UserRole) or ""))
                item.setText(4, _target_path_for_scope_row(entry) if entry is not None else "")

        def _select_complete_swap_entries() -> None:
            generated_sidecar_checkbox.setChecked(True)
            direct_source_model_checkbox.setChecked(False)
            replace_source_sidecar_checkbox.setChecked(False)
            if item_family_scope:
                retarget_source_family_checkbox.setChecked(True)
            for index in range(companion_tree.topLevelItemCount()):
                item = companion_tree.topLevelItem(index)
                if item is None or not (item.flags() & Qt.ItemIsUserCheckable):
                    continue
                entry = entries_by_key.get(str(item.data(0, Qt.UserRole) or ""))
                if entry is None:
                    continue
                should_select = bool(
                    entry.extension == ".dds"
                    or _is_source_physics_companion(entry)
                )
                item.setCheckState(0, Qt.Checked if should_select else Qt.Unchecked)
            _refresh_scope_target_paths()

        def _sync_complete_swap_scope_mode(checked: bool) -> None:
            checked = bool(checked)
            complete_swap_warning.setVisible(checked)
            generated_sidecar_checkbox.setEnabled(not checked)
            direct_source_model_checkbox.setEnabled(not checked)
            replace_source_sidecar_checkbox.setEnabled(not checked)
            retarget_source_family_checkbox.setEnabled(bool(item_family_scope and not checked))
            if checked:
                _select_complete_swap_entries()
            else:
                if not item_family_scope:
                    retarget_source_family_checkbox.setEnabled(False)
                _refresh_scope_target_paths()

        def _select_item_family_entries() -> None:
            if not item_family_scope:
                return
            complete_swap_checkbox.setChecked(False)
            retarget_source_family_checkbox.setChecked(True)
            replace_source_sidecar_checkbox.setChecked(True)
            generated_sidecar_checkbox.setChecked(False)
            for index in range(companion_tree.topLevelItemCount()):
                item = companion_tree.topLevelItem(index)
                if item is None or not (item.flags() & Qt.ItemIsUserCheckable):
                    continue
                entry = entries_by_key.get(str(item.data(0, Qt.UserRole) or ""))
                if entry is None:
                    continue
                extension = str(entry.extension or "").strip().lower()
                should_select = (
                    extension == ".dds"
                    or self._archive_entry_is_material_sidecar(entry)
                    or (_is_source_item_meshphysics(entry) and same_weapon_folder)
                )
                if should_select:
                    item.setCheckState(0, Qt.Checked)
            _refresh_scope_target_paths()

        def _select_character_graph_entries() -> None:
            selected_count = 0
            if not allow_character_scope:
                return
            for index in range(companion_tree.topLevelItemCount()):
                item = companion_tree.topLevelItem(index)
                if item is None or not (item.flags() & Qt.ItemIsUserCheckable):
                    continue
                entry = entries_by_key.get(str(item.data(0, Qt.UserRole) or ""))
                if entry is None:
                    continue
                entry_key = self._archive_entry_identity_key(entry)
                edge = relationship_edges_by_key.get(entry_key)
                should_select = (
                    edge is not None
                    and edge.include_policy in {ARCHIVE_REL_INCLUDE_REQUIRED, ARCHIVE_REL_INCLUDE_RECOMMENDED}
                    and not edge.risk
                    and entry.extension == ".dds"
                )
                if should_select:
                    item.setCheckState(0, Qt.Checked)
                    selected_count += 1
            if selected_count:
                character_swap_plan_checkbox.blockSignals(True)
                character_swap_plan_checkbox.setChecked(True)
                character_swap_plan_checkbox.blockSignals(False)

        select_item_family_button.setEnabled(bool(item_family_scope))
        select_item_family_button.clicked.connect(_select_item_family_entries)
        select_textures_button.clicked.connect(lambda: _set_checked_by_predicate(lambda entry: entry.extension == ".dds", True))
        select_sidecars_button.clicked.connect(lambda: _set_checked_by_predicate(self._archive_entry_is_material_sidecar, True))
        select_sidecars_button.clicked.connect(_refresh_scope_target_paths)
        select_physics_button.clicked.connect(
            lambda _checked=False: _set_checked_by_predicate(
                lambda entry: _is_source_physics_companion(entry),
                True,
            )
        )
        select_physics_button.clicked.connect(_refresh_scope_target_paths)
        replace_source_sidecar_checkbox.toggled.connect(lambda _checked: _refresh_scope_target_paths())
        replace_source_appearance_checkbox.toggled.connect(lambda _checked: _refresh_scope_target_paths())
        retarget_source_family_checkbox.toggled.connect(lambda _checked: _refresh_scope_target_paths())
        complete_swap_checkbox.toggled.connect(_sync_complete_swap_scope_mode)
        direct_source_model_checkbox.toggled.connect(
            lambda checked: (
                complete_swap_checkbox.setChecked(False),
                generated_sidecar_checkbox.setChecked(False),
                replace_source_sidecar_checkbox.setChecked(True),
                retarget_source_family_checkbox.setChecked(True),
                _select_item_family_entries(),
            )
            if checked and item_family_scope
            else None
        )
        select_appearance_button.clicked.connect(_select_character_graph_entries)
        select_appearance_button.setEnabled(bool(allow_character_scope))
        clear_button.clicked.connect(lambda: _set_checked_by_predicate(lambda _entry: True, False))
        cancel_button.clicked.connect(dialog.reject)
        continue_button.clicked.connect(dialog.accept)

        def _show_swap_scope_help() -> None:
            QMessageBox.information(
                dialog,
                "In-Game Swap Scope Help",
                (
                    "Recommended character/body swap defaults:\n"
                    "- Keep generated/retargeted material sidecar enabled.\n"
                    "- Leave direct source material sidecar replacement off.\n"
                    "- Leave full source .app_xml replacement off.\n"
                    "- Use Character Swap Plan when swapping character body/head assets.\n\n"
                    "Recommended weapon/item swap defaults:\n"
                    "- Use Select Item Family when the source has its own material sidecar and textures.\n"
                    "- Use Select Physics only when the source and target physics contract is intentionally being replaced.\n"
                    "- Use direct source model payload when preserving donor physics/material wrappers matters more than alignment transforms.\n"
                    "- Keep prefab/socket rows manual unless you intentionally want to change held/sheath placement metadata.\n\n"
                    "Generated/retargeted material sidecar means the later alignment step patches the target .pac_xml/.pami from the reviewed mapping and texture plan. "
                    "This is usually safer than copying the source .pac_xml because source and target submesh wrappers can differ.\n\n"
                    "Replace target material sidecar copies selected source sidecar bytes onto the target sidecar path. Use this only for manual experiments.\n\n"
                    "Replace target appearance descriptor copies the full source .app_xml. This can redirect hair, armor, customization, scale, sockets, prefab data, and other character graph links.\n\n"
                    "Character Swap Plan creates a surgical target .app_xml patch for body/head references while preserving target hair, armor, skeleton, and physics by default.\n\n"
                    "Checked table rows are written as loose replacement payloads. Rows marked as detected references are shown for context and manual selection; they are not automatically required just because they were found.\n\n"
                    "Select Graph Textures selects only safe DDS texture rows from the character graph. Sidecars, skeleton, physics, and full appearance descriptors remain explicit manual choices."
                ),
            )

        scope_help_button.clicked.connect(_show_swap_scope_help)

        def _character_swap_plan_toggled(checked: bool) -> None:
            if not checked:
                return
            _select_character_graph_entries()

        character_swap_plan_checkbox.toggled.connect(_character_swap_plan_toggled)
        _sync_complete_swap_scope_mode(bool(complete_swap_checkbox.isChecked()))

        if dialog.exec() != QDialog.Accepted:
            return None

        selected_entries: List[ArchiveEntry] = []
        for index in range(companion_tree.topLevelItemCount()):
            item = companion_tree.topLevelItem(index)
            if item is None or item.checkState(0) != Qt.Checked:
                continue
            entry = entries_by_key.get(str(item.data(0, Qt.UserRole) or ""))
            if entry is not None:
                selected_entries.append(entry)
        if character_swap_plan_checkbox.isChecked():
            selected_keys = {self._archive_entry_identity_key(entry) for entry in selected_entries}
            for edge in tuple(getattr(character_relationship_plan, "edges", ()) or ()):
                if edge.risk or edge.include_policy not in {ARCHIVE_REL_INCLUDE_REQUIRED, ARCHIVE_REL_INCLUDE_RECOMMENDED}:
                    continue
                entry = edge.related_entry
                if not isinstance(entry, ArchiveEntry) or entry.extension != ".dds":
                    continue
                key = self._archive_entry_identity_key(entry)
                if key and key not in selected_keys:
                    selected_entries.append(entry)
                    selected_keys.add(key)
        return InGameMeshSwapScopeSelection(
            complete_swap=bool(complete_swap_checkbox.isChecked()),
            prefer_generated_sidecar=bool(generated_sidecar_checkbox.isChecked()),
            use_source_model_payload_directly=bool(direct_source_model_checkbox.isChecked()),
            retarget_source_family_files=bool(retarget_source_family_checkbox.isChecked()),
            replace_target_sidecar_with_source=bool(replace_source_sidecar_checkbox.isChecked()),
            replace_target_appearance_with_source=bool(replace_source_appearance_checkbox.isChecked()),
            use_character_swap_plan=bool(character_swap_plan_checkbox.isChecked()),
            include_physics=any(_is_source_physics_companion(entry) for entry in selected_entries),
            companion_entries=tuple(selected_entries),
        )
