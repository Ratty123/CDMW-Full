"""Host-owned reference selection for hair; all decoding stays on the worker."""

from PySide6.QtWidgets import QDialog
from cdmw.ui.archive_browser.workflow_dependencies import archive_workflow_dependency_context
from cdmw.ui.shell.tab_registry import DetachedToolWindow


def build_hair_entry_bar(tab, *, close_button=None):
    from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QSizePolicy
    bar = QFrame(tab)
    bar.setFrameShape(QFrame.NoFrame)
    bar.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
    layout = QHBoxLayout(bar)
    layout.setContentsMargins(6, 2, 6, 2)
    layout.setSpacing(6)
    button = QPushButton("Hair Tools (Experimental)", bar)
    button.setObjectName("MeshEditorHairMenu")
    font = button.font()
    font.setBold(True)
    button.setFont(font)
    button.setToolTip("Create or edit Kliff, Damiane, and Oongka hairstyles")
    button.clicked.connect(lambda: start_hair_workflow(tab))
    layout.addWidget(button)
    if close_button is not None:
        layout.addWidget(close_button)
    tab.hair_entry_status = QLabel("", bar)
    tab.hair_entry_status.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
    layout.addWidget(tab.hair_entry_status, 1)
    return bar


def start_hair_workflow(tab, mode="generated", preset="bob", *, character=None, target_path=""):
    """All entry points use the same choices, preflight, and explicit Start."""
    from cdmw.domain.hair_characters import unique_hair_character
    from cdmw.ui.mesh_editor.hair_setup_dialog import HairSetupDialog
    owner = tab.window()
    if isinstance(owner, DetachedToolWindow):
        owner = owner.owner
    previous = getattr(tab, "_hair_setup_dialog", None)
    if previous is not None and not previous._closed:
        previous.reject()
    current_target = getattr(tab, "_current_target_entry", lambda: None)()
    authoring = getattr(tab, "standalone_rust_authoring_session", None)
    active_hair = None
    if authoring is not None and not authoring.closed:
        active_hair = authoring.shadow_service._session(authoring.shadow_session_id).hair_state
    if character is None:
        profile = unique_hair_character(current_target.path) if current_target is not None else None
        character = active_hair.payload["template"]["character"] if active_hair else profile.name if profile else None
    reuse_target = (active_hair.payload["template"]["character"], current_target.identity) if (
        active_hair and not active_hair.payload["converted"] and current_target is not None and all(g["mode"] == "generated" for g in active_hair.payload["groups"])) else None
    if not target_path and active_hair and current_target is not None:
        target_path = current_target.path
    dialog = HairSetupDialog(owner, character=character, mode=mode, preset=preset, target_path=target_path,
                             reuse_target=reuse_target, draft_root=getattr(tab, "mesh_editor_draft_root", None))
    tab._hair_setup_dialog = dialog
    def selected(result):
        if getattr(tab, "_hair_setup_dialog", None) is not dialog:
            return
        if result != QDialog.Accepted:
            tab.hair_entry_status.setText("Hair setup cancelled. The current scene is unchanged.")
            return
        target = dialog.selected_entry
        chosen_mode, chosen_preset = dialog.mode.currentData(), dialog.preset.currentData()
        live_target = getattr(tab, "_current_target_entry", lambda: None)()
        if dialog.prepared_result is None and getattr(tab, "standalone_rust_authoring_session", None) is not authoring:
            tab.hair_entry_status.setText("The Mesh Editor is not ready. Reopen Hair Tools to retry.")
            return
        same = live_target is not None and live_target.identity == target.identity
        same_character = active_hair and active_hair.payload["template"]["character"] == dialog.context.character
        if same and same_character and not active_hair.payload["converted"] and chosen_mode == "generated" and all(g["mode"] == "generated" for g in active_hair.payload["groups"]):
            if not tab._send_rust_message(tab._rust_host_message("hair_preset", request_id=0, extra={"preset": chosen_preset})):
                tab.hair_entry_status.setText("The Mesh Editor is not ready. Reopen Hair Tools to retry.")
                return
            owner.shell._activate_tool_widget(tab)
            tab.hair_entry_status.setText("Applying hairstyle preset…")
            return
        # Same-target setup must still allow switching mode or character, and
        # use the existing unsaved-work confirmation before replacing a scene.
        if not owner.shell._prepare_mesh_editor_archive_launch(target, replace_same=same):
            if dialog.prepared_result is not None:
                tab._discard_archive_session_result(dialog.prepared_result)
                dialog.prepared_result = None
            tab.hair_entry_status.setText("Hair setup cancelled. The current scene is unchanged.")
            return
        tab._pending_hair_start = (target.identity, chosen_mode)
        tab._pending_hair_preset = chosen_preset
        tab._pending_hair_character = dialog.context.character
        tab._pending_hair_context = dialog.context
        tab.open_archive_session(target, archive_dependencies=dialog.selected_dependencies, prepared_result=dialog.prepared_result)
        dialog.prepared_result = None
        owner.shell._activate_tool_widget(tab)
        tab.hair_entry_status.setText("Loading character…")
    dialog.finished.connect(selected)
    dialog.open()
    return dialog


