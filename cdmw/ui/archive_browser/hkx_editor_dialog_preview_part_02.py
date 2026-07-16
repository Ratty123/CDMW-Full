from __future__ import annotations

from types import SimpleNamespace

def _dialog_step_0053(_state):
    def _hkx_preview_placement_status_suffix() -> str:
        try:
            evidence_count = int(_state.hkx_preview_placement_state.get("evidence_count") or 0)
        except (TypeError, ValueError):
            evidence_count = 0
        if evidence_count > 0:
            return f" Placement workspace has {evidence_count:,} prefab/socket chain(s)."
        return ""
    _state._hkx_preview_placement_status_suffix = _hkx_preview_placement_status_suffix

def _dialog_step_0054(_state):
    def _set_hkx_preview_loaded_status(preview_model: object, *, source_path: object = "") -> None:
        mesh_count, shape_count, constraint_count, bone_count, skeleton_link_count = _state._hkx_preview_counts(preview_model)
        _state.hkx_preview_skeleton_checkbox.blockSignals(True)
        try:
            if bone_count <= 0 or skeleton_link_count <= 0:
                _state.hkx_preview_skeleton_checkbox.setChecked(False)
            _state.hkx_preview_skeleton_checkbox.setVisible(bone_count > 0 and skeleton_link_count > 0)
            _state.hkx_preview_skeleton_checkbox.setEnabled(bone_count > 0 and skeleton_link_count > 0)
            if hasattr(_state.hkx_link_preview_widget, "set_physics_overlay_bones_visible"):
                _state.hkx_link_preview_widget.set_physics_overlay_bones_visible(
                    _state.hkx_preview_skeleton_checkbox.isChecked()
                    and bone_count > 0
                    and skeleton_link_count > 0
                )
        finally:
            _state.hkx_preview_skeleton_checkbox.blockSignals(False)
        source_name = _state.PurePosixPath(str(source_path or "")).name
        prefix = f"Loaded {source_name}" if source_name else "Embedded current 3D preview"
        bone_note = _state._hkx_preview_context_skeleton_note(
            bone_count,
            skeleton_link_count,
            show_skeleton=_state.hkx_preview_skeleton_checkbox.isChecked(),
        )
        placement_note = _state._hkx_preview_placement_status_suffix()
        if shape_count or constraint_count:
            _state.hkx_preview_status_label.setText(
                f"{prefix}: {mesh_count:,} mesh(es), {shape_count:,} shape target(s), {constraint_count:,} constraint target(s).{bone_note}{placement_note}"
            )
        else:
            _state.hkx_preview_status_label.setText(
                f"{prefix}, but no HKX physics overlay targets were recovered for this model. "
                f"Try another related model if Show in 3D still cannot highlight rows.{bone_note}{placement_note}"
            )
    _state._set_hkx_preview_loaded_status = _set_hkx_preview_loaded_status

def _dialog_step_0055(_state):
    def _sync_hkx_preview_context_skeleton_visibility(checked: bool) -> None:
        preview_model = _state._current_embedded_hkx_preview_model()
        _mesh_count, _shape_count, _constraint_count, bone_count, skeleton_link_count = _state._hkx_preview_counts(preview_model)
        if checked and (bone_count <= 0 or skeleton_link_count <= 0):
            _state.hkx_preview_skeleton_checkbox.blockSignals(True)
            try:
                _state.hkx_preview_skeleton_checkbox.setChecked(False)
            finally:
                _state.hkx_preview_skeleton_checkbox.blockSignals(False)
            checked = False
        if hasattr(_state.hkx_link_preview_widget, "set_physics_overlay_bones_visible"):
            _state.hkx_link_preview_widget.set_physics_overlay_bones_visible(bool(checked))
        if isinstance(preview_model, _state.ModelPreviewData):
            _state._set_hkx_preview_loaded_status(
                preview_model,
                source_path=_state.hkx_link_preview_state.get("source_path") or "",
            )
        else:
            _state.hkx_preview_status_label.setText(
                "No skeleton context recovered. Load a related model first; this toggle only shows bones, not weapon placement."
            )
        _state._apply_hkx_browser_filter()
    _state._sync_hkx_preview_context_skeleton_visibility = _sync_hkx_preview_context_skeleton_visibility

