"""Routing and selection callback factories for static replacement dialog."""

from __future__ import annotations

from types import SimpleNamespace

from cdmw.ui.archive_browser.static_replacement_dialog_factory_runtime import (
    run_static_replacement_factory,
)
from cdmw.ui.archive_browser.static_replacement_source_part_adjustment_state import (
    source_part_glow_reason_text,
    source_part_glow_selection_state,
)
from cdmw.ui.archive_browser import static_replacement_dialog_callbacks_routing_dialog_layout_part_01 as _routing_dialog_layout_part_01
from cdmw.ui.archive_browser import static_replacement_dialog_callbacks_routing_source_part_geometry_action_part_01 as _routing_source_part_geometry_action_part_01
from cdmw.ui.archive_browser import static_replacement_dialog_callbacks_routing_complete_swap_part_01 as _routing_complete_swap_part_01


def create_alignment_dialog_layout_callbacks(context: dict[str, object]) -> SimpleNamespace:
    return run_static_replacement_factory(
        context,
        globals(),
        tuple(globals()),
        (*_routing_dialog_layout_part_01.STEPS,),
    )


def create_alignment_original_texture_intent_callbacks(context: dict[str, object]) -> SimpleNamespace:
    Dict = context.get('Dict')
    List = context.get('List')
    Path = context.get('Path')
    _archive_dds_preview_source_for_path = context.get('_archive_dds_preview_source_for_path')
    _binding_matches_target = context.get('_binding_matches_target')
    _binding_matches_target_helper = context.get('_binding_matches_target_helper')
    _copied_original_dds_badge_helper = context.get('_copied_original_dds_badge_helper')
    _copied_original_texture_tooltip_helper = context.get('_copied_original_texture_tooltip_helper')
    _matches_target = context.get('_matches_target')
    _original_index_from_tree_item = context.get('_original_index_from_tree_item')
    _original_part_texture_intent_rows_helper = context.get('_original_part_texture_intent_rows_helper')
    _original_target_label = context.get('_original_target_label')
    _preview_source_for_path = context.get('_preview_source_for_path')
    binding = context.get('binding')
    binding_names = context.get('binding_names')
    classify_texture_binding = context.get('classify_texture_binding')
    copied_original_texture_disabled_sources = context.get('copied_original_texture_disabled_sources')
    copied_original_texture_intents_by_source = context.get('copied_original_texture_intents_by_source')
    name = context.get('name')
    original_index = context.get('original_index')
    original_mesh_for_mapping = context.get('original_mesh_for_mapping')
    original_tree = context.get('original_tree')
    rows = context.get('rows')
    selected_items = context.get('selected_items')
    selected_original_part = context.get('selected_original_part')
    sidecar_bindings = context.get('sidecar_bindings')
    source_index = context.get('source_index')
    target_key = context.get('target_key')
    target_name = context.get('target_name')
    texture_path = context.get('texture_path')

    def _selected_original_index_from_tree() -> int:
        source_index = _original_index_from_tree_item(original_tree.currentItem())
        if source_index >= 0:
            return source_index
        selected_items = original_tree.selectedItems()
        return _original_index_from_tree_item(selected_items[0]) if selected_items else int(selected_original_part.get("index", -1))

    def _original_part_texture_intent_rows(original_index: int) -> List[Dict[str, str]]:
        if not callable(_original_part_texture_intent_rows_helper):
            return []

        def _preview_source_for_path(texture_path: str) -> Path | None:
            if not callable(_archive_dds_preview_source_for_path):
                return None
            try:
                return _archive_dds_preview_source_for_path(texture_path)
            except NameError:
                return None

        def _matches_target(binding: object, target_name: str) -> bool:
            try:
                if callable(_binding_matches_target):
                    return _binding_matches_target(binding, target_name)
                if callable(_binding_matches_target_helper):
                    return _binding_matches_target_helper(binding, target_name)
            except NameError:
                pass
            binding_names = (
                str(getattr(binding, "part_name", "") or ""),
                str(getattr(binding, "submesh_name", "") or ""),
                str(getattr(binding, "material_name", "") or ""),
            )
            target_key = target_name.lower()
            return any(name.strip().lower() == target_key for name in binding_names)

        def _classify_texture_binding(parameter_name: str, texture_path: str) -> object:
            if callable(classify_texture_binding):
                return classify_texture_binding(parameter_name, texture_path)
            return SimpleNamespace(slot_kind="material")

        return _original_part_texture_intent_rows_helper(
            original_index,
            original_mesh_for_mapping,
            sidecar_bindings,
            target_label=_original_target_label,
            preview_source_for_path=_preview_source_for_path,
            binding_matches_target=_matches_target,
            classify_texture_binding=_classify_texture_binding,
        )

    def _copied_original_texture_tooltip(source_index: int) -> str:
        rows = copied_original_texture_intents_by_source.get(int(source_index), [])
        return _copied_original_texture_tooltip_helper(rows)

    def _copied_original_dds_badge(source_index: int) -> str:
        rows = copied_original_texture_intents_by_source.get(int(source_index), [])
        return _copied_original_dds_badge_helper(
            source_index,
            rows,
            copied_original_texture_disabled_sources,
        )

    return SimpleNamespace(
        _selected_original_index_from_tree=_selected_original_index_from_tree,
        _original_part_texture_intent_rows=_original_part_texture_intent_rows,
        _copied_original_texture_tooltip=_copied_original_texture_tooltip,
        _copied_original_dds_badge=_copied_original_dds_badge,
    )


