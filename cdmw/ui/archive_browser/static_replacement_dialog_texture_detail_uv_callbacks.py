"""Texture detail and UV transform callback factory for the static replacement dialog."""

from __future__ import annotations

from types import SimpleNamespace

from cdmw.ui.archive_browser.static_replacement_texture_async import (
    DdsDetailPreviewResult,
    StaticReplacementDdsDetailController,
)


def create_alignment_texture_detail_uv_callbacks(context: dict[str, object]) -> SimpleNamespace:
    Path = context.get('Path')
    QPixmap = context.get('QPixmap')
    Qt = context.get('Qt')
    _dds_detail_refresh_route_state_helper = context.get('_dds_detail_refresh_route_state_helper')
    _dds_detail_resolved_thumbnail_state_helper = context.get('_dds_detail_resolved_thumbnail_state_helper')
    _default_texture_uv_transform_state = context.get('_default_texture_uv_transform_state')
    _queue_texture_uv_preview_refresh = context.get('_queue_texture_uv_preview_refresh')
    _resolve_dds_detail_preview_path_helper = context.get('_resolve_dds_detail_preview_path_helper')
    _texture_transform_controls_set_loading_helper = context.get('_texture_transform_controls_set_loading_helper')
    _texture_uv_transform_control_load_state_helper = context.get('_texture_uv_transform_control_load_state_helper')
    _texture_uv_transform_control_save_state_helper = context.get('_texture_uv_transform_control_save_state_helper')
    _texture_uv_transform_key = context.get('_texture_uv_transform_key')
    _texture_uv_transform_materials_state_helper = context.get('_texture_uv_transform_materials_state_helper')
    _texture_uv_transform_reset_state_helper = context.get('_texture_uv_transform_reset_state_helper')
    dds_detail_thumbnail_label = context.get('dds_detail_thumbnail_label')
    dialog = context.get('dialog')
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
    dds_detail_controller = StaticReplacementDdsDetailController(self, dialog)
    setattr(dialog, "_dds_detail_controller", dds_detail_controller)
    dialog.finished.connect(lambda _result=0: dds_detail_controller.request_shutdown())

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
            dds_detail_controller.cancel()
            _apply_dds_detail_thumbnail_state(route_state.thumbnail)
            return
        _apply_dds_detail_thumbnail_state(route_state.thumbnail)
        texconv_text = self.texconv_path_edit.text().strip()
        texconv_path = Path(texconv_text).expanduser() if texconv_text else None

        def _resolved(result: DdsDetailPreviewResult) -> None:
            pixmap = QPixmap.fromImage(result.image) if not result.image.isNull() else None
            thumbnail_state = _dds_detail_resolved_thumbnail_state_helper(
                preview_path=result.preview_path,
                status_text=result.status_text,
                pixmap_readable=bool(pixmap is not None and not pixmap.isNull()),
                control_text=material_plan_control_text,
            )
            _apply_dds_detail_thumbnail_state(thumbnail_state, pixmap)

        def _failed(message: str) -> None:
            thumbnail_state = _dds_detail_resolved_thumbnail_state_helper(
                preview_path=None,
                status_text=f"DDS is not previewable here: {message}",
                pixmap_readable=False,
                control_text=material_plan_control_text,
            )
            _apply_dds_detail_thumbnail_state(thumbnail_state)

        dds_detail_controller.start(
            source_path=route_state.preview_source,
            slot_kind=route_state.slot_kind,
            texconv_path=texconv_path,
            on_complete=_resolved,
            on_error=_failed,
        )

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
