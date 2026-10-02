"""GUI-thread selection of an immutable, prepared archive collision input."""

from PySide6.QtWidgets import QDialog

from cdmw.ui.replace_assistant.archive_picker import RemoteArchiveOriginalDialog
from cdmw.ui.shell.tab_registry import DetachedToolWindow


def prepare_cloth_collision_event(tab, session, event):
    args = dict(event.get("arguments") or {})
    role = args.get("role")
    if set(args) != {"role", "source"} or role not in {"body", "head", "weapon"} or args["source"] != "archive":
        raise ValueError("Choose a valid collision source.")
    owner = tab.window()
    if isinstance(owner, DetachedToolWindow):
        owner = owner.owner
    service = getattr(getattr(owner, "archive", None), "archive_catalogue_service", None)
    catalogue_session = getattr(service, "current_session", None)
    if catalogue_session is None:
        raise ValueError("Load the game archives before choosing a collision input.")
    target = tab._current_target_entry()
    weapon = role == "weapon"
    picker = RemoteArchiveOriginalDialog(
        service, catalogue_session, initial_filter="", parent=owner,
        extensions=(".pac",) if weapon else (".pabv",),
        title="Choose weapon PAC from archives" if weapon else "Choose body/head PABV from archives",
        hint="Search the game archives by name or path. Only the selected file is loaded for this preview.",
        prepare_selection=True, maximum_bytes=(32 if weapon else 8) * 1024 * 1024,
    )
    tab._cloth_collision_picker = picker
    try:
        if picker.exec() != QDialog.Accepted or picker.selected_entry is None or picker.selected_prepared is None:
            raise ValueError("Collision input selection cancelled; preview inputs are unchanged.")
        if (tab.standalone_rust_authoring_session is not session or tab.standalone_rust_closing
                or service.current_session is not catalogue_session or tab._current_target_entry().identity != target.identity):
            raise ValueError("The edit session or game archives changed during collision selection.")
        return {**event, "arguments": {"role": role, "_archive_entry": picker.selected_entry,
                                        "_archive_prepared": picker.selected_prepared}}
    finally:
        tab._cloth_collision_picker = None
        picker.reject()
        picker.deleteLater()
