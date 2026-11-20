"""Read notes and format reports from the existing rail pages."""

from __future__ import annotations

from cdmw.mcp.errors import INVALID_ARGUMENTS, NOT_FOUND, UNAVAILABLE, ToolError
from cdmw.mcp.names import EDIT, OUTPUT, READ
from cdmw.mcp.rail_actions import PATH, ROW, TEXT, choices, output, page, press, required, tool, ui
from cdmw.mcp.read_tools import to_data
from cdmw.mcp.tools import ON_WORKER


def _notes(call):
    tab = page(call, "research")
    from cdmw.ui.research.notes_state import sorted_research_note_items

    items = sorted_research_note_items(tab.notes)
    key = call.arguments.get("key")
    if key:
        for note_key, note in items:
            if note_key == key:
                return {"key": note_key, "note": to_data(note), "text": note.note}
        raise ToolError(NOT_FOUND, f"No research note has the key {key!r}.")
    start = call.arguments.get("offset", 0)
    end = start + call.arguments.get("count", 100)
    return {"total": len(items), "notes": [{"key": key, **to_data(note)} for key, note in items[start:end]]}


def _formats(call):
    tab = page(call, "format_explorer")
    args = call.arguments
    key = args.get("key")
    if key:
        # Read all the matching extensions, regardless of the user's previous filters.
        tab.search_box.setText(key)
        tab.group_box.setCurrentIndex(0)
        tab.editable_only.setChecked(False)
        tab.include_absent.setChecked(True)
        for index, row in enumerate(tab._shown):
            if row.extension.casefold().lstrip(".") == key.casefold().lstrip("."):
                tab.table.selectRow(index)
                return {"format": to_data(row), "text": tab.detail.toPlainText()}
        raise ToolError(NOT_FOUND, f"No format report matches {key!r}.")
    start = args.get("offset", 0)
    end = start + args.get("count", 100)
    return {"total": len(tab._shown), "formats": [to_data(row) for row in tab._shown[start:end]]}


def _status(tab) -> dict[str, object]:
    return {"busy": {"refresh": tab.refresh_thread is not None, "references": tab.resolve_thread is not None,
                     "ui_constraints": tab.ui_constraint_thread is not None},
            "references_status": tab.reference_status_label.text(),
            "ui_constraints_status": tab.ui_constraint_status_label.text()}


def _rows(call, rows, name):
    start = call.arguments.get("offset", 0)
    end = start + call.arguments.get("count", 100)
    rows = list(rows or ())
    return {"total": len(rows), name: [to_data(row) for row in rows[start:end]]}


def _read(call):
    action = call.arguments["action"]

    def read():
        if action == "formats":
            return _formats(call)
        if action == "notes":
            return _notes(call)
        tab = page(call, "research")
        if action == "status":
            return _status(tab)
        if action == "references":
            payload = tab.reference_payload or {}
            return {**_rows(call, payload.get("reference_rows"), "references"),
                    "sidecars": [to_data(row) for row in payload.get("sidecar_rows") or ()][:200],
                    "target": tab.reference_target_edit.text(), **_status(tab)}
        return {**_rows(call, tab.research_payload.get("ui_constraint_rows"), "ui_constraints"), **_status(tab)}

    return ui(call, read)


def _change(call):
    args = call.arguments
    action = args["action"]

    def change():
        tab = page(call, "research")
        if action == "refresh":
            press(tab.refresh_button)
        elif action == "scan_ui_constraints":
            press(tab.ui_constraint_refresh_button)
        elif action == "resolve":
            if tab.resolve_thread is not None:
                raise ToolError(UNAVAILABLE, "References are still being resolved; wait for research_read status.")
            tab.reference_target_edit.setText(required(args, "path"))
            press(tab.reference_resolve_button)
        else:  # save_note: the Notes panel's fields and Save Note
            tab.notes_target_edit.setText(required(args, "path"))
            tab.notes_source_label.setText("manual")
            tab.notes_tags_edit.setText(args.get("tags", ""))
            tab.notes_edit.setPlainText(args.get("text", ""))
            press(tab.notes_save_button)
        return _status(tab)

    return ui(call, change)


def _export(call):
    target = output(call, call.arguments["save_file"])
    suffix = target.suffix.lower()
    if suffix not in {".csv", ".json"}:
        raise ToolError(INVALID_ARGUMENTS, "Save the report as a .csv or .json file.")

    def export():
        tab = page(call, "research")
        button = tab.export_report_csv_button if suffix == ".csv" else tab.export_report_json_button
        if not button.isEnabled():
            raise ToolError(UNAVAILABLE, "Run a research refresh first; the texture analysis report is empty.")
        press(button)
        return _status(tab)

    import time

    before = target.stat().st_mtime_ns if target.exists() else None
    outcome = ui(call, export, {"save_file": str(target)})
    deadline = time.monotonic() + 120
    while not (target.exists() and target.stat().st_mtime_ns != before):
        call.check_cancelled()
        if time.monotonic() > deadline:
            raise ToolError(UNAVAILABLE, "The report export did not finish in time; CDMW's status line says why.",
                            outcome)
        time.sleep(0.05)
    return {**outcome, "saved": str(target)}


def research_tools():
    return [
        tool("research.read", READ, "Read Asset Research notes, Inspect File Formats reports, the resolved "
             "references of the last Resolve, the UI rect constraint rows, or what Research is busy with (status).",
             "ui:ResearchTab.notes_tree,FormatExplorerTab.detail", _read,
             {"action": choices("notes", "formats", "references", "ui_constraints", "status"), "key": PATH,
              "offset": ROW, "count": {"type": "integer", "minimum": 1, "maximum": 500}}, ("action",)),
        tool("research.change", EDIT, "Asset Research: refresh the research data, scan UI rect references, resolve "
             "the references of an archive path, or save a note (path, tags, text; an empty note removes the saved "
             "one). Work runs in the background; follow it with research_read status.",
             "ui:ResearchTab", _change,
             {"action": choices("refresh", "scan_ui_constraints", "resolve", "save_note"), "path": PATH,
              "tags": TEXT, "text": {"type": "string", "maxLength": 20000}}, ("action",)),
        tool("research.export", OUTPUT, "Export the texture analysis report (Export Report CSV or JSON) to save_file.",
             "ui:ResearchTab.export_report_json_button", _export, {"save_file": PATH}, ("save_file",),
             output_paths=("save_file",), runs_on=ON_WORKER),
    ]
