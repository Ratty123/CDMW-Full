"""Read notes and format reports from the existing rail pages."""

from __future__ import annotations

from cdmw.mcp.errors import NOT_FOUND, ToolError
from cdmw.mcp.names import READ
from cdmw.mcp.rail_actions import PATH, ROW, choices, page, tool, ui
from cdmw.mcp.read_tools import to_data


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


def _read(call):
    return ui(call, lambda: _formats(call) if call.arguments["action"] == "formats" else _notes(call))


def research_tools():
    return [
        tool("research.read", READ, "Read Asset Research notes or Inspect File Formats reports as text.",
             "ui:ResearchTab.notes_tree,FormatExplorerTab.detail", _read,
             {"action": choices("notes", "formats"), "key": PATH, "offset": ROW,
              "count": {"type": "integer", "minimum": 1, "maximum": 500}}, ("action",)),
    ]
