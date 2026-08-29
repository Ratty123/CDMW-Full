"""Revision-bound derived-panel lifecycle for standalone and embedded Mesh Editor."""

from __future__ import annotations

from cdmw.domain.mesh.panel_state import (
    MeshPanelKind,
    MeshPanelSnapshot,
    MeshPanelStatus,
    MeshPanelUnavailableError,
)
from cdmw.services.active_ui_translation import translate_active_ui_text
from cdmw.ui.mesh_editor.tab_compat import facade_globals as _tab


def _expected_panel_unavailability_message(error: MeshPanelUnavailableError) -> str:
    if error.code == "native_workspace_snapshot_unavailable":
        return translate_active_ui_text(
            "native mesh editor workspace summary failed; Python mesh state is stale"
        )
    if error.code == "native_uv_snapshot_unavailable":
        return translate_active_ui_text(
            "native mesh editor UV summary unavailable; Python mesh state is stale"
        )
    if error.code == "native_skeleton_snapshot_unavailable":
        return translate_active_ui_text(
            "native mesh editor skeleton summary unavailable; Python mesh state is stale"
        )
    if error.code == "native_compare_snapshot_unavailable":
        return translate_active_ui_text(
            "native mesh editor compare summary unavailable; Python mesh state is stale"
        )
    if error.code.endswith("_provider_unavailable"):
        return translate_active_ui_text("unavailable")
    return str(error)