def create_alignment_original_clipboard_callbacks(context: dict[str, object]) -> SimpleNamespace:
    QMenu = context.get('QMenu')
    QMessageBox = context.get('QMessageBox')
    QPoint = context.get('QPoint')
    _alignment_part_clipboard_can_paste = context.get('_alignment_part_clipboard_can_paste')
    _append_original_part_payload_as_source = context.get('_append_original_part_payload_as_source')
    _copied_original_clipboard_status_message_helper = context.get('_copied_original_clipboard_status_message_helper')
    _copy_original_part_payload = context.get('_copy_original_part_payload')
    _pasted_original_source_status_message_helper = context.get('_pasted_original_source_status_message_helper')
    alignment_part_clipboard = context.get('alignment_part_clipboard')
    chosen = context.get('chosen')
    copy_action = context.get('copy_action')
    dialog = context.get('dialog')
    item = context.get('item')
    menu = context.get('menu')
    new_source_index = context.get('new_source_index')
    original_index = context.get('original_index')
    original_part_clipboard_action_text = context.get('original_part_clipboard_action_text')
    original_tree = context.get('original_tree')
    payload = context.get('payload')
    pos = context.get('pos')
    rows = context.get('rows')
    self = context.get('self')

    def _copy_original_part_to_alignment_clipboard(original_index: int = -1) -> None:
        if original_index < 0:
            original_index = _selected_original_index_from_tree()
        payload = _copy_original_part_payload(original_index)
        if payload is None:
            QMessageBox.information(
                dialog,
                original_part_clipboard_action_text["copy_select_title"],
                original_part_clipboard_action_text["copy_select_message"],
            )
            return
        alignment_part_clipboard.clear()
        alignment_part_clipboard.update(payload)
        rows = tuple(payload.get("texture_rows", ()) or ())
        self.set_status_message(_copied_original_clipboard_status_message_helper(original_index, len(rows)))

    def _paste_alignment_part_clipboard_as_replacement_source() -> None:
        if not _alignment_part_clipboard_can_paste():
            QMessageBox.information(
                dialog,
                original_part_clipboard_action_text["paste_select_title"],
                original_part_clipboard_action_text["paste_select_message"],
            )
            return
        new_source_index = _append_original_part_payload_as_source(
            alignment_part_clipboard,
            assign_to_target=False,
            preview_only=True,
            undo_label=original_part_clipboard_action_text["paste_undo_label"],
        )
        if new_source_index >= 0:
            self.set_status_message(_pasted_original_source_status_message_helper(new_source_index))

    def _show_original_parts_context_menu(pos: QPoint) -> None:
        item = original_tree.itemAt(pos)
        if item is not None:
            original_tree.setCurrentItem(item)
        menu = QMenu(original_tree)
        copy_action = menu.addAction(original_part_clipboard_action_text["copy_part_with_textures"])
        copy_action.setEnabled(_selected_original_index_from_tree() >= 0)
        chosen = menu.exec(original_tree.viewport().mapToGlobal(pos))
        if chosen is copy_action:
            _copy_original_part_to_alignment_clipboard(_selected_original_index_from_tree())

    return SimpleNamespace(
        _copy_original_part_to_alignment_clipboard=_copy_original_part_to_alignment_clipboard,
        _paste_alignment_part_clipboard_as_replacement_source=_paste_alignment_part_clipboard_as_replacement_source,
        _show_original_parts_context_menu=_show_original_parts_context_menu,
    )


