"""Archive mesh import and in-game swap launch flow."""
from __future__ import annotations

import dataclasses
from collections.abc import Callable
from pathlib import Path, PurePosixPath
from typing import List, Optional, Tuple

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QFileDialog, QMessageBox, QProgressDialog

from cdmw.core.archive import read_archive_entry_data
from cdmw.core.archive_modding import (
    ArchiveLooseExportResult,
    ArchivePatchRequest,
    MeshImportPreviewResult,
    MeshImportSupplementalFileSpec,
    build_mesh_import_preview,
    export_archive_mesh_payloads_to_mod_ready_loose,
    parsed_mesh_to_preview_model,
)
from cdmw.core.archive_relationships import SWAP_SCOPE_BODY_HEAD, build_character_swap_plan
from cdmw.domain.mesh.session import InGameMeshSwapScopeSelection
from cdmw.models import ArchiveEntry
from cdmw.modding.scene_importer import SceneImportResult
from cdmw.modding.static_mesh_replacer import StaticMeshReplacementOptions
from cdmw.ui.archive_browser.mesh_import_setup_state import (
    direct_source_model_swap_incomplete_payload_status,
    direct_source_model_swap_task_status,
    direct_source_model_swap_unexpected_payload_status,
    direct_source_model_swap_written_status,
    in_game_mesh_swap_progress_text,
    in_game_mesh_swap_same_source_status,
    mesh_import_file_dialog_title,
    mesh_import_preview_cancelled_status,
    mesh_import_preview_rebuild_task_status,
    mesh_import_preview_rebuilt_status,
    mesh_import_preview_unexpected_payload_status,
    mesh_import_replacement_mode_log,
    mesh_import_setup_dialog_title,
    pending_in_game_mesh_swap_cancelled_status,
    pending_in_game_mesh_swap_target_status,
)


