"""Archive mesh DDS import preview helpers."""
from __future__ import annotations

import dataclasses
from collections.abc import Callable
from pathlib import Path
from typing import Optional, Tuple

from PySide6.QtWidgets import QFileDialog, QInputDialog

from cdmw.core.archive import (
    _infer_model_preview_normal_strength,
    _resolve_model_texture_semantic_details,
    build_archive_preview_result,
)
from cdmw.core.texture_pipeline.inspection import parse_dds
from cdmw.core.texture_pipeline.preview import ensure_dds_display_preview_png
from cdmw.models import ArchiveEntry, ArchiveModelTextureReference, ArchivePreviewResult, ModelPreviewData, ModelPreviewMesh


class ArchiveMeshDdsPreviewMixin:
    def _preview_slot_label(slot: str) -> str:
        normalized_slot = str(slot or "").strip().lower()
        return {
            "base": "Base",
            "normal": "Normal",
            "material": "Material",
            "height": "Height",
        }.get(normalized_slot, normalized_slot.title() or "Preview")

    def _build_local_dds_preview_override_path(
        self,
        source_path: Path,
        *,
        texconv_path: Optional[Path] = None,
    ) -> str:
        resolved_texconv_path = texconv_path
        if resolved_texconv_path is None:
            texconv_text = self.texconv_path_edit.text().strip()
            resolved_texconv_path = Path(texconv_text).expanduser() if texconv_text else None
        if resolved_texconv_path is not None and not resolved_texconv_path.is_file():
            resolved_texconv_path = None
        resolved_source = source_path.expanduser().resolve()
        if not resolved_source.is_file():
            raise FileNotFoundError(f"Imported DDS was not found: {resolved_source}")
        dds_info = parse_dds(resolved_source)
        preview_path = ensure_dds_display_preview_png(
            resolved_texconv_path.resolve() if resolved_texconv_path is not None else None,
            resolved_source,
            dds_info=dds_info,
        )
        return str(preview_path)

    def _apply_archive_entry_dds_preview_to_model(
        self,
        preview_model: Optional[object],
        *,
        slot: str,
        preview_path: str,
        texture_name: str,
        semantic_reference_path: str,
    ) -> bool:
        normalized_slot = str(slot or "").strip().lower()
        if normalized_slot not in {"base", "normal", "material", "height"}:
            return False
        preview_path_text = str(preview_path or "").strip()
        texture_name_text = str(texture_name or "").strip()
        if not preview_path_text or not isinstance(preview_model, ModelPreviewData):
            return False
        meshes = [
            mesh
            for mesh in (getattr(preview_model, "meshes", None) or [])
            if isinstance(mesh, ModelPreviewMesh)
        ]
        if not meshes:
            return False

        texture_type, semantic_subtype, _confidence, packed_channels = _resolve_model_texture_semantic_details(
            semantic_reference_path,
        )
        packed_channels_tuple = tuple(
            str(channel or "").strip().lower()
            for channel in packed_channels
            if str(channel or "").strip()
        )
        changed = False
        for mesh in meshes:
            if normalized_slot == "base":
                if str(getattr(mesh, "preview_texture_path", "") or "").strip() != preview_path_text:
                    mesh.preview_texture_path = preview_path_text
                    mesh.preview_texture_image = None
                    changed = True
                if str(getattr(mesh, "texture_name", "") or "").strip() != texture_name_text:
                    mesh.texture_name = texture_name_text
                    changed = True
                if getattr(mesh, "preview_texture_flip_vertical", None) is not False:
                    mesh.preview_texture_flip_vertical = False
                    changed = True
                continue
            if normalized_slot == "normal":
                material_name = str(getattr(mesh, "material_name", "") or "").strip()
                base_texture_name = str(getattr(mesh, "texture_name", "") or "").strip()
                normal_strength = _infer_model_preview_normal_strength(
                    base_texture_path=base_texture_name,
                    normal_texture_path=semantic_reference_path,
                    material_name=material_name,
                    prefer_stronger=True,
                )
                if str(getattr(mesh, "preview_normal_texture_path", "") or "").strip() != preview_path_text:
                    mesh.preview_normal_texture_path = preview_path_text
                    mesh.preview_normal_texture_image = None
                    changed = True
                if str(getattr(mesh, "preview_normal_texture_name", "") or "").strip() != texture_name_text:
                    mesh.preview_normal_texture_name = texture_name_text
                    changed = True
                if abs(float(getattr(mesh, "preview_normal_texture_strength", 0.0) or 0.0) - float(normal_strength)) > 1e-6:
                    mesh.preview_normal_texture_strength = float(normal_strength)
                    changed = True
                continue
            if normalized_slot == "material":
                if str(getattr(mesh, "preview_material_texture_path", "") or "").strip() != preview_path_text:
                    mesh.preview_material_texture_path = preview_path_text
                    mesh.preview_material_texture_image = None
                    changed = True
                if str(getattr(mesh, "preview_material_texture_name", "") or "").strip() != texture_name_text:
                    mesh.preview_material_texture_name = texture_name_text
                    changed = True
                if str(getattr(mesh, "preview_material_texture_type", "") or "").strip().lower() != str(texture_type or "").strip().lower():
                    mesh.preview_material_texture_type = str(texture_type or "").strip().lower()
                    changed = True
                if str(getattr(mesh, "preview_material_texture_subtype", "") or "").strip().lower() != str(semantic_subtype or "").strip().lower():
                    mesh.preview_material_texture_subtype = str(semantic_subtype or "").strip().lower()
                    changed = True
                if tuple(
                    str(channel or "").strip().lower()
                    for channel in (getattr(mesh, "preview_material_texture_packed_channels", ()) or ())
                    if str(channel or "").strip()
                ) != packed_channels_tuple:
                    mesh.preview_material_texture_packed_channels = packed_channels_tuple
                    changed = True
                continue
            if str(getattr(mesh, "preview_height_texture_path", "") or "").strip() != preview_path_text:
                mesh.preview_height_texture_path = preview_path_text
                mesh.preview_height_texture_image = None
                changed = True
            if str(getattr(mesh, "preview_height_texture_name", "") or "").strip() != texture_name_text:
                mesh.preview_height_texture_name = texture_name_text
                changed = True
        return changed

    def _build_archive_mesh_dds_import_preview_result(
        self,
        entry: ArchiveEntry,
        source_path: Path,
        slot: str,
        *,
        texconv_path: Optional[Path],
        companion_entry: Optional[ArchiveEntry],
        visible_texture_mode: str,
    ) -> ArchivePreviewResult:
        normalized_slot = str(slot or "").strip().lower()
        slot_label = self._preview_slot_label(normalized_slot)
        resolved_source_path = source_path.expanduser().resolve()
        preview_result = build_archive_preview_result(
            texconv_path,
            entry,
            companion_entry=companion_entry,
            texture_entries_by_normalized_path=self.archive_entries_by_normalized_path,
            texture_entries_by_basename=self.archive_entries_by_basename,
            sidecar_entries_by_texture_path=self.archive_sidecar_entries_by_texture_path,
            sidecar_entries_by_texture_basename=self.archive_sidecar_entries_by_texture_basename,
            visible_texture_mode=visible_texture_mode,
        )
        preview_model = self._clone_archive_preview_model(preview_result.preview_model, strip_images=False)
        if not isinstance(preview_model, ModelPreviewData) or not getattr(preview_model, "meshes", None):
            failure_reason = (
                str(preview_result.warning_text or "").strip()
                or str(preview_result.detail_text or "").strip()
                or "No renderable model preview is available."
            )
            raise RuntimeError(f"Could not prepare a model preview for {entry.basename}: {failure_reason}")

        preview_path = self._build_local_dds_preview_override_path(
            resolved_source_path,
            texconv_path=texconv_path,
        )
        applied = self._apply_archive_entry_dds_preview_to_model(
            preview_model,
            slot=normalized_slot,
            preview_path=preview_path,
            texture_name=resolved_source_path.name,
            semantic_reference_path=str(resolved_source_path),
        )
        if not applied:
            raise RuntimeError(
                f"Could not apply the imported DDS to the {slot_label.lower()} preview slot for {entry.basename}."
            )

        detail_text = "\n\n".join(
            part
            for part in (
                str(preview_result.detail_text or "").strip(),
                "\n".join(
                    [
                        "DDS Import Preview:",
                        f"Selected DDS: {resolved_source_path.name}",
                        f"Selected slot: {slot_label}",
                    ]
                ),
            )
            if part
        )
        warning_text = "This DDS preview has not been written back to the game archives yet."
        existing_warning = str(preview_result.warning_text or "").strip()
        if existing_warning:
            warning_text = f"{warning_text}\n{existing_warning}"
        return dataclasses.replace(
            preview_result,
            detail_text=detail_text,
            preview_model=preview_model,
            preferred_view="model",
            warning_badge="Import preview",
            warning_text=warning_text,
            loose_file_path="",
            loose_preview_image_path="",
            loose_preview_image=None,
            loose_preview_media_path="",
            loose_preview_media_kind="",
            loose_preview_title="",
            loose_preview_metadata_summary="",
            loose_preview_detail_text="",
        )

    def _show_archive_dds_import_preview_result(
        self,
        preview_result: ArchivePreviewResult,
        *,
        enable_high_quality: bool,
    ) -> None:
        result_with_images = self._attach_archive_preview_result_images(preview_result)
        self.archive_preview_requested_loose = False
        self.current_archive_preview_result = result_with_images
        self._show_archive_preview_result(result_with_images, use_loose=False)
        active_preview = self._active_archive_model_preview_widget()
        if result_with_images.preview_model is None or active_preview is None:
            return
        if hasattr(active_preview, "textures_available") and active_preview.textures_available():
            active_preview.set_use_textures(True)
            if enable_high_quality:
                active_preview.set_high_quality_textures(True)
        self._sync_current_archive_preview_model_from_widget()
        self._sync_archive_model_preview_debug_controls(self._archive_model_preview_controls_target())
        self._refresh_archive_preview_details_text()

    def _start_archive_mesh_dds_import_preview(self, entry: ArchiveEntry) -> None:
        source_path, _selected = QFileDialog.getOpenFileName(
            self,
            "Select DDS File",
            str(self.settings_file_path.parent),
            "DDS (*.dds)",
        )
        if not source_path:
            return
        slot_labels = ["Base", "Normal", "Material", "Height"]
        selected_slot_label, accepted = QInputDialog.getItem(
            self,
            "Preview Slot",
            "Apply the imported DDS to which preview slot?",
            slot_labels,
            0,
            False,
        )
        if not accepted or not selected_slot_label:
            return

        resolved_source_path = Path(source_path).expanduser().resolve()
        normalized_slot = str(selected_slot_label or "").strip().lower()
        texconv_text = self.texconv_path_edit.text().strip()
        texconv_path = Path(texconv_text).expanduser() if texconv_text else None
        companion_entry = self._find_archive_preview_companion_entry(entry)
        preview_settings = self._current_model_preview_render_settings()

        def _task(log: Callable[[str], None]) -> ArchivePreviewResult:
            log(f"Preparing DDS import preview for {entry.path} using {resolved_source_path.name}...")
            return self._build_archive_mesh_dds_import_preview_result(
                entry,
                resolved_source_path,
                normalized_slot,
                texconv_path=texconv_path,
                companion_entry=companion_entry,
                visible_texture_mode=preview_settings.visible_texture_mode,
            )

        def _handle_complete(result: object) -> None:
            if not isinstance(result, ArchivePreviewResult):
                self.set_status_message("DDS import preview finished with an unexpected result payload.", error=True)
                return
            self._show_archive_dds_import_preview_result(
                result,
                enable_high_quality=normalized_slot in {"normal", "material", "height"},
            )
            self.set_status_message(
                f"Prepared {self._preview_slot_label(normalized_slot).lower()} DDS import preview for {entry.basename}.",
                error=False,
            )

        self._run_utility_task(
            status_message=f"Preparing DDS import preview for {entry.basename}...",
            task=_task,
            on_complete=_handle_complete,
            show_archive_progress=True,
        )

    def _current_archive_related_references_for_entry(
        self,
        entry: ArchiveEntry,
    ) -> Tuple[ArchiveModelTextureReference, ...]:
        current_entry = self._current_archive_entry()
        if current_entry is None:
            return ()
        current_path = current_entry.path.replace("\\", "/").strip().lower()
        target_path = entry.path.replace("\\", "/").strip().lower()
        if current_path != target_path:
            return ()
        return tuple(self.current_archive_model_texture_references)
