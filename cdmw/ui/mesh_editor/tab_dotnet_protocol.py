from __future__ import annotations

import json
from typing import Mapping, Sequence

from PySide6.QtCore import QTimer
from cdmw.ui.mesh_editor.actions import mesh_editor_actions_by_key
from cdmw.ui.mesh_editor.tab_compat import facade_globals as _tab
from cdmw.ui.mesh_editor import tab_dotnet_material_commit as _material_commit
from cdmw.ui.mesh_editor.tab_dotnet_material_parameters import MeshEditorDotNetMaterialParameterMixin

class MeshEditorDotNetProtocolMixin(MeshEditorDotNetMaterialParameterMixin):
    def _connect_dotnet_protocol(self, process: _tab.QProcess) -> None:
        self.standalone_dotnet_update_ack_timer.stop()
        self.standalone_dotnet_update_queue.reset()
        self.standalone_texture_region_queue.reset()
        self.standalone_dotnet_material_parameter_timer.stop()
        self.standalone_dotnet_pending_material_parameter_payload = None
        _material_commit.remember_sent_material_parameters(self, None)
        _material_commit.remember_sent_material_resources(self, None)
        self.standalone_dotnet_protocol_stdout = ""
        self.standalone_dotnet_protocol_events = []
        self.standalone_dotnet_capabilities.clear()
        try:
            process.readyReadStandardOutput.connect(
                lambda target=process: self._handle_dotnet_protocol_stdout_ready(target)
            )
            process.started.connect(self._send_dotnet_session_state)
        except (AttributeError, RuntimeError, TypeError):
            pass
        try:
            process.readyReadStandardError.connect(
                lambda target=process: self._handle_dotnet_protocol_stderr_ready(target)
            )
        except (AttributeError, RuntimeError, TypeError):
            pass
    def _handle_dotnet_protocol_stdout_ready(self, process: _tab.QProcess) -> None:
        if self.standalone_dotnet_editor_process is not process:
            return
        try:
            raw = bytes(process.readAllStandardOutput())
        except (AttributeError, RuntimeError, TypeError):
            return
        if not raw:
            return
        self.standalone_dotnet_protocol_stdout += raw.decode("utf-8", "replace")
        if len(self.standalone_dotnet_protocol_stdout) > _tab.DOTNET_PROTOCOL_BUFFER_LIMIT:
            buffered = len(self.standalone_dotnet_protocol_stdout)
            self.standalone_dotnet_protocol_stdout = ""
            self._record_mesh_dotnet_event("mesh_dotnet_protocol_buffer_limit", buffered_chars=buffered)
            self._set_dotnet_status("Mesh .NET editor protocol exceeded its input limit.", error=True)
            self._stop_standalone_dotnet_editor_process(embedded_state="failed")
            return
        while "\n" in self.standalone_dotnet_protocol_stdout:
            line, self.standalone_dotnet_protocol_stdout = self.standalone_dotnet_protocol_stdout.split("\n", 1)
            if len(line) > _tab.DOTNET_PROTOCOL_LINE_LIMIT:
                self._record_mesh_dotnet_event("mesh_dotnet_protocol_line_limit", line_chars=len(line))
                self._set_dotnet_status("Mesh .NET editor protocol ignored an oversized message.", error=True)
                continue
            self._handle_dotnet_protocol_line(line.strip())
    def _handle_dotnet_protocol_stderr_ready(self, process: _tab.QProcess) -> None:
        if self.standalone_dotnet_editor_process is not process:
            return
        try:
            raw = bytes(process.readAllStandardError())
        except (AttributeError, RuntimeError, TypeError):
            return
        self.standalone_dotnet_stderr_tail = _tab.append_bounded_text(
            self.standalone_dotnet_stderr_tail,
            raw.decode("utf-8", "replace"),
        )
    def _handle_dotnet_protocol_line(self, line: str) -> bool:
        if not line:
            return False
        try:
            payload = json.loads(line)
        except ValueError:
            self._set_dotnet_status("Mesh .NET editor protocol ignored malformed JSON.", error=True)
            return False
        if not isinstance(payload, dict):
            self._set_dotnet_status("Mesh .NET editor protocol ignored non-object JSON.", error=True)
            return False
        return self._handle_dotnet_protocol_event(payload)
    def _sync_dotnet_update_ack_timer(self) -> None:
        metrics = self.standalone_dotnet_update_queue.metrics()
        if int(metrics.get("active_revision", 0) or 0) > 0:
            self.standalone_dotnet_update_ack_timer.start(1_000)
        else:
            self.standalone_dotnet_update_ack_timer.stop()
    def _handle_dotnet_update_ack_timeout(self) -> None:
        metrics = self.standalone_dotnet_update_queue.metrics()
        revision = int(metrics.get("active_revision", 0) or 0)
        if revision <= 0 or not self.standalone_dotnet_update_queue.expire_active(revision):
            return
        self._record_mesh_dotnet_event("mesh_dotnet_update_ack_timeout", edit_revision=revision)
        self._sync_dotnet_update_ack_timer()
    def _handle_dotnet_protocol_event(self, payload: Mapping[str, object]) -> bool:
        event = str(payload.get("event", payload.get("type", "")) or "").strip().lower()
        if not event:
            self._set_dotnet_status("Mesh .NET editor protocol message had no event.", error=True)
            return False
        if event in {"preview_vertex_update_ack", "preview_triangle_update_ack"}:
            handled = self.standalone_dotnet_update_queue.acknowledge(event, payload)
            self._sync_dotnet_update_ack_timer()
            return handled
        if event in {"texture_region_applied", "texture_region_failed"}:
            if not self._dotnet_session_matches(payload):
                return False
            self.standalone_dotnet_protocol_events.append(dict(payload))
            if len(self.standalone_dotnet_protocol_events) > _tab.DOTNET_PROTOCOL_EVENT_LIMIT:
                del self.standalone_dotnet_protocol_events[:-_tab.DOTNET_PROTOCOL_EVENT_LIMIT]
            return self.standalone_texture_region_queue.acknowledge(event, payload)
        self.standalone_dotnet_protocol_events.append(dict(payload))
        if len(self.standalone_dotnet_protocol_events) > _tab.DOTNET_PROTOCOL_EVENT_LIMIT:
            del self.standalone_dotnet_protocol_events[:-_tab.DOTNET_PROTOCOL_EVENT_LIMIT]
        if not self._dotnet_session_matches(payload):
            self._send_dotnet_command_result(
                str(payload.get("command", event) or event),
                ok=False,
                status="error",
                diagnostics=("Stale .NET mesh editor session id.",),
            )
            return False
        if event == "ready":
            self._observe_dotnet_capabilities(payload)
            self.standalone_dotnet_update_queue.observe_capabilities(payload)
            self.standalone_dotnet_material_signature = str(
                payload.get("material_signature", self.standalone_dotnet_material_signature) or ""
            )
            self.standalone_dotnet_status_payload["host_lifecycle_counts"] = dict(
                self.standalone_dotnet_lifecycle_counts
            )
            self.standalone_dotnet_ready_timer.stop()
            if not self._handle_dotnet_renderer_status(payload, source_event="ready"):
                if self.standalone_dotnet_target_embedded:
                    self._request_or_stop_blocked_embedded_dotnet("mesh_dotnet_renderer_blocked")
                return False
            renderer = payload.get("renderer")
            if isinstance(renderer, Mapping):
                self.standalone_dotnet_status_payload["renderer"] = dict(renderer)
            self._record_mesh_dotnet_event(
                "mesh_dotnet_process_ready",
                embedded=bool(self.standalone_dotnet_target_embedded),
                package_dir=str(getattr(self.standalone_dotnet_experiment_package, "package_dir", "") or ""),
                status_path=str(getattr(self.standalone_dotnet_experiment_package, "status_path", "") or ""),
            )
            if self.standalone_dotnet_target_embedded:
                self._record_mesh_dotnet_event(
                    "mesh_dotnet_embedded_ready_accepted",
                    dotnet_state=str(self.standalone_dotnet_embedded_state or ""),
                    package_dir=str(getattr(self.standalone_dotnet_experiment_package, "package_dir", "") or ""),
                    status_path=str(getattr(self.standalone_dotnet_experiment_package, "status_path", "") or ""),
                )
                self._set_embedded_dotnet_state("ready", active=True)
                self._notify_embedded_dotnet_ready()
                self.update_editor_action_state(selection_empty=self.current_selection_empty)
            self._send_dotnet_session_state()
            return True
        if event == "protocol_ready":
            self._observe_dotnet_capabilities(payload)
            self.standalone_dotnet_update_queue.observe_capabilities(payload)
            return True
        if event == "activated":
            self.standalone_dotnet_ready_timer.stop()
            if self.standalone_dotnet_target_embedded:
                self._set_embedded_dotnet_state("ready", active=True)
                self._notify_embedded_dotnet_ready()
                self.update_editor_action_state(selection_empty=self.current_selection_empty)
            self._send_dotnet_session_state()
            return True
        if event == "deactivated":
            if self.standalone_dotnet_target_embedded:
                self.standalone_dotnet_deactivate_timer.stop()
                self.standalone_dotnet_deactivate_acknowledged = True
                if self.standalone_dotnet_exit_pending:
                    self._complete_pending_dotnet_exit()
                else:
                    self._set_embedded_dotnet_state("suspended", active=False)
                    self.update_editor_action_state(selection_empty=self.current_selection_empty)
            return True
        if event == "metrics":
            metrics = payload.get("metrics", payload)
            if isinstance(metrics, Mapping):
                self.standalone_dotnet_status_payload["metrics"] = dict(metrics)
                renderer = metrics.get("renderer", payload.get("renderer"))
                if isinstance(renderer, Mapping):
                    self.standalone_dotnet_status_payload["renderer"] = dict(renderer)
                    if not self._handle_dotnet_renderer_status({"renderer": renderer}, source_event="metrics", emit_warning=False):
                        return False
            return True
        if event == "textures_ready":
            renderer = payload.get("renderer")
            if isinstance(renderer, Mapping):
                self.standalone_dotnet_status_payload["renderer"] = dict(renderer)
            self._set_dotnet_status(
                "Mesh .NET textures ready: "
                f"{int(payload.get('decoded_texture_resources', 0) or 0)} decoded, "
                f"{int(payload.get('texture_load_failures', 0) or 0)} failed."
            )
            return True
        if event == "textures_error":
            self._set_dotnet_status(str(payload.get("message", "Texture load failed.") or "Texture load failed."), error=True)
            return False
        if event in {"material_sync_required", "material_state_applied", "material_state_failed", "material_reload_required"}:
            return self._handle_dotnet_material_protocol_event(payload, event)
        if event in {"material_parameter_applied", "material_parameter_failed"}:
            return self._handle_dotnet_material_parameter_event(payload, event)
        if event == "select_request":
            return self._handle_dotnet_select_request(payload)
        if event == "selection_request":
            return self._handle_dotnet_local_selection_request(payload)
        if event in {"stroke_begin", "stroke_update", "stroke_end", "stroke_cancel"}:
            return self._handle_dotnet_stroke_event(payload, event.removeprefix("stroke_"))
        if event in {"command_request", "command_requested"}:
            return self._handle_dotnet_command_request(payload)
        if event == "save_request":
            return self._request_embedded_dotnet_editor_close()
        if event == "error":
            message = str(payload.get("message", "") or "Mesh .NET editor reported an error.")
            self._set_dotnet_status(message, error=True)
            return False
        return False
    def _handle_dotnet_material_protocol_event(self, payload: Mapping[str, object], event: str) -> bool:
        if event == "material_sync_required":
            if not self._dotnet_resident_material_updates_supported():
                self._set_dotnet_status("Mesh .NET helper requested material sync without resident material capability.", error=True)
                return False
            return self._send_dotnet_material_state(reason="signature_mismatch")
        if event in {"material_state_applied", "material_state_failed"}:
            try:
                generation = int(payload.get("generation", 0) or 0)
            except (TypeError, ValueError):
                generation = 0
            if (
                generation <= self.standalone_dotnet_completed_material_generation
                or generation != self.standalone_dotnet_material_generation
            ):
                return False
            self.standalone_dotnet_completed_material_generation = generation
        if event == "material_state_applied":
            if not _material_commit.commit_acknowledged_material_resources(self, payload):
                return False
            self.standalone_dotnet_applied_material_generation = generation
            self.standalone_dotnet_material_signature = str(
                payload.get("material_signature", self.standalone_dotnet_material_signature) or ""
            )
            self.standalone_dotnet_lifecycle_counts["material_state_applied_count"] += 1
            self._set_dotnet_status(f"Mesh materials updated in the resident .NET session (generation {generation}).")
            return True
        if event == "material_state_failed":
            _material_commit.finish_sent_material_resources(self, committed=False)
            _material_commit.remember_sent_material_resources(self, None)
            self.standalone_dotnet_lifecycle_counts["material_state_failed_count"] += 1
            message = str(payload.get("message", payload.get("reason", "Material update failed.")) or "Material update failed.")
            if self.standalone_dotnet_target_embedded and self.standalone_dotnet_embedded_state == "launching":
                self.standalone_dotnet_ready_timer.stop()
                self._set_embedded_dotnet_state("ready", active=True)
                self._notify_embedded_dotnet_ready()
            self._set_dotnet_status(f"Mesh material update failed; keeping last valid resources: {message}", error=True)
            return False
        if event == "material_reload_required":
            if self._dotnet_resident_material_updates_supported():
                self._set_dotnet_status("Resident .NET helper attempted a forbidden material reload.", error=True)
                return False
            controller = self._dotnet_target_controller()
            if not self.standalone_dotnet_target_embedded or controller is None:
                return False
            self.standalone_dotnet_lifecycle_counts["full_reload_count"] += 1
            self._set_dotnet_status("Legacy protocol-v1 helper requires a material package reload.")
            self._stop_standalone_dotnet_editor_process(embedded_state="launching")
            QTimer.singleShot(0, lambda target=controller: self._start_dotnet_editor_requested(target, embedded=True))
            return True
        return False
    def _request_or_stop_blocked_embedded_dotnet(self, reason: str) -> None:
        if not self.standalone_dotnet_target_embedded:
            return
        self._record_mesh_dotnet_event(
            "mesh_dotnet_embedded_process_stopped_after_blocker",
            reason=str(reason or "blocked"),
            dotnet_state=str(self.standalone_dotnet_embedded_state or ""),
            **self._dotnet_process_event_payload(self.standalone_dotnet_editor_process),
        )
        self._stop_standalone_dotnet_editor_process(embedded_state="failed")
    def _handle_dotnet_ready_timeout(self) -> None:
        if not self._standalone_dotnet_editor_process_running():
            return
        if self.standalone_dotnet_target_embedded and self.standalone_dotnet_embedded_state != "launching":
            return
        detail = "Mesh .NET editor started but did not report ready within 10 seconds."
        self._record_mesh_dotnet_event(
            "mesh_dotnet_ready_timeout",
            embedded=bool(self.standalone_dotnet_target_embedded),
            **self._dotnet_process_event_payload(self.standalone_dotnet_editor_process),
        )
        self._stop_standalone_dotnet_editor_process(embedded_state="failed")
        self._set_dotnet_status(detail, error=True)
        if self.standalone_dotnet_target_embedded:
            self._notify_embedded_dotnet_launch_failed("mesh_dotnet_ready_timeout", diagnostics=detail)
    def _handle_dotnet_deactivate_timeout(self) -> None:
        if not self.standalone_dotnet_exit_pending or self.standalone_dotnet_deactivate_acknowledged:
            return
        self._record_mesh_dotnet_event(
            "mesh_dotnet_deactivate_timeout",
            **self._dotnet_process_event_payload(self.standalone_dotnet_editor_process),
        )
        self._stop_standalone_dotnet_editor_process(embedded_state="closing")
        self.standalone_dotnet_deactivate_acknowledged = True
        self._set_dotnet_status("Mesh .NET editor did not acknowledge deactivation; helper stopped before saving resident edits.", error=True)
        self._complete_pending_dotnet_exit()
    def _dotnet_session_matches(self, payload: Mapping[str, object]) -> bool:
        raw_session = str(payload.get("session_id", "") or "").strip()
        if not raw_session:
            return True
        controller = self._dotnet_target_controller()
        if controller is None:
            return False
        try:
            return raw_session == str(controller.session_view().session_id)
        except (AttributeError, RuntimeError, TypeError, ValueError):
            return False
    def _send_dotnet_protocol_message(self, payload: Mapping[str, object]) -> bool:
        process = self.standalone_dotnet_editor_process
        if process is None:
            return False
        try:
            if process.state() == _tab.QProcess.NotRunning:
                return False
            data = (json.dumps(dict(payload), separators=(",", ":"), default=str) + "\n").encode("utf-8")
            return int(process.write(data)) == len(data)
        except (AttributeError, RuntimeError, TypeError, ValueError):
            return False
    def _observe_dotnet_capabilities(self, payload: Mapping[str, object]) -> None:
        raw = payload.get("capabilities", ())
        if isinstance(raw, Sequence) and not isinstance(raw, (str, bytes)):
            self.standalone_dotnet_capabilities.update(str(item) for item in raw)
    def _send_dotnet_material_state(
        self,
        *,
        reason: str = "changed",
        affected_submeshes: Sequence[int] | None = None,
        mesh_snapshot: object | None = None,
        committed_resources: Sequence[Mapping[str, object]] = (),
    ) -> bool:
        controller = self._dotnet_target_controller()
        if controller is None or not self._dotnet_resident_material_updates_supported():
            return False
        try:
            view = controller.session_view()
            mesh = mesh_snapshot if mesh_snapshot is not None else controller.working_mesh(clone=False)
            self.standalone_dotnet_material_generation += 1
            payload = _tab.mesh_dotnet_material_state_payload(
                mesh,
                session_id=view.session_id,
                edit_revision=view.revision,
                generation=self.standalone_dotnet_material_generation,
                affected_submeshes=affected_submeshes,
            )
        except (AttributeError, OSError, RuntimeError, TypeError, ValueError) as exc:
            self.standalone_dotnet_lifecycle_counts["material_state_failed_count"] += 1
            self._set_dotnet_status(f"Could not snapshot resident material state: {exc}", error=True)
            return False
        payload["reason"] = str(reason or "changed")
        if not self._send_dotnet_protocol_message(payload):
            _material_commit.remember_sent_material_resources(self, None)
            self.standalone_dotnet_lifecycle_counts["material_state_failed_count"] += 1
            return False
        _material_commit.remember_sent_material_resources(self, payload, committed_resources)
        self.standalone_dotnet_lifecycle_counts["material_state_update_count"] += 1
        self._record_mesh_dotnet_event(
            "mesh_dotnet_material_state_update",
            generation=self.standalone_dotnet_material_generation,
            edit_revision=view.revision,
            material_signature=str(payload.get("material_signature", "") or ""),
            affected_submesh_count=len(tuple(payload.get("affected_submeshes", ()) or ())),
        )
        return True
    def apply_resident_material_resources(
        self,
        mesh_snapshot: object,
        bindings: Sequence[Mapping[str, object]],
        *,
        affected_submeshes: Sequence[int] = (),
        reason: str = "material_authority_resource",
    ) -> bool:
        if not bindings:
            return False
        affected = {
            int(index)
            for binding in bindings
            for index in (
                tuple(binding.get("affected_submeshes", ()) or ()) if isinstance(binding, Mapping) else ()
            )
            if not isinstance(index, bool)
        }
        scope = tuple(sorted(affected)) or tuple(affected_submeshes)
        snapshot = _material_commit.material_resource_snapshot(
            self, mesh_snapshot, bindings, scope
        )
        return self._send_dotnet_material_state(
            reason=reason,
            affected_submeshes=scope or None,
            mesh_snapshot=snapshot,
            committed_resources=bindings,
        )
    def _flush_dotnet_protocol_messages(self, timeout_ms: int = 500) -> bool:
        del timeout_ms
        return True
    def _send_dotnet_session_state(self) -> bool:
        controller = self._dotnet_target_controller()
        if controller is None:
            return False
        try:
            view = controller.session_view()
        except (AttributeError, RuntimeError, TypeError, ValueError):
            return False
        actions = sorted(mesh_editor_actions_by_key().keys())
        selection = view.selection
        payload = {
            "event": "session_state",
            "session_id": view.session_id,
            "mode": view.mode,
            "revision": view.revision,
            "selection_mode": str(getattr(controller, "active_selection_mode", "") or self.current_selection_mode or "vertex"),
            "selection": self._dotnet_selection_payload(selection),
            "submesh_count": view.submesh_count,
            "vertex_count": view.vertex_count,
            "face_count": view.face_count,
            "undo_count": view.undo_count,
            "redo_count": view.redo_count,
            "actions": actions,
            "selection_depth_mode": "visible",
        }
        return self._send_dotnet_protocol_message(payload)
    @staticmethod
    def _dotnet_selection_payload(selection: _tab.MeshEditSelection) -> dict[str, object]:
        return {
            "vertices_by_submesh": selection.vertices_by_submesh,
            "edges_by_submesh": selection.edges_by_submesh,
            "faces_by_submesh": selection.faces_by_submesh,
            "source_indices": selection.source_indices,
            "empty": selection.is_empty(),
        }
    @classmethod
    def _dotnet_local_selection_payload_to_selection(cls, payload: Mapping[str, object]) -> _tab.MeshEditSelection:
        raw_selection = payload.get("local_selection")
        if not isinstance(raw_selection, Mapping):
            raw_selection = payload.get("selection")
        if not isinstance(raw_selection, Mapping):
            return _tab.MeshEditSelection()
        vertices = cls._dotnet_index_map(raw_selection.get("vertices_by_submesh"))
        faces = cls._dotnet_index_map(raw_selection.get("faces_by_submesh"))
        edges = cls._dotnet_edge_map(raw_selection.get("edges_by_submesh"))
        if not edges:
            edges = cls._dotnet_edge_descriptors(raw_selection.get("edge_descriptors"))
        sources = cls._dotnet_int_values(
            raw_selection.get("source_indices", raw_selection.get("sources", ()))
        )
        return _tab.MeshEditSelection.from_maps(
            vertices_by_submesh=vertices,
            edges_by_submesh=edges,
            faces_by_submesh=faces,
            source_indices=sources,
        )
    @classmethod
    def _dotnet_index_map(cls, value: object) -> dict[int, tuple[int, ...]]:
        result: dict[int, tuple[int, ...]] = {}
        for submesh, values in cls._dotnet_map_items(value):
            indices = tuple(sorted({index for index in cls._dotnet_int_values(values) if index >= 0}))
            if indices:
                result[submesh] = indices
        return result
    @classmethod
    def _dotnet_edge_map(cls, value: object) -> dict[int, tuple[tuple[int, int], ...]]:
        result: dict[int, tuple[tuple[int, int], ...]] = {}
        for submesh, raw_edges in cls._dotnet_map_items(value):
            pairs = cls._dotnet_edge_pairs(raw_edges)
            if pairs:
                result[submesh] = pairs
        return result
    @classmethod
    def _dotnet_edge_descriptors(cls, value: object) -> dict[int, tuple[tuple[int, int], ...]]:
        if isinstance(value, Mapping) or isinstance(value, (str, bytes)):
            return {}
        try:
            items = tuple(value or ())  # type: ignore[arg-type]
        except TypeError:
            return {}
        result: dict[int, set[tuple[int, int]]] = {}
        for item in items:
            if not isinstance(item, Mapping):
                continue
            submesh = cls._standalone_native_payload_int(
                item.get("source_submesh_index", item.get("submesh_index", -1)),
                -1,
            )
            a = cls._standalone_native_payload_int(item.get("vertex_a"), -1)
            b = cls._standalone_native_payload_int(item.get("vertex_b"), -1)
            if submesh < 0 or a < 0 or b < 0 or a == b:
                continue
            pair = (a, b) if a <= b else (b, a)
            result.setdefault(submesh, set()).add(pair)
        return {submesh: tuple(sorted(pairs)) for submesh, pairs in sorted(result.items())}
    @classmethod
    def _dotnet_map_items(cls, value: object) -> tuple[tuple[int, object], ...]:
        pairs: list[tuple[int, object]] = []
        if isinstance(value, Mapping):
            iterable = value.items()
        elif not isinstance(value, (str, bytes)):
            try:
                iterable = tuple(value or ())  # type: ignore[arg-type]
            except TypeError:
                iterable = ()
        else:
            iterable = ()
        for item in iterable:
            if isinstance(value, Mapping):
                raw_key, raw_values = item
            else:
                if isinstance(item, Mapping):
                    raw_key = item.get("index", item.get("submesh", item.get("submesh_index", -1)))
                    raw_values = item.get("indices", item.get("values", item.get("edges", ())))
                else:
                    try:
                        item_values = tuple(item or ())  # type: ignore[arg-type]
                    except TypeError:
                        continue
                    if len(item_values) < 2:
                        continue
                    raw_key, raw_values = item_values[0], item_values[1]
            key = cls._standalone_native_payload_int(raw_key, -1)
            if key >= 0:
                pairs.append((key, raw_values))
        return tuple(pairs)
    @classmethod
    def _dotnet_int_values(cls, value: object) -> tuple[int, ...]:
        if isinstance(value, Mapping) or isinstance(value, (str, bytes)):
            return ()
        try:
            raw_values = tuple(value or ())  # type: ignore[arg-type]
        except TypeError:
            return ()
        return tuple(cls._standalone_native_payload_int(raw, -1) for raw in raw_values)
    @classmethod
    def _dotnet_edge_pairs(cls, value: object) -> tuple[tuple[int, int], ...]:
        if isinstance(value, Mapping) or isinstance(value, (str, bytes)):
            return ()
        try:
            raw_edges = tuple(value or ())  # type: ignore[arg-type]
        except TypeError:
            return ()
        edges: set[tuple[int, int]] = set()
        for raw_edge in raw_edges:
            if isinstance(raw_edge, Mapping):
                a = cls._standalone_native_payload_int(raw_edge.get("vertex_a"), -1)
                b = cls._standalone_native_payload_int(raw_edge.get("vertex_b"), -1)
            else:
                try:
                    pair_values = tuple(raw_edge or ())[:2]  # type: ignore[arg-type]
                except TypeError:
                    continue
                if len(pair_values) < 2:
                    continue
                a = cls._standalone_native_payload_int(pair_values[0], -1)
                b = cls._standalone_native_payload_int(pair_values[1], -1)
            if a >= 0 and b >= 0 and a != b:
                edges.add((a, b) if a <= b else (b, a))
        return tuple(sorted(edges))
    def _send_dotnet_command_result(
        self,
        command: str,
        *,
        ok: bool,
        status: str,
        revision: int | None = None,
        diagnostics: Sequence[object] = (),
    ) -> bool:
        payload: dict[str, object] = {
            "event": "command_result",
            "command": command,
            "ok": bool(ok),
            "status": status,
            "diagnostics": [str(item) for item in diagnostics],
        }
        if revision is not None:
            payload["revision"] = int(revision)
        return self._send_dotnet_protocol_message(payload)
    def _send_dotnet_native_update(
        self,
        update: _tab.MeshEditorNativeUpdate,
        *,
        result: _tab.MeshEditResult | None = None,
    ) -> None:
        controller = self._dotnet_target_controller()
        session_id = ""
        revision = None
        selection: _tab.MeshEditSelection | None = None
        if controller is not None:
            try:
                view = controller.session_view()
                session_id = view.session_id
                revision = view.revision
                selection = view.selection
            except (AttributeError, RuntimeError, TypeError, ValueError):
                pass
        base: dict[str, object] = {}
        if session_id:
            base["session_id"] = session_id
        if revision is not None:
            base["edit_revision"] = int(revision)
            base["revision"] = int(revision)
        if update.refresh_selection:
            self._send_dotnet_protocol_message({
                **base,
                "event": "selection_update",
                "selection": self._dotnet_selection_payload(selection or _tab.MeshEditSelection()),
                "selection_groups": update.selection_groups,
            })
        if update.material_override_groups:
            self.apply_resident_material_parameters(update.material_override_groups)
        edit_packets: list[dict[str, object]] = []
        if update.vertex_groups:
            edit_packets.append({
                **base,
                "event": "preview_vertex_update",
                "vertex_groups": update.vertex_groups,
            })
        if update.triangle_groups or update.triangle_source_submesh_indices or update.replace_all_triangles:
            edit_packets.append({
                **base,
                "event": "preview_triangle_update",
                "triangle_groups": update.triangle_groups,
                "triangle_source_submesh_indices": update.triangle_source_submesh_indices,
                "replace_all_triangles": update.replace_all_triangles,
                "final_submesh_count": update.final_submesh_count,
                "material_override_groups": update.material_override_groups,
            })
        self.standalone_dotnet_update_queue.enqueue(int(revision or 0), edit_packets)
        self._sync_dotnet_update_ack_timer()
        if result is not None:
            self._send_dotnet_command_result(
                result.action,
                ok=str(result.status or "").strip().lower() != "error",
                status=str(result.status or ""),
                revision=result.revision,
                diagnostics=result.diagnostics,
            )
    def _dotnet_screen_selection_payload(self, payload: Mapping[str, object]) -> dict[str, object]:
        screen_payload: dict[str, object] = {}
        raw_screen_brush = payload.get("screen_brush")
        raw_screen_region = payload.get("screen_region")
        if isinstance(raw_screen_brush, Mapping):
            screen_payload["screen_brush"] = self._native_screen_payload(raw_screen_brush)
        if isinstance(raw_screen_region, Mapping):
            screen_payload["screen_region"] = self._native_screen_payload(raw_screen_region)
        if "falloff" in payload:
            screen_payload["falloff"] = str(payload.get("falloff") or "smooth")
        if "target_mode" in payload:
            screen_payload["target_mode"] = str(payload.get("target_mode") or "vertex")
        depth_mode = str(payload.get("selection_depth_mode", "visible") or "visible").strip().lower()
        screen_payload["selection_depth_mode"] = "xray" if depth_mode == "xray" else "visible"
        return screen_payload
    def _apply_dotnet_result_update(
        self,
        controller: _tab.MeshEditorController,
        result: _tab.MeshEditResult,
        *,
        command_name: str = "",
    ) -> bool:
        try:
            update = controller.native_update_for_result(result)
        except Exception as exc:
            self._set_dotnet_status(f"Mesh .NET editor command failed: {exc}", error=True)
            self._send_dotnet_command_result(
                command_name or result.action,
                ok=False,
                status="error",
                diagnostics=(str(exc),),
            )
            return False
        if self.standalone_dotnet_target_embedded:
            self._apply_embedded_native_update(update)
            self._refresh_embedded_workspace_from_builder()
        elif (
            update.vertex_groups
            or update.triangle_groups
            or update.triangle_source_submesh_indices
            or update.selection_groups
            or update.refresh_selection
            or update.material_override_groups
            or update.replace_all_triangles
        ):
            self._apply_standalone_native_update(update)
            QTimer.singleShot(0, self._sync_state)
        self._send_dotnet_native_update(update, result=result)
        return str(result.status or "").strip().lower() != "error"
