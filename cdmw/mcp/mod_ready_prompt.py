"""Answer Browse Archives' mod-ready export prompt for a typed tool.

Saving as a mod (HKX physics, sound banks and other Browse Archives writers) asks for the
parent export folder and the package details in one dialog. A typed tool fills that
dialog's own fields and presses its Continue button, so the dialog's checks apply. The
folder chooser that comes first when no export folder is set yet is answered with the
same folder.
"""

from __future__ import annotations

from pathlib import Path

from cdmw.mcp.rail_actions import TEXT

PROMPT = "layout_cdmw_ui_archive_browser_mod_ready_export__prompt_archive_mod_ready_export_target_dialog"

# The prompt's line edits, in the order the dialog creates them.
FIELDS = ("folder", "title", "version", "author", "description")

SCHEMA = {"title": TEXT, "version": TEXT, "author": TEXT, "description": TEXT}


def answers(arguments) -> dict[str, object]:
    """Answers for the folder chooser that may come before the prompt."""

    return {"folder": str(arguments["folder"])}


def dialogs(arguments, asked: list | None = None) -> dict[str, object]:
    """A dialogs map that fills and accepts the mod-ready export prompt."""

    from PySide6.QtWidgets import QLineEdit, QPushButton

    def fill(dialog):
        edits = dialog.findChildren(QLineEdit)
        if len(edits) < len(FIELDS):
            raise RuntimeError("The mod-ready export prompt has changed; CDMW cannot fill it.")
        values = {"folder": str(Path(str(arguments["folder"])))}
        values.update({key: str(arguments[key]).strip() for key in FIELDS[1:] if arguments.get(key)})
        for key, edit in zip(FIELDS, edits):
            if key in values:
                edit.setText(values[key])
        if asked is not None:
            asked.append({"kind": "mod_ready_export", "title": dialog.windowTitle(),
                          "answer": {key: edit.text() for key, edit in zip(FIELDS, edits)}})
        button = next((b for b in dialog.findChildren(QPushButton) if b.text() == "Continue"), None)
        if button is None:
            raise RuntimeError("The mod-ready export prompt has no Continue button.")
        button.click()
        return dialog.result()

    return {PROMPT: fill}


def children(folder) -> dict[str, int]:
    """The folder's direct children and their change times, to spot what a save added."""

    try:
        return {child.name: child.stat().st_mtime_ns for child in Path(str(folder)).iterdir()}
    except OSError:
        return {}


__all__ = ["FIELDS", "PROMPT", "SCHEMA", "answers", "children", "dialogs"]