def create_alignment_source_tree_role_callbacks(context: dict[str, object]) -> SimpleNamespace:
    QMenu = context.get('QMenu')
    QTreeWidgetItem = context.get('QTreeWidgetItem')
    SOURCE_TREE_ROLE_OPTIONS = context.get('SOURCE_TREE_ROLE_OPTIONS')
    _apply_source_role_selection = context.get('_apply_source_role_selection')
    _auto_fit_alignment_tree_columns = context.get('_auto_fit_alignment_tree_columns')
    _fit_alignment_tree_height_to_rows = context.get('_fit_alignment_tree_height_to_rows')
    _refresh_parts_outliner = context.get('_refresh_parts_outliner')
    _source_index_from_tree_item = context.get('_source_index_from_tree_item')
    _source_tree_population_mark_complete_helper = context.get('_source_tree_population_mark_complete_helper')
    _source_tree_population_ready_text_helper = context.get('_source_tree_population_ready_text_helper')
    _source_tree_role_menu_specs_helper = context.get('_source_tree_role_menu_specs_helper')
    action = context.get('action')
    chosen = context.get('chosen')
    column = context.get('column')
    item = context.get('item')
    label = context.get('label')
    menu = context.get('menu')
    point = context.get('point')
    rect = context.get('rect')
    role_value = context.get('role_value')
    source_index = context.get('source_index')
    source_parts_group = context.get('source_parts_group')
    source_tree = context.get('source_tree')
    source_tree_layout_state = context.get('source_tree_layout_state')
    source_tree_population_state = context.get('source_tree_population_state')
    source_tree_progress_label = context.get('source_tree_progress_label')

    def _open_source_tree_role_dropdown(item: QTreeWidgetItem, column: int) -> None:
        source_index = _source_index_from_tree_item(item)
        if source_index < 0:
            return
        menu = QMenu(source_tree)
        for label, role_value in _source_tree_role_menu_specs_helper(SOURCE_TREE_ROLE_OPTIONS):
            action = menu.addAction(label)
            action.setData(role_value)
        rect = source_tree.visualItemRect(item)
        point = source_tree.viewport().mapToGlobal(rect.bottomLeft())
        chosen = menu.exec(point)
        if chosen is None:
            return
        _apply_source_role_selection(source_index, str(chosen.data() or ""))

    def _handle_source_tree_item_clicked(item: QTreeWidgetItem, column: int) -> None:
        if item is None or int(column) != 3:
            return
        _open_source_tree_role_dropdown(item, column)

    def _finish_source_tree_population() -> None:
        _source_tree_population_mark_complete_helper(source_tree_population_state)
        source_tree_progress_label.setText(
            _source_tree_population_ready_text_helper(source_tree.topLevelItemCount())
        )
        _fit_alignment_tree_height_to_rows(source_tree, **source_tree_layout_state.height_fit_kwargs)
        _auto_fit_alignment_tree_columns(
            source_tree,
            source_tree_layout_state.autofit_min_widths,
            source_tree_layout_state.autofit_max_widths,
            expand_columns=source_tree_layout_state.expand_columns,
        )
        source_parts_group.setMaximumHeight(16777215)
        try:
            _refresh_parts_outliner()
        except NameError:
            pass

    return SimpleNamespace(
        _open_source_tree_role_dropdown=_open_source_tree_role_dropdown,
        _handle_source_tree_item_clicked=_handle_source_tree_item_clicked,
        _finish_source_tree_population=_finish_source_tree_population,
    )