def _dialog_step_0056(_state):
    def _hkx_related_model_entries() -> Tuple[ArchiveEntry, ...]:
        entries_by_extension = getattr(_state.self, "archive_entries_by_extension", {}) or {}
        candidates: List[_state.ArchiveEntry] = []
        seen: set[str] = set()

        def entry_key(candidate: ArchiveEntry) -> str:
            normalized_path = candidate.path.replace("\\", "/").strip().lower()
            return f"{candidate.pamt_path}::{normalized_path}" if normalized_path else ""

        for extension in sorted(_state.ARCHIVE_MESH_EXTENSIONS):
            for candidate in tuple(entries_by_extension.get(extension, ()) or ()):
                if not isinstance(candidate, _state.ArchiveEntry):
                    continue
                key = entry_key(candidate)
                if not key or key in seen:
                    continue
                candidates.append(candidate)
                seen.add(key)
        if candidates:
            return tuple(candidates)
        for candidate in tuple(getattr(_state.self, "archive_entries", ()) or ()):
            if not isinstance(candidate, _state.ArchiveEntry) or candidate.extension not in _state.ARCHIVE_MESH_EXTENSIONS:
                continue
            key = entry_key(candidate)
            if not key or key in seen:
                continue
            candidates.append(candidate)
            seen.add(key)
        return tuple(candidates)
    _state._hkx_related_model_entries = _hkx_related_model_entries

def _dialog_step_0057(_state):
    def _hkx_related_model_candidate_rows(
        filter_text: str = "",
        limit: int = 200,
        candidates: Optional[Sequence[ArchiveEntry]] = None,
    ) -> List[Tuple[int, str, ArchiveEntry]]:
        candidate_pool = tuple(candidates) if candidates is not None else _state._hkx_related_model_entries()
        return _state._rank_hkx_related_model_candidate_rows(
            _state.entry,
            candidate_pool,
            filter_text=filter_text,
            limit=limit,
        )
    _state._hkx_related_model_candidate_rows = _hkx_related_model_candidate_rows

