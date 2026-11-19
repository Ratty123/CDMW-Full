"""Search File Text through the page's options, results and export worker."""

from __future__ import annotations

from cdmw.mcp.errors import REFUSED, UNAVAILABLE, ToolError
from cdmw.mcp.names import EDIT, OUTPUT, READ
from cdmw.mcp.rail_actions import BOOL, PATH, ROW, ROWS, TEXT, choices, choose, output, page, press
from cdmw.mcp.rail_actions import select_tree_rows, tool, ui, window


def _state(tab, *, offset=0, limit=100):
    tree = tab.results_tree
    rows = [
        {"row": index, "file": item.text(0), "matches": item.text(1), "package": item.text(2),
         "path": item.text(3), "extension": item.text(4)}
        for index in range(offset, min(offset + limit, tree.topLevelItemCount()))
        if (item := tree.topLevelItem(index)) is not None
    ]
    preview = tab.preview_text_cache or ""
    return {"busy": tab.is_busy(), "status": tab.search_progress_label.text(),
            "preview_path": tab.current_result_path(), "preview_text": preview[:32000],
            "preview_truncated": len(preview) > 32000,
            "summary": tab.results_summary_label.text(), "total": tree.topLevelItemCount(), "rows": rows}


def _read(call):
    return call.context.ui_call(lambda: _state(page(call, "text_search"), offset=call.arguments.get("offset", 0),
                                               limit=call.arguments.get("count", 100)))


def _change(call):
    args = call.arguments

    def change():
        tab = page(call, "text_search")
        action = args["action"]
        if action == "start":
            if "source" in args:
                choose(tab.source_combo, args["source"])
            tab.query_edit.setText(args.get("query", ""))
            for key, control in (("path_filter", tab.path_filter_edit), ("extensions", tab.extensions_edit),
                                 ("loose_root", tab.loose_root_edit)):
                if key in args:
                    control.setText(args[key])
            for key, control in (("case_sensitive", tab.case_sensitive_checkbox), ("regex", tab.regex_checkbox)):
                if key in args:
                    control.setChecked(args[key])
            press(tab.search_button)
        elif action == "stop":
            press(tab.stop_button)
        elif action == "clear_log":
            press(tab.clear_log_button)
        else:
            if "row" in args:
                select_tree_rows(tab.results_tree, [args["row"]])
            if action == "open_hit":
                hit = tab.current_result()
                if hit is None or hit.source_kind != "archive":
                    raise ToolError(UNAVAILABLE, "Select a result from the game archives.")
                window(call).textures._show_archive_browser_from_texture_editor(hit.relative_path, hit.archive_entry)
            else:
                if "preview_query" in args:
                    tab.preview_find_edit.setText(args["preview_query"])
                for key, control in (("preview_case_sensitive", tab.preview_find_case_checkbox),
                                     ("wrap", tab.preview_wrap_checkbox)):
                    if key in args:
                        control.setChecked(args[key])
                if "preview_step" in args:
                    press({"next": tab.preview_find_next_button, "previous": tab.preview_find_prev_button,
                           "larger": tab.preview_font_larger_button,
                           "smaller": tab.preview_font_smaller_button}[args["preview_step"]])
        return _state(tab, limit=0)

    return ui(call, change)


def _export(call):
    args = call.arguments
    target = output(call, args["folder"], folder=True)
    if any(target.iterdir()):
        raise ToolError(REFUSED, "Choose an empty folder so the export cannot replace files.")

    def export():
        tab = page(call, "text_search")
        tab.export_root_edit.setText(str(target))
        if "rows" in args:
            select_tree_rows(tab.results_tree, args["rows"])
            press(tab.export_selected_button)
        else:
            press(tab.export_all_button)
        return _state(tab, limit=0)

    return ui(call, export, {"confirm": "yes"})


def text_search_tools():
    return [
        tool("search.text_state", READ, "Read Search File Text progress and result rows.", "ui:TextSearchTab.results_tree",
             _read, {"offset": ROW, "count": {"type": "integer", "minimum": 1, "maximum": 500}}),
        tool("search.text_action", EDIT, "Start or stop Search File Text, open an archive hit, set preview options, "
             "or clear its log. Row indexes come from search_text_state.", "ui:TextSearchTab", _change,
             {"action": choices("start", "stop", "open_hit", "preview", "clear_log"), "source": choices("archive", "loose"),
              "query": TEXT, "path_filter": TEXT, "extensions": TEXT, "loose_root": PATH, "case_sensitive": BOOL,
              "regex": BOOL, "row": ROW, "preview_query": TEXT, "preview_case_sensitive": BOOL, "wrap": BOOL,
              "preview_step": choices("next", "previous", "larger", "smaller")}, ("action",)),
        tool("search.text_export", OUTPUT, "Export selected matched files, or all matched files, using Search File Text.",
             "ui:TextSearchTab.export_all_results", _export, {"folder": PATH, "rows": ROWS}, ("folder",),
             output_folders=("folder",)),
    ]
