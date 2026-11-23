"""Browse Archives' right-click actions as registry commands (MCP gap plan item 6).

The file tree's right-click menu (``actions.py``) offers many actions that no
button has: Open Prefab Inspector, Add Bones, the sound and action chart
entries and more. Each gets a command here, on the file that is selected
(the current row of the tree), with the same handler its menu entry runs. A
command's reason is empty exactly when the menu offers the entry for that
file, and otherwise says why, so the Command Palette, ``commands_list`` and
``app_run_command`` show the same state the menu does.
``tests/test_browse_context_commands.py`` checks that against the real menu.

The Action Charts button's menu entries work with nothing selected; their
commands follow the button.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from cdmw.ui.commands.registry import Command

CONTEXT = "browse"
#: Texts the localization catalogues already hold, so the palette shows them translated.
NO_FILE = "Select an archive file first."
NO_FOLDER = "Select archive files or one archive folder before extracting."
NOT_SAFE = "Not available for the current selection."

_STRUCTURED = {".meshinfo", ".motionblending", ".paa", ".paa_metabin", ".pae", ".paem", ".papr", ".paseq",
               ".paseqc", ".paschedule", ".paschedulepath", ".pastage", ".prefab", ".pappt", ".pamhc", ".seqmt"}
_SAFE_STRUCTURED = {".paseq", ".paseqc", ".pastage", ".pabgh"}


@dataclass(frozen=True, slots=True)
class ContextCommand:
    name: str
    #: The menu entry's text, as the right-click menu shows it.
    label: str
    effect: str
    #: (browser, entry) -> "" when the menu offers the entry for this file, else why not.
    offered: Callable[[object, object], str]
    #: (browser, entry) -> run the entry's handler.
    run: Callable[[object, object], object]
    #: "file": needs the selected file; "folder": a selected folder; "none": nothing.
    needs: str = "file"


def _extension(entry) -> str:
    return str(getattr(entry, "extension", "") or "").lower()


def _only(*extensions: str) -> Callable[[object, object], str]:
    wanted = {extension.lower() for extension in extensions}

    def offered(_browser, entry) -> str:
        if _extension(entry) in wanted:
            return ""
        names = ", ".join(sorted(wanted))
        return f"Offered for {names} files; the selected file is {_extension(entry) or 'not one'}."

    return offered


def _any_file(_browser, _entry) -> str:
    return ""


def _mesh(_browser, entry) -> str:
    from cdmw.domain.archives.constants import ARCHIVE_MESH_EXTENSIONS

    return _only(*ARCHIVE_MESH_EXTENSIONS)(_browser, entry)


def _in_item_set(browser, entry) -> str:
    why = _mesh(browser, entry)
    if why:
        return why
    bridge = getattr(browser, "archive_remote_bridge", None)
    contains = getattr(bridge, "item_set_contains", None)
    if callable(contains) and contains(entry):
        return ""
    return "Offered for a model that is part of a worn set opened from Item Finder."


def scene_add_reason(browser, entry) -> str:
    """Why Add to scene cannot take the selected file, or "" (the menu greys it out)."""

    why = _mesh(browser, entry)
    if why:
        return why
    reason = getattr(getattr(browser, "archive_remote_bridge", None), "scene_add_reason", None)
    if not callable(reason):
        return "Load the game archives in Browse Archives first."
    return reason()


def _add_to_scene(browser, _entry) -> bool:
    return bool(browser.archive_remote_bridge.add_to_scene())


def _editable_chart(browser, entry) -> str:
    from cdmw.services.action_chart_edit_service import is_editable_action_chart_path

    why = _only(".paac", ".paacdesc")(browser, entry)
    if why:
        return why
    return "" if is_editable_action_chart_path(entry.path) else "This action chart cannot be edited."


def _audio_export(browser, entry) -> str:
    from cdmw.domain.archives.constants import ARCHIVE_AUDIO_EXPORT_EXTENSIONS, ARCHIVE_AUDIO_PATCH_EXTENSIONS

    return _only(*(ARCHIVE_AUDIO_EXPORT_EXTENSIONS | ARCHIVE_AUDIO_PATCH_EXTENSIONS))(browser, entry)


def _audio_patch(browser, entry) -> str:
    from cdmw.domain.archives.constants import ARCHIVE_AUDIO_PATCH_EXTENSIONS

    return _only(*ARCHIVE_AUDIO_PATCH_EXTENSIONS)(browser, entry)


def _game_table(browser, entry) -> str:
    from cdmw.core.static_table_records import editable_kinds
    from cdmw.ui.archive_browser.game_table_actions import table_kind

    why = _only(".staticinfoheader", ".staticinfobody")(browser, entry)
    if why:
        return why
    if table_kind(entry.path) in editable_kinds():
        return ""
    return f"CDMW has no proven values to edit in the {table_kind(entry.path) or 'this'} table."


def _open_set(browser, entry) -> None:
    from PySide6.QtCore import QTimer

    from cdmw.ui.mesh_editor.item_set_preparation import prepare_item_set_for_editor

    def run() -> None:
        take = getattr(browser.shell, "_take_pending_hidden_parts_for_open", None)
        if callable(take):
            take()
        prepare_item_set_for_editor(browser.shell, entry, edit_set=True)

    QTimer.singleShot(0, run)


def _continue_work(browser, entry) -> None:
    from PySide6.QtCore import QTimer

    QTimer.singleShot(0, lambda path=entry.path: browser.shell._open_mesh_editor_saved_work(path))


def _paths_export(browser, _entry) -> None:
    from cdmw.ui.archive_browser.path_export_dialog import open_archive_path_export

    open_archive_path_export(browser, "folder")


def _action_chart_button(browser, _entry) -> str:
    button = getattr(browser, "archive_action_chart_button", None)
    if button is None:
        return "Browse Archives has no Action Charts button."
    return "" if button.isEnabled() else (str(button.toolTip() or "").strip() or "Not available now.")


CONTEXT_COMMANDS: tuple[ContextCommand, ...] = (
    ContextCommand("extract_selected", "Extract Selected", "output", _any_file,
                   lambda b, e: b.extract_selected_archive_entries()),
    ContextCommand("extract_filtered", "Extract Filtered", "output", _any_file,
                   lambda b, e: b.extract_filtered_archive_entries()),
    ContextCommand("import_loose_mod_folder", "Import Loose Mod Folder...", "edit", _any_file,
                   lambda b, e: b._open_archive_loose_mod_overlay_dialog()),
    ContextCommand("export_obj_neutral", "Export This Model as OBJ (Neutral Appearance)...", "output",
                   _only(".pac"), lambda b, e: b._start_archive_mesh_export(e, "obj", bake_neutral_appearance=True)),
    ContextCommand("open_set_in_mesh_editor", "Open set in Mesh Editor", "edit", _in_item_set, _open_set),
    ContextCommand("preview_only_this_file", "Preview only this file", "read", _in_item_set,
                   lambda b, e: b.archive_remote_bridge.preview_only_current_file()),
    ContextCommand("add_to_scene", "Add to scene", "read", scene_add_reason, _add_to_scene),
    ContextCommand("continue_earlier_work", "Continue Earlier Work...", "read", _mesh, _continue_work),
    ContextCommand("prefab_inspector", "Open Prefab Inspector...", "edit", _only(".prefab"),
                   lambda b, e: b._open_current_archive_prefab_inspector()),
    ContextCommand("prefab_edit_export_json", "Export Prefab Edit JSON...", "output", _only(".prefab"),
                   lambda b, e: b._export_current_archive_prefab_edit_json()),
    ContextCommand("prefab_edit_import_json", "Import Prefab Edit JSON...", "edit", _only(".prefab"),
                   lambda b, e: b._import_current_archive_prefab_edit_json()),
    ContextCommand("add_bones", "Add Bones...", "edit", _only(".pab"),
                   lambda b, e: b._open_current_archive_pab_bone_editor()),
    ContextCommand("skeleton_edit_export_json", "Export Skeleton Edit JSON...", "output", _only(".pab"),
                   lambda b, e: b._export_current_archive_pab_edit_json()),
    ContextCommand("skeleton_edit_import_json", "Import Skeleton Edit JSON...", "edit", _only(".pab"),
                   lambda b, e: b._import_current_archive_pab_edit_json()),
    ContextCommand("edit_action_chart", "Edit Action Chart...", "edit", _editable_chart,
                   lambda b, e: b._open_current_archive_action_chart_editor()),
    ContextCommand("edit_skinned_decal", "Edit Skinned Decal...", "edit", _only(".paseq"),
                   lambda b, e: b._edit_archive_skinned_decal(e)),
    ContextCommand("edit_structured_data", "Edit Structured Data Safely...", "edit", _only(*_SAFE_STRUCTURED),
                   lambda b, e: b._edit_archive_structured_binary_sidecar(e)),
    ContextCommand("edit_game_table", "Edit Game Table Values...", "edit", _game_table,
                   lambda b, e: b._open_game_table_editor(e)),
    ContextCommand("export_wav", "Export WAV...", "output", _audio_export,
                   lambda b, e: b._start_archive_audio_export(e)),
    ContextCommand("import_wav_loose_mod", "Import WAV as Loose Mod...", "output", _audio_patch,
                   lambda b, e: b._start_archive_audio_patch(e)),
    ContextCommand("replace_embedded_sound", "Replace Embedded Sound as Loose Mod...", "output", _only(".bnk"),
                   lambda b, e: b._start_archive_bank_media_replace(e)),
    ContextCommand("edit_sound_bank", "Edit Sound Bank as Loose Mod...", "edit", _only(".bnk"),
                   lambda b, e: b._start_archive_sound_bank_edit(e)),
    ContextCommand("export_folder", "Export Folder...", "output", _any_file,
                   lambda b, e: b.extract_selected_archive_entries(), needs="folder"),
    ContextCommand("export_file_paths", "Export File Paths...", "output", _any_file, _paths_export,
                   needs="folder"),
    ContextCommand("find_action_chart", "Find Action Chart by Character...", "edit", _action_chart_button,
                   lambda b, e: b._open_action_chart_finder(), needs="none"),
    ContextCommand("open_action_chart_mod", "Open Action Chart Mod...", "edit", _action_chart_button,
                   lambda b, e: b._open_action_chart_mod(), needs="none"),
)


def _selected_folder(browser) -> str:
    tree = getattr(browser, "archive_tree", None)
    item = tree.currentItem() if tree is not None and hasattr(tree, "currentItem") else None
    if item is None or browser._archive_tree_item_kind(item) != "folder":
        return ""
    return browser._archive_tree_folder_path(item)


def command_reason(browser, spec: ContextCommand) -> str:
    """Why the command cannot run for what is selected now, or ""."""

    if spec.needs == "none":
        return spec.offered(browser, None)
    if not bool(getattr(browser, "archive_remote_actions_safe", True)):
        return NOT_SAFE
    if spec.needs == "folder":
        return "" if _selected_folder(browser) else NO_FOLDER
    if getattr(browser, "archive_preview_showing_loose", False):
        return NO_FILE
    entry = browser._current_archive_entry()
    if entry is None:
        return NO_FILE
    return spec.offered(browser, entry)


def _command(browser, spec: ContextCommand) -> Command:
    from cdmw.ui.commands.registry import CommandRefused

    def reason() -> str:
        try:
            return command_reason(browser, spec)
        except RuntimeError:  # the window is closing
            return NO_FILE

    def run() -> object:
        why = reason()
        if why:
            raise CommandRefused(why)
        entry = None if spec.needs != "file" else browser._current_archive_entry()
        return spec.run(browser, entry)

    return Command(f"{CONTEXT}.{spec.name}", spec.label, CONTEXT, run, reason,
                   keywords=(spec.name, spec.name.replace("_", " ")), effect=spec.effect)


def context_commands(browser) -> list[Command]:
    return [_command(browser, spec) for spec in CONTEXT_COMMANDS]


__all__ = ["CONTEXT_COMMANDS", "ContextCommand", "command_reason", "context_commands", "scene_add_reason"]
