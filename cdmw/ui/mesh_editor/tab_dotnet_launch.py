from __future__ import annotations

from pathlib import Path
from typing import Mapping, Sequence

from cdmw.services.mesh_rust_contract import resolve_rust_mesh_editor
from cdmw.ui.mesh_editor.tab_compat import facade_globals as _tab


class MeshEditorDotNetLaunchMixin:
    def _record_mesh_dotnet_event(self, event: str, **payload: object) -> None:
        event_name = str(event or "").strip()
        if not event_name:
            return
        normalized = {str(key): self._json_safe_runtime_value(value) for key, value in payload.items()}
        try:
            builder = self.active_builder()
        except RuntimeError:
            builder = None
        try:
            parent = self.parent()
        except RuntimeError:
            parent = None
        for target in (builder, parent):
            recorder = getattr(target, "_record_runtime_event", None) if target is not None else None
            if callable(recorder):
                try:
                    recorder(event_name, **normalized)
                    return
                except TypeError:
                    try:
                        recorder(event_name, normalized)
                        return
                    except Exception:
                        # Best effort: runtime-event sinks are optional diagnostics.
                        pass
                except Exception:
                    # Best effort: a broken parent/builder recorder must not fail UI work.
                    pass
        try:
            self.runtime_event_requested.emit(event_name, normalized)
        except (RuntimeError, TypeError):
            pass
    @staticmethod
    def _json_safe_runtime_value(value: object) -> object:
        if value is None or isinstance(value, (str, int, float, bool)):
            return value
        if isinstance(value, Path):
            return str(value)
        if isinstance(value, Mapping):
            return {str(key): MeshEditorDotNetLaunchMixin._json_safe_runtime_value(item) for key, item in value.items()}
        if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
            return [MeshEditorDotNetLaunchMixin._json_safe_runtime_value(item) for item in tuple(value)]
        return str(value)
    def _dotnet_editor_executable_resolution(self, *, log: bool = True) -> object:
        raw = str(self.settings.value("mesh_editor/rust_mesh_editor_executable", "") or "").strip()
        resolution = resolve_rust_mesh_editor(raw)
        if log:
            self._record_mesh_dotnet_event(
                "mesh_rust_executable_resolved",
                resolved_path=str(getattr(resolution, "resolved_path", "") or ""),
                source=str(getattr(resolution, "source", "") or ""),
                is_file=bool(getattr(resolution, "is_file", False)),
            )
        return resolution
    def _dotnet_editor_executable_path(self, *, log: bool = True) -> Path | None:
        resolution = self._dotnet_editor_executable_resolution(log=log)
        if not resolution.is_file or not resolution.resolved_path:
            return None
        return Path(resolution.resolved_path)
    def _standalone_dotnet_package_worker_active(self) -> bool:
        return self.standalone_dotnet_package_thread is not None or self.standalone_dotnet_package_worker is not None
    def _dotnet_task_active(self) -> bool:
        return (
            self._standalone_dotnet_package_worker_active()
        )
    def _set_dotnet_status(self, message: str, *, error: bool = False) -> None:
        label = (
            getattr(self.embedded_workspace, "status_label", None)
            if self.standalone_dotnet_target_embedded and self.embedded_workspace is not None
            else self.standalone_status_label
        )
        if label is not None:
            label.setText(message)
        self.status_message_requested.emit(message, error)
    def _set_embedded_dotnet_preview_loading(
        self,
        active: bool,
        message: str,
        *,
        detail: str = "",
    ) -> None:
        if not self.standalone_dotnet_target_embedded:
            return
        setter = getattr(
            self.active_builder(),
            "_mesh_editor_embedded_set_preview_loading",
            None,
        )
        if not callable(setter):
            return
        try:
            setter(bool(active), str(message or ""), detail=str(detail or ""))
        except (AttributeError, RuntimeError, TypeError, ValueError):
            pass
    def _start_standalone_dotnet_editor_requested(self) -> None:
        controller = self.standalone_controller
        if controller is None:
            self.status_message_requested.emit("Mesh Editor unavailable: no active session.", True)
            return
        self._start_rust_editor_requested(controller)
    def _start_embedded_dotnet_editor_requested(self) -> None:
        controller = self._embedded_builder_controller()
        if controller is None:
            self.status_message_requested.emit("Mesh Editor unavailable: no embedded edit session.", True)
            return
        self._start_rust_editor_requested(controller)

    def _resident_helper_holds_cached_scene(self) -> bool:
        """True when the running helper is actually serving this tab's cached scene.

        The reuse fast path asks the shared resident controller to activate, and
        that reveals whatever scene is resident. Deciding the helper "already has
        this scene" from `standalone_dotnet_experiment_package` alone is not safe:
        that cache survives `_stop_standalone_dotnet_editor_process` and outlives
        the dialog that filled it, while the helper running by then can be a
        freshly prewarmed one holding the procedural placeholder. That pairing is
        what flashed the warm-up triangle into the pane at Mesh Editor start. Ask
        the controller that owns the process instead of trusting the cache.
        """

        controller = self._active_shared_dotnet_controller()
        if controller is None:
            return False
        cached_package_dir = str(
            getattr(self.standalone_dotnet_experiment_package, "package_dir", "") or ""
        )
        if bool(getattr(controller, "serving_prewarm_placeholder", False)):
            self._record_mesh_dotnet_event(
                "mesh_dotnet_resident_reuse_declined",
                reason="prewarm_placeholder_resident",
                cached_package_dir=cached_package_dir,
            )
            return False
        applied_package_dir = str(getattr(controller, "applied_package_path", "") or "")
        # The shared controller is the package authority. If it cannot name the
        # applied package, a raw helper activation would reveal an uncorrelated
        # scene (including the prewarm placeholder), so resident reuse declines.
        if not applied_package_dir or applied_package_dir != cached_package_dir:
            self._record_mesh_dotnet_event(
                "mesh_dotnet_resident_reuse_declined",
                reason=(
                    "resident_package_unknown"
                    if not applied_package_dir
                    else "resident_package_differs"
                ),
                cached_package_dir=cached_package_dir,
                applied_package_dir=applied_package_dir,
            )
            return False
        return True

    def _start_dotnet_editor_requested(self, controller: _tab.MeshEditorController, *, embedded: bool) -> None:
        del embedded
        self._start_rust_editor_requested(controller)

    def _start_standalone_dotnet_package_worker(
        self,
        controller: _tab.MeshEditorController,
        *,
        embedded: bool,
        executable: Path,
    ) -> None:
        """Compatibility entry for canonical Rust editor preparation."""
        del embedded, executable
        self._start_rust_editor_requested(controller)

    def _dotnet_reference_mesh_for_package(
        self,
        controller: _tab.MeshEditorController,
        *,
        embedded: bool,
    ) -> _tab.ParsedMesh | None:
        if embedded:
            getter = getattr(self.active_builder(), "_mesh_editor_embedded_reference_mesh", None)
            if callable(getter):
                try:
                    reference = getter()
                    return reference if isinstance(reference, _tab.ParsedMesh) else None
                except Exception:
                    return None
            return None
        try:
            return controller.base_mesh(clone=False)
        except (AttributeError, KeyError, RuntimeError, TypeError, ValueError):
            return None

    def _dotnet_reference_material_source_for_package(self, *, embedded: bool) -> object | None:
        if not embedded:
            return None
        getter = getattr(
            self.active_builder(),
            "_mesh_editor_embedded_reference_material_model",
            None,
        )
        if not callable(getter):
            return None
        try:
            return getter()
        except Exception:
            return None

    def _dotnet_editable_material_source_for_package(self, *, embedded: bool) -> object | None:
        if embedded:
            return None
        captured = self.standalone_archive_material_preview_model
        if self._archive_material_preview_model_ready(captured):
            return captured
        provider = self.get_archive_material_preview_model
        if not callable(provider):
            return None
        try:
            provided = provider()
            return provided if self._archive_material_preview_model_ready(provided) else None
        except Exception:
            return None

    def _dotnet_mirror_reference_materials_to_editable_for_package(self, *, embedded: bool) -> bool:
        if not embedded:
            return False
        builder = self.active_builder()
        getter = getattr(
            builder,
            "_mesh_editor_embedded_mirror_reference_materials_to_editable",
            None,
        )
        if not callable(getter):
            getter = getattr(
                builder,
                "_mesh_editor_embedded_defer_reference_material_synthesis",
                None,
            )
        if not callable(getter):
            return False
        try:
            return bool(getter())
        except (AttributeError, RuntimeError, TypeError, ValueError):
            return False

    def _dotnet_reference_native_package_for_package(self, *, embedded: bool) -> Path | None:
        if not embedded:
            value = str(getattr(self, "character_context_native_package_path", "") or "").strip()
            return Path(value) if value else None
        getter = getattr(
            self.active_builder(),
            "_mesh_editor_embedded_reference_native_package",
            None,
        )
        if not callable(getter):
            return None
        try:
            value = str(getter() or "").strip()
            return Path(value) if value else None
        except (OSError, TypeError, ValueError):
            return None

    def _dotnet_initial_scene_modes(self, *, embedded: bool) -> tuple[str, str]:
        """The modes to publish, falling back to the last authoritative pair.

        Both modes are read out of live builder widgets. A read that fails has
        learned nothing about what mode the reader is in, so it must not answer
        with one: these values are published as an authoritative scene frame,
        and a frame naming ``placement`` while the reader is inside Edit Mesh is
        a real transition on the helper's side. It runs the full interaction-mode
        pass, which returns the placement sections to the flanks, un-collapses
        both splitters and reveals the placement panels -- and the next correct
        frame puts the rail back. That is the placement side panel appearing
        behind the tool dock, and the literal ``placement`` written here on any
        transient read failure is what could manufacture it out of nothing.

        The last published mode is the only honest answer to "I could not read
        it": it says the mode has not changed, which is what an exception here
        actually means.
        """

        if not embedded:
            comparison = {"source": "original_only", "ghost": "overlay"}.get(
                str(self.standalone_compare_mode or "edited"),
                "replacement_only",
            )
            return comparison, "mesh_edit"
        builder = self.active_builder()
        comparison_getter = getattr(builder, "_mesh_editor_embedded_comparison_mode", None)
        interaction_getter = getattr(builder, "_mesh_editor_embedded_interaction_mode", None)
        # getattr: this mixin is composed into hosts that do not run the tab's
        # runtime initialiser, and the retained mode is a fallback path, so it
        # must not be the thing that raises.
        desired = getattr(self, "standalone_dotnet_scene_desired", None) or {}
        try:
            comparison = str(
                comparison_getter() if callable(comparison_getter) else "side_by_side"
            )
        except Exception as exc:
            comparison = str(desired.get("comparison_mode", "side_by_side"))
            self._record_mesh_dotnet_event(
                "mesh_dotnet_comparison_mode_read_failed",
                error=str(exc),
                retained_mode=comparison,
            )
        try:
            interaction = str(
                interaction_getter() if callable(interaction_getter) else "placement"
            )
        except Exception as exc:
            interaction = str(desired.get("interaction_mode", "placement"))
            self._record_mesh_dotnet_event(
                "mesh_dotnet_interaction_mode_read_failed",
                error=str(exc),
                retained_mode=interaction,
            )
        return comparison, interaction

    def _dotnet_current_placement_state(self, *, embedded: bool) -> Mapping[str, object] | None:
        if not embedded:
            return None
        getter = getattr(self.active_builder(), "_mesh_editor_embedded_placement_state", None)
        if not callable(getter):
            return None
        try:
            value = getter()
        except Exception:
            return None
        return value if isinstance(value, Mapping) else None
    def _dotnet_current_scene_transform(self, *, embedded: bool) -> object | None:
        if not embedded:
            return None
        getter = getattr(self.active_builder(), "_mesh_editor_embedded_scene_transform", None)
        if not callable(getter):
            return None
        try:
            return getter()
        except Exception:
            return None
    def _cancel_standalone_dotnet_package_worker(self) -> None:
        worker = self.standalone_dotnet_package_worker
        thread = self.standalone_dotnet_package_thread
        if worker is None and thread is None:
            return
        self.standalone_dotnet_package_request_id += 1
        if worker is not None:
            try:
                worker.stop()
            except RuntimeError:
                pass
        if thread is not None:
            try:
                thread.requestInterruption()
                thread.quit()
            except RuntimeError:
                pass
    def _finalize_embedded_dotnet_import(self, reason: str) -> bool:
        builder = self.active_builder()
        finalize = getattr(builder, "_mesh_editor_embedded_finalize_dotnet_import", None) if builder is not None else None
        if not callable(finalize):
            self.status_message_requested.emit(
                "Resident mesh edit finalization failed.",
                True,
            )
            return False
        try:
            return bool(finalize(str(reason or "dotnet_import")))
        except Exception as exc:
            self.status_message_requested.emit(f"Rust Mesh Editor embedded preview finalize failed: {exc}", True)
            return False
    def _complete_embedded_dotnet_exit(self, reason: str, *, final_state: str = "closed") -> bool:
        if not self.standalone_dotnet_target_embedded:
            return False
        if self.standalone_dotnet_embedded_exit_finalized:
            return True
        if not self._finalize_embedded_dotnet_import(str(reason or "dotnet_exit")):
            self._set_embedded_dotnet_state("failed", active=False)
            self._notify_embedded_dotnet_launch_failed("mesh_edit_dotnet_save_failed")
            return False
        self.standalone_dotnet_embedded_exit_finalized = True
        self.standalone_dotnet_exit_pending = False
        self.standalone_dotnet_deactivate_acknowledged = False
        self.standalone_dotnet_deactivate_timer.stop()
        self._set_embedded_dotnet_state(final_state, active=False)
        self._refresh_embedded_workspace_from_builder()
        return True
    def _complete_pending_dotnet_exit(self) -> None:
        if not self.standalone_dotnet_exit_pending or not self.standalone_dotnet_deactivate_acknowledged:
            return
        if self._standalone_action_worker_active():
            return
        self._complete_embedded_dotnet_exit("dotnet_deactivated", final_state="suspended")
    def _dotnet_target_controller(self) -> _tab.MeshEditorController | None:
        controller = self.standalone_dotnet_target_controller or self.standalone_controller
        if controller is not None and controller.mesh_service.settings is None:
            controller.mesh_service.settings = self.settings
        return controller
    def _notify_embedded_dotnet_ready(self) -> None:
        builder = self.active_builder()
        callback = getattr(builder, "_mesh_editor_embedded_dotnet_ready", None) if builder is not None else None
        if callable(callback):
            try:
                callback()
            except Exception as exc:
                self._record_mesh_dotnet_event("mesh_dotnet_ready_callback_error", error=str(exc))
    def _notify_embedded_dotnet_launch_failed(self, reason: str, *, diagnostics: str = "") -> None:
        if self.standalone_dotnet_target_embedded:
            self._set_embedded_dotnet_state("failed", active=False)
        builder = self.active_builder()
        callback = getattr(builder, "_mesh_editor_embedded_dotnet_failed", None) if builder is not None else None
        if callable(callback):
            try:
                callback(str(reason or "mesh_edit_dotnet_failed"), str(diagnostics or ""))
                return
            except Exception as exc:
                self._record_mesh_dotnet_event("mesh_dotnet_failed_callback_error", reason=reason, error=str(exc))