def create_alignment_selection_route_callbacks(context: dict[str, object]) -> SimpleNamespace:
    _parse_mapping_edit = context.get('_parse_mapping_edit')
    _selected_source_index = context.get('_selected_source_index')
    _selected_target_index = context.get('_selected_target_index')
    _set_mapping_indices = context.get('_set_mapping_indices')
    edit = context.get('edit')
    index = context.get('index')
    indices = context.get('indices')
    mapping_edits_by_target = context.get('mapping_edits_by_target')
    source_index = context.get('source_index')
    target_index = context.get('target_index')

    def _assign_selected_source_to_target() -> None:
        source_index = _selected_source_index()
        target_index = _selected_target_index()
        if source_index < 0 or target_index < 0:
            return
        _set_mapping_indices(target_index, [source_index])

    def _merge_selected_source_into_target() -> None:
        source_index = _selected_source_index()
        target_index = _selected_target_index()
        edit = mapping_edits_by_target.get(target_index)
        if source_index < 0 or edit is None:
            return
        indices = _parse_mapping_edit(edit)
        if source_index not in indices:
            indices.append(source_index)
        _set_mapping_indices(target_index, indices)

    def _remove_selected_source_from_target() -> None:
        source_index = _selected_source_index()
        target_index = _selected_target_index()
        edit = mapping_edits_by_target.get(target_index)
        if source_index < 0 or edit is None:
            return
        _set_mapping_indices(
            target_index,
            [index for index in _parse_mapping_edit(edit) if index != source_index],
            defer_preview=True,
        )

    def _clear_selected_target() -> None:
        target_index = _selected_target_index()
        if target_index >= 0:
            _set_mapping_indices(target_index, [], defer_preview=True)

    return SimpleNamespace(
        _assign_selected_source_to_target=_assign_selected_source_to_target,
        _merge_selected_source_into_target=_merge_selected_source_into_target,
        _remove_selected_source_from_target=_remove_selected_source_from_target,
        _clear_selected_target=_clear_selected_target,
    )


def create_alignment_selection_clear_callbacks(context: dict[str, object]) -> SimpleNamespace:
    Mapping = context.get('Mapping')
    QTreeWidget = context.get('QTreeWidget')
    _clear_transform_source_indices = context.get('_clear_transform_source_indices')
    _clear_tree_current_item_helper = context.get('_clear_tree_current_item_helper')
    _load_selected_part_controls = context.get('_load_selected_part_controls')
    _part_selection_clear_scope_state_helper = context.get('_part_selection_clear_scope_state_helper')
    _queue_selection_preview_refresh = context.get('_queue_selection_preview_refresh')
    _refresh_original_reference_preview = context.get('_refresh_original_reference_preview')
    _selection_view_update_kwargs_helper = context.get('_selection_view_update_kwargs_helper')
    _set_mesh_replacement_selection_view = context.get('_set_mesh_replacement_selection_view')
    _sync_highlight_sets = context.get('_sync_highlight_sets')
    _update_mapping_status = context.get('_update_mapping_status')
    _update_selection_context = context.get('_update_selection_context')
    clear_state = context.get('clear_state')
    mapping_tree = context.get('mapping_tree')
    original_tree = context.get('original_tree')
    selected_original_highlight_indices = context.get('selected_original_highlight_indices')
    selected_original_part = context.get('selected_original_part')
    selected_source_highlight_indices = context.get('selected_source_highlight_indices')
    selected_source_part = context.get('selected_source_part')
    selected_target_original_highlight_indices = context.get('selected_target_original_highlight_indices')
    selected_target_slot = context.get('selected_target_slot')
    selected_target_source_highlight_indices = context.get('selected_target_source_highlight_indices')
    selection_payload = context.get('selection_payload')
    source_tree = context.get('source_tree')
    tree = context.get('tree')

    def _clear_tree_current_item(tree: QTreeWidget) -> None:
        _clear_tree_current_item_helper(tree)

    def _apply_part_selection_clear_scope_state(clear_state: Mapping[str, object]) -> None:
        if clear_state.get("selected_source_index") is not None:
            selected_source_part["index"] = int(clear_state["selected_source_index"])
        if clear_state.get("selected_original_index") is not None:
            selected_original_part["index"] = int(clear_state["selected_original_index"])
        if clear_state.get("selected_target_index") is not None:
            selected_target_slot["index"] = int(clear_state["selected_target_index"])
        if clear_state.get("clear_source_highlights"):
            selected_source_highlight_indices.clear()
        if clear_state.get("clear_original_highlights"):
            selected_original_highlight_indices.clear()
        if clear_state.get("clear_target_source_highlights"):
            selected_target_source_highlight_indices.clear()
        if clear_state.get("clear_target_original_highlights"):
            selected_target_original_highlight_indices.clear()
        if clear_state.get("clear_transform_sources"):
            _clear_transform_source_indices()
        selection_payload = clear_state["selection_view"]
        _set_mesh_replacement_selection_view(
            **_selection_view_update_kwargs_helper(selection_payload)  # type: ignore[arg-type]
        )

    def _clear_original_selection() -> None:
        _clear_tree_current_item(original_tree)
        _apply_part_selection_clear_scope_state(_part_selection_clear_scope_state_helper("original"))
        _sync_highlight_sets()
        _refresh_original_reference_preview()
        _update_selection_context()
        _queue_selection_preview_refresh()

    def _clear_replacement_selection() -> None:
        _clear_tree_current_item(source_tree)
        _apply_part_selection_clear_scope_state(_part_selection_clear_scope_state_helper("source"))
        _sync_highlight_sets()
        _load_selected_part_controls()
        _update_mapping_status()
        _update_selection_context()
        _queue_selection_preview_refresh()

    def _clear_target_selection() -> None:
        _clear_tree_current_item(mapping_tree)
        _apply_part_selection_clear_scope_state(_part_selection_clear_scope_state_helper("target"))
        _sync_highlight_sets()
        _refresh_original_reference_preview()
        _load_selected_part_controls()
        _update_mapping_status()
        _update_selection_context()
        _queue_selection_preview_refresh()

    return SimpleNamespace(
        _clear_tree_current_item=_clear_tree_current_item,
        _apply_part_selection_clear_scope_state=_apply_part_selection_clear_scope_state,
        _clear_original_selection=_clear_original_selection,
        _clear_replacement_selection=_clear_replacement_selection,
        _clear_target_selection=_clear_target_selection,
    )


