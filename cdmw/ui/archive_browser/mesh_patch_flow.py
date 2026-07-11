"""Archive mesh patch, loose export, and direct patch flow."""
from __future__ import annotations

import json
import threading
from collections.abc import Callable, Sequence
from pathlib import Path, PurePosixPath
from typing import Dict, Optional, Tuple

from PySide6.QtCore import QSize, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QDialog, QFileDialog, QHBoxLayout, QLabel, QMessageBox, QPlainTextEdit, QPushButton, QVBoxLayout, QWidget

from cdmw.services.archive_preview_service import ensure_archive_preview_source
from cdmw.domain.archives.mesh_contracts import ArchiveLooseExportResult, MeshImportPreviewResult, MeshImportSupplementalFileSpec
from cdmw.services.preview_workflow_service import build_mesh_import_preview
from cdmw.services.archive_workflow_service import export_archive_mesh_payloads_to_mod_ready_loose
from cdmw.services.preview_workflow_service import FinalPackagePreviewResult, MATERIAL_PREFLIGHT_OVERRIDE_WARNING, apply_material_preflight_override, build_final_package_preview, material_preflight_hard_blockers
from cdmw.domain.library.item_icons import ItemIconOverrideSpec
from cdmw.domain.cancellation import raise_if_cancelled
from cdmw.services.mesh_workflow_service import check_material_authority_report as _check_material_authority_report
from cdmw.domain.mesh.session import MeshImportSetupSelection
from cdmw.domain.textures.policy import check_final_preview_material_authority as _check_final_preview_material_authority, complete_swap_allows_inherited_layer_color_bindings as _complete_swap_allows_inherited_layer_color_bindings, complete_swap_authority_contract as _complete_swap_authority_contract, complete_swap_requires_true_source_authority as _complete_swap_requires_true_source_authority, material_authority_check_blockers as _material_authority_check_blockers, material_authority_check_review_lines as _material_authority_check_review_lines
from cdmw.models import ArchiveEntry
from cdmw.services.mesh_workflow_service import SceneImportResult
from cdmw.services.mesh_workflow_service import StaticMeshReplacementOptions
from cdmw.services.archive_mutation_service import ArchivePatchRequest, ArchivePatchResult
from cdmw.ui.archive_browser.dds_preview_resolvers import archive_dds_preview_resolver_pair as _archive_dds_preview_resolver_pair_helper
from cdmw.ui.archive_browser.mesh_import_setup_state import (
    mesh_import_file_dialog_title,
    mesh_import_replacement_mode_log,
    mesh_import_setup_dialog_title,
)
from cdmw.ui.archive_browser.static_replacement_sparse_history import clone_static_replacement_options_for_worker
from cdmw.ui.archive_browser.static_replacement_alignment_setup_state import (
    alignment_builder_window_title,
    alignment_preview_build_failed_status,
)


