"""Which registry commands still need their effect class set (section 7, answer 3).

A command's effect class is a field on ``Command`` with ``edit`` as its
default, set explicitly for read, output and destructive commands. The
commands below are registered outside ``cdmw/ui/commands/`` by code the main
thread owns, so they still have the default. Each maps to the class this
thread recommends; the main thread sets ``effect=`` where the command is made
and then removes its row here. ``USER_ONLY`` commands never become tools.

``tests/test_mcp_tool_table.py`` fails when a command whose label starts with
Build, Export, Delete or Remove has the default and is not listed here, and
when a listed command no longer has the default (its row is then stale).
"""

from __future__ import annotations

from cdmw.mcp.names import DEFAULT_EFFECT, DESTRUCTIVE, EDIT, OUTPUT, READ

#: Words that mark a command as more than an edit unless it says otherwise.
RISKY_LABEL_WORDS = ("Build", "Export", "Delete", "Remove")
#: Ids whose action part names an export, for commands whose label is read
#: from a button at run time (Browse Archives).
RISKY_ID_WORDS = ("export", "build", "delete", "remove")
#: Not a tool, whatever its class: it can change the AI connection setting,
#: the approval classes, Full access or the game folder (section 7, answer 8).
USER_ONLY = "user_only"


def needs_explicit_effect(command) -> bool:
    """A command whose label or id marks it as output or destructive but still has the default class."""

    if command.effect != DEFAULT_EFFECT:
        return False
    label = str(command.label or "").lstrip()
    action = str(command.id).split(".", 1)[-1].casefold()
    return label.startswith(RISKY_LABEL_WORDS) or any(word in action for word in RISKY_ID_WORDS)


#: Command id -> the class this thread recommends. The main thread owns these files.
AWAITING_CLASSIFICATION: dict[str, str] = {
    # cdmw/ui/shell/shell_commands.py
    "shell.export_profile": OUTPUT,
    "shell.import_profile": USER_ONLY,  # a profile carries the AI settings and the game folder
    "shell.settings": READ,
    "shell.detach_tool": READ,
    "shell.attach_tool": READ,
    "shell.attach_all_tools": READ,
    "shell.documentation": READ,
    "shell.report_problem": READ,
    "shell.export_diagnostics": OUTPUT,
    "shell.copy_problem_summary": OUTPUT,  # writes the clipboard, as CDMW Next classes it
    "shell.open_crash_reports": READ,
    "shell.about": READ,
    # (every shell.open.<tool> rail command: READ, switching tools changes no document)
    # cdmw/ui/archive_browser/browse_commands.py
    "browse.preview": READ,
    "browse.open_preview_window": READ,
    "browse.extract_file": OUTPUT,
    "browse.export_file": OUTPUT,
    "browse.copy_filename": OUTPUT,
    "browse.show_only_file": READ,
    "browse.asset_family": READ,
    "browse.filter_to_family": READ,
    "browse.export_family": OUTPUT,
    "browse.character_dependencies": READ,
    "browse.asset_family_panel": READ,
    "browse.appearance_composite": READ,
    "browse.open_in_mesh_editor": EDIT,
    "browse.import_mesh": EDIT,
    "browse.export_obj": OUTPUT,
    "browse.export_glb": OUTPUT,
    "browse.export_fbx": OUTPUT,
    "browse.batch_export_obj": OUTPUT,
    "browse.batch_export_glb": OUTPUT,
    "browse.batch_export_fbx": OUTPUT,
    "browse.hkx_edit": EDIT,
    "browse.hkx_physics_editor": EDIT,
    "browse.hkx_placement": EDIT,
    "browse.hkx_export_xml": OUTPUT,
    "browse.hkx_export_json": OUTPUT,
    "browse.hkx_export_havok_xml_view": OUTPUT,
    "browse.hkx_import_xml": EDIT,
    "browse.hkx_import_json": EDIT,
    "browse.sidecar_inspect": READ,
    "browse.sidecar_export_json": OUTPUT,
    # cdmw/ui/texture_workflow/editor_commands.py
    "texture_editor.open_file": EDIT,
    "texture_editor.open_archive": READ,
    "texture_editor.open_compare": READ,
    "texture_editor.open_project": EDIT,
    "texture_editor.save_project": OUTPUT,
    "texture_editor.save_png": OUTPUT,
    "texture_editor.send_replace": EDIT,
    "texture_editor.send_workflow": EDIT,
    "texture_editor.send_item_icons": EDIT,
    "texture_editor.undo": EDIT,
    "texture_editor.redo": EDIT,
    "texture_editor.clear_selection": EDIT,
    "texture_editor.copy_selection_layer": EDIT,
    "texture_editor.new_layer": EDIT,
    "texture_editor.copy_layer": EDIT,
    "texture_editor.cut_selection": EDIT,
    "texture_editor.paste_layer": EDIT,
    "texture_editor.paste_centered": EDIT,
    "texture_editor.transform_float_layer": EDIT,
    "texture_editor.fit_view": READ,
    "texture_editor.actual_size": READ,
    "texture_editor.tool_paint": READ,
    "texture_editor.tool_erase": READ,
    "texture_editor.tool_fill": READ,
    "texture_editor.tool_gradient": READ,
    "texture_editor.tool_smudge": READ,
    "texture_editor.tool_dodge_burn": READ,
    "texture_editor.tool_move": READ,
    "texture_editor.tool_rect": READ,
    "texture_editor.tool_lasso": READ,
    "texture_editor.tool_clone": READ,
    "texture_editor.tool_heal": READ,
    "texture_editor.tool_patch": READ,
    "texture_editor.brush_smaller": READ,
    "texture_editor.brush_larger": READ,
    "texture_editor.hardness_softer": READ,
    "texture_editor.hardness_harder": READ,
    "texture_editor.toggle_quick_mask": EDIT,
    "texture_editor.export_dds": OUTPUT,
    "texture_editor.preview_compressed": READ,
}

#: Commands that never become tools, whatever class they are given later.
USER_ONLY_COMMANDS = frozenset(i for i, effect in AWAITING_CLASSIFICATION.items() if effect == USER_ONLY)

#: Every class a recommendation may name.
RECOMMENDATIONS = (READ, EDIT, DESTRUCTIVE, OUTPUT, USER_ONLY)
