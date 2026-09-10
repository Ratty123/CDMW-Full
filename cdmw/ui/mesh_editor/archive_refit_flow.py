"""GUI-thread archive selection for one managed Refit command."""

from PySide6.QtWidgets import QDialog

from cdmw.ui.mesh_editor.replace_from_archive_dialog import ReplaceFromArchivePickerDialog
from cdmw.ui.mesh_editor.replace_from_archive_flow import ReplaceFromArchiveFlowController
from cdmw.ui.archive_browser.workflow_dependencies import archive_workflow_dependency_context
from cdmw.ui.shell.tab_registry import DetachedToolWindow


class ArchiveRefitPickerController(ReplaceFromArchiveFlowController):
    def choose(self, target_entry, role):
        owner = self._owner
        service = getattr(getattr(owner, "archive", None), "archive_catalogue_service", None)
        session = getattr(service, "current_session", None)
        if session is None:
            raise ValueError("Load the game archive catalogue before choosing a Refit mesh")
        dependencies = archive_workflow_dependency_context(owner, target_entry)
        picker = ReplaceFromArchivePickerDialog(
            service, session, target_entry=dependencies.selected_entry,
            target_dependencies=dependencies, refit_role=role, parent=owner,
        )
        self._active_picker = picker
        try:
            accepted = picker.exec() == QDialog.Accepted
            if not accepted:
                raise ValueError("Archive selection cancelled; loaded meshes are unchanged")
            if service.current_session is not session:
                raise ValueError("The archive catalogue changed while selecting a Refit mesh")
            return picker.selected_entry, picker.selected_dependencies
        finally:
            self._active_picker = None
            self._retain_picker_until_idle(picker)


def prepare_archive_refit_event(tab, session, event):
    """Only host-selected archive objects enter the worker; never client paths."""
    controller = getattr(tab, "_archive_refit_picker", None)
    if controller is None:
        owner = tab.window()
        if isinstance(owner, DetachedToolWindow):
            owner = owner.owner
        controller = ArchiveRefitPickerController(owner)
        tab._archive_refit_picker = controller
    role = str(dict(event.get("arguments") or {}).get("role", ""))
    if role not in {"body", "armor"}:
        raise ValueError("Choose a body or armor archive mesh")
    target = tab._current_target_entry()
    entry, dependencies = controller.choose(target, role)
    if tab.standalone_rust_authoring_session is not session or tab.standalone_rust_closing:
        raise ValueError("The edit session closed while the archive picker was open")
    if tab._current_target_entry().identity != target.identity:
        raise ValueError("The loaded archive mesh changed during selection")
    return {**event, "arguments": {
        "role": role, "_archive_entry": entry, "_archive_dependencies": dependencies,
        "_primary_entry": target,
    }}