def _dialog_step_0058(_state):
    def _select_hkx_embedded_preview_model_entry() -> Optional[ArchiveEntry]:
        picker = _state.QDialog(_state.dialog)
        picker.setWindowTitle("Load HKX 3D Preview Model")
        picker.resize(960, 560)
        picker_layout = _state.QVBoxLayout(picker)
        picker_layout.setContentsMargins(12, 12, 12, 12)
        picker_layout.setSpacing(8)
        picker_hint = _state.QLabel(
            "Choose the .pac, .pam, or .pamlod model that should be used for this HKX preview. "
            "Rows are ranked by same-stem, package, role, and path-token evidence; use the filter when the automatic match is weak."
        )
        picker_hint.setWordWrap(True)
        picker_layout.addWidget(picker_hint)
        picker_filter = _state.QLineEdit()
        picker_filter.setPlaceholderText("Filter model entries, e.g. nude, phm, cloak, damian, body")
        picker_filter_apply_button = _state.QPushButton("Apply")
        picker_filter_apply_button.setToolTip("Apply the filter now. Filtering is debounced while typing to keep large archives responsive.")
        picker_filter_row = _state.QHBoxLayout()
        picker_filter_row.setContentsMargins(0, 0, 0, 0)
        picker_filter_row.setSpacing(6)
        picker_filter_row.addWidget(picker_filter, stretch=1)
        picker_filter_row.addWidget(picker_filter_apply_button)
        picker_layout.addLayout(picker_filter_row)
        picker_tree = _state.QTreeWidget()
        picker_tree.setColumnCount(4)
        picker_tree.setHeaderLabels(("Match", "Model", "Package", "Why"))
        picker_tree.setAlternatingRowColors(True)
        picker_tree.setUniformRowHeights(True)
        picker_tree.setRootIsDecorated(False)
        picker_tree.setSortingEnabled(False)
        picker_tree.setSelectionMode(_state.QAbstractItemView.SingleSelection)
        picker_tree.setEditTriggers(_state.QAbstractItemView.NoEditTriggers)
        picker_tree.header().setSectionResizeMode(0, _state.QHeaderView.ResizeToContents)
        picker_tree.header().setSectionResizeMode(1, _state.QHeaderView.Stretch)
        picker_tree.header().setSectionResizeMode(2, _state.QHeaderView.ResizeToContents)
        picker_tree.header().setSectionResizeMode(3, _state.QHeaderView.Stretch)
        picker_layout.addWidget(picker_tree, stretch=1)
        picker_status = _state.QLabel("")
        picker_status.setWordWrap(True)
        picker_layout.addWidget(picker_status)
        picker_button_row = _state.QHBoxLayout()
        picker_button_row.addStretch(1)
        picker_load_button = _state.QPushButton("Load Selected")
        picker_cancel_button = _state.QPushButton("Cancel")
        picker_button_row.addWidget(picker_load_button)
        picker_button_row.addWidget(picker_cancel_button)
        picker_layout.addLayout(picker_button_row)
        selection: Dict[str, Optional[ArchiveEntry]] = {"entry": None}
        picker_candidate_cache = tuple(_state._hkx_related_model_entries())
        picker_filter_timer = _state.QTimer(picker)
        picker_filter_timer.setSingleShot(True)
        picker_filter_timer.setInterval(320)

        def _populate_picker(*, force: bool = False) -> None:
            picker_tree.clear()
            filter_text = picker_filter.text().strip()
            if filter_text and len(filter_text) < 2 and not force:
                picker_load_button.setEnabled(False)
                picker_status.setText("Type at least 2 characters, or press Apply to run a broad one-character search.")
                return
            rows = _state._hkx_related_model_candidate_rows(
                filter_text,
                limit=300 if filter_text else 120,
                candidates=picker_candidate_cache,
            )
            for score, reason, candidate in rows:
                strength = "strong" if score >= 130 else "inferred" if score >= 55 else "weak"
                item = _state.QTreeWidgetItem(
                    (
                        f"{strength} {score}",
                        candidate.path,
                        candidate.package_label,
                        reason,
                    )
                )
                item.setData(0, _state.Qt.UserRole, candidate)
                if strength == "strong":
                    item.setForeground(0, _state.QBrush(_state.QColor("#86efac")))
                elif strength == "inferred":
                    item.setForeground(0, _state.QBrush(_state.QColor("#fbbf24")))
                else:
                    item.setForeground(0, _state.QBrush(_state.QColor("#fca5a5")))
                picker_tree.addTopLevelItem(item)
            if picker_tree.topLevelItemCount() > 0:
                picker_tree.setCurrentItem(picker_tree.topLevelItem(0))
            picker_load_button.setEnabled(picker_tree.topLevelItemCount() > 0)
            if rows:
                picker_status.setText(
                    f"{len(rows):,} model candidate(s) shown. Weak matches are guesses; prefer a model you recognize from the asset path."
                )
            elif filter_text:
                picker_status.setText("No model entries match that filter in the currently scanned archive.")
            else:
                picker_status.setText(
                    "No likely model candidate was found from this HKX path. Type a body, outfit, cloak, hair, object, or character token to search model entries."
                )

        def _schedule_picker_filter() -> None:
            picker_load_button.setEnabled(False)
            picker_status.setText("Waiting for typing to pause before filtering...")
            picker_filter_timer.start()

        def _accept_picker() -> None:
            item = picker_tree.currentItem()
            candidate = item.data(0, _state.Qt.UserRole) if item is not None else None
            if not isinstance(candidate, _state.ArchiveEntry):
                return
            selection["entry"] = candidate
            picker.accept()

        picker_filter.textChanged.connect(lambda _text: _schedule_picker_filter())
        picker_filter.returnPressed.connect(lambda: _populate_picker(force=True))
        picker_filter_apply_button.clicked.connect(lambda: _populate_picker(force=True))
        picker_filter_timer.timeout.connect(lambda: _populate_picker(force=False))
        picker_tree.itemDoubleClicked.connect(lambda _item, _column: _accept_picker())
        picker_load_button.clicked.connect(_accept_picker)
        picker_cancel_button.clicked.connect(picker.reject)
        _populate_picker(force=True)
        if picker.exec() != _state.QDialog.Accepted:
            return None
        return selection["entry"]
    _state._select_hkx_embedded_preview_model_entry = _select_hkx_embedded_preview_model_entry

