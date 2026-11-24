"""Host-owned reference selection for hair; all decoding stays on the worker."""

from PySide6.QtWidgets import QDialog
from cdmw.ui.archive_browser.workflow_dependencies import archive_workflow_dependency_context
from cdmw.ui.shell.tab_registry import DetachedToolWindow

HAIR_ENTRY_STATUS_AUTO_CLEAR_MS = 5000
#: The edited DDS a hair_texture command may carry (an AI connection's), in place of
#: Apply edited DDS's file chooser.
HAIR_DDS_KEY = "dds_path"
HAIR_TEXTURE_SUFFIXES = (".dds", ".png", ".jpg", ".jpeg", ".webp", ".bmp")
#: The token of the head and body CDMW found for a Change references that an AI
#: connection asked for (``offer_hair_references``), in place of the two choosers.
HAIR_REFERENCES_KEY = "references_token"


def cancel_hair_entry_status_auto_clear(tab) -> None:
    label = getattr(tab, "hair_entry_status", None)
    if label is None:
        return
    timer = getattr(label, "_auto_clear_timer", None)
    if timer is not None:
        try:
            timer.stop()
        except RuntimeError:
            pass


def clear_hair_entry_status(tab) -> None:
    cancel_hair_entry_status_auto_clear(tab)
    label = getattr(tab, "hair_entry_status", None)
    if label is not None:
        try:
            label.setText("")
        except RuntimeError:
            pass


def arm_hair_entry_status_auto_clear(tab, clear_after_ms: int | None = None) -> None:
    from PySide6.QtCore import QTimer

    cancel_hair_entry_status_auto_clear(tab)
    label = getattr(tab, "hair_entry_status", None)
    if label is None:
        return
    try:
        expected = label.text()
    except RuntimeError:
        return
    delay = HAIR_ENTRY_STATUS_AUTO_CLEAR_MS if clear_after_ms is None else int(clear_after_ms or 0)
    if not expected or delay <= 0:
        return
    timer = QTimer(label)
    timer.setSingleShot(True)
    timer.setInterval(delay)

    def _clear() -> None:
        if getattr(label, "_auto_clear_timer", None) is not timer:
            return
        try:
            if label.text() == expected:
                label.setText("")
        except RuntimeError:
            pass

    timer.timeout.connect(_clear)
    label._auto_clear_timer = timer
    timer.start()


def build_hair_entry_bar(tab, *, close_button=None):
    from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QSizePolicy
    bar = QFrame(tab)
    bar.setObjectName("MeshEditorEntryBar")
    bar.setProperty("commandBar", True)
    bar.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
    layout = QHBoxLayout(bar)
    layout.setContentsMargins(6, 2, 6, 2)
    layout.setSpacing(4)
    button = QPushButton("Hair Tools (Experimental)", bar)
    # Bold through the theme, so it follows the UI font size.
    button.setObjectName("MeshEditorHairMenu")
    button.setToolTip("Create or edit Kliff, Damiane, and Oongka hairstyles")
    button.clicked.connect(lambda: start_hair_workflow(tab))
    tab.hair_entry_button = button
    tab.hair_entry_status = QLabel("", bar)
    tab.hair_entry_status.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
    # Status fills the middle; the bar's actions sit on the right.
    layout.addWidget(tab.hair_entry_status, 1)
    layout.addWidget(button)
    if close_button is not None:
        layout.addWidget(close_button)
    return bar


