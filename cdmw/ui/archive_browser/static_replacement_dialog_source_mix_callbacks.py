"""Source-mix callback factory for the static replacement dialog."""

from __future__ import annotations

from types import SimpleNamespace

from cdmw.ui.archive_browser.source_mix_task_controller import (
    source_mix_task_controller_for_guard,
)
from cdmw.workers.source_mix_workers import (
    SceneImportRequest,
    SceneImportTaskResult,
    SourceMixScanRequest,
    SourceMixScanResult,
    run_scene_import,
    run_source_mix_scan,
)


def create_alignment_source_mix_callbacks(context: dict[str, object]) -> SimpleNamespace:
    ARCHIVE_MESH_EXTENSIONS = context.get('ARCHIVE_MESH_EXTENSIONS')
    ArchiveEntry = context.get('ArchiveEntry')
    List = context.get('List')
    Mapping = context.get('Mapping')
    MeshImportSetupSelection = context.get('MeshImportSetupSelection')
    Path = context.get('Path')
    QFileDialog = context.get('QFileDialog')
    QMessageBox = context.get('QMessageBox')
    QTimer = context.get('QTimer')
    SCENE_TEXTURE_SOURCE_EXTENSIONS = context.get('SCENE_TEXTURE_SOURCE_EXTENSIONS')
    SourceMixCandidate = context.get('SourceMixCandidate')
    _alignment_source_mix_loose_added_message_helper = context.get('_alignment_source_mix_loose_added_message_helper')
    _alignment_source_mix_loose_scan_status_helper = context.get('_alignment_source_mix_loose_scan_status_helper')
    _alignment_source_mix_reopening_archive_status_helper = context.get('_alignment_source_mix_reopening_archive_status_helper')
    _alignment_source_mix_reopening_loose_status_helper = context.get('_alignment_source_mix_reopening_loose_status_helper')
    _alignment_source_mix_reopening_mod_archive_status_helper = context.get('_alignment_source_mix_reopening_mod_archive_status_helper')
    dialog = context.get('dialog')
    entry = context.get('entry')
    self = context.get('self')
    add_archive_source_button = context.get('add_archive_source_button')
    add_loose_source_button = context.get('add_loose_source_button')
    add_mod_archive_source_button = context.get('add_mod_archive_source_button')
    source_mix_control_text = context.get('source_mix_control_text')
    source_mix_status_label = context.get('source_mix_status_label')
    source_task_controller = source_mix_task_controller_for_guard(self, dialog)

    def _set_source_controls_enabled(enabled: bool) -> None:
        for button in (
            add_archive_source_button,
            add_loose_source_button,
            add_mod_archive_source_button,
        ):
            try:
                button.setEnabled(enabled)
            except (AttributeError, RuntimeError):
                pass

    def _start_source_task(
        request: object,
        operation: object,
        *,
        status_message: str,
        title: str,
        on_complete: object,
    ) -> bool:
        started = source_task_controller.start(
            request,
            operation,
            status_message=status_message,
            on_complete=on_complete,
            on_error=lambda message: QMessageBox.warning(dialog, title, message),
            on_idle=lambda: _set_source_controls_enabled(True),
        )
        if started:
            _set_source_controls_enabled(False)
        return started

    def _choose_loaded_archive_mesh_source_for_alignment() -> None:
        entries_by_extension = getattr(self, "archive_entries_by_extension", {}) or {}
        mesh_entries: List[ArchiveEntry] = []
        if isinstance(entries_by_extension, Mapping):
            for extension in sorted(ARCHIVE_MESH_EXTENSIONS):
                mesh_entries.extend(
                    candidate
                    for candidate in tuple(entries_by_extension.get(extension, ()) or ())
                    if isinstance(candidate, ArchiveEntry)
                )
        source_entries = mesh_entries or (getattr(self, "archive_entries", ()) or ())
        if not source_entries:
            QMessageBox.information(
                dialog,
                source_mix_control_text["add_archive"],
                source_mix_control_text["no_loaded_archive_sources"],
            )
            return
        selected_source = self._choose_archive_mesh_source_dialog(
            dialog,
            title=source_mix_control_text["add_archive"],
            entries=source_entries,
            prompt=source_mix_control_text["archive_source_prompt"],
            allowed_extensions=tuple(sorted(ARCHIVE_MESH_EXTENSIONS)),
            excluded_entry=entry,
        )
        if not isinstance(selected_source, ArchiveEntry):
            return
        source_mix_status_label.setText(_alignment_source_mix_reopening_archive_status_helper(selected_source.path))
        dialog.reject()
        QTimer.singleShot(
            0,
            lambda target_entry=entry, selected_source=selected_source: self._start_archive_in_game_mesh_swap(
                target_entry,
                selected_source,
            ),
        )

    def _add_loose_source_folder_for_alignment() -> None:
        selected_dir = QFileDialog.getExistingDirectory(
            dialog,
            source_mix_control_text["add_loose"],
            str(self._suggest_workspace_base_dir()),
        )
        if not selected_dir:
            return

        _start_source_task(
            SourceMixScanRequest(source_path=Path(selected_dir), source_kind="loose"),
            run_source_mix_scan,
            status_message=f"Scanning loose mesh source: {Path(selected_dir).name}...",
            title=source_mix_control_text["add_loose"],
            on_complete=lambda result: _handle_loose_source_scan(selected_dir, result),
        )

    def _handle_loose_source_scan(selected_dir: str, result: object) -> None:
        if not isinstance(result, SourceMixScanResult):
            QMessageBox.warning(dialog, source_mix_control_text["add_loose"], "Source scan returned an unexpected result.")
            return
        candidates = result.candidates
        mesh_candidates = [
            candidate
            for candidate in candidates
            if candidate.extension in ARCHIVE_MESH_EXTENSIONS
            and isinstance(candidate.source_path, Path)
        ]
        mesh_count = sum(1 for candidate in candidates if candidate.extension in ARCHIVE_MESH_EXTENSIONS)
        supplemental_count = sum(
            1
            for candidate in candidates
            if candidate.extension in set(SCENE_TEXTURE_SOURCE_EXTENSIONS)
            or candidate.extension in {".xml", ".pami", ".pac_xml", ".pam_xml", ".pamlod_xml", ".app_xml", ".prefabdata_xml"}
        )
        source_mix_status_label.setText(
            _alignment_source_mix_loose_scan_status_helper(
                selected_dir,
                mesh_count=mesh_count,
                supplemental_count=supplemental_count,
            )
        )
        if mesh_candidates:
            selected_candidate = self._choose_archive_mesh_source_dialog(
                dialog,
                title=source_mix_control_text["use_loose_mesh_title"],
                candidates=mesh_candidates,
                prompt=source_mix_control_text["loose_source_prompt"],
                allowed_extensions=tuple(sorted(ARCHIVE_MESH_EXTENSIONS)),
            )
            if isinstance(selected_candidate, SourceMixCandidate):
                source_candidate = selected_candidate
                source_path = source_candidate.source_path
                if isinstance(source_path, Path):
                    _start_source_task(
                        SceneImportRequest(source_path=source_path),
                        run_scene_import,
                        status_message=f"Importing loose mesh source: {source_path.name}...",
                        title=source_mix_control_text["use_loose_mesh_title"],
                        on_complete=lambda scene_result: _handle_loose_scene_import(source_path, scene_result),
                    )
                    return
        QMessageBox.information(
            dialog,
            source_mix_control_text["loose_added_title"],
            _alignment_source_mix_loose_added_message_helper(
                selected_dir,
                mesh_count=mesh_count,
                supplemental_count=supplemental_count,
            ),
        )

    def _handle_loose_scene_import(source_path: object, result: object) -> None:
        if not isinstance(source_path, Path) or not isinstance(result, SceneImportTaskResult):
            QMessageBox.warning(dialog, source_mix_control_text["use_loose_mesh_title"], "Scene import returned an unexpected result.")
            return
        source_scene_result = result.scene
        supplemental_paths = (
            tuple(source_scene_result.discovered_texture_files)
            + tuple(source_scene_result.extracted_embedded_files)
            + tuple(getattr(source_scene_result, "discovered_supplemental_files", ()) or ())
        )
        source_mix_status_label.setText(_alignment_source_mix_reopening_loose_status_helper(source_path))
        dialog.reject()
        QTimer.singleShot(
            0,
            lambda target_entry=entry, selected_source=source_path, scene_result=source_scene_result, source_supplementals=supplemental_paths: self._start_archive_mesh_patch(
                target_entry,
                preset_setup=MeshImportSetupSelection(
                    scene_path=selected_source,
                    import_mode="static_replacement",
                    supplemental_files=tuple(source_supplementals),
                    scene_import_result=scene_result,
                    source_label=f"{source_mix_control_text['loose_source_label_prefix']}{selected_source}",
                    placement_review_title=source_mix_control_text["loose_placement_review_title"],
                    placement_context_note=source_mix_control_text["loose_placement_context_note"],
                ),
            ),
        )

    def _choose_mod_archive_mesh_source_for_alignment() -> None:
        selected_path, _selected_filter = QFileDialog.getOpenFileName(
            dialog,
            source_mix_control_text["add_mod_archive"],
            str(self._suggest_workspace_base_dir()),
            source_mix_control_text["mod_archive_file_filter"],
        )
        if not selected_path:
            return
        _start_source_task(
            SourceMixScanRequest(source_path=Path(selected_path), source_kind="mod_archive"),
            run_source_mix_scan,
            status_message=f"Scanning source mod archive: {Path(selected_path).name}...",
            title=source_mix_control_text["add_mod_archive"],
            on_complete=_handle_mod_archive_scan,
        )

    def _handle_mod_archive_scan(result: object) -> None:
        if not isinstance(result, SourceMixScanResult):
            QMessageBox.warning(dialog, source_mix_control_text["add_mod_archive"], "Source scan returned an unexpected result.")
            return
        candidates = result.candidates
        mesh_candidates = [candidate for candidate in candidates if candidate.extension in ARCHIVE_MESH_EXTENSIONS and isinstance(candidate.source_archive_entry, ArchiveEntry)]
        if not mesh_candidates:
            QMessageBox.information(
                dialog,
                source_mix_control_text["add_mod_archive"],
                source_mix_control_text["no_mod_archive_mesh_entries"],
            )
            return
        selected_candidate = self._choose_archive_mesh_source_dialog(
            dialog,
            title=source_mix_control_text["use_mod_archive_mesh_title"],
            candidates=mesh_candidates,
            prompt=source_mix_control_text["mod_archive_source_prompt"],
            allowed_extensions=tuple(sorted(ARCHIVE_MESH_EXTENSIONS)),
        )
        if not isinstance(selected_candidate, SourceMixCandidate):
            return
        source_candidate = selected_candidate
        source_entry = source_candidate.source_archive_entry
        if not isinstance(source_entry, ArchiveEntry):
            return
        source_mix_status_label.setText(_alignment_source_mix_reopening_mod_archive_status_helper(source_entry.path))
        dialog.reject()
        QTimer.singleShot(
            0,
            lambda target_entry=entry, selected_source=source_entry: self._start_archive_in_game_mesh_swap(
                target_entry,
                selected_source,
            ),
        )

    return SimpleNamespace(
        _choose_loaded_archive_mesh_source_for_alignment=_choose_loaded_archive_mesh_source_for_alignment,
        _add_loose_source_folder_for_alignment=_add_loose_source_folder_for_alignment,
        _choose_mod_archive_mesh_source_for_alignment=_choose_mod_archive_mesh_source_for_alignment,
    )
