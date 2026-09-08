"""Archive mesh import setup and export dialogs."""

from __future__ import annotations

from pathlib import Path, PurePosixPath
from typing import Callable, Optional, Sequence, Tuple

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QComboBox,
    QDialog,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QSizePolicy,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from cdmw.ui.widgets import CollapsibleSection
from cdmw.services.archive_read_service import read_archive_entry_data
from cdmw.domain.archives.mesh_contracts import MeshExportResult
from cdmw.services.archive_workflow_service import export_archive_mesh
from cdmw.services.mesh_workflow_service import export_model_preview_to_obj
from cdmw.domain.mesh.session import MeshImportSetupSelection
from cdmw.domain.mesh.validation import MeshImportModeAvailability, mesh_import_mode_availability
from cdmw.models import ArchiveEntry
from cdmw.services.mesh_workflow_service import ParsedMesh
from cdmw.services.mesh_workflow_service import SCENE_TEXTURE_SOURCE_EXTENSIONS, SceneImportResult
from cdmw.ui.archive_browser.directory_scan_controller import DirectoryScanController
from cdmw.ui.archive_browser.mesh_import_preflight_controller import (
    MeshImportSetupPreflightResult,
    dispatch_mesh_import_setup_preflight,
)
from cdmw.ui.archive_browser.mesh_import_setup_state import (
    mesh_import_continue_button_text as _mesh_import_continue_button_text,
    mesh_import_placement_status_chips as _mesh_import_placement_status_chips,
    mesh_import_setup_control_text as _mesh_import_setup_control_text,
    mesh_import_static_guidance_text as _mesh_import_static_guidance_text,
)
from cdmw.ui.archive_browser.workflow_dependencies import (
    ArchiveWorkflowDependenciesUnavailable,
    archive_workflow_dependency_context,
)

