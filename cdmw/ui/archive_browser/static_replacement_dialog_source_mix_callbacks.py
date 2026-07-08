"""Source-mix callback factory for the static replacement dialog."""

from __future__ import annotations

from types import SimpleNamespace


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
    import_scene_mesh_with_report = context.get('import_scene_mesh_with_report')
    scan_loose_folder_source = context.get('scan_loose_folder_source')
    scan_mod_archive_source = context.get('scan_mod_archive_source')
    self = context.get('self')
    source_mix_control_text = context.get('source_mix_control_text')
    source_mix_status_label = context.get('source_mix_status_label')

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
        try:
            candidates = scan_loose_folder_source(Path(selected_dir))
        except Exception as exc:
            # User-visible: source scanning may raise parser, archive, filesystem, or validation errors.
            QMessageBox.warning(dialog, source_mix_control_text["add_loose"], str(exc))
            return
        mesh_candidates = [
            candidate
            for candidate in candidates
            if candidate.extension in ARCHIVE_MESH_EXTENSIONS
            and isinstance(candidate.source_path, Path)
            and candidate.source_path.is_file()
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
                    try:
                        source_scene_result = import_scene_mesh_with_report(source_path)
                    except Exception as exc:
                        # User-visible: scene import reports format, parser, and dependency failures directly.
                        QMessageBox.warning(dialog, source_mix_control_text["use_loose_mesh_title"], str(exc))
                        return
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

    def _choose_mod_archive_mesh_source_for_alignment() -> None:
        selected_path, _selected_filter = QFileDialog.getOpenFileName(
            dialog,
            source_mix_control_text["add_mod_archive"],
            str(self._suggest_workspace_base_dir()),
            source_mix_control_text["mod_archive_file_filter"],
        )
        if not selected_path:
            return
        try:
            candidates = scan_mod_archive_source(Path(selected_path))
        except Exception as exc:
            # User-visible: mod archive scanning may fail from archive, format, or validation errors.
            QMessageBox.warning(dialog, source_mix_control_text["add_mod_archive"], str(exc))
            return
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
