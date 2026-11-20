"""Use Browse Archives' controls for the current entry or selection."""

from __future__ import annotations

from cdmw.mcp.errors import NOT_FOUND, REFUSED, UNAVAILABLE, ToolError
from cdmw.mcp.names import EDIT, OUTPUT, READ
from cdmw.mcp.rail_actions import BOOL, PATH, choices, output, press, required, tool, ui, window
from cdmw.mcp.read_tools import to_data
from cdmw.mcp.tools import ON_WORKER
from cdmw.mcp.ui_actions import run_action


_REFERENCE_DIALOG = "layout_cdmw_ui_archive_browser_reference_export__prompt_archive_reference_selection_dialog"
_FAMILY_DIALOG = "layout_cdmw_ui_archive_browser_asset_family_dialog__open_archive_asset_family_workspace_dialog_dialog"
_SIDECAR_DIALOG = (
    "layout_cdmw_ui_archive_browser_binary_sidecar_actions__open_archive_binary_sidecar_inspector_dialog_dialog"
)
_PREVIEW_DIALOG = "layout_cdmw_ui_archive_browser_reference_preview__show_archive_reference_preview_dialog_dialog"


def _archive(call):
    archive = getattr(window(call), "archive", None)
    if archive is None:
        raise ToolError(UNAVAILABLE, "Browse Archives is unavailable.")
    return archive


def _state(archive):
    entry = archive._current_archive_entry()
    controller = getattr(archive, "archive_reference_search_controller", None)
    search = getattr(archive, "archive_reference_search_state", None)
    if search is not None and (entry is None or search.target.identity != entry.identity):
        search = None
    return {"path": entry.path if entry is not None else "",
            "busy": (getattr(archive.shell, "worker_thread", None) is not None
                     or bool(getattr(archive, "_archive_remote_export_request_id", None))
                     or getattr(archive, "_mcp_batch_export", None) is not None),
            "finding_references": bool(controller is not None and controller.busy),
            "references": to_data(search) if search is not None else None,
            "result": str(getattr(archive, "_dashboard_last_result_text", "")),
            "last_action": getattr(archive, "_mcp_archive_action", None)}


def _state_tool(call):
    return call.context.ui_call(lambda: _state(_archive(call)))


def _completion(call, archive, operation, dialogs):
    """Let the owning worker complete and answer the dialogs its callback opens."""
    shell = archive.shell
    previous = getattr(shell, "_utility_completion_handler", None)
    operation()
    callback = getattr(shell, "_utility_completion_handler", None)
    if callback is not None and callback is not previous:
        def complete(value):
            from cdmw.models import ArchivePreviewResult

            if isinstance(value, ArchivePreviewResult):
                result = {"status": value.status, "title": value.title, "text": value.detail_text[:32000]}
            else:
                result = to_data(value)
            archive._mcp_archive_action = {"result": result}
            result = run_action(call.context, lambda: callback(value), dialogs=dialogs)
            if result.get("asked"):
                archive._mcp_archive_action["asked"] = result["asked"]

        shell._utility_completion_handler = complete


def _read_action(call):
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QDialog, QPlainTextEdit, QTextEdit, QTreeWidget

    action = call.arguments["action"]
    result = {}

    def capture(dialog):
        edits = [*dialog.findChildren(QPlainTextEdit), *dialog.findChildren(QTextEdit)]
        result["text"] = "\n".join(edit.toPlainText() for edit in edits)[:64000]
        result["rows"] = [[tree.topLevelItem(row).text(0) for row in range(min(tree.topLevelItemCount(), 100))]
                          for tree in dialog.findChildren(QTreeWidget)]
        return QDialog.DialogCode.Rejected

    def preview_window(dialog):
        dialog.setModal(False)
        dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        dialog.show()
        return QDialog.DialogCode.Accepted

    dialogs = {_FAMILY_DIALOG: capture, _SIDECAR_DIALOG: capture, _PREVIEW_DIALOG: preview_window}

    def run():
        archive = _archive(call)
        if action in {"find_references", "open_preview", "family", "filter_family", "inspect_sidecar", "preview"}:
            if archive._current_archive_entry() is None:
                raise ToolError(UNAVAILABLE, "Select a file in Browse Archives first.")
        button = {
            "find_references": archive.archive_reference_search_button,
            "stop_references": archive.archive_reference_cancel_button,
            "open_preview": archive.archive_action_open_preview_window_button,
            "preview": archive.archive_action_preview_button,
            "family": archive.archive_asset_family_button,
            "filter_family": archive.archive_action_filter_to_family_button,
            "inspect_sidecar": archive.archive_sidecar_inspect_button,
        }[action]
        _completion(call, archive, lambda: press(button), dialogs)
        return {**_state(archive), **result}

    return ui(call, run, dialogs=dialogs)


