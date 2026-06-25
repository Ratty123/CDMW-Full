"""Archive mesh import setup and export dialogs."""

from __future__ import annotations

from pathlib import Path, PurePosixPath
from typing import Callable, Optional, Sequence, Tuple

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QDialog,
    QFileDialog,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QProgressDialog,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QSizePolicy,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from cdmw.core.archive import read_archive_entry_data
from cdmw.core.archive_modding import MeshExportResult, export_archive_mesh
from cdmw.core.model_export import export_model_preview_to_obj
from cdmw.core.mesh_baseline import read_archive_entry_baseline_data
from cdmw.core.mesh_preflight import build_mesh_import_preflight
from cdmw.domain.mesh.session import MeshImportSetupSelection
from cdmw.domain.mesh.validation import MeshImportModeAvailability, mesh_import_mode_availability
from cdmw.models import ArchiveEntry
from cdmw.modding.asset_replacement import ReplacementAssetProfile, analyze_replacement_asset
from cdmw.modding.mesh_parser import ParsedMesh, parse_mesh
from cdmw.modding.scene_importer import SCENE_TEXTURE_SOURCE_EXTENSIONS, import_scene_mesh_with_report
from cdmw.ui.archive_browser.mesh_import_setup_state import (
    mesh_import_continue_button_text as _mesh_import_continue_button_text,
    mesh_import_placement_status_chips as _mesh_import_placement_status_chips,
    mesh_import_replacement_status_chip as _mesh_import_replacement_status_chip,
    mesh_import_setup_control_text as _mesh_import_setup_control_text,
    mesh_import_static_guidance_text as _mesh_import_static_guidance_text,
)


