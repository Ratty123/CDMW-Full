"""Browse Archives' actions as registry commands (P12 step 2).

Browse decides each action button's state in one place,
``_set_action_button_state(button, enabled, tooltip, reason)``, which also
keeps the reason on the button. A command reads that state and reason from its
button and runs by pressing it, so the button and the palette show the same
label, state and reason. The buttons keep their object names and slots.
"""

from __future__ import annotations

from cdmw.ui.commands.registry import Command, CommandRegistry, command_registry

CONTEXT = "browse"
REASON_PROPERTY = "_cdmw_unavailable_reason"
UNAVAILABLE = "Not available for the current selection."

#: Browse button attribute -> command id (``browse.<name>``).
BROWSE_BUTTONS = {
    "archive_action_preview_button": "preview",
    "archive_action_open_preview_window_button": "open_preview_window",
    "archive_action_extract_file_button": "extract_file",
    "archive_action_export_file_button": "export_file",
    "archive_action_copy_filename_button": "copy_filename",
    "archive_action_show_only_file_button": "show_only_file",
    "archive_action_asset_family_button": "asset_family",
    "archive_action_filter_to_family_button": "filter_to_family",
    "archive_action_export_family_button": "export_family",
    "archive_action_character_dependency_button": "character_dependencies",
    "archive_asset_family_button": "asset_family_panel",
    "archive_appearance_composite_button": "appearance_composite",
    "archive_model_open_mesh_editor_button": "open_in_mesh_editor",
    "archive_model_import_mesh_button": "import_mesh",
    "archive_model_export_obj_button": "export_obj",
    "archive_model_export_glb_button": "export_glb",
    "archive_model_export_fbx_button": "export_fbx",
    "archive_model_batch_obj_button": "batch_export_obj",
    "archive_model_batch_glb_button": "batch_export_glb",
    "archive_model_batch_fbx_button": "batch_export_fbx",
    "archive_hkx_edit_button": "hkx_edit",
    "archive_hkx_physics_editor_button": "hkx_physics_editor",
    "archive_hkx_placement_button": "hkx_placement",
    "archive_hkx_export_xml_button": "hkx_export_xml",
    "archive_hkx_export_json_button": "hkx_export_json",
    "archive_hkx_export_havok_xml_view_button": "hkx_export_havok_xml_view",
    "archive_hkx_import_xml_button": "hkx_import_xml",
    "archive_hkx_import_json_button": "hkx_import_json",
    "archive_sidecar_inspect_button": "sidecar_inspect",
    "archive_sidecar_export_json_button": "sidecar_export_json",
}


def command_id(name: str) -> str:
    return f"{CONTEXT}.{name}"


def remember_button_reason(button, enabled: bool, reason: str) -> None:
    """Called by ``_set_action_button_state``: the button carries its own reason."""

    # No registry refresh here: this runs for every button on every state update,
    # and the palette reads the reason when it opens.
    try:
        button.setProperty(REASON_PROPERTY, "" if enabled else str(reason or "").strip())
    except (AttributeError, RuntimeError):
        return


def _button_command(button, name: str) -> Command:
    label = str(button.text() or name).replace("&", "")

    def reason() -> str:
        try:
            if button.isEnabled():
                return ""
            text = str(button.property(REASON_PROPERTY) or "").strip()
        except RuntimeError:
            return UNAVAILABLE
        return text[:1].upper() + text[1:] if text else UNAVAILABLE

    return Command(command_id(name), label, CONTEXT, button.click, reason, keywords=(name,))


def install_browse_commands(browser) -> CommandRegistry | None:
    """Register a command for each Browse action button that exists."""

    registry = command_registry()
    if registry is None:
        return None
    commands = [_button_command(getattr(browser, attribute), name)
                for attribute, name in BROWSE_BUTTONS.items() if getattr(browser, attribute, None) is not None]
    registry.register_all(commands, replace=True)
    return registry
