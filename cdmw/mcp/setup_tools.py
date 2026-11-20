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


def _wait(call, done, what: str, outcome) -> None:
    deadline = time.monotonic() + WAIT_S
    while not call.context.ui_call(done):
        call.check_cancelled()
        if time.monotonic() > deadline:
            raise ToolError(FAILED, f"{what} did not finish in time. CDMW's status line says why.", outcome)
        time.sleep(0.05)


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
    _wait(call, lambda: target.exists() and target.stat().st_mtime_ns != before, "Export Language File", outcome)
    return {**outcome, "saved": str(target)}


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

    _wait(call, done, "Import Language File", outcome)
    return {**outcome, "language": code, "name": name}


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
