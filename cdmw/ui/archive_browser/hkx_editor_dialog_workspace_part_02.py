from __future__ import annotations

from types import SimpleNamespace

def _dialog_step_0082(_state):
    def _browser_item_overlay_match_score(
        item: QTreeWidgetItem,
        viewer_ids: set[str],
        *,
        overlay_kind: str,
    ) -> int:
        data = item.data(0, _state.BROWSER_DATA_ROLE)
        if not isinstance(data, _state.Mapping):
            return -1
        data_viewer_id = _state._browser_data_viewer_id(data)
        if data_viewer_id not in viewer_ids:
            return -1
        editor_tab = str(data.get("editor_tab") or "")
        field = str(data.get("field") or data.get("label") or "")
        score = 1000
        if str(data.get("importable") or "").strip().lower() == "true":
            score += 300
        if editor_tab in {"Structured Editor", "Collision Editor"}:
            score += 180
        if overlay_kind == "shape" and editor_tab == "Collision Editor":
            score += 120
        if overlay_kind == "constraint" and editor_tab == "Structured Editor":
            score += 120
        if str(data.get("patch_path") or "").strip():
            score += 60
        if field and field.lower() != "summary":
            score += 20
        if str(data.get("kind") or "").strip().lower() == "node":
            score -= 120
        return score
    _state._browser_item_overlay_match_score = _browser_item_overlay_match_score

def _dialog_step_0083(_state):
    def _best_hkx_browser_item_for_overlay(
        *,
        kind: object,
        index: object,
        viewer_id: object,
    ) -> Optional[QTreeWidgetItem]:
        viewer_ids = _state._browser_viewer_id_aliases(kind, index, viewer_id)
        overlay_kind = str(kind or "").strip().lower()
        scored_items = [
            (_state._browser_item_overlay_match_score(item, viewer_ids, overlay_kind=overlay_kind), item)
            for item in _state._iter_hkx_browser_items()
        ]
        scored_items = [(score, item) for score, item in scored_items if score >= 0]
        if not scored_items:
            return None
        scored_items.sort(key=lambda pair: pair[0], reverse=True)
        return scored_items[0][1]
    _state._best_hkx_browser_item_for_overlay = _best_hkx_browser_item_for_overlay

def _dialog_step_0084(_state):
    def _overlay_shape_position(shape: HkxPhysicsOverlayShape) -> Tuple[float, float, float]:
        return _state._helper_overlay_shape_position(shape)
    _state._overlay_shape_position = _overlay_shape_position

def _dialog_step_0085(_state):
    def _overlay_target_position_from_model(
        preview_model: object,
        *,
        kind: str,
        index: int,
    ) -> Tuple[float, float, float]:
        return _state._helper_overlay_target_position_from_model(preview_model, kind=kind, index=index)
    _state._overlay_target_position_from_model = _overlay_target_position_from_model

