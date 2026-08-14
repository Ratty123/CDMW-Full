"""Part picking and Edit Mesh state pushed to the resident native host.

Split out of :mod:`tab_shell` to keep that module inside the owned-file line
cap. These belong together because they all push host-side state that the
helper cannot infer: which part events to raise, whether picking is armed,
and what the Edit Mesh session currently is. Picking retries because the
host may not have wired its events yet when the request arrives.
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




class MeshEditorTabShellNativeStateMixin(MeshEditorTabShellRuntimeMixin):
    def _wire_standalone_native_part_events(self, host: object | None) -> None:
        if host is None:
            return
        if _already_wired_to(host, _NATIVE_PART_EVENTS_WIRED_MARK, self):
            return
        wired = False
        for signal_name, handler in (
            ("source_part_selected", self._handle_native_source_part_selected),
            ("source_part_context_requested", self._handle_native_source_part_context_requested),
            ("mesh_edit_stroke_started", self._handle_standalone_native_mesh_edit_stroke_started),
            ("mesh_edit_stroke_previewed", self._handle_standalone_native_mesh_edit_stroke_previewed),
            ("mesh_edit_stroke_finished", self._handle_standalone_native_mesh_edit_stroke_finished),
            ("mesh_edit_stroke_cancelled", self._handle_standalone_native_mesh_edit_stroke_cancelled),
            ("mesh_edit_selection_changed", self._handle_standalone_native_mesh_edit_selection_changed),
            ("native_event_received", self._handle_standalone_native_preview_event),
        ):
            signal = getattr(host, signal_name, None)
            connector = getattr(signal, "connect", None)
            if not callable(connector):
                continue
            try:
                connector(handler)
                wired = True
            except (RuntimeError, TypeError):
                pass
        if wired:
            _mark_wired_to(host, _NATIVE_PART_EVENTS_WIRED_MARK, self)
    def _set_standalone_native_part_picking(self, enabled: bool) -> bool:
        setter = getattr(self.standalone_native_host, "set_source_part_picking", None)
        if not callable(setter):
            self.standalone_native_part_picking_enabled = False
            return False
        try:
            ok = bool(setter(bool(enabled)))
        except RuntimeError:
            self.standalone_native_part_picking_enabled = False
            return False
        self.standalone_native_part_picking_enabled = bool(ok and enabled)
        return ok
    def _request_standalone_native_part_picking(self, enabled: bool, *, retries: int = 0) -> bool:
        self.standalone_native_part_picking_wanted = bool(enabled)
        updater = getattr(self.standalone_workspace, "set_native_part_picking_status", None)
        if not enabled:
            self._set_standalone_native_part_picking(False)
            if callable(updater):
                updater("Part pick: preview off", available=False)
            return False
        ok = self._set_standalone_native_part_picking(True)
        if ok:
            if callable(updater):
                updater("Part pick: ready", available=True)
            return True
        if callable(updater):
            updater("Part pick: unavailable, waiting for .NET/Vortice host", available=False)
        if retries > 0:
            QTimer.singleShot(250, lambda remaining=int(retries) - 1: self._retry_standalone_native_part_picking(remaining))
        return False
    def _retry_standalone_native_part_picking(self, retries: int) -> None:
        if (
            self.standalone_native_part_picking_wanted
            and not self.standalone_native_part_picking_enabled
            and self.has_active_standalone_session()
        ):
            self._request_standalone_native_part_picking(True, retries=max(0, int(retries or 0)))
    def _sync_standalone_native_mesh_edit_state(self, *, force: bool = False) -> bool:
        host = self.standalone_native_host
        setter = getattr(host, "set_mesh_edit_state", None)
        if not callable(setter):
            self.standalone_native_mesh_edit_state_signature = ()
            return False
        tool_state = _STANDALONE_NATIVE_TOOL_STATE.get(str(self.current_tool_action_key or "").strip())
        controller = self.standalone_controller
        if controller is None or tool_state is None or not self._native_mesh_editor_available():
            signature = (False, "orbit", "source", "brush")
            if not force and signature == self.standalone_native_mesh_edit_state_signature:
                return True
            self.standalone_native_mesh_edit_state_signature = signature
            try:
                return bool(
                    setter(
                        enabled=False,
                        tool="orbit",
                        target_mode="source",
                        selection_mode="brush",
                    )
                )
            except (RuntimeError, TypeError):
                return False
        tool, target_mode, mode = tool_state
        try:
            view = controller.session_view()
            source_indices = tuple(int(index) for index in view.selection.source_indices)
            selection_empty = bool(view.selection.is_empty())
        except (AttributeError, RuntimeError, TypeError, ValueError):
            source_indices = ()
            selection_empty = True
        target = "source" if tool == "select" else (
            target_mode if not selection_empty else ("selection" if tool == "move" else "brush")
        )
        signature = (
            True,
            tool,
            target,
            mode,
            str(self.current_selection_mode or "brush"),
            source_indices,
        )
        if not force and signature == self.standalone_native_mesh_edit_state_signature:
            return True
        self.standalone_native_mesh_edit_state_signature = signature
        try:
            return bool(
                setter(
                    enabled=True,
                    scope_mode="selection" if source_indices else "all",
                    source_submesh_indices=source_indices,
                    target_mode=target,
                    tool=tool,
                    radius_pixels=24.0,
                    strength=0.5,
                    falloff="smooth",
                    selection_mode=str(self.current_selection_mode or "brush"),
                    smooth_iterations=3,
                )
            )
        except (RuntimeError, TypeError, ValueError):
            return False
