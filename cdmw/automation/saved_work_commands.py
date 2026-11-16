"""Automation commands for Drafts & Mods and a set session's parts (test runs only).

They do what a click would: show the page, select rows, press Combine into One
Mod, fill its dialog, and select whole parts in the shown Mesh Editor document.
Like every bridge command they run on the UI thread and only exist while the
automation bridge runs under a private test profile with its token.
"""

from __future__ import annotations

from pathlib import Path


def _saved_work_page(window, *, create: bool):
    from cdmw.ui.shell.lazy_tool_tab import LazyToolTab, created_tool_widget

    holder = getattr(window.shell, "saved_work_tab", None)
    page = created_tool_widget(holder)
    if page is None and create and isinstance(holder, LazyToolTab):
        window.shell._activate_tool_key("saved_work")
        # The tab builds its page on a timer after it is shown; build it now, or let a
        # load already under way finish.
        try:
            page = holder.ensure_widget()
        except RuntimeError:
            import time

            from PySide6.QtWidgets import QApplication

            deadline = time.monotonic() + 20.0
            while page is None and time.monotonic() < deadline:
                QApplication.processEvents()
                page = created_tool_widget(holder)
                time.sleep(0.01)
    return page


def saved_work_rows(window, args: dict) -> dict[str, object]:
    """Show Drafts & Mods (refreshing it when ``refresh``) and list its rows as the table shows them."""

    from cdmw.ui.mesh_editor.saved_work_page import _GAME_FILES_ROLE

    page = _saved_work_page(window, create=True)
    if page is None:
        raise RuntimeError("Drafts & Mods is not available.")
    window.shell._activate_tool_key("saved_work")
    if args.get("refresh"):
        page.refresh()
    table = page.table
    header = [table.horizontalHeaderItem(column).text() for column in range(table.columnCount())]
    game_column = header.index("Game file")
    from cdmw.ui.mesh_editor.saved_work_page import _ROW_KEY_ROLE, _row_key

    roots = {_row_key(row): str(row.mod_root or "") for row in page.rows()}
    shown = []
    for index in range(table.rowCount()):
        cells = [table.item(index, column) for column in range(table.columnCount())]
        game = cells[game_column]
        shown.append({
            "mod_root": roots.get(cells[0].data(_ROW_KEY_ROLE), "") if cells[0] is not None else "",
            "cells": [cell.text() if cell is not None else "" for cell in cells],
            "game_file_tooltip": game.toolTip() if game is not None else "",
            "game_files": list(game.data(_GAME_FILES_ROLE) or ()) if game is not None else [],
            "game_file_drawn": _drawn_game_file_text(table, index, game_column),
        })
    return {
        "header": header,
        "shown": shown,
        "rows": [{
            "display_name": row.display_name,
            "kind": row.kind,
            "built": bool(row.is_built_mod),
            "mod_root": str(row.mod_root or ""),
            "game_files": list(row.game_files),
        } for row in page.rows()],
        "combine_reason": page.combine_reason(),
    }


def _drawn_game_file_text(table, row: int, column: int) -> str:
    """The text the Game file delegate draws in that cell at its current width."""

    from PySide6.QtWidgets import QStyleOptionViewItem

    index = table.model().index(row, column)
    delegate = table.itemDelegateForColumn(column)
    if delegate is None or not index.isValid():
        return ""
    option = QStyleOptionViewItem()
    option.initFrom(table.viewport())
    option.rect = table.visualRect(index)
    delegate.initStyleOption(option, index)
    return str(option.text)


def saved_work_combine(window, args: dict) -> dict[str, object]:
    """Select the built mods whose folders are ``mod_roots`` and press Combine into One Mod."""

    page = _saved_work_page(window, create=True)
    if page is None:
        raise RuntimeError("Drafts & Mods is not available.")
    wanted = {str(Path(str(path)).resolve()).casefold() for path in args.get("mod_roots") or ()}
    rows = [row for row in page.rows()
            if row.mod_root is not None and str(Path(row.mod_root).resolve()).casefold() in wanted]
    page.table.clearSelection()
    for row in rows:
        _add_row_to_selection(page, row)
    reason = page.combine_reason()
    if not reason:
        page.combine_button.click()
    return {"selected": len(rows), "reason": reason, "started": page.combine_flow.busy}


def _add_row_to_selection(page, row) -> None:
    from PySide6.QtCore import QItemSelectionModel

    from cdmw.ui.mesh_editor.saved_work_page import _ROW_KEY_ROLE, _row_key

    model = page.table.selectionModel()
    flags = QItemSelectionModel.SelectionFlag.Select | QItemSelectionModel.SelectionFlag.Rows
    for index in range(page.table.rowCount()):
        if page.table.item(index, 0).data(_ROW_KEY_ROLE) == _row_key(row):
            model.select(page.table.model().index(index, 0), flags)


def saved_work_combine_state(window, _args: dict) -> dict[str, object]:
    """The Combine into One Mod dialog as shown: its stage, message and file lists."""

    page = _saved_work_page(window, create=False)
    flow = getattr(page, "combine_flow", None)
    dialog = getattr(flow, "dialog", None)
    if dialog is None:
        return {"open": False}

    def items(widget) -> list[str]:
        return [widget.item(index).text() for index in range(widget.count())]

    return {
        "open": True,
        "stage": dialog.stage,
        "status": dialog.status_label.text(),
        "layout": dialog.layout_value.text(),
        "files": items(dialog.files_list),
        "shared": items(dialog.shared_list),
        "combine_enabled": dialog.combine_button.isEnabled(),
    }


def saved_work_combine_answer(window, args: dict) -> bool:
    """Answer the open dialog: ``write`` with ``title`` into ``output_dir`` (inside the run's
    profile, no ZIP), or cancel it."""

    from cdmw.app.app_folder import cdmw_folder

    page = _saved_work_page(window, create=False)
    dialog = getattr(getattr(page, "combine_flow", None), "dialog", None)
    if dialog is None:
        return False
    if not args.get("write"):
        dialog.cancel_button.click()
        return True
    output = Path(str(args["output_dir"]))
    if not output.is_absolute() or not output.resolve().is_relative_to(cdmw_folder()):
        raise ValueError("A combined mod is written inside the run's own profile folder only.")
    dialog.title_edit.setText(str(args.get("title") or "Combined mod"))
    dialog.folder_edit.setText(str(output))
    dialog.zip_check.setChecked(False)
    if not dialog.combine_button.isEnabled():
        return False
    dialog.combine_button.click()
    return True


def select_whole_parts(window, args: dict) -> bool:
    """Select whole parts (by part number) in the shown Mesh Editor document, as a click on
    their rows in its Parts list does."""

    from cdmw.ui.shell.lazy_tool_tab import created_tool_widget

    view = created_tool_widget(window.shell.mesh_editor_tab)
    tab = getattr(view, "active", None) or view
    if tab is None or not getattr(tab, "standalone_rust_ready", False):
        return False
    indices = sorted({int(index) for index in args.get("indices") or ()})
    return bool(tab._send_rust_message(
        tab._rust_host_message("select_parts", request_id=0, extra={"indices": indices})))
