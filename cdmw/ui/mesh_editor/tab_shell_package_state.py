"""Material state across a shared package swap.

Split out of :mod:`tab_shell` to keep that module inside the owned-file line
cap. A package swap invalidates the material state that was compiled against
the previous one, so it is torn down, the generation it belonged to is
recorded, and publishing resumes only once the new package has landed.
Resuming too early republishes against a package the renderer has dropped.
"""

from __future__ import annotations

import time
from typing import Mapping, Optional

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QApplication, QFrame, QGridLayout, QHBoxLayout, QLabel,
    QPushButton, QTabWidget, QVBoxLayout, QWidget,
)

from cdmw.ui.archive_browser.static_replacement_viewport_display_modes import (
    MESH_PREVIEW_TEXTURED_DISPLAY_MODES,
    normalize_mesh_preview_display_mode,
    untextured_fallback_display_mode,
)
from cdmw.ui.shell.settings_bridge import read_bool_setting
from cdmw.ui.mesh_editor.dotnet_update_queue import DotNetRevisionUpdateQueue
from cdmw.ui.mesh_editor.resident_texture_update_queue import ResidentTextureRegionUpdateQueue
from cdmw.ui.mesh_editor.workspace import MeshEditorWorkspace
from cdmw.ui.mesh_editor import tab_dotnet_material_commit as _material_commit

from cdmw.ui.mesh_editor.tab_compat import facade_globals as _tab
from cdmw.ui.mesh_editor.tab_shell_native_state import MeshEditorTabShellNativeStateMixin
from cdmw.ui.mesh_editor.tab_support import (
    STANDALONE_NATIVE_TOOL_STATE as _STANDALONE_NATIVE_TOOL_STATE,
    _mesh_editor_tab_index,
)
from cdmw.ui.mesh_editor.tab_shell_runtime import MeshEditorTabShellRuntimeMixin

#: Marks naming the tab an object's signals are already connected to.
_SHARED_DOTNET_WIRED_MARK = "_mesh_editor_shared_dotnet_wired_to"
_NATIVE_PART_EVENTS_WIRED_MARK = "_mesh_editor_native_part_events_wired_to"


def _already_wired_to(target: object, mark: str, owner: object) -> bool:
    """True when `owner` has already connected its handlers to `target`.

    The mark lives on the object, so it dies with it. A set of `id()` values
    does not: every builder swap brings a new host and a new controller and
    leaves the old addresses behind, and CPython hands those addresses straight
    back to later allocations of the same size. The tab would then take a live
    object for one it had already wired and connect nothing to it, which is
    silent -- the preview appears and then reports nothing, or a part click and
    a brush stroke go nowhere.
    """

    return getattr(target, mark, None) == id(owner)


def _mark_wired_to(target: object, mark: str, owner: object) -> None:
    try:
        setattr(target, mark, id(owner))
    except (AttributeError, RuntimeError):
        # A target that cannot hold the mark is simply wired again next time,
        # which the connect calls themselves already tolerate.
        pass



