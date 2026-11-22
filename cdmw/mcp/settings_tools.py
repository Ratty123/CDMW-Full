"""Set Settings controls by persisted key and operate Settings > Shortcuts."""

from __future__ import annotations

from cdmw.mcp.approvals import refuse_protected_setting
from cdmw.mcp.errors import INVALID_ARGUMENTS, NOT_FOUND, REFUSED, UNAVAILABLE, ToolError
from cdmw.mcp.names import EDIT
from cdmw.mcp.rail_actions import PATH, choices, choose, page, press, required, tool, ui, window


_SETTINGS_CONTROLS = {
    "appearance/theme": "theme_combo",
    "appearance/language": "language_combo",
    "appearance/ui_font_family": "ui_font_family_combo",
    "appearance/ui_density": "density_combo",
    "appearance/ui_font_size": "ui_font_size_spin",
    "appearance/data_font_size": "data_font_size_spin",
    "appearance/log_font_family": "log_font_family_combo",
    "appearance/log_font_size": "log_font_size_spin",
    "appearance/log_font_bold": "log_font_bold_checkbox",
    "appearance/log_text_style": "log_text_style_combo",
    "appearance/log_color_scheme": "log_color_scheme_combo",
    "appearance/preview_color_scheme": "preview_color_scheme_combo",
    "preferences/auto_load_archive_on_startup": "auto_load_archive_checkbox",
    "preferences/prefer_archive_cache_on_startup": "prefer_cache_checkbox",
    "preferences/restore_last_active_tab": "restore_last_tab_checkbox",
    "preferences/remember_splitter_sizes": "remember_splitters_checkbox",
    "preferences/confirm_workflow_output_cleanup": "confirm_workflow_cleanup_checkbox",
    "preferences/confirm_archive_extract_cleanup": "confirm_archive_cleanup_checkbox",
    "preferences/capture_crash_details": "capture_crash_details_checkbox",
    "preferences/show_verbose_archive_logs": "verbose_archive_logs_checkbox",
    "performance/resource_profile": "archive_resource_profile_combo",
    "performance/native_archive_acceleration": "archive_native_acceleration_checkbox",
    "archive/enable_sidecar_indexing": "archive_sidecar_indexing_checkbox",
    "archive/native_preview_cache_mode": "archive_native_preview_cache_mode_combo",
    "archive/quick_then_full_preview": "archive_quick_then_full_checkbox",
    "archive/maximum_indexing_priority": "archive_maximum_indexing_priority_checkbox",
    "archive/durable_exports": "archive_durable_exports_checkbox",
    "archive/model_use_textures": "model_preview_use_textures_checkbox",
    "archive/model_high_quality": "model_preview_high_quality_checkbox",
    "preview/view_mode": "d3d11_view_mode_combo",
    "preview/alpha_handling_mode": "alpha_handling_combo",
    "preview/sampler_probe_mode": "sampler_probe_combo",
    "preview/diffuse_swizzle_mode": "diffuse_swizzle_combo",
    "preview/solo_batch_index": "solo_batch_spin",
    "preview/texture_max_dimension": "preview_texture_max_dimension_spin",
    "preview/d3d11_light_azimuth_degrees": "d3d11_light_azimuth_spin",
    "preview/d3d11_light_elevation_degrees": "d3d11_light_elevation_spin",
    **{f"preview/{key}": f"{key}_combo" for key in (
        "visible_texture_mode", "render_diagnostic_mode", "d3d11_normal_y_mode",
        "d3d11_texture_address_mode", "texture_probe_source")},
    **{f"preview/{key}": f"{key}_checkbox" for key in (
        "disable_tint", "disable_brightness", "disable_uv_scale", "force_nearest_no_mipmaps",
        "disable_normal_map", "disable_material_map", "disable_height_map", "disable_all_support_maps",
        "disable_lighting", "disable_depth_test", "show_texture_debug_strip", "d3d11_cull_back_faces",
        "invert_orbit_x", "invert_orbit_y", "invert_pan_x", "invert_pan_y")},
    **{f"preview/{key}": f"{key}_spin" for key in (
        "low_quality_texture_max_dimension", "max_anisotropy", "d3d11_mip_lod_bias", "ambient_strength",
        "diffuse_wrap_bias", "diffuse_light_scale", "orbit_sensitivity", "pan_sensitivity", "normal_strength_cap",
        "normal_strength_floor", "height_effect_max", "cavity_clamp_min", "cavity_clamp_max", "specular_base",
        "specular_min", "specular_max", "shininess_base", "shininess_min", "shininess_max", "height_shininess_boost",
        "d3d11_ao_strength", "d3d11_roughness_bias", "d3d11_metalness_scale", "d3d11_environment_strength",
        "d3d11_emissive_gain", "d3d11_tone_exposure", "d3d11_tone_contrast", "d3d11_tone_gamma")},
}
_NUMERIC_MODES = {
    "performance/archive_fetch_batch_size": ("archive_fetch_batch_mode_combo", "archive_fetch_batch_spin"),
    "archive/sidecar_worker_count": ("archive_sidecar_worker_mode_combo", "archive_sidecar_worker_spin"),
    "archive/preview_cache_limit": ("archive_preview_cache_limit_mode_combo", "archive_preview_cache_limit_spin"),
}
_PATH_CONTROLS = {
    "paths/original_dds_root": ("textures", "original_dds_edit"),
    "paths/png_root": ("textures", "png_root_edit"),
    "paths/texture_editor_png_root": ("textures", "texture_editor_png_root_edit"),
    "paths/dds_staging_root": ("textures", "dds_staging_root_edit"),
    "paths/output_root": ("textures", "output_root_edit"),
    "archive/extract_root": ("archive", "archive_extract_root_edit"),
    # Helper programs the texture tools run; Settings saves them from these fields.
    "ncnn/exe_path": ("textures", "ncnn_exe_path_edit"),
    "ncnn/model_dir": ("textures", "ncnn_model_dir_edit"),
    "chainner/exe_path": ("textures", "chainner_exe_path_edit"),
    "chainner/chain_path": ("textures", "chainner_chain_path_edit"),
}

