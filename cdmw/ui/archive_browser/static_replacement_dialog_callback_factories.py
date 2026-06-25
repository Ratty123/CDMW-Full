"""Callback factories for static replacement dialog owner clusters."""

from __future__ import annotations

from types import SimpleNamespace


def create_alignment_mesh_diagnostics_callbacks(context: dict[str, object]) -> SimpleNamespace:
    List = context.get('List')
    ModelPreviewData = context.get('ModelPreviewData')
    Path = context.get('Path')
    QApplication = context.get('QApplication')
    QPlainTextEdit = context.get('QPlainTextEdit')
    QProcess = context.get('QProcess')
    _alignment_d3d11_preview_active = context.get('_alignment_d3d11_preview_active')
    _alignment_mesh_edit_tab_active = context.get('_alignment_mesh_edit_tab_active')
    _alignment_preview_source_face_limit = context.get('_alignment_preview_source_face_limit')
    _mesh_edit_raw_preview_active = context.get('_mesh_edit_raw_preview_active')
    _mesh_editor_diagnostics_append_safe_value_helper = context.get('_mesh_editor_diagnostics_append_safe_value_helper')
    _mesh_editor_diagnostics_copied_status_helper = context.get('_mesh_editor_diagnostics_copied_status_helper')
    _mesh_editor_diagnostics_manifest_lines = context.get('_mesh_editor_diagnostics_manifest_lines')
    _mesh_editor_diagnostics_model_lines = context.get('_mesh_editor_diagnostics_model_lines')
    _mesh_editor_diagnostics_record_text_helper = context.get('_mesh_editor_diagnostics_record_text_helper')
    _mesh_editor_diagnostics_source_mesh_lines = context.get('_mesh_editor_diagnostics_source_mesh_lines')
    _mesh_editor_diagnostics_text_widget_helper = context.get('_mesh_editor_diagnostics_text_widget_helper')
    _source_index_is_enabled_renderable = context.get('_source_index_is_enabled_renderable')
    alignment_d3d11_preview_status_label = context.get('alignment_d3d11_preview_status_label')
    alignment_d3d11_state = context.get('alignment_d3d11_state')
    embedded_alignment_builder = context.get('embedded_alignment_builder')
    entry = context.get('entry')
    find_native_d3d11_host = context.get('find_native_d3d11_host')
    highlighted_source_indices = context.get('highlighted_source_indices')
    json = context.get('json')
    mesh_edit_enabled_checkbox = context.get('mesh_edit_enabled_checkbox')
    mesh_edit_scope_combo = context.get('mesh_edit_scope_combo')
    mesh_edit_show_vertices_checkbox = context.get('mesh_edit_show_vertices_checkbox')
    mesh_edit_tool_combo = context.get('mesh_edit_tool_combo')
    mesh_editor_diagnostics_state = context.get('mesh_editor_diagnostics_state')
    obj_path = context.get('obj_path')
    preview_mode_combo = context.get('preview_mode_combo')
    preview_performance_label = context.get('preview_performance_label')
    preview_render_mode_combo = context.get('preview_render_mode_combo')
    preview_renderer_combo = context.get('preview_renderer_combo')
    preview_visible_mode_combo = context.get('preview_visible_mode_combo')
    replacement_mesh_base_for_mapping = context.get('replacement_mesh_base_for_mapping')
    replacement_mesh_for_mapping = context.get('replacement_mesh_for_mapping')
    replacement_preview_model = context.get('replacement_preview_model')
    selected_source_part = context.get('selected_source_part')
    self = context.get('self')
    texture_files_for_mapping = context.get('texture_files_for_mapping') or ()
    texture_sets = context.get('texture_sets') or {}
    time = context.get('time')

    def _mesh_edit_tab_active() -> bool:
        if not callable(_alignment_mesh_edit_tab_active):
            return False
        return bool(_alignment_mesh_edit_tab_active())

    def _mesh_edit_enabled_checked() -> bool:
        is_checked = getattr(mesh_edit_enabled_checkbox, "isChecked", None)
        if not callable(is_checked):
            return False
        try:
            return bool(is_checked())
        except RuntimeError:
            return False

    def _refresh_mesh_editor_diagnostics(*, auto: bool = False) -> None:
        text_widget = _mesh_editor_diagnostics_text_widget_helper(mesh_editor_diagnostics_state)
        if not isinstance(text_widget, QPlainTextEdit):
            return
        lines: List[str] = []

        lines.append("Mesh Editor Replacement Diagnostics")
        lines.append(f"updated: {time.strftime('%Y-%m-%d %H:%M:%S')}")
        lines.append("")
        _mesh_editor_diagnostics_append_safe_value_helper(lines, "target", lambda: str(getattr(entry, "path", "") or getattr(entry, "basename", "") or ""))
        _mesh_editor_diagnostics_append_safe_value_helper(lines, "source", lambda: str(obj_path))
        _mesh_editor_diagnostics_append_safe_value_helper(lines, "embedded_builder", lambda: bool(embedded_alignment_builder))
        _mesh_editor_diagnostics_append_safe_value_helper(lines, "native_host", lambda: str(find_native_d3d11_host() or "missing"))
        _mesh_editor_diagnostics_append_safe_value_helper(lines, "preview_mode", lambda: str(preview_mode_combo.currentData() or ""))
        _mesh_editor_diagnostics_append_safe_value_helper(lines, "renderer", lambda: str(preview_renderer_combo.currentData() or ""))
        _mesh_editor_diagnostics_append_safe_value_helper(lines, "render_diagnostic_mode", lambda: str(preview_render_mode_combo.currentData() or ""))
        _mesh_editor_diagnostics_append_safe_value_helper(lines, "visible_texture_mode", lambda: str(preview_visible_mode_combo.currentData() or ""))
        _mesh_editor_diagnostics_append_safe_value_helper(lines, "d3d11_active", lambda: bool(_alignment_d3d11_preview_active()))
        _mesh_editor_diagnostics_append_safe_value_helper(lines, "d3d11_status_label", lambda: alignment_d3d11_preview_status_label.text())
        _mesh_editor_diagnostics_append_safe_value_helper(lines, "preview_timing_label", lambda: preview_performance_label.text())
        _mesh_editor_diagnostics_append_safe_value_helper(lines, "mesh_edit_tab_active", _mesh_edit_tab_active)
        _mesh_editor_diagnostics_append_safe_value_helper(lines, "mesh_edit_enabled", _mesh_edit_enabled_checked)
        _mesh_editor_diagnostics_append_safe_value_helper(lines, "mesh_edit_raw_preview_active", lambda: bool(_mesh_edit_raw_preview_active()))
        _mesh_editor_diagnostics_append_safe_value_helper(lines, "mesh_edit_show_vertices", lambda: bool(mesh_edit_show_vertices_checkbox.isChecked()))
        _mesh_editor_diagnostics_append_safe_value_helper(lines, "mesh_edit_tool", lambda: str(mesh_edit_tool_combo.currentData() or ""))
        _mesh_editor_diagnostics_append_safe_value_helper(lines, "mesh_edit_scope", lambda: str(mesh_edit_scope_combo.currentData() or ""))
        _mesh_editor_diagnostics_append_safe_value_helper(lines, "source_face_limit", lambda: int(_alignment_preview_source_face_limit()))
        _mesh_editor_diagnostics_append_safe_value_helper(lines, "selected_source", lambda: int(selected_source_part.get("index", -1)))
        _mesh_editor_diagnostics_append_safe_value_helper(lines, "highlighted_sources", lambda: tuple(sorted(int(index) for index in highlighted_source_indices)))
        lines.append("")
        lines.append("D3D11 state")
        for key in (
            "request_id",
            "preview_loaded",
            "resources_loaded",
            "preview_pipeline_stage",
            "package_quality",
            "replacement_only_direct_source_preview",
            "source_owned_direct_source_preview",
            "force_direct_source_preview",
            "active_package_quality",
            "active_package_display_mode",
            "last_cache_event",
            "last_cache_reason",
            "last_rebuild_reason",
            "active_package_cache_key",
            "prepare_ms",
            "package_ms",
            "loading_percent",
            "loading_stage",
            "loading_message",
        ):
            lines.append(f"  {key}: {alignment_d3d11_state.get(key)}")
        lines.append(f"  active_package: {alignment_d3d11_state.get('active_package')}")
        lines.append(f"  status_file: {alignment_d3d11_state.get('status_file')}")
        process = alignment_d3d11_state.get("process")
        if isinstance(process, QProcess):
            lines.append(f"  process_state: {process.state()}")
            lines.append(f"  process_program: {process.program()}")
            lines.append(f"  process_arguments: {' '.join(process.arguments())}")
        lines.append("")
        lines.append("Source geometry")
        try:
            lines.extend(
                _mesh_editor_diagnostics_source_mesh_lines(
                    "replacement_mesh_for_mapping",
                    replacement_mesh_for_mapping,
                    enabled_predicate=_source_index_is_enabled_renderable,
                )
            )
            lines.extend(
                _mesh_editor_diagnostics_source_mesh_lines(
                    "replacement_mesh_base_for_mapping",
                    replacement_mesh_base_for_mapping,
                    limit=6,
                    enabled_predicate=_source_index_is_enabled_renderable,
                )
            )
        except NameError as exc:
            lines.append(f"source geometry unavailable: {exc}")
        lines.append("")
        lines.append("Preview model")
        try:
            lines.extend(_mesh_editor_diagnostics_model_lines("replacement_preview_model", replacement_preview_model))
        except NameError as exc:
            lines.append(f"preview model unavailable: {exc}")
        queued_model = alignment_d3d11_state.get("queued_model")
        pending_model = alignment_d3d11_state.get("pending_model")
        if isinstance(queued_model, ModelPreviewData):
            lines.extend(_mesh_editor_diagnostics_model_lines("queued_d3d11_model", queued_model, limit=8))
        if isinstance(pending_model, ModelPreviewData):
            lines.extend(_mesh_editor_diagnostics_model_lines("pending_d3d11_model", pending_model, limit=8))
        lines.append("")
        lines.append("Material groups")
        try:
            texture_file_count = len(texture_files_for_mapping)
        except NameError:
            texture_file_count = 0
        try:
            lines.append(f"  texture_files_for_mapping={texture_file_count:,} texture_sets={len(texture_sets):,}")
            for index, texture_set in enumerate(list(texture_sets.values())[:18]):
                slots = getattr(texture_set, "slots", {}) or {}
                slot_text = []
                for slot_name, slot in sorted(slots.items()):
                    source_path = getattr(slot, "source_path", "")
                    slot_text.append(
                        f"{slot_name}:{Path(str(source_path)).name if source_path else '-'}"
                        f":{str(getattr(slot, 'semantic_subtype', '') or '-')}"
                    )
                lines.append(
                    f"  set[{index:02d}] mat={str(getattr(texture_set, 'material_name', '') or '-')[:70]} "
                    f"slots={', '.join(slot_text) or '-'} "
                    f"spec={getattr(texture_set, 'specular_factor', None)} gloss={getattr(texture_set, 'glossiness_factor', None)}"
                )
        except NameError as exc:
            lines.append(f"  material groups unavailable: {exc}")
        lines.append("")
        lines.append("Active package manifest")
        lines.extend(_mesh_editor_diagnostics_manifest_lines(alignment_d3d11_state.get("active_package")))
        lines.append("")
        lines.append("Latest native status")
        status_payload_text = str(alignment_d3d11_state.get("status_payload_text", "") or "").strip()
        if status_payload_text:
            try:
                status_payload = json.loads(status_payload_text)
                lines.append(json.dumps(status_payload, indent=2, sort_keys=True)[:12000])
            except Exception:
                lines.append(status_payload_text[:12000])
        else:
            lines.append("no status payload yet")

        text = "\n".join(lines)
        if not _mesh_editor_diagnostics_record_text_helper(mesh_editor_diagnostics_state, text, auto=auto):
            return
        try:
            cursor_position = int(text_widget.textCursor().position())
            text_widget.setPlainText(text)
            cursor = text_widget.textCursor()
            cursor.setPosition(max(0, min(cursor_position, len(text))))
            text_widget.setTextCursor(cursor)
        except RuntimeError:
            pass

    def _copy_mesh_editor_diagnostics() -> None:
        text_widget = _mesh_editor_diagnostics_text_widget_helper(mesh_editor_diagnostics_state)
        if not isinstance(text_widget, QPlainTextEdit):
            return
        QApplication.clipboard().setText(text_widget.toPlainText())
        self.set_status_message(_mesh_editor_diagnostics_copied_status_helper())

    return SimpleNamespace(
        _refresh_mesh_editor_diagnostics=_refresh_mesh_editor_diagnostics,
        _copy_mesh_editor_diagnostics=_copy_mesh_editor_diagnostics,
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


def create_material_authority_adjustment_callbacks(context: dict[str, object]) -> SimpleNamespace:
    Dict = context.get('Dict')
    QSlider = context.get('QSlider')
    QSpinBox = context.get('QSpinBox')
    _complete_external_swap_enabled = context.get('_complete_external_swap_enabled')
    _current_complete_swap_material_profile_token = context.get('_current_complete_swap_material_profile_token')
    _manual_material_profile_fallback_payload_helper = context.get('_manual_material_profile_fallback_payload_helper')
    _material_authority_adjustment_refresh_reason_helper = context.get('_material_authority_adjustment_refresh_reason_helper')
    _material_authority_adjustment_setting_state_helper = context.get('_material_authority_adjustment_setting_state_helper')
    _material_authority_adjustment_status_text_helper = context.get('_material_authority_adjustment_status_text_helper')
    _material_authority_apply_sidecar_control_state_helper = context.get('_material_authority_apply_sidecar_control_state_helper')
    _material_authority_basic_controls_hint_helper = context.get('_material_authority_basic_controls_hint_helper')
    _material_authority_basic_controls_profile_enabled_helper = context.get('_material_authority_basic_controls_profile_enabled_helper')
    _material_authority_clamped_int_helper = context.get('_material_authority_clamped_int_helper')
    _material_authority_controls_affect_visible_preview_helper = context.get('_material_authority_controls_affect_visible_preview_helper')
    _material_authority_edge_relief_source_helper = context.get('_material_authority_edge_relief_source_helper')
    _material_authority_edge_relief_source_setting_helper = context.get('_material_authority_edge_relief_source_setting_helper')
    _material_authority_global_gloss_reduction_hint_helper = context.get('_material_authority_global_gloss_reduction_hint_helper')
    _material_authority_preview_inactive_reason_helper = context.get('_material_authority_preview_inactive_reason_helper')
    _material_authority_preview_signature_helper = context.get('_material_authority_preview_signature_helper')
    _material_authority_profile_adjustment_kwargs_helper = context.get('_material_authority_profile_adjustment_kwargs_helper')
    _material_authority_reset_values_helper = context.get('_material_authority_reset_values_helper')
    _material_authority_sidecar_dependent_toggle_state_helper = context.get('_material_authority_sidecar_dependent_toggle_state_helper')
    _material_authority_sidecar_option_state_helper = context.get('_material_authority_sidecar_option_state_helper')
    _original_texture_preview_material_preview_enabled_helper = context.get('_original_texture_preview_material_preview_enabled_helper')
    _queue_material_edit_refresh = context.get('_queue_material_edit_refresh')
    _queue_texture_preview_refresh = context.get('_queue_texture_preview_refresh')
    _refresh_manual_material_profile_panel = context.get('_refresh_manual_material_profile_panel')
    _refresh_output_impact_review = context.get('_refresh_output_impact_review')
    _refresh_part_glow_color_controls_enabled = context.get('_refresh_part_glow_color_controls_enabled')
    _selected_part_glow_rgb_from_controls = context.get('_selected_part_glow_rgb_from_controls')
    _set_int_slider_spin_value_silently_helper = context.get('_set_int_slider_spin_value_silently_helper')
    accent_glow_slider = context.get('accent_glow_slider')
    accent_glow_spin = context.get('accent_glow_spin')
    apply_true_source_basic_controls_to_profile = context.get('apply_true_source_basic_controls_to_profile')
    auto_brightness_slider = context.get('auto_brightness_slider')
    auto_brightness_spin = context.get('auto_brightness_spin')
    complete_swap_material_profile_combo = context.get('complete_swap_material_profile_combo')
    complete_swap_material_profile_to_dict = context.get('complete_swap_material_profile_to_dict')
    edge_relief_slider = context.get('edge_relief_slider')
    edge_relief_source_combo = context.get('edge_relief_source_combo')
    edge_relief_spin = context.get('edge_relief_spin')
    external_material_reset_checkbox = context.get('external_material_reset_checkbox')
    get_complete_swap_material_profile = context.get('get_complete_swap_material_profile')
    global_gloss_reduction_hint = context.get('global_gloss_reduction_hint')
    global_gloss_reduction_slider = context.get('global_gloss_reduction_slider')
    global_gloss_reduction_spin = context.get('global_gloss_reduction_spin')
    inject_base_color_checkbox = context.get('inject_base_color_checkbox')
    material_authority_preview_texture_slots = context.get('material_authority_preview_texture_slots')
    modify_original_clone_mode = context.get('modify_original_clone_mode')
    original_texture_preview_state = context.get('original_texture_preview_state')
    part_glow_color_checkbox = context.get('part_glow_color_checkbox')
    prune_unmapped_original_dds_checkbox = context.get('prune_unmapped_original_dds_checkbox')
    rebuild_sidecar_checkbox = context.get('rebuild_sidecar_checkbox')
    self = context.get('self')
    source_brightness_slider = context.get('source_brightness_slider')
    source_brightness_spin = context.get('source_brightness_spin')
    source_color_faithful_checkbox = context.get('source_color_faithful_checkbox')
    source_part_adjustments = context.get('source_part_adjustments')
    texture_sets = context.get('texture_sets')
    tone_contrast_slider = context.get('tone_contrast_slider')
    tone_contrast_spin = context.get('tone_contrast_spin')
    true_source_basic_group = context.get('true_source_basic_group')
    true_source_basic_hint = context.get('true_source_basic_hint')
    true_source_basic_reset_button = context.get('true_source_basic_reset_button')
    unsafe_material_preflight_checkbox = context.get('unsafe_material_preflight_checkbox')

    def _set_global_gloss_reduction(value: int, *, refresh: bool = True) -> None:
        value = _material_authority_clamped_int_helper(value, default=0, minimum=-100, maximum=100)
        value = _set_int_slider_spin_value_silently_helper(
            global_gloss_reduction_slider,
            global_gloss_reduction_spin,
            value,
            minimum=-100,
            maximum=100,
        )
        self.settings.setValue("settings/complete_swap_global_gloss_reduction", value)
        _refresh_global_gloss_reduction_hint()
        if refresh:
            _refresh_output_impact_review()
            _queue_material_authority_adjustment_preview_refresh()

    def _refresh_global_gloss_reduction_hint() -> None:
        value = int(global_gloss_reduction_spin.value())
        profile_name = str(complete_swap_material_profile_combo.currentData() or "")
        global_gloss_reduction_hint.setText(
            _material_authority_global_gloss_reduction_hint_helper(
                complete_enabled=_complete_external_swap_enabled(),
                profile_name=profile_name,
                value=value,
            )
        )

    def _basic_controls_profile_enabled() -> bool:
        profile_name = str(complete_swap_material_profile_combo.currentData() or "")
        return _material_authority_basic_controls_profile_enabled_helper(profile_name)

    def _current_material_authority_preview_profile() -> object:
        return apply_true_source_basic_controls_to_profile(
            get_complete_swap_material_profile(str(_current_complete_swap_material_profile_token())),
            **_material_authority_profile_adjustment_kwargs_helper(
                global_gloss_reduction=global_gloss_reduction_spin.value(),
                edge_relief=edge_relief_spin.value(),
                edge_relief_source=edge_relief_source_combo.currentData(),
                accent_glow=accent_glow_spin.value(),
                auto_brightness=auto_brightness_spin.value(),
                source_brightness=source_brightness_spin.value(),
                tone_contrast=tone_contrast_spin.value(),
            ),
        )

    def _material_authority_preview_signature() -> Dict[str, str]:
        return _material_authority_preview_signature_helper(
            texture_sets=texture_sets,
            profile=_current_material_authority_preview_profile(),
            source_part_adjustments=source_part_adjustments,
            global_gloss_reduction=global_gloss_reduction_spin.value(),
            auto_brightness=auto_brightness_spin.value(),
            source_brightness=source_brightness_spin.value(),
            tone_contrast=tone_contrast_spin.value(),
            edge_relief=edge_relief_spin.value(),
            edge_relief_source=edge_relief_source_combo.currentData(),
            accent_glow=accent_glow_spin.value(),
            glow_color_enabled=part_glow_color_checkbox.isChecked(),
            glow_rgb=_selected_part_glow_rgb_from_controls(),
            texture_slots_resolver=material_authority_preview_texture_slots,
            profile_payload_builder=complete_swap_material_profile_to_dict,
            fallback_profile_payload_builder=_manual_material_profile_fallback_payload_helper,
        )

    def _material_authority_preview_inactive_reason() -> str:
        original_material_preview_active = False
        try:
            original_material_preview_active = _original_texture_preview_material_preview_enabled_helper(
                modify_original_clone_mode,
                original_texture_preview_state,
            )
        except Exception:
            pass
        return _material_authority_preview_inactive_reason_helper(
            complete_enabled=_complete_external_swap_enabled(),
            basic_profile_enabled=_basic_controls_profile_enabled(),
            has_texture_sets=bool(texture_sets),
            original_material_preview_active=original_material_preview_active,
        )

    def _material_authority_controls_affect_visible_preview() -> bool:
        return _material_authority_controls_affect_visible_preview_helper(
            _material_authority_preview_inactive_reason()
        )

    def _queue_material_authority_adjustment_preview_refresh() -> None:
        inactive_reason = _material_authority_preview_inactive_reason()
        if inactive_reason:
            status_text = _material_authority_adjustment_status_text_helper(
                basic_profile_enabled=_basic_controls_profile_enabled(),
                inactive_reason=inactive_reason,
            )
            if status_text:
                true_source_basic_hint.setText(status_text)
            return
        true_source_basic_hint.setText(
            _material_authority_adjustment_status_text_helper(
                basic_profile_enabled=True,
                inactive_reason="",
            )
        )
        _queue_material_edit_refresh(
            refresh_plan=False,
            refresh_preview=True,
            reason=_material_authority_adjustment_refresh_reason_helper(),
        )

    def _set_spin_slider_pair(
        slider: QSlider,
        spin: QSpinBox,
        value: int,
        settings_key: str,
        *,
        minimum: int = 0,
        maximum: int = 100,
        refresh: bool = True,
    ) -> None:
        state = _material_authority_adjustment_setting_state_helper(
            value,
            default=minimum,
            minimum=minimum,
            maximum=maximum,
            settings_key=settings_key,
        )
        value = _set_int_slider_spin_value_silently_helper(
            slider,
            spin,
            int(state["value"]),
            minimum=minimum,
            maximum=maximum,
        )
        if state["settings_key"]:
            self.settings.setValue(str(state["settings_key"]), value)
        if refresh:
            _refresh_output_impact_review()
            _queue_material_authority_adjustment_preview_refresh()

    def _set_edge_relief(value: int, *, refresh: bool = True) -> None:
        _set_spin_slider_pair(
            edge_relief_slider,
            edge_relief_spin,
            value,
            "settings/complete_swap_edge_relief_strength",
            refresh=refresh,
        )

    def _set_source_brightness(value: int, *, refresh: bool = True) -> None:
        _set_spin_slider_pair(
            source_brightness_slider,
            source_brightness_spin,
            value,
            "settings/complete_swap_source_brightness",
            minimum=-100,
            maximum=100,
            refresh=refresh,
        )

    def _set_tone_contrast(value: int, *, refresh: bool = True) -> None:
        _set_spin_slider_pair(
            tone_contrast_slider,
            tone_contrast_spin,
            value,
            "settings/complete_swap_tone_contrast",
            minimum=-100,
            maximum=100,
            refresh=refresh,
        )

    def _set_auto_brightness(value: int, *, refresh: bool = True) -> None:
        _set_spin_slider_pair(
            auto_brightness_slider,
            auto_brightness_spin,
            value,
            "settings/complete_swap_auto_brightness",
            refresh=refresh,
        )

    def _set_edge_relief_source(*, refresh: bool = True) -> None:
        state = _material_authority_edge_relief_source_setting_helper(edge_relief_source_combo.currentData())
        self.settings.setValue(str(state["settings_key"]), str(state["value"]))
        if refresh:
            _refresh_output_impact_review()
            _queue_material_authority_adjustment_preview_refresh()

    def _set_accent_glow(value: int, *, refresh: bool = True) -> None:
        _set_spin_slider_pair(
            accent_glow_slider,
            accent_glow_spin,
            value,
            "",
            refresh=refresh,
        )
        if callable(_refresh_part_glow_color_controls_enabled):
            _refresh_part_glow_color_controls_enabled()

    def _set_edge_relief_source_value(value: str, *, refresh: bool = True) -> None:
        index = edge_relief_source_combo.findData(_material_authority_edge_relief_source_helper(value))
        if index < 0:
            index = 0
        if edge_relief_source_combo.currentIndex() != index:
            edge_relief_source_combo.blockSignals(True)
            edge_relief_source_combo.setCurrentIndex(index)
            edge_relief_source_combo.blockSignals(False)
        _set_edge_relief_source(refresh=refresh)

    def _reset_material_authority_adjustments() -> None:
        reset_values = _material_authority_reset_values_helper()
        _set_global_gloss_reduction(int(reset_values["global_gloss_reduction"]), refresh=False)
        _set_auto_brightness(int(reset_values["auto_brightness"]), refresh=False)
        _set_source_brightness(int(reset_values["source_brightness"]), refresh=False)
        _set_tone_contrast(int(reset_values["tone_contrast"]), refresh=False)
        _set_edge_relief(int(reset_values["edge_relief"]), refresh=False)
        _set_edge_relief_source_value(str(reset_values["edge_relief_source"]), refresh=False)
        _set_accent_glow(int(reset_values["accent_glow"]), refresh=False)
        _refresh_output_impact_review()
        _refresh_global_gloss_reduction_hint()
        _queue_material_authority_adjustment_preview_refresh()

    def _refresh_true_source_basic_controls_state() -> None:
        if bool(context.get("full_import_model_replacement")):
            true_source_basic_group.setVisible(False)
            true_source_basic_group.setEnabled(False)
            true_source_basic_hint.setText(
                "Material Authority tuning is locked by Full Import Model Replacement."
            )
            return
        visible = _basic_controls_profile_enabled()
        enabled = bool(visible)
        true_source_basic_group.setVisible(bool(visible))
        true_source_basic_group.setEnabled(enabled)
        true_source_basic_hint.setText(
            _material_authority_basic_controls_hint_helper(
                visible=bool(visible),
                enabled=bool(enabled),
                inactive_reason=_material_authority_preview_inactive_reason() if enabled else "",
            )
        )

    def _refresh_sidecar_option_state() -> None:
        enabled = rebuild_sidecar_checkbox.isChecked()
        complete_mode = _complete_external_swap_enabled()
        sidecar_state = _material_authority_apply_sidecar_control_state_helper(
            _material_authority_sidecar_option_state_helper(
                sidecar_enabled=bool(enabled),
                complete_mode=bool(complete_mode),
                unsafe_preflight_checked=bool(unsafe_material_preflight_checkbox.isChecked()),
            ),
            rebuild_sidecar_widget=rebuild_sidecar_checkbox,
            dependent_widgets=(
                prune_unmapped_original_dds_checkbox,
                inject_base_color_checkbox,
                source_color_faithful_checkbox,
                external_material_reset_checkbox,
            ),
            complete_widgets=(
                complete_swap_material_profile_combo,
                global_gloss_reduction_slider,
                global_gloss_reduction_spin,
                auto_brightness_slider,
                auto_brightness_spin,
                source_brightness_slider,
                source_brightness_spin,
                tone_contrast_slider,
                tone_contrast_spin,
                accent_glow_slider,
                accent_glow_spin,
                true_source_basic_reset_button,
            ),
            unsafe_preflight_widget=unsafe_material_preflight_checkbox,
        )
        if sidecar_state["force_rebuild_sidecar"]:
            return
        if callable(_refresh_part_glow_color_controls_enabled):
            _refresh_part_glow_color_controls_enabled()
        _refresh_global_gloss_reduction_hint()
        _refresh_manual_material_profile_panel()
        _refresh_true_source_basic_controls_state()

    def _apply_sidecar_dependent_toggle(checked: bool, *, refresh_output: bool = False) -> None:
        state = _material_authority_sidecar_dependent_toggle_state_helper(
            checked=checked,
            rebuild_sidecar_checked=rebuild_sidecar_checkbox.isChecked(),
            refresh_output=refresh_output,
        )
        if state["force_rebuild_sidecar"]:
            rebuild_sidecar_checkbox.setChecked(True)
            return
        if state["refresh_output"]:
            _refresh_output_impact_review()
        if state["refresh_preview"]:
            _queue_texture_preview_refresh()

    return SimpleNamespace(
        _set_global_gloss_reduction=_set_global_gloss_reduction,
        _refresh_global_gloss_reduction_hint=_refresh_global_gloss_reduction_hint,
        _basic_controls_profile_enabled=_basic_controls_profile_enabled,
        _current_material_authority_preview_profile=_current_material_authority_preview_profile,
        _material_authority_preview_signature=_material_authority_preview_signature,
        _material_authority_preview_inactive_reason=_material_authority_preview_inactive_reason,
        _material_authority_controls_affect_visible_preview=_material_authority_controls_affect_visible_preview,
        _queue_material_authority_adjustment_preview_refresh=_queue_material_authority_adjustment_preview_refresh,
        _set_spin_slider_pair=_set_spin_slider_pair,
        _set_edge_relief=_set_edge_relief,
        _set_source_brightness=_set_source_brightness,
        _set_tone_contrast=_set_tone_contrast,
        _set_auto_brightness=_set_auto_brightness,
        _set_edge_relief_source=_set_edge_relief_source,
        _set_accent_glow=_set_accent_glow,
        _set_edge_relief_source_value=_set_edge_relief_source_value,
        _reset_material_authority_adjustments=_reset_material_authority_adjustments,
        _refresh_true_source_basic_controls_state=_refresh_true_source_basic_controls_state,
        _refresh_sidecar_option_state=_refresh_sidecar_option_state,
        _apply_sidecar_dependent_toggle=_apply_sidecar_dependent_toggle,
    )


def create_alignment_source_role_tree_callbacks(context: dict[str, object]) -> SimpleNamespace:
    QMenu = context.get('QMenu')
    _add_source_tree_item = context.get('_add_source_tree_item')
    _alignment_part_clipboard_can_paste = context.get('_alignment_part_clipboard_can_paste')
    _apply_source_part_preview_changes = context.get('_apply_source_part_preview_changes')
    _delete_selected_source_parts = context.get('_delete_selected_source_parts')
    _finish_source_tree_population = context.get('_finish_source_tree_population')
    _load_selected_part_controls = context.get('_load_selected_part_controls')
    _paste_alignment_part_clipboard_as_replacement_source = context.get('_paste_alignment_part_clipboard_as_replacement_source')
    _push_geometry_undo_snapshot = context.get('_push_geometry_undo_snapshot')
    _queue_material_edit_refresh = context.get('_queue_material_edit_refresh')
    _refresh_parts_outliner = context.get('_refresh_parts_outliner')
    _refresh_source_assignment_columns = context.get('_refresh_source_assignment_columns')
    _selected_source_index = context.get('_selected_source_index')
    _selected_source_indices_from_tree = context.get('_selected_source_indices_from_tree')
    _set_source_role_override_value = context.get('_set_source_role_override_value')
    _source_index_from_tree_item = context.get('_source_index_from_tree_item')
    _source_part_context_menu_text_helper = context.get('_source_part_context_menu_text_helper')
    _source_part_role_action_state_helper = context.get('_source_part_role_action_state_helper')
    _source_tree_context_menu_selection_state_helper = context.get('_source_tree_context_menu_selection_state_helper')
    _source_tree_context_selection_clear_multi_indices_helper = context.get('_source_tree_context_selection_clear_multi_indices_helper')
    _source_tree_context_selection_multi_indices_helper = context.get('_source_tree_context_selection_multi_indices_helper')
    _source_tree_context_selection_set_right_press_helper = context.get('_source_tree_context_selection_set_right_press_helper')
    _source_tree_population_chunk_policy_helper = context.get('_source_tree_population_chunk_policy_helper')
    _source_tree_population_loading_text_helper = context.get('_source_tree_population_loading_text_helper')
    _source_tree_population_next_index_helper = context.get('_source_tree_population_next_index_helper')
    _source_tree_population_set_next_index_helper = context.get('_source_tree_population_set_next_index_helper')
    original_part_clipboard_action_text = context.get('original_part_clipboard_action_text')
    pos = context.get('pos')
    replacement_mesh_for_mapping = context.get('replacement_mesh_for_mapping')
    role_value = context.get('role_value')
    source_items_by_index = context.get('source_items_by_index')
    source_parts_apply_state = context.get('source_parts_apply_state')
    source_tree = context.get('source_tree')
    source_tree_context_selection_state = context.get('source_tree_context_selection_state')
    source_tree_population_state = context.get('source_tree_population_state')
    source_tree_population_timer = context.get('source_tree_population_timer')
    source_tree_progress_label = context.get('source_tree_progress_label')
    time = context.get('time')
    undo_label = context.get('undo_label')

    def _apply_source_role_selection(source_index: int, role_value: str, undo_label: str = "Change source role") -> None:
        action_state = _source_part_role_action_state_helper(
            source_index=source_index,
            role_value=role_value,
            undo_label=undo_label,
        )
        if not action_state.available:
            return
        _push_geometry_undo_snapshot(action_state.undo_label)
        _set_source_role_override_value(action_state.source_index, action_state.normalized_role)
        _refresh_source_assignment_columns(lightweight=True)
        try:
            _refresh_parts_outliner()
        except NameError:
            pass
        try:
            _load_selected_part_controls()
        except NameError:
            pass
        _queue_material_edit_refresh(
            refresh_plan=action_state.refresh_plan,
            force_plan=action_state.force_plan,
            refresh_preview=action_state.refresh_preview,
            reason=action_state.refresh_reason,
        )

    def _show_replacement_sources_context_menu(pos: QPoint) -> None:
        item = source_tree.itemAt(pos)
        clicked_source_index = _source_index_from_tree_item(item)
        selected_source_indices = _selected_source_indices_from_tree(include_fallback=False)
        preserved_multi_indices = _source_tree_context_selection_multi_indices_helper(
            source_tree_context_selection_state
        )
        context_selection = _source_tree_context_menu_selection_state_helper(
            clicked_source_index=clicked_source_index,
            selected_source_indices=selected_source_indices,
            preserved_multi_indices=preserved_multi_indices,
            clicked_item_selected=bool(item is not None and item.isSelected()),
        )
        selected_source_indices = list(context_selection.selected_source_indices)
        if item is not None:
            if context_selection.select_clicked_item:
                source_tree.clearSelection()
                item.setSelected(True)
                if context_selection.clear_multi_indices:
                    _source_tree_context_selection_clear_multi_indices_helper(source_tree_context_selection_state)
            source_tree.setCurrentItem(item)
        source_index = _selected_source_index()
        delete_source_indices = selected_source_indices or _selected_source_indices_from_tree(include_fallback=True)
        menu = QMenu(source_tree)
        source_part_context_menu_text = _source_part_context_menu_text_helper()
        delete_action = menu.addAction(source_part_context_menu_text["delete_selected_parts"])
        delete_action.setEnabled(bool(delete_source_indices))
        apply_action = menu.addAction(source_part_context_menu_text["apply"])
        apply_action.setEnabled(bool(source_parts_apply_state.get("pending")))
        menu.addSeparator()
        paste_action = menu.addAction(original_part_clipboard_action_text["paste_replacement_source"])
        paste_action.setEnabled(_alignment_part_clipboard_can_paste())
        menu.addSeparator()
        glow_role_action = menu.addAction(source_part_context_menu_text["set_role_glow"])
        auto_role_action = menu.addAction(source_part_context_menu_text["set_role_auto"])
        glow_role_action.setEnabled(source_index >= 0)
        auto_role_action.setEnabled(source_index >= 0)
        chosen = menu.exec(source_tree.viewport().mapToGlobal(pos))
        if chosen is delete_action:
            _delete_selected_source_parts(delete_source_indices)
        elif chosen is apply_action:
            _apply_source_part_preview_changes()
        elif chosen is paste_action:
            _paste_alignment_part_clipboard_as_replacement_source()
        elif chosen is glow_role_action and source_index >= 0:
            _apply_source_role_selection(source_index, "glow", "Set source role glow")
        elif chosen is auto_role_action and source_index >= 0:
            _apply_source_role_selection(source_index, "", "Clear source role")
        _source_tree_context_selection_set_right_press_helper(source_tree_context_selection_state, False)

    def _populate_source_tree_chunk() -> None:
        if replacement_mesh_for_mapping is None:
            source_tree_population_timer.stop()
            _finish_source_tree_population()
            return
        total = len(getattr(replacement_mesh_for_mapping, "submeshes", ()) or ())
        start = _source_tree_population_next_index_helper(source_tree_population_state)
        chunk_policy = _source_tree_population_chunk_policy_helper()
        deadline = time.perf_counter() + chunk_policy.time_budget_seconds
        added = 0
        while start < total and added < chunk_policy.row_limit and time.perf_counter() < deadline:
            source = replacement_mesh_for_mapping.submeshes[start]
            if start not in source_items_by_index:
                _add_source_tree_item(start, source)
            start += 1
            added += 1
        _source_tree_population_set_next_index_helper(source_tree_population_state, start)
        source_tree_progress_label.setText(
            _source_tree_population_loading_text_helper(min(start, total), total)
        )
        if start >= total:
            source_tree_population_timer.stop()
            _finish_source_tree_population()
        else:
            source_tree_population_timer.start()

    return SimpleNamespace(
        _apply_source_role_selection=_apply_source_role_selection,
        _show_replacement_sources_context_menu=_show_replacement_sources_context_menu,
        _populate_source_tree_chunk=_populate_source_tree_chunk,
    )

def create_alignment_selected_part_control_callbacks(context: dict[str, object]) -> SimpleNamespace:
    Qt = context.get('Qt')
    StaticSourcePartAdjustment = context.get('StaticSourcePartAdjustment')
    _apply_current_glow_color_to_role_overrides = context.get('_apply_current_glow_color_to_role_overrides')
    _clear_transform_source_indices = context.get('_clear_transform_source_indices')
    _copied_original_dds_badge = context.get('_copied_original_dds_badge')
    _copied_original_texture_tooltip = context.get('_copied_original_texture_tooltip')
    _current_dialog_mappings_for_preview = context.get('_current_dialog_mappings_for_preview')
    _ensure_source_part_adjustment = context.get('_ensure_source_part_adjustment')
    _load_part_glow_color_controls = context.get('_load_part_glow_color_controls')
    _mapped_source_indices = context.get('_mapped_source_indices')
    _parse_mapping_edit = context.get('_parse_mapping_edit')
    _part_mapped_target_indices = context.get('_part_mapped_target_indices')
    _push_geometry_undo_snapshot = context.get('_push_geometry_undo_snapshot')
    _queue_material_edit_refresh = context.get('_queue_material_edit_refresh')
    _queue_selection_preview_refresh = context.get('_queue_selection_preview_refresh')
    _queue_static_preview_rebuild = context.get('_queue_static_preview_rebuild')
    _queue_texture_preview_refresh = context.get('_queue_texture_preview_refresh')
    _refresh_copied_original_texture_ui = context.get('_refresh_copied_original_texture_ui')
    _refresh_mesh_edit_controls = context.get('_refresh_mesh_edit_controls')
    _refresh_part_glow_color_controls_enabled = context.get('_refresh_part_glow_color_controls_enabled')
    _refresh_parts_outliner = context.get('_refresh_parts_outliner')
    _refresh_source_assignment_columns = context.get('_refresh_source_assignment_columns')
    _refresh_ui_texture_sets_after_source_part_material_override = context.get('_refresh_ui_texture_sets_after_source_part_material_override')
    _selected_source_indices_from_tree = context.get('_selected_source_indices_from_tree')
    _selected_target_index = context.get('_selected_target_index')
    _set_double_spin_value_silently_helper = context.get('_set_double_spin_value_silently_helper')
    _set_mapping_indices = context.get('_set_mapping_indices')
    _set_source_parts_apply_pending = context.get('_set_source_parts_apply_pending')
    _set_source_parts_preview_rebuild_pending = context.get('_set_source_parts_preview_rebuild_pending')
    _set_source_role_override_value = context.get('_set_source_role_override_value')
    _source_part_control_load_state_helper = context.get('_source_part_control_load_state_helper')
    _source_part_control_state_helper = context.get('_source_part_control_state_helper')
    _source_part_copied_texture_action_state_helper = context.get('_source_part_copied_texture_action_state_helper')
    _source_part_copied_texture_controls_state_helper = context.get('_source_part_copied_texture_controls_state_helper')
    _source_part_copied_texture_status_text_helper = context.get('_source_part_copied_texture_status_text_helper')
    _source_part_display_label_helper = context.get('_source_part_display_label_helper')
    _source_part_edit_undo_label_helper = context.get('_source_part_edit_undo_label_helper')
    _source_part_glow_color_action_state_helper = context.get('_source_part_glow_color_action_state_helper')
    _source_part_include_exclude_pending_reason_helper = context.get('_source_part_include_exclude_pending_reason_helper')
    _source_part_map_to_target_state_helper = context.get('_source_part_map_to_target_state_helper')
    _source_part_output_action_state_helper = context.get('_source_part_output_action_state_helper')
    _source_part_role_action_state_helper = context.get('_source_part_role_action_state_helper')
    _source_part_selected_target_index_helper = context.get('_source_part_selected_target_index_helper')
    _source_part_should_be_preview_only_after_unmap_helper = context.get('_source_part_should_be_preview_only_after_unmap_helper')
    _source_part_source_combo_selection_state_helper = context.get('_source_part_source_combo_selection_state_helper')
    _source_part_target_combo_selection_state_helper = context.get('_source_part_target_combo_selection_state_helper')
    _source_part_unmap_target_states_helper = context.get('_source_part_unmap_target_states_helper')
    _source_role_override_value = context.get('_source_role_override_value')
    _source_target_summary = context.get('_source_target_summary')
    _sync_highlight_sets = context.get('_sync_highlight_sets')
    _sync_part_slider_from_spin = context.get('_sync_part_slider_from_spin')
    _update_mapping_status = context.get('_update_mapping_status')
    _update_selection_context = context.get('_update_selection_context')
    appended_source_indices = context.get('appended_source_indices')
    center_part_button = context.get('center_part_button')
    copied_original_texture_disabled_sources = context.get('copied_original_texture_disabled_sources')
    copied_original_texture_intents_by_source = context.get('copied_original_texture_intents_by_source')
    duplicate_part_button = context.get('duplicate_part_button')
    fit_part_button = context.get('fit_part_button')
    independent_output_source_indices = context.get('independent_output_source_indices')
    mapping_edits_by_target = context.get('mapping_edits_by_target')
    mapping_items_by_target = context.get('mapping_items_by_target')
    mapping_tree = context.get('mapping_tree')
    mirror_duplicate_part_button = context.get('mirror_duplicate_part_button')
    part_add_target_button = context.get('part_add_target_button')
    part_controls = context.get('part_controls')
    part_copied_texture_status_label = context.get('part_copied_texture_status_label')
    part_enabled_checkbox = context.get('part_enabled_checkbox')
    part_inspector_loading = context.get('part_inspector_loading')
    part_name_label = context.get('part_name_label')
    part_nudge_step_spin = context.get('part_nudge_step_spin')
    part_nudge_x_minus_button = context.get('part_nudge_x_minus_button')
    part_nudge_x_plus_button = context.get('part_nudge_x_plus_button')
    part_nudge_y_minus_button = context.get('part_nudge_y_minus_button')
    part_nudge_y_plus_button = context.get('part_nudge_y_plus_button')
    part_nudge_z_minus_button = context.get('part_nudge_z_minus_button')
    part_nudge_z_plus_button = context.get('part_nudge_z_plus_button')
    part_remove_copied_texture_button = context.get('part_remove_copied_texture_button')
    part_remove_target_button = context.get('part_remove_target_button')
    part_replace_target_button = context.get('part_replace_target_button')
    part_role_combo = context.get('part_role_combo')
    part_source_combo = context.get('part_source_combo')
    part_target_combo = context.get('part_target_combo')
    part_target_label = context.get('part_target_label')
    part_use_copied_texture_button = context.get('part_use_copied_texture_button')
    part_use_route_texture_button = context.get('part_use_route_texture_button')
    preview_only_source_indices = context.get('preview_only_source_indices')
    remove_part_button = context.get('remove_part_button')
    replace = context.get('replace')
    replacement_mesh_for_mapping = context.get('replacement_mesh_for_mapping')
    reset_part_button = context.get('reset_part_button')
    selected_source_highlight_indices = context.get('selected_source_highlight_indices')
    selected_source_part = context.get('selected_source_part')
    source_items_by_index = context.get('source_items_by_index')
    source_part_adjustments = context.get('source_part_adjustments')
    source_part_inspector_control_text = context.get('source_part_inspector_control_text')
    source_role_overrides = context.get('source_role_overrides')
    source_tree = context.get('source_tree')
    source_tree_item_update_guard = context.get('source_tree_item_update_guard')
    texture_overrides_dirty = context.get('texture_overrides_dirty')

    def _refresh_selected_part_copied_texture_controls() -> None:
        source_index = int(selected_source_part.get("index", -1))
        rows = copied_original_texture_intents_by_source.get(source_index, []) if source_index >= 0 else []
        disabled = source_index in copied_original_texture_disabled_sources
        has_rows = bool(rows)
        controls_state = _source_part_copied_texture_controls_state_helper(
            has_rows=has_rows,
            disabled=disabled,
        )
        part_copied_texture_status_label.setVisible(controls_state.visible)
        part_use_copied_texture_button.setVisible(controls_state.visible)
        part_use_route_texture_button.setVisible(controls_state.visible)
        part_remove_copied_texture_button.setVisible(controls_state.visible)
        if not has_rows:
            part_copied_texture_status_label.setText(
                _source_part_copied_texture_status_text_helper(has_rows=False)
            )
            part_copied_texture_status_label.setToolTip("")
        else:
            part_copied_texture_status_label.setText(
                _source_part_copied_texture_status_text_helper(
                    has_rows=True,
                    disabled=disabled,
                    copied_badge=_copied_original_dds_badge(source_index),
                )
            )
            part_copied_texture_status_label.setToolTip(_copied_original_texture_tooltip(source_index))
        part_use_copied_texture_button.setEnabled(controls_state.use_copied_enabled)
        part_use_route_texture_button.setEnabled(controls_state.use_route_enabled)
        part_remove_copied_texture_button.setEnabled(controls_state.remove_enabled)

    def _use_copied_original_texture_for_selected_source() -> None:
        action_state = _source_part_copied_texture_action_state_helper(
            action="use_copied",
            source_index=selected_source_part.get("index", -1),
            copied_source_indices=copied_original_texture_intents_by_source.keys(),
        )
        if not action_state.available:
            return
        _push_geometry_undo_snapshot(action_state.undo_label)
        copied_original_texture_disabled_sources.discard(action_state.source_index)
        texture_overrides_dirty["dirty"] = action_state.mark_dirty
        _refresh_copied_original_texture_ui(action_state.source_index)
        _refresh_selected_part_copied_texture_controls()
        if action_state.queue_preview:
            _queue_texture_preview_refresh()

    def _use_route_texture_for_selected_copied_source() -> None:
        action_state = _source_part_copied_texture_action_state_helper(
            action="use_route",
            source_index=selected_source_part.get("index", -1),
            copied_source_indices=copied_original_texture_intents_by_source.keys(),
        )
        if not action_state.available:
            return
        _push_geometry_undo_snapshot(action_state.undo_label)
        if action_state.disable_copied_texture:
            copied_original_texture_disabled_sources.add(action_state.source_index)
        texture_overrides_dirty["dirty"] = action_state.mark_dirty
        _refresh_copied_original_texture_ui(action_state.source_index)
        _refresh_selected_part_copied_texture_controls()
        if action_state.queue_preview:
            _queue_texture_preview_refresh()

    def _remove_copied_texture_from_selected_source() -> None:
        action_state = _source_part_copied_texture_action_state_helper(
            action="remove",
            source_index=selected_source_part.get("index", -1),
            copied_source_indices=copied_original_texture_intents_by_source.keys(),
        )
        if not action_state.available:
            return
        _push_geometry_undo_snapshot(action_state.undo_label)
        if action_state.remove_intent:
            copied_original_texture_intents_by_source.pop(action_state.source_index, None)
        copied_original_texture_disabled_sources.discard(action_state.source_index)
        texture_overrides_dirty["dirty"] = action_state.mark_dirty
        _refresh_copied_original_texture_ui(action_state.source_index)
        _refresh_selected_part_copied_texture_controls()
        if action_state.queue_preview:
            _queue_texture_preview_refresh()

    def _load_selected_part_controls() -> None:
        source_index = int(selected_source_part.get("index", -1))
        part_inspector_loading["active"] = True
        try:
            has_replacement_sources = (
                replacement_mesh_for_mapping is not None
                and bool(getattr(replacement_mesh_for_mapping, "submeshes", ()) or ())
            )
            source_count = len(getattr(replacement_mesh_for_mapping, "submeshes", ()) or ())
            mapped_target_indices = _part_mapped_target_indices(source_index)
            selected_target_choice = _selected_target_index()
            source = (
                replacement_mesh_for_mapping.submeshes[source_index]
                if replacement_mesh_for_mapping is not None and 0 <= source_index < source_count
                else None
            )
            label = _source_part_display_label_helper(source_index, source, {}) if source is not None else ""
            adjustment = source_part_adjustments.get(source_index, StaticSourcePartAdjustment(source_index))
            selected_source_indices = _selected_source_indices_from_tree()
            load_state = _source_part_control_load_state_helper(
                source_index=source_index,
                source_count=source_count,
                has_replacement_sources=has_replacement_sources,
                current_target_choice=part_target_combo.currentData(),
                mapped_target_indices=mapped_target_indices,
                selected_target_index=selected_target_choice,
                name_placeholder=source_part_inspector_control_text["name_placeholder"],
                target_placeholder=source_part_inspector_control_text["target_placeholder"],
                source_label=label,
                target_summary=_source_target_summary(source_index) if source is not None else "",
                role_value=_source_role_override_value(source_index) if source is not None else "",
                multi_selected_count=len(selected_source_indices),
                adjustment=adjustment if source is not None else None,
            )
            control_state = load_state.control_state
            for spin in part_controls:
                spin.setEnabled(control_state.has_source)
            part_nudge_step_spin.setEnabled(control_state.has_source)
            for nudge_button in (
                part_nudge_x_minus_button,
                part_nudge_x_plus_button,
                part_nudge_y_minus_button,
                part_nudge_y_plus_button,
                part_nudge_z_minus_button,
                part_nudge_z_plus_button,
                center_part_button,
            ):
                nudge_button.setEnabled(control_state.has_source)
            part_source_combo.setEnabled(control_state.source_combo_enabled)
            part_enabled_checkbox.setEnabled(control_state.has_source)
            part_role_combo.setEnabled(control_state.has_source)
            part_target_combo.setEnabled(control_state.has_source)
            part_replace_target_button.setEnabled(control_state.target_choice_available)
            part_add_target_button.setEnabled(control_state.target_choice_available)
            part_remove_target_button.setEnabled(control_state.mapped_target_available)
            remove_part_button.setEnabled(control_state.has_source)
            reset_part_button.setEnabled(control_state.has_source)
            fit_part_button.setEnabled(control_state.fit_part_enabled)
            duplicate_part_button.setEnabled(control_state.has_source)
            mirror_duplicate_part_button.setEnabled(control_state.has_source)
            _refresh_selected_part_copied_texture_controls()
            if not load_state.has_source:
                part_name_label.setText(load_state.name_text)
                part_target_label.setText(load_state.target_text)
                part_source_combo.blockSignals(True)
                part_source_combo.setCurrentIndex(0)
                part_source_combo.blockSignals(False)
                part_enabled_checkbox.setChecked(True)
                part_role_combo.blockSignals(True)
                part_role_combo.setCurrentIndex(0)
                part_role_combo.blockSignals(False)
                _load_part_glow_color_controls(None)
                part_target_combo.blockSignals(True)
                part_target_combo.setCurrentIndex(0)
                part_target_combo.blockSignals(False)
                for spin, value in zip(part_controls, load_state.transform_values):
                    _set_double_spin_value_silently_helper(spin, value)
                    _sync_part_slider_from_spin(spin)
                _refresh_selected_part_copied_texture_controls()
                return
            part_name_label.setText(load_state.name_text)
            part_target_label.setText(load_state.target_text)
            part_source_combo.blockSignals(True)
            part_source_combo_index = part_source_combo.findData(load_state.source_combo_value)
            part_source_combo.setCurrentIndex(max(0, part_source_combo_index))
            part_source_combo.blockSignals(False)
            part_enabled_checkbox.blockSignals(True)
            part_enabled_checkbox.setChecked(load_state.enabled_checked)
            part_enabled_checkbox.blockSignals(False)
            part_role_combo.blockSignals(True)
            role_index = part_role_combo.findData(load_state.role_value)
            part_role_combo.setCurrentIndex(max(0, role_index))
            part_role_combo.blockSignals(False)
            _load_part_glow_color_controls(adjustment)
            part_target_combo.blockSignals(True)
            target_combo_index = part_target_combo.findData(load_state.target_choice)
            part_target_combo.setCurrentIndex(max(0, target_combo_index))
            part_target_combo.blockSignals(False)
            raw_target_choice = part_target_combo.currentData()
            loaded_control_state = _source_part_control_state_helper(
                source_index=source_index,
                has_replacement_sources=has_replacement_sources,
                target_choice=raw_target_choice,
                mapped_target_indices=mapped_target_indices,
                selected_target_index=selected_target_choice,
            )
            part_replace_target_button.setEnabled(loaded_control_state.target_choice_available)
            part_add_target_button.setEnabled(loaded_control_state.target_choice_available)
            part_remove_target_button.setEnabled(loaded_control_state.mapped_target_available)
            remove_part_button.setEnabled(loaded_control_state.has_source)
            for spin, value in zip(part_controls, load_state.transform_values):
                _set_double_spin_value_silently_helper(spin, value)
                _sync_part_slider_from_spin(spin)
            _refresh_selected_part_copied_texture_controls()
        finally:
            part_inspector_loading["active"] = False
            try:
                if callable(_refresh_mesh_edit_controls):
                    _refresh_mesh_edit_controls()
            except NameError:
                pass

    def _selected_part_source_changed(_index: int = -1) -> None:
        if part_inspector_loading["active"]:
            return
        selection_state = _source_part_source_combo_selection_state_helper(
            part_source_combo.currentData(),
            available_source_indices=source_items_by_index.keys(),
        )
        if selection_state.select_existing_source:
            source_item = source_items_by_index.get(selection_state.source_index)
            source_tree.clearSelection()
            source_item.setSelected(True)
            source_tree.setCurrentItem(source_item)
            return
        selected_source_part["index"] = -1
        selected_source_highlight_indices.clear()
        _clear_transform_source_indices()
        _sync_highlight_sets()
        _load_selected_part_controls()
        _update_mapping_status()
        _queue_selection_preview_refresh()

    def _set_selected_source_role() -> None:
        if part_inspector_loading["active"]:
            return
        action_state = _source_part_role_action_state_helper(
            source_index=selected_source_part.get("index", -1),
            role_value=part_role_combo.currentData(),
            undo_label=_source_part_edit_undo_label_helper("role"),
        )
        if not action_state.available:
            return
        _push_geometry_undo_snapshot(action_state.undo_label)
        _set_source_role_override_value(action_state.source_index, action_state.normalized_role)
        _load_part_glow_color_controls(source_part_adjustments.get(action_state.source_index))
        _refresh_source_assignment_columns(lightweight=True)
        try:
            _refresh_parts_outliner()
        except NameError:
            pass
        _queue_material_edit_refresh(
            refresh_plan=action_state.refresh_plan,
            force_plan=action_state.force_plan,
            refresh_preview=action_state.refresh_preview,
            reason=action_state.refresh_reason,
        )

    def _set_selected_source_glow_color() -> None:
        action_state = _source_part_glow_color_action_state_helper()
        _push_geometry_undo_snapshot(_source_part_edit_undo_label_helper(action_state.undo_action))
        _apply_current_glow_color_to_role_overrides()
        _refresh_ui_texture_sets_after_source_part_material_override()
        texture_overrides_dirty["dirty"] = True
        _refresh_part_glow_color_controls_enabled()
        _queue_material_edit_refresh(
            refresh_plan=action_state.refresh_plan,
            force_plan=action_state.force_plan,
            refresh_preview=action_state.refresh_preview,
            reason=action_state.refresh_reason,
        )

    def _selected_part_target_index() -> int:
        return _source_part_selected_target_index_helper(part_target_combo.currentData())

    def _select_part_target_row() -> None:
        if part_inspector_loading["active"]:
            return
        source_index = int(selected_source_part.get("index", -1))
        selection_state = _source_part_target_combo_selection_state_helper(
            part_target_combo.currentData(),
            source_index=source_index,
            mapped_target_indices=_part_mapped_target_indices(source_index),
        )
        target_item = mapping_items_by_target.get(selection_state.target_index)
        if target_item is not None:
            mapping_tree.setCurrentItem(target_item)
        button_state = selection_state.button_state
        part_replace_target_button.setEnabled(button_state.replace_enabled)
        part_add_target_button.setEnabled(button_state.add_enabled)
        part_remove_target_button.setEnabled(button_state.remove_enabled)
        _update_mapping_status()
        _update_selection_context()

    def _map_selected_part_to_combo_target(*, replace: bool) -> None:
        source_index = int(selected_source_part.get("index", -1))
        target_index = _selected_part_target_index()
        edit = mapping_edits_by_target.get(target_index)
        if edit is None:
            return
        map_state = _source_part_map_to_target_state_helper(
            source_index=source_index,
            target_index=target_index,
            current_indices=_parse_mapping_edit(edit),
            replace=replace,
        )
        if not map_state.available:
            return
        target_item = mapping_items_by_target.get(target_index)
        if target_item is not None:
            mapping_tree.setCurrentItem(target_item)
        _set_mapping_indices(map_state.target_index, list(map_state.source_indices))
        _load_selected_part_controls()

    def _remove_selected_part_from_combo_target() -> None:
        source_index = int(selected_source_part.get("index", -1))
        target_indices = _part_mapped_target_indices(source_index)
        if source_index < 0 or not target_indices:
            return
        target_source_indices = {
            int(target_index): tuple(_parse_mapping_edit(edit))
            for target_index in target_indices
            for edit in (mapping_edits_by_target.get(target_index),)
            if edit is not None
        }
        for unmap_state in _source_part_unmap_target_states_helper(
            source_index=source_index,
            target_indices=target_indices,
            target_source_indices=target_source_indices,
        ):
            _set_mapping_indices(
                unmap_state.target_index,
                list(unmap_state.remaining_source_indices),
                push_undo=unmap_state.push_undo,
                undo_label=_source_part_edit_undo_label_helper("unmap"),
                defer_preview=True,
            )
        if _source_part_should_be_preview_only_after_unmap_helper(
            source_index=source_index,
            appended_source_indices=appended_source_indices,
            mapped_source_indices=_mapped_source_indices(_current_dialog_mappings_for_preview()),
        ):
            independent_output_source_indices.discard(source_index)
            preview_only_source_indices.add(source_index)
        _load_selected_part_controls()

    def _reset_selected_part() -> None:
        source_index = int(selected_source_part.get("index", -1))
        action_state = _source_part_output_action_state_helper(
            action="reset",
            source_index=source_index,
            selected_source_indices=_selected_source_indices_from_tree(),
        )
        if not action_state.available:
            return
        _push_geometry_undo_snapshot(_source_part_edit_undo_label_helper(action_state.undo_action))
        for target_source_index in action_state.target_indices:
            source_part_adjustments.pop(target_source_index, None)
            source_role_overrides.pop(target_source_index, None)
            source_item = source_items_by_index.get(target_source_index)
            if source_item is not None:
                source_tree_item_update_guard["active"] = True
                try:
                    source_item.setCheckState(0, Qt.Checked if action_state.source_checked else Qt.Unchecked)
                finally:
                    source_tree_item_update_guard["active"] = False
        _load_selected_part_controls()
        _refresh_source_assignment_columns()
        _queue_static_preview_rebuild()

    def _remove_selected_part_from_output() -> None:
        source_index = int(selected_source_part.get("index", -1))
        action_state = _source_part_output_action_state_helper(
            action="remove",
            source_index=source_index,
            selected_source_indices=_selected_source_indices_from_tree(),
        )
        if not action_state.available:
            return
        _push_geometry_undo_snapshot(_source_part_edit_undo_label_helper(action_state.undo_action))
        for target_source_index in action_state.target_indices:
            adjustment = _ensure_source_part_adjustment(target_source_index)
            adjustment.enabled = False
            source_item = source_items_by_index.get(target_source_index)
            if source_item is not None:
                source_tree_item_update_guard["active"] = True
                try:
                    source_item.setCheckState(0, Qt.Checked if action_state.source_checked else Qt.Unchecked)
                finally:
                    source_tree_item_update_guard["active"] = False
        part_enabled_checkbox.blockSignals(True)
        part_enabled_checkbox.setChecked(action_state.part_enabled_checked)
        part_enabled_checkbox.blockSignals(False)
        _refresh_source_assignment_columns()
        if callable(_sync_highlight_sets):
            _sync_highlight_sets()
        if action_state.apply_pending:
            _set_source_parts_apply_pending(_source_part_include_exclude_pending_reason_helper())
        else:
            if callable(_set_source_parts_preview_rebuild_pending):
                _set_source_parts_preview_rebuild_pending(_source_part_include_exclude_pending_reason_helper())
            _queue_static_preview_rebuild()

    return SimpleNamespace(
        _refresh_selected_part_copied_texture_controls=_refresh_selected_part_copied_texture_controls,
        _use_copied_original_texture_for_selected_source=_use_copied_original_texture_for_selected_source,
        _use_route_texture_for_selected_copied_source=_use_route_texture_for_selected_copied_source,
        _remove_copied_texture_from_selected_source=_remove_copied_texture_from_selected_source,
        _load_selected_part_controls=_load_selected_part_controls,
        _selected_part_source_changed=_selected_part_source_changed,
        _set_selected_source_role=_set_selected_source_role,
        _set_selected_source_glow_color=_set_selected_source_glow_color,
        _selected_part_target_index=_selected_part_target_index,
        _select_part_target_row=_select_part_target_row,
        _map_selected_part_to_combo_target=_map_selected_part_to_combo_target,
        _remove_selected_part_from_combo_target=_remove_selected_part_from_combo_target,
        _reset_selected_part=_reset_selected_part,
        _remove_selected_part_from_output=_remove_selected_part_from_output,
    )

def create_alignment_source_part_assignment_callbacks(context: dict[str, object]) -> SimpleNamespace:
    Optional = context.get('Optional')
    QAbstractItemView = context.get('QAbstractItemView')
    QComboBox = context.get('QComboBox')
    QDialog = context.get('QDialog')
    QEvent = context.get('QEvent')
    QFrame = context.get('QFrame')
    QHBoxLayout = context.get('QHBoxLayout')
    QLabel = context.get('QLabel')
    QMessageBox = context.get('QMessageBox')
    QObject = context.get('QObject')
    QPushButton = context.get('QPushButton')
    QTreeWidget = context.get('QTreeWidget')
    QTreeWidgetItem = context.get('QTreeWidgetItem')
    QVBoxLayout = context.get('QVBoxLayout')
    Qt = context.get('Qt')
    Sequence = context.get('Sequence')
    _add_source_tree_item = context.get('_add_source_tree_item')
    _assignment_source_item_helper = context.get('_assignment_source_item_helper')
    _auto_fit_alignment_tree_columns = context.get('_auto_fit_alignment_tree_columns')
    _fit_alignment_tree_height_to_rows = context.get('_fit_alignment_tree_height_to_rows')
    _is_marker_source = context.get('_is_marker_source')
    _parse_mapping_edit = context.get('_parse_mapping_edit')
    _queue_selection_preview_refresh = context.get('_queue_selection_preview_refresh')
    _refresh_original_reference_preview = context.get('_refresh_original_reference_preview')
    _selected_target_index = context.get('_selected_target_index')
    _set_mapping_indices = context.get('_set_mapping_indices')
    _set_transform_source_indices = context.get('_set_transform_source_indices')
    _source_assigned_target_indices_helper = context.get('_source_assigned_target_indices_helper')
    _source_display_name = context.get('_source_display_name')
    _source_part_assignment_button_state_helper = context.get('_source_part_assignment_button_state_helper')
    _source_part_assignment_dialog_text_helper = context.get('_source_part_assignment_dialog_text_helper')
    _source_part_assignment_highlight_state_helper = context.get('_source_part_assignment_highlight_state_helper')
    _source_part_assignment_import_state_helper = context.get('_source_part_assignment_import_state_helper')
    _source_part_assignment_primary_target_helper = context.get('_source_part_assignment_primary_target_helper')
    _source_part_assignment_route_state_helper = context.get('_source_part_assignment_route_state_helper')
    _source_part_assignment_row_specs_helper = context.get('_source_part_assignment_row_specs_helper')
    _source_part_assignment_summary_state_helper = context.get('_source_part_assignment_summary_state_helper')
    _source_part_assignment_target_for_source_helper = context.get('_source_part_assignment_target_for_source_helper')
    _source_part_assignment_target_index_helper = context.get('_source_part_assignment_target_index_helper')
    _source_part_assignment_tree_headers_helper = context.get('_source_part_assignment_tree_headers_helper')
    _source_part_high_density_import_action_helper = context.get('_source_part_high_density_import_action_helper')
    _source_part_high_density_prompt_state_helper = context.get('_source_part_high_density_prompt_state_helper')
    _source_part_high_density_reduction_limits_helper = context.get('_source_part_high_density_reduction_limits_helper')
    _source_part_multipart_import_action_helper = context.get('_source_part_multipart_import_action_helper')
    _source_part_multipart_prompt_state_helper = context.get('_source_part_multipart_prompt_state_helper')
    _source_part_reduction_result_message_helper = context.get('_source_part_reduction_result_message_helper')
    _source_part_valid_indices_helper = context.get('_source_part_valid_indices_helper')
    _source_tree_population_mark_complete_helper = context.get('_source_tree_population_mark_complete_helper')
    _source_tree_population_ready_text_helper = context.get('_source_tree_population_ready_text_helper')
    _source_tree_population_set_next_index_helper = context.get('_source_tree_population_set_next_index_helper')
    _sync_highlight_sets = context.get('_sync_highlight_sets')
    _target_display_name = context.get('_target_display_name')
    _texture_assignment_action_initial_state_helper = context.get('_texture_assignment_action_initial_state_helper')
    _texture_set_for_source_index = context.get('_texture_set_for_source_index')
    control_tabs = context.get('control_tabs')
    dialog = context.get('dialog')
    discovered_texture_files = context.get('discovered_texture_files')
    event = context.get('event')
    flatten_scene_import_result_parts = context.get('flatten_scene_import_result_parts')
    format_scene_import_file_size_summary = context.get('format_scene_import_file_size_summary')
    group_scene_import_result_parts_by_material = context.get('group_scene_import_result_parts_by_material')
    independent_output_source_indices = context.get('independent_output_source_indices')
    mapping_edits = context.get('mapping_edits')
    mapping_edits_by_target = context.get('mapping_edits_by_target')
    original_mesh_for_mapping = context.get('original_mesh_for_mapping')
    part_source_combo = context.get('part_source_combo')
    placement_note = context.get('placement_note')
    preview_only_source_indices = context.get('preview_only_source_indices')
    reduce_scene_import_result_quality = context.get('reduce_scene_import_result_quality')
    replacement_mesh_for_mapping = context.get('replacement_mesh_for_mapping')
    scene_result = context.get('scene_result')
    selected_indices = context.get('selected_indices')
    selected_original_part = context.get('selected_original_part')
    selected_source_highlight_indices = context.get('selected_source_highlight_indices')
    selected_source_part = context.get('selected_source_part')
    selected_target_original_highlight_indices = context.get('selected_target_original_highlight_indices')
    selected_target_slot = context.get('selected_target_slot')
    selected_target_source_highlight_indices = context.get('selected_target_source_highlight_indices')
    self = context.get('self')
    source_indices = context.get('source_indices')
    source_items_by_index = context.get('source_items_by_index')
    source_part_inspector_control_text = context.get('source_part_inspector_control_text')
    source_path = context.get('source_path')
    source_tree = context.get('source_tree')
    source_tree_layout_state = context.get('source_tree_layout_state')
    source_tree_population_state = context.get('source_tree_population_state')
    source_tree_population_timer = context.get('source_tree_population_timer')
    source_tree_progress_label = context.get('source_tree_progress_label')
    static_replacement_vertex_limit = context.get('static_replacement_vertex_limit')
    texture_sets = context.get('texture_sets')
    textures_tab = context.get('textures_tab')

    def _prompt_assign_appended_mesh_parts(
        source_path: Path,
        source_indices: Sequence[int],
        *,
        placement_note: str = "",
        discovered_texture_files: Sequence[Path] = (),
    ) -> str:
        if original_mesh_for_mapping is None or replacement_mesh_for_mapping is None:
            return "keep"
        matched_texture_indices = tuple(
            int(index)
            for index in source_indices
            if _texture_set_for_source_index(int(index), texture_sets) is not None
        )
        import_state = _source_part_assignment_import_state_helper(
            source_indices=source_indices,
            replacement_sources=tuple(replacement_mesh_for_mapping.submeshes),
            source_name=source_path.name,
            placement_note=placement_note,
            discovered_texture_count=len(tuple(discovered_texture_files or ())),
            matched_texture_indices=matched_texture_indices,
            vertex_limit=static_replacement_vertex_limit,
        )
        appended_indices = import_state.appended_indices
        if not appended_indices:
            return "keep"
        target_count = len(original_mesh_for_mapping.submeshes)
        primary_target = _source_part_assignment_primary_target_helper(
            selected_target_index=_selected_target_index(),
            selected_original_index=selected_original_part.get("index", -1),
            target_count=target_count,
        )
        discovered_texture_count = len(tuple(discovered_texture_files or ()))

        def merge_sources_into_target(target_index: int, indices: Sequence[int]) -> None:
            edit = mapping_edits_by_target.get(target_index)
            if edit is None:
                return
            merged = _parse_mapping_edit(edit)
            for index in indices:
                if int(index) not in merged:
                    merged.append(int(index))
            _set_mapping_indices(target_index, merged, push_undo=False)

        source_part_assignment_dialog_text = _source_part_assignment_dialog_text_helper()
        summary_state = _source_part_assignment_summary_state_helper(
            import_state=import_state,
            source_name=source_path.name,
            placement_note=placement_note,
            discovered_texture_count=discovered_texture_count,
            text=source_part_assignment_dialog_text,
        )
        assignment_dialog = QDialog(dialog)
        assignment_dialog.setWindowTitle(source_part_assignment_dialog_text["window_title"])
        assignment_dialog.setMinimumWidth(820)
        assignment_dialog.setStyleSheet(
            assignment_dialog.styleSheet()
            + """
            QFrame#AssignmentSummary {
                background: #151b22;
                border: 1px solid #30363d;
                border-radius: 6px;
            }
            QLabel#AssignmentTitle {
                color: #79c0ff;
                font-weight: 600;
            }
            QLabel#AssignmentWarning {
                color: #f2cc60;
                font-weight: 500;
            }
            QTreeWidget#AssignmentTree {
                background: #0d1117;
                border: 1px solid #30363d;
                border-radius: 4px;
                alternate-background-color: #12181f;
            }
            """
        )
        assignment_layout = QVBoxLayout(assignment_dialog)
        assignment_layout.setContentsMargins(14, 12, 14, 12)
        assignment_layout.setSpacing(10)

        summary_frame = QFrame()
        summary_frame.setObjectName("AssignmentSummary")
        summary_layout = QVBoxLayout(summary_frame)
        summary_layout.setContentsMargins(12, 10, 12, 10)
        summary_layout.setSpacing(6)
        icon_label = QLabel(summary_state.title)
        icon_label.setObjectName("AssignmentTitle")
        summary_layout.addWidget(icon_label)
        intro_label = QLabel("\n".join(summary_state.summary_lines))
        intro_label.setWordWrap(True)
        summary_layout.addWidget(intro_label)
        if summary_state.show_texture_warning:
            texture_warning_label = QLabel(
                source_part_assignment_dialog_text["texture_warning"]
            )
            texture_warning_label.setObjectName("AssignmentWarning")
            texture_warning_label.setWordWrap(True)
            summary_layout.addWidget(texture_warning_label)
        if summary_state.show_dense_warning:
            dense_warning_label = QLabel(
                source_part_assignment_dialog_text["dense_warning"]
            )
            dense_warning_label.setObjectName("AssignmentWarning")
            dense_warning_label.setWordWrap(True)
            summary_layout.addWidget(dense_warning_label)
        assignment_layout.addWidget(summary_frame)

        assignment_tree = QTreeWidget()
        assignment_tree.setObjectName("AssignmentTree")
        assignment_tree.setColumnCount(3)
        assignment_tree.setHeaderLabels(list(_source_part_assignment_tree_headers_helper()))
        assignment_tree.setRootIsDecorated(False)
        assignment_tree.setAlternatingRowColors(True)
        assignment_tree.setUniformRowHeights(True)
        assignment_tree.setSelectionMode(QAbstractItemView.SingleSelection)
        assignment_tree.setMinimumHeight(130)
        assignment_tree.setMaximumHeight(320)
        assignment_tree.header().setStretchLastSection(True)
        assignment_tree.header().resizeSection(0, 310)
        assignment_tree.header().resizeSection(1, 170)
        row_target_combos: list[tuple[int, QComboBox]] = []
        assignment_focus_filters: list[QObject] = []

        def _assignment_combo_target_index(combo: QComboBox) -> int:
            return _source_part_assignment_target_index_helper(combo.currentData())

        def _assignment_row_targets() -> tuple[tuple[int, int], ...]:
            return tuple(
                (int(row_source_index), _assignment_combo_target_index(row_target_combo))
                for row_source_index, row_target_combo in tuple(row_target_combos)
            )

        def _assignment_target_for_source(source_index: int) -> int:
            return _source_part_assignment_target_for_source_helper(
                _assignment_row_targets(),
                source_index,
            )

        def _highlight_assignment_source(source_index: int, target_index: Optional[int] = None) -> None:
            mapped_source_indices: Sequence[int] = ()
            normalized_target = (
                _source_part_assignment_target_index_helper(target_index)
                if target_index is not None
                else -1
            )
            if normalized_target >= 0:
                edit = mapping_edits_by_target.get(normalized_target)
                if edit is not None:
                    mapped_source_indices = tuple(_parse_mapping_edit(edit))
            highlight_state = _source_part_assignment_highlight_state_helper(
                source_index=source_index,
                target_index=target_index,
                mapped_source_indices=mapped_source_indices,
            )
            selected_source_part["index"] = highlight_state.source_index
            selected_source_highlight_indices.clear()
            if highlight_state.source_index >= 0:
                selected_source_highlight_indices.add(highlight_state.source_index)
            _set_transform_source_indices(
                (highlight_state.source_index,) if highlight_state.source_index >= 0 else ()
            )
            if target_index is not None:
                selected_target_slot["index"] = highlight_state.target_index
                selected_target_original_highlight_indices.clear()
                selected_target_original_highlight_indices.update(
                    highlight_state.target_original_indices
                )
                selected_target_source_highlight_indices.clear()
                selected_target_source_highlight_indices.update(
                    highlight_state.target_source_indices
                )
            _sync_highlight_sets()
            _refresh_original_reference_preview()
            _queue_selection_preview_refresh()

        class _AssignmentSourceFocusFilter(QObject):
            def __init__(self, source_index: int, target_combo: QComboBox) -> None:
                super().__init__(assignment_dialog)
                self.source_index = int(source_index)
                self.target_combo = target_combo

            def eventFilter(self, watched: QObject, event: QEvent) -> bool:  # type: ignore[override]
                if event.type() in {
                    QEvent.Type.FocusIn,
                    QEvent.Type.MouseButtonPress,
                }:
                    _highlight_assignment_source(
                        self.source_index,
                        _assignment_combo_target_index(self.target_combo),
                    )
                return False

        row_specs = _source_part_assignment_row_specs_helper(
            appended_indices=appended_indices,
            replacement_sources=tuple(replacement_mesh_for_mapping.submeshes),
            source_display_names=tuple(
                _source_display_name(source_index)
                for source_index in range(len(replacement_mesh_for_mapping.submeshes))
            ),
            target_display_names=tuple(
                _target_display_name(target_index)
                for target_index in range(target_count)
            ),
            primary_target=primary_target,
            text=source_part_assignment_dialog_text,
        )
        for row_spec in row_specs:
            source_item = _assignment_source_item_helper(
                assignment_tree,
                source_index=row_spec.source_index,
                display_name=_source_display_name(row_spec.source_index),
                geometry_text=row_spec.geometry_text,
                tooltip=row_spec.tooltip,
            )
            target_combo = QComboBox()
            for option in row_spec.target_options:
                target_combo.addItem(option.label, option.target_index)
            target_combo.setCurrentIndex(max(0, target_combo.findData(row_spec.default_target)))
            focus_filter = _AssignmentSourceFocusFilter(row_spec.source_index, target_combo)
            target_combo.installEventFilter(focus_filter)
            assignment_focus_filters.append(focus_filter)
            target_combo.currentIndexChanged.connect(
                lambda _row=0, index=int(row_spec.source_index), combo=target_combo: _highlight_assignment_source(
                    index,
                    _assignment_combo_target_index(combo),
                )
            )
            assignment_tree.setItemWidget(source_item, 2, target_combo)
            row_target_combos.append((int(row_spec.source_index), target_combo))
        if assignment_tree.topLevelItemCount() > 0:
            first_item = assignment_tree.topLevelItem(0)
            assignment_tree.setCurrentItem(first_item)
            raw_first_index = first_item.data(0, Qt.UserRole)
            try:
                first_source_index = int(raw_first_index)
                _highlight_assignment_source(
                    first_source_index,
                    _assignment_target_for_source(first_source_index),
                )
            except (TypeError, ValueError):
                pass

        def _assignment_tree_selection_changed() -> None:
            item = assignment_tree.currentItem()
            if item is None:
                return
            try:
                source_index = int(item.data(0, Qt.UserRole))
            except (TypeError, ValueError):
                return
            _highlight_assignment_source(source_index, _assignment_target_for_source(source_index))

        assignment_tree.itemSelectionChanged.connect(_assignment_tree_selection_changed)
        assignment_layout.addWidget(assignment_tree)

        button_state = _source_part_assignment_button_state_helper(
            primary_target=primary_target,
            target_count=target_count,
            texture_warning=import_state.texture_warning,
            current_target_name=(
                _target_display_name(primary_target)
                if 0 <= primary_target < target_count
                else ""
            ),
            text=source_part_assignment_dialog_text,
        )
        button_row = QHBoxLayout()
        button_row.setSpacing(8)
        apply_button = QPushButton(source_part_assignment_dialog_text["apply_button"])
        apply_button.setMinimumWidth(0)
        apply_button.setDefault(True)
        add_all_button = QPushButton(button_state.add_all_text)
        if button_state.add_all_tooltip:
            add_all_button.setToolTip(button_state.add_all_tooltip)
        add_all_button.setMinimumWidth(0)
        add_all_button.setEnabled(button_state.add_all_enabled)
        assign_order_button = QPushButton(source_part_assignment_dialog_text["assign_by_order"])
        assign_order_button.setMinimumWidth(0)
        assign_order_button.setEnabled(button_state.assign_order_enabled)
        textures_button = QPushButton(source_part_assignment_dialog_text["open_textures"])
        textures_button.setMinimumWidth(0)
        textures_button.setVisible(button_state.textures_visible)
        keep_unassigned_button = QPushButton(source_part_assignment_dialog_text["preview_only_button"])
        keep_unassigned_button.setMinimumWidth(0)
        cancel_import_button = QPushButton(source_part_assignment_dialog_text["cancel_import"])
        cancel_import_button.setMinimumWidth(0)
        cancel_import_button.setToolTip(source_part_assignment_dialog_text["cancel_import_tooltip"])
        button_row.addStretch(1)
        for button in (
            apply_button,
            add_all_button,
            assign_order_button,
            textures_button,
            keep_unassigned_button,
            cancel_import_button,
        ):
            button_row.addWidget(button)
        assignment_layout.addLayout(button_row)

        assignment_action = _texture_assignment_action_initial_state_helper()

        def finish_assignment(action: str) -> None:
            assignment_action["value"] = action
            assignment_dialog.accept()

        apply_button.clicked.connect(lambda: finish_assignment("apply"))
        add_all_button.clicked.connect(lambda: finish_assignment("add_all"))
        assign_order_button.clicked.connect(lambda: finish_assignment("by_order"))
        textures_button.clicked.connect(lambda: finish_assignment("textures"))
        keep_unassigned_button.clicked.connect(lambda: finish_assignment("preview"))
        cancel_import_button.clicked.connect(lambda: finish_assignment("cancel"))
        if assignment_dialog.exec() != QDialog.Accepted:
            assignment_action["value"] = "cancel"
        action = str(assignment_action.get("value", "") or "cancel")
        route_state = _source_part_assignment_route_state_helper(
            action=action,
            appended_indices=appended_indices,
            primary_target=primary_target,
            target_count=target_count,
            row_targets=_assignment_row_targets(),
        )

        if route_state.open_textures:
            independent_output_source_indices.difference_update(route_state.preview_indices)
            preview_only_source_indices.update(route_state.preview_indices)
            control_tabs.setCurrentWidget(textures_tab)
            return route_state.route
        if route_state.cancel_import:
            return "cancel"
        for target_index, indices in route_state.assignments_by_target.items():
            merge_sources_into_target(target_index, indices)
        independent_output_source_indices.difference_update(route_state.attached_indices)
        independent_output_source_indices.difference_update(route_state.preview_indices)
        preview_only_source_indices.update(route_state.preview_indices)
        preview_only_source_indices.difference_update(route_state.attached_indices)
        return route_state.route

    def _maybe_flatten_scene_import_parts(
        source_path: Path,
        scene_result: SceneImportResult,
    ) -> Optional[SceneImportResult]:
        prompt_state = _source_part_multipart_prompt_state_helper(
            source_name=source_path.name,
            mesh=scene_result.mesh,
        )
        if not prompt_state.should_prompt:
            return scene_result
        message_box = QMessageBox(dialog)
        message_box.setIcon(QMessageBox.Question)
        message_box.setWindowTitle(prompt_state.title)
        message_box.setText(prompt_state.message)
        keep_button = message_box.addButton(
            prompt_state.keep_separate_parts,
            QMessageBox.AcceptRole,
        )
        group_button = message_box.addButton(
            prompt_state.group_by_material,
            QMessageBox.ActionRole,
        )
        flatten_button = message_box.addButton(
            prompt_state.flatten_to_one_part,
            QMessageBox.ActionRole,
        )
        cancel_button = message_box.addButton(
            prompt_state.cancel_import,
            QMessageBox.RejectRole,
        )
        message_box.setDefaultButton(group_button)
        message_box.exec()
        clicked = message_box.clickedButton()
        import_action = _source_part_multipart_import_action_helper(
            clicked,
            cancel_button=cancel_button,
            group_button=group_button,
            flatten_button=flatten_button,
        )
        if import_action == "cancel":
            return None
        if import_action == "group":
            return group_scene_import_result_parts_by_material(
                scene_result,
                part_name=source_path.stem,
            )
        if import_action != "flatten":
            return scene_result
        flattened_result = flatten_scene_import_result_parts(
            scene_result,
            part_name=source_path.stem,
        )
        return flattened_result

    def _maybe_reduce_high_density_scene_import(
        source_path: Path,
        scene_result: SceneImportResult,
    ) -> Optional[SceneImportResult]:
        size_text = format_scene_import_file_size_summary(source_path, scene_result)
        prompt_state = _source_part_high_density_prompt_state_helper(
            mesh=scene_result.mesh,
            size_text=size_text,
        )
        if not prompt_state.should_prompt:
            return scene_result
        message_box = QMessageBox(dialog)
        message_box.setIcon(QMessageBox.Warning)
        message_box.setWindowTitle(prompt_state.title)
        message_box.setText(prompt_state.message)
        keep_button = message_box.addButton(
            prompt_state.keep_full_quality,
            QMessageBox.AcceptRole,
        )
        reduce_button = message_box.addButton(
            prompt_state.reduce_quality,
            QMessageBox.ActionRole,
        )
        cancel_button = message_box.addButton(
            prompt_state.cancel_import,
            QMessageBox.RejectRole,
        )
        message_box.setDefaultButton(keep_button)
        message_box.exec()
        clicked = message_box.clickedButton()
        import_action = _source_part_high_density_import_action_helper(
            clicked,
            cancel_button=cancel_button,
            reduce_button=reduce_button,
        )
        if import_action == "cancel":
            return None
        if import_action != "reduce":
            return scene_result
        reduction_limits = _source_part_high_density_reduction_limits_helper()
        reduced_result, reduction_report = reduce_scene_import_result_quality(
            scene_result,
            max_faces_per_submesh=reduction_limits.max_faces_per_submesh,
            max_vertices_per_submesh=reduction_limits.max_vertices_per_submesh,
        )
        QMessageBox.information(
            dialog,
            prompt_state.reduction_title,
            _source_part_reduction_result_message_helper(
                original_vertices=reduction_report.original_vertices,
                original_faces=reduction_report.original_faces,
                reduced_vertices=reduction_report.reduced_vertices,
                reduced_faces=reduction_report.reduced_faces,
            ),
        )
        return reduced_result

    def _rebuild_source_part_widgets(
        selected_indices: Sequence[int] = (),
        *,
        current_index: int = -1,
    ) -> None:
        if replacement_mesh_for_mapping is None:
            return
        source_count = len(replacement_mesh_for_mapping.submeshes)
        selected_set = set(_source_part_valid_indices_helper(selected_indices, source_count=source_count))
        try:
            current_index = int(current_index)
        except (TypeError, ValueError):
            current_index = -1
        source_blocked = source_tree.blockSignals(True)
        combo_blocked = part_source_combo.blockSignals(True)
        try:
            source_tree_population_timer.stop()
            source_tree.clear()
            source_items_by_index.clear()
            part_source_combo.clear()
            part_source_combo.addItem(source_part_inspector_control_text["source_select_label"], -1)
            for source_index, source in enumerate(replacement_mesh_for_mapping.submeshes):
                if _is_marker_source(source):
                    continue
                _add_source_tree_item(source_index, source)
                part_source_combo.addItem(_source_display_name(source_index), source_index)
            source_tree.clearSelection()
            current_item: Optional[QTreeWidgetItem] = None
            for source_index in sorted(selected_set):
                item = source_items_by_index.get(source_index)
                if item is None:
                    continue
                item.setSelected(True)
                if current_item is None:
                    current_item = item
            if current_index >= 0 and current_index in source_items_by_index:
                current_item = source_items_by_index[current_index]
                current_item.setSelected(True)
            if current_item is not None:
                source_tree.setCurrentItem(current_item)
            combo_index = part_source_combo.findData(current_index)
            part_source_combo.setCurrentIndex(combo_index if combo_index >= 0 else 0)
            _source_tree_population_set_next_index_helper(
                source_tree_population_state,
                source_count,
            )
            _source_tree_population_mark_complete_helper(source_tree_population_state)
            source_tree_progress_label.setText(
                _source_tree_population_ready_text_helper(source_tree.topLevelItemCount())
            )
        finally:
            part_source_combo.blockSignals(combo_blocked)
            source_tree.blockSignals(source_blocked)
        selected_source_part["index"] = current_index if current_index in source_items_by_index else -1
        _fit_alignment_tree_height_to_rows(source_tree, **source_tree_layout_state.height_fit_kwargs)
        _auto_fit_alignment_tree_columns(
            source_tree,
            source_tree_layout_state.autofit_min_widths,
            source_tree_layout_state.autofit_max_widths,
            expand_columns=source_tree_layout_state.expand_columns,
        )

    def _source_mapping_target_indices(source_index: int) -> List[int]:
        return list(
            _source_assigned_target_indices_helper(
                int(source_index),
                mapping_edits,
                parse_mapping_edit=_parse_mapping_edit,
            )
        )

    return SimpleNamespace(
        _prompt_assign_appended_mesh_parts=_prompt_assign_appended_mesh_parts,
        _maybe_flatten_scene_import_parts=_maybe_flatten_scene_import_parts,
        _maybe_reduce_high_density_scene_import=_maybe_reduce_high_density_scene_import,
        _rebuild_source_part_widgets=_rebuild_source_part_widgets,
        _source_mapping_target_indices=_source_mapping_target_indices,
    )

def create_alignment_source_tree_selection_callbacks(context: dict[str, object]) -> SimpleNamespace:
    Qt = context.get('Qt')
    _add_source_tree_item = context.get('_add_source_tree_item')
    _alignment_d3d11_preview_active = context.get('_alignment_d3d11_preview_active')
    _alignment_d3d11_source_indices_for_editor_id = context.get('_alignment_d3d11_source_indices_for_editor_id')
    _alignment_geometry_tab_active = context.get('_alignment_geometry_tab_active')
    _clear_transform_source_indices = context.get('_clear_transform_source_indices')
    _clear_tree_current_item = context.get('_clear_tree_current_item')
    _d3d11_source_part_selection_route_helper = context.get('_d3d11_source_part_selection_route_helper')
    _fit_alignment_tree_height_to_rows = context.get('_fit_alignment_tree_height_to_rows')
    _is_marker_source = context.get('_is_marker_source')
    _load_selected_part_controls = context.get('_load_selected_part_controls')
    _original_selection_route_state_helper = context.get('_original_selection_route_state_helper')
    _parse_mapping_edit = context.get('_parse_mapping_edit')
    _part_selection_clear_state_helper = context.get('_part_selection_clear_state_helper')
    _part_selection_state_active_helper = context.get('_part_selection_state_active_helper')
    _parts_outliner_selection_row_state_helper = context.get('_parts_outliner_selection_row_state_helper')
    _parts_outliner_set_source_selection = context.get('_parts_outliner_set_source_selection')
    _parts_outliner_target_selection_state_helper = context.get('_parts_outliner_target_selection_state_helper')
    _queue_selection_preview_refresh = context.get('_queue_selection_preview_refresh')
    _refresh_original_reference_preview = context.get('_refresh_original_reference_preview')
    _selected_source_indices_from_tree = context.get('_selected_source_indices_from_tree')
    _selection_filter_refresh_needed_helper = context.get('_selection_filter_refresh_needed_helper')
    _selection_view_update_kwargs_helper = context.get('_selection_view_update_kwargs_helper')
    _set_mesh_replacement_selection_view = context.get('_set_mesh_replacement_selection_view')
    _set_transform_source_indices = context.get('_set_transform_source_indices')
    _source_assigned_target_indices_helper = context.get('_source_assigned_target_indices_helper')
    _source_index_from_tree_item = context.get('_source_index_from_tree_item')
    _source_selection_route_state_helper = context.get('_source_selection_route_state_helper')
    _source_tree_context_selection_action_helper = context.get('_source_tree_context_selection_action_helper')
    _source_tree_context_selection_clear_multi_indices_helper = context.get('_source_tree_context_selection_clear_multi_indices_helper')
    _source_tree_context_selection_record_multi_indices_helper = context.get('_source_tree_context_selection_record_multi_indices_helper')
    _source_tree_context_selection_right_press_helper = context.get('_source_tree_context_selection_right_press_helper')
    _source_tree_current_selection_index_helper = context.get('_source_tree_current_selection_index_helper')
    _sync_highlight_sets = context.get('_sync_highlight_sets')
    _target_selection_index_helper = context.get('_target_selection_index_helper')
    _target_selection_route_state_helper = context.get('_target_selection_route_state_helper')
    _target_source_indices_helper = context.get('_target_source_indices_helper')
    _update_mapping_status = context.get('_update_mapping_status')
    _update_selection_context = context.get('_update_selection_context')
    control_tabs = context.get('control_tabs')
    index = context.get('index')
    mapping_edits = context.get('mapping_edits')
    mapping_edits_by_target = context.get('mapping_edits_by_target')
    mapping_items_by_target = context.get('mapping_items_by_target')
    mapping_tree = context.get('mapping_tree')
    original_tree = context.get('original_tree')
    parts_outliner_tree = context.get('parts_outliner_tree')
    parts_tab = context.get('parts_tab')
    replacement_mesh_for_mapping = context.get('replacement_mesh_for_mapping')
    selected_original_highlight_indices = context.get('selected_original_highlight_indices')
    selected_original_part = context.get('selected_original_part')
    selected_source_highlight_indices = context.get('selected_source_highlight_indices')
    selected_source_part = context.get('selected_source_part')
    selected_target_original_highlight_indices = context.get('selected_target_original_highlight_indices')
    selected_target_slot = context.get('selected_target_slot')
    selected_target_source_highlight_indices = context.get('selected_target_source_highlight_indices')
    source_items_by_index = context.get('source_items_by_index')
    source_parts_group = context.get('source_parts_group')
    source_tree = context.get('source_tree')
    source_tree_context_selection_state = context.get('source_tree_context_selection_state')
    source_tree_layout_state = context.get('source_tree_layout_state')
    texture_filter_refresh = context.get('texture_filter_refresh')
    texture_filter_selected_checkbox = context.get('texture_filter_selected_checkbox')

    def _refresh_source_tree_selection_state() -> None:
        selected_source_indices = _selected_source_indices_from_tree(include_fallback=False)
        context_action = _source_tree_context_selection_action_helper(
            selected_source_indices,
            right_press_active=_source_tree_context_selection_right_press_helper(
                source_tree_context_selection_state
            ),
        )
        if context_action == "record_multi":
            _source_tree_context_selection_record_multi_indices_helper(
                source_tree_context_selection_state,
                selected_source_indices,
            )
        elif context_action == "clear_multi":
            _source_tree_context_selection_clear_multi_indices_helper(source_tree_context_selection_state)
        current = source_tree.currentItem()
        current_index = _source_index_from_tree_item(current)
        selected_item_indices = tuple(
            _source_index_from_tree_item(item) for item in tuple(source_tree.selectedItems() or ())
        )
        current_index = _source_tree_current_selection_index_helper(current_index, selected_item_indices)
        mapped_targets = _source_assigned_target_indices_helper(
            current_index,
            mapping_edits,
            parse_mapping_edit=_parse_mapping_edit,
        ) if current_index >= 0 else ()
        filter_refresh = texture_filter_refresh.get("func")
        selection_state = _source_selection_route_state_helper(
            current_index,
            mapped_targets,
            has_filter_refresh=filter_refresh is not None,
            selected_filter_enabled=(
                texture_filter_selected_checkbox is not None
                and texture_filter_selected_checkbox.isChecked()
            ),
        )
        selected_source_part["index"] = int(selection_state["source_index"])
        source_highlight_indices = tuple(selection_state["source_highlight_indices"])
        transform_source_indices = tuple(selection_state["transform_source_indices"])
        selected_source_highlight_indices.clear()
        selected_source_highlight_indices.update(source_highlight_indices)
        if not bool(selection_state["clear_transform_source_indices"]):
            _set_transform_source_indices(transform_source_indices)
        else:
            _clear_transform_source_indices()
        selected_target_original_highlight_indices.clear()
        selected_target_source_highlight_indices.clear()
        _sync_highlight_sets()
        _load_selected_part_controls()
        _update_mapping_status()
        _set_mesh_replacement_selection_view(
            **selection_state["selection_view_kwargs"]
        )
        _update_selection_context()
        if bool(selection_state["refresh_filter"]):
            filter_refresh()
        _queue_selection_preview_refresh()

    def _source_selection_changed(_current: Optional[QTreeWidgetItem], _previous: Optional[QTreeWidgetItem]) -> None:
        _refresh_source_tree_selection_state()

    def _ensure_source_tree_item_available(source_index: int) -> Optional[QTreeWidgetItem]:
        try:
            source_index = int(source_index)
        except (TypeError, ValueError):
            return None
        source_item = source_items_by_index.get(source_index)
        if source_item is not None:
            return source_item
        if replacement_mesh_for_mapping is None:
            return None
        submeshes = tuple(getattr(replacement_mesh_for_mapping, "submeshes", ()) or ())
        if source_index < 0 or source_index >= len(submeshes):
            return None
        source = submeshes[source_index]
        if _is_marker_source(source):
            return None
        blocked = source_tree.blockSignals(True)
        try:
            _add_source_tree_item(source_index, source)
        finally:
            source_tree.blockSignals(blocked)
        _fit_alignment_tree_height_to_rows(source_tree, **source_tree_layout_state.height_fit_kwargs)
        source_parts_group.setMaximumHeight(16777215)
        return source_items_by_index.get(source_index)

    def _select_source_part_from_viewport(source_index: int) -> bool:
        try:
            source_index = int(source_index)
        except (TypeError, ValueError):
            return False
        source_item = _ensure_source_tree_item_available(source_index)
        if source_item is None:
            return False
        blocked = source_tree.blockSignals(True)
        try:
            source_tree.clearSelection()
            source_item.setSelected(True)
            source_tree.setCurrentItem(source_item)
        finally:
            source_tree.blockSignals(blocked)
        source_tree.scrollToItem(source_item)
        mapped_targets = _source_assigned_target_indices_helper(
            source_index,
            mapping_edits,
            parse_mapping_edit=_parse_mapping_edit,
        )
        filter_refresh = texture_filter_refresh.get("func")
        selection_state = _source_selection_route_state_helper(
            source_index,
            mapped_targets,
            has_filter_refresh=filter_refresh is not None,
            selected_filter_enabled=(
                texture_filter_selected_checkbox is not None
                and texture_filter_selected_checkbox.isChecked()
            ),
        )
        selected_source_part["index"] = int(selection_state["source_index"])
        selected_source_highlight_indices.clear()
        selected_source_highlight_indices.update(tuple(selection_state["source_highlight_indices"]))
        _set_transform_source_indices(tuple(selection_state["transform_source_indices"]))
        _sync_highlight_sets()
        _load_selected_part_controls()
        _update_mapping_status()
        selected_target_original_highlight_indices.clear()
        selected_target_source_highlight_indices.clear()
        selected_target_slot["index"] = -1
        _set_mesh_replacement_selection_view(
            **selection_state["selection_view_kwargs"]
        )
        _update_selection_context()
        if bool(selection_state["refresh_filter"]):
            filter_refresh()
        _queue_selection_preview_refresh()
        return True

    def _d3d11_source_part_selected(source_index: int) -> None:
        source_indices = _alignment_d3d11_source_indices_for_editor_id(int(source_index))
        route_state = _d3d11_source_part_selection_route_helper(
            preview_active=_alignment_d3d11_preview_active(),
            geometry_tab_active=_alignment_geometry_tab_active(),
            source_index=source_index,
            current_source_index=selected_source_part.get("index", -1),
            editor_source_indices=source_indices,
        )
        if not route_state["should_select"]:
            return
        _select_source_part_from_viewport(int(route_state["selected_source_index"]))

    def _original_selection_changed(current: Optional[QTreeWidgetItem], _previous: Optional[QTreeWidgetItem]) -> None:
        raw_indices = current.data(0, Qt.UserRole) if current is not None else ()
        selection_state = _original_selection_route_state_helper(raw_indices)
        selected_original_part["index"] = int(selection_state["original_index"])
        selected_original_highlight_indices.clear()
        selected_original_highlight_indices.update(tuple(selection_state["original_highlight_indices"]))
        _sync_highlight_sets()
        _refresh_original_reference_preview()
        _set_mesh_replacement_selection_view(**selection_state["selection_view_kwargs"])
        _update_selection_context()
        _queue_selection_preview_refresh()

    def _target_selection_changed(current: Optional[QTreeWidgetItem], _previous: Optional[QTreeWidgetItem]) -> None:
        raw_target_index = current.data(0, Qt.UserRole + 1) if current is not None else None
        target_index = _target_selection_index_helper(raw_target_index)
        source_indices = (
            _target_source_indices_helper(
                target_index,
                mapping_edits_by_target,
                parse_mapping_edit=_parse_mapping_edit,
            )
            if target_index >= 0
            else ()
        )
        selection_state = _target_selection_route_state_helper(raw_target_index, source_indices)
        selected_target_slot["index"] = int(selection_state["target_index"])
        selected_target_original_highlight_indices.clear()
        selected_target_original_highlight_indices.update(tuple(selection_state["target_original_highlight_indices"]))
        selected_target_source_highlight_indices.clear()
        selected_target_source_highlight_indices.update(tuple(selection_state["target_source_highlight_indices"]))
        _parts_outliner_set_source_selection(
            selection_state["outliner_source_selection"],
            activate_transform=False,
            select_reference_rows=False,
        )
        source_blocked = source_tree.blockSignals(True)
        try:
            source_tree.clearSelection()
        finally:
            source_tree.blockSignals(source_blocked)
        _sync_highlight_sets()
        _refresh_original_reference_preview()
        _load_selected_part_controls()
        _update_mapping_status()
        _set_mesh_replacement_selection_view(**selection_state["selection_view_kwargs"])
        _update_selection_context()
        _queue_selection_preview_refresh()

    def _parts_outliner_selection_changed(current: Optional[QTreeWidgetItem], _previous: Optional[QTreeWidgetItem]) -> None:
        row_state = _parts_outliner_selection_row_state_helper(current, user_role=int(Qt.UserRole))
        if row_state is None:
            return
        row_kind = str(row_state["row_kind"])
        target_index = int(row_state["target_index"])
        source_indices = list(row_state["source_indices"])  # type: ignore[arg-type]
        if row_kind == "source" and source_indices:
            _select_source_part_from_viewport(source_indices[0])
            if target_index >= 0:
                target_item = mapping_items_by_target.get(target_index)
                if target_item is not None:
                    mapping_tree.blockSignals(True)
                    try:
                        mapping_tree.setCurrentItem(target_item)
                    finally:
                        mapping_tree.blockSignals(False)
                selected_target_slot["index"] = target_index
                selected_target_original_highlight_indices.clear()
                selected_target_source_highlight_indices.clear()
                _sync_highlight_sets()
                _refresh_original_reference_preview()
            return
        if row_kind == "target":
            selection_state = _parts_outliner_target_selection_state_helper(
                row_kind=row_kind,
                target_index=target_index,
                source_indices=tuple(source_indices),
            )
            if selection_state is None:
                return
            selected_target_slot["index"] = int(selection_state["selected_target_index"])
            target_item = mapping_items_by_target.get(target_index)
            if target_item is not None:
                mapping_tree.blockSignals(True)
                try:
                    mapping_tree.setCurrentItem(target_item)
                finally:
                    mapping_tree.blockSignals(False)
            _parts_outliner_set_source_selection(
                source_indices,
                activate_transform=False,
                select_reference_rows=False,
            )
            source_blocked = source_tree.blockSignals(True)
            try:
                source_tree.clearSelection()
            finally:
                source_tree.blockSignals(source_blocked)
            selected_target_original_highlight_indices.clear()
            selected_target_source_highlight_indices.clear()
            selected_target_original_highlight_indices.update(
                tuple(selection_state["target_original_highlight_indices"])  # type: ignore[arg-type]
            )
            selected_target_source_highlight_indices.update(
                tuple(selection_state["target_source_highlight_indices"])  # type: ignore[arg-type]
            )
            _sync_highlight_sets()
            _refresh_original_reference_preview()
            _load_selected_part_controls()
            _update_mapping_status()
            _set_mesh_replacement_selection_view(
                **_selection_view_update_kwargs_helper(selection_state["selection_view"])  # type: ignore[arg-type]
            )
            _update_selection_context()
            _queue_selection_preview_refresh()

    def _clear_part_selections_when_leaving_geometry(index: int) -> None:
        if control_tabs.widget(index) is parts_tab:
            return
        has_selection = _part_selection_state_active_helper(
            selected_source_index=int(selected_source_part.get("index", -1)),
            selected_original_index=int(selected_original_part.get("index", -1)),
            selected_target_index=int(selected_target_slot.get("index", -1)),
            selected_source_highlights=tuple(selected_source_highlight_indices),
            selected_target_source_highlights=tuple(selected_target_source_highlight_indices),
            selected_original_highlights=tuple(selected_original_highlight_indices),
            selected_target_original_highlights=tuple(selected_target_original_highlight_indices),
            source_tree_has_selection=bool(source_tree.selectedItems()),
            original_tree_has_selection=bool(original_tree.selectedItems()),
            mapping_tree_has_selection=bool(mapping_tree.selectedItems()),
        )
        if not has_selection:
            return
        clear_state = _part_selection_clear_state_helper()
        for tree in (source_tree, original_tree, mapping_tree, parts_outliner_tree):
            previous_blocked = tree.blockSignals(True)
            try:
                _clear_tree_current_item(tree)
            finally:
                tree.blockSignals(previous_blocked)
        selected_source_part["index"] = int(clear_state["selected_source_index"])
        selected_original_part["index"] = int(clear_state["selected_original_index"])
        selected_target_slot["index"] = int(clear_state["selected_target_index"])
        selected_source_highlight_indices.clear()
        _clear_transform_source_indices()
        selected_target_source_highlight_indices.clear()
        selected_original_highlight_indices.clear()
        selected_target_original_highlight_indices.clear()
        _sync_highlight_sets()
        _refresh_original_reference_preview()
        _load_selected_part_controls()
        _update_mapping_status()
        selection_payload = clear_state["selection_view"]
        _set_mesh_replacement_selection_view(
            **_selection_view_update_kwargs_helper(selection_payload)  # type: ignore[arg-type]
        )
        _update_selection_context()
        filter_refresh = texture_filter_refresh.get("func")
        if _selection_filter_refresh_needed_helper(
            has_filter_refresh=filter_refresh is not None,
            selected_filter_enabled=(
                texture_filter_selected_checkbox is not None
                and texture_filter_selected_checkbox.isChecked()
            ),
        ):
            filter_refresh()
        _queue_selection_preview_refresh()

    return SimpleNamespace(
        _refresh_source_tree_selection_state=_refresh_source_tree_selection_state,
        _source_selection_changed=_source_selection_changed,
        _ensure_source_tree_item_available=_ensure_source_tree_item_available,
        _select_source_part_from_viewport=_select_source_part_from_viewport,
        _d3d11_source_part_selected=_d3d11_source_part_selected,
        _original_selection_changed=_original_selection_changed,
        _target_selection_changed=_target_selection_changed,
        _parts_outliner_selection_changed=_parts_outliner_selection_changed,
        _clear_part_selections_when_leaving_geometry=_clear_part_selections_when_leaving_geometry,
    )

def create_alignment_texture_detail_uv_callbacks(context: dict[str, object]) -> SimpleNamespace:
    Path = context.get('Path')
    Qt = context.get('Qt')
    _dds_detail_refresh_route_state_helper = context.get('_dds_detail_refresh_route_state_helper')
    _dds_detail_resolved_thumbnail_state_helper = context.get('_dds_detail_resolved_thumbnail_state_helper')
    _default_texture_uv_transform_state = context.get('_default_texture_uv_transform_state')
    _queue_texture_uv_preview_refresh = context.get('_queue_texture_uv_preview_refresh')
    _read_preview_pixmap = context.get('_read_preview_pixmap')
    _resolve_dds_detail_preview_path_helper = context.get('_resolve_dds_detail_preview_path_helper')
    _texture_transform_controls_set_loading_helper = context.get('_texture_transform_controls_set_loading_helper')
    _texture_uv_transform_control_load_state_helper = context.get('_texture_uv_transform_control_load_state_helper')
    _texture_uv_transform_control_save_state_helper = context.get('_texture_uv_transform_control_save_state_helper')
    _texture_uv_transform_key = context.get('_texture_uv_transform_key')
    _texture_uv_transform_materials_state_helper = context.get('_texture_uv_transform_materials_state_helper')
    _texture_uv_transform_reset_state_helper = context.get('_texture_uv_transform_reset_state_helper')
    dds_detail_thumbnail_label = context.get('dds_detail_thumbnail_label')
    enabled = context.get('enabled')
    ensure_dds_display_preview_png = context.get('ensure_dds_display_preview_png')
    item = context.get('item')
    material_key = context.get('material_key')
    material_plan_control_text = context.get('material_plan_control_text')
    parse_dds = context.get('parse_dds')
    queue_preview = context.get('queue_preview')
    raw_path = context.get('raw_path')
    self = context.get('self')
    slot_kind = context.get('slot_kind')
    texture_overrides_dirty = context.get('texture_overrides_dirty')
    texture_sets = context.get('texture_sets')
    texture_transform_controls_loading = context.get('texture_transform_controls_loading')
    texture_transform_flip_u_checkbox = context.get('texture_transform_flip_u_checkbox')
    texture_transform_flip_v_checkbox = context.get('texture_transform_flip_v_checkbox')
    texture_transform_group = context.get('texture_transform_group')
    texture_transform_material_combo = context.get('texture_transform_material_combo')
    texture_transform_offset_u_spin = context.get('texture_transform_offset_u_spin')
    texture_transform_offset_v_spin = context.get('texture_transform_offset_v_spin')
    texture_transform_reset_button = context.get('texture_transform_reset_button')
    texture_transform_rotate_combo = context.get('texture_transform_rotate_combo')
    texture_transform_scale_u_spin = context.get('texture_transform_scale_u_spin')
    texture_transform_scale_v_spin = context.get('texture_transform_scale_v_spin')
    texture_uv_transform_state = context.get('texture_uv_transform_state')

    def _apply_dds_detail_thumbnail_state(thumbnail_state: object, pixmap: Optional[QPixmap] = None) -> None:
        if bool(getattr(thumbnail_state, "show_pixmap", False)) and pixmap is not None and not pixmap.isNull():
            scaled = pixmap.scaled(
                dds_detail_thumbnail_label.size(),
                Qt.KeepAspectRatio,
                Qt.SmoothTransformation,
            )
            dds_detail_thumbnail_label.setPixmap(scaled)
            dds_detail_thumbnail_label.setToolTip(str(getattr(thumbnail_state, "tooltip", "")))
            return
        dds_detail_thumbnail_label.clear()
        dds_detail_thumbnail_label.setText(str(getattr(thumbnail_state, "text", "")))
        dds_detail_thumbnail_label.setToolTip(str(getattr(thumbnail_state, "tooltip", "")))

    def _resolve_dds_detail_preview_path(raw_path: object, slot_kind: object = "base") -> tuple[Optional[Path], str]:
        texconv_text = self.texconv_path_edit.text().strip()
        texconv_path = Path(texconv_text).expanduser() if texconv_text else None
        return _resolve_dds_detail_preview_path_helper(
            raw_path,
            slot_kind,
            texconv_path=texconv_path,
            parse_dds_file=parse_dds,
            ensure_dds_display_preview=ensure_dds_display_preview_png,
        )

    def _refresh_dds_detail_thumbnail(item: Optional[QTreeWidgetItem]) -> None:
        route_state = _dds_detail_refresh_route_state_helper(
            has_item=item is not None,
            preview_source=item.data(0, Qt.UserRole + 4) if item is not None else None,
            slot_kind=(item.data(0, Qt.UserRole + 6) if item is not None else "base") or "base",
            control_text=material_plan_control_text,
        )
        if not route_state.should_resolve:
            _apply_dds_detail_thumbnail_state(route_state.thumbnail)
            return
        preview_path, status_text = _resolve_dds_detail_preview_path(
            route_state.preview_source,
            route_state.slot_kind,
        )
        pixmap = _read_preview_pixmap(preview_path) if preview_path is not None else None
        thumbnail_state = _dds_detail_resolved_thumbnail_state_helper(
            preview_path=preview_path,
            status_text=status_text,
            pixmap_readable=bool(pixmap is not None and not pixmap.isNull()),
            control_text=material_plan_control_text,
        )
        _apply_dds_detail_thumbnail_state(thumbnail_state, pixmap)

    def _set_texture_transform_controls_enabled(enabled: bool) -> None:
        for widget in (
            texture_transform_material_combo,
            texture_transform_rotate_combo,
            texture_transform_flip_u_checkbox,
            texture_transform_flip_v_checkbox,
            texture_transform_offset_u_spin,
            texture_transform_offset_v_spin,
            texture_transform_scale_u_spin,
            texture_transform_scale_v_spin,
            texture_transform_reset_button,
        ):
            widget.setEnabled(bool(enabled))

    def _load_texture_transform_controls(material_key: str) -> None:
        load_state = _texture_uv_transform_control_load_state_helper(
            texture_uv_transform_state,
            material_key,
            _default_texture_uv_transform_state(material_key),
            transform_key=_texture_uv_transform_key,
        )
        _texture_transform_controls_set_loading_helper(
            texture_transform_controls_loading,
            active=True,
            key=str(load_state["key"]),
        )
        values = load_state["values"]  # type: ignore[assignment]
        rotation = int(values["rotate_degrees"])
        rotation_index = texture_transform_rotate_combo.findData(rotation)
        texture_transform_rotate_combo.setCurrentIndex(max(0, rotation_index))
        texture_transform_flip_u_checkbox.setChecked(bool(values["flip_u"]))
        texture_transform_flip_v_checkbox.setChecked(bool(values["flip_v"]))
        texture_transform_offset_u_spin.setValue(float(values["offset_u"]))
        texture_transform_offset_v_spin.setValue(float(values["offset_v"]))
        texture_transform_scale_u_spin.setValue(float(values["scale_u"]))
        texture_transform_scale_v_spin.setValue(float(values["scale_v"]))
        _texture_transform_controls_set_loading_helper(
            texture_transform_controls_loading,
            active=False,
        )

    def _save_texture_transform_controls(
        _signal_value: object = None,
        *,
        queue_preview: bool = True,
    ) -> bool:
        save_state = _texture_uv_transform_control_save_state_helper(
            texture_uv_transform_state,
            texture_transform_controls_loading,
            material_name=texture_transform_material_combo.currentText().strip(),
            rotate_degrees=texture_transform_rotate_combo.currentData() or 0,
            flip_u=texture_transform_flip_u_checkbox.isChecked(),
            flip_v=texture_transform_flip_v_checkbox.isChecked(),
            offset_u=texture_transform_offset_u_spin.value(),
            offset_v=texture_transform_offset_v_spin.value(),
            scale_u=texture_transform_scale_u_spin.value(),
            scale_v=texture_transform_scale_v_spin.value(),
            queue_preview=queue_preview,
        )
        if not bool(save_state["saved"]):
            return False
        if save_state["queue_preview"]:
            _queue_texture_uv_preview_refresh()
        elif save_state["mark_dirty"]:
            texture_overrides_dirty["dirty"] = True
        return True

    def _sync_texture_transform_materials() -> None:
        previous_key = str(texture_transform_material_combo.currentData() or "")
        sync_state = _texture_uv_transform_materials_state_helper(
            texture_sets,
            texture_uv_transform_state,
            previous_key,
            transform_key=_texture_uv_transform_key,
            default_state_for_material=_default_texture_uv_transform_state,
        )
        texture_transform_material_combo.blockSignals(True)
        texture_transform_material_combo.clear()
        for material_name, key in tuple(sync_state["choices"]):  # type: ignore[arg-type]
            texture_transform_material_combo.addItem(material_name, key)
        target_index = texture_transform_material_combo.findData(str(sync_state["selected_key"]))
        texture_transform_material_combo.setCurrentIndex(max(0, target_index))
        texture_transform_material_combo.blockSignals(False)
        has_materials = bool(sync_state["has_materials"])
        texture_transform_group.setVisible(bool(has_materials))
        _set_texture_transform_controls_enabled(has_materials)
        if has_materials:
            selected_key = str(texture_transform_material_combo.currentData() or "")
            selected_material = texture_transform_material_combo.currentText().strip()
            _texture_transform_controls_set_loading_helper(
                texture_transform_controls_loading,
                active=False,
                key=selected_key,
            )
            _load_texture_transform_controls(selected_material)
        else:
            _texture_transform_controls_set_loading_helper(
                texture_transform_controls_loading,
                active=False,
                key="",
            )

    def _handle_texture_transform_material_changed(_index: int) -> None:
        material_name = texture_transform_material_combo.currentText().strip()
        _load_texture_transform_controls(material_name)

    def _reset_selected_texture_transform() -> None:
        material_name = texture_transform_material_combo.currentText().strip()
        reset_state = _texture_uv_transform_reset_state_helper(
            texture_uv_transform_state,
            material_name,
            _default_texture_uv_transform_state(material_name),
            transform_key=_texture_uv_transform_key,
        )
        if not reset_state["reset"]:
            return
        _load_texture_transform_controls(material_name)
        _queue_texture_uv_preview_refresh()

    return SimpleNamespace(
        _apply_dds_detail_thumbnail_state=_apply_dds_detail_thumbnail_state,
        _resolve_dds_detail_preview_path=_resolve_dds_detail_preview_path,
        _refresh_dds_detail_thumbnail=_refresh_dds_detail_thumbnail,
        _set_texture_transform_controls_enabled=_set_texture_transform_controls_enabled,
        _load_texture_transform_controls=_load_texture_transform_controls,
        _save_texture_transform_controls=_save_texture_transform_controls,
        _sync_texture_transform_materials=_sync_texture_transform_materials,
        _handle_texture_transform_material_changed=_handle_texture_transform_material_changed,
        _reset_selected_texture_transform=_reset_selected_texture_transform,
    )

def create_alignment_accept_build_callbacks(context: dict[str, object]) -> SimpleNamespace:
    List = context.get('List')
    Mapping = context.get('Mapping')
    Optional = context.get('Optional')
    QMessageBox = context.get('QMessageBox')
    StaticMeshReplacementOptions = context.get('StaticMeshReplacementOptions')
    StaticSubmeshMapping = context.get('StaticSubmeshMapping')
    StaticTextureSlotOverride = context.get('StaticTextureSlotOverride')
    Tuple = context.get('Tuple')
    _alignment_accept_handler_failed_status_helper = context.get('_alignment_accept_handler_failed_status_helper')
    _alignment_build_status_finished_helper = context.get('_alignment_build_status_finished_helper')
    _alignment_build_status_started_helper = context.get('_alignment_build_status_started_helper')
    _alignment_builder_warning_title_helper = context.get('_alignment_builder_warning_title_helper')
    _alignment_custom_icon_override_spec = context.get('_alignment_custom_icon_override_spec')
    _commit_spinbox_text = context.get('_commit_spinbox_text')
    _complete_external_swap_enabled = context.get('_complete_external_swap_enabled')
    _complete_external_swap_mappings = context.get('_complete_external_swap_mappings')
    _copied_source_texture_slot_overrides = context.get('_copied_source_texture_slot_overrides')
    _current_complete_swap_material_profile_token = context.get('_current_complete_swap_material_profile_token')
    _current_static_placement_snapshot = context.get('_current_static_placement_snapshot')
    _flush_source_role_overrides_for_export = context.get('_flush_source_role_overrides_for_export')
    _invalid_submesh_mapping_missing_source_message_helper = context.get('_invalid_submesh_mapping_missing_source_message_helper')
    _invalid_submesh_mapping_non_numeric_message_helper = context.get('_invalid_submesh_mapping_non_numeric_message_helper')
    _invalid_submesh_mapping_title_helper = context.get('_invalid_submesh_mapping_title_helper')
    _is_marker_source = context.get('_is_marker_source')
    _mapping_table_build_complete_helper = context.get('_mapping_table_build_complete_helper')
    _mapping_vertex_limit_issues = context.get('_mapping_vertex_limit_issues')
    _mesh_replacement_too_large_message_helper = context.get('_mesh_replacement_too_large_message_helper')
    _mesh_replacement_too_large_title_helper = context.get('_mesh_replacement_too_large_title_helper')
    _save_texture_transform_controls = context.get('_save_texture_transform_controls')
    _source_display_name = context.get('_source_display_name')
    _source_part_added_export_blocker_message_helper = context.get('_source_part_added_export_blocker_message_helper')
    _source_part_added_export_blocker_title_helper = context.get('_source_part_added_export_blocker_title_helper')
    _source_renderable_indices_helper = context.get('_source_renderable_indices_helper')
    _static_options_from_placement_snapshot = context.get('_static_options_from_placement_snapshot')
    _target_submesh_display_name_helper = context.get('_target_submesh_display_name_helper')
    _texture_row_effective_source_helper = context.get('_texture_row_effective_source_helper')
    _texture_slot_contract_key = context.get('_texture_slot_contract_key')
    _unmapped_appended_source_indices = context.get('_unmapped_appended_source_indices')
    _update_selected_part_adjustment = context.get('_update_selected_part_adjustment')
    _validate_mapping_text_source_indices_helper = context.get('_validate_mapping_text_source_indices_helper')
    _vertex_limit_issue_display_text_helper = context.get('_vertex_limit_issue_display_text_helper')
    accent_glow_spin = context.get('accent_glow_spin')
    auto_brightness_spin = context.get('auto_brightness_spin')
    build_accept_state = context.get('build_accept_state')
    build_status_bar = context.get('build_status_bar')
    build_status_label = context.get('build_status_label')
    custom_icon_checkbox = context.get('custom_icon_checkbox')
    dialog = context.get('dialog')
    dialog_added_supplemental_files = context.get('dialog_added_supplemental_files')
    edge_relief_source_combo = context.get('edge_relief_source_combo')
    edge_relief_spin = context.get('edge_relief_spin')
    external_material_reset_checkbox = context.get('external_material_reset_checkbox')
    global_gloss_reduction_spin = context.get('global_gloss_reduction_spin')
    import_button = context.get('import_button')
    inject_base_color_checkbox = context.get('inject_base_color_checkbox')
    mapping_edits = context.get('mapping_edits')
    mapping_table_build_state = context.get('mapping_table_build_state')
    mesh_edit_iterations_spin = context.get('mesh_edit_iterations_spin')
    mesh_edit_radius_spin = context.get('mesh_edit_radius_spin')
    mesh_edit_strength_spin = context.get('mesh_edit_strength_spin')
    offset_x_spin = context.get('offset_x_spin')
    offset_y_spin = context.get('offset_y_spin')
    offset_z_spin = context.get('offset_z_spin')
    on_accept = context.get('on_accept')
    original_mesh_for_mapping = context.get('original_mesh_for_mapping')
    part_nudge_step_spin = context.get('part_nudge_step_spin')
    part_offset_x_spin = context.get('part_offset_x_spin')
    part_offset_y_spin = context.get('part_offset_y_spin')
    part_offset_z_spin = context.get('part_offset_z_spin')
    part_rotate_x_spin = context.get('part_rotate_x_spin')
    part_rotate_y_spin = context.get('part_rotate_y_spin')
    part_rotate_z_spin = context.get('part_rotate_z_spin')
    part_scale_x_spin = context.get('part_scale_x_spin')
    part_scale_y_spin = context.get('part_scale_y_spin')
    part_scale_z_spin = context.get('part_scale_z_spin')
    part_uniform_spin = context.get('part_uniform_spin')
    prune_unmapped_original_dds_checkbox = context.get('prune_unmapped_original_dds_checkbox')
    rebuild_sidecar_checkbox = context.get('rebuild_sidecar_checkbox')
    replacement_export_allowed = context.get('replacement_export_allowed')
    replacement_mesh_for_mapping = context.get('replacement_mesh_for_mapping')
    rotate_x_spin = context.get('rotate_x_spin')
    rotate_y_spin = context.get('rotate_y_spin')
    rotate_z_spin = context.get('rotate_z_spin')
    scale_x_spin = context.get('scale_x_spin')
    scale_y_spin = context.get('scale_y_spin')
    scale_z_spin = context.get('scale_z_spin')
    self = context.get('self')
    source_brightness_spin = context.get('source_brightness_spin')
    source_color_faithful_checkbox = context.get('source_color_faithful_checkbox')
    suggested_mappings = context.get('suggested_mappings')
    texture_output_size_combo = context.get('texture_output_size_combo')
    texture_override_assignments = context.get('texture_override_assignments')
    texture_override_rows = context.get('texture_override_rows')
    texture_transform_offset_u_spin = context.get('texture_transform_offset_u_spin')
    texture_transform_offset_v_spin = context.get('texture_transform_offset_v_spin')
    texture_transform_scale_u_spin = context.get('texture_transform_scale_u_spin')
    texture_transform_scale_v_spin = context.get('texture_transform_scale_v_spin')
    tone_contrast_spin = context.get('tone_contrast_spin')
    unsafe_material_preflight_checkbox = context.get('unsafe_material_preflight_checkbox')

    def _apply_alignment_build_status_view(view_state: Mapping[str, object]) -> tuple[str, bool]:
        text = str(view_state.get("text", "") or "")
        try:
            build_status_label.setText(text)
            build_status_label.setVisible(bool(view_state.get("label_visible")))
            build_status_bar.setVisible(bool(view_state.get("bar_visible")))
            if "import_enabled" in view_state:
                import_button.setEnabled(bool(view_state.get("import_enabled")))
        except RuntimeError:
            return text, False
        return text, True

    def _set_alignment_build_status(message: str) -> None:
        text, applied = _apply_alignment_build_status_view(
            _alignment_build_status_started_helper(message)
        )
        if text and not applied:
            self.set_status_message(text)

    def _finish_alignment_build_state(message: str, success: bool) -> None:
        view_state = _alignment_build_status_finished_helper(
            build_accept_state,
            message,
            success=success,
            export_allowed=bool(replacement_export_allowed["allowed"]),
        )
        text, _applied = _apply_alignment_build_status_view(view_state)
        if text:
            self.set_status_message(text, error=bool(view_state.get("status_error")))

    def _dispatch_alignment_accept(options: StaticMeshReplacementOptions) -> None:
        if on_accept is None:
            return
        try:
            on_accept(options)
        except Exception as exc:
            self.set_status_message(_alignment_accept_handler_failed_status_helper(exc), error=True)
            QMessageBox.warning(dialog, _alignment_builder_warning_title_helper(), str(exc))

    def _commit_alignment_numeric_edits(*, refresh_preview: bool = True) -> None:
        for spin in (
            offset_x_spin,
            offset_y_spin,
            offset_z_spin,
            rotate_x_spin,
            rotate_y_spin,
            rotate_z_spin,
            scale_x_spin,
            scale_y_spin,
            scale_z_spin,
            part_offset_x_spin,
            part_offset_y_spin,
            part_offset_z_spin,
            part_rotate_x_spin,
            part_rotate_y_spin,
            part_rotate_z_spin,
            part_scale_x_spin,
            part_scale_y_spin,
            part_scale_z_spin,
            part_uniform_spin,
            part_nudge_step_spin,
            mesh_edit_radius_spin,
            mesh_edit_strength_spin,
            mesh_edit_iterations_spin,
            texture_transform_offset_u_spin,
            texture_transform_offset_v_spin,
            texture_transform_scale_u_spin,
            texture_transform_scale_v_spin,
        ):
            _commit_spinbox_text(spin, block_signals=not bool(refresh_preview))
        _update_selected_part_adjustment(queue_preview=refresh_preview, push_undo=refresh_preview)
        _save_texture_transform_controls(queue_preview=refresh_preview)

    def _build_static_options_from_dialog(
        *,
        show_messages: bool = True,
        include_edited_source_mesh: bool = True,
    ) -> Optional[StaticMeshReplacementOptions]:
        _commit_alignment_numeric_edits(refresh_preview=False)
        parsed_mappings = list(suggested_mappings or [])
        explicit_mapping_validation = False
        mapping_table_ready = True
        try:
            mapping_table_ready = _mapping_table_build_complete_helper(mapping_table_build_state)
        except NameError:
            mapping_table_ready = True
        if _complete_external_swap_enabled() and original_mesh_for_mapping is not None and replacement_mesh_for_mapping is not None:
            parsed_mappings = _complete_external_swap_mappings()
            explicit_mapping_validation = True
        elif mapping_edits and mapping_table_ready and original_mesh_for_mapping is not None and replacement_mesh_for_mapping is not None:
            render_source_indices = set(
                _source_renderable_indices_helper(
                    replacement_mesh_for_mapping,
                    is_marker_source=_is_marker_source,
                    require_enabled=False,
                )
            )
            parsed_mappings: List[StaticSubmeshMapping] = []
            for target_index, edit in mapping_edits:
                raw_text = str(edit.property("committed_mapping_text") or edit.text() or "").strip()
                validation = _validate_mapping_text_source_indices_helper(raw_text, render_source_indices)
                if validation.invalid_token:
                    if show_messages:
                        QMessageBox.warning(
                            dialog,
                            _invalid_submesh_mapping_title_helper(),
                            _invalid_submesh_mapping_non_numeric_message_helper(
                                target_index,
                                validation.invalid_token,
                            ),
                        )
                    return None
                if validation.missing_source_index is not None:
                    if show_messages:
                        QMessageBox.warning(
                            dialog,
                            _invalid_submesh_mapping_title_helper(),
                            _invalid_submesh_mapping_missing_source_message_helper(
                                target_index,
                                validation.missing_source_index,
                            ),
                        )
                    return None
                source_indices = list(validation.source_indices)
                target = original_mesh_for_mapping.submeshes[target_index]
                parsed_mappings.append(
                    StaticSubmeshMapping(
                        target_submesh_index=target_index,
                        target_submesh_name=_target_submesh_display_name_helper(target_index, target),
                        source_submesh_indices=source_indices,
                        target_material_slot_index=target_index,
                        merge_sources=True,
                    )
                )
            explicit_mapping_validation = True
        if explicit_mapping_validation:
            vertex_limit_issues = _mapping_vertex_limit_issues(parsed_mappings)
            if vertex_limit_issues:
                displayed_issues = _vertex_limit_issue_display_text_helper(vertex_limit_issues)
                if show_messages:
                    QMessageBox.warning(
                        dialog,
                        _mesh_replacement_too_large_title_helper(),
                        _mesh_replacement_too_large_message_helper(displayed_issues),
                    )
                return None
            unmapped_added_sources = _unmapped_appended_source_indices(parsed_mappings)
            if unmapped_added_sources:
                displayed_sources = "\n".join(
                    f"- {_source_display_name(source_index)}"
                    for source_index in unmapped_added_sources[:10]
                )
                if len(unmapped_added_sources) > 10:
                    displayed_sources += f"\n- ... {len(unmapped_added_sources) - 10} more"
                if show_messages:
                    QMessageBox.warning(
                        dialog,
                        _source_part_added_export_blocker_title_helper(),
                        _source_part_added_export_blocker_message_helper(displayed_sources),
                    )
                return None
        texture_slot_overrides: List[StaticTextureSlotOverride] = []
        occupied_texture_override_keys: set[Tuple[str, str]] = set()
        for texture_row in texture_override_rows:
            source_path = _texture_row_effective_source_helper(
                texture_row,
                texture_override_assignments,
            )
            if not source_path:
                continue
            target_path = str(texture_row.get("target_path", "") or "")
            slot_kind = str(texture_row.get("slot_kind", "") or "material")
            occupied_texture_override_keys.add(
                (target_path.replace("\\", "/").lower(), _texture_slot_contract_key(slot_kind))
            )
            texture_slot_overrides.append(
                StaticTextureSlotOverride(
                    target_texture_path=target_path,
                    source_path=source_path,
                    slot_kind=slot_kind,
                    target_material_name=str(texture_row.get("target_name", "") or ""),
                    enabled=True,
                )
            )
        texture_slot_overrides.extend(
            _copied_source_texture_slot_overrides(
                parsed_mappings,
                occupied_keys=occupied_texture_override_keys,
            )
        )
        custom_item_icon_override = None
        if custom_icon_checkbox.isChecked():
            custom_item_icon_override = _alignment_custom_icon_override_spec(show_messages=show_messages)
            if custom_item_icon_override is None:
                return None
        try:
            _flush_source_role_overrides_for_export()
        except NameError:
            pass
        placement_snapshot = _current_static_placement_snapshot(
            parsed_mappings,
            include_preview_only_independent_parts=False,
        )
        options = _static_options_from_placement_snapshot(
            placement_snapshot,
            texture_slot_overrides=texture_slot_overrides,
            include_edited_source_mesh=bool(include_edited_source_mesh),
            rebuild_material_sidecar=bool(rebuild_sidecar_checkbox.isChecked() or _complete_external_swap_enabled()),
            complete_external_swap=bool(_complete_external_swap_enabled()),
            neutralize_inherited_material_layers=bool(source_color_faithful_checkbox.isChecked() or _complete_external_swap_enabled()),
            complete_external_material_reset=bool(external_material_reset_checkbox.isChecked() or _complete_external_swap_enabled()),
            enable_missing_base_color_parameters=bool(inject_base_color_checkbox.isChecked() or _complete_external_swap_enabled()),
            texture_output_size_mode=str(texture_output_size_combo.currentData() or "source"),
            complete_swap_material_profile=str(_current_complete_swap_material_profile_token()),
            global_gloss_reduction=float(global_gloss_reduction_spin.value()),
            edge_relief_strength=float(edge_relief_spin.value()),
            edge_relief_source=str(edge_relief_source_combo.currentData() or "hybrid"),
            accent_glow_strength=float(accent_glow_spin.value()),
            auto_brightness_balance=float(auto_brightness_spin.value()),
            dark_detail_lift=float(source_brightness_spin.value()),
            tone_contrast=float(tone_contrast_spin.value()),
            allow_unsafe_material_preflight_export=bool(unsafe_material_preflight_checkbox.isChecked()),
            additional_supplemental_files=list(dialog_added_supplemental_files),
            custom_item_icon_override=custom_item_icon_override,
            prune_unmapped_original_texture_parameters=bool(
                prune_unmapped_original_dds_checkbox.isChecked() or _complete_external_swap_enabled()
            ),
        )
        if bool(context.get("full_import_model_replacement")):
            from cdmw.modding.full_import_model_replacement import (
                apply_full_import_model_replacement_preset,
            )

            return apply_full_import_model_replacement_preset(options)
        return options

    return SimpleNamespace(
        _apply_alignment_build_status_view=_apply_alignment_build_status_view,
        _set_alignment_build_status=_set_alignment_build_status,
        _finish_alignment_build_state=_finish_alignment_build_state,
        _dispatch_alignment_accept=_dispatch_alignment_accept,
        _commit_alignment_numeric_edits=_commit_alignment_numeric_edits,
        _build_static_options_from_dialog=_build_static_options_from_dialog,
    )


def create_alignment_accept_dispatch_callbacks(context: dict[str, object]) -> SimpleNamespace:
    QMessageBox = context.get('QMessageBox')
    QTimer = context.get('QTimer')
    _alignment_build_accept_route_helper = context.get('_alignment_build_accept_route_helper')
    _alignment_build_accept_running_helper = context.get('_alignment_build_accept_running_helper')
    _alignment_build_accept_set_running_helper = context.get('_alignment_build_accept_set_running_helper')
    _alignment_build_callback_result_route_helper = context.get('_alignment_build_callback_result_route_helper')
    _alignment_build_failed_status_helper = context.get('_alignment_build_failed_status_helper')
    _alignment_build_mod_warning_title_helper = context.get('_alignment_build_mod_warning_title_helper')
    _alignment_build_options_route_helper = context.get('_alignment_build_options_route_helper')
    _alignment_build_started_status_helper = context.get('_alignment_build_started_status_helper')
    _alignment_build_status_reset_helper = context.get('_alignment_build_status_reset_helper')
    _alignment_dialog_mark_accepted_helper = context.get('_alignment_dialog_mark_accepted_helper')
    _apply_alignment_build_status_view = context.get('_apply_alignment_build_status_view')
    _build_static_options_from_dialog = context.get('_build_static_options_from_dialog')
    _dispatch_alignment_accept = context.get('_dispatch_alignment_accept')
    _finish_alignment_build_state = context.get('_finish_alignment_build_state')
    _set_alignment_build_status = context.get('_set_alignment_build_status')
    build_accept_state = context.get('build_accept_state')
    continue_build_callback = context.get('continue_build_callback')
    dialog = context.get('dialog')
    dialog_accepted_state = context.get('dialog_accepted_state')
    import_button = context.get('import_button')
    on_accept = context.get('on_accept')
    replacement_export_allowed = context.get('replacement_export_allowed')
    self = context.get('self')
    continue_build_available = callable(continue_build_callback)

    def _accept_static_options() -> None:
        accept_route = _alignment_build_accept_route_helper(
            continue_build=continue_build_available,
            running=_alignment_build_accept_running_helper(build_accept_state),
        )
        if accept_route.should_ignore:
            return
        if accept_route.should_mark_running:
            _alignment_build_accept_set_running_helper(build_accept_state, True)
        if accept_route.should_disable_import:
            import_button.setEnabled(False)
            _set_alignment_build_status("Preparing mesh replacement build options...")
        if accept_route.should_schedule_status_paint:
            QTimer.singleShot(25, _accept_static_options_after_status_paint)
            return
        if accept_route.should_run_immediately:
            _accept_static_options_after_status_paint()

    def _accept_static_options_after_status_paint() -> None:
        try:
            static_options = _build_static_options_from_dialog(
                show_messages=True,
                include_edited_source_mesh=True,
            )
        except Exception as exc:
            QMessageBox.warning(
                dialog,
                _alignment_build_mod_warning_title_helper(),
                str(exc),
            )
            _finish_alignment_build_state(_alignment_build_failed_status_helper(exc), False)
            return
        options_route = _alignment_build_options_route_helper(
            options_available=static_options is not None,
            continue_build=continue_build_available,
        )
        if options_route.should_reset_build_status:
            _apply_alignment_build_status_view(
                _alignment_build_status_reset_helper(
                    build_accept_state,
                    export_allowed=bool(replacement_export_allowed["allowed"]),
                )
            )
        if static_options is None:
            return
        dialog._static_mappings = list(static_options.submesh_mappings or [])  # type: ignore[attr-defined]
        dialog._static_options = static_options  # type: ignore[attr-defined]
        if options_route.should_collect_build_settings:
            _set_alignment_build_status("Collecting mesh replacement mod build settings...")
            try:
                started = bool(
                    continue_build_callback(
                        static_options,
                        dialog,
                        _set_alignment_build_status,
                        _finish_alignment_build_state,
                        "loose",
                    )
                )
            except Exception as exc:
                QMessageBox.warning(
                    dialog,
                    _alignment_build_mod_warning_title_helper(),
                    str(exc),
                )
                _finish_alignment_build_state(_alignment_build_failed_status_helper(exc), False)
                started = False
            callback_route = _alignment_build_callback_result_route_helper(started)
            if callback_route.should_reset_build_status:
                _apply_alignment_build_status_view(
                    _alignment_build_status_reset_helper(
                        build_accept_state,
                        export_allowed=bool(replacement_export_allowed["allowed"]),
                    )
                )
            if callback_route.should_report_started:
                self.set_status_message(_alignment_build_started_status_helper())
            return
        if options_route.should_accept_dialog:
            _alignment_dialog_mark_accepted_helper(dialog_accepted_state)
            dialog.accept()
            if on_accept is not None:
                QTimer.singleShot(0, lambda options=static_options: _dispatch_alignment_accept(options))

    return SimpleNamespace(
        _accept_static_options=_accept_static_options,
        _accept_static_options_after_status_paint=_accept_static_options_after_status_paint,
    )


def create_manual_material_profile_runtime_callbacks(context: dict[str, object]) -> SimpleNamespace:
    Dict = context.get('Dict')
    Mapping = context.get('Mapping')
    Optional = context.get('Optional')
    QCheckBox = context.get('QCheckBox')
    QComboBox = context.get('QComboBox')
    QDoubleSpinBox = context.get('QDoubleSpinBox')
    QMessageBox = context.get('QMessageBox')
    QSpinBox = context.get('QSpinBox')
    Sequence = context.get('Sequence')
    _coerce_manual_profile_values = context.get('_coerce_manual_profile_values')
    _complete_external_swap_enabled = context.get('_complete_external_swap_enabled')
    _delete_manual_material_profile_preset_helper = context.get('_delete_manual_material_profile_preset_helper')
    _manual_material_profile_control_effect_states_helper = context.get('_manual_material_profile_control_effect_states_helper')
    _manual_material_profile_delete_question_helper = context.get('_manual_material_profile_delete_question_helper')
    _manual_material_profile_dirty_state_helper = context.get('_manual_material_profile_dirty_state_helper')
    _manual_material_profile_panel_state_helper = context.get('_manual_material_profile_panel_state_helper')
    _manual_material_profile_preset_from_fields_helper = context.get('_manual_material_profile_preset_from_fields_helper')
    _manual_material_profile_preset_metadata_helper = context.get('_manual_material_profile_preset_metadata_helper')
    _manual_material_profile_preset_names_helper = context.get('_manual_material_profile_preset_names_helper')
    _manual_material_profile_saved_message_helper = context.get('_manual_material_profile_saved_message_helper')
    _manual_material_profile_token_helper = context.get('_manual_material_profile_token_helper')
    _queue_texture_preview_refresh = context.get('_queue_texture_preview_refresh')
    _refresh_output_impact_review = context.get('_refresh_output_impact_review')
    _save_manual_profile_presets = context.get('_save_manual_profile_presets')
    _selected_manual_material_profile_preset_helper = context.get('_selected_manual_material_profile_preset_helper')
    _upsert_manual_material_profile_preset_helper = context.get('_upsert_manual_material_profile_preset_helper')
    complete_swap_material_profile_combo = context.get('complete_swap_material_profile_combo')
    complete_swap_profile_store_path = context.get('complete_swap_profile_store_path')
    dialog = context.get('dialog')
    json = context.get('json')
    manual_profile_apply_button = context.get('manual_profile_apply_button')
    manual_profile_change_status = context.get('manual_profile_change_status')
    manual_profile_control_text = context.get('manual_profile_control_text')
    manual_profile_control_tooltips = context.get('manual_profile_control_tooltips')
    manual_profile_controls = context.get('manual_profile_controls')
    manual_profile_default_values = context.get('manual_profile_default_values')
    manual_profile_dirty = context.get('manual_profile_dirty')
    manual_profile_effect_widgets = context.get('manual_profile_effect_widgets')
    manual_profile_group = context.get('manual_profile_group')
    manual_profile_preset_combo = context.get('manual_profile_preset_combo')
    manual_profile_preset_details_edit = context.get('manual_profile_preset_details_edit')
    manual_profile_preset_name_edit = context.get('manual_profile_preset_name_edit')
    manual_profile_preset_recommended_edit = context.get('manual_profile_preset_recommended_edit')
    manual_profile_presets = context.get('manual_profile_presets')
    manual_profile_ready = context.get('manual_profile_ready')
    manual_profile_saved_values = context.get('manual_profile_saved_values')
    manual_profile_settings_key = context.get('manual_profile_settings_key')
    self = context.get('self')
    serialize_complete_swap_manual_material_profile = context.get('serialize_complete_swap_manual_material_profile')
    write_complete_swap_calibrated_material_profile = context.get('write_complete_swap_calibrated_material_profile')

    def _current_manual_material_profile_values() -> Dict[str, object]:
        values: Dict[str, object] = {}
        for key, control in manual_profile_controls.items():
            if isinstance(control, QComboBox):
                values[key] = str(control.currentData() or "")
            elif isinstance(control, QSpinBox):
                values[key] = int(control.value())
            elif isinstance(control, QDoubleSpinBox):
                values[key] = float(control.value())
            elif isinstance(control, QCheckBox):
                values[key] = bool(control.isChecked())
            elif isinstance(control, tuple):
                rgb_values: list[int] = []
                for channel_control in control:
                    if isinstance(channel_control, QSpinBox):
                        rgb_values.append(int(channel_control.value()))
                if len(rgb_values) >= 3:
                    values[key] = tuple(rgb_values[:3])
        return values

    def _refresh_manual_profile_control_effects(values: Optional[Mapping[str, object]] = None) -> None:
        current_values = dict(values or _current_manual_material_profile_values())
        control_states = _manual_material_profile_control_effect_states_helper(
            current_values,
            control_keys=tuple(manual_profile_effect_widgets),
            control_tooltips=manual_profile_control_tooltips,
        )
        for key, widgets in manual_profile_effect_widgets.items():
            state = control_states.get(key, {})
            for widget in widgets:
                if hasattr(widget, "setEnabled"):
                    widget.setEnabled(bool(state.get("enabled", True)))
                if hasattr(widget, "setToolTip"):
                    widget.setToolTip(str(state.get("tooltip", "")))

    def _set_manual_profile_dirty(dirty: bool) -> None:
        state = _manual_material_profile_dirty_state_helper(dirty)
        manual_profile_dirty["dirty"] = bool(state["dirty"])
        manual_profile_apply_button.setEnabled(bool(state["apply_enabled"]))
        manual_profile_change_status.setText(str(state["status_text"]))

    def _apply_manual_material_profile_values(values: Mapping[str, object], *, persist: bool, refresh_preview: bool = False) -> None:
        was_ready = bool(manual_profile_ready.get("ready"))
        manual_profile_ready["ready"] = False
        try:
            for key, control in manual_profile_controls.items():
                value = values.get(key, manual_profile_default_values.get(key))
                if isinstance(control, QComboBox):
                    index = control.findData(str(value or ""))
                    control.setCurrentIndex(max(0, index))
                elif isinstance(control, QSpinBox):
                    try:
                        control.setValue(int(value))
                    except (TypeError, ValueError, OverflowError):
                        pass
                elif isinstance(control, QDoubleSpinBox):
                    try:
                        control.setValue(float(value))
                    except (TypeError, ValueError, OverflowError):
                        pass
                elif isinstance(control, QCheckBox):
                    control.setChecked(bool(value))
                elif isinstance(control, tuple):
                    rgb = value if isinstance(value, Sequence) and not isinstance(value, (str, bytes)) else ()
                    for channel_index, channel_control in enumerate(control):
                        if not isinstance(channel_control, QSpinBox):
                            continue
                        try:
                            channel_control.setValue(int(rgb[channel_index]))
                        except (TypeError, ValueError, OverflowError, IndexError):
                            pass
        finally:
            manual_profile_ready["ready"] = was_ready
        if persist:
            saved = _current_manual_material_profile_values()
            manual_profile_saved_values.clear()
            manual_profile_saved_values.update(saved)
            self.settings.setValue(manual_profile_settings_key, json.dumps(saved, sort_keys=True, separators=(",", ":")))
            _save_complete_swap_material_profile()
            _refresh_manual_profile_control_effects(saved)
            if refresh_preview:
                _set_manual_profile_dirty(False)
                _refresh_output_impact_review()
                _queue_texture_preview_refresh()
            else:
                _set_manual_profile_dirty(True)

    def _reset_manual_material_profile_to_material_authority() -> None:
        _apply_manual_material_profile_values(manual_profile_default_values, persist=True, refresh_preview=True)

    def _apply_current_manual_material_profile_to_preview() -> None:
        if str(complete_swap_material_profile_combo.currentData() or "") != "material_authority_manual":
            return
        values = _current_manual_material_profile_values()
        self.settings.setValue(manual_profile_settings_key, json.dumps(values, sort_keys=True, separators=(",", ":")))
        manual_profile_saved_values.clear()
        manual_profile_saved_values.update(values)
        _save_complete_swap_material_profile()
        _set_manual_profile_dirty(False)
        _refresh_output_impact_review()
        _queue_texture_preview_refresh()

    _selected_manual_profile_preset = lambda: _selected_manual_material_profile_preset_helper(
            manual_profile_presets,
            manual_profile_preset_combo.currentData(),
        )

    def _refresh_manual_profile_preset_combo(select_name: str = "") -> None:
        current_name = str(select_name or manual_profile_preset_combo.currentData() or "").strip()
        manual_profile_preset_combo.blockSignals(True)
        try:
            manual_profile_preset_combo.clear()
            manual_profile_preset_combo.addItem(manual_profile_control_text["no_saved_profile"], "")
            for name in _manual_material_profile_preset_names_helper(manual_profile_presets):
                manual_profile_preset_combo.addItem(name, name)
            index = manual_profile_preset_combo.findData(current_name)
            manual_profile_preset_combo.setCurrentIndex(max(0, index))
        finally:
            manual_profile_preset_combo.blockSignals(False)
        _show_selected_manual_profile_preset_metadata()

    def _show_selected_manual_profile_preset_metadata() -> None:
        preset = _selected_manual_profile_preset()
        if preset is None:
            return
        metadata = _manual_material_profile_preset_metadata_helper(preset)
        manual_profile_preset_name_edit.setText(metadata["name"])
        manual_profile_preset_details_edit.setPlainText(metadata["details"])
        manual_profile_preset_recommended_edit.setText(metadata["recommended_models"])

    def _save_current_manual_profile_preset() -> None:
        name = manual_profile_preset_name_edit.text().strip()
        if not name:
            QMessageBox.information(
                dialog,
                manual_profile_control_text["save_title"],
                manual_profile_control_text["save_missing_name"],
            )
            return
        preset = _manual_material_profile_preset_from_fields_helper(
            name=name,
            details=manual_profile_preset_details_edit.toPlainText(),
            recommended_models=manual_profile_preset_recommended_edit.text(),
            values=_current_manual_material_profile_values(),
        )
        manual_profile_presets[:] = _upsert_manual_material_profile_preset_helper(manual_profile_presets, preset)
        _save_manual_profile_presets(manual_profile_presets)
        _refresh_manual_profile_preset_combo(name)
        QMessageBox.information(
            dialog,
            manual_profile_control_text["save_title"],
            _manual_material_profile_saved_message_helper(name),
        )

    def _load_selected_manual_profile_preset() -> None:
        preset = _selected_manual_profile_preset()
        if preset is None:
            QMessageBox.information(
                dialog,
                manual_profile_control_text["load_title"],
                manual_profile_control_text["load_missing_selection"],
            )
            return
        _show_selected_manual_profile_preset_metadata()
        _apply_manual_material_profile_values(_coerce_manual_profile_values(preset.get("values")), persist=True, refresh_preview=True)

    def _delete_selected_manual_profile_preset() -> None:
        preset = _selected_manual_profile_preset()
        if preset is None:
            QMessageBox.information(
                dialog,
                manual_profile_control_text["delete_title"],
                manual_profile_control_text["delete_missing_selection"],
            )
            return
        name = str(preset.get("name") or "").strip()
        answer = QMessageBox.question(
            dialog,
            manual_profile_control_text["delete_title"],
            _manual_material_profile_delete_question_helper(name),
        )
        if answer != QMessageBox.Yes:
            return
        manual_profile_presets[:] = _delete_manual_material_profile_preset_helper(manual_profile_presets, name)
        _save_manual_profile_presets(manual_profile_presets)
        _refresh_manual_profile_preset_combo("")

    def _current_complete_swap_material_profile_token() -> str:
        profile_name = str(complete_swap_material_profile_combo.currentData() or "material_authority_detail_mask")
        return _manual_material_profile_token_helper(
            profile_name,
            manual_token=serialize_complete_swap_manual_material_profile(
                _current_manual_material_profile_values()
            ),
        )

    def _refresh_manual_material_profile_panel() -> None:
        state = _manual_material_profile_panel_state_helper(
            complete_swap_material_profile_combo.currentData(),
            complete_enabled=_complete_external_swap_enabled(),
        )
        manual_profile_group.setVisible(bool(state["visible"]))
        manual_profile_group.setEnabled(bool(state["enabled"]))
        _refresh_manual_profile_control_effects()

    def _save_complete_swap_material_profile() -> None:
        profile_name = str(complete_swap_material_profile_combo.currentData() or "material_authority_detail_mask")
        self.settings.setValue("settings/complete_swap_material_profile", profile_name)
        if profile_name == "material_authority_manual":
            self.settings.setValue(
                manual_profile_settings_key,
                json.dumps(_current_manual_material_profile_values(), sort_keys=True, separators=(",", ":")),
            )
        try:
            write_complete_swap_calibrated_material_profile(
                complete_swap_profile_store_path,
                _current_complete_swap_material_profile_token(),
            )
        except Exception:
            pass

    return SimpleNamespace(_current_manual_material_profile_values=_current_manual_material_profile_values, _refresh_manual_profile_control_effects=_refresh_manual_profile_control_effects, _set_manual_profile_dirty=_set_manual_profile_dirty, _apply_manual_material_profile_values=_apply_manual_material_profile_values, _reset_manual_material_profile_to_material_authority=_reset_manual_material_profile_to_material_authority, _apply_current_manual_material_profile_to_preview=_apply_current_manual_material_profile_to_preview, _selected_manual_profile_preset=_selected_manual_profile_preset, _refresh_manual_profile_preset_combo=_refresh_manual_profile_preset_combo, _show_selected_manual_profile_preset_metadata=_show_selected_manual_profile_preset_metadata, _save_current_manual_profile_preset=_save_current_manual_profile_preset, _load_selected_manual_profile_preset=_load_selected_manual_profile_preset, _delete_selected_manual_profile_preset=_delete_selected_manual_profile_preset, _current_complete_swap_material_profile_token=_current_complete_swap_material_profile_token, _refresh_manual_material_profile_panel=_refresh_manual_material_profile_panel, _save_complete_swap_material_profile=_save_complete_swap_material_profile)

def create_alignment_custom_icon_callbacks(context: dict[str, object]) -> SimpleNamespace:
    ArchiveEntry = context.get('ArchiveEntry')
    CUSTOM_ITEM_ICON_NO_TARGET_EXPORT_MESSAGE = context.get('CUSTOM_ITEM_ICON_NO_TARGET_EXPORT_MESSAGE')
    ItemIconOverrideSpec = context.get('ItemIconOverrideSpec')
    NativePreviewPanel = context.get('NativePreviewPanel')
    Optional = context.get('Optional')
    Path = context.get('Path')
    QApplication = context.get('QApplication')
    QFileDialog = context.get('QFileDialog')
    QMessageBox = context.get('QMessageBox')
    QPixmap = context.get('QPixmap')
    QThread = context.get('QThread')
    _alignment_current_camera_state = context.get('_alignment_current_camera_state')
    _alignment_d3d11_preview_active = context.get('_alignment_d3d11_preview_active')
    _custom_item_icon_alignment_generated_path_helper = context.get('_custom_item_icon_alignment_generated_path_helper')
    _custom_item_icon_apply_control_enabled_state_helper = context.get('_custom_item_icon_apply_control_enabled_state_helper')
    _custom_item_icon_control_enabled_state_helper = context.get('_custom_item_icon_control_enabled_state_helper')
    _custom_item_icon_file_dialog_filter_helper = context.get('_custom_item_icon_file_dialog_filter_helper')
    _custom_item_icon_generated_apply_state_helper = context.get('_custom_item_icon_generated_apply_state_helper')
    _custom_item_icon_generated_status_helper = context.get('_custom_item_icon_generated_status_helper')
    _custom_item_icon_generation_status_message_helper = context.get('_custom_item_icon_generation_status_message_helper')
    _custom_item_icon_maybe_register_generated_icon_helper = context.get('_custom_item_icon_maybe_register_generated_icon_helper')
    _custom_item_icon_override_spec_helper = context.get('_custom_item_icon_override_spec_helper')
    _custom_item_icon_preview_image_from_pixmap_helper = context.get('_custom_item_icon_preview_image_from_pixmap_helper')
    _custom_item_icon_status_text_helper = context.get('_custom_item_icon_status_text_helper')
    _custom_item_icon_write_failure_message_helper = context.get('_custom_item_icon_write_failure_message_helper')
    _qt_alignment_camera_tuple_helper = context.get('_qt_alignment_camera_tuple_helper')
    _replay_alignment_d3d11_fast_transform = context.get('_replay_alignment_d3d11_fast_transform')
    _sync_highlight_sets = context.get('_sync_highlight_sets')
    _sync_mesh_edit_preview_settings = context.get('_sync_mesh_edit_preview_settings')
    alignment_d3d11_preview_host = context.get('alignment_d3d11_preview_host')
    custom_icon_checkbox = context.get('custom_icon_checkbox')
    custom_icon_control_text = context.get('custom_icon_control_text')
    custom_icon_file_button = context.get('custom_icon_file_button')
    custom_icon_folder_button = context.get('custom_icon_folder_button')
    custom_icon_library_button = context.get('custom_icon_library_button')
    custom_icon_source_edit = context.get('custom_icon_source_edit')
    custom_icon_status = context.get('custom_icon_status')
    custom_icon_target_combo = context.get('custom_icon_target_combo')
    custom_icon_target_entries = context.get('custom_icon_target_entries')
    custom_icon_target_graph = context.get('custom_icon_target_graph')
    dialog = context.get('dialog')
    entry = context.get('entry')
    obj_path = context.get('obj_path')
    overlay_dialog_preview = context.get('overlay_dialog_preview')
    preview_mode_combo = context.get('preview_mode_combo')
    replacement_only_preview = context.get('replacement_only_preview')
    save_generated_icon_to_library_checkbox = context.get('save_generated_icon_to_library_checkbox')
    self = context.get('self')
    static_dialog_preview = context.get('static_dialog_preview')

    def _alignment_custom_icon_override_spec(*, show_messages: bool) -> Optional[ItemIconOverrideSpec]:
        if not custom_icon_checkbox.isChecked():
            return None
        target_icon_entry = custom_icon_target_combo.currentData()
        if not isinstance(target_icon_entry, ArchiveEntry):
            if show_messages:
                QMessageBox.warning(
                    dialog,
                    custom_icon_control_text["warning_title"],
                    CUSTOM_ITEM_ICON_NO_TARGET_EXPORT_MESSAGE,
                )
            return None
        icon_spec, message = _custom_item_icon_override_spec_helper(
            source_text=custom_icon_source_edit.text(),
            target_entry=target_icon_entry,
            related_stems=self._archive_item_icon_related_stems(entry, custom_icon_target_graph),
            display_name=entry.basename,
        )
        if icon_spec is None:
            if show_messages:
                QMessageBox.warning(dialog, custom_icon_control_text["warning_title"], message)
            return None
        return icon_spec

    def _refresh_alignment_custom_icon_status() -> None:
        _custom_item_icon_apply_control_enabled_state_helper(
            _custom_item_icon_control_enabled_state_helper(
                checked=custom_icon_checkbox.isChecked(),
                has_target_entries=bool(custom_icon_target_entries),
            ),
            source_edit_widget=custom_icon_source_edit,
            file_button_widget=custom_icon_file_button,
            folder_button_widget=custom_icon_folder_button,
            library_button_widget=custom_icon_library_button,
            target_combo_widget=custom_icon_target_combo,
        )
        custom_icon_status.setText(
            _custom_item_icon_status_text_helper(
                checked=custom_icon_checkbox.isChecked(),
                target_entry=custom_icon_target_combo.currentData(),
                source_text=custom_icon_source_edit.text(),
                related_stems=self._archive_item_icon_related_stems(entry, custom_icon_target_graph),
                display_name=entry.basename,
            )
        )

    def _choose_alignment_custom_icon_file() -> None:
        selected, _selected_filter = QFileDialog.getOpenFileName(
            dialog,
            custom_icon_control_text["choose_file_title"],
            str(obj_path.parent if obj_path.parent.is_dir() else self.settings_file_path.parent),
            _custom_item_icon_file_dialog_filter_helper(),
        )
        if selected:
            custom_icon_source_edit.setText(selected)

    def _choose_alignment_custom_icon_folder() -> None:
        selected = QFileDialog.getExistingDirectory(
            dialog,
            custom_icon_control_text["choose_folder_title"],
            str(obj_path.parent if obj_path.parent.is_dir() else self.settings_file_path.parent),
        )
        if selected:
            custom_icon_source_edit.setText(selected)

    def _choose_alignment_custom_icon_library_source() -> None:
        selected = self._choose_item_icon_library_source(dialog)
        if selected is not None:
            custom_icon_source_edit.setText(str(selected))

    def _capture_alignment_replacement_icon_pixmap() -> Optional[QPixmap]:
        if _alignment_d3d11_preview_active():
            previous_mode = str(preview_mode_combo.currentData() or "side_by_side")
            previous_view_state = alignment_d3d11_preview_host.view_state_snapshot()
            capture_view_state = _alignment_current_camera_state()
            try:
                alignment_d3d11_preview_host.restore_view_state(capture_view_state)
                alignment_d3d11_preview_host.set_icon_capture_mode(True)
                alignment_d3d11_preview_host.set_display_mode("replacement_only")
                alignment_d3d11_preview_host.set_highlighted_alignment_submeshes(
                    replacement_submesh_indices=(),
                    original_submesh_indices=(),
                )
                alignment_d3d11_preview_host.set_hidden_source_submeshes(())
                alignment_d3d11_preview_host.set_alignment_state(
                    enabled=False,
                    source_submesh_indices=(),
                    translation_sensitivity=0.85,
                    rotation_degrees_per_pixel=0.18,
                )
                QApplication.processEvents()
                QThread.msleep(80)
                QApplication.processEvents()
                screen = alignment_d3d11_preview_host.screen() or dialog.screen() or QApplication.primaryScreen()
                if screen is None:
                    return None
                pixmap = screen.grabWindow(int(alignment_d3d11_preview_host.winId()))
                return pixmap if not pixmap.isNull() else None
            finally:
                alignment_d3d11_preview_host.set_icon_capture_mode(False)
                alignment_d3d11_preview_host.set_display_mode(previous_mode)
                alignment_d3d11_preview_host.restore_view_state(previous_view_state)
                _sync_highlight_sets()
                _sync_mesh_edit_preview_settings()
                try:
                    _replay_alignment_d3d11_fast_transform()
                except NameError:
                    pass
        preview_widget = replacement_only_preview
        capture_view_state = _alignment_current_camera_state()
        previous_replacement_view_state = replacement_only_preview.view_state_snapshot()
        previous_guides = (
            getattr(static_dialog_preview, "_show_grid_overlay", False),
            getattr(overlay_dialog_preview, "_show_grid_overlay", False),
            getattr(replacement_only_preview, "_show_grid_overlay", False),
        )
        previous_editing = (
            getattr(static_dialog_preview, "_alignment_editing_enabled", False),
            getattr(overlay_dialog_preview, "_alignment_editing_enabled", False),
            getattr(replacement_only_preview, "_alignment_editing_enabled", False),
        )
        try:
            preview_widget.restore_view_state(
                _qt_alignment_camera_tuple_helper(
                    capture_view_state,
                    fit_distance=NativePreviewPanel._FIT_DISTANCE,
                )
            )
            for widget in (static_dialog_preview, overlay_dialog_preview, replacement_only_preview):
                widget.set_alignment_guides_visible(False)
                widget.set_alignment_editing_enabled(False)
                widget.repaint()
            QApplication.processEvents()
            pixmap = preview_widget.grab()
            return pixmap if not pixmap.isNull() else None
        finally:
            replacement_only_preview.restore_view_state(previous_replacement_view_state)
            for widget, guides_visible, editing_enabled in zip(
                (static_dialog_preview, overlay_dialog_preview, replacement_only_preview),
                previous_guides,
                previous_editing,
            ):
                widget.set_alignment_guides_visible(bool(guides_visible))
                widget.set_alignment_editing_enabled(bool(editing_enabled))

    def _generate_alignment_icon_from_preview() -> None:
        pixmap = _capture_alignment_replacement_icon_pixmap()
        if pixmap is None or pixmap.isNull():
            QMessageBox.warning(
                dialog,
                custom_icon_control_text["generate_preview_warning_title"],
                custom_icon_control_text["generate_preview_not_ready"],
            )
            return
        output_path = _custom_item_icon_alignment_generated_path_helper(
            save_to_library=save_generated_icon_to_library_checkbox.isChecked(),
            item_icons_tab=getattr(self, "item_icons_tab", None),
            model_library_tab=getattr(self, "model_library_tab", None),
            target_model_path=str(getattr(entry, "path", "") or entry.basename),
            target_fallback_path=str(getattr(entry, "path", "") or obj_path.stem),
            source_model_path=str(obj_path),
            fallback_dir=Path.cwd(),
        )
        model_library = getattr(self, "model_library_tab", None)
        formatter = getattr(model_library, "_model_preview_icon_image", None)
        icon_image = _custom_item_icon_preview_image_from_pixmap_helper(pixmap, formatter=formatter, size=512)
        if not icon_image.save(str(output_path), "PNG"):
            QMessageBox.warning(
                dialog,
                custom_icon_control_text["generate_preview_warning_title"],
                _custom_item_icon_write_failure_message_helper(output_path),
            )
            return
        registration_result = _custom_item_icon_maybe_register_generated_icon_helper(
            save_to_library=save_generated_icon_to_library_checkbox.isChecked(),
            item_icons_tab=getattr(self, "item_icons_tab", None),
            output_path=output_path,
            target_model_path=str(getattr(entry, "path", "") or entry.basename),
            source_model_path=str(obj_path),
            target_icon_entry=custom_icon_target_combo.currentData(),
        )
        output_path = registration_result.output_path
        saved_to_library = registration_result.saved_to_library
        if registration_result.error_status:
            self.set_status_message(registration_result.error_status, error=True)
        custom_icon_source_edit.setText(str(output_path))
        generated_apply_state = _custom_item_icon_generated_apply_state_helper(
            has_target_entries=bool(custom_icon_target_entries),
            checkbox_enabled=custom_icon_checkbox.isEnabled(),
            current_target_entry=custom_icon_target_combo.currentData(),
        )
        if generated_apply_state["has_target"]:
            custom_icon_checkbox.setChecked(True)
            if generated_apply_state["select_first_target"]:
                custom_icon_target_combo.setCurrentIndex(0)
        _refresh_alignment_custom_icon_status()
        custom_icon_status.setText(
            _custom_item_icon_generated_status_helper(
                output_name=output_path.name,
                saved_to_library=saved_to_library,
                has_target=bool(generated_apply_state["has_target"]),
            )
        )
        self.set_status_message(_custom_item_icon_generation_status_message_helper(output_path))

    return SimpleNamespace(_alignment_custom_icon_override_spec=_alignment_custom_icon_override_spec, _refresh_alignment_custom_icon_status=_refresh_alignment_custom_icon_status, _choose_alignment_custom_icon_file=_choose_alignment_custom_icon_file, _choose_alignment_custom_icon_folder=_choose_alignment_custom_icon_folder, _choose_alignment_custom_icon_library_source=_choose_alignment_custom_icon_library_source, _capture_alignment_replacement_icon_pixmap=_capture_alignment_replacement_icon_pixmap, _generate_alignment_icon_from_preview=_generate_alignment_icon_from_preview)

def create_alignment_transform_drag_callbacks(context: dict[str, object]) -> SimpleNamespace:
    Dict = context.get('Dict')
    List = context.get('List')
    Mapping = context.get('Mapping')
    NativePreviewPanel = context.get('NativePreviewPanel')
    Optional = context.get('Optional')
    QDoubleSpinBox = context.get('QDoubleSpinBox')
    Sequence = context.get('Sequence')
    StaticReplacementTransform = context.get('StaticReplacementTransform')
    StaticSourcePartAdjustment = context.get('StaticSourcePartAdjustment')
    Tuple = context.get('Tuple')
    _add_vector3_delta_helper = context.get('_add_vector3_delta_helper')
    _alignment_d3d11_active_transform_preview_key_helper = context.get('_alignment_d3d11_active_transform_preview_key_helper')
    _alignment_d3d11_base_global_transform_helper = context.get('_alignment_d3d11_base_global_transform_helper')
    _alignment_d3d11_base_part_transform_helper = context.get('_alignment_d3d11_base_part_transform_helper')
    _alignment_d3d11_begin_drag_generation_helper = context.get('_alignment_d3d11_begin_drag_generation_helper')
    _alignment_d3d11_commit_drag_generation_helper = context.get('_alignment_d3d11_commit_drag_generation_helper')
    _alignment_d3d11_drag_part_source_indices_helper = context.get('_alignment_d3d11_drag_part_source_indices_helper')
    _alignment_d3d11_drag_transform_update_state_helper = context.get('_alignment_d3d11_drag_transform_update_state_helper')
    _alignment_d3d11_drag_ui_flush_state_helper = context.get('_alignment_d3d11_drag_ui_flush_state_helper')
    _alignment_d3d11_drag_ui_queue_global_helper = context.get('_alignment_d3d11_drag_ui_queue_global_helper')
    _alignment_d3d11_drag_ui_queue_part_helper = context.get('_alignment_d3d11_drag_ui_queue_part_helper')
    _alignment_d3d11_drag_ui_take_helper = context.get('_alignment_d3d11_drag_ui_take_helper')
    _alignment_d3d11_drag_ui_timer_state_helper = context.get('_alignment_d3d11_drag_ui_timer_state_helper')
    _alignment_d3d11_editor_ids_for_source_indices = context.get('_alignment_d3d11_editor_ids_for_source_indices')
    _alignment_d3d11_fast_transform_payload_helper = context.get('_alignment_d3d11_fast_transform_payload_helper')
    _alignment_d3d11_fast_transform_queue_state_helper = context.get('_alignment_d3d11_fast_transform_queue_state_helper')
    _alignment_d3d11_fast_transform_replay_state_helper = context.get('_alignment_d3d11_fast_transform_replay_state_helper')
    _alignment_d3d11_fast_transform_send_state_helper = context.get('_alignment_d3d11_fast_transform_send_state_helper')
    _alignment_d3d11_finish_drag_update_state_helper = context.get('_alignment_d3d11_finish_drag_update_state_helper')
    _alignment_d3d11_global_control_state_helper = context.get('_alignment_d3d11_global_control_state_helper')
    _alignment_d3d11_global_fast_preview_edit_range_helper = context.get('_alignment_d3d11_global_fast_preview_edit_range_helper')
    _alignment_d3d11_package_refresh_in_flight = context.get('_alignment_d3d11_package_refresh_in_flight')
    _alignment_d3d11_part_fast_preview_edit_indices_helper = context.get('_alignment_d3d11_part_fast_preview_edit_indices_helper')
    _alignment_d3d11_preview_active = context.get('_alignment_d3d11_preview_active')
    _alignment_d3d11_preview_scale_helper = context.get('_alignment_d3d11_preview_scale_helper')
    _alignment_d3d11_selected_part_control_state_helper = context.get('_alignment_d3d11_selected_part_control_state_helper')
    _alignment_d3d11_translation_to_transform_units_helper = context.get('_alignment_d3d11_translation_to_transform_units_helper')
    _alignment_geometry_tab_active = context.get('_alignment_geometry_tab_active')
    _alignment_global_fast_preview_state_helper = context.get('_alignment_global_fast_preview_state_helper')
    _alignment_global_rotation_origin_state_helper = context.get('_alignment_global_rotation_origin_state_helper')
    _alignment_global_transform_spin_commit_state_helper = context.get('_alignment_global_transform_spin_commit_state_helper')
    _alignment_linked_scale_sync_state_helper = context.get('_alignment_linked_scale_sync_state_helper')
    _alignment_part_delta_refresh_state_helper = context.get('_alignment_part_delta_refresh_state_helper')
    _alignment_part_fast_preview_state_helper = context.get('_alignment_part_fast_preview_state_helper')
    _alignment_part_transform_preview_queue_indices_helper = context.get('_alignment_part_transform_preview_queue_indices_helper')
    _alignment_preview_commit_state_helper = context.get('_alignment_preview_commit_state_helper')
    _alignment_preview_drag_prepare_state_helper = context.get('_alignment_preview_drag_prepare_state_helper')
    _alignment_preview_rotation_context_state_helper = context.get('_alignment_preview_rotation_context_state_helper')
    _alignment_rotation_nudge_value_helper = context.get('_alignment_rotation_nudge_value_helper')
    _alignment_transform_preview_queue_state_helper = context.get('_alignment_transform_preview_queue_state_helper')
    _alignment_transform_reset_state_helper = context.get('_alignment_transform_reset_state_helper')
    _capture_static_preview_baked_transform_state_helper = context.get('_capture_static_preview_baked_transform_state_helper')
    _clear_alignment_d3d11_fast_transform_state = context.get('_clear_alignment_d3d11_fast_transform_state')
    _commit_spinbox_text = context.get('_commit_spinbox_text')
    _compute_anchor_alignment = context.get('_compute_anchor_alignment')
    _current_alignment_transform_generation = context.get('_current_alignment_transform_generation')
    _ensure_source_part_adjustment = context.get('_ensure_source_part_adjustment')
    _load_selected_part_controls = context.get('_load_selected_part_controls')
    _mark_alignment_transform_changed = context.get('_mark_alignment_transform_changed')
    _mesh_edit_raw_preview_active = context.get('_mesh_edit_raw_preview_active')
    _part_source_indices_for_commit_helper = context.get('_part_source_indices_for_commit_helper')
    _push_geometry_undo_snapshot = context.get('_push_geometry_undo_snapshot')
    _queue_static_preview_rebuild = context.get('_queue_static_preview_rebuild')
    _refresh_source_assignment_columns = context.get('_refresh_source_assignment_columns')
    _run_static_preview_batch = context.get('_run_static_preview_batch')
    _safe_alignment_timer_active = context.get('_safe_alignment_timer_active')
    _safe_start_alignment_timer = context.get('_safe_start_alignment_timer')
    _safe_stop_alignment_timer = context.get('_safe_stop_alignment_timer')
    _set_double_spin_value_silently_helper = context.get('_set_double_spin_value_silently_helper')
    _single_part_source_index_for_preview_helper = context.get('_single_part_source_index_for_preview_helper')
    _source_part_transform_values_helper = context.get('_source_part_transform_values_helper')
    _spinbox_transform_values_helper = context.get('_spinbox_transform_values_helper')
    _sync_alignment_transform_slider_from_spin = context.get('_sync_alignment_transform_slider_from_spin')
    _sync_part_slider_from_spin = context.get('_sync_part_slider_from_spin')
    alignment_d3d11_drag_generation = context.get('alignment_d3d11_drag_generation')
    alignment_d3d11_drag_transaction = context.get('alignment_d3d11_drag_transaction') or {}
    alignment_d3d11_drag_ui_state = context.get('alignment_d3d11_drag_ui_state')
    alignment_d3d11_drag_ui_timer = context.get('alignment_d3d11_drag_ui_timer')
    alignment_d3d11_preview_host = context.get('alignment_d3d11_preview_host')
    alignment_d3d11_state = context.get('alignment_d3d11_state')
    alignment_mode_combo = context.get('alignment_mode_combo')
    alignment_transform_generation = context.get('alignment_transform_generation')
    dialog = context.get('dialog')
    flip_direction_checkbox = context.get('flip_direction_checkbox')
    material_edit_refresh_timer = context.get('material_edit_refresh_timer')
    modify_original_clone_mode = context.get('modify_original_clone_mode')
    offset_x_spin = context.get('offset_x_spin')
    offset_y_spin = context.get('offset_y_spin')
    offset_z_spin = context.get('offset_z_spin')
    original_mesh_for_mapping = context.get('original_mesh_for_mapping')
    original_reference_preview_model = context.get('original_reference_preview_model')
    overlay_dialog_preview = context.get('overlay_dialog_preview')
    part_offset_x_spin = context.get('part_offset_x_spin')
    part_offset_y_spin = context.get('part_offset_y_spin')
    part_offset_z_spin = context.get('part_offset_z_spin')
    part_rotate_x_spin = context.get('part_rotate_x_spin')
    part_rotate_y_spin = context.get('part_rotate_y_spin')
    part_rotate_z_spin = context.get('part_rotate_z_spin')
    preview_mode_combo = context.get('preview_mode_combo')
    replacement_mesh_base_for_mapping = context.get('replacement_mesh_base_for_mapping')
    replacement_mesh_for_mapping = context.get('replacement_mesh_for_mapping')
    replacement_only_preview = context.get('replacement_only_preview')
    rotate_x_spin = context.get('rotate_x_spin')
    rotate_y_spin = context.get('rotate_y_spin')
    rotate_z_spin = context.get('rotate_z_spin')
    scale_link_checkbox = context.get('scale_link_checkbox')
    scale_spins = context.get('scale_spins')
    scale_syncing = context.get('scale_syncing')
    scale_to_length_checkbox = context.get('scale_to_length_checkbox')
    scale_x_spin = context.get('scale_x_spin')
    scale_y_spin = context.get('scale_y_spin')
    scale_z_spin = context.get('scale_z_spin')
    selected_source_part = context.get('selected_source_part')
    source_material_plan_refresh_timer = context.get('source_material_plan_refresh_timer')
    source_part_adjustments = context.get('source_part_adjustments')
    static_dialog_preview = context.get('static_dialog_preview')
    static_preview_baked_transform_state = context.get('static_preview_baked_transform_state')
    static_preview_interactive_until = context.get('static_preview_interactive_until')
    static_preview_refresh_timer = context.get('static_preview_refresh_timer')
    static_preview_settle_timer = context.get('static_preview_settle_timer')
    tilt_step_spin = context.get('tilt_step_spin')
    time = context.get('time')
    transform_source_indices = context.get('transform_source_indices')

    def _sync_linked_scale(value: float, source_spin: Optional[QDoubleSpinBox] = None) -> None:
        sender = source_spin if source_spin is not None else dialog.sender()
        try:
            source_index = scale_spins.index(sender)
        except ValueError:
            source_index = -1
        sync_state = _alignment_linked_scale_sync_state_helper(
            syncing_active=scale_syncing["active"],
            link_enabled=scale_link_checkbox.isChecked(),
            value=value,
            source_index=source_index,
            scale_count=len(scale_spins),
        )
        if not bool(sync_state["apply"]):
            return
        scale_syncing["active"] = True
        try:
            for target_index in tuple(sync_state["target_indices"]):
                scale_spins[int(target_index)].setValue(float(sync_state["value"]))
        finally:
            scale_syncing["active"] = False

    def _commit_global_transform_spin(spin: QDoubleSpinBox) -> None:
        _commit_spinbox_text(spin)
        commit_state = _alignment_global_transform_spin_commit_state_helper(
            scale_spin=spin in scale_spins,
            d3d11_preview_active=_alignment_d3d11_preview_active(),
        )
        if bool(commit_state["sync_linked_scale"]):
            _sync_linked_scale(float(spin.value()), source_spin=spin)
        if bool(commit_state["queue_preview_update"]):
            _queue_global_transform_preview_update()
            return
        if bool(commit_state["queue_static_rebuild"]):
            _queue_static_preview_rebuild()

    _global_transform_values = lambda: _spinbox_transform_values_helper(
            (offset_x_spin, offset_y_spin, offset_z_spin),
            (rotate_x_spin, rotate_y_spin, rotate_z_spin),
            (scale_x_spin, scale_y_spin, scale_z_spin),
            catch_runtime=False,
        )

    _part_transform_values = lambda source_index: _source_part_transform_values_helper(
        source_part_adjustments,
        source_index,
        StaticSourcePartAdjustment,
    )

    def _capture_static_preview_baked_transform_state(
        selected_preview_indices: Optional[Sequence[int]] = None,
        *,
        transform_generation: Optional[int] = None,
    ) -> None:
        capture_generation = (
            int(transform_generation)
            if transform_generation is not None
            else _current_alignment_transform_generation()
        )
        part_state: Dict[int, object] = {}
        if replacement_mesh_for_mapping is not None:
            for source_index in range(len(getattr(replacement_mesh_for_mapping, "submeshes", ()) or ())):
                part_state[source_index] = _part_transform_values(source_index)
        _capture_static_preview_baked_transform_state_helper(
            static_preview_baked_transform_state,
            global_values=_global_transform_values(),
            part_values=part_state,
            selected_preview_indices=selected_preview_indices,
            transform_generation=capture_generation,
        )
        committed_generation = int(alignment_transform_generation.get("committed", 0) or 0)
        if not bool(alignment_d3d11_drag_transaction.get("active")) and capture_generation >= committed_generation:
            if not _alignment_d3d11_package_refresh_in_flight():
                _clear_alignment_d3d11_fast_transform_state()

    def _active_alignment_transform_preview_widgets() -> tuple[NativePreviewPanel, ...]:
        preview_key = _alignment_d3d11_active_transform_preview_key_helper(preview_mode_combo.currentData())
        if preview_key == "replacement_only":
            return (replacement_only_preview,)
        if preview_key == "overlay":
            return (overlay_dialog_preview,)
        return (static_dialog_preview,)

    def _set_global_fast_preview_edit_scope(preview_widget: NativePreviewPanel) -> None:
        active_mode = str(preview_mode_combo.currentData() or "side_by_side")
        current_model = getattr(preview_widget, "_current_model", None)
        current_mesh_count = len(getattr(current_model, "meshes", ()) or ())
        original_mesh_count = (
            len(getattr(original_reference_preview_model, "meshes", ()) or ())
            if original_reference_preview_model is not None
            else None
        )
        start, count = _alignment_d3d11_global_fast_preview_edit_range_helper(
            active_mode,
            original_mesh_count=original_mesh_count,
            current_mesh_count=current_mesh_count,
        )
        preview_widget.set_alignment_editable_mesh_range(start, count)

    def _set_part_fast_preview_edit_scope(preview_widget: NativePreviewPanel) -> None:
        selected_indices = static_preview_baked_transform_state.get("selected_preview_indices")
        active_mode = str(preview_mode_combo.currentData() or "side_by_side")
        original_mesh_count = (
            len(getattr(original_reference_preview_model, "meshes", ()) or ())
            if original_reference_preview_model is not None
            else None
        )
        editable_indices = _alignment_d3d11_part_fast_preview_edit_indices_helper(
            selected_indices,
            active_mode,
            original_mesh_count=original_mesh_count,
        )
        if editable_indices is None:
            return
        preview_widget.set_alignment_editable_mesh_indices(editable_indices)

    def _queue_alignment_d3d11_fast_transform(
        *,
        source_submesh_indices: Sequence[int] = (),
        translation: Sequence[float] = (0.0, 0.0, 0.0),
        rotation_degrees: Sequence[float] = (0.0, 0.0, 0.0),
        scale_xyz: Sequence[float] = (1.0, 1.0, 1.0),
    ) -> bool:
        transform_generation = (
            _current_alignment_transform_generation()
            if callable(_current_alignment_transform_generation)
            else 0
        )
        payload = _alignment_d3d11_fast_transform_payload_helper(
            source_submesh_indices=source_submesh_indices,
            translation=translation,
            rotation_degrees=rotation_degrees,
            scale_xyz=scale_xyz,
            transform_generation=transform_generation,
        )
        preview_active = (
            _alignment_d3d11_preview_active()
            if callable(_alignment_d3d11_preview_active)
            else False
        )
        queue_state = _alignment_d3d11_fast_transform_queue_state_helper(
            alignment_d3d11_state,
            payload,
            preview_active=preview_active,
            drag_active=bool(alignment_d3d11_drag_transaction.get("active")),
        )
        if not bool(queue_state["send_preview"]):
            return False
        return _send_alignment_d3d11_fast_transform_state(
            scope_source_indices=tuple(queue_state["source_indices"])
        )

    def _send_alignment_d3d11_fast_transform_state(
        *,
        scope_source_indices: Optional[Sequence[int]] = None,
    ) -> bool:
        send_state = _alignment_d3d11_fast_transform_send_state_helper(
            alignment_d3d11_state,
            _alignment_d3d11_editor_ids_for_source_indices,
            scope_source_indices=scope_source_indices,
        )
        state_ok = True
        if bool(send_state["update_scope"]):
            state_ok = alignment_d3d11_preview_host.set_alignment_state(
                enabled=True,
                source_submesh_indices=tuple(send_state["scope_source_indices"]),
                translation_sensitivity=0.85,
                rotation_degrees_per_pixel=0.18,
            )
        transform_ok = alignment_d3d11_preview_host.set_alignment_preview_transforms(
            translation=send_state["translation"],
            rotation_degrees=send_state["rotation_degrees"],
            scale_xyz=send_state["scale_xyz"],
            part_transforms=send_state["part_transforms"],
        )
        return bool(state_ok and transform_ok)

    def _replay_alignment_d3d11_fast_transform() -> None:
        replay_state = _alignment_d3d11_fast_transform_replay_state_helper(
            alignment_d3d11_state,
            mesh_edit_raw_active=_mesh_edit_raw_preview_active(),
            preview_active=_alignment_d3d11_preview_active(),
        )
        if bool(replay_state["clear_state"]):
            _clear_alignment_d3d11_fast_transform_state()
            if bool(replay_state["reset_host"]):
                alignment_d3d11_preview_host.set_alignment_state(
                    enabled=False,
                    source_submesh_indices=(),
                    translation_sensitivity=0.85,
                    rotation_degrees_per_pixel=0.18,
                )
                alignment_d3d11_preview_host.set_alignment_preview_transform()
            return
        if not bool(replay_state["send_preview"]):
            return
        _send_alignment_d3d11_fast_transform_state()

    def _apply_global_transform_fast_preview() -> bool:
        baked = static_preview_baked_transform_state.get("global")
        preview_scale = _alignment_d3d11_preview_scale_helper(original_reference_preview_model)
        fast_preview_state = _alignment_global_fast_preview_state_helper(
            baked,
            _global_transform_values(),
            preview_scale=preview_scale,
            d3d11_active=_alignment_d3d11_preview_active(),
            drag_active=bool(alignment_d3d11_drag_transaction.get("active")),
        )
        if not bool(fast_preview_state["apply"]):
            return False
        for preview_widget in _active_alignment_transform_preview_widgets():
            _set_global_fast_preview_edit_scope(preview_widget)
            base_rotation = tuple(fast_preview_state["base_rotation"])
            preview_widget.set_alignment_base_rotation_degrees(
                float(base_rotation[0]),
                float(base_rotation[1]),
                float(base_rotation[2]),
            )
            preview_widget.set_alignment_rotation_origin_override(_current_global_rotation_origin_for_preview())
            preview_widget.set_alignment_committed_preview_transform(
                translation=fast_preview_state["translation"],
                rotation_degrees=fast_preview_state["rotation_degrees"],
                scale_xyz=fast_preview_state["scale_xyz"],
            )
        if bool(fast_preview_state["queue_d3d11"]):
            _queue_alignment_d3d11_fast_transform(
                source_submesh_indices=tuple(fast_preview_state["source_submesh_indices"]),
                translation=fast_preview_state["translation"],
                rotation_degrees=fast_preview_state["rotation_degrees"],
                scale_xyz=fast_preview_state["scale_xyz"],
            )
        return True

    def _apply_part_transform_fast_preview(source_index: int) -> bool:
        parts = static_preview_baked_transform_state.get("parts")
        baked = parts.get(source_index) if isinstance(parts, dict) else None
        preview_scale = _alignment_d3d11_preview_scale_helper(original_reference_preview_model)
        fast_preview_state = _alignment_part_fast_preview_state_helper(
            int(source_index),
            baked,
            _part_transform_values(source_index),
            preview_scale=preview_scale,
            d3d11_active=_alignment_d3d11_preview_active(),
            drag_active=bool(alignment_d3d11_drag_transaction.get("active")),
        )
        if not bool(fast_preview_state["apply"]):
            return False
        for preview_widget in _active_alignment_transform_preview_widgets():
            _set_part_fast_preview_edit_scope(preview_widget)
            base_rotation = tuple(fast_preview_state["base_rotation"])
            preview_widget.set_alignment_base_rotation_degrees(
                float(base_rotation[0]),
                float(base_rotation[1]),
                float(base_rotation[2]),
            )
            preview_widget.set_alignment_rotation_origin_override(fast_preview_state["origin_override"])
            preview_widget.set_alignment_committed_preview_transform(
                translation=fast_preview_state["translation"],
                rotation_degrees=fast_preview_state["rotation_degrees"],
                scale_xyz=fast_preview_state["scale_xyz"],
            )
        if bool(fast_preview_state["queue_d3d11"]):
            _queue_alignment_d3d11_fast_transform(
                source_submesh_indices=tuple(fast_preview_state["source_submesh_indices"]),
                translation=fast_preview_state["translation"],
                rotation_degrees=fast_preview_state["rotation_degrees"],
                scale_xyz=fast_preview_state["scale_xyz"],
            )
        return True

    def _queue_global_transform_preview_update(*_args: object) -> None:
        _mark_alignment_transform_changed()
        queue_time = time.monotonic()
        applied = _apply_global_transform_fast_preview()
        preview_queue_state = _alignment_transform_preview_queue_state_helper(
            now=queue_time,
            applied=applied,
        )
        static_preview_interactive_until["time"] = float(preview_queue_state["interactive_until"])
        if bool(preview_queue_state["start_timer"]):
            static_preview_refresh_timer.start()

    def _queue_part_transform_preview_update(source_index: object) -> None:
        _mark_alignment_transform_changed()
        queue_time = time.monotonic()
        source_indices = _alignment_part_transform_preview_queue_indices_helper(source_index)
        applied = False
        for index in source_indices:
            applied = bool(_apply_part_transform_fast_preview(int(index))) or applied
        preview_queue_state = _alignment_transform_preview_queue_state_helper(
            now=queue_time,
            applied=applied,
        )
        static_preview_interactive_until["time"] = float(preview_queue_state["interactive_until"])
        if bool(preview_queue_state["start_timer"]):
            static_preview_refresh_timer.start()

    for spin in (
        offset_x_spin,
        offset_y_spin,
        offset_z_spin,
        rotate_x_spin,
        rotate_y_spin,
        rotate_z_spin,
        scale_x_spin,
        scale_y_spin,
        scale_z_spin,
    ):
        spin.valueChanged.connect(_queue_global_transform_preview_update)
        spin.editingFinished.connect(lambda spin=spin: _commit_global_transform_spin(spin))
    for spin in (scale_x_spin, scale_y_spin, scale_z_spin):
        spin.valueChanged.connect(_sync_linked_scale)
    alignment_mode_combo.currentIndexChanged.connect(_queue_static_preview_rebuild)
    scale_to_length_checkbox.toggled.connect(_queue_static_preview_rebuild)
    flip_direction_checkbox.toggled.connect(_queue_static_preview_rebuild)
    if modify_original_clone_mode:
        alignment_mode_combo.setCurrentIndex(max(0, alignment_mode_combo.findData("manual")))
        scale_to_length_checkbox.setChecked(False)
        flip_direction_checkbox.setChecked(False)

    def _apply_alignment_transform_reset_state(reset_state: Mapping[str, object]) -> None:
        alignment_mode = reset_state.get("alignment_mode")
        if isinstance(alignment_mode, str):
            alignment_mode_combo.setCurrentIndex(max(0, alignment_mode_combo.findData(alignment_mode)))
        scale_to_length = reset_state.get("scale_to_length")
        if isinstance(scale_to_length, bool):
            scale_to_length_checkbox.setChecked(scale_to_length)
        flip_direction = reset_state.get("flip_direction")
        if isinstance(flip_direction, bool):
            flip_direction_checkbox.setChecked(flip_direction)
        scale_link = reset_state.get("scale_link")
        if isinstance(scale_link, bool):
            scale_link_checkbox.setChecked(scale_link)
        offset = reset_state.get("offset")
        if isinstance(offset, tuple):
            for spin, value in zip((offset_x_spin, offset_y_spin, offset_z_spin), offset):
                spin.setValue(float(value))
        rotation = reset_state.get("rotation")
        if isinstance(rotation, tuple):
            for spin, value in zip((rotate_x_spin, rotate_y_spin, rotate_z_spin), rotation):
                spin.setValue(float(value))
        scale = reset_state.get("scale")
        if isinstance(scale, tuple):
            for spin, value in zip((scale_x_spin, scale_y_spin, scale_z_spin), scale):
                spin.setValue(float(value))

    def _reset_location_values() -> None:
        def _apply() -> None:
            reset_state = _alignment_transform_reset_state_helper("location")
            _apply_alignment_transform_reset_state(reset_state)
            if bool(reset_state["queue_rebuild"]):
                _queue_static_preview_rebuild()

        _run_static_preview_batch(_apply)

    def _reset_rotation_values() -> None:
        def _apply() -> None:
            reset_state = _alignment_transform_reset_state_helper("rotation")
            _apply_alignment_transform_reset_state(reset_state)
            if bool(reset_state["queue_rebuild"]):
                _queue_static_preview_rebuild()

        _run_static_preview_batch(_apply)

    def _reset_scale_values() -> None:
        def _apply() -> None:
            reset_state = _alignment_transform_reset_state_helper("scale")
            _apply_alignment_transform_reset_state(reset_state)
            if bool(reset_state["queue_rebuild"]):
                _queue_static_preview_rebuild()

        _run_static_preview_batch(_apply)

    def _reset_placement_values() -> None:
        def _apply() -> None:
            reset_state = _alignment_transform_reset_state_helper(
                "placement",
                modify_original_clone_mode=modify_original_clone_mode,
            )
            _apply_alignment_transform_reset_state(reset_state)
            if bool(reset_state["queue_rebuild"]):
                _queue_static_preview_rebuild()

        _run_static_preview_batch(_apply)

    def _nudge_rotation(spin: QDoubleSpinBox, direction: float) -> None:
        spin.setValue(
            _alignment_rotation_nudge_value_helper(
                spin.value(),
                direction,
                tilt_step_spin.value(),
            )
        )

    def _current_global_rotation_origin_for_preview() -> Optional[Tuple[float, float, float]]:
        if original_reference_preview_model is None or original_mesh_for_mapping is None:
            return None
        preview_replacement_mesh = replacement_mesh_for_mapping or replacement_mesh_base_for_mapping
        if preview_replacement_mesh is None:
            return None
        try:
            alignment = _compute_anchor_alignment(
                original_mesh_for_mapping,
                preview_replacement_mesh,
                StaticReplacementTransform(
                    scale_to_original_length=bool(scale_to_length_checkbox.isChecked()),
                    alignment_mode=str(alignment_mode_combo.currentData() or "grid_flat"),
                    flip_target_axis=bool(flip_direction_checkbox.isChecked()),
                ),
            )
            offset = (
                float(offset_x_spin.value()),
                float(offset_y_spin.value()),
                float(offset_z_spin.value()),
            )
            center = tuple(
                getattr(original_reference_preview_model, "normalization_center", (0.0, 0.0, 0.0))
                or (0.0, 0.0, 0.0)
            )
            while len(center) < 3:
                center = (*center, 0.0)
            return _alignment_global_rotation_origin_state_helper(
                alignment,
                offset_xyz=offset,
                normalization_center=center,
                normalization_scale=getattr(original_reference_preview_model, "normalization_scale", 1.0),
            )
        except Exception:
            return None

    def _alignment_part_source_indices_for_commit() -> List[int]:
        if not callable(_part_source_indices_for_commit_helper):
            return []
        geometry_tab_active = (
            _alignment_geometry_tab_active()
            if callable(_alignment_geometry_tab_active)
            else False
        )
        return list(
            _part_source_indices_for_commit_helper(
                transform_source_indices,
                replacement_mesh_for_mapping,
                geometry_tab_active=geometry_tab_active,
            )
        )

    _alignment_single_part_source_index_for_preview = (
        lambda: _single_part_source_index_for_preview_helper(_alignment_part_source_indices_for_commit())
    )

    def _apply_alignment_part_translation_delta(source_indices: Sequence[int], delta_xyz: Sequence[float]) -> None:
        for source_index in source_indices:
            adjustment = _ensure_source_part_adjustment(int(source_index))
            adjustment.offset_xyz = _add_vector3_delta_helper(adjustment.offset_xyz or (0.0, 0.0, 0.0), delta_xyz)
        refresh_state = _alignment_part_delta_refresh_state_helper(
            selected_source_part.get("index", -1),
            source_indices,
        )
        if bool(refresh_state["reload_selected_controls"]):
            _load_selected_part_controls()
        if bool(refresh_state["refresh_source_columns"]):
            _refresh_source_assignment_columns(lightweight=True)
        if bool(refresh_state["queue_part_preview"]):
            _queue_part_transform_preview_update(tuple(refresh_state["source_indices"]))

    def _apply_alignment_part_rotation_delta(source_indices: Sequence[int], delta_xyz: Sequence[float]) -> None:
        for source_index in source_indices:
            adjustment = _ensure_source_part_adjustment(int(source_index))
            adjustment.rotate_xyz_degrees = _add_vector3_delta_helper(
                adjustment.rotate_xyz_degrees or (0.0, 0.0, 0.0),
                delta_xyz,
            )
        refresh_state = _alignment_part_delta_refresh_state_helper(
            selected_source_part.get("index", -1),
            source_indices,
        )
        if bool(refresh_state["reload_selected_controls"]):
            _load_selected_part_controls()
        if bool(refresh_state["refresh_source_columns"]):
            _refresh_source_assignment_columns(lightweight=True)
        if bool(refresh_state["queue_part_preview"]):
            _queue_part_transform_preview_update(tuple(refresh_state["source_indices"]))

    def _sync_alignment_preview_rotation_context(preview_widget: NativePreviewPanel) -> None:
        selected_index = _alignment_single_part_source_index_for_preview()
        part_rotation: tuple[float, float, float] = (0.0, 0.0, 0.0)
        if selected_index >= 0:
            adjustment = source_part_adjustments.get(selected_index, StaticSourcePartAdjustment(selected_index))
            part_rotation = tuple(
                float(value)
                for value in tuple(adjustment.rotate_xyz_degrees or (0.0, 0.0, 0.0))[:3]
            )
        rotation_state = _alignment_preview_rotation_context_state_helper(
            selected_index,
            part_rotation=part_rotation,
            global_rotation=(
                float(rotate_x_spin.value()),
                float(rotate_y_spin.value()),
                float(rotate_z_spin.value()),
            ),
            global_origin=_current_global_rotation_origin_for_preview(),
        )
        rotation = rotation_state["base_rotation"]
        if isinstance(rotation, tuple):
            preview_widget.set_alignment_base_rotation_degrees(rotation[0], rotation[1], rotation[2])
        preview_widget.set_alignment_rotation_origin_override(rotation_state["origin_override"])

    def _prepare_alignment_preview_drag(preview_widget: NativePreviewPanel) -> None:
        _safe_stop_alignment_timer(material_edit_refresh_timer)
        _safe_stop_alignment_timer(source_material_plan_refresh_timer)
        _safe_stop_alignment_timer(static_preview_refresh_timer)
        _safe_stop_alignment_timer(static_preview_settle_timer)
        prepare_state = _alignment_preview_drag_prepare_state_helper(
            _alignment_part_source_indices_for_commit(),
            undo_label="Preview part drag",
        )
        if bool(prepare_state["push_undo"]):
            _push_geometry_undo_snapshot(str(prepare_state["undo_label"]))
        _sync_alignment_preview_rotation_context(preview_widget)

    def _prepare_alignment_d3d11_preview_drag() -> None:
        _safe_stop_alignment_timer(material_edit_refresh_timer)
        _safe_stop_alignment_timer(source_material_plan_refresh_timer)
        _safe_stop_alignment_timer(static_preview_refresh_timer)
        _safe_stop_alignment_timer(static_preview_settle_timer)
        _safe_stop_alignment_timer(alignment_d3d11_drag_ui_timer)
        _flush_alignment_d3d11_drag_ui()
        prepare_state = _alignment_preview_drag_prepare_state_helper(
            _alignment_part_source_indices_for_commit(),
            undo_label="D3D11 part drag",
        )
        part_source_indices = tuple(prepare_state["part_source_indices"])
        if bool(prepare_state["push_undo"]):
            _push_geometry_undo_snapshot(str(prepare_state["undo_label"]))
        _alignment_d3d11_begin_drag_generation_helper(
            alignment_d3d11_drag_generation,
            alignment_d3d11_drag_transaction,
            part_source_indices=part_source_indices,
            global_values=_global_transform_values(),
            part_values_by_source_index={
                int(source_index): _part_transform_values(int(source_index))
                for source_index in part_source_indices
            },
        )

    def _commit_alignment_d3d11_drag_generation() -> None:
        _alignment_d3d11_commit_drag_generation_helper(
            alignment_d3d11_drag_generation,
            alignment_d3d11_drag_transaction,
        )

    def _set_global_transform_values_for_d3d11_drag(
        *,
        offset: Optional[Sequence[float]] = None,
        rotation: Optional[Sequence[float]] = None,
    ) -> None:
        control_state = _alignment_d3d11_global_control_state_helper(
            offset=offset,
            rotation=rotation,
        )
        if not bool(control_state["apply"]):
            return
        normalized_offset = control_state["offset"]
        if isinstance(normalized_offset, tuple):
            for spin, value in zip((offset_x_spin, offset_y_spin, offset_z_spin), normalized_offset):
                _set_double_spin_value_silently_helper(spin, float(value))
                _sync_alignment_transform_slider_from_spin(spin)
        normalized_rotation = control_state["rotation"]
        if isinstance(normalized_rotation, tuple):
            for spin, value in zip((rotate_x_spin, rotate_y_spin, rotate_z_spin), normalized_rotation):
                _set_double_spin_value_silently_helper(spin, float(value))
                _sync_alignment_transform_slider_from_spin(spin)

    def _queue_global_transform_values_for_d3d11_drag(
        *,
        offset: Optional[Sequence[float]] = None,
        rotation: Optional[Sequence[float]] = None,
    ) -> None:
        _alignment_d3d11_drag_ui_queue_global_helper(
            alignment_d3d11_drag_ui_state,
            offset=offset,
            rotation=rotation,
        )
        timer_state = _alignment_d3d11_drag_ui_timer_state_helper(
            active=_safe_alignment_timer_active(alignment_d3d11_drag_ui_timer)
        )
        if bool(timer_state["start_timer"]):
            _safe_start_alignment_timer(alignment_d3d11_drag_ui_timer)

    def _set_selected_part_controls_for_d3d11_drag(
        source_index: int,
        *,
        offset: Optional[Sequence[float]] = None,
        rotation: Optional[Sequence[float]] = None,
    ) -> None:
        control_state = _alignment_d3d11_selected_part_control_state_helper(
            selected_source_part.get("index", -1),
            source_index,
            offset=offset,
            rotation=rotation,
        )
        if not bool(control_state["apply"]):
            return
        normalized_offset = control_state["offset"]
        if isinstance(normalized_offset, tuple):
            for spin, value in zip((part_offset_x_spin, part_offset_y_spin, part_offset_z_spin), normalized_offset):
                _set_double_spin_value_silently_helper(spin, float(value))
                _sync_part_slider_from_spin(spin)
        normalized_rotation = control_state["rotation"]
        if isinstance(normalized_rotation, tuple):
            for spin, value in zip((part_rotate_x_spin, part_rotate_y_spin, part_rotate_z_spin), normalized_rotation):
                _set_double_spin_value_silently_helper(spin, float(value))
                _sync_part_slider_from_spin(spin)

    def _queue_selected_part_controls_for_d3d11_drag(
        source_index: int,
        *,
        offset: Optional[Sequence[float]] = None,
        rotation: Optional[Sequence[float]] = None,
    ) -> None:
        _alignment_d3d11_drag_ui_queue_part_helper(
            alignment_d3d11_drag_ui_state,
            source_index,
            offset=offset,
            rotation=rotation,
        )
        timer_state = _alignment_d3d11_drag_ui_timer_state_helper(
            active=_safe_alignment_timer_active(alignment_d3d11_drag_ui_timer)
        )
        if bool(timer_state["start_timer"]):
            _safe_start_alignment_timer(alignment_d3d11_drag_ui_timer)

    def _flush_alignment_d3d11_drag_ui() -> None:
        global_offset, global_rotation, controls = _alignment_d3d11_drag_ui_take_helper(
            alignment_d3d11_drag_ui_state
        )
        flush_state = _alignment_d3d11_drag_ui_flush_state_helper(
            global_offset,
            global_rotation,
            controls,
        )
        global_control = flush_state["global"]
        if isinstance(global_control, Mapping) and bool(global_control["apply"]):
            _set_global_transform_values_for_d3d11_drag(
                offset=global_control["offset"] if isinstance(global_control["offset"], tuple) else None,
                rotation=global_control["rotation"] if isinstance(global_control["rotation"], tuple) else None,
            )
        for values in tuple(flush_state["parts"]):
            if isinstance(values, Mapping):
                _set_selected_part_controls_for_d3d11_drag(
                    int(values["source_index"]),
                    offset=values["offset"] if isinstance(values["offset"], tuple) else None,
                    rotation=values["rotation"] if isinstance(values["rotation"], tuple) else None,
                )

    alignment_d3d11_drag_ui_timer.timeout.connect(_flush_alignment_d3d11_drag_ui)

    _alignment_d3d11_base_global_transform = lambda: _alignment_d3d11_base_global_transform_helper(
            alignment_d3d11_drag_transaction,
            _global_transform_values(),
        )

    _alignment_d3d11_base_part_transform = lambda source_index: _alignment_d3d11_base_part_transform_helper(
            alignment_d3d11_drag_transaction,
            int(source_index),
            _part_transform_values(int(source_index)),
        )

    def _alignment_d3d11_translation_to_transform_units(
        dx: float,
        dy: float,
        dz: float,
    ) -> tuple[float, float, float]:
        preview_scale = _alignment_d3d11_preview_scale_helper(original_reference_preview_model)
        return _alignment_d3d11_translation_to_transform_units_helper(
            (dx, dy, dz),
            preview_scale=preview_scale,
        )

    def _apply_alignment_d3d11_translation_total(dx: float, dy: float, dz: float) -> None:
        static_preview_refresh_timer.stop()
        delta = _alignment_d3d11_translation_to_transform_units(dx, dy, dz)
        part_source_indices = _alignment_d3d11_drag_part_source_indices_helper(alignment_d3d11_drag_transaction)
        if part_source_indices:
            update_state = _alignment_d3d11_drag_transform_update_state_helper(
                part_source_indices=part_source_indices,
                delta_xyz=delta,
                value_index=0,
                part_transform_values={
                    int(source_index): _alignment_d3d11_base_part_transform(source_index)
                    for source_index in part_source_indices
                },
            )
            for source_index, new_offset in dict(update_state["part_values"]).items():
                adjustment = _ensure_source_part_adjustment(int(source_index))
                adjustment.offset_xyz = new_offset
                _queue_selected_part_controls_for_d3d11_drag(int(source_index), offset=new_offset)
            return
        base_offset, _base_rotation, _base_scale = _alignment_d3d11_base_global_transform()
        update_state = _alignment_d3d11_drag_transform_update_state_helper(
            part_source_indices=(),
            delta_xyz=delta,
            value_index=0,
            global_base_values=base_offset,
        )
        global_value = update_state["global_value"]
        if isinstance(global_value, tuple):
            _queue_global_transform_values_for_d3d11_drag(offset=global_value)

    def _apply_alignment_d3d11_rotation_total(dx: float, dy: float, dz: float) -> None:
        static_preview_refresh_timer.stop()
        delta = (float(dx), float(dy), float(dz))
        part_source_indices = _alignment_d3d11_drag_part_source_indices_helper(alignment_d3d11_drag_transaction)
        if part_source_indices:
            update_state = _alignment_d3d11_drag_transform_update_state_helper(
                part_source_indices=part_source_indices,
                delta_xyz=delta,
                value_index=1,
                part_transform_values={
                    int(source_index): _alignment_d3d11_base_part_transform(source_index)
                    for source_index in part_source_indices
                },
            )
            for source_index, new_rotation in dict(update_state["part_values"]).items():
                adjustment = _ensure_source_part_adjustment(int(source_index))
                adjustment.rotate_xyz_degrees = new_rotation
                _queue_selected_part_controls_for_d3d11_drag(int(source_index), rotation=new_rotation)
            return
        _base_offset, base_rotation, _base_scale = _alignment_d3d11_base_global_transform()
        update_state = _alignment_d3d11_drag_transform_update_state_helper(
            part_source_indices=(),
            delta_xyz=delta,
            value_index=1,
            global_base_values=base_rotation,
        )
        global_value = update_state["global_value"]
        if isinstance(global_value, tuple):
            _queue_global_transform_values_for_d3d11_drag(rotation=global_value)

    def _finish_alignment_d3d11_translation(dx: float, dy: float, dz: float) -> None:
        _apply_alignment_d3d11_translation_total(dx, dy, dz)
        _safe_stop_alignment_timer(alignment_d3d11_drag_ui_timer)
        _flush_alignment_d3d11_drag_ui()
        finish_state = _alignment_d3d11_finish_drag_update_state_helper(
            alignment_d3d11_drag_generation,
            alignment_d3d11_drag_transaction,
        )
        if bool(finish_state["refresh_source_columns"]):
            _refresh_source_assignment_columns(lightweight=True)
        if bool(finish_state["queue_part_preview"]):
            _queue_part_transform_preview_update(tuple(finish_state["part_source_indices"]))
        if bool(finish_state["queue_global_preview"]):
            _queue_global_transform_preview_update()
        _replay_alignment_d3d11_fast_transform()

    def _finish_alignment_d3d11_rotation(dx: float, dy: float, dz: float) -> None:
        _apply_alignment_d3d11_rotation_total(dx, dy, dz)
        _safe_stop_alignment_timer(alignment_d3d11_drag_ui_timer)
        _flush_alignment_d3d11_drag_ui()
        finish_state = _alignment_d3d11_finish_drag_update_state_helper(
            alignment_d3d11_drag_generation,
            alignment_d3d11_drag_transaction,
        )
        if bool(finish_state["refresh_source_columns"]):
            _refresh_source_assignment_columns(lightweight=True)
        if bool(finish_state["queue_part_preview"]):
            _queue_part_transform_preview_update(tuple(finish_state["part_source_indices"]))
        if bool(finish_state["queue_global_preview"]):
            _queue_global_transform_preview_update()
        _replay_alignment_d3d11_fast_transform()

    def _commit_alignment_preview_translation(dx: float, dy: float, dz: float) -> None:
        static_preview_refresh_timer.stop()
        commit_state = _alignment_preview_commit_state_helper(
            _alignment_part_source_indices_for_commit(),
            current_values=(
                float(offset_x_spin.value()),
                float(offset_y_spin.value()),
                float(offset_z_spin.value()),
            ),
            delta_xyz=(dx, dy, dz),
        )
        if commit_state["scope"] == "parts":
            _apply_alignment_part_translation_delta(
                tuple(commit_state["part_source_indices"]),
                (dx, dy, dz),
            )
            return
        global_values = commit_state["global_values"]
        if isinstance(global_values, tuple):
            for spin, value in zip((offset_x_spin, offset_y_spin, offset_z_spin), global_values):
                _set_double_spin_value_silently_helper(spin, float(value))
                _sync_alignment_transform_slider_from_spin(spin)
        _queue_global_transform_preview_update()

    def _commit_alignment_preview_rotation(dx: float, dy: float, dz: float) -> None:
        static_preview_refresh_timer.stop()
        commit_state = _alignment_preview_commit_state_helper(
            _alignment_part_source_indices_for_commit(),
            current_values=(
                float(rotate_x_spin.value()),
                float(rotate_y_spin.value()),
                float(rotate_z_spin.value()),
            ),
            delta_xyz=(dx, dy, dz),
        )
        if commit_state["scope"] == "parts":
            _apply_alignment_part_rotation_delta(
                tuple(commit_state["part_source_indices"]),
                (dx, dy, dz),
            )
            return
        global_values = commit_state["global_values"]
        if isinstance(global_values, tuple):
            for spin, value in zip((rotate_x_spin, rotate_y_spin, rotate_z_spin), global_values):
                _set_double_spin_value_silently_helper(spin, float(value))
                _sync_alignment_transform_slider_from_spin(spin)
        _queue_global_transform_preview_update()

    return SimpleNamespace(_sync_linked_scale=_sync_linked_scale, _commit_global_transform_spin=_commit_global_transform_spin, _global_transform_values=_global_transform_values, _part_transform_values=_part_transform_values, _capture_static_preview_baked_transform_state=_capture_static_preview_baked_transform_state, _active_alignment_transform_preview_widgets=_active_alignment_transform_preview_widgets, _set_global_fast_preview_edit_scope=_set_global_fast_preview_edit_scope, _set_part_fast_preview_edit_scope=_set_part_fast_preview_edit_scope, _queue_alignment_d3d11_fast_transform=_queue_alignment_d3d11_fast_transform, _send_alignment_d3d11_fast_transform_state=_send_alignment_d3d11_fast_transform_state, _replay_alignment_d3d11_fast_transform=_replay_alignment_d3d11_fast_transform, _apply_global_transform_fast_preview=_apply_global_transform_fast_preview, _apply_part_transform_fast_preview=_apply_part_transform_fast_preview, _queue_global_transform_preview_update=_queue_global_transform_preview_update, _queue_part_transform_preview_update=_queue_part_transform_preview_update, _apply_alignment_transform_reset_state=_apply_alignment_transform_reset_state, _reset_location_values=_reset_location_values, _reset_rotation_values=_reset_rotation_values, _reset_scale_values=_reset_scale_values, _reset_placement_values=_reset_placement_values, _nudge_rotation=_nudge_rotation, _current_global_rotation_origin_for_preview=_current_global_rotation_origin_for_preview, _alignment_part_source_indices_for_commit=_alignment_part_source_indices_for_commit, _apply_alignment_part_translation_delta=_apply_alignment_part_translation_delta, _apply_alignment_part_rotation_delta=_apply_alignment_part_rotation_delta, _sync_alignment_preview_rotation_context=_sync_alignment_preview_rotation_context, _prepare_alignment_preview_drag=_prepare_alignment_preview_drag, _prepare_alignment_d3d11_preview_drag=_prepare_alignment_d3d11_preview_drag, _commit_alignment_d3d11_drag_generation=_commit_alignment_d3d11_drag_generation, _set_global_transform_values_for_d3d11_drag=_set_global_transform_values_for_d3d11_drag, _queue_global_transform_values_for_d3d11_drag=_queue_global_transform_values_for_d3d11_drag, _set_selected_part_controls_for_d3d11_drag=_set_selected_part_controls_for_d3d11_drag, _queue_selected_part_controls_for_d3d11_drag=_queue_selected_part_controls_for_d3d11_drag, _flush_alignment_d3d11_drag_ui=_flush_alignment_d3d11_drag_ui, _alignment_d3d11_base_global_transform=_alignment_d3d11_base_global_transform, _alignment_d3d11_base_part_transform=_alignment_d3d11_base_part_transform, _alignment_d3d11_translation_to_transform_units=_alignment_d3d11_translation_to_transform_units, _apply_alignment_d3d11_translation_total=_apply_alignment_d3d11_translation_total, _apply_alignment_d3d11_rotation_total=_apply_alignment_d3d11_rotation_total, _finish_alignment_d3d11_translation=_finish_alignment_d3d11_translation, _finish_alignment_d3d11_rotation=_finish_alignment_d3d11_rotation, _commit_alignment_preview_translation=_commit_alignment_preview_translation, _commit_alignment_preview_rotation=_commit_alignment_preview_rotation)


def create_alignment_parts_outliner_mapping_callbacks(context: dict[str, object]) -> SimpleNamespace:
    List = context.get('List')
    PARTS_OUTLINER_ROLE_OPTIONS = context.get('PARTS_OUTLINER_ROLE_OPTIONS')
    QBrush = context.get('QBrush')
    QColor = context.get('QColor')
    QLabel = context.get('QLabel')
    QLineEdit = context.get('QLineEdit')
    QMenu = context.get('QMenu')
    QPoint = context.get('QPoint')
    QSizePolicy = context.get('QSizePolicy')
    QTimer = context.get('QTimer')
    QTreeWidgetItem = context.get('QTreeWidgetItem')
    Qt = context.get('Qt')
    Sequence = context.get('Sequence')
    StaticSourcePartAdjustment = context.get('StaticSourcePartAdjustment')
    _alignment_dialog_widgets_live = context.get('_alignment_dialog_widgets_live')
    _alignment_part_clipboard_can_paste = context.get('_alignment_part_clipboard_can_paste')
    _alignment_part_transform_preview_queue_indices_helper = context.get('_alignment_part_transform_preview_queue_indices_helper')
    _auto_fit_alignment_tree_columns = context.get('_auto_fit_alignment_tree_columns')
    _capture_initial_geometry_snapshot = context.get('_capture_initial_geometry_snapshot')
    _commit_mapping_edit = context.get('_commit_mapping_edit')
    _copied_original_texture_tooltip = context.get('_copied_original_texture_tooltip')
    _ensure_source_part_adjustment = context.get('_ensure_source_part_adjustment')
    _fit_alignment_tree_height_to_rows = context.get('_fit_alignment_tree_height_to_rows')
    _is_marker_source = context.get('_is_marker_source')
    _load_selected_part_controls = context.get('_load_selected_part_controls')
    _mapped_source_vertex_counts_helper = context.get('_mapped_source_vertex_counts_helper')
    _mapped_target_vertex_count_helper = context.get('_mapped_target_vertex_count_helper')
    _mapping_committed_source_cell_state_helper = context.get('_mapping_committed_source_cell_state_helper')
    _mapping_edit_committed_text_helper = context.get('_mapping_edit_committed_text_helper')
    _mapping_edit_draft_tooltip_helper = context.get('_mapping_edit_draft_tooltip_helper')
    _mapping_edit_indices_helper = context.get('_mapping_edit_indices_helper')
    _mapping_edit_placeholder_text_helper = context.get('_mapping_edit_placeholder_text_helper')
    _mapping_edit_source_cell_state_helper = context.get('_mapping_edit_source_cell_state_helper')
    _mapping_indices_for_source_target_helper = context.get('_mapping_indices_for_source_target_helper')
    _mapping_preserve_split_group_count_helper = context.get('_mapping_preserve_split_group_count_helper')
    _mapping_role_hint = context.get('_mapping_role_hint')
    _mapping_route_button_enabled_state_helper = context.get('_mapping_route_button_enabled_state_helper')
    _mapping_source_cell_text = context.get('_mapping_source_cell_text')
    _mapping_source_indices_text_helper = context.get('_mapping_source_indices_text_helper')
    _mapping_source_target_route_state_helper = context.get('_mapping_source_target_route_state_helper')
    _mapping_status_action_state_helper = context.get('_mapping_status_action_state_helper')
    _mapping_status_current_target_line_helper = context.get('_mapping_status_current_target_line_helper')
    _mapping_status_physics_state_helper = context.get('_mapping_status_physics_state_helper')
    _mapping_status_selection_lines_helper = context.get('_mapping_status_selection_lines_helper')
    _mapping_status_summary_badges_helper = context.get('_mapping_status_summary_badges_helper')
    _mapping_status_summary_html_helper = context.get('_mapping_status_summary_html_helper')
    _mapping_table_advanced_visibility_state_helper = context.get('_mapping_table_advanced_visibility_state_helper')
    _mapping_table_build_can_start_helper = context.get('_mapping_table_build_can_start_helper')
    _mapping_table_build_complete_helper = context.get('_mapping_table_build_complete_helper')
    _mapping_table_build_mark_complete_helper = context.get('_mapping_table_build_mark_complete_helper')
    _mapping_table_build_mark_requested_started_helper = context.get('_mapping_table_build_mark_requested_started_helper')
    _mapping_table_build_next_index_helper = context.get('_mapping_table_build_next_index_helper')
    _mapping_table_build_set_next_index_helper = context.get('_mapping_table_build_set_next_index_helper')
    _mapping_table_build_start_delay_ms_helper = context.get('_mapping_table_build_start_delay_ms_helper')
    _mapping_table_chunk_presentation_state_helper = context.get('_mapping_table_chunk_presentation_state_helper')
    _mapping_table_chunk_row_limit_helper = context.get('_mapping_table_chunk_row_limit_helper')
    _mapping_table_chunk_time_budget_seconds_helper = context.get('_mapping_table_chunk_time_budget_seconds_helper')
    _mapping_table_column_max_widths_helper = context.get('_mapping_table_column_max_widths_helper')
    _mapping_table_column_min_widths_helper = context.get('_mapping_table_column_min_widths_helper')
    _mapping_table_expand_columns_helper = context.get('_mapping_table_expand_columns_helper')
    _mapping_table_height_fit_kwargs_helper = context.get('_mapping_table_height_fit_kwargs_helper')
    _mapping_table_loading_progress_text_helper = context.get('_mapping_table_loading_progress_text_helper')
    _mapping_table_ready_progress_text_helper = context.get('_mapping_table_ready_progress_text_helper')
    _mapping_table_row_hidden_by_filters_helper = context.get('_mapping_table_row_hidden_by_filters_helper')
    _mapping_table_target_row_state_helper = context.get('_mapping_table_target_row_state_helper')
    _mapping_target_confidence_state_helper = context.get('_mapping_target_confidence_state_helper')
    _mapping_target_dds_cell_state_helper = context.get('_mapping_target_dds_cell_state_helper')
    _mapping_target_details_text_helper = context.get('_mapping_target_details_text_helper')
    _mapping_target_item_helper = context.get('_mapping_target_item_helper')
    _mapping_text_has_indices_helper = context.get('_mapping_text_has_indices_helper')
    _mapping_vertex_limit_issues_helper = context.get('_mapping_vertex_limit_issues_helper')
    _mapping_vertex_limit_status_line_helper = context.get('_mapping_vertex_limit_status_line_helper')
    _parts_outliner_action_role_value_helper = context.get('_parts_outliner_action_role_value_helper')
    _parts_outliner_action_target_index_helper = context.get('_parts_outliner_action_target_index_helper')
    _parts_outliner_cache_matches_helper = context.get('_parts_outliner_cache_matches_helper')
    _parts_outliner_cache_record_revision_helper = context.get('_parts_outliner_cache_record_revision_helper')
    _parts_outliner_copied_texture_tooltip_source_index_helper = context.get('_parts_outliner_copied_texture_tooltip_source_index_helper')
    _parts_outliner_drop_target_index_helper = context.get('_parts_outliner_drop_target_index_helper')
    _parts_outliner_geometry_text_helper = context.get('_parts_outliner_geometry_text_helper')
    _parts_outliner_revision_helper = context.get('_parts_outliner_revision_helper')
    _parts_outliner_role_menu_specs_helper = context.get('_parts_outliner_role_menu_specs_helper')
    _parts_outliner_selection_changed = context.get('_parts_outliner_selection_changed')
    _parts_outliner_source_click_action_helper = context.get('_parts_outliner_source_click_action_helper')
    _parts_outliner_source_drop_allowed_helper = context.get('_parts_outliner_source_drop_allowed_helper')
    _parts_outliner_source_index_helper = context.get('_parts_outliner_source_index_helper')
    _parts_outliner_source_indices_helper = context.get('_parts_outliner_source_indices_helper')
    _parts_outliner_source_item_helper = context.get('_parts_outliner_source_item_helper')
    _parts_outliner_source_label_helper = context.get('_parts_outliner_source_label_helper')
    _parts_outliner_source_role_change_refresh_reason_helper = context.get('_parts_outliner_source_role_change_refresh_reason_helper')
    _parts_outliner_source_role_change_undo_label_helper = context.get('_parts_outliner_source_role_change_undo_label_helper')
    _parts_outliner_source_target_apply_state_helper = context.get('_parts_outliner_source_target_apply_state_helper')
    _parts_outliner_target_item_helper = context.get('_parts_outliner_target_item_helper')
    _parts_outliner_target_label_helper = context.get('_parts_outliner_target_label_helper')
    _parts_outliner_target_menu_specs_helper = context.get('_parts_outliner_target_menu_specs_helper')
    _parts_outliner_unassigned_group_item_helper = context.get('_parts_outliner_unassigned_group_item_helper')
    _parts_outliner_unassigned_source_indices_helper = context.get('_parts_outliner_unassigned_source_indices_helper')
    _parts_outliner_unassigned_target_label_helper = context.get('_parts_outliner_unassigned_target_label_helper')
    _paste_alignment_part_clipboard_as_replacement_source = context.get('_paste_alignment_part_clipboard_as_replacement_source')
    _physics_status_tooltip = context.get('_physics_status_tooltip')
    _push_geometry_undo_snapshot = context.get('_push_geometry_undo_snapshot')
    _qt_object_is_valid = context.get('_qt_object_is_valid')
    _queue_material_edit_refresh = context.get('_queue_material_edit_refresh')
    _queue_selection_preview_refresh = context.get('_queue_selection_preview_refresh')
    _queue_static_preview_rebuild = context.get('_queue_static_preview_rebuild')
    _queue_static_preview_refresh = context.get('_queue_static_preview_refresh')
    _refresh_source_assignment_columns = context.get('_refresh_source_assignment_columns')
    _refresh_source_material_plan = context.get('_refresh_source_material_plan')
    _removed_target_dds_cell_text = context.get('_removed_target_dds_cell_text')
    _removed_target_dds_tooltip_helper = context.get('_removed_target_dds_tooltip_helper')
    _routing_effect_lines_helper = context.get('_routing_effect_lines_helper')
    _routing_source_material_labels_helper = context.get('_routing_source_material_labels_helper')
    _select_source_part_from_viewport = context.get('_select_source_part_from_viewport')
    _selected_source_indices_state_helper = context.get('_selected_source_indices_state_helper')
    _selected_source_summary = context.get('_selected_source_summary')
    _selection_view_update_kwargs_helper = context.get('_selection_view_update_kwargs_helper')
    _set_mesh_replacement_selection_view = context.get('_set_mesh_replacement_selection_view')
    _set_preview_performance_status = context.get('_set_preview_performance_status')
    _set_source_role_override_value = context.get('_set_source_role_override_value')
    _source_assignment_index_helper = context.get('_source_assignment_index_helper')
    _source_display_name = context.get('_source_display_name')
    _source_index_from_tree_item = context.get('_source_index_from_tree_item')
    _source_index_help_text = context.get('_source_index_help_text')
    _source_material_group_label_helper = context.get('_source_material_group_label_helper')
    _source_outliner_dds_text = context.get('_source_outliner_dds_text')
    _source_outliner_geometry_helper = context.get('_source_outliner_geometry_helper')
    _source_outliner_label_helper = context.get('_source_outliner_label_helper')
    _source_outliner_state = context.get('_source_outliner_state')
    _source_part_check_toggle_state_helper = context.get('_source_part_check_toggle_state_helper')
    _source_part_display_label_helper = context.get('_source_part_display_label_helper')
    _source_part_edit_undo_label_helper = context.get('_source_part_edit_undo_label_helper')
    _source_part_include_exclude_pending_reason_helper = context.get('_source_part_include_exclude_pending_reason_helper')
    _source_part_role_action_state_helper = context.get('_source_part_role_action_state_helper')
    _source_part_routing_preview_action_helper = context.get('_source_part_routing_preview_action_helper')
    _source_parts_apply_pending_presentation_helper = context.get('_source_parts_apply_pending_presentation_helper')
    _source_parts_clear_apply_pending_helper = context.get('_source_parts_clear_apply_pending_helper')
    _source_parts_clear_apply_pending_presentation_helper = context.get('_source_parts_clear_apply_pending_presentation_helper')
    _source_parts_mark_apply_pending_helper = context.get('_source_parts_mark_apply_pending_helper')
    _source_parts_mark_preview_rebuild_pending_helper = context.get('_source_parts_mark_preview_rebuild_pending_helper')
    _source_parts_preview_rebuild_pending_helper = context.get('_source_parts_preview_rebuild_pending_helper')
    _source_parts_preview_rebuild_pending_presentation_helper = context.get('_source_parts_preview_rebuild_pending_presentation_helper')
    _source_physics_status_text = context.get('_source_physics_status_text')
    _source_role_label = context.get('_source_role_label')
    _source_tree_item_helper = context.get('_source_tree_item_helper')
    _source_tree_item_state_helper = context.get('_source_tree_item_state_helper')
    _sync_highlight_sets = context.get('_sync_highlight_sets')
    _target_display_name = context.get('_target_display_name')
    _target_mapping_selection_view_payload_helper = context.get('_target_mapping_selection_view_payload_helper')
    _target_outliner_state = context.get('_target_outliner_state')
    _target_physics_status_text = context.get('_target_physics_status_text')
    _target_selection_changed = context.get('_target_selection_changed')
    _target_texture_status_details = context.get('_target_texture_status_details')
    _target_texture_status_text = context.get('_target_texture_status_text')
    _texture_set_for_source_index_helper = context.get('_texture_set_for_source_index_helper')
    _tree_item_source_index_or_fallback_helper = context.get('_tree_item_source_index_or_fallback_helper')
    _tree_item_target_index_or_fallback_helper = context.get('_tree_item_target_index_or_fallback_helper')
    _unique_nonnegative_indices_helper = context.get('_unique_nonnegative_indices_helper')
    _update_selection_context = context.get('_update_selection_context')
    advanced_part_tools_section = context.get('advanced_part_tools_section')
    apply_best_guesses_button = context.get('apply_best_guesses_button')
    apply_source_parts_button = context.get('apply_source_parts_button')
    assign_source_button = context.get('assign_source_button')
    clear_all_guesses_button = context.get('clear_all_guesses_button')
    clear_target_button = context.get('clear_target_button')
    copied_original_texture_disabled_sources = context.get('copied_original_texture_disabled_sources')
    copied_original_texture_intents_by_source = context.get('copied_original_texture_intents_by_source')
    empty_targets_filter_checkbox = context.get('empty_targets_filter_checkbox')
    group_materials_button = context.get('group_materials_button')
    independent_output_source_indices = context.get('independent_output_source_indices')
    initial_mapping_text_by_target = context.get('initial_mapping_text_by_target')
    low_confidence_filter_checkbox = context.get('low_confidence_filter_checkbox')
    mapping_edit_refresh_timer = context.get('mapping_edit_refresh_timer')
    mapping_edits = context.get('mapping_edits')
    mapping_edits_by_target = context.get('mapping_edits_by_target')
    mapping_items_by_target = context.get('mapping_items_by_target')
    mapping_progress_label = context.get('mapping_progress_label')
    mapping_status_label = context.get('mapping_status_label')
    mapping_table_build_requested = context.get('mapping_table_build_requested')
    mapping_table_build_state = context.get('mapping_table_build_state')
    mapping_table_build_timer = context.get('mapping_table_build_timer')
    mapping_targets = context.get('mapping_targets')
    mapping_tree = context.get('mapping_tree')
    mappings_by_target = context.get('mappings_by_target')
    merge_source_button = context.get('merge_source_button')
    original_button_panel = context.get('original_button_panel')
    original_mesh_for_mapping = context.get('original_mesh_for_mapping')
    original_part_clipboard_action_text = context.get('original_part_clipboard_action_text')
    original_parts_label = context.get('original_parts_label')
    original_tree = context.get('original_tree')
    parts_outliner_cache_state = context.get('parts_outliner_cache_state')
    parts_outliner_item_update_guard = context.get('parts_outliner_item_update_guard')
    parts_outliner_source_items = context.get('parts_outliner_source_items')
    parts_outliner_target_items = context.get('parts_outliner_target_items')
    parts_outliner_tree = context.get('parts_outliner_tree')
    preview_only_source_indices = context.get('preview_only_source_indices')
    preview_target_button = context.get('preview_target_button')
    remove_source_button = context.get('remove_source_button')
    replacement_mesh_for_mapping = context.get('replacement_mesh_for_mapping')
    row = context.get('row')
    selected_source_highlight_indices = context.get('selected_source_highlight_indices')
    selected_source_part = context.get('selected_source_part')
    selected_target_slot = context.get('selected_target_slot')
    simplified_part_label = context.get('simplified_part_label')
    source_display_overrides = context.get('source_display_overrides')
    source_items_by_index = context.get('source_items_by_index')
    source_part_adjustments = context.get('source_part_adjustments')
    source_parts_apply_state = context.get('source_parts_apply_state')
    source_parts_group = context.get('source_parts_group')
    source_parts_pending_label = context.get('source_parts_pending_label')
    source_tree = context.get('source_tree')
    source_tree_item_update_guard = context.get('source_tree_item_update_guard')
    static_replacement_vertex_limit = context.get('static_replacement_vertex_limit')
    target_slots_label = context.get('target_slots_label')
    texture_overrides_dirty = context.get('texture_overrides_dirty')
    texture_sets = context.get('texture_sets')
    time = context.get('time')
    transform_source_indices = context.get('transform_source_indices')

    _parts_outliner_source_label = lambda source_index: _source_outliner_label_helper(
        source_index,
        replacement_mesh_for_mapping,
        source_display_overrides,
        simplify_label=simplified_part_label,
    )
    _parts_outliner_source_geometry = lambda source_index: _source_outliner_geometry_helper(
        source_index,
        replacement_mesh_for_mapping,
    )

    def _selected_source_indices_from_tree(*, include_fallback: bool = True) -> List[int]:
        selected_items: Sequence[QTreeWidgetItem] = ()
        if _qt_object_is_valid(source_tree):
            try:
                selected_items = tuple(source_tree.selectedItems())
            except RuntimeError:
                selected_items = ()
        return list(
            _selected_source_indices_state_helper(
                selected_items,
                source_index_from_item=_source_index_from_tree_item,
                fallback_source_index=selected_source_part.get("index", -1),
                include_fallback=include_fallback,
            )
        )

    def _set_transform_source_indices(source_indices: Sequence[int]) -> None:
        transform_source_indices.clear()
        transform_source_indices.update(_alignment_part_transform_preview_queue_indices_helper(source_indices))

    def _clear_transform_source_indices() -> None:
        transform_source_indices.clear()

    def _set_source_parts_apply_pending(reason: str) -> None:
        reason_text = _source_parts_mark_apply_pending_helper(source_parts_apply_state, reason)
        presentation = _source_parts_apply_pending_presentation_helper(reason_text)
        try:
            apply_source_parts_button.setEnabled(presentation.apply_button_enabled)
            source_parts_pending_label.setText(presentation.label_text)
            source_parts_pending_label.setVisible(presentation.label_visible)
        except NameError:
            pass
        _set_preview_performance_status(
            presentation.performance_summary,
            details=presentation.performance_details,
        )

    def _clear_source_parts_apply_pending() -> None:
        _source_parts_clear_apply_pending_helper(source_parts_apply_state)
        presentation = _source_parts_clear_apply_pending_presentation_helper()
        try:
            apply_source_parts_button.setEnabled(presentation.apply_button_enabled)
            source_parts_pending_label.setText(presentation.label_text)
            source_parts_pending_label.setVisible(presentation.label_visible)
        except NameError:
            pass

    def _set_source_parts_preview_rebuild_pending(reason: str) -> None:
        reason_text = _source_parts_mark_preview_rebuild_pending_helper(source_parts_apply_state, reason)
        presentation = _source_parts_preview_rebuild_pending_presentation_helper(reason_text)
        try:
            apply_source_parts_button.setEnabled(presentation.apply_button_enabled)
            source_parts_pending_label.setText(presentation.label_text)
            source_parts_pending_label.setVisible(presentation.label_visible)
        except NameError:
            pass
        _set_preview_performance_status(
            presentation.performance_summary,
            details=presentation.performance_details,
        )

    def _clear_source_parts_preview_rebuild_pending() -> None:
        if not _source_parts_preview_rebuild_pending_helper(source_parts_apply_state):
            return
        _clear_source_parts_apply_pending()

    def _add_source_tree_item(source_index: int, source: object) -> None:
        if _is_marker_source(source):
            return
        label = _source_part_display_label_helper(source_index, source, source_display_overrides)
        role_hint = _source_role_label(source_index)
        copied_texture_rows = copied_original_texture_intents_by_source.get(int(source_index), [])
        adjustment = source_part_adjustments.get(source_index)
        item_state = _source_tree_item_state_helper(
            source_index=source_index,
            source=source,
            copied_texture_rows=copied_texture_rows,
            copied_texture_disabled=int(source_index) in copied_original_texture_disabled_sources,
            adjustment=adjustment,
        )
        source_item = _source_tree_item_helper(
            source_index=item_state.source_index,
            label=label,
            role_hint=role_hint,
            geometry_text=item_state.geometry_text,
            source_name=item_state.source_name,
            source_material=item_state.source_material,
            copied_texture_count=item_state.copied_texture_count,
            copied_texture_disabled=item_state.copied_texture_disabled,
            copied_texture_tooltip=_copied_original_texture_tooltip(source_index),
            enabled=item_state.enabled,
        )
        source_tree.addTopLevelItem(source_item)
        source_items_by_index[source_index] = source_item

    def _source_item_check_state_changed(item: QTreeWidgetItem, column: int) -> None:
        source_index = _source_index_from_tree_item(item)
        toggle_state = _source_part_check_toggle_state_helper(
            source_index=source_index,
            column=column,
            guard_active=bool(source_tree_item_update_guard.get("active")),
            checked=item.checkState(0) == Qt.Checked,
            selected_source_index=selected_source_part.get("index", -1),
        )
        if not toggle_state.available:
            return
        _push_geometry_undo_snapshot(_source_part_edit_undo_label_helper(toggle_state.undo_action))
        adjustment = _ensure_source_part_adjustment(toggle_state.source_index)
        adjustment.enabled = toggle_state.enabled
        _refresh_source_assignment_columns()
        if toggle_state.refresh_selected_controls:
            if callable(_load_selected_part_controls):
                _load_selected_part_controls()
        if callable(_sync_highlight_sets):
            _sync_highlight_sets()
        if toggle_state.apply_pending:
            _set_source_parts_apply_pending(_source_part_include_exclude_pending_reason_helper())
        else:
            _set_source_parts_preview_rebuild_pending(_source_part_include_exclude_pending_reason_helper())
            if callable(_queue_selection_preview_refresh):
                _queue_selection_preview_refresh()
            else:
                _queue_static_preview_rebuild()

    _outliner_source_index_from_item = lambda item: _parts_outliner_source_index_helper(item)

    _parts_outliner_drop_target_index = lambda item: _parts_outliner_drop_target_index_helper(
        item,
        user_role=int(Qt.UserRole),
    )

    def _parts_outliner_set_source_selection(
        source_indices: Sequence[int],
        *,
        activate_transform: bool,
        select_reference_rows: bool = True,
    ) -> None:
        normalized = list(_unique_nonnegative_indices_helper(source_indices))
        if select_reference_rows:
            source_blocked = source_tree.blockSignals(True)
            try:
                source_tree.clearSelection()
                for source_index in normalized[:1]:
                    source_item = source_items_by_index.get(source_index)
                    if source_item is None:
                        continue
                    source_item.setSelected(True)
                    source_tree.setCurrentItem(source_item)
            finally:
                source_tree.blockSignals(source_blocked)
        if activate_transform:
            selected_source_part["index"] = normalized[0] if normalized else -1
            selected_source_highlight_indices.clear()
            selected_source_highlight_indices.update(normalized[:1])
            _set_transform_source_indices(normalized[:1])
        else:
            selected_source_part["index"] = -1
            selected_source_highlight_indices.clear()
            _clear_transform_source_indices()

    def _refresh_parts_outliner() -> None:
        if bool(parts_outliner_item_update_guard.get("refreshing")):
            return
        revision = _parts_outliner_revision_helper(
            original_mesh=original_mesh_for_mapping,
            replacement_mesh=replacement_mesh_for_mapping,
            mapping_edits=mapping_edits,
            preview_only_source_indices=preview_only_source_indices,
            independent_output_source_indices=independent_output_source_indices,
            copied_original_texture_intents_by_source=copied_original_texture_intents_by_source,
        )
        if _parts_outliner_cache_matches_helper(
            parts_outliner_cache_state,
            revision,
            has_items=parts_outliner_tree.topLevelItemCount() > 0,
        ):
            return
        _parts_outliner_cache_record_revision_helper(parts_outliner_cache_state, revision)
        parts_outliner_item_update_guard["refreshing"] = True
        try:
            parts_outliner_tree.clear()
            parts_outliner_source_items.clear()
            parts_outliner_target_items.clear()
            assignment_index = _source_assignment_index_helper(mapping_edits, parse_mapping_edit=_parse_mapping_edit)
            assigned_sources: set[int] = set()
            if original_mesh_for_mapping is not None:
                for target_index, target in enumerate(original_mesh_for_mapping.submeshes):
                    target_name = _target_display_name(target_index)
                    edit = mapping_edits_by_target.get(target_index)
                    source_indices = _parse_mapping_edit(edit) if edit is not None else []
                    assigned_sources.update(_parts_outliner_source_indices_helper(source_indices))
                    target_label_text = getattr(target, "material", "") or getattr(target, "name", "") or target_name
                    state_text, state_color = _target_outliner_state(target_index, source_indices)
                    dds_cell_state = _mapping_target_dds_cell_state_helper(
                        state_text=state_text,
                        has_source_indices=bool(source_indices),
                    )
                    physics_text = _target_physics_status_text(target_label_text, target)
                    target_item = _parts_outliner_target_item_helper(
                        target_index=target_index,
                        label=_parts_outliner_target_label_helper(
                            target_index,
                            target_label_text,
                            simplify_label=simplified_part_label,
                        ),
                        role_hint=_mapping_role_hint(f"{getattr(target, 'name', '')} {getattr(target, 'material', '')}"),
                        dds_text=(
                            _removed_target_dds_cell_text(target_label_text)
                            if dds_cell_state["uses_removed_target_text"]
                            else _target_texture_status_text(target_label_text)
                        ),
                        state_text=state_text,
                        state_color=state_color,
                        physics_text=physics_text,
                        geometry_text=_parts_outliner_geometry_text_helper(target),
                        source_indices=tuple(source_indices),
                        texture_tooltip=_target_texture_status_details(target_label_text),
                        physics_tooltip=_physics_status_tooltip(physics_text),
                    )
                    parts_outliner_tree.addTopLevelItem(target_item)
                    parts_outliner_target_items[target_index] = target_item
                    for source_index in source_indices:
                        source_state, source_color = _source_outliner_state(source_index, tuple(assignment_index.get(source_index, ())))
                        source_physics = _source_physics_status_text(source_index, target_index)
                        tooltip_source_index = _parts_outliner_copied_texture_tooltip_source_index_helper(
                            source_index,
                            copied_original_texture_intents_by_source,
                        )
                        source_item = _parts_outliner_source_item_helper(
                            source_index=source_index,
                            target_index=target_index,
                            label=_parts_outliner_source_label_helper(
                                _parts_outliner_source_label(source_index)
                            ),
                            target_text=target_name,
                            role_label=_source_role_label(source_index),
                            dds_text=_source_outliner_dds_text(source_index),
                            state_text=source_state,
                            state_color=source_color,
                            physics_text=source_physics,
                            geometry_text=_parts_outliner_source_geometry(source_index),
                            physics_tooltip=_physics_status_tooltip(source_physics),
                            copied_texture_tooltip=_copied_original_texture_tooltip(
                                tooltip_source_index
                            ) if tooltip_source_index is not None else "",
                        )
                        target_item.addChild(source_item)
                        parts_outliner_source_items[source_index] = source_item
                    target_item.setExpanded(True)
            unassigned_indices = _parts_outliner_unassigned_source_indices_helper(
                replacement_mesh_for_mapping,
                tuple(assigned_sources),
                is_marker_source=_is_marker_source,
            )
            if unassigned_indices:
                group_item = _parts_outliner_unassigned_group_item_helper(len(unassigned_indices))
                parts_outliner_tree.addTopLevelItem(group_item)
                for source_index in unassigned_indices:
                    assigned_target_indices = tuple(assignment_index.get(int(source_index), ()))
                    source_state, source_color = _source_outliner_state(source_index, assigned_target_indices)
                    source_physics = _source_physics_status_text(source_index, -1)
                    tooltip_source_index = _parts_outliner_copied_texture_tooltip_source_index_helper(
                        source_index,
                        copied_original_texture_intents_by_source,
                    )
                    source_item = _parts_outliner_source_item_helper(
                        source_index=source_index,
                        target_index=-1,
                        label=_parts_outliner_source_label_helper(
                            _parts_outliner_source_label(source_index)
                        ),
                        target_text=_parts_outliner_unassigned_target_label_helper(),
                        role_label=_source_role_label(source_index),
                        dds_text=_source_outliner_dds_text(source_index),
                        state_text=source_state,
                        state_color=source_color,
                        physics_text=source_physics,
                        geometry_text=_parts_outliner_source_geometry(source_index),
                        physics_tooltip=_physics_status_tooltip(source_physics),
                        copied_texture_tooltip=_copied_original_texture_tooltip(
                            tooltip_source_index
                        ) if tooltip_source_index is not None else "",
                        unassigned=True,
                    )
                    group_item.addChild(source_item)
                    parts_outliner_source_items[source_index] = source_item
                group_item.setExpanded(True)
            _fit_alignment_tree_height_to_rows(parts_outliner_tree, minimum=128, screen_margin=420, maximum=420)
            parts_outliner_tree.setProperty("cdmw_defer_autofit", False)
            _auto_fit_alignment_tree_columns(
                parts_outliner_tree,
                (120, 110, 70, 64, 72, 56, 100),
                (260, 260, 150, 130, 140, 100, 220),
                expand_columns=(0, 1, 6),
            )
        finally:
            parts_outliner_item_update_guard["refreshing"] = False

    def _show_parts_outliner_context_menu(pos: QPoint) -> None:
        item = parts_outliner_tree.itemAt(pos)
        if item is not None:
            parts_outliner_tree.setCurrentItem(item)
        menu = QMenu(parts_outliner_tree)
        paste_action = menu.addAction(original_part_clipboard_action_text["paste_replacement_source"])
        paste_action.setEnabled(_alignment_part_clipboard_can_paste())
        chosen = menu.exec(parts_outliner_tree.viewport().mapToGlobal(pos))
        if chosen is paste_action:
            _paste_alignment_part_clipboard_as_replacement_source()

    def _apply_parts_outliner_source_target(source_index: int, target_index: int) -> None:
        if replacement_mesh_for_mapping is None:
            return
        apply_state = _parts_outliner_source_target_apply_state_helper(
            source_index=source_index,
            target_index=target_index,
            source_count=len(replacement_mesh_for_mapping.submeshes),
        )
        if not apply_state.available:
            return
        _push_geometry_undo_snapshot("Change source target")
        route_state = _mapping_source_target_route_state_helper(apply_state.target_index)
        defer_preview = bool(route_state["defer_preview"])
        for candidate_target, edit in tuple(mapping_edits):
            current_indices = tuple(_parse_mapping_edit(edit))
            updated_indices = _mapping_indices_for_source_target_helper(
                current_indices,
                apply_state.source_index,
                target_matches=int(candidate_target) == apply_state.target_index,
            )
            if updated_indices != current_indices:
                _set_mapping_indices(candidate_target, updated_indices, push_undo=False, defer_preview=defer_preview)
        if route_state["preview_only"]:
            preview_only_source_indices.add(apply_state.source_index)
        else:
            preview_only_source_indices.discard(apply_state.source_index)
        independent_output_source_indices.discard(apply_state.source_index)
        selected_target_slot["index"] = int(route_state["selected_target_index"])
        texture_overrides_dirty["dirty"] = True
        _refresh_source_assignment_columns()
        _refresh_parts_outliner()
        _select_source_part_from_viewport(apply_state.source_index)
        try:
            _refresh_source_material_plan()
        except NameError:
            pass
        _update_mapping_status()
        preview_action = _source_part_routing_preview_action_helper(
            defer_preview=defer_preview,
            pending_reason=str(route_state["pending_reason"]),
        )
        if preview_action["apply_pending"]:
            _set_source_parts_apply_pending(str(preview_action["pending_reason"]))
        elif preview_action["queue_preview"]:
            _queue_static_preview_rebuild()

    def _handle_parts_outliner_source_drop(
        source_item: object,
        target_item: object,
    ) -> bool:
        if not isinstance(source_item, QTreeWidgetItem):
            return False
        source_index = _outliner_source_index_from_item(source_item)
        target_index = _parts_outliner_drop_target_index(
            target_item if isinstance(target_item, QTreeWidgetItem) else None
        )
        if not _parts_outliner_source_drop_allowed_helper(
            refreshing=bool(parts_outliner_item_update_guard.get("refreshing")),
            source_index=source_index,
            target_index=target_index,
        ):
            return False
        _apply_parts_outliner_source_target(source_index, target_index)
        return True

    def _apply_parts_outliner_source_role(source_index: int, role_value: str) -> None:
        action_state = _source_part_role_action_state_helper(
            source_index=source_index,
            role_value=role_value,
            undo_label=_parts_outliner_source_role_change_undo_label_helper(),
            refresh_reason=_parts_outliner_source_role_change_refresh_reason_helper(),
        )
        if not action_state.available:
            return
        _push_geometry_undo_snapshot(action_state.undo_label)
        _set_source_role_override_value(action_state.source_index, action_state.normalized_role)
        _refresh_source_assignment_columns(lightweight=True)
        _refresh_parts_outliner()
        _select_source_part_from_viewport(action_state.source_index)
        _queue_material_edit_refresh(
            refresh_plan=action_state.refresh_plan,
            force_plan=action_state.force_plan,
            refresh_preview=action_state.refresh_preview,
            reason=action_state.refresh_reason,
        )
        _update_mapping_status()

    def _open_parts_outliner_target_dropdown(item: QTreeWidgetItem, column: int) -> None:
        source_index = _outliner_source_index_from_item(item)
        if source_index < 0:
            return
        menu = QMenu(parts_outliner_tree)
        target_labels = (
            tuple(_target_display_name(target_index) for target_index, _target in enumerate(original_mesh_for_mapping.submeshes))
            if original_mesh_for_mapping is not None
            else ()
        )
        for label, target_value in _parts_outliner_target_menu_specs_helper(target_labels):
            action = menu.addAction(label)
            action.setData(target_value)
        rect = parts_outliner_tree.visualItemRect(item)
        point = parts_outliner_tree.viewport().mapToGlobal(rect.bottomLeft())
        chosen = menu.exec(point)
        if chosen is None:
            return
        target_index = _parts_outliner_action_target_index_helper(chosen.data())
        _apply_parts_outliner_source_target(source_index, target_index)

    def _open_parts_outliner_role_dropdown(item: QTreeWidgetItem, column: int) -> None:
        source_index = _outliner_source_index_from_item(item)
        if source_index < 0:
            return
        menu = QMenu(parts_outliner_tree)
        for label, role_value in _parts_outliner_role_menu_specs_helper(PARTS_OUTLINER_ROLE_OPTIONS):
            action = menu.addAction(label)
            action.setData(role_value)
        rect = parts_outliner_tree.visualItemRect(item)
        point = parts_outliner_tree.viewport().mapToGlobal(rect.bottomLeft())
        chosen = menu.exec(point)
        if chosen is None:
            return
        _apply_parts_outliner_source_role(source_index, _parts_outliner_action_role_value_helper(chosen.data()))

    def _handle_parts_outliner_item_clicked(item: QTreeWidgetItem, column: int) -> None:
        if item is None or bool(parts_outliner_item_update_guard.get("refreshing")):
            return
        _parts_outliner_selection_changed(item, None)
        click_action = _parts_outliner_source_click_action_helper(item.data(0, Qt.UserRole), column)
        if click_action == "target":
            _open_parts_outliner_target_dropdown(item, column)
        elif click_action == "role":
            _open_parts_outliner_role_dropdown(item, column)

    def _append_mapping_target_row(target_index: int, target: object) -> None:
        mapping = mappings_by_target.get(int(target_index))
        row_state = _mapping_table_target_row_state_helper(
            target_index=target_index,
            target=target,
            mapping=mapping,
        )
        target_role_hint = _mapping_role_hint(row_state.target_role_source_text)
        edit = QLineEdit()
        edit.setText(row_state.initial_mapping_text)
        initial_mapping_text_by_target[row_state.target_index] = edit.text()
        edit.setProperty("committed_mapping_text", edit.text())
        confidence_state = _mapping_target_confidence_state_helper(mapping)
        confidence_label_text = str(confidence_state["text"])
        confidence_color = str(confidence_state["color"])
        outliner_state, outliner_state_color = _target_outliner_state(
            row_state.target_index,
            row_state.initial_source_indices,
        )
        confidence_label = QLabel(confidence_label_text)
        confidence_label.setToolTip(
            "Low confidence means the source name, size, or position did not strongly match this original slot. "
            "Override by typing the correct replacement source index."
        )
        confidence_label.setStyleSheet(f"color: {confidence_color}; font-weight: 600;")
        selected_text, selected_ok = _selected_source_summary(edit.text())
        selected_display = _mapping_source_cell_text(selected_text, selected_ok)
        target_details = _mapping_target_details_text_helper(
            row_state.target_index,
            row_state.target_label_text,
            target_role_hint,
            target,
        )
        target_dds_status = (
            _removed_target_dds_cell_text(row_state.target_label_text)
            if outliner_state == "Removed"
            else _target_texture_status_text(row_state.target_label_text)
        )
        mapping_item = _mapping_target_item_helper(
            target_index=row_state.target_index,
            target_label_text=row_state.target_label_text,
            target_role_hint=target_role_hint,
            selected_display=selected_display,
            outliner_state=outliner_state,
            outliner_state_color=outliner_state_color,
            target_dds_status=target_dds_status,
            physics_status=_target_physics_status_text(row_state.target_label_text, target),
            initial_source_indices=row_state.initial_source_indices,
            confidence_label_text=confidence_label_text,
            target_details=target_details,
            target_texture_details=_target_texture_status_details(row_state.target_label_text),
            selected_ok=selected_ok,
            removed=row_state.removed,
            mapping_text_empty=row_state.mapping_text_empty,
        )
        mapping_tree.addTopLevelItem(mapping_item)
        mapping_items_by_target[row_state.target_index] = mapping_item

        def _update_selected_source_label(
            text: str,
            *,
            item: QTreeWidgetItem = mapping_item,
        ) -> None:
            summary, ok = _selected_source_summary(text)
            source_cell_state = _mapping_edit_source_cell_state_helper(
                text,
                edit.property("committed_mapping_text"),
                has_source_indices=_mapping_text_has_indices_helper(text),
            )
            item.setText(3, _mapping_source_cell_text(summary, ok))
            item.setData(0, Qt.UserRole, tuple(_parse_mapping_edit(edit)))
            item.setData(0, Qt.UserRole + 3, bool(source_cell_state["is_empty"]))
            item.setToolTip(3, _mapping_edit_draft_tooltip_helper())
            item.setForeground(3, QBrush(QColor(str(source_cell_state["foreground"]))))

        edit.textChanged.connect(_update_selected_source_label)
        edit.editingFinished.connect(lambda edit=edit: _commit_mapping_edit(edit))
        edit.setPlaceholderText(_mapping_edit_placeholder_text_helper())
        edit.setToolTip(_source_index_help_text())
        edit.setMinimumHeight(max(22, edit.sizeHint().height()))
        edit.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        mapping_tree.setItemWidget(mapping_item, 2, edit)
        mapping_edits.append((row_state.target_index, edit))
        mapping_edits_by_target[row_state.target_index] = edit

    def _build_mapping_table_chunk() -> None:
        if (
            not _alignment_dialog_widgets_live()
            or not _qt_object_is_valid(mapping_progress_label)
            or not _qt_object_is_valid(mapping_tree)
        ):
            mapping_table_build_timer.stop()
            return
        if _mapping_table_build_complete_helper(mapping_table_build_state):
            mapping_table_build_timer.stop()
            return
        started = time.monotonic()
        appended = 0
        total = len(mapping_targets)
        while _mapping_table_build_next_index_helper(mapping_table_build_state) < total:
            target_index = _mapping_table_build_next_index_helper(mapping_table_build_state)
            _append_mapping_target_row(target_index, mapping_targets[target_index])
            _mapping_table_build_set_next_index_helper(mapping_table_build_state, target_index + 1)
            appended += 1
            if (
                appended >= _mapping_table_chunk_row_limit_helper()
                or (time.monotonic() - started) >= _mapping_table_chunk_time_budget_seconds_helper()
            ):
                break
        current = _mapping_table_build_next_index_helper(mapping_table_build_state)
        mapping_progress_label.setText(
            _mapping_table_loading_progress_text_helper(current, total)
        )
        chunk_presentation = _mapping_table_chunk_presentation_state_helper(
            current_rows=current,
            total_rows=total,
            show_low_only=low_confidence_filter_checkbox.isChecked(),
            show_empty_only=empty_targets_filter_checkbox.isChecked(),
        )
        if chunk_presentation.filters_active or chunk_presentation.complete:
            _apply_target_slot_filters(fit_height=chunk_presentation.fit_height)
        if chunk_presentation.complete:
            _mapping_table_build_mark_complete_helper(mapping_table_build_state)
            mapping_table_build_timer.stop()
            mapping_progress_label.setText(_mapping_table_ready_progress_text_helper(total))
            _refresh_source_assignment_columns(lightweight=True)
            mapping_tree.setProperty("cdmw_defer_autofit", False)
            _auto_fit_alignment_tree_columns(
                mapping_tree,
                _mapping_table_column_min_widths_helper(),
                _mapping_table_column_max_widths_helper(),
                expand_columns=_mapping_table_expand_columns_helper(),
            )
            _capture_initial_geometry_snapshot()
            _refresh_parts_outliner()

    def _apply_target_slot_filters(_checked: object = None, *, fit_height: bool = True) -> None:
        if not _alignment_dialog_widgets_live() or not _qt_object_is_valid(mapping_tree):
            return
        show_low_only = bool(low_confidence_filter_checkbox.isChecked())
        show_empty_only = bool(empty_targets_filter_checkbox.isChecked())
        for item_index in range(mapping_tree.topLevelItemCount()):
            item = mapping_tree.topLevelItem(item_index)
            confidence_text = str(item.data(0, Qt.UserRole + 2) or "")
            is_empty = bool(item.data(0, Qt.UserRole + 3))
            item.setHidden(
                _mapping_table_row_hidden_by_filters_helper(
                    confidence_text=confidence_text,
                    is_empty=is_empty,
                    show_low_only=show_low_only,
                    show_empty_only=show_empty_only,
                )
            )
        if fit_height:
            _fit_alignment_tree_height_to_rows(mapping_tree, **_mapping_table_height_fit_kwargs_helper())

    def _ensure_mapping_table_building() -> None:
        if (
            not _alignment_dialog_widgets_live()
            or not _qt_object_is_valid(mapping_progress_label)
        ):
            mapping_table_build_timer.stop()
            return
        if not _mapping_table_build_can_start_helper(
            mapping_table_build_requested,
            mapping_table_build_state,
        ):
            return
        _mapping_table_build_mark_requested_started_helper(mapping_table_build_requested)
        mapping_progress_label.setText(
            _mapping_table_loading_progress_text_helper(0, len(mapping_targets))
        )
        QTimer.singleShot(_mapping_table_build_start_delay_ms_helper(), mapping_table_build_timer.start)

    def _clear_all_mapping_guesses() -> None:
        _push_geometry_undo_snapshot("Clear all routing guesses")
        for _target_index, edit in mapping_edits:
            edit.setText("")

    def _apply_best_mapping_guesses() -> None:
        _push_geometry_undo_snapshot("Apply best routing guesses")
        for target_index, edit in mapping_edits:
            edit.setText(initial_mapping_text_by_target.get(target_index, ""))

    def _preview_selected_target_slot() -> None:
        item = mapping_tree.currentItem()
        if item is not None:
            _target_selection_changed(item, None)
        _queue_static_preview_refresh()

    _selected_source_index = lambda: _tree_item_source_index_or_fallback_helper(
        source_tree.currentItem(),
        int(selected_source_part.get("index", -1)),
    )

    _selected_target_index = lambda: _tree_item_target_index_or_fallback_helper(
        mapping_tree.currentItem(),
        int(selected_target_slot.get("index", -1)),
    )

    _parse_mapping_edit = lambda edit: list(_mapping_edit_indices_helper(edit))

    _texture_set_for_source_index = lambda source_index, texture_sets_by_key: _texture_set_for_source_index_helper(
        source_index,
        replacement_mesh_for_mapping,
        texture_sets_by_key,
    )

    _source_material_group_label = lambda source_index, texture_sets_by_key: _source_material_group_label_helper(
        source_index,
        replacement_mesh_for_mapping,
        texture_sets_by_key,
        source_part_adjustments,
    )

    _mapped_target_vertex_count = lambda source_indices: _mapped_target_vertex_count_helper(
        source_indices,
        replacement_mesh_for_mapping,
        source_part_adjustments,
        default_adjustment=StaticSourcePartAdjustment,
        is_marker_source=_is_marker_source,
    )
    _mapped_source_vertex_counts = lambda source_indices: list(
        _mapped_source_vertex_counts_helper(
            source_indices,
            replacement_mesh_for_mapping,
            source_part_adjustments,
            default_adjustment=StaticSourcePartAdjustment,
            is_marker_source=_is_marker_source,
        )
    )
    _mapping_preserve_split_group_count = lambda source_indices: _mapping_preserve_split_group_count_helper(
        _mapped_source_vertex_counts(source_indices),
        static_replacement_vertex_limit,
        source_display_name=_source_display_name,
    )
    _mapping_vertex_limit_issues = lambda mappings: list(
        _mapping_vertex_limit_issues_helper(
            mappings,
            original_format=str(getattr(original_mesh_for_mapping, "format", "") or ""),
            vertex_limit=static_replacement_vertex_limit,
            target_display_name=_target_display_name,
            mapped_target_vertex_count=_mapped_target_vertex_count,
            preserve_split_group_count=_mapping_preserve_split_group_count,
        )
    )
    _routing_source_material_labels = lambda source_indices: list(
        _routing_source_material_labels_helper(source_indices, replacement_mesh_for_mapping, texture_sets)
    )
    _routing_effect_lines = lambda target_index, source_indices, *, selection_ok, selection_summary: list(
        _routing_effect_lines_helper(
            target_index,
            source_indices,
            selection_ok=selection_ok,
            selection_summary=selection_summary,
            target_display_name=_target_display_name,
            source_display_name=_source_display_name,
            source_material_labels=_routing_source_material_labels,
        )
    )

    def _set_advanced_mapping_visible(checked: bool) -> None:
        visibility_state = _mapping_table_advanced_visibility_state_helper(checked)
        original_parts_label.setVisible(visibility_state.advanced_visible)
        original_tree.setVisible(visibility_state.advanced_visible)
        original_button_panel.setVisible(visibility_state.advanced_visible)
        source_parts_group.setVisible(visibility_state.advanced_visible)
        for mapping_action_button in (
            clear_all_guesses_button,
            apply_best_guesses_button,
            group_materials_button,
            preview_target_button,
        ):
            mapping_action_button.setVisible(visibility_state.visible_widgets)
        mapping_tree.setVisible(visibility_state.visible_widgets)
        target_slots_label.setVisible(visibility_state.visible_widgets)
        mapping_progress_label.setVisible(visibility_state.visible_widgets)
        for column, hidden in visibility_state.hidden_columns:
            mapping_tree.setColumnHidden(column, hidden)
        if visibility_state.expand_part_tools:
            mapping_tree.setColumnWidth(2, max(118, mapping_tree.columnWidth(2)))
            mapping_tree.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
            try:
                advanced_part_tools_section.set_expanded(True)
            except Exception:
                pass
        else:
            mapping_tree.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        mapping_tree.doItemsLayout()
        QTimer.singleShot(0, mapping_tree.doItemsLayout)
        QTimer.singleShot(
            0,
            lambda: _fit_alignment_tree_height_to_rows(mapping_tree, **_mapping_table_height_fit_kwargs_helper()),
        )
        QTimer.singleShot(
            0,
            lambda: _auto_fit_alignment_tree_columns(
                mapping_tree,
                _mapping_table_column_min_widths_helper(),
                _mapping_table_column_max_widths_helper(),
                expand_columns=_mapping_table_expand_columns_helper(),
            ),
        )

    def _update_mapping_status() -> None:
        source_index = _selected_source_index()
        target_index = _selected_target_index()
        source_text = _source_display_name(source_index) if source_index >= 0 else "no source selected"
        target_text = _target_display_name(target_index) if target_index >= 0 else "no target selected"
        status_lines = list(_mapping_status_selection_lines_helper(source_text, target_text))
        edit = mapping_edits_by_target.get(target_index)
        if edit is not None:
            summary, ok = _selected_source_summary(edit.text())
            source_indices = _parse_mapping_edit(edit)
            status_lines.append(_mapping_status_current_target_line_helper(summary, selection_ok=ok))
            status_lines.extend(
                _routing_effect_lines(
                    target_index,
                    source_indices,
                    selection_ok=ok,
                    selection_summary=summary,
                )
            )
            vertex_count = _mapped_target_vertex_count(source_indices)
            if vertex_count > static_replacement_vertex_limit:
                split_count, split_error = _mapping_preserve_split_group_count(source_indices)
                limit_line = _mapping_vertex_limit_status_line_helper(
                    vertex_count,
                    split_count=split_count,
                    split_error=split_error,
                    original_format=str(getattr(original_mesh_for_mapping, "format", "") or ""),
                    vertex_limit=static_replacement_vertex_limit,
                )
                if limit_line:
                    status_lines.append(limit_line)
        else:
            status_lines.extend(
                _routing_effect_lines(
                    target_index,
                    (),
                    selection_ok=True,
                    selection_summary="",
                )
            )
        dds_text = "-"
        target_physics_text = "-"
        source_physics_text = "-"
        source_indices_for_target: List[int] = []
        if edit is not None:
            source_indices_for_target = _parse_mapping_edit(edit)
            if original_mesh_for_mapping is not None and 0 <= target_index < len(original_mesh_for_mapping.submeshes):
                target = original_mesh_for_mapping.submeshes[target_index]
                target_label_text = str(getattr(target, "material", "") or getattr(target, "name", "") or target_text)
                dds_text = (
                    _removed_target_dds_cell_text(target_label_text)
                    if not source_indices_for_target
                    else _target_texture_status_text(target_label_text)
                )
                target_physics_text = _target_physics_status_text(target_label_text, target)
        elif source_index >= 0:
            dds_text = _source_outliner_dds_text(source_index)
        action_state = _mapping_status_action_state_helper(
            has_target_edit=edit is not None,
            source_index=source_index,
            source_indices_for_target=source_indices_for_target,
            preview_only_source_indices=preview_only_source_indices,
        )
        if source_index >= 0:
            source_physics_text = _source_physics_status_text(source_index, target_index)
        physics_state = _mapping_status_physics_state_helper(
            target_index=target_index,
            source_indices_for_target=source_indices_for_target,
            target_physics_text=target_physics_text,
            source_physics_text=source_physics_text,
        )
        mapping_status_label.setText(
            _mapping_status_summary_html_helper(
                _mapping_status_summary_badges_helper(
                    source_text=source_text,
                    target_text=target_text,
                    action_text=action_state["text"],
                    action_color=action_state["color"],
                    dds_text=dds_text,
                    physics_text=physics_state["text"],
                    physics_color=physics_state["color"],
                )
            )
        )
        mapping_status_label.setToolTip("\n".join(status_lines))
        route_enabled_state = _mapping_route_button_enabled_state_helper(
            source_index=source_index,
            target_index=target_index,
        )
        assign_source_button.setEnabled(route_enabled_state["assign_source"])
        merge_source_button.setEnabled(route_enabled_state["merge_source"])
        remove_source_button.setEnabled(route_enabled_state["remove_source"])
        clear_target_button.setEnabled(route_enabled_state["clear_target"])

    def _sync_target_mapping_tree_item(target_index: int) -> None:
        edit = mapping_edits_by_target.get(int(target_index))
        item = mapping_items_by_target.get(int(target_index))
        if edit is None or item is None:
            return
        committed_text = _mapping_edit_committed_text_helper(edit)
        committed_indices = _parse_mapping_edit(edit)
        summary, ok = _selected_source_summary(committed_text)
        source_cell_state = _mapping_committed_source_cell_state_helper(
            selection_ok=ok,
            has_source_indices=bool(committed_indices),
        )
        item.setText(3, _mapping_source_cell_text(summary, ok))
        item.setForeground(3, QBrush(QColor(str(source_cell_state["foreground"]))))
        item.setData(0, Qt.UserRole, tuple(committed_indices))
        item.setData(0, Qt.UserRole + 3, bool(source_cell_state["is_empty"]))
        state_text, state_color = _target_outliner_state(int(target_index), committed_indices)
        item.setText(4, state_text)
        item.setForeground(4, QBrush(QColor(state_color)))
        dds_cell_state = _mapping_target_dds_cell_state_helper(
            state_text=state_text,
            has_source_indices=bool(committed_indices),
        )
        if dds_cell_state["uses_removed_target_text"]:
            item.setText(5, _removed_target_dds_cell_text(item.text(0)))
            item.setToolTip(5, _removed_target_dds_tooltip_helper())
        else:
            item.setText(5, _target_texture_status_text(item.text(0)))
            item.setToolTip(5, _target_texture_status_details(item.text(0)))
        item.setForeground(5, QBrush(QColor(str(dds_cell_state["foreground"]))))

    def _set_mapping_indices(
        target_index: int,
        source_indices: Sequence[int],
        *,
        push_undo: bool = True,
        undo_label: str = "Change target routing",
        defer_preview: bool = False,
    ) -> None:
        edit = mapping_edits_by_target.get(target_index)
        if edit is None:
            return
        if push_undo:
            _push_geometry_undo_snapshot(undo_label)
        for source_index in source_indices:
            try:
                mapped_source_index = int(source_index)
            except (TypeError, ValueError):
                continue
            independent_output_source_indices.discard(mapped_source_index)
            preview_only_source_indices.discard(mapped_source_index)
        edit.setText(_mapping_source_indices_text_helper(source_indices))
        edit.setProperty("committed_mapping_text", edit.text().strip())
        _sync_target_mapping_tree_item(int(target_index))
        texture_overrides_dirty["dirty"] = True
        mapping_edit_refresh_timer.stop()
        _refresh_source_assignment_columns()
        _update_mapping_status()
        selection_payload = _target_mapping_selection_view_payload_helper(
            selected_target_index=int(selected_target_slot.get("index", -1)),
            target_index=int(target_index),
            source_indices=tuple(source_indices or ()),
        )
        if selection_payload is not None:
            _set_mesh_replacement_selection_view(
                **_selection_view_update_kwargs_helper(selection_payload)
            )
        _update_selection_context()
        preview_action = _source_part_routing_preview_action_helper(
            defer_preview=defer_preview,
            pending_reason="routing removal changed",
        )
        if preview_action["apply_pending"]:
            _set_source_parts_apply_pending(str(preview_action["pending_reason"]))
        elif preview_action["queue_preview"]:
            _queue_static_preview_rebuild()

    return SimpleNamespace(
        _parts_outliner_source_label=_parts_outliner_source_label,
        _parts_outliner_source_geometry=_parts_outliner_source_geometry,
        _selected_source_indices_from_tree=_selected_source_indices_from_tree,
        _set_transform_source_indices=_set_transform_source_indices,
        _clear_transform_source_indices=_clear_transform_source_indices,
        _set_source_parts_apply_pending=_set_source_parts_apply_pending,
        _clear_source_parts_apply_pending=_clear_source_parts_apply_pending,
        _set_source_parts_preview_rebuild_pending=_set_source_parts_preview_rebuild_pending,
        _clear_source_parts_preview_rebuild_pending=_clear_source_parts_preview_rebuild_pending,
        _add_source_tree_item=_add_source_tree_item,
        _source_item_check_state_changed=_source_item_check_state_changed,
        _outliner_source_index_from_item=_outliner_source_index_from_item,
        _parts_outliner_set_source_selection=_parts_outliner_set_source_selection,
        _refresh_parts_outliner=_refresh_parts_outliner,
        _show_parts_outliner_context_menu=_show_parts_outliner_context_menu,
        _apply_parts_outliner_source_target=_apply_parts_outliner_source_target,
        _parts_outliner_drop_target_index=_parts_outliner_drop_target_index,
        _handle_parts_outliner_source_drop=_handle_parts_outliner_source_drop,
        _apply_parts_outliner_source_role=_apply_parts_outliner_source_role,
        _open_parts_outliner_target_dropdown=_open_parts_outliner_target_dropdown,
        _open_parts_outliner_role_dropdown=_open_parts_outliner_role_dropdown,
        _handle_parts_outliner_item_clicked=_handle_parts_outliner_item_clicked,
        _append_mapping_target_row=_append_mapping_target_row,
        _build_mapping_table_chunk=_build_mapping_table_chunk,
        _apply_target_slot_filters=_apply_target_slot_filters,
        _ensure_mapping_table_building=_ensure_mapping_table_building,
        _clear_all_mapping_guesses=_clear_all_mapping_guesses,
        _apply_best_mapping_guesses=_apply_best_mapping_guesses,
        _preview_selected_target_slot=_preview_selected_target_slot,
        _selected_source_index=_selected_source_index,
        _selected_target_index=_selected_target_index,
        _parse_mapping_edit=_parse_mapping_edit,
        _texture_set_for_source_index=_texture_set_for_source_index,
        _source_material_group_label=_source_material_group_label,
        _mapped_target_vertex_count=_mapped_target_vertex_count,
        _mapped_source_vertex_counts=_mapped_source_vertex_counts,
        _mapping_preserve_split_group_count=_mapping_preserve_split_group_count,
        _mapping_vertex_limit_issues=_mapping_vertex_limit_issues,
        _routing_source_material_labels=_routing_source_material_labels,
        _routing_effect_lines=_routing_effect_lines,
        _set_advanced_mapping_visible=_set_advanced_mapping_visible,
        _update_mapping_status=_update_mapping_status,
        _sync_target_mapping_tree_item=_sync_target_mapping_tree_item,
        _set_mapping_indices=_set_mapping_indices,
    )


def create_alignment_d3d11_loading_callbacks(context: dict[str, object]) -> SimpleNamespace:
    Dict = context.get('Dict')
    Mapping = context.get('Mapping')
    ModelPreviewData = context.get('ModelPreviewData')
    NativePreviewPanel = context.get('NativePreviewPanel')
    Path = context.get('Path')
    QProcess = context.get('QProcess')
    QThread = context.get('QThread')
    QTimer = context.get('QTimer')
    _alignment_active_qt_camera_role_helper = context.get('_alignment_active_qt_camera_role_helper')
    _alignment_d3d11_camera_active_helper = context.get('_alignment_d3d11_camera_active_helper')
    _alignment_d3d11_clear_loading_start_helper = context.get('_alignment_d3d11_clear_loading_start_helper')
    _alignment_d3d11_clear_stuck_loading_route_helper = context.get('_alignment_d3d11_clear_stuck_loading_route_helper')
    _alignment_d3d11_ensure_loading_started_helper = context.get('_alignment_d3d11_ensure_loading_started_helper')
    _alignment_d3d11_failed_performance_helper = context.get('_alignment_d3d11_failed_performance_helper')
    _alignment_d3d11_host_ready_state_helper = context.get('_alignment_d3d11_host_ready_state_helper')
    _alignment_d3d11_live_frame_available_helper = context.get('_alignment_d3d11_live_frame_available_helper')
    _alignment_d3d11_loaded_package_transform_current_helper = context.get('_alignment_d3d11_loaded_package_transform_current_helper')
    _alignment_d3d11_loading_active_helper = context.get('_alignment_d3d11_loading_active_helper')
    _alignment_d3d11_loading_cleared_performance_helper = context.get('_alignment_d3d11_loading_cleared_performance_helper')
    _alignment_d3d11_loading_next_frame_helper = context.get('_alignment_d3d11_loading_next_frame_helper')
    _alignment_d3d11_loading_presentation_helper = context.get('_alignment_d3d11_loading_presentation_helper')
    _alignment_d3d11_loading_recovery_action_helper = context.get('_alignment_d3d11_loading_recovery_action_helper')
    _alignment_d3d11_loading_set_active_helper = context.get('_alignment_d3d11_loading_set_active_helper')
    _alignment_d3d11_loading_spinner_frames_helper = context.get('_alignment_d3d11_loading_spinner_frames_helper')
    _alignment_d3d11_loading_spinner_html_helper = context.get('_alignment_d3d11_loading_spinner_html_helper')
    _alignment_d3d11_loading_stuck_helper = context.get('_alignment_d3d11_loading_stuck_helper')
    _alignment_d3d11_loading_watchdog_snapshot_helper = context.get('_alignment_d3d11_loading_watchdog_snapshot_helper')
    _alignment_d3d11_mark_preview_unloaded_helper = context.get('_alignment_d3d11_mark_preview_unloaded_helper')
    _alignment_d3d11_pipeline_stage_helper = context.get('_alignment_d3d11_pipeline_stage_helper')
    _alignment_d3d11_progress_update_helper = context.get('_alignment_d3d11_progress_update_helper')
    _alignment_d3d11_record_stale_reload_restart_helper = context.get('_alignment_d3d11_record_stale_reload_restart_helper')
    _alignment_d3d11_request_active_helper = context.get('_alignment_d3d11_request_active_helper')
    _alignment_d3d11_reset_request_state_helper = context.get('_alignment_d3d11_reset_request_state_helper')
    _alignment_d3d11_resources_waiting_detail_helper = context.get('_alignment_d3d11_resources_waiting_detail_helper')
    _alignment_d3d11_resources_waiting_performance_details_helper = context.get('_alignment_d3d11_resources_waiting_performance_details_helper')
    _alignment_d3d11_resources_waiting_performance_helper = context.get('_alignment_d3d11_resources_waiting_performance_helper')
    _alignment_d3d11_restart_performance_helper = context.get('_alignment_d3d11_restart_performance_helper')
    _alignment_d3d11_saved_view_state_route_helper = context.get('_alignment_d3d11_saved_view_state_route_helper')
    _alignment_d3d11_stale_loading_detail_helper = context.get('_alignment_d3d11_stale_loading_detail_helper')
    _alignment_d3d11_stop_process = context.get('_alignment_d3d11_stop_process')
    _alignment_d3d11_view_state_payload_route_helper = context.get('_alignment_d3d11_view_state_payload_route_helper')
    _alignment_d3d11_watchdog_ready_performance_helper = context.get('_alignment_d3d11_watchdog_ready_performance_helper')
    _alignment_dialog_widgets_live = context.get('_alignment_dialog_widgets_live')
    _alignment_preview_mode_key_helper = context.get('_alignment_preview_mode_key_helper')
    _alignment_preview_mode_saved_state_helper = context.get('_alignment_preview_mode_saved_state_helper')
    _alignment_preview_quality_label_helper = context.get('_alignment_preview_quality_label_helper')
    _alignment_preview_view_sync_should_apply_helper = context.get('_alignment_preview_view_sync_should_apply_helper')
    _clear_alignment_d3d11_fast_transform_state = context.get('_clear_alignment_d3d11_fast_transform_state')
    _current_alignment_preview_render_settings = context.get('_current_alignment_preview_render_settings')
    _fixed_alignment_camera_state_helper = context.get('_fixed_alignment_camera_state_helper')
    _get_preview_render_settings = context.get('_get_preview_render_settings')
    _nudged_alignment_camera_state_helper = context.get('_nudged_alignment_camera_state_helper')
    _qt_alignment_camera_state_mapping_helper = context.get('_qt_alignment_camera_state_mapping_helper')
    _qt_alignment_camera_tuple_helper = context.get('_qt_alignment_camera_tuple_helper')
    _qt_object_is_valid = context.get('_qt_object_is_valid')
    _queue_latest_alignment_d3d11_rebuild_for_stale_reload = context.get('_queue_latest_alignment_d3d11_rebuild_for_stale_reload')
    _record_runtime_event = context.get('_record_runtime_event')
    _replay_alignment_d3d11_fast_transform = context.get('_replay_alignment_d3d11_fast_transform')
    _safe_alignment_timer_active = context.get('_safe_alignment_timer_active')
    _safe_start_alignment_timer = context.get('_safe_start_alignment_timer')
    _safe_stop_alignment_timer = context.get('_safe_stop_alignment_timer')
    _set_preview_performance_status = context.get('_set_preview_performance_status')
    _sync_highlight_sets = context.get('_sync_highlight_sets')
    alignment_d3d11_available = context.get('alignment_d3d11_available')
    alignment_d3d11_drag_transaction = context.get('alignment_d3d11_drag_transaction') or {}
    alignment_d3d11_loading_spinner_label = context.get('alignment_d3d11_loading_spinner_label')
    alignment_d3d11_loading_state = context.get('alignment_d3d11_loading_state')
    alignment_d3d11_loading_timer = context.get('alignment_d3d11_loading_timer')
    alignment_d3d11_preview_host = context.get('alignment_d3d11_preview_host')
    alignment_d3d11_preview_status_label = context.get('alignment_d3d11_preview_status_label')
    alignment_d3d11_reload_stuck_timeout_s = context.get('alignment_d3d11_reload_stuck_timeout_s')
    alignment_d3d11_state = context.get('alignment_d3d11_state')
    alignment_d3d11_view_state = context.get('alignment_d3d11_view_state')
    alignment_preview_mode_view_states = context.get('alignment_preview_mode_view_states')
    alignment_preview_view_sync = context.get('alignment_preview_view_sync')
    alignment_transform_generation = context.get('alignment_transform_generation') or {}
    dialog_title = context.get('dialog_title')
    entry = context.get('entry')
    original_dialog_preview = context.get('original_dialog_preview')
    overlay_dialog_preview = context.get('overlay_dialog_preview')
    preview_mode_combo = context.get('preview_mode_combo')
    preview_render_settings = context.get('preview_render_settings')
    preview_renderer_combo = context.get('preview_renderer_combo')
    replacement_only_preview = context.get('replacement_only_preview')
    self = context.get('self')
    static_dialog_preview = context.get('static_dialog_preview')
    time = context.get('time')

    def _set_preview_performance_status_if_ready(summary: str, *, details: str = "") -> None:
        if callable(_set_preview_performance_status):
            _set_preview_performance_status(summary, details=details)

    def _current_alignment_preview_render_settings_value():
        if callable(_current_alignment_preview_render_settings):
            return _current_alignment_preview_render_settings()
        if callable(_get_preview_render_settings):
            return _get_preview_render_settings()
        if preview_render_settings is not None:
            return preview_render_settings
        return self._current_model_preview_render_settings()

    def _tick_alignment_d3d11_loading_spinner() -> None:
        if not _alignment_dialog_widgets_live() or not _qt_object_is_valid(alignment_d3d11_loading_spinner_label):
            return
        frames = _alignment_d3d11_loading_spinner_frames_helper()
        frame_index = _alignment_d3d11_loading_next_frame_helper(
            alignment_d3d11_loading_state,
            len(frames),
        )
        alignment_d3d11_loading_spinner_label.setText(
            _alignment_d3d11_loading_spinner_html_helper(frames[frame_index])
        )
        try:
            if _alignment_d3d11_loading_stuck():
                _clear_stuck_alignment_d3d11_loading("loading watchdog")
        except NameError:
            pass

    def _set_alignment_d3d11_loading(active: bool, message: str = "", *, detail: str = "") -> None:
        active = _alignment_d3d11_loading_set_active_helper(alignment_d3d11_loading_state, active)
        presentation = _alignment_d3d11_loading_presentation_helper(
            active,
            message=message,
            detail=detail,
        )
        if not _alignment_dialog_widgets_live():
            _alignment_d3d11_loading_set_active_helper(alignment_d3d11_loading_state, False)
            _alignment_d3d11_clear_loading_start_helper(alignment_d3d11_state)
            inactive_presentation = _alignment_d3d11_loading_presentation_helper(False)
            try:
                _safe_stop_alignment_timer(alignment_d3d11_loading_timer)
                if _qt_object_is_valid(alignment_d3d11_loading_spinner_label):
                    alignment_d3d11_loading_spinner_label.setVisible(inactive_presentation.spinner_visible)
                    if inactive_presentation.clear_spinner_text:
                        alignment_d3d11_loading_spinner_label.setText("")
            except RuntimeError:
                pass
            return
        if presentation.status_text:
            alignment_d3d11_preview_status_label.setText(presentation.status_text)
        if presentation.status_tooltip:
            alignment_d3d11_preview_status_label.setToolTip(presentation.status_tooltip)
        if active:
            _alignment_d3d11_ensure_loading_started_helper(alignment_d3d11_state, time.perf_counter())
            alignment_d3d11_loading_spinner_label.setVisible(presentation.spinner_visible)
            if not _safe_alignment_timer_active(alignment_d3d11_loading_timer):
                _tick_alignment_d3d11_loading_spinner()
                _safe_start_alignment_timer(alignment_d3d11_loading_timer)
        else:
            _alignment_d3d11_clear_loading_start_helper(alignment_d3d11_state)
            _safe_stop_alignment_timer(alignment_d3d11_loading_timer)
            alignment_d3d11_loading_spinner_label.setVisible(presentation.spinner_visible)
            if presentation.clear_spinner_text:
                alignment_d3d11_loading_spinner_label.setText("")

    def _set_alignment_d3d11_progress(
        percent: int,
        message: str,
        *,
        request_id: int = 0,
        stage: str = "",
        detail: str = "",
        active: bool = True,
    ) -> None:
        if int(request_id or 0) > 0 and int(request_id or 0) != int(alignment_d3d11_state.get("request_id", 0) or 0):
            return
        message_text, tooltip_text, loading_active = _alignment_d3d11_progress_update_helper(
            alignment_d3d11_state,
            percent,
            message,
            stage=stage,
            detail=detail,
            active=active,
        )
        _set_alignment_d3d11_loading(
            loading_active,
            message_text,
            detail=tooltip_text,
        )

    def _set_alignment_d3d11_pipeline_stage(stage: str, detail: str = "") -> None:
        normalized = _alignment_d3d11_pipeline_stage_helper(alignment_d3d11_state, stage)
        if detail:
            _record_runtime_event(
                "alignment_d3d11_preview_pipeline_stage",
                path=getattr(entry, "path", ""),
                dialog_title=dialog_title,
                stage=normalized,
                detail=str(detail or ""),
            )

    alignment_d3d11_loading_timer.timeout.connect(_tick_alignment_d3d11_loading_spinner)

    def _reset_alignment_d3d11_request_state(
        *,
        increment_request: bool = True,
        clear_loading: bool = False,
        message: str = "",
    ) -> None:
        _alignment_d3d11_reset_request_state_helper(
            alignment_d3d11_state,
            increment_request=increment_request,
            clear_loading=clear_loading,
        )
        if clear_loading:
            _set_alignment_d3d11_loading(False, message or "Preview idle.")

    def _alignment_d3d11_request_active() -> bool:
        process = alignment_d3d11_state.get("process")
        process_active = isinstance(process, QProcess) and process.state() != QProcess.NotRunning
        thread = alignment_d3d11_state.get("thread")
        thread_active = isinstance(thread, QThread) and thread.isRunning()
        queued_model_active = isinstance(alignment_d3d11_state.get("queued_model"), ModelPreviewData)
        pending_model_active = isinstance(alignment_d3d11_state.get("pending_model"), ModelPreviewData)
        active_package = alignment_d3d11_state.get("active_package")
        active_package_exists = isinstance(active_package, Path) and active_package.exists()
        return _alignment_d3d11_request_active_helper(
            process_active=process_active,
            thread_active=thread_active,
            queued_model_active=queued_model_active,
            pending_model_active=pending_model_active,
            active_package_exists=active_package_exists,
        )

    def _alignment_d3d11_live_frame_available() -> bool:
        process = alignment_d3d11_state.get("process")
        active_package = alignment_d3d11_state.get("active_package")
        return _alignment_d3d11_live_frame_available_helper(
            alignment_d3d11_state,
            process_active=isinstance(process, QProcess) and process.state() != QProcess.NotRunning,
            active_package_exists=isinstance(active_package, Path) and active_package.exists(),
        )

    def _alignment_d3d11_host_ready(*, require_child: bool = False) -> tuple[bool, str]:
        if not _alignment_dialog_widgets_live():
            return False, "alignment dialog is closing"
        try:
            parent_hwnd = alignment_d3d11_preview_host.winId()
            child_hwnd = 0
            if require_child:
                child_hwnd_getter = getattr(alignment_d3d11_preview_host, "_host_hwnd", None)
                child_hwnd = child_hwnd_getter() if callable(child_hwnd_getter) else 0
            host_ready_state = _alignment_d3d11_host_ready_state_helper(
                dialog_live=_alignment_dialog_widgets_live(),
                host_visible=alignment_d3d11_preview_host.isVisible(),
                width=alignment_d3d11_preview_host.width(),
                height=alignment_d3d11_preview_host.height(),
                parent_hwnd=parent_hwnd,
                child_hwnd=child_hwnd,
                require_child=require_child,
            )
        except Exception as exc:
            host_ready_state = _alignment_d3d11_host_ready_state_helper(
                dialog_live=True,
                host_visible=True,
                width=0,
                height=0,
                parent_hwnd=0,
                require_child=require_child,
                check_error=exc,
            )
        return host_ready_state.ready, host_ready_state.detail

    def _alignment_d3d11_loading_stuck() -> bool:
        loading_active = _alignment_d3d11_loading_active_helper(alignment_d3d11_loading_state)
        if bool(alignment_d3d11_state.get("preview_loaded")):
            if isinstance(alignment_d3d11_state.get("queued_model"), ModelPreviewData):
                return False
            if isinstance(alignment_d3d11_state.get("pending_model"), ModelPreviewData):
                return False
            thread = alignment_d3d11_state.get("thread")
            thread_active = False
            if isinstance(thread, QThread):
                try:
                    if thread.isRunning():
                        return False
                    thread_active = False
                except RuntimeError:
                    return False
            return _alignment_d3d11_loading_stuck_helper(
                loading_active=loading_active,
                preview_loaded=True,
                queued_model_active=False,
                pending_model_active=False,
                thread_active=thread_active,
                loading_started_at=0.0,
                loading_elapsed_s=0.0,
                timeout_s=alignment_d3d11_reload_stuck_timeout_s,
                request_active=False,
                process_active=False,
                active_package_exists=False,
            )
        started_at = float(alignment_d3d11_state.get("loading_started_at", 0.0) or 0.0)
        elapsed_s = time.perf_counter() - started_at if started_at > 0.0 else 0.0
        request_active = _alignment_d3d11_request_active()
        process = alignment_d3d11_state.get("process")
        process_active = isinstance(process, QProcess) and process.state() != QProcess.NotRunning
        active_package = alignment_d3d11_state.get("active_package")
        active_package_exists = isinstance(active_package, Path) and active_package.exists()
        return _alignment_d3d11_loading_stuck_helper(
            loading_active=loading_active,
            preview_loaded=False,
            queued_model_active=False,
            pending_model_active=False,
            thread_active=False,
            loading_started_at=started_at,
            loading_elapsed_s=elapsed_s,
            timeout_s=alignment_d3d11_reload_stuck_timeout_s,
            request_active=request_active,
            process_active=process_active,
            active_package_exists=active_package_exists,
        )

    def _clear_stuck_alignment_d3d11_loading(reason: str) -> None:
        if not _alignment_dialog_widgets_live():
            closed_action = _alignment_d3d11_loading_recovery_action_helper(
                _alignment_d3d11_clear_stuck_loading_route_helper(
                    dialog_live=False,
                    preview_loaded=False,
                    resources_loaded=False,
                    process_active=False,
                    active_package_exists=False,
                    host_ready=False,
                    child_ready=False,
                    restart_count=0,
                    drag_active=False,
                )
            )
            if closed_action.should_mark_preview_unloaded:
                _alignment_d3d11_mark_preview_unloaded_helper(alignment_d3d11_state)
            if closed_action.should_set_loading_inactive:
                _alignment_d3d11_loading_set_active_helper(alignment_d3d11_loading_state, False)
                _alignment_d3d11_clear_loading_start_helper(alignment_d3d11_state)
            _safe_stop_alignment_timer(alignment_d3d11_loading_timer)
            return
        process = alignment_d3d11_state.get("process")
        active_package = alignment_d3d11_state.get("active_package")
        process_active = isinstance(process, QProcess) and process.state() != QProcess.NotRunning
        package_active = isinstance(active_package, Path) and active_package.exists()
        watchdog_snapshot = _alignment_d3d11_loading_watchdog_snapshot_helper(
            alignment_d3d11_state,
            now_s=time.perf_counter(),
        )
        host_ready = False
        host_detail = ""
        child_ready = False
        child_detail = ""
        if not watchdog_snapshot.preview_loaded:
            host_ready, host_detail = _alignment_d3d11_host_ready(require_child=False)
            child_ready, child_detail = _alignment_d3d11_host_ready(require_child=True)
        clear_route = _alignment_d3d11_clear_stuck_loading_route_helper(
            dialog_live=True,
            preview_loaded=watchdog_snapshot.preview_loaded,
            resources_loaded=watchdog_snapshot.resources_loaded,
            process_active=process_active,
            active_package_exists=package_active,
            host_ready=host_ready,
            child_ready=child_ready,
            restart_count=watchdog_snapshot.restart_count,
            drag_active=bool(alignment_d3d11_drag_transaction.get("active")),
        )
        recovery_action = _alignment_d3d11_loading_recovery_action_helper(clear_route)
        if recovery_action.should_reset_request_idle:
            _reset_alignment_d3d11_request_state(
                increment_request=False,
                clear_loading=True,
                message=recovery_action.loading_message,
            )
            loading_cleared_presentation = _alignment_d3d11_loading_cleared_performance_helper(reason)
            _set_preview_performance_status_if_ready(
                loading_cleared_presentation.summary,
                details=loading_cleared_presentation.details,
            )
            return
        if recovery_action.should_restore_loaded_preview:
            alignment_d3d11_preview_host.set_display_mode(str(preview_mode_combo.currentData() or "side_by_side"))
            alignment_d3d11_preview_host.set_render_tuning(_current_alignment_preview_render_settings_value())
            saved_view_state = _alignment_d3d11_saved_view_state()
            if saved_view_state:
                alignment_d3d11_preview_host.restore_view_state(saved_view_state)
            if _alignment_d3d11_loaded_package_transform_current_helper(
                alignment_d3d11_state,
                alignment_transform_generation,
                request_id=watchdog_snapshot.active_request_id,
            ):
                if callable(_clear_alignment_d3d11_fast_transform_state):
                    _clear_alignment_d3d11_fast_transform_state(reset_host=True)
            if callable(_sync_highlight_sets):
                _sync_highlight_sets()
            if callable(_replay_alignment_d3d11_fast_transform):
                _replay_alignment_d3d11_fast_transform()
            _set_alignment_d3d11_progress(100, recovery_action.progress_message, active=False)
            watchdog_ready_presentation = _alignment_d3d11_watchdog_ready_performance_helper(
                quality_label=_alignment_preview_quality_label_helper(alignment_d3d11_state),
                reason=reason,
                active_package=active_package,
            )
            _set_preview_performance_status_if_ready(
                watchdog_ready_presentation.summary,
                details=watchdog_ready_presentation.details,
            )
            return
        if recovery_action.action == "resources_waiting":
            waiting_detail = _alignment_d3d11_resources_waiting_detail_helper(
                reason=reason,
                elapsed_s=watchdog_snapshot.elapsed_s,
                last_percent=watchdog_snapshot.last_percent,
                last_stage=watchdog_snapshot.last_stage,
                host_detail=host_detail,
                child_detail=child_detail,
                active_package=active_package,
            )
            waiting_performance_details = _alignment_d3d11_resources_waiting_performance_details_helper(
                reason=reason,
                elapsed_s=watchdog_snapshot.elapsed_s,
                host_detail=host_detail,
                child_detail=child_detail,
                active_package=active_package,
            )
            waiting_performance = _alignment_d3d11_resources_waiting_performance_helper(waiting_performance_details)
            _set_alignment_d3d11_loading(
                False,
                recovery_action.loading_message,
                detail=waiting_detail,
            )
            _set_preview_performance_status_if_ready(
                waiting_performance.summary,
                details=waiting_performance.details,
            )
            return
        stale_details = _alignment_d3d11_stale_loading_detail_helper(
            reason=reason,
            elapsed_s=watchdog_snapshot.elapsed_s,
            last_percent=watchdog_snapshot.last_percent,
            last_stage=watchdog_snapshot.last_stage,
            host_detail=host_detail,
            child_detail=child_detail,
            active_package=active_package,
        )
        if recovery_action.should_record_restart:
            _alignment_d3d11_record_stale_reload_restart_helper(alignment_d3d11_state)
        if recovery_action.action == "restart":
            _set_alignment_d3d11_loading(
                False,
                recovery_action.loading_message,
                detail=stale_details,
            )
            restart_presentation = _alignment_d3d11_restart_performance_helper(
                quality_label=_alignment_preview_quality_label_helper(alignment_d3d11_state),
                stale_details=stale_details,
                restart_count=watchdog_snapshot.restart_count,
            )
            _set_preview_performance_status_if_ready(
                restart_presentation.summary,
                details=restart_presentation.details,
            )
            if recovery_action.should_stop_process:
                _alignment_d3d11_stop_process()
            QTimer.singleShot(
                0,
                lambda expected_request=watchdog_snapshot.active_request_id: _queue_latest_alignment_d3d11_rebuild_for_stale_reload(expected_request),
            )
            return
        _set_alignment_d3d11_loading(
            False,
            recovery_action.loading_message,
            detail=stale_details,
        )
        failed_presentation = _alignment_d3d11_failed_performance_helper(
            quality_label=_alignment_preview_quality_label_helper(alignment_d3d11_state),
            stale_details=stale_details,
        )
        _set_preview_performance_status_if_ready(
            failed_presentation.summary,
            details=failed_presentation.details,
        )

    def _handle_alignment_d3d11_view_state_payload(payload: object) -> None:
        current_generation = int(getattr(self, "mesh_editor_d3d11_view_state_reset_generation", 0) or 0)
        view_state_route = _alignment_d3d11_view_state_payload_route_helper(
            alignment_d3d11_state,
            current_generation,
            payload_is_mapping=isinstance(payload, Mapping),
        )
        if view_state_route.should_ignore:
            return
        if view_state_route.should_clear_saved_state:
            alignment_d3d11_view_state.clear()
        if not view_state_route.should_store_snapshot:
            return
        alignment_d3d11_view_state.update(
            self._sanitize_d3d11_view_state_for_restore(alignment_d3d11_preview_host.view_state_snapshot())
        )

    alignment_d3d11_preview_host.view_state_payload_changed.connect(_handle_alignment_d3d11_view_state_payload)

    def _alignment_d3d11_saved_view_state() -> Dict[str, object]:
        current_generation = int(getattr(self, "mesh_editor_d3d11_view_state_reset_generation", 0) or 0)
        saved_route = _alignment_d3d11_saved_view_state_route_helper(
            alignment_d3d11_state,
            current_generation,
            has_saved_state=bool(alignment_d3d11_view_state),
        )
        if saved_route.should_clear_saved_state:
            alignment_d3d11_view_state.clear()
            return {}
        if not saved_route.should_return_saved_state:
            return {}
        return self._sanitize_d3d11_view_state_for_restore(alignment_d3d11_view_state)

    def _sync_alignment_preview_view_state(source_widget: NativePreviewPanel, *target_widgets: NativePreviewPanel) -> None:
        if not _alignment_preview_view_sync_should_apply_helper(
            alignment_preview_view_sync,
            preview_mode_combo.currentData(),
        ):
            return
        state = source_widget.view_state_snapshot()
        alignment_preview_view_sync["active"] = True
        try:
            for target_widget in target_widgets:
                target_widget.restore_view_state(state)
        finally:
            alignment_preview_view_sync["active"] = False

    original_dialog_preview.view_state_changed.connect(
        lambda *_args: _sync_alignment_preview_view_state(original_dialog_preview, static_dialog_preview)
    )
    static_dialog_preview.view_state_changed.connect(
        lambda *_args: _sync_alignment_preview_view_state(static_dialog_preview, original_dialog_preview)
    )

    def _alignment_d3d11_camera_active() -> bool:
        return _alignment_d3d11_camera_active_helper(
            preview_renderer_combo.currentData(),
            bool(alignment_d3d11_available),
        )

    def _alignment_active_qt_camera_widgets() -> tuple[NativePreviewPanel, ...]:
        active_role = _alignment_active_qt_camera_role_helper(preview_mode_combo.currentData())
        if active_role == "replacement_only":
            return (replacement_only_preview,)
        if active_role == "overlay":
            return (overlay_dialog_preview,)
        return (original_dialog_preview, static_dialog_preview)

    def _alignment_current_camera_state() -> Dict[str, object]:
        if _alignment_d3d11_camera_active():
            return self._sanitize_d3d11_view_state_for_restore(
                alignment_d3d11_preview_host.view_state_snapshot()
            )
        widgets = _alignment_active_qt_camera_widgets()
        state = widgets[0].view_state_snapshot() if widgets else replacement_only_preview.view_state_snapshot()
        return _qt_alignment_camera_state_mapping_helper(state, role="replacement")

    def _apply_alignment_camera_state(state: Mapping[str, object]) -> None:
        if _alignment_d3d11_camera_active():
            alignment_d3d11_preview_host.restore_view_state(state)
            return
        qt_state = _qt_alignment_camera_tuple_helper(state, fit_distance=NativePreviewPanel._FIT_DISTANCE)
        for preview_widget in (
            original_dialog_preview,
            static_dialog_preview,
            overlay_dialog_preview,
            replacement_only_preview,
        ):
            preview_widget.restore_view_state(qt_state)

    def _save_alignment_preview_mode_view_state(mode: str) -> None:
        try:
            alignment_preview_mode_view_states[_alignment_preview_mode_key_helper(mode)] = _alignment_current_camera_state()
        except Exception:
            pass

    def _restore_alignment_preview_mode_view_state(mode: str) -> None:
        state = _alignment_preview_mode_saved_state_helper(alignment_preview_mode_view_states, mode)
        if state is not None:
            _apply_alignment_camera_state(state)

    def _set_alignment_camera(yaw: float, pitch: float) -> None:
        state = _alignment_current_camera_state()
        state.update(_fixed_alignment_camera_state_helper(yaw, pitch, role="replacement"))
        if _alignment_d3d11_camera_active():
            alignment_d3d11_preview_host.set_view(
                yaw=float(yaw),
                pitch=float(pitch),
                zoom_factor=1.0,
                fit_to_view=True,
                pan=(0.0, 0.0, 0.0),
            )
            return
        _apply_alignment_camera_state(state)

    def _nudge_alignment_camera(delta_yaw: float = 0.0, delta_pitch: float = 0.0) -> None:
        state = _alignment_current_camera_state()
        _apply_alignment_camera_state(
            _nudged_alignment_camera_state_helper(
                state,
                delta_yaw=delta_yaw,
                delta_pitch=delta_pitch,
                role="replacement",
            )
        )

    return SimpleNamespace(
        _tick_alignment_d3d11_loading_spinner=_tick_alignment_d3d11_loading_spinner,
        _set_alignment_d3d11_loading=_set_alignment_d3d11_loading,
        _set_alignment_d3d11_progress=_set_alignment_d3d11_progress,
        _set_alignment_d3d11_pipeline_stage=_set_alignment_d3d11_pipeline_stage,
        _reset_alignment_d3d11_request_state=_reset_alignment_d3d11_request_state,
        _alignment_d3d11_request_active=_alignment_d3d11_request_active,
        _alignment_d3d11_live_frame_available=_alignment_d3d11_live_frame_available,
        _alignment_d3d11_host_ready=_alignment_d3d11_host_ready,
        _alignment_d3d11_loading_stuck=_alignment_d3d11_loading_stuck,
        _clear_stuck_alignment_d3d11_loading=_clear_stuck_alignment_d3d11_loading,
        _handle_alignment_d3d11_view_state_payload=_handle_alignment_d3d11_view_state_payload,
        _alignment_d3d11_saved_view_state=_alignment_d3d11_saved_view_state,
        _sync_alignment_preview_view_state=_sync_alignment_preview_view_state,
        _alignment_d3d11_camera_active=_alignment_d3d11_camera_active,
        _alignment_active_qt_camera_widgets=_alignment_active_qt_camera_widgets,
        _alignment_current_camera_state=_alignment_current_camera_state,
        _apply_alignment_camera_state=_apply_alignment_camera_state,
        _save_alignment_preview_mode_view_state=_save_alignment_preview_mode_view_state,
        _restore_alignment_preview_mode_view_state=_restore_alignment_preview_mode_view_state,
        _set_alignment_camera=_set_alignment_camera,
        _nudge_alignment_camera=_nudge_alignment_camera,
    )


def create_alignment_refresh_queue_callbacks(context: dict[str, object]) -> SimpleNamespace:
    Callable = context.get('Callable')
    Dict = context.get('Dict')
    ModelPreviewData = context.get('ModelPreviewData')
    ModelPreviewRenderSettings = context.get('ModelPreviewRenderSettings')
    Optional = context.get('Optional')
    Path = context.get('Path')
    QApplication = context.get('QApplication')
    QProcess = context.get('QProcess')
    QThread = context.get('QThread')
    QTimer = context.get('QTimer')
    QTreeWidget = context.get('QTreeWidget')
    Sequence = context.get('Sequence')
    StaticSourcePartAdjustment = context.get('StaticSourcePartAdjustment')
    _alignment_d3d11_clear_fast_transform_state_helper = context.get('_alignment_d3d11_clear_fast_transform_state_helper')
    _alignment_d3d11_invalidate_package_cache = context.get('_alignment_d3d11_invalidate_package_cache')
    _alignment_d3d11_mark_rebuild_reason_helper = context.get('_alignment_d3d11_mark_rebuild_reason_helper')
    _alignment_d3d11_mark_transform_changed_helper = context.get('_alignment_d3d11_mark_transform_changed_helper')
    _alignment_d3d11_package_refresh_in_flight_helper = context.get('_alignment_d3d11_package_refresh_in_flight_helper')
    _alignment_d3d11_preview_active = context.get('_alignment_d3d11_preview_active')
    _alignment_d3d11_selection_highlight_performance_helper = context.get('_alignment_d3d11_selection_highlight_performance_helper')
    _alignment_d3d11_stop_worker = context.get('_alignment_d3d11_stop_worker')
    _alignment_dialog_widgets_live = context.get('_alignment_dialog_widgets_live')
    _alignment_mesh_edit_tab_active = context.get('_alignment_mesh_edit_tab_active')
    _alignment_preview_background_source_face_limit_for_total = context.get('_alignment_preview_background_source_face_limit_for_total')
    _alignment_preview_is_interactive_helper = context.get('_alignment_preview_is_interactive_helper')
    _alignment_preview_requested_source_indices_helper = context.get('_alignment_preview_requested_source_indices_helper')
    _alignment_preview_selected_source_face_limit_for_total = context.get('_alignment_preview_selected_source_face_limit_for_total')
    _alignment_preview_source_face_limit_for_counts = context.get('_alignment_preview_source_face_limit_for_counts')
    _alignment_preview_source_face_total_helper = context.get('_alignment_preview_source_face_total_helper')
    _alignment_preview_widget_render_settings_helper = context.get('_alignment_preview_widget_render_settings_helper')
    _auto_fit_tree_columns_helper = context.get('_auto_fit_tree_columns_helper')
    _capture_static_preview_baked_transform_state_helper = context.get('_capture_static_preview_baked_transform_state_helper')
    _configure_alignment_tree_helper = context.get('_configure_alignment_tree_helper')
    _configure_texture_mapping_tree_helper = context.get('_configure_texture_mapping_tree_helper')
    _current_alignment_preview_render_settings = context.get('_current_alignment_preview_render_settings')
    _current_alignment_transform_generation_helper = context.get('_current_alignment_transform_generation_helper')
    _get_preview_render_settings = context.get('_get_preview_render_settings')
    _fit_tree_height_to_rows_helper = context.get('_fit_tree_height_to_rows_helper')
    _install_tree_column_autofit_helper = context.get('_install_tree_column_autofit_helper')
    _material_edit_refresh_queued_performance_helper = context.get('_material_edit_refresh_queued_performance_helper')
    _material_edit_refresh_queued_progress_message_helper = context.get('_material_edit_refresh_queued_progress_message_helper')
    _material_edit_refresh_running_performance_helper = context.get('_material_edit_refresh_running_performance_helper')
    _material_edit_refresh_running_progress_message_helper = context.get('_material_edit_refresh_running_progress_message_helper')
    _mesh_edit_raw_preview_active_helper = context.get('_mesh_edit_raw_preview_active_helper')
    _mesh_edit_raw_preview_initial_state_helper = context.get('_mesh_edit_raw_preview_initial_state_helper')
    _queue_alignment_post_open_task_helper = context.get('_queue_alignment_post_open_task_helper')
    _queue_material_edit_refresh_state_helper = context.get('_queue_material_edit_refresh_state_helper')
    _queue_source_material_plan_refresh_state_helper = context.get('_queue_source_material_plan_refresh_state_helper')
    _record_runtime_event = context.get('_record_runtime_event')
    _refresh_source_material_plan = context.get('_refresh_source_material_plan')
    _run_alignment_post_open_tasks_helper = context.get('_run_alignment_post_open_tasks_helper')
    _safe_stop_alignment_timer = context.get('_safe_stop_alignment_timer')
    _set_alignment_d3d11_progress = context.get('_set_alignment_d3d11_progress')
    _set_preview_performance_status = context.get('_set_preview_performance_status')
    _source_part_transform_values_helper = context.get('_source_part_transform_values_helper')
    _source_parts_selection_pending_presentation_helper = context.get('_source_parts_selection_pending_presentation_helper')
    _spinbox_transform_values_helper = context.get('_spinbox_transform_values_helper')
    _static_preview_batch_queue_request_helper = context.get('_static_preview_batch_queue_request_helper')
    _sync_highlight_sets = context.get('_sync_highlight_sets')
    _take_material_edit_refresh_state_helper = context.get('_take_material_edit_refresh_state_helper')
    _take_source_material_plan_refresh_state_helper = context.get('_take_source_material_plan_refresh_state_helper')
    alignment_d3d11_drag_transaction = context.get('alignment_d3d11_drag_transaction') or {}
    alignment_d3d11_preview_host = context.get('alignment_d3d11_preview_host')
    alignment_d3d11_reload_timer = context.get('alignment_d3d11_reload_timer')
    alignment_d3d11_state = context.get('alignment_d3d11_state')
    alignment_post_open_state = context.get('alignment_post_open_state')
    alignment_post_open_tasks = context.get('alignment_post_open_tasks')
    alignment_transform_generation = context.get('alignment_transform_generation')
    alignment_tree_event_filters = context.get('alignment_tree_event_filters')
    control_tabs = context.get('control_tabs')
    defer_original_texture_preview = context.get('defer_original_texture_preview')
    dialog = context.get('dialog')
    dialog_title = context.get('dialog_title')
    entry = context.get('entry')
    make_tree_columns_persistent = context.get('make_tree_columns_persistent')
    material_edit_refresh_state = context.get('material_edit_refresh_state')
    material_edit_refresh_timer = context.get('material_edit_refresh_timer')
    mesh_edit_enabled_checkbox = context.get('mesh_edit_enabled_checkbox')
    modify_original_clone_mode = context.get('modify_original_clone_mode')
    offset_x_spin = context.get('offset_x_spin')
    offset_y_spin = context.get('offset_y_spin')
    offset_z_spin = context.get('offset_z_spin')
    preview_render_settings = context.get('preview_render_settings')
    replacement_mesh_base_for_mapping = context.get('replacement_mesh_base_for_mapping')
    replacement_mesh_for_mapping = context.get('replacement_mesh_for_mapping')
    rotate_x_spin = context.get('rotate_x_spin')
    rotate_y_spin = context.get('rotate_y_spin')
    rotate_z_spin = context.get('rotate_z_spin')
    scale_x_spin = context.get('scale_x_spin')
    scale_y_spin = context.get('scale_y_spin')
    scale_z_spin = context.get('scale_z_spin')
    selected_source_part = context.get('selected_source_part')
    self = context.get('self')
    source_geometry_revision = context.get('source_geometry_revision')
    source_material_plan_refresh_state = context.get('source_material_plan_refresh_state')
    source_material_plan_refresh_timer = context.get('source_material_plan_refresh_timer')
    source_part_adjustments = context.get('source_part_adjustments')
    source_parts_apply_state = context.get('source_parts_apply_state')
    static_preview_baked_transform_state = context.get('static_preview_baked_transform_state')
    static_preview_batch_state = context.get('static_preview_batch_state')
    static_preview_geometry_cache = context.get('static_preview_geometry_cache')
    static_preview_interactive_until = context.get('static_preview_interactive_until')
    static_preview_prepared_cache = context.get('static_preview_prepared_cache')
    static_preview_refresh_timer = context.get('static_preview_refresh_timer')
    static_preview_settle_timer = context.get('static_preview_settle_timer')
    texture_material_plan_loaded = context.get('texture_material_plan_loaded')
    texture_overrides_dirty = context.get('texture_overrides_dirty')
    textures_tab = context.get('textures_tab')
    time = context.get('time')

    def _d3d11_preview_active() -> bool:
        if not callable(_alignment_d3d11_preview_active):
            return False
        return bool(_alignment_d3d11_preview_active())

    def _queue_alignment_post_open_task(callback: Callable[[], None]) -> None:
        _queue_alignment_post_open_task_helper(
            alignment_post_open_state,
            alignment_post_open_tasks,
            callback,
            schedule=QTimer.singleShot,
        )

    def _run_alignment_post_open_tasks() -> None:
        _run_alignment_post_open_tasks_helper(
            alignment_post_open_state,
            alignment_post_open_tasks,
            schedule=QTimer.singleShot,
        )

    def _load_original_reference_texture_preview() -> None:
        return

    _global_transform_values = lambda: _spinbox_transform_values_helper(
            (offset_x_spin, offset_y_spin, offset_z_spin),
            (rotate_x_spin, rotate_y_spin, rotate_z_spin),
            (scale_x_spin, scale_y_spin, scale_z_spin),
            catch_runtime=True,
        )

    _part_transform_values = lambda source_index: _source_part_transform_values_helper(
        source_part_adjustments,
        source_index,
        StaticSourcePartAdjustment,
    )

    _current_alignment_transform_generation = lambda: _current_alignment_transform_generation_helper(
        alignment_transform_generation
    )

    def _current_alignment_preview_render_settings_value():
        if callable(_current_alignment_preview_render_settings):
            return _current_alignment_preview_render_settings()
        if callable(_get_preview_render_settings):
            return _get_preview_render_settings()
        if preview_render_settings is not None:
            return preview_render_settings
        return self._current_model_preview_render_settings()

    def _mark_alignment_transform_changed() -> int:
        generation = _alignment_d3d11_mark_transform_changed_helper(
            alignment_d3d11_state,
            alignment_transform_generation,
        )
        _safe_stop_alignment_timer(alignment_d3d11_reload_timer)
        stop_worker = _alignment_d3d11_stop_worker
        if not callable(stop_worker):
            stop_worker = context.get("_alignment_d3d11_stop_worker")
        if callable(stop_worker):
            stop_worker()
        return generation

    def _clear_alignment_d3d11_fast_transform_state(*, reset_host: bool = False) -> None:
        _alignment_d3d11_clear_fast_transform_state_helper(alignment_d3d11_state)
        if reset_host and not bool(alignment_d3d11_drag_transaction.get("active")):
            try:
                alignment_d3d11_preview_host.set_alignment_preview_transforms()
            except Exception:
                pass

    def _alignment_d3d11_package_refresh_in_flight() -> bool:
        queued_model_active = isinstance(alignment_d3d11_state.get("queued_model"), ModelPreviewData)
        pending_model_active = isinstance(alignment_d3d11_state.get("pending_model"), ModelPreviewData)
        thread_active = False
        thread = alignment_d3d11_state.get("thread")
        if isinstance(thread, QThread):
            try:
                thread_active = bool(thread.isRunning())
            except RuntimeError:
                thread_active = True
        process_active = False
        process = alignment_d3d11_state.get("process")
        if isinstance(process, QProcess):
            try:
                process_active = process.state() != QProcess.NotRunning
            except RuntimeError:
                process_active = True
        active_package = alignment_d3d11_state.get("active_package")
        if not callable(_alignment_d3d11_package_refresh_in_flight_helper):
            return False
        preview_active = (
            bool(_d3d11_preview_active())
            if callable(_alignment_d3d11_preview_active)
            else False
        )
        return _alignment_d3d11_package_refresh_in_flight_helper(
            alignment_d3d11_state,
            preview_active=preview_active,
            queued_model_active=queued_model_active,
            pending_model_active=pending_model_active,
            thread_active=thread_active,
            process_active=process_active,
            active_package_exists=isinstance(active_package, Path) and active_package.exists(),
            committed_transform_generation=int(alignment_transform_generation.get("committed", 0) or 0),
        )

    def _capture_static_preview_baked_transform_state(
        selected_preview_indices: Optional[Sequence[int]] = None,
        *,
        transform_generation: Optional[int] = None,
    ) -> None:
        capture_generation = (
            int(transform_generation)
            if transform_generation is not None
            else _current_alignment_transform_generation()
        )
        part_state: Dict[int, object] = {}
        if replacement_mesh_for_mapping is not None:
            for source_index in range(len(getattr(replacement_mesh_for_mapping, "submeshes", ()) or ())):
                part_state[source_index] = _part_transform_values(source_index)
        _capture_static_preview_baked_transform_state_helper(
            static_preview_baked_transform_state,
            global_values=_global_transform_values(),
            part_values=part_state,
            selected_preview_indices=selected_preview_indices,
            transform_generation=capture_generation,
        )
        committed_generation = int(alignment_transform_generation.get("committed", 0) or 0)
        if not bool(alignment_d3d11_drag_transaction.get("active")) and capture_generation >= committed_generation:
            if not _alignment_d3d11_package_refresh_in_flight():
                _clear_alignment_d3d11_fast_transform_state(reset_host=True)

    _alignment_preview_is_interactive = lambda: _alignment_preview_is_interactive_helper(
        static_preview_interactive_until
    )

    _mesh_edit_raw_preview_active = lambda: _mesh_edit_raw_preview_active_helper(
        mesh_edit_enabled_checkbox,
        _alignment_mesh_edit_tab_active,
    )

    def _mesh_edit_enabled_checked() -> bool:
        is_checked = getattr(mesh_edit_enabled_checkbox, "isChecked", None)
        if not callable(is_checked):
            return False
        try:
            return bool(is_checked())
        except RuntimeError:
            return False

    mesh_edit_raw_preview_state = _mesh_edit_raw_preview_initial_state_helper()

    def _alignment_preview_widget_render_settings() -> ModelPreviewRenderSettings:
        settings = _current_alignment_preview_render_settings_value()
        return _alignment_preview_widget_render_settings_helper(
            settings,
            interactive=_alignment_preview_is_interactive(),
        )

    def _alignment_preview_source_face_limit() -> int:
        if _mesh_edit_enabled_checked():
            return 0
        mesh = replacement_mesh_for_mapping or replacement_mesh_base_for_mapping
        if mesh is None:
            return 0
        submesh_face_counts = [
            len(getattr(submesh, "faces", ()) or ())
            for submesh in getattr(mesh, "submeshes", ()) or ()
            if len(getattr(submesh, "faces", ()) or ()) > 0
        ]
        appended_geometry = 0
        if modify_original_clone_mode:
            appended_geometry = int(source_geometry_revision.get("value", 0) or 0)
        try:
            d3d11_normal_active = _d3d11_preview_active()
        except NameError:
            d3d11_normal_active = False
        return _alignment_preview_source_face_limit_for_counts(
            tuple(submesh_face_counts),
            modify_original_clone_mode=bool(modify_original_clone_mode),
            appended_geometry=appended_geometry,
            d3d11_normal_active=bool(d3d11_normal_active),
            interactive=_alignment_preview_is_interactive(),
        )

    def _alignment_preview_selected_source_face_limit(source_indices: Sequence[int]) -> int:
        if _mesh_edit_enabled_checked():
            return 0
        mesh = replacement_mesh_for_mapping or replacement_mesh_base_for_mapping
        if mesh is None:
            return _alignment_preview_source_face_limit()
        requested_indices = _alignment_preview_requested_source_indices_helper(mesh, source_indices)
        if not requested_indices:
            return _alignment_preview_source_face_limit()
        total_faces = _alignment_preview_source_face_total_helper(mesh, requested_indices)
        selected_source_index = int(selected_source_part.get("index", -1))
        selected_requested = selected_source_index in requested_indices
        return _alignment_preview_selected_source_face_limit_for_total(
            total_faces,
            selected_requested=selected_requested,
            interactive=_alignment_preview_is_interactive(),
            fallback_limit=_alignment_preview_source_face_limit(),
        )

    def _alignment_preview_background_source_face_limit(source_indices: Sequence[int]) -> int:
        if _mesh_edit_enabled_checked() and callable(_alignment_mesh_edit_tab_active) and _alignment_mesh_edit_tab_active():
            return 0
        mesh = replacement_mesh_for_mapping or replacement_mesh_base_for_mapping
        if mesh is None:
            return _alignment_preview_source_face_limit()
        requested_indices = _alignment_preview_requested_source_indices_helper(mesh, source_indices)
        if not requested_indices:
            return _alignment_preview_source_face_limit()
        total_faces = _alignment_preview_source_face_total_helper(mesh, requested_indices)
        return _alignment_preview_background_source_face_limit_for_total(
            total_faces,
            interactive=_alignment_preview_is_interactive(),
            fallback_limit=_alignment_preview_source_face_limit(),
        )

    def _configure_alignment_tree(
        tree: QTreeWidget,
        widths: Sequence[int],
        *,
        max_height: int = 0,
        stretch_columns: Sequence[int] = (),
        persist_key: str = "",
    ) -> None:
        _configure_alignment_tree_helper(
            tree,
            widths,
            max_height=max_height,
            stretch_columns=stretch_columns,
            persist_key=persist_key,
            settings=self.settings,
            save_callback=self.schedule_settings_save,
            persist_columns=make_tree_columns_persistent,
        )

    def _configure_texture_mapping_tree(tree: QTreeWidget, *, persist_key: str = "") -> None:
        _configure_texture_mapping_tree_helper(
            tree,
            persist_key=persist_key,
            settings=self.settings,
            save_callback=self.schedule_settings_save,
            persist_columns=make_tree_columns_persistent,
        )

    def _fit_alignment_tree_height_to_rows(
        tree: QTreeWidget,
        *,
        minimum: int,
        screen_margin: int,
        maximum: int = 0,
    ) -> None:
        _fit_tree_height_to_rows_helper(
            tree,
            minimum=minimum,
            screen_margin=screen_margin,
            maximum=maximum,
            screen_provider=lambda: dialog.screen() or self.screen() or QApplication.primaryScreen(),
        )

    def _auto_fit_alignment_tree_columns(
        tree: QTreeWidget,
        minimums: Sequence[int],
        maximums: Sequence[int],
        *,
        expand_column: int = -1,
        expand_columns: Sequence[int] = (),
    ) -> None:
        _auto_fit_tree_columns_helper(
            tree,
            minimums,
            maximums,
            expand_column=expand_column,
            expand_columns=expand_columns,
        )

    def _install_alignment_tree_column_autofit(
        tree: QTreeWidget,
        minimums: Sequence[int],
        maximums: Sequence[int],
        *,
        expand_column: int = -1,
        expand_columns: Sequence[int] = (),
    ) -> None:
        _install_tree_column_autofit_helper(
            tree,
            minimums,
            maximums,
            expand_column=expand_column,
            expand_columns=expand_columns,
            event_filters=alignment_tree_event_filters,
        )

    def _mark_alignment_d3d11_rebuild_reason(reason: str) -> None:
        _alignment_d3d11_mark_rebuild_reason_helper(alignment_d3d11_state, reason)

    def _queue_static_preview_refresh(*_args: object) -> None:
        _mark_alignment_d3d11_rebuild_reason("geometry")
        if _static_preview_batch_queue_request_helper(static_preview_batch_state, "refresh"):
            _record_runtime_event(
                "mesh_alignment_static_preview_refresh_batched",
                path=getattr(entry, "path", ""),
                dialog_title=dialog_title,
                modify_original_clone=modify_original_clone_mode,
            )
            return
        _record_runtime_event(
            "mesh_alignment_static_preview_refresh_queued",
            path=getattr(entry, "path", ""),
            dialog_title=dialog_title,
            d3d11_preview_active=bool(_d3d11_preview_active()),
            next_rebuild_reason=str(alignment_d3d11_state.get("next_rebuild_reason", "") or ""),
            modify_original_clone=modify_original_clone_mode,
        )
        static_preview_refresh_timer.start()

    def _queue_selection_preview_refresh(*_args: object) -> None:
        def _set_preview_performance_status_if_ready(summary: str, *, details: str = "") -> None:
            if callable(_set_preview_performance_status):
                _set_preview_performance_status(summary, details=details)

        if bool(source_parts_apply_state.get("pending")):
            if callable(_sync_highlight_sets):
                _sync_highlight_sets()
            reason = str(source_parts_apply_state.get("reason", "") or "part changes").strip()
            if callable(_source_parts_selection_pending_presentation_helper):
                presentation = _source_parts_selection_pending_presentation_helper(reason)
                _set_preview_performance_status_if_ready(
                    presentation.performance_summary,
                    details=presentation.performance_details,
                )
            return
        if _d3d11_preview_active():
            if callable(_sync_highlight_sets):
                _sync_highlight_sets()
            if callable(_alignment_d3d11_selection_highlight_performance_helper):
                performance = _alignment_d3d11_selection_highlight_performance_helper()
                _set_preview_performance_status_if_ready(
                    performance.summary,
                    details=performance.details,
                )
            return
        if callable(_sync_highlight_sets):
            _sync_highlight_sets()
        _queue_static_preview_refresh()

    def _queue_static_preview_rebuild(*_args: object) -> None:
        _mark_alignment_d3d11_rebuild_reason("geometry")
        if _static_preview_batch_queue_request_helper(static_preview_batch_state, "rebuild"):
            return
        static_preview_interactive_until["time"] = time.monotonic() + 0.8
        static_preview_settle_timer.start()
        static_preview_refresh_timer.start()

    def _queue_texture_preview_refresh(*_args: object) -> None:
        _mark_alignment_d3d11_rebuild_reason("material")
        if _static_preview_batch_queue_request_helper(static_preview_batch_state, "texture"):
            return
        if callable(_alignment_d3d11_invalidate_package_cache):
            _alignment_d3d11_invalidate_package_cache("material")
        texture_overrides_dirty["dirty"] = True
        static_preview_refresh_timer.start()

    def _queue_texture_uv_preview_refresh(*_args: object) -> None:
        _mark_alignment_d3d11_rebuild_reason("texture_uv")
        if _static_preview_batch_queue_request_helper(static_preview_batch_state, "texture_uv"):
            return
        static_preview_geometry_cache.clear()
        static_preview_prepared_cache.clear()
        if callable(_alignment_d3d11_invalidate_package_cache):
            _alignment_d3d11_invalidate_package_cache("texture_uv")
        texture_overrides_dirty["dirty"] = True
        static_preview_refresh_timer.start()

    def _queue_material_edit_refresh(
        *,
        refresh_plan: bool = False,
        force_plan: bool = False,
        refresh_preview: bool = True,
        reason: str = "material edit",
    ) -> None:
        if not _alignment_dialog_widgets_live():
            return
        queued_reason = _queue_material_edit_refresh_state_helper(
            material_edit_refresh_state,
            refresh_plan=refresh_plan,
            force_plan=force_plan,
            refresh_preview=refresh_preview,
            reason=reason,
        )
        texture_overrides_dirty["dirty"] = True
        queued_performance = _material_edit_refresh_queued_performance_helper(queued_reason)
        _set_preview_performance_status(
            queued_performance.summary,
            details=queued_performance.details,
        )
        try:
            _set_alignment_d3d11_progress(
                5,
                _material_edit_refresh_queued_progress_message_helper(queued_reason),
                stage="material_edit_queued",
                active=False,
            )
        except RuntimeError:
            pass
        material_edit_refresh_timer.start()

    def _queue_source_material_plan_refresh(
        *,
        force_plan: bool = False,
        reason: str = "material edit",
    ) -> None:
        if not _alignment_dialog_widgets_live():
            return
        _queue_source_material_plan_refresh_state_helper(
            source_material_plan_refresh_state,
            force_plan=force_plan,
            reason=reason,
        )
        source_material_plan_refresh_timer.start()

    def _run_source_material_plan_refresh() -> None:
        if not _alignment_dialog_widgets_live():
            return
        source_plan_refresh = _take_source_material_plan_refresh_state_helper(source_material_plan_refresh_state)
        force_plan = bool(source_plan_refresh["force_plan"])
        reason = str(source_plan_refresh["reason"])
        try:
            material_tab_active = control_tabs.currentWidget() is textures_tab
        except (NameError, RuntimeError):
            material_tab_active = False
        if not material_tab_active:
            texture_material_plan_loaded["loaded"] = False
            _record_runtime_event(
                "mesh_alignment_source_material_plan_deferred",
                path=getattr(entry, "path", ""),
                dialog_title=dialog_title,
                reason=reason,
                force_plan=force_plan,
                modify_original_clone=modify_original_clone_mode,
            )
            return
        started_at = time.perf_counter()
        try:
            _refresh_source_material_plan(force=force_plan)
        except TypeError:
            _refresh_source_material_plan()
        except NameError:
            return
        _record_runtime_event(
            "mesh_alignment_source_material_plan_refresh",
            path=getattr(entry, "path", ""),
            dialog_title=dialog_title,
            reason=reason,
            force_plan=force_plan,
            elapsed_ms=int((time.perf_counter() - started_at) * 1000),
            modify_original_clone=modify_original_clone_mode,
        )

    def _run_material_edit_refresh() -> None:
        if not _alignment_dialog_widgets_live():
            return
        material_refresh = _take_material_edit_refresh_state_helper(material_edit_refresh_state)
        refresh_plan = bool(material_refresh["refresh_plan"])
        force_plan = bool(material_refresh["force_plan"])
        refresh_preview = bool(material_refresh["refresh_preview"])
        reason = str(material_refresh["reason"])
        started_at = time.perf_counter()
        running_performance = _material_edit_refresh_running_performance_helper(reason)
        _set_preview_performance_status(
            running_performance.summary,
            details=running_performance.details,
        )
        try:
            _set_alignment_d3d11_progress(
                20,
                _material_edit_refresh_running_progress_message_helper(reason),
                stage="material_edit_refresh",
                active=False,
            )
        except RuntimeError:
            pass
        if refresh_preview:
            _queue_texture_preview_refresh()
        if refresh_plan:
            _queue_source_material_plan_refresh(force_plan=force_plan, reason=reason)
        _record_runtime_event(
            "mesh_alignment_material_edit_refresh",
            path=getattr(entry, "path", ""),
            dialog_title=dialog_title,
            reason=reason,
            refresh_plan=refresh_plan,
            force_plan=force_plan,
            refresh_preview=refresh_preview,
            elapsed_ms=int((time.perf_counter() - started_at) * 1000),
            modify_original_clone=modify_original_clone_mode,
            defer_original_texture_preview=defer_original_texture_preview,
        )

    return SimpleNamespace(
        _queue_alignment_post_open_task=_queue_alignment_post_open_task,
        _run_alignment_post_open_tasks=_run_alignment_post_open_tasks,
        _load_original_reference_texture_preview=_load_original_reference_texture_preview,
        _mark_alignment_transform_changed=_mark_alignment_transform_changed,
        _clear_alignment_d3d11_fast_transform_state=_clear_alignment_d3d11_fast_transform_state,
        _alignment_d3d11_package_refresh_in_flight=_alignment_d3d11_package_refresh_in_flight,
        _capture_static_preview_baked_transform_state=_capture_static_preview_baked_transform_state,
        _alignment_preview_widget_render_settings=_alignment_preview_widget_render_settings,
        _alignment_preview_source_face_limit=_alignment_preview_source_face_limit,
        _alignment_preview_selected_source_face_limit=_alignment_preview_selected_source_face_limit,
        _alignment_preview_background_source_face_limit=_alignment_preview_background_source_face_limit,
        _configure_alignment_tree=_configure_alignment_tree,
        _configure_texture_mapping_tree=_configure_texture_mapping_tree,
        _fit_alignment_tree_height_to_rows=_fit_alignment_tree_height_to_rows,
        _auto_fit_alignment_tree_columns=_auto_fit_alignment_tree_columns,
        _install_alignment_tree_column_autofit=_install_alignment_tree_column_autofit,
        _mark_alignment_d3d11_rebuild_reason=_mark_alignment_d3d11_rebuild_reason,
        _queue_static_preview_refresh=_queue_static_preview_refresh,
        _queue_selection_preview_refresh=_queue_selection_preview_refresh,
        _queue_static_preview_rebuild=_queue_static_preview_rebuild,
        _queue_texture_preview_refresh=_queue_texture_preview_refresh,
        _queue_texture_uv_preview_refresh=_queue_texture_uv_preview_refresh,
        _queue_material_edit_refresh=_queue_material_edit_refresh,
        _queue_source_material_plan_refresh=_queue_source_material_plan_refresh,
        _run_source_material_plan_refresh=_run_source_material_plan_refresh,
        _run_material_edit_refresh=_run_material_edit_refresh,
    )


def create_alignment_d3d11_package_lifecycle_callbacks(context: dict[str, object]) -> SimpleNamespace:
    AlignmentD3D11PackageWorker = context.get('AlignmentD3D11PackageWorker')
    Dict = context.get('Dict')
    MODEL_PREVIEW_BACKGROUND_COLOR = context.get('MODEL_PREVIEW_BACKGROUND_COLOR')
    MODEL_PREVIEW_TEXT_COLOR = context.get('MODEL_PREVIEW_TEXT_COLOR')
    Mapping = context.get('Mapping')
    MeshPreviewCacheSignature = context.get('MeshPreviewCacheSignature')
    ModelPreviewData = context.get('ModelPreviewData')
    ModelPreviewRenderSettings = context.get('ModelPreviewRenderSettings')
    Optional = context.get('Optional')
    Path = context.get('Path')
    QObject = context.get('QObject')
    QProcess = context.get('QProcess')
    QThread = context.get('QThread')
    QTimer = context.get('QTimer')
    Qt = context.get('Qt')
    ReplacementTextureSet = context.get('ReplacementTextureSet')
    Slot = context.get('Slot')
    _AlignmentD3D11PackageWorkerReceiver = context.get('_AlignmentD3D11PackageWorkerReceiver')
    _active_tab_is_helper = context.get('_active_tab_is_helper')
    _alignment_d3d11_active_package_matches_helper = context.get('_alignment_d3d11_active_package_matches_helper')
    _alignment_d3d11_active_package_snapshot_helper = context.get('_alignment_d3d11_active_package_snapshot_helper')
    _alignment_d3d11_begin_archive_parity_upgrade_helper = context.get('_alignment_d3d11_begin_archive_parity_upgrade_helper')
    _alignment_d3d11_begin_package_request_helper = context.get('_alignment_d3d11_begin_package_request_helper')
    _alignment_d3d11_cache_display_class_helper = context.get('_alignment_d3d11_cache_display_class_helper')
    _alignment_d3d11_cache_key_with_native_reference_helper = context.get('_alignment_d3d11_cache_key_with_native_reference_helper')
    _alignment_d3d11_cached_loading_performance_helper = context.get('_alignment_d3d11_cached_loading_performance_helper')
    _alignment_d3d11_cached_loading_progress_detail_helper = context.get('_alignment_d3d11_cached_loading_progress_detail_helper')
    _alignment_d3d11_cached_renderer_reload_detail_helper = context.get('_alignment_d3d11_cached_renderer_reload_detail_helper')
    _alignment_d3d11_cached_reuse_performance_helper = context.get('_alignment_d3d11_cached_reuse_performance_helper')
    _alignment_d3d11_clear_active_package_helper = context.get('_alignment_d3d11_clear_active_package_helper')
    _alignment_d3d11_clear_archive_parity_upgrade_helper = context.get('_alignment_d3d11_clear_archive_parity_upgrade_helper')
    _alignment_d3d11_clear_package_worker_refs_helper = context.get('_alignment_d3d11_clear_package_worker_refs_helper')
    _alignment_d3d11_clear_pending_process_retry_helper = context.get('_alignment_d3d11_clear_pending_process_retry_helper')
    _alignment_d3d11_clear_process_status_refs_helper = context.get('_alignment_d3d11_clear_process_status_refs_helper')
    _alignment_d3d11_clear_queued_preview_request_helper = context.get('_alignment_d3d11_clear_queued_preview_request_helper')
    _alignment_d3d11_closed_status_route_helper = context.get('_alignment_d3d11_closed_status_route_helper')
    _alignment_d3d11_dirty_flags_for_reason = context.get('_alignment_d3d11_dirty_flags_for_reason')
    _alignment_d3d11_drag_reload_stale_helper = context.get('_alignment_d3d11_drag_reload_stale_helper')
    _alignment_d3d11_editor_ids_for_source_indices_helper = context.get('_alignment_d3d11_editor_ids_for_source_indices_helper')
    _alignment_d3d11_error_status_route_helper = context.get('_alignment_d3d11_error_status_route_helper')
    _alignment_d3d11_geometry_cache_key_helper = context.get('_alignment_d3d11_geometry_cache_key_helper')
    _alignment_d3d11_host_ready = context.get('_alignment_d3d11_host_ready')
    _alignment_d3d11_invalid_status_payload_route_helper = context.get('_alignment_d3d11_invalid_status_payload_route_helper')
    _alignment_d3d11_invalidate_package_cache_helper = context.get('_alignment_d3d11_invalidate_package_cache_helper')
    _alignment_d3d11_live_frame_available = context.get('_alignment_d3d11_live_frame_available')
    _alignment_d3d11_loaded_package_transform_current_helper = context.get('_alignment_d3d11_loaded_package_transform_current_helper')
    _alignment_d3d11_loaded_status_route_helper = context.get('_alignment_d3d11_loaded_status_route_helper')
    _alignment_d3d11_loaded_timing_presentation_helper = context.get('_alignment_d3d11_loaded_timing_presentation_helper')
    _alignment_d3d11_loading_status_route_helper = context.get('_alignment_d3d11_loading_status_route_helper')
    _alignment_d3d11_loading_stuck = context.get('_alignment_d3d11_loading_stuck')
    _alignment_d3d11_mark_active_cached_package_reused_helper = context.get('_alignment_d3d11_mark_active_cached_package_reused_helper')
    _alignment_d3d11_mark_loaded_package_helper = context.get('_alignment_d3d11_mark_loaded_package_helper')
    _alignment_d3d11_mark_loading_started_helper = context.get('_alignment_d3d11_mark_loading_started_helper')
    _alignment_d3d11_mark_preview_loaded_helper = context.get('_alignment_d3d11_mark_preview_loaded_helper')
    _alignment_d3d11_mark_preview_unloaded_helper = context.get('_alignment_d3d11_mark_preview_unloaded_helper')
    _alignment_d3d11_mark_resources_loaded_helper = context.get('_alignment_d3d11_mark_resources_loaded_helper')
    _alignment_d3d11_material_cache_key_helper = context.get('_alignment_d3d11_material_cache_key_helper')
    _alignment_d3d11_model_cache_signature_helper = context.get('_alignment_d3d11_model_cache_signature_helper')
    _alignment_d3d11_package_cache_get_helper = context.get('_alignment_d3d11_package_cache_get_helper')
    _alignment_d3d11_package_cache_put_helper = context.get('_alignment_d3d11_package_cache_put_helper')
    _alignment_d3d11_package_drop_cleanup_state_helper = context.get('_alignment_d3d11_package_drop_cleanup_state_helper')
    _alignment_d3d11_package_failed_performance_helper = context.get('_alignment_d3d11_package_failed_performance_helper')
    _alignment_d3d11_package_is_cached_helper = context.get('_alignment_d3d11_package_is_cached_helper')
    _alignment_d3d11_package_loading_detail_helper = context.get('_alignment_d3d11_package_loading_detail_helper')
    _alignment_d3d11_package_preparing_performance_helper = context.get('_alignment_d3d11_package_preparing_performance_helper')
    _alignment_d3d11_package_quality_helper = context.get('_alignment_d3d11_package_quality_helper')
    _alignment_d3d11_package_ready_route_helper = context.get('_alignment_d3d11_package_ready_route_helper')
    _alignment_d3d11_package_start_route_helper = context.get('_alignment_d3d11_package_start_route_helper')
    _alignment_d3d11_pending_host_performance_helper = context.get('_alignment_d3d11_pending_host_performance_helper')
    _alignment_d3d11_prepare_active_package_helper = context.get('_alignment_d3d11_prepare_active_package_helper')
    _alignment_d3d11_process_finished_route_helper = context.get('_alignment_d3d11_process_finished_route_helper')
    _alignment_d3d11_process_request_metadata_helper = context.get('_alignment_d3d11_process_request_metadata_helper')
    _alignment_d3d11_process_reuse_state_helper = context.get('_alignment_d3d11_process_reuse_state_helper')
    _alignment_d3d11_process_start_route_helper = context.get('_alignment_d3d11_process_start_route_helper')
    _alignment_d3d11_queue_pending_request_helper = context.get('_alignment_d3d11_queue_pending_request_helper')
    _alignment_d3d11_queue_preview_request_helper = context.get('_alignment_d3d11_queue_preview_request_helper')
    _alignment_d3d11_queued_latest_preview_reload_detail_helper = context.get('_alignment_d3d11_queued_latest_preview_reload_detail_helper')
    _alignment_d3d11_queued_preview_reload_detail_helper = context.get('_alignment_d3d11_queued_preview_reload_detail_helper')
    _alignment_d3d11_record_cache_hit_metadata_helper = context.get('_alignment_d3d11_record_cache_hit_metadata_helper')
    _alignment_d3d11_record_cache_lookup_result_helper = context.get('_alignment_d3d11_record_cache_lookup_result_helper')
    _alignment_d3d11_record_package_request_metadata_helper = context.get('_alignment_d3d11_record_package_request_metadata_helper')
    _alignment_d3d11_record_package_timing_helper = context.get('_alignment_d3d11_record_package_timing_helper')
    _alignment_d3d11_record_package_worker_refs_helper = context.get('_alignment_d3d11_record_package_worker_refs_helper')
    _alignment_d3d11_record_pending_process_retry_helper = context.get('_alignment_d3d11_record_pending_process_retry_helper')
    _alignment_d3d11_record_process_ref_helper = context.get('_alignment_d3d11_record_process_ref_helper')
    _alignment_d3d11_record_status_payload_helper = context.get('_alignment_d3d11_record_status_payload_helper')
    _alignment_d3d11_reload_queued_performance_helper = context.get('_alignment_d3d11_reload_queued_performance_helper')
    _alignment_d3d11_remember_request_cache_key_helper = context.get('_alignment_d3d11_remember_request_cache_key_helper')
    _alignment_d3d11_remember_request_package_quality_helper = context.get('_alignment_d3d11_remember_request_package_quality_helper')
    _alignment_d3d11_renderer_error_message_helper = context.get('_alignment_d3d11_renderer_error_message_helper')
    _alignment_d3d11_renderer_error_performance_helper = context.get('_alignment_d3d11_renderer_error_performance_helper')
    _alignment_d3d11_renderer_host_restart_performance_helper = context.get('_alignment_d3d11_renderer_host_restart_performance_helper')
    _alignment_d3d11_request_reason_helper = context.get('_alignment_d3d11_request_reason_helper')
    _alignment_d3d11_reset_material_parity_state_helper = context.get('_alignment_d3d11_reset_material_parity_state_helper')
    _alignment_d3d11_reset_request_state_helper = context.get('_alignment_d3d11_reset_request_state_helper')
    _alignment_d3d11_resources_loaded_status_route_helper = context.get('_alignment_d3d11_resources_loaded_status_route_helper')
    _alignment_d3d11_restore_active_package_helper = context.get('_alignment_d3d11_restore_active_package_helper')
    _alignment_d3d11_saved_view_state = context.get('_alignment_d3d11_saved_view_state')
    _alignment_d3d11_source_indices_for_editor_id_helper = context.get('_alignment_d3d11_source_indices_for_editor_id_helper')
    _alignment_d3d11_stale_package_dropped_detail_helper = context.get('_alignment_d3d11_stale_package_dropped_detail_helper')
    _alignment_d3d11_stale_package_dropped_performance_helper = context.get('_alignment_d3d11_stale_package_dropped_performance_helper')
    _alignment_d3d11_stale_reload_route_helper = context.get('_alignment_d3d11_stale_reload_route_helper')
    _alignment_d3d11_start_timeout_route_helper = context.get('_alignment_d3d11_start_timeout_route_helper')
    _alignment_d3d11_starting_performance_helper = context.get('_alignment_d3d11_starting_performance_helper')
    _alignment_d3d11_startup_timeout_performance_helper = context.get('_alignment_d3d11_startup_timeout_performance_helper')
    _alignment_d3d11_status_event_helper = context.get('_alignment_d3d11_status_event_helper')
    _alignment_d3d11_status_read_error_route_helper = context.get('_alignment_d3d11_status_read_error_route_helper')
    _alignment_d3d11_store_package_cache_helper = context.get('_alignment_d3d11_store_package_cache_helper')
    _alignment_d3d11_take_pending_request_helper = context.get('_alignment_d3d11_take_pending_request_helper')
    _alignment_d3d11_texture_flip_v_live_performance_helper = context.get('_alignment_d3d11_texture_flip_v_live_performance_helper')
    _alignment_d3d11_theme_payload_helper = context.get('_alignment_d3d11_theme_payload_helper')
    _alignment_d3d11_unavailable_performance_helper = context.get('_alignment_d3d11_unavailable_performance_helper')
    _alignment_d3d11_unavailable_status_route_helper = context.get('_alignment_d3d11_unavailable_status_route_helper')
    _alignment_d3d11_waiting_for_preview_panel_detail_helper = context.get('_alignment_d3d11_waiting_for_preview_panel_detail_helper')
    _alignment_default_d3d11_editor_ids_helper = context.get('_alignment_default_d3d11_editor_ids_helper')
    _alignment_dialog_widgets_live = context.get('_alignment_dialog_widgets_live')
    _alignment_file_signature = context.get('_alignment_file_signature')
    _alignment_preview_quality_label_helper = context.get('_alignment_preview_quality_label_helper')
    _alignment_sample_sequence = context.get('_alignment_sample_sequence')
    _alignment_sequence_digest = context.get('_alignment_sequence_digest')
    _apply_source_material_texture_overrides_to_texture_sets_helper = context.get('_apply_source_material_texture_overrides_to_texture_sets_helper')
    _apply_source_part_role_overrides = context.get('_apply_source_part_role_overrides')
    _clear_alignment_d3d11_fast_transform_state = context.get('_clear_alignment_d3d11_fast_transform_state')
    _clear_source_parts_preview_rebuild_pending = context.get('_clear_source_parts_preview_rebuild_pending')
    _clear_stuck_alignment_d3d11_loading = context.get('_clear_stuck_alignment_d3d11_loading')
    _clone_preview_model = context.get('_clone_preview_model')
    _combine_preview_models = context.get('_combine_preview_models')
    _current_alignment_preview_render_settings = context.get('_current_alignment_preview_render_settings')
    _current_alignment_transform_generation = context.get('_current_alignment_transform_generation')
    _current_donor_material_plans = context.get('_current_donor_material_plans')
    _current_source_material_texture_overrides = context.get('_current_source_material_texture_overrides')
    _d3d11_cache_event_user_label = context.get('_d3d11_cache_event_user_label')
    _d3d11_status_file_signature = context.get('_d3d11_status_file_signature')
    _donor_material_plan_payload_helper = context.get('_donor_material_plan_payload_helper')
    _get_preview_render_settings = context.get('_get_preview_render_settings')
    _global_flip_v_fast_preview_value_helper = context.get('_global_flip_v_fast_preview_value_helper')
    _load_original_reference_texture_preview = context.get('_load_original_reference_texture_preview')
    _mark_alignment_d3d11_rebuild_reason = context.get('_mark_alignment_d3d11_rebuild_reason')
    _mesh_edit_raw_preview_active = context.get('_mesh_edit_raw_preview_active')
    _model_bounds_x = context.get('_model_bounds_x')
    _original_reference_texture_preview_archive_parity_state_helper = context.get('_original_reference_texture_preview_archive_parity_state_helper')
    _queue_static_preview_refresh = context.get('_queue_static_preview_refresh')
    _record_runtime_event = context.get('_record_runtime_event')
    _replay_alignment_d3d11_fast_transform = context.get('_replay_alignment_d3d11_fast_transform')
    _safe_start_alignment_timer = context.get('_safe_start_alignment_timer')
    _safe_stop_alignment_timer = context.get('_safe_stop_alignment_timer')
    _set_alignment_d3d11_loading = context.get('_set_alignment_d3d11_loading')
    _set_alignment_d3d11_pipeline_stage = context.get('_set_alignment_d3d11_pipeline_stage')
    _set_alignment_d3d11_progress = context.get('_set_alignment_d3d11_progress')
    _set_preview_performance_status = context.get('_set_preview_performance_status')
    _source_index_is_enabled_renderable = context.get('_source_index_is_enabled_renderable')
    _stop_original_reference_texture_worker = context.get('_stop_original_reference_texture_worker')
    _sync_highlight_sets = context.get('_sync_highlight_sets')
    _sync_mesh_edit_preview_settings = context.get('_sync_mesh_edit_preview_settings')
    _texture_uv_fast_preview_record_global_flip_v_helper = context.get('_texture_uv_fast_preview_record_global_flip_v_helper')
    _texture_uv_state_has_edits = context.get('_texture_uv_state_has_edits')
    _tint_preview_model = context.get('_tint_preview_model')
    _translated_preview_model = context.get('_translated_preview_model')
    alignment_d3d11_available = context.get('alignment_d3d11_available')
    alignment_d3d11_drag_generation = context.get('alignment_d3d11_drag_generation')
    alignment_d3d11_drag_transaction = context.get('alignment_d3d11_drag_transaction') or {}
    alignment_d3d11_drag_ui_timer = context.get('alignment_d3d11_drag_ui_timer')
    alignment_d3d11_fast_reload_interval_ms = context.get('alignment_d3d11_fast_reload_interval_ms')
    alignment_d3d11_loading_timer = context.get('alignment_d3d11_loading_timer')
    alignment_d3d11_package_reload_interval_ms = context.get('alignment_d3d11_package_reload_interval_ms')
    alignment_d3d11_preview_host = context.get('alignment_d3d11_preview_host')
    alignment_d3d11_preview_page = context.get('alignment_d3d11_preview_page')
    alignment_d3d11_preview_status_label = context.get('alignment_d3d11_preview_status_label')
    alignment_d3d11_reload_timer = context.get('alignment_d3d11_reload_timer')
    alignment_d3d11_state = context.get('alignment_d3d11_state')
    alignment_d3d11_status_timer = context.get('alignment_d3d11_status_timer')
    alignment_d3d11_texture_uv_fast_state = context.get('alignment_d3d11_texture_uv_fast_state')
    alignment_dialog_key_hash = context.get('alignment_dialog_key_hash')
    alignment_preview_control_text = context.get('alignment_preview_control_text')
    alignment_transform_generation = context.get('alignment_transform_generation') or {}
    control_tabs = context.get('control_tabs')
    dialog = context.get('dialog')
    dialog_title = context.get('dialog_title')
    hashlib = context.get('hashlib')
    json = context.get('json')
    entry = context.get('entry')
    material_authority_preview_signature_state = context.get('material_authority_preview_signature_state')
    mesh_edit_tab = context.get('mesh_edit_tab')
    modify_original_clone_mode = context.get('modify_original_clone_mode')
    original_reference_preview_model = context.get('original_reference_preview_model')
    original_reference_texture_preview_state = context.get('original_reference_texture_preview_state')
    parts_tab = context.get('parts_tab')
    preview_mode_combo = context.get('preview_mode_combo')
    preview_render_settings = context.get('preview_render_settings')
    preview_renderer_combo = context.get('preview_renderer_combo')
    preview_stack = context.get('preview_stack')
    replacement_mesh_for_mapping = context.get('replacement_mesh_for_mapping')
    self = context.get('self')
    shutil = context.get('shutil')
    source_part_adjustments = context.get('source_part_adjustments')
    static_preview_geometry_cache = context.get('static_preview_geometry_cache')
    static_preview_prepared_cache = context.get('static_preview_prepared_cache')
    static_preview_refresh_timer = context.get('static_preview_refresh_timer')
    texture_overrides_dirty = context.get('texture_overrides_dirty')
    texture_uv_global_transform_state = context.get('texture_uv_global_transform_state')
    texture_uv_transform_state = context.get('texture_uv_transform_state')
    time = context.get('time')
    transform_source_indices = context.get('transform_source_indices')

    def _apply_source_material_texture_overrides_to_ui_texture_sets(
        texture_sets_by_key: Dict[str, ReplacementTextureSet],
    ) -> None:
        _apply_source_material_texture_overrides_to_texture_sets_helper(
            texture_sets_by_key,
            _current_source_material_texture_overrides(),
            replacement_mesh=replacement_mesh_for_mapping,
            source_part_adjustments=source_part_adjustments,
            apply_source_part_role_overrides=_apply_source_part_role_overrides,
        )

    def _alignment_d3d11_preview_active() -> bool:
        return (
            str(preview_renderer_combo.currentData() or "").strip().lower() == "d3d11"
            and bool(alignment_d3d11_available)
        )

    def _current_alignment_transform_generation_value() -> int:
        if callable(_current_alignment_transform_generation):
            return int(_current_alignment_transform_generation() or 0)
        if isinstance(alignment_transform_generation, dict):
            return int(alignment_transform_generation.get("value", 0) or 0)
        return 0

    def _current_alignment_preview_render_settings_value():
        if callable(_current_alignment_preview_render_settings):
            return _current_alignment_preview_render_settings()
        if callable(_get_preview_render_settings):
            return _get_preview_render_settings()
        if preview_render_settings is not None:
            return preview_render_settings
        return self._current_model_preview_render_settings()

    def _mesh_edit_raw_preview_active_value() -> bool:
        if callable(_mesh_edit_raw_preview_active):
            return bool(_mesh_edit_raw_preview_active())
        return False

    def _set_preview_performance_status_if_ready(summary: str, *, details: str = "") -> None:
        if callable(_set_preview_performance_status):
            _set_preview_performance_status(summary, details=details)

    def _sync_mesh_edit_preview_settings_if_ready() -> None:
        if callable(_sync_mesh_edit_preview_settings):
            _sync_mesh_edit_preview_settings()

    def _clear_alignment_d3d11_fast_transform_state_if_ready(*, reset_host: bool = False) -> None:
        if callable(_clear_alignment_d3d11_fast_transform_state):
            _clear_alignment_d3d11_fast_transform_state(reset_host=reset_host)

    def _clear_source_parts_preview_rebuild_pending_if_ready() -> None:
        if callable(_clear_source_parts_preview_rebuild_pending):
            _clear_source_parts_preview_rebuild_pending()

    def _sync_highlight_sets_if_ready() -> None:
        if callable(_sync_highlight_sets):
            _sync_highlight_sets()

    def _replay_alignment_d3d11_fast_transform_if_ready() -> None:
        if callable(_replay_alignment_d3d11_fast_transform):
            _replay_alignment_d3d11_fast_transform()

    _current_global_flip_v_fast_preview_value = lambda: _global_flip_v_fast_preview_value_helper(
            d3d11_preview_active=_alignment_d3d11_preview_active(),
            texture_uv_transform_state=texture_uv_transform_state,
            texture_uv_global_transform_state=texture_uv_global_transform_state,
            state_has_edits=_texture_uv_state_has_edits,
        )

    def _reapply_global_flip_v_fast_preview(expected_flip_v: bool) -> None:
        current_flip_v = _current_global_flip_v_fast_preview_value()
        if current_flip_v is None or bool(current_flip_v) != bool(expected_flip_v):
            return
        if alignment_d3d11_preview_host.set_texture_flip_vertical(bool(expected_flip_v), editor_role="replacement_preview"):
            _texture_uv_fast_preview_record_global_flip_v_helper(
                alignment_d3d11_texture_uv_fast_state,
                expected_flip_v,
            )

    def _try_apply_global_flip_v_fast_preview() -> bool:
        flip_v = _current_global_flip_v_fast_preview_value()
        if flip_v is None:
            return False
        if alignment_d3d11_preview_host.set_texture_flip_vertical(flip_v, editor_role="replacement_preview"):
            _texture_uv_fast_preview_record_global_flip_v_helper(
                alignment_d3d11_texture_uv_fast_state,
                flip_v,
            )
            _alignment_d3d11_mark_preview_loaded_helper(alignment_d3d11_state)
            texture_overrides_dirty["dirty"] = True
            _set_alignment_d3d11_progress(100, "Preview ready.", active=False)
            flip_v_presentation = _alignment_d3d11_texture_flip_v_live_performance_helper()
            _set_preview_performance_status_if_ready(
                flip_v_presentation.summary,
                details=flip_v_presentation.details,
            )
            QTimer.singleShot(160, lambda expected_flip_v=flip_v: _reapply_global_flip_v_fast_preview(bool(expected_flip_v)))
            return True
        return False

    _alignment_geometry_tab_active = lambda: _active_tab_is_helper(control_tabs, parts_tab)

    _alignment_mesh_edit_tab_active = lambda: _active_tab_is_helper(control_tabs, mesh_edit_tab)

    _alignment_d3d11_editor_ids_for_source_indices = lambda source_indices, *, selection_overlay=False: _alignment_d3d11_editor_ids_for_source_indices_helper(
            source_indices,
            alignment_d3d11_state,
            selection_overlay=selection_overlay,
        )

    _alignment_d3d11_source_indices_for_editor_id = (
        lambda editor_id: _alignment_d3d11_source_indices_for_editor_id_helper(editor_id, alignment_d3d11_state)
    )

    def _alignment_default_d3d11_editor_ids() -> tuple[int, ...]:
        submeshes = tuple(getattr(replacement_mesh_for_mapping, "submeshes", ()) or ()) if replacement_mesh_for_mapping is not None else ()
        return _alignment_default_d3d11_editor_ids_helper(
            tuple(transform_source_indices),
            len(submeshes),
            source_index_is_enabled_renderable=_source_index_is_enabled_renderable,
            editor_ids_for_source_indices=_alignment_d3d11_editor_ids_for_source_indices,
        )

    def _cleanup_alignment_d3d11_package(package_dir: object, *, delay_ms: int = 0, force: bool = False) -> None:
        if package_dir is None:
            return
        try:
            package_path = Path(package_dir)
        except TypeError:
            return

        def _remove() -> None:
            if not force and _alignment_d3d11_package_is_cached_helper(
                package_path,
                alignment_d3d11_state.get("package_cache"),
            ):
                return
            try:
                shutil.rmtree(package_path, ignore_errors=True)
            except OSError:
                pass

        if delay_ms > 0:
            QTimer.singleShot(int(delay_ms), _remove)
        else:
            _remove()

    def _alignment_d3d11_invalidate_package_cache(reason: str = "geometry") -> None:
        _alignment_d3d11_invalidate_package_cache_helper(
            alignment_d3d11_state,
            reason,
            cleanup_package=lambda package_path, delay_ms: _cleanup_alignment_d3d11_package(
                package_path,
                delay_ms=delay_ms,
                force=True,
            ),
        )

    _alignment_d3d11_model_cache_signature = lambda model: _alignment_d3d11_model_cache_signature_helper(
            model,
            file_signature=_alignment_file_signature,
            sample_sequence=_alignment_sample_sequence,
        )

    def _alignment_d3d11_geometry_cache_key(
        model: ModelPreviewData,
        settings: ModelPreviewRenderSettings,
        *,
        display_mode: str,
    ) -> str:
        _ = settings
        return _alignment_d3d11_geometry_cache_key_helper(
            model,
            display_mode=display_mode,
            modify_original_clone_mode=bool(modify_original_clone_mode),
            sequence_digest=_alignment_sequence_digest,
        )

    _alignment_d3d11_material_cache_key = lambda model, settings, *, package_quality: _alignment_d3d11_material_cache_key_helper(
            model,
            settings,
            package_quality=package_quality,
            donor_material_plan_payload=_donor_material_plan_payload_helper(_current_donor_material_plans()),
            material_authority_preview_signature=str(
                material_authority_preview_signature_state.get("cache", "") or ""
            ),
            file_signature=_alignment_file_signature,
        )

    def _alignment_d3d11_preview_cache_signature(
        model: ModelPreviewData,
        settings: ModelPreviewRenderSettings,
        *,
        display_mode: str,
        package_quality: str,
    ) -> MeshPreviewCacheSignature:
        return MeshPreviewCacheSignature(
            geometry_key=_alignment_d3d11_geometry_cache_key(model, settings, display_mode=display_mode),
            material_key=_alignment_d3d11_material_cache_key(model, settings, package_quality=package_quality),
            display_class=f"{_alignment_d3d11_cache_display_class_helper(display_mode)}|{str(package_quality or 'normal')}",
        )

    def _alignment_d3d11_preview_cache_key(
        model: ModelPreviewData,
        settings: ModelPreviewRenderSettings,
        *,
        label: str,
        display_mode: str,
        package_quality: str,
    ) -> str:
        _ = label
        return _alignment_d3d11_preview_cache_signature(
            model,
            settings,
            display_mode=display_mode,
            package_quality=package_quality,
        ).package_key

    def _alignment_d3d11_package_cache_get(cache_key: str) -> Optional[Mapping[str, object]]:
        package_cache = alignment_d3d11_state.get("package_cache")
        return _alignment_d3d11_package_cache_get_helper(
            cache_key,
            package_cache,
            cleanup_package=lambda package_dir: _cleanup_alignment_d3d11_package(package_dir, force=True),
        )

    def _alignment_d3d11_package_cache_put(
        cache_key: str,
        package_dir: Path,
        *,
        display_mode: str,
        package_quality: str,
        prepare_ms: float,
        package_ms: float,
    ) -> None:
        if not str(cache_key or ""):
            return
        package_cache, evicted_package_dirs = _alignment_d3d11_package_cache_put_helper(
            cache_key,
            package_dir,
            alignment_d3d11_state.get("package_cache"),
            display_class=_alignment_d3d11_cache_display_class_helper(display_mode),
            display_mode=display_mode,
            package_quality=package_quality,
            prepare_ms=prepare_ms,
            package_ms=package_ms,
            created=time.monotonic(),
            limit=alignment_d3d11_state.get("package_cache_limit", 12),
        )
        _alignment_d3d11_store_package_cache_helper(alignment_d3d11_state, package_cache)
        for evicted_package_dir in evicted_package_dirs:
            _cleanup_alignment_d3d11_package(evicted_package_dir, force=True)

    def _drop_alignment_d3d11_package_reload(
        package_dir: object,
        *,
        request_id: int = 0,
        reason: str,
    ) -> None:
        active_package = alignment_d3d11_state.get("active_package")
        process = alignment_d3d11_state.get("process")
        process_active = isinstance(process, QProcess) and process.state() != QProcess.NotRunning
        drop_cleanup_state = _alignment_d3d11_package_drop_cleanup_state_helper(
            package=package_dir,
            active_package=active_package,
            process_active=process_active,
        )
        _record_runtime_event(
            "alignment_d3d11_package_reload_dropped",
            reason=str(reason or "unknown"),
            request_id=int(request_id or 0),
            active_request_id=int(alignment_d3d11_state.get("request_id", 0) or 0),
            package_dir=str(drop_cleanup_state.package_path or ""),
            dialog_closing=not _alignment_dialog_widgets_live(),
        )
        if drop_cleanup_state.should_cleanup:
            _cleanup_alignment_d3d11_package(drop_cleanup_state.package_path)

    def _alignment_d3d11_stop_process() -> None:
        process = alignment_d3d11_state.get("process")
        package_dir = _alignment_d3d11_clear_active_package_helper(
            alignment_d3d11_state,
            clear_process=True,
            clear_request_id=False,
            clear_status=True,
        )
        _safe_stop_alignment_timer(alignment_d3d11_status_timer)
        if not isinstance(process, QProcess):
            _cleanup_alignment_d3d11_package(package_dir)
            return
        try:
            process.disconnect()
        except (RuntimeError, TypeError):
            pass
        try:
            if process.state() != QProcess.NotRunning:
                process.terminate()
                QTimer.singleShot(1200, lambda process=process: self._kill_archive_isolated_renderer_process_if_running(process))
                _cleanup_alignment_d3d11_package(package_dir, delay_ms=5000)
            else:
                _cleanup_alignment_d3d11_package(package_dir)
            process.deleteLater()
        except RuntimeError:
            _cleanup_alignment_d3d11_package(package_dir)

    def _alignment_d3d11_stop_worker() -> None:
        worker = alignment_d3d11_state.get("worker")
        if isinstance(worker, AlignmentD3D11PackageWorker):
            worker.stop()

    def _shutdown_alignment_d3d11_preview() -> None:
        _safe_stop_alignment_timer(alignment_d3d11_reload_timer)
        _safe_stop_alignment_timer(alignment_d3d11_status_timer)
        _safe_stop_alignment_timer(alignment_d3d11_loading_timer)
        try:
            _safe_stop_alignment_timer(alignment_d3d11_drag_ui_timer)
        except NameError:
            pass
        _alignment_d3d11_reset_request_state_helper(
            alignment_d3d11_state,
            clear_active_metadata=True,
            clear_mapping_ids=True,
        )
        _alignment_d3d11_stop_worker()
        try:
            _stop_original_reference_texture_worker()
        except NameError:
            pass
        _alignment_d3d11_invalidate_package_cache("shutdown")
        _alignment_d3d11_stop_process()
        pending_package = alignment_d3d11_state.get("active_package")
        _cleanup_alignment_d3d11_package(pending_package)

    def _safe_shutdown_alignment_d3d11_preview() -> None:
        try:
            _shutdown_alignment_d3d11_preview()
        except Exception as exc:
            _record_runtime_event("alignment_d3d11_shutdown_error", message=str(exc))

    def _side_by_side_alignment_preview_model(original_model: object, replacement_model: object) -> Optional[object]:
        if not isinstance(original_model, ModelPreviewData) or not isinstance(replacement_model, ModelPreviewData):
            return replacement_model if isinstance(replacement_model, ModelPreviewData) else None
        original_min, original_max = _model_bounds_x(original_model)
        replacement_min, replacement_max = _model_bounds_x(replacement_model)
        original_width = max(0.1, original_max - original_min)
        replacement_width = max(0.1, replacement_max - replacement_min)
        gap = max(0.45, max(original_width, replacement_width) * 0.45)
        original_center = (original_min + original_max) * 0.5
        replacement_center = (replacement_min + replacement_max) * 0.5
        left_target = -((original_width + gap) * 0.5)
        right_target = (replacement_width + gap) * 0.5
        original_shifted = _translated_preview_model(
            _tint_preview_model(original_model, (0.30, 0.42, 0.54), clear_textures=False),
            left_target - original_center,
            clone_model=_clone_preview_model,
        )
        replacement_shifted = _translated_preview_model(
            replacement_model,
            right_target - replacement_center,
            clone_model=_clone_preview_model,
        )
        return _combine_preview_models(original_shifted, replacement_shifted)

    def _queue_alignment_d3d11_preview(
        model: object,
        *,
        label: str = "Live alignment preview",
        reason: str = "",
    ) -> None:
        if not _alignment_d3d11_preview_active():
            _record_runtime_event(
                "mesh_alignment_d3d11_preview_queue_skipped",
                path=getattr(entry, "path", ""),
                dialog_title=dialog_title,
                reason="inactive_renderer",
                requested_reason=str(reason or ""),
                modify_original_clone=modify_original_clone_mode,
            )
            return
        if not isinstance(model, ModelPreviewData):
            _set_alignment_d3d11_loading(False, "Preview has no renderable model yet.")
            _record_runtime_event(
                "mesh_alignment_d3d11_preview_queue_skipped",
                path=getattr(entry, "path", ""),
                dialog_title=dialog_title,
                reason="invalid_model",
                requested_reason=str(reason or ""),
                model_type=type(model).__name__,
                modify_original_clone=modify_original_clone_mode,
            )
            return
        transform_generation = _current_alignment_transform_generation_value()
        display_mode = str(preview_mode_combo.currentData() or "side_by_side")
        rebuild_reason = str(reason or alignment_d3d11_state.get("next_rebuild_reason", "") or "geometry").strip().lower()
        if rebuild_reason not in {"geometry", "texture_uv", "material", "mode_missing_original"}:
            rebuild_reason = "geometry"
        if rebuild_reason != "material":
            _alignment_d3d11_reset_material_parity_state_helper(alignment_d3d11_state)
            _set_alignment_d3d11_pipeline_stage("material_loading", f"queued {rebuild_reason} rebuild")
        _queued_settings, _queued_high_quality_textures, _queued_combiner, queued_package_quality = (
            _alignment_d3d11_package_quality(label, model, reason=rebuild_reason)
        )
        _alignment_d3d11_queue_preview_request_helper(
            alignment_d3d11_state,
            model=_clone_preview_model(model),
            label=label,
            display_mode=display_mode,
            reason=rebuild_reason,
            transform_generation=transform_generation,
            package_quality=queued_package_quality,
        )
        _record_runtime_event(
            "mesh_alignment_d3d11_preview_queued",
            path=getattr(entry, "path", ""),
            dialog_title=dialog_title,
            display_mode=display_mode,
            rebuild_reason=rebuild_reason,
            package_quality=queued_package_quality,
            transform_generation=int(transform_generation or 0),
            modify_original_clone=modify_original_clone_mode,
        )
        live_frame_available = _alignment_d3d11_live_frame_available()
        if not live_frame_available:
            _alignment_d3d11_mark_preview_unloaded_helper(alignment_d3d11_state)
        _set_alignment_d3d11_progress(
            0,
            "Preparing preview - queued.",
            stage="queued",
            detail=_alignment_d3d11_queued_preview_reload_detail_helper(rebuild_reason),
            active=not live_frame_available,
        )
        alignment_d3d11_reload_timer.setInterval(
            alignment_d3d11_fast_reload_interval_ms
            if rebuild_reason == "material"
            else alignment_d3d11_package_reload_interval_ms
        )
        _safe_start_alignment_timer(alignment_d3d11_reload_timer)

    def _alignment_d3d11_package_quality(
        label: str,
        model: object = None,
        *,
        reason: str = "",
    ) -> tuple[ModelPreviewRenderSettings, bool, bool, str]:
        settings = _current_alignment_preview_render_settings_value()
        normalized_reason = str(reason or alignment_d3d11_state.get("next_rebuild_reason", "") or "").strip().lower()
        return _alignment_d3d11_package_quality_helper(
            settings,
            alignment_d3d11_state,
            reason=normalized_reason,
            mesh_edit_raw_preview_active=_mesh_edit_raw_preview_active_value(),
        )

    def _queue_alignment_archive_parity_upgrade(reason: str = "fast preview ready") -> None:
        if not _alignment_dialog_widgets_live() or not _alignment_d3d11_preview_active():
            return
        if not _alignment_d3d11_begin_archive_parity_upgrade_helper(alignment_d3d11_state):
            return
        _set_alignment_d3d11_pipeline_stage("material_loading", reason)
        _set_alignment_d3d11_progress(
            100,
            (
                "Fast preview ready; loading full Archive Preview material parity in background. "
                "UI stays usable; preview-changing edits restart this load."
            ),
            stage="material_loading",
            active=False,
        )

        def _upgrade() -> None:
            if not _alignment_dialog_widgets_live() or not _alignment_d3d11_preview_active():
                _alignment_d3d11_clear_archive_parity_upgrade_helper(alignment_d3d11_state)
                return
            parity_ready, parity_should_start = _original_reference_texture_preview_archive_parity_state_helper(
                original_reference_texture_preview_state,
                active_preview_mode=str(preview_mode_combo.currentData() or "side_by_side"),
                has_original_reference_model=original_reference_preview_model is not None,
            )
            if not parity_ready:
                if parity_should_start:
                    _load_original_reference_texture_preview()
                return
            _alignment_d3d11_clear_archive_parity_upgrade_helper(alignment_d3d11_state)
            _mark_alignment_d3d11_rebuild_reason("material")
            _queue_static_preview_refresh()

        QTimer.singleShot(120, _upgrade)

    def _queue_latest_alignment_d3d11_rebuild_for_stale_reload(request_id: int = 0) -> None:
        if not _alignment_dialog_widgets_live() or bool(alignment_d3d11_drag_transaction.get("active")):
            return
        reason = _alignment_d3d11_request_reason_helper(
            alignment_d3d11_state,
            request_id=int(request_id or 0),
            fallback=str(alignment_d3d11_state.get("last_rebuild_reason", "geometry") or "geometry"),
        )
        dirty_flags = _alignment_d3d11_dirty_flags_for_reason(reason)
        _mark_alignment_d3d11_rebuild_reason(reason)
        if dirty_flags.affects_geometry():
            static_preview_geometry_cache.clear()
            static_preview_prepared_cache.clear()
        if dirty_flags.affects_material():
            texture_overrides_dirty["dirty"] = True
        _alignment_d3d11_invalidate_package_cache(f"stale_{reason}")
        static_preview_refresh_timer.start()

    def _handle_alignment_d3d11_stale_reload(package_dir: object, *, request_id: int = 0, reason: str) -> None:
        _drop_alignment_d3d11_package_reload(package_dir, request_id=int(request_id or 0), reason=str(reason or "stale_reload"))
        process = alignment_d3d11_state.get("process")
        active_package = alignment_d3d11_state.get("active_package")
        stale_reload_route = _alignment_d3d11_stale_reload_route_helper(
            dialog_live=_alignment_dialog_widgets_live(),
            drag_active=bool(alignment_d3d11_drag_transaction.get("active")),
            process_active=isinstance(process, QProcess) and process.state() != QProcess.NotRunning,
            active_package_exists=isinstance(active_package, Path) and active_package.exists(),
        )
        if stale_reload_route.should_pause_loading:
            _set_alignment_d3d11_loading(False, stale_reload_route.pause_message)
            return
        if not stale_reload_route.should_continue:
            return
        active_preview_alive = stale_reload_route.active_preview_alive
        if active_preview_alive:
            _alignment_d3d11_mark_preview_loaded_helper(alignment_d3d11_state)
            _alignment_d3d11_mark_resources_loaded_helper(alignment_d3d11_state)
            _sync_highlight_sets_if_ready()
            _replay_alignment_d3d11_fast_transform_if_ready()
        _set_alignment_d3d11_progress(
            100 if active_preview_alive else 0,
            "Preview changed; rebuilding current view.",
            request_id=0,
            stage="stale_reload_requeued",
            detail=_alignment_d3d11_stale_package_dropped_detail_helper(
                reason=reason,
                request_id=int(request_id or 0),
                active_preview_alive=active_preview_alive,
            ),
            active=False,
        )
        stale_dropped_presentation = _alignment_d3d11_stale_package_dropped_performance_helper(
            reason=reason,
            request_id=int(request_id or 0),
            active_preview_alive=active_preview_alive,
        )
        _set_preview_performance_status_if_ready(
            stale_dropped_presentation.summary,
            details=stale_dropped_presentation.details,
        )
        QTimer.singleShot(0, lambda expected_request=int(request_id or 0): _queue_latest_alignment_d3d11_rebuild_for_stale_reload(expected_request))

    def _handle_alignment_d3d11_package_progress(
        request_id: int,
        current: int,
        total: int,
        message: str,
    ) -> None:
        if not _alignment_dialog_widgets_live():
            return
        if int(request_id or 0) != int(alignment_d3d11_state.get("request_id", 0) or 0):
            return
        total = max(1, int(total or 1))
        current = max(0, min(total, int(current or 0)))
        percent = current if total == 100 else int(round((float(current) / float(total)) * 80.0))
        percent = max(0, min(80, percent))
        _set_alignment_d3d11_progress(
            percent,
            str(message or "Preparing preview package."),
            request_id=int(request_id or 0),
            stage="package",
            detail=f"request_id={int(request_id or 0)}\nprogress={current}/{total}",
        )

    class _AlignmentD3D11PackageWorkerReceiver(QObject):
        @Slot(int, int, int, str)
        def handle_progress(self, request_id: int, current: int, total: int, message: str) -> None:
            _handle_alignment_d3d11_package_progress(request_id, current, total, message)

        @Slot(int, object, float, float)
        def handle_completed(
            self,
            request_id: int,
            package_dir_object: object,
            prepare_ms: float,
            package_ms: float,
        ) -> None:
            _handle_alignment_d3d11_package_ready(
                request_id,
                package_dir_object,
                prepare_ms,
                package_ms,
            )

        @Slot(int, str)
        def handle_error(self, request_id: int, message: str) -> None:
            _handle_alignment_d3d11_package_error(request_id, message)

    alignment_d3d11_package_worker_receiver = _AlignmentD3D11PackageWorkerReceiver(dialog)

    def _start_alignment_d3d11_package_worker(
        model: object,
        label: str,
        transform_generation: Optional[int] = None,
        display_mode: str = "",
        reason: str = "geometry",
    ) -> None:
        _record_runtime_event(
            "mesh_alignment_d3d11_package_start_entered",
            path=getattr(entry, "path", ""),
            dialog_title=dialog_title,
            model_type=type(model).__name__,
            display_mode=str(display_mode or ""),
            reason=str(reason or ""),
            transform_generation=int(transform_generation or 0),
            modify_original_clone=modify_original_clone_mode,
        )
        route_state = _alignment_d3d11_package_start_route_helper(
            dialog_live=_alignment_dialog_widgets_live(),
            preview_active=_alignment_d3d11_preview_active(),
            model_is_preview_data=isinstance(model, ModelPreviewData),
            display_mode=display_mode,
            fallback_display_mode=preview_mode_combo.currentData() or "side_by_side",
            reason=reason,
            transform_generation=transform_generation,
            current_transform_generation=_current_alignment_transform_generation_value(),
            active_request_id=alignment_d3d11_state.get("request_id", 0),
        )
        if route_state.should_drop:
            _record_runtime_event(
                "alignment_d3d11_package_reload_dropped",
                reason=route_state.drop_reason,
                request_id=int(alignment_d3d11_state.get("request_id", 0) or 0),
                active_request_id=int(alignment_d3d11_state.get("request_id", 0) or 0),
                package_dir="",
                dialog_closing=True,
            )
            return
        if not route_state.should_start:
            _record_runtime_event(
                "mesh_alignment_d3d11_package_start_skipped",
                path=getattr(entry, "path", ""),
                dialog_title=dialog_title,
                drop_reason=str(route_state.drop_reason or ""),
                display_mode=str(route_state.display_mode or ""),
                rebuild_reason=str(route_state.rebuild_reason or ""),
                modify_original_clone=modify_original_clone_mode,
            )
            return
        requested_display_mode = route_state.display_mode
        rebuild_reason = route_state.rebuild_reason
        dirty_flags = _alignment_d3d11_dirty_flags_for_reason(rebuild_reason)
        if dirty_flags.affects_geometry():
            _alignment_d3d11_reset_material_parity_state_helper(alignment_d3d11_state)
            _set_alignment_d3d11_pipeline_stage("material_loading", f"starting {rebuild_reason} rebuild")
        request_transform_generation = route_state.transform_generation
        settings, high_quality_textures, enable_material_combiner, package_quality = _alignment_d3d11_package_quality(
            label,
            model,
            reason=rebuild_reason,
        )
        if isinstance(alignment_d3d11_state.get("thread"), QThread):
            _alignment_d3d11_queue_pending_request_helper(
                alignment_d3d11_state,
                model=model,
                label=label,
                display_mode=requested_display_mode,
                reason=rebuild_reason,
                transform_generation=request_transform_generation,
                package_quality=package_quality,
            )
            live_frame_available = _alignment_d3d11_live_frame_available()
            if not live_frame_available:
                _alignment_d3d11_mark_preview_unloaded_helper(alignment_d3d11_state)
            _alignment_d3d11_stop_worker()
            _set_alignment_d3d11_progress(
                0,
                "Preparing preview - queued latest request.",
                stage="queued",
                detail=_alignment_d3d11_queued_latest_preview_reload_detail_helper(rebuild_reason),
                active=not live_frame_available,
            )
            _record_runtime_event(
                "mesh_alignment_d3d11_package_start_deferred",
                path=getattr(entry, "path", ""),
                dialog_title=dialog_title,
                rebuild_reason=rebuild_reason,
                package_quality=package_quality,
                modify_original_clone=modify_original_clone_mode,
            )
            return
        request_id = _alignment_d3d11_begin_package_request_helper(
            alignment_d3d11_state,
            drag_generation=int(alignment_d3d11_drag_generation.get("value", 0) or 0),
            transform_generation=request_transform_generation,
            display_mode=requested_display_mode,
            reason=rebuild_reason,
            package_quality=package_quality,
        )
        _alignment_d3d11_record_package_request_metadata_helper(
            alignment_d3d11_state,
            package_quality=package_quality,
            rebuild_reason=rebuild_reason,
        )
        live_frame_available = _alignment_d3d11_live_frame_available()
        if not live_frame_available:
            _alignment_d3d11_mark_preview_unloaded_helper(alignment_d3d11_state)
        package_quality_key = str(package_quality).strip().lower()
        native_reference_package_dir: Optional[Path] = None
        if package_quality_key in {"archive_parity", "material_refresh"} and requested_display_mode in {
            "side_by_side",
            "overlay",
        }:
            native_reference_package_text = str(
                original_reference_texture_preview_state.get("native_package_path", "") or ""
            ).strip()
            if native_reference_package_text:
                try:
                    candidate_native_reference_package_dir = Path(native_reference_package_text)
                    if candidate_native_reference_package_dir.is_dir():
                        native_reference_package_dir = candidate_native_reference_package_dir
                except (OSError, ValueError):
                    native_reference_package_dir = None
        cache_key = _alignment_d3d11_preview_cache_key(
            model,
            settings,
            label=label,
            display_mode=requested_display_mode,
            package_quality=package_quality,
        )
        native_reference_signature_hash = ""
        if native_reference_package_dir is not None:
            try:
                native_reference_stat = native_reference_package_dir.stat()
                native_reference_signature = (
                    f"{native_reference_package_dir}|"
                    f"{int(native_reference_stat.st_mtime_ns)}|{int(native_reference_stat.st_size)}"
                )
            except OSError:
                native_reference_signature = str(native_reference_package_dir)
            native_reference_signature_hash = hashlib.sha1(
                native_reference_signature.encode("utf-8", "ignore")
            ).hexdigest()
        cache_key = _alignment_d3d11_cache_key_with_native_reference_helper(
            cache_key,
            native_reference_signature_hash=native_reference_signature_hash,
        )
        _alignment_d3d11_remember_request_cache_key_helper(alignment_d3d11_state, request_id, cache_key)
        cache_entry = _alignment_d3d11_package_cache_get(cache_key)
        if isinstance(cache_entry, Mapping):
            try:
                cached_package_dir = Path(cache_entry.get("package_dir", ""))
            except TypeError:
                cached_package_dir = None
            if isinstance(cached_package_dir, Path):
                package_quality = _alignment_d3d11_record_cache_hit_metadata_helper(
                    alignment_d3d11_state,
                    cache_entry,
                    package_quality=package_quality,
                )
                _alignment_d3d11_remember_request_package_quality_helper(
                    alignment_d3d11_state,
                    request_id,
                    package_quality,
                )
                existing_process = alignment_d3d11_state.get("process")
                active_package = alignment_d3d11_state.get("active_package")
                active_matches = _alignment_d3d11_active_package_matches_helper(
                    process_active=(
                        isinstance(existing_process, QProcess)
                        and existing_process.state() != QProcess.NotRunning
                    ),
                    active_package=active_package,
                    package=cached_package_dir,
                )
                if active_matches:
                    active_matches, _active_host_detail = _alignment_d3d11_host_ready(require_child=True)
                if active_matches:
                    if _alignment_d3d11_loaded_package_transform_current_helper(
                        alignment_d3d11_state,
                        alignment_transform_generation,
                        request_id=request_id,
                    ):
                        _clear_alignment_d3d11_fast_transform_state_if_ready(reset_host=True)
                    cached_quality = _alignment_d3d11_mark_active_cached_package_reused_helper(
                        alignment_d3d11_state,
                        request_id=request_id,
                        display_mode=requested_display_mode,
                        package_quality=package_quality,
                        cache_key=cache_key,
                    )
                    alignment_d3d11_preview_host.set_display_mode(str(preview_mode_combo.currentData() or requested_display_mode))
                    alignment_d3d11_preview_host.set_render_tuning(_current_alignment_preview_render_settings_value())
                    preview_stack.setCurrentWidget(alignment_d3d11_preview_page)
                    _sync_highlight_sets_if_ready()
                    _replay_alignment_d3d11_fast_transform_if_ready()
                    if cached_quality == "fast_geometry":
                        _set_alignment_d3d11_pipeline_stage("fast_geometry", "active cached fast package reused")
                    elif cached_quality == "archive_parity":
                        _set_alignment_d3d11_pipeline_stage("archive_parity_ready", "active cached archive package reused")
                    _set_alignment_d3d11_progress(
                        100,
                        "Preview ready.",
                        request_id=request_id,
                        stage="ready",
                        detail=f"Reused active cached package. reason={rebuild_reason}",
                        active=False,
                    )
                    cached_reuse_presentation = _alignment_d3d11_cached_reuse_performance_helper(
                        alignment_d3d11_state,
                        quality_label=_alignment_preview_quality_label_helper(alignment_d3d11_state),
                        rebuild_reason=rebuild_reason,
                    )
                    _set_preview_performance_status_if_ready(
                        cached_reuse_presentation.summary,
                        details=cached_reuse_presentation.details,
                    )
                    _clear_source_parts_preview_rebuild_pending_if_ready()
                    if cached_quality == "fast_geometry":
                        _queue_alignment_archive_parity_upgrade("active cached fast package reused")
                    return
                live_frame_available = _alignment_d3d11_live_frame_available()
                _set_alignment_d3d11_progress(
                    82,
                    "Loading cached preview package.",
                    request_id=request_id,
                    stage="cached_package",
                    detail=_alignment_d3d11_cached_loading_progress_detail_helper(rebuild_reason),
                    active=not live_frame_available,
                )
                cached_loading_presentation = _alignment_d3d11_cached_loading_performance_helper(
                    rebuild_reason
                )
                _set_preview_performance_status_if_ready(
                    cached_loading_presentation.summary,
                    details=cached_loading_presentation.details,
                )
                _start_alignment_d3d11_process(cached_package_dir, request_id=request_id)
                _record_runtime_event(
                    "mesh_alignment_d3d11_package_cache_used",
                    path=getattr(entry, "path", ""),
                    dialog_title=dialog_title,
                    request_id=int(request_id or 0),
                    package_dir=str(cached_package_dir),
                    rebuild_reason=rebuild_reason,
                    package_quality=package_quality,
                    modify_original_clone=modify_original_clone_mode,
                )
                return
        _alignment_d3d11_record_cache_lookup_result_helper(alignment_d3d11_state, cache_key)
        mesh_edit_raw_package = _mesh_edit_raw_preview_active_value()
        package_quality_key = str(package_quality).strip().lower()
        worker_use_textures = bool(getattr(settings, "use_textures_by_default", True))
        worker_high_quality_textures = bool(worker_use_textures and high_quality_textures)
        worker_enable_material_combiner = bool(worker_use_textures and enable_material_combiner)
        worker_original_reference_material_parity = bool(worker_use_textures)
        geometry_signature = _alignment_d3d11_geometry_cache_key(
            model,
            settings,
            display_mode=requested_display_mode,
        )
        preview_cache_root = self.archive_cache_root / "d3d11_preview_cache" / alignment_dialog_key_hash
        worker = AlignmentD3D11PackageWorker(
            request_id,
            model,
            settings,
            use_textures=worker_use_textures,
            high_quality_textures=worker_high_quality_textures,
            enable_material_combiner=worker_enable_material_combiner,
            original_reference_material_parity=worker_original_reference_material_parity,
            display_mode=requested_display_mode,
            editor_workspace="modify_original_alignment" if modify_original_clone_mode else "mesh_replacement_alignment",
            package_quality=package_quality,
            geometry_signature=geometry_signature,
            reuse_prepared_geometry=bool(geometry_signature),
            geometry_cache_dir=preview_cache_root / "geometry",
            texture_cache_dir=preview_cache_root / "textures",
            original_reference_native_package_dir=native_reference_package_dir,
        )
        thread = QThread(dialog)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.progress_changed.connect(
            alignment_d3d11_package_worker_receiver.handle_progress,
            Qt.QueuedConnection,
        )
        worker.completed.connect(
            alignment_d3d11_package_worker_receiver.handle_completed,
            Qt.QueuedConnection,
        )
        worker.error.connect(
            alignment_d3d11_package_worker_receiver.handle_error,
            Qt.QueuedConnection,
        )
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(_cleanup_alignment_d3d11_package_worker_refs)
        _alignment_d3d11_record_package_worker_refs_helper(
            alignment_d3d11_state,
            worker=worker,
            thread=thread,
        )
        loading_detail = _alignment_d3d11_package_loading_detail_helper(
            package_quality=package_quality_key,
            high_quality_textures=high_quality_textures,
            mesh_edit_raw_package=mesh_edit_raw_package,
            fast_geometry_loaded=bool(alignment_d3d11_state.get("fast_geometry_loaded")),
        )
        _set_alignment_d3d11_progress(
            0,
            f"Preparing preview - {loading_detail}.",
            request_id=request_id,
            stage="package",
            detail=f"Building preview package. quality={package_quality} reason={rebuild_reason} label={label}",
            active=not live_frame_available,
        )
        preparing_presentation = _alignment_d3d11_package_preparing_performance_helper(
            alignment_d3d11_state,
            quality_label=_alignment_preview_quality_label_helper(alignment_d3d11_state),
            cache_label=_d3d11_cache_event_user_label(alignment_d3d11_state.get("last_cache_event")),
            rebuild_reason=rebuild_reason,
        )
        _set_preview_performance_status_if_ready(
            preparing_presentation.summary,
            details=preparing_presentation.details,
        )
        _record_runtime_event(
            "mesh_alignment_d3d11_package_worker_started",
            path=getattr(entry, "path", ""),
            dialog_title=dialog_title,
            request_id=int(request_id or 0),
            rebuild_reason=rebuild_reason,
            package_quality=package_quality,
            display_mode=requested_display_mode,
            modify_original_clone=modify_original_clone_mode,
        )
        thread.start()

    def _flush_alignment_d3d11_preview_request() -> None:
        if not _alignment_dialog_widgets_live():
            return
        model = alignment_d3d11_state.get("queued_model")
        label = str(alignment_d3d11_state.get("queued_label", "") or "Live alignment preview")
        display_mode = str(alignment_d3d11_state.get("queued_display_mode", "") or preview_mode_combo.currentData() or "side_by_side")
        reason = str(alignment_d3d11_state.get("queued_reason", "") or "geometry")
        transform_generation = int(alignment_d3d11_state.get("queued_transform_generation", 0) or 0)
        _alignment_d3d11_clear_queued_preview_request_helper(alignment_d3d11_state)
        _record_runtime_event(
            "mesh_alignment_d3d11_preview_flush",
            path=getattr(entry, "path", ""),
            dialog_title=dialog_title,
            model_type=type(model).__name__,
            display_mode=display_mode,
            reason=reason,
            transform_generation=transform_generation,
            modify_original_clone=modify_original_clone_mode,
        )
        _start_alignment_d3d11_package_worker(
            model,
            label,
            transform_generation,
            display_mode=display_mode,
            reason=reason,
        )

    def _handle_alignment_d3d11_package_ready(
        request_id: int,
        package_dir_object: object,
        prepare_ms: float,
        package_ms: float,
    ) -> None:
        try:
            package_dir = Path(package_dir_object)
        except TypeError:
            return
        drag_reload_stale = _alignment_d3d11_drag_reload_stale_helper(
            alignment_d3d11_state,
            alignment_d3d11_drag_transaction,
            alignment_d3d11_drag_generation,
            alignment_transform_generation,
            request_id=int(request_id),
        )
        ready_route = _alignment_d3d11_package_ready_route_helper(
            dialog_live=_alignment_dialog_widgets_live(),
            request_id=request_id,
            current_request_id=alignment_d3d11_state.get("request_id", 0),
            drag_reload_stale=drag_reload_stale,
        )
        if ready_route.should_drop:
            if ready_route.drop_reason == "dialog_closing":
                _drop_alignment_d3d11_package_reload(
                    package_dir,
                    request_id=int(request_id),
                    reason="dialog_closing",
                )
                return
            if ready_route.drop_reason == "stale_request":
                _drop_alignment_d3d11_package_reload(
                    package_dir,
                    request_id=int(request_id),
                    reason="stale_request",
                )
                return
            _drop_alignment_d3d11_package_reload(
                package_dir,
                request_id=int(request_id),
                reason=ready_route.drop_reason,
            )
            return
        if ready_route.should_handle_stale_drag:
            _handle_alignment_d3d11_stale_reload(package_dir, request_id=int(request_id), reason="stale_drag")
            return
        if not ready_route.should_accept:
            return
        _alignment_d3d11_record_package_timing_helper(
            alignment_d3d11_state,
            prepare_ms=prepare_ms,
            package_ms=package_ms,
        )
        package_metadata = _alignment_d3d11_process_request_metadata_helper(
            alignment_d3d11_state,
            int(request_id),
            display_mode_fallback=preview_mode_combo.currentData() or "side_by_side",
            package_quality_fallback=alignment_d3d11_state.get("package_quality", "normal") or "normal",
            rebuild_reason_fallback=alignment_d3d11_state.get("last_rebuild_reason", "geometry") or "geometry",
        )
        _alignment_d3d11_package_cache_put(
            package_metadata.cache_key,
            package_dir,
            display_mode=package_metadata.display_mode,
            package_quality=package_metadata.package_quality,
            prepare_ms=float(prepare_ms),
            package_ms=float(package_ms),
        )
        _start_alignment_d3d11_process(package_dir, request_id=int(request_id))

    def _handle_alignment_d3d11_package_error(request_id: int, message: str) -> None:
        if not _alignment_dialog_widgets_live():
            return
        if int(request_id) != int(alignment_d3d11_state.get("request_id", 0) or 0):
            return
        _set_alignment_d3d11_loading(False, f"Preview load failed: {message}")
        package_failed_presentation = _alignment_d3d11_package_failed_performance_helper(message)
        _set_preview_performance_status_if_ready(
            package_failed_presentation.summary,
            details=package_failed_presentation.details,
        )
        _clear_source_parts_preview_rebuild_pending_if_ready()

    def _cleanup_alignment_d3d11_package_worker_refs() -> None:
        _alignment_d3d11_clear_package_worker_refs_helper(alignment_d3d11_state)
        pending_request = _alignment_d3d11_take_pending_request_helper(
            alignment_d3d11_state,
            label_fallback="Live alignment preview",
            display_mode_fallback=str(preview_mode_combo.currentData() or "side_by_side"),
        )
        pending_model = pending_request["model"]
        if _alignment_dialog_widgets_live() and _alignment_d3d11_preview_active() and isinstance(pending_model, ModelPreviewData):
            pending_label = str(pending_request["label"])
            pending_display_mode = str(pending_request["display_mode"])
            pending_reason = str(pending_request["reason"])
            pending_transform_generation = int(pending_request["transform_generation"])
            QTimer.singleShot(
                0,
                lambda model=pending_model, label=pending_label, generation=pending_transform_generation, mode=pending_display_mode, queued_reason=pending_reason: (
                    _start_alignment_d3d11_package_worker(
                        model,
                        label,
                        generation,
                        display_mode=mode,
                        reason=queued_reason,
                    )
                ),
            )

    def _start_alignment_d3d11_process(package_dir: Path, *, request_id: int = 0) -> None:
        drag_reload_stale = int(request_id or 0) > 0 and _alignment_d3d11_drag_reload_stale_helper(
            alignment_d3d11_state,
            alignment_d3d11_drag_transaction,
            alignment_d3d11_drag_generation,
            alignment_transform_generation,
            request_id=int(request_id),
        )
        route_state = _alignment_d3d11_process_start_route_helper(
            dialog_live=_alignment_dialog_widgets_live(),
            request_id=request_id,
            current_request_id=alignment_d3d11_state.get("request_id", 0),
            drag_active=bool(alignment_d3d11_drag_transaction.get("active")),
            drag_reload_stale=drag_reload_stale,
        )
        if route_state.should_drop:
            if route_state.drop_reason == "dialog_closing":
                _drop_alignment_d3d11_package_reload(
                    package_dir,
                    request_id=int(request_id or 0),
                    reason="dialog_closing",
                )
                return
            if route_state.drop_reason == "stale_request":
                _drop_alignment_d3d11_package_reload(
                    package_dir,
                    request_id=int(request_id or 0),
                    reason="stale_request",
                )
                return
            _drop_alignment_d3d11_package_reload(
                package_dir,
                request_id=int(request_id or 0),
                reason=route_state.drop_reason,
            )
            if route_state.should_pause_loading:
                _set_alignment_d3d11_loading(False, route_state.pause_message)
            return
        if route_state.should_handle_stale_drag:
            _handle_alignment_d3d11_stale_reload(package_dir, request_id=int(request_id or 0), reason="stale_drag")
            return
        if not route_state.should_start:
            return
        status_file = package_dir / "host_status.json"
        try:
            status_file.unlink(missing_ok=True)
        except OSError:
            pass
        package_metadata = _alignment_d3d11_process_request_metadata_helper(
            alignment_d3d11_state,
            int(request_id or 0),
            display_mode_fallback=preview_mode_combo.currentData() or "side_by_side",
            package_quality_fallback=alignment_d3d11_state.get("package_quality", "normal") or "normal",
            rebuild_reason_fallback=alignment_d3d11_state.get("last_rebuild_reason", "geometry") or "geometry",
        )
        package_display_mode = package_metadata.display_mode
        package_quality = package_metadata.package_quality
        rebuild_reason = package_metadata.rebuild_reason
        package_cache_key = package_metadata.cache_key
        existing_process = alignment_d3d11_state.get("process")
        reuse_host_ready, reuse_host_detail = _alignment_d3d11_host_ready(require_child=True)
        reuse_state = _alignment_d3d11_process_reuse_state_helper(
            process_active=isinstance(existing_process, QProcess) and existing_process.state() != QProcess.NotRunning,
            host_ready=reuse_host_ready,
            host_detail=reuse_host_detail,
        )
        if reuse_state.can_reuse_process:
            previous_active_package = _alignment_d3d11_active_package_snapshot_helper(alignment_d3d11_state)
            previous_package = previous_active_package.get("active_package")
            _alignment_d3d11_prepare_active_package_helper(
                alignment_d3d11_state,
                package=package_dir,
                request_id=int(request_id or 0),
                display_mode=package_display_mode,
                package_quality=package_quality,
                cache_key=package_cache_key,
                status_file=status_file,
            )
            if alignment_d3d11_preview_host.load_package(package_dir, status_file, reset_view=False):
                alignment_d3d11_preview_host.set_display_mode(str(preview_mode_combo.currentData() or "side_by_side"))
                alignment_d3d11_preview_host.set_render_tuning(_current_alignment_preview_render_settings_value())
                _cleanup_alignment_d3d11_package(previous_package, delay_ms=5000)
                preview_stack.setCurrentWidget(alignment_d3d11_preview_page)
                _alignment_d3d11_mark_loading_started_helper(alignment_d3d11_state, time.perf_counter())
                _set_alignment_d3d11_progress(
                    82,
                    "Loading preview package in native renderer.",
                    request_id=int(request_id or 0),
                    stage="native_reload",
                    detail=_alignment_d3d11_cached_renderer_reload_detail_helper(rebuild_reason),
                )
                channel_debug = self._archive_material_channel_debug_from_package(package_dir)
                cache_event = str(alignment_d3d11_state.get("last_cache_event", "miss") or "miss")
                cache_label = _d3d11_cache_event_user_label(cache_event)
                reload_presentation = _alignment_d3d11_reload_queued_performance_helper(
                    alignment_d3d11_state,
                    quality_label=_alignment_preview_quality_label_helper(alignment_d3d11_state),
                    cache_label=cache_label,
                    package_quality=package_quality,
                    rebuild_reason=rebuild_reason,
                    channel_debug=channel_debug,
                )
                _set_preview_performance_status_if_ready(
                    reload_presentation.summary,
                    details=reload_presentation.details,
                )
                _safe_start_alignment_timer(alignment_d3d11_status_timer)
                return
            _alignment_d3d11_restore_active_package_helper(alignment_d3d11_state, previous_active_package)
        elif reuse_state.should_report_restart:
            restart_presentation = _alignment_d3d11_renderer_host_restart_performance_helper(
                rebuild_reason=rebuild_reason,
                host_detail=reuse_state.host_detail,
            )
            _set_preview_performance_status_if_ready(
                restart_presentation.summary,
                details=restart_presentation.details,
            )
        _alignment_d3d11_stop_process()
        _alignment_d3d11_prepare_active_package_helper(
            alignment_d3d11_state,
            package=package_dir,
            request_id=int(request_id or 0),
            display_mode=package_display_mode,
            package_quality=package_quality,
            cache_key=package_cache_key,
            status_file=status_file,
        )
        preview_stack.setCurrentWidget(alignment_d3d11_preview_page)
        new_host_ready, new_host_detail = _alignment_d3d11_host_ready(require_child=False)
        if not new_host_ready:
            retry_count = _alignment_d3d11_record_pending_process_retry_helper(
                alignment_d3d11_state,
                package=package_dir,
            )
            _set_alignment_d3d11_progress(
                82,
                "Waiting for preview panel layout.",
                request_id=int(request_id or 0),
                stage="waiting_for_visible_preview",
                detail=_alignment_d3d11_waiting_for_preview_panel_detail_helper(
                    rebuild_reason=rebuild_reason,
                    host_detail=new_host_detail,
                    retry_count=retry_count,
                ),
                active=False,
            )
            pending_host_presentation = _alignment_d3d11_pending_host_performance_helper(
                rebuild_reason=rebuild_reason,
                host_detail=new_host_detail,
            )
            _set_preview_performance_status_if_ready(
                pending_host_presentation.summary,
                details=pending_host_presentation.details,
            )
            if retry_count <= 80:
                QTimer.singleShot(
                    75,
                    lambda package=package_dir, expected_request=int(request_id or 0): _start_alignment_d3d11_process(
                        package,
                        request_id=expected_request,
                    ),
                )
            else:
                _set_alignment_d3d11_loading(False, "Preview panel is not renderable yet.")
            return
        _alignment_d3d11_clear_pending_process_retry_helper(alignment_d3d11_state)
        process = QProcess(dialog)
        try:
            program, arguments = self._native_d3d11_renderer_command(
                package_dir,
                status_file,
                host_widget=alignment_d3d11_preview_host,
                theme_payload=_alignment_d3d11_theme_payload_helper(
                    MODEL_PREVIEW_BACKGROUND_COLOR,
                    MODEL_PREVIEW_TEXT_COLOR,
                ),
            )
        except Exception as exc:
            _set_alignment_d3d11_loading(False, f"Preview unavailable: {exc}")
            unavailable_presentation = _alignment_d3d11_unavailable_performance_helper()
            _set_preview_performance_status_if_ready(
                unavailable_presentation.summary,
                details=unavailable_presentation.details,
            )
            _cleanup_alignment_d3d11_package(package_dir)
            _alignment_d3d11_clear_active_package_helper(alignment_d3d11_state)
            return
        process.setProgram(program)
        process.setArguments(arguments)
        try:
            process.setWorkingDirectory(str(Path(__file__).resolve().parents[3]))
        except Exception:
            pass
        process.setProcessChannelMode(QProcess.SeparateChannels)
        process.readyReadStandardError.connect(lambda process=process: _handle_alignment_d3d11_stderr(process))
        process.finished.connect(lambda exit_code, exit_status, process=process: _handle_alignment_d3d11_finished(process, exit_code, exit_status))
        process.errorOccurred.connect(lambda error, process=process: _handle_alignment_d3d11_error(process, error))
        _alignment_d3d11_record_process_ref_helper(alignment_d3d11_state, process)
        _alignment_d3d11_mark_loading_started_helper(alignment_d3d11_state, time.perf_counter())
        _set_alignment_d3d11_progress(
            82,
            "Starting native preview renderer.",
            request_id=int(request_id or 0),
            stage="native_start",
            detail=f"reason={rebuild_reason}",
        )
        starting_presentation = _alignment_d3d11_starting_performance_helper(
            alignment_d3d11_state,
            quality_label=_alignment_preview_quality_label_helper(alignment_d3d11_state),
            cache_label=_d3d11_cache_event_user_label(alignment_d3d11_state.get("last_cache_event", "miss")),
            package_quality=package_quality,
            rebuild_reason=rebuild_reason,
        )
        _set_preview_performance_status_if_ready(
            starting_presentation.summary,
            details=starting_presentation.details,
        )
        _safe_start_alignment_timer(alignment_d3d11_status_timer)
        process.start()
        QTimer.singleShot(10000, lambda expected_status=status_file: _check_alignment_d3d11_start_timeout(expected_status))

    def _check_alignment_d3d11_start_timeout(expected_status: Path) -> None:
        process = alignment_d3d11_state.get("process")
        timeout_route = _alignment_d3d11_start_timeout_route_helper(
            dialog_live=_alignment_dialog_widgets_live(),
            status_matches=alignment_d3d11_state.get("status_file") == expected_status,
            process_active=isinstance(process, QProcess) and process.state() != QProcess.NotRunning,
            status_file_exists=expected_status.is_file(),
        )
        if not timeout_route.should_report_timeout:
            return
        _set_alignment_d3d11_progress(
            82,
            "Starting native preview renderer.",
            stage="native_start_timeout",
            detail="Native D3D11 startup timeout waiting for status.",
        )
        startup_timeout_presentation = _alignment_d3d11_startup_timeout_performance_helper()
        _set_preview_performance_status_if_ready(
            startup_timeout_presentation.summary,
            details=startup_timeout_presentation.details,
        )

    def _handle_alignment_d3d11_stderr(process: QProcess) -> None:
        if not _alignment_dialog_widgets_live():
            return
        if process is not alignment_d3d11_state.get("process"):
            return
        try:
            chunk = bytes(process.readAllStandardError()).decode("utf-8", errors="replace").strip()
        except RuntimeError:
            return
        if chunk:
            _set_alignment_d3d11_loading(False, f"Preview renderer message: {chunk[-300:]}")

    def _handle_alignment_d3d11_error(process: QProcess, error: object) -> None:
        if not _alignment_dialog_widgets_live():
            return
        if process is not alignment_d3d11_state.get("process"):
            return
        _set_alignment_d3d11_loading(False, f"Preview process error: {error}")
        _clear_source_parts_preview_rebuild_pending_if_ready()

    def _handle_alignment_d3d11_finished(process: QProcess, exit_code: int, exit_status: object) -> None:
        widgets_live = _alignment_dialog_widgets_live()
        finish_route = _alignment_d3d11_process_finished_route_helper(
            current_process=process is alignment_d3d11_state.get("process"),
            widgets_live=widgets_live,
            exit_code=exit_code,
        )
        if finish_route.should_ignore:
            return
        if widgets_live:
            _poll_alignment_d3d11_status()
        _safe_stop_alignment_timer(alignment_d3d11_status_timer)
        package_dir = _alignment_d3d11_clear_active_package_helper(alignment_d3d11_state)
        _alignment_d3d11_clear_process_status_refs_helper(alignment_d3d11_state)
        _cleanup_alignment_d3d11_package(package_dir)
        if finish_route.should_report_error:
            _set_alignment_d3d11_loading(False, f"Preview closed with code {int(exit_code)} ({exit_status}).")
            _clear_source_parts_preview_rebuild_pending_if_ready()

    def _poll_alignment_d3d11_status() -> None:
        if not _alignment_dialog_widgets_live():
            return
        status_file = alignment_d3d11_state.get("status_file")
        if not isinstance(status_file, Path):
            return
        try:
            stat = status_file.stat()
        except OSError:
            unavailable_route = _alignment_d3d11_unavailable_status_route_helper(
                preview_loaded=bool(alignment_d3d11_state.get("preview_loaded")),
                loading_stuck=_alignment_d3d11_loading_stuck(),
                reason="missing status file",
            )
            if unavailable_route.action == "ready":
                _set_alignment_d3d11_progress(100, unavailable_route.message, active=False)
            elif unavailable_route.action == "clear_stuck":
                _clear_stuck_alignment_d3d11_loading(unavailable_route.message)
            return
        signature = _d3d11_status_file_signature(stat)
        try:
            payload_text = status_file.read_text(encoding="utf-8")
        except Exception as exc:
            read_error_route = _alignment_d3d11_status_read_error_route_helper(exc)
            _set_alignment_d3d11_loading(False, read_error_route.message)
            return
        if not _alignment_d3d11_record_status_payload_helper(
            alignment_d3d11_state,
            signature=signature,
            payload_text=payload_text,
        ):
            unchanged_route = _alignment_d3d11_unavailable_status_route_helper(
                preview_loaded=bool(alignment_d3d11_state.get("preview_loaded")),
                loading_stuck=_alignment_d3d11_loading_stuck(),
                reason="unchanged status file",
            )
            if unchanged_route.action == "ready":
                _set_alignment_d3d11_progress(100, unchanged_route.message, active=False)
            elif unchanged_route.action == "clear_stuck":
                _clear_stuck_alignment_d3d11_loading(unchanged_route.message)
            return
        try:
            payload = json.loads(payload_text)
        except Exception as exc:
            parse_error_route = _alignment_d3d11_status_read_error_route_helper(exc)
            _set_alignment_d3d11_loading(False, parse_error_route.message)
            return
        if not isinstance(payload, Mapping):
            _alignment_d3d11_invalid_status_payload_route_helper()
            return
        event = _alignment_d3d11_status_event_helper(payload)
        if event == "loaded":
            loaded_quality = _alignment_d3d11_mark_loaded_package_helper(alignment_d3d11_state)
            active_request_id = int(alignment_d3d11_state.get("active_package_request_id", 0) or 0)
            drag_reload_stale = active_request_id and _alignment_d3d11_drag_reload_stale_helper(
                alignment_d3d11_state,
                alignment_d3d11_drag_transaction,
                alignment_d3d11_drag_generation,
                alignment_transform_generation,
                request_id=active_request_id,
            )
            drag_active = False
            if bool(alignment_d3d11_drag_transaction.get("active")):
                drag_active = True
            loaded_route = _alignment_d3d11_loaded_status_route_helper(
                loaded_quality=loaded_quality,
                active_request_id=active_request_id,
                drag_active=drag_active,
                drag_reload_stale=bool(drag_reload_stale),
            )
            if loaded_route.pipeline_stage:
                _set_alignment_d3d11_pipeline_stage(loaded_route.pipeline_stage, loaded_route.pipeline_detail)
            if loaded_route.should_sync_mesh_edit_preview:
                try:
                    _sync_mesh_edit_preview_settings_if_ready()
                except NameError:
                    pass
            if loaded_route.should_defer_for_drag:
                _set_alignment_d3d11_progress(100, loaded_route.progress_message, active=False)
                return
            if loaded_route.should_keep_live_transform:
                live_transform_message = loaded_route.progress_message or "Preview loaded; keeping live transform."
                _replay_alignment_d3d11_fast_transform_if_ready()
                _set_alignment_d3d11_progress(
                    100,
                    live_transform_message,
                    active=False,
                )
                return
            alignment_d3d11_preview_host.set_display_mode(str(preview_mode_combo.currentData() or "side_by_side"))
            alignment_d3d11_preview_host.set_render_tuning(_current_alignment_preview_render_settings_value())
            saved_view_state = _alignment_d3d11_saved_view_state()
            if saved_view_state:
                alignment_d3d11_preview_host.restore_view_state(saved_view_state)
            if _alignment_d3d11_loaded_package_transform_current_helper(
                alignment_d3d11_state,
                alignment_transform_generation,
                request_id=active_request_id,
            ):
                _clear_alignment_d3d11_fast_transform_state_if_ready(reset_host=True)
            _sync_highlight_sets_if_ready()
            _replay_alignment_d3d11_fast_transform_if_ready()
            channel_debug = self._archive_material_channel_debug_from_package(
                alignment_d3d11_state.get("active_package")
            )
            _set_alignment_d3d11_progress(
                100,
                loaded_route.progress_message,
                stage=loaded_route.progress_stage,
                active=False,
            )
            cache_event = str(alignment_d3d11_state.get("last_cache_event", "miss") or "miss")
            cache_label = _d3d11_cache_event_user_label(cache_event)
            timing_presentation = _alignment_d3d11_loaded_timing_presentation_helper(
                alignment_d3d11_state,
                payload,
                quality_label=_alignment_preview_quality_label_helper(alignment_d3d11_state),
                cache_label=cache_label,
                channel_debug=channel_debug,
            )
            _set_preview_performance_status_if_ready(timing_presentation.summary, details=timing_presentation.details)
            _clear_source_parts_preview_rebuild_pending_if_ready()
            if loaded_route.should_queue_archive_parity:
                _queue_alignment_archive_parity_upgrade("fast geometry loaded")
        elif event == "resources_loaded":
            _alignment_d3d11_mark_resources_loaded_helper(alignment_d3d11_state)
            resources_route = _alignment_d3d11_resources_loaded_status_route_helper(payload)
            _set_alignment_d3d11_progress(
                98,
                resources_route.message,
                stage=resources_route.stage,
                detail=resources_route.detail,
                active=resources_route.active,
            )
            if resources_route.waiting_for_visible_panel:
                return
        elif event == "loading":
            loading_route = _alignment_d3d11_loading_status_route_helper(
                payload,
                preview_loaded=bool(alignment_d3d11_state.get("preview_loaded")),
                loading_stuck=_alignment_d3d11_loading_stuck(),
            )
            message = loading_route.message
            if loading_route.action == "tooltip":
                alignment_d3d11_preview_status_label.setToolTip(message)
                return
            if loading_route.action == "clear_stuck":
                _clear_stuck_alignment_d3d11_loading("stale loading status")
                return
            _set_alignment_d3d11_progress(
                loading_route.progress_percent,
                message,
                stage=loading_route.stage,
                detail=message,
            )
        elif event == "error":
            message = _alignment_d3d11_renderer_error_message_helper(payload.get("message", ""))
            error_route = _alignment_d3d11_error_status_route_helper(message)
            if error_route.should_mark_preview_unloaded:
                _alignment_d3d11_mark_preview_unloaded_helper(alignment_d3d11_state)
            _set_alignment_d3d11_loading(False, f"Preview load failed: {error_route.message}")
            renderer_error_presentation = _alignment_d3d11_renderer_error_performance_helper(
                error_route.performance_message
            )
            _set_preview_performance_status_if_ready(
                renderer_error_presentation.summary,
                details=renderer_error_presentation.details,
            )
            if error_route.should_clear_pending_rebuild:
                _clear_source_parts_preview_rebuild_pending_if_ready()
        elif event == "closed":
            closed_route = _alignment_d3d11_closed_status_route_helper(
                alignment_preview_control_text["d3d11_closed_status"]
            )
            if closed_route.should_mark_preview_unloaded:
                _alignment_d3d11_mark_preview_unloaded_helper(alignment_d3d11_state)
            _set_alignment_d3d11_loading(False, closed_route.message)
            if closed_route.should_clear_pending_rebuild:
                _clear_source_parts_preview_rebuild_pending_if_ready()

    return SimpleNamespace(
        _apply_source_material_texture_overrides_to_ui_texture_sets=_apply_source_material_texture_overrides_to_ui_texture_sets,
        _alignment_d3d11_preview_active=_alignment_d3d11_preview_active,
        _reapply_global_flip_v_fast_preview=_reapply_global_flip_v_fast_preview,
        _try_apply_global_flip_v_fast_preview=_try_apply_global_flip_v_fast_preview,
        _alignment_default_d3d11_editor_ids=_alignment_default_d3d11_editor_ids,
        _cleanup_alignment_d3d11_package=_cleanup_alignment_d3d11_package,
        _alignment_d3d11_invalidate_package_cache=_alignment_d3d11_invalidate_package_cache,
        _alignment_d3d11_geometry_cache_key=_alignment_d3d11_geometry_cache_key,
        _alignment_d3d11_preview_cache_signature=_alignment_d3d11_preview_cache_signature,
        _alignment_d3d11_preview_cache_key=_alignment_d3d11_preview_cache_key,
        _alignment_d3d11_package_cache_get=_alignment_d3d11_package_cache_get,
        _alignment_d3d11_package_cache_put=_alignment_d3d11_package_cache_put,
        _drop_alignment_d3d11_package_reload=_drop_alignment_d3d11_package_reload,
        _alignment_d3d11_stop_process=_alignment_d3d11_stop_process,
        _alignment_d3d11_stop_worker=_alignment_d3d11_stop_worker,
        _shutdown_alignment_d3d11_preview=_shutdown_alignment_d3d11_preview,
        _safe_shutdown_alignment_d3d11_preview=_safe_shutdown_alignment_d3d11_preview,
        _side_by_side_alignment_preview_model=_side_by_side_alignment_preview_model,
        _queue_alignment_d3d11_preview=_queue_alignment_d3d11_preview,
        _alignment_d3d11_package_quality=_alignment_d3d11_package_quality,
        _queue_alignment_archive_parity_upgrade=_queue_alignment_archive_parity_upgrade,
        _queue_latest_alignment_d3d11_rebuild_for_stale_reload=_queue_latest_alignment_d3d11_rebuild_for_stale_reload,
        _handle_alignment_d3d11_stale_reload=_handle_alignment_d3d11_stale_reload,
        _handle_alignment_d3d11_package_progress=_handle_alignment_d3d11_package_progress,
        _start_alignment_d3d11_package_worker=_start_alignment_d3d11_package_worker,
        _flush_alignment_d3d11_preview_request=_flush_alignment_d3d11_preview_request,
        _handle_alignment_d3d11_package_ready=_handle_alignment_d3d11_package_ready,
        _handle_alignment_d3d11_package_error=_handle_alignment_d3d11_package_error,
        _cleanup_alignment_d3d11_package_worker_refs=_cleanup_alignment_d3d11_package_worker_refs,
        _start_alignment_d3d11_process=_start_alignment_d3d11_process,
        _check_alignment_d3d11_start_timeout=_check_alignment_d3d11_start_timeout,
        _handle_alignment_d3d11_stderr=_handle_alignment_d3d11_stderr,
        _handle_alignment_d3d11_error=_handle_alignment_d3d11_error,
        _handle_alignment_d3d11_finished=_handle_alignment_d3d11_finished,
        _poll_alignment_d3d11_status=_poll_alignment_d3d11_status,
    )


def create_alignment_preview_mode_callbacks(context: dict[str, object]) -> SimpleNamespace:
    ModelPreviewData = context.get('ModelPreviewData')
    NativePreviewPanel = context.get('NativePreviewPanel')
    QProcess = context.get('QProcess')
    _alignment_d3d11_editor_ids_for_source_indices = context.get('_alignment_d3d11_editor_ids_for_source_indices')
    _alignment_d3d11_invalidate_package_cache = context.get('_alignment_d3d11_invalidate_package_cache')
    _alignment_d3d11_live_display_mode_performance_helper = context.get('_alignment_d3d11_live_display_mode_performance_helper')
    _alignment_d3d11_mode_refresh_needed_helper = context.get('_alignment_d3d11_mode_refresh_needed_helper')
    _alignment_d3d11_preview_active = context.get('_alignment_d3d11_preview_active')
    _alignment_d3d11_preview_mode_static_refresh_needed_helper = context.get('_alignment_d3d11_preview_mode_static_refresh_needed_helper')
    _alignment_d3d11_reset_request_state_helper = context.get('_alignment_d3d11_reset_request_state_helper')
    _alignment_d3d11_stop_process = context.get('_alignment_d3d11_stop_process')
    _alignment_d3d11_stop_worker = context.get('_alignment_d3d11_stop_worker')
    _alignment_default_d3d11_editor_ids = context.get('_alignment_default_d3d11_editor_ids')
    _alignment_dialog_widgets_live = context.get('_alignment_dialog_widgets_live')
    _alignment_geometry_tab_active = context.get('_alignment_geometry_tab_active')
    _alignment_preview_help_presentation_helper = context.get('_alignment_preview_help_presentation_helper')
    _alignment_preview_mode_record_helper = context.get('_alignment_preview_mode_record_helper')
    _alignment_preview_mode_route_helper = context.get('_alignment_preview_mode_route_helper')
    _alignment_preview_renderer_route_helper = context.get('_alignment_preview_renderer_route_helper')
    _disabled_source_part_indices = context.get('_disabled_source_part_indices')
    _mark_alignment_d3d11_rebuild_reason = context.get('_mark_alignment_d3d11_rebuild_reason')
    _mesh_edit_raw_preview_active = context.get('_mesh_edit_raw_preview_active')
    _queue_selection_preview_refresh = context.get('_queue_selection_preview_refresh')
    _queue_static_preview_refresh = context.get('_queue_static_preview_refresh')
    _replay_alignment_d3d11_fast_transform = context.get('_replay_alignment_d3d11_fast_transform')
    _restore_alignment_preview_mode_view_state = context.get('_restore_alignment_preview_mode_view_state')
    _save_alignment_preview_mode_view_state = context.get('_save_alignment_preview_mode_view_state')
    _selection_highlight_sets_state_helper = context.get('_selection_highlight_sets_state_helper')
    _set_alignment_d3d11_loading = context.get('_set_alignment_d3d11_loading')
    _set_preview_performance_status = context.get('_set_preview_performance_status')
    alignment_d3d11_available = context.get('alignment_d3d11_available')
    alignment_d3d11_preview_host = context.get('alignment_d3d11_preview_host')
    alignment_d3d11_preview_page = context.get('alignment_d3d11_preview_page')
    alignment_d3d11_state = context.get('alignment_d3d11_state')
    alignment_preview_control_text = context.get('alignment_preview_control_text')
    alignment_preview_mode_state = context.get('alignment_preview_mode_state')
    alignment_preview_settings_button = context.get('alignment_preview_settings_button')
    control_tabs = context.get('control_tabs')

    def _geometry_tab_active() -> bool:
        if not callable(_alignment_geometry_tab_active):
            return False
        return bool(_alignment_geometry_tab_active())

    def _d3d11_preview_active() -> bool:
        if not callable(_alignment_d3d11_preview_active):
            return False
        return bool(_alignment_d3d11_preview_active())

    def _d3d11_editor_ids_for_source_indices(indices: object, **kwargs: object) -> tuple[object, ...]:
        if not callable(_alignment_d3d11_editor_ids_for_source_indices):
            return ()
        return tuple(_alignment_d3d11_editor_ids_for_source_indices(indices, **kwargs) or ())

    def _disabled_source_indices() -> tuple[object, ...]:
        if not callable(_disabled_source_part_indices):
            return ()
        return tuple(_disabled_source_part_indices() or ())

    def _default_d3d11_editor_ids() -> tuple[object, ...]:
        if not callable(_alignment_default_d3d11_editor_ids):
            return ()
        return tuple(_alignment_default_d3d11_editor_ids() or ())

    highlighted_original_indices = context.get('highlighted_original_indices')
    highlighted_source_indices = context.get('highlighted_source_indices')
    original_dialog_preview = context.get('original_dialog_preview')
    overlay_dialog_preview = context.get('overlay_dialog_preview')
    overlay_original_locked_checkbox = context.get('overlay_original_locked_checkbox')
    preview_gizmo_checkbox = context.get('preview_gizmo_checkbox')
    preview_help = context.get('preview_help')
    preview_mode_combo = context.get('preview_mode_combo')
    preview_renderer_combo = context.get('preview_renderer_combo')
    preview_stack = context.get('preview_stack')
    replacement_only_preview = context.get('replacement_only_preview')
    selected_original_highlight_indices = context.get('selected_original_highlight_indices')
    selected_source_highlight_indices = context.get('selected_source_highlight_indices')
    selected_target_original_highlight_indices = context.get('selected_target_original_highlight_indices')
    selected_target_source_highlight_indices = context.get('selected_target_source_highlight_indices')
    static_dialog_preview = context.get('static_dialog_preview')
    textures_tab = context.get('textures_tab')

    def _set_preview_renderer() -> None:
        if not _alignment_dialog_widgets_live():
            return
        renderer_route = _alignment_preview_renderer_route_helper(
            preview_renderer_combo.currentData(),
            d3d11_available=alignment_d3d11_available,
            d3d11_active=_d3d11_preview_active(),
        )
        if renderer_route.should_report_unavailable:
            _set_alignment_d3d11_loading(False, alignment_preview_control_text["d3d11_unavailable_status"])
        if renderer_route.should_show_d3d11_preview:
            d3d11_preview_help = _alignment_preview_help_presentation_helper(d3d11_active=True)
            preview_stack.setCurrentWidget(alignment_d3d11_preview_page)
            preview_help.setText(d3d11_preview_help.text)
            preview_help.setToolTip(d3d11_preview_help.tooltip)
            alignment_preview_settings_button.setToolTip(d3d11_preview_help.settings_tooltip)
            if renderer_route.should_sync_highlights:
                _sync_highlight_sets()
            if renderer_route.should_queue_selection_preview_refresh:
                _queue_selection_preview_refresh()
            return
        if renderer_route.should_reset_d3d11_state:
            _alignment_d3d11_reset_request_state_helper(
                alignment_d3d11_state,
                clear_active_metadata=True,
            )
        if renderer_route.should_stop_d3d11_worker:
            _alignment_d3d11_stop_worker()
        if renderer_route.should_invalidate_d3d11_cache:
            _alignment_d3d11_invalidate_package_cache("renderer")
        if renderer_route.should_stop_d3d11_process:
            _alignment_d3d11_stop_process()
        static_preview_help = _alignment_preview_help_presentation_helper(d3d11_active=False)
        preview_help.setText(static_preview_help.text)
        preview_help.setToolTip(static_preview_help.tooltip)
        alignment_preview_settings_button.setToolTip(static_preview_help.settings_tooltip)
        if renderer_route.should_apply_static_preview_mode:
            _set_preview_mode()

    def _sync_highlight_sets() -> None:
        d3d11_active = _d3d11_preview_active()
        geometry_active = _geometry_tab_active() if d3d11_active else False
        selection_state = _selection_highlight_sets_state_helper(
            selected_source_highlights=tuple(selected_source_highlight_indices),
            selected_target_source_highlights=tuple(selected_target_source_highlight_indices),
            selected_original_highlights=tuple(selected_original_highlight_indices),
            selected_target_original_highlights=tuple(selected_target_original_highlight_indices),
            d3d11_active=d3d11_active,
            geometry_active=geometry_active,
            texture_tab_active=control_tabs.widget(control_tabs.currentIndex()) is textures_tab if d3d11_active else False,
            mesh_edit_raw_active=bool(_mesh_edit_raw_preview_active()) if d3d11_active else False,
            preview_gizmo_checked=bool(preview_gizmo_checkbox.isChecked()) if d3d11_active else False,
            selected_source_overlay_ids=(
                _d3d11_editor_ids_for_source_indices(
                    tuple(selected_source_highlight_indices),
                    selection_overlay=True,
                )
                if d3d11_active
                else ()
            ),
            selected_source_editor_ids=(
                _d3d11_editor_ids_for_source_indices(tuple(selected_source_highlight_indices))
                if d3d11_active
                else ()
            ),
            selected_target_source_editor_ids=(
                _d3d11_editor_ids_for_source_indices(tuple(selected_target_source_highlight_indices))
                if d3d11_active
                else ()
            ),
            disabled_source_editor_ids=(
                _d3d11_editor_ids_for_source_indices(_disabled_source_indices())
                if d3d11_active
                else ()
            ),
            default_d3d11_editor_ids=_default_d3d11_editor_ids() if d3d11_active else (),
        )
        highlighted_source_indices.clear()
        highlighted_source_indices.update(tuple(selection_state["highlighted_source_indices"]))  # type: ignore[arg-type]
        highlighted_original_indices.clear()
        highlighted_original_indices.update(tuple(selection_state["highlighted_original_indices"]))  # type: ignore[arg-type]
        if d3d11_active:
            alignment_d3d11_preview_host.set_highlighted_alignment_submeshes(
                replacement_submesh_indices=tuple(selection_state["d3d11_highlighted_indices"]),  # type: ignore[arg-type]
                original_submesh_indices=tuple(selection_state["d3d11_original_highlighted_indices"]),  # type: ignore[arg-type]
            )
            alignment_d3d11_preview_host.set_hidden_source_submeshes(
                tuple(selection_state["d3d11_hidden_source_indices"])  # type: ignore[arg-type]
            )
            alignment_d3d11_preview_host.set_alignment_state(
                enabled=bool(selection_state["d3d11_gizmo_enabled"]),
                source_submesh_indices=tuple(selection_state["d3d11_selected_indices"]),  # type: ignore[arg-type]
                translation_sensitivity=0.85,
                rotation_degrees_per_pixel=0.18,
            )
            try:
                if callable(_replay_alignment_d3d11_fast_transform):
                    _replay_alignment_d3d11_fast_transform()
            except NameError:
                pass

    def _preview_mode_qt_widgets(mode: str) -> tuple[NativePreviewPanel, ...]:
        normalized_mode = str(mode or "side_by_side")
        if normalized_mode == "replacement_only":
            return (replacement_only_preview,)
        if normalized_mode == "overlay":
            return (overlay_dialog_preview,)
        return (original_dialog_preview, static_dialog_preview)

    def _preview_mode_needs_static_refresh(mode: str) -> bool:
        if _d3d11_preview_active():
            mode_refresh_needed = _alignment_d3d11_mode_refresh_needed_helper(
                alignment_d3d11_state,
                mode,
                queued_model_active=isinstance(alignment_d3d11_state.get("queued_model"), ModelPreviewData),
                pending_model_active=isinstance(alignment_d3d11_state.get("pending_model"), ModelPreviewData),
                mesh_edit_raw_preview_active=_mesh_edit_raw_preview_active(),
            )
            if mode_refresh_needed:
                return True
            process = alignment_d3d11_state.get("process")
            renderer_active = isinstance(process, QProcess) and process.state() != QProcess.NotRunning
            queued = isinstance(alignment_d3d11_state.get("queued_model"), ModelPreviewData)
            pending = isinstance(alignment_d3d11_state.get("pending_model"), ModelPreviewData)
            return _alignment_d3d11_preview_mode_static_refresh_needed_helper(
                alignment_d3d11_state,
                mode_refresh_needed=False,
                renderer_active=renderer_active,
                queued_model_active=queued,
                pending_model_active=pending,
            )
        return any(
            getattr(widget, "_current_model", None) is None
            for widget in _preview_mode_qt_widgets(mode)
        )

    def _set_preview_mode() -> None:
        mode = str(preview_mode_combo.currentData() or "side_by_side")
        previous_mode, mode = _alignment_preview_mode_record_helper(alignment_preview_mode_state, mode)
        if previous_mode != mode:
            _save_alignment_preview_mode_view_state(previous_mode)
        needs_static_refresh = _preview_mode_needs_static_refresh(mode)
        mode_route = _alignment_preview_mode_route_helper(
            mode,
            d3d11_active=_d3d11_preview_active(),
            needs_static_refresh=needs_static_refresh,
        )
        if mode_route.d3d11_active:
            if mode_route.should_set_live_d3d11_mode:
                alignment_d3d11_preview_host.set_display_mode(mode_route.mode)
                live_mode_presentation = _alignment_d3d11_live_display_mode_performance_helper(mode)
                _set_preview_performance_status(
                    live_mode_presentation.summary,
                    details=live_mode_presentation.details,
                )
            if mode_route.should_mark_d3d11_rebuild:
                _mark_alignment_d3d11_rebuild_reason("mode_missing_original")
            preview_stack.setCurrentWidget(alignment_d3d11_preview_page)
            if mode_route.should_restore_view_state:
                _restore_alignment_preview_mode_view_state(mode_route.mode)
            if mode_route.should_replay_fast_transform:
                if callable(_replay_alignment_d3d11_fast_transform):
                    _replay_alignment_d3d11_fast_transform()
        else:
            preview_stack.setCurrentIndex(mode_route.static_stack_index)
            if mode_route.should_restore_view_state:
                _restore_alignment_preview_mode_view_state(mode_route.mode)
        overlay_original_locked_checkbox.blockSignals(True)
        overlay_original_locked_checkbox.setChecked(True)
        overlay_original_locked_checkbox.blockSignals(False)
        overlay_original_locked_checkbox.setEnabled(False)
        if mode_route.should_queue_static_preview_refresh:
            _queue_static_preview_refresh()

    return SimpleNamespace(
        _set_preview_renderer=_set_preview_renderer,
        _sync_highlight_sets=_sync_highlight_sets,
        _preview_mode_qt_widgets=_preview_mode_qt_widgets,
        _preview_mode_needs_static_refresh=_preview_mode_needs_static_refresh,
        _set_preview_mode=_set_preview_mode,
    )


def create_alignment_preview_model_callbacks(context: dict[str, object]) -> SimpleNamespace:
    CollapsibleSection = context.get('CollapsibleSection')
    Dict = context.get('Dict')
    List = context.get('List')
    Mapping = context.get('Mapping')
    ModelPreviewData = context.get('ModelPreviewData')
    Optional = context.get('Optional')
    Path = context.get('Path')
    QLabel = context.get('QLabel')
    QSizePolicy = context.get('QSizePolicy')
    QVBoxLayout = context.get('QVBoxLayout')
    QWidget = context.get('QWidget')
    Qt = context.get('Qt')
    SCENE_TEXTURE_SOURCE_EXTENSIONS = context.get('SCENE_TEXTURE_SOURCE_EXTENSIONS')
    SceneImportResult = context.get('SceneImportResult')
    Sequence = context.get('Sequence')
    StaticIndependentPart = context.get('StaticIndependentPart')
    StaticMeshReplacementOptions = context.get('StaticMeshReplacementOptions')
    StaticReplacementTransform = context.get('StaticReplacementTransform')
    StaticSourcePartAdjustment = context.get('StaticSourcePartAdjustment')
    StaticSubmeshMapping = context.get('StaticSubmeshMapping')
    StaticTextureSlotOverride = context.get('StaticTextureSlotOverride')
    _alignment_d3d11_preview_source_editor_id_map_state_helper = context.get('_alignment_d3d11_preview_source_editor_id_map_state_helper')
    _alignment_d3d11_record_source_editor_id_maps_helper = context.get('_alignment_d3d11_record_source_editor_id_maps_helper')
    _alignment_dialog_widgets_live = context.get('_alignment_dialog_widgets_live')
    _alignment_mesh_edit_tab_active = context.get('_alignment_mesh_edit_tab_active')
    _alignment_preview_background_source_face_limit = context.get('_alignment_preview_background_source_face_limit')
    _alignment_preview_selected_source_face_limit = context.get('_alignment_preview_selected_source_face_limit')
    _alignment_startup_step = context.get('_alignment_startup_step')
    _alignment_virtual_texture_contract_defaults_helper = context.get('_alignment_virtual_texture_contract_defaults_helper')
    _apply_missing_texture_overlay_color_helper = context.get('_apply_missing_texture_overlay_color_helper')
    _apply_original_material_preview_helper = context.get('_apply_original_material_preview_helper')
    _apply_source_selection_overlay_model_state_helper = context.get('_apply_source_selection_overlay_model_state_helper')
    _best_source_for_slot_helper = context.get('_best_source_for_slot_helper')
    _binding_matches_target_helper = context.get('_binding_matches_target_helper')
    _combine_optional_preview_models_helper = context.get('_combine_optional_preview_models_helper')
    _combine_preview_with_overlay_helper = context.get('_combine_preview_with_overlay_helper')
    _complete_external_swap_enabled = context.get('_complete_external_swap_enabled')
    _complete_external_swap_mappings = context.get('_complete_external_swap_mappings')
    _copy_exact_clone_original_preview_materials_helper = context.get('_copy_exact_clone_original_preview_materials_helper')
    _copy_original_preview_material_helper = context.get('_copy_original_preview_material_helper')
    _current_donor_material_plans = context.get('_current_donor_material_plans')
    _current_source_material_texture_overrides = context.get('_current_source_material_texture_overrides')
    _current_source_part_adjustments = context.get('_current_source_part_adjustments')
    _current_texture_uv_transforms = context.get('_current_texture_uv_transforms')
    _disabled_source_indices_from_adjustments_helper = context.get('_disabled_source_indices_from_adjustments_helper')
    _enabled_renderable_source_indices = context.get('_enabled_renderable_source_indices')
    _geometry_mapping_summary_html_helper = context.get('_geometry_mapping_summary_html_helper')
    _independent_parts_helper = context.get('_independent_parts_helper')
    _is_marker_source = context.get('_is_marker_source')
    _load_original_reference_texture_preview = context.get('_load_original_reference_texture_preview')
    _looks_like_standalone_pbr_source = context.get('_looks_like_standalone_pbr_source')
    _mapped_source_indices_helper = context.get('_mapped_source_indices_helper')
    _mapping_table_build_complete_helper = context.get('_mapping_table_build_complete_helper')
    _mapping_text_valid_source_indices_helper = context.get('_mapping_text_valid_source_indices_helper')
    _morph_slider_reload_profiles = context.get('_morph_slider_reload_profiles')
    _original_reference_texture_preview_ready_state_helper = context.get('_original_reference_texture_preview_ready_state_helper')
    _original_texture_preview_material_preview_enabled_helper = context.get('_original_texture_preview_material_preview_enabled_helper')
    _output_impact_review_presentation_helper = context.get('_output_impact_review_presentation_helper')
    _parse_mapping_edit = context.get('_parse_mapping_edit')
    _parsed_preview_mesh_from_submeshes_helper = context.get('_parsed_preview_mesh_from_submeshes_helper')
    _part_specific_tokens_helper = context.get('_part_specific_tokens_helper')
    _preview_model_in_original_frame_helper = context.get('_preview_model_in_original_frame_helper')
    _preview_overlay_offset_helper = context.get('_preview_overlay_offset_helper')
    _preview_target_mesh_indices_helper = context.get('_preview_target_mesh_indices_helper')
    _qt_object_is_valid = context.get('_qt_object_is_valid')
    _refresh_mesh_replacement_properties_inspector = context.get('_refresh_mesh_replacement_properties_inspector')
    _register_texture_source_files_helper = context.get('_register_texture_source_files_helper')
    _selected_part_preview_indices_helper = context.get('_selected_part_preview_indices_helper')
    _selected_source_overlay_indices_helper = context.get('_selected_source_overlay_indices_helper')
    _set_alignment_d3d11_progress = context.get('_set_alignment_d3d11_progress')
    _set_preview_performance_status = context.get('_set_preview_performance_status')
    _source_display_name = context.get('_source_display_name')
    _source_index_groups_for_overlay_helper = context.get('_source_index_groups_for_overlay_helper')
    _source_index_is_enabled_renderable = context.get('_source_index_is_enabled_renderable')
    _source_indices_from_pairs_helper = context.get('_source_indices_from_pairs_helper')
    _source_indices_in_range_helper = context.get('_source_indices_in_range_helper')
    _source_mesh_pairs_for_indices_helper = context.get('_source_mesh_pairs_for_indices_helper')
    _source_overlay_preview_index_state_helper = context.get('_source_overlay_preview_index_state_helper')
    _source_preview_geometry_key_helper = context.get('_source_preview_geometry_key_helper')
    _source_renderable_indices_helper = context.get('_source_renderable_indices_helper')
    _source_selection_overlay_adjustments_helper = context.get('_source_selection_overlay_adjustments_helper')
    _source_selection_overlay_index_state_helper = context.get('_source_selection_overlay_index_state_helper')
    _source_texture_evidence_by_local_path_helper = context.get('_source_texture_evidence_by_local_path_helper')
    _submeshes_from_source_pairs_helper = context.get('_submeshes_from_source_pairs_helper')
    _target_display_name = context.get('_target_display_name')
    _target_submesh_display_name_helper = context.get('_target_submesh_display_name_helper')
    _texture_file_lookup_maps_helper = context.get('_texture_file_lookup_maps_helper')
    _texture_uv_transform_payload_helper = context.get('_texture_uv_transform_payload_helper')
    _transformed_replacement_sources = context.get('_transformed_replacement_sources')
    _unmapped_appended_source_indices_helper = context.get('_unmapped_appended_source_indices_helper')
    _visible_direct_source_pairs_helper = context.get('_visible_direct_source_pairs_helper')
    alignment_d3d11_state = context.get('alignment_d3d11_state')
    alignment_mode_combo = context.get('alignment_mode_combo')
    alignment_startup_text = context.get('alignment_startup_text')
    alignment_virtual_texture_contract = context.get('alignment_virtual_texture_contract')
    appended_source_indices = context.get('appended_source_indices')
    classify_texture_binding = context.get('classify_texture_binding')
    clone_mesh_for_editing = context.get('clone_mesh_for_editing')
    default_pac_xml_profile_cache_path = context.get('default_pac_xml_profile_cache_path')
    direct_source_preview_index_map = context.get('direct_source_preview_index_map')
    discover_scene_texture_files = context.get('discover_scene_texture_files')
    flip_direction_checkbox = context.get('flip_direction_checkbox')
    geometry_overview_group = context.get('geometry_overview_group')
    geometry_overview_layout = context.get('geometry_overview_layout')
    geometry_summary = context.get('geometry_summary')
    independent_output_source_indices = context.get('independent_output_source_indices')
    mapping_edits = context.get('mapping_edits')
    mapping_group = context.get('mapping_group')
    mapping_table_action_control_text = context.get('mapping_table_action_control_text')
    mapping_table_build_state = context.get('mapping_table_build_state')
    mesh_edit_enabled_checkbox = context.get('mesh_edit_enabled_checkbox')
    mesh_edit_group = context.get('mesh_edit_group')
    mesh_edit_layout_page = context.get('mesh_edit_layout_page')
    mesh_edit_revision = context.get('mesh_edit_revision')
    modify_original_clone_mode = context.get('modify_original_clone_mode')
    morph_slider_group = context.get('morph_slider_group')
    normalize_texture_reference_for_sidecar_lookup = context.get('normalize_texture_reference_for_sidecar_lookup')
    obj_path = context.get('obj_path')
    offset_x_spin = context.get('offset_x_spin')
    offset_y_spin = context.get('offset_y_spin')
    offset_z_spin = context.get('offset_z_spin')
    original_dialog_preview = context.get('original_dialog_preview')
    original_mesh_for_mapping = context.get('original_mesh_for_mapping')
    original_part_copies = context.get('original_part_copies')
    original_reference_preview_model = context.get('original_reference_preview_model')
    original_reference_texture_preview_state = context.get('original_reference_texture_preview_state')
    original_texture_preview_state = context.get('original_texture_preview_state')
    output_impact_review_label = context.get('output_impact_review_label')
    part_inspector = context.get('part_inspector')
    parts_layout = context.get('parts_layout')
    parts_tab = context.get('parts_tab')
    preview_only_source_indices = context.get('preview_only_source_indices')
    preview_submesh_index_map = context.get('preview_submesh_index_map')
    prompt_shell_context = context.get('prompt_shell_context')
    prune_unmapped_original_dds_checkbox = context.get('prune_unmapped_original_dds_checkbox')
    _queue_alignment_post_open_task = context.get('_queue_alignment_post_open_task')
    rebuild_sidecar_checkbox = context.get('rebuild_sidecar_checkbox')
    replacement_mesh_base_for_mapping = context.get('replacement_mesh_base_for_mapping')
    replacement_mesh_for_mapping = context.get('replacement_mesh_for_mapping')
    rotate_x_spin = context.get('rotate_x_spin')
    rotate_y_spin = context.get('rotate_y_spin')
    rotate_z_spin = context.get('rotate_z_spin')
    scale_to_length_checkbox = context.get('scale_to_length_checkbox')
    scale_x_spin = context.get('scale_x_spin')
    scale_y_spin = context.get('scale_y_spin')
    scale_z_spin = context.get('scale_z_spin')
    scene_import_result = context.get('scene_import_result')
    selected_source_highlight_indices = context.get('selected_source_highlight_indices')
    selected_source_part = context.get('selected_source_part')
    self = context.get('self')
    source_geometry_revision = context.get('source_geometry_revision')
    source_overlay_preview_index_map = context.get('source_overlay_preview_index_map')
    source_part_adjustments = context.get('source_part_adjustments')
    source_selection_overlay_editor_id_map = context.get('source_selection_overlay_editor_id_map')
    source_selection_overlay_preview_index_map = context.get('source_selection_overlay_preview_index_map')
    source_texture_evidence = context.get('source_texture_evidence')
    suggested_mappings = context.get('suggested_mappings')
    supplemental_files = context.get('supplemental_files')
    texture_override_rows = context.get('texture_override_rows')

    def _prompt_context_value(name: str, default: object = None) -> object:
        if isinstance(prompt_shell_context, dict) and name in prompt_shell_context:
            return prompt_shell_context.get(name, default)
        return context.get(name, default)

    _queue_alignment_post_open_task = _prompt_context_value(
        "_queue_alignment_post_open_task",
        _queue_alignment_post_open_task,
    )

    def _spin_value(name: str, default: float = 0.0) -> float:
        spin = _prompt_context_value(name)
        value = getattr(spin, "value", None)
        if not callable(value):
            return default
        try:
            return float(value())
        except (RuntimeError, TypeError, ValueError):
            return default

    def _checkbox_checked(name: str, default: bool = False) -> bool:
        checkbox = _prompt_context_value(name)
        is_checked = getattr(checkbox, "isChecked", None)
        if not callable(is_checked):
            return default
        try:
            return bool(is_checked())
        except RuntimeError:
            return default

    def _combo_data(name: str, default: str = "grid_flat") -> object:
        combo = _prompt_context_value(name)
        current_data = getattr(combo, "currentData", None)
        if not callable(current_data):
            return default
        try:
            return current_data()
        except RuntimeError:
            return default

    def _refresh_output_impact_review() -> None:
        if not _alignment_dialog_widgets_live():
            return
        if not _qt_object_is_valid(output_impact_review_label):
            return
        removed_targets: List[str] = []
        used_sources: set[int] = set()
        disabled_mapped_sources: set[int] = set()
        for target_index, edit in mapping_edits:
            source_indices = _parse_mapping_edit(edit)
            enabled_source_indices = _enabled_renderable_source_indices(source_indices)
            if not enabled_source_indices:
                removed_targets.append(_target_display_name(target_index))
            used_sources.update(int(index) for index in enabled_source_indices)
            disabled_mapped_sources.update(
                int(index)
                for index in source_indices
                if int(index) not in enabled_source_indices
            )
        generated_dds_count = len(
            [
                row
                for row in texture_override_rows
                if str(row.get("checked", "") or "").lower() in {"1", "true"}
                or bool(str(row.get("assigned_source", "") or row.get("suggested_source", "") or "").strip())
            ]
        )
        sidecar_enabled = _checkbox_checked("rebuild_sidecar_checkbox")
        prune_unmapped_enabled = _checkbox_checked("prune_unmapped_original_dds_checkbox")
        output_impact = _output_impact_review_presentation_helper(
            removed_targets,
            len(used_sources),
            len(disabled_mapped_sources),
            len(preview_only_source_indices),
            generated_dds_count,
            sidecar_enabled=sidecar_enabled,
            prune_unmapped_enabled=prune_unmapped_enabled,
        )
        output_impact_review_label.setText(output_impact["html"])
        output_impact_review_label.setToolTip(output_impact["tooltip"])
        _refresh_mesh_replacement_properties_inspector()

    def _refresh_geometry_summary() -> None:
        if not _alignment_dialog_widgets_live():
            return
        if not _qt_object_is_valid(geometry_summary):
            return
        source_count = sum(
            1
            for source in getattr(replacement_mesh_for_mapping, "submeshes", ()) or ()
            if not _is_marker_source(source)
        )
        active_target_count = sum(
            1
            for _target_index, edit in mapping_edits
            if _enabled_renderable_source_indices(_parse_mapping_edit(edit))
        )
        empty_target_count = max(0, len(mapping_edits) - active_target_count)
        appended_count = int(source_geometry_revision.get("value", 0) or 0)
        geometry_summary.setText(
            _geometry_mapping_summary_html_helper(
                source_count,
                active_target_count,
                empty_target_count,
                session_edit_count=appended_count,
            )
        )
    geometry_hint = QLabel(mapping_table_action_control_text["geometry_hint_html"])
    geometry_hint.setWordWrap(True)
    geometry_hint.setTextFormat(Qt.RichText)
    geometry_hint.setObjectName("HintLabel")
    geometry_hint.setToolTip(mapping_table_action_control_text["geometry_hint_tooltip"])
    geometry_overview_layout.addWidget(geometry_hint)
    geometry_overview_group.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)

    def _refresh_startup_model_controls() -> None:
        _refresh_geometry_summary()
        _refresh_output_impact_review()
        _refresh_mesh_replacement_properties_inspector()
        _morph_slider_reload_profiles()

    parts_outliner_panel = QWidget(parts_tab)
    parts_outliner_panel.setObjectName("PartsRoutingOutlinerPropertiesStack")
    parts_outliner_layout = QVBoxLayout(parts_outliner_panel)
    parts_outliner_layout.setContentsMargins(0, 0, 0, 0)
    parts_outliner_layout.setSpacing(3)
    parts_outliner_layout.addWidget(mapping_group, 0)
    advanced_part_tools_section = CollapsibleSection(
        mapping_table_action_control_text["advanced_part_transform"],
        expanded=False,
    )
    advanced_part_tools_section.body_layout.addWidget(part_inspector)
    parts_outliner_layout.addWidget(advanced_part_tools_section, 0)
    parts_outliner_layout.addStretch(1)
    parts_layout.addWidget(parts_outliner_panel, 1)
    parts_layout.addStretch(1)
    if callable(_queue_alignment_post_open_task):
        _queue_alignment_post_open_task(_refresh_startup_model_controls)
    elif _prompt_context_value("rotate_x_spin") is not None:
        _refresh_startup_model_controls()
    mesh_edit_layout_page.addWidget(mesh_edit_group, 0)
    mesh_edit_layout_page.addWidget(morph_slider_group, 0)
    mesh_edit_layout_page.addStretch(1)

    _alignment_startup_step(alignment_startup_text["replacement_texture_sources"])
    texture_files_for_mapping: List[Path] = []
    seen_texture_file_keys: set[str] = set()
    auto_scene_texture_sources: List[Path] = []
    if isinstance(scene_import_result, SceneImportResult):
        auto_scene_texture_sources.extend(
            path
            for path in tuple(scene_import_result.discovered_texture_files or ())
            + tuple(scene_import_result.extracted_embedded_files or ())
            + tuple(getattr(scene_import_result, "discovered_supplemental_files", ()) or ())
            if isinstance(path, Path)
        )
    try:
        auto_scene_texture_sources.extend(discover_scene_texture_files(obj_path, replacement_mesh_for_mapping))
    except Exception:
        pass
    _register_texture_source_files_helper(
        tuple(supplemental_files or ()) + tuple(auto_scene_texture_sources),
        texture_files_for_mapping=texture_files_for_mapping,
        seen_texture_file_keys=seen_texture_file_keys,
        allowed_extensions=SCENE_TEXTURE_SOURCE_EXTENSIONS,
    )
    source_texture_evidence_by_local_path = _source_texture_evidence_by_local_path_helper(source_texture_evidence)
    texture_files_by_basename, texture_files_by_normalized_source_path = _texture_file_lookup_maps_helper(
        texture_files_for_mapping,
        source_texture_evidence_by_local_path,
        normalize_texture_reference=normalize_texture_reference_for_sidecar_lookup,
    )

    _part_specific_tokens = lambda value: _part_specific_tokens_helper(value)

    _binding_matches_target = lambda binding, target_name: _binding_matches_target_helper(
        binding,
        target_name,
    )

    _best_source_for_slot = lambda target_name, source_indices, slot_kind, texture_sets_by_key, *, parameter_name="", target_texture_path="", target_shader_family="": _best_source_for_slot_helper(
        target_name,
        source_indices,
        slot_kind,
        texture_sets_by_key,
        parameter_name=parameter_name,
        target_texture_path=target_texture_path,
        target_shader_family=target_shader_family,
        texture_files_for_mapping=texture_files_for_mapping,
        texture_files_by_basename=texture_files_by_basename,
        texture_files_by_normalized_source_path=texture_files_by_normalized_source_path,
        source_texture_evidence_by_local_path_map=source_texture_evidence_by_local_path,
        replacement_mesh=replacement_mesh_for_mapping,
        classify_texture_binding=classify_texture_binding,
        normalize_texture_reference=normalize_texture_reference_for_sidecar_lookup,
        looks_like_standalone_pbr_source=_looks_like_standalone_pbr_source,
    )

    def _current_dialog_mappings_for_preview() -> List[StaticSubmeshMapping]:
        if _complete_external_swap_enabled():
            return _complete_external_swap_mappings()
        mapping_table_ready = True
        try:
            mapping_table_ready = _mapping_table_build_complete_helper(mapping_table_build_state)
        except NameError:
            mapping_table_ready = True
        if (
            not mapping_edits
            or not mapping_table_ready
            or original_mesh_for_mapping is None
            or replacement_mesh_for_mapping is None
        ):
            return list(suggested_mappings or [])
        render_source_indices = set(
            _source_renderable_indices_helper(
                replacement_mesh_for_mapping,
                source_part_adjustments,
                is_marker_source=_is_marker_source,
            )
        )
        parsed_mappings: List[StaticSubmeshMapping] = []
        for target_index, edit in mapping_edits:
            source_indices = list(_mapping_text_valid_source_indices_helper(edit.text(), render_source_indices))
            target = original_mesh_for_mapping.submeshes[target_index]
            parsed_mappings.append(
                StaticSubmeshMapping(
                    target_submesh_index=target_index,
                    target_submesh_name=_target_submesh_display_name_helper(target_index, target),
                    source_submesh_indices=source_indices,
                    target_material_slot_index=target_index,
                    merge_sources=True,
                )
            )
        return parsed_mappings

    def _preview_target_mesh_indices(
        preview_model: object,
        target_name: str,
        fallback_indices: Sequence[int],
        *,
        mapped_preview: bool,
        current_mappings: Sequence[StaticSubmeshMapping],
    ) -> List[int]:
        return list(
            _preview_target_mesh_indices_helper(
                preview_model,
                target_name,
                fallback_indices,
                mapped_preview=mapped_preview,
                current_mappings=current_mappings,
                preview_submesh_index_map=preview_submesh_index_map,
            )
        )

    _preview_model_in_original_frame = lambda parsed_mesh, *, source_indices=None, source_index_map=None, parsed_submesh_index_map=None: _preview_model_in_original_frame_helper(
        parsed_mesh,
        normalization_center=getattr(original_reference_preview_model, "normalization_center", (0.0, 0.0, 0.0)),
        normalization_scale=float(getattr(original_reference_preview_model, "normalization_scale", 1.0) or 1.0),
        source_indices=source_indices,
        source_index_map=source_index_map,
        parsed_submesh_index_map=parsed_submesh_index_map,
    )

    _source_preview_geometry_key = lambda current_mappings: _source_preview_geometry_key_helper(
        current_mappings,
        _current_source_part_adjustments(),
        original_part_copies,
        alignment_mode=str(_combo_data("alignment_mode_combo") or "grid_flat"),
        scale_to_length=_checkbox_checked("scale_to_length_checkbox"),
        flip=_checkbox_checked("flip_direction_checkbox"),
        rotate_xyz=(
            _spin_value("rotate_x_spin"),
            _spin_value("rotate_y_spin"),
            _spin_value("rotate_z_spin"),
        ),
        scale_xyz=(
            _spin_value("scale_x_spin", 1.0),
            _spin_value("scale_y_spin", 1.0),
            _spin_value("scale_z_spin", 1.0),
        ),
        offset_xyz=(
            _spin_value("offset_x_spin"),
            _spin_value("offset_y_spin"),
            _spin_value("offset_z_spin"),
        ),
        texture_uv_payload=_texture_uv_transform_payload_helper(_current_texture_uv_transforms()),
        mesh_edit_revision=int(mesh_edit_revision.get("value", 0) or 0),
        source_geometry_revision=int(source_geometry_revision.get("value", 0) or 0),
        independent_output_source_indices=independent_output_source_indices,
        preview_only_source_indices=preview_only_source_indices,
    )

    _mapped_source_indices = lambda current_mappings: _mapped_source_indices_helper(current_mappings)

    def _current_independent_parts(
        *,
        include_preview_only: bool = False,
        current_mappings: Sequence[StaticSubmeshMapping] | None = None,
    ) -> list[StaticIndependentPart]:
        return list(
            _independent_parts_helper(
                replacement_mesh=replacement_mesh_for_mapping,
                independent_output_source_indices=independent_output_source_indices,
                preview_only_source_indices=preview_only_source_indices,
                current_mappings=current_mappings if current_mappings is not None else _current_dialog_mappings_for_preview(),
                source_part_adjustments=source_part_adjustments,
                default_adjustment=StaticSourcePartAdjustment,
                is_marker_source=_is_marker_source,
                source_display_name=_source_display_name,
                independent_part_type=StaticIndependentPart,
                include_preview_only=include_preview_only,
            )
        )

    def _current_static_alignment_transform() -> StaticReplacementTransform:
        return StaticReplacementTransform(
            rotate_xyz_degrees=(
                _spin_value("rotate_x_spin"),
                _spin_value("rotate_y_spin"),
                _spin_value("rotate_z_spin"),
            ),
            scale=_spin_value("scale_x_spin", 1.0),
            scale_xyz=(
                _spin_value("scale_x_spin", 1.0),
                _spin_value("scale_y_spin", 1.0),
                _spin_value("scale_z_spin", 1.0),
            ),
            offset_xyz=(
                _spin_value("offset_x_spin"),
                _spin_value("offset_y_spin"),
                _spin_value("offset_z_spin"),
            ),
            scale_to_original_length=_checkbox_checked("scale_to_length_checkbox"),
            alignment_mode=str(_combo_data("alignment_mode_combo") or "grid_flat"),
            flip_target_axis=_checkbox_checked("flip_direction_checkbox"),
        )

    def _current_static_placement_snapshot(
        current_mappings: Sequence[StaticSubmeshMapping],
        *,
        include_preview_only_independent_parts: bool,
    ) -> Dict[str, object]:
        return {
            "transform": _current_static_alignment_transform(),
            "submesh_mappings": list(current_mappings or []),
            "source_part_adjustments": _current_source_part_adjustments(),
            "texture_uv_transforms": _current_texture_uv_transforms(),
            "source_material_texture_overrides": _current_source_material_texture_overrides(),
            "donor_material_plans": _current_donor_material_plans(),
            "original_part_copies": list(original_part_copies),
            "global_transform_exempt_source_indices": sorted(int(index) for index in appended_source_indices),
            "independent_output_parts": _current_independent_parts(
                include_preview_only=include_preview_only_independent_parts,
                current_mappings=current_mappings,
            ),
            "removed_target_submesh_indices": sorted(
                int(mapping.target_submesh_index)
                for mapping in tuple(current_mappings or ())
                if not any(
                    _source_index_is_enabled_renderable(int(source_index))
                    for source_index in tuple(getattr(mapping, "source_submesh_indices", ()) or ())
                )
            ),
            "mesh_edit_revision": int(mesh_edit_revision.get("value", 0) or 0),
            "source_geometry_revision": int(source_geometry_revision.get("value", 0) or 0),
            "preview_only_source_indices": sorted(int(index) for index in preview_only_source_indices),
        }

    def _static_options_from_placement_snapshot(
        placement_snapshot: Mapping[str, object],
        *,
        texture_slot_overrides: Sequence[StaticTextureSlotOverride] = (),
        include_edited_source_mesh: bool = False,
        additional_supplemental_files: Sequence[object] = (),
        rebuild_material_sidecar: bool = False,
        complete_external_swap: bool = False,
        neutralize_inherited_material_layers: bool = False,
        complete_external_material_reset: bool = False,
        enable_missing_base_color_parameters: bool = False,
        texture_output_size_mode: str = "source",
        complete_swap_material_profile: str = "material_authority_detail_mask",
        global_gloss_reduction: float = 0.0,
        edge_relief_strength: float = 0.0,
        edge_relief_source: str = "hybrid",
        accent_glow_strength: float = 0.0,
        auto_brightness_balance: float = 50.0,
        dark_detail_lift: float = 0.0,
        tone_contrast: float = 0.0,
        allow_unsafe_material_preflight_export: bool = False,
        custom_item_icon_override: object | None = None,
        prune_unmapped_original_texture_parameters: bool = False,
    ) -> StaticMeshReplacementOptions:
        edited_source_mesh = None
        if (
            include_edited_source_mesh
            and replacement_mesh_for_mapping is not None
            and (
                int(placement_snapshot.get("mesh_edit_revision", 0) or 0) > 0
                or int(placement_snapshot.get("source_geometry_revision", 0) or 0) > 0
            )
        ):
            edited_source_mesh = clone_mesh_for_editing(replacement_mesh_for_mapping)
        pac_xml_corpus_root = ""
        archive_extract_widget = getattr(self, "archive_extract_root_edit", None)
        if archive_extract_widget is not None:
            try:
                pac_xml_corpus_root = archive_extract_widget.text().strip()
            except Exception:
                pac_xml_corpus_root = ""
        return StaticMeshReplacementOptions(
            transform=placement_snapshot["transform"],
            submesh_mappings=list(placement_snapshot.get("submesh_mappings", []) or []),
            edited_source_mesh=edited_source_mesh,
            rebuild_material_sidecar=bool(rebuild_material_sidecar),
            complete_external_swap=bool(complete_external_swap),
            neutralize_inherited_material_layers=bool(neutralize_inherited_material_layers),
            complete_external_material_reset=bool(complete_external_material_reset),
            enable_missing_base_color_parameters=bool(enable_missing_base_color_parameters),
            texture_slot_overrides=list(texture_slot_overrides or []),
            source_material_texture_overrides=list(
                placement_snapshot.get("source_material_texture_overrides", []) or []
            ),
            donor_material_plans=list(placement_snapshot.get("donor_material_plans", []) or []),
            texture_output_size_mode=str(texture_output_size_mode or "source"),
            complete_swap_material_profile=str(complete_swap_material_profile or "material_authority_detail_mask"),
            global_gloss_reduction=max(-100.0, min(100.0, float(global_gloss_reduction or 0.0))),
            edge_relief_strength=max(0.0, min(100.0, float(edge_relief_strength or 0.0))),
            edge_relief_source=str(edge_relief_source or "hybrid"),
            accent_glow_strength=max(0.0, min(100.0, float(accent_glow_strength or 0.0))),
            auto_brightness_balance=max(0.0, min(100.0, float(auto_brightness_balance or 0.0))),
            dark_detail_lift=max(-100.0, min(100.0, float(dark_detail_lift or 0.0))),
            tone_contrast=max(-100.0, min(100.0, float(tone_contrast or 0.0))),
            allow_unsafe_material_preflight_export=bool(allow_unsafe_material_preflight_export),
            texture_uv_transforms=list(placement_snapshot.get("texture_uv_transforms", []) or []),
            source_part_adjustments=list(placement_snapshot.get("source_part_adjustments", []) or []),
            original_part_copies=list(placement_snapshot.get("original_part_copies", []) or []),
            removed_target_submesh_indices=list(
                placement_snapshot.get("removed_target_submesh_indices", []) or []
            ),
            prune_removed_target_texture_parameters=bool(
                rebuild_material_sidecar
                and prune_unmapped_original_texture_parameters
                and placement_snapshot.get("removed_target_submesh_indices", [])
            ),
            prune_unmapped_original_texture_parameters=bool(
                rebuild_material_sidecar
                and prune_unmapped_original_texture_parameters
            ),
            global_transform_exempt_source_indices=list(
                placement_snapshot.get("global_transform_exempt_source_indices", []) or []
            ),
            independent_output_parts=list(placement_snapshot.get("independent_output_parts", []) or []),
            additional_supplemental_files=list(additional_supplemental_files or []),
            custom_item_icon_override=custom_item_icon_override,
            pac_xml_corpus_root=pac_xml_corpus_root,
            pac_xml_profile_cache_path=str(default_pac_xml_profile_cache_path(self.settings_file_path.parent)),
        )

    _unmapped_appended_source_indices = lambda current_mappings: _unmapped_appended_source_indices_helper(
        replacement_mesh=replacement_mesh_for_mapping,
        appended_source_indices=appended_source_indices,
        current_mappings=current_mappings,
        source_part_adjustments=source_part_adjustments,
        default_adjustment=StaticSourcePartAdjustment,
        is_marker_source=_is_marker_source,
    )

    def _build_unmapped_appended_source_overlay_model(
        current_mappings: Sequence[StaticSubmeshMapping],
    ) -> Optional[ModelPreviewData]:
        if original_mesh_for_mapping is None or replacement_mesh_for_mapping is None:
            return None
        overlay_source_indices = _unmapped_appended_source_indices(current_mappings)
        if not overlay_source_indices:
            return None
        background_overlay_indices, selected_overlay_indices = _source_index_groups_for_overlay_helper(
            overlay_source_indices,
            selected_source_index=int(selected_source_part.get("index", -1)),
        )

        def build_overlay_subset(
            subset_indices: Sequence[int],
            *,
            face_limit: int,
        ) -> Optional[ModelPreviewData]:
            subset_indices = tuple(int(index) for index in subset_indices)
            if not subset_indices:
                return None
            transformed_sources = _transformed_replacement_sources(
                original_mesh_for_mapping,
                replacement_mesh_for_mapping,
                _current_static_alignment_transform(),
                _current_source_part_adjustments(),
                _current_texture_uv_transforms(),
                global_transform_exempt_indices=set(),
                global_transform_source_indices=(
                    _mapped_source_indices(current_mappings) | set(overlay_source_indices)
                ),
                max_source_faces_per_submesh=face_limit,
                output_source_indices=set(subset_indices),
            )
            overlay_pairs = list(_source_mesh_pairs_for_indices_helper(transformed_sources, subset_indices))
            if not overlay_pairs:
                return None
            overlay_sources = _submeshes_from_source_pairs_helper(overlay_pairs)
            local_index_map: Dict[int, int] = {}
            overlay_model = _preview_model_in_original_frame(
                _parsed_preview_mesh_from_submeshes_helper(
                    replacement_mesh_for_mapping,
                    overlay_sources,
                ),
                source_indices=_source_indices_from_pairs_helper(overlay_pairs),
                source_index_map=local_index_map,
            )
            _apply_missing_texture_overlay_color_helper(overlay_model)
            return overlay_model

        return _combine_optional_preview_models_helper(
            (
                build_overlay_subset(
                    background_overlay_indices,
                    face_limit=_alignment_preview_background_source_face_limit(background_overlay_indices),
                ),
                build_overlay_subset(
                    selected_overlay_indices,
                    face_limit=_alignment_preview_selected_source_face_limit(selected_overlay_indices),
                ),
            )
        )

    def _append_unmapped_appended_source_overlays(
        preview_model: object,
        current_mappings: Sequence[StaticSubmeshMapping],
    ) -> object:
        source_overlay_preview_index_map.clear()
        if not isinstance(preview_model, ModelPreviewData):
            return preview_model
        overlay_model = _build_unmapped_appended_source_overlay_model(current_mappings)
        overlay_offset = _preview_overlay_offset_helper(preview_model, overlay_model)
        if overlay_offset is None:
            return preview_model
        source_overlay_preview_index_map.update(
            _source_overlay_preview_index_state_helper(
                overlay_model,
                overlay_offset=overlay_offset,
            )
        )
        return _combine_preview_with_overlay_helper(preview_model, overlay_model)

    def _source_selection_overlay_adjustments(source_indices: Sequence[int]) -> List[StaticSourcePartAdjustment]:
        return list(
            _source_selection_overlay_adjustments_helper(
                source_indices,
                _current_source_part_adjustments(),
                StaticSourcePartAdjustment,
            )
        )

    def _mesh_edit_enabled_checked() -> bool:
        is_checked = getattr(mesh_edit_enabled_checkbox, "isChecked", None)
        if not callable(is_checked):
            return False
        try:
            return bool(is_checked())
        except RuntimeError:
            return False

    def _mesh_edit_active_for_alignment_basis() -> bool:
        return bool(
            _mesh_edit_enabled_checked()
            and callable(_alignment_mesh_edit_tab_active)
            and _alignment_mesh_edit_tab_active()
        )

    def _build_selected_source_highlight_overlay_model(
        current_mappings: Sequence[StaticSubmeshMapping],
    ) -> Optional[ModelPreviewData]:
        if original_mesh_for_mapping is None or replacement_mesh_for_mapping is None:
            return None
        requested_source_indices = _selected_source_overlay_indices_helper(
            selected_source_highlight_indices,
            replacement_mesh_for_mapping.submeshes,
            is_marker_source=_is_marker_source,
        )
        if not requested_source_indices:
            return None
        transformed_sources = _transformed_replacement_sources(
            original_mesh_for_mapping,
            replacement_mesh_for_mapping,
            _current_static_alignment_transform(),
            _source_selection_overlay_adjustments(requested_source_indices),
            _current_texture_uv_transforms(),
            global_transform_exempt_indices=set(),
            global_transform_source_indices=(
                _mapped_source_indices(current_mappings) | set(requested_source_indices)
            ),
            max_source_faces_per_submesh=_alignment_preview_selected_source_face_limit(requested_source_indices),
            output_source_indices=set(requested_source_indices),
            alignment_basis_mesh=(
                replacement_mesh_base_for_mapping
                if _mesh_edit_active_for_alignment_basis()
                else None
            ),
        )
        overlay_pairs = list(_source_mesh_pairs_for_indices_helper(transformed_sources, requested_source_indices))
        if not overlay_pairs:
            return None
        overlay_sources = _submeshes_from_source_pairs_helper(overlay_pairs)
        overlay_model = _preview_model_in_original_frame(
            _parsed_preview_mesh_from_submeshes_helper(
                replacement_mesh_for_mapping,
                overlay_sources,
            ),
            source_indices=_source_indices_from_pairs_helper(overlay_pairs),
            source_index_map={},
        )
        _apply_source_selection_overlay_model_state_helper(overlay_model)
        return overlay_model

    def _append_selected_source_highlight_overlay(
        preview_model: object,
        current_mappings: Sequence[StaticSubmeshMapping],
    ) -> object:
        source_selection_overlay_preview_index_map.clear()
        source_selection_overlay_editor_id_map.clear()
        if not isinstance(preview_model, ModelPreviewData):
            return preview_model
        overlay_model = _build_selected_source_highlight_overlay_model(current_mappings)
        overlay_offset = _preview_overlay_offset_helper(preview_model, overlay_model)
        if overlay_offset is None:
            return preview_model
        preview_index_state, editor_id_state = _source_selection_overlay_index_state_helper(
            overlay_model,
            overlay_offset=overlay_offset,
        )
        source_selection_overlay_preview_index_map.update(preview_index_state)
        source_selection_overlay_editor_id_map.update(editor_id_state)
        return _combine_preview_with_overlay_helper(preview_model, overlay_model)

    def _build_direct_source_preview_model(
        current_mappings: Sequence[StaticSubmeshMapping],
        preview_source_indices: Sequence[int],
    ) -> Optional[ModelPreviewData]:
        if original_mesh_for_mapping is None or replacement_mesh_for_mapping is None:
            return None
        source_mesh = replacement_mesh_for_mapping
        requested_source_indices = _source_indices_in_range_helper(
            preview_source_indices,
            len(source_mesh.submeshes),
        )
        transformed_sources = _transformed_replacement_sources(
            original_mesh_for_mapping,
            source_mesh,
            _current_static_alignment_transform(),
            _current_source_part_adjustments(),
            _current_texture_uv_transforms(),
            global_transform_exempt_indices=set(),
            global_transform_source_indices=(
                _mapped_source_indices(current_mappings) | requested_source_indices
            ),
            max_source_faces_per_submesh=0,
            output_source_indices=requested_source_indices,
            alignment_basis_mesh=(
                replacement_mesh_base_for_mapping
                if _mesh_edit_active_for_alignment_basis()
                else None
            ),
        )
        disabled_source_indices = _disabled_source_indices_from_adjustments_helper(
            source_part_adjustments.values()
        )
        visible_source_pairs = list(
            _visible_direct_source_pairs_helper(
                transformed_sources,
                requested_source_indices=requested_source_indices,
                disabled_source_indices=disabled_source_indices,
                is_marker_source=_is_marker_source,
            )
        )
        if not visible_source_pairs:
            direct_source_preview_index_map.clear()
            return None
        visible_sources = _submeshes_from_source_pairs_helper(visible_source_pairs)
        direct_source_preview_index_map.clear()
        return _preview_model_in_original_frame(
            _parsed_preview_mesh_from_submeshes_helper(
                source_mesh,
                visible_sources,
            ),
            source_indices=_source_indices_from_pairs_helper(visible_source_pairs),
            source_index_map=direct_source_preview_index_map,
        )

    def _selected_part_preview_indices(
        preview_model: object,
        *,
        mapped_preview: bool,
        current_mappings: Sequence[StaticSubmeshMapping],
    ) -> Optional[List[int]]:
        indices = _selected_part_preview_indices_helper(
            preview_model,
            source_index=int(selected_source_part.get("index", -1)),
            highlighted_source_indices=selected_source_highlight_indices,
            mapped_preview=mapped_preview,
            current_mappings=current_mappings,
            direct_source_preview_index_map=direct_source_preview_index_map,
            source_overlay_preview_index_map=source_overlay_preview_index_map,
            preview_target_mesh_indices=lambda model, target_name, fallback, mapped, mappings: _preview_target_mesh_indices(
                model,
                target_name,
                fallback,
                mapped_preview=mapped,
                current_mappings=mappings,
            ),
        )
        return None if indices is None else list(indices)

    def _remember_alignment_d3d11_source_editor_ids(
        preview_model: object,
        *,
        mapped_preview: bool,
        current_mappings: Sequence[StaticSubmeshMapping],
    ) -> None:
        map_state = _alignment_d3d11_preview_source_editor_id_map_state_helper(
            preview_model,
            mapped_preview=mapped_preview,
            current_mappings=current_mappings,
            source_overlay_preview_index_map=source_overlay_preview_index_map,
            source_selection_overlay_preview_index_map=source_selection_overlay_preview_index_map,
            direct_source_preview_index_map=direct_source_preview_index_map,
            preview_submesh_index_map=preview_submesh_index_map,
            preview_target_mesh_indices=lambda model, target_name, source_indices, mapped, mappings: _preview_target_mesh_indices(
                model,
                target_name,
                source_indices,
                mapped_preview=mapped,
                current_mappings=mappings,
            ),
        )
        _alignment_d3d11_record_source_editor_id_maps_helper(
            alignment_d3d11_state,
            **map_state,
        )

    def _copy_original_preview_material(
        dst_mesh: object,
        src_mesh: object,
        *,
        copy_matching_surface: bool = False,
    ) -> None:
        _copy_original_preview_material_helper(
            dst_mesh,
            src_mesh,
            copy_matching_surface=copy_matching_surface,
        )

    _copy_exact_clone_original_preview_materials = lambda preview_model: _copy_exact_clone_original_preview_materials_helper(
        preview_model,
        modify_original_clone_mode=modify_original_clone_mode,
        original_texture_preview_enabled=_original_texture_preview_material_preview_enabled_helper(
            modify_original_clone_mode,
            original_texture_preview_state,
        ),
        original_reference_preview_model=original_reference_preview_model,
    )

    def _apply_original_material_preview(
        preview_model: object,
        *,
        mapped_preview: bool,
        current_mappings: Sequence[StaticSubmeshMapping],
    ) -> None:
        _apply_original_material_preview_helper(
            preview_model,
            original_texture_preview_enabled=_original_texture_preview_material_preview_enabled_helper(
                modify_original_clone_mode,
                original_texture_preview_state,
            ),
            original_reference_preview_model=original_reference_preview_model,
            modify_original_clone_mode=bool(modify_original_clone_mode),
            mapped_preview=mapped_preview,
            current_mappings=current_mappings,
            direct_source_preview_index_map=direct_source_preview_index_map,
            preview_target_mesh_indices=lambda model, target_name, source_indices, mapped, mappings: _preview_target_mesh_indices(
                model,
                target_name,
                source_indices,
                mapped_preview=mapped,
                current_mappings=mappings,
            ),
        )

    def _ensure_original_reference_texture_preview_ready(
        active_preview_mode: str,
        *,
        reason: str,
    ) -> bool:
        readiness_state = _original_reference_texture_preview_ready_state_helper(
            original_reference_texture_preview_state,
            active_preview_mode=active_preview_mode,
            has_original_reference_model=original_reference_preview_model is not None,
            reason=reason,
        )
        if readiness_state.ready:
            return True
        _set_alignment_d3d11_progress(
            10,
            readiness_state.progress_message,
            stage="source_textures",
            detail=readiness_state.message,
        )
        original_dialog_preview.clear_model(readiness_state.message)
        _set_preview_performance_status(
            readiness_state.performance.summary,
            details=readiness_state.performance.details,
        )
        if readiness_state.should_start_load:
            _load_original_reference_texture_preview()
        return False

    def _refresh_alignment_virtual_sidecar_contract(
        parsed_mappings: Sequence[StaticSubmeshMapping],
    ) -> Dict[str, object]:
        # Early preview refreshes can run before the texture-override table helpers
        # below have rebound this name to the full sidecar contract builder.
        _alignment_virtual_texture_contract_defaults_helper(alignment_virtual_texture_contract)
        return alignment_virtual_texture_contract

    return SimpleNamespace(
        _refresh_output_impact_review=_refresh_output_impact_review,
        _refresh_geometry_summary=_refresh_geometry_summary,
        _current_dialog_mappings_for_preview=_current_dialog_mappings_for_preview,
        _preview_target_mesh_indices=_preview_target_mesh_indices,
        _current_independent_parts=_current_independent_parts,
        _current_static_alignment_transform=_current_static_alignment_transform,
        _current_static_placement_snapshot=_current_static_placement_snapshot,
        _static_options_from_placement_snapshot=_static_options_from_placement_snapshot,
        _build_unmapped_appended_source_overlay_model=_build_unmapped_appended_source_overlay_model,
        _append_unmapped_appended_source_overlays=_append_unmapped_appended_source_overlays,
        _source_selection_overlay_adjustments=_source_selection_overlay_adjustments,
        _build_selected_source_highlight_overlay_model=_build_selected_source_highlight_overlay_model,
        _append_selected_source_highlight_overlay=_append_selected_source_highlight_overlay,
        _build_direct_source_preview_model=_build_direct_source_preview_model,
        _selected_part_preview_indices=_selected_part_preview_indices,
        _remember_alignment_d3d11_source_editor_ids=_remember_alignment_d3d11_source_editor_ids,
        _copy_original_preview_material=_copy_original_preview_material,
        _apply_original_material_preview=_apply_original_material_preview,
        _ensure_original_reference_texture_preview_ready=_ensure_original_reference_texture_preview_ready,
        _refresh_alignment_virtual_sidecar_contract=_refresh_alignment_virtual_sidecar_contract,
    )
