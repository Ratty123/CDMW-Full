"""Archive mesh import and in-game swap launch flow."""
from __future__ import annotations

import dataclasses
import threading
from dataclasses import dataclass
from collections.abc import Callable
from pathlib import Path, PurePosixPath
from typing import List, Optional, Tuple

from PySide6.QtWidgets import QFileDialog, QMessageBox

from cdmw.services.archive_read_service import read_archive_entry_data
from cdmw.domain.archives.mesh_contracts import (
    ArchiveLooseExportResult,
    MeshImportPreviewResult,
    MeshImportSupplementalFileSpec,
)
from cdmw.services.archive_mutation_service import ArchivePatchRequest
from cdmw.services.preview_workflow_service import (
    build_mesh_import_preview,
    parsed_mesh_to_preview_model,
)
from cdmw.services.archive_workflow_service import export_archive_mesh_payloads_to_mod_ready_loose
from cdmw.domain.archives.relationships import SWAP_SCOPE_BODY_HEAD
from cdmw.services.archive_workflow_service import build_character_swap_plan
from cdmw.domain.cancellation import raise_if_cancelled
from cdmw.domain.mesh.session import InGameMeshSwapScopeSelection, MeshImportSetupSelection
from cdmw.models import ArchiveEntry
from cdmw.services.mesh_workflow_service import SceneImportResult
from cdmw.services.mesh_workflow_service import StaticMeshReplacementOptions
from cdmw.services.diagnostics_service import is_expected_cancellation_message
from cdmw.ui.archive_browser.mesh_swap_scope_preflight import (
    ArchiveMeshSwapScopePreflightRequest,
    ArchiveMeshSwapScopePreflightResult,
    prepare_archive_mesh_swap_scope,
)
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
from cdmw.ui.archive_browser.workflow_dependencies import (
    ArchiveWorkflowDependencyContext,
    ArchiveWorkflowDependenciesUnavailable,
    archive_workflow_dependency_context,
    merge_archive_workflow_dependency_contexts,
)


@dataclass(frozen=True, slots=True)
class ArchiveInGameMeshSwapPreparationRequest:
    request_id: int
    target_entry: ArchiveEntry
    source_entry: ArchiveEntry
    scope: InGameMeshSwapScopeSelection
    dependencies: ArchiveWorkflowDependencyContext


@dataclass(frozen=True, slots=True)
class ArchiveInGameMeshSwapPreparationResult:
    request_id: int
    scene_import_result: SceneImportResult
    source_texture_evidence: Tuple[object, ...]
    extra_specs: Tuple[MeshImportSupplementalFileSpec, ...]


