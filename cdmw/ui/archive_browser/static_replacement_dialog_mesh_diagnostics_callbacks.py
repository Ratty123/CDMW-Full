"""Mesh diagnostics callback factory for the static replacement dialog."""

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
    prompt_shell_context = context.get('prompt_shell_context')

    def _live_value(name: str, fallback: object = None) -> object:
        if isinstance(prompt_shell_context, dict) and name in prompt_shell_context:
            return prompt_shell_context.get(name)
        return context.get(name, fallback)

    def _widget_value(name: str, method: str, default: object = "") -> object:
        callback = getattr(_live_value(name), method, None)
        if not callable(callback):
            return default
        return callback()

    def _callback_value(name: str, default: object = False) -> object:
        callback = _live_value(name)
        if not callable(callback):
            return default
        return callback()

    def _selected_source_index() -> int:
        current = _live_value("selected_source_part", selected_source_part)
        getter = getattr(current, "get", None)
        if not callable(getter):
            return -1
        return int(getter("index", -1))

    def _highlighted_source_indices() -> tuple[int, ...]:
        values = _live_value("highlighted_source_indices", highlighted_source_indices) or ()
        return tuple(sorted(int(index) for index in values))

    def _current_texture_sets() -> object:
        getter = _live_value("_get_texture_sets")
        if callable(getter):
            return getter()
        return _live_value("texture_sets", texture_sets) or {}

    def _mesh_edit_tab_active() -> bool:
        active_callback = _live_value("_alignment_mesh_edit_tab_active", _alignment_mesh_edit_tab_active)
        if not callable(active_callback):
            return False
        return bool(active_callback())

    def _mesh_edit_enabled_checked() -> bool:
        is_checked = getattr(_live_value("mesh_edit_enabled_checkbox", mesh_edit_enabled_checkbox), "isChecked", None)
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
        current_d3d11_state = _live_value("alignment_d3d11_state", alignment_d3d11_state)
        if not callable(getattr(current_d3d11_state, "get", None)):
            current_d3d11_state = {}
        lines: List[str] = []

        lines.append("Mesh Editor Replacement Diagnostics")
        lines.append(f"updated: {time.strftime('%Y-%m-%d %H:%M:%S')}")
        lines.append("")
        _mesh_editor_diagnostics_append_safe_value_helper(lines, "target", lambda: str(getattr(entry, "path", "") or getattr(entry, "basename", "") or ""))
        _mesh_editor_diagnostics_append_safe_value_helper(lines, "source", lambda: str(obj_path))
        _mesh_editor_diagnostics_append_safe_value_helper(lines, "embedded_builder", lambda: bool(embedded_alignment_builder))
        _mesh_editor_diagnostics_append_safe_value_helper(lines, "native_host", lambda: str(find_native_d3d11_host() or "missing"))
        _mesh_editor_diagnostics_append_safe_value_helper(lines, "preview_mode", lambda: str(_widget_value("preview_mode_combo", "currentData") or ""))
        _mesh_editor_diagnostics_append_safe_value_helper(lines, "renderer", lambda: str(_widget_value("preview_renderer_combo", "currentData") or ""))
        _mesh_editor_diagnostics_append_safe_value_helper(lines, "render_diagnostic_mode", lambda: str(_widget_value("preview_render_mode_combo", "currentData") or ""))
        _mesh_editor_diagnostics_append_safe_value_helper(lines, "visible_texture_mode", lambda: str(_widget_value("preview_visible_mode_combo", "currentData") or ""))
        _mesh_editor_diagnostics_append_safe_value_helper(lines, "d3d11_active", lambda: bool(_callback_value("_alignment_d3d11_preview_active")))
        _mesh_editor_diagnostics_append_safe_value_helper(lines, "d3d11_status_label", lambda: _widget_value("alignment_d3d11_preview_status_label", "text"))
        _mesh_editor_diagnostics_append_safe_value_helper(lines, "preview_timing_label", lambda: _widget_value("preview_performance_label", "text"))
        _mesh_editor_diagnostics_append_safe_value_helper(lines, "mesh_edit_tab_active", _mesh_edit_tab_active)
        _mesh_editor_diagnostics_append_safe_value_helper(lines, "mesh_edit_enabled", _mesh_edit_enabled_checked)
        _mesh_editor_diagnostics_append_safe_value_helper(lines, "mesh_edit_raw_preview_active", lambda: bool(_callback_value("_mesh_edit_raw_preview_active")))
        _mesh_editor_diagnostics_append_safe_value_helper(lines, "mesh_edit_show_vertices", lambda: bool(_widget_value("mesh_edit_show_vertices_checkbox", "isChecked", False)))
        _mesh_editor_diagnostics_append_safe_value_helper(lines, "mesh_edit_tool", lambda: str(_widget_value("mesh_edit_tool_combo", "currentData") or ""))
        _mesh_editor_diagnostics_append_safe_value_helper(lines, "mesh_edit_scope", lambda: str(_widget_value("mesh_edit_scope_combo", "currentData") or ""))
        _mesh_editor_diagnostics_append_safe_value_helper(lines, "source_face_limit", lambda: int(_callback_value("_alignment_preview_source_face_limit", 0)))
        _mesh_editor_diagnostics_append_safe_value_helper(lines, "selected_source", _selected_source_index)
        _mesh_editor_diagnostics_append_safe_value_helper(lines, "highlighted_sources", _highlighted_source_indices)
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
            lines.append(f"  {key}: {current_d3d11_state.get(key)}")
        lines.append(f"  active_package: {current_d3d11_state.get('active_package')}")
        lines.append(f"  status_file: {current_d3d11_state.get('status_file')}")
        process = current_d3d11_state.get("process")
        if isinstance(process, QProcess):
            lines.append(f"  process_state: {process.state()}")
            lines.append(f"  process_program: {process.program()}")
            lines.append(f"  process_start_arguments: {' '.join(process.arguments())}")
        lines.append("")
        lines.append("Source geometry")
        try:
            lines.extend(
                _mesh_editor_diagnostics_source_mesh_lines(
                    "replacement_mesh_for_mapping",
                    _live_value("replacement_mesh_for_mapping", replacement_mesh_for_mapping),
                    enabled_predicate=_source_index_is_enabled_renderable,
                )
            )
            lines.extend(
                _mesh_editor_diagnostics_source_mesh_lines(
                    "replacement_mesh_base_for_mapping",
                    _live_value("replacement_mesh_base_for_mapping", replacement_mesh_base_for_mapping),
                    limit=6,
                    enabled_predicate=_source_index_is_enabled_renderable,
                )
            )
        except NameError as exc:
            lines.append(f"source geometry unavailable: {exc}")
        lines.append("")
        lines.append("Preview model")
        try:
            lines.extend(_mesh_editor_diagnostics_model_lines("replacement_preview_model", _live_value("replacement_preview_model", replacement_preview_model)))
        except NameError as exc:
            lines.append(f"preview model unavailable: {exc}")
        queued_model = current_d3d11_state.get("queued_model")
        pending_model = current_d3d11_state.get("pending_model")
        if isinstance(queued_model, ModelPreviewData):
            lines.extend(_mesh_editor_diagnostics_model_lines("queued_d3d11_model", queued_model, limit=8))
        if isinstance(pending_model, ModelPreviewData):
            lines.extend(_mesh_editor_diagnostics_model_lines("pending_d3d11_model", pending_model, limit=8))
        lines.append("")
        lines.append("Material groups")
        try:
            texture_file_count = len(_live_value("texture_files_for_mapping", texture_files_for_mapping) or ())
        except NameError:
            texture_file_count = 0
        try:
            current_texture_sets = _current_texture_sets()
            lines.append(f"  texture_files_for_mapping={texture_file_count:,} texture_sets={len(current_texture_sets):,}")
            for index, texture_set in enumerate(list(current_texture_sets.values())[:18]):
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
        lines.extend(_mesh_editor_diagnostics_manifest_lines(current_d3d11_state.get("active_package")))
        lines.append("")
        lines.append("Latest native status")
        status_payload_text = str(current_d3d11_state.get("status_payload_text", "") or "").strip()
        if status_payload_text:
            try:
                status_payload = json.loads(status_payload_text)
                lines.append(json.dumps(status_payload, indent=2, sort_keys=True)[:12000])
            except ValueError:
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
            # Best-effort diagnostics UI refresh: the widget may be closing or deleted.
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