def begin_hair_context(tab, session, event):
    """Return immediately; resume the ordered protocol queue after preparation."""
    from cdmw.ui.mesh_editor.hair_context_preparation import HairContextPreparation
    owner = tab.window()
    if isinstance(owner, DetachedToolWindow):
        owner = owner.owner
    target = tab._current_target_entry()
    if target is None:
        raise ValueError("Open a registered player hairstyle before entering Hair.")
    dependencies = getattr(tab, "archive_session_dependencies", None) or archive_workflow_dependency_context(owner, target)
    previous = getattr(tab, "_hair_context_preparation", None)
    if previous is not None:
        previous.cancel()
    else:
        previous = HairContextPreparation(owner.archive.archive_catalogue_service, tab)
        tab._hair_context_preparation = previous
    # Disconnect only this operation's handlers; the cached resolver is reusable.
    for signal in (previous.ready, previous.failed):
        try:
            signal.disconnect()
        except (RuntimeError, TypeError):
            pass

    def resume(context=None, error=""):
        if (tab.standalone_rust_authoring_session is not session or tab.standalone_rust_closing
                or tab._current_target_entry() is None or tab._current_target_entry().identity != target.identity):
            return
        args = {**dict(event.get("arguments") or {}), "_hair_context_ready": True,
                "_target_entry": target, "_target_dependencies": dependencies}
        args["start_preset"] = getattr(tab, "_pending_hair_preset", "bob")
        tab._pending_hair_preset = "bob"
        if context is not None:
            args.update(context.arguments())
        tab.standalone_rust_protocol_queue.insert(0, {**event, "arguments": args, "_hair_preparation_error": error})
        tab._start_next_rust_protocol_worker()
    previous.ready.connect(resume)
    previous.failed.connect(lambda message: resume(error=message))
    context = getattr(tab, "_pending_hair_context", None)
    tab._pending_hair_context = None
    if context is not None:
        resume(context)
    else:
        state = session.shadow_service._session(session.shadow_session_id).hair_state
        previous.start(state.payload["template"]["character"] if state else getattr(tab, "_pending_hair_character", "Damiane"))


def open_hair_texture_source(tab, path):
    owner = tab.window()
    if isinstance(owner, DetachedToolWindow):
        owner = owner.owner
    owner.textures._open_source_in_texture_editor(path, None)


def prepare_hair_event(tab, session, event):
    from cdmw.ui.mesh_editor.hair_reference_picker import HairReferencePickerDialog
    owner = tab.window()
    if isinstance(owner, DetachedToolWindow):
        owner = owner.owner
    target = tab._current_target_entry()
    if target is None:
        raise ValueError("Open a registered player hairstyle before changing references.")
    service = owner.archive.archive_catalogue_service
    archive_session = service.current_session
    arguments = {**dict(event.get("arguments") or {}), "_target_entry": target,
                 "_target_dependencies": getattr(tab, "archive_session_dependencies", None) or archive_workflow_dependency_context(owner, target)}
    for role, entry_key, dependencies_key in (("head", "_archive_entry", "_archive_dependencies"),
                                             ("body", "_body_archive_entry", "_body_archive_dependencies")):
        state = session.shadow_service._session(session.shadow_session_id).hair_state
        picker = HairReferencePickerDialog(owner, role, character=state.payload["template"]["character"] if state else "Damiane")
        if picker.exec() != QDialog.Accepted:
            raise ValueError("Reference selection cancelled; the current hairstyle is unchanged.")
        if (service.current_session is not archive_session or tab.standalone_rust_authoring_session is not session
                or tab.standalone_rust_closing or tab._current_target_entry() is None
                or tab._current_target_entry().identity != target.identity):
            raise ValueError("The editor or archive changed during reference selection.")
        arguments[entry_key] = picker.selected_entry
        arguments[dependencies_key] = picker.selected_dependencies
    return {**event, "arguments": arguments}
