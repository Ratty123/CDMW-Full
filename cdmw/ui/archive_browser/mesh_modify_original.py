"""Archive Modify Original workspace flow."""

from __future__ import annotations

import dataclasses
import json
import os
import re
import shutil
import time
from collections.abc import Callable, Mapping
from pathlib import Path, PurePosixPath
from typing import Optional, Tuple

from PySide6.QtCore import Qt, QTimer, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QFileDialog,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QRadioButton,
    QVBoxLayout,
)

from cdmw.core.archive import find_available_output_path, read_archive_entry_data
from cdmw.core.archive_modding import (
    ARCHIVE_MESH_EXTENSIONS,
    export_archive_mesh,
    mesh_import_runtime_sibling_mesh_candidates,
)
from cdmw.core.mesh_baseline import read_archive_entry_baseline_data
from cdmw.domain.mesh.session import MeshImportSetupSelection, ModifyOriginalWorkflowSelection
from cdmw.models import ArchiveEntry
from cdmw.modding.mesh_parser import ParsedMesh, parse_mesh
from cdmw.modding.scene_importer import SceneImportResult, import_scene_mesh_with_report
from cdmw.modding.static_mesh_replacer import StaticMeshReplacementOptions, StaticSubmeshMapping
from cdmw.services.diagnostics_service import process_is_alive as _process_is_alive
from cdmw.services.workspace_layout import workspace_paths