class MeshEditorPanelStateMixin:
    def _reset_standalone_panel_snapshots(self) -> None:
        panel_resets = (
            ("standalone_workspace_panel_state", "update_workspace_panel_state"),
            ("standalone_uv_panel_state", "update_uv_panel_state"),
            ("standalone_skeleton_panel_state", "update_skeleton_panel_state"),
            ("standalone_compare_panel_state", "update_compare_panel_state"),
            ("standalone_validation_panel_state", "update_export_validation_state"),
            ("standalone_rebuild_panel_state", "update_rebuild_report_state"),
        )
        for state_name, updater_name in panel_resets:
            state = MeshPanelSnapshot.unavailable()
            setattr(self, state_name, state)
            updater = getattr(self.standalone_workspace, updater_name, None)
            if callable(updater):
                updater(state)

    def _refresh_standalone_export_validation(self, view: _tab.MeshEditSessionView | None) -> None:
        state = self._standalone_panel_state("standalone_validation_panel_state")
        controller = self.standalone_controller
        if view is None or controller is None or controller.active_session_id != view.session_id:
            self.standalone_last_export_validation_report = None
            self.standalone_export_validation_revision = None
            self._publish_standalone_panel_state(
                "standalone_validation_panel_state",
                "update_export_validation_state",
                "update_export_validation",
                state.mark_unavailable(),
            )
            return
        revision = int(getattr(view, "revision", -1))
        session_id = str(view.session_id)
        report = self.standalone_last_export_validation_report
        legacy_revision = self.standalone_export_validation_revision
        if report is not None and legacy_revision is not None and state.value is not report:
            state = state.begin_refresh(
                session_id=session_id,
                revision=int(legacy_revision),
            ).publish_ready(report)
        if report is not None and self.standalone_export_validation_revision == revision:
            if not state.is_current(session_id=session_id, revision=revision) or state.value is not report:
                state = state.begin_refresh(session_id=session_id, revision=revision).publish_ready(report)
            self._publish_standalone_panel_state(
                "standalone_validation_panel_state",
                "update_export_validation_state",
                "update_export_validation",
                state,
            )
            return
        if state.session_id != session_id or state.revision != revision or state.status is MeshPanelStatus.READY:
            state = state.mark_unavailable(
                session_id=session_id,
                revision=revision,
                message="Run validation",
            )
        self._publish_standalone_panel_state(
            "standalone_validation_panel_state",
            "update_export_validation_state",
            "update_export_validation",
            state,
        )

    def _refresh_standalone_rebuild_report(self, view: _tab.MeshEditSessionView | None) -> None:
        state = self._standalone_panel_state("standalone_rebuild_panel_state")
        controller = self.standalone_controller
        if view is None or (controller is not None and controller.active_session_id != view.session_id):
            self.standalone_last_rebuild_report = None
            self.standalone_rebuild_report_revision = None
            self._publish_standalone_panel_state(
                "standalone_rebuild_panel_state",
                "update_rebuild_report_state",
                "update_rebuild_report",
                state.mark_unavailable(),
            )
            return
        revision = int(getattr(view, "revision", -1))
        session_id = str(view.session_id)
        report = self.standalone_last_rebuild_report
        legacy_revision = self.standalone_rebuild_report_revision
        # Minimal compatibility hosts sometimes stamp an opaque sentinel instead
        # of a rebuild report. Preserve it without asking the real renderer to
        # present fields that do not exist.
        legacy_report_is_renderable = report is None or hasattr(report, "validation_status")
        if report is not None and legacy_revision == revision and not legacy_report_is_renderable:
            return
        if report is not None and legacy_revision is not None and state.value is not report and legacy_report_is_renderable:
            state = state.begin_refresh(
                session_id=session_id,
                revision=int(legacy_revision),
            ).publish_ready(report)
        if report is not None and self.standalone_rebuild_report_revision == revision:
            if not state.is_current(session_id=session_id, revision=revision) or state.value is not report:
                state = state.begin_refresh(session_id=session_id, revision=revision).publish_ready(report)
            self._publish_standalone_panel_state(
                "standalone_rebuild_panel_state",
                "update_rebuild_report_state",
                "update_rebuild_report",
                state,
            )
            return
        if state.session_id != session_id or state.revision != revision or state.status is MeshPanelStatus.READY:
            state = state.mark_unavailable(
                session_id=session_id,
                revision=revision,
                message="Run rebuild report",
            )
        self._publish_standalone_panel_state(
            "standalone_rebuild_panel_state",
            "update_rebuild_report_state",
            "update_rebuild_report",
            state,
        )

    def _refresh_standalone_workspace_summary(self, view: _tab.MeshEditSessionView | None) -> None:
        self._refresh_standalone_summary_panel(
            view,
            panel_name=MeshPanelKind.WORKSPACE,
            state_name="standalone_workspace_panel_state",
            state_updater_name="update_workspace_panel_state",
            legacy_updater_name="update_workspace_summary",
            provider_name="workspace_summary",
        )

    def _refresh_standalone_uv_summary(self, view: _tab.MeshEditSessionView | None) -> None:
        self._refresh_standalone_summary_panel(
            view,
            panel_name=MeshPanelKind.UV,
            state_name="standalone_uv_panel_state",
            state_updater_name="update_uv_panel_state",
            legacy_updater_name="update_uv_summary",
            provider_name="uv_summary",
        )

    def _refresh_standalone_skeleton_summary(self, view: _tab.MeshEditSessionView | None) -> None:
        self._refresh_standalone_summary_panel(
            view,
            panel_name=MeshPanelKind.SKELETON,
            state_name="standalone_skeleton_panel_state",
            state_updater_name="update_skeleton_panel_state",
            legacy_updater_name="update_skeleton_summary",
            provider_name="skeleton_summary",
        )

    def _refresh_standalone_compare_summary(self, view: _tab.MeshEditSessionView | None) -> None:
        self._refresh_standalone_summary_panel(
            view,
            panel_name=MeshPanelKind.COMPARE,
            state_name="standalone_compare_panel_state",
            state_updater_name="update_compare_panel_state",
            legacy_updater_name="update_compare_summary",
            provider_name="compare_summary",
        )

    def _standalone_panel_state(self, state_name: str) -> MeshPanelSnapshot[object]:
        state = getattr(self, state_name, None)
        return state if isinstance(state, MeshPanelSnapshot) else MeshPanelSnapshot.unavailable()

    def _publish_standalone_panel_state(
        self,
        state_name: str,
        state_updater_name: str,
        legacy_updater_name: str,
        state: MeshPanelSnapshot[object],
    ) -> None:
        setattr(self, state_name, state)
        updater = getattr(self.standalone_workspace, state_updater_name, None)
        if callable(updater):
            updater(state)
            return
        legacy_updater = getattr(self.standalone_workspace, legacy_updater_name, None)
        if callable(legacy_updater):
            legacy_updater(state.value)

    def _refresh_standalone_summary_panel(
        self,
        view: _tab.MeshEditSessionView | None,
        *,
        panel_name: MeshPanelKind,
        state_name: str,
        state_updater_name: str,
        legacy_updater_name: str,
        provider_name: str,
    ) -> None:
        state = self._standalone_panel_state(state_name)
        controller = self.standalone_controller
        if view is None or controller is None or controller.active_session_id != view.session_id:
            self._publish_standalone_panel_state(
                state_name,
                state_updater_name,
                legacy_updater_name,
                state.mark_unavailable(),
            )
            return
        session_id = str(view.session_id)
        revision = int(getattr(view, "revision", -1))
        pending = state.begin_refresh(session_id=session_id, revision=revision)
        self._publish_standalone_panel_state(
            state_name,
            state_updater_name,
            legacy_updater_name,
            pending,
        )
        provider = getattr(controller, provider_name, None)
        if not callable(provider):
            failed = pending.publish_error(
                error_code=f"{panel_name.value}_provider_unavailable",
                message=translate_active_ui_text("unavailable"),
                unavailable=True,
            )
            self._publish_standalone_panel_state(
                state_name,
                state_updater_name,
                legacy_updater_name,
                failed,
            )
            return
        try:
            value = provider()
            if value is None:
                raise RuntimeError(
                    translate_active_ui_text("Derived panel provider returned no value.")
                )
        except MeshPanelUnavailableError as exc:
            failed = pending.publish_error(
                error_code=exc.code,
                message=_expected_panel_unavailability_message(exc),
                unavailable=True,
            )
            if self._standalone_panel_state(state_name).matches_request(
                session_id=session_id,
                revision=revision,
                generation=pending.generation,
            ):
                self._publish_standalone_panel_state(
                    state_name,
                    state_updater_name,
                    legacy_updater_name,
                    failed,
                )
            return
        except Exception as exc:
            failed = pending.publish_error(
                error_code=f"unexpected_{panel_name.value}_summary_failure",
                message=str(exc) or type(exc).__name__,
            )
            if self._standalone_panel_state(state_name).matches_request(
                session_id=session_id,
                revision=revision,
                generation=pending.generation,
            ):
                self._publish_standalone_panel_state(
                    state_name,
                    state_updater_name,
                    legacy_updater_name,
                    failed,
                )
                recorder = getattr(self, "_record_mesh_dotnet_event", None)
                if callable(recorder):
                    recorder(
                        "mesh_derived_panel_refresh_failed",
                        panel=panel_name.value,
                        session_id=session_id,
                        revision=revision,
                        generation=pending.generation,
                        exception_type=type(exc).__name__,
                        message=str(exc),
                    )
            return
        current = self._standalone_panel_state(state_name)
        if not current.matches_request(
            session_id=session_id,
            revision=revision,
            generation=pending.generation,
        ):
            return
        self._publish_standalone_panel_state(
            state_name,
            state_updater_name,
            legacy_updater_name,
            pending.publish_ready(value),
        )

    def _defer_standalone_summary_panel(
        self,
        view: _tab.MeshEditSessionView | None,
        *,
        state_name: str,
        state_updater_name: str,
        legacy_updater_name: str,
    ) -> None:
        state = self._standalone_panel_state(state_name)
        controller = self.standalone_controller
        if view is None or controller is None or controller.active_session_id != view.session_id:
            deferred = state.mark_unavailable()
        else:
            session_id = str(view.session_id)
            revision = int(view.revision)
            if state.session_id == session_id and state.revision == revision:
                deferred = state
            else:
                deferred = state.begin_refresh(session_id=session_id, revision=revision)
        self._publish_standalone_panel_state(
            state_name,
            state_updater_name,
            legacy_updater_name,
            deferred,
        )

    def _refresh_embedded_workspace_from_builder(
        self,
        *,
        include_derived: bool = True,
        session_view: _tab.MeshEditSessionView | None = None,
    ) -> None:
        workspace = self.embedded_workspace
        if workspace is None:
            return
        controller = self._embedded_builder_controller()
        view = session_view
        if controller is not None and view is None:
            try:
                view = controller.session_view()
            except (AttributeError, RuntimeError, TypeError, ValueError):
                view = None
        if controller is None or view is None:
            if hasattr(workspace, "status_label"):
                workspace.status_label.setText("No active edit session.")
            workspace.update_session_summary(None)
            for state_name, state_updater_name, legacy_updater_name in (
                ("_workspace_panel_state", "update_workspace_panel_state", "update_workspace_summary"),
                ("_uv_panel_state", "update_uv_panel_state", "update_uv_summary"),
                ("_skeleton_panel_state", "update_skeleton_panel_state", "update_skeleton_summary"),
                ("_compare_panel_state", "update_compare_panel_state", "update_compare_summary"),
                ("_export_validation_panel_state", "update_export_validation_state", "update_export_validation"),
                ("_rebuild_panel_state", "update_rebuild_report_state", "update_rebuild_report"),
            ):
                state = getattr(workspace, state_name, MeshPanelSnapshot.unavailable())
                if not isinstance(state, MeshPanelSnapshot):
                    state = MeshPanelSnapshot.unavailable()
                self._publish_workspace_panel_state(
                    workspace,
                    state_name,
                    state_updater_name,
                    legacy_updater_name,
                    state.mark_unavailable(),
                )
            workspace.update_action_state(has_target=False)
            return
        native_editor_available = self._native_mesh_editor_available()
        if hasattr(workspace, "status_label"):
            if native_editor_available:
                workspace.status_label.setText(
                    f"Mesh editing ready | Mode: {str(view.mode or 'edit').title()} | "
                    f"Revision {view.revision} | Undo {view.undo_count} | Redo {view.redo_count}"
                )
            else:
                workspace.status_label.setText("Native Mesh Editor unavailable: C++ mesh core missing.")
        workspace.update_session_summary(view, mesh_label=self._entry_label(self._current_target_entry()))
        if not include_derived:
            update_selection = getattr(workspace, "update_workspace_selection", None)
            if callable(update_selection):
                update_selection(view.selection)
        if include_derived:
            for panel_name, method_name, state_name, state_updater_name, legacy_updater_name in (
                (MeshPanelKind.WORKSPACE, "workspace_summary", "_workspace_panel_state", "update_workspace_panel_state", "update_workspace_summary"),
                (MeshPanelKind.UV, "uv_summary", "_uv_panel_state", "update_uv_panel_state", "update_uv_summary"),
                (MeshPanelKind.SKELETON, "skeleton_summary", "_skeleton_panel_state", "update_skeleton_panel_state", "update_skeleton_summary"),
                (MeshPanelKind.COMPARE, "compare_summary", "_compare_panel_state", "update_compare_panel_state", "update_compare_summary"),
                (MeshPanelKind.VALIDATION, "export_validation_report", "_export_validation_panel_state", "update_export_validation_state", "update_export_validation"),
            ):
                self._refresh_embedded_summary_panel(
                    workspace,
                    controller,
                    view,
                    panel_name=panel_name,
                    provider_name=method_name,
                    state_name=state_name,
                    state_updater_name=state_updater_name,
                    legacy_updater_name=legacy_updater_name,
                )
            rebuild_state = getattr(workspace, "_rebuild_panel_state", MeshPanelSnapshot.unavailable())
            if not isinstance(rebuild_state, MeshPanelSnapshot):
                rebuild_state = MeshPanelSnapshot.unavailable()
            self._publish_workspace_panel_state(
                workspace,
                "_rebuild_panel_state",
                "update_rebuild_report_state",
                "update_rebuild_report",
                rebuild_state.mark_unavailable(
                    session_id=str(view.session_id),
                    revision=int(view.revision),
                    message="Run rebuild report",
                ),
            )
        workspace.update_action_state(
            has_target=True,
            selection_empty=bool(view.selection.is_empty()),
            mode=str(view.mode or "edit"),
            active_selection_mode=str(getattr(controller, "active_selection_mode", "") or self.current_selection_mode or "brush"),
            undo_count=int(view.undo_count or 0),
            redo_count=int(view.redo_count or 0),
            native_editor_available=native_editor_available,
        )
        builder = self.active_builder()
        selection_changed = getattr(builder, "_mesh_editor_embedded_apply_part_selection_from_viewport", None)
        if callable(selection_changed):
            selection_changed(tuple(view.selection.source_indices))

    @staticmethod
    def _publish_workspace_panel_state(
        workspace: object,
        state_name: str,
        state_updater_name: str,
        legacy_updater_name: str,
        state: MeshPanelSnapshot[object],
    ) -> None:
        setattr(workspace, state_name, state)
        updater = getattr(workspace, state_updater_name, None)
        if callable(updater):
            updater(state)
            return
        legacy_updater = getattr(workspace, legacy_updater_name, None)
        if callable(legacy_updater):
            legacy_updater(state.value)

    def _refresh_embedded_summary_panel(
        self,
        workspace: object,
        controller: object,
        view: _tab.MeshEditSessionView,
        *,
        panel_name: MeshPanelKind,
        provider_name: str,
        state_name: str,
        state_updater_name: str,
        legacy_updater_name: str,
    ) -> None:
        state = getattr(workspace, state_name, MeshPanelSnapshot.unavailable())
        if not isinstance(state, MeshPanelSnapshot):
            state = MeshPanelSnapshot.unavailable()
        session_id = str(view.session_id)
        revision = int(view.revision)
        pending = state.begin_refresh(session_id=session_id, revision=revision)
        self._publish_workspace_panel_state(
            workspace,
            state_name,
            state_updater_name,
            legacy_updater_name,
            pending,
        )
        provider = getattr(controller, provider_name, None)
        try:
            if not callable(provider):
                raise MeshPanelUnavailableError(
                    f"{panel_name.value}_provider_unavailable",
                    translate_active_ui_text("unavailable"),
                )
            value = provider()
            if value is None:
                raise RuntimeError(
                    translate_active_ui_text("Derived panel provider returned no value.")
                )
        except MeshPanelUnavailableError as exc:
            resolved = pending.publish_error(
                error_code=exc.code,
                message=_expected_panel_unavailability_message(exc),
                unavailable=True,
            )
        except Exception as exc:
            resolved = pending.publish_error(
                error_code=f"unexpected_{panel_name.value}_summary_failure",
                message=str(exc) or type(exc).__name__,
            )
            recorder = getattr(self, "_record_mesh_dotnet_event", None)
            if callable(recorder):
                recorder(
                    "mesh_derived_panel_refresh_failed",
                    panel=panel_name.value,
                    session_id=session_id,
                    revision=revision,
                    generation=pending.generation,
                    exception_type=type(exc).__name__,
                    message=str(exc),
                )
        else:
            resolved = pending.publish_ready(value)
        current = getattr(workspace, state_name, None)
        if isinstance(current, MeshPanelSnapshot) and current.matches_request(
            session_id=session_id,
            revision=revision,
            generation=pending.generation,
        ):
            self._publish_workspace_panel_state(
                workspace,
                state_name,
                state_updater_name,
                legacy_updater_name,
                resolved,
            )
