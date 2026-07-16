"""Archive attachment placement diff dialog."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from html import escape
from pathlib import Path, PurePosixPath
from typing import Dict, List, Optional, Tuple

from PySide6.QtCore import QThread, Qt, QTimer
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSplitter,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from cdmw.domain.archives.attachments import PrefabAttachmentProfilePatchResult
from cdmw.services.archive_workflow_service import (
    build_attachment_body_location_choices,
    build_pac_xml_stack_equip_type_patch,
    build_part_in_out_socket_attach_point_patch,
    build_part_in_out_socket_class_copy_patch,
    build_part_in_out_socket_profile_patch,
    build_prefab_attachment_profile_patch,
    build_socket_bone_data_profile_patch,
    infer_attachment_child_socket_name,
    infer_part_in_out_weapon_class,
    infer_stack_equip_type_for_socket,
    inspect_prefab_attachment_profile_fields,
    parse_part_in_out_socket_info_xml,
    parse_socket_bone_data_xml,
    part_in_out_rows_for_weapon_class,
)
from cdmw.domain.archives.filters import (
    archive_entry_identity_key,
    archive_entry_is_mod_package,
    archive_entry_load_priority,
)
from cdmw.services.archive_workflow_service import (
    build_iteminfo_behavior_equip_type_patch,
    build_universal_twohand_sword_animation_alias_plan,
    build_universal_twohand_sword_true_onehand_iteminfo_patch,
)
from cdmw.domain.archives.mesh_contracts import (
    ArchiveLooseExportResult,
    MeshImportSupplementalFileSpec,
)
from cdmw.services.archive_mutation_service import ArchivePatchRequest
from cdmw.services.archive_workflow_service import export_archive_payloads_to_mod_ready_loose
from cdmw.domain.library.item_icons import (
    ITEM_ICON_SOURCE_EXTENSIONS,
    ItemIconOverrideSpec,
)
from cdmw.domain.xml_text import decode_xml_text_payload, encode_xml_text_like_source
from cdmw.domain.mesh.session import PlacementLooseRootPreparation, PlacementWorkspacePreparation
from cdmw.models import (
    ArchiveEntry,
    ArchiveEntryIdentity,
    AssetFamilyGraph,
    AssetFamilyMember,
    AttachmentAnimationAliasPlanResult,
    AttachmentBodyLocationChoice,
    AttachmentItemInfoBehaviorPatchResult,
    AttachmentPartInOutDocument,
    AttachmentPartInOutPatchResult,
    AttachmentPlacementEvidence,
    AttachmentSocketDocument,
    AttachmentSocketInfo,
    AttachmentStackEquipTypePatchResult,
    AttachmentUniversalItemInfoBehaviorPatchResult,
)
from cdmw.ui.archive_browser.attachment_prepared_payloads import AttachmentPreparedPayloads
from cdmw.ui.archive_browser.attachment_profile_import import start_attachment_profile_import
from cdmw.ui.shell.responsiveness_controller import expand_tree_columns_to_available_width
from cdmw.ui.widgets import CollapsibleSection
from cdmw.workers.attachment_io_workers import (
    ATTACHMENT_PAYLOAD_MAX_BYTES,
    AttachmentPayloadReadRequest,
    run_attachment_payload_read,
)


class ArchiveAttachmentPlacementDiffDialogMixin:
    """Placement comparison dialog for attachment workflows."""

    def _open_archive_attachment_placement_diff_dialog(
        self,
        target_entry: ArchiveEntry,
        donor_entry: Optional[ArchiveEntry] = None,
        *,
        preparation: Optional[PlacementWorkspacePreparation] = None,
    ) -> None:
        preparation_matches = bool(
            isinstance(preparation, PlacementWorkspacePreparation)
            and isinstance(preparation.target_graph, AssetFamilyGraph)
            and self._same_archive_entry(preparation.target_entry, target_entry)
            and (
                (not isinstance(donor_entry, ArchiveEntry) and not isinstance(preparation.donor_entry, ArchiveEntry))
                or (
                    isinstance(donor_entry, ArchiveEntry)
                    and isinstance(preparation.donor_entry, ArchiveEntry)
                    and self._same_archive_entry(preparation.donor_entry, donor_entry)
                )
            )
        )
        if not preparation_matches:
            self._run_archive_attachment_placement_prepare(
                target_entry,
                donor_entry,
                status_message=f"Preparing placement comparison for {target_entry.basename}...",
                on_prepared=lambda prepared: self._open_archive_attachment_placement_diff_dialog(
                    target_entry,
                    donor_entry,
                    preparation=prepared,
                ),
            )
            return
        assert isinstance(preparation, PlacementWorkspacePreparation)
        assert isinstance(preparation.target_graph, AssetFamilyGraph)
        target_graph = preparation.target_graph
        donor_graph = (
            preparation.donor_graph
            if isinstance(donor_entry, ArchiveEntry) and isinstance(preparation.donor_graph, AssetFamilyGraph)
            else AssetFamilyGraph(
                root_path="",
                family_key="",
                summary="No placement source selected. Choose a body location to build XML-only placement, or open Advanced source copy.",
            )
        )
        package_plan_rows: List[dict] = []
        package_plan_warnings: List[str] = []
        dialog = QDialog(self)
        dialog.setWindowTitle("Weapon Placement")
        dialog.setWindowFlags(
            dialog.windowFlags()
            | Qt.WindowMaximizeButtonHint
            | Qt.WindowMinimizeButtonHint
        )
        dialog.setSizeGripEnabled(True)
        dialog.resize(1180, 760)
        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)
        intro = QLabel(
            "Move the target weapon between 1H/2H body placements. Default output changes placement only; target model, textures, icon, and physics stay intact."
        )
        intro.setObjectName("HintLabel")
        intro.setWordWrap(True)
        layout.addWidget(intro)
        direction_label = QLabel(
            f"Target to change: {target_entry.path}"
            + (f"\nPlacement source: {donor_entry.path}" if isinstance(donor_entry, ArchiveEntry) else "\nPlacement source: none selected")
        )
        direction_label.setObjectName("HintLabel")
        direction_label.setWordWrap(True)
        direction_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(direction_label)
        main_splitter = QSplitter(Qt.Horizontal)
        main_splitter.setChildrenCollapsible(False)
        main_splitter.setHandleWidth(10)
        layout.addWidget(main_splitter, 1)

        left_column = QWidget()
        left_column.setMinimumWidth(420)
        left_column_layout = QVBoxLayout(left_column)
        left_column_layout.setContentsMargins(0, 0, 0, 0)
        left_column_layout.setSpacing(8)
        left_scroll = QScrollArea(dialog)
        left_scroll.setWidgetResizable(True)
        left_scroll.setMinimumWidth(0)
        left_scroll_content = QWidget()
        left_scroll_layout = QVBoxLayout(left_scroll_content)
        left_scroll_layout.setContentsMargins(0, 0, 0, 0)
        left_scroll_layout.setSpacing(8)
        left_scroll.setWidget(left_scroll_content)
        left_column_layout.addWidget(left_scroll, 1)
        main_splitter.addWidget(left_column)

        right_column = QWidget()
        right_column.setMinimumWidth(420)
        right_column_layout = QVBoxLayout(right_column)
        right_column_layout.setContentsMargins(0, 0, 0, 0)
        right_column_layout.setSpacing(8)
        right_scroll = QScrollArea(dialog)
        right_scroll.setWidgetResizable(True)
        right_scroll.setMinimumWidth(0)
        right_scroll_content = QWidget()
        right_scroll_layout = QVBoxLayout(right_scroll_content)
        right_scroll_layout.setContentsMargins(0, 0, 0, 0)
        right_scroll_layout.setSpacing(8)
        right_scroll.setWidget(right_scroll_content)
        right_column_layout.addWidget(right_scroll, 1)
        main_splitter.addWidget(right_column)

        section_splitter = QSplitter(Qt.Vertical)
        section_splitter.setChildrenCollapsible(False)
        section_splitter.setHandleWidth(8)
        advanced_evidence_section = CollapsibleSection("Advanced: Evidence And Compare", expanded=False)
        advanced_evidence_section.body_layout.addWidget(section_splitter)
        evidence_section = QGroupBox("Target / Source Evidence")
        evidence_section.setMinimumWidth(0)
        evidence_layout = QVBoxLayout(evidence_section)
        evidence_layout.setContentsMargins(8, 8, 8, 8)
        evidence_layout.setSpacing(6)
        tree = QTreeWidget()
        tree.setColumnCount(5)
        tree.setHeaderLabels(["Side", "Chain / Role", "File / Socket", "Evidence", "Status"])
        tree.setRootIsDecorated(True)
        tree.setAlternatingRowColors(True)
        tree.setUniformRowHeights(True)
        tree.setMinimumWidth(0)
        tree.setMinimumHeight(260)
        evidence_layout.addWidget(tree, 1)
        section_splitter.addWidget(evidence_section)

        def add_graph(side: str, graph: AssetFamilyGraph) -> None:
            side_item = QTreeWidgetItem([side, "", "", "", ""])
            side_item.setFlags(Qt.ItemIsEnabled)
            side_item.setExpanded(True)
            tree.addTopLevelItem(side_item)
            for evidence in tuple(getattr(graph, "attachment_evidence", ()) or ()):
                if not isinstance(evidence, AttachmentPlacementEvidence):
                    continue
                chain = f"{evidence.character_socket_name or '-'} -> {evidence.weapon_socket_name or '-'}"
                side_item.addChild(
                    QTreeWidgetItem(
                        [
                            side,
                            "Placement chain",
                            chain,
                            str(evidence.confidence or "-"),
                            "Preview only",
                        ]
                    )
                )
            for member in tuple(getattr(graph, "member_rows", ()) or ()):
                if not isinstance(member, AssetFamilyMember):
                    continue
                if member.group not in {"Selected Model", "Attachment / Placement", "Prefab / Metadata", "Physics / HKX", "Animation / Motion"}:
                    continue
                side_item.addChild(
                    QTreeWidgetItem(
                        [
                            side,
                            str(member.group or member.role or "-"),
                            str(member.path or member.display_name or "-"),
                            str(member.source_evidence or member.confidence or "-"),
                            str(member.status or "-"),
                        ]
                    )
                )
            if side_item.childCount() <= 0:
                side_item.addChild(QTreeWidgetItem([side, "No placement chain", "-", "No prefab/socket evidence", "Read-only"]))

        def _rebuild_source_evidence_tree() -> None:
            tree.clear()
            add_graph(f"Target to change: {target_entry.basename}", target_graph)
            if isinstance(donor_entry, ArchiveEntry):
                add_graph(f"Placement source: {donor_entry.basename}", donor_graph)
            else:
                source_item = QTreeWidgetItem(["Placement source", "None selected", "-", "-", "Simple XML placement"])
                source_item.setFlags(Qt.ItemIsEnabled)
                tree.addTopLevelItem(source_item)
            tree.expandAll()

        _rebuild_source_evidence_tree()

        target_evidence = self._attachment_visual_best_evidence(target_graph)
        donor_evidence = self._attachment_visual_best_evidence(donor_graph)
        target_socket_entry = self._attachment_socket_entry_from_selection(target_graph)
        donor_socket_entry = self._attachment_socket_entry_from_selection(donor_graph)
        socket_documents_by_key: Dict[Tuple[str, str, int], AttachmentSocketDocument] = {}
        prepared_payloads = AttachmentPreparedPayloads(preparation)
        if isinstance(preparation, PlacementWorkspacePreparation):
            if isinstance(target_socket_entry, ArchiveEntry) and isinstance(preparation.target_socket_document, AttachmentSocketDocument):
                socket_documents_by_key[self._attachment_package_entry_key(target_socket_entry)] = preparation.target_socket_document
            if isinstance(donor_socket_entry, ArchiveEntry) and isinstance(preparation.donor_socket_document, AttachmentSocketDocument):
                socket_documents_by_key[self._attachment_package_entry_key(donor_socket_entry)] = preparation.donor_socket_document

        compare_group = QGroupBox("Socket Value Compare")
        compare_group.setMinimumWidth(0)
        compare_layout = QVBoxLayout(compare_group)
        compare_layout.setContentsMargins(8, 8, 8, 8)
        compare_layout.setSpacing(6)
        compare_hint = QLabel(
            "Compare the actual recovered socket/prefab values before copying source placement into the target. "
            "Different rows are candidates for a full source-copy package or a manual socket XML mix."
        )
        compare_hint.setObjectName("HintLabel")
        compare_hint.setWordWrap(True)
        compare_layout.addWidget(compare_hint)
        compare_tree = QTreeWidget()
        compare_tree.setColumnCount(5)
        compare_tree.setHeaderLabels(["Value", "Target To Change", "Placement Source", "Status", "Meaning"])
        compare_tree.setRootIsDecorated(True)
        compare_tree.setAlternatingRowColors(True)
        compare_tree.setUniformRowHeights(True)
        compare_tree.setEditTriggers(QAbstractItemView.NoEditTriggers)
        compare_tree.setMinimumWidth(0)
        compare_tree.setMinimumHeight(260)
        compare_layout.addWidget(compare_tree, stretch=1)

        def _evidence_value(evidence: Optional[AttachmentPlacementEvidence], name: str) -> str:
            if not isinstance(evidence, AttachmentPlacementEvidence):
                return ""
            value = getattr(evidence, name, "")
            if isinstance(value, (tuple, list)):
                try:
                    return self._format_attachment_transform(tuple(float(component) for component in value))
                except (TypeError, ValueError, OverflowError):
                    return ", ".join(str(component) for component in value if str(component).strip())
            return str(value or "")

        def _compare_status(target_value: str, donor_value: str) -> str:
            target_text = str(target_value or "").strip()
            donor_text = str(donor_value or "").strip()
            if not target_text and not donor_text:
                return "Missing"
            if target_text and not donor_text:
                return "Target only"
            if donor_text and not target_text:
                return "Donor only"
            if target_text == donor_text:
                return "Same"
            return "Different"

        def _add_compare_row(parent: QTreeWidgetItem, label: str, target_value: object, donor_value: object, meaning: str) -> None:
            target_text = str(target_value or "").strip() or "-"
            donor_text = str(donor_value or "").strip() or "-"
            status_text = _compare_status("" if target_text == "-" else target_text, "" if donor_text == "-" else donor_text)
            item = QTreeWidgetItem([label, target_text, donor_text, status_text, meaning])
            item.setToolTip(1, target_text)
            item.setToolTip(2, donor_text)
            item.setToolTip(4, meaning)
            self._ui_style_status_columns(item, {3: status_text})
            parent.addChild(item)

        def _socket_document(entry: Optional[ArchiveEntry]) -> Optional[AttachmentSocketDocument]:
            if not isinstance(entry, ArchiveEntry):
                return None
            return socket_documents_by_key.get(self._attachment_package_entry_key(entry))

        target_socket_document: Optional[AttachmentSocketDocument] = None
        donor_socket_document: Optional[AttachmentSocketDocument] = None
        target_sockets: Dict[str, AttachmentSocketInfo] = {}
        donor_sockets: Dict[str, AttachmentSocketInfo] = {}

        def _rebuild_compare_tree() -> None:
            nonlocal target_socket_document, donor_socket_document, target_sockets, donor_sockets
            compare_tree.clear()
            evidence_group = QTreeWidgetItem(["Placement evidence", "", "", "", "Recovered prefab/socket chain values"])
            evidence_group.setExpanded(True)
            compare_tree.addTopLevelItem(evidence_group)
            for label, attr_name, meaning in (
                ("Character socket", "character_socket_name", "Character-side attach point"),
                ("Character parent", "character_socket_parent", "Skeleton/socket parent"),
                ("Character translation", "character_socket_translation", "Character socket translation"),
                ("Character rotation", "character_socket_rotation", "Character socket rotation"),
                ("Weapon pivot", "weapon_socket_name", "Weapon-side pivot socket"),
                ("Weapon parent", "weapon_socket_parent", "Weapon socket parent"),
                ("Weapon translation", "weapon_socket_translation", "Weapon pivot translation"),
                ("Weapon rotation", "weapon_socket_rotation", "Weapon pivot rotation"),
                ("Prefab", "prefab_path", "Prefab that declares placement fields"),
                ("Socket XML", "socket_file_path", "Weapon socket descriptor"),
                ("Skeleton", "skeleton_path", "Character skeleton/socket context"),
                ("Transform fields", "transform_fields", "Prefab placement field names"),
            ):
                _add_compare_row(
                    evidence_group,
                    label,
                    _evidence_value(target_evidence, attr_name),
                    _evidence_value(donor_evidence, attr_name),
                    meaning,
                )

            target_socket_document = _socket_document(target_socket_entry)
            donor_socket_document = _socket_document(donor_socket_entry)
            target_sockets = {
                str(socket.name or "").strip().casefold(): socket
                for socket in tuple(getattr(target_socket_document, "sockets", ()) or ())
                if isinstance(socket, AttachmentSocketInfo) and str(socket.name or "").strip()
            }
            donor_sockets = {
                str(socket.name or "").strip().casefold(): socket
                for socket in tuple(getattr(donor_socket_document, "sockets", ()) or ())
                if isinstance(socket, AttachmentSocketInfo) and str(socket.name or "").strip()
            }
            important_socket_keys = {
                str(_evidence_value(target_evidence, "weapon_socket_name")).strip().casefold(),
                str(_evidence_value(donor_evidence, "weapon_socket_name")).strip().casefold(),
                str(_evidence_value(target_evidence, "character_socket_name")).strip().casefold(),
                str(_evidence_value(donor_evidence, "character_socket_name")).strip().casefold(),
            }
            important_socket_keys.discard("")
            socket_keys = list(important_socket_keys)
            for socket_key in sorted(set(target_sockets) | set(donor_sockets)):
                if socket_key not in socket_keys:
                    socket_keys.append(socket_key)
            socket_group = QTreeWidgetItem(
                [
                    "Socket XML rows",
                    target_socket_entry.path if isinstance(target_socket_entry, ArchiveEntry) else "-",
                    donor_socket_entry.path if isinstance(donor_socket_entry, ArchiveEntry) else "-",
                    "Compare",
                    "Per-socket parent, translation, and rotation values",
                ]
            )
            socket_group.setExpanded(True)
            compare_tree.addTopLevelItem(socket_group)
            for socket_key in socket_keys[:80]:
                target_socket = target_sockets.get(socket_key)
                donor_socket = donor_sockets.get(socket_key)
                socket_name = (
                    str(getattr(target_socket, "name", "") or "")
                    or str(getattr(donor_socket, "name", "") or "")
                    or socket_key
                )
                target_value = "-"
                donor_value = "-"
                if isinstance(target_socket, AttachmentSocketInfo):
                    target_value = (
                        f"parent {target_socket.parent or '-'} | "
                        f"T {self._format_attachment_transform(target_socket.translation) or '-'} | "
                        f"R {self._format_attachment_transform(target_socket.rotation) or '-'}"
                    )
                if isinstance(donor_socket, AttachmentSocketInfo):
                    donor_value = (
                        f"parent {donor_socket.parent or '-'} | "
                        f"T {self._format_attachment_transform(donor_socket.translation) or '-'} | "
                        f"R {self._format_attachment_transform(donor_socket.rotation) or '-'}"
                    )
                _add_compare_row(socket_group, socket_name, target_value, donor_value, "Socket XML row")
            compare_tree.expandAll()
            compare_tree.header().setStretchLastSection(True)
            compare_tree.header().resizeSection(0, 180)
            compare_tree.header().resizeSection(1, 360)
            compare_tree.header().resizeSection(2, 360)

        _rebuild_compare_tree()
        section_splitter.addWidget(compare_group)

        def _placement_xml_entry_by_basename(*basenames: str, prefer_original: bool = False) -> Optional[ArchiveEntry]:
            normalized_names = [PurePosixPath(str(name or "").replace("\\", "/")).name.casefold() for name in basenames if str(name or "").strip()]
            candidates: List[ArchiveEntry] = []
            seen_candidate_keys: set[ArchiveEntryIdentity] = set()

            def add_candidate(candidate: object) -> None:
                if not isinstance(candidate, ArchiveEntry):
                    return
                key = archive_entry_identity_key(candidate)
                if key in seen_candidate_keys:
                    return
                seen_candidate_keys.add(key)
                candidates.append(candidate)

            for basename in normalized_names:
                for candidate in tuple(self.archive_entries_by_basename.get(basename, ()) or ()):
                    add_candidate(candidate)
            if not candidates:
                for candidate in tuple(getattr(self, "archive_entries", ()) or ()):
                    if not isinstance(candidate, ArchiveEntry):
                        continue
                    candidate_name = PurePosixPath(candidate.path.replace("\\", "/")).name.casefold()
                    if candidate_name in normalized_names:
                        add_candidate(candidate)
            if prefer_original:
                original_candidates = [candidate for candidate in candidates if not archive_entry_is_mod_package(candidate)]
                if not original_candidates:
                    return None
                return max(original_candidates, key=archive_entry_load_priority)
            return candidates[0] if candidates else None

        def _placement_entry_by_virtual_path(virtual_path: str, *fallback_basenames: str) -> Optional[ArchiveEntry]:
            candidate = self._find_archive_entry_by_virtual_path(virtual_path)
            if isinstance(candidate, ArchiveEntry):
                return candidate
            return _placement_xml_entry_by_basename(*fallback_basenames)

        def _placement_original_entry_by_virtual_path(virtual_path: str) -> Optional[ArchiveEntry]:
            normalized_path = str(virtual_path or "").replace("\\", "/").strip().strip("/").casefold()
            if not normalized_path:
                return None
            candidates = [
                candidate
                for candidate in tuple(getattr(self, "archive_entries", ()) or ())
                if isinstance(candidate, ArchiveEntry)
                and not archive_entry_is_mod_package(candidate)
                and str(candidate.path or "").replace("\\", "/").strip().strip("/").casefold() == normalized_path
            ]
            if not candidates:
                return None
            return max(candidates, key=archive_entry_load_priority)

        def _original_archive_entries_by_virtual_path() -> Dict[str, ArchiveEntry]:
            result: Dict[str, ArchiveEntry] = {}
            for candidate in tuple(getattr(self, "archive_entries", ()) or ()):
                if not isinstance(candidate, ArchiveEntry) or archive_entry_is_mod_package(candidate):
                    continue
                normalized_path = str(candidate.path or "").replace("\\", "/").strip().strip("/").casefold()
                if not normalized_path:
                    continue
                current = result.get(normalized_path)
                if current is None or archive_entry_load_priority(candidate) > archive_entry_load_priority(current):
                    result[normalized_path] = candidate
            return result

        part_in_out_entry = _placement_xml_entry_by_basename("phm_description_player_kliff.xml")
        character_socket_entry = _placement_xml_entry_by_basename("phm_01.pab.sockets.xml", "identityskeleton.pab.sockets.xml")
        if (
            isinstance(preparation, PlacementWorkspacePreparation)
            and isinstance(character_socket_entry, ArchiveEntry)
            and isinstance(preparation.character_socket_document, AttachmentSocketDocument)
        ):
            socket_documents_by_key[self._attachment_package_entry_key(character_socket_entry)] = preparation.character_socket_document
        iteminfo_entry = _placement_entry_by_virtual_path("gamedata/binary__/client/bin/iteminfo.pabgb", "iteminfo.pabgb")
        iteminfo_header_entry = _placement_entry_by_virtual_path("gamedata/binary__/client/bin/iteminfo.pabgh", "iteminfo.pabgh")
        equiptype_entry = _placement_entry_by_virtual_path("gamedata/binary__/client/bin/equiptypeinfo.pabgb", "equiptypeinfo.pabgb")
        equiptype_header_entry = _placement_entry_by_virtual_path("gamedata/binary__/client/bin/equiptypeinfo.pabgh", "equiptypeinfo.pabgh")
        universal_part_in_out_entry = _placement_xml_entry_by_basename("phm_description_player_kliff.xml", prefer_original=True)
        universal_twohandsword_upper_entry = _placement_original_entry_by_virtual_path(
            "actionchart/bin__/upperaction/1_pc/1_phm/twohandsword_upper.paac"
        )
        universal_longsword_upper_entry = _placement_original_entry_by_virtual_path(
            "actionchart/bin__/upperaction/1_pc/1_phm/longsword_upper.paac"
        )
        universal_ride_twohandsword_upper_entry = _placement_original_entry_by_virtual_path(
            "actionchart/bin__/upperaction/1_pc/1_phm/ride_weapon_twohandsword_upper.paac"
        )
        universal_basic_weaponin_entry = _placement_original_entry_by_virtual_path(
            "actionchart/bin__/upperaction/1_pc/1_phm/basic_upper_weaponin.paac"
        )
        def _infer_current_weapon_class() -> str:
            return (
                infer_part_in_out_weapon_class(target_entry.path)
                or (
                    infer_part_in_out_weapon_class(donor_entry.path)
                    if isinstance(donor_entry, ArchiveEntry)
                    else ""
                )
                or infer_part_in_out_weapon_class(_evidence_value(target_evidence, "model_path"))
                or infer_part_in_out_weapon_class(_evidence_value(donor_evidence, "model_path"))
            )

        def _infer_current_donor_weapon_class() -> str:
            return (
                infer_part_in_out_weapon_class(donor_entry.path)
                if isinstance(donor_entry, ArchiveEntry)
                else ""
            ) or infer_part_in_out_weapon_class(_evidence_value(donor_evidence, "model_path"))

        inferred_weapon_class = _infer_current_weapon_class()
        donor_inferred_weapon_class = _infer_current_donor_weapon_class()
        target_loose_preparations = tuple(
            row
            for row in preparation.target_loose_roots
            if isinstance(row, PlacementLooseRootPreparation)
        )
        target_loose_roots = tuple(row.root for row in target_loose_preparations)
        target_loose_by_root = {row.root: row for row in target_loose_preparations}
        imported_profile_state: Dict[str, object] = {
            "part_in_out_text": "",
            "part_in_out_path": "",
            "socket_text": "",
            "socket_path": "",
        }
        behavior_patch_cache: Dict[
            Tuple[object, ...],
            Tuple[Optional[ArchiveEntry], Optional[ArchiveEntry], Optional[AttachmentItemInfoBehaviorPatchResult], str],
        ] = {}

        def _read_archive_bytes(entry: Optional[ArchiveEntry]) -> bytes:
            return prepared_payloads.read(
                entry,
                allow_io=QThread.currentThread() != dialog.thread(),
            )

        def _read_archive_text(entry: Optional[ArchiveEntry]) -> str:
            data = _read_archive_bytes(entry)
            return decode_xml_text_payload(data).text if data else ""

        def _read_original_archive_bytes(entry: Optional[ArchiveEntry]) -> bytes:
            if not isinstance(entry, ArchiveEntry) or archive_entry_is_mod_package(entry):
                return b""
            return _read_archive_bytes(entry)

        def _read_original_archive_text(entry: Optional[ArchiveEntry]) -> str:
            data = _read_original_archive_bytes(entry)
            if not data:
                return ""
            return decode_xml_text_payload(data).text

        def _character_socket_document() -> Optional[AttachmentSocketDocument]:
            cached = _socket_document(character_socket_entry)
            if isinstance(cached, AttachmentSocketDocument):
                return cached
            text = _read_archive_text(character_socket_entry)
            if not text:
                return None
            document = parse_socket_bone_data_xml(text, getattr(character_socket_entry, "path", ""))
            return document if document.sockets or document.stack_equip_infos else None

        def _part_in_out_document() -> Optional[AttachmentPartInOutDocument]:
            text = _read_archive_text(part_in_out_entry)
            if not text:
                return None
            document = parse_part_in_out_socket_info_xml(text, getattr(part_in_out_entry, "path", ""))
            return document if document.rows else None

        part_in_out_document = _part_in_out_document()

        def _current_part_in_out_document() -> Optional[AttachmentPartInOutDocument]:
            profile_text = str(imported_profile_state.get("part_in_out_text") or "")
            if profile_text:
                document = parse_part_in_out_socket_info_xml(
                    profile_text,
                    str(imported_profile_state.get("part_in_out_path") or ""),
                )
                if document.rows:
                    return document
            return part_in_out_document

        def _current_character_socket_document() -> Optional[AttachmentSocketDocument]:
            profile_text = str(imported_profile_state.get("socket_text") or "")
            if profile_text:
                document = parse_socket_bone_data_xml(
                    profile_text,
                    str(imported_profile_state.get("socket_path") or ""),
                )
                if document.sockets or document.stack_equip_infos:
                    return document
            return _character_socket_document()

        visual_plan_section = QGroupBox("Move Weapon On Body")
        visual_plan_section.setMinimumWidth(0)
        visual_plan_section.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
        visual_plan_layout = QVBoxLayout(visual_plan_section)
        visual_plan_layout.setContentsMargins(8, 8, 8, 8)
        visual_plan_layout.setSpacing(8)
        visual_group = QGroupBox("Simple Placement")
        visual_group.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
        visual_layout = QGridLayout(visual_group)
        visual_layout.setContentsMargins(8, 8, 8, 8)
        visual_layout.setHorizontalSpacing(6)
        visual_layout.setVerticalSpacing(5)
        visual_hint = QLabel(
            "Choose a 1H/2H source weapon, then build. Default mode moves this target only; model, textures, icon, and physics stay target-owned."
        )
        visual_hint.setObjectName("HintLabel")
        visual_hint.setWordWrap(True)
        visual_layout.addWidget(visual_hint, 0, 0, 1, 4)
        target_summary = QLabel("")
        target_summary.setObjectName("HintLabel")
        target_summary.setWordWrap(True)
        target_summary.setTextInteractionFlags(Qt.TextSelectableByMouse)
        visual_layout.addWidget(target_summary, 1, 0, 1, 4)
        current_placement_state_label = QLabel("")
        current_placement_state_label.setObjectName("HintLabel")
        current_placement_state_label.setWordWrap(True)
        current_placement_state_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        visual_layout.addWidget(QLabel("Current Placement State"), 2, 0)
        visual_layout.addWidget(current_placement_state_label, 2, 1, 1, 3)
        source_copy_button = QPushButton("Choose 1H/2H Source Weapon...")
        source_copy_button.setToolTip("Choose another weapon only for its placement socket values. Target files stay target-owned.")
        visual_layout.addWidget(source_copy_button, 3, 0, 1, 4)
        new_placement_state_label = QLabel("")
        new_placement_state_label.setObjectName("HintLabel")
        new_placement_state_label.setWordWrap(True)
        new_placement_state_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        visual_layout.addWidget(QLabel("New Placement State"), 4, 0)
        visual_layout.addWidget(new_placement_state_label, 4, 1, 1, 3)
        swap_type_combo = QComboBox()
        swap_type_combo.addItem("Placement only (hip/back)", "placement_only")
        swap_type_combo.addItem("Full 1H/2H behavior (experimental)", "full_behavior")
        swap_type_combo.setToolTip(
            "Placement only is the safe default. Full behavior is blocked unless target/source behavior metadata can be patched without unsafe prefab resizing."
        )
        behavior_result_label = QLabel("")
        behavior_result_label.setObjectName("HintLabel")
        behavior_result_label.setWordWrap(True)
        behavior_result_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        visual_layout.addWidget(QLabel("Swap type"), 5, 0)
        visual_layout.addWidget(swap_type_combo, 5, 1)
        visual_layout.addWidget(behavior_result_label, 5, 2, 1, 2)
        placement_state_combo = QComboBox()
        placement_state_combo.addItem("Stowed / on body", "stowed")
        held_rows = (
            tuple(
                row
                for row in part_in_out_rows_for_weapon_class(part_in_out_document, inferred_weapon_class)
                if str(getattr(row, "out_socket_bone", "") or "").strip()
                or str(getattr(row, "out_child_socket_bone", "") or "").strip()
            )
            if isinstance(part_in_out_document, AttachmentPartInOutDocument)
            else ()
        )
        if held_rows:
            placement_state_combo.addItem("Held / in hand", "held")
        placement_state_combo.setToolTip("Advanced. Normal 1H/2H placement swaps use stowed/on-body placement.")
        patch_part_in_out_checkbox = QCheckBox("Advanced: class-wide descriptor fallback")
        patch_part_in_out_checkbox.setToolTip(
            "Default off. This edits the global character descriptor for every weapon in the selected class. "
            "Use only for class-wide hip/back mods or troubleshooting."
        )
        patch_socket_checkbox = QCheckBox("Patch socket profile transforms")
        patch_socket_checkbox.setEnabled(False)
        patch_part_in_out_checkbox.setVisible(True)
        patch_socket_checkbox.setVisible(False)
        patch_part_in_out_checkbox.setChecked(False)
        use_profile_transforms_checkbox = QCheckBox("Apply imported socket transform values")
        use_profile_transforms_checkbox.setEnabled(False)
        use_profile_transforms_checkbox.setToolTip("Use only after importing edited .sockets.xml numeric transform values.")
        attach_point_combo = QComboBox()

        def _populate_attach_point_combo() -> None:
            current_data = attach_point_combo.currentData()
            if isinstance(current_data, AttachmentBodyLocationChoice):
                selected_socket = str(current_data.socket_name or "").strip().casefold()
            else:
                selected_socket = str(current_data or "").strip().casefold()
            attach_point_combo.blockSignals(True)
            try:
                attach_point_combo.clear()
                attach_point_combo.addItem(
                    "Use source weapon placement" if isinstance(donor_entry, ArchiveEntry) else "Pick body location manually",
                    "",
                )
                selected_index = 0
                character_document = _current_character_socket_document()
                body_location_choices = build_attachment_body_location_choices(
                    character_document,
                    _current_part_in_out_document(),
                    weapon_class=inferred_weapon_class,
                )
                for choice in body_location_choices:
                    index = attach_point_combo.count()
                    attach_point_combo.addItem(choice.label or choice.socket_name, choice)
                    if choice.note:
                        attach_point_combo.setItemData(index, choice.note, Qt.ToolTipRole)
                    if selected_socket and choice.socket_name.casefold() == selected_socket:
                        selected_index = index
                if isinstance(character_document, AttachmentSocketDocument):
                    seen_attach_points: set[str] = set()
                    for choice in body_location_choices:
                        if choice.socket_name:
                            seen_attach_points.add(choice.socket_name.casefold())
                    for socket in tuple(character_document.sockets or ()):
                        socket_name = str(socket.name or "").strip()
                        key = socket_name.casefold()
                        if not socket_name or key in seen_attach_points:
                            continue
                        if not body_location_choices and any(token in key for token in ("spine", "pelvis", "hand", "weapon", "shield")):
                            seen_attach_points.add(key)
                            index = attach_point_combo.count()
                            attach_point_combo.addItem(socket_name, socket_name)
                            if selected_socket and key == selected_socket:
                                selected_index = index
                attach_point_combo.setCurrentIndex(selected_index)
            finally:
                attach_point_combo.blockSignals(False)

        _populate_attach_point_combo()
        visual_layout.addWidget(QLabel("Manual body location"), 7, 0)
        visual_layout.addWidget(attach_point_combo, 7, 1, 1, 3)
        target_context_status = QLabel("")
        target_context_status.setObjectName("HintLabel")
        target_context_status.setWordWrap(True)
        target_context_status.setTextInteractionFlags(Qt.TextSelectableByMouse)
        visual_layout.addWidget(QLabel("Target Context"), 8, 0)
        visual_layout.addWidget(target_context_status, 8, 1, 1, 3)
        simple_ready_status = QLabel("")
        simple_ready_status.setObjectName("HintLabel")
        simple_ready_status.setWordWrap(True)
        visual_layout.addWidget(simple_ready_status, 10, 0, 1, 4)
        visual_status = QLabel("")
        visual_status.setObjectName("HintLabel")
        visual_status.setTextFormat(Qt.RichText)
        visual_status.setWordWrap(True)
        visual_status.setTextInteractionFlags(Qt.TextSelectableByMouse)
        visual_plan_layout.addWidget(visual_group)

        target_loose_combo = QComboBox()
        if target_loose_roots:
            for loose_root in target_loose_roots:
                target_loose_combo.addItem(str(loose_root), loose_root)
        else:
            target_loose_combo.addItem("No loose target package detected; vanilla target files stay in game.", None)
            target_loose_combo.setEnabled(False)
        target_loose_label = QLabel("Target Context Source")
        target_loose_visible = len(target_loose_roots) > 1
        target_loose_label.setVisible(target_loose_visible)
        target_loose_combo.setVisible(target_loose_visible)
        if target_loose_visible:
            target_loose_combo.setToolTip("Multiple loose target mods contain this target. Choose which target-owned files to preserve.")
        visual_layout.addWidget(target_loose_label, 9, 0)
        visual_layout.addWidget(target_loose_combo, 9, 1, 1, 3)

        plan_group = QGroupBox("Package Plan")
        plan_layout = QVBoxLayout(plan_group)
        plan_layout.setContentsMargins(8, 8, 8, 8)
        plan_layout.setSpacing(6)
        legacy_raw_prefab_checkbox = QCheckBox("Legacy raw prefab copy (risky)")
        legacy_raw_prefab_checkbox.setToolTip(
            "Default off. Copies donor prefab-style package rows like the old workflow and can pull source references into the target."
        )
        legacy_hkx_checkbox = QCheckBox("Replacement-only: copy source HKX/physics")
        legacy_hkx_checkbox.setToolTip("Replacement-only legacy option. Normal placement keeps target-owned physics/HKX.")
        legacy_hkx_checkbox.setEnabled(False)
        legacy_hkx_checkbox.setVisible(False)
        experimental_prefab_resize_checkbox = QCheckBox("Experimental: allow length-changing prefab role/socket patch")
        experimental_prefab_resize_checkbox.setToolTip(
            "Default off. Allows target prefab stream size to change while copying source role/socket metadata. "
            "This is crash-risk research only until prefab offset/fixup handling is proven."
        )
        use_source_icon_checkbox = QCheckBox("Use placement source icon")
        use_source_icon_checkbox.setToolTip("Default off. Target icon stays unless this is explicitly enabled.")
        use_source_icon_checkbox.setEnabled(isinstance(donor_entry, ArchiveEntry))
        option_row = QHBoxLayout()
        option_row.addWidget(legacy_raw_prefab_checkbox)
        option_row.addWidget(legacy_hkx_checkbox)
        option_row.addStretch(1)
        package_details_section = CollapsibleSection("Advanced: Package Details", expanded=False)
        placement_state_row = QHBoxLayout()
        placement_state_row.addWidget(QLabel("Placement state"))
        placement_state_row.addWidget(placement_state_combo, 1)
        package_details_section.body_layout.addLayout(placement_state_row)
        package_details_section.body_layout.addLayout(option_row)
        package_details_section.body_layout.addWidget(experimental_prefab_resize_checkbox)
        package_details_section.body_layout.addWidget(use_source_icon_checkbox)
        package_details_section.body_layout.addWidget(patch_part_in_out_checkbox)
        package_details_section.body_layout.addWidget(visual_status)
        plan_tree = QTreeWidget()
        plan_tree.setColumnCount(4)
        plan_tree.setHeaderLabels(["Action", "Source file", "Loose target path", "Notes"])
        plan_tree.setRootIsDecorated(False)
        plan_tree.setAlternatingRowColors(True)
        plan_tree.setUniformRowHeights(True)
        plan_tree.setMinimumWidth(0)
        plan_tree.setMinimumHeight(180)
        plan_tree.header().setStretchLastSection(True)
        plan_tree.header().resizeSection(0, 210)
        plan_tree.header().resizeSection(1, 360)
        plan_tree.header().resizeSection(2, 360)
        plan_layout.addWidget(plan_tree)
        warning_label = QLabel("")
        warning_label.setObjectName("HintLabel")
        warning_label.setWordWrap(True)
        plan_layout.addWidget(warning_label)

        custom_icon_group = QGroupBox("Icon")
        custom_icon_group.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
        custom_icon_layout = QGridLayout(custom_icon_group)
        custom_icon_layout.setContentsMargins(8, 8, 8, 8)
        custom_icon_layout.setHorizontalSpacing(6)
        custom_icon_layout.setVerticalSpacing(5)
        custom_icon_checkbox = QCheckBox("Use custom icon override")
        custom_icon_checkbox.setToolTip(
            "Optional override. Existing target icon files from the selected loose mod are preserved automatically."
        )
        custom_icon_override_button = QPushButton("Override Icon...")
        custom_icon_clear_button = QPushButton("Clear Override")
        custom_icon_source_edit = QLineEdit()
        custom_icon_source_edit.setPlaceholderText("Choose an image file or a folder to auto-match")
        custom_icon_file_button = QPushButton("File...")
        custom_icon_folder_button = QPushButton("Folder...")
        custom_icon_library_button = QPushButton("Library...")
        custom_icon_target_combo = QComboBox()
        custom_icon_status = QLabel("Existing target icon is preserved automatically when present in the selected target files.")
        custom_icon_status.setObjectName("HintLabel")
        custom_icon_status.setWordWrap(True)
        custom_icon_status.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        custom_icon_layout.addWidget(custom_icon_status, 0, 0, 1, 3)
        custom_icon_layout.addWidget(custom_icon_override_button, 0, 3)
        custom_icon_layout.addWidget(custom_icon_clear_button, 0, 4)
        custom_icon_controls_widget = QWidget()
        custom_icon_controls_layout = QGridLayout(custom_icon_controls_widget)
        custom_icon_controls_layout.setContentsMargins(0, 4, 0, 0)
        custom_icon_controls_layout.setHorizontalSpacing(6)
        custom_icon_controls_layout.setVerticalSpacing(5)
        custom_icon_controls_layout.addWidget(custom_icon_checkbox, 0, 0, 1, 5)
        custom_icon_controls_layout.addWidget(QLabel("Source"), 1, 0)
        custom_icon_controls_layout.addWidget(custom_icon_source_edit, 1, 1)
        custom_icon_controls_layout.addWidget(custom_icon_file_button, 1, 2)
        custom_icon_controls_layout.addWidget(custom_icon_folder_button, 1, 3)
        custom_icon_controls_layout.addWidget(custom_icon_library_button, 1, 4)
        custom_icon_controls_layout.addWidget(QLabel("Target icon"), 2, 0)
        custom_icon_controls_layout.addWidget(custom_icon_target_combo, 2, 1, 1, 4)
        custom_icon_controls_layout.setColumnStretch(1, 1)
        custom_icon_layout.addWidget(custom_icon_controls_widget, 1, 0, 1, 5)
        custom_icon_layout.setColumnStretch(1, 1)
        target_icon_entries = self._attachment_package_item_icon_entries(target_entry, target_graph)
        for icon_entry in target_icon_entries:
            custom_icon_target_combo.addItem(icon_entry.path, icon_entry)
        if not target_icon_entries:
            custom_icon_checkbox.setEnabled(False)
            custom_icon_override_button.setEnabled(False)
            custom_icon_target_combo.addItem("No resolved existing target icon path", None)
            custom_icon_status.setText("No existing target icon path was resolved for this target; custom icon packaging is unavailable.")
        visual_plan_layout.addWidget(custom_icon_group)
        left_scroll_layout.addWidget(visual_plan_section)
        left_scroll_layout.addStretch(1)
        right_scroll_layout.addWidget(plan_group)
        advanced_features_toggle = QCheckBox("Enable Advanced Features")
        advanced_features_toggle.setToolTip("Show package details, imported socket profile, raw socket XML, and evidence/compare tools.")
        right_scroll_layout.addWidget(advanced_features_toggle)
        advanced_features_widget = QWidget()
        advanced_features_layout = QVBoxLayout(advanced_features_widget)
        advanced_features_layout.setContentsMargins(0, 0, 0, 0)
        advanced_features_layout.setSpacing(8)
        advanced_features_widget.setVisible(False)
        advanced_features_layout.addWidget(package_details_section)
        class_wide_section = CollapsibleSection("Advanced: Class-Wide Tools", expanded=False)
        class_wide_hint = QLabel(
            "Affects all PHM 2H swords. Use only when you want class-wide animation aliases and placement, not one selected weapon."
        )
        class_wide_hint.setObjectName("HintLabel")
        class_wide_hint.setWordWrap(True)
        universal_twohand_button = QPushButton("Build Universal 2H Swords As 1H")
        universal_twohand_button.setToolTip(
            "Class-wide tool. Exports PHM 2H sword animation aliases plus optional hip placement XML. No actionchart PAAC graph copy and no ItemInfo table export."
        )
        universal_twohand_true_button = QPushButton("Build Universal 2H Swords As True 1H")
        universal_twohand_true_button.setToolTip(
            "Disabled after in-game crash testing. True 1H/offhand needs more than ItemInfo; forcing the partial table patch can hang or crash the game."
        )
        universal_twohand_true_button.setEnabled(False)
        class_wide_section.body_layout.addWidget(class_wide_hint)
        class_wide_section.body_layout.addWidget(universal_twohand_button)
        class_wide_section.body_layout.addWidget(universal_twohand_true_button)
        advanced_features_layout.addWidget(class_wide_section)
        imported_profile_section = CollapsibleSection("Advanced: Imported Socket Profile", expanded=False)
        imported_profile_hint = QLabel(
            "Use only when you have edited socket transform XML and want to copy its numeric offsets/rotations. Normal body-slot changes do not need this."
        )
        imported_profile_hint.setObjectName("HintLabel")
        imported_profile_hint.setWordWrap(True)
        import_profile_button = QPushButton("Import Placement Profile XML...")
        import_profile_button.setToolTip("Import phm_description_player_kliff.xml or edited .sockets.xml profile data.")
        imported_profile_section.body_layout.addWidget(imported_profile_hint)
        imported_profile_section.body_layout.addWidget(import_profile_button)
        imported_profile_section.body_layout.addWidget(use_profile_transforms_checkbox)
        advanced_features_layout.addWidget(imported_profile_section)
        section_splitter.setCollapsible(0, False)
        section_splitter.setCollapsible(1, False)
        section_splitter.setStretchFactor(0, 1)
        section_splitter.setStretchFactor(1, 1)
        section_splitter.setSizes([360, 360])
        footer = QLabel(
            "Placement only changes hip/back slot. Full behavior changes target ItemInfo equip type too. Target-owned model, textures, icon, and physics stay intact."
        )
        footer.setObjectName("HintLabel")
        footer.setWordWrap(True)
        visual_plan_layout.addWidget(footer)
        target_socket_button = QPushButton("Open Target Socket XML")
        target_socket_button.setEnabled(isinstance(target_socket_entry, ArchiveEntry))
        donor_socket_button = QPushButton("Open Source Socket XML")
        donor_socket_button.setEnabled(isinstance(donor_socket_entry, ArchiveEntry))
        raw_xml_section = CollapsibleSection("Advanced: Raw Socket XML", expanded=False)
        raw_xml_row = QHBoxLayout()
        raw_xml_row.addWidget(target_socket_button)
        raw_xml_row.addWidget(donor_socket_button)
        raw_xml_row.addStretch(1)
        raw_xml_section.body_layout.addLayout(raw_xml_row)
        advanced_features_layout.addWidget(raw_xml_section)
        advanced_features_layout.addWidget(advanced_evidence_section)
        right_scroll_layout.addWidget(advanced_features_widget)
        right_scroll_layout.addStretch(1)
        main_splitter.setCollapsible(0, False)
        main_splitter.setCollapsible(1, False)
        main_splitter.setStretchFactor(0, 2)
        main_splitter.setStretchFactor(1, 3)
        main_splitter.setSizes([520, 760])
        build_button = QPushButton("Build Placement Package...")
        close_button = QPushButton("Close")
        close_row = QHBoxLayout()
        close_row.addStretch(1)
        close_row.addWidget(build_button)
        close_row.addWidget(close_button)
        left_column_layout.addLayout(close_row)

        def _selected_target_loose_root() -> Optional[Path]:
            value = target_loose_combo.currentData()
            return value if isinstance(value, Path) else None

        def _target_loose_specs() -> Tuple[MeshImportSupplementalFileSpec, ...]:
            loose_root = _selected_target_loose_root()
            prepared = target_loose_by_root.get(loose_root) if isinstance(loose_root, Path) else None
            if not isinstance(prepared, PlacementLooseRootPreparation):
                return ()
            return tuple(
                MeshImportSupplementalFileSpec(
                    source_path=spec.source_path,
                    target_path=spec.target_path,
                    kind=spec.kind,
                    target_entry=spec.target_entry,
                    note=spec.note,
                )
                for spec in prepared.specs
            )

        def _target_loose_warning() -> str:
            loose_root = _selected_target_loose_root()
            prepared = target_loose_by_root.get(loose_root) if isinstance(loose_root, Path) else None
            return str(prepared.warning or "") if isinstance(prepared, PlacementLooseRootPreparation) else ""

        def _visual_selected_attach_choice() -> Optional[AttachmentBodyLocationChoice]:
            value = attach_point_combo.currentData()
            return value if isinstance(value, AttachmentBodyLocationChoice) else None

        def _visual_selected_attach_socket() -> str:
            choice = _visual_selected_attach_choice()
            if isinstance(choice, AttachmentBodyLocationChoice):
                return str(choice.socket_name or "").strip()
            return str(attach_point_combo.currentData() or "").strip()

        def _child_socket_for_attach_point(socket_name: str) -> str:
            choice = _visual_selected_attach_choice()
            if (
                isinstance(choice, AttachmentBodyLocationChoice)
                and choice.socket_name.casefold() == str(socket_name or "").strip().casefold()
                and choice.child_socket_name
            ):
                return choice.child_socket_name
            return infer_attachment_child_socket_name(
                str(socket_name or "").strip(),
                _current_part_in_out_document(),
                weapon_class=inferred_weapon_class,
            )

        def _selected_loose_file_for_virtual(virtual_path: object) -> Optional[Path]:
            root = _selected_target_loose_root()
            normalized = str(virtual_path or "").replace("\\", "/").strip().lstrip("/")
            if normalized.casefold().startswith("files/"):
                normalized = normalized[6:]
            prepared = target_loose_by_root.get(root) if isinstance(root, Path) else None
            if not isinstance(prepared, PlacementLooseRootPreparation) or not normalized:
                return None
            key = normalized.casefold()
            return next(
                (spec.source_path for spec in prepared.specs if spec.target_path.casefold() == key),
                None,
            )

        def _read_placement_base_text(entry: Optional[ArchiveEntry]) -> str:
            data = _read_placement_base_bytes(entry)
            return decode_xml_text_payload(data).text if data else ""

        def _read_placement_base_bytes(entry: Optional[ArchiveEntry]) -> bytes:
            if not isinstance(entry, ArchiveEntry):
                return b""
            loose_path = _selected_loose_file_for_virtual(entry.path)
            if isinstance(loose_path, Path):
                if QThread.currentThread() == dialog.thread():
                    return b""
                try:
                    return run_attachment_payload_read(
                        AttachmentPayloadReadRequest(
                            file_path=loose_path,
                            max_bytes=ATTACHMENT_PAYLOAD_MAX_BYTES,
                        )
                    ).data
                except Exception:
                    pass
            return _read_archive_bytes(entry)

        def _encode_placement_base_text(entry: Optional[ArchiveEntry], payload_text: str) -> bytes:
            return encode_xml_text_like_source(payload_text, _read_placement_base_bytes(entry))

        def _visual_selected_swap_type() -> str:
            value = str(swap_type_combo.currentData() or "").strip().casefold()
            return "full_behavior" if value == "full_behavior" else "placement_only"

        def _visual_iteminfo_behavior_patch() -> Tuple[
            Optional[ArchiveEntry],
            Optional[ArchiveEntry],
            Optional[AttachmentItemInfoBehaviorPatchResult],
            str,
        ]:
            if _visual_selected_swap_type() != "full_behavior":
                return None, None, None, "Placement only: behavior table is not patched."
            if not isinstance(donor_entry, ArchiveEntry):
                result = AttachmentItemInfoBehaviorPatchResult(
                    blocking_reason="Choose a 1H/2H source weapon before using full behavior mode."
                )
                return None, None, result, result.blocking_reason
            required_entries = (iteminfo_entry, iteminfo_header_entry, equiptype_entry, equiptype_header_entry)
            if not all(isinstance(entry, ArchiveEntry) for entry in required_entries):
                result = AttachmentItemInfoBehaviorPatchResult(
                    blocking_reason="Full behavior mode needs iteminfo.pabgb/.pabgh and equiptypeinfo.pabgb/.pabgh."
                )
                return iteminfo_entry, iteminfo_header_entry, result, result.blocking_reason
            cache_key = (
                str(_selected_target_loose_root() or ""),
                getattr(iteminfo_entry, "path", ""),
                getattr(iteminfo_header_entry, "path", ""),
                getattr(equiptype_entry, "path", ""),
                getattr(equiptype_header_entry, "path", ""),
                getattr(target_entry, "path", ""),
                getattr(donor_entry, "path", ""),
                inferred_weapon_class,
                donor_inferred_weapon_class,
            )
            cached = behavior_patch_cache.get(cache_key)
            if cached is not None:
                return cached
            iteminfo_data = _read_placement_base_bytes(iteminfo_entry)
            iteminfo_header_data = _read_placement_base_bytes(iteminfo_header_entry)
            equiptype_data = _read_placement_base_bytes(equiptype_entry)
            equiptype_header_data = _read_placement_base_bytes(equiptype_header_entry)
            if not iteminfo_data or not iteminfo_header_data or not equiptype_data or not equiptype_header_data:
                result = AttachmentItemInfoBehaviorPatchResult(
                    data=iteminfo_data,
                    blocking_reason="Full behavior mode could not read ItemInfo or EquipTypeInfo tables.",
                )
                value = (iteminfo_entry, iteminfo_header_entry, result, result.blocking_reason)
                behavior_patch_cache[cache_key] = value
                return value
            target_model_path = str(_evidence_value(target_evidence, "model_path") or target_entry.path)
            source_model_path = str(_evidence_value(donor_evidence, "model_path") or donor_entry.path)
            result = build_iteminfo_behavior_equip_type_patch(
                iteminfo_data,
                iteminfo_header_data,
                equiptype_data,
                equiptype_header_data,
                target_model_path=target_model_path,
                source_model_path=source_model_path,
                target_weapon_class=inferred_weapon_class,
                source_weapon_class=donor_inferred_weapon_class,
            )
            if isinstance(result, AttachmentItemInfoBehaviorPatchResult) and result.blocking_reason:
                value = (iteminfo_entry, iteminfo_header_entry, result, result.blocking_reason)
                behavior_patch_cache[cache_key] = value
                return value
            if isinstance(result, AttachmentItemInfoBehaviorPatchResult) and result.old_equip_type_name:
                value = (
                    iteminfo_entry,
                    iteminfo_header_entry,
                    result,
                    f"{result.old_equip_type_name or '-'} -> {result.new_equip_type_name or '-'}",
                )
                behavior_patch_cache[cache_key] = value
                return value
            value = (iteminfo_entry, iteminfo_header_entry, result, "No ItemInfo behavior change was produced.")
            behavior_patch_cache[cache_key] = value
            return value

        def _placement_behavior_patch_blocking_reason() -> str:
            if _visual_selected_swap_type() != "full_behavior":
                return ""
            _entry, _header_entry, patch, note = _visual_iteminfo_behavior_patch()
            if isinstance(patch, AttachmentItemInfoBehaviorPatchResult) and patch.blocking_reason:
                return patch.blocking_reason
            _prefab_entry, prefab_patch, prefab_note = _visual_target_prefab_patch()
            if not isinstance(prefab_patch, PrefabAttachmentProfilePatchResult):
                return prefab_note or "Full behavior needs a target prefab role patch."
            return "" if isinstance(patch, AttachmentItemInfoBehaviorPatchResult) else str(note or "")

        def _target_pac_xml_entry_for_patch() -> Optional[ArchiveEntry]:
            if str(getattr(target_entry, "extension", "") or "").casefold() == ".pac_xml":
                return target_entry
            target_path = str(getattr(target_entry, "path", "") or "").replace("\\", "/").strip()
            if "/model/" in target_path and str(getattr(target_entry, "extension", "") or "").casefold() in {".pac", ".pam", ".pamlod"}:
                direct_path = target_path.replace("/model/", "/modelproperty/", 1) + "_xml"
                direct_entry = self._find_archive_entry_by_virtual_path(direct_path)
                if isinstance(direct_entry, ArchiveEntry) and str(direct_entry.extension or "").casefold() == ".pac_xml":
                    return direct_entry
            target_model = self._attachment_visual_model_entry(target_entry, target_graph)
            sidecar_entry = self._attachment_package_material_sidecar_for_model(target_entry, target_graph, target_model)
            if isinstance(sidecar_entry, ArchiveEntry) and str(sidecar_entry.extension or "").casefold() == ".pac_xml":
                return sidecar_entry
            for action, support_entry, _note in self._attachment_package_target_support_entries(target_entry, target_graph):
                if (
                    isinstance(support_entry, ArchiveEntry)
                    and str(support_entry.extension or "").casefold() == ".pac_xml"
                    and "material" in str(action or "").casefold()
                ):
                    return support_entry
            return None

        def _target_prefab_entry_for_patch() -> Optional[ArchiveEntry]:
            prefab_path = _evidence_value(target_evidence, "prefab_path")
            candidate = self._find_archive_entry_by_virtual_path(prefab_path)
            if isinstance(candidate, ArchiveEntry):
                return candidate
            for action, support_entry, _note in self._attachment_package_target_support_entries(target_entry, target_graph):
                if (
                    isinstance(support_entry, ArchiveEntry)
                    and str(action or "").casefold().startswith("preserve target prefab")
                ):
                    return support_entry
            return None

        def _descriptor_socket_pair(weapon_class: str, placement_state: str) -> Tuple[str, str, str]:
            socket_attr = "out_socket_bone" if placement_state == "held" else "in_socket_bone"
            child_attr = "out_child_socket_bone" if placement_state == "held" else "in_child_socket_bone"
            document = _current_part_in_out_document()
            if not isinstance(document, AttachmentPartInOutDocument):
                return "", "", ""
            for row in part_in_out_rows_for_weapon_class(document, weapon_class):
                attrs = getattr(row, "attributes", {}) or {}
                if str(attrs.get("Visible", "") or "").strip().casefold() == "out":
                    continue
                socket_value = str(getattr(row, socket_attr, "") or "").strip()
                child_value = str(getattr(row, child_attr, "") or "").strip()
                if socket_value and child_value:
                    return socket_value, child_value, str(getattr(row, "part_name", "") or "")
            return "", "", ""

        def _desired_prefab_attach_pair() -> Tuple[str, str]:
            if _visual_selected_placement_state() != "stowed":
                return "", ""
            attach_socket = _visual_selected_attach_socket()
            if attach_socket:
                return attach_socket, _child_socket_for_attach_point(attach_socket)
            if isinstance(donor_entry, ArchiveEntry):
                if donor_inferred_weapon_class:
                    descriptor_socket, descriptor_child, _descriptor_part = _descriptor_socket_pair(
                        donor_inferred_weapon_class,
                        _visual_selected_placement_state(),
                    )
                    if descriptor_socket and descriptor_child:
                        return descriptor_socket, descriptor_child
                evidence_socket = str(_evidence_value(donor_evidence, "character_socket_name") or "").strip()
                evidence_child = str(_evidence_value(donor_evidence, "weapon_socket_name") or "").strip()
                if evidence_socket and evidence_child:
                    return evidence_socket, evidence_child
            return "", ""

        def _desired_stack_equip_type() -> str:
            attached_socket, _pivot_socket = _desired_prefab_attach_pair()
            return infer_stack_equip_type_for_socket(attached_socket, _current_character_socket_document())

        def _visual_target_pac_xml_patch() -> Tuple[Optional[ArchiveEntry], Optional[AttachmentStackEquipTypePatchResult], str]:
            target_equip_type = _desired_stack_equip_type()
            if not target_equip_type:
                return None, None, "No target stack equip type could be inferred from the selected/source socket."
            target_pac_xml_entry = _target_pac_xml_entry_for_patch()
            if not isinstance(target_pac_xml_entry, ArchiveEntry):
                return None, None, "No target .pac_xml sidecar was resolved; slot metadata patch is unavailable."
            base_text = _read_placement_base_text(target_pac_xml_entry)
            if not base_text:
                return target_pac_xml_entry, None, "Target .pac_xml sidecar could not be read."
            patch = build_pac_xml_stack_equip_type_patch(base_text, equip_type=target_equip_type)
            if not isinstance(patch, AttachmentStackEquipTypePatchResult) or not patch.old_equip_type:
                return target_pac_xml_entry, None, "Target .pac_xml has no StackEquipDataContainer _equipType."
            return target_pac_xml_entry, patch, f"{patch.old_equip_type or '-'} -> {patch.new_equip_type or '-'}"

        def _donor_prefab_entry_for_patch() -> Optional[ArchiveEntry]:
            if not isinstance(donor_entry, ArchiveEntry):
                return None
            return self._choose_attachment_package_donor_prefab(
                donor_entry,
                donor_graph,
                _target_prefab_entry_for_patch(),
            )

        def _visual_target_prefab_patch() -> Tuple[Optional[ArchiveEntry], Optional[PrefabAttachmentProfilePatchResult], str]:
            attached_socket, pivot_socket = _desired_prefab_attach_pair()
            if not attached_socket or not pivot_socket:
                return None, None, ""
            target_prefab_entry = _target_prefab_entry_for_patch()
            if not isinstance(target_prefab_entry, ArchiveEntry):
                return None, None, "No target prefab was resolved; target-only placement patch is unavailable."
            loose_path = _selected_loose_file_for_virtual(target_prefab_entry.path)
            try:
                if isinstance(loose_path, Path):
                    payload_data = _read_placement_base_bytes(target_prefab_entry)
                    base_note = f"loose target prefab {loose_path}"
                else:
                    payload_data = _read_archive_bytes(target_prefab_entry)
                    base_note = f"archive target prefab {target_prefab_entry.path}"
                if not payload_data:
                    return target_prefab_entry, None, "Target prefab payload is still loading or unavailable."
                source_part_name = ""
                source_socket_file = ""
                source_note = ""
                if isinstance(donor_entry, ArchiveEntry) and _visual_selected_swap_type() == "full_behavior":
                    donor_prefab_entry = _donor_prefab_entry_for_patch()
                    if not isinstance(donor_prefab_entry, ArchiveEntry):
                        return target_prefab_entry, None, "Full behavior needs a resolved source prefab role profile."
                    else:
                        donor_payload = _read_archive_bytes(donor_prefab_entry)
                        if not donor_payload:
                            return target_prefab_entry, None, "Source prefab payload is still loading or unavailable."
                        source_fields = {
                            field.field_name: field.value
                            for field in inspect_prefab_attachment_profile_fields(donor_payload)
                        }
                        source_part_name = str(source_fields.get("_partName") or "").strip()
                        source_socket_file = str(source_fields.get("_socketFileName") or "").strip()
                        if not source_part_name:
                            return target_prefab_entry, None, "Full behavior needs a source prefab CD_* part role."
                        if source_part_name:
                            source_note = f"; source role profile {donor_prefab_entry.path}"
                prefab_patch = build_prefab_attachment_profile_patch(
                    payload_data,
                    attached_socket_name=attached_socket,
                    pivot_socket_name=pivot_socket,
                    part_name=source_part_name,
                    socket_file_path=source_socket_file,
                    allow_length_changes=experimental_prefab_resize_checkbox.isChecked(),
                )
                if (
                    len(prefab_patch.data) != len(payload_data)
                    and not experimental_prefab_resize_checkbox.isChecked()
                ):
                    return target_prefab_entry, None, "Target prefab patch unavailable: prefab stream length changed outside experimental mode."
            except Exception as exc:
                if _visual_selected_swap_type() == "full_behavior" and "would resize target prefab" in str(exc):
                    return (
                        target_prefab_entry,
                        None,
                        f"Full behavior blocked: source role/socket metadata would resize target prefab. {exc}",
                    )
                return target_prefab_entry, None, f"Target prefab patch unavailable: {exc}"
            return target_prefab_entry, prefab_patch, f"Base: {base_note}{source_note}"

        def _visual_selected_placement_state() -> str:
            state = str(placement_state_combo.currentData() or "stowed").strip().casefold()
            return "held" if state == "held" else "stowed"

        def _visual_part_in_out_patch(base_text: str) -> AttachmentPartInOutPatchResult:
            if not patch_part_in_out_checkbox.isChecked() or not inferred_weapon_class:
                return AttachmentPartInOutPatchResult(text=base_text)
            profile_text = str(imported_profile_state.get("part_in_out_text") or "")
            if profile_text:
                return build_part_in_out_socket_profile_patch(
                    base_text,
                    profile_text,
                    weapon_class=inferred_weapon_class,
                )
            attach_socket = _visual_selected_attach_socket()
            if not attach_socket and isinstance(donor_entry, ArchiveEntry) and donor_inferred_weapon_class:
                return build_part_in_out_socket_class_copy_patch(
                    base_text,
                    target_weapon_class=inferred_weapon_class,
                    source_weapon_class=donor_inferred_weapon_class,
                    placement_state=_visual_selected_placement_state(),
                )
            if not attach_socket:
                return AttachmentPartInOutPatchResult(text=base_text)
            return build_part_in_out_socket_attach_point_patch(
                base_text,
                weapon_class=inferred_weapon_class,
                in_socket_bone=attach_socket,
                in_child_socket_bone=_child_socket_for_attach_point(attach_socket),
                placement_state=_visual_selected_placement_state(),
            )

        def _visual_socket_patch(base_text: str, part_patch: Optional[AttachmentPartInOutPatchResult] = None) -> AttachmentPartInOutPatchResult:
            if not patch_socket_checkbox.isChecked():
                return AttachmentPartInOutPatchResult(text=base_text)
            profile_text = str(imported_profile_state.get("socket_text") or "")
            if not profile_text:
                return AttachmentPartInOutPatchResult(text=base_text)
            socket_names: List[str] = []
            attach_socket = _visual_selected_attach_socket()
            if attach_socket:
                socket_names.append(attach_socket)
            if isinstance(part_patch, AttachmentPartInOutPatchResult):
                for diff in tuple(part_patch.diffs or ()):
                    if diff.field_name in {"InSocketBone", "OutSocketBone"} and diff.new_value:
                        socket_names.append(diff.new_value)
            if not socket_names:
                socket_names.extend(
                    str(value or "")
                    for value in (
                        _evidence_value(target_evidence, "character_socket_name"),
                        _evidence_value(donor_evidence, "character_socket_name"),
                    )
                    if str(value or "").strip()
                )
            return build_socket_bone_data_profile_patch(
                base_text,
                profile_text,
                socket_names=tuple(dict.fromkeys(socket_names)),
            )

        def _visual_part_in_out_preview_patch() -> Optional[AttachmentPartInOutPatchResult]:
            if not patch_part_in_out_checkbox.isChecked() or not isinstance(part_in_out_entry, ArchiveEntry):
                return None
            patch = _visual_part_in_out_patch(_read_placement_base_text(part_in_out_entry))
            return patch if isinstance(patch, AttachmentPartInOutPatchResult) and bool(patch.diffs) else None

        def _placement_part_in_out_patch_blocking_reason(
            part_patch: Optional[AttachmentPartInOutPatchResult],
        ) -> str:
            if not isinstance(part_patch, AttachmentPartInOutPatchResult) or not part_patch.diffs:
                return ""
            expected_class = str(inferred_weapon_class or "").strip().casefold()
            if expected_class in {"twohand", "mainhand"}:
                return (
                    "Placement patch scope is too broad. Select a weapon with a resolved exact class before building."
                )
            patched_part_names = tuple(
                dict.fromkeys(
                    tuple(part_patch.patched_part_names or ())
                    + tuple(str(diff.part_name or "").strip() for diff in tuple(part_patch.diffs or ()))
                )
            )
            class_by_part = {
                name: infer_part_in_out_weapon_class(name)
                for name in patched_part_names
                if str(name or "").strip()
            }
            if expected_class:
                invalid_parts = [
                    name
                    for name, class_name in class_by_part.items()
                    if str(class_name or "").strip().casefold() != expected_class
                ]
                if invalid_parts:
                    return (
                        "Placement patch touches unrelated descriptor rows: "
                        + ", ".join(invalid_parts[:8])
                        + (" ..." if len(invalid_parts) > 8 else "")
                    )
            touched_classes = {
                str(class_name or "").strip().casefold()
                for class_name in class_by_part.values()
                if str(class_name or "").strip()
            }
            if len(touched_classes) > 1:
                return "Placement patch touches mixed weapon families: " + ", ".join(sorted(touched_classes))
            return ""

        def _visual_socket_preview_patch(
            part_patch: Optional[AttachmentPartInOutPatchResult] = None,
        ) -> Optional[AttachmentPartInOutPatchResult]:
            if not patch_socket_checkbox.isChecked() or not isinstance(character_socket_entry, ArchiveEntry):
                return None
            patch = _visual_socket_patch(_read_archive_text(character_socket_entry), part_patch)
            return patch if isinstance(patch, AttachmentPartInOutPatchResult) and bool(patch.diffs) else None

        def _placement_global_xml_alias_specs(
            entry: Optional[ArchiveEntry],
            payload_text: str,
            aliases: Sequence[str],
            *,
            kind: str,
        ) -> Tuple[MeshImportSupplementalFileSpec, ...]:
            if not isinstance(entry, ArchiveEntry) or not str(payload_text or ""):
                return ()
            current_path = entry.path.replace("\\", "/").strip().lstrip("/")
            current_key = current_path.casefold()
            payload_data = _encode_placement_base_text(entry, str(payload_text or ""))
            specs: List[MeshImportSupplementalFileSpec] = []
            seen: set[str] = {current_key}
            for alias in aliases:
                alias_path = str(alias or "").replace("\\", "/").strip().lstrip("/")
                alias_key = alias_path.casefold()
                if not alias_path or alias_key in seen:
                    continue
                seen.add(alias_key)
                specs.append(
                    MeshImportSupplementalFileSpec(
                        source_path=Path(alias_path),
                        target_path=alias_path,
                        kind=kind,
                        payload_data=payload_data,
                        note="Known working CDUMM placement XML alias.",
                    )
                )
            return tuple(specs)

        def _visual_patch_preview_rows() -> List[Tuple[str, str, str]]:
            rows: List[Tuple[str, str, str]] = []
            target_pac_xml_entry, pac_xml_patch, pac_xml_note = _visual_target_pac_xml_patch()
            if (
                isinstance(target_pac_xml_entry, ArchiveEntry)
                and isinstance(pac_xml_patch, AttachmentStackEquipTypePatchResult)
                and pac_xml_patch.changed
            ):
                rows.append(
                    (
                        "Target slot metadata (.pac_xml)",
                        target_pac_xml_entry.path,
                        f"StackEquipDataContainer _equipType {pac_xml_note}; preserves target material and physics sidecar data.",
                    )
                )
            target_prefab_entry, prefab_patch, prefab_note = _visual_target_prefab_patch()
            if isinstance(target_prefab_entry, ArchiveEntry) and isinstance(prefab_patch, PrefabAttachmentProfilePatchResult):
                proof_summary = "; ".join(tuple(prefab_patch.proof_lines[-2:]))
                prefab_action = (
                    "Target prefab placement + role metadata"
                    if _visual_selected_swap_type() == "full_behavior"
                    else "Target prefab placement metadata"
                )
                rows.append(
                    (
                        prefab_action,
                        target_prefab_entry.path,
                        f"Target-only prefab profile patch. {prefab_note}. {proof_summary}",
                    )
                )
            behavior_entry, _behavior_header_entry, behavior_patch, behavior_note = _visual_iteminfo_behavior_patch()
            if (
                _visual_selected_swap_type() == "full_behavior"
                and isinstance(behavior_entry, ArchiveEntry)
                and isinstance(behavior_patch, AttachmentItemInfoBehaviorPatchResult)
                and bool(behavior_patch.old_equip_type_name)
            ):
                behavior_action = "ItemInfo behavior" if behavior_patch.changed else "ItemInfo behavior context"
                behavior_detail = (
                    f"{behavior_note}; patches only _equipTypeInfo at 0x{behavior_patch.patch_offset:X}"
                    if behavior_patch.changed
                    else f"{behavior_note}; included so full-behavior target context stays explicit"
                )
                rows.append(
                    (
                        behavior_action,
                        behavior_entry.path,
                        (
                            f"{behavior_detail}. Source visual/physics files are not copied."
                        ),
                    )
                )
            part_patch = _visual_part_in_out_preview_patch()
            socket_patch = _visual_socket_preview_patch(part_patch)
            if isinstance(part_patch, AttachmentPartInOutPatchResult):
                patched_part_names = tuple(part_patch.patched_part_names or ())
                patched_parts_note = (
                    "; rows: "
                    + ", ".join(patched_part_names[:8])
                    + (" ..." if len(patched_part_names) > 8 else "")
                    if patched_part_names
                    else ""
                )
                rows.append(
                    (
                        "Class stowed placement descriptor" if _visual_selected_placement_state() == "stowed" else "Class held placement descriptor",
                        part_in_out_entry.path,
                        f"Selected class: {inferred_weapon_class or 'unknown'}; {len(part_patch.diffs)} descriptor change(s){patched_parts_note}.",
                    )
                )
            if isinstance(socket_patch, AttachmentPartInOutPatchResult):
                rows.append(
                    (
                        "Patch character socket XML",
                        character_socket_entry.path,
                        f"Uses imported socket profile transforms for selected attach socket(s); {len(socket_patch.diffs)} change(s).",
                    )
                )
            return rows

        def _descriptor_socket_summary(weapon_class: str, placement_state: str, evidence: Optional[AttachmentPlacementEvidence]) -> str:
            state_text = "Held / in hand" if placement_state == "held" else "Stowed / on body"
            socket_value, child_value, part_name = _descriptor_socket_pair(weapon_class, placement_state)
            if socket_value or child_value:
                return f"{state_text}: {socket_value or '-'} -> {child_value or '-'} ({part_name or weapon_class})"
            evidence_socket = _evidence_value(evidence, "character_socket_name")
            evidence_child = _evidence_value(evidence, "weapon_socket_name")
            if evidence_socket or evidence_child:
                return f"{state_text}: {evidence_socket or '-'} -> {evidence_child or '-'}"
            return f"{state_text}: unknown"

        def _new_placement_summary() -> str:
            state = _visual_selected_placement_state()
            attach_socket = _visual_selected_attach_socket()
            if attach_socket:
                return f"{'Held / in hand' if state == 'held' else 'Stowed / on body'}: {attach_socket} -> {_child_socket_for_attach_point(attach_socket) or '-'}"
            if isinstance(donor_entry, ArchiveEntry) and donor_inferred_weapon_class:
                return _descriptor_socket_summary(donor_inferred_weapon_class, state, donor_evidence)
            return "Choose a placement source or body location."

        def _refresh_visual_status() -> None:
            class_text = inferred_weapon_class or "unknown"
            target_summary.setText(
                f"Target: {target_entry.basename} | class: {class_text} | "
                f"current: {_evidence_value(target_evidence, 'character_socket_name') or 'unknown'}"
            )
            current_placement_state_label.setText(
                _descriptor_socket_summary(inferred_weapon_class, _visual_selected_placement_state(), target_evidence)
            )
            new_placement_state_label.setText(_new_placement_summary())
            behavior_entry, _behavior_header_entry, behavior_patch, behavior_note = _visual_iteminfo_behavior_patch()
            if _visual_selected_swap_type() == "full_behavior":
                behavior_block_reason = _placement_behavior_patch_blocking_reason()
                if behavior_block_reason:
                    behavior_result_label.setText(
                        f"Target visuals: preserved | Target physics/HKX: preserved | Full behavior blocked: {behavior_block_reason}"
                    )
                elif isinstance(behavior_patch, AttachmentItemInfoBehaviorPatchResult) and behavior_patch.old_equip_type_name:
                    if behavior_patch.changed:
                        behavior_result_label.setText(
                            f"Target visuals: preserved | Target physics/HKX: preserved | Behavior: {behavior_patch.old_equip_type_name} -> {behavior_patch.new_equip_type_name}"
                        )
                    else:
                        behavior_result_label.setText(
                            f"Target visuals: preserved | Target physics/HKX: preserved | Behavior already {behavior_patch.old_equip_type_name}"
                        )
                else:
                    behavior_result_label.setText(
                        f"Target visuals: preserved | Target physics/HKX: preserved | {behavior_note or 'Behavior: unresolved'}"
                    )
            else:
                behavior_result_label.setText(
                    "Target visuals: preserved | Target physics/HKX: preserved | ItemInfo combat behavior unchanged."
                )
            placement_state_text = (
                "held / in hand"
                if _visual_selected_placement_state() == "held"
                else "stowed / on body"
            )
            notes = [
                f"<span style='color:#fbbf24;font-weight:700;'>target class</span> {escape(class_text)}",
                f"<span style='color:#fbbf24;font-weight:700;'>state</span> {escape(placement_state_text)}",
            ]
            if _visual_selected_swap_type() == "full_behavior":
                if isinstance(behavior_patch, AttachmentItemInfoBehaviorPatchResult) and behavior_patch.changed:
                    notes.append(
                        f"<span style='color:#6ee7b7;font-weight:700;'>ItemInfo behavior</span> "
                        f"{escape(behavior_patch.old_equip_type_name)} -&gt; {escape(behavior_patch.new_equip_type_name)}; "
                        f"<code>{escape(behavior_entry.path if isinstance(behavior_entry, ArchiveEntry) else 'iteminfo.pabgb')}</code>"
                    )
                    for proof_line in tuple(behavior_patch.proof_lines[:3]):
                        notes.append(f"<span style='color:#93c5fd;font-weight:700;'>behavior proof</span> {escape(proof_line)}")
                elif isinstance(behavior_patch, AttachmentItemInfoBehaviorPatchResult) and behavior_patch.blocking_reason:
                    notes.append(
                        f"<span style='color:#f59e0b;font-weight:700;'>ItemInfo behavior blocked</span> "
                        f"{escape(behavior_patch.blocking_reason)}"
                    )
                notes.append(
                    "<span style='color:#93c5fd;font-weight:700;'>WeaponBehaviorSwapAnalysis</span> "
                    "per-target full behavior needs proven prefab/actionchart authority; unsafe prefab resize is blocked by default. "
                    "Class-wide actionchart tool is under Advanced: Class-Wide Tools."
                )
            else:
                notes.append("<span style='color:#93c5fd;font-weight:700;'>ItemInfo behavior</span> unchanged (placement only)")
            target_prefab_entry, prefab_patch, prefab_note = _visual_target_prefab_patch()
            target_pac_xml_entry, pac_xml_patch, pac_xml_note = _visual_target_pac_xml_patch()
            if isinstance(target_pac_xml_entry, ArchiveEntry) and isinstance(pac_xml_patch, AttachmentStackEquipTypePatchResult):
                if pac_xml_patch.changed:
                    notes.append(
                        f"<span style='color:#6ee7b7;font-weight:700;'>target slot metadata</span> "
                        f"<code>{escape(target_pac_xml_entry.path)}</code>; {escape(pac_xml_note)}"
                    )
                elif pac_xml_patch.old_equip_type:
                    notes.append(
                        f"<span style='color:#93c5fd;font-weight:700;'>target slot metadata</span> "
                        f"<code>{escape(target_pac_xml_entry.path)}</code>; already {escape(pac_xml_patch.old_equip_type)}"
                    )
            elif _desired_prefab_attach_pair()[0] and pac_xml_note:
                notes.append(f"<span style='color:#f59e0b;font-weight:700;'>target slot metadata unavailable</span> {escape(pac_xml_note)}")
            if isinstance(target_prefab_entry, ArchiveEntry) and isinstance(prefab_patch, PrefabAttachmentProfilePatchResult):
                notes.append(
                    f"<span style='color:#6ee7b7;font-weight:700;'>target-only patch</span> "
                    f"<code>{escape(target_prefab_entry.path)}</code>; {escape(prefab_note)}"
                )
            elif _desired_prefab_attach_pair()[0] and prefab_note:
                notes.append(f"<span style='color:#f59e0b;font-weight:700;'>target-only patch unavailable</span> {escape(prefab_note)}")
            if patch_part_in_out_checkbox.isChecked():
                notes.append(
                    "<span style='color:#f59e0b;font-weight:700;'>class-wide descriptor fallback</span> "
                    "enabled; every weapon in the selected class can move"
                )
            else:
                notes.append(
                    "<span style='color:#93c5fd;font-weight:700;'>class-wide descriptor fallback</span> "
                    "off; normal build targets only this weapon prefab/metadata"
                )
            if isinstance(part_in_out_entry, ArchiveEntry):
                notes.append(f"<span style='color:#6ee7b7;font-weight:700;'>PartInOut XML</span> <code>{escape(part_in_out_entry.path)}</code>")
            else:
                notes.append("<span style='color:#f59e0b;font-weight:700;'>PartInOut XML missing</span> descriptor patch unavailable")
                patch_part_in_out_checkbox.setChecked(False)
                patch_part_in_out_checkbox.setEnabled(False)
            if isinstance(character_socket_entry, ArchiveEntry):
                notes.append(f"<span style='color:#6ee7b7;font-weight:700;'>character socket XML</span> <code>{escape(character_socket_entry.path)}</code>")
            else:
                notes.append("<span style='color:#f59e0b;font-weight:700;'>character socket XML missing</span> socket profile patch unavailable")
                patch_socket_checkbox.setChecked(False)
                patch_socket_checkbox.setEnabled(False)
            if imported_profile_state.get("part_in_out_path"):
                notes.append(f"<span style='color:#34d399;font-weight:700;'>imported PartInOut profile</span> <code>{escape(str(imported_profile_state.get('part_in_out_path') or ''))}</code>")
            elif isinstance(donor_entry, ArchiveEntry) and donor_inferred_weapon_class and not _visual_selected_attach_socket():
                notes.append(
                    f"<span style='color:#6ee7b7;font-weight:700;'>source placement</span> "
                    f"{escape(donor_entry.basename)} class {escape(donor_inferred_weapon_class)}; donor files are not copied"
                )
            if imported_profile_state.get("socket_path"):
                notes.append(f"<span style='color:#34d399;font-weight:700;'>imported socket profile</span> <code>{escape(str(imported_profile_state.get('socket_path') or ''))}</code>")
                use_profile_transforms_checkbox.setEnabled(isinstance(character_socket_entry, ArchiveEntry))
                patch_socket_checkbox.setEnabled(isinstance(character_socket_entry, ArchiveEntry))
            elif not patch_socket_checkbox.isChecked():
                use_profile_transforms_checkbox.setEnabled(False)
                use_profile_transforms_checkbox.setChecked(False)
                patch_socket_checkbox.setEnabled(False)
            attach_socket = _visual_selected_attach_socket()
            if attach_socket:
                choice = _visual_selected_attach_choice()
                label = choice.label if isinstance(choice, AttachmentBodyLocationChoice) else attach_socket
                notes.append(
                    f"<span style='color:#fbbf24;font-weight:700;'>attach point</span> "
                    f"{escape(label)}: {escape(attach_socket)} -&gt; {escape(_child_socket_for_attach_point(attach_socket) or 'unchanged child socket')}"
                )
                if isinstance(choice, AttachmentBodyLocationChoice) and choice.note:
                    notes.append(f"<span style='color:#93c5fd;font-weight:700;'>body row</span> {escape(choice.note)}")
            visual_status.setText("<br>".join(notes))

        def _import_visual_profile_xml() -> None:
            selected, _selected_filter = QFileDialog.getOpenFileName(
                dialog,
                "Import Placement Profile XML",
                str(Path.home() / "Desktop"),
                "Placement XML (*.xml *.sockets.xml);;All files (*.*)",
            )
            if not selected:
                return
            path = Path(selected).expanduser()

            def _apply_profile_payload(text: str) -> None:
                lowered = path.name.casefold()
                if lowered.endswith(".sockets.xml") or "socket" in lowered:
                    imported_profile_state["socket_text"] = text
                    imported_profile_state["socket_path"] = str(path)
                    patch_socket_checkbox.setEnabled(isinstance(character_socket_entry, ArchiveEntry))
                    should_use_profile = False
                    attach_socket = _visual_selected_attach_socket()
                    if isinstance(character_socket_entry, ArchiveEntry) and attach_socket:
                        preview_patch = build_socket_bone_data_profile_patch(
                            _read_archive_text(character_socket_entry),
                            text,
                            socket_names=(attach_socket,),
                        )
                        should_use_profile = bool(preview_patch.diffs)
                    use_profile_transforms_checkbox.setEnabled(isinstance(character_socket_entry, ArchiveEntry))
                    use_profile_transforms_checkbox.setChecked(should_use_profile)
                    patch_socket_checkbox.setChecked(should_use_profile)
                else:
                    imported_profile_state["part_in_out_text"] = text
                    imported_profile_state["part_in_out_path"] = str(path)
                    if isinstance(part_in_out_entry, ArchiveEntry):
                        patch_part_in_out_checkbox.setChecked(True)
                _populate_attach_point_combo()
                _refresh_visual_status()
                _refresh_package_plan()

            start_attachment_profile_import(
                self,
                dialog,
                import_profile_button,
                path,
                on_loaded=_apply_profile_payload,
            )

        def _advanced_features_enabled() -> bool:
            return bool(advanced_features_toggle.isChecked())

        def _effective_package_plan_rows() -> List[dict]:
            if not _advanced_features_enabled():
                return []
            effective_rows: List[dict] = []
            for row in package_plan_rows:
                donor = row.get("donor_entry")
                target = row.get("target_entry")
                action = str(row.get("action") or "")
                if not isinstance(donor, ArchiveEntry) or not isinstance(target, ArchiveEntry):
                    continue
                same_entry = self._same_archive_entry(donor, target)
                explicit_source_icon = (
                    use_source_icon_checkbox.isChecked()
                    and "icon" in action.casefold()
                    and "explicit" in action.casefold()
                )
                if legacy_raw_prefab_checkbox.isChecked() or same_entry or explicit_source_icon:
                    effective_rows.append(row)
            return effective_rows

        def _refresh_package_plan() -> None:
            nonlocal package_plan_rows, package_plan_warnings
            if isinstance(donor_entry, ArchiveEntry):
                package_plan_rows, package_plan_warnings = self._build_attachment_donor_package_plan(
                    target_entry,
                    donor_entry,
                    target_graph,
                    donor_graph,
                    legacy_raw_prefab_copy=legacy_raw_prefab_checkbox.isChecked(),
                    copy_source_icon=use_source_icon_checkbox.isChecked(),
                    experimental_copy_source_hkx=legacy_hkx_checkbox.isChecked(),
                )
            else:
                package_plan_rows, package_plan_warnings = [], []
            advanced_enabled = _advanced_features_enabled()
            effective_package_plan_rows = _effective_package_plan_rows()
            visual_rows = _visual_patch_preview_rows()
            plan_tree.clear()
            if effective_package_plan_rows:
                for row in effective_package_plan_rows:
                    donor = row.get("donor_entry")
                    target = row.get("target_entry")
                    donor_path = donor.path if isinstance(donor, ArchiveEntry) else "-"
                    target_path = target.path if isinstance(target, ArchiveEntry) else "-"
                    item = QTreeWidgetItem(
                        [
                            str(row.get("action") or "-"),
                            donor_path,
                            target_path,
                            str(row.get("note") or ""),
                        ]
                    )
                    item.setToolTip(1, donor_path)
                    item.setToolTip(2, target_path)
                    item.setToolTip(3, str(row.get("note") or ""))
                    plan_tree.addTopLevelItem(item)
            elif not visual_rows:
                plan_tree.addTopLevelItem(
                    QTreeWidgetItem(
                        [
                            "No buildable placement patch yet",
                            "-",
                            "-",
                            "Choose a source/body location, or open Advanced if target-only prefab patch is unavailable.",
                        ]
                    )
                )
            patch_scope_blocked = _placement_part_in_out_patch_blocking_reason(_visual_part_in_out_preview_patch())
            behavior_blocked = _placement_behavior_patch_blocking_reason()
            _pac_xml_entry, pac_xml_patch, pac_xml_note = _visual_target_pac_xml_patch()
            pac_xml_blocked = (
                pac_xml_note
                if _desired_stack_equip_type()
                and not (
                    isinstance(pac_xml_patch, AttachmentStackEquipTypePatchResult)
                    and (pac_xml_patch.changed or pac_xml_patch.old_equip_type)
                )
                else ""
            )
            _prefab_entry, prefab_patch, prefab_note = _visual_target_prefab_patch()
            prefab_blocked = (
                prefab_note
                if _desired_prefab_attach_pair()[0] and not isinstance(prefab_patch, PrefabAttachmentProfilePatchResult)
                else ""
            )
            for action, target_path, note in visual_rows:
                item = QTreeWidgetItem([action, "target-owned metadata", target_path, note])
                item.setToolTip(2, target_path)
                item.setToolTip(3, note)
                plan_tree.addTopLevelItem(item)
            loose_specs = _target_loose_specs()
            _pac_context_entry, pac_context_patch, _pac_context_note = _visual_target_pac_xml_patch()
            slot_context = ""
            if isinstance(pac_context_patch, AttachmentStackEquipTypePatchResult) and pac_context_patch.old_equip_type:
                desired_equip_type = pac_context_patch.new_equip_type or _desired_stack_equip_type()
                slot_context = f" Target slot: {pac_context_patch.old_equip_type} -> {desired_equip_type}."
            behavior_context = ""
            _behavior_entry, _behavior_header_entry, behavior_patch, _behavior_note = _visual_iteminfo_behavior_patch()
            if isinstance(behavior_patch, AttachmentItemInfoBehaviorPatchResult) and behavior_patch.old_equip_type_name:
                if _visual_selected_swap_type() == "full_behavior" and behavior_patch.changed:
                    behavior_context = (
                        f" Behavior: {behavior_patch.old_equip_type_name} -> {behavior_patch.new_equip_type_name}."
                    )
                elif _visual_selected_swap_type() == "full_behavior":
                    behavior_context = f" Behavior already {behavior_patch.old_equip_type_name}."
            elif _visual_selected_swap_type() == "placement_only":
                behavior_context = " Behavior unchanged."
            target_context_status.setText(
                (
                    f"Modded target files preserved ({len(loose_specs):,}).{slot_context}{behavior_context}"
                    if loose_specs
                    else f"Vanilla target files stay in game. Package writes placement metadata only.{slot_context}{behavior_context}"
                )
            )
            target_context_status.setToolTip(
                (
                    f"Preserving target-owned loose files from {_selected_target_loose_root()}."
                    if loose_specs
                    else "No loose target mod detected; vanilla model, textures, icon, and physics are provided by the game."
                )
            )
            if loose_specs and not advanced_enabled:
                plan_tree.addTopLevelItem(
                    QTreeWidgetItem(
                        [
                            "Preserve target-owned files",
                            f"{len(loose_specs):,} file(s)",
                            "-",
                            "Existing modded target model, textures, icon, prefab, and physics are kept.",
                        ]
                    )
                )
            for spec in (loose_specs[:40] if advanced_enabled else ()):
                item = QTreeWidgetItem(
                    [
                        "Preserve existing target loose file",
                        str(spec.source_path),
                        str(spec.target_path or "-"),
                        str(spec.note or "Target-owned model/material/texture/icon payload."),
                    ]
                )
                item.setToolTip(1, str(spec.source_path))
                item.setToolTip(2, str(spec.target_path or "-"))
                plan_tree.addTopLevelItem(item)
            if advanced_enabled and len(loose_specs) > 40:
                plan_tree.addTopLevelItem(
                    QTreeWidgetItem(
                        [
                            "Preserve existing target loose file",
                            f"{len(loose_specs) - 40:,} more",
                            "-",
                            "Additional target-owned loose payloads are preserved.",
                        ]
                    )
                )
            warning_parts = (
                ([patch_scope_blocked] if patch_scope_blocked else [])
                + ([behavior_blocked] if behavior_blocked else [])
                + ([pac_xml_blocked] if pac_xml_blocked else [])
                + ([prefab_blocked] if prefab_blocked else [])
                + (list(package_plan_warnings[:5]) if advanced_enabled else [])
            )
            warning_label.setText("Review notes: " + " ".join(warning_parts) if warning_parts else "")
            warning_label.setVisible(bool(warning_parts))
            loose_scan_error = _target_loose_warning()
            build_ready = bool(effective_package_plan_rows or visual_rows) and not bool(
                patch_scope_blocked or behavior_blocked or loose_scan_error
            )
            build_button.setEnabled(build_ready)
            if loose_scan_error:
                simple_ready_status.setText(loose_scan_error)
            elif patch_scope_blocked:
                simple_ready_status.setText("Cannot build safely. Open Advanced to review the blocked descriptor patch.")
            elif behavior_blocked:
                simple_ready_status.setText("Cannot build full behavior safely. Use Placement only or choose a resolved 1H/2H source.")
            elif visual_rows:
                simple_ready_status.setText("Ready: target metadata patch. Source weapon files will not be copied.")
            elif effective_package_plan_rows:
                simple_ready_status.setText("Ready: advanced package rows enabled.")
            elif prefab_blocked:
                simple_ready_status.setText(
                    "Source/body location selected, but target prefab cannot be patched safely. Open Advanced for fallback options."
                )
            else:
                simple_ready_status.setText("Pick a 1H/2H source weapon or manual body location to build.")
            expand_tree_columns_to_available_width(plan_tree)

        def _placement_custom_icon_override_spec(*, show_messages: bool) -> Optional[ItemIconOverrideSpec]:
            if not custom_icon_checkbox.isChecked():
                return None
            target_icon_entry = custom_icon_target_combo.currentData()
            if not isinstance(target_icon_entry, ArchiveEntry):
                if show_messages:
                    QMessageBox.warning(
                        dialog,
                        "Custom Item Icon",
                        "Choose an existing resolved target icon path before building a custom item icon.",
                    )
                return None
            source_text = custom_icon_source_edit.text().strip()
            if not source_text:
                if show_messages:
                    QMessageBox.warning(dialog, "Custom Item Icon", "Choose a custom icon source file or folder.")
                return None
            source_root = Path(source_text).expanduser()
            chosen, _candidates, message = self.app_context.services.require_item_icons().choose_source(
                source_root,
                target_path=target_icon_entry.path,
                related_stems=self._archive_item_icon_related_stems(target_entry, target_graph),
                display_name=target_entry.basename,
            )
            if chosen is None:
                if show_messages:
                    QMessageBox.warning(dialog, "Custom Item Icon", message)
                return None
            return ItemIconOverrideSpec(
                source_path=chosen.path,
                target_entry=target_icon_entry,
                target_path=target_icon_entry.path,
                source_mode="folder" if source_root.is_dir() else "file",
            )

        def _refresh_custom_icon_status() -> None:
            custom_icon_controls_widget.setVisible(bool(custom_icon_checkbox.isChecked()))
            custom_icon_clear_button.setVisible(bool(custom_icon_checkbox.isChecked()))
            controls_enabled = bool(custom_icon_checkbox.isChecked() and target_icon_entries)
            custom_icon_source_edit.setEnabled(controls_enabled)
            custom_icon_file_button.setEnabled(controls_enabled)
            custom_icon_folder_button.setEnabled(controls_enabled)
            custom_icon_library_button.setEnabled(controls_enabled)
            custom_icon_target_combo.setEnabled(controls_enabled)
            if not custom_icon_checkbox.isChecked():
                custom_icon_status.setText("Icon: existing target icon is preserved.")
                return
            target_icon_entry = custom_icon_target_combo.currentData()
            if not isinstance(target_icon_entry, ArchiveEntry):
                custom_icon_status.setText("Current: no existing target icon path. Source: not used. Final: unavailable.")
                return
            source_text = custom_icon_source_edit.text().strip()
            if not source_text:
                custom_icon_status.setText(
                    f"Current: {target_icon_entry.path}. Source: choose file or folder. Final: fit + pad to existing icon template."
                )
                return
            chosen, candidates, message = self.app_context.services.require_item_icons().choose_source(
                Path(source_text).expanduser(),
                target_path=target_icon_entry.path,
                related_stems=self._archive_item_icon_related_stems(target_entry, target_graph),
                display_name=target_entry.basename,
            )
            if chosen is None:
                custom_icon_status.setText(
                    f"Current: {target_icon_entry.path}. Source: {message} Final: unavailable."
                )
                return
            extra = f" ({len(candidates):,} candidate(s) scanned)" if Path(source_text).expanduser().is_dir() else ""
            custom_icon_status.setText(
                f"Current: {target_icon_entry.path}. Source: {chosen.path}{extra}. "
                "Final: fit + pad to the target icon size, format, and mip count."
            )

        def _choose_custom_icon_file() -> None:
            suffixes = " ".join(f"*{suffix}" for suffix in sorted(ITEM_ICON_SOURCE_EXTENSIONS))
            selected, _selected_filter = QFileDialog.getOpenFileName(
                dialog,
                "Choose Custom Item Icon",
                str(self.settings_file_path.parent),
                f"Icon images ({suffixes});;All files (*.*)",
            )
            if selected:
                custom_icon_source_edit.setText(selected)

        def _choose_custom_icon_folder() -> None:
            selected = QFileDialog.getExistingDirectory(
                dialog,
                "Choose Custom Item Icon Folder",
                str(self.settings_file_path.parent),
            )
            if selected:
                custom_icon_source_edit.setText(selected)

        def _choose_custom_icon_library_source() -> None:
            selected = self._choose_item_icon_library_source(dialog)
            if selected is not None:
                custom_icon_source_edit.setText(str(selected))

        def _refresh_experimental_options() -> None:
            if not legacy_raw_prefab_checkbox.isChecked() and legacy_hkx_checkbox.isChecked():
                legacy_hkx_checkbox.setChecked(False)
            legacy_hkx_enabled = legacy_raw_prefab_checkbox.isChecked()
            legacy_hkx_checkbox.setVisible(legacy_hkx_enabled)
            legacy_hkx_checkbox.setEnabled(legacy_hkx_enabled)
            _refresh_package_plan()

        def _set_placement_source_loading(active: bool, message: str = "") -> None:
            source_copy_button.setEnabled(not active)
            swap_type_combo.setEnabled(not active)
            placement_state_combo.setEnabled(not active)
            attach_point_combo.setEnabled(not active)
            universal_twohand_button.setEnabled(not active)
            universal_twohand_true_button.setEnabled(not active)
            use_source_icon_checkbox.setEnabled((not active) and isinstance(donor_entry, ArchiveEntry))
            donor_socket_button.setEnabled((not active) and isinstance(donor_socket_entry, ArchiveEntry))
            if active:
                build_button.setEnabled(False)
                status = message or "Loading placement comparison..."
                simple_ready_status.setText(status)
                target_context_status.setText(status)
                visual_status.setText(status)
                warning_label.setText(status)
                warning_label.setVisible(True)
                plan_tree.clear()
                plan_tree.addTopLevelItem(QTreeWidgetItem(["Loading placement comparison...", "-", "-", status]))

        def _apply_prepared_placement_source(prepared: PlacementWorkspacePreparation) -> None:
            nonlocal target_graph, donor_entry, donor_graph
            nonlocal target_evidence, donor_evidence, target_socket_entry, donor_socket_entry
            nonlocal inferred_weapon_class, donor_inferred_weapon_class
            if not dialog.isVisible():
                return
            prepared_payloads.merge(prepared)
            if isinstance(prepared.target_graph, AssetFamilyGraph):
                target_graph = prepared.target_graph
                target_evidence = self._attachment_visual_best_evidence(target_graph)
                target_socket_entry = self._attachment_socket_entry_from_selection(target_graph)
                if isinstance(target_socket_entry, ArchiveEntry) and isinstance(prepared.target_socket_document, AttachmentSocketDocument):
                    socket_documents_by_key[self._attachment_package_entry_key(target_socket_entry)] = prepared.target_socket_document
            if not isinstance(prepared.donor_entry, ArchiveEntry) or not isinstance(prepared.donor_graph, AssetFamilyGraph):
                _set_placement_source_loading(False)
                self.set_status_message("Placement source preparation finished without a source graph.", error=True)
                _refresh_visual_status()
                _refresh_package_plan()
                return
            donor_entry = prepared.donor_entry
            donor_graph = prepared.donor_graph
            donor_evidence = self._attachment_visual_best_evidence(donor_graph)
            donor_socket_entry = self._attachment_socket_entry_from_selection(donor_graph)
            if isinstance(donor_socket_entry, ArchiveEntry) and isinstance(prepared.donor_socket_document, AttachmentSocketDocument):
                socket_documents_by_key[self._attachment_package_entry_key(donor_socket_entry)] = prepared.donor_socket_document
            inferred_weapon_class = _infer_current_weapon_class()
            donor_inferred_weapon_class = _infer_current_donor_weapon_class()
            behavior_patch_cache.clear()
            direction_label.setText(f"Target to change: {target_entry.path}\nPlacement source: {donor_entry.path}")
            target_socket_button.setEnabled(isinstance(target_socket_entry, ArchiveEntry))
            donor_socket_button.setEnabled(isinstance(donor_socket_entry, ArchiveEntry))
            _rebuild_source_evidence_tree()
            _rebuild_compare_tree()
            _populate_attach_point_combo()
            _apply_default_swap_type()
            _set_placement_source_loading(False)
            _refresh_custom_icon_status()
            _refresh_visual_status()
            _refresh_package_plan()

        def _choose_placement_source_from_workspace() -> None:
            donor = self._open_archive_attachment_donor_picker_dialog(dialog, target_entry)
            if isinstance(donor, ArchiveEntry):
                status = "Loading placement comparison..."
                _set_placement_source_loading(True, status)
                started = self._run_archive_attachment_placement_prepare(
                    target_entry,
                    donor,
                    status_message=f"Loading placement comparison for {target_entry.basename}...",
                    on_prepared=_apply_prepared_placement_source,
                    on_error=lambda _message: _set_placement_source_loading(False),
                )
                if not started:
                    _set_placement_source_loading(False)

        def _apply_default_swap_type() -> None:
            swap_type_combo.blockSignals(True)
            try:
                placement_index = swap_type_combo.findData("placement_only")
                if placement_index >= 0:
                    swap_type_combo.setCurrentIndex(placement_index)
            finally:
                swap_type_combo.blockSignals(False)

        def _universal_twohand_sword_part_in_out_patch() -> Tuple[
            Optional[ArchiveEntry],
            Optional[AttachmentPartInOutPatchResult],
            str,
        ]:
            if not isinstance(universal_part_in_out_entry, ArchiveEntry):
                return None, None, "2H sword hip placement XML was not found; package will contain animation aliases only."
            base_text = _read_original_archive_text(universal_part_in_out_entry)
            if not base_text:
                return universal_part_in_out_entry, None, "Original 2H sword hip placement XML could not be read."
            patch = build_part_in_out_socket_attach_point_patch(
                base_text,
                weapon_class="twohand_sword",
                in_socket_bone="Pelvis_L_Socket",
                in_child_socket_bone="Pelvis_L_ChildSocket",
                placement_state="stowed",
            )
            if isinstance(patch, AttachmentPartInOutPatchResult) and patch.diffs:
                return universal_part_in_out_entry, patch, f"{len(patch.diffs):,} 2H sword hip placement field(s) patched."
            return universal_part_in_out_entry, patch, "2H sword hip placement XML included from original archive; no descriptor diff was needed."

        def _universal_twohand_sword_animation_alias_plan() -> Tuple[
            AttachmentAnimationAliasPlanResult,
            Dict[str, ArchiveEntry],
        ]:
            original_entries_by_path = _original_archive_entries_by_virtual_path()
            if not isinstance(universal_twohandsword_upper_entry, ArchiveEntry):
                return (
                    AttachmentAnimationAliasPlanResult(
                        blocking_reason=(
                            "Universal 2H sword animation aliases need the original "
                            "actionchart/bin__/upperaction/1_pc/1_phm/twohandsword_upper.paac entry."
                        )
                    ),
                    original_entries_by_path,
                )
            twohand_actionchart_data = _read_original_archive_bytes(universal_twohandsword_upper_entry)
            if not twohand_actionchart_data:
                return (
                    AttachmentAnimationAliasPlanResult(
                        blocking_reason="Original twohandsword_upper.paac could not be read for animation reference scanning."
                    ),
                    original_entries_by_path,
                )
            ride_actionchart_data = (
                _read_original_archive_bytes(universal_ride_twohandsword_upper_entry)
                if isinstance(universal_ride_twohandsword_upper_entry, ArchiveEntry)
                else b""
            )
            longsword_actionchart_data = (
                _read_original_archive_bytes(universal_longsword_upper_entry)
                if isinstance(universal_longsword_upper_entry, ArchiveEntry)
                else b""
            )
            weaponin_actionchart_data = (
                _read_original_archive_bytes(universal_basic_weaponin_entry)
                if isinstance(universal_basic_weaponin_entry, ArchiveEntry)
                else b""
            )
            plan = build_universal_twohand_sword_animation_alias_plan(
                twohand_actionchart_data,
                ride_actionchart_data,
                available_paths=tuple(entry.path for entry in original_entries_by_path.values()),
                longsword_actionchart_data=longsword_actionchart_data,
                weaponin_actionchart_data=weaponin_actionchart_data,
            )
            return plan, original_entries_by_path

        def _universal_twohand_sword_true_onehand_iteminfo_patch_plan(
            original_entries_by_path: Mapping[str, ArchiveEntry],
        ) -> Tuple[
            Optional[ArchiveEntry],
            Optional[ArchiveEntry],
            Optional[AttachmentUniversalItemInfoBehaviorPatchResult],
            str,
        ]:
            def original_entry(path: str) -> Optional[ArchiveEntry]:
                return original_entries_by_path.get(str(path or "").replace("\\", "/").strip().strip("/").casefold())

            iteminfo_task_entry = original_entry("gamedata/binary__/client/bin/iteminfo.pabgb")
            iteminfo_header_task_entry = original_entry("gamedata/binary__/client/bin/iteminfo.pabgh")
            equiptype_task_entry = original_entry("gamedata/binary__/client/bin/equiptypeinfo.pabgb")
            equiptype_header_task_entry = original_entry("gamedata/binary__/client/bin/equiptypeinfo.pabgh")
            required_entries = (
                iteminfo_task_entry,
                iteminfo_header_task_entry,
                equiptype_task_entry,
                equiptype_header_task_entry,
            )
            if not all(isinstance(entry, ArchiveEntry) for entry in required_entries):
                result = AttachmentUniversalItemInfoBehaviorPatchResult(
                    blocking_reason=(
                        "True 1H mode needs original iteminfo.pabgb/.pabgh and equiptypeinfo.pabgb/.pabgh."
                    )
                )
                return iteminfo_task_entry, iteminfo_header_task_entry, result, result.blocking_reason

            iteminfo_data = _read_original_archive_bytes(iteminfo_task_entry)
            iteminfo_header_data = _read_original_archive_bytes(iteminfo_header_task_entry)
            equiptype_data = _read_original_archive_bytes(equiptype_task_entry)
            equiptype_header_data = _read_original_archive_bytes(equiptype_header_task_entry)
            if not iteminfo_data or not iteminfo_header_data or not equiptype_data or not equiptype_header_data:
                result = AttachmentUniversalItemInfoBehaviorPatchResult(
                    blocking_reason="True 1H mode could not read ItemInfo or EquipTypeInfo tables from original archives."
                )
                return iteminfo_task_entry, iteminfo_header_task_entry, result, result.blocking_reason

            result = build_universal_twohand_sword_true_onehand_iteminfo_patch(
                iteminfo_data,
                iteminfo_header_data,
                equiptype_data,
                equiptype_header_data,
            )
            if isinstance(result, AttachmentUniversalItemInfoBehaviorPatchResult) and result.blocking_reason:
                return iteminfo_task_entry, iteminfo_header_task_entry, result, result.blocking_reason
            if isinstance(result, AttachmentUniversalItemInfoBehaviorPatchResult) and result.changed:
                return (
                    iteminfo_task_entry,
                    iteminfo_header_task_entry,
                    result,
                    f"{result.changed_count:,} 2H sword ItemInfo row(s) patched to true 1H equipment behavior.",
                )
            return iteminfo_task_entry, iteminfo_header_task_entry, result, "No true 1H ItemInfo behavior change was produced."

        def _build_universal_twohand_sword_package(*, include_true_onehand_iteminfo: bool = False) -> None:
            if include_true_onehand_iteminfo:
                QMessageBox.warning(
                    dialog,
                    "Build Universal 2H Swords As True 1H",
                    (
                        "True 1H/offhand export is disabled after in-game crash testing. "
                        "The current ItemInfo-only patch is incomplete; it does not safely resolve the equip-state/offhand logic."
                    ),
                )
                return
            alias_plan, original_entries_by_path = _universal_twohand_sword_animation_alias_plan()
            if not isinstance(alias_plan, AttachmentAnimationAliasPlanResult) or alias_plan.blocking_reason:
                QMessageBox.warning(
                    dialog,
                    "Build Universal 2H Swords As 1H",
                    alias_plan.blocking_reason if isinstance(alias_plan, AttachmentAnimationAliasPlanResult) else "Animation alias planning failed.",
                )
                return
            placement_entry, placement_patch, placement_note = _universal_twohand_sword_part_in_out_patch()
            iteminfo_entry_task, iteminfo_header_entry_task, iteminfo_patch, iteminfo_note = (
                _universal_twohand_sword_true_onehand_iteminfo_patch_plan(original_entries_by_path)
                if include_true_onehand_iteminfo
                else (None, None, None, "ItemInfo true 1H behavior patch not requested.")
            )
            if (
                include_true_onehand_iteminfo
                and isinstance(iteminfo_patch, AttachmentUniversalItemInfoBehaviorPatchResult)
                and iteminfo_patch.blocking_reason
            ):
                QMessageBox.warning(dialog, "Build Universal 2H Swords As True 1H", iteminfo_patch.blocking_reason)
                return
            preview_lines = [
                "- Alias PHM 2H sword animation payloads to matching 1H sword payloads:",
            ]
            preview_lines.extend(f"- {line}" for line in tuple(alias_plan.proof_lines or ()))
            for pair in tuple(alias_plan.pairs[:10]):
                preview_lines.append(f"- {pair.source_path} -> {pair.target_path}")
            if len(alias_plan.pairs) > 10:
                preview_lines.append(f"- ...and {len(alias_plan.pairs) - 10:,} more animation alias payload(s)")
            if isinstance(placement_entry, ArchiveEntry) and isinstance(placement_patch, AttachmentPartInOutPatchResult) and placement_patch.text:
                preview_lines.append(f"- Include 2H sword hip placement XML -> {placement_entry.path}")
                preview_lines.append("- Include known CDUMM alias -> character/phm_description_player_kliff.xml")
            else:
                preview_lines.append(f"- Placement XML skipped: {placement_note}")
            if include_true_onehand_iteminfo and isinstance(iteminfo_patch, AttachmentUniversalItemInfoBehaviorPatchResult):
                preview_lines.append("- Include experimental ItemInfo true 1H/offhand equipment patch:")
                preview_lines.extend(f"- {line}" for line in tuple(iteminfo_patch.proof_lines[:8]))
                if len(iteminfo_patch.proof_lines) > 8:
                    preview_lines.append(f"- ...and {len(iteminfo_patch.proof_lines) - 8:,} more ItemInfo proof line(s)")
            question = (
                "Build universal all-2H-swords-as-1H package?\n\n"
                "Scope: PHM 2H sword motion aliases plus 2H sword hip placement XML"
                + (" plus guarded ItemInfo true 1H/offhand patch." if include_true_onehand_iteminfo else ".")
                + "\n"
                "No actionchart .paac graph copy. "
                + ("ItemInfo export is limited to 2H sword rows with proven true-1H signatures. " if include_true_onehand_iteminfo else "No ItemInfo table export. ")
                + "No axe/spear/hammer/mace/cannon rows. "
                "No per-sword model, prefab, icon, or HKX copies.\n\n"
                + "\n".join(preview_lines)
                + "\n\nNo original archives will be modified."
            )
            answer = QMessageBox.question(
                dialog,
                "Build Universal 2H Swords As True 1H" if include_true_onehand_iteminfo else "Build Universal 2H Swords As 1H",
                question,
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if answer != QMessageBox.Yes:
                return
            target_settings = self._collect_archive_mod_ready_export_target(
                browse_title="Choose Universal 2H Swords As 1H Export Root",
                prompt_for_metadata=True,
                dialog_title="Build Universal 2H Swords As True 1H" if include_true_onehand_iteminfo else "Build Universal 2H Swords As 1H",
                allow_dmm_texture_structure=False,
                initial_package_title="all2h-as-1h true1h" if include_true_onehand_iteminfo else "all2h-as-1h",
                initial_package_description=(
                    "2H swords use matching 1H PHM sword animation payloads where safely resolved. "
                    + (
                        "Experimental ItemInfo patch changes 2H sword equipment behavior to 1H/offhand while preserving item rows and assets."
                        if include_true_onehand_iteminfo
                        else "Includes 2H sword hip placement XML when available."
                    )
                ),
                parent=dialog,
            )
            if target_settings is None:
                return
            export_root, package_info, create_no_encrypt_file, _include_related, export_options = target_settings
            diagnostics = [
                "Feature: Universal 2H Swords As 1H",
                "Base source: original numeric game archive entries only; modded/loose animation sources blocked.",
                "Behavior path: PHM 2H sword motion/motionblending aliases use matching 1H sword payloads where safely resolved.",
                "Scanned graphs: twohandsword_upper, ride_weapon_twohandsword_upper, basic_upper_weaponin, and passive refs from longsword_upper when present.",
                "Combat/guard PAA aliases are skipped by default; PAA-only combat swaps desync the original 2H actionchart timing.",
                "2H sword WeaponCasePart is left unchanged; forcing the 1H case part is not universal across 2H sword prefabs.",
                "Actionchart PAAC graph copy is disabled; whole-PAAC 1H graph swaps can hang save loading.",
                (
                    "ItemInfo table is exported with a guarded _equipTypeInfo plus 9-byte one-hand sword-family and _itemType patch for 2H sword rows only."
                    if include_true_onehand_iteminfo
                    else "ItemInfo table is not exported; previous ItemInfo-only batch patch can crash the game."
                ),
                "Other 2H weapon families unchanged: axe, spear, hammer, mace, cannon.",
                "No source model/prefab/icon/HKX files copied; only animation payload aliases are exported.",
                placement_note,
                iteminfo_note,
                *tuple(alias_plan.proof_lines or ()),
                *tuple(iteminfo_patch.proof_lines if isinstance(iteminfo_patch, AttachmentUniversalItemInfoBehaviorPatchResult) else ()),
            ]
            package_info = self._placement_swap_package_info_with_diagnostics(package_info, diagnostics)
            alias_plan_snapshot = alias_plan
            original_entries_by_path_snapshot = dict(original_entries_by_path)
            include_true_onehand_iteminfo_snapshot = bool(include_true_onehand_iteminfo)
            iteminfo_entry_snapshot = iteminfo_entry_task
            iteminfo_header_entry_snapshot = iteminfo_header_entry_task
            iteminfo_patch_snapshot = iteminfo_patch

            def _task(log: Callable[[str], None]) -> ArchiveLooseExportResult:
                requests_by_path: Dict[str, ArchivePatchRequest] = {}
                alias_request_count = 0
                for pair in tuple(alias_plan_snapshot.pairs or ()):
                    source_key = str(pair.source_path or "").replace("\\", "/").strip().strip("/").casefold()
                    target_key = str(pair.target_path or "").replace("\\", "/").strip().strip("/").casefold()
                    source_entry = original_entries_by_path_snapshot.get(source_key)
                    target_entry = original_entries_by_path_snapshot.get(target_key)
                    if not isinstance(source_entry, ArchiveEntry) or not isinstance(target_entry, ArchiveEntry):
                        log(f"Skip unresolved animation alias path: {pair.source_path} -> {pair.target_path}")
                        continue
                    payload_data = _read_original_archive_bytes(source_entry)
                    if not payload_data:
                        log(f"Skip unreadable animation alias source: {source_entry.path}")
                        continue
                    requests_by_path[target_key] = ArchivePatchRequest(target_entry, payload_data)
                    alias_request_count += 1
                    log(f"Alias 2H sword animation payload: {source_entry.path} -> {target_entry.path}; {pair.reason}")

                alias_specs: List[MeshImportSupplementalFileSpec] = []
                placement_entry_task, placement_patch_task, placement_note_task = _universal_twohand_sword_part_in_out_patch()
                if (
                    isinstance(placement_entry_task, ArchiveEntry)
                    and isinstance(placement_patch_task, AttachmentPartInOutPatchResult)
                    and str(placement_patch_task.text or "")
                ):
                    placement_key = placement_entry_task.path.replace("\\", "/").strip().casefold()
                    requests_by_path[placement_key] = ArchivePatchRequest(
                        placement_entry_task,
                        _encode_placement_base_text(placement_entry_task, placement_patch_task.text),
                    )
                    alias_specs.extend(
                        _placement_global_xml_alias_specs(
                            placement_entry_task,
                            placement_patch_task.text,
                            ("character/phm_description_player_kliff.xml",),
                            kind="placement_descriptor_alias",
                        )
                    )
                    log(f"Include 2H sword hip placement XML: {placement_entry_task.path}; {placement_note_task}")
                    for diff in tuple(placement_patch_task.diffs[:20]):
                        log(
                            "Patch PartInOut placement XML: "
                            f"{diff.part_name} {diff.field_name}: {diff.old_value or '-'} -> {diff.new_value or '-'}"
                        )
                else:
                    log(f"Skip 2H sword hip placement XML: {placement_note_task}")

                if include_true_onehand_iteminfo_snapshot:
                    if not (
                        isinstance(iteminfo_entry_snapshot, ArchiveEntry)
                        and isinstance(iteminfo_header_entry_snapshot, ArchiveEntry)
                        and isinstance(iteminfo_patch_snapshot, AttachmentUniversalItemInfoBehaviorPatchResult)
                        and iteminfo_patch_snapshot.changed
                    ):
                        raise ValueError("True 1H ItemInfo patch was requested but no validated patch payload was available.")
                    iteminfo_key = iteminfo_entry_snapshot.path.replace("\\", "/").strip().casefold()
                    requests_by_path[iteminfo_key] = ArchivePatchRequest(iteminfo_entry_snapshot, iteminfo_patch_snapshot.data)
                    iteminfo_header_data = _read_original_archive_bytes(iteminfo_header_entry_snapshot)
                    if iteminfo_header_data:
                        iteminfo_header_key = iteminfo_header_entry_snapshot.path.replace("\\", "/").strip().casefold()
                        requests_by_path[iteminfo_header_key] = ArchivePatchRequest(iteminfo_header_entry_snapshot, iteminfo_header_data)
                        log(f"Include unchanged ItemInfo header companion: {iteminfo_header_entry_snapshot.path}")
                    else:
                        log("ItemInfo header companion could not be read; patched iteminfo.pabgb will still be exported.")
                    log(f"Patch ItemInfo true 1H/offhand behavior: {iteminfo_entry_snapshot.path}; {iteminfo_note}")
                    for proof_line in tuple(iteminfo_patch_snapshot.proof_lines[:40]):
                        log(f"ItemInfo true 1H proof: {proof_line}")

                if alias_request_count <= 0:
                    raise ValueError("No universal 2H sword animation alias payloads could be read from original archives.")

                return export_archive_payloads_to_mod_ready_loose(
                    list(requests_by_path.values()),
                    parent_root=export_root,
                    package_info=package_info,
                    export_options=export_options,
                    create_no_encrypt_file=create_no_encrypt_file,
                    extra_payloads_to_include=tuple(alias_specs),
                    on_log=log,
                )

            def _handle_complete(result: object) -> None:
                if isinstance(result, ArchiveLooseExportResult):
                    QMessageBox.information(
                        dialog,
                        "Universal 2H Swords As True 1H Complete" if include_true_onehand_iteminfo_snapshot else "Universal 2H Swords As 1H Complete",
                        f"Wrote universal 2H swords as 1H loose package:\n{result.package_root}",
                    )
                    self.set_status_message(
                        "Wrote universal 2H swords as true 1H package."
                        if include_true_onehand_iteminfo_snapshot
                        else "Wrote universal 2H swords as 1H package."
                    )
                    dialog.accept()
                else:
                    self.set_status_message(
                        "Universal 2H swords as 1H export finished with an unexpected result payload.",
                        error=True,
                    )

            self._run_utility_task(
                status_message=(
                    "Building universal 2H swords as true 1H package..."
                    if include_true_onehand_iteminfo
                    else "Building universal 2H swords as 1H package..."
                ),
                task=_task,
                on_complete=_handle_complete,
                show_archive_progress=True,
            )

        def _build_donor_placement_package() -> None:
            visual_rows = _visual_patch_preview_rows()
            effective_package_plan_rows = _effective_package_plan_rows()
            patch_scope_blocked = _placement_part_in_out_patch_blocking_reason(_visual_part_in_out_preview_patch())
            if patch_scope_blocked:
                QMessageBox.warning(dialog, "Build Placement Package", patch_scope_blocked)
                return
            behavior_blocked = _placement_behavior_patch_blocking_reason()
            if behavior_blocked:
                QMessageBox.warning(dialog, "Build Placement Package", behavior_blocked)
                return
            if not effective_package_plan_rows and not visual_rows:
                QMessageBox.warning(
                    dialog,
                    "Build Placement Package",
                    "Nothing to build yet. Choose a 1H/2H source weapon or a manual body location first.",
                )
                return
            custom_icon_spec = None
            if custom_icon_checkbox.isChecked():
                custom_icon_spec = _placement_custom_icon_override_spec(show_messages=True)
                if custom_icon_spec is None:
                    return
            preview_lines = []
            for row in effective_package_plan_rows[:8]:
                donor = row.get("donor_entry")
                target = row.get("target_entry")
                if isinstance(donor, ArchiveEntry) and isinstance(target, ArchiveEntry):
                    preview_lines.append(f"- {donor.basename} -> {target.path}")
            if len(effective_package_plan_rows) > 8:
                preview_lines.append(f"- ...and {len(effective_package_plan_rows) - 8} more file(s)")
            loose_specs = _target_loose_specs()
            if loose_specs:
                preview_lines.append(f"- preserve {len(loose_specs):,} existing target loose file(s)")
            if custom_icon_spec is not None:
                preview_lines.append(f"- custom icon {custom_icon_spec.source_path.name} -> {custom_icon_spec.target_path}")
            for action, target_path, _note in visual_rows:
                preview_lines.append(f"- {action} -> {target_path}")
            question = (
                "Write a mod-ready loose package using this placement plan?\n\n"
                f"Target that changes: {target_entry.path}\n"
                f"Placement source: {donor_entry.path if isinstance(donor_entry, ArchiveEntry) else 'none'}\n\n"
                + "\n".join(preview_lines)
                + "\n\nNo original archives will be modified."
            )
            answer = QMessageBox.question(
                dialog,
                "Build Placement Package",
                question,
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if answer != QMessageBox.Yes:
                return
            target_settings = self._collect_archive_mod_ready_export_target(
                browse_title="Choose Placement Package Export Root",
                prompt_for_metadata=True,
                dialog_title="Build Placement Package",
                allow_dmm_texture_structure=False,
            )
            if target_settings is None:
                return
            export_root, package_info, create_no_encrypt_file, _include_related, export_options = target_settings
            plan_snapshot = tuple(dict(row) for row in effective_package_plan_rows)
            diagnostics = [
                f"Target: {target_entry.path}",
                f"Placement source: {donor_entry.path if isinstance(donor_entry, ArchiveEntry) else 'none'}",
                f"Placement state: {_visual_selected_placement_state()}",
                f"Swap type: {_visual_selected_swap_type()}",
                (
                    "Legacy raw prefab copy enabled."
                    if legacy_raw_prefab_checkbox.isChecked()
                    else "Target-only mode: source model/material/textures/icon/prefab bytes are not copied."
                ),
                (
                    "Experimental length-changing prefab role/socket patch enabled."
                    if experimental_prefab_resize_checkbox.isChecked()
                    else "Length-changing prefab role/socket patch blocked by default."
                ),
                (
                    "Replacement-only source HKX/physics copied to target path."
                    if legacy_hkx_checkbox.isChecked()
                    else "Source HKX/physics not copied by default."
                ),
                (
                    f"Existing target loose files preserved from {_selected_target_loose_root()}."
                    if loose_specs
                    else "No existing target loose package detected; vanilla target files remain in game."
                ),
                *tuple(package_plan_warnings[:8]),
            ]
            for row in plan_snapshot:
                action = str(row.get("action") or "")
                if "experimental" in action.casefold():
                    donor = row.get("donor_entry")
                    target = row.get("target_entry")
                    if isinstance(donor, ArchiveEntry) and isinstance(target, ArchiveEntry):
                        diagnostics.append(f"{action}: {donor.path} -> {target.path}")
            if custom_icon_spec is not None:
                diagnostics.append(f"Custom item icon: {custom_icon_spec.source_path} -> {custom_icon_spec.target_path}")
            for action, target_path, note in _visual_patch_preview_rows():
                diagnostics.append(f"{action}: {target_path}; {note}")
            package_info = self._placement_swap_package_info_with_diagnostics(package_info, diagnostics)
            loose_specs_snapshot = tuple(loose_specs)

            def _task(log: Callable[[str], None]) -> ArchiveLooseExportResult:
                requests_by_path: Dict[str, ArchivePatchRequest] = {}
                seen_request_paths: set[str] = set()
                alias_specs: List[MeshImportSupplementalFileSpec] = []
                behavior_entry, behavior_header_entry, behavior_patch, behavior_note = _visual_iteminfo_behavior_patch()
                if _visual_selected_swap_type() == "full_behavior":
                    if isinstance(behavior_patch, AttachmentItemInfoBehaviorPatchResult) and behavior_patch.blocking_reason:
                        raise ValueError(behavior_patch.blocking_reason)
                    if (
                        isinstance(behavior_entry, ArchiveEntry)
                        and isinstance(behavior_header_entry, ArchiveEntry)
                        and isinstance(behavior_patch, AttachmentItemInfoBehaviorPatchResult)
                        and bool(behavior_patch.old_equip_type_name)
                    ):
                        target_key = behavior_entry.path.replace("\\", "/").strip().casefold()
                        header_key = behavior_header_entry.path.replace("\\", "/").strip().casefold()
                        header_payload = _read_placement_base_bytes(behavior_header_entry)
                        if not header_payload:
                            raise ValueError("Could not read iteminfo.pabgh companion for full behavior package.")
                        requests_by_path[target_key] = ArchivePatchRequest(behavior_entry, behavior_patch.data)
                        requests_by_path[header_key] = ArchivePatchRequest(behavior_header_entry, header_payload)
                        seen_request_paths.add(target_key)
                        seen_request_paths.add(header_key)
                        log(
                            (
                                "Patch ItemInfo behavior"
                                if behavior_patch.changed
                                else "Include ItemInfo behavior context"
                            )
                            + f": {behavior_entry.path}; {behavior_note}"
                        )
                        log(f"Include unchanged ItemInfo header companion: {behavior_header_entry.path}")
                        for proof_line in tuple(behavior_patch.proof_lines):
                            log(f"ItemInfo behavior proof: {proof_line}")
                target_pac_xml_entry, pac_xml_patch, pac_xml_note = _visual_target_pac_xml_patch()
                if (
                    isinstance(target_pac_xml_entry, ArchiveEntry)
                    and isinstance(pac_xml_patch, AttachmentStackEquipTypePatchResult)
                    and pac_xml_patch.changed
                ):
                    target_key = target_pac_xml_entry.path.replace("\\", "/").strip().casefold()
                    requests_by_path[target_key] = ArchivePatchRequest(target_pac_xml_entry, _encode_placement_base_text(target_pac_xml_entry, pac_xml_patch.text))
                    seen_request_paths.add(target_key)
                    log(f"Patch target .pac_xml slot metadata: {target_pac_xml_entry.path}; {pac_xml_note}")
                target_prefab_entry, prefab_patch, prefab_note = _visual_target_prefab_patch()
                if isinstance(target_prefab_entry, ArchiveEntry) and isinstance(prefab_patch, PrefabAttachmentProfilePatchResult):
                    target_key = target_prefab_entry.path.replace("\\", "/").strip().casefold()
                    requests_by_path[target_key] = ArchivePatchRequest(target_prefab_entry, prefab_patch.data)
                    seen_request_paths.add(target_key)
                    log(f"Patch target prefab placement: {target_prefab_entry.path}; {prefab_note}")
                    for proof_line in prefab_patch.proof_lines:
                        log(f"Prefab socket proof: {proof_line}")
                for row in plan_snapshot:
                    donor = row.get("donor_entry")
                    target = row.get("target_entry")
                    if not isinstance(donor, ArchiveEntry) or not isinstance(target, ArchiveEntry):
                        continue
                    target_key = target.path.replace("\\", "/").strip().casefold()
                    action = str(row.get("action") or "Copy source bytes")
                    same_entry = self._same_archive_entry(donor, target)
                    explicit_source_icon = (
                        use_source_icon_checkbox.isChecked()
                        and "icon" in action.casefold()
                        and "explicit" in action.casefold()
                    )
                    if not (legacy_raw_prefab_checkbox.isChecked() or same_entry or explicit_source_icon):
                        log(f"Blocked donor file row outside explicit advanced mode: {action}: {donor.path} -> {target.path}")
                        continue
                    if target_key in seen_request_paths:
                        continue
                    seen_request_paths.add(target_key)
                    payload_data = _read_archive_bytes(donor)
                    if not payload_data:
                        raise ValueError(f"Could not read placement source payload: {donor.path}")
                    log(f"{action}: {donor.path} -> {target.path}")
                    requests_by_path[target_key] = ArchivePatchRequest(target, payload_data)
                part_patch_for_socket: Optional[AttachmentPartInOutPatchResult] = None
                if patch_part_in_out_checkbox.isChecked() and isinstance(part_in_out_entry, ArchiveEntry):
                    base_text = _read_placement_base_text(part_in_out_entry)
                    part_patch_for_socket = _visual_part_in_out_patch(base_text)
                    if isinstance(part_patch_for_socket, AttachmentPartInOutPatchResult) and part_patch_for_socket.diffs:
                        target_key = part_in_out_entry.path.replace("\\", "/").strip().casefold()
                        requests_by_path[target_key] = ArchivePatchRequest(part_in_out_entry, _encode_placement_base_text(part_in_out_entry, part_patch_for_socket.text))
                        alias_specs.extend(
                            _placement_global_xml_alias_specs(
                                part_in_out_entry,
                                part_patch_for_socket.text,
                                ("character/phm_description_player_kliff.xml",),
                                kind="placement_descriptor_alias",
                            )
                        )
                        for diff in tuple(part_patch_for_socket.diffs[:20]):
                            log(
                                "Patch PartInOut placement XML: "
                                f"{diff.part_name} {diff.field_name}: {diff.old_value or '-'} -> {diff.new_value or '-'}"
                            )
                    else:
                        log("Patch PartInOut placement XML: no selected-class descriptor changes were produced.")
                if patch_socket_checkbox.isChecked() and isinstance(character_socket_entry, ArchiveEntry):
                    base_text = _read_archive_text(character_socket_entry)
                    socket_patch = _visual_socket_patch(base_text, part_patch_for_socket)
                    if isinstance(socket_patch, AttachmentPartInOutPatchResult) and socket_patch.diffs:
                        target_key = character_socket_entry.path.replace("\\", "/").strip().casefold()
                        requests_by_path[target_key] = ArchivePatchRequest(character_socket_entry, _encode_placement_base_text(character_socket_entry, socket_patch.text))
                        alias_specs.extend(
                            _placement_global_xml_alias_specs(
                                character_socket_entry,
                                socket_patch.text,
                                ("character/phm_01.pab.sockets.xml",),
                                kind="placement_socket_alias",
                            )
                        )
                        for diff in tuple(socket_patch.diffs[:20]):
                            log(
                                "Patch character socket XML: "
                                f"{diff.part_name} {diff.field_name}: {diff.old_value or '-'} -> {diff.new_value or '-'}"
                            )
                    else:
                        log("Patch character socket XML: no selected socket transform changes were produced.")
                if custom_icon_spec is not None:
                    generated_icon_spec = self._build_custom_item_icon_supplemental_spec(
                        custom_icon_spec,
                        on_log=log,
                    )
                    target_icon_entry = generated_icon_spec.target_entry
                    if not isinstance(target_icon_entry, ArchiveEntry):
                        raise ValueError("Custom item icon target was not a resolved archive entry.")
                    target_key = target_icon_entry.path.replace("\\", "/").strip().casefold()
                    log(f"Custom item icon: {generated_icon_spec.source_path} -> {generated_icon_spec.target_path}")
                    requests_by_path[target_key] = ArchivePatchRequest(target_icon_entry, generated_icon_spec.payload_data)
                requests = list(requests_by_path.values())
                if not requests:
                    raise ValueError("No placement source package payloads could be read.")
                return export_archive_payloads_to_mod_ready_loose(
                    requests,
                    parent_root=export_root,
                    package_info=package_info,
                    export_options=export_options,
                    create_no_encrypt_file=create_no_encrypt_file,
                    extra_payloads_to_include=tuple(loose_specs_snapshot) + tuple(alias_specs),
                    on_log=log,
                )

            def _handle_complete(result: object) -> None:
                if isinstance(result, ArchiveLooseExportResult):
                    QMessageBox.information(
                        dialog,
                        "Placement Package Complete",
                        f"Wrote placement loose package:\n{result.package_root}",
                    )
                    self.set_status_message(f"Wrote placement package for {target_entry.basename}.")
                    dialog.accept()
                else:
                    self.set_status_message("Placement package export finished with an unexpected result payload.", error=True)

            self._run_utility_task(
                status_message=f"Building placement package for {target_entry.basename}...",
                task=_task,
                on_complete=_handle_complete,
                show_archive_progress=True,
            )

        custom_icon_checkbox.toggled.connect(lambda _checked=False: _refresh_custom_icon_status())
        custom_icon_override_button.clicked.connect(
            lambda _checked=False: (custom_icon_checkbox.setChecked(True), _refresh_custom_icon_status())
        )
        custom_icon_clear_button.clicked.connect(
            lambda _checked=False: (
                custom_icon_checkbox.setChecked(False),
                custom_icon_source_edit.clear(),
                use_source_icon_checkbox.setChecked(False),
                _refresh_custom_icon_status(),
                _refresh_package_plan(),
            )
        )
        custom_icon_source_edit.textChanged.connect(lambda _text="": _refresh_custom_icon_status())
        custom_icon_target_combo.currentIndexChanged.connect(lambda _index=0: _refresh_custom_icon_status())
        custom_icon_file_button.clicked.connect(lambda _checked=False: _choose_custom_icon_file())
        custom_icon_folder_button.clicked.connect(lambda _checked=False: _choose_custom_icon_folder())
        custom_icon_library_button.clicked.connect(lambda _checked=False: _choose_custom_icon_library_source())
        source_copy_button.clicked.connect(lambda _checked=False: _choose_placement_source_from_workspace())
        advanced_features_toggle.toggled.connect(
            lambda checked=False: (
                advanced_features_widget.setVisible(bool(checked)),
                _refresh_visual_status(),
                _refresh_package_plan(),
            )
        )
        target_loose_combo.currentIndexChanged.connect(
            lambda _index=0: _refresh_package_plan()
        )
        swap_type_combo.currentIndexChanged.connect(lambda _index=0: (_refresh_visual_status(), _refresh_package_plan()))
        _apply_default_swap_type()
        _refresh_custom_icon_status()
        import_profile_button.clicked.connect(lambda _checked=False: _import_visual_profile_xml())
        placement_state_combo.currentIndexChanged.connect(lambda _index=0: (_refresh_visual_status(), _refresh_package_plan()))
        use_profile_transforms_checkbox.toggled.connect(
            lambda checked=False: (
                patch_socket_checkbox.setChecked(bool(checked) and isinstance(character_socket_entry, ArchiveEntry)),
                _refresh_visual_status(),
                _refresh_package_plan(),
            )
        )
        patch_part_in_out_checkbox.toggled.connect(lambda _checked=False: (_refresh_visual_status(), _refresh_package_plan()))
        patch_socket_checkbox.toggled.connect(lambda _checked=False: (_refresh_visual_status(), _refresh_package_plan()))
        attach_point_combo.currentIndexChanged.connect(
            lambda _index=0: (
                patch_part_in_out_checkbox.setChecked(
                    bool(str(imported_profile_state.get("part_in_out_text") or "").strip())
                ),
                _refresh_visual_status(),
                _refresh_package_plan(),
            )
        )
        _refresh_visual_status()
        dialog.finished.connect(lambda _result=0: self._cancel_archive_attachment_placement_prepare())
        legacy_raw_prefab_checkbox.toggled.connect(lambda _checked=False: _refresh_experimental_options())
        legacy_hkx_checkbox.toggled.connect(lambda _checked=False: _refresh_package_plan())
        experimental_prefab_resize_checkbox.toggled.connect(lambda _checked=False: (_refresh_visual_status(), _refresh_package_plan()))
        use_source_icon_checkbox.toggled.connect(lambda _checked=False: _refresh_package_plan())
        _refresh_experimental_options()
        target_socket_button.clicked.connect(
            lambda _checked=False: self._open_archive_socket_xml_editor_dialog(target_socket_entry, owner=dialog)
            if isinstance(target_socket_entry, ArchiveEntry)
            else None
        )
        donor_socket_button.clicked.connect(
            lambda _checked=False: self._open_archive_socket_xml_editor_dialog(donor_socket_entry, owner=dialog)
            if isinstance(donor_socket_entry, ArchiveEntry)
            else None
        )
        universal_twohand_button.clicked.connect(lambda _checked=False: _build_universal_twohand_sword_package())
        universal_twohand_true_button.clicked.connect(
            lambda _checked=False: _build_universal_twohand_sword_package(include_true_onehand_iteminfo=True)
        )
        build_button.clicked.connect(lambda _checked=False: _build_donor_placement_package())
        close_button.clicked.connect(dialog.accept)

        placement_dialog_layout_state = {"mode": ""}

        def _apply_placement_dialog_responsive_layout(*, force_sizes: bool = False) -> None:
            width = max(1, int(dialog.width()))
            height = max(1, int(dialog.height()))
            compact = width < 1040
            mode = "compact" if compact else "wide"
            mode_changed = str(placement_dialog_layout_state.get("mode") or "") != mode
            placement_dialog_layout_state["mode"] = mode
            if compact:
                if main_splitter.orientation() != Qt.Vertical:
                    main_splitter.setOrientation(Qt.Vertical)
                main_splitter.setHandleWidth(8)
                left_column.setMinimumWidth(0)
                right_column.setMinimumWidth(0)
                if force_sizes or mode_changed:
                    main_splitter.setSizes([max(320, int(height * 0.54)), max(260, int(height * 0.38))])
            else:
                if main_splitter.orientation() != Qt.Horizontal:
                    main_splitter.setOrientation(Qt.Horizontal)
                main_splitter.setHandleWidth(10)
                left_column.setMinimumWidth(420)
                right_column.setMinimumWidth(420)
                if force_sizes or mode_changed:
                    left_width = max(460, min(680, int(width * 0.42)))
                    main_splitter.setSizes([left_width, max(420, width - left_width)])

        previous_placement_dialog_resize_event = dialog.resizeEvent

        def _responsive_placement_dialog_resize_event(event: object) -> None:
            previous_placement_dialog_resize_event(event)
            QTimer.singleShot(0, _apply_placement_dialog_responsive_layout)

        dialog.resizeEvent = _responsive_placement_dialog_resize_event  # type: ignore[method-assign]

        def _fit_placement_dialog_to_screen() -> None:
            screen = dialog.screen() or self.screen() or QApplication.primaryScreen()
            if screen is None:
                dialog.resize(1180, 760)
                _apply_placement_dialog_responsive_layout(force_sizes=True)
                return
            available = screen.availableGeometry()
            available_width = max(640, int(available.width()) - 24)
            available_height = max(420, int(available.height()) - 24)
            max_width = min(1500, max(760, int(float(available.width()) * 0.92)), available_width)
            max_height = min(860, max(560, int(float(available.height()) * 0.88)), available_height)
            size_hint = dialog.sizeHint()
            target_width = min(max_width, max(min(1180, max_width), int(size_hint.width())))
            target_height = min(max_height, max(min(720, max_height), int(size_hint.height())))
            dialog.resize(target_width, target_height)
            _apply_placement_dialog_responsive_layout(force_sizes=True)
            frame = dialog.frameGeometry()
            frame.moveCenter(available.center())
            left = max(available.left(), min(frame.left(), available.right() - frame.width() + 1))
            top = max(available.top(), min(frame.top(), available.bottom() - frame.height() + 1))
            dialog.move(left, top)

        dialog.adjustSize()
        _fit_placement_dialog_to_screen()
        QTimer.singleShot(0, _fit_placement_dialog_to_screen)
        dialog.exec()


__all__ = ["ArchiveAttachmentPlacementDiffDialogMixin"]
