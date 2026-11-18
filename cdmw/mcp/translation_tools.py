"""Typed access to the Edit Translations table, translation dialog and export."""

from __future__ import annotations

from cdmw.mcp.errors import NOT_FOUND, UNAVAILABLE, ToolError
from cdmw.mcp.names import EDIT, OUTPUT, READ
from cdmw.mcp.rail_actions import BOOL, PATH, ROW, ROWS, TEXT, choices, choose, output, page, press, required, tool, ui


def _state(tab, args):
    model = tab.model
    offset = args.get("offset", 0)
    count = args.get("count", 0)
    rows = []
    for index in range(offset, min(offset + count, model.rowCount())):
        row = model.catalogue.row(model.entry_index(index))
        rows.append({"row": index, "entry": model.entry_index(index), "key": row.key, "text": row.text,
                     "category": row.category, "reference": row.reference, "edited": row.edited})
    machine = getattr(tab, "_mcp_translation_dialog", None)
    return {"language": model.catalogue.language if model.catalogue is not None else "",
            "languages": [tab.language_box.itemText(i) for i in range(tab.language_box.count())],
            "busy": any((tab._thread, tab._language_thread, tab._export_thread,
                         machine._thread if machine is not None else None)),
            "total": model.rowCount(), "status": tab.status_label.text(), "changes": tab.pending_label.text(),
            "export": tab.export_note.text(), "translation": machine.log.toPlainText() if machine is not None else "",
            "rows": rows}


def _review(call):
    args = {"count": 100, **call.arguments}
    return call.context.ui_call(lambda: _state(page(call, "translation_studio"), args))


def _loaded(tab):
    machine = getattr(tab, "_mcp_translation_dialog", None)
    if (tab.model.catalogue is None or tab._thread is not None or tab._export_thread is not None
            or (machine is not None and machine._thread is not None)):
        raise ToolError(UNAVAILABLE, "Load a language table and wait for its current operation to finish.")
    return tab.model.catalogue


def _replace(call):
    args = call.arguments
    needle = required(args, "find")
    replacement = args.get("text", "")

    def snapshot():
        tab = page(call, "translation_studio")
        catalogue = _loaded(tab)
        indexes = [tab.model.entry_index(row) for row in args.get("rows", range(tab.model.rowCount()))]
        if None in indexes:
            raise ToolError(NOT_FOUND, "A requested line is absent from the current table.")
        return catalogue, {index: catalogue.text_at(index) for index in indexes}

    catalogue, before = call.context.ui_call(snapshot)
    changes = {index: old.replace(needle, replacement) for index, old in before.items()
               if needle in old and needle != replacement}

    def apply():
        tab = page(call, "translation_studio")
        if _loaded(tab) is not catalogue or any(catalogue.text_at(index) != before[index] for index in changes):
            raise ToolError(UNAVAILABLE, "The translation table changed while replacements were prepared.")
        tab.apply_ai_translations(changes)
        return _state(tab, {})

    return ui(call, apply)