#: Helper locations Settings and the pages remember outside any field: each is checked as the
#: page that asks for it checks it, then written straight to the settings file.
_CHECKED_PATHS = {
    "new_item/blender_executable": "blender",
    "dmm/install_folder": "dmm",
}


def _check_helper(kind: str, text: str) -> str:
    from pathlib import Path

    if kind == "blender":
        from cdmw.services.fbx_blender_conversion import is_blender_executable

        if not is_blender_executable(text):
            return "That is not a Blender program (choose blender.exe)."
    elif kind == "dmm" and not (Path(text) / "DMM.exe").is_file():
        return "That is not DMM's folder (choose the folder that contains DMM.exe)."
    return ""


def _control_value(control, value):
    from PySide6.QtWidgets import QCheckBox, QComboBox, QDoubleSpinBox, QSpinBox

    if not control.isEnabled():
        raise ToolError(UNAVAILABLE, "The Settings control is disabled.")
    if isinstance(control, QCheckBox) and type(value) is bool:
        control.setChecked(value)
    elif isinstance(control, QComboBox):
        choose(control, value)
    elif isinstance(control, (QSpinBox, QDoubleSpinBox)):
        integer = isinstance(control, QSpinBox)
        if (type(value) is not int if integer else type(value) not in (int, float)):
            raise ToolError(INVALID_ARGUMENTS, "Enter the numeric setting value.")
        if not control.minimum() <= value <= control.maximum():
            raise ToolError(INVALID_ARGUMENTS, f"Choose a value from {control.minimum()} to {control.maximum()}.")
        control.setValue(value)
    else:
        raise ToolError(INVALID_ARGUMENTS, "The value does not match the Settings control.")


def _set(call):
    from pathlib import Path
    from cdmw.domain.archives.discovery import ARCHIVE_IGNORED_FOLDERS_OVERRIDE_SETTING, normalize_ignored_archive_folders
    from cdmw.domain.output_paths import game_path_reason
    from cdmw.domain.preview_view_modes import LEGACY_VIEW_MODE_KEY, VIEW_MODE_KEY
    from cdmw.services.dmm_runtime_mount import SHOW_MOUNTED_MODS_SETTING

    raw = call.arguments["key"]
    key = str(raw).strip().replace("\\", "/").strip("/").casefold()
    refuse_protected_setting(key)
    if key == LEGACY_VIEW_MODE_KEY:
        key = VIEW_MODE_KEY
    value = call.arguments["value"]
    if key in _PATH_CONTROLS or key in _CHECKED_PATHS:
        text = value.strip() if isinstance(value, str) else None
        if text is None or (text and not Path(text).is_absolute()):
            raise ToolError(INVALID_ARGUMENTS, "Enter an absolute path or clear the setting.")
        reason = game_path_reason(text, game_folder=call.context.game_folder())
        if reason:
            raise ToolError(REFUSED, reason)
        value = text
        problem = _check_helper(_CHECKED_PATHS[key], text) if key in _CHECKED_PATHS and text else ""
        if problem:
            raise ToolError(INVALID_ARGUMENTS, problem)

    def change():
        tab = page(call, "settings")
        if key in _CHECKED_PATHS:
            current = window(call)
            current.shell.settings.setValue(key, value)
            current.shell.settings.sync()
            return {"key": key, "value": current.shell.settings.value(key)}
        if key in _PATH_CONTROLS:
            owner, control = _PATH_CONTROLS[key]
            current = window(call)
            field = getattr(getattr(current, owner, None), control, None)
            if field is not None:
                field.setText(value)
                current.shell.flush_settings_save()
            else:
                # The page that holds the field is not built yet; it reads the setting when it is.
                current.shell.settings.setValue(key, value)
                current.shell.settings.sync()
        elif key == SHOW_MOUNTED_MODS_SETTING:
            if type(value) is not bool:
                raise ToolError(INVALID_ARGUMENTS, "Supply true or false.")
            _control_value(tab.dmm_mounted_mods_group.show_checkbox, value)
        elif key == ARCHIVE_IGNORED_FOLDERS_OVERRIDE_SETTING:
            if not isinstance(value, list):
                raise ToolError(INVALID_ARGUMENTS, "Supply the list of paths to ignore.")
            try:
                folders = normalize_ignored_archive_folders(value)
            except ValueError as error:
                raise ToolError(INVALID_ARGUMENTS, str(error)) from None
            group = tab.archive_ignored_folders_group
            group.folder_list.clear()
            group.folder_list.addItems(folders)
            group._save()
        elif key in _NUMERIC_MODES:
            if type(value) is not int or value < 0:
                raise ToolError(INVALID_ARGUMENTS, "Enter a nonnegative whole number.")
            combo_name, spin_name = _NUMERIC_MODES[key]
            combo, spin = getattr(tab, combo_name), getattr(tab, spin_name)
            if key == "archive/sidecar_worker_count":
                if value and not spin.minimum() <= value <= spin.maximum():
                    raise ToolError(INVALID_ARGUMENTS, "Choose a supported worker count.")
                choose(combo, int(value != 0))
            else:
                index = combo.findData(value)
                if index < 0 and not spin.minimum() <= value <= spin.maximum():
                    raise ToolError(INVALID_ARGUMENTS, "Choose a supported numeric preset or value.")
                if index >= 0:
                    combo.setCurrentIndex(index)
                else:
                    choose(combo, -1)  # The Settings page's custom numeric preset.
            if spin.isEnabled():
                _control_value(spin, value)
        elif key in _SETTINGS_CONTROLS:
            _control_value(getattr(tab, _SETTINGS_CONTROLS[key]), value)
        else:
            keys = _SETTINGS_CONTROLS.keys() | _NUMERIC_MODES.keys() | _PATH_CONTROLS.keys() | _CHECKED_PATHS.keys()
            raise ToolError(NOT_FOUND, f"There is no supported Settings control for {raw!r}.",
                            {"keys": sorted(keys | {ARCHIVE_IGNORED_FOLDERS_OVERRIDE_SETTING, SHOW_MOUNTED_MODS_SETTING})})
        tab.flush_settings_save()
        return {"key": key, "value": tab.settings.value(key)}

    return ui(call, change)


