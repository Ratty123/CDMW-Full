"""Archive mesh direct patch and preview helpers."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

from PySide6.QtGui import QImageReader
from PySide6.QtWidgets import QFileDialog, QMessageBox, QWidget

from cdmw.core.archive_modding import (
    ARCHIVE_PATCH_BACKUP_ROOT,
    ArchivePatchRequest,
    MeshImportPreviewResult,
    MeshImportSupplementalFileSpec,
)
from cdmw.core.final_package_preview import FinalPackagePreviewResult
from cdmw.models import ArchiveEntry, ArchivePreviewResult, ImportIssueStatus
from cdmw.modding.scene_importer import SCENE_TEXTURE_SOURCE_EXTENSIONS
from cdmw.rendering.model_preview_prepare import prepare_model_preview


class ArchiveMeshDirectPatchMixin:
    """Direct archive mesh patch confirmation and preview helpers."""
    def _mesh_direct_patch_spec_is_generated(
        self,
        spec: MeshImportSupplementalFileSpec,
        ) -> bool:
        kind = str(getattr(spec, "kind", "") or "").strip().casefold()
        return kind in {"sidecar_generated", "texture_generated", "item_icon_generated"}

    def _mesh_direct_patch_spec_payload(
        self,
        spec: MeshImportSupplementalFileSpec,
        ) -> Tuple[Optional[bytes], str]:
        payload_data = bytes(getattr(spec, "payload_data", b"") or b"")
        if payload_data:
            return payload_data, ""
        source_path = getattr(spec, "source_path", None)
        if not isinstance(source_path, Path):
            return None, "no payload data or source file"
        try:
            resolved_source = source_path.expanduser().resolve()
        except Exception:
            resolved_source = source_path
        if not resolved_source.is_file():
            return None, f"source file is not readable: {resolved_source}"
        try:
            return resolved_source.read_bytes(), ""
        except Exception as exc:
            return None, f"could not read {resolved_source}: {exc}"

    def _build_mesh_direct_patch_requests(
        self,
        primary_entry: ArchiveEntry,
        preview_result: MeshImportPreviewResult,
        *,
        paired_entry: Optional[ArchiveEntry] = None,
        supplemental_specs: Sequence[MeshImportSupplementalFileSpec] = (),
        ) -> Tuple[List[ArchivePatchRequest], List[str]]:
        request_by_normalized_path: Dict[str, ArchivePatchRequest] = {}
        warnings: List[str] = []

        def _add_request(entry: ArchiveEntry, payload_data: bytes, label: str) -> None:
            if not payload_data:
                warnings.append(f"Skipping {label}: empty payload.")
                return
            target_key = str(entry.path or "").replace("\\", "/").strip().casefold()
            if not target_key:
                warnings.append(f"Skipping {label}: target path is empty.")
                return
            request_by_normalized_path[target_key] = ArchivePatchRequest(
                entry=entry,
                payload_data=payload_data,
            )

        _add_request(primary_entry, preview_result.rebuilt_data, primary_entry.path)
        if paired_entry is not None and preview_result.paired_lod_data is not None:
            _add_request(paired_entry, preview_result.paired_lod_data, paired_entry.path)

        for spec in supplemental_specs:
            if not isinstance(spec, MeshImportSupplementalFileSpec):
                continue
            if not self._mesh_direct_patch_spec_is_generated(spec):
                continue
            target_entry = getattr(spec, "target_entry", None)
            target_path = str(getattr(spec, "target_path", "") or "").strip()
            if not isinstance(target_entry, ArchiveEntry):
                warnings.append(
                    "Skipping generated supplemental patch target without an existing archive entry: "
                    f"{target_path or getattr(spec, 'source_path', '')}"
                )
                continue
            payload_data, reason = self._mesh_direct_patch_spec_payload(spec)
            if payload_data is None:
                warnings.append(
                    f"Skipping generated supplemental patch target {target_entry.path}: {reason}"
                )
                continue
            _add_request(target_entry, payload_data, target_entry.path)

        return list(request_by_normalized_path.values()), warnings

    def _mesh_direct_patch_target_paths(
        self,
        primary_entry: ArchiveEntry,
        preview_result: MeshImportPreviewResult,
        *,
        paired_entry: Optional[ArchiveEntry] = None,
        supplemental_specs: Sequence[MeshImportSupplementalFileSpec] = (),
        ) -> Tuple[str, ...]:
        paths: List[str] = []

        def _add_path(raw_path: object) -> None:
            path = str(raw_path or "").replace("\\", "/").strip()
            if path and path.casefold() not in {existing.casefold() for existing in paths}:
                paths.append(path)

        _add_path(primary_entry.path)
        if paired_entry is not None and preview_result.paired_lod_data is not None:
            _add_path(paired_entry.path)
        for spec in supplemental_specs:
            if not isinstance(spec, MeshImportSupplementalFileSpec):
                continue
            if not self._mesh_direct_patch_spec_is_generated(spec):
                continue
            target_entry = getattr(spec, "target_entry", None)
            if isinstance(target_entry, ArchiveEntry):
                _add_path(target_entry.path)
        return tuple(paths)

    def _confirm_mesh_direct_archive_patch(
        self,
        target_paths: Sequence[str],
        *,
        parent: Optional[QWidget] = None,
        ) -> bool:
        compact_paths = [str(path or "").strip() for path in target_paths if str(path or "").strip()]
        shown_targets = "\n".join(f"- {path}" for path in compact_paths[:8])
        if len(compact_paths) > 8:
            shown_targets += f"\n- ... {len(compact_paths) - 8:,} more target(s)"
        prompt_parent = parent if parent is not None else self
        prompt = QMessageBox(prompt_parent)
        prompt.setIcon(QMessageBox.Warning)
        prompt.setWindowTitle("Patch Game Files")
        prompt.setText("Patch game archive files directly?")
        prompt.setInformativeText(
            "This modifies the installed game archive package files. Close the game and any mod manager before continuing.\n\n"
            "A backup of the touched PAPGT/PAMT/PAZ files will be created first and can be restored from Archive Patch Backups.\n\n"
            f"Targets:\n{shown_targets or '- none'}"
        )
        prompt.setDetailedText(
            "Archive entries that will be patched:\n"
            + "\n".join(compact_paths)
            + f"\n\nBackup root:\n{ARCHIVE_PATCH_BACKUP_ROOT}"
        )
        prompt.setStandardButtons(QMessageBox.Yes | QMessageBox.No)
        prompt.setDefaultButton(QMessageBox.No)
        yes_button = prompt.button(QMessageBox.Yes)
        if yes_button is not None:
            yes_button.setText("Patch Game Files")
        no_button = prompt.button(QMessageBox.No)
        if no_button is not None:
            no_button.setText("Cancel")
        return prompt.exec() == QMessageBox.Yes

    def _show_archive_import_preview(
        self,
        entry: ArchiveEntry,
        import_result: MeshImportPreviewResult,
        *,
        patched: bool,
        backup_dir: Optional[Path] = None,
        loose_package_root: Optional[Path] = None,
        final_preview: Optional[FinalPackagePreviewResult] = None,
        ) -> None:
        preview_model_for_display = (
            final_preview.preview_model
            if isinstance(final_preview, FinalPackagePreviewResult)
            else import_result.preview_model
        )
        self._attach_archive_model_preview_images(preview_model_for_display)
        detail_lines = list(import_result.summary_lines)
        if isinstance(final_preview, FinalPackagePreviewResult):
            detail_lines.append("")
            detail_lines.extend(final_preview.summary_lines)
            if final_preview.warnings:
                detail_lines.append("Final output warnings:")
                detail_lines.extend(f"- {warning}" for warning in final_preview.warnings[:12])
            if final_preview.preflight_errors:
                detail_lines.append(
                    "Final output preflight warnings:"
                    if patched
                    else "Final output preflight blockers:"
                )
                detail_lines.extend(f"- {blocker}" for blocker in final_preview.preflight_errors[:12])
            if final_preview.missing_texture_paths:
                detail_lines.append("Missing final texture path examples:")
                detail_lines.extend(f"- {path}" for path in final_preview.missing_texture_paths[:8])
        if import_result.import_issues:
            detail_lines.append("")
            detail_lines.append("Import validation:")
            for issue in import_result.import_issues:
                detail_lines.append(f"- {issue.status}: {issue.title} - {issue.detail}")
                for diff in tuple(getattr(issue, "diffs", ()) or ())[:3]:
                    diff_detail = str(getattr(diff, "detail", "") or "").strip()
                    if diff_detail:
                        detail_lines.append(f"  * {diff_detail}")
                extra_diff_count = max(0, len(tuple(getattr(issue, "diffs", ()) or ())) - 3)
                if extra_diff_count > 0:
                    detail_lines.append(f"  * ... {extra_diff_count:,} more difference(s)")
        if patched and backup_dir is not None:
            detail_lines.append(f"Backup: {backup_dir}")
        if not patched and loose_package_root is not None:
            detail_lines.append(f"Loose export: {loose_package_root}")
        warning_badge = ""
        warning_text = ""
        if patched:
            warning_badge = "Patched archive"
            warning_text = "This rebuilt mesh has been patched directly into the scanned game archives."
            if backup_dir is not None:
                warning_text += f"\n\nBackup: {backup_dir}"
            if isinstance(final_preview, FinalPackagePreviewResult) and final_preview.preflight_errors:
                first_warning = str(final_preview.preflight_errors[0] or "").strip()
                if len(first_warning) > 320:
                    first_warning = first_warning[:317].rstrip() + "..."
                warning_text += f"\n\nMaterial preflight warning: {first_warning}"
        elif loose_package_root is not None:
            warning_badge = "Loose export"
            if isinstance(final_preview, FinalPackagePreviewResult):
                warning_text = (
                    f"This rebuilt mesh has been written to the mod-ready package at {loose_package_root}. "
                    "The preview is using final package texture paths where they could be validated."
                )
                if final_preview.warnings:
                    first_warning = str(final_preview.warnings[0] or "").strip()
                    if len(first_warning) > 320:
                        first_warning = first_warning[:317].rstrip() + "..."
                    warning_text += f"\n\nFinal output warning: {first_warning}"
            else:
                warning_text = f"This rebuilt mesh has been written to the mod-ready package at {loose_package_root}."
        elif not patched:
            warning_badge = "Import preview"
            warning_text = "This rebuilt mesh preview has not been written back to the game archives yet."
        runtime_target_warning = next(
            (
                str(line or "").strip()
                for line in import_result.summary_lines
                if str(line or "").strip().startswith("Runtime target warning:")
            ),
            "",
        )
        if runtime_target_warning:
            warning_text = (
                f"{warning_text}\n\n{runtime_target_warning}"
                if warning_text
                else runtime_target_warning
            )
        prepared_model, prepared_preview_model = prepare_model_preview(preview_model_for_display)
        preview_result = ArchivePreviewResult(
            status="ok",
            title=entry.basename,
            metadata_summary=(
                f"{entry.extension} | {import_result.parsed_mesh.total_vertices:,} vertices"
                f" | {import_result.parsed_mesh.total_faces:,} faces"
            ),
            detail_text="\n".join(detail_lines),
            preview_model=prepared_model,
            prepared_preview_model=prepared_preview_model,
            model_texture_references=tuple(import_result.texture_references),
            preferred_view="model",
            warning_badge=warning_badge,
            warning_text=warning_text,
        )
        self.archive_preview_requested_loose = False
        self.current_archive_preview_result = preview_result
        self._show_archive_preview_result(preview_result, use_loose=False)

    def _confirm_archive_mesh_import_commit(
        self,
        entry: ArchiveEntry,
        import_result: MeshImportPreviewResult,
        *,
        destination: str,
        source_obj_path: Path,
        ) -> bool:
        issues = tuple(import_result.import_issues or ())
        actionable_issues = [
            issue for issue in issues if issue.status != ImportIssueStatus.AUTO_FIXED.value
        ]
        if not actionable_issues:
            return True

        status_counts = Counter(issue.status for issue in issues)
        message_lines = [
            f"{source_obj_path.name} for {entry.basename} has import validation findings.",
            "",
            "Summary:",
            ", ".join(
                f"{status_counts.get(status, 0):,} {status}"
                for status in (
                    ImportIssueStatus.AUTO_FIXED.value,
                    ImportIssueStatus.WARNING.value,
                    ImportIssueStatus.REQUIRES_MANUAL_REVIEW.value,
                )
                if status_counts.get(status, 0) > 0
            ),
            "",
            "Actionable findings:",
        ]
        for issue in actionable_issues[:6]:
            message_lines.append(f"- {issue.status}: {issue.title}")
            if issue.detail:
                message_lines.append(f"  {issue.detail}")
        remaining_count = len(actionable_issues) - 6
        if remaining_count > 0:
            message_lines.append(f"... and {remaining_count:,} more issue(s) in the preview details.")
        message_lines.append("")
        message_lines.append(
            "Continue anyway?"
            if any(issue.status == ImportIssueStatus.REQUIRES_MANUAL_REVIEW.value for issue in actionable_issues)
            else "Continue with the import?"
        )

        prompt = QMessageBox(self)
        prompt.setIcon(QMessageBox.Warning)
        prompt.setWindowTitle(
            "Review Import Compatibility"
            if any(issue.status == ImportIssueStatus.REQUIRES_MANUAL_REVIEW.value for issue in actionable_issues)
            else "Review Import Warnings"
        )
        prompt.setText("\n".join(message_lines))
        prompt.setStandardButtons(QMessageBox.Yes | QMessageBox.No)
        prompt.setDefaultButton(QMessageBox.No)
        yes_button = prompt.button(QMessageBox.Yes)
        if yes_button is not None:
            yes_button.setText(
                "Patch Anyway" if destination == "patch" else "Export Anyway"
            )
        no_button = prompt.button(QMessageBox.No)
        if no_button is not None:
            no_button.setText("Cancel")
        if prompt.exec() != QMessageBox.Yes:
            return False
        return True

    def _attach_archive_model_preview_images(self, preview_model: Optional[object]) -> None:
        if preview_model is None:
            return
        meshes = getattr(preview_model, "meshes", None)
        if not meshes:
            return
        for mesh in meshes:
            texture_slots = (
                ("preview_texture_path", "preview_texture_image"),
                ("preview_normal_texture_path", "preview_normal_texture_image"),
                ("preview_material_texture_path", "preview_material_texture_image"),
                ("preview_height_texture_path", "preview_height_texture_image"),
            )
            for path_attr, image_attr in texture_slots:
                preview_texture_path = str(getattr(mesh, path_attr, "") or "").strip()
                if not preview_texture_path or getattr(mesh, image_attr, None) is not None:
                    continue
                reader = QImageReader(preview_texture_path)
                image = reader.read()
                if image.isNull():
                    continue
                setattr(mesh, image_attr, image)

    def _prompt_archive_mesh_related_file_selection(
        self,
        entry: ArchiveEntry,
        *,
        title: str,
        intro_text: str,
        confirm_button_text: str,
        default_checked: bool = True,
        parent: Optional[QWidget] = None,
        ) -> Optional[Tuple[ArchiveEntry, ...]]:
        references = self._current_archive_related_references_for_entry(entry)
        return self._prompt_archive_reference_selection(
            title=title,
            intro_text=intro_text,
            references=references,
            confirm_button_text=confirm_button_text,
            default_checked=default_checked,
            parent=parent,
        )

    def _prompt_archive_mesh_import_supplemental_files(
        self,
        entry: ArchiveEntry,
        *,
        title: str,
        ) -> Optional[Tuple[Path, ...]]:
        decision = QMessageBox.question(
            self,
            title,
            (
                f"Do you want to add local supplemental files for {entry.basename}?\n\n"
                "Supported files:\n"
                "  - .png / .jpg / .jpeg replacement texture sources for static scene imports\n"
                "  - .dds texture overrides\n"
                "  - .xml / .pac_xml PAC material sidecars\n"
                "  - .pami PAM material sidecars\n\n"
                "Selected files will be used for rebuilt preview, and mapped files can also be included in the loose export package."
            ),
            QMessageBox.Yes | QMessageBox.No | QMessageBox.Cancel,
            QMessageBox.No,
        )
        if decision == QMessageBox.Cancel:
            return None
        if decision != QMessageBox.Yes:
            return ()

        source_dialog = QMessageBox(self)
        source_dialog.setWindowTitle(title)
        source_dialog.setIcon(QMessageBox.Question)
        source_dialog.setText("Select supplemental files or a folder?")
        source_dialog.setInformativeText(
            "Use a folder when replacement textures are already grouped together, such as a Blender export texture folder."
        )
        files_button = source_dialog.addButton("Select Files", QMessageBox.AcceptRole)
        folder_button = source_dialog.addButton("Select Folder", QMessageBox.ActionRole)
        source_dialog.addButton(QMessageBox.Cancel)
        source_dialog.setDefaultButton(files_button)
        source_dialog.exec()
        clicked_source = source_dialog.clickedButton()
        supported_suffixes = set(SCENE_TEXTURE_SOURCE_EXTENSIONS) | {
            ".xml",
            ".pami",
            ".pac_xml",
            ".pam_xml",
            ".pamlod_xml",
            ".app_xml",
            ".prefabdata_xml",
        }
        if clicked_source == folder_button:
            selected_dir = QFileDialog.getExistingDirectory(
                self,
                title,
                str(self.settings_file_path.parent),
            )
            if not selected_dir:
                return ()
            return tuple(
                path
                for path in sorted(Path(selected_dir).rglob("*"))
                if path.is_file() and path.suffix.lower() in supported_suffixes
            )
        if clicked_source != files_button:
            return None

        selected_files, _selected_filter = QFileDialog.getOpenFileNames(
            self,
            title,
            str(self.settings_file_path.parent),
            "Supplemental Files (*.png *.jpg *.jpeg *.dds *.xml *.pami *.pac_xml *.pam_xml *.pamlod_xml *.app_xml *.prefabdata_xml);;Texture Sources (*.png *.jpg *.jpeg *.dds);;DDS Files (*.dds);;Image Files (*.png *.jpg *.jpeg);;Material Sidecars (*.xml *.pami *.pac_xml *.pam_xml *.pamlod_xml *.app_xml *.prefabdata_xml)",
        )
        if not selected_files:
            return ()
        return tuple(Path(path) for path in selected_files if path)

    @staticmethod
    def _archive_mesh_import_file_filter() -> str:
        return (
            "Mesh Files (*.obj *.dae *.gltf *.glb *.pac *.pam *.pamlod);;"
            "Wavefront OBJ (*.obj);;"
            "Collada DAE (*.dae);;"
            "glTF / GLB (*.gltf *.glb);;"
            "Local Game Mesh (*.pac *.pam *.pamlod)"
        )

    @staticmethod
    def _has_valid_obj_roundtrip_sidecar(scene_path: Path) -> bool:
        candidate = Path(f"{scene_path}.meta.json")
        if not candidate.is_file():
            return False
        try:
            payload = json.loads(candidate.read_text(encoding="utf-8"))
        except Exception:
            return False
        if not isinstance(payload, dict):
            return False
        payload_format = str(payload.get("format", "") or "").strip()
        return not payload_format or payload_format in {"obj_meta_v1", "mesh_roundtrip_manifest_v2"}

    @staticmethod
    def _obj_roundtrip_source_matches_entry(scene_path: Path, entry: ArchiveEntry) -> bool:
        candidate = Path(f"{scene_path}.meta.json")
        if not candidate.is_file():
            return False
        try:
            payload = json.loads(candidate.read_text(encoding="utf-8"))
        except Exception:
            return False
        if not isinstance(payload, dict):
            return False
        source_path = str(payload.get("source_path", "") or "").replace("\\", "/").strip().strip("/")
        entry_path = str(getattr(entry, "path", "") or "").replace("\\", "/").strip().strip("/")
        return bool(source_path and entry_path and source_path.lower() == entry_path.lower())

__all__ = ["ArchiveMeshDirectPatchMixin"]