class ArchiveMeshImportExportMixin:
    """Archive mesh import setup and export UI flow."""

    def _prepare_archive_mesh_import_setup_async(
        self,
        entry: ArchiveEntry,
        scene_path: Path,
        *,
        title: str,
        on_complete: Callable[[Optional[MeshImportSetupSelection]], None],
        scene_import_result: Optional[SceneImportResult] = None,
        source_skeleton: object | None = None,
        original_mesh: Optional[ParsedMesh] = None,
        source_label: str = "",
        force_static_replacement: bool = False,
        placement_review_title: str = "",
        placement_context_note: str = "",
        full_import_model_replacement: bool = False,
        materials_and_textures_only: bool = False,
    ) -> int:
        return dispatch_mesh_import_setup_preflight(
            self,
            entry,
            scene_path,
            title=title,
            on_complete=on_complete,
            scene_import_result=scene_import_result,
            source_skeleton=source_skeleton,
            original_mesh=original_mesh,
            source_label=source_label,
            force_static_replacement=force_static_replacement,
            placement_review_title=placement_review_title,
            placement_context_note=placement_context_note,
            full_import_model_replacement=full_import_model_replacement,
            materials_and_textures_only=materials_and_textures_only,
        )

    def _prompt_archive_mesh_import_setup(
        self,
        entry: ArchiveEntry,
        scene_path: Path,
        *,
        title: str,
        prepared_preflight: MeshImportSetupPreflightResult,
        source_skeleton: object | None = None,
        source_label: str = "",
        force_static_replacement: bool = False,
        placement_review_title: str = "",
        placement_context_note: str = "",
        full_import_model_replacement: bool = False,
        materials_and_textures_only: bool = False,
        ) -> Optional[MeshImportSetupSelection]:
        source_display_label = source_label.strip() or str(scene_path)
        scene_import_result = prepared_preflight.scene_import_result
        suffix = scene_path.suffix.lower()
        is_obj = suffix == ".obj" and not force_static_replacement
        has_roundtrip_sidecar = bool(prepared_preflight.has_roundtrip_sidecar) if is_obj else False
        profile = prepared_preflight.profile
        original_mesh_for_setup = prepared_preflight.original_mesh
        preflight, setup_control_text = prepared_preflight.preflight, _mesh_import_setup_control_text()

        dialog = QDialog(self)
        dialog.setObjectName("MeshImportSetupDialog")
        dialog.setWindowTitle(title)
        dialog.setMinimumSize(640, 300)
        root_layout = QVBoxLayout(dialog)
        root_layout.setContentsMargins(12, 10, 12, 10)
        root_layout.setSpacing(8)
        content_scroll = QScrollArea(dialog)
        content_scroll.setWidgetResizable(True)
        content_scroll.setFrameShape(QFrame.NoFrame)
        content_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        content_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        content_scroll.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        content_widget = QWidget(content_scroll)
        layout = QVBoxLayout(content_widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        layout.setAlignment(Qt.AlignTop)
        content_scroll.setWidget(content_widget)
        root_layout.addWidget(content_scroll, 1)

        summary_group = QWidget()
        summary_layout = QVBoxLayout(summary_group)
        summary_layout.setContentsMargins(4, 4, 4, 4)
        summary_layout.setSpacing(12)
        layout.addWidget(summary_group)

        def _chip(text: str, role: str = "info") -> QLabel:
            display_text = str(text or "").strip() or "-"
            chip = QLabel(display_text)
            chip.setObjectName("MetricChip")
            chip.setProperty("chipRole", role)
            chip.setWordWrap(True)
            chip.setTextInteractionFlags(Qt.TextSelectableByMouse)
            return chip

        def _path_value(text: str) -> QLabel:
            label = QLabel(PurePosixPath(text.replace("\\", "/")).name)
            label.setObjectName("CompactPathValue")
            label.setToolTip(text)
            label.setTextInteractionFlags(Qt.TextSelectableByMouse)
            label.setWordWrap(True)
            return label

        def _row_label(text: str) -> QLabel:
            label = QLabel(text)
            label.setObjectName("HintLabel")
            label.setMinimumWidth(82)
            return label

        source_group = QWidget()
        source_layout = QGridLayout(source_group)
        source_layout.setContentsMargins(0, 0, 0, 0)
        source_layout.setHorizontalSpacing(10)
        source_layout.setVerticalSpacing(5)
        source_layout.addWidget(_row_label("Source"), 0, 0)
        source_value_label = _path_value(source_display_label)
        source_layout.addWidget(source_value_label, 0, 1)
        source_layout.addWidget(_row_label("Target"), 1, 0)
        source_layout.addWidget(_path_value(entry.path), 1, 1)
        mesh_format_text = str(getattr(scene_import_result.mesh, "format", "") or "").strip().upper()
        if not mesh_format_text:
            mesh_format_text = scene_path.suffix.lower().lstrip(".").upper()
        mesh_summary = QLabel(
            f"{mesh_format_text} · {len(scene_import_result.mesh.submeshes):,} parts · "
            f"{scene_import_result.mesh.total_faces:,} faces"
        )
        mesh_summary.setObjectName("HintLabel")
        source_layout.addWidget(mesh_summary, 2, 1)
        source_layout.setColumnStretch(1, 1)
        summary_layout.addWidget(source_group)

        details_section = CollapsibleSection("Details", expanded=False)
        details_section.setObjectName("MeshImportDetails")
        details_layout = details_section.body_layout
        external_audit = getattr(scene_import_result, "external_audit", None)
        if external_audit is not None:
            audit_label = _row_label("Asset check")
            audit_label.setToolTip("Best-effort read-only classification of the imported model source.")
            audit_row = QGridLayout()
            audit_row.setSpacing(6)
            audit_row.addWidget(audit_label, 0, 0)
            audit_category = str(getattr(external_audit, "verified_category", "") or "unknown")
            audit_confidence = float(getattr(external_audit, "confidence", 0.0) or 0.0)
            if audit_category == "unknown":
                audit_chip = _chip(f"Unclassified asset ({audit_confidence:.0%} match)", "warn")
                audit_chip.setToolTip(
                    "The optional model audit could not confidently classify this file. "
                    "Geometry can still be routed manually; use the part list, DDS contract, and live preview diagnostics as the source of truth."
                )
            else:
                audit_chip = _chip(f"{audit_category} ({audit_confidence:.0%} match)", "ready")
                audit_chip.setToolTip("Best-effort detected asset category from the optional external model audit.")
            audit_row.addWidget(audit_chip, 0, 1)
            texture_slots = tuple(getattr(external_audit, "texture_slots", ()) or ())
            if texture_slots:
                audit_row.addWidget(_chip("textures: " + ", ".join(str(slot) for slot in texture_slots[:4]), "info"), 1, 1)
            workflows = tuple(getattr(external_audit, "pbr_workflows", ()) or ())
            if workflows:
                audit_row.addWidget(_chip("PBR: " + ", ".join(str(workflow) for workflow in workflows[:2]), "info"), 2, 1)
            if bool(getattr(external_audit, "false_positive", False)) or bool(getattr(external_audit, "mixed_model", False)):
                audit_row.addWidget(_chip("review subparts", "warn"), 3, 1)
            audit_row.setColumnStretch(1, 1)
            details_layout.addLayout(audit_row)

        mode_group = QWidget()
        mode_layout = QVBoxLayout(mode_group)
        mode_layout.setContentsMargins(0, 0, 0, 0)
        mode_layout.setSpacing(5)
        mode_choice_row = QHBoxLayout()
        mode_choice_row.addWidget(_row_label("Mode"))
        roundtrip_radio = QRadioButton("Round-trip edit")
        roundtrip_radio.setToolTip(
            "OBJ-only path for meshes exported by this app. Keeps original mesh structure and uses OBJ sidecar metadata when available."
        )
        static_radio = QRadioButton("Mesh Replacement")
        static_radio.setToolTip(
            "Maps an arbitrary static OBJ/DAE/GLB/glTF scene onto the selected original game mesh and opens Mesh Replacement Alignment."
        )
        mode_choice_row.addWidget(roundtrip_radio)
        mode_choice_row.addWidget(static_radio)
        mode_choice_row.addStretch(1)
        mode_layout.addLayout(mode_choice_row)
        availability = mesh_import_mode_availability(
            scene_path,
            has_roundtrip_sidecar=has_roundtrip_sidecar,
            static_supported=bool(profile is None or profile.export_supported),
        )
        if force_static_replacement:
            availability = MeshImportModeAvailability(
                roundtrip_enabled=False,
                static_enabled=availability.static_enabled,
                default_mode="static_replacement" if availability.static_enabled else "",
                guidance=(
                    "Modify Original clone sources use Mesh Replacement mode so Geometry can resize original parts."
                    if suffix == ".obj"
                    else (
                        "In-game archive mesh sources use Mesh Replacement mode. "
                        "The selected archive mesh is parsed directly and mapped onto this target."
                    )
                ),
            )
        if not availability.roundtrip_enabled:
            roundtrip_radio.setEnabled(False)
            roundtrip_radio.hide()
            roundtrip_radio.setToolTip("Round-trip edit is OBJ-only and requires a local OBJ source.")
        if not availability.static_enabled:
            static_radio.setEnabled(False)
            static_radio.setToolTip("\n".join(profile.errors) or "Mesh replacement is not enabled for this target asset.")
        static_limits_label = QLabel(_mesh_import_static_guidance_text(availability.guidance))
        static_limits_label.setWordWrap(True)
        static_limits_label.setObjectName("HintLabel")
        details_layout.addWidget(static_limits_label)
        if availability.default_mode == "roundtrip":
            roundtrip_radio.setChecked(True)
        elif availability.default_mode == "static_replacement":
            static_radio.setChecked(True)
        summary_layout.addWidget(mode_group)

        material_choice = QWidget()
        material_choice_layout = QHBoxLayout(material_choice)
        material_choice_layout.setContentsMargins(0, 0, 0, 0)
        material_choice_layout.setSpacing(8)
        material_choice_layout.addWidget(_row_label("Materials"))
        material_mode_combo = QComboBox()
        material_mode_combo.setObjectName("MeshImportMaterialMode")
        material_mode_combo.addItem("Keep target materials and textures", False)
        material_mode_combo.addItem("Replace materials and textures too", True)
        material_mode_combo.setToolTip(
            "Keep the game's materials for a geometry-only replacement. To replace materials too, "
            "include the imported model's MTL and textures. You can change this in the builder."
        )
        material_choice_layout.addWidget(material_mode_combo, 1)
        summary_layout.addWidget(material_choice)
        show_material_choice = not (
            force_static_replacement or full_import_model_replacement or materials_and_textures_only
        )

        if placement_context_note.strip():
            placement_group = QWidget()
            placement_layout = QVBoxLayout(placement_group)
            placement_layout.setContentsMargins(0, 0, 0, 0)
            placement_layout.setSpacing(5)
            placement_status_row = QHBoxLayout()
            placement_status_row.setSpacing(6)
            for chip_text, chip_tone in _mesh_import_placement_status_chips():
                placement_status_row.addWidget(_chip(chip_text, chip_tone))
            placement_status_row.addStretch(1)
            placement_layout.addLayout(placement_status_row)
            placement_note_label = QLabel(placement_context_note.strip())
            placement_note_label.setWordWrap(True)
            placement_note_label.setObjectName("HintLabel")
            placement_layout.addWidget(placement_note_label)
            details_layout.addWidget(placement_group)

        diagnostics = list(scene_import_result.diagnostics)
        if profile is not None:
            diagnostics.append(f"Target compatibility: {profile.support_level} ({profile.category_hint}).")
            diagnostics.extend(profile.errors[:3])
            diagnostics.extend(profile.warnings[:3])
        preflight_group = QWidget()
        preflight_layout = QVBoxLayout(preflight_group)
        preflight_layout.setContentsMargins(0, 0, 0, 0)
        preflight_layout.setSpacing(5)
        preflight_tree = QTreeWidget()
        preflight_tree.setColumnCount(2)
        preflight_tree.setHeaderLabels(["Check", "Value"])
        preflight_tree.setRootIsDecorated(False)
        preflight_tree.setAlternatingRowColors(True)
        preflight_tree.setSelectionMode(QAbstractItemView.NoSelection)
        preflight_tree.setMinimumHeight(112)
        preflight_tree.setMaximumHeight(128)
        preflight_tree.header().setStretchLastSection(True)
        preflight_tree.header().resizeSection(0, 180)
        detail_lines = dict.fromkeys((*preflight.detail_lines, *diagnostics))
        for line in detail_lines:
            line_text = str(line)
            if ":" in line_text:
                key, value = line_text.split(":", 1)
                item = QTreeWidgetItem([key.strip(), value.strip()])
            else:
                item = QTreeWidgetItem(["Info", line_text])
            lower_line = line_text.lower()
            if "large" in lower_line or "slow" in lower_line or "warning" in lower_line:
                item.setBackground(0, QBrush(QColor("#48facc15")))
                item.setBackground(1, QBrush(QColor("#48facc15")))
            elif "target" in lower_line or "source" in lower_line:
                item.setBackground(1, QBrush(QColor("#48bfdbfe")))
            preflight_tree.addTopLevelItem(item)
        preflight_layout.addWidget(preflight_tree)
        details_layout.addWidget(preflight_group)

        files_section = CollapsibleSection("Files", expanded=False)
        files_section.setObjectName("MeshImportFiles")
        supplemental_layout = files_section.body_layout
        supplemental_list = QListWidget()
        supplemental_list.setToolTip("Checked files are included with the import. Add local DDS/images or material sidecars only when needed.")
        supplemental_list.setMinimumHeight(76)
        supplemental_list.setMaximumHeight(112)
        supplemental_list.setSelectionMode(QAbstractItemView.ExtendedSelection)
        supplemental_warning_label = QLabel("")
        supplemental_warning_label.setObjectName("WarningLabel")
        supplemental_warning_label.setWordWrap(True)
        supplemental_warning_label.setVisible(False)
        supported_suffixes = set(SCENE_TEXTURE_SOURCE_EXTENSIONS) | {
            ".xml", ".pami", ".pac_xml", ".pam_xml", ".pamlod_xml", ".app_xml", ".prefabdata_xml"}
        seen_paths: set[str] = set()
        folder_scan_state = {"blocked": False}

        def _add_supplemental_path(path: Path, *, checked: bool = True, verified: bool = False) -> None:
            try:
                resolved = Path(path) if verified else path.expanduser().resolve()
            except Exception:
                return
            if (not verified and not resolved.is_file()) or resolved.suffix.lower() not in supported_suffixes:
                return
            key = str(resolved).lower()
            if key in seen_paths:
                return
            seen_paths.add(key)
            item = QListWidgetItem(resolved.name)
            item.setToolTip(str(resolved))
            item.setData(Qt.UserRole, str(resolved))
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Checked if checked else Qt.Unchecked)
            supplemental_list.addItem(item)

        def _refresh_supplemental_warning() -> None:
            checked_count = sum(
                supplemental_list.item(index).checkState() == Qt.Checked
                for index in range(supplemental_list.count())
            )
            files_section.toggle_button.setText(f"Files ({checked_count} included)")
            if folder_scan_state["blocked"]:
                return
            if roundtrip_radio.isChecked() or not (material_mode_combo.currentData() or full_import_model_replacement or materials_and_textures_only):
                supplemental_warning_label.clear()
                supplemental_warning_label.hide()
                return
            texture_count = 0
            checked_texture_count = 0
            for index in range(supplemental_list.count()):
                item = supplemental_list.item(index)
                if item is None:
                    continue
                raw_path = str(item.data(Qt.UserRole) or "")
                if Path(raw_path).suffix.lower() not in SCENE_TEXTURE_SOURCE_EXTENSIONS:
                    continue
                texture_count += 1
                if item.checkState() == Qt.Checked:
                    checked_texture_count += 1
            if texture_count <= 0:
                supplemental_warning_label.setText(
                    "No source textures found. Check the source materials in the builder."
                )
                supplemental_warning_label.setVisible(True)
                return
            if checked_texture_count <= 0:
                supplemental_warning_label.setText(
                    "Textures are available but none are included."
                )
                supplemental_warning_label.setVisible(True)
                return
            supplemental_warning_label.clear()
            supplemental_warning_label.setVisible(False)

        auto_paths = (
            tuple(scene_import_result.discovered_texture_files)
            + tuple(scene_import_result.extracted_embedded_files)
            + tuple(getattr(scene_import_result, "discovered_supplemental_files", ()) or ())
        )
        for auto_path in auto_paths:
            _add_supplemental_path(auto_path, checked=True)

        supplemental_layout.addWidget(supplemental_list)
        supplemental_buttons = QHBoxLayout()
        add_files_button = QPushButton("Add Files")
        add_folder_button = QPushButton("Add Folder")
        clear_button = QPushButton("Clear")
        folder_scan = DirectoryScanController(thread_parent=self, parent=dialog)
        supplemental_buttons.addWidget(add_files_button)
        supplemental_buttons.addWidget(add_folder_button)
        supplemental_buttons.addStretch(1)
        supplemental_buttons.addWidget(clear_button)
        supplemental_layout.addLayout(supplemental_buttons)
        layout.addWidget(files_section)
        layout.addWidget(details_section)
        layout.addWidget(supplemental_warning_label)
        if not (availability.roundtrip_enabled or availability.static_enabled):
            blocker = QLabel("\n".join(profile.errors) if profile is not None and profile.errors else "Mesh replacement is not enabled for this target asset.")
            blocker.setObjectName("WarningLabel")
            blocker.setWordWrap(True)
            layout.addWidget(blocker)

        def _add_files() -> None:
            selected_files, _selected_filter = QFileDialog.getOpenFileNames(
                dialog,
                "Add Supplemental Files",
                str(scene_path.parent),
                "Supplemental Files (*.png *.jpg *.jpeg *.dds *.xml *.pami *.pac_xml *.pam_xml *.pamlod_xml *.app_xml *.prefabdata_xml);;Texture Sources (*.png *.jpg *.jpeg *.dds);;DDS Files (*.dds);;Material Sidecars (*.xml *.pami *.pac_xml *.pam_xml *.pamlod_xml *.app_xml *.prefabdata_xml)",
            )
            for raw_path in selected_files:
                if raw_path:
                    _add_supplemental_path(Path(raw_path), checked=True)
            _refresh_supplemental_warning()

        def _add_folder() -> None:
            selected_dir = QFileDialog.getExistingDirectory(dialog, "Add Supplemental Folder", str(scene_path.parent))
            if not selected_dir:
                return
            folder_scan.start(Path(selected_dir), suffixes=tuple(supported_suffixes))

        def _add_folder_batch(_request_id: int, paths: object) -> None:
            previous = supplemental_list.blockSignals(True)
            try:
                for candidate in paths if isinstance(paths, tuple) else ():
                    _add_supplemental_path(candidate, checked=True, verified=True)
            finally:
                supplemental_list.blockSignals(previous)

        def _finish_folder_scan(_request_id: int, truncated: bool) -> None:
            folder_scan_state["blocked"] = bool(truncated)
            _refresh_supplemental_warning()
            if truncated:
                supplemental_warning_label.setText("Folder scan reached its 10,000-file safety limit; narrow the selected folder.")
                supplemental_warning_label.setVisible(True)
            _refresh_continue_state()

        def _fail_folder_scan(_request_id: int, message: str) -> None:
            folder_scan_state["blocked"] = True
            supplemental_warning_label.setText(f"Could not scan supplemental folder: {message}")
            supplemental_warning_label.setVisible(True)
            _refresh_continue_state()

        def _clear_supplemental() -> None:
            folder_scan.cancel()
            folder_scan_state["blocked"] = False
            supplemental_list.clear()
            seen_paths.clear()
            _refresh_supplemental_warning()
            _refresh_continue_state()

        add_files_button.clicked.connect(_add_files)
        add_folder_button.clicked.connect(_add_folder)
        folder_scan.batch_ready.connect(_add_folder_batch)
        folder_scan.completed.connect(_finish_folder_scan)
        folder_scan.error.connect(_fail_folder_scan)
        clear_button.clicked.connect(_clear_supplemental)
        supplemental_list.itemChanged.connect(lambda _item: _refresh_supplemental_warning())
        material_mode_combo.currentIndexChanged.connect(lambda _index: _refresh_supplemental_warning())
        _refresh_supplemental_warning()

        button_row = QHBoxLayout()
        button_row.addStretch(1)
        cancel_button = QPushButton(setup_control_text["cancel_button"])
        continue_button = QPushButton(
            _mesh_import_continue_button_text(placement_context_note=placement_context_note)
        )
        continue_button.setDefault(True)
        button_row.addWidget(cancel_button)
        button_row.addWidget(continue_button)
        root_layout.addLayout(button_row)

        def _refresh_continue_state() -> None:
            material_choice.setVisible(show_material_choice and static_radio.isChecked())
            _refresh_supplemental_warning()
            continue_button.setEnabled(
                not folder_scan.is_running()
                and not folder_scan_state["blocked"]
                and (
                    (roundtrip_radio.isEnabled() and roundtrip_radio.isChecked())
                    or (static_radio.isEnabled() and static_radio.isChecked())
                )
            )

        roundtrip_radio.toggled.connect(_refresh_continue_state)
        static_radio.toggled.connect(_refresh_continue_state)
        folder_scan.busy_changed.connect(
            lambda busy: (add_folder_button.setEnabled(not busy), _refresh_continue_state())
        )
        dialog.finished.connect(lambda _result=0: folder_scan.close())
        cancel_button.clicked.connect(dialog.reject)
        continue_button.clicked.connect(dialog.accept)
        _refresh_continue_state()

        def _fit_mesh_import_setup_dialog_to_screen() -> None:
            screen = dialog.screen() or self.screen() or QApplication.primaryScreen()
            if screen is None:
                dialog.resize(680, 360)
                return
            available = screen.availableGeometry()
            max_width = min(900, max(640, int(float(available.width()) * 0.92)))
            max_height = min(720, max(300, int(float(available.height()) * 0.86)))
            dialog.setMaximumSize(max_width, max_height)
            layout.activate()
            margins = root_layout.contentsMargins()
            content_height = layout.sizeHint().height() + button_row.sizeHint().height()
            content_height += margins.top() + margins.bottom() + root_layout.spacing() + 6
            target_width = min(max_width, max(640, dialog.width()))
            target_height = min(max_height, max(300, content_height))
            dialog.resize(target_width, target_height)
            frame = dialog.frameGeometry()
            frame.moveCenter(available.center())
            left = max(available.left(), min(frame.left(), available.right() - frame.width() + 1))
            top = max(available.top(), min(frame.top(), available.bottom() - frame.height() + 1))
            dialog.move(left, top)

        files_section.toggled.connect(lambda _expanded: QTimer.singleShot(0, _fit_mesh_import_setup_dialog_to_screen))
        details_section.toggled.connect(lambda _expanded: QTimer.singleShot(0, _fit_mesh_import_setup_dialog_to_screen))
        dialog.resize(680, 360)
        _fit_mesh_import_setup_dialog_to_screen()
        QTimer.singleShot(0, _fit_mesh_import_setup_dialog_to_screen)

        if dialog.exec() != QDialog.Accepted:
            return None
        import_mode = "roundtrip" if roundtrip_radio.isChecked() else "static_replacement"
        if import_mode == "static_replacement" and not static_radio.isEnabled():
            return None
        checked_items = (supplemental_list.item(index) for index in range(supplemental_list.count()))
        supplemental_files: list[Path] = [
            Path(str(item.data(Qt.UserRole) or ""))
            for item in checked_items
            if item is not None and item.checkState() == Qt.Checked and str(item.data(Qt.UserRole) or "")
        ]
        preferred_complete_source_swap = None
        if full_import_model_replacement or materials_and_textures_only:
            preferred_complete_source_swap = True
        elif show_material_choice and import_mode == "static_replacement":
            preferred_complete_source_swap = bool(material_mode_combo.currentData())
        return MeshImportSetupSelection(
            scene_path=scene_path,
            import_mode=import_mode,
            supplemental_files=tuple(supplemental_files),
            scene_import_result=scene_import_result,
            source_skeleton=source_skeleton,
            preferred_complete_source_swap=preferred_complete_source_swap,
            original_mesh=original_mesh_for_setup,
            preflight=preflight,
            source_label=source_display_label,
            placement_review_title=placement_review_title,
            placement_context_note=placement_context_note.strip(),
            full_import_model_replacement=bool(full_import_model_replacement),
            materials_and_textures_only=bool(materials_and_textures_only),
        )

    def _start_archive_mesh_export(self, entry: ArchiveEntry, export_format: str) -> None:
        try:
            dependencies = archive_workflow_dependency_context(self, entry)
        except ArchiveWorkflowDependenciesUnavailable as exc:
            self.shell.set_status_message(f"Mesh export is unavailable: {exc}", error=True)
            return
        entry = dependencies.selected_entry
        default_dir = self.shell.settings_file_path.parent / "mesh_export"
        output_dir = QFileDialog.getExistingDirectory(
            self,
            f"Export {export_format.upper()}",
            str(default_dir),
        )
        if not output_dir:
            return

        selected_related_entries: Tuple[ArchiveEntry, ...] = ()
        normalized_export_format = export_format.strip().lower()
        if normalized_export_format in {"obj", "fbx"}:
            selected_related_entries_result = self._prompt_archive_mesh_related_file_selection(
                entry,
                title=f"Export Referenced Files With {normalized_export_format.upper()}",
                intro_text=(
                    "Select which resolved referenced files should be copied alongside the mesh export. "
                    "The selected files will be written into a referenced_files/ folder inside the chosen export directory."
                ),
                confirm_button_text=f"Export {normalized_export_format.upper()}",
            )
            if selected_related_entries_result is None:
                return
            selected_related_entries = selected_related_entries_result

        def _launch_export(*, allow_missing_skeleton: bool = False) -> None:
            def _task(log: Callable[[str], None]) -> MeshExportResult:
                return export_archive_mesh(
                    entry,
                    Path(output_dir),
                    export_format,
                    archive_entries_by_normalized_path=dependencies.entries_by_normalized_path,
                    archive_entries_by_basename=dependencies.entries_by_basename,
                    related_entries=selected_related_entries,
                    allow_missing_skeleton=allow_missing_skeleton,
                    on_log=log,
                )

            def _handle_complete(result: object) -> None:
                if not isinstance(result, MeshExportResult):
                    self.shell.set_status_message("Mesh export finished with an unexpected result payload.", error=True)
                    return
                if result.requires_confirmation:
                    confirmation = QMessageBox.question(
                        self,
                        result.confirmation_title or "Export FBX Without Skeleton?",
                        result.confirmation_message or (
                            "No usable skeleton could be resolved. Continue with a mesh-only FBX export?"
                        ),
                        QMessageBox.Yes | QMessageBox.No,
                        QMessageBox.No,
                    )
                    if confirmation == QMessageBox.Yes:
                        QTimer.singleShot(0, lambda: _launch_export(allow_missing_skeleton=True))
                    else:
                        self.shell.set_status_message(f"Cancelled {export_format.upper()} export for {entry.basename}.")
                    return

                displayed_paths = [str(path) for path in result.output_paths[:15]]
                if len(result.output_paths) > 15:
                    displayed_paths.append(f"... {len(result.output_paths) - 15} more file(s)")
                exported_files = "\n".join(displayed_paths)
                summary_text = "\n".join(result.summary_lines)
                QMessageBox.information(
                    self,
                    "Mesh Export Complete",
                    f"{summary_text}\n\nExported files:\n{exported_files}",
                )
                self.shell.set_status_message(f"Exported {entry.basename} as {export_format.upper()}.")

            self.shell._run_utility_task(
                status_message=f"Exporting {entry.basename} as {export_format.upper()}...",
                task=_task,
                on_complete=_handle_complete,
                show_archive_progress=True,
            )

        _launch_export()

    def _export_current_archive_model(self) -> None:
        result = self.current_archive_preview_result
        preview_model = result.preview_model if result is not None else None
        if preview_model is None or self.archive_preview_showing_loose:
            self.shell.set_status_message("No model preview is available to export.", error=True)
            return

        current_entry = self._current_archive_mesh_entry()
        if current_entry is not None:
            self._start_archive_mesh_export(current_entry, "obj")
            return

        preview_path = str(getattr(preview_model, "path", "") or "").strip()
        if preview_path:
            default_stem = Path(PurePosixPath(preview_path).name).stem
        else:
            default_stem = Path(current_entry.basename).stem if current_entry is not None else "archive_model"

        default_dir = self.shell.settings_file_path.parent / "model_export"
        default_target = default_dir / f"{default_stem}.obj"
        selected, _ = QFileDialog.getSaveFileName(
            self,
            "Export Model Preview",
            str(default_target),
            "Wavefront OBJ (*.obj)",
        )
        if not selected:
            return

        try:
            exported_path = export_model_preview_to_obj(preview_model, Path(selected))
        except Exception as exc:
            QMessageBox.warning(self, "Model Export", str(exc))
            self.shell.set_status_message(f"Model export failed: {exc}", error=True)
            return

        self.shell.set_status_message(f"Exported model preview to {exported_path}")

__all__ = ["ArchiveMeshImportExportMixin"]