class MeshEditorTabShellPackageStateMixin(MeshEditorTabShellNativeStateMixin):
    def _handle_shared_dotnet_package_applied(
        self,
        controller: object,
        package_path: str,
        generation: int,
    ) -> None:
        del package_path
        if controller is not self._active_shared_dotnet_controller():
            return
        token = (
            int(getattr(controller, "process_generation", 0) or 0),
            int(generation or 0),
        )
        self._invalidate_dotnet_material_state_for_package(controller, generation)
        if token == self.standalone_dotnet_material_ready_flush_token:
            return
        self.standalone_dotnet_material_ready_flush_token = token
        QTimer.singleShot(
            0,
            lambda expected=token: self._resume_dotnet_material_state_after_package(
                expected
            ),
        )

    def _dotnet_material_package_generation(self) -> int:
        """Return the accepted resident package generation material edits target."""

        controller = self._active_shared_dotnet_controller()
        try:
            applied_generation = int(
                getattr(controller, "applied_package_generation", 0) or 0
            )
        except (TypeError, ValueError, OverflowError):
            applied_generation = 0
        if applied_generation > 0:
            return applied_generation
        try:
            return max(0, int(self.standalone_dotnet_material_package_token[1]))
        except (AttributeError, IndexError, TypeError, ValueError, OverflowError):
            return 0

    def _invalidate_dotnet_material_state_for_package(
        self,
        controller: object,
        generation: int,
    ) -> bool:
        """Forget material bindings replaced by an accepted resident package."""

        if controller is not self._active_shared_dotnet_controller():
            return False
        token = (
            int(getattr(controller, "process_generation", 0) or 0),
            int(generation or 0),
        )
        if token[1] <= 0 or token == self.standalone_dotnet_material_package_token:
            return False
        self.standalone_dotnet_material_package_token = token

        desired_display = self.standalone_dotnet_presentation_desired.get("display")
        desired_mode = normalize_mesh_preview_display_mode(
            desired_display.get("mode", "untextured_faces")
            if isinstance(desired_display, Mapping)
            else "untextured_faces"
        )
        requested_mode = ""
        use_presentation_state = False
        if bool(self.standalone_dotnet_pending_textured_view):
            requested_mode = normalize_mesh_preview_display_mode(
                self.standalone_dotnet_pending_textured_view_mode
            )
            use_presentation_state = bool(
                self.standalone_dotnet_pending_textured_view_uses_presentation
            )
        elif self.standalone_dotnet_deferred_textured_view_mode:
            requested_mode = normalize_mesh_preview_display_mode(
                self.standalone_dotnet_deferred_textured_view_mode
            )
            use_presentation_state = bool(
                self.standalone_dotnet_deferred_textured_view_uses_presentation
            )
        elif desired_mode in MESH_PREVIEW_TEXTURED_DISPLAY_MODES:
            requested_mode = desired_mode

        # A material compile and its acknowledgement describe the package that
        # was resident when they started. Fail any export-owned resource publish
        # before clearing it, stop the worker, and advance completed tombstone
        # generations so neither a late compile nor a late helper ack can mutate
        # the replacement package or make it look textured without publishing
        # again.
        staged_resources = self.standalone_dotnet_sent_material_resource_payload
        if isinstance(staged_resources, Mapping):
            _material_commit.finish_sent_material_resources(self, committed=False)
            _material_commit.remember_sent_material_resources(self, None)
            active_worker = self.standalone_dotnet_material_update_worker
            active_request = getattr(active_worker, "request", None)
            if int(getattr(active_request, "generation", 0) or 0) == int(
                staged_resources.get("generation", 0) or 0
            ):
                self.standalone_dotnet_material_update_active_resources = ()
        self._cancel_dotnet_material_compile()
        paired_upgrade = self.standalone_dotnet_pending_paired_material_upgrade
        if isinstance(paired_upgrade, tuple) and len(paired_upgrade) == 3:
            paired_upgrade = paired_upgrade[2]
        if (
            paired_upgrade is not None
            and self.standalone_dotnet_pending_paired_material_model is None
        ):
            self.standalone_dotnet_pending_paired_material_model = paired_upgrade
        self.standalone_dotnet_pending_paired_material_upgrade = None
        boundary_generation = max(
            int(self.standalone_dotnet_material_generation),
            int(self.standalone_dotnet_completed_material_generation),
        ) + 1
        self.standalone_dotnet_material_generation = boundary_generation
        self.standalone_dotnet_completed_material_generation = boundary_generation
        self.standalone_dotnet_applied_material_generation = 0
        self.standalone_dotnet_material_signature = ""
        self.standalone_dotnet_material_role_by_generation.clear()
        self.standalone_dotnet_material_input_signature_by_generation.clear()
        self.standalone_dotnet_material_generation_by_role.clear()
        self.standalone_dotnet_completed_material_generation_by_role.clear()
        self.standalone_dotnet_applied_material_generation_by_role.clear()
        self.standalone_dotnet_texture_resources_ready_by_role.clear()
        self.standalone_dotnet_material_signature_by_role.clear()
        self.standalone_dotnet_material_input_signature_by_role.clear()
        self.standalone_dotnet_material_error_by_role.clear()

        self.standalone_dotnet_material_parameter_timer.stop()
        self.standalone_dotnet_pending_material_parameter_payload = None
        _material_commit.remember_sent_material_parameters(self, None)
        parameter_boundary = max(
            int(self.standalone_dotnet_material_parameter_generation),
            int(self.standalone_dotnet_sent_material_parameter_generation),
            int(self.standalone_dotnet_completed_material_parameter_generation),
        ) + 1
        self.standalone_dotnet_material_parameter_generation = parameter_boundary
        self.standalone_dotnet_sent_material_parameter_generation = 0
        self.standalone_dotnet_applied_material_parameter_generation = 0
        self.standalone_dotnet_completed_material_parameter_generation = (
            parameter_boundary
        )

        if bool(self.standalone_dotnet_pending_textured_view):
            self._finish_pending_textured_view(
                success=False,
                reason="resident_package_replaced",
            )
        elif requested_mode in MESH_PREVIEW_TEXTURED_DISPLAY_MODES:
            self.standalone_dotnet_deferred_textured_view_mode = requested_mode
            self.standalone_dotnet_deferred_textured_view_uses_presentation = (
                use_presentation_state
            )
            fallback_mode = untextured_fallback_display_mode(requested_mode)
            self._remember_dotnet_desired_display_mode(fallback_mode)
            self.sync_viewport_display_combos(fallback_mode)
        return True

    def _resume_dotnet_material_state_after_package(
        self,
        expected_token: tuple[int, int],
    ) -> None:
        if expected_token != self.standalone_dotnet_material_package_token:
            return
        requested_mode = str(
            self.standalone_dotnet_deferred_textured_view_mode or ""
        )
        use_presentation_state = bool(
            self.standalone_dotnet_deferred_textured_view_uses_presentation
        )
        if requested_mode:
            self._handle_embedded_viewport_display_mode(
                requested_mode,
                use_presentation_state=use_presentation_state,
            )
        self._flush_pending_dotnet_reference_material_resources()

    def _handle_shared_dotnet_package_failed(
        self,
        controller: object,
        package_path: str,
        generation: int,
        message: str,
    ) -> None:
        del package_path, generation
        if controller is not self._active_shared_dotnet_controller():
            return
        self._finish_pending_textured_view(
            success=False,
            reason="package_update_failed",
        )
        self._set_dotnet_status(
            f"Mesh Editor package update failed; the resident scene was kept: {message}",
            error=True,
        )