def _edit_action(call):
    def run():
        archive = _archive(call)
        button = (archive.archive_model_open_mesh_editor_button if call.arguments["action"] == "open_mesh"
                  else archive.archive_hkx_physics_editor_button)
        press(button)
        return _state(archive)

    return ui(call, run)


def _export(call):
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QDialog, QMessageBox, QPushButton, QTreeWidget

    args = call.arguments
    action = args["action"]
    answers = {}
    destination = None
    if action in {"file", "sidecar_corpus"}:
        destination = output(call, required(args, "path"))
        if action == "sidecar_corpus" and not destination.suffix:
            destination = output(call, destination.with_suffix(".sidecar-corpus.json"))
        answers["save_file"] = str(destination)
        if action == "sidecar_corpus":
            answers["item"] = "Files" if "sources" in args else "Folder"
            answers["number"] = args.get("scan_limit", 1000)
            if "sources" in args:
                answers["files"] = args["sources"]
            else:
                answers["folder"] = required(args, "source_folder")
    elif action in {"extract", "extract_selection", "extract_filtered", "folder"}:
        destination = output(call, required(args, "path"))
    elif action == "paths_list":
        destination = output(call, required(args, "path"))
        if destination.suffix.lower() not in {".txt", ".csv"}:
            raise ToolError(REFUSED, "A path list is a .txt or .csv file.")
        answers["save_file"] = str(destination)
    elif action != "copy_filename":
        destination = output(call, required(args, "folder"), folder=True)
        if any(destination.iterdir()):
            raise ToolError(REFUSED, "Choose an empty folder so the export cannot replace files.")
        answers["folder"] = str(destination)
    if action == "mesh_family":
        return _family_export(call, destination)
    if action == "batch_mesh":
        return _selection_batch_export(call, destination)
    if action == "paths_list":
        return _paths_list(call, destination, answers)

    def reference_dialog(dialog):
        tree = dialog.findChild(QTreeWidget)
        if tree is not None and not args.get("include_references", True):
            for i in range(tree.topLevelItemCount()):
                tree.topLevelItem(i).setCheckState(0, Qt.CheckState.Unchecked)
        button = next((control for control in dialog.findChildren(QPushButton) if control.isDefault()), None)
        if button is None:
            return QDialog.DialogCode.Rejected
        press(button)
        return dialog.result()

    def extract_dialog(box):
        if destination.exists():
            # Refuse a path created by another action since validation.
            button = box.button(QMessageBox.StandardButton.Cancel)
            if button is not None:
                button.click()
            return QDialog.DialogCode.Rejected
        button = box.defaultButton()
        if button is not None and box.buttonRole(button) == QMessageBox.ButtonRole.AcceptRole:
            button.click()
        return box.result()

    dialogs = {_REFERENCE_DIALOG: reference_dialog}
    if action in {"extract", "extract_selection", "extract_filtered", "folder"}:
        dialogs[QMessageBox] = extract_dialog

    def run():
        archive = _archive(call)
        if archive.shell._background_task_active():
            raise ToolError(UNAVAILABLE, "Wait for the current Browse Archives operation to finish.")
        archive._mcp_archive_action = None
        if action == "copy_filename":
            press(archive.archive_action_copy_filename_button)
        elif action == "extract":
            if archive._current_archive_entry() is None:
                raise ToolError(UNAVAILABLE, "Select an archive file before extracting it.")
            archive._extract_current_archive_file(output_root_override=destination)
        elif action == "extract_selection":
            archive.extract_selected_archive_entries(output_root_override=destination)
        elif action == "folder":
            from cdmw.ui.archive_browser.context_commands import NO_FOLDER, _selected_folder

            if not _selected_folder(archive):
                raise ToolError(UNAVAILABLE, NO_FOLDER + " (view_open with folder selects one.)")
            archive.extract_selected_archive_entries(output_root_override=destination)
        elif action == "extract_filtered":
            archive.extract_filtered_archive_entries(output_root_override=destination)
        elif action == "mesh_neutral_obj":
            entry = archive._current_archive_entry()
            if entry is None or entry.extension != ".pac":
                raise ToolError(UNAVAILABLE, "Select a .pac model first: the neutral appearance is a character's.")
            _completion(call, archive, lambda: archive._start_archive_mesh_export(
                entry, "obj", bake_neutral_appearance=True), dialogs)
        else:
            button = {"file": archive.archive_action_export_file_button, "sidecar_corpus": archive.archive_sidecar_corpus_button,
                      "family": archive.archive_action_export_family_button,
                      "mesh": getattr(archive, f"archive_model_export_{args.get('format', 'obj')}_button")}[action]
            _completion(call, archive, lambda: press(button), dialogs)
        return {**_state(archive), "destination": str(destination or "")}

    return ui(call, run, answers, dialogs=dialogs)