class ArchiveMeshPatchFlowMixin:
    def _start_archive_mesh_patch(
        self,
        entry: ArchiveEntry,
        *,
        preset_setup: Optional[MeshImportSetupSelection] = None,
    ) -> None:
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
                    self._start_archive_mesh_patch(entry, preset_setup=setup)
                    if isinstance(setup, MeshImportSetupSelection)
                    else None
                ),
            )
            return
        else:
            setup = preset_setup
        scene_path_obj = setup.scene_path
        import_mode = setup.import_mode
        setup_title_key = f"{setup.placement_review_title} {setup.source_label}".casefold()
        mesh_editor_mode = (
            "modify_original"
            if "modify original" in setup_title_key
            else "in_game_swap"
            if "swap" in setup_title_key
            else "external_import"
        )
        self._open_mesh_editor_for_entry(
            entry,
            mode=mesh_editor_mode,
            source_path=scene_path_obj,
            source_skeleton=setup.source_skeleton,
            supplemental_files=setup.supplemental_files,
            scene_import_result=setup.scene_import_result,
            activate=True,
        )
        build_entry = entry
        if scene_path_obj.suffix.lower() in {".dae", ".gltf", ".glb", ".pac", ".pam", ".pamlod"}:
            self.append_archive_log(mesh_import_replacement_mode_log(scene_path_obj.suffix))

        def _start_build_with_static_options(
            static_replacement_options: Optional[StaticMeshReplacementOptions],
            dialog_parent: Optional[QWidget] = None,
            build_status_callback: Optional[Callable[[str], None]] = None,
            build_finished_callback: Optional[Callable[[str, bool], None]] = None,
            output_mode: str = "loose",
        ) -> bool:
            build_dialog_parent = dialog_parent if dialog_parent is not None else self
            destination = "patch" if str(output_mode or "").strip().casefold() == "patch" else "loose"

            def _set_builder_status(message: str) -> None:
                if build_status_callback is not None:
                    build_status_callback(message)
                else:
                    self.set_status_message(message)

            def _finish_builder_status(message: str, success: bool) -> None:
                if build_finished_callback is not None:
                    build_finished_callback(message, success)
                else:
                    self.set_status_message(message, error=not bool(success))

            supplemental_files = setup.supplemental_files
            if static_replacement_options is not None:
                supplemental_files = tuple(supplemental_files or ()) + tuple(
                    path
                    for path in getattr(static_replacement_options, "additional_supplemental_files", ()) or ()
                    if isinstance(path, Path)
                )

            loose_export_settings = None
            selected_related_entries: Sequence[ArchiveEntry] = ()
            if destination == "loose":
                _set_builder_status("Choosing mesh replacement export metadata...")
                loose_export_settings = self._collect_archive_mod_ready_export_target(
                    browse_title="Select Mod-Ready Export Parent Root",
                    prompt_for_metadata=True,
                    initial_include_related_files=False,
                    show_include_related_files_option=False,
                    dialog_title="Mesh Loose Export Metadata",
                    allow_dmm_texture_structure=False,
                    show_texture_resolution_manifest_option=True,
                    show_material_authority_report_option=True,
                    show_active_file_authority_audit_option=True,
                    parent=build_dialog_parent,
                )
                if loose_export_settings is None:
                    _finish_builder_status("Mesh replacement build cancelled before export target selection.", False)
                    return False
                _set_builder_status("Choosing optional related files for loose package...")
                selected_related_entries_result = self._prompt_archive_mesh_related_file_selection(
                    build_entry,
                    title="Include Additional Referenced Files",
                    intro_text=(
                        "Select any original archive companion files that should be copied into the loose mod. "
                        "Generated replacement textures and patched material sidecars are included automatically when enabled; "
                        "original .pac_xml, .pab, .hkx, and old DDS files are unchecked by default."
                    ),
                    confirm_button_text="Continue",
                    default_checked=False,
                    parent=build_dialog_parent,
                )
                if selected_related_entries_result is None:
                    _finish_builder_status("Mesh replacement build cancelled before related file selection.", False)
                    return False
                selected_related_entries = selected_related_entries_result
                _set_builder_status("Building loose mod package...")
            else:
                _set_builder_status("Preparing direct archive patch...")

            paired_entry = None
            if build_entry.extension == ".pam":
                paired_entry = self._find_archive_entry_by_virtual_path(str(PurePosixPath(build_entry.path).with_suffix(".pamlod")))
            texconv_text = self.texconv_path_edit.text().strip()
            require_source_owned_colors = bool(getattr(static_replacement_options, "complete_external_swap", False))

            def _preview_task(
                log: Callable[[str], None],
                stop_event: threading.Event,
            ) -> MeshImportPreviewResult:
                worker_options = clone_static_replacement_options_for_worker(static_replacement_options, stop_event)
                active_static_options = self._retarget_static_options_for_runtime_entry(
                    entry,
                    build_entry,
                    worker_options,
                    setup.scene_import_result.mesh if isinstance(setup.scene_import_result, SceneImportResult) else None,
                    on_log=log,
                    stop_event=stop_event,
                )
                log(f"Rebuilding {build_entry.path} from {scene_path_obj.name}...")
                preview_settings = self._current_model_preview_render_settings()
                preview_result = build_mesh_import_preview(
                    build_entry,
                    scene_path_obj,
                    import_mode=import_mode,
                    static_replacement_options=active_static_options,
                    scene_import_result=setup.scene_import_result,
                    source_display_label=setup.source_label,
                    archive_entries_by_normalized_path=self.archive_entries_by_normalized_path,
                    texconv_path=(Path(texconv_text).expanduser() if texconv_text else None),
                    texture_entries_by_normalized_path=self.archive_entries_by_normalized_path,
                    texture_entries_by_basename=self.archive_entries_by_basename,
                    visible_texture_mode=preview_settings.visible_texture_mode,
                    supplemental_files=supplemental_files,
                    stop_event=stop_event,
                )
                return preview_result
            _archive_dds_preview_source_for_path, _archive_dds_preview_sources_for_basename = (
                _archive_dds_preview_resolver_pair_helper(
                    self.archive_entries_by_normalized_path,
                    self.archive_entries_by_basename,
                    ensure_preview_source=ensure_archive_preview_source,
                )
            )

            def _start_commit(preview_result: MeshImportPreviewResult) -> None:
                material_report_render_settings = self._current_model_preview_render_settings()
                mutation_service = self.app_context.services.require_archive_mutations() if destination == "patch" else None

                def _commit_task(
                    log: Callable[[str], None],
                    stop_event: threading.Event,
                ) -> object:
                    raise_if_cancelled(stop_event, "Mesh replacement export cancelled.")
                    unsafe_material_preflight_override = bool(
                        destination == "loose"
                        and getattr(static_replacement_options, "allow_unsafe_material_preflight_export", False)
                    )
                    export_options = None
                    parent_root = None
                    package_info = None
                    create_no_encrypt = False
                    include_related_files = False
                    if destination == "loose":
                        if loose_export_settings is None:
                            raise ValueError("Loose export settings were not collected.")
                        parent_root, package_info, create_no_encrypt, include_related_files, export_options = loose_export_settings

                    custom_icon_specs: Tuple[MeshImportSupplementalFileSpec, ...] = ()
                    custom_icon_override = (
                        getattr(static_replacement_options, "custom_item_icon_override", None)
                        if static_replacement_options is not None
                        else None
                    )
                    if isinstance(custom_icon_override, ItemIconOverrideSpec):
                        custom_icon_specs = (
                            self._build_custom_item_icon_supplemental_spec(
                                custom_icon_override,
                                texconv_path=(Path(texconv_text).expanduser() if texconv_text else None),
                                on_log=log,
                            ),
                        )
                    loose_supplemental_specs = tuple(setup.extra_supplemental_specs or ()) + tuple(
                        preview_result.supplemental_file_specs or ()
                    )
                    loose_supplemental_specs = loose_supplemental_specs + custom_icon_specs
                    direct_patch_supplemental_specs = tuple(
                        spec
                        for spec in tuple(preview_result.supplemental_file_specs or ()) + custom_icon_specs
                        if isinstance(spec, MeshImportSupplementalFileSpec)
                        and isinstance(getattr(spec, "target_entry", None), ArchiveEntry)
                        and self._mesh_direct_patch_spec_is_generated(spec)
                    )
                    supplemental_specs_to_include = (
                        direct_patch_supplemental_specs
                        if destination == "patch"
                        else loose_supplemental_specs
                    )
                    if destination == "patch":
                        requests, request_warnings = self._build_mesh_direct_patch_requests(
                            build_entry,
                            preview_result,
                            paired_entry=paired_entry,
                            supplemental_specs=direct_patch_supplemental_specs,
                        )
                        for warning in request_warnings:
                            log(warning)
                    else:
                        request_by_normalized_path: Dict[str, ArchivePatchRequest] = {
                            build_entry.path.replace("\\", "/").strip().casefold(): ArchivePatchRequest(
                                entry=build_entry,
                                payload_data=preview_result.rebuilt_data,
                            )
                        }
                        if paired_entry is not None and preview_result.paired_lod_data is not None:
                            request_by_normalized_path[paired_entry.path.replace("\\", "/").strip().casefold()] = ArchivePatchRequest(
                                entry=paired_entry,
                                payload_data=preview_result.paired_lod_data,
                            )
                        requests = list(request_by_normalized_path.values())

                    if destination == "patch":
                        preflight_failed_prefix = "Final package texture preflight failed before direct archive patch: "
                        preflight_failed_log = (
                            "Final package texture preflight failed before direct archive patch; no files were written:\n"
                        )
                        log("Running final package texture preflight before direct archive patch...")
                    else:
                        preflight_failed_prefix = "Final package texture preflight failed before export: "
                        preflight_failed_log = (
                            "Final package texture preflight failed before export; no files were written:\n"
                        )
                        log("Running final package texture preflight before export...")
                    pre_export_preview: Optional[FinalPackagePreviewResult] = None
                    try:
                        pre_export_preview = build_final_package_preview(
                            preview_result,
                            supplemental_file_specs=supplemental_specs_to_include,
                            source_path=scene_path_obj,
                            export_options=export_options,
                            texconv_path=(Path(texconv_text).expanduser() if texconv_text else None),
                            original_dds_resolver=_archive_dds_preview_source_for_path,
                            original_dds_basename_resolver=_archive_dds_preview_sources_for_basename,
                            require_source_owned_colors=require_source_owned_colors,
                            strict_source_owned_material_contract=_complete_swap_requires_true_source_authority(static_replacement_options),
                            allow_inherited_layer_color_bindings=_complete_swap_allows_inherited_layer_color_bindings(static_replacement_options),
                            material_authority_contract=_complete_swap_authority_contract(static_replacement_options),
                            render_settings=material_report_render_settings,
                        )
                    except Exception as exc:
                        blocker_lines = (
                            f"{preflight_failed_prefix}{exc}",
                        )
                        log(
                            preflight_failed_log
                            + "\n".join(f"- {line}" for line in blocker_lines)
                        )
                        if destination == "loose" and unsafe_material_preflight_override:
                            log(
                                MATERIAL_PREFLIGHT_OVERRIDE_WARNING
                                + "\nContinuing loose export even though final package preflight could not be built."
                            )
                        else:
                            return {
                                "preview": preview_result,
                                "loose": None,
                                "patch": None,
                                "final_preview": None,
                                "preflight_blocked": blocker_lines,
                                "preflight_hard_blocked": blocker_lines,
                            }
                    if pre_export_preview is not None:
                        pre_export_authority_check = _check_final_preview_material_authority(
                            pre_export_preview,
                            report_checker=_check_material_authority_report,
                        )
                        pre_export_authority_blockers = _material_authority_check_blockers(pre_export_authority_check)
                        if pre_export_authority_blockers:
                            blockers = "\n".join(f"- {line}" for line in pre_export_authority_blockers[:12])
                            if len(pre_export_authority_blockers) > 12:
                                blockers += f"\n- ... {len(pre_export_authority_blockers) - 12:,} more blocker(s)"
                            if destination == "loose" and unsafe_material_preflight_override:
                                log(
                                    MATERIAL_PREFLIGHT_OVERRIDE_WARNING
                                    + "\nContinuing loose export despite material authority report blocker(s):\n"
                                    + blockers
                                )
                            else:
                                log(
                                    "Material authority report check blocked export because generated package evidence is incomplete:\n"
                                    + blockers
                                )
                                return {
                                    "preview": preview_result,
                                    "loose": None,
                                    "patch": None,
                                    "final_preview": pre_export_preview,
                                    "preflight_blocked": pre_export_authority_blockers,
                                    "preflight_hard_blocked": pre_export_authority_blockers,
                                }
                        for warning in _material_authority_check_review_lines(pre_export_authority_check, limit=6):
                            log(f"Material authority review: {warning}")
                        if pre_export_preview.preflight_errors:
                            blocker_lines = tuple(str(line) for line in pre_export_preview.preflight_errors if str(line or "").strip())
                            hard_blockers = material_preflight_hard_blockers(blocker_lines)
                            blockers = "\n".join(f"- {line}" for line in blocker_lines[:12])
                            if len(pre_export_preview.preflight_errors) > 12:
                                blockers += f"\n- ... {len(pre_export_preview.preflight_errors) - 12:,} more blocker(s)"
                            if destination == "loose" and unsafe_material_preflight_override:
                                log(
                                    MATERIAL_PREFLIGHT_OVERRIDE_WARNING
                                    + "\nContinuing loose export despite material preflight blocker(s):\n"
                                    + blockers
                                )
                                apply_material_preflight_override(pre_export_preview, include_hard=True)
                            else:
                                if destination == "patch":
                                    log(
                                        "Final package texture preflight blocked direct archive patch because the package contract would not be WYSIWYG:\n"
                                        + blockers
                                    )
                                else:
                                    log(
                                        "Final package texture preflight blocked export because the package contract would not be WYSIWYG:\n"
                                        + blockers
                                    )
                                return {
                                    "preview": preview_result,
                                    "loose": None,
                                    "patch": None,
                                    "final_preview": pre_export_preview,
                                    "preflight_blocked": blocker_lines,
                                    "preflight_hard_blocked": hard_blockers,
                                }
                    if destination == "patch":
                        if not requests:
                            raise ValueError("No archive patch requests could be built for the rebuilt mesh.")
                        log(f"Patching {len(requests)} rebuilt/generated entries directly into game archives...")
                        assert mutation_service is not None
                        plan = mutation_service.prepare_patch(
                            requests, confirmed=True, description=f"Patch rebuilt mesh {build_entry.path}",
                        )
                        patch_result = mutation_service.apply_patch(plan, on_log=log, stop_event=stop_event)
                        return {
                            "preview": preview_result,
                            "patch": patch_result,
                            "final_preview": pre_export_preview,
                        }

                    log(f"Writing {len(requests)} rebuilt entries into a mod-ready loose package...")
                    loose_result = export_archive_mesh_payloads_to_mod_ready_loose(
                        requests,
                        primary_entry=build_entry,
                        preview_result=preview_result,
                        source_obj_path=scene_path_obj,
                        source_display_label=setup.source_label,
                        parent_root=parent_root,
                        package_info=package_info,
                        export_options=export_options,
                        create_no_encrypt_file=create_no_encrypt,
                        include_related_files=include_related_files,
                        related_entries_to_include=selected_related_entries,
                        supplemental_files_to_include=supplemental_specs_to_include,
                        on_log=log,
                    )
                    texture_resolution_manifest_path = loose_result.package_root / "cdmw_texture_resolution_manifest.json"
                    if not bool(getattr(export_options, "create_texture_resolution_manifest", False)):
                        try:
                            if texture_resolution_manifest_path.exists():
                                texture_resolution_manifest_path.unlink()
                                log(f"Removed stale texture resolution manifest: {texture_resolution_manifest_path}")
                        except Exception as exc:
                            log(f"Warning: could not remove stale texture resolution manifest: {exc}")
                    material_authority_report_path = loose_result.package_root / "cdmw_material_authority_report.json"
                    material_authority_check_path = loose_result.package_root / "cdmw_material_authority_report_check.json"
                    if not bool(getattr(export_options, "create_material_authority_report", False)):
                        for stale_report_path in (material_authority_report_path, material_authority_check_path):
                            try:
                                if stale_report_path.exists():
                                    stale_report_path.unlink()
                                    log(f"Removed stale material authority report: {stale_report_path}")
                            except Exception as exc:
                                log(f"Warning: could not remove stale material authority report: {exc}")
                    final_preview: Optional[FinalPackagePreviewResult] = None
                    try:
                        log("Building final output preview from packaged sidecar/DDS payloads...")
                        final_preview = build_final_package_preview(
                            preview_result,
                            supplemental_file_specs=supplemental_specs_to_include,
                            source_path=scene_path_obj,
                            export_options=export_options,
                            texconv_path=(Path(texconv_text).expanduser() if texconv_text else None),
                            original_dds_resolver=_archive_dds_preview_source_for_path,
                            original_dds_basename_resolver=_archive_dds_preview_sources_for_basename,
                            package_root=loose_result.package_root,
                            require_source_owned_colors=require_source_owned_colors,
                            strict_source_owned_material_contract=_complete_swap_requires_true_source_authority(static_replacement_options),
                            allow_inherited_layer_color_bindings=_complete_swap_allows_inherited_layer_color_bindings(static_replacement_options),
                            material_authority_contract=_complete_swap_authority_contract(static_replacement_options),
                            render_settings=material_report_render_settings,
                        )
                        if final_preview.preflight_errors:
                            if unsafe_material_preflight_override:
                                apply_material_preflight_override(final_preview, include_hard=True)
                                log(MATERIAL_PREFLIGHT_OVERRIDE_WARNING)
                                for blocker in final_preview.warnings[-12:]:
                                    if str(blocker).startswith("Unsafe material preflight override:"):
                                        log(str(blocker))
                            else:
                                for blocker in final_preview.preflight_errors[:12]:
                                    log(f"Final package texture preflight blocker: {blocker}")
                        if bool(getattr(export_options, "create_texture_resolution_manifest", False)):
                            if final_preview.texture_resolution_manifest.rows:
                                texture_resolution_manifest_path.write_text(
                                    json.dumps(final_preview.texture_resolution_manifest.to_dict(), indent=2),
                                    encoding="utf-8",
                                )
                                log(f"Wrote texture resolution manifest: {texture_resolution_manifest_path}")
                            elif texture_resolution_manifest_path.exists():
                                texture_resolution_manifest_path.unlink()
                                log(f"Removed empty texture resolution manifest: {texture_resolution_manifest_path}")
                        material_authority_check = _check_final_preview_material_authority(
                            final_preview,
                            report_checker=_check_material_authority_report,
                        )
                        if bool(getattr(export_options, "create_material_authority_report", False)):
                            material_authority_report_path.write_text(
                                json.dumps(final_preview.material_authority_report.to_dict(), indent=2),
                                encoding="utf-8",
                            )
                            log(f"Wrote material authority report: {material_authority_report_path}")
                            material_authority_check_path.write_text(
                                json.dumps(dict(material_authority_check), indent=2, sort_keys=True),
                                encoding="utf-8",
                            )
                            log(
                                "Wrote material authority report check: "
                                f"{material_authority_check_path} ({material_authority_check.get('status', 'unknown')})"
                            )
                        for blocker in _material_authority_check_blockers(material_authority_check)[:12]:
                            log(f"Material authority report blocker: {blocker}")
                        for warning in _material_authority_check_review_lines(material_authority_check, limit=8):
                            log(f"Material authority report review: {warning}")
                    except Exception as exc:
                        log(f"Final output preview could not be built: {exc}")
                    return {
                        "preview": preview_result,
                        "loose": loose_result,
                        "patch": None,
                        "final_preview": final_preview,
                    }

                def _handle_commit_complete(result: object) -> None:
                    if not isinstance(result, dict):
                        _finish_builder_status("Mesh import finished with an unexpected result payload.", False)
                        return
                    preview_payload = result.get("preview")
                    loose_result = result.get("loose")
                    patch_result = result.get("patch")
                    preflight_blockers = tuple(
                        str(line)
                        for line in tuple(result.get("preflight_blocked") or ())
                        if str(line or "").strip()
                    )
                    preflight_hard_blockers = tuple(
                        str(line)
                        for line in tuple(result.get("preflight_hard_blocked") or ())
                        if str(line or "").strip()
                    )
                    if not isinstance(preview_payload, MeshImportPreviewResult):
                        _finish_builder_status("Mesh import finished with an incomplete result payload.", False)
                        return
                    if preflight_blockers:
                        blocker_text = "\n".join(f"- {line}" for line in preflight_blockers)
                        try:
                            build_dialog_parent.isVisible()
                            blocker_parent = build_dialog_parent
                        except RuntimeError:
                            blocker_parent = self
                        blocker_dialog = QDialog(blocker_parent)
                        blocker_dialog.setWindowTitle("Final Preflight Blocked Export")
                        blocker_dialog.resize(900, 560)
                        blocker_layout = QVBoxLayout(blocker_dialog)
                        blocker_layout.setContentsMargins(14, 14, 14, 14)
                        blocker_layout.setSpacing(10)
                        blocker_summary = QLabel(
                            (
                                "<b>Game archive files were not patched.</b><br><br>"
                                if destination == "patch"
                                else "<b>Loose package was not written.</b><br><br>"
                            )
                            + "Complete source-owned swap requires the final package preview to match exact material bindings."
                        )
                        blocker_summary.setWordWrap(True)
                        blocker_layout.addWidget(blocker_summary)
                        blocker_details = QPlainTextEdit()
                        blocker_details.setReadOnly(True)
                        blocker_details.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
                        blocker_details.setPlainText(
                            (
                                "Final package texture preflight blocked direct archive patch because the package contract would not be WYSIWYG:\n"
                                if destination == "patch"
                                else "Final package texture preflight blocked export because the package contract would not be WYSIWYG:\n"
                            )
                            + blocker_text
                        )
                        blocker_details.setMinimumSize(QSize(860, 390))
                        blocker_layout.addWidget(blocker_details, 1)
                        blocker_button_row = QHBoxLayout()
                        blocker_button_row.addStretch(1)
                        unsafe_choice = {"export": False}
                        unsafe_export_button = None
                        unsafe_export_available = bool(
                            destination == "loose"
                            and not getattr(static_replacement_options, "allow_unsafe_material_preflight_export", False)
                        )
                        if unsafe_export_available:
                            blocker_cancel_button = QPushButton("Cancel")
                            blocker_cancel_button.clicked.connect(blocker_dialog.reject)
                            blocker_button_row.addWidget(blocker_cancel_button)
                            unsafe_export_button = QPushButton("Export Anyway (Unsafe)")
                            unsafe_export_button.setObjectName("MeshAlignmentUnsafeMaterialPreflightExportButton")
                            unsafe_export_button.setToolTip(MATERIAL_PREFLIGHT_OVERRIDE_WARNING)

                            def _accept_unsafe_material_preflight_export() -> None:
                                unsafe_choice["export"] = True
                                blocker_dialog.accept()

                            unsafe_export_button.clicked.connect(_accept_unsafe_material_preflight_export)
                            blocker_button_row.addWidget(unsafe_export_button)
                        else:
                            blocker_ok_button = QPushButton("OK")
                            blocker_ok_button.clicked.connect(blocker_dialog.accept)
                            blocker_button_row.addWidget(blocker_ok_button)
                        blocker_layout.addLayout(blocker_button_row)
                        blocker_dialog.exec()
                        if unsafe_choice.get("export"):
                            if static_replacement_options is not None:
                                setattr(static_replacement_options, "allow_unsafe_material_preflight_export", True)
                            _set_builder_status("Writing loose mod package with unsafe material preflight override...")
                            _start_commit(preview_payload)
                            return
                        _finish_builder_status("Mesh replacement build blocked by final package texture preflight.", False)
                        return
                    if destination == "patch":
                        if not isinstance(patch_result, ArchivePatchResult):
                            _finish_builder_status("Mesh archive patch finished with an incomplete result payload.", False)
                            return
                        self._apply_archive_patch_result(patch_result)
                        final_preview = (
                            result.get("final_preview")
                            if isinstance(result.get("final_preview"), FinalPackagePreviewResult)
                            else None
                        )
                        self._show_archive_import_preview(
                            build_entry,
                            preview_payload,
                            patched=True,
                            backup_dir=patch_result.backup_dir,
                            final_preview=final_preview,
                        )
                        updated_entry = self._find_archive_entry_by_virtual_path(build_entry.path) or build_entry
                        self._render_archive_preview(updated_entry, force=True)
                        try:
                            build_dialog_parent.isVisible()
                            patch_box_parent = build_dialog_parent
                        except RuntimeError:
                            patch_box_parent = self
                        patch_box = QMessageBox(patch_box_parent)
                        patch_box.setIcon(QMessageBox.Information)
                        patch_box.setWindowTitle("Game Files Patched")
                        patch_box.setText("Patched game archive files.")
                        patch_box.setInformativeText(str(patch_result.backup_dir))
                        patch_box.setDetailedText(
                            "Patched archive entries:\n"
                            + "\n".join(str(path) for path in patch_result.changed_paths)
                            + f"\n\nBackup:\n{patch_result.backup_dir}"
                        )
                        patch_box.setStandardButtons(QMessageBox.Ok)
                        patch_box.setMinimumSize(QSize(560, 180))
                        patch_box.exec()
                        _finish_builder_status(
                            f"Patched rebuilt {build_entry.basename} into game archives.",
                            True,
                        )
                        return
                    if not isinstance(loose_result, ArchiveLooseExportResult):
                        _finish_builder_status("Mesh loose export finished with an incomplete result payload.", False)
                        return
                    self._show_archive_import_preview(
                        build_entry,
                        preview_payload,
                        patched=False,
                        loose_package_root=loose_result.package_root,
                        final_preview=(
                            result.get("final_preview")
                            if isinstance(result.get("final_preview"), FinalPackagePreviewResult)
                            else None
                        ),
                    )
                    try:
                        build_dialog_parent.isVisible()
                        export_box_parent = build_dialog_parent
                    except RuntimeError:
                        export_box_parent = self
                    export_box = QMessageBox(export_box_parent)
                    export_box.setIcon(QMessageBox.Information)
                    export_box.setWindowTitle("Loose Export Complete")
                    export_box.setText("Loose package written.")
                    export_box.setInformativeText(str(loose_result.package_root))
                    audit_line = (
                        f"\n\nActive file authority report:\n{loose_result.authority_audit_path}"
                        if loose_result.authority_audit_path is not None
                        else ""
                    )
                    export_box.setDetailedText(
                        "Wrote rebuilt mesh payload(s) into:\n"
                        f"{loose_result.package_root}"
                        f"{audit_line}\n\n"
                        "If the edited PAC is present but the game still shows the original, check the equipped asset variant, "
                        "enabled mod-manager profile, game cache, paired LOD, and cloth/physics companion files."
                    )
                    export_box.setStandardButtons(QMessageBox.Ok)
                    verify_button = None
                    if loose_result.authority_audit_path is not None:
                        verify_button = export_box.addButton("Verify Loose Mod Target", QMessageBox.ActionRole)
                    export_box.setMinimumSize(QSize(560, 180))
                    export_box.exec()
                    if verify_button is not None and export_box.clickedButton() is verify_button:
                        QDesktopServices.openUrl(QUrl.fromLocalFile(str(loose_result.authority_audit_path.resolve())))
                    _finish_builder_status(
                        f"Wrote rebuilt {build_entry.basename} into a mod-ready loose package.",
                        True,
                    )

                self._run_utility_task_when_idle(
                    status_message=(
                        f"Patching {build_entry.basename} into game archive files..."
                        if destination == "patch"
                        else f"Writing {build_entry.basename} into a mod-ready loose package..."
                    ),
                    task=_commit_task,
                    on_complete=_handle_commit_complete,
                    on_error=lambda message: _finish_builder_status(
                        f"Mesh replacement build failed: {message}",
                        False,
                    ),
                    show_archive_progress=True,
                    task_accepts_cancel=True,
                )

            def _handle_preview_complete(result: object) -> None:
                if not isinstance(result, MeshImportPreviewResult):
                    _finish_builder_status("Mesh import preview finished with an unexpected result payload.", False)
                    return
                if static_replacement_options is None:
                    self._show_archive_import_preview(build_entry, result, patched=False)
                    if not self._confirm_archive_mesh_import_commit(
                        build_entry,
                        result,
                        destination=destination,
                        source_obj_path=scene_path_obj,
                    ):
                        _finish_builder_status("Mesh import cancelled after validation review.", False)
                        return
                if destination == "patch":
                    target_paths = list(
                        self._mesh_direct_patch_target_paths(
                            build_entry,
                            result,
                            paired_entry=paired_entry,
                            supplemental_specs=tuple(result.supplemental_file_specs or ()),
                        )
                    )
                    custom_icon_override = (
                        getattr(static_replacement_options, "custom_item_icon_override", None)
                        if static_replacement_options is not None
                        else None
                    )
                    if isinstance(custom_icon_override, ItemIconOverrideSpec):
                        custom_icon_target = getattr(custom_icon_override, "target_entry", None)
                        if isinstance(custom_icon_target, ArchiveEntry):
                            custom_icon_path = str(custom_icon_target.path or "").replace("\\", "/").strip()
                            if custom_icon_path and custom_icon_path.casefold() not in {
                                path.casefold() for path in target_paths
                            }:
                                target_paths.append(custom_icon_path)
                    if not self._confirm_mesh_direct_archive_patch(
                        target_paths,
                        parent=build_dialog_parent,
                    ):
                        _finish_builder_status("Mesh archive patch cancelled before writing game files.", False)
                        return
                    _set_builder_status("Patching game archive files...")
                else:
                    _set_builder_status("Writing loose mod package...")
                _start_commit(result)

            self._run_utility_task(
                status_message=f"Rebuilding mesh preview for {build_entry.basename}...",
                task=_preview_task,
                on_complete=_handle_preview_complete,
                on_error=lambda message: _finish_builder_status(
                    alignment_preview_build_failed_status(message),
                    False,
                ),
                show_archive_progress=True,
                task_accepts_cancel=True,
            )
            return True

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
                dialog_title=setup.placement_review_title or alignment_builder_window_title(),
                placement_context_note=setup.placement_context_note,
                source_texture_evidence=setup.source_texture_evidence,
                extra_supplemental_specs=setup.extra_supplemental_specs,
                defer_original_texture_preview=bool(setup.defer_original_texture_preview),
                runtime_export_target_entry=build_entry,
                full_import_model_replacement=bool(setup.full_import_model_replacement),
                embedded_host=self.mesh_editor_tab.builder_host() if hasattr(self, "mesh_editor_tab") else None,
                continue_build_callback=_start_build_with_static_options,
            )
            return

        _start_build_with_static_options(None)
