"""Setup and language files as typed tools (MCP gap plan item 16).

``app.workspace_init`` presses Init Workspace with its folder chooser answered, as the
Setup panel does: CDMW creates its workspace folders there and points its paths at
them. ``app.language_export`` and ``app.language_import`` press Settings > Appearance's
Export and Import Language File buttons. Helper locations (Blender, DMM) are set
through ``app_settings_set``, which checks them first.
"""

from __future__ import annotations

import time
from pathlib import Path

from cdmw.mcp.errors import FAILED, INVALID_ARGUMENTS, UNAVAILABLE, ToolError
from cdmw.mcp.names import EDIT, OUTPUT
from cdmw.mcp.rail_actions import PATH, page, press, tool, ui, window
from cdmw.mcp.tools import ON_WORKER

WAIT_S = 60.0


REPORT_WAIT_S = 5.0


def _take_report(call, title: str):
    """Read and close the message box a finished language task shows (UI thread)."""

    from PySide6.QtWidgets import QApplication, QMessageBox

    shell = getattr(window(call), "shell", None)
    localizer = getattr(shell, "ui_localizer", None)
    titles = {title, localizer.translate(title)} if localizer is not None else {title}
    box = QApplication.activeModalWidget()
    if isinstance(box, QMessageBox) and box.windowTitle() in titles:
        row = {"text": box.text(), "warning": box.icon() in (QMessageBox.Icon.Warning, QMessageBox.Icon.Critical)}
        box.accept()
        return row
    return None


def _wait(call, done, what: str, outcome, report: str = "") -> dict | None:
    """Wait for ``done``; a language task also reports in a message box, which the tool reads and
    closes, so the interface is not left waiting on a box nobody answers."""

    deadline = time.monotonic() + WAIT_S
    shown = None
    while not call.context.ui_call(done):
        call.check_cancelled()
        if report and (shown := call.context.ui_call(lambda: _take_report(call, report))) and shown["warning"]:
            raise ToolError(FAILED, shown["text"], outcome)
        if time.monotonic() > deadline:
            raise ToolError(FAILED, f"{what} did not finish in time. CDMW's status line says why.", outcome)
        time.sleep(0.05)
    if report and shown is None:
        until = time.monotonic() + REPORT_WAIT_S
        while shown is None and time.monotonic() < until:
            call.check_cancelled()
            shown = call.context.ui_call(lambda: _take_report(call, report))
            time.sleep(0.05)
    return shown


def _workspace(call):
    folder = Path(str(call.arguments["folder"]))
    if not folder.is_dir():
        raise ToolError(INVALID_ARGUMENTS, f"The workspace folder does not exist: {folder}")

    def start():
        current = window(call)
        button = getattr(getattr(current, "textures", None), "init_workspace_button", None)
        if button is None:
            raise ToolError(UNAVAILABLE, "The Setup panel is not available.")
        before = current.textures.output_root_edit.text()
        press(button)
        return {"before": before}

    outcome = ui(call, start, {"folder": str(folder)})
    before = outcome.pop("before", "")

    def done():
        text = window(call).textures.output_root_edit.text().strip()
        return bool(text) and text != before and Path(text).is_relative_to(folder)

    _wait(call, done, "Init Workspace", outcome)

    def paths():
        textures = window(call).textures
        return {"original_dds_root": textures.original_dds_edit.text(), "png_root": textures.png_root_edit.text(),
                "output_root": textures.output_root_edit.text(),
                "dds_staging_root": textures.dds_staging_root_edit.text(),
                "archive_extract_root": window(call).archive.archive_extract_root_edit.text()}

    return {**outcome, "folder": str(folder), "paths": call.context.ui_call(paths)}


def _export(call):
    target = Path(str(call.arguments["save_file"]))
    if target.suffix.lower() != ".json":
        raise ToolError(INVALID_ARGUMENTS, "Save the language file as a .json file.")
    before = target.stat().st_mtime_ns if target.exists() else None
    outcome = ui(call, lambda: press(page(call, "settings").export_language_button) or {},
                 {"save_file": str(target)})
    shown = _wait(call, lambda: target.exists() and target.stat().st_mtime_ns != before, "Export Language File",
                  outcome, report="Export Language File")
    return {**outcome, "saved": str(target), "report": (shown or {}).get("text", "")}


def _import(call):
    from cdmw.services.localization_file_service import load_language_file, safe_language_code

    source = Path(str(call.arguments["file"]))
    if not source.is_file():
        raise ToolError(INVALID_ARGUMENTS, f"There is no language file {source}.")
    try:
        code, name, _translations = load_language_file(source)
    except (OSError, ValueError) as exc:
        raise ToolError(INVALID_ARGUMENTS, f"This is not a CDMW language file: {exc}") from None
    code = safe_language_code(code)
    outcome = ui(call, lambda: press(page(call, "settings").import_language_button) or {}, {"file": str(source)})

    def done():
        shell = window(call).shell
        controller = getattr(shell, "_language_task_controller", None)
        settled = controller is None or not controller.active
        return settled and str(shell.settings.value("appearance/language", "") or "") == code

    shown = _wait(call, done, "Import Language File", outcome, report="Import Language File")
    return {**outcome, "language": code, "name": name, "report": (shown or {}).get("text", "")}


def setup_tools():
    return [
        tool("app.workspace_init", OUTPUT,
             "Press Init Workspace: create CDMW's workspace folders inside folder (an existing folder outside the "
             "game folder) and point the texture and extraction paths at them.",
             "ui:textures.init_workspace_button", _workspace,
             {"folder": PATH}, ("folder",), output_folders=("folder",), runs_on=ON_WORKER),
        tool("app.language_export", OUTPUT,
             "Press Export Language File in Settings > Appearance: write the current language's text table to "
             "save_file (.json) for translating.",
             "ui:SettingsTab.export_language_button", _export,
             {"save_file": PATH}, ("save_file",), output_paths=("save_file",), runs_on=ON_WORKER),
        tool("app.language_import", EDIT,
             "Press Import Language File in Settings > Appearance: install a translated language file and switch "
             "CDMW to it. Longer translations can crowd buttons and dialogs.",
             "ui:SettingsTab.import_language_button", _import,
             {"file": PATH}, ("file",), runs_on=ON_WORKER),
    ]


__all__ = ["setup_tools"]