def _family_export(call, destination):
    from cdmw.domain.archives.constants import ARCHIVE_MESH_EXTENSIONS
    from cdmw.mcp.read_tools import _compat, _lookup
    from cdmw.ui.archive_browser.mesh_batch_export_controller import BatchMeshSelection

    captured = {}

    def read_family():
        archive = _archive(call)
        entry = archive._current_archive_entry()
        if entry is None:
            raise ToolError(UNAVAILABLE, "Select a member of an asset family first.")
        family = archive._archive_asset_family_graph_or_prepare(entry, "Batch Mesh Export")
        if family is None:
            raise ToolError(UNAVAILABLE, "The family is being prepared. Retry after its preview is ready.")
        entries = archive._archive_entries_from_asset_family_graph(family[0])
        bridge = getattr(archive, "archive_remote_bridge", None)
        captured.update(archive=archive, source=entry.identity,
                        entries=tuple(item for item in entries if item.extension in ARCHIVE_MESH_EXTENSIONS),
                        remote=bool(bridge is not None and bridge.displays_v2))

    ui(call, read_family)
    if not captured["entries"]:
        raise ToolError(NOT_FOUND, "The family contains no resolved mesh files.")
    selections = []
    for entry in captured["entries"]:
        call.check_cancelled()
        dto = None
        if captured["remote"]:
            _session, copies = _lookup(call, entry.path)
            dto = next((candidate for candidate in copies if _compat(call, candidate).identity == entry.identity), None)
            if dto is None:
                raise ToolError(UNAVAILABLE, f"The catalogue no longer has this family member: {entry.path}.")
        selections.append(BatchMeshSelection(entry, dto))

    def check():
        archive = _archive(call)
        entry = archive._current_archive_entry()
        if archive is not captured["archive"] or entry is None or entry.identity != captured["source"]:
            raise ToolError(UNAVAILABLE, "The selected archive family changed. Choose it again.")
        return archive

    return _run_batch(call, check, tuple(selections), destination)


def _selection_batch_export(call, destination):
    """Batch Export Selected Models for the rows selected now (view_open with paths selects them)."""

    from cdmw.ui.archive_browser import mesh_batch_export_controller as batch

    def check():
        archive = _archive(call)
        nodes = tuple(archive.archive_tree.selectedItems())
        if batch.batch_selection_has_unloaded_rows(archive, nodes):
            raise ToolError(UNAVAILABLE, "Some selected rows are not loaded yet; select the files with view_open "
                                         "paths instead of a folder or a filter.")
        return archive

    def read():
        return batch.selected_batch_models(check())

    selections = call.context.ui_call(read)
    if not selections:
        raise ToolError(UNAVAILABLE, "Select PAC, PAM or PAMLOD files first (view_open with paths). Folders and "
                                     "other file types are not included.")
    return _run_batch(call, check, tuple(selections), destination)


def _run_batch(call, check, selections, destination):
    def launch():
        archive = check()
        if archive.shell._background_task_active() or getattr(archive, "_mcp_batch_export", None) is not None:
            raise ToolError(UNAVAILABLE, "Wait for the current Browse Archives operation to finish.")

        def configure(dialog):
            archive._mcp_batch_export = dialog
            archive._mcp_archive_action = None
            dialog.output_edit.setText(str(destination))
            dialog.mesh_only.setChecked(call.arguments.get("allow_missing_skeleton", False))

            def finished(_code):
                archive._mcp_archive_action = {"report": dialog.report.toPlainText()[:64000]}
                archive._mcp_batch_export = None

            dialog.finished.connect(finished)
            dialog.controller.finished.connect(dialog.accept)
            dialog.open()
            press(dialog.start_button)

        archive._open_batch_mesh_export(selections, call.arguments.get("format", "obj"), run_dialog=configure)
        return {**_state(archive), "destination": str(destination), "files": len(selections)}

    return ui(call, launch)