def _edit(call):
    from PySide6.QtWidgets import QDialog
    from tools.translation_studio.ai_panel import TranslateDialog
    from tools.translation_studio.table_model import TEXT as TEXT_COLUMN

    args = call.arguments
    action = args["action"]
    if action == "replace":
        return _replace(call)
    answers = {"confirm": "yes" if args.get("discard_edits") else "no"}
    if action == "open":
        answers["file"] = required(args, "path")
        if "game_path" in args:
            answers["text"] = args["game_path"]

    def start_machine(dialog):
        from PySide6.QtCore import Qt
        from cdmw.ui.shell.close_controller import register_transient_worker_controller
        from cdmw.mcp.rail_actions import window

        tab = page(call, "translation_studio")
        dialog.target_box.setCurrentText(required(args, "target_language"))
        dialog.source_box.setText(args.get("source_language", ""))
        dialog.instructions.setText(args.get("instructions", ""))
        dialog.skip_mismatch.setChecked(args.get("keep_markup", True))
        press(dialog.start_button)
        previous = getattr(tab, "_mcp_translation_dialog", None)
        if previous is not None:
            previous.deleteLater()
        tab._mcp_translation_dialog = dialog
        if dialog._thread is not None:
            register_transient_worker_controller(window(call).shell, dialog)
            dialog.finished.connect(tab._refresh_view)
            dialog._thread.finished.connect(dialog.accept, Qt.ConnectionType.QueuedConnection)
            dialog.open()
        return QDialog.DialogCode.Accepted

    def change():
        tab = page(call, "translation_studio")
        machine = getattr(tab, "_mcp_translation_dialog", None)
        if action == "stop_translation":
            if machine is None:
                raise ToolError(UNAVAILABLE, "No AI translation is running.")
            press(machine.stop_button)
        elif machine is not None and machine._thread is not None:
            raise ToolError(UNAVAILABLE, "Wait for the translation pass to finish, or stop it first.")
        elif action == "refresh_languages":
            press(tab.refresh_button)
        elif action == "open":
            press(tab.open_file_button)
        elif action == "load":
            choose(tab.language_box, required(args, "language"))
            if "reference" in args:
                choose(tab.reference_box, args["reference"])
            press(tab.load_button)
        else:
            _loaded(tab)
            model = tab.model
            if action == "search":
                if "query" in args:
                    tab.search_box.setText(args["query"])
                if "category" in args:
                    choose(tab.category_box, args["category"])
                if "edited_only" in args:
                    tab.edited_only.setChecked(args["edited_only"])
            elif action == "reset":
                press(tab.reset_button)
            else:
                row = required(args, "row")
                if model.entry_index(row) is None:
                    raise ToolError(NOT_FOUND, "A requested line is absent from the current table.")
                tab.table.selectRow(row)
                if action == "set":
                    model.setData(model.index(row, TEXT_COLUMN), args.get("text", ""))
                elif action == "revert":
                    press(tab.revert_button)
                else:
                    press(tab.ai_button)
        return _state(tab, {})

    return ui(call, change, answers, dialogs={TranslateDialog: start_machine})


def _save(call):
    args = call.arguments
    folder = output(call, args["folder"], folder=True)

    def save():
        tab = page(call, "translation_studio")
        machine = getattr(tab, "_mcp_translation_dialog", None)
        if machine is not None and machine._thread is not None:
            raise ToolError(UNAVAILABLE, "Wait for the translation pass to finish.")
        if "name" in args:
            tab.mod_name.setText(args["name"])
        if "author" in args:
            tab.mod_author.setText(args["author"])
        from tools.translation_studio.tab import _PACKAGE_MANAGERS

        name = tab.mod_name.text().strip() or "Translation tweak"
        for manager in _PACKAGE_MANAGERS:
            output(call, folder / f"{name} - {manager}")
        press(tab.export_button)
        return _state(tab, {})

    return ui(call, save, {"folder": str(folder)})


def translation_tools():
    return [
        tool("translation.edit", EDIT, "Open or load a table, filter lines, edit or replace text, revert, reset, "
             "or machine-translate a selected row using the provider configured in Edit Translations.",
             "ui:TranslationStudioTab", _edit,
             {"action": choices("open", "load", "refresh_languages", "search", "set", "replace", "revert", "reset",
                                "translate", "stop_translation"),
              "path": PATH, "game_path": TEXT, "discard_edits": BOOL, "language": TEXT, "reference": TEXT,
              "query": TEXT, "category": {"type": ["string", "integer", "null"]}, "edited_only": BOOL,
              "row": ROW, "rows": ROWS, "text": {"type": "string", "maxLength": 65536}, "find": PATH,
              "source_language": TEXT, "target_language": TEXT, "instructions": TEXT, "keep_markup": BOOL},
             ("action",)),
        tool("translation.review", READ, "Review the shown lines, pending edits, and translation or export progress.",
             "ui:TranslationStudioTab.model", _review,
             {"offset": ROW, "count": {"type": "integer", "minimum": 1, "maximum": 500}}),
        tool("translation.save", OUTPUT, "Build the translation mod from the open table using Edit Translations.",
             "ui:TranslationStudioTab.export_button", _save,
             {"folder": PATH, "name": TEXT, "author": TEXT}, ("folder",), output_folders=("folder",)),
    ]
