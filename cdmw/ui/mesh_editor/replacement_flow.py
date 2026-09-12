"""Host-owned file selection and archive context for replacement commands."""

from PySide6.QtWidgets import QFileDialog

from cdmw.ui.archive_browser.workflow_dependencies import archive_workflow_dependency_context
from cdmw.ui.shell.tab_registry import DetachedToolWindow


def prepare_replacement_event(tab, session, event):
    args = dict(event.get("arguments") or {})
    target = tab._current_target_entry()
    if target is None:
        raise ValueError("Open an archive mesh before importing a replacement.")
    owner = tab.window()
    if isinstance(owner, DetachedToolWindow):
        owner = owner.owner
    if session.shadow_service._session(session.shadow_session_id).replacement_state is None:
        args["_archive_entry"] = target
        args["_archive_dependencies"] = archive_workflow_dependency_context(owner, target)
    if event.get("command") == "replacement_choose":
        path, _ = QFileDialog.getOpenFileName(tab, "Import Replacement", "", "Mesh models (*.obj *.dae *.gltf *.glb)")
        if not path:
            args["cancelled"] = True
        else:
            args["source_path"] = path
    if tab.standalone_rust_authoring_session is not session or tab.standalone_rust_closing:
        raise ValueError("The mesh session closed during replacement selection.")
    if tab._current_target_entry().identity != target.identity:
        raise ValueError("The archive target changed during replacement selection.")
    return {**event, "arguments": args}
