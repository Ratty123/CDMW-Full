"""Item Icons source, view, preview and export controls."""

from __future__ import annotations

from cdmw.mcp.errors import NOT_FOUND, UNAVAILABLE, ToolError
from cdmw.mcp.names import EDIT, OUTPUT, READ
from cdmw.mcp.rail_actions import PATH, ROW, TEXT, choices, choose, output, page, press, required
from cdmw.mcp.rail_actions import select_tree_rows, tool, ui
from cdmw.mcp.ui_actions import run_action


def _state(tab, args):
    selected = tab.current_source_path()
    tree = tab.records_tree
    start = args.get("offset", 0)
    end = min(start + args.get("count", 0), tree.topLevelItemCount())
    return {"sources": [str(path) for path in tab.library_roots], "source": str(selected or ""),
            "target": tab._current_target_path(), "background": tab._background_mode(),
            "status": tab.library_status_label.text(), "preview": tab.target_meta_label.text(),
            "busy": tab._output_thread is not None, "last_output": getattr(tab, "_mcp_icon_output", None),
            "targets": [tab.target_combo.itemText(i) for i in range(min(tab.target_combo.count(), 500))],
            "total": tree.topLevelItemCount(),
            "rows": [{"row": index, "file": item.toolTip(0), "size": item.text(1), "tags": item.text(2)}
                     for index in range(start, end) if (item := tree.topLevelItem(index)) is not None]}


def _read(call):
    args = {"count": 100, **call.arguments}
    return call.context.ui_call(lambda: _state(page(call, "item_icons"), args))


def _set_view(tab, args):
    if "filter" in args:
        tab.filter_edit.setText(args["filter"])
    if "row" in args:
        select_tree_rows(tab.records_tree, [args["row"]])
    if "target" in args:
        tab.target_filter_edit.setText(args["target"])
        if tab._target_entry_for_path(args["target"]) is None:
            tab.refresh_targets(force=True)
        tab._handle_target_filter_changed()
        if tab._target_entry_for_path(args["target"]) is None:
            raise ToolError(NOT_FOUND, f"No existing icon target matches {args['target']!r}.")
    if "background" in args:
        choose(tab.background_mode_combo, args["background"])


def _change(call):
    args = call.arguments
    action = args["action"]
    answers = {"folder": required(args, "folder")} if action == "add_source" else {}

    def change():
        tab = page(call, "item_icons")
        if action == "remove_source":
            row = required(args, "row")
            if tab.roots_list.item(row) is None:
                raise ToolError(NOT_FOUND, "No source folder has that row.")
            tab.roots_list.setCurrentRow(row)
        elif action in {"view", "preview"}:
            _set_view(tab, args)
        button = {
            "add_source": tab.add_root_button, "remove_source": tab.remove_root_button, "rescan": tab.rescan_button,
            "preview": tab.preview_final_button, "refresh_targets": tab.refresh_targets_button,
            "use_archive_selection": tab.use_archive_selection_button, "open_editor": tab.open_editor_button,
            "open_target": tab.open_target_archive_button,
        }.get(action)
        if action == "open_source_in_editor":
            if "row" in args:
                select_tree_rows(tab.records_tree, [args["row"]])
            source = tab.current_source_path()
            if source is None or not source.is_file():
                raise ToolError(UNAVAILABLE, "Select an icon source file first.")
            tab.open_selected_in_texture_editor()
        if button is not None:
            press(button)
        return _state(tab, {})

    return ui(call, change, answers)


def _export(call):
    from cdmw.ui.item_icons.tab import _safe_relative_target_path

    args = call.arguments
    folder = output(call, args["folder"], folder=True)

    def export():
        from cdmw.domain.output_paths import game_path_reason

        tab = page(call, "item_icons")
        _set_view(tab, args)
        target = tab._current_target_path()
        if not target or tab.current_source_path() is None:
            raise ToolError(UNAVAILABLE, "Choose a source image and an existing target icon path.")
        destination = folder / _safe_relative_target_path(target)
        reason = game_path_reason(destination, game_folder=call.context.game_folder())
        if reason or destination.exists():
            from cdmw.mcp.errors import REFUSED

            raise ToolError(REFUSED, reason or f"An icon already exists at {destination}.")
        if not tab.export_generated_button.isEnabled():
            raise ToolError(UNAVAILABLE, tab.export_generated_button.toolTip() or "An icon output is already running.")
        tab._mcp_icon_output = None

        def notify(dialog):
            record = run_action(call.context, dialog)
            tab._mcp_icon_output = record.get("asked", [])

        tab.export_generated_icon(notify=notify)
        return {**_state(tab, {}), "destination": str(destination)}

    return ui(call, export, {"folder": str(folder)})


def item_icon_tools():
    view = {"row": ROW, "target": PATH, "filter": TEXT,
            "background": choices("auto_transparent", "keep_source", "target_underlay")}
    return [
        tool("item_icons.state", READ, "Read icon sources, current target and preview status.",
             "ui:ItemIconLibraryTab.records_tree", _read,
             {"offset": ROW, "count": {"type": "integer", "minimum": 1, "maximum": 500}}),
        tool("item_icons.change", EDIT, "Manage source folders and set or preview the selected icon and view.",
             "ui:ItemIconLibraryTab", _change,
             {**view, "action": choices("add_source", "remove_source", "rescan", "view", "preview",
                                        "refresh_targets", "use_archive_selection", "open_editor", "open_target",
                                        "open_source_in_editor"),
              "folder": PATH}, ("action",)),
        tool("item_icons.make", OUTPUT, "Make and export a compatible icon using the selected source and target.",
             "ui:ItemIconLibraryTab.export_generated_button", _export,
             {**view, "folder": PATH}, ("folder",), output_folders=("folder",)),
    ]