def start_hair_workflow(tab, mode="generated", preset="empty", *, character=None, target_path=""):
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
    # Each read of .payload decodes the whole hairstyle, bindings included: read it once here.
    hair = active_hair.payload if active_hair else None
    hair_character_name = hair["template"]["character"] if hair else None
    create_session = bool(hair) and not hair["converted"] and any(g["mode"] == "generated" for g in hair["groups"])
    session_keep_scalp_cap = create_session and any(g["mode"] == "existing" for g in hair["groups"])
    del hair
    if character is None:
        profile = unique_hair_character(current_target.path) if current_target is not None else None
        character = hair_character_name or (profile.name if profile else None)
    reuse_target = (hair_character_name, current_target.identity) if (
        create_session and current_target is not None) else None
    reuse_scalp_cap = session_keep_scalp_cap if reuse_target is not None else None
    if not target_path and active_hair and current_target is not None:
        target_path = current_target.path
    dialog = HairSetupDialog(owner, character=character, mode=mode, preset=preset, target_path=target_path,
                             reuse_target=reuse_target, reuse_scalp_cap=reuse_scalp_cap,
                             draft_root=getattr(tab, "mesh_editor_draft_root", None))
    tab._hair_setup_dialog = dialog
    def selected(result):
        if getattr(tab, "_hair_setup_dialog", None) is not dialog:
            return
        if result != QDialog.Accepted:
            tab.hair_entry_status.setText("Hair setup cancelled. The current scene is unchanged.")
            arm_hair_entry_status_auto_clear(tab)
            return
        target = dialog.selected_entry
        chosen_mode, chosen_preset = dialog.mode.currentData(), "empty"
        choose_donor = getattr(dialog, "choose_donor_material", None)
        keep_scalp = getattr(dialog, "keep_scalp_cap", None)
        custom_donor = bool(choose_donor.isChecked()) if choose_donor is not None else False
        keep_scalp_checked = bool(keep_scalp.isChecked()) if keep_scalp is not None else session_keep_scalp_cap
        live_target = getattr(tab, "_current_target_entry", lambda: None)()
        if dialog.prepared_result is None and getattr(tab, "standalone_rust_authoring_session", None) is not authoring:
            tab.hair_entry_status.setText("The Mesh Editor is not ready. Reopen Hair Tools to retry.")
            arm_hair_entry_status_auto_clear(tab)
            return
        same = live_target is not None and live_target.identity == target.identity
        same_character = hair_character_name == dialog.context.character
        if (same and same_character and create_session and chosen_mode == "generated"
                and not custom_donor and keep_scalp_checked == session_keep_scalp_cap):
            if not tab._send_rust_message(tab._rust_host_message("hair_preset", request_id=0, extra={"preset": chosen_preset})):
                tab.hair_entry_status.setText("The Mesh Editor is not ready. Reopen Hair Tools to retry.")
                arm_hair_entry_status_auto_clear(tab)
                return
            owner.shell._activate_tool_widget(tab)
            cancel_hair_entry_status_auto_clear(tab)
            tab.hair_entry_status.setText("Starting empty hairstyle…")
            return
        # Same-target setup must still allow switching mode or character, and
        # use the existing unsaved-work confirmation before replacing a scene.
        if not owner.shell._prepare_mesh_editor_archive_launch(target, replace_same=same):
            if dialog.prepared_result is not None:
                tab._discard_archive_session_result(dialog.prepared_result)
                dialog.prepared_result = None
            tab.hair_entry_status.setText("Hair setup cancelled. The current scene is unchanged.")
            arm_hair_entry_status_auto_clear(tab)
            return
        # The shell may have opened another document for the hairstyle, so that the one
        # this setup started in keeps its edit: the hairstyle opens in the shown one.
        document, tool = _launch_document(owner.shell, tab)
        document._pending_hair_start = (target.identity, chosen_mode)
        document._pending_hair_preset = chosen_preset
        document._pending_hair_character = dialog.context.character
        document._pending_hair_context = dialog.context
        document._pending_hair_keep_scalp_cap = keep_scalp_checked if chosen_mode == "generated" else False
        document.open_archive_session(target, archive_dependencies=dialog.selected_dependencies,
                                      prepared_result=dialog.prepared_result)
        dialog.prepared_result = None
        owner.shell._activate_tool_widget(tool)
        cancel_hair_entry_status_auto_clear(document)
        document.hair_entry_status.setText("Loading character…")
    dialog.finished.connect(selected)
    dialog.open()
    return dialog


def _launch_document(shell, tab):
    """The document an open prepared by the shell lands in, and the widget the shell raises for it.

    ``tab`` is where Hair Tools was started: one Mesh Editor document, or the Mesh Editor
    as the shell knows it (Character Finder). Preparing the launch may have opened and
    shown another document; without a documents view, ``tab`` is the editor itself.
    """
    find = getattr(shell, "_mesh_documents", None)
    view = find() if callable(find) else None
    tool = getattr(shell, "mesh_editor_tab", None)
    if view is None or (tab is not view and tab is not tool and tab not in view.documents):
        return tab, tab
    return view.active, tool if tool is not None else view


def hair_character_for_target(tab, target):
    """The character whose head and body a hairstyle opened without a setup choice is fitted to.

    The character of the last Hair Tools setup is remembered on the tab, but a hairstyle opened
    another way (Character Finder) may belong to someone else; its folder decides then.
    """
    from cdmw.domain.hair_characters import HAIR_CHARACTERS
    remembered = getattr(tab, "_pending_hair_character", None)
    owners = [profile.name for profile in HAIR_CHARACTERS if profile.accepts_hair(target.path)]
    if remembered in owners or not owners:
        return remembered or "Damiane"
    return owners[0]