_PATH_SCOPES = ("all", "filtered", "selected", "folder")


def _paths_list(call, destination, answers):
    """Export File Paths: the dialog's scope set, Export pressed, the list written in the background."""

    from PySide6.QtCore import QEventLoop, QTimer

    from cdmw.ui.archive_browser.path_export_dialog import ArchivePathExportDialog

    scope = str(call.arguments.get("scope") or "filtered")
    report: dict[str, object] = {}

    def run_dialog(dialog):
        index = _PATH_SCOPES.index(scope)
        item = dialog.scope.model().item(index)
        if item is None or not item.isEnabled():
            report["error"] = f"The {scope} scope is not available now (select files or a folder first)."
            return 0
        dialog.scope.setCurrentIndex(index)
        loop = QEventLoop()

        def done(result):
            report["result"] = {"count": int(getattr(result, "count", 0) or 0),
                                "cancelled": bool(getattr(result, "cancelled", False)),
                                "path": str(getattr(result, "destination", "") or destination)}
            loop.quit()

        def failed(message):
            report["error"] = str(message)
            loop.quit()

        dialog.controller.finished.connect(done)
        dialog.controller.failed.connect(failed)
        press(dialog.export_button)
        if not dialog.controller.active:
            report.setdefault("error", dialog.status.text() or "The path export did not start.")
            return 0
        QTimer.singleShot(600_000, loop.quit)
        loop.exec()
        return 1

    def run():
        archive = _archive(call)
        if archive.shell._background_task_active() or not archive.archive_remote_actions_safe:
            raise ToolError(UNAVAILABLE, "Wait for the current Browse Archives operation to finish.")
        from cdmw.ui.archive_browser.path_export_dialog import open_archive_path_export

        open_archive_path_export(archive, scope)
        if "error" in report:
            raise ToolError(UNAVAILABLE, str(report["error"]))
        return {**_state(archive), "destination": str(destination), "paths": report.get("result")}

    return ui(call, run, answers, dialogs={ArchivePathExportDialog: run_dialog})


def browse_archive_tools():
    return [
        tool("files.browser_state", READ, "Read Browse Archives' current selection, export status and reference results.",
             "ui:ArchiveBrowser", _state_tool),
        tool("files.browser_view", READ, "Preview a selected file, open its preview window, inspect or filter "
             "its family, search for references or inspect a sidecar.", "ui:Browse Archives Tools", _read_action,
             {"action": choices("preview", "open_preview", "family", "filter_family", "find_references",
                                "stop_references", "inspect_sidecar")}, ("action",)),
        tool("files.browser_edit", EDIT, "Open the selected mesh or HKX file in its editor.",
             "ui:Browse Archives Tools", _edit_action, {"action": choices("open_mesh", "edit_hkx_physics")},
             ("action",)),
        tool("files.browser_export", OUTPUT, "Extract or export the current archive selection, its family, "
             "or a mesh or mesh family as OBJ, GLB or FBX. Also copy a filename or scan a sidecar corpus. "
             "extract_filtered extracts every file the filters show; folder extracts the selected folder; "
             "batch_mesh exports every selected model (select them with view_open paths); mesh_neutral_obj "
             "writes a .pac as OBJ with the character's neutral appearance; paths_list writes the archive "
             "paths of 'scope' (all, filtered, selected or folder) to a .txt or .csv file without extracting. "
             "Use a new path for file export, extraction and path lists, "
             "and an empty folder for family and mesh export.", "ui:Browse Archives export actions", _export,
             {"action": choices("file", "extract", "extract_selection", "extract_filtered", "folder", "family",
                                "mesh", "mesh_family", "mesh_neutral_obj", "batch_mesh", "paths_list",
                                "copy_filename", "sidecar_corpus"),
              "scope": choices(*_PATH_SCOPES),
              "path": PATH, "folder": PATH, "format": choices("obj", "glb", "fbx"),
              "source_folder": PATH, "sources": {"type": "array", "items": PATH, "minItems": 1, "maxItems": 256},
              "scan_limit": {"type": "integer", "minimum": 0, "maximum": 1000000},
              "include_references": BOOL, "allow_missing_skeleton": BOOL}, ("action",),
             output_paths=("path",), output_folders=("folder",), runs_on=ON_WORKER),
    ]