def _dialog_step_0086(_state):
    def _nearest_overlay_shape_links_for_target(
        *,
        kind: str,
        index: int,
        limit: int = 4,
    ) -> List[Tuple[str, str, float, str]]:
        normalized_kind = str(kind or "").strip().lower()
        matches: List[Tuple[float, str, str, str]] = []
        for preview in _state._hkx_overlay_preview_widgets():
            if not hasattr(preview, "current_model_preview"):
                continue
            try:
                preview_model = preview.current_model_preview()
            except (AttributeError, RuntimeError, TypeError, ValueError):
                preview_model = None
            if not isinstance(preview_model, _state.ModelPreviewData):
                continue
            overlay = getattr(preview_model, "physics_overlay", None)
            if not isinstance(overlay, _state.HkxPhysicsOverlayData):
                continue
            target_position = _state._overlay_target_position_from_model(preview_model, kind=normalized_kind, index=int(index))
            if not target_position:
                continue
            for fallback_index, shape in enumerate(tuple(getattr(overlay, "shapes", ()) or ())):
                if not isinstance(shape, _state.HkxPhysicsOverlayShape):
                    continue
                source_index = int(
                    getattr(shape, "source_shape_index", fallback_index)
                    if getattr(shape, "source_shape_index", -1) >= 0
                    else fallback_index
                )
                if normalized_kind == "shape" and source_index == int(index):
                    continue
                shape_position = _state._overlay_shape_position(shape)
                if not shape_position:
                    continue
                distance = _state.math.sqrt(
                    ((shape_position[0] - target_position[0]) ** 2)
                    + ((shape_position[1] - target_position[1]) ** 2)
                    + ((shape_position[2] - target_position[2]) ** 2)
                )
                label = str(
                    getattr(shape, "label", "")
                    or getattr(shape, "body_name", "")
                    or getattr(shape, "socket_name", "")
                    or getattr(shape, "shape_type", "")
                    or f"shape {source_index}"
                )
                placement_source = str(getattr(shape, "placement_source", "") or "")
                matches.append((distance, f"shape/{source_index}", label, placement_source))
        matches.sort(key=lambda row: row[0])
        result: List[Tuple[str, str, float, str]] = []
        seen: set[str] = set()
        for distance, viewer_id, label, placement_source in matches:
            if viewer_id in seen:
                continue
            result.append((viewer_id, label, distance, placement_source))
            seen.add(viewer_id)
            if len(result) >= max(1, int(limit)):
                break
        return result
    _state._nearest_overlay_shape_links_for_target = _nearest_overlay_shape_links_for_target

def _dialog_step_0087(_state):
    def _make_hkx_browser_item_visible(item: QTreeWidgetItem, viewer_id: str) -> None:
        _state.browser_editable_only_checkbox.setChecked(False)
        _state.browser_raw_preserved_checkbox.setChecked(False)
        _state.browser_decoded_only_checkbox.setChecked(False)
        _state.browser_preview_linked_checkbox.setChecked(True)
        _state.browser_filter_edit.setText(viewer_id)
        _state._apply_hkx_browser_filter()
        parent = item.parent()
        while parent is not None:
            parent.setExpanded(True)
            parent = parent.parent()
        item.setHidden(False)
        _state.hkx_browser_tree.setCurrentItem(item)
        _state.hkx_browser_tree.scrollToItem(item, _state.QAbstractItemView.PositionAtCenter)
    _state._make_hkx_browser_item_visible = _make_hkx_browser_item_visible