def begin_hair_context(tab, session, event):
    """Return immediately; resume the ordered protocol queue after preparation."""
    from cdmw.ui.mesh_editor.hair_context_preparation import HairContextPreparation
    owner = tab.window()
    if isinstance(owner, DetachedToolWindow):
        owner = owner.owner
    target = tab._current_target_entry()
    if target is None:
        raise ValueError("Open a registered hairstyle before entering Hair.")
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
        args["start_preset"] = "empty"
        tab._pending_hair_preset = "empty"
        if "keep_scalp_cap" not in args:
            args["keep_scalp_cap"] = bool(getattr(tab, "_pending_hair_keep_scalp_cap", False))
        if context is not None:
            args.update(context.arguments())
        tab.standalone_rust_protocol_queue.insert(0, {**event, "arguments": args, "_hair_preparation_error": error})
        tab._start_next_rust_protocol_worker()
    previous.ready.connect(resume)
    previous.failed.connect(lambda message: resume(error=message))
    context = getattr(tab, "_pending_hair_context", None)
    tab._pending_hair_context = None
    state = session.shadow_service._session(session.shadow_session_id).hair_state
    character = state.payload["template"]["character"] if state else hair_character_for_target(tab, target)
    # A context left by a setup that never reached this point belongs to another hairstyle.
    if context is not None and context.character == character:
        resume(context)
    else:
        previous.start(character)


def open_hair_texture_source(tab, path):
    owner = tab.window()
    if isinstance(owner, DetachedToolWindow):
        owner = owner.owner
    owner.textures._open_source_in_texture_editor(path, None)


def hair_dds_path(tab, event):
    """The edited texture that Apply edited DDS applies: the file the command carries, checked,
    else the chooser's answer ("" when it was cancelled). An image is re-encoded to the
    template's DDS layout when it is applied."""
    from pathlib import Path
    given = dict(event.get("arguments") or {}).get(HAIR_DDS_KEY)
    if given is not None:
        path = Path(str(given))
        if not path.is_absolute() or path.suffix.lower() not in HAIR_TEXTURE_SUFFIXES or not path.is_file():
            raise ValueError("Choose an existing image or DDS file smaller than 128 MiB.")
        return str(path)
    from PySide6.QtWidgets import QFileDialog
    path, _ = QFileDialog.getOpenFileName(tab.window(), "Apply Edited Hair Texture", "",
                                          "Textures (*.dds *.png *.jpg *.jpeg *.webp *.bmp)")
    return path


def offer_hair_references(tab, head, body):
    """Keep a head and body (each ``(entry, dependencies)``) for the next Change references
    that names the token returned; only that command takes them."""
    import uuid
    token = uuid.uuid4().hex
    tab._hair_reference_answers = {token: {"head": head, "body": body}}
    return token


def _take_hair_references(tab, token):
    answers = getattr(tab, "_hair_reference_answers", None) or {}
    tab._hair_reference_answers = {}
    return answers.get(str(token))


def prepare_hair_event(tab, session, event):
    from cdmw.ui.mesh_editor.hair_reference_picker import HairReferencePickerDialog
    owner = tab.window()
    if isinstance(owner, DetachedToolWindow):
        owner = owner.owner
    target = tab._current_target_entry()
    if target is None:
        raise ValueError("Open a registered hairstyle before changing references.")
    service = owner.archive.archive_catalogue_service
    archive_session = service.current_session
    arguments = {**dict(event.get("arguments") or {}), "_target_entry": target,
                 "_target_dependencies": getattr(tab, "archive_session_dependencies", None) or archive_workflow_dependency_context(owner, target)}
    token = arguments.pop(HAIR_REFERENCES_KEY, None)
    answers = _take_hair_references(tab, token) if token is not None else None
    if token is not None and answers is None:
        raise ValueError("The head and body found for this change are no longer waiting; ask for them again.")
    for role, entry_key, dependencies_key in (("head", "_archive_entry", "_archive_dependencies"),
                                             ("body", "_body_archive_entry", "_body_archive_dependencies")):
        if answers is not None:
            # Found by their paths, as a click in the chooser would have chosen them.
            arguments[entry_key], arguments[dependencies_key] = answers[role]
            continue
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
