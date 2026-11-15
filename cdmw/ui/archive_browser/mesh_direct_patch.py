"""Archive mesh import preview and review helpers.

CDMW never writes into the game's archives; a replacement is always built as a mod.
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Optional

from PySide6.QtGui import QImageReader
from PySide6.QtWidgets import QMessageBox

from cdmw.domain.archives.mesh_contracts import MeshImportPreviewResult
from cdmw.services.preview_workflow_service import FinalPackagePreviewResult
from cdmw.models import ArchiveEntry, ArchivePreviewResult, ImportIssueStatus
from cdmw.services.preview_rendering_service import prepare_model_preview


class ArchiveMeshDirectPatchMixin:
    """Mesh import preview and review helpers."""

    def _show_archive_import_preview(
        self,
        entry: ArchiveEntry,
        import_result: MeshImportPreviewResult,
        *,
        patched: bool = False,
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
                detail_lines.append("Final output preflight blockers:")
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
        # ``patched`` stays for its callers; nothing is patched into the game any more.
        if loose_package_root is not None:
            detail_lines.append(f"Loose export: {loose_package_root}")
        warning_badge = ""
        warning_text = ""
        if loose_package_root is not None:
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
        else:
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
        destination: str = "loose",
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
            yes_button.setText("Export Anyway")
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
        references = self._archive_related_references_for_entry(entry)
        if references is None:
            self.shell.set_status_message(
                f"The referenced files of {entry.basename} are still being prepared. "
                "Preview it, then export again.",
                error=True,
            )
            return None
        return self._prompt_archive_reference_selection(
            title=title,
            intro_text=intro_text,
            references=references,
            confirm_button_text=confirm_button_text,
            default_checked=default_checked,
            parent=parent,
        )

    @staticmethod
    def _archive_mesh_import_file_filter() -> str:
        return (
            "Mesh Files (*.obj *.fbx *.dae *.gltf *.glb *.zip *.pac *.pam *.pamlod);;"
            "Wavefront OBJ (*.obj);;"
            "Autodesk FBX (*.fbx);;"
            "Collada DAE (*.dae);;"
            "glTF / GLB (*.gltf *.glb);;"
            "Model Archives (*.zip);;"
            "Local Game Mesh (*.pac *.pam *.pamlod)"
        )

    @staticmethod
    def _has_valid_obj_roundtrip_sidecar(scene_path: Path) -> bool:
        if scene_path.suffix.lower() in {".fbx", ".glb", ".gltf"}:
            from cdmw.services.mesh_workflow_service import _load_glb_roundtrip_sidecar
            try:
                _load_glb_roundtrip_sidecar(scene_path)
                return True
            except (ValueError, TypeError, OSError):
                return False
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
