"""The embedded Mesh Editor as a component a host carries (P4 V2).

The viewport host (``RustMeshEditorHostFrame``) and the protocol driver
(``MeshEditorRustEditorMixin`` and ``MeshEditorRustProcessMixin``) used to be
mixins of ``MeshEditorTab`` and shared every attribute with it. They now live in
one object with state of its own. What it reads from its host is declared in
``HOST_NAMES`` and nothing else; what it owns is ``STATE_NAMES``. The Mesh Editor
tab is its first host; V3 adds Browse Archives as a second.

The mixins keep their modules, so names that tests patch by module path
(``cdmw.ui.mesh_editor.tab_rust_process.QProcess`` and the rest) are looked up
where they always were.
"""

from __future__ import annotations

from PySide6.QtCore import QObject, Signal

from cdmw.ui.mesh_editor.tab_rust_editor import MeshEditorRustEditorMixin
from cdmw.ui.mesh_editor.tab_rust_process import MeshEditorRustProcessMixin

#: Everything the component reads from its host. A test checks the component's
#: code against this list, so a new dependency on the host has to be declared.
HOST_NAMES = (
    "_archive_refit_picker", "_archive_texture_indexes", "_cloth_collision_picker",
    "_current_target_entry", "_hair_context_preparation", "_hair_picker",
    "_start_archive_material_context_resolution", "archive_material_context_package_path",
    "archive_material_context_verified_for_rust", "archive_physics_profile_context",
    "archive_session_retry_request", "close_standalone_session", "current_archive_selection",
    "edit_item_set", "font", "hair_entry_status", "item_set_contexts",
    "mesh_editor_backend_reason_label", "open_archive_session", "open_mesh_file_session_async",
    "open_selected_mesh_button", "settings", "standalone_archive_material_preview_model",
    "standalone_controller", "standalone_file_retry_request", "standalone_native_host_frame",
    "standalone_status_label", "status_message_requested", "switch_item_piece_requested",
    "theme_key", "update_editor_session_state", "window",
)

#: The state the component owns (everything its code assigns).
STATE_NAMES = (
    "_archive_refit_picker_active", "_hair_entry_generation", "_pending_hair_start",
    "_rust_last_crash_at",
    "_rust_follows_keymap", "_rust_keymap_echo", "_shared_preview_settings_connected",
    "_engine_window_refused_session",
    "mesh_editor_backend",
    "standalone_export_validation_revision", "standalone_last_export_validation_report",
    "standalone_rust_active_event", "standalone_rust_authoring_session",
    "standalone_rust_checked_executable", "standalone_rust_checked_executable_signature",
    "standalone_rust_child_hwnd", "standalone_rust_close_session_pending", "standalone_rust_closing",
    "standalone_rust_dispose_active_root", "standalone_rust_dispose_active_session",
    "standalone_rust_dispose_pending", "standalone_rust_dispose_queue", "standalone_rust_dispose_thread",
    "standalone_rust_dispose_worker", "standalone_rust_executable_path", "standalone_rust_failure_reported",
    "standalone_rust_finish_accepted", "standalone_rust_finish_timer", "standalone_rust_gpu_failed",
    "standalone_rust_hello_received", "standalone_rust_host_request_id", "standalone_rust_incompatible_reason",
    "standalone_rust_last_client_request_id", "standalone_rust_launch_executable_signature",
    "standalone_rust_launch_parent_hwnd", "standalone_rust_material_wait_controller",
    "standalone_rust_material_wait_session_id", "standalone_rust_owned_root",
    "standalone_rust_prepare_active_request_id", "standalone_rust_prepare_controller",
    "standalone_rust_prepare_process_generation", "standalone_rust_prepare_request_id",
    "standalone_rust_parked",
    "standalone_rust_unpark_requested",
    "standalone_rust_prepare_service", "standalone_rust_prepare_session_id", "standalone_rust_prepare_thread",
    "standalone_rust_prepare_worker", "standalone_rust_process", "standalone_rust_process_error_reported",
    "standalone_rust_process_generation", "standalone_rust_protocol_events", "standalone_rust_protocol_queue",
    "standalone_rust_protocol_request_id", "standalone_rust_protocol_status", "standalone_rust_protocol_thread",
    "standalone_rust_protocol_worker", "standalone_rust_ready", "standalone_rust_ready_timer",
    "standalone_rust_relaunch_request", "standalone_rust_session_root", "standalone_rust_stale_sessions_swept",
    "standalone_rust_stderr_diagnostic", "standalone_rust_stderr_in_backtrace", "standalone_rust_stderr_partial",
    "standalone_rust_stderr_tail", "standalone_rust_stdout_buffer", "standalone_rust_stop_after_protocol",
    "standalone_rust_target_controller", "standalone_rust_terminal_close_pending",
    "standalone_rust_texture_unavailable_reason", "standalone_rust_theme_digest",
    "standalone_rust_translation_parts_supported",
)


