"""Model Library sources, search, selection and output controls."""

from __future__ import annotations

from cdmw.mcp.errors import INVALID_ARGUMENTS, NOT_FOUND, REFUSED, UNAVAILABLE, ToolError
from cdmw.mcp.names import DESTRUCTIVE, EDIT, OUTPUT, READ
from cdmw.mcp.rail_actions import BOOL, PATH, ROW, ROWS, TEXT, choices, choose, output, page, press, required
from cdmw.mcp.rail_actions import select_tree_rows, tool, ui


def _state(tab, args):
    from PySide6.QtCore import Qt

    tree = tab.results_tree
    start = args.get("offset", 0)
    end = min(start + args.get("count", 0), tree.topLevelItemCount())
    return {"sources": list(tab.local_roots), "view": tab._active_results_view, "catalogue": str(tab.catalogue_dir()),
            "busy": tab._task_thread is not None, "status": tab.catalogue_status_label.text(),
            "total": tree.topLevelItemCount(),
            "rows": [{"row": index, "name": item.text(1), "source": item.text(2), "location": item.text(9),
                      "checked": item.checkState(0) == Qt.CheckState.Checked}
                     for index in range(start, end) if (item := tree.topLevelItem(index)) is not None]}


def _read(call):
    args = {"count": 100, **call.arguments}

    def read():
        tab = page(call, "model_library")
        state = _state(tab, args)
        if "urls_for" in args:
            # Show File URLs: the same text the menu's dialog shows, for mirror rows only.
            payloads = []
            for row in args["urls_for"]:
                item = tab.results_tree.topLevelItem(row)
                if item is None:
                    raise ToolError(NOT_FOUND, f"There is no result row {row}.")
                payload = _row_payload(item)
                if payload.get("kind") != "mirror":
                    raise ToolError(INVALID_ARGUMENTS, f"Row {row} is not a mirror model; only those have file URLs.")
                payloads.append(payload)
            state["file_urls"] = tab._selected_file_url_text(payloads)
        return state

    return call.context.ui_call(read)


def _row_payload(item) -> dict:
    from PySide6.QtCore import Qt

    payload = item.data(0, Qt.ItemDataRole.UserRole)
    return dict(payload) if isinstance(payload, dict) else {}


def _form(tab, args):
    for key, control in (("mirror_url", tab.mirror_url_edit), ("query", tab.search_edit),
                         ("license", tab.license_filter_edit), ("creator", tab.creator_filter_edit),
                         ("exclude_creators", tab.creator_exclude_edit)):
        if key in args:
            control.setText(args[key])
    if "mirror_url" in args:
        tab.mirror_url_edit.editingFinished.emit()
    if "format" in args:
        choose(tab.format_filter_combo, args["format"])
    if "current_only" in args:
        tab.index_current_search_checkbox.setChecked(args["current_only"])
    if "max_shards" in args:
        tab.max_shards_spin.setValue(args["max_shards"])
    if "result_limit" in args:
        tab.result_limit_spin.setValue(args["result_limit"])
    if "formats" in args:
        for key, control in tab.preferred_format_checks.items():
            control.setChecked(key in args["formats"])


def _change(call):
    args = call.arguments
    folder = output(call, args["catalogue"], folder=True) if "catalogue" in args else None

    def change():
        tab = page(call, "model_library")
        action = args["action"]
        if action == "add_source":
            tab.local_path_edit.setText(required(args, "path"))
            press(tab.add_local_root_button)
        elif action == "remove_source":
            select_tree_rows(tab.roots_tree, [required(args, "row")])
            press(tab.remove_local_root_button)
        elif action == "scan_sources":
            tab.scan_local_roots()
        elif action in {"search", "configure"}:
            if folder is not None:
                if tab._task_thread is not None or tab._pending_dotnet_icon_capture is not None:
                    raise ToolError(UNAVAILABLE, "Wait for the current Model Library task to finish.")
                tab.catalogue_dir_edit.setText(str(folder))
                tab.catalogue_dir_edit.editingFinished.emit()
            _form(tab, args)
            if "view" in args:
                press(tab.local_results_view_button if args["view"] == "local" else tab.mirror_results_view_button)
            if action == "search":
                press(tab.apply_results_query_button)
        elif action == "cancel":
            press(tab.cancel_task_button)
        else:
            select_tree_rows(tab.results_tree, [required(args, "row")])
            payload = tab._selected_payload() or {}
            if action == "use" and payload.get("kind") == "mirror":
                raise ToolError(UNAVAILABLE, "Use models_output with download_use for a mirror row.")
            if action == "preview_in_browser":
                if payload.get("kind") == "mirror" or not tab._payload_can_import(payload):
                    raise ToolError(UNAVAILABLE, "This row cannot be previewed in Browse Archives; download it first.")
                tab.preview_selected_model()  # the row menu's Preview In Archive Browser
            else:
                press(tab.preview_button if action == "preview" else tab.use_in_new_item_studio_button)
        return _state(tab, {})

    return ui(call, change)