def _dialog_step_0059(_state):
    def _load_hkx_embedded_preview_model(model_entry: Optional[ArchiveEntry]) -> None:
        if not isinstance(model_entry, _state.ArchiveEntry):
            return
        if _state.self._background_task_active():
            _state.hkx_preview_status_label.setText("Another background task is running. Wait for it to finish before loading a 3D preview.")
            return
        _state._set_hkx_preview_panel_visible(True)
        _state.hkx_link_preview_state["loaded"] = False
        _state.hkx_link_preview_state["pending_entry_key"] = _state.self._archive_entry_identity_key(model_entry)
        _state.hkx_link_preview_widget.clear_model(f"Building embedded 3D preview for {model_entry.basename}...")
        _state.hkx_preview_status_label.setText(f"Building embedded preview for {model_entry.path}...")
        companion_entry = _state.self._find_archive_preview_companion_entry(model_entry)
        preview_settings = _state.self._current_model_preview_render_settings()
        support_texture_slots = _state.self._archive_preview_support_texture_slots(preview_settings)
        entry_key = _state.self._archive_entry_identity_key(model_entry)
        preview_request = _state.HkxEmbeddedPreviewRequest(
            entry_key,
            model_entry,
            companion_entry,
            _state.self.archive_entries_by_normalized_path,
            _state.self.archive_entries_by_basename,
            _state.self.archive_sidecar_entries_by_texture_path,
            _state.self.archive_sidecar_entries_by_texture_basename,
            preview_settings.visible_texture_mode,
            support_texture_slots,
        )

        def _task(log: Callable[[str], None], stop_event: object) -> object:
            log(f"Building embedded HKX 3D preview for {model_entry.path}...")
            return _state.build_hkx_embedded_preview(preview_request, stop_event=stop_event)

        def _handle_complete(result: object) -> None:
            if not _state.dialog.isVisible():
                return
            if not isinstance(result, tuple) or len(result) != 3:
                _state.hkx_preview_status_label.setText("Embedded 3D preview finished with an unexpected result payload.")
                return
            result_entry_key, result_path, preview_result = result
            if result_entry_key != _state.hkx_link_preview_state.get("pending_entry_key"):
                return
            if not isinstance(preview_result, _state.ArchivePreviewResult):
                _state.hkx_preview_status_label.setText("Embedded 3D preview did not return an archive preview result.")
                return
            preview_model = getattr(preview_result, "preview_model", None)
            if not isinstance(preview_model, _state.ModelPreviewData) or not getattr(preview_model, "meshes", None):
                detail = str(getattr(preview_result, "detail_text", "") or getattr(preview_result, "warning_text", "") or "").strip()
                _state.hkx_link_preview_state["loaded"] = False
                _state.hkx_link_preview_widget.clear_model("The selected archive entry did not produce a renderable 3D model preview.")
                _state.hkx_preview_status_label.setText(detail or f"No renderable 3D model was recovered from {result_path}.")
                _state._apply_hkx_browser_filter()
                return
            try:
                result_with_images = _state.self._attach_archive_preview_result_images(preview_result)
                _state.hkx_link_preview_widget.set_prepared_model(
                    result_with_images.preview_model,
                    getattr(result_with_images, "prepared_preview_model", None),
                )
                if hasattr(_state.hkx_link_preview_widget, "set_physics_overlay_bones_visible"):
                    _state.hkx_link_preview_widget.set_physics_overlay_bones_visible(_state.hkx_preview_skeleton_checkbox.isChecked())
                _state._enable_hkx_preview_overlay(_state.hkx_link_preview_widget)
            except Exception as exc:
                # User-visible: embedded preview load/display failures are reported in-panel.
                _state.hkx_link_preview_state["loaded"] = False
                _state.hkx_preview_status_label.setText(f"Could not display the embedded 3D preview: {exc}")
                return
            _state.hkx_link_preview_state["loaded"] = True
            _state.hkx_link_preview_state["source_entry_key"] = result_entry_key
            _state.hkx_link_preview_state["source_path"] = result_path
            _state._set_hkx_preview_loaded_status(result_with_images.preview_model, source_path=result_path)
            _state._sync_hkx_edited_overlay_targets(_state._silent_xml_root_from_editor())
            _state._apply_hkx_browser_filter()

        _state.self._run_utility_task(
            status_message=f"Building embedded HKX 3D preview for {model_entry.basename}...",
            task=_task,
            on_complete=_handle_complete,
            show_archive_progress=True,
            task_accepts_cancel=True,
        )
    _state._load_hkx_embedded_preview_model = _load_hkx_embedded_preview_model