class LiveEditComponent(MeshEditorRustEditorMixin, QObject):
    """One embedded editor: its helper process, its protocol and its viewport host.

    Public surface for a host: ``open(controller)``, ``close_edit(reason)``,
    ``is_ready``, ``is_busy``, ``finish_accepted``, and the signals ``became_ready``
    and ``closed``. The host provides the names in ``HOST_NAMES``.
    """

    became_ready = Signal()
    closed = Signal()
    #: Browse's viewport could not hold the edit; the editor opened in the
    #: host's own viewport instead. The argument is the reason.
    moved_to_own_viewport = Signal(str)
    #: The edit moved from Browse's viewport to the host's (Promote to tab, P4 V5).
    promoted_to_tab = Signal()
    #: (session, payload): a deferred morph query answered, on its own thread.
    morph_state_arrived = Signal(object, object)
    #: (session, error): the session files were written again after a crash.
    crash_rewrite_done = Signal(object, str)
    #: Browse's viewport while an edit is bound to it (``edit_in_viewport``).
    _viewport_binding = None
    #: The view is closed to save memory; the session stays (P15 step 3).
    standalone_rust_parked = False
    standalone_rust_unpark_requested = False

    def __init__(self, host: QObject) -> None:
        QObject.__init__(self, host)
        self._live_edit_host = host
        self.morph_state_arrived.connect(self._send_rust_morph_state)
        self.crash_rewrite_done.connect(self._relaunch_rust_editor_after_crash)
        self._viewport_binding = None

    # ----- the public surface -------------------------------------------------
    def open(self, controller: object) -> None:
        self._start_rust_editor_requested(controller)

    def close_edit(self, reason: str = "") -> None:
        self._stop_rust_editor_process(reason=reason)

    @property
    def is_ready(self) -> bool:
        return bool(self.standalone_rust_ready)

    @property
    def is_busy(self) -> bool:
        return bool(self._rust_editor_task_active())

    @property
    def finish_accepted(self) -> bool:
        return bool(self.standalone_rust_finish_accepted)

    @property
    def host(self) -> QObject:
        return self._live_edit_host

    # ----- edit in another host's viewport (P4 V3) ----------------------------
    def edit_in_viewport(self, binding: object) -> None:
        """Open the next edit in ``binding``'s viewport (Browse's) instead of the host's."""

        self._viewport_binding = binding

    @property
    def viewport_binding(self) -> object | None:
        return self._viewport_binding

    def request_finish(self) -> bool:
        """Finish Edit Mesh, as the editor's Finish button does; False when no editor is ready."""

        if not self.standalone_rust_ready:
            return False
        return bool(self._send_rust_command("session.finish"))

    # ----- Promote to tab (P4 V5) --------------------------------------------
    def promote_to_tab(self) -> bool:
        """Move the edit from Browse's viewport into the host's (the Mesh Editor tab).

        The edit keeps running in Browse's process, in a window of its own under
        the tab; nothing reopens. False when there is no edit in Browse to move.
        """

        binding = self._viewport_binding
        channel = getattr(binding, "channel", None)
        promote = getattr(channel, "promote", None)
        if binding is None or not callable(promote) or not self.standalone_rust_ready:
            return False
        frame = self._live_edit_host.standalone_native_host_frame
        prepare = getattr(frame, "prepare_launch", None)
        parent_hwnd = int(prepare() or 0) if callable(prepare) else 0
        if parent_hwnd <= 0:
            return False
        channel.promoted.connect(self._finish_promotion)
        channel.promote_refused.connect(self._promotion_refused)
        if not promote(parent_hwnd):
            channel.promoted.disconnect(self._finish_promotion)
            channel.promote_refused.disconnect(self._promotion_refused)
            return False
        return True

    def _finish_promotion(self, child_hwnd: int, parent_hwnd: int) -> None:
        binding = self._viewport_binding
        if binding is None:
            return
        self._viewport_binding = None
        channel = binding.hand_over()
        frame = self._live_edit_host.standalone_native_host_frame
        attach = getattr(frame, "attach_child_window", None)
        process_id = int(channel.processId()) if channel is not None else 0
        attached, reason = attach(child_hwnd, process_id, parent_hwnd) if callable(attach) else (False, "")
        if not attached:
            self._fail_rust_editor(f"The edit could not move to the Mesh Editor tab: {reason or 'no host window'}.")
            return
        self.standalone_rust_child_hwnd = child_hwnd
        show_editor = getattr(frame, "show_editor", None)
        if callable(show_editor):
            show_editor()
        self.promoted_to_tab.emit()

    def _promotion_refused(self, reason: str) -> None:
        self.status_message_requested.emit(f"The edit stays in Browse Archives: {reason}", True)

    def _release_viewport_binding(self) -> None:
        binding, self._viewport_binding = self._viewport_binding, None
        if binding is not None:
            binding.end()