def _produce(call):
    from PySide6.QtCore import Qt
    from cdmw.domain.output_paths import game_path_reason
    from cdmw.domain.workspace import workspace_paths

    args = call.arguments
    folder = output(call, args["folder"], folder=True)
    action = args["action"]
    game = call.context.game_folder()
    relative_targets = {
        "index": ("mirror_catalogue.sqlite", "mirror_catalogue.sqlite-journal", "catalogue_shards", "downloads",
                  "README.mirror.html", "catalogue_index.html"),
        "download": ("downloads",),
        "download_use": ("downloads",),
        "icon": ("generated_icons",),
    }[action]
    for relative in relative_targets:
        reason = game_path_reason(folder / relative, game_folder=game)
        if reason:
            raise ToolError(REFUSED, reason)

    def produce():
        tab = page(call, "model_library")
        if tab._task_thread is not None or tab._pending_dotnet_icon_capture is not None:
            raise ToolError(UNAVAILABLE, "Wait for the current Model Library task to finish.")
        if action == "icon":
            library = workspace_paths(tab.base_dir)["item_icon_library_root"]
            reason = game_path_reason(library / "edited", game_folder=game)
            if reason:
                raise ToolError(REFUSED, reason)
        tab.catalogue_dir_edit.setText(str(folder))
        tab.catalogue_dir_edit.editingFinished.emit()
        _form(tab, args)
        if action == "index":
            press(tab.build_index_button)
        elif action == "download":
            if "rows" in args:
                rows = args["rows"]
                select_tree_rows(tab.results_tree, [rows[0]])
                items = [tab.results_tree.topLevelItem(row) for row in rows]
                if any(item is None for item in items):
                    raise ToolError(UNAVAILABLE, "A checked row is absent from the current Model Library results.")
                tab._set_all_result_checks(False)
                for item in items:
                    item.setCheckState(0, Qt.CheckState.Checked)
            press(tab.download_button)
        elif action == "download_use":
            select_tree_rows(tab.results_tree, [required(args, "row")])
            press(tab.use_in_new_item_studio_button)
        else:
            select_tree_rows(tab.results_tree, [required(args, "row")])
            press(tab.generate_icon_button)
        return _state(tab, {})

    return ui(call, produce)


def _delete(call):
    """Delete downloaded mirror copies only: a user's own local model files are never an AI's to delete."""

    from PySide6.QtWidgets import QMessageBox

    args = call.arguments
    action = args["action"]

    def confirm(box):
        button = next((b for b in box.buttons() if box.buttonRole(b) == QMessageBox.ButtonRole.DestructiveRole), None)
        if button is None:
            raise ToolError(UNAVAILABLE, "The delete question has no Delete button.")
        button.click()
        return 0

    def delete():
        tab = page(call, "model_library")
        if tab._task_thread is not None:
            raise ToolError(UNAVAILABLE, "Wait for the current Model Library task to finish.")
        if action == "downloads":
            payloads = []
            for row in args.get("rows") or ():
                item = tab.results_tree.topLevelItem(row)
                if item is None:
                    raise ToolError(NOT_FOUND, f"There is no result row {row}.")
                select_tree_rows(tab.results_tree, [row])
                payload = tab._selected_payload() or {}
                if tab._downloaded_model_folder_target_for_payload(payload) is None:
                    raise ToolError(REFUSED, f"Row {row} is not a downloaded copy; only downloaded mirror folders "
                                             "can be deleted this way.")
                payloads.append(payload)
            if not payloads:
                raise ToolError(INVALID_ARGUMENTS, "Give the rows of the downloaded copies to delete.")
            tab._delete_local_payloads(payloads)
        else:
            tab.delete_no_texture_downloads()
        return _state(tab, {})

    return ui(call, delete, dialogs={QMessageBox: confirm})


def model_library_tools():
    options = {"mirror_url": TEXT, "query": TEXT, "license": TEXT, "creator": TEXT, "exclude_creators": TEXT,
               "format": choices("", "gltf", "glb", "source"), "current_only": BOOL,
               "max_shards": {"type": "integer", "minimum": 0, "maximum": 100000},
               "result_limit": {"type": "integer", "minimum": 1, "maximum": 5000},
               "formats": {"type": "array", "maxItems": 4, "items": choices("gltf", "glb", "source", "extra")}}
    return [
        tool("models.state", READ, "Read Model Library sources and result rows. urls_for lists the file URLs of "
             "mirror rows, as Show File URLs does.", "ui:ModelLibraryTab.results_tree",
             _read, {"offset": ROW, "count": {"type": "integer", "minimum": 1, "maximum": 500}, "urls_for": ROWS}),
        tool("models.change", EDIT, "Manage sources, configure or search models, preview a row here or in Browse Archives, use it in "
             "Create New Item or cancel work.", "ui:ModelLibraryTab", _change,
             {**options, "action": choices("add_source", "remove_source", "scan_sources", "configure", "search",
                                           "preview", "preview_in_browser", "use", "cancel"),
              "view": choices("local", "mirror"), "path": PATH, "row": ROW, "catalogue": PATH}, ("action",)),
        tool("models.output", OUTPUT, "Build the mirror search index, download checked results or generate "
             "a preview icon. Download and use a mirror model with download_use. The folder becomes Model Library's "
             "catalogue directory.", "ui:ModelLibraryTab",
             _produce, {**options, "action": choices("index", "download", "download_use", "icon"),
                        "folder": PATH, "rows": ROWS, "row": ROW}, ("action", "folder"),
             output_folders=("folder",)),
        tool("models.delete", DESTRUCTIVE,
             "Delete downloaded Model Library copies: the downloaded mirror folders of rows, or every visible "
             "download whose textures were not found (More > Delete No-Texture Downloads). Your own local model "
             "files are never deleted by this tool.",
             "ui:ModelLibraryTab.results_tree", _delete,
             {"action": choices("downloads", "no_texture_downloads"), "rows": ROWS}, ("action",)),
    ]