def _dialog_step_0088(_state):
    def _show_preview_overlay_target_in_hkx_editor(
        kind: str,
        label: str,
        index: int,
        source_path: str,
        viewer_id: str,
    ) -> None:
        item = _state._best_hkx_browser_item_for_overlay(kind=kind, index=index, viewer_id=viewer_id)
        effective_viewer_id = str(viewer_id or f"{kind}/{index}").strip()
        nearest_shape_links = _state._nearest_overlay_shape_links_for_target(kind=kind, index=index, limit=4)

        def _show_nearest_shape_fallback() -> bool:
            for shape_viewer_id, shape_label, distance, placement_source in nearest_shape_links:
                shape_index_text = shape_viewer_id.split("/", 1)[1] if "/" in shape_viewer_id else ""
                shape_item = _state._best_hkx_browser_item_for_overlay(
                    kind="shape",
                    index=shape_index_text,
                    viewer_id=shape_viewer_id,
                )
                connected = _state._set_connected_target_filter(shape_viewer_id, shape_label)
                if shape_item is not None:
                    _state._make_hkx_browser_item_visible(shape_item, shape_viewer_id)
                if connected or shape_item is not None:
                    placement_note = (
                        "This shape has a recovered skeleton/body placement."
                        if placement_source
                        else "This shape is still drawn from recovered local/raw coordinates, so its on-screen placement may be approximate."
                    )
                    _state.connected_detail_text.setPlainText(
                        "\n".join(
                            line
                            for line in (
                                f"3D target selected: {effective_viewer_id}"
                                + (f" ({label})" if label else ""),
                                (
                                    "No exact bone-to-editable-value row is recovered yet."
                                    if str(kind or "").strip().lower() == "bone"
                                    else "No exact row was recovered for the selected overlay target."
                                ),
                                f"Showing nearest decoded physics shape instead: {shape_viewer_id}"
                                + (f" ({shape_label})" if shape_label else "")
                                + f", distance {distance:.3f}.",
                                "Nearest spatial fallback only: this is not a proven Havok ownership link.",
                                placement_note,
                                "Most editable values attach to orange/pink collision shapes, constraints, or body records. Green skeleton bones are mainly context until bone-to-body ownership is fully decoded.",
                                "",
                                *_state._connected_target_candidate_summary_lines(shape_viewer_id),
                            )
                            if line
                        )
                    )
                    _state.browser_status_label.setText(
                        f"Nearest spatial fallback only: selected {effective_viewer_id}; no exact row is known, so decoded shape {shape_viewer_id} is shown as a potential physics link."
                    )
                    return True
            return False

        if item is None:
            _state.browser_status_label.setText(
                f"No exact linked row recovered: selected {effective_viewer_id} in 3D preview, but no linked HKX browser/editor row is recovered yet."
            )
            _state._set_hkx_editor_section(9)
            exact_connected = _state._set_connected_target_filter(effective_viewer_id, label)
            if not exact_connected and _show_nearest_shape_fallback():
                _state.self.set_status_message(f"Selected HKX overlay target {effective_viewer_id}; showing nearest decoded shape link.")
                return
            if not _state._select_best_connected_row_for_target(effective_viewer_id):
                _state.connected_detail_text.setPlainText(
                    "\n".join(
                        line
                        for line in (
                            f"3D target selected: {effective_viewer_id}" + (f" ({label})" if label else ""),
                            "No exact linked connected-physics row is recovered yet.",
                            (
                                "This selected target is a skeleton bone. The current decoder does not yet prove which hknp body/shape owns every bone."
                                if str(kind or "").strip().lower() == "bone"
                                else ""
                            ),
                            "Try clicking an orange/pink collision shape or constraint guide. Those are the targets most likely to have editable radius, transform, mass, damping, motor, or material rows.",
                            "",
                            *_state._connected_target_candidate_summary_lines(effective_viewer_id),
                        )
                        if line
                    )
                )
            return
        _state._make_hkx_browser_item_visible(item, effective_viewer_id)
        _state._show_browser_row_in_editor()
        data = _state._current_browser_data()
        target_name = str(label or data.get("label") or effective_viewer_id)
        source_note = f" from {source_path}" if source_path else ""
        exact_connected = _state._set_connected_target_filter(effective_viewer_id, target_name)
        _state._set_hkx_editor_section(9)
        selected_link = _state._select_best_connected_row_for_target(effective_viewer_id)
        if not selected_link and not exact_connected:
            selected_link = _show_nearest_shape_fallback()
        _state.browser_status_label.setText(
            f"Selected 3D physics target {target_name}{source_note}; "
            + (
                "exact linked rows are selected below."
                if selected_link and exact_connected
                else "nearest decoded physics context is shown below."
                if selected_link
                else "linked HKX rows are filtered below."
            )
        )
        _state.self.set_status_message(f"Selected HKX physics overlay target {effective_viewer_id}.")
    _state._show_preview_overlay_target_in_hkx_editor = _show_preview_overlay_target_in_hkx_editor

def _dialog_step_0089(_state):
    def _handle_browser_selection(current: Optional[QTreeWidgetItem], _previous: Optional[QTreeWidgetItem] = None) -> None:
        _state._update_comparison_text_from_item(current)
        _state._sync_browser_action_buttons()
        data = _state._current_browser_data() if current is not None else {}
        editor_tab = str(data.get("editor_tab") or "").strip()
        should_follow = editor_tab in {"Structured Editor", "Collision Editor"} or (
            bool(editor_tab) and str(data.get("importable") or "").strip().lower() == "true"
        )
        if data:
            viewer_id = str(data.get("viewer_selection_id") or "").strip() if data else ""
            if viewer_id:
                resolved_viewer_id, _resolve_reason = _state._resolve_preview_viewer_id_for_data(data)
                _state._set_connected_target_filter(resolved_viewer_id or viewer_id, str(data.get("label") or ""))
        if (
            current is not None
            and _state.browser_follow_selection_checkbox.isChecked()
            and not _state.syncing_browser_follow["active"]
        ):
            if should_follow:
                try:
                    _state.syncing_browser_follow["active"] = True
                    _state._show_browser_row_in_editor()
                finally:
                    _state.syncing_browser_follow["active"] = False
        if data and _state.browser_follow_preview_checkbox.isChecked():
            _state._highlight_browser_data_in_preview(
                data,
                quiet=True,
                switch_to_embedded_preview=False,
                autoload_preview=False,
            )
    _state._handle_browser_selection = _handle_browser_selection