def create_alignment_source_part_transform_control_callbacks(context: dict[str, object]) -> SimpleNamespace:
    Optional = context.get('Optional')
    QDoubleSpinBox = context.get('QDoubleSpinBox')
    QSlider = context.get('QSlider')
    _make_spinbox_slider_helper = context.get('_make_spinbox_slider_helper')
    part_offset_x_spin = context.get('part_offset_x_spin')
    part_offset_y_spin = context.get('part_offset_y_spin')
    part_offset_z_spin = context.get('part_offset_z_spin')
    part_rotate_x_spin = context.get('part_rotate_x_spin')
    part_rotate_y_spin = context.get('part_rotate_y_spin')
    part_rotate_z_spin = context.get('part_rotate_z_spin')
    part_transform_sliders = context.get('part_transform_sliders')
    scale = context.get('scale')
    slider = context.get('slider')
    slider_maximum = context.get('slider_maximum')
    slider_minimum = context.get('slider_minimum')
    slider_value = context.get('slider_value')
    spin = context.get('spin')
    tooltip = context.get('tooltip')

    def _part_transform_slider(
        spin: QDoubleSpinBox,
        *,
        scale: float,
        tooltip: str,
        slider_minimum: Optional[float] = None,
        slider_maximum: Optional[float] = None,
    ) -> QSlider:
        slider = _make_spinbox_slider_helper(
            spin,
            scale=scale,
            tooltip=tooltip,
            object_name="AlignmentPartTransformSlider",
            minimum_width=72,
            slider_minimum=slider_minimum,
            slider_maximum=slider_maximum,
        )
        part_transform_sliders[spin] = slider
        return slider

    def _sync_part_slider_from_spin(spin: QDoubleSpinBox) -> None:
        slider = part_transform_sliders.get(spin)
        if slider is None:
            return
        scale = 2000.0 if spin in (part_offset_x_spin, part_offset_y_spin, part_offset_z_spin) else 10.0 if spin in (part_rotate_x_spin, part_rotate_y_spin, part_rotate_z_spin) else 1000.0
        slider_value = int(round(float(spin.value()) * scale))
        if slider.value() == slider_value:
            return
        slider.blockSignals(True)
        slider.setValue(slider_value)
        slider.blockSignals(False)

    return SimpleNamespace(
        _part_transform_slider=_part_transform_slider,
        _sync_part_slider_from_spin=_sync_part_slider_from_spin,
    )


