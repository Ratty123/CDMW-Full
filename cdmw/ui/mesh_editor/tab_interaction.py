from __future__ import annotations

import time
from typing import Mapping

from PySide6.QtCore import QPoint, Qt, QTimer


_LEGACY_SCREEN_CAMERA_FIELDS = frozenset(
    {"camera_world", "yaw_degrees", "pitch_degrees", "distance", "vertical_fov_degrees", "pan"}
)


from cdmw.ui.mesh_editor.tab_compat import facade_globals as _tab


class MeshEditorInteractionMixin:
    def _handle_skeleton_pose_request(self, command: str, payload: object) -> bool:
        controller = self.standalone_controller
        if controller is None:
            self.status_message_requested.emit("Open a standalone Mesh Editor session before editing skeleton preview.", True)
            return False
        normalized = str(command or "").strip().lower()
        try:
            if normalized == "set_pose_preview":
                controller.set_pose_preview(bool(payload))
            elif normalized == "select_bone":
                controller.select_bone(int(payload))  # type: ignore[arg-type]
            elif normalized == "rotate_selected_bone":
                controller.rotate_selected_bone(payload)  # type: ignore[arg-type]
            elif normalized == "reset_pose":
                controller.reset_pose()
            elif normalized == "set_animation_playback":
                summary = controller.set_animation_playback(bool(payload))
                if summary.animation_playback.enabled:
                    self.standalone_animation_last_tick = time.monotonic()
                    self.standalone_animation_timer.start()
                else:
                    self.standalone_animation_timer.stop()
            elif normalized == "set_animation_loop":
                controller.set_animation_loop(bool(payload))
            elif normalized == "set_animation_speed":
                controller.set_animation_speed(payload)
            elif normalized == "seek_animation":
                controller.seek_animation(payload)
                self.standalone_animation_last_tick = time.monotonic()
            elif normalized == "scrub_animation_fraction":
                controller.scrub_animation_fraction(payload)
                self.standalone_animation_last_tick = time.monotonic()
            elif normalized == "step_animation_frame":
                controller.step_animation_frame(payload)
                self.standalone_animation_last_tick = time.monotonic()
            elif normalized == "step_animation":
                controller.step_animation(payload)
                self.standalone_animation_last_tick = time.monotonic()
            elif normalized == "adjust_selected_vertex_bone_weight":
                controller.adjust_selected_vertex_bone_weight(payload)
            elif normalized == "normalize_selected_vertex_weights":
                controller.normalize_selected_vertex_weights()
            elif normalized == "transfer_selected_vertex_weights_from_source":
                controller.transfer_selected_vertex_weights_from_source(source_skeleton=self.standalone_source_skeleton)
            else:
                return False
        except Exception as exc:
            self.status_message_requested.emit(f"Mesh Editor skeleton preview failed: {exc}", True)
            return False
        self.update_editor_session_state(controller.session_view(), active_selection_mode=controller.active_selection_mode)
        if self.standalone_compare_mode != "source":
            if self._standalone_native_preview_update_active():
                if self.standalone_native_package_thread is None:
                    self.start_standalone_native_preview_async(reset_view=False)
            else:
                self._refresh_standalone_preview()
        self.status_message_requested.emit("Mesh Editor skeleton preview updated.", False)
        return True
    def _tick_standalone_animation_playback(self) -> None:
        controller = self.standalone_controller
        if controller is None:
            self.standalone_animation_timer.stop()
            return
        now = time.monotonic()
        previous = self.standalone_animation_last_tick or now
        self.standalone_animation_last_tick = now
        delta = max(0.0, min(0.25, now - previous))
        try:
            summary = controller.step_animation(delta)
        except Exception as exc:
            self.standalone_animation_timer.stop()
            self.status_message_requested.emit(f"Mesh Editor animation playback failed: {exc}", True)
            return
        if not summary.animation_playback.enabled:
            self.standalone_animation_timer.stop()
        self.update_editor_session_state(controller.session_view(), active_selection_mode=controller.active_selection_mode)
        if self.standalone_compare_mode != "source":
            if self._standalone_native_preview_update_active():
                if self.standalone_native_package_thread is None:
                    self.start_standalone_native_preview_async(reset_view=False)
            else:
                self._refresh_standalone_preview()
    def _handle_uv_region_selection(self, uv_min: object, uv_max: object, operation: str = "replace") -> bool:
        controller = self.standalone_controller
        if controller is None:
            self.status_message_requested.emit("Open a standalone Mesh Editor session before selecting UVs.", True)
            return False
        try:
            result = controller.select_uv_region(uv_min, uv_max, operation=operation)  # type: ignore[arg-type]
        except Exception as exc:
            self.status_message_requested.emit(f"Mesh Editor UV selection failed: {exc}", True)
            return False
        if not result.ok:
            diagnostic = "; ".join(str(item) for item in tuple(result.diagnostics or ()) if str(item).strip())
            self.status_message_requested.emit(
                f"Mesh Editor UV selection failed{': ' + diagnostic if diagnostic else ''}.",
                True,
            )
            return False
        update = controller.native_update_for_result(result)
        view = controller.session_view()
        self.update_editor_session_state(view, active_selection_mode=controller.active_selection_mode)
        self._apply_standalone_native_update(update)
        if view.selection.is_empty():
            self.status_message_requested.emit("Mesh Editor UV region selection is empty.", False)
        else:
            self.status_message_requested.emit("Mesh Editor UV region selected.", False)
        return True
    def _handle_uv_lasso_selection(self, points: object, operation: str = "replace") -> bool:
        controller = self.standalone_controller
        if controller is None:
            self.status_message_requested.emit("Open a standalone Mesh Editor session before selecting UVs.", True)
            return False
        try:
            result = controller.select_uv_lasso(points, operation=operation)  # type: ignore[arg-type]
        except Exception as exc:
            self.status_message_requested.emit(f"Mesh Editor UV lasso selection failed: {exc}", True)
            return False
        if not result.ok:
            diagnostic = "; ".join(str(item) for item in tuple(result.diagnostics or ()) if str(item).strip())
            self.status_message_requested.emit(
                f"Mesh Editor UV lasso selection failed{': ' + diagnostic if diagnostic else ''}.",
                True,
            )
            return False
        update = controller.native_update_for_result(result)
        view = controller.session_view()
        self.update_editor_session_state(view, active_selection_mode=controller.active_selection_mode)
        self._apply_standalone_native_update(update)
        if view.selection.is_empty():
            self.status_message_requested.emit("Mesh Editor UV lasso selection is empty.", False)
        else:
            self.status_message_requested.emit("Mesh Editor UV lasso selected.", False)
        return True
    def _handle_native_source_part_selected(self, part_index: int) -> bool:
        try:
            normalized_index = int(part_index)
        except (TypeError, ValueError):
            normalized_index = -1
        if normalized_index < 0:
            return False
        return self._handle_part_selection(normalized_index, "toggle")
    def _handle_native_source_part_context_requested(self, part_index: int, x: int, y: int) -> bool:
        controller = self.standalone_controller
        if controller is None:
            return False
        try:
            normalized_index = int(part_index)
        except (TypeError, ValueError):
            normalized_index = -1
        if normalized_index < 0:
            return False
        if self._selection_for_part_context(controller, normalized_index) is None:
            return False
        global_pos = self._standalone_native_global_pos(x, y)
        QTimer.singleShot(
            0,
            lambda index=normalized_index, position=global_pos: self.standalone_workspace.show_part_context_menu_for_part(
                index,
                position,
            ),
        )
        return True
    def _standalone_native_global_pos(self, x: int, y: int) -> object | None:
        host = self.standalone_native_host
        cursor = getattr(host, "cursor", None)
        if callable(cursor):
            try:
                return cursor().pos()
            except RuntimeError:
                pass
        mapper = getattr(host, "mapToGlobal", None)
        if callable(mapper):
            try:
                return mapper(QPoint(int(x), int(y)))
            except (RuntimeError, TypeError, ValueError):
                pass
        return None
    def _handle_standalone_native_mesh_edit_stroke_started(self, payload: object) -> bool:
        return self._apply_standalone_native_mesh_edit_stroke(payload, "begin")
    def _handle_standalone_native_mesh_edit_stroke_previewed(self, payload: object) -> bool:
        return self._apply_standalone_native_mesh_edit_stroke(payload, "update")
    def _handle_standalone_native_mesh_edit_stroke_finished(self, payload: object) -> bool:
        return self._apply_standalone_native_mesh_edit_stroke(payload, "end")
    def _handle_standalone_native_mesh_edit_stroke_cancelled(self, payload: object) -> bool:
        return self._apply_standalone_native_mesh_edit_stroke(payload, "cancel")
    def _handle_standalone_native_mesh_edit_selection_changed(self, payload: object) -> bool:
        controller = self.standalone_controller
        if controller is None or not isinstance(payload, Mapping):
            return False
        raw_screen_brush = payload.get("screen_brush")
        raw_screen_region = payload.get("screen_region")
        if not isinstance(raw_screen_brush, Mapping) and not isinstance(raw_screen_region, Mapping):
            return False
        if self._native_editor_action_blocked("select"):
            return False
        operation = str(payload.get("operation", payload.get("selection_operation", "replace")) or "replace").strip().lower()
        context_request = bool(payload.get("context_request"))
        screen_payload: dict[str, object] = {}
        if isinstance(raw_screen_brush, Mapping):
            screen_payload["screen_brush"] = self._native_screen_payload(raw_screen_brush)
        if isinstance(raw_screen_region, Mapping):
            screen_payload["screen_region"] = self._native_screen_payload(raw_screen_region)
        if "falloff" in payload:
            screen_payload["falloff"] = str(payload.get("falloff") or "smooth")
        if "target_mode" in payload:
            screen_payload["target_mode"] = str(payload.get("target_mode") or "vertex")
        if "selection_depth_mode" in payload:
            screen_payload["selection_depth_mode"] = str(payload.get("selection_depth_mode") or "visible")
        try:
            result = controller.apply(
                "select",
                selection=_tab.MeshEditSelection(),
                operation=operation,
                _native_screen_selection_payload=screen_payload,
            )
            native_update = controller.native_update_for_result(result)
        except Exception as exc:
            self.standalone_status_label.setText(f"Native D3D11 mesh selection failed: {exc}")
            self.status_message_requested.emit(f"Native D3D11 mesh selection failed: {exc}", True)
            return False
        if not result.ok:
            diagnostic = "; ".join(str(item) for item in tuple(result.diagnostics or ()) if str(item).strip())
            self.standalone_status_label.setText(f"Native D3D11 mesh selection failed{': ' + diagnostic if diagnostic else ''}.")
            return False
        self.standalone_last_action_result = result
        self.standalone_last_action_metrics = {
            str(key): float(value) for key, value in dict(result.metrics).items()
        }
        if not self._apply_standalone_native_update(native_update):
            return False
        if context_request:
            if float(dict(result.metrics).get("editor_select_source_pick_count", 0.0) or 0.0) <= 0.0:
                self.standalone_status_label.setText("Native D3D11 mesh context hit no source part.")
                return False
            view = controller.session_view()
            source_indices = tuple(int(index) for index in view.selection.source_indices)
            if not source_indices:
                self.standalone_status_label.setText("Native D3D11 mesh context hit no source part.")
                return False
            try:
                context_x = int(payload.get("context_x", 0) or 0)
                context_y = int(payload.get("context_y", 0) or 0)
            except (TypeError, ValueError):
                context_x = 0
                context_y = 0
            global_pos = self._standalone_native_global_pos(context_x, context_y)
            QTimer.singleShot(
                0,
                lambda index=source_indices[0], position=global_pos: self.standalone_workspace.show_part_context_menu_for_part(
                    index,
                    position,
                ),
            )
            self.standalone_status_label.setText("Native D3D11 mesh context opened.")
            return True
        self.standalone_status_label.setText("Native D3D11 mesh selection updated.")
        return True
    def _apply_standalone_native_mesh_edit_stroke(self, payload: object, phase: str) -> bool:
        controller = self.standalone_controller
        if controller is None or not isinstance(payload, Mapping):
            return False
        normalized_phase = str(phase or "").strip().lower()
        if self._native_editor_action_blocked("transform" if str(payload.get("tool") or "").strip().lower() in {"move", "vertex"} else "brush"):
            return False
        command = self._standalone_native_mesh_edit_stroke_command(payload, normalized_phase)
        if command is None:
            return False
        stroke_id = str(command.params.get("stroke_id") or "")
        if normalized_phase == "begin":
            if self.standalone_native_mesh_edit_stroke_id and self.standalone_native_mesh_edit_stroke_id != stroke_id:
                return False
        elif stroke_id and self.standalone_native_mesh_edit_stroke_id and self.standalone_native_mesh_edit_stroke_id != stroke_id:
            return False
        if stroke_id and normalized_phase == "begin":
            self.standalone_native_mesh_edit_stroke_id = stroke_id
            self.standalone_native_mesh_edit_stroke_changed = False
        sequence = self._ensure_standalone_live_stroke_dispatcher().submit(
            controller,
            command,
            normalized_phase,
        )
        if sequence <= 0 and normalized_phase == "begin":
            self.standalone_native_mesh_edit_stroke_id = ""
        return sequence > 0
    def _ensure_standalone_live_stroke_dispatcher(self) -> _tab.MeshLiveStrokeDispatcher:
        dispatcher = self.standalone_live_stroke_dispatcher
        if dispatcher is not None:
            return dispatcher
        dispatcher = _tab.MeshLiveStrokeDispatcher(self)
        dispatcher.completed.connect(
            self._handle_standalone_live_stroke_completed,
            Qt.ConnectionType.QueuedConnection,
        )
        dispatcher.failed.connect(
            self._handle_standalone_live_stroke_failed,
            Qt.ConnectionType.QueuedConnection,
        )
        self.standalone_live_stroke_dispatcher = dispatcher
        return dispatcher
    def _handle_standalone_live_stroke_completed(self, outcome: object) -> None:
        if not isinstance(outcome, _tab.MeshLiveStrokeOutcome):
            return
        if outcome.source == "dotnet":
            self._handle_dotnet_live_stroke_completed(outcome)
            return
        controller = self.standalone_controller
        if controller is None or outcome.controller is not controller:
            return
        result = outcome.result
        native_update = outcome.native_update
        phase = outcome.phase
        has_native_delta = result.ok and (
            result.affected_submesh_indices
            or result.changed_vertices_by_submesh
            or result.topology_changed
            or native_update.vertex_groups
            or native_update.triangle_groups
            or native_update.material_override_groups
        )
        stroke_changed = bool(self.standalone_native_mesh_edit_stroke_changed or has_native_delta)
        if has_native_delta:
            self.standalone_native_mesh_edit_stroke_changed = True
        if phase in {"end", "cancel"}:
            self.standalone_native_mesh_edit_stroke_id = ""
            self.standalone_native_mesh_edit_stroke_changed = False
        if str(result.status or "").strip().lower() in {"ok", "noop"}:
            self.standalone_last_action_result = result
            self.standalone_last_action_metrics = {
                str(key): float(value) for key, value in dict(result.metrics).items()
            }
        if has_native_delta:
            if not self._apply_standalone_native_update(native_update):
                return
            if phase != "update":
                if phase == "end" and stroke_changed:
                    self.current_selection_mode = controller.active_selection_mode
                    self.current_undo_count += 1
                    self.current_redo_count = 0
                    QTimer.singleShot(0, self._sync_state)
                self.standalone_status_label.setText(f"Native D3D11 mesh edit stroke {phase}.")
            else:
                self.standalone_status_label.setText("Native D3D11 mesh edit stroke updating.")
        elif phase in {"end", "cancel"}:
            if phase == "end" and stroke_changed:
                self.current_selection_mode = controller.active_selection_mode
                self.current_undo_count += 1
                self.current_redo_count = 0
                QTimer.singleShot(0, self._sync_state)
            self.standalone_status_label.setText(f"Native D3D11 mesh edit stroke {phase}.")
    def _handle_standalone_live_stroke_failed(self, failure: object) -> None:
        if not isinstance(failure, _tab.MeshLiveStrokeFailure):
            return
        if failure.source == "dotnet":
            self._handle_dotnet_live_stroke_failed(failure)
            return
        if failure.controller is not self.standalone_controller:
            return
        if failure.phase in {"end", "cancel"}:
            self.standalone_native_mesh_edit_stroke_id = ""
            self.standalone_native_mesh_edit_stroke_changed = False
        if failure.cancelled:
            return
        message = f"Native D3D11 mesh edit stroke failed: {failure.message}"
        self.standalone_status_label.setText(message)
        self.status_message_requested.emit(message, True)
    def _standalone_native_mesh_edit_stroke_command(self, payload: Mapping[object, object], phase: str) -> _tab.MeshEditCommand | None:
        normalized_phase = str(phase or "").strip().lower()
        if normalized_phase not in {"begin", "update", "end", "cancel"}:
            return None
        stroke_id = str(payload.get("stroke_id") or "").strip()
        if not stroke_id:
            return None
        tool = str(payload.get("tool") or "").strip().lower()
        raw_groups_for_reuse = payload.get("groups")
        try:
            has_groups_for_reuse = bool(tuple(raw_groups_for_reuse or ())) and not isinstance(raw_groups_for_reuse, (Mapping, str, bytes))  # type: ignore[arg-type]
        except TypeError:
            has_groups_for_reuse = False
        reuse_resident_selection = (
            normalized_phase == "update"
            and (
                tool in {"move", "vertex", "grab"}
                or (
                    tool in {"smooth", "inflate", "pinch"}
                    and isinstance(payload.get("screen_brush"), Mapping)
                    and not has_groups_for_reuse
                )
            )
            and bool(stroke_id)
            and stroke_id == self.standalone_native_mesh_edit_stroke_id
        )
        params: dict[str, object] = {
            "stroke_phase": normalized_phase,
            "stroke_id": stroke_id,
        }
        if tool in {"move", "vertex"}:
            raw_screen_drag = payload.get("screen_drag")
            if not isinstance(raw_screen_drag, Mapping):
                if normalized_phase in {"end", "cancel"}:
                    return _tab.MeshEditCommand("transform", params=params, mode="edit", label="D3D11 stroke")
                return None
            params["screen_drag"] = MeshEditorInteractionMixin._native_screen_payload(raw_screen_drag)
            if not reuse_resident_selection:
                raw_screen_brush = payload.get("screen_brush")
                if isinstance(raw_screen_brush, Mapping):
                    screen_payload: dict[str, object] = {"screen_brush": MeshEditorInteractionMixin._native_screen_payload(raw_screen_brush)}
                    if "target_mode" in payload:
                        screen_payload["target_mode"] = str(payload.get("target_mode") or "vertex")
                    if "selection_depth_mode" in payload:
                        screen_payload["selection_depth_mode"] = str(payload.get("selection_depth_mode") or "visible")
                    if "falloff" in payload:
                        screen_payload["falloff"] = str(payload.get("falloff") or "smooth")
                    params["_native_screen_selection_payload"] = screen_payload
                else:
                    native_selection = self._standalone_native_payload_selection(payload)
                    if native_selection:
                        params["_native_selection_payload"] = native_selection
            return _tab.MeshEditCommand("transform", params=params, mode="edit", label="D3D11 stroke")
        if tool not in {"grab", "smooth", "inflate", "pinch"}:
            return None
        params["tool"] = tool
        raw_center = payload.get("center")
        if raw_center is not None:
            params["center"] = raw_center if isinstance(raw_center, Mapping) else self._standalone_native_payload_vec3(raw_center)
        raw_screen_drag = payload.get("screen_drag")
        if isinstance(raw_screen_drag, Mapping):
            params["screen_drag"] = MeshEditorInteractionMixin._native_screen_payload(raw_screen_drag)
        if "radius" in payload:
            params["radius"] = self._standalone_native_payload_float(payload.get("radius"), 1.0)
        raw_screen_radius = payload.get("screen_radius")
        if isinstance(raw_screen_radius, Mapping):
            params["screen_radius"] = MeshEditorInteractionMixin._native_screen_payload(raw_screen_radius)
        raw_screen_brush = payload.get("screen_brush")
        if isinstance(raw_screen_brush, Mapping):
            params["screen_brush"] = MeshEditorInteractionMixin._native_screen_payload(raw_screen_brush)
        if "target_mode" in payload:
            params["target_mode"] = str(payload.get("target_mode") or "vertex")
        if "selection_depth_mode" in payload:
            params["selection_depth_mode"] = str(payload.get("selection_depth_mode") or "visible")
        if "strength" in payload:
            params["strength"] = self._standalone_native_payload_float(payload.get("strength"), 0.5)
        if "amount" in payload:
            params["amount"] = self._standalone_native_payload_float(payload.get("amount"), 0.0)
        if "falloff" in payload:
            params["falloff"] = str(payload.get("falloff") or "smooth")
        if "smooth_iterations" in payload:
            params["iterations"] = self._standalone_native_payload_int(payload.get("smooth_iterations"), 3)
        if "invert" in payload:
            params["invert"] = bool(payload.get("invert"))
        if not reuse_resident_selection and not (isinstance(raw_screen_brush, Mapping) and not has_groups_for_reuse):
            native_selection = self._standalone_native_payload_selection(payload)
            if native_selection:
                params["_native_selection_payload"] = native_selection
        return _tab.MeshEditCommand("brush", params=params, mode="sculpt", label="D3D11 stroke")
    @staticmethod
    def _native_screen_payload(payload: Mapping[object, object]) -> dict[object, object]:
        return {key: value for key, value in payload.items() if str(key) not in _LEGACY_SCREEN_CAMERA_FIELDS}
    @classmethod
    def _standalone_native_payload_selection(cls, payload: Mapping[object, object]) -> dict[str, object]:
        raw_groups = payload.get("groups")
        if isinstance(raw_groups, Mapping) or isinstance(raw_groups, (str, bytes)):
            return {}
        try:
            groups = tuple(raw_groups or ())  # type: ignore[arg-type]
        except TypeError:
            return {}
        vertices_by_submesh: list[dict[str, object]] = []
        faces_by_submesh: list[dict[str, object]] = []
        for raw_group in groups:
            if not isinstance(raw_group, Mapping):
                continue
            submesh_index = cls._standalone_native_payload_int(
                raw_group.get("source_submesh_index", raw_group.get("index", raw_group.get("submesh_index"))),
                -1,
            )
            if submesh_index < 0:
                continue
            vertex_payload = cls._standalone_native_group_indices(
                raw_group,
                values_key="source_vertex_indices",
                binary_key="source_vertex_indices_binary",
                weights_key="source_vertex_weights",
                weights_binary_key="source_vertex_weights_binary",
                start_key="source_vertex_start",
                count_key="source_vertex_count",
            )
            if vertex_payload:
                vertices_by_submesh.append({"index": submesh_index, **vertex_payload})
            face_payload = cls._standalone_native_group_indices(
                raw_group,
                values_key="source_face_indices",
                binary_key="source_face_indices_binary",
                start_key="source_face_start",
                count_key="source_face_count",
            )
            if face_payload:
                faces_by_submesh.append({"index": submesh_index, **face_payload})
        result: dict[str, object] = {}
        if vertices_by_submesh:
            result["vertices_by_submesh"] = vertices_by_submesh
        if faces_by_submesh:
            result["faces_by_submesh"] = faces_by_submesh
        return result
    @classmethod
    def _standalone_native_group_indices(
        cls,
        group: Mapping[object, object],
        *,
        values_key: str,
        binary_key: str,
        start_key: str,
        count_key: str,
        weights_key: str = "",
        weights_binary_key: str = "",
    ) -> dict[str, object]:
        binary = group.get(binary_key)
        weight_payload: dict[str, object] = {}
        weights_binary = group.get(weights_binary_key) if weights_binary_key else None
        if isinstance(weights_binary, Mapping):
            weight_payload["weights_binary"] = dict(weights_binary)
        elif weights_key:
            raw_weights = group.get(weights_key)
            if not isinstance(raw_weights, Mapping) and not isinstance(raw_weights, (str, bytes)):
                try:
                    weights = tuple(raw_weights or ())  # type: ignore[arg-type]
                except TypeError:
                    weights = ()
                if weights:
                    weight_payload["weights"] = weights
        if isinstance(binary, Mapping):
            return {"indices_binary": dict(binary), **weight_payload}
        start = cls._standalone_native_payload_int(group.get(start_key), -1)
        count = cls._standalone_native_payload_int(group.get(count_key), 0)
        if start >= 0 and count > 0:
            return {"start": start, "count": count, **weight_payload}
        raw_values = group.get(values_key)
        if isinstance(raw_values, Mapping) or isinstance(raw_values, (str, bytes)):
            return {}
        try:
            values = tuple(raw_values or ())  # type: ignore[arg-type]
        except TypeError:
            return {}
        indices = sorted({cls._standalone_native_payload_int(value, -1) for value in values})
        indices = [index for index in indices if index >= 0]
        return {"indices": indices, **weight_payload} if indices else {}
    @staticmethod
    def _standalone_native_payload_vec3(value: object) -> tuple[float, float, float]:
        if isinstance(value, Mapping):
            raw_values = (value.get("x", 0.0), value.get("y", 0.0), value.get("z", 0.0))
        else:
            try:
                raw_values = tuple(value or ())[:3]  # type: ignore[arg-type]
            except TypeError:
                raw_values = ()
        result: list[float] = []
        for raw in tuple(raw_values)[:3]:
            try:
                result.append(float(raw))  # type: ignore[arg-type]
            except (TypeError, ValueError):
                result.append(0.0)
        while len(result) < 3:
            result.append(0.0)
        return result[0], result[1], result[2]
    @staticmethod
    def _standalone_native_payload_float(value: object, fallback: float = 0.0) -> float:
        try:
            return float(value)  # type: ignore[arg-type]
        except (TypeError, ValueError, OverflowError):
            return float(fallback)
    @staticmethod
    def _standalone_native_payload_int(value: object, fallback: int = 0) -> int:
        try:
            return int(value)  # type: ignore[arg-type]
        except (TypeError, ValueError, OverflowError):
            return int(fallback)