def _dialog_step_0060(_state):
    def _choose_and_load_hkx_embedded_preview_model() -> None:
        model_entry = _state._select_hkx_embedded_preview_model_entry()
        if model_entry is not None:
            _state._load_hkx_embedded_preview_model(model_entry)
    _state._choose_and_load_hkx_embedded_preview_model = _choose_and_load_hkx_embedded_preview_model

def _dialog_step_0061(_state):
    def _hkx_preview_target_ids_from_model(preview_model: object, *, include_bones: bool = True) -> set[str]:
        return _state._helper_hkx_preview_target_ids_from_model(preview_model, include_bones=include_bones)
    _state._hkx_preview_target_ids_from_model = _hkx_preview_target_ids_from_model

def _dialog_step_0062(_state):
    def _available_hkx_preview_target_ids() -> set[str]:
        target_ids: set[str] = set()
        for preview in _state._hkx_overlay_preview_widgets():
            if not hasattr(preview, "current_model_preview"):
                continue
            try:
                preview_model = preview.current_model_preview()
            except (AttributeError, RuntimeError, TypeError, ValueError):
                preview_model = None
            include_bones = True
            if hasattr(preview, "physics_overlay_bones_visible"):
                try:
                    include_bones = bool(preview.physics_overlay_bones_visible())
                except (AttributeError, RuntimeError, TypeError, ValueError):
                    include_bones = True
            target_ids.update(_state._hkx_preview_target_ids_from_model(preview_model, include_bones=include_bones))
        return target_ids
    _state._available_hkx_preview_target_ids = _available_hkx_preview_target_ids

def _dialog_step_0063(_state):
    def _refresh_hkx_link_preview_model() -> bool:
        preview_model = _state._current_hkx_link_preview_model()
        if not isinstance(preview_model, _state.ModelPreviewData) or not getattr(preview_model, "meshes", None):
            _state.hkx_link_preview_state["loaded"] = False
            _state.hkx_preview_refresh_button.setVisible(False)
            _state.hkx_link_preview_widget.clear_model(
                "No model is loaded in this embedded preview.\n\nClick Load Model to choose a related .pac/.pam/.pamlod from the open archive."
            )
            _state.hkx_preview_status_label.setText(
                "Click Load Model to choose a related .pac/.pam/.pamlod inside this editor."
            )
            return False
        try:
            _state.hkx_link_preview_widget.set_model(preview_model)
            if hasattr(_state.hkx_link_preview_widget, "set_physics_overlay_bones_visible"):
                _state.hkx_link_preview_widget.set_physics_overlay_bones_visible(_state.hkx_preview_skeleton_checkbox.isChecked())
            _state._enable_hkx_preview_overlay(_state.hkx_link_preview_widget)
        except Exception as exc:
            # User-visible: preview model handoff failures are reported in-panel.
            _state.hkx_link_preview_state["loaded"] = False
            _state.hkx_preview_status_label.setText(f"Could not load the embedded HKX 3D preview: {exc}")
            return False
        _state.hkx_link_preview_state["loaded"] = True
        _state.hkx_preview_refresh_button.setVisible(False)
        _state._set_hkx_preview_loaded_status(preview_model)
        _state._sync_hkx_edited_overlay_targets(_state._silent_xml_root_from_editor())
        _state._apply_hkx_browser_filter()
        return True
    _state._refresh_hkx_link_preview_model = _refresh_hkx_link_preview_model

def _dialog_step_0064(_state):
    def _sync_hkx_edited_overlay_targets(root: Optional[ET.Element] = None) -> None:
        if root is None:
            root = _state._silent_xml_root_from_editor()
        edited_targets = sorted(_state._dirty_overlay_viewer_ids_from_root(root))
        for preview in _state._hkx_overlay_preview_widgets():
            if hasattr(preview, "set_physics_overlay_edited_targets"):
                preview.set_physics_overlay_edited_targets(edited_targets)
    _state._sync_hkx_edited_overlay_targets = _sync_hkx_edited_overlay_targets