def _normalized_selected_glow_source_indices(
    selected_indices_getter: object,
    selected_source_part: dict[str, object],
) -> tuple[int, ...]:
    try:
        raw_indices = selected_indices_getter() if callable(selected_indices_getter) else ()
    except (AttributeError, RuntimeError, TypeError, ValueError):
        raw_indices = ()
    normalized: set[int] = set()
    for index in tuple(raw_indices or ()):
        try:
            value = int(index)
        except (TypeError, ValueError):
            continue
        if value >= 0:
            normalized.add(value)
    if normalized:
        return tuple(sorted(normalized))
    try:
        fallback = int(selected_source_part.get('index', -1))
    except (AttributeError, TypeError, ValueError):
        fallback = -1
    return (fallback,) if fallback >= 0 else ()


def _load_source_part_glow_widget_values(
    adjustment: object,
    checkbox: object,
    spins: tuple[object, ...],
    strength_checkbox: object,
    strength_spin: object,
) -> None:
    rgb = tuple(getattr(adjustment, 'emissive_color_rgb', ()) or ()) if adjustment is not None else ()
    strength = getattr(adjustment, 'emissive_strength', None) if adjustment is not None else None
    widgets = tuple(widget for widget in (checkbox, *spins, strength_checkbox, strength_spin) if widget is not None)
    previous_blocks: list[tuple[object, bool]] = []
    for widget in widgets:
        blocker = getattr(widget, 'blockSignals', None)
        previous_blocks.append((widget, bool(blocker(True)) if callable(blocker) else False))
    try:
        if checkbox is not None:
            checkbox.setChecked(len(rgb) >= 3)
        for spin, value in zip(spins, rgb[:3] if len(rgb) >= 3 else (255, 255, 255)):
            spin.setValue(max(0, min(255, int(value))))
        if strength_checkbox is not None:
            strength_checkbox.setChecked(strength is not None)
        if strength_spin is not None:
            strength_spin.setValue(max(0.0, min(20.0, float(strength if strength is not None else 1.0))))
    finally:
        for widget, previous in previous_blocks:
            blocker = getattr(widget, 'blockSignals', None)
            if callable(blocker):
                blocker(previous)