def _shortcuts(call):
    from PySide6.QtGui import QKeySequence
    from PySide6.QtWidgets import QDialog, QDialogButtonBox
    from cdmw.ui.commands.shortcuts_page import KeyDialog

    args = call.arguments
    action = args["action"]

    def answer(dialog):
        keys = required(args, "keys")
        for i, editor in enumerate(dialog.editors):
            key = keys[i] if i < len(keys) else ""
            sequence = QKeySequence.fromString(key, QKeySequence.SequenceFormat.PortableText)
            if key and sequence.isEmpty():
                raise ToolError(INVALID_ARGUMENTS, f"Unrecognized shortcut {key!r}.")
            editor.touched = True
            editor.setKeySequence(sequence)
        dialog._show_state()
        if dialog.refusal():
            raise ToolError(INVALID_ARGUMENTS, dialog.refusal())
        press(dialog.buttons.button(QDialogButtonBox.StandardButton.Ok))
        return QDialog.DialogCode.Accepted

    def change():
        shortcuts = getattr(page(call, "settings"), "shortcuts_page", None)
        if shortcuts is None:
            raise ToolError(UNAVAILABLE, "Settings > Shortcuts is unavailable.")
        if shortcuts._stale:
            shortcuts.refill()
        if action == "reset_all":
            press(shortcuts.reset_all_button)
            return {"reset_all": True}
        command = required(args, "command")
        if shortcuts.row_for(command) is None:
            raise ToolError(NOT_FOUND, f"No shortcut command matches {command!r}.")
        if not shortcuts.select_command(command):
            shortcuts.search.clear()
            shortcuts.show_combo.setCurrentIndex(0)
        if not shortcuts.select_command(command):
            raise ToolError(UNAVAILABLE, "The requested command has no editable shortcut row.")
        press({"rebind": shortcuts.change_button, "unbind": shortcuts.unbind_button,
               "reset": shortcuts.reset_button}[action])
        return {"command": command, "keys": list(shortcuts.row_for(command).keys)}

    return ui(call, change, {"confirm": "yes"} if action == "reset_all" else None, dialogs={KeyDialog: answer})


def settings_tools():
    return [
        tool("app.settings_set", EDIT, "Set a CDMW Settings control by persisted key and return its saved value.",
             "ui:SettingsTab", _set,
             {"key": PATH, "value": {"type": ["string", "boolean", "number", "array"], "items": PATH, "maxItems": 256}},
             ("key", "value")),
        tool("shortcuts.change", EDIT, "Rebind a command's keys, unbind it, or restore defaults in Settings > Shortcuts.",
             "ui:ShortcutsPage", _shortcuts,
             {"action": choices("rebind", "unbind", "reset", "reset_all"), "command": PATH,
              "keys": {"type": "array", "items": PATH, "minItems": 1, "maxItems": 2}}, ("action",)),
    ]