class ArchiveMeshLaunchFlowMixin:
    def _build_in_game_mesh_swap_extra_specs(
        self,
        target_entry: ArchiveEntry,
        source_entry: ArchiveEntry,
        scope: InGameMeshSwapScopeSelection,
        *,
        dependencies: ArchiveWorkflowDependencyContext, stop_event: Optional[threading.Event] = None,
    ) -> Tuple[MeshImportSupplementalFileSpec, ...]:
        raise_if_cancelled(stop_event, "In-game mesh companion preparation cancelled.")
        specs: List[MeshImportSupplementalFileSpec] = []
        selected_entries = list(scope.companion_entries or ())
        if scope.use_character_swap_plan:
            try:
                character_plan = build_character_swap_plan(
                    target_entry,
                    source_entry,
                    dependencies.entries,
                    swap_scope=SWAP_SCOPE_BODY_HEAD,
                )
            except Exception:
                character_plan = None
            patched_payload = bytes(getattr(character_plan, "patched_target_app_xml", b"") or b"")
            patched_target_path = str(getattr(character_plan, "patched_target_app_path", "") or "").strip()
            if patched_payload and patched_target_path:
                target_app = None
                for candidate in tuple(dependencies.entries_by_normalized_path.get(patched_target_path.lower(), ()) or ()):
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
                selected_sidecars = list(self._archive_model_sidecar_entries_for_swap(source_entry, dependencies=dependencies))[:1]
            for source_sidecar in selected_sidecars:
                raise_if_cancelled(stop_event, "In-game mesh companion preparation cancelled.")
                try:
                    payload_data, _decompressed, _note = read_archive_entry_data(
                        source_sidecar,
                        stop_event=stop_event,
                    )
                except Exception:
                    continue
                target_path, target_sidecar = self._target_sidecar_path_for_source_sidecar(
                    target_entry, source_sidecar, dependencies=dependencies
                )
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
                selected_appearances = list(
                    self._archive_character_appearance_entries_for_swap(
                        source_entry, dependencies=dependencies, stop_event=stop_event
                    )
                )[:1]
            for source_appearance in selected_appearances:
                raise_if_cancelled(stop_event, "In-game mesh companion preparation cancelled.")
                try:
                    payload_data, _decompressed, _note = read_archive_entry_data(
                        source_appearance,
                        stop_event=stop_event,
                    )
                except Exception:
                    continue
                target_path, target_appearance = self._target_appearance_path_for_source_appearance(
                    target_entry, source_appearance, dependencies=dependencies
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
            raise_if_cancelled(stop_event, "In-game mesh companion preparation cancelled.")
            if source_companion.path in replaced_source_sidecar_paths:
                continue
            if source_companion.path in replaced_source_appearance_paths:
                continue
            if scope.complete_swap and self._archive_entry_is_material_sidecar(source_companion):
                continue
            if scope.complete_swap and self._archive_entry_is_appearance_descriptor(source_companion):
                continue
            try:
                payload_data, _decompressed, _note = read_archive_entry_data(
                    source_companion,
                    stop_event=stop_event,
                )
            except Exception:
                continue
            target_path = source_companion.path
            target_entry_for_spec: Optional[ArchiveEntry] = source_companion
            if scope.retarget_source_family_files:
                target_path, target_entry_for_spec = self._target_family_path_for_source_companion(
                    target_entry, source_entry, source_companion, dependencies=dependencies
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
        *,
        extra_specs: Tuple[MeshImportSupplementalFileSpec, ...],
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
        def _task(log: Callable[[str], None], stop_event: threading.Event) -> object:
            log(f"Reading source model payload: {source_entry.path}")
            source_payload, _decompressed, _note = read_archive_entry_data(
                source_entry,
                stop_event=stop_event,
            )
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
            task_accepts_cancel=True,
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

    def _start_archive_mesh_import_preview(
        self,
        entry: ArchiveEntry,
        *,
        preset_setup: Optional[MeshImportSetupSelection] = None,
    ) -> None:
        try:
            dependencies = archive_workflow_dependency_context(self, entry)
        except ArchiveWorkflowDependenciesUnavailable as exc:
            self.set_status_message(f"Mesh import preview is unavailable: {exc}", error=True)
            return
        entry = dependencies.selected_entry
        if preset_setup is None:
            scene_path, _selected = QFileDialog.getOpenFileName(
                self,
                mesh_import_file_dialog_title(),
                str(self.settings_file_path.parent),
                self._archive_mesh_import_file_filter(),
            )
            if not scene_path:
                return
            self._prepare_archive_mesh_import_setup_async(
                entry,
                Path(scene_path),
                title=mesh_import_setup_dialog_title(),
                on_complete=lambda setup: (
                    self._start_archive_mesh_import_preview(entry, preset_setup=setup)
                    if isinstance(setup, MeshImportSetupSelection)
                    else None
                ),
            )
            return
        else:
            setup = preset_setup
        scene_path_obj = setup.scene_path
        import_mode = setup.import_mode
        self._open_mesh_editor_for_entry(
            entry,
            mode="external_import",
            source_path=scene_path_obj,
            source_skeleton=setup.source_skeleton,
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
                    archive_entries_by_normalized_path=dependencies.entries_by_normalized_path,
                    texture_entries_by_normalized_path=dependencies.entries_by_normalized_path,
                    texture_entries_by_basename=dependencies.entries_by_basename,
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
                source_skeleton=setup.source_skeleton,
                original_mesh=setup.original_mesh,
                preferred_rebuild_material_sidecar=setup.preferred_rebuild_material_sidecar,
                preferred_complete_source_swap=bool(setup.preferred_complete_source_swap),
                source_texture_evidence=setup.source_texture_evidence,
                extra_supplemental_specs=setup.extra_supplemental_specs,
                embedded_host=self.mesh_editor_tab.builder_host() if hasattr(self, "mesh_editor_tab") else None,
                on_accept=_start_import_preview_with_options,
                on_cancel=lambda: self.set_status_message(mesh_import_preview_cancelled_status()),
            )
            return

        _start_import_preview_with_options(None)

    def _start_archive_in_game_mesh_swap(self, target_entry: ArchiveEntry, source_entry: ArchiveEntry) -> None:
        if self._same_archive_entry(target_entry, source_entry):
            self.set_status_message(in_game_mesh_swap_same_source_status(), error=True)
            return
        remote_bridge = getattr(self, "archive_remote_bridge", None)
        if remote_bridge is not None and bool(getattr(remote_bridge, "displays_v2", False)):
            try:
                target_dependencies = archive_workflow_dependency_context(self, target_entry)
                source_dependencies = archive_workflow_dependency_context(self, source_entry)
                dependencies = merge_archive_workflow_dependency_contexts(
                    target_entry,
                    target_dependencies,
                    source_dependencies,
                )
            except ArchiveWorkflowDependenciesUnavailable as exc:
                self.set_status_message(f"In-game mesh swap is unavailable: {exc}", error=True)
                return
            prepared_target = dependencies.entry_matching(target_entry)
            prepared_source = dependencies.entry_matching(source_entry)
            if prepared_target is None or prepared_source is None:
                self.set_status_message(
                    "In-game mesh swap is unavailable because its prepared target/source entries expired.",
                    error=True,
                )
                return
            target_entry = prepared_target
            source_entry = prepared_source
        else:
            dependencies = ArchiveWorkflowDependencyContext(
                selected_entry=target_entry,
                entries=getattr(self, "archive_entries", ()) or (),
                entries_by_normalized_path=getattr(self, "archive_entries_by_normalized_path", {}) or {},
                entries_by_basename=getattr(self, "archive_entries_by_basename", {}) or {},
                remote=False,
            )
        self._open_mesh_editor_for_entry(
            target_entry,
            mode="in_game_swap",
            source_entry=source_entry,
            activate=True,
        )
        request_id = int(getattr(self, "archive_in_game_mesh_swap_scope_request_id", 0) or 0) + 1
        self.archive_in_game_mesh_swap_scope_request_id = request_id
        request = ArchiveMeshSwapScopePreflightRequest(
            request_id=request_id,
            target_entry=target_entry,
            source_entry=source_entry,
            dependencies=dependencies,
        )

        def _task(
            _log: Callable[[str], None],
            progress: Callable[[int, int, str], None],
            stop_event: threading.Event,
        ) -> object:
            progress(0, 1, "Scanning source relationships and material contracts...")
            result = prepare_archive_mesh_swap_scope(self, request, stop_event=stop_event)
            progress(1, 1, "In-game mesh swap scope ready.")
            return result

        def _failed(message: str) -> None:
            if (
                request_id != int(getattr(self, "archive_in_game_mesh_swap_scope_request_id", 0) or 0)
                or bool(getattr(self, "_shutting_down", False))
                or is_expected_cancellation_message(message)
                or "cancel" in str(message).casefold()
            ):
                return
            QMessageBox.warning(self, "In-Game Mesh Swap Scope", message)

        def _ready(payload: object) -> None:
            if (
                not isinstance(payload, ArchiveMeshSwapScopePreflightResult)
                or payload.request_id
                != int(getattr(self, "archive_in_game_mesh_swap_scope_request_id", 0) or 0)
                or bool(getattr(self, "_shutting_down", False))
            ):
                return
            swap_scope = self._prompt_archive_in_game_mesh_swap_scope(
                target_entry,
                source_entry,
                prepared_scope=payload,
            )
            if swap_scope is not None:
                self._continue_archive_in_game_mesh_swap(
                    target_entry,
                    source_entry,
                    swap_scope,
                    dependencies=dependencies,
                )

        self._run_utility_task_when_idle(
            status_message="Preparing in-game mesh swap scope...",
            task=_task,
            on_complete=_ready,
            on_error=_failed,
            show_archive_progress=True,
            task_accepts_progress=True,
            task_accepts_cancel=True,
        )

    def _continue_archive_in_game_mesh_swap(
        self,
        target_entry: ArchiveEntry,
        source_entry: ArchiveEntry,
        swap_scope: InGameMeshSwapScopeSelection, *, dependencies: ArchiveWorkflowDependencyContext,
    ) -> None:
        progress_text = in_game_mesh_swap_progress_text()
        request_id = int(getattr(self, "archive_in_game_mesh_swap_request_id", 0) or 0) + 1
        self.archive_in_game_mesh_swap_request_id = request_id
        request = ArchiveInGameMeshSwapPreparationRequest(
            request_id=request_id,
            target_entry=target_entry,
            source_entry=source_entry,
            scope=swap_scope, dependencies=dependencies,
        )

        def _task(
            _log: Callable[[str], None],
            progress: Callable[[int, int, str], None],
            stop_event: threading.Event,
        ) -> object:
            progress(0, 3, "Reading source archive mesh...")
            scene_import_result = self._load_archive_mesh_scene_import_result(
                request.source_entry,
                stop_event=stop_event,
            )
            progress(1, 3, "Resolving source texture evidence...")
            source_texture_paths, source_texture_evidence = self._build_archive_swap_source_texture_evidence(
                request.source_entry, dependencies=request.dependencies, stop_event=stop_event
            )
            progress(2, 3, "Preparing source companion payloads...")
            if source_texture_paths:
                scene_import_result = dataclasses.replace(
                    scene_import_result,
                    discovered_texture_files=tuple(source_texture_paths),
                    diagnostics=tuple(scene_import_result.diagnostics)
                    + (f"Found {len(source_texture_paths):,} source DDS texture candidate(s) from source .pac_xml/sidecars.",),
                )
            extra_specs = self._build_in_game_mesh_swap_extra_specs(
                request.target_entry,
                request.source_entry,
                request.scope, dependencies=request.dependencies, stop_event=stop_event
            )
            raise_if_cancelled(stop_event, "In-game mesh swap preparation cancelled.")
            progress(3, 3, "In-game mesh source ready.")
            return ArchiveInGameMeshSwapPreparationResult(
                request_id=request.request_id,
                scene_import_result=scene_import_result,
                source_texture_evidence=tuple(source_texture_evidence),
                extra_specs=tuple(extra_specs),
            )

        def _failed(message: str) -> None:
            if (
                request_id != int(getattr(self, "archive_in_game_mesh_swap_request_id", 0) or 0)
                or bool(getattr(self, "_shutting_down", False))
                or is_expected_cancellation_message(message)
                or "cancel" in str(message).casefold()
            ):
                return
            QMessageBox.warning(
                self,
                "In-Game Mesh Source Unsupported",
                f"{source_entry.path} could not be parsed as a replacement mesh.\n\n{message}",
            )

        def _ready(payload: object) -> None:
            if (
                not isinstance(payload, ArchiveInGameMeshSwapPreparationResult)
                or payload.request_id != int(getattr(self, "archive_in_game_mesh_swap_request_id", 0) or 0)
                or bool(getattr(self, "_shutting_down", False))
            ):
                return
            if swap_scope.use_source_model_payload_directly:
                self.pending_in_game_mesh_swap_target = None
                self._update_archive_model_action_controls(self._archive_model_preview_controls_target())
                self._start_archive_direct_source_model_swap(
                    target_entry,
                    source_entry,
                    payload.scene_import_result,
                    swap_scope,
                    extra_specs=payload.extra_specs,
                )
                return

            swap_placement_note = (
                "Review offset, rotation, scale, and part mapping before export. "
                "In-game swap sources can differ in origin, facing direction, scale, or bone-relative placement."
            )

            def _continue_setup(setup: Optional[MeshImportSetupSelection]) -> None:
                if (
                    setup is None
                    or request_id != int(getattr(self, "archive_in_game_mesh_swap_request_id", 0) or 0)
                    or bool(getattr(self, "_shutting_down", False))
                ):
                    return
                setup.preferred_rebuild_material_sidecar = bool(
                    swap_scope.prefer_generated_sidecar or swap_scope.complete_swap
                )
                setup.preferred_complete_source_swap = bool(swap_scope.complete_swap)
                setup.source_texture_evidence = tuple(payload.source_texture_evidence)
                setup.extra_supplemental_specs = payload.extra_specs
                self.pending_in_game_mesh_swap_target = None
                self._update_archive_model_action_controls(self._archive_model_preview_controls_target())
                self._start_archive_mesh_patch(target_entry, preset_setup=setup)

            self._prepare_archive_mesh_import_setup_async(
                target_entry,
                self._archive_mesh_source_scene_path(source_entry),
                title="In-Game Mesh Swap Setup",
                on_complete=_continue_setup,
                scene_import_result=payload.scene_import_result,
                source_label=self._archive_mesh_source_label(source_entry),
                force_static_replacement=True,
                placement_review_title="In-Game Mesh Swap Placement",
                placement_context_note=swap_placement_note,
            )

        self._run_utility_task_when_idle(
            status_message=progress_text["label"],
            task=_task,
            on_complete=_ready,
            on_error=_failed,
            show_archive_progress=True,
            task_accepts_progress=True,
            task_accepts_cancel=True,
        )