def create_alignment_source_part_glow_callbacks(context: dict[str, object]) -> SimpleNamespace:
    Optional = context.get('Optional')
    StaticSourcePartAdjustment = context.get('StaticSourcePartAdjustment')
    _complete_external_swap_enabled = context.get('_complete_external_swap_enabled')
    _source_part_glow_color_controls_state_helper = context.get('_source_part_glow_color_controls_state_helper')
    _source_part_glow_rgb_helper = context.get('_source_part_glow_rgb_helper')
    _selected_source_indices_from_tree = context.get('_selected_source_indices_from_tree')
    selected_source_part = context.get('selected_source_part')
    if not isinstance(selected_source_part, dict):
        selected_source_part = {}
    source_part_adjustments = context.get('source_part_adjustments')
    if not isinstance(source_part_adjustments, dict):
        source_part_adjustments = {}
    prompt_shell_context = context.get('prompt_shell_context')

    def _prompt_context_value(name: str) -> object:
        if isinstance(prompt_shell_context, dict) and name in prompt_shell_context:
            return prompt_shell_context.get(name)
        return context.get(name)

    def _part_glow_color_checkbox() -> object:
        return _prompt_context_value('part_glow_color_checkbox')

    def _part_glow_color_pick_button() -> object:
        return _prompt_context_value('part_glow_color_pick_button')

    def _part_glow_color_spins() -> tuple[object, ...]:
        spins = _prompt_context_value('part_glow_color_spins')
        if not isinstance(spins, (list, tuple)):
            return ()
        return tuple(
            spin
            for spin in spins
            if callable(getattr(spin, "value", None))
        )

    def _part_glow_strength_checkbox() -> object:
        return _prompt_context_value('part_glow_strength_checkbox')

    def _part_glow_strength_spin() -> object:
        return _prompt_context_value('part_glow_strength_spin')

    def _selected_glow_source_indices() -> tuple[int, ...]:
        return _normalized_selected_glow_source_indices(
            _selected_source_indices_from_tree,
            selected_source_part,
        )

    def _selected_part_glow_strength_from_controls() -> float:
        spin = _part_glow_strength_spin()
        try:
            return max(0.0, min(20.0, float(spin.value())))
        except (AttributeError, TypeError, ValueError, OverflowError):
            return 1.0

    def _selected_part_glow_rgb_from_controls() -> tuple[int, int, int]:
        values = tuple(spin.value() for spin in _part_glow_color_spins())
        if callable(_source_part_glow_rgb_helper):
            return _source_part_glow_rgb_helper(values)
        return (0, 0, 0)

    def _sync_part_glow_color_button() -> None:
        spins = _part_glow_color_spins()
        checkbox = _part_glow_color_checkbox()
        pick_button = _part_glow_color_pick_button()
        if not spins or checkbox is None or pick_button is None:
            return
        controls_state = _source_part_glow_color_controls_state_helper(
            rgb=_selected_part_glow_rgb_from_controls(),
            complete_external_swap_enabled=True,
            checked=checkbox.isChecked(),
            checkbox_enabled=checkbox.isEnabled(),
        )
        pick_button.setText(controls_state.color_text)
        pick_button.setStyleSheet(controls_state.style_sheet)

    def _refresh_part_glow_color_controls_enabled() -> None:
        spins = _part_glow_color_spins()
        checkbox = _part_glow_color_checkbox()
        pick_button = _part_glow_color_pick_button()
        strength_checkbox = _part_glow_strength_checkbox()
        strength_spin = _part_glow_strength_spin()
        if not spins or checkbox is None or pick_button is None:
            return
        selected_indices = _selected_glow_source_indices()
        # Glow used to require exactly one selected part, so a multi-part
        # selection silently edited nothing. Any selection is editable as long
        # as every part in it carries the glow role.
        selection_state = source_part_glow_selection_state(
            source_part_adjustments,
            selected_indices,
        )
        try:
            material_authority_active = bool(_complete_external_swap_enabled())
        except Exception:
            material_authority_active = True
        can_override = bool(selection_state["editable"]) and material_authority_active
        checkbox.setEnabled(can_override)
        controls_state = _source_part_glow_color_controls_state_helper(
            rgb=_selected_part_glow_rgb_from_controls(),
            complete_external_swap_enabled=can_override,
            checked=checkbox.isChecked(),
            checkbox_enabled=checkbox.isEnabled(),
        )
        for spin in spins:
            spin.setEnabled(controls_state.enabled)
        pick_button.setEnabled(controls_state.enabled)
        if strength_checkbox is not None:
            strength_checkbox.setEnabled(can_override)
        if strength_spin is not None:
            strength_spin.setEnabled(bool(can_override and strength_checkbox is not None and strength_checkbox.isChecked()))
        reason = source_part_glow_reason_text(
            selection_state,
            material_authority_active=material_authority_active,
        )
        for widget in (checkbox, pick_button, *spins, strength_checkbox, strength_spin):
            if widget is not None and reason and callable(getattr(widget, 'setToolTip', None)):
                widget.setToolTip(reason)
        _sync_part_glow_color_button()

    def _load_part_glow_color_controls(adjustment: Optional[StaticSourcePartAdjustment]) -> None:
        checkbox = _part_glow_color_checkbox()
        spins = _part_glow_color_spins()
        strength_checkbox = _part_glow_strength_checkbox()
        strength_spin = _part_glow_strength_spin()
        _load_source_part_glow_widget_values(
            adjustment,
            checkbox,
            spins,
            strength_checkbox,
            strength_spin,
        )
        _refresh_part_glow_color_controls_enabled()

    return SimpleNamespace(
        _selected_part_glow_rgb_from_controls=_selected_part_glow_rgb_from_controls,
        _selected_part_glow_strength_from_controls=_selected_part_glow_strength_from_controls,
        _selected_glow_source_indices=_selected_glow_source_indices,
        _sync_part_glow_color_button=_sync_part_glow_color_button,
        _refresh_part_glow_color_controls_enabled=_refresh_part_glow_color_controls_enabled,
        _load_part_glow_color_controls=_load_part_glow_color_controls,
    )


def create_alignment_source_part_geometry_action_callbacks(context: dict[str, object]) -> SimpleNamespace:
    return run_static_replacement_factory(
        context,
        globals(),
        tuple(globals()),
        (*_routing_source_part_geometry_action_part_01.STEPS,),
    )


def create_alignment_complete_swap_callbacks(context: dict[str, object]) -> SimpleNamespace:
    return run_static_replacement_factory(
        context,
        globals(),
        tuple(globals()),
        (*_routing_complete_swap_part_01.STEPS,),
    )