def _dialog_step_0065(_state):
    def _resolve_preview_viewer_id_for_data(
        data: Mapping[str, object],
        root: Optional[ET.Element] = None,
    ) -> Tuple[str, str]:
        candidates: List[Tuple[int, str, str]] = []

        def _add(viewer_id: object, reason: str, score: int) -> None:
            preview_id = _state._previewable_viewer_id(viewer_id)
            if not preview_id:
                return
            candidates.append((score, preview_id, reason))

        direct_viewer_id = str(data.get("viewer_selection_id") or "").strip()
        _add(direct_viewer_id, "direct preview target", 1200)
        if str(data.get("shape_index") or "").strip():
            _add(f"shape/{data.get('shape_index')}", "row shape index", 1120)
        for key in ("identity_path", "details", "patch_path", "label", "subject", "connected_label", "explanation"):
            for viewer_id in _state._viewer_ids_from_text(data.get(key)):
                _add(viewer_id, f"{key} text", 1040)
        if root is None:
            root = _state._silent_xml_root_from_editor()
        if root is not None:
            graph = root.find("./relationshipGraph")
            if graph is not None:
                nodes_by_id = {
                    str(node.get("id") or ""): dict(node.attrib)
                    for node in graph.findall("./nodes/node")
                    if str(node.get("id") or "")
                }
                adjacency: Dict[str, List[Tuple[str, Mapping[str, str]]]] = _state.defaultdict(list)
                for edge in graph.findall("./edges/edge"):
                    source_id = str(edge.get("source") or "")
                    target_id = str(edge.get("target") or "")
                    if not source_id or not target_id:
                        continue
                    edge_data = dict(edge.attrib)
                    adjacency[source_id].append((target_id, edge_data))
                    adjacency[target_id].append((source_id, edge_data))
                    if source_id == str(data.get("source_id") or "") or target_id == str(data.get("target_id") or ""):
                        _add(edge.get("viewer_selection_id"), "selected graph edge", 1140)
                start_ids = set()
                for record_index in _state._record_indices_from_data(data):
                    start_ids.add(f"record:{record_index}")
                for key in ("source_id", "target_id", "id"):
                    value = str(data.get(key) or "").strip()
                    if value:
                        start_ids.add(value)
                for viewer_id in _state._viewer_ids_from_text(" ".join(str(data.get(key) or "") for key in ("viewer_selection_id", "id"))):
                    if viewer_id.startswith("record/"):
                        start_ids.add(viewer_id.replace("/", ":"))
                visited: set[str] = set()
                queue: List[Tuple[str, int]] = [(node_id, 0) for node_id in start_ids if node_id]
                while queue:
                    node_id, depth = queue.pop(0)
                    if node_id in visited or depth > 3:
                        continue
                    visited.add(node_id)
                    node = nodes_by_id.get(node_id, {})
                    depth_score = max(0, 980 - depth * 120)
                    _add(node_id, "relationship graph node", depth_score)
                    _add(node.get("viewer_selection_id"), "relationship graph node viewer target", depth_score + 20)
                    for neighbor_id, edge_data in adjacency.get(node_id, []):
                        relation = str(edge_data.get("relation") or "")
                        relation_bonus = 120 if relation in {"decoded_from", "uses_vertices", "uses_planes", "uses_shape_payload", "body_shape", "has_editable_value"} else 0
                        _add(neighbor_id, f"relationship graph {relation or 'edge'}", depth_score + relation_bonus)
                        _add(edge_data.get("viewer_selection_id"), f"relationship graph {relation or 'edge'} viewer target", depth_score + relation_bonus + 30)
                        neighbor = nodes_by_id.get(neighbor_id, {})
                        _add(neighbor.get("viewer_selection_id"), "relationship graph neighbor viewer target", depth_score + relation_bonus + 20)
                        if neighbor_id not in visited:
                            queue.append((neighbor_id, depth + 1))
        if not candidates:
            return "", ""
        best_by_id: Dict[str, Tuple[int, str, str]] = {}
        for score, viewer_id, reason in candidates:
            previous = best_by_id.get(viewer_id)
            if previous is None or score > previous[0]:
                best_by_id[viewer_id] = (score, viewer_id, reason)
        best = sorted(best_by_id.values(), key=lambda item: item[0], reverse=True)[0]
        return best[1], best[2]
    _state._resolve_preview_viewer_id_for_data = _resolve_preview_viewer_id_for_data

STEPS = (_dialog_step_0053, _dialog_step_0054, _dialog_step_0055, _dialog_step_0056, _dialog_step_0057, _dialog_step_0058, _dialog_step_0059, _dialog_step_0060, _dialog_step_0061, _dialog_step_0062, _dialog_step_0063, _dialog_step_0064, _dialog_step_0065,)