def _dialog_step_0090(_state):
    def _show_browser_row_in_editor() -> None:
        data = _state._current_browser_data()
        if not data:
            return
        editor_tab = str(data.get("editor_tab") or "")
        field = str(data.get("field") or data.get("label") or "").strip()
        record_index = str(data.get("record_index") or "").strip()
        subject = str(data.get("subject") or "").strip()
        shape_hint = (
            str(data.get("viewer_selection_id") or "")
            .replace("shape:", "")
            .replace("shape/", "")
            .strip()
        )
        if editor_tab == "Structured Editor":
            _state._set_hkx_editor_section(1)
            _state.tuning_editable_only_checkbox.setChecked(str(data.get("importable") or "").strip().lower() == "true")
            item_index = str(data.get("item_index") or "").strip()
            filter_text = " ".join(value for value in (record_index, item_index, field) if value).strip()
            _state.tuning_filter_edit.setText(filter_text or " ".join(value for value in (record_index, field, subject) if value).strip())
            _state._populate_tuning_tree()
        elif editor_tab == "Collision Editor":
            _state._set_hkx_editor_section(2)
            _state.collision_filter_edit.setText(" ".join(value for value in (shape_hint, field, subject) if value).strip())
            _state._populate_collision_tree()
        elif editor_tab:
            for index in range(_state.tab_widget.count()):
                if _state.tab_widget.tabText(index).startswith(editor_tab):
                    _state._set_hkx_editor_section(index)
                    break
        else:
            _state._set_hkx_editor_section(0)
        _state._update_comparison_text_from_item(_state.hkx_browser_tree.currentItem())
    _state._show_browser_row_in_editor = _show_browser_row_in_editor

def _dialog_step_0091(_state):
    def _show_browser_row_in_xml() -> None:
        data = _state._current_browser_data()
        if not data:
            return
        _state._set_hkx_editor_section(_state.tab_widget.count() - 1)
        pattern = str(data.get("patch_path") or data.get("id") or data.get("label") or "").strip()
        if not pattern:
            return
        _state.search_edit.setText(pattern)
        cursor = _state.editor.textCursor()
        cursor.movePosition(_state.QTextCursor.MoveOperation.Start)
        _state.editor.setTextCursor(cursor)
        if not _state.editor.find(pattern):
            compact_pattern = pattern.split("[", 1)[0]
            if compact_pattern:
                _state.search_edit.setText(compact_pattern)
                cursor.movePosition(_state.QTextCursor.MoveOperation.Start)
                _state.editor.setTextCursor(cursor)
                _state.editor.find(compact_pattern)
    _state._show_browser_row_in_xml = _show_browser_row_in_xml