class ArchiveMeshModifyOriginalMixin:
    """Modify Original workspace and in-app clone workflow."""
    def _prompt_archive_modify_original_workspace_options(
        self,
        entry: ArchiveEntry,
        ) -> Optional[ModifyOriginalWorkflowSelection]:
        default_parent = Path(self._suggest_workspace_base_dir()).expanduser() / "modify_original"
        dialog = QDialog(self)
        dialog.setWindowTitle("Modify Original")
        dialog.setModal(True)
        dialog.resize(800, 360)
        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        intro = QLabel(
            "Open an editable clone of the selected archive mesh in Mesh Replacement Geometry. "
            "No workspace export is required; the game archive is not changed here, and edits are written only when you save a loose mod package."
        )
        intro.setWordWrap(True)
        intro.setObjectName("HintLabel")
        layout.addWidget(intro)

        source_label = QLabel(f"Source: {entry.path}")
        source_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        source_label.setWordWrap(True)
        layout.addWidget(source_label)

        mode_group = QGroupBox("Workflow")
        mode_layout = QVBoxLayout(mode_group)
        mode_layout.setContentsMargins(10, 8, 10, 8)
        mode_layout.setSpacing(6)
        edit_in_app_radio = QRadioButton("Edit inside Mesh Replacement (no workspace export)")
        edit_in_app_radio.setChecked(True)
        edit_in_app_radio.setToolTip(
            "Creates the temporary editable clone internally, opens Geometry, and writes output only through the loose-mod save path."
        )
        create_workspace_radio = QRadioButton("Create editable workspace folder")
        create_workspace_radio.setToolTip(
            "Also writes the OBJ clone and referenced files to a visible workspace folder for external inspection or editing."
        )
        mode_layout.addWidget(edit_in_app_radio)
        mode_layout.addWidget(create_workspace_radio)
        layout.addWidget(mode_group)

        form = QGridLayout()
        form.setHorizontalSpacing(8)
        form.setVerticalSpacing(8)
        parent_edit = QLineEdit(str(default_parent))
        browse_button = QPushButton("Browse...")
        form.addWidget(QLabel("Workspace parent"), 0, 0)
        form.addWidget(parent_edit, 0, 1)
        form.addWidget(browse_button, 0, 2)
        layout.addLayout(form)

        include_family_checkbox = QCheckBox("Use resolved asset-family files for texture/material context")
        include_family_checkbox.setChecked(True)
        include_family_checkbox.setToolTip(
            "Uses resolved asset-family material context by default. "
            "In app-only mode this does not copy the full resolved family; copying only happens for visible workspaces/export paths."
        )
        open_after_checkbox = QCheckBox("Open workspace folder when finished")
        open_after_checkbox.setChecked(False)
        layout.addWidget(include_family_checkbox)
        layout.addWidget(open_after_checkbox)

        notes = QLabel(
            "Default mode stays inside the app. The optional workspace is only for users who want a visible OBJ/reference folder; "
            "both paths still use Mesh Replacement validation before writing a loose mod."
        )
        notes.setObjectName("HintLabel")
        notes.setWordWrap(True)
        layout.addWidget(notes)

        button_row = QHBoxLayout()
        button_row.addStretch(1)
        cancel_button = QPushButton("Cancel")
        create_button = QPushButton("Continue")
        create_button.setDefault(True)
        button_row.addWidget(cancel_button)
        button_row.addWidget(create_button)
        layout.addLayout(button_row)

        def browse_parent() -> None:
            selected = QFileDialog.getExistingDirectory(
                dialog,
                "Select Modify Original Workspace Parent",
                parent_edit.text().strip() or str(default_parent),
            )
            if selected:
                parent_edit.setText(selected)

        def refresh_workflow_controls() -> None:
            workspace_enabled = bool(create_workspace_radio.isChecked())
            parent_edit.setEnabled(workspace_enabled)
            browse_button.setEnabled(workspace_enabled)
            open_after_checkbox.setEnabled(workspace_enabled)
            create_button.setText("Create Workspace" if workspace_enabled else "Continue")

        edit_in_app_radio.toggled.connect(refresh_workflow_controls)
        create_workspace_radio.toggled.connect(refresh_workflow_controls)
        browse_button.clicked.connect(browse_parent)
        cancel_button.clicked.connect(dialog.reject)
        create_button.clicked.connect(dialog.accept)
        refresh_workflow_controls()
        if dialog.exec() != QDialog.Accepted:
            return None
        parent_root = Path(parent_edit.text().strip() or str(default_parent)).expanduser()
        create_workspace = bool(create_workspace_radio.isChecked())
        return ModifyOriginalWorkflowSelection(
            create_workspace=create_workspace,
            workspace_parent=parent_root if create_workspace else None,
            include_family_files=bool(include_family_checkbox.isChecked()),
            open_workspace_after_create=bool(create_workspace and open_after_checkbox.isChecked()),
        )

    @staticmethod
    def _archive_modify_original_workspace_name(entry: ArchiveEntry) -> str:
        source_key = PurePosixPath(entry.path.replace("\\", "/")).with_suffix("").as_posix().replace("/", "_")
        safe_name = re.sub(r"[^A-Za-z0-9_.-]+", "_", source_key).strip("._")
        return safe_name or re.sub(r"[^A-Za-z0-9_.-]+", "_", entry.basename).strip("._") or "archive_mesh"

    @staticmethod
    def _modify_original_workspace_supplemental_files(workspace_dir: Path) -> Tuple[Path, ...]:
        referenced_root = workspace_dir / "referenced_files"
        if not referenced_root.is_dir():
            return ()
        supported_suffixes = {
            ".dds",
            ".xml",
            ".pami",
            ".pac_xml",
            ".pam_xml",
            ".pamlod_xml",
            ".app_xml",
            ".prefabdata_xml",
        }
        return tuple(
            sorted(
                (
                    path
                    for path in referenced_root.rglob("*")
                    if path.is_file() and path.suffix.lower() in supported_suffixes
                ),
                key=lambda path: path.as_posix().lower(),
            )
        )

    def _cleanup_stale_modify_original_sessions(self, *, max_age_seconds: float = 24.0 * 60.0 * 60.0) -> None:
        session_root = workspace_paths(self.settings_file_path.parent)["modify_original_sessions_root"]
        if not session_root.is_dir():
            return
        try:
            root_resolved = session_root.resolve()
        except OSError:
            root_resolved = session_root
        current_time = time.time()
        removed_count = 0
        failed_count = 0
        for candidate in tuple(session_root.iterdir()):
            try:
                if not candidate.is_dir():
                    continue
                try:
                    candidate_resolved = candidate.resolve()
                except OSError:
                    candidate_resolved = candidate
                if candidate_resolved == root_resolved or root_resolved not in candidate_resolved.parents:
                    continue
                manifest_path = candidate / "modify_original_workspace.json"
                manifest: Mapping[str, object] = {}
                if manifest_path.is_file():
                    try:
                        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
                        if isinstance(payload, Mapping):
                            manifest = payload
                    except Exception:
                        manifest = {}
                workspace_mode = str(manifest.get("workspace_mode", "") or "")
                if workspace_mode and workspace_mode != "internal_app_session":
                    continue
                try:
                    process_id = int(manifest.get("process_id", 0) or 0)
                except (TypeError, ValueError):
                    process_id = 0
                if process_id == os.getpid() or (process_id > 0 and _process_is_alive(process_id)):
                    continue
                try:
                    age_seconds = current_time - float(manifest.get("created_at", candidate.stat().st_mtime) or 0.0)
                except Exception:
                    age_seconds = max_age_seconds
                if age_seconds < min(float(max_age_seconds), 30.0 * 60.0):
                    continue
                shutil.rmtree(candidate)
                removed_count += 1
            except Exception:
                failed_count += 1
        if removed_count:
            self.append_archive_log(f"Cleaned {removed_count:,} stale Modify Original internal session folder(s).")
        if failed_count:
            self.append_archive_log(f"Skipped {failed_count:,} stale Modify Original session folder(s) that were locked or unavailable.")

    def _modify_original_runtime_candidate_note(
        self,
        entry: ArchiveEntry,
        mesh: Optional[ParsedMesh],
        ) -> str:
        if not isinstance(entry, ArchiveEntry) or not isinstance(mesh, ParsedMesh):
            return ""
        source_path = str(getattr(entry, "path", "") or "").replace("\\", "/").strip().lower()
        candidates = mesh_import_runtime_sibling_mesh_candidates(
            entry,
            mesh,
            self.archive_entries_by_basename,
        )
        if not candidates:
            return ""
        has_player_candidate = any(
            "/1_pc/" in str(getattr(candidate, "path", "") or "").replace("\\", "/").lower()
            for candidate in candidates
        )
        if "/2_mon/" not in source_path and not has_player_candidate:
            return ""
        candidate_paths = [
            str(getattr(candidate, "path", "") or "").replace("\\", "/").strip()
            for candidate in candidates[:3]
            if str(getattr(candidate, "path", "") or "").strip()
        ]
        if not candidate_paths:
            return ""
        suffix = " ..." if len(candidates) > len(candidate_paths) else ""
        return (
            " Related runtime mesh candidate(s) found: "
            + ", ".join(candidate_paths)
            + suffix
            + ". Modify Original keeps the selected PAC as the export target; open a candidate directly to edit that asset."
        )

    def _retarget_static_options_for_runtime_entry(
        self,
        selected_entry: ArchiveEntry,
        runtime_entry: ArchiveEntry,
        options: Optional[StaticMeshReplacementOptions],
        fallback_source_mesh: Optional[ParsedMesh],
        *,
        on_log: Optional[Callable[[str], None]] = None,
        ) -> Optional[StaticMeshReplacementOptions]:
        if options is None or self._same_archive_entry(selected_entry, runtime_entry):
            return options
        source_mesh = (
            options.edited_source_mesh
            if isinstance(getattr(options, "edited_source_mesh", None), ParsedMesh)
            else fallback_source_mesh
        )
        if not isinstance(source_mesh, ParsedMesh):
            return options
        try:
            runtime_data = read_archive_entry_baseline_data(
                runtime_entry,
                read_entry_data=read_archive_entry_data,
            ).data
            runtime_mesh = parse_mesh(runtime_data, runtime_entry.path)
        except Exception as exc:
            if on_log is not None:
                on_log(f"Runtime target remap skipped; could not parse {runtime_entry.path}: {exc}")
            return options
        if len(runtime_mesh.submeshes) != 1:
            return options

        disabled_source_indices = {
            int(getattr(adjustment, "source_submesh_index", -1))
            for adjustment in tuple(getattr(options, "source_part_adjustments", ()) or ())
            if not bool(getattr(adjustment, "enabled", True))
        }

        def source_is_output_candidate(source_index: int) -> bool:
            if source_index in disabled_source_indices:
                return False
            if source_index < 0 or source_index >= len(source_mesh.submeshes):
                return False
            source = source_mesh.submeshes[source_index]
            name = str(getattr(source, "name", "") or "").strip().lower()
            if name.startswith("cdmw_anchor") or name.startswith("cft_anchor"):
                return False
            return bool(getattr(source, "vertices", None)) and bool(getattr(source, "faces", None))

        source_indices: list[int] = []
        for mapping in tuple(getattr(options, "submesh_mappings", ()) or ()):
            for raw_source_index in tuple(getattr(mapping, "source_submesh_indices", ()) or ()):
                try:
                    source_index = int(raw_source_index)
                except (TypeError, ValueError):
                    continue
                if source_index not in source_indices and source_is_output_candidate(source_index):
                    source_indices.append(source_index)
        if not source_indices:
            for source_index in range(len(source_mesh.submeshes)):
                if source_is_output_candidate(source_index):
                    source_indices.append(source_index)
        if not source_indices:
            return options

        target = runtime_mesh.submeshes[0]
        target_name = str(getattr(target, "material", "") or getattr(target, "name", "") or "target 0").strip()
        if on_log is not None:
            on_log(
                "Runtime target override: routing edited source part(s) "
                f"{source_indices} into {runtime_entry.path} target 0 ({target_name})."
            )
        return dataclasses.replace(
            options,
            submesh_mappings=[
                StaticSubmeshMapping(
                    target_submesh_index=0,
                    target_submesh_name=target_name,
                    source_submesh_indices=source_indices,
                    target_material_slot_index=0,
                    merge_sources=True,
                )
            ],
            removed_target_submesh_indices=[],
        )

    def _start_archive_modify_original_workspace(self, entry: ArchiveEntry) -> None:
        if not isinstance(entry, ArchiveEntry) or entry.extension not in ARCHIVE_MESH_EXTENSIONS:
            self.set_status_message("Select a supported archive mesh first.", error=True)
            return
        self._open_mesh_editor_for_entry(entry, mode="modify_original", activate=True)
        selection = self._prompt_archive_modify_original_workspace_options(entry)
        if selection is None:
            return
        create_workspace = bool(selection.create_workspace)
        include_family = bool(selection.include_family_files)
        open_after = bool(create_workspace and selection.open_workspace_after_create)
        workspace_name = self._archive_modify_original_workspace_name(entry)
        if create_workspace:
            parent_root = selection.workspace_parent or (Path(self._suggest_workspace_base_dir()).expanduser() / "modify_original")
            workspace_dir = find_available_output_path(parent_root / workspace_name)
        else:
            self._cleanup_stale_modify_original_sessions()
            session_root = workspace_paths(self.settings_file_path.parent)["modify_original_sessions_root"]
            workspace_dir = find_available_output_path(session_root / workspace_name)
        related_entries: Tuple[ArchiveEntry, ...] = ()
        if include_family and create_workspace:
            try:
                graph, _references = self._archive_asset_family_graph_for_entry(entry)
                family_related_entries = tuple(
                    related_entry
                    for related_entry in self._archive_entries_from_asset_family_graph(graph, include_hints=False)
                    if not self._same_archive_entry(related_entry, entry)
                )
                related_entries = family_related_entries
            except Exception:
                related_entries = ()

        def _task(log: Callable[[str], None]) -> dict[str, object]:
            workspace_dir.parent.mkdir(parents=True, exist_ok=True)
            log(
                f"Creating Modify Original workspace: {workspace_dir}"
                if create_workspace
                else f"Preparing Modify Original in-app session: {workspace_dir}"
            )
            if include_family and not create_workspace:
                log(
                    "Modify Original in-app session uses the archive material graph directly; "
                    "resolved asset-family file copying is skipped to keep startup responsive."
                )
            result = export_archive_mesh(
                entry,
                workspace_dir,
                "obj",
                archive_entries_by_normalized_path=self.archive_entries_by_normalized_path,
                archive_entries_by_basename=self.archive_entries_by_basename,
                related_entries=related_entries,
                allow_missing_skeleton=True,
                resolve_skeleton_for_obj=create_workspace,
                on_log=log,
            )
            obj_paths = [path for path in result.output_paths if path.suffix.lower() == ".obj"]
            if not obj_paths:
                raise ValueError("OBJ export did not produce an editable clone file.")
            obj_path = obj_paths[0]
            log("Preloading Modify Original clone geometry off the UI thread...")
            scene_import_result = import_scene_mesh_with_report(obj_path)
            log("Preloading original archive mesh for Geometry alignment...")
            original_data = read_archive_entry_baseline_data(entry, read_entry_data=read_archive_entry_data).data
            original_mesh = parse_mesh(original_data, entry.path)
            supplemental_files = self._modify_original_workspace_supplemental_files(workspace_dir)
            readme_path: Optional[Path] = None
            manifest_path = workspace_dir / "modify_original_workspace.json"
            if create_workspace:
                readme_path = workspace_dir / "MODIFY_ORIGINAL_README.txt"
                readme_path.write_text(
                    "\n".join(
                        [
                            "Crimson Desert Mod Workbench - Modify Original Workspace",
                            "",
                            f"Source archive mesh: {entry.path}",
                            f"Editable OBJ clone: {obj_path.name}",
                            "",
                            "What this workspace is for:",
                            "- The app opens this OBJ clone in Mesh Replacement Setup automatically.",
                            "- Use Geometry in the alignment window to resize, move, or reshape existing mesh parts.",
                            "- Keep topology, material names, and draw-part structure stable for the safest import.",
                            "- Edit copied DDS/material sidecar files under referenced_files/ when you want texture/material context changes.",
                            "",
                            "What this workspace does not do:",
                            "- It does not patch game archives directly.",
                            "- It does not make arbitrary topology, skeleton, or animation edits safe.",
                            "- It does not bypass the existing loose-mod export and validation path.",
                            "",
                            "Back in the app, use Mesh Replacement Setup and Geometry to review the clone and write a mod-ready loose package.",
                        ]
                    ),
                    encoding="utf-8",
                )
            manifest_path.write_text(
                json.dumps(
                    {
                        "format": "cdmw_modify_original_workspace_v1",
                        "workspace_mode": "user_workspace" if create_workspace else "internal_app_session",
                        "create_workspace": create_workspace,
                        "source_archive_path": entry.path,
                        "source_package": entry.package_label,
                        "workspace_dir": str(workspace_dir),
                        "editable_obj": str(obj_path),
                        "related_file_count": len(related_entries),
                        "supplemental_file_count": len(supplemental_files),
                        "include_family_files": include_family,
                        "open_workspace_after_create": open_after,
                        "process_id": os.getpid(),
                        "created_at": time.time(),
                        "exported_files": [str(path) for path in result.output_paths],
                        "policy": "safe_clone_workspace_imports_through_mesh_replacement_geometry_path",
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )
            return {
                "workspace_dir": workspace_dir,
                "obj_path": obj_path,
                "readme_path": readme_path,
                "manifest_path": manifest_path,
                "create_workspace": create_workspace,
                "output_paths": tuple(result.output_paths),
                "summary_lines": tuple(result.summary_lines),
                "related_count": len(related_entries),
                "supplemental_files": supplemental_files,
                "scene_import_result": scene_import_result,
                "original_mesh": original_mesh,
            }

        def _handle_complete(result: object) -> None:
            if not isinstance(result, dict):
                self.set_status_message("Modify Original workspace finished with an unexpected result payload.", error=True)
                return
            workspace = result.get("workspace_dir")
            obj_path = result.get("obj_path")
            if not isinstance(workspace, Path) or not isinstance(obj_path, Path):
                self.set_status_message("Modify Original workspace did not return an editable OBJ clone.", error=True)
                return
            if open_after:
                QDesktopServices.openUrl(QUrl.fromLocalFile(str(workspace.resolve())))
            if create_workspace:
                self.set_status_message(f"Modify Original workspace ready: {obj_path.name}. Opening Mesh Replacement setup...")
            else:
                self.set_status_message(f"Modify Original in-app clone ready: {obj_path.name}. Opening Geometry...")
            QTimer.singleShot(
                0,
                lambda current_entry=entry, payload=result: self._open_modify_original_mesh_setup(
                    current_entry,
                    payload,
                ),
            )

        self._run_utility_task(
            status_message=(
                f"Creating Modify Original workspace for {entry.basename}..."
                if create_workspace
                else f"Preparing Modify Original in-app session for {entry.basename}..."
            ),
            task=_task,
            on_complete=_handle_complete,
            show_archive_progress=True,
        )

    def _open_modify_original_mesh_setup(
        self,
        entry: ArchiveEntry,
        result: Mapping[str, object],
        ) -> None:
        obj_path = result.get("obj_path")
        if not isinstance(obj_path, Path) or not obj_path.is_file():
            self.set_status_message("Modify Original clone is missing; cannot open Mesh Replacement setup.", error=True)
            return
        supplemental_files = tuple(
            path for path in result.get("supplemental_files", ()) if isinstance(path, Path)
        )
        scene_import_result = result.get("scene_import_result")
        if not isinstance(scene_import_result, SceneImportResult):
            scene_import_result = None
        original_mesh = result.get("original_mesh")
        if not isinstance(original_mesh, ParsedMesh):
            original_mesh = None
        runtime_target_note = self._modify_original_runtime_candidate_note(
            entry,
            scene_import_result.mesh if isinstance(scene_import_result, SceneImportResult) else original_mesh,
        )
        if not bool(result.get("create_workspace")):
            setup = MeshImportSetupSelection(
                scene_path=obj_path,
                import_mode="static_replacement",
                supplemental_files=supplemental_files,
                scene_import_result=scene_import_result,
                original_mesh=original_mesh,
                source_label=f"Modify Original in-app clone: {obj_path.name}",
                placement_review_title="Modify Original Geometry",
                placement_context_note=(
                    "This is an internal clone of the selected archive mesh. "
                    "Geometry can resize or move existing parts; no workspace export was required, and output is written only through loose-mod save."
                    f"{runtime_target_note}"
                ),
                defer_original_texture_preview=True,
            )
            self._start_archive_mesh_patch(entry, preset_setup=setup)
            return
        setup = self._prompt_archive_mesh_import_setup(
            entry,
            obj_path,
            title="Modify Original Mesh Setup",
            scene_import_result=scene_import_result,
            original_mesh=original_mesh,
            source_label=f"Modify Original clone: {obj_path}",
            force_static_replacement=True,
            placement_review_title="Modify Original Geometry",
            placement_context_note=(
                "This is an automatic clone of the selected archive mesh. "
                "Mesh Replacement is preselected so the Geometry tab can resize or move existing parts."
            ),
        )
        if setup is None:
            return
        setup.supplemental_files = supplemental_files
        setup.source_label = setup.source_label or f"Modify Original clone: {obj_path}"
        setup.defer_original_texture_preview = True
        if runtime_target_note:
            setup.placement_context_note = f"{setup.placement_context_note}{runtime_target_note}"
        self._start_archive_mesh_patch(entry, preset_setup=setup)

__all__ = ["ArchiveMeshModifyOriginalMixin"]