def _host_property(name: str) -> property:
    def get(self: LiveEditComponent):
        return getattr(self._live_edit_host, name)

    return property(get, doc=f"Read from the host: {name}.")


for _name in HOST_NAMES:
    setattr(LiveEditComponent, _name, _host_property(_name))


def _viewport_frame(self: LiveEditComponent):
    binding = self._viewport_binding
    if binding is not None:
        return binding.frame
    return self._live_edit_host.standalone_native_host_frame


# An edit in Browse's viewport answers the host-frame calls for that viewport.
LiveEditComponent.standalone_native_host_frame = property(
    _viewport_frame, doc="The host's viewport frame, or the borrowed viewport's while one is bound.")


def moved_method_names() -> tuple[str, ...]:
    """Methods the component took over from the tab."""

    names: list[str] = []
    for cls in (MeshEditorRustEditorMixin, MeshEditorRustProcessMixin):
        names.extend(name for name, value in vars(cls).items()
                     if callable(value) and not name.startswith("__"))
    return tuple(dict.fromkeys(names))


class _ForwardedMethod:
    """A moved method, reached through the host.

    Assigning it on a host instance (``tab._send_rust_message = fake``, or
    ``patch.object(tab, ...)``) overrides it on the component, where the
    component's own calls see it too; deleting the override restores it.
    """

    def __init__(self, name: str) -> None:
        self.name = name

    def __get__(self, obj, owner=None):
        if obj is None:
            name = self.name

            def unbound(host, *args, **kwargs):
                return getattr(host.live_edit, name)(*args, **kwargs)

            unbound.__name__ = name
            return unbound
        return getattr(obj.live_edit, self.name)

    def __set__(self, obj, value) -> None:
        setattr(obj.live_edit, self.name, value)

    def __delete__(self, obj) -> None:
        try:
            delattr(obj.live_edit, self.name)
        except AttributeError:
            pass


def install_live_edit_forwarders(cls: type) -> None:
    """Keep ``tab.standalone_rust_*`` and the moved methods working on a host class.

    Tab code, other mixins and tests read, write and call these names on the tab;
    each forwards to ``self.live_edit``.
    """

    def state(name: str) -> property:
        return property(lambda self: getattr(self.live_edit, name),
                        lambda self, value: setattr(self.live_edit, name, value),
                        doc=f"Owned by the live-edit component: {name}.")

    for name in STATE_NAMES:
        setattr(cls, name, state(name))
    for name in moved_method_names():
        setattr(cls, name, _ForwardedMethod(name))
