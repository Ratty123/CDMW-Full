"""Host-owned reference selection for hair; all decoding stays on the worker."""

from PySide6.QtWidgets import QDialog
from cdmw.ui.archive_browser.workflow_dependencies import archive_workflow_dependency_context
from cdmw.ui.mesh_editor.archive_refit_flow import ArchiveRefitPickerController
from cdmw.ui.mesh_editor.replace_from_archive_dialog import ReplaceFromArchivePickerDialog
from cdmw.ui.shell.tab_registry import DetachedToolWindow


def open_hair_texture_source(tab, path):
    owner = tab.window()
    if isinstance(owner, DetachedToolWindow):
        owner = owner.owner
    owner.textures._open_source_in_texture_editor(path, None)


def prepare_hair_event(tab, session, event):
    owner = tab.window()
    if isinstance(owner, DetachedToolWindow):
        owner = owner.owner
    target = tab._current_target_entry()
    if target is None:
        raise ValueError("Open a Damiane hairstyle from the archive before creating hair.")
    service = owner.archive.archive_catalogue_service
    archive_session = service.current_session
    dependencies = archive_workflow_dependency_context(owner, target)
    picker = ReplaceFromArchivePickerDialog(
        service, archive_session, target_entry=target, target_dependencies=dependencies,
        refit_role="hair", parent=owner,
    )
    controller = getattr(tab, "_hair_picker", None)
    if controller is None:
        controller = ArchiveRefitPickerController(owner)
        tab._hair_picker = controller
    controller._active_picker = picker
    try:
        if picker.exec() != QDialog.Accepted:
            raise ValueError("Head selection cancelled; the current hairstyle is unchanged.")
        if (service.current_session is not archive_session or tab.standalone_rust_authoring_session is not session
                or tab.standalone_rust_closing or tab._current_target_entry().identity != target.identity):
            raise ValueError("The editor or archive changed during reference selection.")
        arguments = {
            **dict(event.get("arguments") or {}), "_archive_entry": picker.selected_entry,
            "_archive_dependencies": picker.selected_dependencies,
            "_target_entry": target, "_target_dependencies": dependencies,
        }
        # Keep actual upper-body geometry as a separate reference. It is never
        # appended to the output part table or used as a generated hair donor.
        body_picker = ReplaceFromArchivePickerDialog(service, archive_session,
            target_entry=target, target_dependencies=dependencies, refit_role="body", parent=owner)
        body_picker.setWindowTitle("Choose Damiane Body for Neck and Shoulder Reference")
        body_picker.choose_button.setText("Use Body Reference")
        controller._active_picker = body_picker
        try:
            if body_picker.exec() != QDialog.Accepted:
                raise ValueError("Body reference selection cancelled; the current mesh is unchanged.")
            if (service.current_session is not archive_session or tab.standalone_rust_authoring_session is not session
                    or tab.standalone_rust_closing):
                raise ValueError("The editor or archive changed during body selection.")
            arguments["_body_archive_entry"] = body_picker.selected_entry
            arguments["_body_archive_dependencies"] = body_picker.selected_dependencies
        finally:
            controller._retain_picker_until_idle(body_picker)
        return {**event, "arguments": arguments}
    finally:
        controller._active_picker = None
        controller._retain_picker_until_idle(picker)