def _dialog_step_0092(_state):
    def _highlight_browser_data_in_preview(
        data: Mapping[str, object],
        *,
        status_label: Optional[QLabel] = None,
        quiet: bool = False,
        switch_to_embedded_preview: bool = False,
        autoload_preview: bool = True,
    ) -> bool:
        viewer_id = str(data.get("viewer_selection_id") or "").strip() if data else ""
        label = status_label or _state.browser_status_label
        if not data or not _state._has_preview_link_hint(data):
            if not quiet:
                label.setText("No exact visual link: this HKX row has no recovered 3D target. Use Connected Physics or Decoder Evidence for non-visual context.")
            return False
        label_hint = str(data.get("label") or data.get("subject") or "").strip()
        source_hint = str(data.get("source_path") or _state.entry.path or "").strip()
        if switch_to_embedded_preview:
            _state._set_hkx_preview_panel_visible(True)
        if autoload_preview and not bool(_state.hkx_link_preview_state.get("loaded")):
            _state._refresh_hkx_link_preview_model()
        preview_viewer_id, resolve_reason = _state._resolve_preview_viewer_id_for_data(data)
        if not preview_viewer_id:
            record_note = ""
            if _state._record_indices_from_data(data):
                record_note = " This row is an internal HKX ITEM record; no visible shape/constraint link has been recovered for it yet."
            if not quiet:
                label.setText(
                    "No exact visual link for this row."
                    + record_note
                    + " Use Connected Physics or Context Hints to inspect nearby body/material/string context."
                )
            return False
        if switch_to_embedded_preview:
            _state.hkx_link_preview_widget.setFocus(_state.Qt.FocusReason.OtherFocusReason)
        selected_widgets: List[str] = []
        for preview in _state._hkx_overlay_preview_widgets():
            if not hasattr(preview, "select_physics_overlay_target"):
                continue
            _state._enable_hkx_preview_overlay(preview)
            try:
                if preview.select_physics_overlay_target(
                    preview_viewer_id,
                    label_hint=label_hint,
                    source_path_hint=source_hint,
                ):
                    selected_widgets.append("embedded" if preview is _state.hkx_link_preview_widget else "main")
            except (AttributeError, RuntimeError, TypeError, ValueError):
                continue
        selected = bool(selected_widgets)
        if selected:
            if preview_viewer_id != _state._previewable_viewer_id(viewer_id):
                if not quiet:
                    label.setText(
                        f"Exact 3D target selected: resolved {viewer_id or 'selected row'} to {preview_viewer_id} via {resolve_reason}; highlighted it in the HKX 3D preview."
                    )
            else:
                if not quiet:
                    label.setText(f"Exact 3D target selected: highlighted {preview_viewer_id} in the HKX 3D preview.")
            _state._set_connected_target_filter(preview_viewer_id, label_hint)
            _state.self.set_status_message(f"Highlighted HKX overlay target {preview_viewer_id}.")
            return True
        if not quiet:
            available_targets = _state._available_hkx_preview_target_ids()
            if not available_targets:
                label.setText(
                    f"3D link recovered, no model loaded: this row maps to {preview_viewer_id}, but no matching 3D physics overlay is loaded. "
                    "Use the embedded 3D Preview pane's Load Model button to choose the related .pac/.pam/.pamlod without leaving this editor."
                )
                _state.hkx_preview_status_label.setText(
                    "No loaded 3D overlay targets are available. Click Load Model to build a related model preview inside this HKX editor."
                )
            else:
                sample = ", ".join(sorted(available_targets)[:6])
                more = f", +{len(available_targets) - 6} more" if len(available_targets) > 6 else ""
                label.setText(
                    f"Loaded model lacks this target: this row maps to {preview_viewer_id}, but the loaded 3D preview does not contain that target. "
                    f"Current preview targets include: {sample}{more}. It may be a different related model or a recovered-only HKX target."
                )
                _state.hkx_preview_status_label.setText(
                    f"Loaded 3D preview has {len(available_targets):,} overlay target(s), but not {preview_viewer_id}."
                )
        return False
    _state._highlight_browser_data_in_preview = _highlight_browser_data_in_preview

def _dialog_step_0093(_state):
    def _show_browser_row_in_preview() -> None:
        data = _state._current_browser_data()
        if not data:
            _state.browser_status_label.setText("Select a decoded row first.")
            return
        _state._set_hkx_preview_panel_visible(True, refresh=True)
        _state._highlight_browser_data_in_preview(data, switch_to_embedded_preview=True)
    _state._show_browser_row_in_preview = _show_browser_row_in_preview

STEPS = (_dialog_step_0082, _dialog_step_0083, _dialog_step_0084, _dialog_step_0085, _dialog_step_0086, _dialog_step_0087, _dialog_step_0088, _dialog_step_0089, _dialog_step_0090, _dialog_step_0091, _dialog_step_0092, _dialog_step_0093,)