class ArchiveMeshImportExportMixin:
    """Archive mesh import setup and export UI flow."""
    def _prompt_archive_mesh_import_setup(
        self,
        entry: ArchiveEntry,
        scene_path: Path,
        *,
        title: str,
        scene_import_result: Optional[SceneImportResult] = None,
        original_mesh: Optional[ParsedMesh] = None,
        source_label: str = "",
        force_static_replacement: bool = False,
        placement_review_title: str = "",
        placement_context_note: str = "",
        full_import_model_replacement: bool = False,
        ) -> Optional[MeshImportSetupSelection]:
        setup_control_text = _mesh_import_setup_control_text()
        source_display_label = source_label.strip() or str(scene_path)
        startup_progress = QProgressDialog(setup_control_text["startup_label"], "", 0, 0, self)
        startup_progress.setWindowTitle(setup_control_text["startup_title"])
        startup_progress.setCancelButton(None)
        startup_progress.setMinimumDuration(0)
        startup_progress.setAutoClose(False)
        # Keep the main window paintable while the alignment shell is being
        # assembled. Some imports still need real work before the dialog can
        # exec(), but the progress window must not make the app look hung.
        startup_progress.setWindowModality(Qt.NonModal)
        startup_progress.show()
        QApplication.processEvents()
        if scene_import_result is None:
            try:
                startup_progress.setLabelText(setup_control_text["reading_replacement_scene"])
                QApplication.processEvents()
                scene_import_result = import_scene_mesh_with_report(scene_path)
            except Exception as exc:
                startup_progress.close()
                QApplication.processEvents()
                QMessageBox.warning(
                    self,
                    setup_control_text["unsupported_title"],
                    f"{scene_path.name} could not be imported.\n\n{exc}",
                )
                return None

        suffix = scene_path.suffix.lower()
        is_obj = suffix == ".obj" and not force_static_replacement
        has_roundtrip_sidecar = self._has_valid_obj_roundtrip_sidecar(scene_path) if is_obj else False
        profile: Optional[ReplacementAssetProfile] = None
        original_mesh_for_setup: Optional[ParsedMesh] = original_mesh
        try:
            if original_mesh_for_setup is None:
                startup_progress.setLabelText(setup_control_text["reading_original_mesh"])
                QApplication.processEvents()
                original_data = read_archive_entry_baseline_data(entry, read_entry_data=read_archive_entry_data).data
                original_mesh_for_setup = parse_mesh(original_data, entry.path)
            startup_progress.setLabelText(setup_control_text["checking_asset_compatibility"])
            QApplication.processEvents()
            profile = analyze_replacement_asset(
                entry,
                archive_entries_by_basename=self.archive_entries_by_basename,
                parsed_mesh=original_mesh_for_setup,
            )
        except Exception:
            profile = None
            original_mesh_for_setup = None
        preflight = build_mesh_import_preflight(
            entry,
            scene_path,
            replacement_mesh=scene_import_result.mesh,
            original_mesh=original_mesh_for_setup,
            import_diagnostics=scene_import_result.diagnostics,
        )
        startup_progress.setLabelText(preflight.summary)
        QApplication.processEvents()
        startup_progress.close()
        QApplication.processEvents()

        dialog = QDialog(self)
        dialog.setObjectName("MeshImportSetupDialog")
        dialog.setWindowTitle(title)
        dialog.setMinimumSize(760, 460)
        dialog.setStyleSheet(
            """
            QDialog#MeshImportSetupDialog QLabel#HintLabel {
                color: #a7b0bd;
            }
            QDialog#MeshImportSetupDialog QLabel#WarningLabel {
                color: #facc15;
            }
            QDialog#MeshImportSetupDialog QLabel#CompactPathValue {
                color: #dbeafe;
                font-family: Consolas, "Cascadia Mono", monospace;
            }
            QDialog#MeshImportSetupDialog QLabel#MetricChip {
                border-radius: 4px;
                padding: 3px 8px;
                font-weight: 600;
            }
            QDialog#MeshImportSetupDialog QLabel#MetricChip[chipRole="format"] {
                background: #164e63;
                color: #a5f3fc;
            }
            QDialog#MeshImportSetupDialog QLabel#MetricChip[chipRole="ready"] {
                background: #14532d;
                color: #bbf7d0;
            }
            QDialog#MeshImportSetupDialog QLabel#MetricChip[chipRole="warn"] {
                background: #713f12;
                color: #fde68a;
            }
            QDialog#MeshImportSetupDialog QLabel#MetricChip[chipRole="info"] {
                background: #1e3a8a;
                color: #bfdbfe;
            }
            QDialog#MeshImportSetupDialog QGroupBox {
                margin-top: 10px;
                padding: 8px;
            }
            QDialog#MeshImportSetupDialog QGroupBox::title {
                left: 10px;
                padding: 0 4px;
                color: #e5e7eb;
                font-weight: 700;
            }
            QDialog#MeshImportSetupDialog QTreeWidget,
            QDialog#MeshImportSetupDialog QListWidget {
                alternate-background-color: #24272d;
            }
            """
        )
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
        content_scroll.setWidget(content_widget)
        root_layout.addWidget(content_scroll, 1)

        intro_text = (
            "Review the archive source, then continue to placement and Mesh Replacement Alignment."
            if force_static_replacement
            else "Review the import source, pick import mode, then continue to Mesh Replacement Alignment."
        )
        intro = QLabel(intro_text)
        intro.setWordWrap(True)
        intro.setObjectName("HintLabel")
        layout.addWidget(intro)

        summary_group = QGroupBox("Import Summary")
        summary_layout = QVBoxLayout(summary_group)
        summary_layout.setContentsMargins(10, 8, 10, 8)
        summary_layout.setSpacing(7)
        layout.addWidget(summary_group)

        def _compact_path(raw_path: str, *, keep: int = 86) -> str:
            text = str(raw_path or "").replace("\\", "/").strip()
            if len(text) <= keep:
                return text
            tail = text[-max(16, keep - 3) :]
            slash_index = tail.find("/")
            if slash_index > 0:
                tail = tail[slash_index + 1 :]
            return f".../{tail}"

        def _chip(text: str, role: str = "info") -> QLabel:
            display_text = str(text or "").strip() or "-"
            chip = QLabel(display_text)
            chip.setObjectName("MetricChip")
            chip.setProperty("chipRole", role)
            chip.setTextInteractionFlags(Qt.TextSelectableByMouse)
            return chip

        def _path_value(text: str) -> QLabel:
            label = QLabel(_compact_path(text))
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
        source_layout.addWidget(_row_label("Detected"), 1, 0)
        detected_row = QHBoxLayout()
        detected_row.setSpacing(6)
        mesh_format_text = str(getattr(scene_import_result.mesh, "format", "") or "").strip().upper()
        if not mesh_format_text:
            mesh_format_text = scene_path.suffix.lower().lstrip(".").upper()
        format_chip = _chip(mesh_format_text or "Format unknown", "format" if mesh_format_text else "warn")
        format_chip.setToolTip("Detected import format. Falls back to the source file extension when external mesh metadata is absent.")
        detected_row.addWidget(format_chip)
        detected_row.addWidget(_chip(f"{len(scene_import_result.mesh.submeshes):,} submesh(es)", "info"))
        detected_row.addWidget(_chip(f"{scene_import_result.mesh.total_vertices:,} vertices", "info"))
        detected_row.addWidget(_chip(f"{scene_import_result.mesh.total_faces:,} faces", "info"))
        detected_row.addStretch(1)
        source_layout.addLayout(detected_row, 1, 1)
        external_audit = getattr(scene_import_result, "external_audit", None)
        if external_audit is not None:
            audit_label = _row_label("Asset check")
            audit_label.setToolTip("Best-effort read-only classification of the imported model source.")
            source_layout.addWidget(audit_label, 2, 0)
            audit_row = QHBoxLayout()
            audit_row.setSpacing(6)
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
            audit_row.addWidget(audit_chip)
            texture_slots = tuple(getattr(external_audit, "texture_slots", ()) or ())
            if texture_slots:
                audit_row.addWidget(_chip("textures: " + ", ".join(str(slot) for slot in texture_slots[:4]), "info"))
            workflows = tuple(getattr(external_audit, "pbr_workflows", ()) or ())
            if workflows:
                audit_row.addWidget(_chip("PBR: " + ", ".join(str(workflow) for workflow in workflows[:2]), "info"))
            if bool(getattr(external_audit, "false_positive", False)) or bool(getattr(external_audit, "mixed_model", False)):
                audit_row.addWidget(_chip("review subparts", "warn"))
            audit_row.addStretch(1)
            source_layout.addLayout(audit_row, 2, 1)
        summary_layout.addWidget(source_group)

        mode_group = QWidget()
        mode_layout = QVBoxLayout(mode_group)
        mode_layout.setContentsMargins(0, 0, 0, 0)
        mode_layout.setSpacing(5)
        mode_choice_row = QHBoxLayout()
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
            force_label = "Auto clone source" if suffix == ".obj" else "Archive source"
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
        else:
            force_label = ""
        if not availability.roundtrip_enabled:
            roundtrip_radio.setEnabled(False)
            roundtrip_radio.setToolTip("Round-trip edit is OBJ-only and requires a local OBJ source.")
        if not availability.static_enabled:
            static_radio.setEnabled(False)
            static_radio.setToolTip("\n".join(profile.errors) or "Mesh replacement is not enabled for this target asset.")
        mode_status_row = QHBoxLayout()
        mode_status_row.setSpacing(6)
        mode_status_row.addWidget(
            _chip(
                force_label if force_static_replacement else setup_control_text["local_source"],
                "format" if force_static_replacement else "info",
            )
        )
        replacement_status_text, replacement_status_tone = _mesh_import_replacement_status_chip(
            static_enabled=availability.static_enabled
        )
        mode_status_row.addWidget(_chip(replacement_status_text, replacement_status_tone))
        if not availability.roundtrip_enabled:
            mode_status_row.addWidget(_chip(setup_control_text["roundtrip_unavailable"], "warn"))
        mode_status_row.addStretch(1)
        mode_layout.addLayout(mode_status_row)
        static_limits_label = QLabel(_mesh_import_static_guidance_text(availability.guidance))
        static_limits_label.setWordWrap(True)
        static_limits_label.setObjectName("HintLabel")
        mode_layout.addWidget(static_limits_label)
        if availability.default_mode == "roundtrip":
            roundtrip_radio.setChecked(True)
        elif availability.default_mode == "static_replacement":
            static_radio.setChecked(True)
        summary_layout.addWidget(mode_group)

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
            summary_layout.addWidget(placement_group)

        diagnostics = list(scene_import_result.diagnostics)
        if profile is not None:
            diagnostics.append(f"Target compatibility: {profile.support_level} ({profile.category_hint}).")
            diagnostics.extend(profile.errors[:3])
            diagnostics.extend(profile.warnings[:3])
        if diagnostics:
            diagnostics_group = QWidget()
            diagnostics_layout = QVBoxLayout(diagnostics_group)
            diagnostics_layout.setContentsMargins(0, 0, 0, 0)
            diagnostics_layout.setSpacing(3)
            for line in diagnostics[:6]:
                line_text = str(line)
                line_label = QLabel(line_text)
                line_label.setWordWrap(True)
                line_label.setObjectName("HintLabel")
                if "supported" in line_text.lower():
                    line_label.setStyleSheet("color: #86efac;")
                elif "warning" in line_text.lower() or "error" in line_text.lower():
                    line_label.setStyleSheet("color: #facc15;")
                diagnostics_layout.addWidget(line_label)
            summary_layout.addWidget(diagnostics_group)

        payload_group = QGroupBox(setup_control_text["payload_group"])
        payload_layout = QVBoxLayout(payload_group)
        payload_layout.setContentsMargins(10, 8, 10, 8)
        payload_layout.setSpacing(7)
        layout.addWidget(payload_group)

        preflight_group = QWidget()
        preflight_layout = QVBoxLayout(preflight_group)
        preflight_layout.setContentsMargins(0, 0, 0, 0)
        preflight_layout.setSpacing(5)
        preflight_summary_row = QHBoxLayout()
        preflight_summary_row.setSpacing(6)
        preflight_summary_row.addWidget(
            _chip(
                preflight.summary,
                "warn" if preflight.severity == "warning" else "ready",
            )
        )
        preflight_summary_row.addStretch(1)
        preflight_layout.addLayout(preflight_summary_row)
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
        for line in preflight.detail_lines:
            line_text = str(line)
            if ":" in line_text:
                key, value = line_text.split(":", 1)
                item = QTreeWidgetItem([key.strip(), value.strip()])
            else:
                item = QTreeWidgetItem(["Info", line_text])
            lower_line = line_text.lower()
            if "large" in lower_line or "slow" in lower_line or "warning" in lower_line:
                item.setForeground(0, QBrush(QColor("#facc15")))
                item.setForeground(1, QBrush(QColor("#facc15")))
            elif "target" in lower_line or "source" in lower_line:
                item.setForeground(1, QBrush(QColor("#bfdbfe")))
            preflight_tree.addTopLevelItem(item)
        preflight_layout.addWidget(preflight_tree)
        payload_layout.addWidget(preflight_group)

        supplemental_group = QWidget()
        supplemental_layout = QVBoxLayout(supplemental_group)
        supplemental_layout.setContentsMargins(0, 0, 0, 0)
        supplemental_layout.setSpacing(5)
        supplemental_hint = QLabel("Checked files are included with the import. Add local DDS/images or material sidecars only when needed.")
        supplemental_hint.setWordWrap(True)
        supplemental_hint.setObjectName("HintLabel")
        supplemental_layout.addWidget(supplemental_hint)
        supplemental_list = QListWidget()
        supplemental_list.setMinimumHeight(76)
        supplemental_list.setMaximumHeight(112)
        supplemental_list.setSelectionMode(QAbstractItemView.ExtendedSelection)
        supplemental_warning_label = QLabel("")
        supplemental_warning_label.setObjectName("WarningLabel")
        supplemental_warning_label.setWordWrap(True)
        supplemental_warning_label.setVisible(False)
        supported_suffixes = set(SCENE_TEXTURE_SOURCE_EXTENSIONS) | {
            ".xml",
            ".pami",
            ".pac_xml",
            ".pam_xml",
            ".pamlod_xml",
            ".app_xml",
            ".prefabdata_xml",
        }
        seen_paths: set[str] = set()

        def _add_supplemental_path(path: Path, *, checked: bool = True) -> None:
            try:
                resolved = path.expanduser().resolve()
            except Exception:
                return
            if not resolved.is_file() or resolved.suffix.lower() not in supported_suffixes:
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
                    "No local texture files were found for this source. Continue only if a geometry-only import is intended, or add a texture folder."
                )
                supplemental_warning_label.setVisible(True)
                return
            if checked_texture_count <= 0:
                supplemental_warning_label.setText(
                    "Texture files are available, but none are checked. The import will continue without local textures unless files are selected."
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
        supplemental_layout.addWidget(supplemental_warning_label)
        supplemental_buttons = QHBoxLayout()
        add_files_button = QPushButton("Add Files")
        add_folder_button = QPushButton("Add Folder")
        clear_button = QPushButton("Clear")
        supplemental_buttons.addWidget(add_files_button)
        supplemental_buttons.addWidget(add_folder_button)
        supplemental_buttons.addStretch(1)
        supplemental_buttons.addWidget(clear_button)
        supplemental_layout.addLayout(supplemental_buttons)
        payload_layout.addWidget(supplemental_group)

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
            for candidate in sorted(Path(selected_dir).rglob("*")):
                _add_supplemental_path(candidate, checked=True)
            _refresh_supplemental_warning()

        def _clear_supplemental() -> None:
            supplemental_list.clear()
            seen_paths.clear()
            _refresh_supplemental_warning()

        add_files_button.clicked.connect(_add_files)
        add_folder_button.clicked.connect(_add_folder)
        clear_button.clicked.connect(_clear_supplemental)
        supplemental_list.itemChanged.connect(lambda _item: _refresh_supplemental_warning())
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
            continue_button.setEnabled(
                (roundtrip_radio.isEnabled() and roundtrip_radio.isChecked())
                or (static_radio.isEnabled() and static_radio.isChecked())
            )

        roundtrip_radio.toggled.connect(_refresh_continue_state)
        static_radio.toggled.connect(_refresh_continue_state)
        cancel_button.clicked.connect(dialog.reject)
        continue_button.clicked.connect(dialog.accept)
        _refresh_continue_state()

        def _fit_mesh_import_setup_dialog_to_screen() -> None:
            screen = dialog.screen() or self.screen() or QApplication.primaryScreen()
            if screen is None:
                dialog.resize(980, 720)
                return
            available = screen.availableGeometry()
            max_width = min(1180, max(760, int(float(available.width()) * 0.92)))
            max_height = min(820, max(460, int(float(available.height()) * 0.86)))
            dialog.setMaximumSize(max_width, max_height)
            size_hint = dialog.sizeHint()
            target_width = min(max_width, max(760, int(size_hint.width())))
            target_height = min(max_height, max(460, int(size_hint.height())))
            dialog.resize(target_width, target_height)
            frame = dialog.frameGeometry()
            frame.moveCenter(available.center())
            left = max(available.left(), min(frame.left(), available.right() - frame.width() + 1))
            top = max(available.top(), min(frame.top(), available.bottom() - frame.height() + 1))
            dialog.move(left, top)

        dialog.adjustSize()
        _fit_mesh_import_setup_dialog_to_screen()
        QTimer.singleShot(0, _fit_mesh_import_setup_dialog_to_screen)

        if dialog.exec() != QDialog.Accepted:
            return None
        import_mode = "roundtrip" if roundtrip_radio.isChecked() else "static_replacement"
        if import_mode == "static_replacement" and not static_radio.isEnabled():
            return None
        supplemental_files: list[Path] = []
        for index in range(supplemental_list.count()):
            item = supplemental_list.item(index)
            if item is None or item.checkState() != Qt.Checked:
                continue
            raw_path = str(item.data(Qt.UserRole) or "")
            if raw_path:
                supplemental_files.append(Path(raw_path))
        return MeshImportSetupSelection(
            scene_path=scene_path,
            import_mode=import_mode,
            supplemental_files=tuple(supplemental_files),
            scene_import_result=scene_import_result,
            original_mesh=original_mesh_for_setup,
            preflight=preflight,
            source_label=source_display_label,
            placement_review_title=placement_review_title,
            placement_context_note=placement_context_note.strip(),
            full_import_model_replacement=bool(full_import_model_replacement),
        )

    def _start_archive_mesh_export(self, entry: ArchiveEntry, export_format: str) -> None:
        default_dir = self.settings_file_path.parent / "mesh_export"
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
                    archive_entries_by_normalized_path=self.archive_entries_by_normalized_path,
                    archive_entries_by_basename=self.archive_entries_by_basename,
                    related_entries=selected_related_entries,
                    allow_missing_skeleton=allow_missing_skeleton,
                    on_log=log,
                )

            def _handle_complete(result: object) -> None:
                if not isinstance(result, MeshExportResult):
                    self.set_status_message("Mesh export finished with an unexpected result payload.", error=True)
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
                        self.set_status_message(f"Cancelled {export_format.upper()} export for {entry.basename}.")
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
                self.set_status_message(f"Exported {entry.basename} as {export_format.upper()}.")

            self._run_utility_task(
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
            self.set_status_message("No model preview is available to export.", error=True)
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

        default_dir = self.settings_file_path.parent / "model_export"
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
            self.set_status_message(f"Model export failed: {exc}", error=True)
            return

        self.set_status_message(f"Exported model preview to {exported_path}")

__all__ = ["ArchiveMeshImportExportMixin"]