class ArchiveMeshLaunchFlowMixin:
    def _build_in_game_mesh_swap_extra_specs(
        self,
        target_entry: ArchiveEntry,
        source_entry: ArchiveEntry,
        scope: InGameMeshSwapScopeSelection,
    ) -> Tuple[MeshImportSupplementalFileSpec, ...]:
        specs: List[MeshImportSupplementalFileSpec] = []
        selected_entries = list(scope.companion_entries or ())
        if scope.use_character_swap_plan:
            try:
                character_plan = build_character_swap_plan(
                    target_entry,
                    source_entry,
                    self.archive_entries,
                    swap_scope=SWAP_SCOPE_BODY_HEAD,
                )
            except Exception:
                character_plan = None
            patched_payload = bytes(getattr(character_plan, "patched_target_app_xml", b"") or b"")
            patched_target_path = str(getattr(character_plan, "patched_target_app_path", "") or "").strip()
            if patched_payload and patched_target_path:
                target_app = None
                for candidate in tuple(self.archive_entries_by_normalized_path.get(patched_target_path.lower(), ()) or ()):
                    target_app = candidate
                    break
                specs.append(
                    MeshImportSupplementalFileSpec(
                        source_path=Path(PurePosixPath(patched_target_path).name),
                        target_path=patched_target_path,
                        kind="file",
                        target_entry=target_app,
                        used_for_preview=False,
                        payload_data=patched_payload,
                        note="Surgical Character Swap Plan appearance patch: body/head source prefabs with target hair/armor preserved",
                    )
                )
        if scope.replace_target_sidecar_with_source:
            selected_sidecars = [entry for entry in selected_entries if self._archive_entry_is_material_sidecar(entry)]
            if not selected_sidecars:
                selected_sidecars = list(self._archive_model_sidecar_entries_for_swap(source_entry))[:1]
            for source_sidecar in selected_sidecars:
                try:
                    payload_data, _decompressed, _note = read_archive_entry_data(source_sidecar)
                except Exception:
                    continue
                target_path, target_sidecar = self._target_sidecar_path_for_source_sidecar(target_entry, source_sidecar)
                specs.append(
                    MeshImportSupplementalFileSpec(
                        source_path=Path(PurePosixPath(source_sidecar.path.replace("\\", "/")).name),
                        target_path=target_path,
                        kind="sidecar",
                        target_entry=target_sidecar,
                        used_for_preview=False,
                        payload_data=payload_data,
                        note=f"Source material sidecar copied from {source_sidecar.path}",
                    )
                )
        replaced_source_sidecar_paths = {
            str(getattr(spec, "note", "") or "").replace("Source material sidecar copied from ", "")
            for spec in specs
            if spec.kind == "sidecar"
        }
        if scope.replace_target_appearance_with_source:
            selected_appearances = [
                entry for entry in selected_entries if self._archive_entry_is_appearance_descriptor(entry)
            ]
            if not selected_appearances:
                selected_appearances = list(self._archive_character_appearance_entries_for_swap(source_entry))[:1]
            for source_appearance in selected_appearances:
                try:
                    payload_data, _decompressed, _note = read_archive_entry_data(source_appearance)
                except Exception:
                    continue
                target_path, target_appearance = self._target_appearance_path_for_source_appearance(
                    target_entry,
                    source_appearance,
                )
                if not target_path:
                    continue
                specs.append(
                    MeshImportSupplementalFileSpec(
                        source_path=Path(PurePosixPath(source_appearance.path.replace("\\", "/")).name),
                        target_path=target_path,
                        kind="file",
                        target_entry=target_appearance,
                        used_for_preview=False,
                        payload_data=payload_data,
                        note=f"Source appearance descriptor copied from {source_appearance.path}",
                    )
                )
        replaced_source_appearance_paths = {
            str(getattr(spec, "note", "") or "").replace("Source appearance descriptor copied from ", "")
            for spec in specs
            if "Source appearance descriptor copied from " in str(getattr(spec, "note", "") or "")
        }
        for source_companion in selected_entries:
            if source_companion.path in replaced_source_sidecar_paths:
                continue
            if source_companion.path in replaced_source_appearance_paths:
                continue
            if scope.complete_swap and self._archive_entry_is_material_sidecar(source_companion):
                continue
            if scope.complete_swap and self._archive_entry_is_appearance_descriptor(source_companion):
                continue
            try:
                payload_data, _decompressed, _note = read_archive_entry_data(source_companion)
            except Exception:
                continue
            target_path = source_companion.path
            target_entry_for_spec: Optional[ArchiveEntry] = source_companion
            if scope.retarget_source_family_files:
                target_path, target_entry_for_spec = self._target_family_path_for_source_companion(
                    target_entry,
                    source_entry,
                    source_companion,
                )
            kind = (
                "texture"
                if source_companion.extension == ".dds"
                else "sidecar"
                if self._archive_entry_is_material_sidecar(source_companion)
                else "file"
            )
            specs.append(
                MeshImportSupplementalFileSpec(
                    source_path=Path(PurePosixPath(source_companion.path.replace("\\", "/")).name),
                    target_path=target_path,
                    kind=kind,
                    target_entry=target_entry_for_spec,
                    used_for_preview=False,
                    payload_data=payload_data,
                    note=(
                        f"Source companion replacement payload from {source_companion.path} -> {target_path}"
                        if source_companion.extension in {".pab", ".hkx", ".hkt"}
                        else f"Source companion copied from {source_companion.path} -> {target_path}"
                    ),
                )
            )
        return tuple(specs)

    def _start_archive_direct_source_model_swap(
        self,
        target_entry: ArchiveEntry,
        source_entry: ArchiveEntry,
        scene_import_result: SceneImportResult,
        scope: InGameMeshSwapScopeSelection,
    ) -> None:
        loose_export_settings = self._collect_archive_mod_ready_export_target(
            browse_title="Select Mod-Ready Export Parent Root",
            prompt_for_metadata=True,
            initial_include_related_files=False,
            show_include_related_files_option=False,
            dialog_title="Direct In-Game Source Swap Export",
            allow_dmm_texture_structure=False,
            show_active_file_authority_audit_option=True,
        )
        if loose_export_settings is None:
            return
        extra_specs = self._build_in_game_mesh_swap_extra_specs(target_entry, source_entry, scope)

        def _task(log: Callable[[str], None]) -> object:
            log(f"Reading source model payload: {source_entry.path}")
            source_payload, _decompressed, _note = read_archive_entry_data(source_entry)
            preview_model = parsed_mesh_to_preview_model(scene_import_result.mesh)
            preview_result = MeshImportPreviewResult(
                rebuilt_data=source_payload,
                parsed_mesh=scene_import_result.mesh,
                preview_model=preview_model,
                summary_lines=[
                    f"Direct source model payload: {source_entry.path}",
                    f"Target model path: {target_entry.path}",
                    "Alignment transform was not applied. This mode preserves the donor model/material/physics contract better than a rebuilt target-slot mesh.",
                ],
                import_mode="direct_source_model_swap",
                supplemental_file_specs=tuple(extra_specs),
            )
            parent_root, package_info, create_no_encrypt, include_related_files, export_options = loose_export_settings
            request = ArchivePatchRequest(entry=target_entry, payload_data=source_payload)
            log(f"Writing direct source model swap package for {target_entry.path}...")
            loose_result = export_archive_mesh_payloads_to_mod_ready_loose(
                (request,),
                primary_entry=target_entry,
                preview_result=preview_result,
                source_obj_path=self._archive_mesh_source_scene_path(source_entry),
                source_display_label=self._archive_mesh_source_label(source_entry),
                parent_root=parent_root,
                package_info=package_info,
                export_options=export_options,
                create_no_encrypt_file=create_no_encrypt,
                include_related_files=include_related_files,
                related_entries_to_include=(),
                supplemental_files_to_include=tuple(extra_specs),
                on_log=log,
            )
            return {"preview": preview_result, "loose": loose_result}

        def _handle_complete(result: object) -> None:
            if not isinstance(result, dict):
                self.set_status_message(direct_source_model_swap_unexpected_payload_status(), error=True)
                return
            preview_result = result.get("preview")
            loose_result = result.get("loose")
            if not isinstance(preview_result, MeshImportPreviewResult) or not isinstance(loose_result, ArchiveLooseExportResult):
                self.set_status_message(direct_source_model_swap_incomplete_payload_status(), error=True)
                return
            self._show_archive_import_preview(target_entry, preview_result, patched=False)
            self.set_status_message(
                direct_source_model_swap_written_status(target_entry.basename, loose_result.package_root),
            )

        self._run_utility_task(
            status_message=direct_source_model_swap_task_status(target_entry.basename),
            task=_task,
            on_complete=_handle_complete,
            show_archive_progress=True,
        )

    def _handle_archive_in_game_mesh_swap_entry(self, entry: ArchiveEntry) -> None:
        pending_target = self.pending_in_game_mesh_swap_target
        if pending_target is None:
            self.pending_in_game_mesh_swap_target = entry
            self.set_status_message(
                pending_in_game_mesh_swap_target_status(entry.basename)
            )
            self._update_archive_model_action_controls(self._archive_model_preview_controls_target())
            return
        if self._same_archive_entry(entry, pending_target):
            self.pending_in_game_mesh_swap_target = None
            self.set_status_message(pending_in_game_mesh_swap_cancelled_status())
            self._update_archive_model_action_controls(self._archive_model_preview_controls_target())
            return
        self._start_archive_in_game_mesh_swap(pending_target, entry)

    def _start_archive_mesh_import_preview(self, entry: ArchiveEntry) -> None:
        scene_path, _selected = QFileDialog.getOpenFileName(
            self,
            mesh_import_file_dialog_title(),
            str(self.settings_file_path.parent),
            self._archive_mesh_import_file_filter(),
        )
        if not scene_path:
            return
        setup = self._prompt_archive_mesh_import_setup(
            entry,
            Path(scene_path),
            title=mesh_import_setup_dialog_title(),
        )
        if setup is None:
            return
        scene_path_obj = setup.scene_path
        import_mode = setup.import_mode
        self._open_mesh_editor_for_entry(
            entry,
            mode="external_import",
            source_path=scene_path_obj,
            supplemental_files=setup.supplemental_files,
            scene_import_result=setup.scene_import_result,
            activate=True,
        )
        if scene_path_obj.suffix.lower() in {".dae", ".gltf", ".glb", ".pac", ".pam", ".pamlod"}:
            self.append_archive_log(mesh_import_replacement_mode_log(scene_path_obj.suffix))

        def _start_import_preview_with_options(static_replacement_options: Optional[StaticMeshReplacementOptions]) -> None:
            supplemental_files = setup.supplemental_files
            if static_replacement_options is not None:
                supplemental_files = tuple(supplemental_files or ()) + tuple(
                    path
                    for path in getattr(static_replacement_options, "additional_supplemental_files", ()) or ()
                    if isinstance(path, Path)
                )
            texconv_text = self.texconv_path_edit.text().strip()

            def _task(log: Callable[[str], None]) -> MeshImportPreviewResult:
                log(f"Rebuilding {entry.path} from {scene_path_obj.name}...")
                preview_settings = self._current_model_preview_render_settings()
                return build_mesh_import_preview(
                    entry,
                    scene_path_obj,
                    import_mode=import_mode,
                    static_replacement_options=static_replacement_options,
                    scene_import_result=setup.scene_import_result,
                    source_display_label=setup.source_label,
                    archive_entries_by_normalized_path=self.archive_entries_by_normalized_path,
                    texconv_path=(Path(texconv_text).expanduser() if texconv_text else None),
                    texture_entries_by_normalized_path=self.archive_entries_by_normalized_path,
                    texture_entries_by_basename=self.archive_entries_by_basename,
                    visible_texture_mode=preview_settings.visible_texture_mode,
                    supplemental_files=supplemental_files,
                )

            def _handle_complete(result: object) -> None:
                if not isinstance(result, MeshImportPreviewResult):
                    self.set_status_message(mesh_import_preview_unexpected_payload_status(), error=True)
                    return
                self._show_archive_import_preview(entry, result, patched=False)
                self.set_status_message(mesh_import_preview_rebuilt_status(entry.basename))

            self._run_utility_task(
                status_message=mesh_import_preview_rebuild_task_status(entry.basename),
                task=_task,
                on_complete=_handle_complete,
                show_archive_progress=True,
            )

        if import_mode == "static_replacement":
            self._prompt_archive_static_replacement_options(
                entry,
                scene_path_obj,
                supplemental_files=setup.supplemental_files,
                import_diagnostics=(
                    tuple(setup.preflight.detail_lines[:6]) if setup.preflight is not None else ()
                ),
                scene_import_result=setup.scene_import_result,
                original_mesh=setup.original_mesh,
                preferred_rebuild_material_sidecar=setup.preferred_rebuild_material_sidecar,
                preferred_complete_source_swap=bool(setup.preferred_complete_source_swap),
                source_texture_evidence=setup.source_texture_evidence,
                extra_supplemental_specs=setup.extra_supplemental_specs,
                on_accept=_start_import_preview_with_options,
                on_cancel=lambda: self.set_status_message(mesh_import_preview_cancelled_status()),
            )
            return

        _start_import_preview_with_options(None)

    def _start_archive_in_game_mesh_swap(self, target_entry: ArchiveEntry, source_entry: ArchiveEntry) -> None:
        if self._same_archive_entry(target_entry, source_entry):
            self.set_status_message(in_game_mesh_swap_same_source_status(), error=True)
            return
        self._open_mesh_editor_for_entry(
            target_entry,
            mode="in_game_swap",
            source_entry=source_entry,
            activate=True,
        )
        swap_scope = self._prompt_archive_in_game_mesh_swap_scope(target_entry, source_entry)
        if swap_scope is None:
            return
        progress_text = in_game_mesh_swap_progress_text()
        progress = QProgressDialog(progress_text["label"], "", 0, 0, self)
        progress.setWindowTitle(progress_text["title"])
        progress.setCancelButton(None)
        progress.setMinimumDuration(0)
        progress.setAutoClose(False)
        progress.setWindowModality(Qt.WindowModal)
        progress.show()
        QApplication.processEvents()
        try:
            scene_import_result = self._load_archive_mesh_scene_import_result(source_entry)
        except Exception as exc:
            progress.close()
            QApplication.processEvents()
            QMessageBox.warning(
                self,
                "In-Game Mesh Source Unsupported",
                f"{source_entry.path} could not be parsed as a replacement mesh.\n\n{exc}",
            )
            return
        source_texture_paths, source_texture_evidence = self._build_archive_swap_source_texture_evidence(source_entry)
        if source_texture_paths:
            scene_import_result = dataclasses.replace(
                scene_import_result,
                discovered_texture_files=tuple(source_texture_paths),
                diagnostics=tuple(scene_import_result.diagnostics)
                + (f"Found {len(source_texture_paths):,} source DDS texture candidate(s) from source .pac_xml/sidecars.",),
            )
        progress.close()
        QApplication.processEvents()

        if swap_scope.use_source_model_payload_directly:
            self.pending_in_game_mesh_swap_target = None
            self._update_archive_model_action_controls(self._archive_model_preview_controls_target())
            self._start_archive_direct_source_model_swap(
                target_entry,
                source_entry,
                scene_import_result,
                swap_scope,
            )
            return

        swap_placement_note = (
            "Review offset, rotation, scale, and part mapping before export. "
            "In-game swap sources can differ in origin, facing direction, scale, or bone-relative placement."
        )
        setup = self._prompt_archive_mesh_import_setup(
            target_entry,
            self._archive_mesh_source_scene_path(source_entry),
            title="In-Game Mesh Swap Setup",
            scene_import_result=scene_import_result,
            source_label=self._archive_mesh_source_label(source_entry),
            force_static_replacement=True,
            placement_review_title="In-Game Mesh Swap Placement",
            placement_context_note=swap_placement_note,
        )
        if setup is None:
            return
        setup.preferred_rebuild_material_sidecar = bool(swap_scope.prefer_generated_sidecar or swap_scope.complete_swap)
        setup.preferred_complete_source_swap = bool(swap_scope.complete_swap)
        setup.source_texture_evidence = tuple(source_texture_evidence)
        setup.extra_supplemental_specs = self._build_in_game_mesh_swap_extra_specs(
            target_entry,
            source_entry,
            swap_scope,
        )
        self.pending_in_game_mesh_swap_target = None
        self._update_archive_model_action_controls(self._archive_model_preview_controls_target())
        self._start_archive_mesh_patch(target_entry, preset_setup=setup)
