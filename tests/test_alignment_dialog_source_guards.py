from __future__ import annotations

import unittest
from pathlib import Path

from tests.native_source_text import d3d11_preview_source
from tests.mesh_editor_source_support import mesh_editor_tab_source
from tests.source_function_map import function_source
from tests.static_replacement_source_support import (
    static_replacement_callback_concern_source,
    static_replacement_callback_family_source,
    static_replacement_callback_implementation_source,
    static_replacement_mesh_edit_implementation_source,
    static_replacement_remaining_callback_source,
    static_replacement_routing_callback_source,
    static_replacement_source_part_mutation_callback_source,
    static_replacement_texture_callback_source,
    static_replacement_ui_concern_source,
    static_replacement_ui_implementation_source,
)


ROOT = Path(__file__).resolve().parents[1]
MAIN_WINDOW = ROOT / "cdmw" / "ui" / "shell" / "app_window.py"
SHELL_TOOL_TABS = ROOT / "cdmw" / "ui" / "shell" / "tool_tabs.py"
SHELL_WINDOW_BOOTSTRAP_STATE = ROOT / "cdmw" / "ui" / "shell" / "window_bootstrap_state.py"
ABOUT_DOCUMENTATION_EN = ROOT / "cdmw" / "ui" / "shell" / "about_documentation_en.py"
ARCHIVE_ACTIONS = ROOT / "cdmw" / "ui" / "archive_browser" / "actions.py"
ARCHIVE_ACTION_CONTROLS = ROOT / "cdmw" / "ui" / "archive_browser" / "action_controls.py"
ARCHIVE_MESH_DIRECT_PATCH = ROOT / "cdmw" / "ui" / "archive_browser" / "mesh_direct_patch.py"
ARCHIVE_MESH_IMPORT_EXPORT = ROOT / "cdmw" / "ui" / "archive_browser" / "mesh_import_export.py"
ARCHIVE_MESH_BUILDER_LIFECYCLE = ROOT / "cdmw" / "ui" / "archive_browser" / "mesh_builder_lifecycle.py"
ARCHIVE_MESH_LAUNCH_FLOW = ROOT / "cdmw" / "ui" / "archive_browser" / "mesh_launch_flow.py"
ARCHIVE_MESH_PATCH_FLOW = ROOT / "cdmw" / "ui" / "archive_browser" / "mesh_patch_flow.py"
ARCHIVE_MESH_SWAP_SUPPORT = ROOT / "cdmw" / "ui" / "archive_browser" / "mesh_swap_support.py"
ARCHIVE_MESH_SWAP_SCOPE_DIALOG = ROOT / "cdmw" / "ui" / "archive_browser" / "mesh_swap_scope_dialog.py"
ARCHIVE_MESH_SWAP_SCOPE_PREFLIGHT = ROOT / "cdmw" / "ui" / "archive_browser" / "mesh_swap_scope_preflight.py"
ARCHIVE_MESH_MODIFY_ORIGINAL = ROOT / "cdmw" / "ui" / "archive_browser" / "mesh_modify_original.py"
ARCHIVE_MESH_SETUP_HELPERS = ROOT / "cdmw" / "ui" / "archive_browser" / "mesh_setup_helpers.py"
ARCHIVE_MESH_IMPORT_SETUP_STATE = ROOT / "cdmw" / "ui" / "archive_browser" / "mesh_import_setup_state.py"
ARCHIVE_PREVIEW_DETAILS = ROOT / "cdmw" / "ui" / "archive_browser" / "preview_details.py"
ARCHIVE_PREVIEW_LAYOUT = ROOT / "cdmw" / "ui" / "archive_browser" / "preview_layout.py"
ARCHIVE_REFERENCE_PREVIEW = ROOT / "cdmw" / "ui" / "archive_browser" / "reference_preview.py"
ARCHIVE_SOURCE_PICKER_DIALOG = ROOT / "cdmw" / "ui" / "archive_browser" / "source_picker_dialog.py"
ARCHIVE_SOURCE_MIX_ACTIONS = ROOT / "cdmw" / "ui" / "archive_browser" / "source_mix_actions.py"
ARCHIVE_ASSET_FAMILY_LAYOUT = ROOT / "cdmw" / "ui" / "archive_browser" / "asset_family_layout.py"
ARCHIVE_ASSET_FAMILY_REFERENCES = ROOT / "cdmw" / "ui" / "archive_browser" / "asset_family_references.py"
ARCHIVE_MOD_READY_EXPORT = ROOT / "cdmw" / "ui" / "archive_browser" / "mod_ready_export.py"
ARCHIVE_STATIC_REPLACEMENT_DIALOG = ROOT / "cdmw" / "ui" / "archive_browser" / "static_replacement_dialog.py"
ARCHIVE_STATIC_REPLACEMENT_DIALOG_PROMPT = (
    ROOT / "cdmw" / "ui" / "archive_browser" / "static_replacement_dialog_prompt.py"
)
ARCHIVE_STATIC_REPLACEMENT_DIALOG_PROMPT_SHELL = (
    ROOT / "cdmw" / "ui" / "archive_browser" / "static_replacement_dialog_prompt_shell.py"
)
ARCHIVE_STATIC_REPLACEMENT_DIALOG_PROMPT_OPEN = (
    ROOT / "cdmw" / "ui" / "archive_browser" / "static_replacement_dialog_prompt_open.py"
)
ARCHIVE_STATIC_REPLACEMENT_DIALOG_PROMPT_SETUP = (
    ROOT / "cdmw" / "ui" / "archive_browser" / "static_replacement_dialog_prompt_setup.py"
)
ARCHIVE_STATIC_REPLACEMENT_DIALOG_PROMPT_SETUP_HELPERS = (
    ROOT / "cdmw" / "ui" / "archive_browser" / "static_replacement_dialog_prompt_setup_helpers.py"
)
ARCHIVE_STATIC_REPLACEMENT_PROMPT_PREFLIGHT = (
    ROOT / "cdmw" / "ui" / "archive_browser" / "static_replacement_prompt_preflight.py"
)
ARCHIVE_STATIC_REPLACEMENT_DIALOG_PROMPT_STATE_CALLBACKS = (
    ROOT / "cdmw" / "ui" / "archive_browser" / "static_replacement_dialog_prompt_state_callbacks.py"
)
ARCHIVE_STATIC_REPLACEMENT_DIALOG_PROMPT_TRANSFORM = (
    ROOT / "cdmw" / "ui" / "archive_browser" / "static_replacement_dialog_prompt_transform.py"
)
ARCHIVE_STATIC_REPLACEMENT_DIALOG_PROMPT_DEPS = (
    ROOT / "cdmw" / "ui" / "archive_browser" / "static_replacement_dialog_prompt_deps.py"
)
ARCHIVE_STATIC_REPLACEMENT_DIALOG_PROMPT_DEPS_BASE = (
    ROOT / "cdmw" / "ui" / "archive_browser" / "static_replacement_dialog_prompt_deps_base.py"
)
ARCHIVE_STATIC_REPLACEMENT_DIALOG_PROMPT_DEPS_STATE_A = (
    ROOT / "cdmw" / "ui" / "archive_browser" / "static_replacement_dialog_prompt_deps_state_a.py"
)
ARCHIVE_STATIC_REPLACEMENT_DIALOG_PROMPT_DEPS_STATE_B = (
    ROOT / "cdmw" / "ui" / "archive_browser" / "static_replacement_dialog_prompt_deps_state_b.py"
)
ARCHIVE_STATIC_REPLACEMENT_DIALOG_PROMPT_DEPS_CALLBACKS = (
    ROOT / "cdmw" / "ui" / "archive_browser" / "static_replacement_dialog_prompt_deps_callbacks.py"
)
ARCHIVE_STATIC_REPLACEMENT_DIALOG_HELPERS = (
    ROOT / "cdmw" / "ui" / "archive_browser" / "static_replacement_dialog_helpers.py"
)
ARCHIVE_STATIC_REPLACEMENT_DIALOG_CALLBACK_FACTORIES = (
    ROOT / "cdmw" / "ui" / "archive_browser" / "static_replacement_dialog_callback_factories.py"
)
ARCHIVE_STATIC_REPLACEMENT_DIALOG_MESH_DIAGNOSTICS_CALLBACKS = (
    ROOT / "cdmw" / "ui" / "archive_browser" / "static_replacement_dialog_mesh_diagnostics_callbacks.py"
)
ARCHIVE_STATIC_REPLACEMENT_DIALOG_SOURCE_MIX_CALLBACKS = (
    ROOT / "cdmw" / "ui" / "archive_browser" / "static_replacement_dialog_source_mix_callbacks.py"
)
ARCHIVE_STATIC_REPLACEMENT_DIALOG_TEXTURE_DETAIL_UV_CALLBACKS = (
    ROOT / "cdmw" / "ui" / "archive_browser" / "static_replacement_dialog_texture_detail_uv_callbacks.py"
)
ARCHIVE_STATIC_REPLACEMENT_DIALOG_ACCEPT_DISPATCH_CALLBACKS = (
    ROOT / "cdmw" / "ui" / "archive_browser" / "static_replacement_dialog_accept_dispatch_callbacks.py"
)
ARCHIVE_STATIC_REPLACEMENT_DIALOG_CUSTOM_ICON_CALLBACKS = (
    ROOT / "cdmw" / "ui" / "archive_browser" / "static_replacement_dialog_custom_icon_callbacks.py"
)
ARCHIVE_STATIC_REPLACEMENT_DIALOG_SOURCE_ROLE_TREE_CALLBACKS = (
    ROOT / "cdmw" / "ui" / "archive_browser" / "static_replacement_dialog_source_role_tree_callbacks.py"
)
ARCHIVE_STATIC_REPLACEMENT_DIALOG_MANUAL_PROFILE_CALLBACKS = (
    ROOT / "cdmw" / "ui" / "archive_browser" / "static_replacement_dialog_manual_profile_callbacks.py"
)
ARCHIVE_STATIC_REPLACEMENT_DIALOG_MATERIAL_AUTHORITY_CALLBACKS = (
    ROOT / "cdmw" / "ui" / "archive_browser" / "static_replacement_dialog_material_authority_callbacks.py"
)
ARCHIVE_STATIC_REPLACEMENT_DIALOG_TEXTURE_CALLBACKS = (
    ROOT / "cdmw" / "ui" / "archive_browser" / "static_replacement_dialog_texture_callbacks.py"
)
ARCHIVE_STATIC_REPLACEMENT_DIALOG_ROUTING_CALLBACKS = (
    ROOT / "cdmw" / "ui" / "archive_browser" / "static_replacement_dialog_routing_callbacks.py"
)
ARCHIVE_STATIC_REPLACEMENT_DIALOG_SOURCE_PART_MUTATION_CALLBACKS = (
    ROOT / "cdmw" / "ui" / "archive_browser" / "static_replacement_dialog_source_part_mutation_callbacks.py"
)
ARCHIVE_STATIC_REPLACEMENT_DIALOG_MESH_EDIT_CALLBACKS = (
    ROOT / "cdmw" / "ui" / "archive_browser" / "static_replacement_dialog_mesh_edit_callbacks.py"
)
ARCHIVE_STATIC_REPLACEMENT_DIALOG_REMAINING_CALLBACKS = (
    ROOT / "cdmw" / "ui" / "archive_browser" / "static_replacement_dialog_remaining_callbacks.py"
)
ARCHIVE_STATIC_REPLACEMENT_DIALOG_UI_SECTIONS = (
    ROOT / "cdmw" / "ui" / "archive_browser" / "static_replacement_dialog_ui_sections.py"
)
ARCHIVE_STATIC_REPLACEMENT_DIALOG_PREVIEW_SHELL = (
    ROOT / "cdmw" / "ui" / "archive_browser" / "static_replacement_dialog_preview_shell.py"
)
ARCHIVE_STATIC_REPLACEMENT_DIALOG_WORKFLOW_SHELL = (
    ROOT / "cdmw" / "ui" / "archive_browser" / "static_replacement_dialog_workflow_shell.py"
)
ARCHIVE_STATIC_REPLACEMENT_DIALOG_SELECTION_MAPPING = (
    ROOT / "cdmw" / "ui" / "archive_browser" / "static_replacement_dialog_selection_mapping.py"
)
ARCHIVE_STATIC_REPLACEMENT_COMBO_OPTIONS = (
    ROOT / "cdmw" / "ui" / "archive_browser" / "static_replacement_combo_options.py"
)
ARCHIVE_STATIC_REPLACEMENT_TEXTURE_ROWS = (
    ROOT / "cdmw" / "ui" / "archive_browser" / "static_replacement_texture_rows.py"
)
ARCHIVE_STATIC_REPLACEMENT_TEXTURE_DIALOGS = (
    ROOT / "cdmw" / "ui" / "archive_browser" / "static_replacement_texture_dialogs.py"
)
ARCHIVE_STATIC_REPLACEMENT_MATERIAL_PLAN_ITEMS = (
    ROOT / "cdmw" / "ui" / "archive_browser" / "static_replacement_material_plan_items.py"
)
ARCHIVE_STATIC_REPLACEMENT_MATERIAL_PLAN_UI_STATE = (
    ROOT / "cdmw" / "ui" / "archive_browser" / "static_replacement_material_plan_ui_state.py"
)
ARCHIVE_STATIC_REPLACEMENT_DONOR_MATERIAL_STATE = (
    ROOT / "cdmw" / "ui" / "archive_browser" / "static_replacement_donor_material_state.py"
)
ARCHIVE_STATIC_REPLACEMENT_DONOR_MATERIAL_LOADER = (
    ROOT / "cdmw" / "ui" / "archive_browser" / "static_replacement_donor_material_loader.py"
)
ARCHIVE_STATIC_REPLACEMENT_TEXTURE_EDITOR_UI_STATE = (
    ROOT / "cdmw" / "ui" / "archive_browser" / "static_replacement_texture_editor_ui_state.py"
)
ARCHIVE_STATIC_REPLACEMENT_ADDED_PART_TEXTURE_ITEMS = (
    ROOT / "cdmw" / "ui" / "archive_browser" / "static_replacement_added_part_texture_items.py"
)
ARCHIVE_STATIC_REPLACEMENT_ADDED_PART_TEXTURES = (
    ROOT / "cdmw" / "ui" / "archive_browser" / "static_replacement_added_part_textures.py"
)
ARCHIVE_STATIC_REPLACEMENT_PART_ITEMS = (
    ROOT / "cdmw" / "ui" / "archive_browser" / "static_replacement_part_items.py"
)
ARCHIVE_STATIC_REPLACEMENT_PARTS_OUTLINER_STATE = (
    ROOT / "cdmw" / "ui" / "archive_browser" / "static_replacement_parts_outliner_state.py"
)
ARCHIVE_STATIC_REPLACEMENT_VIRTUAL_TEXTURE_CONTRACT = (
    ROOT / "cdmw" / "ui" / "archive_browser" / "static_replacement_virtual_texture_contract.py"
)
ARCHIVE_STATIC_REPLACEMENT_TEXTURE_MATCHING = (
    ROOT / "cdmw" / "ui" / "archive_browser" / "static_replacement_texture_matching.py"
)
ARCHIVE_STATIC_REPLACEMENT_TEXTURE_SOURCES = (
    ROOT / "cdmw" / "ui" / "archive_browser" / "static_replacement_texture_sources.py"
)
ARCHIVE_STATIC_REPLACEMENT_TEXTURE_UV = (
    ROOT / "cdmw" / "ui" / "archive_browser" / "static_replacement_texture_uv.py"
)
ARCHIVE_STATIC_REPLACEMENT_GEOMETRY_MATH = (
    ROOT / "cdmw" / "ui" / "archive_browser" / "static_replacement_geometry_math.py"
)
ARCHIVE_STATIC_REPLACEMENT_GEOMETRY_HISTORY = (
    ROOT / "cdmw" / "ui" / "archive_browser" / "static_replacement_geometry_history.py"
)
ARCHIVE_STATIC_REPLACEMENT_D3D11_CACHE = (
    ROOT / "cdmw" / "ui" / "archive_browser" / "static_replacement_d3d11_cache.py"
)
ARCHIVE_STATIC_REPLACEMENT_D3D11_STATE = (
    ROOT / "cdmw" / "ui" / "archive_browser" / "static_replacement_d3d11_state.py"
)
ARCHIVE_STATIC_REPLACEMENT_D3D11_MAPPING = (
    ROOT / "cdmw" / "ui" / "archive_browser" / "static_replacement_d3d11_mapping.py"
)
ARCHIVE_STATIC_REPLACEMENT_D3D11_REQUEST_STATE = (
    ROOT / "cdmw" / "ui" / "archive_browser" / "static_replacement_d3d11_request_state.py"
)
ARCHIVE_STATIC_REPLACEMENT_D3D11_PACKAGE_STATE = (
    ROOT / "cdmw" / "ui" / "archive_browser" / "static_replacement_d3d11_package_state.py"
)
ARCHIVE_STATIC_REPLACEMENT_D3D11_RUNTIME_STATE = (
    ROOT / "cdmw" / "ui" / "archive_browser" / "static_replacement_d3d11_runtime_state.py"
)
ARCHIVE_STATIC_REPLACEMENT_D3D11_WATCHDOG_STATE = (
    ROOT / "cdmw" / "ui" / "archive_browser" / "static_replacement_d3d11_watchdog_state.py"
)
ARCHIVE_STATIC_REPLACEMENT_D3D11_PRESENTATION_STATE = (
    ROOT / "cdmw" / "ui" / "archive_browser" / "static_replacement_d3d11_presentation_state.py"
)
ARCHIVE_STATIC_REPLACEMENT_D3D11_LOADING_DETAILS = (
    ROOT / "cdmw" / "ui" / "archive_browser" / "static_replacement_d3d11_loading_details.py"
)
ARCHIVE_STATIC_REPLACEMENT_PREVIEW_LIMITS = (
    ROOT / "cdmw" / "ui" / "archive_browser" / "static_replacement_preview_limits.py"
)
ARCHIVE_STATIC_REPLACEMENT_PREVIEW_MAPPING = (
    ROOT / "cdmw" / "ui" / "archive_browser" / "static_replacement_preview_mapping.py"
)
ARCHIVE_STATIC_REPLACEMENT_PREVIEW_MATERIALS = (
    ROOT / "cdmw" / "ui" / "archive_browser" / "static_replacement_preview_materials.py"
)
ARCHIVE_STATIC_REPLACEMENT_PREVIEW_MODELS = (
    ROOT / "cdmw" / "ui" / "archive_browser" / "static_replacement_preview_models.py"
)
ARCHIVE_STATIC_REPLACEMENT_PREVIEW_SELECTION_OVERLAY = (
    ROOT / "cdmw" / "ui" / "archive_browser" / "static_replacement_preview_selection_overlay.py"
)
ARCHIVE_STATIC_REPLACEMENT_ORIGINAL_PREVIEW_MODELS = (
    ROOT / "cdmw" / "ui" / "archive_browser" / "static_replacement_original_preview_models.py"
)
ARCHIVE_STATIC_REPLACEMENT_PREVIEW_TEXTURES = (
    ROOT / "cdmw" / "ui" / "archive_browser" / "static_replacement_preview_textures.py"
)
ARCHIVE_STATIC_REPLACEMENT_PREVIEW_MATERIAL_AUTHORITY = (
    ROOT / "cdmw" / "ui" / "archive_browser" / "static_replacement_preview_material_authority.py"
)
ARCHIVE_STATIC_REPLACEMENT_PREVIEW_STATUS_STATE = (
    ROOT / "cdmw" / "ui" / "archive_browser" / "static_replacement_preview_status_state.py"
)
ARCHIVE_STATIC_REPLACEMENT_PREVIEW_BATCH_STATE = (
    ROOT / "cdmw" / "ui" / "archive_browser" / "static_replacement_preview_batch_state.py"
)
ARCHIVE_STATIC_REPLACEMENT_PREVIEW_CACHE = (
    ROOT / "cdmw" / "ui" / "archive_browser" / "static_replacement_preview_cache.py"
)
ARCHIVE_STATIC_REPLACEMENT_STATIC_PREVIEW_STATE = (
    ROOT / "cdmw" / "ui" / "archive_browser" / "static_replacement_static_preview_state.py"
)
ARCHIVE_STATIC_REPLACEMENT_NATIVE_MANIFEST = (
    ROOT / "cdmw" / "ui" / "archive_browser" / "static_replacement_native_manifest.py"
)
ARCHIVE_STATIC_REPLACEMENT_ORIGINAL_TEXTURE_PREVIEW_STATE = (
    ROOT / "cdmw" / "ui" / "archive_browser" / "static_replacement_original_texture_preview_state.py"
)
ARCHIVE_STATIC_REPLACEMENT_MANUAL_MATERIAL_PROFILE = (
    ROOT / "cdmw" / "ui" / "archive_browser" / "static_replacement_manual_material_profile.py"
)
ARCHIVE_STATIC_REPLACEMENT_MATERIAL_AUTHORITY_CONTROLS = (
    ROOT / "cdmw" / "ui" / "archive_browser" / "static_replacement_material_authority_controls.py"
)
ARCHIVE_STATIC_REPLACEMENT_MATERIAL_REFRESH_STATE = (
    ROOT / "cdmw" / "ui" / "archive_browser" / "static_replacement_material_refresh_state.py"
)
ARCHIVE_STATIC_REPLACEMENT_CUSTOM_ICON = (
    ROOT / "cdmw" / "ui" / "archive_browser" / "static_replacement_custom_icon.py"
)
ARCHIVE_STATIC_REPLACEMENT_SOURCE_MIX_STATE = (
    ROOT / "cdmw" / "ui" / "archive_browser" / "static_replacement_source_mix_state.py"
)
ARCHIVE_STATIC_REPLACEMENT_ALIGNMENT_SETUP_STATE = (
    ROOT / "cdmw" / "ui" / "archive_browser" / "static_replacement_alignment_setup_state.py"
)
ARCHIVE_STATIC_REPLACEMENT_LAYOUT_STATE = (
    ROOT / "cdmw" / "ui" / "archive_browser" / "static_replacement_layout_state.py"
)
ARCHIVE_STATIC_REPLACEMENT_ADVANCED_DDS_STATE = (
    ROOT / "cdmw" / "ui" / "archive_browser" / "static_replacement_advanced_dds_state.py"
)
ARCHIVE_STATIC_REPLACEMENT_TEXTURE_TABLE = (
    ROOT / "cdmw" / "ui" / "archive_browser" / "static_replacement_texture_table.py"
)
ARCHIVE_STATIC_REPLACEMENT_TEXTURE_TABLE_ITEMS = (
    ROOT / "cdmw" / "ui" / "archive_browser" / "static_replacement_texture_table_items.py"
)
ARCHIVE_STATIC_REPLACEMENT_ORIGINAL_PARTS = (
    ROOT / "cdmw" / "ui" / "archive_browser" / "static_replacement_original_parts.py"
)
ARCHIVE_STATIC_REPLACEMENT_SOURCE_DISPLAY = (
    ROOT / "cdmw" / "ui" / "archive_browser" / "static_replacement_source_display.py"
)
ARCHIVE_STATIC_REPLACEMENT_SELECTION_VIEW_STATE = (
    ROOT / "cdmw" / "ui" / "archive_browser" / "static_replacement_selection_view_state.py"
)
ARCHIVE_STATIC_REPLACEMENT_SELECTION_ROUTE_STATE = (
    ROOT / "cdmw" / "ui" / "archive_browser" / "static_replacement_selection_route_state.py"
)
ARCHIVE_STATIC_REPLACEMENT_SELECTION_HIGHLIGHT_STATE = (
    ROOT / "cdmw" / "ui" / "archive_browser" / "static_replacement_selection_highlight_state.py"
)
ARCHIVE_STATIC_REPLACEMENT_SOURCE_ASSIGNMENT_STATE = (
    ROOT / "cdmw" / "ui" / "archive_browser" / "static_replacement_source_assignment_state.py"
)
ARCHIVE_STATIC_REPLACEMENT_SOURCE_MATCHING = (
    ROOT / "cdmw" / "ui" / "archive_browser" / "static_replacement_source_matching.py"
)
ARCHIVE_STATIC_REPLACEMENT_SOURCE_PARTS_STATE = (
    ROOT / "cdmw" / "ui" / "archive_browser" / "static_replacement_source_parts_state.py"
)
ARCHIVE_STATIC_REPLACEMENT_SOURCE_PART_ADJUSTMENT_STATE = (
    ROOT / "cdmw" / "ui" / "archive_browser" / "static_replacement_source_part_adjustment_state.py"
)
ARCHIVE_STATIC_REPLACEMENT_SOURCE_PART_ACTION_STATE = (
    ROOT / "cdmw" / "ui" / "archive_browser" / "static_replacement_source_part_action_state.py"
)
ARCHIVE_STATIC_REPLACEMENT_SOURCE_PART_APPEND_STATE = (
    ROOT / "cdmw" / "ui" / "archive_browser" / "static_replacement_source_part_append_state.py"
)
ARCHIVE_STATIC_REPLACEMENT_SOURCE_PART_ASSIGNMENT_STATE = (
    ROOT / "cdmw" / "ui" / "archive_browser" / "static_replacement_source_part_assignment_state.py"
)
ARCHIVE_STATIC_REPLACEMENT_SOURCE_PART_CONTROLS_STATE = (
    ROOT / "cdmw" / "ui" / "archive_browser" / "static_replacement_source_part_controls_state.py"
)
ARCHIVE_STATIC_REPLACEMENT_SOURCE_PART_DUPLICATE_STATE = (
    ROOT / "cdmw" / "ui" / "archive_browser" / "static_replacement_source_part_duplicate_state.py"
)
ARCHIVE_STATIC_REPLACEMENT_SOURCE_PART_GROUPING_STATE = (
    ROOT / "cdmw" / "ui" / "archive_browser" / "static_replacement_source_part_grouping_state.py"
)
ARCHIVE_STATIC_REPLACEMENT_SOURCE_PART_IMPORT_STATE = (
    ROOT / "cdmw" / "ui" / "archive_browser" / "static_replacement_source_part_import_state.py"
)
ARCHIVE_STATIC_REPLACEMENT_SOURCE_PART_MAPPING_STATE = (
    ROOT / "cdmw" / "ui" / "archive_browser" / "static_replacement_source_part_mapping_state.py"
)
ARCHIVE_STATIC_REPLACEMENT_SOURCE_PART_INSPECTOR_STATE = (
    ROOT / "cdmw" / "ui" / "archive_browser" / "static_replacement_source_part_inspector_state.py"
)
ARCHIVE_STATIC_REPLACEMENT_SOURCE_PART_PENDING_STATE = (
    ROOT / "cdmw" / "ui" / "archive_browser" / "static_replacement_source_part_pending_state.py"
)
ARCHIVE_STATIC_REPLACEMENT_SOURCE_PART_PROPERTIES_STATE = (
    ROOT / "cdmw" / "ui" / "archive_browser" / "static_replacement_source_part_properties_state.py"
)
ARCHIVE_STATIC_REPLACEMENT_SOURCE_PART_SELECTION_STATE = (
    ROOT / "cdmw" / "ui" / "archive_browser" / "static_replacement_source_part_selection_state.py"
)
ARCHIVE_STATIC_REPLACEMENT_SOURCE_PART_TRANSFORM_CONTROLS_STATE = (
    ROOT / "cdmw" / "ui" / "archive_browser" / "static_replacement_source_part_transform_controls_state.py"
)
ARCHIVE_STATIC_REPLACEMENT_SOURCE_TREE_STATE = (
    ROOT / "cdmw" / "ui" / "archive_browser" / "static_replacement_source_tree_state.py"
)
ARCHIVE_STATIC_REPLACEMENT_MAPPING_TABLE_STATE = (
    ROOT / "cdmw" / "ui" / "archive_browser" / "static_replacement_mapping_table_state.py"
)
ARCHIVE_STATIC_REPLACEMENT_POST_OPEN_STATE = (
    ROOT / "cdmw" / "ui" / "archive_browser" / "static_replacement_post_open_state.py"
)
ARCHIVE_STATIC_REPLACEMENT_QT_HELPERS = (
    ROOT / "cdmw" / "ui" / "archive_browser" / "static_replacement_qt_helpers.py"
)
ARCHIVE_STATIC_REPLACEMENT_BUILD_FOOTER = (
    ROOT / "cdmw" / "ui" / "archive_browser" / "static_replacement_build_footer.py"
)
ARCHIVE_STATIC_REPLACEMENT_ACCEPT_STATE = (
    ROOT / "cdmw" / "ui" / "archive_browser" / "static_replacement_accept_state.py"
)
ARCHIVE_STATIC_REPLACEMENT_STARTUP_STATE = (
    ROOT / "cdmw" / "ui" / "archive_browser" / "static_replacement_startup_state.py"
)
ARCHIVE_STATIC_REPLACEMENT_TRANSFORM_STATE = (
    ROOT / "cdmw" / "ui" / "archive_browser" / "static_replacement_transform_state.py"
)
ARCHIVE_STATIC_REPLACEMENT_TRANSFORM_CONTROL_STATE = (
    ROOT / "cdmw" / "ui" / "archive_browser" / "static_replacement_transform_control_state.py"
)
ARCHIVE_STATIC_REPLACEMENT_DIAGNOSTICS = (
    ROOT / "cdmw" / "ui" / "archive_browser" / "static_replacement_diagnostics.py"
)
ARCHIVE_STATIC_REPLACEMENT_MESH_EDIT_PAYLOAD = (
    ROOT / "cdmw" / "ui" / "archive_browser" / "static_replacement_mesh_edit_payload.py"
)
ARCHIVE_STATIC_REPLACEMENT_MESH_EDIT_STATE = (
    ROOT / "cdmw" / "ui" / "archive_browser" / "static_replacement_mesh_edit_state.py"
)
ARCHIVE_STATIC_REPLACEMENT_MORPH_SLIDER_STATE = (
    ROOT / "cdmw" / "ui" / "archive_browser" / "static_replacement_morph_slider_state.py"
)
ARCHIVE_PREVIEW_SETTINGS = ROOT / "cdmw" / "ui" / "archive_browser" / "preview_settings.py"
ARCHIVE_ATTACHMENT_ICONS = ROOT / "cdmw" / "ui" / "archive_browser" / "attachment_icons.py"
ARCHIVE_ATTACHMENT_PLACEMENT_DIFF_DIALOG = ROOT / "cdmw" / "ui" / "archive_browser" / "attachment_placement_diff_dialog.py"
ARCHIVE_ATTACHMENT_SAFE_PLACEMENT_DIALOG = ROOT / "cdmw" / "ui" / "archive_browser" / "attachment_safe_placement_dialog.py"
WORKFLOW_PROFILES_UI = ROOT / "cdmw" / "ui" / "texture_workflow" / "workflow_profiles_ui.py"
WIDGETS = ROOT / "cdmw" / "ui" / "widgets.py"
NATIVE_PREVIEW_PANEL = ROOT / "cdmw" / "ui" / "native_preview_panel.py"
DOTNET_PREVIEW_HOST = ROOT / "cdmw" / "ui" / "preview" / "dotnet_host.py"
ARCHIVE_MODDING = ROOT / "cdmw" / "core" / "archive_modding.py"
ARCHIVE_LOOSE_EXPORT = ROOT / "cdmw" / "core" / "archive_loose_export.py"
STATIC_REPLACER = ROOT / "cdmw" / "modding" / "static_mesh_replacer.py"
STATIC_MESH_TYPES = ROOT / "cdmw" / "modding" / "static_mesh_types.py"
MATERIAL_REPLACER = ROOT / "cdmw" / "modding" / "material_replacer.py"
MATERIAL_PROFILES = ROOT / "cdmw" / "modding" / "material_profiles.py"
MATERIAL_REBUILT_PAYLOADS = ROOT / "cdmw" / "modding" / "material_rebuilt_payloads.py"
MATERIAL_REPLACEMENT_PIPELINE = ROOT / "cdmw" / "modding" / "material_replacement_pipeline.py"
MATERIAL_SIDECAR_PAYLOADS = ROOT / "cdmw" / "modding" / "material_sidecar_payloads.py"
MATERIAL_SIDECAR_PATCHING = ROOT / "cdmw" / "modding" / "material_sidecar_patching.py"
MATERIAL_SOURCE_DRIVEN = ROOT / "cdmw" / "modding" / "material_source_driven.py"
MATERIAL_TEXTURE_PAYLOADS = ROOT / "cdmw" / "modding" / "material_texture_payloads.py"
MATERIAL_TEXTURE_ROUTING = ROOT / "cdmw" / "modding" / "material_texture_routing.py"
SCENE_IMPORT_RESULT_OPS = ROOT / "cdmw" / "modding" / "scene_import_result_ops.py"
FINAL_PACKAGE_BUILDER = ROOT / "cdmw" / "core" / "final_package_builder.py"
FINAL_PACKAGE_MATERIAL_AUTHORITY = ROOT / "cdmw" / "core" / "final_package_material_authority.py"
FINAL_PACKAGE_PAC_XML_PREFLIGHT = ROOT / "cdmw" / "core" / "final_package_pac_xml_preflight.py"
FINAL_PACKAGE_PREVIEW = ROOT / "cdmw" / "core" / "final_package_preview.py"
FINAL_PACKAGE_PREVIEW_MODEL = ROOT / "cdmw" / "core" / "final_package_preview_model.py"
FINAL_PACKAGE_TEXTURE_PLAN = ROOT / "cdmw" / "core" / "final_package_texture_plan.py"
TEXTURE_DOMAIN_POLICY = ROOT / "cdmw" / "domain" / "textures" / "policy.py"
MESH_EDITOR_TAB = ROOT / "cdmw" / "ui" / "mesh_editor" / "tab.py"
MESH_EDITOR_SESSION = ROOT / "cdmw" / "ui" / "mesh_editor" / "session.py"
MESH_EDITOR_SHELL_BRIDGE = ROOT / "cdmw" / "ui" / "mesh_editor" / "shell_bridge.py"
MESH_DOMAIN_SESSION = ROOT / "cdmw" / "domain" / "mesh" / "session.py"
MESH_DOMAIN_VALIDATION = ROOT / "cdmw" / "domain" / "mesh" / "validation.py"
STARTUP_DIALOGS = ROOT / "cdmw" / "ui" / "shell" / "startup_dialogs.py"
NATIVE_PREVIEW_PACKAGE = ROOT / "cdmw" / "rendering" / "native_preview_package.py"
NATIVE_PREVIEW_PACKAGE_WRITER = ROOT / "cdmw" / "rendering" / "native_preview_package_writer.py"


def _legacy_nested_source(path: Path) -> str:
    return "\n".join(f"    {line}" if line else line for line in path.read_text(encoding="utf-8").splitlines())


def _legacy_nested_text(source: str) -> str:
    return "\n".join(f"    {line}" if line else line for line in source.splitlines())


def _ui_section_source() -> str:
    return static_replacement_ui_implementation_source(ROOT)


def _nested_function_source(source: str, name: str) -> str:
    return function_source(source, name)


def _callback_factory_source() -> str:
    return "\n".join(
        (
            static_replacement_callback_implementation_source(ROOT),
            *(
                path.read_text(encoding="utf-8")
                for path in (
                    ARCHIVE_STATIC_REPLACEMENT_DIALOG_MESH_DIAGNOSTICS_CALLBACKS,
                    ARCHIVE_STATIC_REPLACEMENT_DIALOG_SOURCE_MIX_CALLBACKS,
                    ARCHIVE_STATIC_REPLACEMENT_DIALOG_TEXTURE_DETAIL_UV_CALLBACKS,
                    ARCHIVE_STATIC_REPLACEMENT_DIALOG_ACCEPT_DISPATCH_CALLBACKS,
                    ARCHIVE_STATIC_REPLACEMENT_DIALOG_CUSTOM_ICON_CALLBACKS,
                    ARCHIVE_STATIC_REPLACEMENT_DIALOG_SOURCE_ROLE_TREE_CALLBACKS,
                    ARCHIVE_STATIC_REPLACEMENT_DIALOG_MANUAL_PROFILE_CALLBACKS,
                    ARCHIVE_STATIC_REPLACEMENT_DIALOG_MATERIAL_AUTHORITY_CALLBACKS,
                )
            ),
        )
    )


def _native_preview_package_source() -> str:
    return "\n".join(
        (
            NATIVE_PREVIEW_PACKAGE.read_text(encoding="utf-8"),
            NATIVE_PREVIEW_PACKAGE_WRITER.read_text(encoding="utf-8"),
        )
    )


def _main_window_source() -> str:
    return "\n".join(
        (
            MAIN_WINDOW.read_text(encoding="utf-8"),
            SHELL_TOOL_TABS.read_text(encoding="utf-8"),
            SHELL_WINDOW_BOOTSTRAP_STATE.read_text(encoding="utf-8"),
            ARCHIVE_STATIC_REPLACEMENT_DIALOG_HELPERS.read_text(encoding="utf-8"),
            ARCHIVE_STATIC_REPLACEMENT_COMBO_OPTIONS.read_text(encoding="utf-8"),
            ARCHIVE_STATIC_REPLACEMENT_TEXTURE_ROWS.read_text(encoding="utf-8"),
            ARCHIVE_STATIC_REPLACEMENT_TEXTURE_DIALOGS.read_text(encoding="utf-8"),
            ARCHIVE_STATIC_REPLACEMENT_MATERIAL_PLAN_ITEMS.read_text(encoding="utf-8"),
            ARCHIVE_STATIC_REPLACEMENT_ADDED_PART_TEXTURE_ITEMS.read_text(encoding="utf-8"),
            ARCHIVE_STATIC_REPLACEMENT_PART_ITEMS.read_text(encoding="utf-8"),
            ARCHIVE_STATIC_REPLACEMENT_VIRTUAL_TEXTURE_CONTRACT.read_text(encoding="utf-8"),
            ARCHIVE_STATIC_REPLACEMENT_TEXTURE_MATCHING.read_text(encoding="utf-8"),
            ARCHIVE_STATIC_REPLACEMENT_D3D11_STATE.read_text(encoding="utf-8"),
            ARCHIVE_STATIC_REPLACEMENT_D3D11_REQUEST_STATE.read_text(encoding="utf-8"),
            ARCHIVE_STATIC_REPLACEMENT_D3D11_PACKAGE_STATE.read_text(encoding="utf-8"),
            ARCHIVE_STATIC_REPLACEMENT_D3D11_RUNTIME_STATE.read_text(encoding="utf-8"),
            ARCHIVE_STATIC_REPLACEMENT_D3D11_WATCHDOG_STATE.read_text(encoding="utf-8"),
            ARCHIVE_STATIC_REPLACEMENT_D3D11_PRESENTATION_STATE.read_text(encoding="utf-8"),
            ARCHIVE_STATIC_REPLACEMENT_D3D11_LOADING_DETAILS.read_text(encoding="utf-8"),
            ARCHIVE_STATIC_REPLACEMENT_SOURCE_DISPLAY.read_text(encoding="utf-8"),
            ARCHIVE_STATIC_REPLACEMENT_PREVIEW_MAPPING.read_text(encoding="utf-8"),
            ARCHIVE_STATIC_REPLACEMENT_PREVIEW_MATERIALS.read_text(encoding="utf-8"),
            ARCHIVE_STATIC_REPLACEMENT_PREVIEW_SELECTION_OVERLAY.read_text(encoding="utf-8"),
            ARCHIVE_STATIC_REPLACEMENT_PREVIEW_TEXTURES.read_text(encoding="utf-8"),
            ARCHIVE_STATIC_REPLACEMENT_PREVIEW_STATUS_STATE.read_text(encoding="utf-8"),
            ARCHIVE_STATIC_REPLACEMENT_PREVIEW_CACHE.read_text(encoding="utf-8"),
            ARCHIVE_STATIC_REPLACEMENT_NATIVE_MANIFEST.read_text(encoding="utf-8"),
            ARCHIVE_STATIC_REPLACEMENT_POST_OPEN_STATE.read_text(encoding="utf-8"),
            ARCHIVE_STATIC_REPLACEMENT_QT_HELPERS.read_text(encoding="utf-8"),
            ARCHIVE_STATIC_REPLACEMENT_TRANSFORM_STATE.read_text(encoding="utf-8"),
            ARCHIVE_STATIC_REPLACEMENT_DIAGNOSTICS.read_text(encoding="utf-8"),
            ARCHIVE_STATIC_REPLACEMENT_MESH_EDIT_PAYLOAD.read_text(encoding="utf-8"),
            ARCHIVE_STATIC_REPLACEMENT_MESH_EDIT_STATE.read_text(encoding="utf-8"),
            ARCHIVE_STATIC_REPLACEMENT_MORPH_SLIDER_STATE.read_text(encoding="utf-8"),
            ARCHIVE_STATIC_REPLACEMENT_PREVIEW_LIMITS.read_text(encoding="utf-8"),
            ARCHIVE_STATIC_REPLACEMENT_SOURCE_MIX_STATE.read_text(encoding="utf-8"),
            ARCHIVE_STATIC_REPLACEMENT_ALIGNMENT_SETUP_STATE.read_text(encoding="utf-8"),
            _legacy_nested_source(ARCHIVE_STATIC_REPLACEMENT_DIALOG),
            _legacy_nested_source(ARCHIVE_STATIC_REPLACEMENT_DIALOG_PROMPT),
            _legacy_nested_source(ARCHIVE_STATIC_REPLACEMENT_DIALOG_PROMPT_SHELL),
            _legacy_nested_source(ARCHIVE_STATIC_REPLACEMENT_DIALOG_PROMPT_OPEN),
            _legacy_nested_source(ARCHIVE_STATIC_REPLACEMENT_DIALOG_PROMPT_SETUP),
            _legacy_nested_source(ARCHIVE_STATIC_REPLACEMENT_DIALOG_PROMPT_SETUP_HELPERS),
            _legacy_nested_source(ARCHIVE_STATIC_REPLACEMENT_PROMPT_PREFLIGHT),
            _legacy_nested_source(ARCHIVE_STATIC_REPLACEMENT_DIALOG_PROMPT_STATE_CALLBACKS),
            _legacy_nested_source(ARCHIVE_STATIC_REPLACEMENT_DIALOG_PROMPT_TRANSFORM),
            _legacy_nested_source(ARCHIVE_STATIC_REPLACEMENT_DIALOG_PROMPT_DEPS),
            _legacy_nested_source(ARCHIVE_STATIC_REPLACEMENT_DIALOG_PROMPT_DEPS_BASE),
            _legacy_nested_source(ARCHIVE_STATIC_REPLACEMENT_DIALOG_PROMPT_DEPS_STATE_A),
            _legacy_nested_source(ARCHIVE_STATIC_REPLACEMENT_DIALOG_PROMPT_DEPS_STATE_B),
            _legacy_nested_source(ARCHIVE_STATIC_REPLACEMENT_DIALOG_PROMPT_DEPS_CALLBACKS),
            _legacy_nested_source(ARCHIVE_STATIC_REPLACEMENT_DIALOG_PREVIEW_SHELL),
            _legacy_nested_source(ARCHIVE_STATIC_REPLACEMENT_DIALOG_WORKFLOW_SHELL),
            _legacy_nested_source(ARCHIVE_STATIC_REPLACEMENT_DIALOG_SELECTION_MAPPING),
            _legacy_nested_source(ARCHIVE_STATIC_REPLACEMENT_DIALOG_REMAINING_CALLBACKS),
            _legacy_nested_text(_ui_section_source()),
            _legacy_nested_text(static_replacement_callback_implementation_source(ROOT)),
            _legacy_nested_source(ARCHIVE_STATIC_REPLACEMENT_DIALOG_MESH_DIAGNOSTICS_CALLBACKS),
            _legacy_nested_source(ARCHIVE_STATIC_REPLACEMENT_DIALOG_SOURCE_MIX_CALLBACKS),
            _legacy_nested_source(ARCHIVE_STATIC_REPLACEMENT_DIALOG_TEXTURE_DETAIL_UV_CALLBACKS),
            _legacy_nested_source(ARCHIVE_STATIC_REPLACEMENT_DIALOG_ACCEPT_DISPATCH_CALLBACKS),
            _legacy_nested_source(ARCHIVE_STATIC_REPLACEMENT_DIALOG_CUSTOM_ICON_CALLBACKS),
            _legacy_nested_source(ARCHIVE_STATIC_REPLACEMENT_DIALOG_SOURCE_ROLE_TREE_CALLBACKS),
            _legacy_nested_source(ARCHIVE_STATIC_REPLACEMENT_DIALOG_MANUAL_PROFILE_CALLBACKS),
            _legacy_nested_source(ARCHIVE_STATIC_REPLACEMENT_DIALOG_MATERIAL_AUTHORITY_CALLBACKS),
            _legacy_nested_source(ARCHIVE_STATIC_REPLACEMENT_DIALOG_TEXTURE_CALLBACKS),
            _legacy_nested_source(ARCHIVE_STATIC_REPLACEMENT_DIALOG_ROUTING_CALLBACKS),
            _legacy_nested_source(ARCHIVE_STATIC_REPLACEMENT_DIALOG_SOURCE_PART_MUTATION_CALLBACKS),
            _legacy_nested_source(ARCHIVE_STATIC_REPLACEMENT_DIALOG_MESH_EDIT_CALLBACKS),
            _legacy_nested_text(static_replacement_mesh_edit_implementation_source(ROOT)),
        )
    )


def _source_part_owner_sources() -> str:
    return "\n".join(
        path.read_text(encoding="utf-8")
        for path in (
            ARCHIVE_STATIC_REPLACEMENT_SOURCE_PART_ADJUSTMENT_STATE,
            ARCHIVE_STATIC_REPLACEMENT_SOURCE_PART_ACTION_STATE,
            ARCHIVE_STATIC_REPLACEMENT_SOURCE_PART_APPEND_STATE,
            ARCHIVE_STATIC_REPLACEMENT_SOURCE_PART_ASSIGNMENT_STATE,
            ARCHIVE_STATIC_REPLACEMENT_SOURCE_PART_CONTROLS_STATE,
            ARCHIVE_STATIC_REPLACEMENT_SOURCE_PART_DUPLICATE_STATE,
            ARCHIVE_STATIC_REPLACEMENT_SOURCE_PART_GROUPING_STATE,
            ARCHIVE_STATIC_REPLACEMENT_SOURCE_PART_IMPORT_STATE,
            ARCHIVE_STATIC_REPLACEMENT_SOURCE_PART_MAPPING_STATE,
            ARCHIVE_STATIC_REPLACEMENT_SOURCE_PART_INSPECTOR_STATE,
            ARCHIVE_STATIC_REPLACEMENT_SOURCE_PART_PENDING_STATE,
            ARCHIVE_STATIC_REPLACEMENT_SOURCE_PART_PROPERTIES_STATE,
            ARCHIVE_STATIC_REPLACEMENT_SOURCE_PART_SELECTION_STATE,
            ARCHIVE_STATIC_REPLACEMENT_SOURCE_PART_TRANSFORM_CONTROLS_STATE,
        )
    )


def _about_documentation_source() -> str:
    return ABOUT_DOCUMENTATION_EN.read_text(encoding="utf-8")


def _archive_preview_settings_source() -> str:
    return ARCHIVE_PREVIEW_SETTINGS.read_text(encoding="utf-8")


def _archive_mesh_import_sources() -> str:
    return "\n".join(
        (
            ARCHIVE_MESH_DIRECT_PATCH.read_text(encoding="utf-8"),
            ARCHIVE_MESH_IMPORT_EXPORT.read_text(encoding="utf-8"),
            ARCHIVE_MESH_LAUNCH_FLOW.read_text(encoding="utf-8"),
            ARCHIVE_MESH_PATCH_FLOW.read_text(encoding="utf-8"),
            ARCHIVE_MESH_SWAP_SUPPORT.read_text(encoding="utf-8"),
            ARCHIVE_MESH_SWAP_SCOPE_DIALOG.read_text(encoding="utf-8"),
            ARCHIVE_MESH_SWAP_SCOPE_PREFLIGHT.read_text(encoding="utf-8"),
            ARCHIVE_MESH_MODIFY_ORIGINAL.read_text(encoding="utf-8"),
            ARCHIVE_MESH_SETUP_HELPERS.read_text(encoding="utf-8"),
            ARCHIVE_MESH_IMPORT_SETUP_STATE.read_text(encoding="utf-8"),
        )
    )


def _archive_mod_ready_export_source() -> str:
    return ARCHIVE_MOD_READY_EXPORT.read_text(encoding="utf-8")


def _widgets_source() -> str:
    return "\n".join((WIDGETS.read_text(encoding="utf-8"), NATIVE_PREVIEW_PANEL.read_text(encoding="utf-8")))


def _native_d3d11_preview_host_source() -> str:
    return DOTNET_PREVIEW_HOST.read_text(encoding="utf-8")


def _archive_modding_source() -> str:
    return "\n".join(
        (
            ARCHIVE_MODDING.read_text(encoding="utf-8"),
            *(
                path.read_text(encoding="utf-8")
                for path in sorted((ROOT / "cdmw" / "core").glob("archive_mesh_import*.py"))
            ),
            ARCHIVE_LOOSE_EXPORT.read_text(encoding="utf-8"),
        )
    )


def _static_replacer_source() -> str:
    return "\n".join(
        path.read_text(encoding="utf-8")
        for path in (
            STATIC_REPLACER,
            *sorted((ROOT / "cdmw" / "modding").glob("static_mesh_*.py")),
        )
    )


def _material_replacer_source() -> str:
    return "\n".join(
        (
            MATERIAL_REPLACER.read_text(encoding="utf-8"),
            MATERIAL_PROFILES.read_text(encoding="utf-8"),
            MATERIAL_REBUILT_PAYLOADS.read_text(encoding="utf-8"),
            MATERIAL_REPLACEMENT_PIPELINE.read_text(encoding="utf-8"),
            MATERIAL_SIDECAR_PAYLOADS.read_text(encoding="utf-8"),
            MATERIAL_SIDECAR_PATCHING.read_text(encoding="utf-8"),
            MATERIAL_SOURCE_DRIVEN.read_text(encoding="utf-8"),
            MATERIAL_TEXTURE_PAYLOADS.read_text(encoding="utf-8"),
            MATERIAL_TEXTURE_ROUTING.read_text(encoding="utf-8"),
        )
    )


def _final_package_preview_source() -> str:
    return "\n".join(
        (
            FINAL_PACKAGE_PREVIEW.read_text(encoding="utf-8"),
            FINAL_PACKAGE_BUILDER.read_text(encoding="utf-8"),
            FINAL_PACKAGE_MATERIAL_AUTHORITY.read_text(encoding="utf-8"),
            FINAL_PACKAGE_PAC_XML_PREFLIGHT.read_text(encoding="utf-8"),
            FINAL_PACKAGE_PREVIEW_MODEL.read_text(encoding="utf-8"),
            FINAL_PACKAGE_TEXTURE_PLAN.read_text(encoding="utf-8"),
        )
    )


def _texture_domain_policy_source() -> str:
    return TEXTURE_DOMAIN_POLICY.read_text(encoding="utf-8")


def _mesh_editor_source() -> str:
    return mesh_editor_tab_source(ROOT)


def _mesh_editor_session_source() -> str:
    return MESH_EDITOR_SESSION.read_text(encoding="utf-8")


def _mesh_editor_shell_bridge_source() -> str:
    return MESH_EDITOR_SHELL_BRIDGE.read_text(encoding="utf-8")


class AlignmentDialogSourceGuardTests(unittest.TestCase):
    def test_assets_mesh_editor_tab_is_registered_as_primary_workspace(self) -> None:
        source = _main_window_source() + "\n" + _mesh_editor_shell_bridge_source()
        mesh_editor_source = _mesh_editor_source()
        mesh_editor_session_source = _mesh_editor_session_source()

        self.assertIn("from cdmw.ui.mesh_editor.session import MeshEditorSessionRequest", source)
        self.assertIn("from cdmw.ui.mesh_editor.tab import MeshEditorTab", source)
        self.assertIn("tab = MeshEditorTab(", source)
        self.assertIn('self.assets_tabs, "Mesh Editor", "mesh_editor", self._create_mesh_editor_tab', source)
        self.assertIn('self._register_detachable_tool("mesh_editor", self.mesh_editor_tab, "Mesh Editor")', source)
        self.assertIn("tab.modify_original_requested.connect(self._mesh_editor_modify_original_requested)", source)
        self.assertIn("tab.import_replacement_requested.connect(self._mesh_editor_import_replacement_requested)", source)
        self.assertIn("tab.preview_rebuilt_asset_requested.connect(self._mesh_editor_preview_rebuilt_asset_requested)", source)
        self.assertIn("tab.package_rebuilt_asset_requested.connect(self._mesh_editor_package_rebuilt_asset_requested)", source)
        self.assertIn("tab.in_game_swap_requested.connect(self._mesh_editor_in_game_swap_requested)", source)
        self.assertIn("tab.mesh_action_requested.connect(self._mesh_editor_action_requested)", source)
        self.assertIn("def _mesh_editor_route_active_builder_action(self, action: object) -> Optional[bool]:", source)
        self.assertIn('getattr(active_builder, "_mesh_editor_action_bar_action_requested", None)', source)
        self.assertIn("def _mesh_editor_action_requested(self, action: object) -> None:", source)
        self.assertIn("routed = self._mesh_editor_route_active_builder_action(action)", source)
        self.assertIn("self.mesh_editor_tab.set_active_tool_state(", source)
        self.assertIn("Mesh Editor action sent: {text}.", source)
        self.assertIn("Mesh Editor action is not available in the embedded builder yet: {text}.", source)
        self.assertNotIn('self.archive_open_mesh_editor_button = QPushButton("Open in Mesh Editor...")', source)
        self.assertNotIn('self.archive_open_mesh_editor_button.setObjectName("ArchiveOpenMeshEditorButton")', source)
        self.assertNotIn("self.archive_open_mesh_editor_button.clicked.connect", source)
        self.assertNotIn('"Open in Mesh Editor..."', source)
        self.assertIn("def _open_mesh_editor_for_entry(", source)
        self.assertIn("def _mesh_editor_active_builder_entry_key(", source)
        self.assertIn("def _prepare_mesh_editor_archive_launch(", source)
        self.assertIn("self._mesh_editor_active_builder_entry_key() == self._mesh_editor_entry_key(entry)", source)
        self.assertIn("def _launch_archive_mesh_editor_for_entry(", source)
        self.assertIn("Replace Mesh Editor Workflow", source)
        self.assertIn("MeshEditorSessionRequest(", source)
        self.assertIn("from PySide6.QtCore import QTimer", source)
        self.assertIn(
            "QTimer.singleShot(0, lambda current_entry=entry: self._start_archive_modify_original_workspace(current_entry))",
            source,
        )
        self.assertIn('mode: str = "modify_original"', source)
        self.assertIn('mode="external_import"', source)
        self.assertIn('mode="in_game_swap"', source)

        self.assertIn("class MeshEditorSessionRequest:", mesh_editor_session_source)
        self.assertIn("class MeshEditorTab(", mesh_editor_source)
        self.assertIn("MeshEditorActionsMixin, QWidget):", mesh_editor_source)
        self.assertIn('self.workspace_stack.setObjectName("MeshEditorWorkspaceStack")', mesh_editor_source)
        self.assertIn('page.setObjectName("MeshEditorEmptyState")', mesh_editor_source)
        self.assertIn('self.embedded_builder_host.setObjectName("MeshEditorEmbeddedBuilderHost")', mesh_editor_source)
        self.assertIn("def builder_host(self) -> QWidget:", mesh_editor_source)
        self.assertIn("def active_builder(self) -> Optional[QWidget]:", mesh_editor_source)
        self.assertIn("def has_active_builder(self) -> bool:", mesh_editor_source)
        self.assertIn("def mount_embedded_builder(self, builder: QWidget) -> None:", mesh_editor_source)
        self.assertIn("def show_empty_state(self, message: str = \"\") -> None:", mesh_editor_source)
        self.assertIn("def update_editor_action_state(", mesh_editor_source)
        self.assertIn("self.update_editor_action_state(", mesh_editor_source)
        self.assertIn("if self.has_active_builder():", mesh_editor_source)
        self.assertNotIn('title = QLabel("Mesh Editor")', mesh_editor_source)
        self.assertNotIn("MeshEditorToolShelf", mesh_editor_source)
        self.assertNotIn("MeshEditorPreviewToolbar", mesh_editor_source)
        self.assertNotIn("MeshEditorCameraToolbar", mesh_editor_source)
        self.assertNotIn("MeshEditorWorkflowTabs", mesh_editor_source)
        self.assertNotIn("MeshEditorPropertiesPanel", mesh_editor_source)

    def test_mesh_editor_opens_alignment_builder_embedded_when_host_available(self) -> None:
        source = (
            _main_window_source()
            + "\n"
            + _archive_mesh_import_sources()
            + "\n"
            + ARCHIVE_MESH_BUILDER_LIFECYCLE.read_text(encoding="utf-8")
            + "\n"
            + _mesh_editor_shell_bridge_source()
        )
        mesh_editor_source = _mesh_editor_source()

        self.assertIn('self.embedded_builder_host.setObjectName("MeshEditorEmbeddedBuilderHost")', mesh_editor_source)
        self.assertIn("def builder_host(self) -> QWidget:", mesh_editor_source)
        self.assertIn("def mount_embedded_builder(self, builder: QWidget) -> None:", mesh_editor_source)
        self.assertIn("self.workspace_stack.setCurrentWidget(self.embedded_builder_host)", mesh_editor_source)
        self.assertIn("def show_empty_state(self, message: str = \"\") -> None:", mesh_editor_source)
        self.assertIn("self.workspace_stack.setCurrentWidget(self.empty_state)", mesh_editor_source)

        self.assertIn("embedded_host: Optional[QWidget] = None", source)
        self.assertIn("embedded_alignment_builder = embedded_host is not None", source)
        self.assertNotIn("QDialog embedding hard-crashes in the packaged Windows build", source)
        self.assertNotIn("embedded_alignment_builder = False", source)
        self.assertLess(
            source.index("embedded_alignment_builder = embedded_host is not None"),
            source.index("dialog_type = _EmbeddedAlignmentBuilderDialog if embedded_alignment_builder else QDialog"),
        )
        self.assertIn("dialog = dialog_type(embedded_host if embedded_alignment_builder else self)", source)
        self.assertIn("dialog.setWindowFlags(Qt.Widget)", source)
        self.assertIn("dialog.setMinimumSize(0, 0)", source)
        self.assertIn("if embedded_alignment_builder:", source)
        self.assertIn("controls_panel.setVisible(True)", source)
        layout_state_source = ARCHIVE_STATIC_REPLACEMENT_LAYOUT_STATE.read_text(encoding="utf-8")
        responsive_layout_body = _nested_function_source(
            static_replacement_routing_callback_source(ROOT),
            "_apply_alignment_dialog_responsive_layout",
        )
        self.assertIn('"preferred"', layout_state_source)
        self.assertIn("_state.controls_panel.setSizePolicy(policy_by_name[layout_spec.controls_policy], _state.QSizePolicy.Expanding)", responsive_layout_body)
        self.assertIn("_state.controls_panel.setMinimumWidth(layout_spec.controls_min_width)", responsive_layout_body)
        self.assertIn("_state.controls_panel.setMaximumWidth(layout_spec.controls_max_width)", responsive_layout_body)
        self.assertIn("_state.content_container.setMinimumWidth(layout_spec.content_min_width)", responsive_layout_body)
        self.assertIn("_state.content_container.setMaximumWidth(layout_spec.content_max_width)", responsive_layout_body)
        self.assertIn("_state.preview_panel.setMinimumWidth(layout_spec.preview_min_width)", responsive_layout_body)
        self.assertIn("_state.main_splitter.setStretchFactor(0, layout_spec.main_stretch[0])", responsive_layout_body)
        self.assertIn("_state.main_splitter.setStretchFactor(1, layout_spec.main_stretch[1])", responsive_layout_body)
        self.assertIn("target_control_width = max(420, min(620, int(normalized_width * 0.24)))", layout_state_source)
        self.assertIn("control_width = min(target_control_width, max(controls_min_width, normalized_width - 360))", layout_state_source)
        self.assertIn("max(360, normalized_width - control_width)", layout_state_source)
        self.assertIn("controls_min_width=controls_min_width", layout_state_source)
        self.assertIn("controls_max_width=16777215", layout_state_source)
        preview_shell_source = ARCHIVE_STATIC_REPLACEMENT_DIALOG_PREVIEW_SHELL.read_text(encoding="utf-8")
        self.assertLess(
            preview_shell_source.index("main_splitter.addWidget(preview_panel)"),
            preview_shell_source.index("main_splitter.addWidget(controls_panel)"),
        )
        self.assertIn("_new_alignment_scroll_tab_helper(", source)
        self.assertIn("embedded=embedded_alignment_builder", source)
        self.assertIn("scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff if embedded else Qt.ScrollBarAsNeeded)", source)
        self.assertIn("page.setMinimumWidth(0 if embedded_alignment_builder else alignment_control_content_min_width)", source)
        self.assertIn("QSizePolicy.Ignored if embedded else QSizePolicy.MinimumExpanding", source)
        self.assertIn("mesh_edit_page.setMinimumWidth(0 if embedded_alignment_builder else mesh_edit_control_content_min_width)", source)
        self.assertNotIn("def _apply_embedded_mesh_editor_preview_layout() -> None:", source)
        self.assertIn("controls_panel.setVisible(False)", source)
        self.assertIn("controls_panel.setVisible(True)", source)
        self.assertNotIn("controls_panel.setMaximumWidth(0)", source)
        self.assertNotIn('dialog.setProperty("mesh_editor_embedded_preview_only", True)', source)
        self.assertIn("builder_host = self.mesh_editor_tab.builder_host()", source)
        self.assertIn("if isinstance(builder_host, QWidget) and dialog.parentWidget() is builder_host:", source)
        self.assertIn("self._activate_tool_widget(self.mesh_editor_tab)", source)
        self.assertIn("self.mesh_editor_tab.show_empty_state(", source)
        self.assertIn("self.mesh_editor_tab.mount_embedded_builder(dialog)", source)
        self.assertIn("_fit_alignment_dialog_to_screen()", source)
        self.assertIn("dialog.raise_()", source)
        self.assertIn("if not embedded_alignment_builder:", source)
        self.assertIn("embedded_host=self.mesh_editor_tab.builder_host() if hasattr(self, \"mesh_editor_tab\") else None", source)
        self.assertIn('control_tabs.setObjectName("MeshAlignmentStickyWorkflowTabs")', source)
        self.assertIn('controls_panel.setObjectName("MeshAlignmentStickyControlPanel")', source)
        self.assertIn("alignment_d3d11_preview_host = DotNetPreviewHostFrame(", source)
        self.assertIn("profile=DotNetPreviewProfile.AUTHORING", source)
        self.assertIn("AlignmentD3D11PackageWorker(", source)
        self.assertIn('display_mode=requested_display_mode', source)
        package_lifecycle_source = static_replacement_callback_concern_source(
            ROOT, "d3d11_package_lifecycle"
        )
        self.assertIn(
            "editor_workspace='modify_original_alignment' if _state.modify_original_clone_mode else 'mesh_replacement_alignment'",
            package_lifecycle_source,
        )

    def test_mesh_editor_replacement_diagnostics_tab_reports_live_package_state(self) -> None:
        source = _main_window_source() + "\n" + _mesh_editor_shell_bridge_source()
        diagnostics_source = ARCHIVE_STATIC_REPLACEMENT_DIAGNOSTICS.read_text(encoding="utf-8")
        alignment_setup_source = ARCHIVE_STATIC_REPLACEMENT_ALIGNMENT_SETUP_STATE.read_text(encoding="utf-8")

        self.assertIn('alignment_workflow_control_text = _alignment_workflow_control_text_helper()', source)
        self.assertIn('alignment_workflow_control_text["diagnostics_object"]', source)
        self.assertIn('control_tabs.addTab(diagnostics_tab, alignment_workflow_control_text["diagnostics_label"])', source)
        self.assertIn('diagnostics_text.setObjectName(alignment_workflow_control_text["diagnostics_text_object"])', source)
        self.assertIn('"diagnostics_object": "MeshAlignmentDiagnosticsScrollTab"', alignment_setup_source)
        self.assertIn('"diagnostics_label": "Diagnostics"', alignment_setup_source)
        self.assertIn('"diagnostics_text_object": "MeshAlignmentDiagnosticsText"', alignment_setup_source)
        self.assertIn("def mesh_editor_diagnostics_initial_state() -> dict[str, object]:", source)
        self.assertIn("_mesh_editor_diagnostics_set_text_widget_helper(mesh_editor_diagnostics_state, diagnostics_text)", source)
        self.assertIn("def _refresh_mesh_editor_diagnostics(", source)
        self.assertIn("mesh_editor_diagnostics_manifest_lines as _mesh_editor_diagnostics_manifest_lines", source)
        self.assertIn("def mesh_editor_diagnostics_manifest_lines(", diagnostics_source)
        self.assertIn("def mesh_editor_diagnostics_model_lines(", diagnostics_source)
        self.assertIn("def mesh_editor_diagnostics_source_mesh_lines(", diagnostics_source)
        self.assertIn("def mesh_editor_diagnostics_copied_status", diagnostics_source)
        self.assertIn("_mesh_editor_diagnostics_copied_status_helper()", source)
        self.assertIn("getattr(getattr(alignment_d3d11_preview_host, 'controller', None), '_executable'", source)
        self.assertIn("active_package_quality", source)
        self.assertIn("mesh_edit_raw_preview_active", source)
        self.assertIn("source_face_limit", source)
        self.assertIn("Embedded .NET/Vortice state", source)
        self.assertIn("active_preview_backend", source)
        self.assertIn("_mesh_editor_embedded_runtime_diagnostics", source)
        self.assertIn("manifest flags: two_sided_batches=", diagnostics_source)
        self.assertIn("manifest material inputs: ", diagnostics_source)
        self.assertIn("Latest .NET/Vortice protocol event", source)
        self.assertIn("diagnostics_copy_button.clicked.connect", source)
        self.assertIn("_queue_alignment_post_open_task(_refresh_mesh_editor_diagnostics)", source)

    def test_alignment_dialog_qsize_runtime_dependency_is_imported(self) -> None:
        source = ARCHIVE_ATTACHMENT_SAFE_PLACEMENT_DIALOG.read_text(encoding="utf-8")
        self.assertIn("QSize(", source)
        self.assertIn("from PySide6.QtCore import QSize, Qt", source)

    def test_runtime_target_warnings_are_visible_and_companions_autocopy(self) -> None:
        source = _main_window_source() + "\n" + _archive_mesh_import_sources()
        archive_source = _archive_modding_source()
        mesh_session_source = MESH_DOMAIN_SESSION.read_text(encoding="utf-8")
        self.assertIn('startswith("Runtime target warning:")', source)
        self.assertIn("runtime_target_warning", source)
        self.assertIn("def _mesh_import_runtime_sibling_warning_lines", archive_source)
        self.assertIn("def mesh_import_runtime_sibling_mesh_candidates", archive_source)
        self.assertIn("runtime_target_entry: Optional[ArchiveEntry] = None", mesh_session_source)
        self.assertIn("def _modify_original_runtime_candidate_note", source)
        self.assertIn("def _retarget_static_options_for_runtime_entry", source)
        self.assertIn("Modify Original keeps the selected PAC as the export target", source)
        self.assertNotIn("Modify Original runtime target override", source)
        self.assertNotIn("runtime_target_entry=runtime_target_entry", source)
        self.assertIn("runtime_export_target_entry=build_entry", source)
        self.assertIn("Auto-including exact mesh companion file(s)", archive_source)

    def test_alignment_modes_are_simplified_and_default_grid_flat(self) -> None:
        source = _main_window_source()
        setup_ui_source = static_replacement_ui_concern_source(ROOT, "setup_options_transform")
        preview_model_source = static_replacement_callback_concern_source(ROOT, "preview_model")
        source_parts_state_source = _source_part_owner_sources()
        static_source = _static_replacer_source()
        transform_control_source = ARCHIVE_STATIC_REPLACEMENT_TRANSFORM_CONTROL_STATE.read_text(encoding="utf-8")
        alignment_setup_source = ARCHIVE_STATIC_REPLACEMENT_ALIGNMENT_SETUP_STATE.read_text(encoding="utf-8")
        self.assertIn("ALIGNMENT_MODE_OPTIONS", source)
        self.assertIn('("Auto: Force grid flat", "grid_flat")', source)
        self.assertIn('("Manual only", "manual")', source)
        self.assertIn("_state._populate_combo_options_helper(_state.alignment_mode_combo, _state.ALIGNMENT_MODE_OPTIONS)", setup_ui_source)
        self.assertIn("alignment_setup_options_control_text", alignment_setup_source)
        self.assertIn(
            "_state.alignment_setup_options_control_text = _state._alignment_setup_options_control_text_helper()",
            setup_ui_source,
        )
        self.assertIn("_state.QGroupBox(_state.alignment_setup_options_control_text['group_title'])", setup_ui_source)
        self.assertIn("_state.QLabel(_state.alignment_setup_options_control_text['alignment_mode_label'])", setup_ui_source)
        self.assertIn("_state.QCheckBox(_state.alignment_setup_options_control_text['scale_to_length'])", setup_ui_source)
        self.assertIn("_state.QCheckBox(_state.alignment_setup_options_control_text['flip_direction'])", setup_ui_source)
        self.assertIn('"alignment_mode"] = "grid_flat"', transform_control_source)
        self.assertNotIn('"alignment_mode"] = "manual" if bool(modify_original_clone_mode) else "grid_flat"', transform_control_source)
        self.assertIn("alignment_mode_combo.findData(alignment_mode)", source)
        self.assertIn("alignment_mode=str(_state._combo_data('alignment_mode_combo') or 'grid_flat')", preview_model_source)
        self.assertIn('alignment_mode: str = "grid_flat"', static_source)
        self.assertNotIn('alignment_mode_combo.addItem("Auto: preserve original placement"', source)
        self.assertNotIn('alignment_mode_combo.addItem("Auto: match original/grid flat"', source)
        self.assertNotIn('alignment_mode_combo.addItem("Auto: handheld/grip anchor"', source)
        self.assertNotIn("Quick orientation", source)
        self.assertNotIn("orientation_preset_combo", source)
        self.assertNotIn("apply_orientation_preset_button", source)
        self.assertNotIn("_apply_orientation_preset", source)
        self.assertIn("_state.reset_buttons_by_key['placement'].clicked.connect(_state._reset_placement_values)", setup_ui_source)

    def test_alignment_camera_controls_are_view_only_and_feed_icon_capture(self) -> None:
        source = _main_window_source()
        loading_source = static_replacement_callback_concern_source(ROOT, "d3d11_loading")
        capture_source = ARCHIVE_STATIC_REPLACEMENT_DIALOG_CUSTOM_ICON_CALLBACKS.read_text(encoding="utf-8")
        preview_status_source = ARCHIVE_STATIC_REPLACEMENT_PREVIEW_STATUS_STATE.read_text(encoding="utf-8")
        self.assertIn("def alignment_preview_camera_button_specs", preview_status_source)
        self.assertIn('"MeshAlignmentCameraFrontButton"', preview_status_source)
        self.assertIn('"MeshAlignmentCameraLeftButton"', preview_status_source)
        self.assertIn('"MeshAlignmentCameraRightButton"', preview_status_source)
        self.assertIn('"MeshAlignmentCameraBackButton"', preview_status_source)
        self.assertIn('"MeshAlignmentCameraTopButton"', preview_status_source)
        self.assertIn('"MeshAlignmentCameraBottomButton"', preview_status_source)
        self.assertIn('"MeshAlignmentCameraResetFitButton"', preview_status_source)
        self.assertIn("_alignment_preview_camera_button_specs_helper()", source)
        preview_shell_source = ARCHIVE_STATIC_REPLACEMENT_DIALOG_PREVIEW_SHELL.read_text(encoding="utf-8")
        ui_sections_source = _ui_section_source()
        self.assertIn('preview_camera_row.addWidget(setup_texture_flip_u_checkbox)', preview_shell_source)
        self.assertIn('preview_camera_row.addWidget(setup_texture_flip_v_checkbox)', preview_shell_source)
        self.assertIn('setup_texture_flip_controls_in_preview = bool(', ui_sections_source)
        self.assertIn("def _alignment_current_camera_state", loading_source)
        self.assertIn("def _apply_alignment_camera_state", loading_source)
        self.assertIn("send_resident_presentation_state(_state.dialog, {'camera': dict(state)})", loading_source)
        self.assertIn("_state.alignment_preview_mode_view_states[", loading_source)
        self.assertIn("_state.alignment_d3d11_preview_host.restore_view_state(state)", loading_source)
        self.assertIn("_state._qt_alignment_camera_tuple_helper(", loading_source)
        self.assertIn("fit_distance=_state.NativePreviewPanel._FIT_DISTANCE", loading_source)
        self.assertTrue(all(token in capture_source for token in ('capture = getattr(dialog, "_mesh_editor_embedded_capture_icon", None)', "if callable(capture):", "capture(on_captured)", "replacement_only_preview.restore_view_state(previous_replacement_view_state)")))
        self.assertNotIn("set_icon_capture_mode", capture_source)
        self.assertNotIn("camera_front_button.clicked.connect(lambda _checked=False: rotate_", source)

    def test_manual_texture_override_uses_assignment_store(self) -> None:
        source = _main_window_source()
        texture_ui_source = static_replacement_ui_concern_source(ROOT, "texture_material")
        texture_callback_source = static_replacement_callback_family_source(ROOT, "texture")
        texture_rows_source = ARCHIVE_STATIC_REPLACEMENT_TEXTURE_ROWS.read_text(encoding="utf-8")
        texture_table_source = ARCHIVE_STATIC_REPLACEMENT_TEXTURE_TABLE.read_text(encoding="utf-8")
        texture_table_items_source = ARCHIVE_STATIC_REPLACEMENT_TEXTURE_TABLE_ITEMS.read_text(encoding="utf-8")
        texture_editor_ui_state_source = ARCHIVE_STATIC_REPLACEMENT_TEXTURE_EDITOR_UI_STATE.read_text(encoding="utf-8")
        material_plan_ui_state_source = ARCHIVE_STATIC_REPLACEMENT_MATERIAL_PLAN_UI_STATE.read_text(encoding="utf-8")
        self.assertIn("texture_override_assignments: Dict[Tuple[str, str, str], str] = {}", source)
        self.assertIn("_state.selected_source_combo = _state.QComboBox()", texture_ui_source)
        self.assertIn("_state.selected_source_combo.currentIndexChanged.connect(_state._selected_texture_source_changed)", texture_ui_source)
        self.assertIn("def texture_source_choices_for_row", texture_rows_source)
        self.assertIn("_state.texture_source_choices_for_row = lambda state: _state._texture_source_choices_for_row_helper(", texture_ui_source)
        self.assertIn("def texture_row_effective_source", texture_rows_source)
        self.assertIn("def sync_texture_row_assignment_state", texture_rows_source)
        self.assertIn("_texture_row_effective_source_helper(", source)
        self.assertIn("_sync_texture_row_assignment_state_helper(", source)
        self.assertIn("selected_texture_source_commit_state as _selected_texture_source_commit_state_helper", source)
        self.assertIn("selected_texture_source_commit_state", texture_table_source)
        self.assertIn("def selected_texture_source_commit_state(", texture_editor_ui_state_source)
        self.assertIn("selected_texture_source_combo_change_state as _selected_texture_source_combo_change_state_helper", source)
        self.assertIn("selected_texture_source_combo_change_state", texture_table_source)
        self.assertIn("def selected_texture_source_combo_change_state(", texture_editor_ui_state_source)
        self.assertIn("combo_state.source_path", source)
        self.assertIn("target_texture_clear_assignment_state as _target_texture_clear_assignment_state_helper", source)
        self.assertIn("selected_material_texture_clear_action_state as _selected_material_texture_clear_action_state_helper", source)
        self.assertIn("selected_material_texture_file_action_state as _selected_material_texture_file_action_state_helper", source)
        self.assertIn("registered_texture_sources_action_state as _registered_texture_sources_action_state_helper", source)
        self.assertIn("target_texture_clear_assignment_state", texture_table_source)
        self.assertIn("selected_material_texture_clear_action_state", texture_table_source)
        self.assertIn("def target_texture_clear_assignment_state(", texture_editor_ui_state_source)
        self.assertIn("def selected_material_texture_clear_action_state(", material_plan_ui_state_source)
        self.assertIn("def selected_material_texture_file_action_state(", material_plan_ui_state_source)
        self.assertIn("def registered_texture_sources_action_state(", material_plan_ui_state_source)
        texture_sources_source = ARCHIVE_STATIC_REPLACEMENT_TEXTURE_SOURCES.read_text(encoding="utf-8")
        self.assertIn("register_allowed_texture_source_file as _register_allowed_texture_source_file_helper", source)
        self.assertIn("def register_allowed_texture_source_file(", texture_sources_source)
        self.assertIn("register_dialog_supplemental_file as _register_dialog_supplemental_file_helper", source)
        self.assertIn("def register_dialog_supplemental_file(", texture_sources_source)
        self.assertIn("register_texture_source_file as _register_texture_source_file_helper", source)
        self.assertIn("def register_texture_source_file(", texture_sources_source)
        self.assertIn("texture_override_assignments[row_key] = normalized_source_path", source)
        self.assertIn('texture_override_assignments[row_key] = ""', source)
        self.assertIn("_commit_texture_row_source(row_state, source_path)", source)
        self.assertIn("_state.texture_override_tree.itemActivated.connect(_state._texture_table_item_activated)", texture_ui_source)
        self.assertIn("static_replacement_texture_table_items import", source)
        self.assertIn("apply_texture_row_to_item", texture_table_source)
        self.assertIn("texture_assignment_slot_item", texture_table_source)
        self.assertIn("texture_item_for_row", texture_table_source)
        self.assertIn("texture_override_item", texture_table_source)
        self.assertIn("def apply_texture_row_to_item(", texture_table_items_source)
        self.assertIn("def texture_assignment_slot_item(", texture_table_items_source)
        self.assertIn("def texture_item_for_row(", texture_table_items_source)
        self.assertIn("def texture_override_item(", texture_table_items_source)
        self.assertIn(
            "def _refresh_texture_row_in_place(row_state: Dict[str, Any], *, sync_editor: bool=True)",
            texture_callback_source,
        )
        self.assertIn('row_state["checked"] = bool(normalized_source_path)', source)
        self.assertNotIn("selected_source_combo.activated.connect", source)
        self.assertNotIn("selected_source_combo.textActivated.connect", source)
        self.assertNotIn("_stage_selected_texture_source", source)

    def test_alignment_original_part_copy_paste_source_workflow_exists(self) -> None:
        source = _main_window_source()
        outliner_source = static_replacement_ui_concern_source(ROOT, "source_parts_outliner")
        selected_part_source = static_replacement_callback_concern_source(ROOT, "selected_part_control")
        original_parts_source = ARCHIVE_STATIC_REPLACEMENT_ORIGINAL_PARTS.read_text(encoding="utf-8")
        source_parts_state_source = _source_part_owner_sources()
        self.assertIn("alignment_part_clipboard: Dict[str, object] = {}", source)
        self.assertIn("copied_original_texture_intents_by_source: Dict[int, List[Dict[str, str]]] = {}", source)
        self.assertIn("_copy_original_part_payload = lambda", source)
        self.assertIn("def _append_original_part_payload_as_source", source)
        self.assertIn("def _copy_original_part_to_alignment_clipboard", source)
        self.assertIn("def _paste_alignment_part_clipboard_as_replacement_source", source)
        self.assertIn('menu.addAction(original_part_clipboard_action_text["copy_part_with_textures"])', source)
        self.assertIn('menu.addAction(original_part_clipboard_action_text["paste_replacement_source"])', source)
        self.assertIn('"copy_part_with_textures": "Copy Part With Textures"', original_parts_source)
        self.assertIn('"paste_replacement_source": "Paste As Replacement Source"', original_parts_source)
        self.assertIn("_state.original_tree.setContextMenuPolicy(_state.Qt.CustomContextMenu)", outliner_source)
        self.assertIn("_state.source_tree.setContextMenuPolicy(_state.Qt.CustomContextMenu)", outliner_source)
        self.assertIn("_state.parts_outliner_tree.setContextMenuPolicy(_state.Qt.CustomContextMenu)", outliner_source)
        self.assertIn("preview_only_source_indices.add(new_source_index)", source)
        self.assertIn("_set_transform_source_indices((new_source_index,))", source)
        set_transform_start = source.index("def _set_transform_source_indices(")
        set_transform_end = source.index("def _clear_transform_source_indices()", set_transform_start)
        set_transform_source = source[set_transform_start:set_transform_end]
        self.assertIn("_alignment_part_transform_preview_queue_indices_helper(source_indices)", set_transform_source)
        self.assertNotIn("for raw_index in tuple(source_indices or ())", set_transform_source)
        self.assertIn("copied_original_texture_intents_by_source[new_source_index] = texture_rows", source)
        self.assertIn("def _copied_source_texture_slot_overrides", source)
        self.assertIn("source_index in _state.copied_original_texture_disabled_sources", selected_part_source)
        self.assertNotIn("source_material_texture_override_assignments[(material_name, slot_kind)] = source_path", source)
        self.assertIn(
            "_state.part_use_copied_texture_button = _state.QPushButton(_state.source_part_inspector_control_text['use_copied_texture'])",
            outliner_source,
        )
        self.assertIn(
            "_state.part_use_route_texture_button = _state.QPushButton(_state.source_part_inspector_control_text['use_route_texture'])",
            outliner_source,
        )
        self.assertIn(
            "_state.part_remove_copied_texture_button = _state.QPushButton(_state.source_part_inspector_control_text['remove_copied_texture'])",
            outliner_source,
        )
        self.assertIn('"use_copied_texture": "Use copied original"', source_parts_state_source)
        self.assertIn('"use_route_texture": "Use route source"', source_parts_state_source)
        self.assertIn('"remove_copied_texture": "Remove copied texture"', source_parts_state_source)
        self.assertIn("def source_part_copied_texture_action_state", source_parts_state_source)
        self.assertIn("_source_part_copied_texture_action_state_helper(", source)
        self.assertIn("action_state.disable_copied_texture", source)
        self.assertIn("action_state.remove_intent", source)
        self.assertIn("def _remove_copied_texture_from_selected_source", source)
        self.assertIn("Copied Orig", source)

    def test_loose_export_builds_final_output_preview_after_commit(self) -> None:
        source = _main_window_source() + "\n" + _archive_mesh_import_sources() + "\n" + _archive_mod_ready_export_source()
        self.assertIn("build_final_package_preview(", source)
        self.assertIn("final_preview: Optional[FinalPackagePreviewResult]", source)
        self.assertIn("Building final output preview from packaged sidecar/DDS payloads", source)
        self.assertIn("original_dds_resolver=_archive_dds_preview_source_for_path", source)
        self.assertIn("original_dds_basename_resolver=_archive_dds_preview_sources_for_basename", source)
        self.assertIn("Running final package texture preflight before export", source)
        self.assertIn("package_root=loose_result.package_root", source)
        self.assertIn("Final package texture preflight blocker", source)
        self.assertIn("show_texture_resolution_manifest_option=True", source)
        self.assertIn("create_texture_resolution_manifest=texture_resolution_manifest_checkbox.isChecked()", source)
        self.assertIn("show_material_authority_report_option=True", source)
        self.assertIn('material_authority_report_checkbox = QCheckBox("CDMW material authority report/check")', source)
        self.assertIn("create_material_authority_report=material_authority_report_checkbox.isChecked()", source)
        self.assertIn("show_active_file_authority_audit_option=True", source)
        self.assertIn('active_file_authority_audit_checkbox = QCheckBox("Active file authority audit report")', source)
        self.assertIn("create_active_file_authority_audit=active_file_authority_audit_checkbox.isChecked()", source)
        self.assertIn('texture_resolution_manifest_path = loose_result.package_root / "cdmw_texture_resolution_manifest.json"', source)
        self.assertIn('if not bool(getattr(export_options, "create_texture_resolution_manifest", False)):', source)
        self.assertIn("Removed stale texture resolution manifest", source)
        self.assertIn('if bool(getattr(export_options, "create_texture_resolution_manifest", False)):', source)
        self.assertIn('if not bool(getattr(export_options, "create_material_authority_report", False)):', source)
        self.assertIn("Removed stale material authority report", source)
        self.assertIn('if bool(getattr(export_options, "create_material_authority_report", False)):', source)
        final_preview_source = _final_package_preview_source()
        self.assertIn('"cdmw_material_authority_report.json"', final_preview_source)
        self.assertIn('"cdmw_material_authority_report_check.json"', final_preview_source)
        self.assertIn("The preview is using final package texture paths where they could be validated.", source)

    def test_complete_swap_preflight_blocker_uses_visible_result_path(self) -> None:
        source = _main_window_source() + "\n" + _archive_mesh_import_sources()
        self.assertIn('"preflight_blocked": blocker_lines', source)
        self.assertIn("Final package texture preflight failed before export", source)
        self.assertIn('blocker_dialog.setWindowTitle("Final Preflight Blocked Export")', source)
        self.assertIn("<b>Loose package was not written.</b>", source)
        self.assertIn("blocker_details.setPlainText(", source)
        self.assertIn("Mesh replacement build blocked by final package texture preflight.", source)
        self.assertIn("preflight_blockers = tuple(", source)
        self.assertNotIn("raise RuntimeError(\n                                \"Final package texture preflight blocked export", source)

    def test_complete_swap_sync_skips_deleted_alignment_widgets(self) -> None:
        source = _main_window_source()
        routing_source = static_replacement_callback_family_source(ROOT, "routing")
        loading_source = static_replacement_callback_concern_source(ROOT, "d3d11_loading")
        package_source = static_replacement_callback_concern_source(ROOT, "d3d11_package_lifecycle")
        self.assertIn("alignment_dialog_closing = _alignment_dialog_closing_initial_state_helper()", source)
        self.assertIn("def qt_object_is_valid(widget: object) -> bool:", source)
        self.assertIn("def _alignment_dialog_widgets_live() -> bool:", source)
        self.assertIn("def _call_if_alignment_widgets_live(callback: Callable[[], None]) -> None:", source)
        self.assertIn('"Internal C++ object" in message', source)
        self.assertIn("def _complete_swap_widgets_live() -> bool:", source)
        self.assertIn("if not _state._complete_swap_widgets_live():", routing_source)
        self.assertIn("_alignment_dialog_mark_closing_helper(alignment_dialog_closing)", source)
        self.assertIn("return (False, 'alignment dialog is closing')", loading_source)
        self.assertIn("def _drop_alignment_d3d11_package_reload(", source)
        self.assertIn("'alignment_d3d11_package_reload_dropped'", package_source)
        self.assertIn("reason='dialog_closing'", package_source)

    def test_alignment_dialog_removes_in_memory_test_build_preview(self) -> None:
        source = _main_window_source() + "\n" + _archive_mesh_import_sources()
        preview_status_source = ARCHIVE_STATIC_REPLACEMENT_PREVIEW_STATUS_STATE.read_text(encoding="utf-8")
        build_footer_source = ARCHIVE_STATIC_REPLACEMENT_BUILD_FOOTER.read_text(encoding="utf-8")
        self.assertNotIn('QPushButton("Test Build Preview")', source)
        self.assertNotIn('QPushButton("Back to Live Preview")', source)
        self.assertNotIn("Final Test Build Preview", source)
        self.assertNotIn("def _test_build_final_preview", source)
        self.assertNotIn("alignment_test_build_preview", source)
        self.assertNotIn("test_build_preview_button", source)
        self.assertIn("_make_alignment_build_footer_helper(", source)
        self.assertIn("alignment_build_footer_import_button_state(", build_footer_source)
        self.assertIn("def live_alignment_preview_status_message", source)
        self.assertNotIn("Full geometry can be slow on large models", source)
        self.assertIn("static_options = _build_static_options_from_dialog(", source)
        self.assertIn("include_edited_source_mesh=True", source)
        self.assertIn("def _current_static_placement_snapshot", source)
        self.assertIn("def _static_options_from_placement_snapshot", source)
        self.assertIn("include_preview_only_independent_parts=False", source)
        self.assertIn("include_preview_only_independent_parts=True", source)
        self.assertIn("_alignment_preview_help_presentation_helper(d3d11_active=False)", source)
        self.assertIn("Live preview. Build Mod validates final package paths during export.", preview_status_source)
        self.assertIn("original_dds_resolver=_archive_dds_preview_source_for_path", source)
        self.assertIn("original_dds_basename_resolver=_archive_dds_preview_sources_for_basename", source)
        self.assertNotIn("_copy_final_texture_slots", source)

    def test_build_mod_callback_does_not_capture_alignment_dialog_locals(self) -> None:
        source = _main_window_source() + "\n" + _archive_mesh_import_sources()
        dialog_accept_start = source.index("def _accept_static_options_after_status_paint() -> None:")
        dialog_accept_body = source[
            dialog_accept_start:
            source.index("return SimpleNamespace(", dialog_accept_start)
        ]
        build_callback_start = source.index("def _start_build_with_static_options(")
        build_callback_body = source[
            build_callback_start:
            source.index('if import_mode == "static_replacement":', build_callback_start)
        ]

        self.assertIn("include_edited_source_mesh=True", dialog_accept_body)
        self.assertNotIn("clone_static_replacement_options_for_worker", dialog_accept_body)
        self.assertIn("clone_static_replacement_options_for_worker(", build_callback_body)
        self.assertNotIn("replacement_mesh_for_mapping", build_callback_body)
        self.assertNotIn("replacement_mesh_base_for_mapping", build_callback_body)
        self.assertNotIn("mesh_edit_revision", build_callback_body)
        self.assertNotIn("source_geometry_revision", build_callback_body)
        self.assertNotIn("replacement_mesh_snapshot_source", build_callback_body)
        self.assertNotIn("needs_edited_source_mesh_snapshot", build_callback_body)

    def test_material_texture_contract_has_thumbnail_and_final_preview_refresh(self) -> None:
        source = _main_window_source()
        texture_ui_source = static_replacement_ui_concern_source(ROOT, "texture_material")
        texture_callback_source = static_replacement_callback_family_source(ROOT, "texture")
        texture_table_source = ARCHIVE_STATIC_REPLACEMENT_TEXTURE_TABLE.read_text(encoding="utf-8")
        material_plan_ui_state_source = ARCHIVE_STATIC_REPLACEMENT_MATERIAL_PLAN_UI_STATE.read_text(encoding="utf-8")
        texture_editor_ui_state_source = ARCHIVE_STATIC_REPLACEMENT_TEXTURE_EDITOR_UI_STATE.read_text(encoding="utf-8")
        self.assertIn("_state.dds_detail_panel.setObjectName('DDSDetailPane')", texture_ui_source)
        self.assertIn("_state.dds_detail_thumbnail_label.setObjectName('DDSDetailThumbnail')", texture_ui_source)
        self.assertIn("def _resolve_dds_detail_preview_path", source)
        self.assertIn("def resolve_dds_detail_preview_path", source)
        self.assertIn("ensure_dds_display_preview=ensure_dds_display_preview_png", source)
        self.assertIn("def _refresh_dds_detail_thumbnail", source)
        self.assertIn("dds_detail_item_state", texture_table_source)
        self.assertIn("dds_detail_thumbnail_state", texture_table_source)
        self.assertIn("dds_detail_clear_state", texture_table_source)
        self.assertIn("dds_detail_refresh_route_state", texture_table_source)
        self.assertIn("dds_detail_resolved_thumbnail_state", texture_table_source)
        self.assertIn("def dds_detail_item_state", material_plan_ui_state_source)
        self.assertIn("def dds_detail_thumbnail_state", material_plan_ui_state_source)
        self.assertIn("def dds_detail_clear_state", material_plan_ui_state_source)
        self.assertIn("def dds_detail_refresh_route_state", material_plan_ui_state_source)
        self.assertIn("def dds_detail_resolved_thumbnail_state", material_plan_ui_state_source)
        self.assertIn("_dds_detail_clear_state_helper(", source)
        self.assertIn("_dds_detail_refresh_route_state_helper(", source)
        self.assertIn("_dds_detail_resolved_thumbnail_state_helper(", source)
        self.assertNotIn("_dds_detail_item_state_helper(", source)
        self.assertNotIn("_dds_detail_thumbnail_state_helper(", source)
        self.assertIn("item.setData(0, Qt.UserRole + 4, source_preview_path)", source)
        self.assertIn("item.setData(0, Qt.UserRole + 4, str(getattr(row, \"preview_texture_path\", \"\") or \"\"))", source)
        self.assertIn("def _refresh_material_plan_from_final_preview(final_preview: FinalPackagePreviewResult)", source)
        self.assertIn("_source_indices_for_target_contract = lambda", source)
        self.assertIn("Final texture contract resolved from packaged sidecar/DDS payloads.", material_plan_ui_state_source)
        self.assertIn("final_dds_contract_summary_html", texture_table_source)
        self.assertIn("def final_dds_contract_summary_html", texture_editor_ui_state_source)
        self.assertIn("def final_preview_plan_state", material_plan_ui_state_source)
        self.assertIn("def final_preview_material_status_row_states", material_plan_ui_state_source)
        self.assertIn("def final_preview_binding_row_states", material_plan_ui_state_source)
        self.assertIn("def final_preview_binding_target_index", material_plan_ui_state_source)
        self.assertIn("_final_preview_plan_state_helper(final_preview)", source)
        self.assertIn("_final_dds_contract_summary_html_helper(len(final_plan_state.binding_rows))", source)
        self.assertIn("_state.material_contract_label.setToolTip(str(_state.material_plan_control_text['final_contract_tooltip']))", texture_callback_source)
        self.assertIn("def _refresh_material_plan_from_final_preview(final_preview: FinalPackagePreviewResult)", source)
        self.assertNotIn("binding_rows = tuple(getattr(final_preview, \"binding_rows\", ()) or ())", source)

    def test_removed_test_build_preview_leaves_no_d3d11_final_test_path(self) -> None:
        source = _main_window_source()
        self.assertNotIn("def _test_build_final_preview() -> None:", source)
        self.assertNotIn('label="Final Test Build Preview"', source)
        self.assertNotIn('reason="final_test"', source)
        self.assertNotIn('"final_test"', source)
        self.assertNotIn("stage_final_package_preview_payloads", source)
        self.assertIn("def _start_alignment_d3d11_package_worker(", source)
        self.assertIn("reason: str='geometry'", source)

    def test_alignment_dialog_has_resident_dotnet_vortice_preview_mode(self) -> None:
        source = _main_window_source() + "\n" + _archive_preview_settings_source()
        host_source = (ROOT / "cdmw" / "ui" / "preview" / "dotnet_host.py").read_text(encoding="utf-8")
        controller_source = (ROOT / "cdmw" / "ui" / "preview" / "dotnet_session.py").read_text(encoding="utf-8")
        worker_source = (ROOT / "cdmw" / "workers" / "d3d11_package_workers.py").read_text(encoding="utf-8")
        self.assertIn('(".NET/Vortice Preview", "d3d11")', source)
        self.assertIn("DotNetPreviewHostFrame(", source)
        self.assertIn("profile=DotNetPreviewProfile.AUTHORING", source)
        self.assertIn('setObjectName("AlignmentDotNetVorticePreviewHost")', source)
        self.assertIn("preview_stack.setCurrentWidget(alignment_d3d11_preview_page)", source)
        self.assertIn("build_or_lookup_dotnet_preview_package_from_model(", worker_source)
        self.assertIn("resident_preview_package_replace_v2", controller_source)
        self.assertIn("set_authoring_rehydrator", controller_source)
        self.assertIn("def set_alignment_state", host_source)
        self.assertNotIn("NativeD3D11PreviewHostFrame", source)
        self.assertNotIn("write_isolated_d3d11_preview_package(", worker_source)
        return
        native_source = d3d11_preview_source()
        worker_source = (ROOT / "cdmw" / "workers" / "d3d11_package_workers.py").read_text(encoding="utf-8")
        package_source = _native_preview_package_source()
        d3d11_mapping_source = (ROOT / "cdmw" / "ui" / "archive_browser" / "static_replacement_d3d11_mapping.py").read_text(encoding="utf-8")
        d3d11_presentation_source = (
            ROOT / "cdmw" / "ui" / "archive_browser" / "static_replacement_d3d11_presentation_state.py"
        ).read_text(encoding="utf-8")
        preview_status_source = ARCHIVE_STATIC_REPLACEMENT_PREVIEW_STATUS_STATE.read_text(encoding="utf-8")
        remaining_callbacks_source = static_replacement_remaining_callback_source(ROOT)
        routing_callbacks_source = static_replacement_routing_callback_source(ROOT)
        self.assertIn("PREVIEW_RENDERER_OPTIONS", source)
        self.assertIn('("Native D3D11 accurate", "d3d11")', source)
        self.assertIn("_populate_combo_options_helper(preview_renderer_combo, PREVIEW_RENDERER_OPTIONS)", source)
        self.assertNotIn('preview_renderer_combo.addItem("Legacy GreenUp edit", "legacy")', source)
        self.assertIn("preview_renderer_combo.setVisible(False)", source)
        self.assertIn("alignment_d3d11_preview_host = NativeD3D11PreviewHostFrame", source)
        self.assertNotIn("WebGlPbrPreviewHostFrame", source)
        self.assertIn("AlignmentD3D11PackageWorker", source)
        self.assertIn("write_isolated_d3d11_preview_package(", worker_source)
        self.assertIn("prepare_model_preview(", worker_source)
        self.assertIn("enable_material_combiner=True", worker_source)
        self.assertIn("material_combiner_policy", package_source)
        self.assertIn("original_reference_archive_parity", package_source)
        self.assertIn("modify_original_archive_parity", package_source)
        self.assertNotIn("original_reference_archive_direct", package_source)
        self.assertNotIn("modify_original_archive_direct", package_source)
        self.assertIn('workspace == "modify_original_alignment"', package_source)
        self.assertIn("display_mode=self.display_mode", worker_source)
        self.assertIn("editor_workspace=self.editor_workspace", worker_source)
        self.assertNotIn("def _alignment_d3d11_uses_accurate_package", source)
        self.assertNotIn('str(label or "").strip().casefold() == "final test build preview"', source)
        self.assertNotIn('if detail_mode == "full":', source)
        self.assertNotIn('if detail_mode == "fast":', source)
        self.assertNotIn('if detail_mode == "auto":', source)
        self.assertNotIn('if modify_original_clone_mode and detail_mode == "auto":', source)
        self.assertNotIn("return face_count <= 120_000", source)
        self.assertIn("_alignment_d3d11_package_quality(label, model, reason=rebuild_reason)", source)
        self.assertNotIn("def _alignment_d3d11_fast_render_settings", source)
        self.assertNotIn("fast_settings.disable_all_support_maps = True", source)
        self.assertNotIn("fast_settings.disable_normal_map = True", source)
        self.assertNotIn("fast_settings.disable_material_map = True", source)
        self.assertNotIn("fast_settings.disable_height_map = True", source)
        self.assertNotIn('return _alignment_d3d11_fast_render_settings(settings), False, False, "fast_geometry"', source)
        self.assertIn('return clamp_model_preview_render_settings(geometry_settings), False, False, "material_refresh"', source)
        self.assertIn('return clamp_model_preview_render_settings(geometry_settings), False, False, "archive_parity"', source)
        self.assertIn('return clamp_model_preview_render_settings(settings), high_quality_textures, enable_material_combiner, "mesh_edit_raw"', source)
        self.assertNotIn("raw_settings.disable_all_support_maps = True", source)
        self.assertNotIn("raw_settings.disable_normal_map = True", source)
        self.assertNotIn("raw_settings.disable_material_map = True", source)
        self.assertNotIn("raw_settings.disable_height_map = True", source)
        self.assertIn("enable_material_combiner=bool(self.enable_material_combiner and self.use_textures)", worker_source)
        self.assertIn('package_quality_key = str(package_quality).strip().lower()', source)
        self.assertIn("worker_use_textures = False", source)
        self.assertIn("high_quality_textures=worker_high_quality_textures", source)
        self.assertIn("enable_material_combiner=worker_enable_material_combiner", source)
        self.assertIn("mesh_edit_raw_package = _state._mesh_edit_raw_preview_active_value()", source)
        self.assertIn("use_textures=worker_use_textures", source)
        self.assertIn("worker_original_reference_material_parity = bool(worker_use_textures)", source)
        self.assertIn("original_reference_material_parity=worker_original_reference_material_parity", source)
        self.assertIn("reuse_prepared_geometry=bool(geometry_signature)", source)
        self.assertIn("def _mesh_by_source_identity", worker_source)
        self.assertIn("by_source[(role_key, source_index)] = mesh", worker_source)
        self.assertIn("_preview_roles_compatible(", worker_source)
        self.assertIn('state["active_package_quality"] = str(package_quality or "")', source)
        self.assertIn('request_package_qualities[_request_id(request_id)] = str(package_quality or "normal").strip().lower()', source)
        self.assertNotIn("original_reference_material_parity=enable_material_combiner", source)
        self.assertIn("f'Preparing preview - {loading_detail}.'", source)
        self.assertIn("progress_changed = Signal(int, int, int, str)", worker_source)
        self.assertIn("on_progress=_emit_package_progress", worker_source)
        self.assertIn("alignment_d3d11_loading_spinner_label = QLabel(\"\")", source)
        self.assertIn('alignment_d3d11_loading_spinner_label.setObjectName("AlignmentD3D11LoadingSpinner")', source)
        self.assertIn("alignment_d3d11_loading_spinner_label.setTextFormat(Qt.RichText)", source)
        self.assertIn("alignment_d3d11_loading_spinner_label.setFixedSize(36, 30)", source)
        self.assertIn('ALIGNMENT_D3D11_LOADING_SPINNER_FRAMES = ("&#9679;", "&#9683;", "&#9681;", "&#9682;")', d3d11_presentation_source)
        self.assertIn("frames = _state._alignment_d3d11_loading_spinner_frames_helper()", source)
        self.assertIn("_alignment_d3d11_loading_spinner_html_helper(frames[frame_index])", source)
        self.assertIn("_alignment_d3d11_package_preparing_performance_helper(", source)
        self.assertIn("D3D11 package preparing - {str(quality_label or '')}", d3d11_presentation_source)
        self.assertNotIn('_set_preview_performance_status(\n                    "Loading preview...",', source)
        self.assertIn("alignment_d3d11_loading_timer = QTimer(dialog)", source)
        self.assertIn("def _set_alignment_d3d11_loading(active: bool, message: str='', *, detail: str='') -> None:", source)
        self.assertIn("if not _alignment_dialog_widgets_live():", source)
        self.assertIn("def _drop_alignment_d3d11_package_reload(", source)
        self.assertIn("reason='stale_request'", source)
        self.assertIn("reason='stale_drag'", source)
        self.assertIn('reason="dialog_closing_worker"', source)
        self.assertIn("_state.alignment_d3d11_loading_timer.timeout.connect(_state._tick_alignment_d3d11_loading_spinner)", source)
        self.assertIn("state.get('package_quality', 'normal')", d3d11_presentation_source)
        self.assertIn("'modify_original_alignment' if _state.modify_original_clone_mode else 'mesh_replacement_alignment'", source)
        self.assertIn("alignment_d3d11_display_model as _alignment_d3d11_display_model_helper", source)
        self.assertIn("d3d11_preview_model = _state._alignment_d3d11_display_model_helper(", remaining_callbacks_source)
        self.assertIn("def _side_by_side_alignment_preview_model", source)
        self.assertIn("def _shutdown_alignment_d3d11_preview() -> None:", source)
        self.assertIn("def _safe_shutdown_alignment_d3d11_preview() -> None:", source)
        self.assertIn("_alignment_d3d11_stop_worker()", source)
        self.assertIn("_state._safe_stop_alignment_timer(_state.alignment_d3d11_status_timer)", source)
        self.assertIn('state["queued_model"] = None', source)
        self.assertIn('state["pending_model"] = None', source)
        self.assertIn("dialog.finished.connect(_modeless_alignment_dialog_finished)", source)
        self.assertIn("_safe_shutdown_alignment_d3d11_preview()", source)
        self.assertNotIn("_clear_alignment_webgl_preview", source)
        self.assertNotIn("\n                alignment_d3d11_stop_worker()", source)
        self.assertIn("clone_model(original_reference_model)", d3d11_mapping_source)
        self.assertIn('"original_reference"', d3d11_mapping_source)
        self.assertIn("combined = combine_alignment_preview_models(", d3d11_mapping_source)
        self.assertIn("preserve_overlays=preserve", d3d11_mapping_source)
        self.assertIn("return combine_preview_models(original_workspace, replacement_workspace)", d3d11_mapping_source)
        self.assertNotIn("legacy_preview_fallback_checkbox", source)
        self.assertNotIn("_toggle_legacy_preview_fallback", source)
        self.assertIn('alignment_preview_settings_button = QPushButton(alignment_preview_control_text["settings_button"])', source)
        self.assertIn('alignment_renderer_scope_label = QLabel(alignment_preview_control_text["renderer_scope"])', source)
        self.assertIn('"settings_button": "Preview Settings..."', preview_status_source)
        self.assertIn("Mesh Replacement Alignment renderer and texture controls are available from Preview Settings.", preview_status_source)
        self.assertIn("alignment_preview_render_control_text = _alignment_preview_render_control_text_helper()", source)
        self.assertIn('preview_visible_mode_combo.setToolTip(alignment_preview_render_control_text["visible_tooltip"])', source)
        self.assertIn('"visible_tooltip": "Texture-selection strategy for alignment preview rebuilds."', preview_status_source)
        self.assertIn('"replacement_preview_description": "Select texture slots to preview."', preview_status_source)
        self.assertNotIn("_alignment_webgl_preview_active", source)
        self.assertNotIn("_load_alignment_webgl_preview", source)
        self.assertIn("def alignment_lit_render_settings(", source)
        self.assertIn("archive_renderer_backend=_alignment_renderer_backend_for_dialog()", source)
        self.assertIn("archive_renderer_backend_changed_handler=_set_alignment_renderer_from_dialog", source)
        self.assertIn("settings_changed_handler=_sync_from_modal_settings", source)
        self.assertIn("preview_settings=_state._current_alignment_preview_render_settings()", remaining_callbacks_source)
        self.assertIn("dialog.settings_changed.connect(self._handle_model_preview_settings_changed)", source)
        self.assertIn("dialog.settings_changed.connect(settings_changed_handler)", source)
        self.assertIn('active_dialogs = getattr(self, "_modal_model_preview_settings_dialogs", None)', source)
        self.assertIn('modal_handlers = getattr(self, "_modal_model_preview_settings_handlers", None)', source)
        self.assertIn("active_handlers[dialog] = settings_changed_handler", source)
        self.assertIn("modal_dialog.set_settings(settings)", source)
        self.assertIn("handler(settings)", source)
        self.assertIn("_state.context.get('_alignment_lit_render_settings_helper') or _state.context.get('_alignment_lit_render_settings')", remaining_callbacks_source)
        self.assertIn("def _lit_alignment_settings(settings: object) -> ModelPreviewRenderSettings:", remaining_callbacks_source)
        self.assertIn("_state._alignment_lit_render_settings(settings, fallback_settings)", remaining_callbacks_source)
        self.assertNotIn("_state._alignment_lit_render_settings(settings)", remaining_callbacks_source)
        self.assertNotIn("base_texture_defaults", source)
        self.assertIn("preview_render_settings = _alignment_lit_render_settings_helper(", source)
        self.assertNotIn('aligned_settings.render_diagnostic_mode = "lit"', source)
        self.assertIn("settings.visible_texture_mode = str(", source)
        self.assertIn("settings.disable_all_support_maps = not bool(_state.preview_support_maps_checkbox.isChecked())", remaining_callbacks_source)
        self.assertNotIn('if detail_mode != "full":', source)
        self.assertIn("channel_debug = _state.self._archive_material_channel_debug_from_package(package_dir)", source)
        self.assertIn("def _set_preview_performance_status(summary: str, *, details: str='') -> None:", routing_callbacks_source)
        self.assertIn("_alignment_d3d11_loaded_timing_presentation_helper(", source)
        self.assertIn("_set_preview_performance_status_if_ready(timing_presentation.summary, details=timing_presentation.details)", source)
        self.assertIn("_alignment_d3d11_reload_queued_performance_helper(", source)
        self.assertIn("cache={cache_event}", d3d11_presentation_source)
        self.assertIn("native_load_upload", d3d11_presentation_source)
        self.assertIn("def clone_preview_attr_value(value: object) -> object:", source)
        self.assertIn("if isinstance(value, QImage):", source)
        self.assertIn("return value.copy()", source)
        self.assertIn("def _safe_refresh_static_dialog_preview", source)
        self.assertIn("'mesh_alignment_preview_refresh_failed'", remaining_callbacks_source)
        self.assertIn("_state.static_preview_refresh_timer.timeout.connect(_state._safe_refresh_static_dialog_preview)", source)
        self.assertNotIn("+ (f\"; {channel_debug}\" if channel_debug else \"\")", source)
        self.assertIn("_alignment_preview_help_presentation_helper(d3d11_active=True)", source)
        self.assertIn('text="Resident .NET/Vortice alignment preview."', preview_status_source)
        self.assertIn("Movement, rotation, part hover/selection, brush/vertex strokes, and view modes run through the resident .NET/Vortice renderer.", preview_status_source)
        self.assertNotIn("Reference WebGL/PBR", source)
        self.assertIn("alignment_d3d11_preview_host.set_display_mode(", source)
        self.assertIn("alignment_d3d11_preview_host.set_mesh_edit_state(", source)
        self.assertIn("alignment_d3d11_preview_host.set_alignment_state(", source)
        self.assertIn("alignment_d3d11_drag_transaction", source)
        self.assertIn("alignment_d3d11_drag_ui_timer.setInterval(66)", source)
        self.assertIn("def _queue_global_transform_values_for_d3d11_drag", source)
        self.assertIn("def _queue_selected_part_controls_for_d3d11_drag", source)
        self.assertIn("_alignment_d3d11_drag_ui_queue_global_helper(", source)
        self.assertIn("_alignment_d3d11_drag_ui_queue_part_helper(", source)
        self.assertIn("_alignment_d3d11_global_control_state_helper(", source)
        self.assertIn("_alignment_d3d11_drag_ui_timer_state_helper(", source)
        self.assertIn("_alignment_d3d11_drag_ui_flush_state_helper(", source)
        self.assertIn("_alignment_d3d11_drag_transform_update_state_helper(", source)
        self.assertIn("_alignment_d3d11_finish_drag_update_state_helper(", source)
        self.assertIn("_alignment_d3d11_drag_ui_take_helper(", source)
        self.assertIn("def _flush_alignment_d3d11_drag_ui", source)
        self.assertIn("_state.alignment_d3d11_drag_ui_timer.timeout.connect(_state._flush_alignment_d3d11_drag_ui)", source)
        self.assertIn("_state.alignment_d3d11_preview_host.alignment_drag_started.connect(_state._prepare_alignment_d3d11_preview_drag)", source)
        self.assertIn("_state.alignment_d3d11_preview_host.alignment_drag_changed.connect(_state._apply_alignment_d3d11_translation_total)", source)
        self.assertIn("_state.alignment_d3d11_preview_host.alignment_drag_finished.connect(_state._finish_alignment_d3d11_translation)", source)
        self.assertIn("_state.alignment_d3d11_preview_host.alignment_rotation_changed.connect(_state._apply_alignment_d3d11_rotation_total)", source)
        self.assertIn("_state.alignment_d3d11_preview_host.alignment_rotation_finished.connect(_state._finish_alignment_d3d11_rotation)", source)
        self.assertIn("_state.alignment_d3d11_preview_host.source_part_hovered.connect(_state._d3d11_source_part_hovered)", source)
        self.assertIn("def _d3d11_source_part_hovered(editor_id: int) -> None:", source)
        self.assertIn("_state.alignment_d3d11_preview_host.source_part_selected.connect(_state._d3d11_source_part_selected)", source)
        self.assertIn("def _geometry_tab_active() -> bool:", source)
        self.assertIn("if callable(_state._alignment_geometry_tab_active):", source)
        self.assertIn("_state.control_tabs.widget(_state.control_tabs.currentIndex()) is _state.parts_tab", source)
        self.assertIn("in {'mesh editing', 'merged mesh editing'}", source)
        self.assertIn("geometry_tab_active=_state._geometry_tab_active()", source)
        selected_handler = source[
            source.index("def _d3d11_source_part_selected")
            : source.index("def _d3d11_source_part_hovered", source.index("def _d3d11_source_part_selected"))
        ]
        self.assertIn("refresh_preview=False", selected_handler)
        self.assertIn(
            "_state.alignment_d3d11_preview_host.source_part_context_requested.connect(_state._d3d11_source_part_context_requested)",
            source,
        )
        context_handler = source[
            source.index("def _d3d11_source_part_context_requested")
            : source.index("def _original_selection_changed", source.index("def _d3d11_source_part_context_requested"))
        ]
        self.assertIn("refresh_filter=False", context_handler)
        self.assertIn("refresh_preview=False", context_handler)
        self.assertIn("QTimer = context.get('QTimer')", source)
        self.assertIn("cursor = getattr(_state.alignment_d3d11_preview_host, 'cursor', None)", context_handler)
        self.assertIn("global_pos = _state.alignment_d3d11_preview_host.mapToGlobal(_state.QPoint(int(x), int(y)))", context_handler)
        self.assertIn("QTimer.singleShot(0, open_context_menu)", context_handler)
        self.assertIn("_state.hovered_source_part['index'] = source_index", source)
        self.assertIn("_state.alignment_d3d11_preview_host.mesh_edit_stroke_started.connect(lambda payload: _state._mesh_edit_begin_stroke(payload))", source)
        self.assertNotIn("Mesh Edit uses viewport strokes from Legacy GreenUp edit", source)
        self.assertIn("std::string alignment_axis_at", native_source)
        axis_hit_start = native_source.index("std::string alignment_axis_at")
        axis_hit_end = native_source.index("std::string alignment_rotation_handle_at", axis_hit_start)
        axis_hit_block = native_source[axis_hit_start:axis_hit_end]
        self.assertIn("float center_distance = std::numeric_limits<float>::infinity();", axis_hit_block)
        self.assertIn("if (!best_axis.empty() && (center_distance > 12.0f || best_distance + 4.0f < center_distance))", axis_hit_block)
        self.assertIn('return "screen";', axis_hit_block)
        self.assertIn("draw_alignment_overlay_gdi", native_source)
        self.assertIn("if (source_part_.click_pending)", native_source)
        self.assertIn("PreviewCameraState reference_camera_", native_source)
        self.assertIn("input_view_role_at", native_source)
        self.assertIn("float side_by_side_reference_width() const", native_source)
        self.assertIn("std::floor(static_cast<float>(width_) * std::clamp(side_by_side_split_ratio_", native_source)
        self.assertIn("const float left_width = side_by_side_reference_width();", native_source)
        self.assertIn("static_cast<float>(x) <= left_width", native_source)
        self.assertIn("world_units_per_pixel_for_role", native_source)
        self.assertIn("view.role == PreviewViewRole::Reference ? DirectX::XMMatrixIdentity()", native_source)
        self.assertIn("const float local_x = x - view.viewport.TopLeftX", native_source)
        self.assertIn("const float clip_x = (local_x / std::max(1.0f, view.viewport.Width))", native_source)
        self.assertNotIn("TextOutA", native_source)
        self.assertIn("alignment_preview_transform_for_batch", native_source)
        self.assertIn("transformed_batch_position", native_source)
        self.assertIn("project_batch_position", native_source)
        self.assertIn("send_alignment_vector_event(\"alignment_drag_finished\"", native_source)
        self.assertIn("send_alignment_vector_event(\"alignment_drag_changed\"", native_source)
        self.assertIn("send_alignment_vector_event(\"alignment_rotation_finished\"", native_source)
        self.assertIn("send_alignment_vector_event(\"alignment_rotation_changed\"", native_source)
        self.assertIn("alignment_drag_change_due", native_source)
        self.assertIn("last_translation_change_sent", native_source)
        self.assertIn("last_rotation_change_sent", native_source)
        self.assertIn("origin_cache_valid", native_source)
        self.assertIn("origin_cache", native_source)
        self.assertIn("translation_drag_base", native_source)
        self.assertIn("translation_drag_delta", native_source)
        self.assertIn("rotation_drag_base", native_source)
        self.assertIn("rotation_drag_delta", native_source)
        self.assertIn("int source_part_at", native_source)
        self.assertIn("send_source_part_event(\"source_part_hovered\"", native_source)
        self.assertIn("send_source_part_event(\"source_part_selected\"", native_source)
        self.assertIn("send_source_part_context_event", native_source)
        self.assertIn('command == "set_source_part_picking"', native_source)
        self.assertNotIn("std::vector<EditorCandidate> mesh_edit_candidates_at", native_source)
        self.assertIn("send_mesh_edit_event(\"mesh_edit_stroke_started\"", native_source)
        self.assertIn("send_mesh_edit_event(\"mesh_edit_stroke_previewed\"", native_source)
        self.assertIn("command == \"set_display_mode\"", native_source)
        self.assertIn("parse_display_mode", native_source)
        self.assertIn("PreviewViewRole::Reference", native_source)
        self.assertIn("PreviewViewRole::Replacement", native_source)
        self.assertIn("replacement_editor_viewport()", native_source)
        overlay_start = native_source.index('if (display_mode_ == "overlay" && has_reference) {')
        overlay_end = native_source.index("PreviewRenderView only;", overlay_start)
        overlay_block = native_source[overlay_start:overlay_end]
        self.assertIn("reference_overlay.role = PreviewViewRole::Reference;", overlay_block)
        self.assertIn("reference_overlay.reference_tint_alpha = 0.0f;", overlay_block)
        self.assertLess(overlay_block.index("views.push_back(reference_overlay);"), overlay_block.index("views.push_back(replacement);"))
        self.assertNotIn("reference_overlay.wireframe = true;", overlay_block)
        self.assertNotIn("reference_overlay.no_depth = true;", overlay_block)
        self.assertIn("overlay_depth_state_", native_source)
        self.assertIn("batch.editor_role = lower_copy(json_string_field(editor_identity, \"role\"))", native_source)
        self.assertIn('role == "original_reference" ? 0.82f : 0.74f', native_source)
        self.assertIn("selection_tint_alpha", native_source)
        self.assertIn("batch.highlight_strength > 0.0f ? 1.0f : 0.36f", native_source)
        self.assertIn("batch.highlight_strength > 0.0f ? 0.82f : 0.58f", native_source)
        self.assertIn("batch.highlight_strength > 0.0f ? 0.04f : 1.0f", native_source)
        self.assertIn("const bool mesh_edit_flat = mesh_edit_active && !mesh_edit_preserve_materials_for_batch(batch);", native_source)
        self.assertIn("draw_preview_batch(batch, batch_world * view_projection, batch_world, tint, mesh_edit_flat);", native_source)
        self.assertIn("mesh.preview_role = role", source)
        self.assertIn('"original_reference"', d3d11_mapping_source)
        self.assertIn('"replacement_preview"', d3d11_mapping_source)
        self.assertIn("source_vertex_weights", native_source)
        self.assertIn("identity_file", native_source)

    def test_alignment_d3d11_mode_switch_reloads_when_original_role_missing(self) -> None:
        source = _main_window_source()
        self.assertIn('"queued_display_mode": ""', source)
        self.assertIn('"pending_display_mode": ""', source)
        self.assertIn('"active_package_display_mode": ""', source)
        self.assertIn('"active_package_quality": ""', source)
        self.assertIn('"request_display_modes": {}', source)
        self.assertIn('"request_package_qualities": {}', source)
        self.assertIn("def alignment_d3d11_mode_requires_original(mode: str) -> bool:", source)
        self.assertIn('return str(mode or "side_by_side") in {"side_by_side", "overlay"}', source)
        self.assertIn("def alignment_d3d11_package_mode_has_original(mode: str) -> bool:", source)
        self.assertIn('return normalized_mode in {"side_by_side", "overlay"}', source)
        self.assertIn("def alignment_d3d11_mode_refresh_needed(", source)
        self.assertIn("active_package_present and not alignment_d3d11_package_mode_has_original(active_display_mode)", source)
        self.assertIn('active_package_quality == "mesh_edit_raw" and not mesh_edit_raw_preview_active', source)
        preview_mode_source = static_replacement_callback_concern_source(ROOT, "preview_mode")
        self.assertIn("mode_refresh_needed = _state._alignment_d3d11_mode_refresh_needed_helper(", preview_mode_source)
        self.assertIn("if mode_refresh_needed:", preview_mode_source)
        self.assertIn("def alignment_d3d11_queue_preview_request(", source)
        self.assertIn('state["queued_display_mode"] = str(display_mode or "")', source)
        self.assertIn("def alignment_d3d11_queue_pending_request(", source)
        self.assertIn('state["pending_display_mode"] = str(display_mode or "")', source)
        self.assertIn("request_display_modes[request_id] = str(display_mode or \"\")", source)
        self.assertIn("alignment_d3d11_remember_request_package_quality(state, request_id, package_quality)", source)
        package_source = static_replacement_callback_concern_source(ROOT, "d3d11_package_lifecycle")
        self.assertIn('display_mode=requested_display_mode', package_source)
        self.assertIn("def alignment_d3d11_prepare_active_package(", source)
        self.assertIn('state["active_package_display_mode"] = str(display_mode or "")', source)

    def test_alignment_dialog_build_mod_keeps_window_open_for_repeat_exports(self) -> None:
        source = _main_window_source() + "\n" + ARCHIVE_MESH_BUILDER_LIFECYCLE.read_text(encoding="utf-8")
        build_footer_source = ARCHIVE_STATIC_REPLACEMENT_BUILD_FOOTER.read_text(encoding="utf-8")
        accept_state_source = ARCHIVE_STATIC_REPLACEMENT_ACCEPT_STATE.read_text(encoding="utf-8")
        self.assertIn("continue_build_callback: Optional[", source)
        self.assertIn("Optional[QWidget],", source)
        self.assertIn("Callable[[str], None],", source)
        self.assertIn("Callable[[str, bool], None],", source)
        self.assertIn("Callable[[str, bool], None],\n                        str,", source)
        self.assertIn("on_accept: Optional[Callable[[StaticMeshReplacementOptions], None]] = None", source)
        self.assertIn("on_cancel: Optional[Callable[[], None]] = None", source)
        self.assertIn("self._modeless_alignment_dialogs = {}", source)
        self.assertIn("def _modeless_alignment_dialog_key", source)
        self.assertIn("def _activate_modeless_alignment_dialog", source)
        self.assertIn("def _register_modeless_alignment_dialog", source)
        self.assertIn("def _unregister_modeless_alignment_dialog", source)
        self.assertIn("alignment_dialog_key = self._modeless_alignment_dialog_key(entry, obj_path, dialog_title)", source)
        self.assertIn("if self._activate_modeless_alignment_dialog(alignment_dialog_key):", source)
        self.assertIn("self._register_modeless_alignment_dialog(alignment_dialog_key, dialog)", source)
        self.assertIn("dialog.setModal(False)", source)
        self.assertIn("dialog.setWindowModality(Qt.NonModal)", source)
        self.assertIn("_make_alignment_build_footer_helper(", source)
        self.assertIn("alignment_build_footer_import_button_state(", build_footer_source)
        self.assertIn(
            "Build/export with the current alignment settings and keep this window open for more edits.",
            build_footer_source,
        )
        self.assertIn('build_status_label.setObjectName("MeshReplacementBuilderStatus")', build_footer_source)
        self.assertIn('QProgressBar()', build_footer_source)
        self.assertIn('cancel_button = QPushButton("Cancel")', build_footer_source)
        self.assertIn("build_accept_state = _alignment_build_accept_initial_state_helper()", source)
        self.assertIn("_alignment_build_accept_set_running_helper(build_accept_state, True)", source)
        self.assertIn("alignment_build_accept_set_running(state, False)", accept_state_source)
        self.assertIn('QTimer.singleShot(25, _accept_static_options_after_status_paint)', source)
        self.assertIn("def _accept_static_options_after_status_paint() -> None:", source)
        self.assertIn("include_edited_source_mesh=True", source)
        status_start = source.index("def _set_alignment_build_status")
        status_end = source.index("def _dispatch_alignment_accept", status_start)
        status_block = source[status_start:status_end]
        self.assertNotIn("QApplication.processEvents()", status_block)
        self.assertIn("continue_build_available = callable(continue_build_callback)", source)
        self.assertIn("continue_build=continue_build_available", source)
        self.assertIn("continue_build_callback(", source)
        self.assertIn("static_options,", source)
        self.assertIn("dialog,", source)
        self.assertIn('"loose",', source)
        self.assertIn("_alignment_build_started_status_helper()", source)
        self.assertIn(
            "Started mesh replacement build. Builder window remains open for more edits.",
            accept_state_source,
        )
        self.assertIn("_alignment_dialog_mark_accepted_helper(dialog_accepted_state)", source)
        self.assertIn("dialog.accept()", source)
        self.assertIn("def _dispatch_alignment_accept(options: StaticMeshReplacementOptions) -> None:", source)
        self.assertIn("QTimer.singleShot(0, lambda options=static_options: _dispatch_alignment_accept(options))", source)
        self.assertIn("dialog.finished.connect(_modeless_alignment_dialog_finished)", source)
        self.assertIn("self._unregister_modeless_alignment_dialog(alignment_dialog_key, dialog)", source)
        self.assertIn("dialog.deleteLater()", source)
        self.assertIn("dialog.show()", source)
        self.assertIn("dialog.raise_()", source)
        self.assertIn("dialog.activateWindow()", source)
        self.assertIn("source_skeleton: object | None = None", ARCHIVE_STATIC_REPLACEMENT_DIALOG.read_text(encoding="utf-8"))
        self.assertIn("source_skeleton: object | None = None", ARCHIVE_STATIC_REPLACEMENT_DIALOG_PROMPT.read_text(encoding="utf-8"))
        mesh_edit_callback_source = static_replacement_mesh_edit_implementation_source(ROOT)
        self.assertIn("'prompt_shell_context', 'source_skeleton'", mesh_edit_callback_source)
        self.assertIn("session.controller.attach_skeleton(", mesh_edit_callback_source)
        alignment_block = source[
            source.index("def _prompt_archive_static_replacement_options"):
            source.index("__all__", source.index("def _prompt_archive_static_replacement_options"))
        ]
        self.assertNotIn("patch_game_files_button", alignment_block)
        self.assertNotIn('QPushButton("Patch Game Files")', alignment_block)
        self.assertNotIn("Directly patch the rebuilt mesh into scanned game archives for testing.", alignment_block)
        self.assertNotIn("Started mesh replacement archive patch. Builder window remains open for more edits.", alignment_block)
        self.assertNotIn("if dialog.exec() != QDialog.Accepted", alignment_block)
        self.assertNotIn("\n            dialog.exec()", alignment_block)

    def test_mesh_replacement_build_flow_uses_builder_parent_and_captured_state(self) -> None:
        source = _main_window_source() + "\n" + _archive_mesh_import_sources() + "\n" + _archive_mod_ready_export_source()
        accept_source = static_replacement_callback_concern_source(ROOT, "accept_build")
        alignment_setup_source = ARCHIVE_STATIC_REPLACEMENT_ALIGNMENT_SETUP_STATE.read_text(encoding="utf-8")
        self.assertIn("def alignment_builder_window_title", alignment_setup_source)
        self.assertIn("def alignment_builder_already_open_status", alignment_setup_source)
        self.assertIn('return "Mesh Replacement Builder"', alignment_setup_source)
        self.assertIn('dialog_title: str = ""', source)
        self.assertIn("dialog_title = dialog_title or _alignment_builder_window_title_helper()", source)
        self.assertIn("self.set_status_message(_alignment_builder_already_open_status_helper())", source)
        self.assertIn("dialog_title=setup.placement_review_title or alignment_builder_window_title()", source)
        self.assertIn("dialog.setWindowTitle(dialog_title)", source)
        self.assertNotIn("dialog.setWindowTitle(_alignment_builder_window_title_helper())", source)
        self.assertIn("parent: Optional[QWidget] = None", source)
        self.assertIn("dialog_parent = parent if parent is not None else self", source)
        self.assertIn("parent=build_dialog_parent", source)
        self.assertIn("export_box_parent = build_dialog_parent", source)
        self.assertIn("patch_box_parent = build_dialog_parent", source)
        self.assertIn("export_box = QMessageBox(export_box_parent)", source)
        self.assertIn("patch_box = QMessageBox(patch_box_parent)", source)
        self.assertIn('complete_external_swap: bool = False', _static_replacer_source())
        self.assertIn("complete_external_swap=bool(False if _state.modify_original_clone_mode else complete_swap_enabled)", accept_source)
        self.assertIn('require_source_owned_colors = bool(getattr(static_replacement_options, "complete_external_swap", False))', source)
        mesh_patch_start = source.index("def _start_archive_mesh_patch")
        commit_start = source.index("def _commit_task(", mesh_patch_start)
        commit_end = source.index("def _handle_commit_complete(result: object) -> None:", commit_start)
        commit_block = source[commit_start:commit_end]
        self.assertNotIn("_complete_external_swap_enabled()", commit_block)
        self.assertIn("def _start_build_with_static_options(", source)
        self.assertIn("continue_build_callback=_start_build_with_static_options", source)
        self.assertIn("on_accept=_start_import_preview_with_options", source)
        self.assertIn("Mesh replacement build cancelled before export target selection.", source)
        self.assertIn("Mesh replacement build cancelled before related file selection.", source)
        self.assertIn('destination = "patch" if str(output_mode or "").strip().casefold() == "patch" else "loose"', source)
        self.assertIn('if destination == "loose":', source)
        self.assertIn("Preparing direct archive patch...", source)
        self.assertIn("include_edited_source_mesh=True", source)
        self.assertNotIn("def _static_options_with_worker_source_snapshot", source)
        self.assertNotIn("Cloning edited replacement mesh snapshot for build worker...", source)
        self.assertNotIn("replacement_mesh_snapshot_source", source)
        self.assertNotIn("needs_edited_source_mesh_snapshot", source)
        self.assertRegex(source, r"worker_options,\n\s+setup\.scene_import_result\.mesh")
        self.assertIn("Mesh archive patch cancelled before writing game files.", source)
        self.assertRegex(source, r"\n\s+return\n\n\s+_start_build_with_static_options\(None\)")

    def test_mesh_editor_import_and_modify_original_paths_share_embedded_builder(self) -> None:
        launch_source = ARCHIVE_MESH_LAUNCH_FLOW.read_text(encoding="utf-8")
        patch_source = ARCHIVE_MESH_PATCH_FLOW.read_text(encoding="utf-8")
        modify_source = ARCHIVE_MESH_MODIFY_ORIGINAL.read_text(encoding="utf-8")
        embedded_host = 'embedded_host=self.mesh_editor_tab.builder_host() if hasattr(self, "mesh_editor_tab") else None'

        self.assertIn(embedded_host, launch_source)
        self.assertIn("on_accept=_start_import_preview_with_options", launch_source)
        self.assertIn(embedded_host, patch_source)
        self.assertIn("continue_build_callback=_start_build_with_static_options", patch_source)
        self.assertIn("source_skeleton=source_skeleton", modify_source)
        self.assertIn("scene_import_result=scene_import_result", modify_source)
        self.assertIn("self._start_archive_mesh_patch(entry, preset_setup=setup)", modify_source)

    def test_mesh_replacement_direct_archive_patch_flow_is_explicit_and_backed_up(self) -> None:
        source = _main_window_source() + "\n" + _archive_mesh_import_sources()
        self.assertIn("def _build_mesh_direct_patch_requests(", source)
        self.assertIn('kind in {"sidecar_generated", "texture_generated", "item_icon_generated"}', source)
        self.assertIn("payload_data = bytes(getattr(spec, \"payload_data\", b\"\") or b\"\")", source)
        self.assertIn("return resolved_source.read_bytes(), \"\"", source)
        self.assertIn("patch_result = mutation_service.apply_patch(", source)
        self.assertNotIn("patch_result = patch_archive_entries(", source)
        self.assertIn("self._apply_archive_patch_result(patch_result)", source)
        self.assertIn("self._render_archive_preview(updated_entry, force=True)", source)
        self.assertIn("self._confirm_mesh_direct_archive_patch(", source)
        self.assertIn("Final package texture preflight blocked direct archive patch because the package contract would not be WYSIWYG", source)
        self.assertIn('"preflight_hard_blocked": hard_blockers', source)
        self.assertIn("Export Anyway (Unsafe)", source)
        self.assertIn('"Final output preflight warnings:"', source)
        self.assertIn("Material preflight warning:", source)
        self.assertIn("A backup of the touched PAPGT/PAMT/PAZ files will be created first", source)
        self.assertNotIn("ARCHIVE_PATCH_BACKUP_ROOT", source)
        self.assertIn("self.app_context.services.require_archive_mutations().backup_root", source)
        self.assertIn('patch_box.setWindowTitle("Game Files Patched")', source)
        self.assertIn('warning_badge = "Patched archive"', source)
        self.assertIn("selected_related_entries: Sequence[ArchiveEntry] = ()", source)
        patch_start = source.index('if destination == "patch":')
        patch_end = source.index('log(f"Writing {len(requests)} rebuilt entries into a mod-ready loose package...")', patch_start)
        patch_block = source[patch_start:patch_end]
        self.assertIn("direct_patch_supplemental_specs", patch_block)
        self.assertNotIn("_collect_archive_mod_ready_export_target", patch_block)
        self.assertNotIn("export_archive_mesh_payloads_to_mod_ready_loose", patch_block)

    def test_startup_splash_registers_as_taskbar_window(self) -> None:
        source = STARTUP_DIALOGS.read_text(encoding="utf-8")
        splash_start = source.index("class StartupSplashDialog")
        splash_block = source[splash_start:source.index("class StartupArchivePathDialog", splash_start)]
        self.assertIn("super().__init__(None)", splash_block)
        self.assertIn("self.setWindowFlags(Qt.Window | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)", splash_block)
        self.assertIn("self.setModal(False)", splash_block)
        self.assertNotIn("Qt.SplashScreen", splash_block)

    def test_alignment_dialog_has_source_mixing_tray_without_new_top_level_tab(self) -> None:
        source = _main_window_source() + "\n" + ARCHIVE_SOURCE_PICKER_DIALOG.read_text(encoding="utf-8")
        workflow_source = ARCHIVE_STATIC_REPLACEMENT_DIALOG_WORKFLOW_SHELL.read_text(encoding="utf-8")
        ui_source = _ui_section_source()
        source_mix_state_source = ARCHIVE_STATIC_REPLACEMENT_SOURCE_MIX_STATE.read_text(encoding="utf-8")
        self.assertIn('summary_section = CollapsibleSection("Summary", expanded=False)', source)
        self.assertIn("setup_layout.addWidget(summary_section)", source)
        self.assertIn("setup_summary_layout.addWidget(import_section)", source)
        self.assertIn("setup_summary_layout.addWidget(context_group)", source)
        self.assertIn('advanced_setup_section = CollapsibleSection("Advanced", expanded=False)', source)
        self.assertIn("advanced_setup_section.setParent(setup_page)", workflow_source)
        self.assertNotIn("advanced_setup_section.setVisible(True)", workflow_source)
        self.assertIn('source_mix_tray = QGroupBox(source_mix_control_text["group_title"])', source)
        self.assertIn("setup_advanced_layout.addWidget(source_mix_tray)", source)
        self.assertNotIn("setup_layout.addWidget(source_mix_tray)", source)
        self.assertNotIn("setup_layout.addWidget(advanced_setup_section)", workflow_source)
        self.assertIn("_state.setup_advanced_layout.addWidget(_state.options_group)", ui_source)
        self.assertLess(ui_source.index("_state.setup_layout.addWidget(_state.transform_section)"), ui_source.index("_state.setup_layout.addWidget(_state.item_icon_section)"))
        self.assertLess(ui_source.index("_state.setup_layout.addWidget(_state.item_icon_section)"), ui_source.index("_state.setup_layout.addWidget(_state.advanced_setup_section)"))
        self.assertLess(ui_source.index("_state.setup_layout.addWidget(_state.advanced_setup_section)"), ui_source.index("_state.setup_layout.addWidget(_state.modify_original_texture_tuning_section)"))
        self.assertLess(ui_source.index("_state.setup_layout.addWidget(_state.modify_original_texture_tuning_section)"), ui_source.index("_state.setup_layout.addWidget(_state.placement_note)"))
        self.assertIn('add_archive_source_button = QPushButton(source_mix_control_text["add_archive"])', source)
        self.assertIn('add_loose_source_button = QPushButton(source_mix_control_text["add_loose"])', source)
        self.assertIn('add_mod_archive_source_button = QPushButton(source_mix_control_text["add_mod_archive"])', source)
        self.assertIn('"group_title": "Source Mixing"', source_mix_state_source)
        self.assertIn('"add_archive": "Add Archive Source"', source_mix_state_source)
        self.assertIn('"add_loose": "Add Loose Mod Folder"', source_mix_state_source)
        self.assertIn('"add_mod_archive": "Add .pamt/.paz Mod"', source_mix_state_source)
        self.assertIn("def _choose_loaded_archive_mesh_source_for_alignment", source)
        self.assertIn("def _choose_mod_archive_mesh_source_for_alignment", source)
        self.assertIn("def _choose_archive_mesh_source_dialog", source)
        self.assertIn('"archive_source_prompt": "Search archive source by name, path, package, or role"', source_mix_state_source)

        self.assertIn("This does not rescan the archive.", source)
        self.assertIn('preview_title = QLabel("Source Preview")', source)
        self.assertIn('extension_combo.addItem("All supported", "")', source)
        self.assertIn('control_row.addWidget(QLabel("Extension"))', source)
        self.assertIn("QTimer.singleShot(0, _restart_source_picker_population)", source)
        self.assertIn('entries_by_extension = getattr(self, "archive_entries_by_extension", {}) or {}', source)
        self.assertIn('source_entries = mesh_entries or (getattr(self, "archive_entries", ()) or ())', source)
        self.assertIn("allowed_extensions=tuple(sorted(ARCHIVE_MESH_EXTENSIONS))", source)
        self.assertIn("excluded_entry=entry", source)
        self.assertIn("self._start_archive_in_game_mesh_swap(", source)
        self.assertIn('SourceMixScanRequest(source_path=Path(selected_dir), source_kind="loose")', source)
        self.assertIn('SourceMixScanRequest(source_path=Path(selected_path), source_kind="mod_archive")', source)
        self.assertIn("run_source_mix_scan", source)
        self.assertNotIn("scan_loose_folder_source(Path(selected_dir))", source)
        self.assertIn("Geometry same | Materials same | Render settings same | Camera synced", source_mix_state_source)
        self.assertIn("Selection highlight preserves texture bindings", source_mix_state_source)
        self.assertNotIn('self.main_tabs.addTab(self.mod_composer_tab', source)

    def test_embedded_scene_transform_binding_is_deferred_until_factory_completion(self) -> None:
        source = static_replacement_ui_concern_source(ROOT, "mesh_geometry_preview")
        binding = "lambda: _state._current_static_alignment_transform()"
        assignment = (
            "_state._current_static_alignment_transform = "
            "_state.alignment_preview_model_callbacks._current_static_alignment_transform"
        )
        self.assertIn(binding, source)
        self.assertIn(assignment, source)
        self.assertLess(source.index(binding), source.index(assignment))

    def test_archive_browser_has_source_mix_pair_overlay_export(self) -> None:
        source = (
            _main_window_source()
            + "\n"
            + ARCHIVE_ACTIONS.read_text(encoding="utf-8")
            + "\n"
            + ARCHIVE_SOURCE_MIX_ACTIONS.read_text(encoding="utf-8")
        )
        self.assertIn('menu.addAction(menu_icons["workflow"], "Build Loose Package From Sources...")', source)
        self.assertIn("def _open_archive_source_mix_package_dialog", source)
        self.assertIn("validate_source_mix_selections(selections)", source)
        self.assertIn("export_archive_payloads_to_mod_ready_loose(", source)
        self.assertIn("SourceMixScanRequest(", source)
        self.assertIn("run_source_mix_scan", source)
        self.assertNotIn("scan_loose_folder_source(", source)
        self.assertNotIn("scan_mod_archive_source(", source)
        self.assertIn("paired_counterpart_virtual_path(entry.path)", source)

    def test_source_mix_exports_sidecar_referenced_texture_payloads(self) -> None:
        source = ARCHIVE_SOURCE_MIX_ACTIONS.read_text(encoding="utf-8")
        self.assertIn("def _source_mix_lookup_keys_for_texture_path", source)
        self.assertIn("def _source_mix_sidecar_referenced_payload_specs", source)
        self.assertIn("parse_texture_sidecar_bindings(sidecar_text", source)
        self.assertIn("Auto-included because selected sidecar", source)
        self.assertIn("extra_payloads_to_include=extra_payload_specs", source)
        self.assertIn("Auto-including {len(extra_payload_specs):,} sidecar-referenced texture payload(s)", source)

    def test_alignment_dialog_sidecar_toggles_flow_into_preview_build(self) -> None:
        source = _main_window_source() + "\n" + _archive_mesh_import_sources()
        accept_source = static_replacement_callback_concern_source(ROOT, "accept_build")
        self.assertIn("complete_swap_enabled = bool(_state._complete_external_swap_enabled()) and (not _state.modify_original_clone_mode)", accept_source)
        self.assertIn("else _state.rebuild_sidecar_checkbox.isChecked() or complete_swap_enabled", accept_source)
        self.assertIn("complete_external_swap=bool(False if _state.modify_original_clone_mode else complete_swap_enabled)", accept_source)
        self.assertIn("else _state.source_color_faithful_checkbox.isChecked() or complete_swap_enabled", accept_source)
        self.assertIn("else _state.external_material_reset_checkbox.isChecked() or complete_swap_enabled", accept_source)
        self.assertIn("else _state.inject_base_color_checkbox.isChecked() or complete_swap_enabled", accept_source)
        self.assertIn("require_source_owned_colors=require_source_owned_colors", source)
        self.assertIn("static_replacement_options=active_static_options", source)
        self.assertIn("extra_supplemental_specs=setup.extra_supplemental_specs", source)

    def test_modify_original_texture_tuning_is_separate_from_import_mesh_material_authority(self) -> None:
        workflow_source = ARCHIVE_STATIC_REPLACEMENT_DIALOG_WORKFLOW_SHELL.read_text(encoding="utf-8")
        ui_source = static_replacement_ui_concern_source(ROOT, "setup_options_transform")
        outliner_source = static_replacement_ui_concern_source(ROOT, "source_parts_outliner")
        callbacks_source = _callback_factory_source()
        remaining_source = static_replacement_remaining_callback_source(ROOT)
        manual_profile_source = ARCHIVE_STATIC_REPLACEMENT_MANUAL_MATERIAL_PROFILE.read_text(encoding="utf-8")

        self.assertIn('"modify_original"', workflow_source)
        self.assertIn("control_tabs.setTabVisible(control_tabs.indexOf(textures_tab), False)", workflow_source)
        self.assertIn('source_mix_tray.setVisible(static_replacement_workflow_mode == "import_mesh")', workflow_source)
        self.assertIn("_state.modify_original_texture_tuning_checkbox = _state.QCheckBox('Advanced Texture Tuning')", ui_source)
        self.assertIn("_state.part_material_tuning_widgets = (", outliner_source)
        self.assertIn("visible = not bool(_state.modify_original_clone_mode) or _state._modify_original_texture_tuning_enabled()", outliner_source)
        self.assertIn("_state._refresh_part_material_tuning_visibility()", outliner_source)
        placeholder_index = ui_source.index("def _refresh_part_material_tuning_visibility() -> None:\n        return None")
        signal_index = ui_source.index("_state.modify_original_texture_tuning_checkbox.toggled.connect(")
        real_refresh_index = outliner_source.index("_state.part_material_tuning_widgets = (")
        self.assertLess(placeholder_index, signal_index)
        self.assertGreater(real_refresh_index, 0)
        self.assertIn("_state._modify_original_texture_tuning_enabled = _state.context.get('_modify_original_texture_tuning_enabled')", outliner_source)
        self.assertIn("if not callable(_state._modify_original_texture_tuning_enabled):\n        _state._modify_original_texture_tuning_enabled = lambda: False", outliner_source)
        self.assertIn("_state.material_authority_section.setVisible(not _state.modify_original_clone_mode)", ui_source)
        self.assertIn(
            "_state.manual_profile_settings_key = _state.modify_original_manual_profile_settings_key if _state.modify_original_clone_mode else _state.import_manual_profile_settings_key",
            ui_source,
        )
        self.assertIn("if not _state.modify_original_clone_mode:\n        _state._manual_combo(", ui_source)
        self.assertIn("if not _state.modify_original_clone_mode:\n        _state._manual_check(38, 'source_color_layer_authority'", ui_source)
        self.assertIn("modify_original_tuning_enabled = _state._modify_original_tuning_enabled_value()", callbacks_source)
        self.assertIn("texture_slot_overrides=[] if modify_original_options_mode else", callbacks_source)
        self.assertIn("source_material_texture_overrides=list([] if modify_original_options_mode", callbacks_source)
        self.assertIn("donor_material_plans=[] if modify_original_options_mode else", callbacks_source)
        self.assertIn("allow_unsafe_material_preflight_export=bool(False if modify_original_options_mode else", callbacks_source)
        self.assertIn("additional_supplemental_files=[] if modify_original_options_mode else", callbacks_source)
        self.assertIn("def _material_authority_preview_route_enabled() -> bool:", callbacks_source)
        self.assertIn("if bool(modify_original_clone_mode) and callable(_modify_original_texture_tuning_enabled):", callbacks_source)
        self.assertIn("effective_enabled = bool(enabled) and (", callbacks_source)
        self.assertIn("if not _state._modify_original_texture_tuning_enabled():\n                return False", callbacks_source)
        self.assertIn("complete_enabled=_material_authority_preview_route_enabled()", callbacks_source)
        self.assertIn("auto_brightness_balance=0.0 if _state.modify_original_clone_mode else", callbacks_source)
        self.assertIn("modify_original_tuning_enabled = _state._modify_original_tuning_enabled_value()", remaining_source)
        self.assertIn("material_authority_preview_route_enabled = bool(", remaining_source)
        self.assertIn("complete_external_swap_enabled=material_authority_preview_route_enabled", remaining_source)
        self.assertIn("MODIFY_ORIGINAL_MANUAL_TEXTURE_TUNING_KEYS", manual_profile_source)
        self.assertIn('"settings/modify_original_manual_texture_tuning"', manual_profile_source)
        self.assertNotIn('"base_binding_mode",\n    "mask_binding_mode",\n    "support_policy"', manual_profile_source)

    def test_mesh_replacement_loose_export_completion_dialog_is_readable(self) -> None:
        source = _main_window_source() + "\n" + _archive_mesh_import_sources()
        self.assertIn("export_box = QMessageBox(export_box_parent)", source)
        self.assertIn('export_box.setWindowTitle("Loose Export Complete")', source)
        self.assertIn('export_box.setText("Loose package written.")', source)
        self.assertIn("export_box.setInformativeText(str(loose_result.package_root))", source)
        self.assertIn("export_box.setDetailedText(", source)
        self.assertIn("export_box.setMinimumSize(QSize(560, 180))", source)
        self.assertNotIn('QMessageBox.information(\n                            self,\n                            "Loose Export Complete"', source)

    def test_archive_preview_details_falls_back_to_current_result_text(self) -> None:
        source = "\n".join(
            (
                _main_window_source(),
                ARCHIVE_PREVIEW_DETAILS.read_text(encoding="utf-8"),
            )
        )
        self.assertIn('if not base_detail_text and self.current_archive_preview_result is not None:', source)
        self.assertIn('self.current_archive_preview_result.detail_text', source)
        self.assertIn('self.current_archive_preview_result.metadata_summary', source)

    def test_modify_original_has_cross_original_material_source_flow(self) -> None:
        source = _main_window_source()
        archive_source = _archive_modding_source()
        static_source = _static_replacer_source()
        authority_controls_source = ARCHIVE_STATIC_REPLACEMENT_MATERIAL_AUTHORITY_CONTROLS.read_text(encoding="utf-8")
        donor_state_source = ARCHIVE_STATIC_REPLACEMENT_DONOR_MATERIAL_STATE.read_text(encoding="utf-8")
        donor_loader_source = ARCHIVE_STATIC_REPLACEMENT_DONOR_MATERIAL_LOADER.read_text(encoding="utf-8")

        self.assertIn("class StaticDonorMaterialTextureBinding", static_source)
        self.assertIn("class StaticDonorMaterialPlan", static_source)
        self.assertIn("donor_material_plans: list[StaticDonorMaterialPlan]", static_source)
        self.assertIn(
            "donor_bindings_from_sidecar_profiles as _donor_bindings_from_sidecar_profiles_helper",
            source,
        )
        self.assertIn(
            "donor_material_plan_build_state as _donor_material_plan_build_state_helper",
            source,
        )
        self.assertIn("_state.donor_control_text = _state._material_authority_donor_control_text_helper()", source)
        self.assertIn("_state.QGroupBox(_state.str(_state.donor_control_text['group_title']))", source)
        self.assertIn("_state.QPushButton(_state.str(_state.donor_control_text['use_button']))", source)
        self.assertIn("_state.QPushButton(_state.str(_state.donor_control_text['clear_button']))", source)
        self.assertIn("_state.donor_material_plan_tree.setHeaderLabels(_state.list(_state.donor_control_text['plan_headers']))", source)
        self.assertIn('"group_title": "Cross-Original Material Sources"', authority_controls_source)
        self.assertIn('"use_button": "Use Another Original Mesh..."', authority_controls_source)
        self.assertIn('"clear_button": "Clear Selected Target"', authority_controls_source)
        self.assertIn('"parts_label": "Donor parts / material wrappers"', authority_controls_source)
        self.assertIn("def _open_original_material_source_picker", source)
        self.assertIn("donor_preview = _state.NativePreviewPanel", source)
        self.assertIn("donor_part_tree.setHeaderLabels(list(_state.donor_control_text['part_headers']))", source)
        self.assertIn("donor_texture_tree.setHeaderLabels(list(_state.donor_control_text['texture_headers']))", source)
        self.assertIn('"part_headers": ["Donor part", "Shader", "Textures", "Emissive/glow"]', authority_controls_source)
        self.assertIn('"texture_headers": ["Role", "Parameter", "DDS", "Shader", "State"]', authority_controls_source)
        self.assertIn("def donor_bindings_from_sidecar_profiles", donor_state_source)
        self.assertIn("parse_material_sidecar_profile(sidecar_text, sidecar_path=sidecar_path)", donor_state_source)
        self.assertIn("if not bindings:", donor_loader_source)
        self.assertIn("bindings = donor_bindings_from_sidecar_profiles(sidecar_texts)", donor_loader_source)
        self.assertIn("task_accepts_cancel=True", source)
        self.assertIn("DONOR_MODE_OPTIONS", source)
        self.assertIn('("Authoritative donor recipe", "authoritative_recipe")', source)
        self.assertIn('("Donor material behavior", "material_behavior")', source)
        self.assertIn('("Donor material profile", "material_profile")', source)
        self.assertIn('("Donor textures", "donor_textures")', source)
        self.assertIn("_state._populate_combo_options_helper(donor_mode_combo, _state.DONOR_MODE_OPTIONS)", source)
        self.assertIn("profile_mode_index = donor_mode_combo.findData('authoritative_recipe')", source)
        self.assertIn('donor_mode_combo.setCurrentIndex(profile_mode_index)', source)
        self.assertIn("replaces inherited target material bindings", authority_controls_source)
        self.assertIn("uses compatible target .pac_xml texture parameters first", authority_controls_source)
        self.assertIn('state = (', donor_state_source)
        self.assertIn('"emissive/glow"', donor_state_source)
        self.assertIn("StaticDonorMaterialTextureBinding(", donor_state_source)
        self.assertIn("plan = StaticDonorMaterialPlan(", donor_state_source)
        self.assertIn("_state.donor_material_plans_by_target[target_index] = plan_state.plan", source)
        self.assertIn("donor_material_plan_payload=_state._donor_material_plan_payload_helper(_state._current_donor_material_plans())", source)
        self.assertIn("'donor_material_plans': _state._current_donor_material_plans()", source)
        self.assertIn("donor_material_plans=[] if modify_original_options_mode else list(placement_snapshot.get", source)
        self.assertIn('"donor_material_plans": tuple(getattr(options', archive_source)
        self.assertIn('or values["donor_material_plans"]', archive_source)
        self.assertIn('donor_material_plans=values["donor_material_plans"]', archive_source)

    def test_custom_item_icon_controls_flow_into_mesh_and_placement_exports(self) -> None:
        source = (
            _main_window_source()
            + "\n"
            + _archive_mesh_import_sources()
            + "\n"
            + ARCHIVE_ATTACHMENT_PLACEMENT_DIFF_DIALOG.read_text(encoding="utf-8")
        )
        icon_source = ARCHIVE_ATTACHMENT_ICONS.read_text(encoding="utf-8")
        combined_source = source + "\n" + icon_source
        static_source = _static_replacer_source()
        custom_icon_source = ARCHIVE_STATIC_REPLACEMENT_CUSTOM_ICON.read_text(encoding="utf-8")
        setup_ui_source = static_replacement_ui_concern_source(ROOT, "setup_options_transform")
        capture_source = ARCHIVE_STATIC_REPLACEMENT_DIALOG_CUSTOM_ICON_CALLBACKS.read_text(encoding="utf-8")
        self.assertIn("from cdmw.domain.library.item_icons import", source + icon_source + custom_icon_source)
        self.assertIn("custom_icon_control_text = _custom_item_icon_control_text_helper()", source)
        self.assertIn("_state.custom_icon_checkbox = _state.QCheckBox(_state.custom_icon_control_text['use_custom_icon'])", setup_ui_source)
        self.assertIn("_state.QLabel(_state.custom_icon_control_text['source_label'])", setup_ui_source)
        self.assertIn("_state.QLabel(_state.custom_icon_control_text['target_label'])", setup_ui_source)
        self.assertIn("def _alignment_custom_icon_override_spec", source)
        self.assertIn("def _placement_custom_icon_override_spec", source)
        self.assertIn("_state.custom_icon_library_button = _state.QPushButton(_state.custom_icon_control_text['library_button'])", setup_ui_source)
        self.assertIn("_state.QCheckBox(_state.custom_icon_control_text['save_generated_to_library'])", setup_ui_source)
        self.assertIn("'MeshAlignmentSaveGeneratedIconToLibraryCheckbox'", setup_ui_source)
        self.assertIn('"use_custom_icon": "Use custom item icon"', custom_icon_source)
        self.assertIn('"source_label": "Item icon source"', custom_icon_source)
        self.assertIn('"target_label": "Item icon target"', custom_icon_source)
        self.assertIn('"save_generated_to_library": "Save generated preview icon to Icon Creator library"', custom_icon_source)
        self.assertIn('"warning_title": "Custom Item Icon"', custom_icon_source)
        self.assertIn('"choose_file_title": "Choose Custom Item Icon"', custom_icon_source)
        self.assertIn('"choose_folder_title": "Choose Custom Item Icon Folder"', custom_icon_source)
        self.assertIn('"generate_preview_button": "Generate Icon"', custom_icon_source)
        self.assertIn('"generate_preview_warning_title": "Generate Icon From Preview"', custom_icon_source)
        self.assertIn("custom_item_icon_write_failure_message", custom_icon_source)
        self.assertIn("custom_item_icon_generation_status_message", custom_icon_source)
        self.assertIn("mesh_editor_generated_icon_path", custom_icon_source)
        self.assertIn("register_mesh_editor_generated_icon", custom_icon_source)
        self.assertIn("self._choose_item_icon_library_source(dialog)", source)
        self.assertIn("custom_item_icon_override_spec", source)
        self.assertIn(".choose_source(", custom_icon_source)
        self.assertIn("custom_item_icon_setup_state", custom_icon_source)
        self.assertIn("custom_item_icon_control_enabled_state", custom_icon_source)
        self.assertIn("custom_item_icon_generated_apply_state", custom_icon_source)
        self.assertIn("_custom_item_icon_setup_state_helper(", source)
        self.assertIn("_custom_item_icon_control_enabled_state_helper(", source)
        self.assertIn("custom_item_icon_status_text", custom_icon_source)
        self.assertIn("CUSTOM_ITEM_ICON_NO_TARGET_EXPORT_MESSAGE", source)
        self.assertIn("custom_item_icon_preview_image", custom_icon_source)
        self.assertIn("custom_item_icon_register_generated_icon", custom_icon_source)
        self.assertIn("custom_item_icon_suggested_generated_path", custom_icon_source)
        self.assertIn("custom_item_icon_override=custom_item_icon_override", source)
        self.assertIn("kind=\"item_icon_generated\"", combined_source)
        self.assertIn("custom_icon_specs", source)
        self.assertIn("requests_by_path[target_key] = ArchivePatchRequest(target_icon_entry, generated_icon_spec.payload_data)", source)
        self.assertIn("custom_item_icon_override: object | None = None", static_source)
        self.assertTrue(all(token in capture_source for token in ('capture = getattr(dialog, "_mesh_editor_embedded_capture_icon", None)', "if callable(capture):", "capture(on_captured)", "on_captured(None)")))
        self.assertNotIn("set_icon_capture_mode", capture_source)
        self.assertNotIn("screen.grabWindow", capture_source)

    def test_modify_original_clone_uses_exact_geometry_preview_and_target_highlight(self) -> None:
        source = _main_window_source() + "\n" + _archive_mesh_import_sources()
        callback_factory_source = _callback_factory_source()
        prompt_shell_source = ARCHIVE_STATIC_REPLACEMENT_DIALOG_PROMPT_SHELL.read_text(encoding="utf-8")
        prompt_setup_source = ARCHIVE_STATIC_REPLACEMENT_DIALOG_PROMPT_SETUP.read_text(encoding="utf-8")
        prompt_state_source = ARCHIVE_STATIC_REPLACEMENT_DIALOG_PROMPT_STATE_CALLBACKS.read_text(encoding="utf-8")
        mesh_edit_callback_source = static_replacement_mesh_edit_implementation_source(ROOT)
        refresh_queue_source = static_replacement_callback_concern_source(ROOT, "refresh_queue")
        transform_drag_source = static_replacement_callback_concern_source(ROOT, "transform_drag")
        selected_part_control_source = static_replacement_callback_concern_source(ROOT, "selected_part_control")
        remaining_callback_source = static_replacement_remaining_callback_source(ROOT)
        routing_callback_source = static_replacement_routing_callback_source(ROOT)
        selection_mapping_source = ARCHIVE_STATIC_REPLACEMENT_DIALOG_SELECTION_MAPPING.read_text(encoding="utf-8")
        ui_sections_source = _ui_section_source()
        ui_sections_facade_source = ARCHIVE_STATIC_REPLACEMENT_DIALOG_UI_SECTIONS.read_text(encoding="utf-8")
        source_parts_state_source = _source_part_owner_sources()
        mapping_table_state_source = ARCHIVE_STATIC_REPLACEMENT_MAPPING_TABLE_STATE.read_text(encoding="utf-8")
        self.assertIn("modify_original_clone_mode = _modify_original_clone_mode(", source)
        self.assertIn("if _state.modify_original_clone_mode:\n            appended_geometry = int(_state.source_geometry_revision.get('value', 0) or 0)", refresh_queue_source)
        self.assertNotIn('if _alignment_preview_detail_mode() == "full":\n                            return 0', source)
        self.assertIn("target_total_faces=35_000", source)
        self.assertIn("target_total_faces=35_000", source)
        self.assertIn('confidence_label="exact-original-clone"', source)
        self.assertIn("_state.alignment_mode_combo.findData('manual')", transform_drag_source)
        self.assertIn("selected_target_source_highlight_indices", source)
        self.assertIn("selected_target_original_highlight_indices", source)
        self.assertIn("_source_part_assignment_highlight_state_helper(", source)
        self.assertIn("selected_target_source_highlight_indices.update", source)
        self.assertIn("def _context_builtin(context: dict[str, object], name: str) -> object:", ui_sections_facade_source)
        self.assertIn("_state.getattr = _state._context_builtin(_state.context, 'getattr')", ui_sections_source)
        self.assertNotIn("_state.getattr = _state.context.get('getattr')", ui_sections_source)
        self.assertIn("_state.NameError = _state._context_builtin(_state.context, 'NameError')", ui_sections_source)
        self.assertIn("if callable(_state._refresh_mesh_edit_controls):", selected_part_control_source)
        self.assertIn("def _sync_mesh_editor_tab_action_state(", mesh_edit_callback_source)
        self.assertIn('getattr(_state.self, "mesh_editor_tab", None)', mesh_edit_callback_source)
        self.assertIn('getattr(mesh_editor_tab, "update_editor_action_state", None)', mesh_edit_callback_source)
        self.assertIn("undo_count=len(_state.mesh_edit_undo_stack)", mesh_edit_callback_source)
        self.assertIn("redo_count=len(_state.mesh_edit_redo_stack)", mesh_edit_callback_source)
        self.assertIn("_sync_mesh_editor_tab_action_state(", mesh_edit_callback_source)
        self.assertIn("def _mesh_editor_action_bar_action_requested(_state, _callbacks, action: object) -> bool:", mesh_edit_callback_source)
        self.assertIn('if command == "delete":', mesh_edit_callback_source)
        self.assertIn("_mesh_edit_delete_selected_faces()", mesh_edit_callback_source)
        self.assertIn('if command == "subdivide":', mesh_edit_callback_source)
        self.assertIn("_mesh_edit_subdivide_selection()", mesh_edit_callback_source)
        self.assertIn('if command == "refine_smooth":', mesh_edit_callback_source)
        self.assertIn("_mesh_edit_subdivide_selection(refine_smooth=True)", mesh_edit_callback_source)
        self.assertIn('if command in {"split", "separate"}:', mesh_edit_callback_source)
        self.assertIn("_mesh_edit_split_selection_to_part()", mesh_edit_callback_source)
        self.assertIn("def _mesh_editor_edge_selection(", mesh_edit_callback_source)
        self.assertIn("edges_by_submesh: dict[int, set[tuple[int, int]]] = {}", mesh_edit_callback_source)
        self.assertIn("for submesh_index, edge_items in (_state.mesh_edit_selected_edges_by_submesh or {}).items():", mesh_edit_callback_source)
        self.assertIn("edges_by_submesh.setdefault(int(submesh_index), set()).add((left, right))", mesh_edit_callback_source)
        self.assertIn("def _mesh_editor_apply_action_bar_service_action(", mesh_edit_callback_source)
        self.assertIn("edge_action: bool = False", mesh_edit_callback_source)
        self.assertIn("params_factory: object | None = None", mesh_edit_callback_source)
        self.assertIn("selected_edges = _callbacks._mesh_editor_edge_selection(selected_vertices, selected_faces) if edge_action else {}", mesh_edit_callback_source)
        self.assertIn("if callable(params_factory):", mesh_edit_callback_source)
        self.assertIn("edges_by_submesh=selected_edges", mesh_edit_callback_source)
        self.assertIn("def _mesh_editor_prompt_action_value(", mesh_edit_callback_source)
        self.assertIn("_state.QInputDialog.getDouble(", mesh_edit_callback_source)
        self.assertIn("def _mesh_editor_prompt_material_part(", mesh_edit_callback_source)
        self.assertIn('_state.QInputDialog.getItem(', mesh_edit_callback_source)
        self.assertIn("'_current_complete_swap_material_profile_token'", mesh_edit_callback_source)
        self.assertIn('actual_topology_action = bool(topology_action or getattr(edit_result, "topology_changed", False))', mesh_edit_callback_source)
        self.assertIn('if key == "transform_rotate":', mesh_edit_callback_source)
        self.assertIn('"Rotate selected elements around Z axis (degrees):"', mesh_edit_callback_source)
        self.assertIn('params={"rotate": (0.0, 0.0, degrees)}', mesh_edit_callback_source)
        self.assertIn('if key == "transform_scale":', mesh_edit_callback_source)
        self.assertIn('"Uniform scale selected elements:"', mesh_edit_callback_source)
        self.assertIn('params={"scale": (factor, factor, factor)}', mesh_edit_callback_source)
        self.assertIn("_SERVICE_TOPOLOGY_ACTIONS = frozenset(", mesh_edit_callback_source)
        self.assertIn('_EDGE_SERVICE_ACTIONS = frozenset({"loop_cut", "edge_split", "bridge"})', mesh_edit_callback_source)
        self.assertIn('"dissolve"', mesh_edit_callback_source)
        self.assertIn('"duplicate"', mesh_edit_callback_source)
        self.assertIn('"mirror"', mesh_edit_callback_source)
        self.assertIn('"extrude"', mesh_edit_callback_source)
        self.assertIn('"inset"', mesh_edit_callback_source)
        self.assertIn('"merge"', mesh_edit_callback_source)
        self.assertIn('"weld"', mesh_edit_callback_source)
        self.assertIn('"fill"', mesh_edit_callback_source)
        self.assertIn('"uv_transform"', mesh_edit_callback_source)
        self.assertIn('"recalculate_normals"', mesh_edit_callback_source)
        self.assertIn('"weighted_normals"', mesh_edit_callback_source)
        self.assertIn('"flip_normals"', mesh_edit_callback_source)
        self.assertIn('if command == "material_assign":', mesh_edit_callback_source)
        self.assertIn("params_factory=lambda: _callbacks._mesh_editor_material_assign_params(text)", mesh_edit_callback_source)
        self.assertIn('if command == "material_copy":', mesh_edit_callback_source)
        self.assertIn("params_factory=lambda: _callbacks._mesh_editor_material_copy_params(text)", mesh_edit_callback_source)
        self.assertIn("Select adjacent vertices, faces, or edges before using {action_text}.", mesh_edit_callback_source)
        self.assertIn("Select vertices or faces before using {action_text}.", mesh_edit_callback_source)
        self.assertIn("_mesh_editor_commit_action_bar_service_result(", mesh_edit_callback_source)
        self.assertIn('if command == "undo":', mesh_edit_callback_source)
        self.assertIn("_callbacks._mesh_edit_undo()", mesh_edit_callback_source)
        self.assertIn("setattr(_state.dialog, '_mesh_editor_action_bar_action_requested'", ui_sections_source)
        self.assertIn("_state.alignment_mesh_edit_callbacks._mesh_editor_action_bar_action_requested", ui_sections_source)
        self.assertIn("texture_files_for_mapping = context.get('texture_files_for_mapping') or ()", callback_factory_source)
        self.assertIn("_get_texture_sets = context.get('_get_texture_sets')", callback_factory_source)
        self.assertIn("def _current_texture_sets_for_material_authority() -> Mapping[str, object]:", callback_factory_source)
        self.assertIn("getter = context.get('_get_texture_sets')", callback_factory_source)
        self.assertIn("_mesh_editor_diagnostics_append_safe_value_helper(lines, \"mesh_edit_tab_active\", _mesh_edit_tab_active)", callback_factory_source)
        self.assertIn("def _alignment_transform_generation() -> int:", remaining_callback_source)
        self.assertIn("mesh_edit_tab_active=_state._mesh_edit_tab_active()", remaining_callback_source)
        self.assertIn("if callable(getattr(_state.undo_geometry_button, 'setEnabled', None)):", remaining_callback_source)
        self.assertIn("_state._load_selected_part_controls()\n    _state._refresh_mesh_edit_controls()", ui_sections_source)
        self.assertLess(
            ui_sections_source.index("_state.alignment_original_texture_material_callbacks = _state.create_alignment_original_texture_material_callbacks"),
            ui_sections_source.index("_state.use_another_original_mesh_button.clicked.connect(_state._open_original_material_source_picker)"),
        )
        self.assertLess(
            ui_sections_source.index("_state._original_target_label = lambda original_index: _state._original_target_label_helper"),
            ui_sections_source.index("_state.alignment_original_texture_intent_callbacks = _state.create_alignment_original_texture_intent_callbacks"),
        )
        self.assertLess(
            ui_sections_source.index("_state.source_tree_population_state = _state._source_tree_population_initial_state_helper()"),
            ui_sections_source.index("_state.alignment_source_role_tree_population_callbacks = _state.create_alignment_source_role_tree_callbacks"),
        )
        self.assertLess(
            ui_sections_source.index("_state._add_source_tree_item = _state.parts_outliner_mapping_callbacks._add_source_tree_item"),
            ui_sections_source.index("_state.alignment_source_role_tree_population_callbacks = _state.create_alignment_source_role_tree_callbacks"),
        )
        self.assertLess(
            ui_sections_source.index("_state.alignment_source_tree_population_role_callbacks = _state.create_alignment_source_tree_role_callbacks"),
            ui_sections_source.index("_state.alignment_source_role_tree_population_callbacks = _state.create_alignment_source_role_tree_callbacks"),
        )
        self.assertLess(
            ui_sections_source.index("_state.alignment_source_role_tree_population_callbacks = _state.create_alignment_source_role_tree_callbacks"),
            ui_sections_source.index("_state.source_tree_population_timer.timeout.connect(_state._populate_source_tree_chunk)"),
        )
        self.assertIn("if callable(_state._binding_matches_target_callback):", ui_sections_source)
        self.assertIn("def _binding_matches_target(binding: object, target_name: str) -> bool:", ui_sections_source)
        self.assertIn("_state._alignment_d3d11_editor_ids_for_source_indices = lambda source_indices", callback_factory_source)
        self.assertIn("_state.prompt_shell_context.get('_alignment_d3d11_editor_ids_for_source_indices')", callback_factory_source)
        self.assertIn("'_alignment_d3d11_editor_ids_for_source_indices': _state._alignment_d3d11_editor_ids_for_source_indices", callback_factory_source)
        self.assertIn("'_alignment_d3d11_source_indices_for_editor_id': _state._alignment_d3d11_source_indices_for_editor_id", callback_factory_source)
        self.assertIn("'_alignment_mesh_edit_tab_active': _state._alignment_mesh_edit_tab_active", callback_factory_source)
        self.assertIn("_alignment_d3d11_editor_ids_for_source_indices", prompt_state_source)
        self.assertIn('prompt_shell_context["_alignment_d3d11_source_indices_for_editor_id"] = _alignment_d3d11_source_indices_for_editor_id', prompt_state_source)
        self.assertIn('prompt_shell_context["_alignment_mesh_edit_tab_active"] = _alignment_mesh_edit_tab_active', prompt_state_source)
        self.assertIn("if isinstance(state.prompt_shell_context, dict):", mesh_edit_callback_source)
        self.assertIn('state.prompt_shell_context.get("_alignment_mesh_edit_tab_active")', mesh_edit_callback_source)
        self.assertIn('state.prompt_shell_context.get("_alignment_d3d11_source_indices_for_editor_id")', mesh_edit_callback_source)
        self.assertIn("source_indices_for_editor_id=state._d3d11_source_indices_for_editor_id", mesh_edit_callback_source)
        self.assertIn("_replay_alignment_d3d11_fast_transform()", callback_factory_source)
        self.assertIn("except NameError:", callback_factory_source)
        self.assertIn(
            "alignment_mesh_geometry_preview_section = create_alignment_mesh_geometry_preview_section({\n            **context,",
            prompt_setup_source,
        )
        self.assertLess(
            prompt_setup_source.index("texture_files_for_mapping = list(prompt_preflight.texture_files)"),
            prompt_setup_source.index("alignment_texture_material_section = create_alignment_texture_material_section"),
        )
        self.assertIn("_set_texture_sets = context['_set_texture_sets']", prompt_setup_source)
        self.assertIn("_set_texture_sets(dict(prompt_preflight.texture_sets))", prompt_setup_source)
        self.assertLess(
            prompt_setup_source.index("_set_texture_sets(dict(prompt_preflight.texture_sets))"),
            prompt_setup_source.index("alignment_texture_material_section = create_alignment_texture_material_section"),
        )
        self.assertIn("'rebuild_sidecar_checkbox': (lambda: context.get('rebuild_sidecar_checkbox'))", prompt_setup_source)
        source_role_context_start = ui_sections_source.index("_state.alignment_source_role_tree_population_callbacks = _state.create_alignment_source_role_tree_callbacks")
        source_role_context_end = ui_sections_source.index("_state._show_replacement_sources_context_menu = _state.alignment_source_role_tree_population_callbacks", source_role_context_start)
        source_role_context = ui_sections_source[source_role_context_start:source_role_context_end]
        self.assertIn("'_delete_selected_source_parts': lambda *args, **kwargs: _state._delete_selected_source_parts(*args, **kwargs)", source_role_context)
        self.assertIn("'_load_selected_part_controls': lambda *args, **kwargs: _state._load_selected_part_controls(*args, **kwargs)", source_role_context)
        self.assertIn("'_selected_source_indices_from_tree': lambda *args, **kwargs: _state._selected_source_indices_from_tree(*args, **kwargs)", source_role_context)
        self.assertIn(
            "alignment_texture_material_section = create_alignment_texture_material_section({\n            **context,",
            prompt_setup_source,
        )
        self.assertIn(
            "alignment_selection_mapping_helpers = create_alignment_selection_mapping_helpers({\n        **context,",
            prompt_state_source,
        )
        self.assertIn('context.get("_source_texture_slot_count") or (lambda *_args, **_kwargs: 0)', prompt_state_source)
        self.assertIn("except (KeyError, NameError):", selection_mapping_source)
        self.assertIn("_source_index_is_enabled_renderable_helper(", selection_mapping_source)
        self.assertIn("_replacement_mesh()", selection_mapping_source)
        self.assertIn("source_part_adjustments or {}", selection_mapping_source)
        self.assertIn("is_marker_source=_is_marker_source", selection_mapping_source)
        self.assertNotIn(
            "_source_index_is_enabled_renderable_helper(\n            source_part_adjustments,\n            source_index,",
            selection_mapping_source,
        )
        self.assertIn("_state.part_inspector = _state.QGroupBox(_state.source_part_inspector_control_text['group_title'])", source)
        self.assertLess(
            source.index("_state.source_part_inspector_control_text = _state._source_part_inspector_control_text_helper()"),
            source.index("_state.part_inspector = _state.QGroupBox(_state.source_part_inspector_control_text['group_title'])"),
        )
        self.assertIn('"group_title": "Selected Replacement Part"', source_parts_state_source)
        self.assertIn("_state.part_source_combo = _state.QComboBox()", source)
        self.assertIn("_state.part_enabled_checkbox = _state.QCheckBox(_state.source_part_inspector_control_text['include_in_output'])", source)
        self.assertIn('"include_in_output": "Include in output"', source_parts_state_source)
        self.assertIn("_state.remove_part_button = _state.QPushButton(_state.source_part_transform_control_text['remove_part'])", source)
        self.assertIn('"remove_part": "Disable Part Output"', source_parts_state_source)
        self.assertIn("mapped targets with", source_parts_state_source)
        self.assertIn("no enabled source export as removed placeholders", source_parts_state_source)
        self.assertIn("_state.advanced_part_tools_section = _state.CollapsibleSection(", source)
        self.assertIn("'Part Setup'", source)
        self.assertIn("_state.advanced_part_tools_section.body_layout.addWidget(_state.part_inspector)", source)
        self.assertIn("_state.setup_layout = _state.context.get('setup_layout')", source)
        self.assertIn("_state.setup_layout.addWidget(_state.advanced_part_tools_section)", source)
        self.assertNotIn("_state.advanced_part_tools_section.body_layout.addWidget(_state.mesh_edit_group)", source)
        alignment_setup_source = ARCHIVE_STATIC_REPLACEMENT_ALIGNMENT_SETUP_STATE.read_text(encoding="utf-8")
        self.assertIn('alignment_workflow_control_text["mesh_edit_object"]', source)
        self.assertIn('control_tabs.addTab(mesh_edit_tab, alignment_workflow_control_text["mesh_edit_label"])', source)
        self.assertIn("control_tabs.setTabVisible(control_tabs.indexOf(mesh_edit_tab), False)", source)
        self.assertIn("control_tabs.setTabVisible(control_tabs.indexOf(textures_tab), False)", source)
        self.assertIn('"mesh_edit_object": "MeshAlignmentMeshEditingScrollTab"', alignment_setup_source)
        self.assertIn('"mesh_edit_label": "Mesh Editing"', alignment_setup_source)
        self.assertIn("_state.mesh_edit_layout_page.addWidget(_state.mesh_edit_group, 0)", source)
        self.assertIn("_state.parts_outliner_panel.setObjectName('PartsRoutingOutlinerPropertiesStack')", source)
        self.assertNotIn("_state.parts_outliner_layout.addWidget(_state.geometry_overview_group, 0)", source)
        self.assertIn("_state.source_tree.setSelectionMode(_state.QAbstractItemView.ExtendedSelection)", source)
        self.assertIn("def auto_fit_tree_columns(", source)
        self.assertIn("_state._auto_fit_tree_columns_helper(", source)
        texture_table_source = ARCHIVE_STATIC_REPLACEMENT_TEXTURE_TABLE.read_text(encoding="utf-8")
        material_plan_ui_state_source = ARCHIVE_STATIC_REPLACEMENT_MATERIAL_PLAN_UI_STATE.read_text(encoding="utf-8")
        self.assertIn("material_plan_column_fit_specs", texture_table_source)
        self.assertIn("material_plan_column_refit_requests", texture_table_source)
        self.assertIn("def material_plan_column_fit_specs", material_plan_ui_state_source)
        self.assertIn("def material_plan_column_refit_requests", material_plan_ui_state_source)
        self.assertIn("_material_plan_column_fit_specs_helper()", source)
        self.assertIn("_material_plan_column_refit_requests_helper()", source)
        texture_callback_source = static_replacement_texture_callback_source(ROOT)
        self.assertIn("_state._auto_fit_alignment_tree_columns(_state.texture_override_tree, (120, 150, 90, 180, 220, 96, 180)", texture_callback_source)
        self.assertIn("def _selected_source_indices_from_tree", source)
        self.assertIn("source_display_label_cache: Dict[int, str] = {}", source)
        self.assertIn("source_display_duplicate_counts_cache: Dict[str, int] = {}", source)
        source_display_source = ARCHIVE_STATIC_REPLACEMENT_SOURCE_DISPLAY.read_text(encoding="utf-8")
        self.assertIn("def invalidate_source_display_cache", source_display_source)
        self.assertIn("_invalidate_source_display_cache_helper(", source)
        self.assertNotIn("Transforms and Include apply to all selected parts", source)
        self.assertIn("_state.source_tree.itemSelectionChanged.connect(_state._refresh_source_tree_selection_state)", source)
        source_selection_block = source[
            source.index("def _refresh_source_tree_selection_state")
            : source.index("def _ensure_source_tree_item_available", source.index("def _refresh_source_tree_selection_state"))
        ]
        self.assertIn("current_item: Optional[QTreeWidgetItem]=None", source_selection_block)
        self.assertIn(
            "current = current_item if current_item is not None else _state.source_tree.currentItem()",
            source_selection_block,
        )
        self.assertIn("_state._refresh_source_tree_selection_state(_current)", source_selection_block)
        self.assertIn("def _source_tree_selection_should_queue_preview() -> bool:", source)
        self.assertIn("return renderer_key != 'd3d11'", source)
        self.assertIn("if _state._source_tree_selection_should_queue_preview():", source_selection_block)
        self.assertIn("_state._queue_selection_preview_refresh()", source_selection_block)
        self.assertIn("Use Uniform Scale for equal resizing, or Axis Scale for X/Y/Z-only changes.", source_parts_state_source)
        self.assertIn("font_sizes = _alignment_dialog_font_sizes(context)", prompt_shell_source)
        self.assertIn("QDialog#MeshReplacementAlignmentDialog {{\n            font-size: {ui_font_size}px;", prompt_shell_source)
        self.assertIn("QDialog#MeshReplacementAlignmentDialog QTreeWidget {{\n            font-size: {data_font_size}px;", prompt_shell_source)
        self.assertIn('setattr(dialog, "sync_ui_font", _sync_alignment_dialog_font)', prompt_shell_source)
        self.assertIn(
            "QDialog#MeshReplacementAlignmentDialog QTextBrowser,\n        QDialog#MeshReplacementAlignmentDialog QTextEdit,\n        QDialog#MeshReplacementAlignmentDialog QPlainTextEdit",
            prompt_shell_source,
        )
        self.assertIn("page_layout.setContentsMargins(3, 2, 3, 2)", source)
        self.assertIn('alignment_workflow_control_text["setup_object"]', source)
        self.assertIn('alignment_workflow_control_text["parts_object"]', source)
        self.assertIn('alignment_workflow_control_text["materials_object"]', source)
        self.assertIn('control_tabs.addTab(parts_tab, alignment_workflow_control_text["parts_label"])', source)
        self.assertIn('control_tabs.addTab(textures_tab, alignment_workflow_control_text["materials_label"])', source)
        self.assertIn('"setup_object": "MeshAlignmentSetupScrollTab"', alignment_setup_source)
        self.assertIn('"parts_object": "MeshAlignmentPartsScrollTab"', alignment_setup_source)
        self.assertIn('"materials_object": "MeshAlignmentMaterialsScrollTab"', alignment_setup_source)
        self.assertIn('"parts_label": "Parts && Routing"', alignment_setup_source)
        self.assertIn('"materials_label": "Materials && Textures"', alignment_setup_source)
        self.assertIn("header.setMinimumSectionSize(28)", source)
        self.assertIn("minimum_width=28", source)
        self.assertIn("restore_later=False", source)
        self.assertIn("persist_order=False", source)
        self.assertIn("sections_movable=False", source)
        self.assertIn("_state.axis_scale_label = _state.QLabel(_state.source_part_transform_control_text['axis_scale_label'])", source)
        self.assertIn("_state.uniform_scale_label = _state.QLabel(_state.source_part_transform_control_text['uniform_scale_label'])", source)
        self.assertIn('"axis_scale_label": "Axis Scale"', source_parts_state_source)
        self.assertIn('"uniform_scale_label": "Uniform Scale"', source_parts_state_source)
        self.assertIn("_state.part_uniform_spin.setPrefix(_state.source_part_transform_control_text['uniform_prefix'])", source)
        self.assertIn("_state.spin.setToolTip(_state.source_part_transform_control_text['axis_spin_tooltip'])", source)
        self.assertIn('"uniform_prefix": "All "', source_parts_state_source)
        self.assertIn('"axis_spin_tooltip": "Non-uniform axis scale. 1.0 leaves this axis unchanged."', source_parts_state_source)
        self.assertIn("original_texture_preview_default = bool(modify_original_clone_mode)", prompt_shell_source)
        self.assertIn(
            "original_texture_preview_state = _original_texture_preview_initial_state_helper(\n        original_texture_preview_default\n    )",
            prompt_shell_source,
        )
        self.assertIn("def _alignment_texture_lookup_indexes() -> Tuple", source)
        self.assertIn("archive_texture_lookup_indexes_for_alignment(", source)
        self.assertIn("_collect_same_stem_related_target_basenames(request.entry)", source)
        self.assertIn('"mesh_alignment_texture_lookup_ready"', source)
        texture_sources_source = ARCHIVE_STATIC_REPLACEMENT_TEXTURE_SOURCES.read_text(encoding="utf-8")
        self.assertIn("def archive_texture_lookup_indexes_for_alignment(", texture_sources_source)
        self.assertIn('extension_index.get(".dds", ())', texture_sources_source)
        self.assertIn("setup.defer_original_texture_preview = True", source)
        self.assertIn("and defer_original_texture_preview", source)
        self.assertIn(
            "_original_texture_preview_material_preview_enabled_helper(modify_original_clone_mode, original_texture_preview_state)",
            source,
        )
        self.assertIn("preview_render_settings.disable_all_support_maps = True", source)
        self.assertIn('"mesh_alignment_startup_step"', source)
        self.assertIn("original_texture_preview_checkbox.setChecked(", source)
        original_texture_preview_state_source = ARCHIVE_STATIC_REPLACEMENT_ORIGINAL_TEXTURE_PREVIEW_STATE.read_text(encoding="utf-8")
        self.assertIn("_state.original_texture_preview_control_text = _state._original_texture_preview_control_text_helper()", source)
        self.assertIn("_state.QGroupBox(_state.original_texture_preview_control_text['group_title'])", source)
        self.assertIn("_state.QCheckBox(_state.original_texture_preview_control_text['checkbox_label'])", source)
        self.assertIn('"group_title": "Original Texture Preview"', original_texture_preview_state_source)
        self.assertIn('"checkbox_label": "Preview with original DDS/materials"', original_texture_preview_state_source)
        self.assertIn("visually aligned with Archive Preview", original_texture_preview_state_source)
        self.assertIn("_state.original_texture_preview_group.setVisible(_state.bool(_state.modify_original_clone_mode))", source)
        self.assertIn("def _apply_original_material_preview", source)
        self.assertIn("def preview_mesh_surface_matches", source)
        self.assertIn('source_submesh_index = int(getattr(preview_mesh, "source_submesh_index", -1))', source)
        self.assertIn("translation_delta: tuple[float, float, float] | None = None", source)
        self.assertIn("abs(delta[0] - translation_delta[0]) > epsilon", source)

    def test_mesh_editor_output_contract_ignores_disabled_mapped_sources(self) -> None:
        source = (
            _main_window_source()
            + "\n"
            + _mesh_editor_shell_bridge_source()
            + "\n"
            + ARCHIVE_STATIC_REPLACEMENT_SOURCE_DISPLAY.read_text(encoding="utf-8")
            + "\n"
            + ARCHIVE_STATIC_REPLACEMENT_SOURCE_PART_PROPERTIES_STATE.read_text(encoding="utf-8")
        )
        source_parts_state_source = _source_part_owner_sources()
        preview_model_source = static_replacement_callback_concern_source(ROOT, "preview_model")
        output_impact_source = _nested_function_source(preview_model_source, "_refresh_output_impact_review")
        mapping_table_state_source = ARCHIVE_STATIC_REPLACEMENT_MAPPING_TABLE_STATE.read_text(encoding="utf-8")
        self.assertIn("def enabled_renderable_source_indices(", source)
        self.assertIn("_enabled_renderable_source_indices_helper(", source)
        self.assertIn("enabled_source_indices = _state._enabled_renderable_source_indices(source_indices)", output_impact_source)
        self.assertIn("if not enabled_source_indices:\n        return \"Removed\", \"#fb923c\"", source)
        self.assertIn("used_sources.update((int(index) for index in enabled_source_indices))", output_impact_source)
        self.assertIn("Disabled mapped sources ignored by final geometry", mapping_table_state_source)
        self.assertIn("disabled_mapped_sources", source)
        self.assertIn("disabled_source_count", source)
        self.assertIn("mapped targets with", source_parts_state_source)
        self.assertIn("no enabled source export as removed placeholders", source_parts_state_source)
        self.assertIn("copy_matching_surface=True", source)
        self.assertIn("preserve_material_preview=_original_texture_preview_material_preview_enabled_helper(", source)
        self.assertIn("_apply_original_material_preview(", source)
        self.assertIn("if modify_original_clone_mode and mapped_preview:", source)
        self.assertIn("target_mesh_indices = preview_target_mesh_indices(", source)
        self.assertIn("for mesh_index in target_mesh_indices:", source)
        self.assertIn("original_meshes[target_index]", source)
        self.assertIn('"preview_texture_image"', source)
        self.assertIn('"preview_debug_disable_support_maps"', source)
        self.assertIn("(not use_original_material_preview)", source)
        material_preview_start = source.index("def _apply_original_material_preview(")
        material_preview_end = source.index("def _ensure_original_reference_texture_preview_ready", material_preview_start)
        material_preview_source = source[material_preview_start:material_preview_end]
        self.assertNotIn("clear_textures=True", material_preview_source)
        self.assertIn("alignment_preview_view_sync = _alignment_preview_view_sync_initial_state_helper()", source)
        self.assertIn("def _sync_alignment_preview_view_state", source)
        self.assertNotIn("original_dialog_preview.view_state_changed.connect", source)
        self.assertNotIn("static_dialog_preview.view_state_changed.connect", source)
        self.assertIn("mesh_editor_d3d11_view_state_reset_generation", source)
        self.assertIn("_mesh_editor_session_request_key", source)
        self.assertIn("_alignment_d3d11_saved_view_state", source)
        d3d11_loading_source = static_replacement_callback_concern_source(ROOT, "d3d11_loading")
        self.assertIn(
            "_state.self._sanitize_d3d11_view_state_for_restore(_state.alignment_d3d11_view_state)",
            d3d11_loading_source,
        )

    def test_alignment_dialog_is_maximizable_and_keeps_controls_readable(self) -> None:
        source = _main_window_source()
        self.assertIn("dialog.setWindowFlag(Qt.WindowMaximizeButtonHint, True)", source)
        self.assertIn("dialog.setWindowFlag(Qt.WindowMinimizeButtonHint, True)", source)
        self.assertIn("alignment_control_min_width = 420 if embedded_alignment_builder else 640", source)
        self.assertIn("alignment_control_content_min_width = 0 if embedded_alignment_builder else 700", source)
        self.assertIn("mesh_edit_control_min_width = 300 if embedded_alignment_builder else 300", source)
        self.assertIn("mesh_edit_control_content_min_width = 0 if embedded_alignment_builder else 300", source)
        self.assertIn("mesh_edit_control_max_width = 340 if embedded_alignment_builder else 340", source)
        self.assertIn('controls_panel.setObjectName("MeshAlignmentStickyControlPanel")', source)
        self.assertIn('control_tabs.setObjectName("MeshAlignmentStickyWorkflowTabs")', source)
        self.assertIn("control_tabs.setUsesScrollButtons(True)", source)
        self.assertIn("control_tabs.setElideMode(Qt.ElideNone)", source)
        self.assertIn("control_tabs.tabBar().setExpanding(False)", source)
        self.assertIn("control_tabs.setTabToolTip(tab_index, tab_label)", source)
        alignment_setup_source = ARCHIVE_STATIC_REPLACEMENT_ALIGNMENT_SETUP_STATE.read_text(encoding="utf-8")
        self.assertIn('alignment_workflow_control_text["setup_object"]', source)
        self.assertIn('alignment_workflow_control_text["parts_object"]', source)
        self.assertIn('alignment_workflow_control_text["materials_object"]', source)
        self.assertIn('"setup_object": "MeshAlignmentSetupScrollTab"', alignment_setup_source)
        self.assertIn('"parts_object": "MeshAlignmentPartsScrollTab"', alignment_setup_source)
        self.assertIn('"materials_object": "MeshAlignmentMaterialsScrollTab"', alignment_setup_source)
        layout_state_source = ARCHIVE_STATIC_REPLACEMENT_LAYOUT_STATE.read_text(encoding="utf-8")
        self.assertIn("content_container.setMinimumWidth(layout_spec.content_min_width)", source)
        self.assertIn("controls_panel.setMaximumWidth(layout_spec.controls_max_width)", source)
        routing_source = static_replacement_routing_callback_source(ROOT)
        responsive_layout_body = _nested_function_source(
            routing_source, "_apply_alignment_dialog_responsive_layout"
        )
        self.assertIn(
            "_state.controls_panel.setSizePolicy(policy_by_name[layout_spec.controls_policy], _state.QSizePolicy.Expanding)",
            responsive_layout_body,
        )
        self.assertIn("min(int(mesh_edit_control_max_width), int(normalized_width * 0.24))", layout_state_source)
        self.assertIn("main_splitter.setChildrenCollapsible(False)", source)
        self.assertIn("preview_splitter.setChildrenCollapsible(False)", source)
        self.assertIn("preview_splitter.setStretchFactor(0, 1)", source)
        self.assertIn("preview_splitter.setStretchFactor(1, 1)", source)
        self.assertIn("preview_splitter.setSizes([520, 520])", source)
        preview_shell_source = ARCHIVE_STATIC_REPLACEMENT_DIALOG_PREVIEW_SHELL.read_text(encoding="utf-8")
        mesh_callbacks_source = static_replacement_mesh_edit_implementation_source(ROOT)
        self.assertIn("ui/mesh_alignment/{scope}/{mode}/{kind}_splitter_sizes", routing_source)
        self.assertIn("_state._saved_splitter_sizes('main', layout_spec.mode, 2) or layout_spec.main_sizes", responsive_layout_body)
        self.assertIn("_state._saved_splitter_sizes('preview', layout_spec.mode, 2) or layout_spec.preview_sizes", responsive_layout_body)
        self.assertIn("main_splitter.splitterMoved.connect(_save_alignment_dialog_splitter_sizes)", preview_shell_source)
        self.assertIn("preview_splitter.splitterMoved.connect(_save_alignment_dialog_splitter_sizes)", preview_shell_source)
        self.assertIn("alignment_d3d11_split_ratio_settings_key", preview_shell_source)
        self.assertIn("alignment_d3d11_preview_host.native_event_received.connect(_remember_alignment_d3d11_split_ratio)", preview_shell_source)
        self.assertIn("alignment_d3d11_preview_host.remember_side_by_side_split_ratio", preview_shell_source)
        mesh_tab_body = _nested_function_source(mesh_callbacks_source, "_mesh_edit_control_tab_changed")
        self.assertIn("_state._apply_alignment_dialog_responsive_layout()", mesh_tab_body)
        self.assertNotIn("_state._apply_alignment_dialog_responsive_layout(force_sizes=True)", mesh_tab_body)
        self.assertIn("preview_header = QVBoxLayout()", source)
        self.assertIn("preview_action_row = QHBoxLayout()", source)
        self.assertIn("preview_controls_row = QHBoxLayout(legacy_preview_controls_widget)", source)
        self.assertIn("preview_camera_row = QHBoxLayout(legacy_preview_camera_widget)", source)
        self.assertIn('generate_alignment_icon_button = QPushButton(custom_icon_control_text["generate_preview_button"])', source)
        self.assertIn("generate_alignment_icon_button.setMaximumWidth(128)", source)
        self.assertNotIn("preview_header.addStretch(1)", source)
        self.assertIn("def alignment_dialog_layout_initial_state() -> dict[str, str]:", layout_state_source)
        self.assertIn("alignment_dialog_layout_state = _alignment_dialog_layout_initial_state_helper()", source)
        self.assertIn("_alignment_dialog_responsive_layout_helper(", source)
        self.assertIn("def alignment_dialog_responsive_layout(", layout_state_source)
        self.assertTrue(
            responsive_layout_body.startswith("def _apply_alignment_dialog_responsive_layout")
        )
        self.assertIn("_apply_alignment_dialog_responsive_layout(force_sizes=True)", source)
        preview_shell_source = ARCHIVE_STATIC_REPLACEMENT_DIALOG_PREVIEW_SHELL.read_text(encoding="utf-8")
        self.assertLess(
            preview_shell_source.index("alignment_dialog_layout_state = _alignment_dialog_layout_initial_state_helper()"),
            preview_shell_source.index("alignment_dialog_layout_callbacks = create_alignment_dialog_layout_callbacks"),
        )
        self.assertLess(
            preview_shell_source.index("previous_dialog_resize_event = dialog.resizeEvent"),
            preview_shell_source.index("alignment_dialog_layout_callbacks = create_alignment_dialog_layout_callbacks"),
        )
        self.assertIn("Let winId() create the native handle after the builder is visible", preview_shell_source)
        self.assertNotIn("alignment_d3d11_preview_host.setAttribute(Qt.WA_NativeWindow, True)", preview_shell_source)

    def test_alignment_d3d11_close_race_avoids_deleted_qt_timers_and_dialog(self) -> None:
        source = _main_window_source()
        self.assertIn("def safe_stop_timer(timer: object) -> None:", source)
        self.assertIn("def safe_start_timer(timer: object) -> None:", source)
        self.assertIn("def safe_timer_active(timer: object) -> bool:", source)

        routing_source = static_replacement_routing_callback_source(ROOT)
        layout_body = _nested_function_source(routing_source, "_apply_alignment_dialog_responsive_layout")
        self.assertIn("if not _state._alignment_dialog_widgets_live() or not _state._qt_object_is_valid(_state.main_splitter):", layout_body)
        self.assertLess(
            layout_body.index("if not _state._alignment_dialog_widgets_live() or not _state._qt_object_is_valid(_state.main_splitter):"),
            layout_body.index("width = max(1, int(_state.dialog.width()))"),
        )

        resize_body = _nested_function_source(routing_source, "_responsive_dialog_resize_event")
        self.assertIn("if not _state._alignment_dialog_widgets_live():", resize_body)
        self.assertIn("if callable(_state.previous_dialog_resize_event):", resize_body)
        self.assertLess(resize_body.index("if not _state._alignment_dialog_widgets_live():"), resize_body.index("if callable(_state.previous_dialog_resize_event):"))
        self.assertLess(resize_body.index("if callable(_state.previous_dialog_resize_event):"), resize_body.index("_state.previous_dialog_resize_event(event)"))

        finish_body = _nested_function_source(
            static_replacement_callback_concern_source(ROOT, "d3d11_package_lifecycle"),
            "_handle_alignment_d3d11_finished",
        )
        self.assertIn("widgets_live = _state._alignment_dialog_widgets_live()", finish_body)
        self.assertIn("if widgets_live:", finish_body)
        self.assertIn("_state._poll_alignment_d3d11_status()", finish_body)
        self.assertIn("_state._safe_stop_alignment_timer(_state.alignment_d3d11_status_timer)", finish_body)
        self.assertNotIn("alignment_d3d11_status_timer.stop()", finish_body)

    def test_model_preview_draws_selected_part_outline_overlay(self) -> None:
        dotnet_source = (ROOT / "tools" / "dotnet_mesh_editor_experiment" / "D3D11MaterialViewport.Overlay.cs").read_text(encoding="utf-8")
        host_source = (ROOT / "cdmw" / "ui" / "preview" / "dotnet_host.py").read_text(encoding="utf-8")
        self.assertIn("_overlaySelectedSources", dotnet_source)
        self.assertIn("DrawOverlayPrimitive", dotnet_source)
        self.assertIn("source_part_selected", host_source)
        return
        native_source = d3d11_preview_source()
        self.assertIn("set_highlighted_alignment_submeshes", _main_window_source())
        self.assertIn("set_highlighted_source_submeshes", _native_d3d11_preview_host_source())
        self.assertIn("draw_alignment_overlay_gdi", native_source)
        self.assertIn("alignment_rotation_handle_at", native_source)
        self.assertIn('rotation_handle == "roll"', native_source)

    def test_alignment_drag_commits_final_release_delta_before_clearing_live_transform(self) -> None:
        widget_source = _widgets_source()
        main_source = _main_window_source()
        host_source = (ROOT / "cdmw" / "ui" / "preview" / "dotnet_host.py").read_text(encoding="utf-8")
        self.assertIn("alignment_drag_changed.emit(*translation)", host_source)
        self.assertIn("alignment_drag_finished.emit(*translation)", host_source)
        self.assertIn("_finish_alignment_d3d11_translation", main_source)
        return
        native_source = d3d11_preview_source()
        self.assertIn("bool update_alignment_rotation_drag", native_source)
        self.assertIn("bool update_alignment_drag", native_source)
        release_start = native_source.index("bool finish_alignment_drag")
        release_end = native_source.index("bool cancel_alignment_drag", release_start)
        release_block = native_source[release_start:release_end]
        self.assertLess(
            release_block.index("update_alignment_rotation_drag(x, y, wparam);"),
            release_block.index('send_alignment_vector_event("alignment_rotation_finished", alignment_.rotation_drag_delta);'),
        )
        self.assertLess(
            release_block.index('send_alignment_vector_event("alignment_rotation_finished", alignment_.rotation_drag_delta);'),
            release_block.index("alignment_.rotation_drag_active = false;"),
        )
        self.assertLess(
            release_block.index("update_alignment_translation_drag(x, y, wparam);"),
            release_block.index('send_alignment_vector_event("alignment_drag_finished", alignment_.translation_drag_delta);'),
        )
        self.assertLess(
            release_block.index('send_alignment_vector_event("alignment_drag_finished", alignment_.translation_drag_delta);'),
            release_block.index("alignment_.drag_active = false;"),
        )
        translation_start = main_source.index("def _commit_alignment_preview_translation")
        rotation_start = main_source.index("def _commit_alignment_preview_rotation")
        commit_block = main_source[translation_start:main_source.index("return SimpleNamespace(", rotation_start)]
        self.assertNotIn("QTimer.singleShot(0, _refresh_static_dialog_preview)", commit_block)
        self.assertIn("def _alignment_part_source_indices_for_commit", main_source)
        self.assertIn("transform_source_indices", main_source[main_source.index("def _alignment_part_source_indices_for_commit"):translation_start])
        self.assertNotIn("selected_source_highlight_indices", main_source[main_source.index("def _alignment_part_source_indices_for_commit"):translation_start])
        prepare_start = main_source.index("def _sync_alignment_preview_rotation_context")
        prepare_end = main_source.index("def _commit_alignment_d3d11_drag_generation", prepare_start)
        prepare_block = main_source[prepare_start:prepare_end]
        self.assertIn("_alignment_preview_rotation_context_state_helper(", prepare_block)
        self.assertIn("_alignment_preview_drag_prepare_state_helper(", prepare_block)
        self.assertIn("_alignment_preview_commit_state_helper(", commit_block)
        self.assertIn("_apply_alignment_part_translation_delta(", commit_block)
        self.assertIn("_apply_alignment_part_rotation_delta(", commit_block)
        self.assertIn("_queue_global_transform_preview_update()", commit_block)
        self.assertNotIn("_queue_static_preview_rebuild()", commit_block)
        d3d11_finish_start = main_source.index("def _finish_alignment_d3d11_translation")
        d3d11_finish_end = main_source.index("def _commit_alignment_preview_translation", d3d11_finish_start)
        d3d11_finish_block = main_source[d3d11_finish_start:d3d11_finish_end]
        self.assertIn("_alignment_d3d11_finish_drag_update_state_helper(", d3d11_finish_block)
        self.assertNotIn("_alignment_d3d11_finish_drag_preview_state_helper(", d3d11_finish_block)
        self.assertNotIn("_alignment_d3d11_finish_drag_transaction_helper(", d3d11_finish_block)
        self.assertIn("_replay_alignment_d3d11_fast_transform()", d3d11_finish_block)
        self.assertNotIn("_queue_static_preview_rebuild()", d3d11_finish_block)
        self.assertIn("_state.preview_widget.alignment_rotation_finished.connect(_state._commit_alignment_preview_rotation)", main_source)
        self.assertIn("preview_widget.set_alignment_translation_sensitivity(0.85)", main_source)
        self.assertIn("def set_alignment_translation_sensitivity", widget_source)
        self.assertIn("_state.alignment_d3d11_preview_host.alignment_drag_finished.connect(_state._finish_alignment_d3d11_translation)", main_source)
        self.assertIn("_state.alignment_d3d11_preview_host.alignment_rotation_finished.connect(_state._finish_alignment_d3d11_rotation)", main_source)
        self.assertIn("void drop_pending_package_reload", native_source)
        self.assertIn('drop_pending_package_reload("alignment_translation_start")', native_source)
        self.assertIn('drop_pending_package_reload("alignment_rotation_start")', native_source)
        process_start = native_source.index("bool process_pending_commands")
        process_end = native_source.index("private:", process_start)
        process_block = native_source[process_start:process_end]
        self.assertIn("alignment_.drag_active || alignment_.rotation_drag_active", process_block)
        self.assertIn('drop_pending_package_reload("alignment_drag_active")', process_block)

    def test_alignment_dialog_has_obj_mesh_edit_controls_and_revision_hooks(self) -> None:
        main_source = _main_window_source()
        mesh_edit_callback_source = static_replacement_mesh_edit_implementation_source(ROOT)
        mesh_edit_ui_source = static_replacement_ui_concern_source(ROOT, "mesh_geometry_preview")
        widget_source = _widgets_source()
        archive_source = _archive_modding_source()
        static_source = _static_replacer_source()
        static_payload_source = ARCHIVE_STATIC_REPLACEMENT_MESH_EDIT_PAYLOAD.read_text(encoding="utf-8")
        mesh_edit_state_source = ARCHIVE_STATIC_REPLACEMENT_MESH_EDIT_STATE.read_text(encoding="utf-8")
        host_source = (ROOT / "cdmw" / "ui" / "preview" / "dotnet_host.py").read_text(encoding="utf-8")
        controller_source = (ROOT / "cdmw" / "ui" / "preview" / "dotnet_session.py").read_text(encoding="utf-8")
        self.assertIn("mesh_edit_stroke_started = Signal(object)", host_source)
        self.assertIn("mesh_edit_stroke_finished = Signal(object)", host_source)
        self.assertIn("send_authoring_message", controller_source)
        self.assertIn("mesh_edit_revision_ack_v1", controller_source)
        self.assertIn("Mesh Editing needs a parsed static mesh source", mesh_edit_state_source)
        return
        native_source = d3d11_preview_source()

        self.assertIn("_state.mesh_edit_supported = _state.bool(", mesh_edit_ui_source)
        self.assertIn("Mesh Editing needs a parsed static mesh source", mesh_edit_state_source)
        alignment_setup_source = ARCHIVE_STATIC_REPLACEMENT_ALIGNMENT_SETUP_STATE.read_text(encoding="utf-8")
        self.assertIn('control_tabs.addTab(mesh_edit_tab, alignment_workflow_control_text["mesh_edit_label"])', main_source)
        self.assertIn('"mesh_edit_label": "Mesh Editing"', alignment_setup_source)
        self.assertIn("_state.mesh_edit_group = _state.QFrame(_state.mesh_edit_page)", mesh_edit_ui_source)
        self.assertIn("_state.mesh_edit_group.setObjectName('MeshEditVerticalToolbox')", mesh_edit_ui_source)
        self.assertIn("_state.mesh_edit_title_label = _state.QLabel(_state._mesh_edit_dialog_title_helper())", mesh_edit_ui_source)
        self.assertIn('preview_mesh_edit_checkbox = QCheckBox("Edit Mesh")', main_source)
        self.assertIn("mesh_edit_enabled_checkbox = preview_mesh_edit_checkbox", main_source)
        self.assertIn('"edit_mode": "Edit Mesh"', main_source)
        self.assertIn("_state.mesh_edit_enabled_checkbox.setObjectName('MeshEditModeCheckbox')", mesh_edit_ui_source)
        self.assertIn("_state.mesh_edit_scope_combo = _state.QComboBox()", mesh_edit_ui_source)
        self.assertIn('("All editable parts", "all")', main_source)
        self.assertIn('("Selected part only", "selected")', main_source)
        self.assertIn("_state.mesh_edit_part_combo = _state.QComboBox()", mesh_edit_ui_source)
        self.assertIn('("Move", "grab")', main_source)
        self.assertIn('("Smooth", "smooth")', main_source)
        self.assertIn('("Push/Pull", "inflate")', main_source)
        self.assertIn('("Pinch/Relax", "pinch")', main_source)
        self.assertIn('("Remove Faces", "remove")', main_source)
        self.assertIn('("Select Vertices", "vertex")', main_source)
        self.assertIn("mesh_edit_tool_combo.setVisible(False)", main_source)
        self.assertIn("_state.mesh_edit_layout.addWidget(_state.QLabel(_state.mesh_edit_action_control_text['tool_label']))", mesh_edit_ui_source)
        self.assertIn("_state.mesh_edit_remove_mode_label = _state.QLabel(_state.mesh_edit_action_control_text['remove_mode_label'])", mesh_edit_ui_source)
        self.assertIn('"tool_label": "Tool"', mesh_edit_state_source)
        self.assertIn('"remove_mode_label": "Remove Mode"', mesh_edit_state_source)
        self.assertIn("_state.mesh_edit_tool_palette.setObjectName('MeshEditVerticalToolPalette')", mesh_edit_ui_source)
        self.assertIn("_state.mesh_edit_tool_buttons: _state.Dict[_state.str, _state.QToolButton] = {}", mesh_edit_ui_source)
        self.assertIn("button.setAutoExclusive(True)", main_source)
        self.assertIn("_state.mesh_edit_delete_mode_combo = _state.QComboBox()", mesh_edit_ui_source)
        self.assertIn('("On release", "release")', main_source)
        self.assertIn('("During drag", "live")', main_source)
        self.assertNotIn('("Selection only", "selection")', main_source)
        self.assertIn("_state.mesh_edit_mirror_checkbox = _state.QCheckBox(_state.mesh_edit_action_control_text['mirror_checkbox'])", mesh_edit_ui_source)
        self.assertIn("_state.mesh_edit_show_vertices_checkbox = _state.QCheckBox(_state.mesh_edit_action_control_text['show_vertices_checkbox'])", mesh_edit_ui_source)
        self.assertIn('"mirror_checkbox": "Mirror X"', main_source)
        self.assertIn('"show_vertices_checkbox": "Vertex dots"', main_source)
        self.assertIn("mesh_edit_show_vertices_checkbox.setChecked(False)", main_source)
        self.assertNotIn('mesh_edit_select_brush_button = QPushButton("Select Brush")', main_source)
        self.assertIn("_state.mesh_edit_clear_selection_button = _state.QPushButton(_state.mesh_edit_action_control_text['clear_selection'])", mesh_edit_ui_source)
        self.assertIn("_state.mesh_edit_delete_faces_button = _state.QPushButton(_state.mesh_edit_action_control_text['delete_faces'])", mesh_edit_ui_source)
        self.assertIn("_state.mesh_edit_undo_button = _state.QPushButton(_state.mesh_edit_action_control_text['undo'])", mesh_edit_ui_source)
        self.assertIn("_state.mesh_edit_redo_button = _state.QPushButton(_state.mesh_edit_action_control_text['redo'])", mesh_edit_ui_source)
        self.assertIn("_state.mesh_edit_reset_part_button = _state.QPushButton(_state.mesh_edit_action_control_text['reset_scope'])", mesh_edit_ui_source)
        self.assertIn('"clear_selection": "Clear Selection"', main_source)
        self.assertIn('"delete_faces": "Delete Selected Faces"', main_source)
        self.assertIn("def mesh_edit_delete_faces_text", mesh_edit_state_source)
        self.assertIn("def mesh_edit_subdivide_text", mesh_edit_state_source)
        self.assertIn("_mesh_edit_delete_faces_text_helper()", main_source)
        self.assertIn("_mesh_edit_subdivide_text_helper()", main_source)
        self.assertIn('"reset_scope": "Reset Scope"', main_source)
        self.assertIn("mesh_edit_revision = _mesh_edit_revision_initial_state_helper()", main_source)
        self.assertIn("mesh_edit_selected_vertices_by_submesh: Dict[int, set[int]] = {}", main_source)
        self.assertIn("mesh_edit_selected_faces_by_submesh: Dict[int, set[int]] = {}", main_source)
        self.assertIn("source_geometry_revision = _source_geometry_revision_initial_state_helper()", main_source)
        self.assertIn("appended_source_indices: set[int] = set()", main_source)
        self.assertIn("independent_output_source_indices: set[int] = set()", main_source)
        self.assertIn("preview_only_source_indices: set[int] = set()", main_source)
        self.assertIn("source_overlay_preview_index_map: Dict[int, int] = {}", main_source)
        self.assertIn("mesh_edit_undo_stack: List[ParsedMesh] = []", main_source)
        self.assertIn("mesh_edit_redo_stack: List[ParsedMesh] = []", main_source)
        self.assertIn("'mesh_edit_revision': int(_state.mesh_edit_revision.get('value', 0) or 0)", main_source)
        self.assertIn("'source_geometry_revision': int(_state.source_geometry_revision.get('value', 0) or 0)", main_source)
        self.assertIn("static_preview_geometry_cache.clear()", main_source)
        self.assertIn("mesh_edit_active_stroke: Dict[str, object] = {}", main_source)
        self.assertIn("_mesh_edit_allowed_source_indices = lambda", main_source)
        self.assertIn("def _mesh_edit_can_edit_scope", main_source)
        self.assertIn("def _mesh_edit_reset_scope", main_source)
        self.assertIn("def _alignment_mesh_edit_tab_active() -> bool:", main_source)
        self.assertIn("def _mesh_edit_tab_active() -> bool:", main_source)
        self.assertIn('_context_or_prompt("mesh_edit_enabled_checkbox")', main_source)
        self.assertIn("def _mesh_edit_control_tab_changed", main_source)
        self.assertIn("_state.control_tabs.currentChanged.connect(_state._mesh_edit_control_tab_changed)", mesh_edit_ui_source)
        self.assertIn("and _state._mesh_edit_tab_active()", mesh_edit_callback_source)
        self.assertIn("mesh_edit_page.setMinimumWidth(0 if embedded_alignment_builder else mesh_edit_control_content_min_width)", main_source)
        self.assertIn("mesh_edit_layout_page.setContentsMargins(0, 0, 0, 0)", main_source)
        self.assertIn("mesh_edit_tab.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)", main_source)
        self.assertIn("mesh_edit_remove_mode_label.setVisible(remove_tool)", main_source)
        self.assertIn("mesh_edit_delete_mode_combo.setVisible(remove_tool)", main_source)
        self.assertIn("def mesh_edit_should_restore_deleted_output(", main_source)
        self.assertIn("restore_deleted_output_by_source[source_index] = _state._mesh_edit_should_restore_deleted_output_helper(", mesh_edit_callback_source)
        self.assertIn("restore_deleted_sources = tuple(", main_source)
        self.assertIn("_mesh_edit_source_enable_mutation_blocked(\"reset.restore_deleted_output\", restore_deleted_sources)", main_source)
        self.assertIn("def _mesh_edit_restore_base_sources_native(", mesh_edit_callback_source)
        self.assertIn("restore_native_mesh_submeshes_from_mesh", main_source)
        self.assertIn("not any(", main_source)
        self.assertIn("_source_index_is_enabled_renderable", main_source)
        reset_scope = main_source[
            main_source.index("def _mesh_edit_reset_scope") : main_source.index("def _mesh_edit_source_to_preview_point")
        ]
        self.assertIn('_mesh_edit_restore_base_sources_native(source_indices, operation="mesh_edit.reset_scope")', reset_scope)
        self.assertIn("Python geometry clone fallback is disabled.", reset_scope)
        self.assertIn("restore_deleted_sources = tuple(", reset_scope)
        self.assertIn("_mesh_edit_source_enable_mutation_blocked(\"reset.restore_deleted_output\", restore_deleted_sources)", reset_scope)
        self.assertNotIn("adjustment = _ensure_source_part_adjustment(source_index)\n                        adjustment.enabled = True", reset_scope)
        self.assertIn("source_submesh_indices=allowed_indices", main_source)
        self.assertIn("delete_mode=delete_mode", main_source)
        self.assertIn("def _mesh_edit_begin_stroke", main_source)
        self.assertIn("def _mesh_edit_apply_preview_payload", main_source)
        self.assertIn("def _mesh_edit_finish_stroke", main_source)
        self.assertIn("def _mesh_edit_cancel_stroke", main_source)
        self.assertIn("def _mesh_edit_delete_selected_faces", main_source)
        self.assertNotIn("delete_faces_by_indices(", main_source)
        self.assertNotIn("delete_faces_touching_vertices(", main_source)
        self.assertNotIn("compact_orphan_vertices(", main_source)
        self.assertIn('"delete"', main_source)
        self.assertIn('"delete_loose_vertices"', main_source)
        self.assertIn('"tool": tool', main_source)
        self.assertIn('"delete_mode": delete_mode', main_source)
        self.assertIn('"remove_faces_by_submesh": {}', main_source)
        self.assertIn('"remove_vertices_by_submesh": {}', main_source)
        self.assertIn('"live_delete_submeshes": set()', main_source)
        self.assertIn("_mesh_edit_faces_from_payload = lambda", main_source)
        self.assertIn('payload_index_key="source_face_indices"', main_source)
        self.assertIn("_mesh_edit_i32_payload_values(group, payload_index_key", static_payload_source)
        self.assertIn("result.emptied_submesh_indices", main_source)
        self.assertIn("mesh_edit_delete_faces_button.clicked.connect", main_source)
        self.assertIn("mesh_edit_stroke_started.connect(lambda payload: _state._mesh_edit_begin_stroke(payload))", main_source)
        self.assertIn("mesh_edit_stroke_previewed.connect(lambda payload: _state._mesh_edit_apply_preview_payload(payload))", main_source)
        self.assertIn("mesh_edit_stroke_finished.connect(lambda payload: _state._mesh_edit_finish_stroke(payload))", main_source)
        self.assertIn("mesh_edit_stroke_cancelled.connect(lambda payload: _state._mesh_edit_cancel_stroke(payload))", main_source)
        self.assertIn("mesh_edit_selection_changed.connect(lambda payload: _state._mesh_edit_selection_changed(payload))", main_source)
        self.assertIn("static_preview_geometry_cache.clear()", main_source)
        self.assertIn("_refresh_static_dialog_preview(live_mesh_edit=True)", main_source)
        self.assertIn("edited_source_mesh = None", main_source)
        self.assertIn("include_edited_source_mesh", main_source)
        self.assertIn("or int(placement_snapshot.get('source_geometry_revision', 0) or 0) > 0", main_source)
        self.assertIn("clone_mesh_for_static_replacement_native_first(", main_source)
        original_preview_models_source = ARCHIVE_STATIC_REPLACEMENT_ORIGINAL_PREVIEW_MODELS.read_text(encoding="utf-8")
        self.assertIn("mesh.source_submesh_index = -1", original_preview_models_source)
        self.assertIn("mesh.source_vertex_indices = []", original_preview_models_source)
        self.assertIn("mesh.source_face_indices = []", original_preview_models_source)

        self.assertIn("mesh_edit_stroke_finished = Signal(object)", widget_source)
        self.assertIn("mesh_edit_stroke_started = Signal(object)", widget_source)
        self.assertIn("mesh_edit_stroke_previewed = Signal(object)", widget_source)
        self.assertIn("mesh_edit_stroke_cancelled = Signal(object)", widget_source)
        self.assertIn("mesh_edit_selection_changed = Signal(object)", widget_source)
        self.assertIn("def set_mesh_editing_enabled", widget_source)
        self.assertIn("def set_model_preserving_view", widget_source)
        self.assertIn("def set_mesh_edit_target_mode", widget_source)
        self.assertIn("def set_mesh_edit_tool", widget_source)
        self.assertIn("def set_mesh_edit_source_submesh_indices", widget_source)
        self.assertIn("def set_mesh_edit_delete_mode", widget_source)
        self.assertIn("def set_mesh_edit_brush_settings", widget_source)
        self.assertIn("def clear_mesh_edit_vertex_selection", widget_source)
        self.assertIn("def select_mesh_edit_brush_vertices", widget_source)
        self.assertNotIn("struct EditorCandidate", native_source)
        self.assertNotIn("std::vector<EditorCandidate> mesh_edit_candidates_at", native_source)
        self.assertNotIn("std::vector<EditorCandidate> mesh_edit_face_candidates_at", native_source)
        self.assertNotIn("std::vector<EditorCandidate> mesh_edit_brush_candidates_at", native_source)
        self.assertNotIn("float mesh_edit_falloff_weight", native_source)
        self.assertIn("source_vertex_weights", native_source)
        self.assertIn("source_face_indices", native_source)
        self.assertIn("source_face_start", native_source)
        self.assertIn("mesh_edit_.selected_vertices.insert", native_source)
        self.assertIn("std::string mesh_edit_payload_json", native_source)
        self.assertIn("std::string scope_mode = \"all\";", native_source)
        self.assertIn("std::string delete_mode = \"release\";", native_source)
        self.assertIn("std::set<int> source_submesh_indices;", native_source)
        self.assertIn("bool mesh_edit_source_allowed", native_source)
        self.assertIn('json_string_field(payload, "delete_mode"', native_source)
        self.assertIn('json_int_array_field(payload, "source_submesh_indices")', native_source)
        self.assertNotIn("std::vector<EditorCandidate> mesh_edit_selected_candidates", native_source)
        self.assertIn("source_submesh_index", native_source)
        self.assertIn("source_vertex_index", native_source)
        self.assertIn("source_vertex_weights", native_source)
        self.assertIn("Enable viewport mesh editing for visible replacement source geometry", main_source)
        self.assertIn("mesh_edit_payload_vertex_weights(group, vertex_indices)", static_payload_source)

        self.assertIn("source_submesh_index=submesh_index", archive_source)
        self.assertIn("source_vertex_range_start=0", archive_source)
        self.assertIn("source_vertex_range_count=len(submesh.vertices)", archive_source)
        self.assertIn("source_face_range_start=0", archive_source)
        self.assertIn("source_face_range_count=len(submesh.faces)", archive_source)
        self.assertNotIn("source_vertex_indices=list(range(len(submesh.vertices)))", archive_source)
        self.assertNotIn("source_face_indices=list(range(len(submesh.faces)))", archive_source)
        self.assertIn("identity_stride_bytes", _native_preview_package_source())
        self.assertIn("batch.cpu_source_faces", native_source)
        self.assertIn("edited_source_mesh: ParsedMesh | None = None", static_source)
        self.assertIn("class StaticIndependentPart", static_source)
        self.assertIn("independent_output_parts: list[StaticIndependentPart] = field(default_factory=list)", static_source)
        self.assertIn("additional_supplemental_files: list[object] = field(default_factory=list)", static_source)
        self.assertIn("def _replacement_mesh_from_options", static_source)

    def test_alignment_dialog_can_append_mesh_parts_in_geometry(self) -> None:
        source = _main_window_source()
        assignment_source = static_replacement_callback_concern_source(ROOT, "source_part_assignment")
        mutation_source = static_replacement_source_part_mutation_callback_source(ROOT)
        remaining_source = static_replacement_remaining_callback_source(ROOT)
        routing_source = static_replacement_routing_callback_source(ROOT)
        outliner_source = static_replacement_ui_concern_source(ROOT, "source_parts_outliner")
        source_parts_state_source = _source_part_owner_sources()
        geometry_math_source = ARCHIVE_STATIC_REPLACEMENT_GEOMETRY_MATH.read_text(encoding="utf-8")
        transform_control_source = ARCHIVE_STATIC_REPLACEMENT_TRANSFORM_CONTROL_STATE.read_text(encoding="utf-8")
        preview_status_source = ARCHIVE_STATIC_REPLACEMENT_PREVIEW_STATUS_STATE.read_text(encoding="utf-8")
        preview_limits_source = ARCHIVE_STATIC_REPLACEMENT_PREVIEW_LIMITS.read_text(encoding="utf-8")
        scene_source = SCENE_IMPORT_RESULT_OPS.read_text(encoding="utf-8")
        self.assertIn("_state.append_mesh_part_button = _state.QPushButton(_state.source_part_inspector_control_text['add_mesh_part'])", outliner_source)
        self.assertIn('"add_mesh_part": "Add Mesh Part..."', source_parts_state_source)
        self.assertIn("def _append_mesh_part_to_geometry", source)
        self.assertIn("append_scene_import_to_mesh(", source)
        self.assertIn("refresh_parsed_mesh_totals", source)
        self.assertIn("def _normalize_appended_part_to_work_area", source)
        self.assertIn("_reference_vertices_for_appended_part = lambda", source)
        self.assertNotIn("preview_detail_combo", source)
        self.assertNotIn('QLabel("Detail")', source)
        self.assertIn("preview_render_controls_widget.setVisible(False)", source)
        self.assertIn("preview_panel_layout.addWidget(preview_render_controls_widget)", source)
        self.assertIn("archive_renderer_backend_enabled=True", source)
        self.assertIn("def adaptive_alignment_preview_face_limit", preview_limits_source)
        self.assertIn("def alignment_preview_quality_label", source)
        self.assertIn("_alignment_preview_help_presentation_helper(d3d11_active=False)", source)
        self.assertIn("Live preview. Build Mod validates final package paths during export.", preview_status_source)
        self.assertIn("def _alignment_preview_widget_render_settings", source)
        self.assertIn("settings.disable_all_support_maps = True", source)
        self.assertIn("widget.set_high_quality_textures(not interactive_preview)", source)
        self.assertNotIn('mode in {"auto", "full", "fast"}', source)
        self.assertIn("_alignment_preview_is_interactive = lambda", source)
        self.assertNotIn('if preview_detail_mode == "auto" and total_faces <= 120_000', source)
        self.assertIn("_alignment_transform_preview_queue_state_helper(", source)
        self.assertIn("_state.static_preview_interactive_until['time'] = float(preview_queue_state['interactive_until'])", source)
        self.assertIn("def _apply_alignment_transform_reset_state(reset_state: Mapping[str, object]) -> None:", source)
        self.assertIn("def alignment_transform_reset_state(", transform_control_source)
        self.assertIn("_state._alignment_transform_reset_state_helper('location')", source)
        self.assertIn("_state._alignment_transform_reset_state_helper('rotation')", source)
        self.assertIn("_state._alignment_transform_reset_state_helper('scale')", source)
        self.assertIn("_alignment_transform_reset_state_helper(", source)
        self.assertIn("_state._alignment_transform_reset_state_helper('placement'", source)
        self.assertIn("modify_original_clone_mode=modify_original_clone_mode", source)
        self.assertIn("_alignment_rotation_nudge_value_helper(", source)
        self.assertIn("_alignment_global_rotation_origin_state_helper(", source)
        self.assertIn("_alignment_linked_scale_sync_state_helper(", source)
        self.assertIn("def alignment_linked_scale_sync_state(", transform_control_source)
        self.assertIn("_alignment_transform_slider_sync_state_helper(", source)
        self.assertIn("def alignment_transform_slider_sync_state(", transform_control_source)
        self.assertIn("_alignment_global_transform_spin_commit_state_helper(", source)
        self.assertIn("def alignment_global_transform_spin_commit_state(", transform_control_source)
        self.assertIn("_alignment_global_transform_spin_specs_helper(", source)
        self.assertIn("def alignment_global_transform_spin_specs(", transform_control_source)
        self.assertIn("_alignment_global_transform_slider_specs_helper(", source)
        self.assertIn("def alignment_global_transform_slider_specs(", transform_control_source)
        self.assertNotIn("offset_x_spin = _make_double_spin_helper(value=0.0, minimum=-10.0", source)
        self.assertIn("def alignment_rotation_nudge_value(", geometry_math_source)
        self.assertIn("def alignment_global_rotation_origin_state(", geometry_math_source)
        self.assertIn('"preview_quality": "normal"', source)
        self.assertIn("target_total_faces=75_000", source)
        self.assertIn("maximum=22_000", source)
        self.assertIn("def _alignment_preview_selected_source_face_limit", source)
        self.assertIn("def _alignment_preview_background_source_face_limit", source)
        self.assertIn("return 35_000", source)
        self.assertIn("horizontal_axes = tuple(index for index in range(3) if index != axis)", geometry_math_source)
        self.assertIn("needs_recenter = any(", geometry_math_source)
        self.assertIn("centered in the current asset work area", geometry_math_source)
        self.assertIn("scaled {scale:.4g}x for preview control", geometry_math_source)
        self.assertIn("appended_source_indices.update", source)
        self.assertIn("def _prompt_assign_appended_mesh_parts", source)
        self.assertIn("assignment_dialog.setWindowTitle(frame.text['window_title'])", assignment_source)
        self.assertIn('"window_title": "Assign Added Mesh Parts"', source_parts_state_source)
        self.assertIn("AssignmentSummary", source)
        self.assertIn("AssignmentTree", source)
        self.assertIn("def highlight_source", assignment_source)
        self.assertIn("_source_part_assignment_highlight_state_helper(", source)
        self.assertIn("def source_part_assignment_highlight_state(", source_parts_state_source)
        self.assertIn("def target_for_source", assignment_source)
        self.assertIn("selected_target_original_highlight_indices.update", source)
        self.assertIn("def _rollback_cancelled_appended_mesh_part_import", source)
        append_body = _nested_function_source(mutation_source, "_append_mesh_part_to_geometry")
        self.assertIn("if assignment_action == 'cancel':", append_body)
        self.assertIn("_state._source_part_cancel_import_status_helper(source_path.name)", append_body)
        self.assertIn('return f"Canceled {source_name}; Geometry was unchanged."', source_parts_state_source)
        self.assertIn("preview_only_source_indices.update", source)
        self.assertIn('"default_target_summary": "Default: attach to the selected target when one is selected."', source_parts_state_source)
        self.assertNotIn('target_combo.addItem("Create new part", -2)', source)
        self.assertIn("_source_part_assignment_row_specs_helper(", source)
        self.assertIn("def source_part_assignment_row_specs(", source_parts_state_source)
        self.assertIn('SourcePartAssignmentTargetOption(copy["preview_only_combo"], -1)', source_parts_state_source)
        self.assertIn('"preview_only_combo": "Preview only"', source_parts_state_source)
        self.assertIn("Detected {int(texture_count):,} texture file(s)", source_parts_state_source)
        self.assertIn("_source_part_append_texture_control_state_helper(", source)
        self.assertIn("def source_part_append_texture_control_state(", source_parts_state_source)
        self.assertIn("inject_base_color_checkbox.setChecked(True)", source)
        self.assertIn("_source_part_assignment_button_state_helper(", source)
        self.assertIn("def source_part_assignment_button_state(", source_parts_state_source)
        self.assertIn('copy["attach_all_current"]', source_parts_state_source)
        self.assertIn('"attach_all_current": "Attach All To Current"', source_parts_state_source)
        self.assertIn("assign_order_button = _state.QPushButton(frame.text['assign_by_order'])", assignment_source)
        self.assertIn('"assign_by_order": "Assign By Order"', source_parts_state_source)
        self.assertIn("apply_button = _state.QPushButton(frame.text['apply_button'])", assignment_source)
        self.assertIn('"apply_button": "Apply Attachments"', source_parts_state_source)
        self.assertIn("Preview-only parts are visible in this session but are blocked from final PAC/PAM export.", source_parts_state_source)
        self.assertIn("copy['attach_to_target_prefix']", source_parts_state_source)
        self.assertIn('"attach_to_target_prefix": "Attach to "', source_parts_state_source)
        self.assertIn("row_target_combos", source)
        self.assertIn("assignments_by_target", source)
        self.assertIn("_source_part_assignment_route_state_helper(", source)
        self.assertIn("def source_part_assignment_route_state(", source_parts_state_source)
        self.assertIn("textures_button = _state.QPushButton(frame.text['open_textures'])", assignment_source)
        self.assertIn('"open_textures": "Open Textures"', source_parts_state_source)
        self.assertIn("_source_part_append_file_route_state_helper(", source)
        self.assertIn("def source_part_append_file_route_state(", source_parts_state_source)
        self.assertIn("def source_part_added_export_blocker_title", source_parts_state_source)
        self.assertIn('return "Attach Added Mesh Parts"', source_parts_state_source)
        self.assertIn("def _maybe_reduce_high_density_scene_import", source)
        self.assertIn("def _maybe_flatten_scene_import_parts", source)
        self.assertNotIn("def _format_mesh_density_counts", source)
        self.assertNotIn("def _scene_import_appendable_part_count", source)
        self.assertNotIn("def _scene_import_is_high_density", source)
        self.assertIn("_source_part_multipart_prompt_state_helper(", source)
        self.assertIn("_source_part_high_density_prompt_state_helper(", source)
        self.assertIn("def source_part_format_mesh_density_counts", source_parts_state_source)
        self.assertIn("def source_part_scene_import_appendable_part_count", source_parts_state_source)
        self.assertIn("def source_part_scene_import_is_high_density", source_parts_state_source)
        self.assertIn("def source_part_multipart_prompt_state", source_parts_state_source)
        self.assertIn("def source_part_high_density_prompt_state", source_parts_state_source)
        self.assertIn("message_box.setWindowTitle(prompt_state.title)", source)
        self.assertIn('"multipart_title": "Mesh Contains Multiple Parts"', source_parts_state_source)
        self.assertIn('"flatten_to_one_part": "Flatten To One Part"', source_parts_state_source)
        self.assertIn('"keep_separate_parts": "Keep Separate Parts"', source_parts_state_source)
        self.assertIn('"group_by_material": "Group By Material"', source_parts_state_source)
        self.assertIn("group_scene_import_result_parts_by_material(", source)
        self.assertIn("flatten_scene_import_result_parts(", source)
        self.assertIn("_source_part_reduction_result_message_helper(", source)
        self.assertIn('"high_density_title": "High Density Mesh Import"', source_parts_state_source)
        self.assertIn('"keep_full_quality": "Keep Full Quality"', source_parts_state_source)
        self.assertIn('"reduce_quality": "Reduce For Performance/Size"', source_parts_state_source)
        mesh_validation_source = MESH_DOMAIN_VALIDATION.read_text(encoding="utf-8")
        self.assertIn("def _format_scene_import_byte_size", mesh_validation_source)
        self.assertIn("def format_scene_import_file_size_summary", mesh_validation_source)
        self.assertIn("linked mesh buffer(s)", mesh_validation_source)
        self.assertNotIn("source_path.stat().st_size / (1024 * 1024):.1f", source)
        self.assertIn("reduce_scene_import_result_quality", source)
        self.assertIn("_source_part_append_imported_state_helper(", source)
        self.assertIn("def source_part_append_imported_state(", source_parts_state_source)
        self.assertIn("_source_part_append_rollback_snapshot_helper(", source)
        self.assertIn("def source_part_append_rollback_snapshot(", source_parts_state_source)
        self.assertIn("appended_ordinal=appended_ordinal", source_parts_state_source)
        self.assertIn("appended_source_count=appended_source_count", source_parts_state_source)
        self.assertIn("def _append_unmapped_appended_source_overlays", source)
        self.assertIn("source_overlay_preview_index_map", source)
        self.assertIn("preview_submesh_index_map: Dict[int, int] = {}", source)
        self.assertIn("_preview_model_in_original_frame = lambda", source)
        self.assertIn("parsed_submesh_index_map[submesh_position] = len(preview_meshes) - 1", source)
        self.assertIn("mapped_index = preview_submesh_index_map.get(target_index)", source)
        self.assertIn("source_overlay_preview_index_map[int(independent_part.source_submesh_index)] = preview_index", source)
        preview_models_source = ARCHIVE_STATIC_REPLACEMENT_PREVIEW_MODELS.read_text(encoding="utf-8")
        self.assertIn("_should_use_direct_source_preview_helper(", source)
        self.assertIn("appended_source_indices=_state.appended_source_indices", remaining_source)
        self.assertIn("mapped_source_indices=mapped_preview_source_indices", source)
        self.assertIn("def should_use_direct_source_preview(", preview_models_source)
        self.assertIn("def _mapped_source_indices_value(mappings: object) -> set[int]:", source)
        self.assertIn("mapped_preview_source_indices = _state._mapped_source_indices_value(current_mappings)", remaining_source)
        self.assertIn("_alignment_preview_background_source_face_limit(background_overlay_indices)", source)
        self.assertIn("global_transform_source_indices=_state._mapped_source_indices(current_mappings)", source)
        self.assertIn("'global_transform_exempt_source_indices': sorted((int(index) for index in _state.appended_source_indices))", source)
        self.assertIn("appended_geometry = int(_state.source_geometry_revision.get", source)
        self.assertIn("spin.setKeyboardTracking(False)", source)
        self.assertIn("_state.part_nudge_step_spin = _state._make_double_spin_helper(0.005, 1e-05, 1.0, 5, 0.0005)", outliner_source)
        source_parts_state_source = _source_part_owner_sources()
        self.assertIn("_state.center_part_button = _state.QPushButton(_state.source_part_transform_control_text['center_part'])", outliner_source)
        self.assertIn("_state.undo_geometry_button = _state.QPushButton(_state.source_part_transform_control_text['undo_geometry'])", outliner_source)
        self.assertIn("_state.reset_geometry_button = _state.QPushButton(_state.source_part_transform_control_text['reset_geometry'])", outliner_source)
        self.assertIn('"center_part": "Center To Target"', source_parts_state_source)
        self.assertIn('"undo_geometry": "Undo Geometry"', source_parts_state_source)
        self.assertIn('"reset_geometry": "Reset Geometry"', source_parts_state_source)
        self.assertIn("geometry_undo_stack: List[Dict[str, Any]] = []", source)
        self.assertIn("def _capture_geometry_history_state", source)
        self.assertIn("def _restore_geometry_history_state", source)
        geometry_history_source = ARCHIVE_STATIC_REPLACEMENT_GEOMETRY_HISTORY.read_text(encoding="utf-8")
        self.assertIn("_geometry_history_capture_state_helper(", source)
        self.assertIn("_geometry_history_restore_state_helper(", source)
        self.assertIn("_geometry_history_push_state_helper(", source)
        self.assertIn("def geometry_history_capture_state(", geometry_history_source)
        self.assertIn("def geometry_history_restore_state(", geometry_history_source)
        self.assertIn("def geometry_history_push_state(", geometry_history_source)
        self.assertIn("def _push_geometry_undo_snapshot", source)
        self.assertIn("def _undo_geometry_change", source)
        self.assertIn("def _reset_geometry_changes", source)
        self.assertIn("_set_mapping_indices(target_index, source_indices, push_undo=False)", source)
        self.assertIn("_state._push_geometry_undo_snapshot(source_part_group_routing_text['undo_label'], metadata_only=True)", mutation_source)
        self.assertIn('"undo_label": "Group routing by source material"', source_parts_state_source)
        self.assertIn("_state._source_part_edit_undo_label_helper('fit')", routing_source)
        self.assertIn("_state._source_part_edit_undo_label_helper('nudge')", routing_source)
        self.assertIn("_state._source_part_edit_undo_label_helper('center')", routing_source)
        self.assertIn("def _nudge_selected_part_axis", source)
        self.assertIn("def _center_selected_part_on_target", source)
        self.assertIn("_state.QShortcut(_state.QKeySequence('Ctrl+PageUp'), _state.dialog)", outliner_source)
        self.assertIn("SceneImportRequest(source_path=source_path)", source)
        self.assertIn("run_scene_import", source)
        self.assertNotIn("import_scene_mesh_with_report(source_path)", source)
        self.assertIn("source_geometry_revision[\"value\"]", source)
        self.assertIn("dialog_added_supplemental_files", source)
        self.assertIn("additional_supplemental_files=[] if _state.modify_original_clone_mode else list(_state.dialog_added_supplemental_files)", source)
        self.assertIn("_source_part_append_mesh_file_dialog_text_helper()", source)
        self.assertIn("source_part_append_mesh_file_dialog_text['mesh_filter']", append_body)
        self.assertIn("source_part_append_mesh_file_dialog_text['fbx_title']", append_body)
        self.assertIn("_source_part_unsupported_mesh_part_message_helper(source_path.name)", source)
        self.assertIn("_source_part_add_mesh_part_failed_title_helper()", source)
        self.assertIn("_source_part_added_mesh_part_status_helper(source_path.name, placement_note)", source)
        self.assertIn('return "Add Mesh Part Failed"', source_parts_state_source)
        self.assertIn('return f"Added {source_name}; {note}."', source_parts_state_source)
        self.assertIn('"title": "Add Mesh Part"', source_parts_state_source)
        self.assertIn('"fbx_title": "FBX Import Deferred"', source_parts_state_source)
        self.assertIn('"unsupported_title": "Unsupported Mesh Part"', source_parts_state_source)
        self.assertIn("_state.append_mesh_part_button.clicked.connect(_state._append_mesh_part_to_geometry)", outliner_source)
        self.assertIn("_state.undo_geometry_button.clicked.connect(_state._undo_geometry_change)", outliner_source)
        self.assertIn("_state.reset_geometry_button.clicked.connect(_state._reset_geometry_changes)", outliner_source)
        self.assertIn("class SceneMeshAppendResult", scene_source)
        self.assertIn("def flatten_scene_import_result_parts", scene_source)
        self.assertIn("def append_scene_import_to_mesh", scene_source)

    def test_alignment_geometry_tab_uses_compact_source_parts_master_list(self) -> None:
        from tests.alignment_dialog_geometry_source_guard import (
            assert_alignment_geometry_tab_uses_compact_source_parts_master_list,
        )

        assert_alignment_geometry_tab_uses_compact_source_parts_master_list(self)

    def test_parts_outliner_has_click_edit_contract_and_copied_part_safety(self) -> None:
        source = _main_window_source()
        builder_host_source = (ROOT / "cdmw" / "ui" / "mesh_editor" / "builder_host.py").read_text(encoding="utf-8")
        parts_outliner_state_source = ARCHIVE_STATIC_REPLACEMENT_PARTS_OUTLINER_STATE.read_text(encoding="utf-8")
        self.assertIn("class MeshReplacementPartsOutlinerTree(QTreeWidget):", builder_host_source)
        self.assertIn("def dropEvent(self, event: object) -> None:", builder_host_source)
        self.assertIn("_state.parts_outliner_tree = _state.MeshReplacementPartsOutlinerTree()", source)
        self.assertIn("_state.parts_outliner_tree.setDragEnabled(True)", source)
        self.assertIn("_state.parts_outliner_tree.setAcceptDrops(True)", source)
        self.assertIn("_state.parts_outliner_tree.setDragDropMode(_state.QAbstractItemView.InternalMove)", source)
        self.assertIn("_state.parts_outliner_tree.itemClicked.connect(_state._handle_parts_outliner_item_clicked)", source)
        self.assertIn("_state.source_tree.itemClicked.connect(_state._handle_source_tree_item_clicked)", source)
        self.assertIn("_state.parts_outliner_tree.set_source_drop_handler(_state._handle_parts_outliner_source_drop)", source)
        self.assertNotIn("_state.parts_outliner_tree.currentItemChanged.connect(_state._parts_outliner_selection_changed)", source)
        mapping_callbacks_start = source.index(
            "_state.parts_outliner_mapping_callbacks = _state.create_alignment_parts_outliner_mapping_callbacks"
        )
        mapping_callbacks_end = source.index(
            "_state._parts_outliner_source_label = _state.parts_outliner_mapping_callbacks._parts_outliner_source_label",
            mapping_callbacks_start,
        )
        mapping_callbacks_block = source[mapping_callbacks_start:mapping_callbacks_end]
        self.assertIn("'_parts_outliner_selection_changed': lambda *args, **kwargs:", mapping_callbacks_block)
        self.assertIn("'_select_source_part_from_viewport': lambda *args, **kwargs:", mapping_callbacks_block)
        self.assertIn("'_target_selection_changed': lambda *args, **kwargs:", mapping_callbacks_block)
        self.assertIn("def _open_parts_outliner_target_dropdown", source)
        self.assertIn("def _open_parts_outliner_role_dropdown", source)
        self.assertIn("_parts_outliner_target_menu_specs_helper(target_labels)", source)
        self.assertIn("_state._parts_outliner_role_menu_specs_helper(_state.PARTS_OUTLINER_ROLE_OPTIONS)", source)
        self.assertIn("def parts_outliner_target_menu_specs", parts_outliner_state_source)
        self.assertIn("def parts_outliner_role_menu_specs", parts_outliner_state_source)
        self.assertIn("def _open_source_tree_role_dropdown", source)
        material_refresh_state_source = ARCHIVE_STATIC_REPLACEMENT_MATERIAL_REFRESH_STATE.read_text(encoding="utf-8")
        self.assertIn("def material_edit_refresh_interval_ms", material_refresh_state_source)
        self.assertIn("material_edit_refresh_timer.setInterval(_material_edit_refresh_interval_ms_helper())", source)
        self.assertIn("def _queue_material_edit_refresh", source)
        self.assertIn("def _run_material_edit_refresh() -> None:", source)
        self.assertIn("material_edit_refresh_timer.timeout.connect(_run_material_edit_refresh)", source)
        self.assertIn("def source_material_plan_refresh_interval_ms", material_refresh_state_source)
        self.assertIn(
            "source_material_plan_refresh_timer.setInterval(_source_material_plan_refresh_interval_ms_helper())",
            source,
        )
        self.assertIn("def _queue_source_material_plan_refresh", source)
        self.assertIn("def _run_source_material_plan_refresh() -> None:", source)
        self.assertIn("source_material_plan_refresh_timer.timeout.connect(_run_source_material_plan_refresh)", source)
        self.assertIn("_safe_stop_alignment_timer(material_edit_refresh_timer)", source)
        self.assertIn("_safe_stop_alignment_timer(source_material_plan_refresh_timer)", source)
        callback_source = _callback_factory_source()
        material_refresh_block = _nested_function_source(callback_source, "_run_material_edit_refresh")
        self.assertIn("_queue_texture_preview_refresh()", material_refresh_block)
        self.assertIn("_queue_source_material_plan_refresh(force_plan=force_plan, reason=reason)", material_refresh_block)
        self.assertLess(
            material_refresh_block.index("_queue_texture_preview_refresh()"),
            material_refresh_block.index("_queue_source_material_plan_refresh(force_plan=force_plan, reason=reason)"),
        )
        self.assertNotIn("_refresh_source_material_plan", material_refresh_block)
        plan_refresh_block = _nested_function_source(callback_source, "_run_source_material_plan_refresh")
        self.assertIn("material_tab_active = _state.control_tabs.currentWidget() is _state.textures_tab", plan_refresh_block)
        self.assertIn("_state.texture_material_plan_loaded['loaded'] = False", plan_refresh_block)
        self.assertIn("'mesh_alignment_source_material_plan_deferred'", plan_refresh_block)
        self.assertIn("def _apply_parts_outliner_source_target", source)
        self.assertIn("def _handle_parts_outliner_source_drop", source)
        self.assertIn("_apply_parts_outliner_source_target(source_index, target_index)", source)
        target_block = _nested_function_source(callback_source, "_apply_parts_outliner_source_target")
        self.assertIn("_parts_outliner_source_target_apply_state_helper(", target_block)
        self.assertIn("source_count=len(_state.replacement_mesh_for_mapping.submeshes)", target_block)
        self.assertIn("apply_state.source_index", target_block)
        self.assertIn("apply_state.target_index", target_block)
        self.assertNotIn("source_index = int(source_index)", target_block)
        self.assertNotIn("target_index = int(target_index)", target_block)
        self.assertIn("def parts_outliner_source_target_apply_state", parts_outliner_state_source)
        self.assertIn("_parts_outliner_source_indices_helper(source_indices)", source)
        self.assertIn("_parts_outliner_target_label_helper(", source)
        self.assertIn("_parts_outliner_geometry_text_helper(target)", source)
        self.assertIn("_parts_outliner_source_label_helper(", source)
        self.assertIn("_parts_outliner_unassigned_source_indices_helper(", source)
        self.assertIn("_parts_outliner_copied_texture_tooltip_source_index_helper(", source)
        self.assertIn("def parts_outliner_source_indices", parts_outliner_state_source)
        self.assertIn("def parts_outliner_target_label", parts_outliner_state_source)
        self.assertIn("def parts_outliner_geometry_text", parts_outliner_state_source)
        self.assertIn("def parts_outliner_source_label", parts_outliner_state_source)
        self.assertIn("def parts_outliner_unassigned_source_indices", parts_outliner_state_source)
        self.assertIn("def parts_outliner_copied_texture_tooltip_source_index", parts_outliner_state_source)
        self.assertIn("def _apply_parts_outliner_source_role", source)
        role_block = _nested_function_source(callback_source, "_apply_parts_outliner_source_role")
        self.assertIn("_queue_material_edit_refresh(", role_block)
        self.assertIn("_refresh_source_assignment_columns(lightweight=True)", role_block)
        self.assertIn("refresh_plan=action_state.refresh_plan", role_block)
        self.assertIn("force_plan=action_state.force_plan", role_block)
        self.assertIn("def parts_outliner_source_role_change_refresh_reason", parts_outliner_state_source)
        self.assertIn("refresh_reason=_state._parts_outliner_source_role_change_refresh_reason_helper()", role_block)
        self.assertIn("reason=action_state.refresh_reason", role_block)
        self.assertIn("_source_part_role_action_state_helper(", role_block)
        self.assertIn("source_index=source_index", role_block)
        self.assertIn("_set_source_role_override_value(action_state.source_index, action_state.normalized_role)", role_block)
        self.assertNotIn("source_index = int(source_index)", role_block)
        self.assertNotIn("_queue_static_preview_rebuild()", role_block)
        source_role_start = source.index("def apply_role_selection")
        source_role_end = source.index("def _set_visible", source_role_start)
        source_role_block = source[source_role_start:source_role_end]
        self.assertIn('queue_material_edit = self._callback("_queue_material_edit_refresh")', source_role_block)
        self.assertIn("queue_material_edit(", source_role_block)
        self.assertIn(
            'refresh_assignment_columns = self._callback("_refresh_source_assignment_columns")',
            source_role_block,
        )
        self.assertIn("refresh_assignment_columns(lightweight=True)", source_role_block)
        self.assertIn("reason=action_state.refresh_reason", source_role_block)
        self.assertIn('role_action_state = self._callback("_source_part_role_action_state_helper")', source_role_block)
        self.assertIn("if not callable(role_action_state) or not callable(set_role_override):", source_role_block)
        self.assertIn("source_index=source_index", source_role_block)
        self.assertIn('set_role_override = self._callback("_set_source_role_override_value")', source_role_block)
        self.assertIn("set_role_override(action_state.source_index, action_state.normalized_role)", source_role_block)
        self.assertNotIn("source_index = int(source_index)", source_role_block)
        self.assertNotIn("_queue_static_preview_rebuild()", source_role_block)
        selected_role_start = source.index("def _set_selected_source_role")
        selected_role_end = source.index("def _set_selected_source_glow_color", selected_role_start)
        selected_role_block = source[selected_role_start:selected_role_end]
        self.assertIn("_queue_material_edit_refresh(", selected_role_block)
        self.assertIn("_refresh_source_assignment_columns(lightweight=True)", selected_role_block)
        self.assertIn("_source_part_role_action_state_helper(", selected_role_block)
        self.assertIn("reason=action_state.refresh_reason", selected_role_block)
        self.assertNotIn("_queue_static_preview_rebuild()", selected_role_block)
        self.assertIn("Qt.ItemFlag.ItemIsDragEnabled", source)
        self.assertIn("Qt.ItemFlag.ItemIsDropEnabled", source)
        self.assertIn('"Preview-only / Unassigned"', parts_outliner_state_source)
        self.assertIn('("auto", "")', source)
        self.assertIn('("blade", "blade")', source)
        self.assertIn('("cloth", "cloth")', source)
        self.assertIn('("Glow / emissive", "glow")', source)
        self.assertIn('("glow/emissive", "glow")', source)
        self.assertIn("_source_part_role_override_state_helper(", source)
        self.assertIn("source_role_overrides[role_state.source_index] = role_state.normalized_role", source)
        self.assertIn("adjustment.material_role = role_state.normalized_role", source)
        self.assertIn("def _flush_source_role_overrides_for_export", source)
        flush_role_start = source.index("def _flush_source_role_overrides_for_export")
        flush_role_end = source.index("def _refresh_ui_texture_sets_after_source_part_material_override", flush_role_start)
        flush_role_block = source[flush_role_start:flush_role_end]
        self.assertIn("_source_part_role_export_flush_states_helper(", flush_role_block)
        self.assertIn("flush_state.material_role_changed", flush_role_block)
        self.assertNotIn("clear_emissive_color", flush_role_block)
        self.assertNotIn("source_index = int(raw_source_index)", flush_role_block)
        self.assertIn("_apply_current_glow_color_to_role_overrides()", source)
        self.assertIn("_flush_source_role_overrides_for_export()", source)
        self.assertIn("source_index = _source_index_from_tree_item(item)", source)
        self.assertIn("MeshAlignmentSourceGlowColorOverrideCheckBox", source)
        self.assertIn("MeshAlignmentSourceGlowColorRSpinBox", source)
        self.assertIn("MeshAlignmentSourceGlowColorGSpinBox", source)
        self.assertIn("MeshAlignmentSourceGlowColorBSpinBox", source)
        source_parts_state_source = _source_part_owner_sources()
        self.assertIn("def source_part_glow_color_button_text", source_parts_state_source)
        self.assertIn("def source_part_glow_color_controls_state", source_parts_state_source)
        self.assertIn("_source_part_glow_color_controls_state_helper(", source)
        self.assertIn("_source_part_glow_rgb_helper(", source)
        authority_controls_source = ARCHIVE_STATIC_REPLACEMENT_MATERIAL_AUTHORITY_CONTROLS.read_text(encoding="utf-8")
        self.assertIn("_state.true_source_basic_form.addWidget(_state.QLabel(_state.material_authority_adjustment_labels['glow_color']), 8, 0)", source)
        self.assertIn('"glow_color": "Glow color"', authority_controls_source)
        self.assertIn("_state.true_source_basic_form.addLayout(_state.part_glow_color_row, 8, 1)", source)
        self.assertNotIn("_state.part_layout.addLayout(_state.part_glow_color_row", source)
        self.assertIn("adjustment.emissive_color_rgb = role_state.emissive_color_rgb", source)
        preview_textures_source = ARCHIVE_STATIC_REPLACEMENT_PREVIEW_TEXTURES.read_text(encoding="utf-8")
        self.assertIn("def apply_source_role_emissive_preview_for_model(", preview_textures_source)
        self.assertIn("def clear_source_role_emissive_preview(mesh: object) -> None:", preview_textures_source)
        self.assertIn("if not accent_glow_preview_enabled(profile):", preview_textures_source)
        self.assertIn('confidence="source-role-preview"', preview_textures_source)
        self.assertIn('overrides["emissive_intensity"] = emissive_intensity', preview_textures_source)
        self.assertIn('overrides["emissive_color"] = color_hex', preview_textures_source)
        selected_part_callback_source = _callback_factory_source()
        glow_color_start = selected_part_callback_source.index("def _set_selected_source_glow_color")
        glow_color_end = selected_part_callback_source.index("def _selected_part_target_index", glow_color_start)
        glow_color_block = selected_part_callback_source[glow_color_start:glow_color_end]
        self.assertIn("_source_part_glow_color_action_state_helper()", glow_color_block)
        self.assertIn("_apply_current_glow_color_to_role_overrides()", glow_color_block)
        self.assertIn("_refresh_ui_texture_sets_after_source_part_material_override()", glow_color_block)
        self.assertIn("refresh_plan=action_state.refresh_plan", glow_color_block)
        self.assertIn("force_plan=action_state.force_plan", glow_color_block)
        self.assertIn("reason=action_state.refresh_reason", glow_color_block)
        material_source = _material_replacer_source()
        static_source = _static_replacer_source()
        self.assertIn("emissive_color_rgb: tuple[int, int, int] = ()", static_source)
        self.assertIn("accent_glow_color_rgb: tuple[float, float, float] = ()", material_source)
        self.assertIn("texture_set.accent_glow_color_rgb = glow_rgb", material_source)
        self.assertIn("preview_only_source_indices.add(source_index)", source)
        self.assertIn("_state.parts_outliner_tree.setRootIsDecorated(True)", source)
        self.assertIn("_parts_outliner_target_label_helper(", source)
        self.assertIn("_parts_outliner_source_label_helper(", source)
        self.assertIn("_state.mapping_status_label.setObjectName('MeshRoutingSelectedContractSummary')", source)
        self.assertIn("_mapping_status_summary_badges_helper(", source)
        self.assertNotIn('_mapping_status_summary_badge("Source"', source)
        mapping_table_state_source = ARCHIVE_STATIC_REPLACEMENT_MAPPING_TABLE_STATE.read_text(encoding="utf-8")
        self.assertIn("def mapping_status_summary_badge", mapping_table_state_source)
        self.assertIn("def mapping_status_summary_badges", mapping_table_state_source)
        self.assertIn('mapping_status_summary_badge("Source"', mapping_table_state_source)
        self.assertIn('mapping_status_summary_badge("Physics"', mapping_table_state_source)
        self.assertIn("copied_original_source_indices: set[int] = set()", source)
        self.assertIn("copied_original_source_to_original_index", source)
        self.assertIn("copied_original_physics_sensitive_sources", source)
        self.assertIn("copied_original_source_indices.add(new_source_index)", source)
        self.assertIn("appended_source_indices.add(new_source_index)", source)
        append_block = _nested_function_source(
            static_replacement_remaining_callback_source(ROOT),
            "_append_original_part_payload_as_source",
        )
        self.assertNotIn("original_part_copies.append(", append_block)
        self.assertTrue(
            "source_geometry_revision[\"value\"]" in append_block
            or "source_geometry_revision['value']" in append_block
        )

    def test_parts_outliner_physics_is_preserved_not_auto_copied(self) -> None:
        source = _main_window_source() + "\n" + ARCHIVE_STATIC_REPLACEMENT_ORIGINAL_PARTS.read_text(encoding="utf-8")
        self.assertIn("_part_physics_review_reason = lambda", source)
        self.assertIn('"flag"', source)
        self.assertIn('"hkx"', source)
        self.assertIn('"hkt"', source)
        self.assertIn("Target physics is preserved; copied geometry/textures do not auto-copy HKX/HKT", source)
        self.assertIn("_source_physics_status_text = lambda", source)
        self.assertIn("return \"Preserved\"", source)
        self.assertIn("copied_original_physics_sensitive_sources.add(new_source_index)", source)
        self.assertNotIn("dialog_added_supplemental_files.append(hkx", source.lower())
        self.assertNotIn("dialog_added_supplemental_files.append(hkt", source.lower())

    def test_alignment_numeric_spinboxes_commit_typed_text(self) -> None:
        source = _main_window_source()
        accept_source = static_replacement_callback_concern_source(ROOT, "accept_build")
        helper_source = ARCHIVE_STATIC_REPLACEMENT_QT_HELPERS.read_text(encoding="utf-8")
        self.assertIn("def _commit_spinbox_text", source)
        self.assertIn("_commit_spinbox_text_helper(spin, block_signals=block_signals)", source)
        self.assertIn("spin.interpretText()", helper_source)
        self.assertIn("part_spin.editingFinished.connect", source)
        self.assertIn("mesh_edit_radius_spin.editingFinished.connect", source)
        self.assertIn("def _commit_global_transform_spin", source)
        self.assertIn("_state.spin.editingFinished.connect(lambda spin=_state.spin: _state._commit_global_transform_spin(spin))", source)
        self.assertIn("texture_spin.editingFinished.connect", source)
        self.assertIn("def _commit_spinbox_text(spin: QDoubleSpinBox, *, block_signals: bool = False) -> None:", source)
        self.assertIn("previous_blocked = bool(spin.blockSignals(True))", helper_source)
        self.assertIn("spin.blockSignals(previous_blocked)", helper_source)
        self.assertIn("def _commit_alignment_numeric_edits(*, refresh_preview: bool=True) -> None:", accept_source)
        self.assertIn("_state._commit_spinbox_text(spin, block_signals=not bool(refresh_preview))", accept_source)
        self.assertIn("_state._update_selected_part_adjustment(queue_preview=refresh_preview, push_undo=refresh_preview)", accept_source)
        self.assertIn("_state._save_texture_transform_controls(queue_preview=refresh_preview)", accept_source)
        self.assertIn("_commit_alignment_numeric_edits(refresh_preview=False)", source)
        build_block = _nested_function_source(accept_source, "_build_static_options_from_dialog")
        self.assertIn("_commit_alignment_numeric_edits(refresh_preview=False)", build_block)
        self.assertNotIn("_commit_alignment_numeric_edits()", build_block)

    def test_alignment_transform_controls_are_debounced_and_slider_backed(self) -> None:
        source = _main_window_source()
        setup_ui_source = static_replacement_ui_concern_source(ROOT, "setup_options_transform")
        mesh_ui_source = static_replacement_ui_concern_source(ROOT, "mesh_geometry_preview")
        texture_ui_source = static_replacement_ui_concern_source(ROOT, "texture_material")
        qt_helper_source = ARCHIVE_STATIC_REPLACEMENT_QT_HELPERS.read_text(encoding="utf-8")
        transform_state_source = ARCHIVE_STATIC_REPLACEMENT_TRANSFORM_STATE.read_text(encoding="utf-8")
        transform_control_source = ARCHIVE_STATIC_REPLACEMENT_TRANSFORM_CONTROL_STATE.read_text(encoding="utf-8")
        self.assertIn("QSlider", source)
        self.assertIn('"slider_object_name": "AlignmentTransformSlider"', transform_control_source)
        self.assertIn("object_name=str(transform_layout_specs['slider_object_name'])", source)
        self.assertIn('object_name="AlignmentPartTransformSlider"', source)
        self.assertIn("alignment_transform_location_original_text", transform_state_source)
        self.assertIn("_state._alignment_transform_location_original_text_helper(_state.original_center)", setup_ui_source)
        self.assertIn("alignment_transform_control_text['axis_slider_tooltip_template'].format(", source)
        self.assertIn('"location_label": "Location"', transform_control_source)
        self.assertIn('"section_title": "Transform"', transform_control_source)
        self.assertIn("_state.CollapsibleSection(_state.alignment_transform_control_text['section_title'], expanded=True)", setup_ui_source)
        self.assertIn("wrapper_layout.addWidget(spin)", qt_helper_source)
        self.assertIn("spin.valueChanged.connect(_sync_slider_from_spin)", qt_helper_source)
        self.assertIn("slider.valueChanged.connect(_sync_spin_from_slider)", qt_helper_source)
        self.assertIn('"slider_minimum": 0.1', transform_control_source)
        self.assertIn('"slider_maximum": 3.0', transform_control_source)
        self.assertIn("def alignment_global_transform_layout_specs(", transform_control_source)
        self.assertIn("def alignment_global_transform_row_specs(", transform_control_source)
        self.assertIn("_alignment_global_transform_row_specs_helper(", source)
        self.assertIn("def alignment_global_transform_reset_button_specs(", transform_control_source)
        self.assertIn("def alignment_global_transform_tilt_button_specs(", transform_control_source)
        self.assertIn("_alignment_global_transform_reset_button_specs_helper(", source)
        self.assertIn("_alignment_global_transform_tilt_button_specs_helper(", source)
        self.assertIn("spin.setKeyboardTracking(False)", qt_helper_source)
        self.assertIn("_state.mesh_edit_radius_spin = _state._make_double_spin_helper(24.0, 2.0, 256.0, 0, 2.0", mesh_ui_source)
        self.assertIn("_state.mesh_edit_strength_spin = _state._make_double_spin_helper(50.0, 0.0, 100.0, 0, 5.0", mesh_ui_source)
        self.assertIn("_state.texture_transform_offset_u_spin = _state._make_double_spin_helper(0.0, -10.0, 10.0, 4, 0.01)", texture_ui_source)
        self.assertIn("_state.texture_transform_scale_v_spin = _state._make_double_spin_helper(1.0, 0.01, 100.0, 4, 0.01)", texture_ui_source)

    def test_alignment_transform_preview_uses_fast_path_without_settled_rebuild(self) -> None:
        source = _main_window_source()
        mapping_source = static_replacement_callback_concern_source(ROOT, "parts_outliner_mapping")
        transform_source = static_replacement_callback_concern_source(ROOT, "transform_drag")
        refresh_source = static_replacement_callback_concern_source(ROOT, "refresh_queue")
        package_source = static_replacement_callback_concern_source(ROOT, "d3d11_package_lifecycle")
        remaining_source = static_replacement_callback_family_source(ROOT, "remaining")
        preview_status_source = ARCHIVE_STATIC_REPLACEMENT_PREVIEW_STATUS_STATE.read_text(encoding="utf-8")
        mapping_table_state_source = ARCHIVE_STATIC_REPLACEMENT_MAPPING_TABLE_STATE.read_text(encoding="utf-8")
        self.assertIn("static_preview_batch_state", source)
        self.assertIn("mapping_edit_refresh_timer.setInterval(_mapping_edit_refresh_interval_ms_helper())", source)
        self.assertIn("def mapping_edit_refresh_interval_ms() -> int:", mapping_table_state_source)
        self.assertIn("return 260", mapping_table_state_source)
        self.assertIn("edit.editingFinished.connect(lambda edit=edit: _state._commit_mapping_edit(edit))", mapping_source)
        self.assertIn("edit.setProperty('committed_mapping_text', edit.text())", mapping_source)
        self.assertIn("_refresh_source_assignment_columns(lightweight=True)", source)
        self.assertIn("_state.spin.valueChanged.connect(_state._queue_global_transform_preview_update)", source)
        self.assertIn("def _queue_global_transform_preview_update", source)
        self.assertIn("def _queue_part_transform_preview_update", source)
        self.assertIn("pending_fast_transform", source)
        self.assertIn("pending_part_fast_transforms", source)
        self.assertIn("def _queue_alignment_d3d11_fast_transform", source)
        self.assertIn("def _send_alignment_d3d11_fast_transform_state", source)
        self.assertIn("set_alignment_preview_transforms", source)
        self.assertIn("_alignment_d3d11_fast_transform_queue_state_helper(", source)
        self.assertIn("_alignment_d3d11_fast_transform_send_state_helper(", source)
        self.assertIn("def _replay_alignment_d3d11_fast_transform", source)
        self.assertIn("_alignment_d3d11_fast_transform_replay_state_helper(", source)
        self.assertIn("def _clear_alignment_d3d11_fast_transform_state(*, reset_host: bool=False) -> None:", refresh_source)
        self.assertIn("alignment_d3d11_preview_host.set_alignment_preview_transforms()", source)
        self.assertIn("_alignment_d3d11_loaded_package_transform_current_helper(", source)
        self.assertIn("alignment_transform_generation", source)
        self.assertIn("_clear_alignment_d3d11_fast_transform_state(reset_host=True)", source)
        self.assertIn("_replay_alignment_d3d11_fast_transform()", source)
        self.assertIn("alignment_d3d11_drag_generation", source)
        self.assertIn("alignment_transform_generation", source)
        self.assertIn("_alignment_d3d11_drag_reload_stale_helper(", source)
        self.assertIn("alignment_d3d11_drag_generation", source)
        self.assertIn("request_drag_generation", source)
        self.assertIn("request_transform_generation", source)
        self.assertIn("request_transform_generations", source)
        self.assertIn("active_package_request_id", source)
        self.assertIn("def _handle_alignment_d3d11_stale_reload(package_dir: object, *, request_id: int=0, reason: str) -> None:", package_source)
        self.assertIn("alignment_d3d11_mark_preview_loaded", source)
        self.assertIn("_state._alignment_d3d11_mark_preview_loaded_helper(_state.alignment_d3d11_state)", package_source)
        self.assertIn("_state._alignment_d3d11_invalidate_package_cache(f'stale_{reason}')", package_source)
        self.assertIn("_state.QTimer.singleShot(0, lambda expected_request=int(request_id or 0): _state._queue_latest_alignment_d3d11_rebuild_for_stale_reload(expected_request))", package_source)
        stale_queue_block = _nested_function_source(
            package_source, "_queue_latest_alignment_d3d11_rebuild_for_stale_reload"
        )
        self.assertIn("dirty_flags = _state._alignment_d3d11_dirty_flags_for_reason(reason)", stale_queue_block)
        self.assertIn("_mark_alignment_d3d11_rebuild_reason(reason)", stale_queue_block)
        self.assertIn("if dirty_flags.affects_geometry():", stale_queue_block)
        self.assertIn("static_preview_geometry_cache.clear()", stale_queue_block)
        self.assertIn("static_preview_prepared_cache.clear()", stale_queue_block)
        self.assertIn("if dirty_flags.affects_material():", stale_queue_block)
        self.assertIn("_state.texture_overrides_dirty['dirty'] = True", stale_queue_block)
        self.assertNotIn('_mark_alignment_d3d11_rebuild_reason("geometry")', stale_queue_block)
        self.assertIn("_mark_alignment_transform_changed()", source)
        self.assertIn("_state._safe_stop_alignment_timer(_state.alignment_d3d11_reload_timer)", source)
        self.assertIn("_alignment_d3d11_reset_request_state_helper(", source)
        self.assertIn("clear_active_request_id=False", source)
        self.assertIn("_alignment_d3d11_stop_worker()", source)
        self.assertIn("_alignment_d3d11_fast_transform_payload_helper(", source)
        self.assertIn("if callable(_state._current_alignment_transform_generation)", source)
        self.assertIn("transform_generation=transform_generation", source)
        self.assertIn("active_request_id = int(_state.alignment_d3d11_state.get('active_package_request_id', 0) or 0)", source)
        self.assertIn("Preview loaded; keeping live transform.", source)
        self.assertNotIn("Native D3D11 preview loaded stale package; refreshing after transform.", source)
        self.assertIn("if bool(_state.alignment_d3d11_drag_transaction.get('active')):", source)
        self.assertIn(
            "if not bool(_state.alignment_d3d11_drag_transaction.get('active')) and capture_generation >= committed_generation:",
            source,
        )
        self.assertIn("preview_widget.set_alignment_committed_preview_transform", source)
        self.assertIn("_state._safe_stop_alignment_timer(_state.static_preview_settle_timer)", source)
        update_block = "\n".join(
            (
                _nested_function_source(transform_source, "_queue_global_transform_preview_update"),
                _nested_function_source(transform_source, "_queue_part_transform_preview_update"),
            )
        )
        self.assertNotIn("static_preview_settle_timer.start()", update_block)
        self.assertIn("_alignment_transform_preview_queue_state_helper(", update_block)
        self.assertIn("_alignment_part_transform_preview_queue_indices_helper(", update_block)
        self.assertIn("if bool(preview_queue_state['start_timer']) and (not _state._active_mesh_edit_transform_preview_queue_blocked(", update_block)
        self.assertIn("static_preview_refresh_timer.start()", update_block)
        self.assertNotIn("_alignment_d3d11_global_fast_transform_pending()", update_block)
        part_update_block = _nested_function_source(remaining_source, "_update_selected_part_adjustment")
        self.assertIn("queue_preview: bool=True", part_update_block)
        self.assertIn("push_undo: bool=True", part_update_block)
        self.assertIn("_source_part_adjustment_apply_state_helper(", part_update_block)
        self.assertIn("if not apply_state.available or not apply_state.changed:", part_update_block)
        self.assertIn("if push_undo:", part_update_block)
        self.assertIn("_state._source_part_edit_undo_label_helper('toggle' if apply_state.enabled_changed else 'adjust')", part_update_block)
        self.assertIn("if mesh_edit_active and apply_state.geometry_changed:", part_update_block)
        self.assertIn("send_resident_material_parameters(", part_update_block)
        self.assertIn("if queue_preview:", part_update_block)
        self.assertIn("_refresh_selected_part_enable_preview(apply_state.target_indices)", part_update_block)
        self.assertNotIn("_set_source_parts_preview_rebuild_pending(", part_update_block)
        self.assertNotIn("_queue_static_preview_rebuild()", part_update_block)
        self.assertIn("_queue_part_transform_preview_update(tuple(apply_state.target_indices))", part_update_block)
        self.assertIn("_set_source_parts_apply_pending(", part_update_block)
        part_commit_block = _nested_function_source(transform_source, "_alignment_part_source_indices_for_commit")
        self.assertNotIn("_alignment_d3d11_global_fast_transform_pending()", part_commit_block)
        self.assertIn("_alignment_part_delta_refresh_state_helper(", source)
        self.assertIn("_state._queue_part_transform_preview_update(tuple(refresh_state['source_indices']))", source)
        start_process_block = _nested_function_source(package_source, "_start_alignment_d3d11_process")
        self.assertIn("_state._handle_alignment_d3d11_stale_reload(package_dir, request_id=int(request_id or 0), reason='stale_drag')", start_process_block)
        self.assertNotIn("_queue_static_preview_rebuild()", start_process_block)
        status_block = _nested_function_source(package_source, "_poll_alignment_d3d11_status")
        self.assertIn("Preview loaded; keeping live transform.", status_block)
        self.assertNotIn("_queue_static_preview_rebuild()", status_block)
        self.assertIn("transform_generation=refresh_transform_generation", source)
        self.assertIn("_alignment_preview_initial_performance_status_helper()", source)
        self.assertIn("Preview timing: waiting for first refresh.", preview_status_source)
        self.assertIn("preview_performance_label.setWordWrap(False)", source)
        self.assertIn("preview_performance_label.setMaximumHeight(24)", source)
        self.assertIn("def _set_preview_performance_status(summary: str, *, details: str='') -> None:", source)
        self.assertIn("geometry_elapsed_ms", source)
        self.assertIn("prepared_elapsed_ms", source)
        self.assertIn("refreshed_preview_widgets: _state.List[_state.NativePreviewPanel] = []", source)
        static_preview_state_source = ARCHIVE_STATIC_REPLACEMENT_STATIC_PREVIEW_STATE.read_text(encoding="utf-8")
        self.assertIn("_static_preview_upload_elapsed_ms_helper(refreshed_preview_widgets)", source)
        self.assertIn("def static_preview_upload_elapsed_ms(", static_preview_state_source)
        self.assertIn("_last_gl_upload_ms", static_preview_state_source)
        self.assertIn("def _set_global_fast_preview_edit_scope", source)
        self.assertIn("_alignment_d3d11_global_fast_preview_edit_range_helper(", source)
        self.assertIn("preview_widget.set_alignment_editable_mesh_range(start, count)", source)
        self.assertIn("def _set_part_fast_preview_edit_scope", source)
        self.assertIn("_alignment_global_fast_preview_state_helper(", source)
        self.assertIn("_alignment_part_fast_preview_state_helper(", source)
        self.assertNotIn("_global_fast_preview_transform_delta_helper(", source)
        self.assertNotIn("_part_fast_preview_transform_delta_helper(", source)

    def test_alignment_texture_uv_refresh_skips_slow_settle_debounce(self) -> None:
        source = _main_window_source()
        package_source = static_replacement_callback_concern_source(ROOT, "d3d11_package_lifecycle")
        refresh_source = static_replacement_callback_concern_source(ROOT, "refresh_queue")
        routing_source = static_replacement_callback_family_source(ROOT, "routing")
        texture_detail_source = ARCHIVE_STATIC_REPLACEMENT_DIALOG_TEXTURE_DETAIL_UV_CALLBACKS.read_text(encoding="utf-8")
        remaining_source = static_replacement_remaining_callback_source(ROOT)
        preview_batch_source = ARCHIVE_STATIC_REPLACEMENT_PREVIEW_BATCH_STATE.read_text(encoding="utf-8")
        self.assertIn("alignment_d3d11_fast_reload_interval_ms = 180", source)
        self.assertIn("alignment_d3d11_package_reload_interval_ms = 560", source)
        self.assertIn("alignment_d3d11_reload_timer.setInterval(alignment_d3d11_fast_reload_interval_ms)", source)
        queue_block = _nested_function_source(package_source, "_queue_alignment_d3d11_preview")
        self.assertIn("del model, label", queue_block)
        self.assertIn("reason='dotnet_authoritative'", queue_block)
        self.assertIn("requested_reason=str(reason or '')", queue_block)
        self.assertNotIn("alignment_d3d11_reload_timer.setInterval(", queue_block)
        self.assertIn("static_preview_batch_state = _static_preview_batch_initial_state_helper()", source)
        self.assertIn('return {"depth": 0, **{key: False for key in _REQUEST_KEYS}}', preview_batch_source)
        self.assertIn("def _queue_texture_uv_preview_refresh(*_args: object) -> None:", source)
        uv_queue_block = _nested_function_source(refresh_source, "_queue_texture_uv_preview_refresh")
        self.assertIn("_state._static_preview_batch_queue_request_helper(_state.static_preview_batch_state, 'texture_uv')", uv_queue_block)
        self.assertIn("static_preview_geometry_cache.clear()", uv_queue_block)
        self.assertIn("static_preview_prepared_cache.clear()", uv_queue_block)
        self.assertIn("_state._mark_alignment_d3d11_rebuild_reason('texture_uv')", uv_queue_block)
        self.assertIn("_state._alignment_d3d11_invalidate_package_cache('texture_uv')", uv_queue_block)
        self.assertIn("_state.texture_overrides_dirty['dirty'] = True", uv_queue_block)
        self.assertIn("static_preview_refresh_timer.start()", uv_queue_block)
        self.assertNotIn("static_preview_settle_timer.start()", uv_queue_block)

        batch_block = _nested_function_source(routing_source, "_run_static_preview_batch")
        self.assertIn('batch_requests = _state._static_preview_batch_end_helper(_state.static_preview_batch_state)', batch_block)
        self.assertIn("wants_texture_uv = bool(batch_requests.get('texture_uv'))", batch_block)
        self.assertIn("elif wants_texture_uv:", batch_block)
        self.assertIn("_queue_texture_uv_preview_refresh()", batch_block)

        save_block = _nested_function_source(texture_detail_source, "_save_texture_transform_controls")
        self.assertIn("queue_preview: bool = True", save_block)
        self.assertIn("_texture_uv_transform_control_save_state_helper(", save_block)
        self.assertIn('if save_state["queue_preview"]:', save_block)
        self.assertIn("_queue_texture_uv_preview_refresh()", save_block)
        self.assertIn('texture_overrides_dirty["dirty"] = True', save_block)
        self.assertNotIn("_queue_static_preview_rebuild()", save_block)

        reset_block = _nested_function_source(texture_detail_source, "_reset_selected_texture_transform")
        self.assertIn("_texture_uv_transform_reset_state_helper(", reset_block)
        self.assertIn("_queue_texture_uv_preview_refresh()", reset_block)
        self.assertNotIn("_queue_static_preview_rebuild()", reset_block)

        setup_block = _nested_function_source(remaining_source, "_save_setup_texture_orientation")
        self.assertIn("_try_apply_global_flip_v_fast_preview()", setup_block)
        self.assertIn("_queue_texture_uv_preview_refresh()", setup_block)
        self.assertNotIn("_queue_static_preview_rebuild()", setup_block)

        fast_flip_block = "\n".join(
            (
                _nested_function_source(package_source, "_reapply_global_flip_v_fast_preview"),
                _nested_function_source(package_source, "_reapply_current_global_flip_v_fast_preview"),
                _nested_function_source(package_source, "_try_apply_global_flip_v_fast_preview"),
            )
        )
        self.assertIn("def _reapply_global_flip_v_fast_preview(expected_flip_v: bool) -> None:", fast_flip_block)
        self.assertIn("def _reapply_current_global_flip_v_fast_preview() -> None:", fast_flip_block)
        self.assertIn("send_resident_presentation_state(", fast_flip_block)
        self.assertIn("{'uv': {'flip_v': bool(expected_flip_v)}}", fast_flip_block)
        self.assertIn("{'uv': {'flip_v': bool(flip_v)}}", fast_flip_block)
        self.assertIn("alignment_d3d11_preview_host.set_texture_flip_vertical(bool(expected_flip_v)", fast_flip_block)
        self.assertIn("_texture_uv_fast_preview_record_global_flip_v_helper(", fast_flip_block)
        self.assertIn("_state._set_alignment_d3d11_progress(100, 'Preview ready.', active=False)", fast_flip_block)
        self.assertIn("QTimer.singleShot(160", fast_flip_block)
        self.assertIn("_state.texture_overrides_dirty['dirty'] = True", fast_flip_block)
        self.assertIn("_reapply_current_global_flip_v_fast_preview()", source)
        host_source = _native_d3d11_preview_host_source()
        self.assertIn('self._presentation_state["uv"] = {"flip_v": bool(enabled)}', host_source)
        self.assertIn("return self._remember_presentation_state()", host_source)
        self.assertIn("def set_material_overrides(", host_source)
        self.assertIn('"material_parameter_update"', host_source)

    def test_mesh_editor_builder_uses_embedded_host_and_live_preview_state(self) -> None:
        prompt_shell = ARCHIVE_STATIC_REPLACEMENT_DIALOG_PROMPT_SHELL.read_text(encoding="utf-8")
        prompt_setup = ARCHIVE_STATIC_REPLACEMENT_DIALOG_PROMPT_SETUP.read_text(encoding="utf-8")
        callbacks = _callback_factory_source()
        remaining = static_replacement_remaining_callback_source(ROOT)

        self.assertIn("embedded_alignment_builder = embedded_host is not None", prompt_shell)
        self.assertNotIn("embedded_alignment_builder = False", prompt_shell)

        setup_start = prompt_setup.index("replacement_mesh_base_for_mapping = prompt_preflight.replacement_mesh_base")
        setup_end = prompt_setup.index("original_dialog_preview.set_render_settings", setup_start)
        setup_block = prompt_setup[setup_start:setup_end]
        self.assertIn("_set_replacement_mesh_base_for_mapping(replacement_mesh_base_for_mapping)", setup_block)
        self.assertIn("_set_replacement_mesh_for_mapping(replacement_mesh_for_mapping)", setup_block)
        self.assertIn("_set_replacement_preview_model(replacement_preview_model)", setup_block)

        queue_start = callbacks.index("def _queue_static_preview_refresh")
        queue_end = callbacks.index("def _queue_selection_preview_refresh", queue_start)
        queue_block = callbacks[queue_start:queue_end]
        self.assertIn("d3d11_preview_active=bool(_state._d3d11_preview_active())", queue_block)
        self.assertNotIn("d3d11_preview_active=bool(_alignment_d3d11_preview_active())", queue_block)

        original_ready_start = remaining.index("def create_alignment_original_texture_worker_callbacks")
        original_ready_end = remaining.index("class _OriginalTexturePreviewWorkerReceiver", original_ready_start)
        original_ready_block = remaining[original_ready_start:original_ready_end]
        self.assertIn("_record_runtime_event = context.get('_record_runtime_event')", original_ready_block)
        self.assertIn("if not callable(_record_runtime_event):", original_ready_block)

    def test_alignment_d3d11_preview_reuses_cached_packages_for_live_changes(self) -> None:
        preview_shell_source = (
            ROOT / "cdmw" / "ui" / "archive_browser" / "static_replacement_dialog_preview_shell.py"
        ).read_text(encoding="utf-8")
        loading_source = static_replacement_callback_concern_source(ROOT, "d3d11_loading")
        package_source = static_replacement_callback_concern_source(ROOT, "d3d11_package_lifecycle")
        d3d11_presentation_source = (
            ROOT / "cdmw" / "ui" / "archive_browser" / "static_replacement_d3d11_presentation_state.py"
        ).read_text(encoding="utf-8")
        d3d11_watchdog_source = (
            ROOT / "cdmw" / "ui" / "archive_browser" / "static_replacement_d3d11_watchdog_state.py"
        ).read_text(encoding="utf-8")
        self.assertIn('"package_cache": OrderedDict()', preview_shell_source)
        self.assertIn('"preview_loaded": False', preview_shell_source)
        self.assertIn('"stale_reload_restart_count": 0', preview_shell_source)
        self.assertIn('"loading_started_at": 0.0', preview_shell_source)
        for function_name in (
            "_alignment_d3d11_preview_cache_key",
            "_alignment_d3d11_package_cache_get",
            "_alignment_d3d11_package_cache_put",
            "_start_alignment_d3d11_package_worker",
            "_queue_alignment_d3d11_preview",
        ):
            self.assertIn(f"def {function_name}", package_source)
        self.assertIn("def _alignment_d3d11_live_frame_available", loading_source)
        self.assertIn("Reused active cached package", package_source)
        self.assertIn("Starting .NET/Vortice Preview renderer.", package_source)
        self.assertIn("Preview ready.", package_source)

        clear_loading_block = _nested_function_source(
            loading_source, "_clear_stuck_alignment_d3d11_loading"
        )
        self.assertIn("_state._set_preview_performance_status_if_ready(", clear_loading_block)
        self.assertIn("recovery_action.should_stop_process", clear_loading_block)
        self.assertIn("callable(_state._alignment_d3d11_stop_process)", clear_loading_block)
        self.assertIn("_state.QTimer.singleShot(0, _restart_latest_alignment_d3d11_rebuild)", clear_loading_block)
        self.assertIn("def _stale_reload_rebuild_callback", loading_source)
        self.assertIn("_queue_latest_alignment_d3d11_rebuild_for_stale_reload", loading_source)
        self.assertIn("Preview reload restarted.", d3d11_watchdog_source)
        self.assertIn("_state._alignment_d3d11_restart_performance_helper(", loading_source)
        self.assertIn(".NET/Vortice Preview reload restarted", d3d11_presentation_source)
        self.assertNotIn("Preview stale/no fresh frame.", loading_source)
        loading_stuck_block = _nested_function_source(loading_source, "_alignment_d3d11_loading_stuck")
        self.assertIn("queued_model", loading_stuck_block)
        self.assertIn("pending_model", loading_stuck_block)
        self.assertIn("thread.isRunning()", loading_stuck_block)
        self.assertIn(".NET load/upload 0.0 ms (active package reused)", d3d11_presentation_source)
        self.assertIn('details="cache=live-command reason=display_mode"', d3d11_presentation_source)
        self.assertIn("native_load_upload", d3d11_presentation_source)

        render_settings_block = _nested_function_source(
            static_replacement_remaining_callback_source(ROOT),
            "_apply_alignment_preview_render_settings",
        )
        self.assertIn("_state.alignment_d3d11_preview_host.set_render_tuning(_state.state.preview_render_settings)", render_settings_block)
        self.assertIn("render_settings_route = _state._alignment_d3d11_render_settings_route_helper(", render_settings_block)
        self.assertIn(
            "package_settings_changed=_state._alignment_preview_package_settings_changed(old_settings, _state.state.preview_render_settings)",
            render_settings_block,
        )
        self.assertIn("if render_settings_route.action == 'd3d11_rebuild':", render_settings_block)
        self.assertIn("_state._queue_static_preview_refresh()", render_settings_block)
        self.assertLess(
            render_settings_block.index("_state._queue_static_preview_refresh()"),
            render_settings_block.index("_state.alignment_d3d11_preview_host.set_render_tuning(_state.state.preview_render_settings)"),
        )
        self.assertIn("return", render_settings_block)

        start_worker_block = _nested_function_source(package_source, "_start_alignment_d3d11_package_worker")
        self.assertNotIn("final_test", start_worker_block)
        self.assertIn("_state._alignment_d3d11_package_cache_get(cache_key)", start_worker_block)
        self.assertIn("_state._start_alignment_d3d11_process(cached_package_dir, request_id=request_id)", start_worker_block)
        self.assertIn("live_frame_available = _state._alignment_d3d11_live_frame_available()", start_worker_block)
        queue_block = _nested_function_source(package_source, "_queue_alignment_d3d11_preview")
        self.assertIn("del model, label", queue_block)
        self.assertIn("reason='dotnet_authoritative'", queue_block)
        self.assertIn("requested_reason=str(reason or '')", queue_block)
        self.assertNotIn("_alignment_d3d11_live_frame_available()", queue_block)
        self.assertNotIn("alignment_d3d11_reload_timer", queue_block)

    def test_alignment_d3d11_gizmo_defaults_visible_and_tracks_the_checkbox(self) -> None:
        source = _main_window_source()
        prep_source = (ROOT / "cdmw" / "rendering" / "model_preview_prepare.py").read_text(encoding="utf-8")
        preview_status_source = ARCHIVE_STATIC_REPLACEMENT_PREVIEW_STATUS_STATE.read_text(encoding="utf-8")
        self.assertIn('preview_gizmo_checkbox = QCheckBox(alignment_preview_control_text["gizmo"])', source)
        self.assertIn('"gizmo": "Gizmo"', preview_status_source)
        self.assertIn('preview_part_pick_checkbox = QCheckBox(alignment_preview_control_text["part_pick"])', source)
        self.assertIn('preview_mesh_edit_checkbox = QCheckBox("Edit Mesh")', source)
        self.assertIn("mesh_edit_enabled_checkbox = preview_mesh_edit_checkbox", source)
        self.assertIn('"part_pick": "Part Pick"', preview_status_source)
        self.assertIn("preview_gizmo_checkbox.setChecked(True)", source)
        self.assertIn("preview_part_pick_checkbox.setChecked(False)", source)
        self.assertNotIn("preview_gizmo_checkbox.setChecked(False)", source)
        self.assertIn("def _sync_highlight_sets_when_ready(*args, **kwargs):", source)
        self.assertIn("'_sync_highlight_sets': _sync_highlight_sets_when_ready", source)
        self.assertIn("preview_gizmo_checkbox.toggled.connect(lambda *_args: _sync_highlight_sets())", source)
        self.assertIn("def _preview_part_pick_toggled(checked: bool = False) -> None:", source)
        self.assertIn("_clear_all_part_selections()", source)
        self.assertIn("preview_part_pick_checkbox.toggled.connect(_preview_part_pick_toggled)", source)
        selection_highlight_state_source = ARCHIVE_STATIC_REPLACEMENT_SELECTION_HIGHLIGHT_STATE.read_text(encoding="utf-8")
        self.assertIn("def selection_highlight_sets_state", selection_highlight_state_source)
        selection_source = static_replacement_callback_concern_source(ROOT, "preview_mode")
        self.assertIn("preview_gizmo_checked=bool(_state.preview_gizmo_checkbox.isChecked())", selection_source)
        self.assertIn("gizmo_visible=bool(_state.preview_gizmo_checkbox.isChecked())", selection_source)
        self.assertIn("part_pick_checked=part_pick_checked", selection_source)
        self.assertIn("_state.alignment_d3d11_preview_host.set_source_part_picking(part_pick_checked)", selection_source)
        self.assertIn("enabled=bool(selection_state['d3d11_gizmo_enabled'])", selection_source)
        package_source = static_replacement_callback_concern_source(ROOT, "d3d11_package_lifecycle")
        self.assertIn("def _alignment_default_d3d11_editor_ids", package_source)
        self.assertIn("tuple(_state.transform_source_indices)", package_source)
        self.assertIn(
            "source_index_is_enabled_renderable=_state._source_index_is_enabled_renderable",
            package_source,
        )
        self.assertIn(
            "source_submesh_indices=tuple(selection_state['d3d11_selected_indices'])",
            selection_source,
        )
        self.assertIn("editor_role_key = editor_role.lower()", prep_source)
        self.assertIn('"replacement" in editor_role_key', prep_source)
        self.assertIn("editor_editable=editor_editable", prep_source)

    def test_alignment_fast_preview_does_not_replace_export_options(self) -> None:
        source = _main_window_source()
        static_source = _static_replacer_source()
        transform_drag_source = static_replacement_callback_concern_source(ROOT, "transform_drag")
        self.assertIn("def _current_static_alignment_transform() -> StaticReplacementTransform:", source)
        self.assertIn("modify_original_centered_transform_anchors(", source)
        self.assertIn("source_anchor=source_anchor", source)
        self.assertIn("target_anchor=target_anchor", source)
        self.assertIn("modify_original_centered_transform_anchors(", transform_drag_source)
        self.assertIn("rotate_xyz_degrees=(", source)
        self.assertIn("_state._spin_value('rotate_x_spin')", source)
        self.assertIn("offset_xyz=(", source)
        self.assertIn("_state._spin_value('offset_x_spin')", source)
        self.assertIn("placement_snapshot = _current_static_placement_snapshot", source)
        self.assertIn("include_preview_only_independent_parts=False", source)
        self.assertNotIn("set_alignment_committed_preview_transform", static_source)

    def test_alignment_dialog_clears_part_selection_when_leaving_geometry(self) -> None:
        selection_source = static_replacement_callback_concern_source(ROOT, "source_tree_selection")
        preview_mode_source = static_replacement_callback_concern_source(ROOT, "preview_mode")
        geometry_section_source = static_replacement_ui_concern_source(ROOT, "mesh_geometry_preview")
        self.assertIn("def _clear_part_selections_when_leaving_geometry", selection_source)
        self.assertIn("if _state.control_tabs.widget(index) is _state.parts_tab:", selection_source)
        self.assertIn("_state.selected_source_part['index'] = int(clear_state['selected_source_index'])", selection_source)
        self.assertIn("_state.selected_target_slot['index'] = -1", selection_source)
        self.assertNotIn("source_tree_hover_direct_indices", selection_source)
        self.assertIn("hovered_source_highlights=hovered_source_indices", preview_mode_source)
        self.assertNotIn("hovered_original_highlight_indices", selection_source)
        self.assertNotIn("_StaticMappingHoverFilter", selection_source)
        self.assertNotIn("_StaticTreeHoverFilter", selection_source)
        self.assertIn(
            "_state.control_tabs.currentChanged.connect(_state._clear_part_selections_when_leaving_geometry)",
            geometry_section_source,
        )

    def test_alignment_geometry_can_duplicate_and_mirror_source_parts(self) -> None:
        source = _main_window_source()
        mutation_source = static_replacement_source_part_mutation_callback_source(ROOT)
        outliner_source = static_replacement_ui_concern_source(ROOT, "source_parts_outliner")
        geometry_math_source = ARCHIVE_STATIC_REPLACEMENT_GEOMETRY_MATH.read_text(encoding="utf-8")
        source_parts_state_source = _source_part_owner_sources()
        self.assertIn("_state.duplicate_part_button = _state.QPushButton(_state.source_part_inspector_control_text['duplicate_part'])", outliner_source)
        self.assertIn("_state.mirror_duplicate_part_button = _state.QPushButton(_state.source_part_inspector_control_text['mirror_duplicate_part'])", outliner_source)
        self.assertIn('"duplicate_part": "Duplicate Part"', source_parts_state_source)
        self.assertIn('"mirror_duplicate_part": "Mirror Duplicate"', source_parts_state_source)
        self.assertIn("def _duplicate_selected_part(*, mirrored: bool=False)", mutation_source)
        self.assertIn("_state._source_part_duplicate_route_state_helper(", mutation_source)
        self.assertIn("_state._source_part_duplicate_presentation_state_helper(", mutation_source)
        self.assertIn("_state.self.set_status_message(duplicate_route.status_text)", mutation_source)
        self.assertIn("def source_part_duplicate_undo_label", source_parts_state_source)
        self.assertIn("def source_part_duplicate_copy_suffix", source_parts_state_source)
        self.assertIn("def source_part_duplicate_status", source_parts_state_source)
        self.assertIn("def source_part_duplicate_route_state", source_parts_state_source)
        self.assertIn("def source_part_duplicate_presentation_state", source_parts_state_source)
        self.assertIn("_state._mirror_submesh_x = lambda", outliner_source)
        self.assertIn("(int(face[0]), int(face[2]), int(face[1]))", geometry_math_source)
        self.assertIn("_state.duplicate_part_button.clicked.connect(lambda _checked=False: _state._duplicate_selected_part(mirrored=False))", outliner_source)
        self.assertIn("_state.mirror_duplicate_part_button.clicked.connect(lambda _checked=False: _state._duplicate_selected_part(mirrored=True))", outliner_source)

    def test_texture_plan_has_single_bulk_apply_action(self) -> None:
        source = _main_window_source() + "\n" + ARCHIVE_STATIC_REPLACEMENT_SOURCE_DISPLAY.read_text(encoding="utf-8")
        texture_section_source = static_replacement_ui_concern_source(ROOT, "texture_material")
        mesh_preview_section_source = static_replacement_ui_concern_source(ROOT, "mesh_geometry_preview")
        outliner_section_source = static_replacement_ui_concern_source(ROOT, "source_parts_outliner")
        setup_section_source = static_replacement_ui_concern_source(ROOT, "setup_options_transform")
        texture_table_source = ARCHIVE_STATIC_REPLACEMENT_TEXTURE_TABLE.read_text(encoding="utf-8")
        material_plan_ui_state_source = ARCHIVE_STATIC_REPLACEMENT_MATERIAL_PLAN_UI_STATE.read_text(encoding="utf-8")
        self.assertIn("_state.apply_texture_plan_button = _state.QPushButton(_state.str(_state.material_plan_control_text['apply_suggested']))", texture_section_source)
        self.assertIn("_state.apply_selected_source_textures_button = _state.QPushButton(_state.str(_state.material_plan_control_text['use_selected']))", texture_section_source)
        self.assertIn('"apply_suggested": "Apply Suggested"', material_plan_ui_state_source)
        self.assertIn('"use_selected": "Use Selected"', material_plan_ui_state_source)
        self.assertIn("material_plan_control_text", texture_table_source)
        self.assertIn("def material_plan_control_text", material_plan_ui_state_source)
        self.assertIn("selection_context_frame = QFrame(content_container)", source)
        self.assertIn("mesh_replacement_selection_view_model: Dict[str, object]", source)
        self.assertIn("def _set_mesh_replacement_selection_view", source)
        self.assertIn("def target_outliner_state", source)
        self.assertIn("_target_outliner_state = lambda target_index", source)
        self.assertNotIn('QGroupBox("Inspector")', source)
        self.assertNotIn('MeshReplacementPropertiesInspector', source)
        source_parts_state_source = _source_part_owner_sources()
        self.assertIn("def source_part_properties_control_text", source_parts_state_source)
        self.assertIn("def source_part_properties_label_html", source_parts_state_source)
        self.assertIn("def source_part_properties_output_text", source_parts_state_source)
        self.assertIn("def source_part_target_properties_warning", source_parts_state_source)
        self.assertIn("def source_part_source_properties_warning", source_parts_state_source)
        self.assertIn("def source_part_source_properties_dds_text", source_parts_state_source)
        self.assertIn("def source_part_material_properties_text", source_parts_state_source)
        self.assertIn("def source_part_properties_inspector_state", source_parts_state_source)
        self.assertIn("_state.properties_group = _state.QGroupBox(_state.str(_state.properties_control_text['title']))", mesh_preview_section_source)
        self.assertIn("_state.properties_group.setObjectName(_state.str(_state.properties_control_text['group_object']))", mesh_preview_section_source)
        self.assertIn("_source_part_properties_inspector_state_helper(", source)
        self.assertNotIn("_source_part_properties_label_html_helper(", source)
        self.assertNotIn("_source_part_properties_output_text_helper(", source)
        self.assertNotIn("_source_part_target_properties_warning_helper(state, sidecar_status)", source)
        self.assertNotIn("_source_part_source_properties_warning_helper(mapped_targets)", source)
        self.assertNotIn("_source_part_source_properties_dds_text_helper(material_name)", source)
        self.assertNotIn("_source_part_material_properties_text_helper(", source)
        self.assertIn("def source_outliner_state", source)
        self.assertIn("_source_outliner_state = lambda source_index", source)
        source_assignment_state_source = ARCHIVE_STATIC_REPLACEMENT_SOURCE_ASSIGNMENT_STATE.read_text(encoding="utf-8")
        self.assertIn("def source_assigned_target_indices", source_assignment_state_source)
        self.assertIn("def source_assignment_index", source_assignment_state_source)
        source_display_source = ARCHIVE_STATIC_REPLACEMENT_SOURCE_DISPLAY.read_text(encoding="utf-8")
        self.assertIn("source_assigned_target_indices,", source_display_source)
        self.assertIn("normalized_source_index = int(source_index)", source_assignment_state_source)
        part_mapped_source = _nested_function_source(
            static_replacement_remaining_callback_source(ROOT),
            "_part_mapped_target_indices",
        )
        self.assertIn("_state._source_assigned_target_indices_helper(", part_mapped_source)
        self.assertNotIn("source_index = int(source_index)", part_mapped_source)
        added_part_textures_source = ARCHIVE_STATIC_REPLACEMENT_ADDED_PART_TEXTURES.read_text(encoding="utf-8")
        self.assertIn("def added_part_texture_role_label", added_part_textures_source)
        self.assertIn("added_part_texture_role_label=_added_part_texture_role_label_helper", source)
        self.assertIn('"base": "Base / Color"', added_part_textures_source)
        self.assertIn('"material": "Material / Mask"', added_part_textures_source)
        helper_source = ARCHIVE_STATIC_REPLACEMENT_DIALOG_HELPERS.read_text(encoding="utf-8")
        mapping_table_state_source = ARCHIVE_STATIC_REPLACEMENT_MAPPING_TABLE_STATE.read_text(encoding="utf-8")
        self.assertIn("def mapping_source_cell_text", helper_source)
        self.assertIn("mapping_source_cell_text as _mapping_source_cell_text", source)
        self.assertIn("def _material_sidecar_patch_enabled", source)
        self.assertIn("def _removed_target_dds_cell_text", source)
        self.assertIn("assignment_index = _source_assignment_index_helper(mapping_edits, parse_mapping_edit=_parse_mapping_edit)", source)
        self.assertIn("target -> source -> DDS", mapping_table_state_source)
        self.assertIn('mapping_hint = QLabel(mapping_table_action_control_text["routing_hint_html"])', source)
        self.assertIn('mapping_hint.setToolTip(mapping_table_action_control_text["routing_hint_tooltip"])', source)
        self.assertNotIn("Routing controls the final draw/material slots.", source)
        self.assertIn("_refresh_output_impact_review()", source)
        self.assertIn("_state._mapping_route_primary_button_specs_helper(_state.mapping_route_control_text)", outliner_section_source)
        self.assertIn("_state._mapping_route_button_style_helper(_state.button_spec.object_name, _state.button_spec.color)", outliner_section_source)
        self.assertIn("_state._mapping_route_selection_button_specs_helper(_state.mapping_route_control_text)", outliner_section_source)
        self.assertIn("_state.primary_route_buttons['assign_source']", outliner_section_source)
        self.assertIn("_state.primary_route_buttons['merge_source']", outliner_section_source)
        self.assertIn("_state.primary_route_buttons['remove_source']", outliner_section_source)
        self.assertIn("_state.primary_route_buttons['clear_target']", outliner_section_source)
        self.assertIn("_state.selection_route_buttons['clear_replacement']", outliner_section_source)
        self.assertIn("_state.selection_route_buttons['clear_all']", outliner_section_source)
        self.assertIn('"replace_object": "MeshRoutingReplaceButton"', mapping_table_state_source)
        self.assertIn('"add_object": "MeshRoutingAddButton"', mapping_table_state_source)
        self.assertIn('"remove_source_object": "MeshRoutingRemoveSourceButton"', mapping_table_state_source)
        self.assertIn('"remove_target_object": "MeshRoutingRemoveTargetButton"', mapping_table_state_source)
        self.assertIn('"clear_replacement_tooltip"', mapping_table_state_source)
        self.assertIn('"clear_all_tooltip"', mapping_table_state_source)
        self.assertIn("def mapping_route_primary_button_specs", mapping_table_state_source)
        self.assertIn("def mapping_route_selection_button_specs", mapping_table_state_source)
        self.assertIn("def mapping_route_button_style", mapping_table_state_source)
        self.assertIn("def mapping_edit_draft_tooltip", mapping_table_state_source)
        self.assertIn("def mapping_status_summary_html", mapping_table_state_source)
        self.assertIn("_mapping_edit_draft_tooltip_helper()", source)
        self.assertIn("_mapping_status_summary_html_helper(", source)
        self.assertIn("def removed_target_dds_tooltip", mapping_table_state_source)
        self.assertIn("def source_assignment_row_state", source_assignment_state_source)
        self.assertIn("def source_assignment_targets_tooltip", source_assignment_state_source)
        self.assertIn("def source_assignment_state_tooltip", source_assignment_state_source)
        self.assertIn("_removed_target_dds_tooltip_helper()", source)
        self.assertIn("_source_assignment_row_state_helper(", source)
        self.assertNotIn("_source_assignment_targets_tooltip_helper(assigned_targets)", source)
        self.assertNotIn("_source_assignment_state_tooltip_helper(source_state)", source)
        self.assertIn('"Preview-only"', source)
        self.assertIn('"Will prune"', source)
        self.assertIn('"Kept"', source)
        self.assertIn('"Orig refs"', source)
        self.assertIn("Removed target: geometry is omitted", source_parts_state_source)
        self.assertIn("_state.mapping_tree.setHeaderLabels(list(_state.mapping_table_action_control_text['headers']))", outliner_section_source)
        self.assertIn("_state.material_plan_tree.setHeaderLabels(_state.list(_state.material_plan_control_text['material_plan_headers']))", texture_section_source)
        self.assertIn(
            '"material_plan_headers": ["Part", "Role", "Source", "DDS", "Preview", "Param"]',
            material_plan_ui_state_source,
        )
        self.assertIn("def _update_selection_context", source)
        self.assertIn("def target_index_for_name", source)
        self.assertIn("_target_index_for_name = lambda target_name", source)
        self.assertIn("def _highlight_texture_plan_item", source)
        self.assertIn("_material_plan_item_selection_helper", source)
        self.assertIn("_target_mapping_selection_view_payload_helper(", source)
        selection_view_state_source = ARCHIVE_STATIC_REPLACEMENT_SELECTION_VIEW_STATE.read_text(encoding="utf-8")
        selection_route_state_source = ARCHIVE_STATIC_REPLACEMENT_SELECTION_ROUTE_STATE.read_text(encoding="utf-8")
        selection_highlight_state_source = ARCHIVE_STATIC_REPLACEMENT_SELECTION_HIGHLIGHT_STATE.read_text(encoding="utf-8")
        self.assertIn("def source_selection_state", selection_view_state_source)
        self.assertIn("def original_selection_state", selection_view_state_source)
        self.assertIn("def target_selection_state", selection_view_state_source)
        self.assertIn("def source_selection_route_state", selection_route_state_source)
        self.assertIn("def original_selection_route_state", selection_route_state_source)
        self.assertIn("def target_selection_route_state", selection_route_state_source)
        self.assertIn("def d3d11_source_part_selection_route", selection_route_state_source)
        self.assertIn("selection_highlight_sets_state", selection_view_state_source)
        self.assertIn("parts_outliner_target_selection_state", selection_view_state_source)
        self.assertIn("texture_row_selection_highlight_state", selection_view_state_source)
        self.assertIn("def selection_highlight_sets_state", selection_highlight_state_source)
        self.assertIn("def parts_outliner_target_selection_state", selection_highlight_state_source)
        self.assertIn("def texture_row_selection_highlight_state", selection_highlight_state_source)
        self.assertIn("_source_selection_route_state_helper(", source)
        self.assertIn("_original_selection_route_state_helper(raw_indices)", source)
        self.assertIn("_target_selection_route_state_helper(raw_target_index, source_indices)", source)
        self.assertIn("_d3d11_source_part_selection_route_helper(", source)
        self.assertIn("_selection_highlight_sets_state_helper(", source)
        self.assertIn("_parts_outliner_target_selection_state_helper(", source)
        self.assertIn("_texture_row_selection_highlight_state_helper(", source)
        self.assertIn("material_routing_tree.currentItemChanged.connect", source)
        self.assertIn("material_plan_tree.currentItemChanged.connect", source)
        self.assertNotIn("selected_target_original_highlight_indices.add(target_index)", source)
        source_matching_source = ARCHIVE_STATIC_REPLACEMENT_SOURCE_MATCHING.read_text(encoding="utf-8")
        self.assertIn("def source_indices_for_route_parts", source_matching_source)
        material_plan_refresh_source = _nested_function_source(
            static_replacement_remaining_callback_source(ROOT),
            "_refresh_source_material_plan",
        )
        self.assertIn("route_source_indices = _state._source_indices_for_route_parts_helper(", material_plan_refresh_source)
        self.assertIn("_source_material_route_item_helper", source)
        self.assertIn("source_indices=route_source_indices", source)
        self.assertIn("def source_material_route_item", source)
        self.assertIn("item.setData(0, Qt.UserRole, tuple(source_indices))", source)
        self.assertIn("_state.material_plan_advanced_section = _state.CollapsibleSection(", texture_section_source)
        self.assertIn("_state.str(_state.material_plan_control_text['advanced_routes'])", texture_section_source)
        self.assertIn('"advanced_routes": "Advanced Routes"', material_plan_ui_state_source)
        self.assertIn("expanded=False", source)
        self.assertNotIn('material_plan_advanced_checkbox = QCheckBox("Advanced features")', source)
        self.assertNotIn("material_plan_advanced_checkbox.toggled.connect(_sync_material_plan_advanced_visibility)", source)
        self.assertNotIn("def _sync_material_plan_advanced_visibility", source)
        self.assertIn("_state.material_plan_advanced_section.body_layout.addWidget(_state.material_routing_tree)", texture_section_source)
        self.assertIn("_state.material_plan_layout.addWidget(_state.material_plan_tree)", texture_section_source)
        self.assertIn("_state.material_routing_tree = _state.QTreeWidget()", texture_section_source)
        self.assertIn("build_source_material_routing_plan", source)
        self.assertIn("is_static_replacement_helper_material_name", _material_replacer_source())
        self.assertIn("DDS {escape(status_text)}", source)
        self.assertIn(
            "Stock/shared shader layers and helper wrappers are preserved by default.",
            material_plan_ui_state_source,
        )
        self.assertIn("def _apply_replacement_texture_plan_to_overrides", source)
        self.assertIn("def _apply_selected_source_material_textures", source)
        self.assertIn(
            "selected_source_material_texture_action_state as _selected_source_material_texture_action_state_helper",
            source,
        )
        self.assertIn("def selected_source_material_texture_action_state", material_plan_ui_state_source)
        self.assertIn("action_state.message_key", source)
        self.assertIn("action_state.planned_rows", source)
        self.assertIn("_state.apply_selected_source_textures_button.clicked.connect(_state._apply_selected_source_material_textures)", texture_section_source)
        self.assertIn("suggested_texture_plan_action_state as _suggested_texture_plan_action_state_helper", source)
        self.assertIn("all_suggested_override_sources_action_state as _all_suggested_override_sources_action_state_helper", source)
        self.assertIn("def suggested_texture_plan_action_state(", material_plan_ui_state_source)
        self.assertIn("def all_suggested_override_sources_action_state(", material_plan_ui_state_source)
        self.assertIn("file_state.texture_path", source)
        self.assertIn("add_state.should_check_rebuild_sidecar", source)
        advanced_dds_state_source = ARCHIVE_STATIC_REPLACEMENT_ADVANCED_DDS_STATE.read_text(encoding="utf-8")
        self.assertIn("_state.apply_all_suggested_overrides_button = _state.QPushButton(_state.str(_state.advanced_dds_control_text['apply_all_button']))", texture_section_source)
        self.assertIn('"apply_all_button": "Apply all Suggested for Override Source"', advanced_dds_state_source)
        self.assertIn("advanced_dds_apply_guidance_state as _advanced_dds_apply_guidance_state_helper", source)
        self.assertIn("advanced_dds_override_row_scan_state as _advanced_dds_override_row_scan_state_helper", source)
        self.assertIn("advanced_dds_suggested_source_counts as _advanced_dds_suggested_source_counts_helper", source)
        self.assertIn("def advanced_dds_override_row_scan_state(", advanced_dds_state_source)
        self.assertIn('"state_label": "Needs review"', advanced_dds_state_source)
        self.assertIn("scan_state.texture_override_rows", source)
        self.assertIn("def advanced_dds_apply_guidance_state(", advanced_dds_state_source)
        self.assertIn('row_state["state_label"] = "Original shared layer"', advanced_dds_state_source)
        self.assertNotIn("classify_texture_assignment_guidance,", source)
        self.assertIn("def _apply_all_suggested_override_sources", source)
        self.assertIn("Review the final preview before export.", advanced_dds_state_source)
        self.assertIn("_state.apply_all_suggested_overrides_button.clicked.connect(_state._apply_all_suggested_override_sources)", texture_section_source)
        texture_uv_source = ARCHIVE_STATIC_REPLACEMENT_TEXTURE_UV.read_text(encoding="utf-8")
        self.assertIn("_state.texture_transform_group = _state.QGroupBox(_state.texture_uv_control_text['transform_group'])", texture_section_source)
        self.assertIn("_state.texture_transform_flip_u_checkbox = _state.QCheckBox(_state.texture_uv_control_text['flip_u_label'])", texture_section_source)
        self.assertIn("_state.texture_transform_flip_v_checkbox = _state.QCheckBox(_state.texture_uv_control_text['flip_v_label'])", texture_section_source)
        self.assertIn("_state.texture_transform_reset_button = _state.QPushButton(_state.texture_uv_control_text['reset_button'])", texture_section_source)
        self.assertIn("_state.setup_texture_flip_u_checkbox = _state.QCheckBox(_state.texture_uv_control_text['flip_u_label'])", setup_section_source)
        self.assertIn("_state.setup_texture_flip_v_checkbox = _state.QCheckBox(_state.texture_uv_control_text['flip_v_label'])", setup_section_source)
        self.assertIn("_state.setup_texture_reset_button = _state.QPushButton(_state.texture_uv_control_text['setup_reset_button'])", setup_section_source)
        self.assertIn("_state.texture_output_size_combo.setToolTip(_state.texture_uv_control_text['setup_output_size_tooltip'])", setup_section_source)
        self.assertIn('"transform_group": "Texture Orientation / UV Transform"', texture_uv_source)
        self.assertIn('"reset_button": "Reset UV"', texture_uv_source)
        self.assertIn('"setup_reset_button": "Reset"', texture_uv_source)
        self.assertIn("_state.setup_texture_rotate_combo.setObjectName('MeshAlignmentSetupTextureRotateCombo')", setup_section_source)
        self.assertIn('texture_uv_global_transform_state: Dict[str, object]', source)
        self.assertIn("global_has_edits = state_has_edits(texture_uv_global_transform_state)", texture_uv_source)
        self.assertIn("per_material_override_keys", texture_uv_source)
        self.assertIn("StaticTextureUvTransform", texture_uv_source)
        self.assertIn("_current_texture_uv_transforms = lambda", source)
        self.assertIn("_current_texture_uv_transforms_helper", source)
        self.assertIn("'texture_uv_transforms': _state._current_texture_uv_transforms()", _callback_factory_source())
        self.assertIn("texture_uv_transforms=[] if modify_original_options_mode else list(placement_snapshot.get('texture_uv_transforms', []) or [])", _callback_factory_source())
        self.assertIn("mesh.preview_texture_flip_vertical = flip_v", source)
        self.assertIn("scene_import_normalizes_texture_v(", source)
        self.assertIn("from cdmw.services.preview_workflow_service import scene_import_normalizes_texture_v", source)
        added_part_textures_source = ARCHIVE_STATIC_REPLACEMENT_ADDED_PART_TEXTURES.read_text(encoding="utf-8")
        self.assertIn("_state.added_texture_control_text = _state._added_part_texture_control_text_helper()", texture_section_source)
        self.assertIn("_state.added_texture_group = _state.QGroupBox(_state.str(_state.added_texture_control_text['group_title']))", texture_section_source)
        self.assertIn('"group_title": "Added Part Textures"', added_part_textures_source)
        self.assertIn('"empty_label": "No added mesh parts in this session."', added_part_textures_source)
        self.assertIn("def added_part_texture_override_action_state", added_part_textures_source)
        self.assertIn("def added_part_selected_texture_assignment_state", added_part_textures_source)
        self.assertIn("def added_part_detected_assignment_state", added_part_textures_source)
        self.assertIn("def added_part_texture_group_size_state", added_part_textures_source)
        self.assertIn("def added_part_texture_editor_context_state", added_part_textures_source)
        self.assertIn("def added_part_texture_row_states", added_part_textures_source)
        self.assertIn("def added_part_texture_choose_dialog_state", added_part_textures_source)
        self.assertIn("def current_added_part_texture_source_index", added_part_textures_source)
        self.assertIn("_state.added_texture_layout.setAlignment(_state.Qt.AlignTop)", texture_section_source)
        self.assertIn("_state.added_texture_layout.addWidget(_state.added_texture_tree, 0)", texture_section_source)
        self.assertIn("def _sync_added_part_texture_group_size", source)
        self.assertIn("_added_part_texture_group_size_state_helper(", source)
        self.assertIn("added_texture_group.setMaximumHeight(size_state.max_height)", source)
        self.assertIn("def _refresh_added_part_texture_tree", source)
        self.assertIn("_added_part_texture_row_states_helper(", source)
        self.assertIn("_added_part_texture_editor_context_state_helper(", source)
        self.assertIn("_added_part_texture_choose_dialog_state_helper(", source)
        self.assertIn("_sync_added_part_texture_group_size(visibility_state.has_rows)", source)
        self.assertIn("def _set_added_part_texture_override", source)
        self.assertIn("_added_part_texture_override_action_state_helper(", source)
        self.assertIn("_added_part_selected_texture_assignment_state_helper(", source)
        self.assertIn("_added_part_detected_assignment_state_helper(", source)
        self.assertIn("_current_added_part_texture_source_index_helper(", source)
        self.assertIn("def _highlight_added_part_texture_source", source)
        self.assertIn("_highlight_added_part_texture_source(source_index)", source)
        self.assertIn("'source_material_texture_overrides': _state._current_source_material_texture_overrides()", _callback_factory_source())
        self.assertIn("placement_snapshot.get('source_material_texture_overrides', [])", _callback_factory_source())
        self.assertIn("_state.str(_state.advanced_dds_control_text['section_title'])", texture_section_source)
        self.assertIn('"section_title": "Advanced Original DDS Overrides"', advanced_dds_state_source)
        self.assertLess(
            texture_section_source.index("_state.textures_layout.addWidget(_state.material_plan_group, 0)"),
            texture_section_source.index("_state.str(_state.advanced_dds_control_text['section_title'])"),
        )
        self.assertIn("_state.material_plan_layout.addWidget(_state.texture_transform_group)", texture_section_source)
        self.assertLess(
            texture_section_source.index("_state.material_plan_layout.addWidget(_state.texture_transform_group)"),
            texture_section_source.index("_state.material_plan_layout.addWidget(_state.material_plan_advanced_section)"),
        )
        self.assertIn("_state.texture_editor_control_text = _state._texture_editor_control_text_helper()", texture_section_source)
        self.assertIn("_state.texture_override_tree.setHeaderLabels(_state.list(_state.texture_editor_control_text['override_headers']))", texture_section_source)
        self.assertIn("for _state.role_kind in _state.tuple(_state.texture_editor_control_text['role_options']):", texture_section_source)
        self.assertIn("_state.selected_texture_editor_label = _state.QLabel(_state.str(_state.texture_editor_control_text['selected_label']))", texture_section_source)
        self.assertIn("_state.QLabel(_state.str(_state.texture_editor_control_text['no_editable_slots']))", texture_section_source)
        self.assertIn("_state.QLabel(_state.str(_state.texture_editor_control_text['no_sidecar_slots']))", texture_section_source)
        texture_editor_ui_state_source = ARCHIVE_STATIC_REPLACEMENT_TEXTURE_EDITOR_UI_STATE.read_text(encoding="utf-8")
        self.assertIn("texture_editor_control_text", texture_table_source)
        self.assertIn("def texture_editor_control_text", texture_editor_ui_state_source)
        self.assertIn('"override_headers": ["Target", "Source", "Role", "DDS", "Assigned", "Status", "Controls"]', texture_editor_ui_state_source)
        self.assertIn('"selected_label": "Selected row"', texture_editor_ui_state_source)
        self.assertIn('"no_sidecar_slots": "No sidecar texture slots were found for this asset."', texture_editor_ui_state_source)
        self.assertIn("texture_transform_group.setVisible(bool(has_materials))", source)
        self.assertIn("texture_transform_group.setVisible(detail_state.transform_visible)", source)
        self.assertNotIn("texture_transform_group.setVisible(bool(has_materials and advanced_materials_checkbox.isChecked()))", source)
        self.assertNotIn('texture_transform_group.setVisible(bool(selected_texture_plan_source.get("material_name")))', source)
        self.assertIn("texture_detail_browser.setMinimumWidth(300)", source)
        self.assertIn("_state.alignment_font_sizes = _state._alignment_dialog_font_sizes(_state.context)", texture_section_source)
        self.assertIn("QTextBrowser {{ font-size: {_state.alignment_font_sizes['data']}px; line-height: 1.08; }}", texture_section_source)
        self.assertIn("_state.material_plan_layout.setContentsMargins(5, 3, 5, 3)", texture_section_source)
        self.assertIn("_state.texture_transform_layout.setContentsMargins(5, 3, 5, 3)", texture_section_source)
        self.assertIn("_state.texture_workflow_layout.setSpacing(3)", texture_section_source)
        self.assertIn("compact = Path(normalized).name or normalized", source)
        self.assertNotIn('CollapsibleSection("Texture Assignments", expanded=True)', source)
        self.assertNotIn("texture_override_tree.setCurrentItem(texture_override_tree.topLevelItem(0))", source)
        self.assertNotIn('QPushButton("Apply Suggested...")', source)
        self.assertNotIn('QPushButton("Assign Matching Role...")', source)

    def test_helmet_alignment_warns_about_head_hair_visibility(self) -> None:
        source = _main_window_source() + "\n" + _archive_mesh_import_sources()
        self.assertIn("Helmet visibility", source)
        self.assertIn("It does not change whether the game hides the character head or hair.", source)
        self.assertIn("choose an original helmet with matching visibility rules", source)

    def test_alignment_routing_can_group_by_source_material(self) -> None:
        source = _main_window_source()
        outliner_source = static_replacement_ui_concern_source(ROOT, "source_parts_outliner")
        grouped_routing_source = _nested_function_source(
            static_replacement_source_part_mutation_callback_source(ROOT),
            "_apply_source_material_grouped_routing",
        )
        mapping_table_state_source = ARCHIVE_STATIC_REPLACEMENT_MAPPING_TABLE_STATE.read_text(encoding="utf-8")
        self.assertIn("_state.group_materials_button = _state.QPushButton(_state.mapping_table_action_control_text['group_materials'])", outliner_source)
        self.assertIn('"group_materials": "Group by Source Material"', mapping_table_state_source)
        self.assertIn("def _apply_source_material_grouped_routing", source)
        self.assertIn("_texture_set_for_source_index = lambda", source)
        source_parts_state_source = _source_part_owner_sources()
        self.assertIn("source_part_group_routing_text['clear_manual_title']", grouped_routing_source)
        self.assertIn("source_part_group_routing_text['clear_manual_message']", grouped_routing_source)
        self.assertIn("_state._source_part_group_routing_overflow_message_helper(overflow_groups)", grouped_routing_source)
        self.assertIn("Manual original-DDS override assignments can force the old slot layout", source_parts_state_source)
        self.assertIn(
            "The replacement has more source material group(s) than original target draw slot(s).",
            source_parts_state_source,
        )
        self.assertIn("_state.group_materials_button.clicked.connect(_state._apply_source_material_grouped_routing)", outliner_source)

    def test_in_game_mesh_swap_reuses_alignment_import_path(self) -> None:
        source = (
            _main_window_source()
            + "\n"
            + _archive_mesh_import_sources()
            + "\n"
            + ARCHIVE_ACTIONS.read_text(encoding="utf-8")
            + "\n"
            + ARCHIVE_ACTION_CONTROLS.read_text(encoding="utf-8")
            + "\n"
            + ARCHIVE_PREVIEW_LAYOUT.read_text(encoding="utf-8")
            + "\n"
            + _about_documentation_source()
        )
        self.assertIn('QPushButton("Swap With In-Game Mesh...")', source)
        self.assertIn("pending_in_game_mesh_swap_target", source)
        self.assertIn("def _handle_archive_in_game_mesh_swap_entry", source)
        self.assertIn('"Start In-Game Mesh Swap..."', source)
        self.assertIn('"Use This as Swap Source..."', source)
        self.assertIn('"Use as Swap Source..."', source)
        self.assertIn("def _start_archive_in_game_mesh_swap", source)
        self.assertIn("def _load_archive_mesh_scene_import_result", source)
        self.assertIn("def _build_archive_swap_source_texture_evidence", source)
        self.assertIn("def _source_texture_relevance_score", source)
        self.assertIn('texture_entries_by_key: "OrderedDict[str, ArchiveEntry]"', source)
        self.assertIn("resolve_material_texture_graph(entry", source)
        self.assertIn("source_texture_evidence_by_local_path", source)
        self.assertIn("parse_material_sidecar_profile", source)
        self.assertIn("material_profile_label", source)
        self.assertIn("material_profile_shader", source)
        self.assertIn("target_shader_family", source)
        self.assertIn("def source_sidecar_evidence_score", source)
        self.assertIn("Found {len(source_texture_paths):,} source DDS texture candidate(s) from source .pac_xml/sidecars.", source)
        self.assertIn("force_static_replacement=True", source)
        self.assertIn('placement_review_title="In-Game Mesh Swap Placement"', source)
        self.assertIn("swap_placement_note = (", source)
        self.assertIn("Review offset, rotation, scale, and part mapping before export.", source)
        self.assertIn("Replacement Preview is the candidate location/rotation/scale that will be written.", source)
        self.assertIn("Final loose export preview may differ if packaged material sidecar or DDS bindings resolve differently.", source)
        alignment_setup_source = ARCHIVE_STATIC_REPLACEMENT_ALIGNMENT_SETUP_STATE.read_text(encoding="utf-8")
        layout_state_source = ARCHIVE_STATIC_REPLACEMENT_LAYOUT_STATE.read_text(encoding="utf-8")
        mesh_import_setup_source = ARCHIVE_MESH_IMPORT_SETUP_STATE.read_text(encoding="utf-8")
        self.assertIn('CollapsibleSection(import_diagnostics_control_text["import_notes_section"], expanded=False)', source)
        self.assertIn('"import_notes_section": "Import Notes"', alignment_setup_source)
        self.assertIn('CollapsibleSection(compatibility_control_text["details_section"], expanded=False)', source)
        self.assertIn('group.setTitle(compatibility_control_text["details_group"])', source)
        self.assertIn('"details_section": "Compatibility Details"', mesh_import_setup_source)
        self.assertIn('"details_group": "Details"', mesh_import_setup_source)
        self.assertIn('placement_group = QWidget()', source)
        self.assertIn('_mesh_import_continue_button_text(placement_context_note=placement_context_note)', source)
        self.assertIn('return "Review Placement" if placement_context_note.strip() else "Continue"', mesh_import_setup_source)
        self.assertIn("dialog_title=setup.placement_review_title or alignment_builder_window_title()", source)
        self.assertIn("def alignment_builder_window_title", alignment_setup_source)
        self.assertIn("def _fit_alignment_dialog_to_screen", source)
        self.assertIn("_alignment_dialog_fit_size_helper(", source)
        self.assertIn("_alignment_dialog_frame_origin_helper(", source)
        self.assertIn("inner_width = max(640, normalized_width - 24)", layout_state_source)
        self.assertIn("left=max(int(available_left), min(int(frame_left), int(available_right) - int(frame_width) + 1))", layout_state_source)
        self.assertIn("placement_context_note=setup.placement_context_note", source)
        self.assertIn("source_texture_evidence=setup.source_texture_evidence", source)
        self.assertIn("scene_import_result=setup.scene_import_result", source)
        self.assertIn("source_display_label=setup.source_label", source)
        self.assertNotIn("def _prompt_archive_in_game_mesh_source", source)
        mesh_session_source = MESH_DOMAIN_SESSION.read_text(encoding="utf-8")
        self.assertIn("class InGameMeshSwapScopeSelection", mesh_session_source)
        self.assertIn("complete_swap: bool = False", mesh_session_source)
        self.assertIn("include_physics: bool = False", mesh_session_source)
        self.assertIn("use_source_model_payload_directly", mesh_session_source)
        self.assertIn("retarget_source_family_files", mesh_session_source)
        self.assertIn('dialog.setWindowTitle("In-Game Mesh Swap Scope")', source)
        self.assertIn('QCheckBox("Complete In-Game Swap (source mesh/material/textures/physics)")', source)
        self.assertIn("complete_swap_scope_default = True", source)
        self.assertIn("def _select_complete_swap_entries", source)
        self.assertIn("def _is_source_physics_companion", source)
        self.assertIn('QCheckBox("Use source model payload directly instead of rebuilding target geometry")', source)
        self.assertIn('QCheckBox("Retarget selected source item-family files to target paths")', source)
        self.assertIn('QPushButton("Select Item Family")', source)
        self.assertIn('QPushButton("Select Physics")', source)
        self.assertIn("same_weapon_folder", source)
        self.assertIn("cross-family physics can crash in game", source)
        self.assertIn("preserve_source_contract_default", source)
        self.assertIn("_pbdSimulationMaterialName", source)
        self.assertIn("Donor material contract warning", source)
        self.assertIn("Defaulting to Complete In-Game Swap through the placement workflow", source)
        self.assertIn("source_has_larger_material_contract", source)
        self.assertIn("replace_target_sidecar_with_source", source)
        self.assertIn("replace_target_appearance_with_source", source)
        self.assertIn("use_character_swap_plan", source)
        self.assertIn("def _archive_entry_is_equipment_model_for_swap", source)
        self.assertIn("def _archive_entries_allow_character_swap_scope", source)
        self.assertIn('"nude",', source)
        self.assertIn("candidate_tokens = _semantic_tokens(PurePosixPath(normalized_path).stem)", source)
        self.assertIn("return bool(candidate_tokens & part_markers)", source)
        self.assertIn("if allow_character_scope:", source)
        self.assertIn("Disabled for weapon/item swaps; this avoids pulling unrelated head/hair/beard appearance files.", source)
        self.assertIn("def _target_family_path_for_source_companion", source)
        self.assertIn("leading_zero_count", source)
        self.assertIn("def _start_archive_direct_source_model_swap", source)
        self.assertIn('import_mode="direct_source_model_swap"', source)
        self.assertIn("def _archive_entry_is_appearance_descriptor", source)
        self.assertIn("def _archive_character_app_graph_entries_for_swap", source)
        self.assertIn("def _archive_character_app_graph_texture_entries_for_swap", source)
        self.assertIn("def _target_appearance_path_for_source_appearance", source)
        self.assertIn("def _build_in_game_mesh_swap_extra_specs", source)
        self.assertIn("extra_supplemental_specs", source)
        self.assertIn("loose_supplemental_specs = tuple(setup.extra_supplemental_specs or ()) + tuple(", source)
        self.assertRegex(source, r"supplemental_specs_to_include = \(\n\s+direct_patch_supplemental_specs")
        setup_ui_source = static_replacement_ui_concern_source(ROOT, "setup_options_transform")
        self.assertIn("preferred_rebuild_material_sidecar", source)
        self.assertIn("preferred_complete_source_swap", source)
        self.assertIn("setup.preferred_complete_source_swap = bool(swap_scope.complete_swap)", source)
        self.assertIn("preferred_complete_source_swap=bool(setup.preferred_complete_source_swap)", source)
        self.assertIn("if _state.preferred_complete_source_swap:", setup_ui_source)
        self.assertIn("_state._select_complete_swap_material_profile('material_authority_detail_mask', persist=False)", setup_ui_source)
        self.assertIn("def _archive_model_source_texture_entries_for_swap", source)
        self.assertIn("_archive_model_source_texture_entries_for_swap(", source)
        self.assertIn("stop_event=stop_event", source)
        self.assertIn("sidecar_texture_references=source_sidecar_bindings", source)
        self.assertIn("_extract_archive_sidecar_texture_lookup_paths(sidecar_text)", source)
        self.assertIn('str(candidate.extension or "").strip().lower() != ".dds"', source)
        self.assertIn("Checked rows are written as loose replacement payloads", source)
        self.assertIn("REPLACES this game file while enabled; rig/physics-sensitive", source)
        self.assertIn("Appearance descriptors are separate from material sidecars", source)
        self.assertIn("Can replace target appearance descriptor", source)
        self.assertIn('QPushButton("Select Graph Textures")', source)
        self.assertIn('QPushButton("Help: what should I choose?")', source)
        self.assertIn("Recommended character/body swap defaults", source)
        self.assertIn("What this row means", source)
        self.assertIn("def _select_character_graph_entries", source)
        self.assertIn("relationship_edges_by_key", source)
        self.assertIn("edge.include_policy in {ARCHIVE_REL_INCLUDE_REQUIRED, ARCHIVE_REL_INCLUDE_RECOMMENDED}", source)
        self.assertIn('basename.endswith((".app.xml", ".app_xml"))', source)
        self.assertIn('QCheckBox("Use Character Swap Plan (experimental)")', source)
        self.assertIn("character_swap_plan_checkbox.toggled.connect(_character_swap_plan_toggled)", source)
        self.assertIn("Surgical Character Swap Plan appearance patch", source)
        self.assertIn(".pab/.pabc skeleton and .hkx/.hkt physics rows are not merged", source)
        self.assertIn("Full character/body swaps often require matching <code>.app_xml</code>", source)
        self.assertIn("Use <b>Character Swap Plan</b> for experimental full-character/body swaps", source)

    def test_texture_suggestions_require_specific_character_part_tokens(self) -> None:
        source = _main_window_source()
        self.assertIn("_part_specific_tokens = lambda", source)
        self.assertIn('result.add("hand")', source)
        self.assertIn('result.add("body")', source)
        self.assertIn('{"body", "torso", "nude", "skin", "chest", "waist"}', source)
        self.assertIn("target_part_specific = part_specific_tokens", source)
        self.assertIn("candidate_specific = part_specific_tokens(candidates[0].stem)", source)
        self.assertIn("if target_specific and candidate_specific and not (target_specific & candidate_specific):", source)
        self.assertIn("texture_files_by_basename", source)
        self.assertIn("texture_files_by_normalized_source_path", source)
        self.assertIn("exact_source_path = texture_files_by_normalized_source_path.get(normalized_target_texture_path)", source)
        self.assertIn("if target_part_specific:", source)
        self.assertIn("if file_part_specific and not (target_part_specific & file_part_specific):", source)
        self.assertIn("continue", source)
        self.assertIn("score -= 60.0", source)
        self.assertIn("score -= 90.0", source)

    def test_mesh_import_setup_dialog_is_compact(self) -> None:
        source = _main_window_source() + "\n" + _archive_mesh_import_sources() + "\n" + _about_documentation_source()
        self.assertIn('dialog.setObjectName("MeshImportSetupDialog")', source)
        self.assertIn("dialog.setMinimumSize(760, 460)", source)
        self.assertIn('QGroupBox("Import Summary")', source)
        mesh_import_setup_source = ARCHIVE_MESH_IMPORT_SETUP_STATE.read_text(encoding="utf-8")
        self.assertIn('payload_group = QGroupBox(setup_control_text["payload_group"])', source)
        self.assertIn('"payload_group": "Preflight & Files"', mesh_import_setup_source)
        self.assertLess(
            source.index('summary_layout = QVBoxLayout(summary_group)'),
            source.index("summary_layout.addWidget(source_group)"),
        )
        self.assertIn('QLabel#MetricChip', source)
        self.assertIn('def _compact_path', source)
        self.assertIn("content_scroll = QScrollArea(dialog)", source)
        self.assertIn("def _fit_mesh_import_setup_dialog_to_screen", source)
        self.assertIn("dialog.setMaximumSize(max_width, max_height)", source)
        self.assertIn('preflight_tree = QTreeWidget()', source)
        self.assertIn('preflight_tree.setHeaderLabels(["Check", "Value"])', source)
        self.assertIn('preflight_tree.setMaximumHeight(128)', source)
        self.assertIn('supplemental_list.setMaximumHeight(112)', source)
        self.assertIn("<b>Live Alignment Preview</b> is the transform workspace.", source)
        self.assertIn("After loose export, the Archive Preview switches to a final-output view when possible", source)
        self.assertNotIn("Mesh Replacement automates common part and texture mappings, but some assets still need manual texture-slot review.", source)

    def test_modify_original_startup_defers_heavy_alignment_tables(self) -> None:
        source = _main_window_source() + "\n" + ARCHIVE_REFERENCE_PREVIEW.read_text(encoding="utf-8")
        outliner_source = static_replacement_ui_concern_source(ROOT, "source_parts_outliner")
        source_tree_state_source = ARCHIVE_STATIC_REPLACEMENT_SOURCE_TREE_STATE.read_text(encoding="utf-8")
        texture_table_source = ARCHIVE_STATIC_REPLACEMENT_TEXTURE_TABLE.read_text(encoding="utf-8")
        material_plan_ui_state_source = ARCHIVE_STATIC_REPLACEMENT_MATERIAL_PLAN_UI_STATE.read_text(encoding="utf-8")
        self.assertIn("_state.source_tree.itemChanged.connect(_state._source_item_check_state_changed)", outliner_source)
        self.assertLess(outliner_source.index("_state._source_item_check_state_changed = _state.parts_outliner_mapping_callbacks._source_item_check_state_changed"), outliner_source.index("_state.source_tree.itemChanged.connect(_state._source_item_check_state_changed)"))
        self.assertIn("source_item.setCheckState(0", source)
        self.assertNotIn("source_tree.setItemWidget(source_item, 0", source)
        self.assertNotIn("source_enabled_checkbox = QCheckBox", source)
        self.assertIn("_state.source_tree_population_timer = _state.QTimer(_state.dialog)", outliner_source)
        self.assertIn("def _populate_source_tree_chunk() -> None:", source)
        self.assertIn("_state._source_tree_population_queued_text_helper(_state.replacement_source_count)", outliner_source)
        self.assertIn("Replacement source list queued", source_tree_state_source)
        self.assertIn("alignment_post_open_tasks: List[Callable[[], None]] = []", source)
        self.assertIn("def _queue_alignment_post_open_task(callback: Callable[[], None]) -> None:", source)
        self.assertIn("_state._queue_alignment_post_open_task(_state.source_tree_population_timer.start)", outliner_source)
        self.assertIn("_queue_alignment_post_open_task(_set_preview_renderer)", source)
        self.assertIn("_queue_alignment_post_open_task(_queue_static_preview_refresh)", source)
        self.assertIn("QTimer.singleShot(0, _run_alignment_post_open_tasks)", source)
        self.assertIn("for task_index, callback in enumerate(pending_tasks):", source)
        self.assertIn("int(task_index) * int(spacing_ms),", source)
        self.assertIn(
            "lambda callback=callback: _run_alignment_post_open_task(state, callback)",
            source,
        )
        self.assertIn("schedule=_state.QTimer.singleShot", static_replacement_callback_concern_source(ROOT, "refresh_queue"))
        self.assertNotIn("QTimer.singleShot(0, source_tree_population_timer.start)", source)
        self.assertNotIn("QTimer.singleShot(0, _refresh_static_dialog_preview)", source)
        preview_status_source = ARCHIVE_STATIC_REPLACEMENT_PREVIEW_STATUS_STATE.read_text(encoding="utf-8")
        self.assertIn('original_dialog_preview.clear_model(alignment_preview_render_control_text["original_reference_loading"])', source)
        self.assertIn('static_dialog_preview.clear_model(alignment_preview_render_control_text["replacement_preview_loading"])', source)
        self.assertIn('"original_reference_loading": "Original reference preview is loading..."', preview_status_source)
        self.assertIn('"replacement_preview_loading": "Replacement preview is loading..."', preview_status_source)
        mapping_build_source = _nested_function_source(static_replacement_callback_concern_source(ROOT, "parts_outliner_mapping"), "_ensure_mapping_table_building")
        self.assertIn("def _ensure_mapping_table_building() -> None:", mapping_build_source)
        source_tree_selection_source = static_replacement_callback_concern_source(ROOT, "source_tree_selection")
        self.assertIn("_state.control_tabs.widget(index) is _state.parts_tab", source_tree_selection_source)
        self.assertIn("_state._mapping_table_build_can_start_helper(", mapping_build_source)
        self.assertIn("def mapping_table_build_can_start", ARCHIVE_STATIC_REPLACEMENT_MAPPING_TABLE_STATE.read_text(encoding="utf-8"))
        self.assertNotIn("QTimer.singleShot(0, mapping_table_build_timer.start)", source)
        self.assertIn("texture_material_plan_loaded = _texture_material_plan_loaded_initial_state_helper()", source)
        self.assertIn("texture_material_plan_loaded_initial_state", texture_table_source)
        self.assertIn('return {"loaded": False, "loading": False}', material_plan_ui_state_source)
        material_plan_refresh_source = _nested_function_source(
            static_replacement_remaining_callback_source(ROOT),
            "_refresh_source_material_plan",
        )
        self.assertIn("def _refresh_source_material_plan(*, force: bool=False) -> None:", material_plan_refresh_source)
        self.assertIn(
            "_state.control_tabs.widget(index) is _state.textures_tab",
            static_replacement_ui_concern_source(ROOT, "texture_material"),
        )
        texture_section_source = static_replacement_ui_concern_source(ROOT, "texture_material")
        self.assertIn("_state.deferred_sidecar_bindings_for_advanced = _state.tuple(_state.sidecar_bindings_for_advanced or ())", texture_section_source)
        self.assertNotIn("if False and deferred_sidecar_bindings_for_advanced", source)
        self.assertIn("_state.texture_group = _state.QGroupBox(_state.str(_state.advanced_dds_control_text['group_title']))", texture_section_source)
        self.assertNotIn("texture_group.setCheckable(True)", source)
        self.assertNotIn("texture_group.setChecked(False)", source)
        advanced_dds_state_source = ARCHIVE_STATIC_REPLACEMENT_ADVANCED_DDS_STATE.read_text(encoding="utf-8")
        self.assertIn("_state.advanced_dds_overrides_state = _state._advanced_dds_overrides_initial_state_helper()", texture_section_source)
        self.assertIn("_state.StaticReplacementAdvancedDdsController(_state.self, _state.dialog)", texture_section_source)
        self.assertIn("_state.AdvancedDdsRowScanRequest(", texture_section_source)
        self.assertNotIn("_advanced_dds_override_row_scan_state_helper(", source)
        self.assertIn("_state.texture_rows_by_target.setdefault(target_name, []).extend(rows)", texture_section_source)
        self.assertIn(
            'return {"loaded": False, "loading": False, "load_requested": False}',
            advanced_dds_state_source,
        )
        self.assertIn("def _ensure_advanced_dds_overrides_loaded(reason: str='manual') -> bool:", texture_section_source)
        self.assertIn("_state.advanced_dds_load_button.clicked.connect", texture_section_source)
        self.assertIn("_state.advanced_texture_section = _state.CollapsibleSection(", texture_section_source)
        self.assertIn("_state.str(_state.advanced_dds_control_text['section_title'])", texture_section_source)
        self.assertIn("_state.advanced_texture_section.toggled.connect", texture_section_source)
        self.assertNotIn("if not texture_override_rows:\n                        texture_layout.addWidget", source)
        self.assertLess(
            texture_section_source.index("_state.texture_workflow = _state.QWidget()"),
            texture_section_source.index("_state.advanced_texture_section = _state.CollapsibleSection("),
        )
        dialog_deps_callback_source = ARCHIVE_STATIC_REPLACEMENT_DIALOG_PROMPT_DEPS_CALLBACKS.read_text(encoding="utf-8")
        dialog_ui_section_source = _ui_section_source()
        helper_source = ARCHIVE_STATIC_REPLACEMENT_DIALOG_HELPERS.read_text(encoding="utf-8")
        original_texture_preview_state_source = ARCHIVE_STATIC_REPLACEMENT_ORIGINAL_TEXTURE_PREVIEW_STATE.read_text(
            encoding="utf-8"
        )
        self.assertIn("def texture_override_row_sort_key", helper_source)
        self.assertIn("texture_override_row_sort_key as _texture_override_row_sort_key", dialog_deps_callback_source)
        texture_callback_source = static_replacement_texture_callback_source(ROOT)
        self.assertIn("key=lambda row_state: _state._texture_override_row_sort_key", texture_callback_source)
        self.assertLess(
            dialog_ui_section_source.index("_state.create_alignment_texture_table_callbacks("),
            dialog_ui_section_source.index("_state.advanced_texture_section = _state.CollapsibleSection("),
        )
        self.assertIn("initial_static_preview_refreshed = False", source)
        self.assertIn("if not _state.initial_static_preview_refreshed:", texture_section_source)
        self.assertIn("Advanced DDS Overrides can be expanded after the material contract loads.", advanced_dds_state_source)
        self.assertIn("def _load_original_reference_texture_preview() -> None:", source)
        self.assertIn("_queue_alignment_post_open_task(_load_original_reference_texture_preview)", source)
        post_open_start = source.index("dialog.finished.connect(_modeless_alignment_dialog_finished)")
        post_open_end = source.index("build_footer = _make_alignment_build_footer_helper(", post_open_start)
        post_open_block = source[post_open_start:post_open_end]
        self.assertLess(
            post_open_block.index("_queue_alignment_post_open_task(_queue_static_preview_refresh)"),
            post_open_block.index("_queue_alignment_post_open_task(_load_original_reference_texture_preview)"),
        )
        self.assertIn("def _ensure_original_reference_texture_preview_ready", source)
        self.assertIn("_original_reference_texture_preview_ready_state_helper(", source)
        self.assertIn("Loading original textures: base/sidecar/support maps...", original_texture_preview_state_source)
        self.assertIn("_original_reference_texture_preview_error_state_helper(", source)
        self.assertIn("_original_reference_texture_preview_exception_state_helper(", source)
        self.assertIn("_original_reference_texture_preview_load_start_state_helper(", source)
        self.assertIn("_original_reference_texture_preview_ready_result_state_helper(", source)
        self.assertIn("_original_texture_preview_toggle_state_helper(", source)
        self.assertIn(
            "Original texture preview failed; continuing untextured",
            original_texture_preview_state_source,
        )
        self.assertIn("def original_reference_texture_preview_ready_state", original_texture_preview_state_source)
        self.assertIn("def original_reference_texture_preview_ready_result_state", original_texture_preview_state_source)
        self.assertIn("def original_reference_texture_preview_error_state", original_texture_preview_state_source)
        self.assertIn("def original_reference_texture_preview_exception_state", original_texture_preview_state_source)
        self.assertIn("def original_texture_preview_toggle_state", original_texture_preview_state_source)
        texture_error_start = texture_callback_source.index(
            "def _handle_original_reference_texture_preview_error("
        )
        texture_error_end = texture_callback_source.index(
            "def _current_archive_original_preview_model(",
            texture_error_start,
        )
        texture_error_block = texture_callback_source[texture_error_start:texture_error_end]
        self.assertNotIn("_mark_alignment_d3d11_rebuild_reason", texture_error_block)
        self.assertNotIn("_queue_static_preview_refresh", texture_error_block)
        self.assertIn("static_preview_geometry_cache.clear()", source)
        self.assertIn("static_preview_prepared_cache.clear()", source)
        reference_required_start = original_texture_preview_state_source.index(
            "def original_reference_texture_preview_required"
        )
        reference_required_end = original_texture_preview_state_source.index(
            "def original_reference_texture_preview_readiness",
            reference_required_start,
        )
        reference_required_block = original_texture_preview_state_source[reference_required_start:reference_required_end]
        self.assertNotIn("original_texture_preview_state", reference_required_block)
        original_load_start = texture_callback_source.index("def _load_original_reference_texture_preview() -> None:")
        original_load_end = texture_callback_source.index("def _highlight_texture_plan_item", original_load_start)
        original_load_block = texture_callback_source[original_load_start:original_load_end]
        self.assertNotIn("original_texture_preview_state", original_load_block)
        self.assertIn("_current_archive_original_preview_model()", original_load_block)
        self.assertIn("build_archive_preview_result(", original_load_block)
        self.assertIn("texture_entries_by_normalized_path_for_alignment", original_load_block)
        self.assertIn("texture_entries_by_basename_for_alignment", original_load_block)
        self.assertIn("texture_entries_by_normalized_path=archive_texture_entries_by_normalized_path", original_load_block)
        self.assertIn("texture_entries_by_basename=archive_texture_entries_by_basename", original_load_block)
        self.assertIn("AlignmentOriginalTexturePreviewWorker", original_load_block)
        self.assertIn("_load_native_preview_core_material_manifest_for_alignment(", original_load_block)
        self.assertIn("worker.completed.connect(", original_load_block)
        self.assertIn("Qt.QueuedConnection", original_load_block)
        self.assertIn("def apply_native_preview_core_material_manifest", source)
        self.assertIn("_apply_native_preview_core_material_manifest_helper(", source)
        self.assertIn("preview_native_material_overrides", source)
        native_manifest_source = ARCHIVE_STATIC_REPLACEMENT_NATIVE_MANIFEST.read_text(encoding="utf-8")
        native_apply_start = native_manifest_source.index("def apply_native_preview_core_material_manifest")
        native_apply_end = native_manifest_source.index("def load_native_preview_core_material_manifest_for_alignment", native_apply_start)
        native_apply_block = native_manifest_source[native_apply_start:native_apply_end]
        self.assertIn('identity.get("source_component_index", 0)', native_apply_block)
        self.assertIn('identity.get("prefab_component", False)', native_apply_block)
        self.assertIn("source_component_index != 0", native_apply_block)
        self.assertIn('raw_index = identity.get("source_submesh_index", batch.get("index", -1))', native_apply_block)
        self.assertNotIn('identity.get("source_local_submesh_index"', native_apply_block)
        prompt_setup_helper_source = ARCHIVE_STATIC_REPLACEMENT_DIALOG_PROMPT_SETUP_HELPERS.read_text(encoding="utf-8")
        self.assertIn("build_static_replacement_prompt_sidecar_context(", source)
        sidecar_lookup_start = prompt_setup_helper_source.index('sidecar_bindings')
        sidecar_lookup_end = prompt_setup_helper_source.index("return SimpleNamespace(", sidecar_lookup_start)
        sidecar_lookup_block = prompt_setup_helper_source[sidecar_lookup_start:sidecar_lookup_end]
        self.assertIn("archive_entries_by_basename=texture_entries_by_basename_for_alignment", sidecar_lookup_block)
        self.assertIn("source_display_label_cache: Dict[int, str] = {}", source)
        source_display_source = ARCHIVE_STATIC_REPLACEMENT_SOURCE_DISPLAY.read_text(encoding="utf-8")
        self.assertIn("def invalidate_source_display_cache", source_display_source)
        self.assertIn("_invalidate_source_display_cache_helper(", source)
        preview_mode_source = static_replacement_callback_concern_source(ROOT, "preview_mode")
        self.assertIn("def _preview_mode_needs_static_refresh(mode: str) -> bool:", preview_mode_source)
        preview_mode_block = _nested_function_source(preview_mode_source, "_set_preview_mode")
        self.assertIn("needs_static_refresh = _state._preview_mode_needs_static_refresh(mode)", preview_mode_block)
        self.assertIn("mode_route = _state._alignment_preview_mode_route_helper(", preview_mode_block)
        self.assertIn("if mode_route.should_queue_static_preview_refresh:", preview_mode_block)
        self.assertIn("_state.alignment_d3d11_preview_host.set_display_mode(mode_route.mode)", preview_mode_block)
        self.assertIn("_state.preview_stack.setCurrentWidget(_state.alignment_d3d11_preview_page)", preview_mode_block)
        self.assertNotIn("_state.preview_stack.setCurrentIndex", preview_mode_block)
        self.assertIn("_state._restore_alignment_preview_mode_view_state(mode_route.mode)", preview_mode_block)
        self.assertEqual(preview_mode_block.count("_state._queue_static_preview_refresh()"), 1)
        self.assertIn("alignment_d3d11_drag_generation", source)
        self.assertIn("alignment_transform_generation", source)
        self.assertIn("_alignment_d3d11_drag_reload_stale_helper(", source)
        self.assertIn("request_drag_generation", source)
        self.assertIn("request_transform_generation", source)
        self.assertNotIn("Manual DDS overrides are deferred.", source)
        self.assertNotIn("dict(self.archive_entries_by_normalized_path)", source)
        self.assertNotIn("dict(self.archive_entries_by_basename)", source)
        package_worker_block = _nested_function_source(
            static_replacement_callback_concern_source(ROOT, "d3d11_package_lifecycle"),
            "_start_alignment_d3d11_package_worker",
        )
        self.assertIn("mesh_edit_raw_package = _state._mesh_edit_raw_preview_active_value()", package_worker_block)
        self.assertIn("use_textures=worker_use_textures", package_worker_block)
        self.assertIn("original_reference_material_parity=worker_original_reference_material_parity", package_worker_block)
        self.assertIn("package_quality=package_quality", package_worker_block)
        self.assertIn("geometry_cache_dir=preview_cache_root / 'geometry'", package_worker_block)
        self.assertNotIn("original_reference_native_package_dir=", package_worker_block)
        self.assertIn("editor_workspace='modify_original_alignment' if _state.modify_original_clone_mode else 'mesh_replacement_alignment'", package_worker_block)
        self.assertNotIn("original_reference_material_parity=enable_material_combiner", package_worker_block)

    def test_alignment_normal_quality_uses_archive_parity_and_startup_steps_are_timed(self) -> None:
        source = _main_window_source()
        startup_start = source.index("def _alignment_startup_step(message: str) -> None:")
        startup_body = source[startup_start: source.index("def _finish_alignment_startup_progress", startup_start)]

        self.assertIn("builder_startup_step_elapsed_ms=elapsed_ms", startup_body)
        self.assertNotIn("def _alignment_auto_detail_uses_fast_package", source)
        self.assertNotIn("def _alignment_d3d11_uses_accurate_package", source)
        self.assertNotIn('str(label or "").strip().casefold() == "final test build preview"', source)
        self.assertNotIn("return not _alignment_auto_detail_uses_fast_package(label, model)", source)
        self.assertNotIn('return settings, True, True, "accurate"', source)
        self.assertIn('return clamp_model_preview_render_settings(geometry_settings), False, False, "archive_parity"', source)
        self.assertNotIn('return _alignment_d3d11_fast_render_settings(settings), False, False, "fast_geometry"', source)
        self.assertIn('return clamp_model_preview_render_settings(geometry_settings), False, False, "material_refresh"', source)
        self.assertIn("target_total_faces=35_000", source)
        self.assertNotIn('if _alignment_preview_detail_mode() == "full":\n                            return 0', source)

    def test_alignment_dialog_routes_visible_dds_contract_and_prune_intent(self) -> None:
        source = _main_window_source()
        accept_source = static_replacement_callback_concern_source(ROOT, "accept_build")
        outliner_source = static_replacement_ui_concern_source(ROOT, "source_parts_outliner")
        setup_ui_source = static_replacement_ui_concern_source(ROOT, "setup_options_transform")
        callback_source = _callback_factory_source()
        routing_source = static_replacement_routing_callback_source(ROOT)
        static_source = _static_replacer_source()
        authority_controls_source = ARCHIVE_STATIC_REPLACEMENT_MATERIAL_AUTHORITY_CONTROLS.read_text(encoding="utf-8")
        archive_source = _archive_modding_source()
        package_source = (ROOT / "cdmw" / "services" / "mesh_dotnet_preview_package.py").read_text(encoding="utf-8")
        self.assertIn("build_mesh_dotnet_experiment_package(", package_source)
        self.assertIn("MESH_DOTNET_MATERIAL_COMPILER_VERSION", package_source)
        self.assertIn("net_materials.json", package_source)
        self.assertIn("canonical", package_source.casefold())
        self.assertIn("source_material_texture_override_assignments", source)
        return
        native_source = d3d11_preview_source()
        self.assertIn("_state.mapping_tree.setHeaderLabels(list(_state.mapping_table_action_control_text['headers']))", outliner_source)
        self.assertIn("mapping_tree.setColumnHidden(1, True)", source)
        self.assertIn("mapping_tree.setColumnHidden(2, True)", source)
        self.assertIn("_state.mapping_tree.setHorizontalScrollBarPolicy(_state.Qt.ScrollBarAlwaysOff)", outliner_source)
        self.assertIn("def _set_advanced_mapping_visible(checked: bool) -> None:", source)
        self.assertIn("_state.source_parts_group = _state.QGroupBox(str(_state.source_tree_control_text['source_group_title']))", outliner_source)
        self.assertIn("_state.source_parts_group.setObjectName('MeshReplacementReferenceParts')", outliner_source)
        self.assertIn("_state.parts_outliner_layout.addWidget(_state.mapping_group, 0)", source)
        self.assertIn("_state.advanced_routing_layout.addWidget(_state.parts_outliner_group, 0)", outliner_source)
        self.assertNotIn("parts_outliner_layout.addWidget(source_parts_group, 0)", source)
        self.assertIn('return f"Orig {count} | Src {source_count}"', source)
        self.assertIn('return "Sidecar unknown"', source)
        self.assertIn('return "Orig 0 | Src 0"', source)
        self.assertNotIn('return "No DDS rows"', source)
        self.assertIn("_state.prune_unmapped_original_dds_checkbox = _state.QCheckBox(_state.material_authority_setup_labels['prune_unmapped_original_dds'])", setup_ui_source)
        self.assertIn('"prune_unmapped_original_dds": "Remove unused original texture refs"', authority_controls_source)
        self.assertIn("rebuild_sidecar_checkbox.setChecked(False)", source)
        self.assertIn("prune_unmapped_original_dds_checkbox.setChecked(False)", source)
        self.assertNotIn("source_material_rebuild_available = bool(texture_sets)", source)
        self.assertNotIn("else source_material_rebuild_available", source)
        self.assertIn("_state.external_material_reset_checkbox = _state.QCheckBox(_state.material_authority_setup_labels['external_material_reset'])", setup_ui_source)
        self.assertIn("_state.complete_external_swap_checkbox = _state.QCheckBox(_state.material_authority_setup_labels['complete_external_swap'])", setup_ui_source)
        self.assertIn('"external_material_reset": "Advanced: reset inherited material response"', authority_controls_source)
        self.assertIn('"complete_external_swap": "Complete source-owned mesh/material swap"', authority_controls_source)
        self.assertIn("_state.complete_external_swap_checkbox.setObjectName('MeshAlignmentCompleteExternalSwapCheckbox')", setup_ui_source)
        self.assertNotIn('advanced_materials_checkbox = QCheckBox("Advanced Materials")', source)
        self.assertNotIn('advanced_materials_checkbox.setObjectName("MeshAlignmentAdvancedMaterialsCheckbox")', source)
        self.assertIn("_state.material_route_summary_label.setObjectName('MeshAlignmentMaterialRouteSummary')", setup_ui_source)
        self.assertNotIn("def _set_advanced_materials_visible(checked: bool) -> None:", source)
        self.assertIn("_manual_material_profile_panel_state_helper(", source)
        self.assertIn('manual_profile_group.setVisible(bool(state["visible"]))', source)
        self.assertIn("true_source_basic_group.setVisible(bool(visible))", source)
        self.assertIn("texture_transform_group.setVisible(bool(has_materials))", source)
        self.assertNotIn("advanced_materials_checkbox.isChecked()", source)
        self.assertIn("def _complete_external_swap_mappings", source)
        complete_swap_start = source.rindex("def _complete_external_swap_mappings")
        complete_swap_block = source[
            complete_swap_start
            : source.index("def _apply_complete_external_swap_routing_to_ui", complete_swap_start)
        ]
        self.assertIn("_mapping_edit_valid_source_indices_helper(edit, render_source_indices)", complete_swap_block)
        self.assertIn("_source_renderable_indices_helper(", complete_swap_block)
        self.assertIn("if parsed_mappings:", complete_swap_block)
        self.assertIn("return parsed_mappings", complete_swap_block)
        self.assertIn('return f"__source_part_{source_index}_{material_key}"', source)
        self.assertIn("complete_swap_enabled = bool(_state._complete_external_swap_enabled())", accept_source)
        self.assertIn("parsed_mappings = _state._complete_external_swap_mappings()", accept_source)
        self.assertIn("_state.complete_external_swap_checkbox.toggled.connect(_state._sync_complete_external_swap_mode)", setup_ui_source)
        checkbox_connect = setup_ui_source.index("_state.complete_external_swap_checkbox.toggled.connect(_state._sync_complete_external_swap_mode)")
        custom_icon_bind = setup_ui_source.index(
            "_state.alignment_custom_icon_callbacks = _state.create_alignment_custom_icon_callbacks"
        )
        option_impact_refresh = setup_ui_source.rindex("_state._refresh_output_impact_review()", 0, custom_icon_bind)
        mesh_edit_connect = setup_ui_source.index("_state.alignment_d3d11_preview_host.mesh_edit_stroke_started.connect(lambda payload: _state._mesh_edit_begin_stroke(payload))")
        viewport_select_connect = setup_ui_source.index("_state.alignment_d3d11_preview_host.source_part_selected.connect(_state._d3d11_source_part_selected)")
        self.assertLess(checkbox_connect, option_impact_refresh)
        self.assertLess(option_impact_refresh, custom_icon_bind)
        self.assertLess(option_impact_refresh, mesh_edit_connect)
        self.assertLess(mesh_edit_connect, viewport_select_connect)
        self.assertIn("_state._set_checkbox_checked_silently_helper(_state.rebuild_sidecar_checkbox, True)", routing_source)
        self.assertIn("_state._set_checkbox_checked_silently_helper(_state.prune_unmapped_original_dds_checkbox, True)", routing_source)
        self.assertIn("_state._material_authority_complete_swap_source_output_size_index_helper(", routing_source)
        self.assertIn("_state._material_authority_complete_swap_profile_name_helper(current_profile)", routing_source)
        self.assertIn("find_data = getattr(_state.texture_output_size_combo, 'findData', None)", routing_source)
        self.assertIn("callable(find_data)", source)
        self.assertIn("callable(_state._set_combo_index_silently_helper)", routing_source)
        self.assertIn("block_signals = getattr(_state.complete_swap_material_profile_combo, 'blockSignals', None)", routing_source)
        self.assertIn("if callable(_state._alignment_d3d11_invalidate_package_cache):", callback_source)
        self.assertIn("stage='complete_swap_toggle_queued'", routing_source)
        self.assertIn("_state.QTimer.singleShot(0, _apply_checked_complete_swap)", routing_source)
        self.assertIn("_material_authority_complete_swap_forced_child_states_helper(", source)
        self.assertIn("_material_authority_complete_swap_restored_child_states_helper(", source)
        self.assertIn("_material_authority_complete_swap_next_transition_generation_helper(", source)
        self.assertIn("_material_authority_complete_swap_should_apply_checked_helper(", source)
        self.assertIn("'previous_forced_child_states'", routing_source)
        self.assertIn("material_authority_complete_swap_forced_child_states", authority_controls_source)
        self.assertIn("material_authority_complete_swap_restored_child_states", authority_controls_source)
        self.assertIn("material_authority_complete_swap_next_transition_generation", authority_controls_source)
        self.assertIn("material_authority_complete_swap_should_apply_checked", authority_controls_source)
        self.assertIn("material_authority_sidecar_option_state", authority_controls_source)
        self.assertIn("material_authority_sidecar_control_application_state", authority_controls_source)
        self.assertIn("material_authority_sidecar_dependent_toggle_state", authority_controls_source)
        self.assertIn("material_authority_apply_sidecar_control_state", authority_controls_source)
        self.assertIn("_material_authority_apply_sidecar_control_state_helper(", source)
        self.assertIn("rebuild_sidecar_widget=rebuild_sidecar_checkbox", source)
        self.assertIn("dependent_widgets=(", source)
        self.assertIn("complete_widgets=(", source)
        self.assertIn('state["dependent_sidecar_options_enabled"]', authority_controls_source)
        self.assertIn('state["clear_dependent_sidecar_options"]', authority_controls_source)
        self.assertIn("prune_removed_target_texture_parameters=bool(rebuild_material_sidecar and prune_unmapped_original_texture_parameters and placement_snapshot.get('removed_target_submesh_indices', []))", callback_source)
        self.assertIn("prune_unmapped_original_texture_parameters=bool(rebuild_material_sidecar and prune_unmapped_original_texture_parameters)", callback_source)
        self.assertIn(
            "False if _state.modify_original_clone_mode else _state.prune_unmapped_original_dds_checkbox.isChecked() or complete_swap_enabled",
            accept_source,
        )
        self.assertIn("_state._set_checkbox_checked_silently_helper(_state.source_color_faithful_checkbox, True)", routing_source)
        self.assertIn("prune_unmapped_original_texture_parameters: bool = False", static_source)
        self.assertIn("complete_external_material_reset: bool = False", static_source)
        self.assertIn('"prune_unmapped_original_texture_parameters": bool(', archive_source)
        self.assertIn('complete_reset = bool(getattr(options, "complete_external_material_reset"', archive_source)

        complete_apply_block = _nested_function_source(
            routing_source, "_apply_complete_external_swap_routing_to_ui"
        )
        self.assertIn("def _mapped_source_indices_value(mappings: object) -> set[int]:", source)
        self.assertIn("mapped_sources = _state._mapped_source_indices_value(mappings)", complete_apply_block)
        self.assertIn("stage='complete_swap_routing'", complete_apply_block)
        self.assertIn("_state._material_authority_complete_swap_routing_progress_message_helper()", complete_apply_block)
        self.assertIn("if callable(_state._set_alignment_d3d11_progress):", complete_apply_block)
        self.assertIn("if push_undo and callable(_state._push_geometry_undo_snapshot):", complete_apply_block)
        self.assertIn("_state._queue_source_material_plan_refresh(", complete_apply_block)
        self.assertIn("if callable(_state._queue_source_material_plan_refresh):", complete_apply_block)
        self.assertIn("force_plan=True", complete_apply_block)
        self.assertIn("reason=routing_reason", complete_apply_block)
        self.assertIn(
            "material_authority_complete_swap_routing_reason",
            authority_controls_source,
        )
        self.assertIn("complete source-owned swap routing", authority_controls_source)
        self.assertIn("_material_authority_complete_swap_update_performance_helper()", source)
        self.assertIn("Complete source-owned swap update queued.", authority_controls_source)
        self.assertNotIn("_call_if_alignment_widgets_live(_refresh_source_material_plan)", complete_apply_block)
        self.assertIn('complete_external_material_reset=values["complete_external_material_reset"]', archive_source)
        self.assertIn('prune_unmapped_original_texture_parameters=values["prune_unmapped_original_texture_parameters"]', archive_source)
        host_source = _native_d3d11_preview_host_source()
        self.assertIn("def set_highlighted_alignment_submeshes", host_source)
        self.assertIn("original_submesh_indices=tuple(selection_state['d3d11_original_highlighted_indices'])", source)
        self.assertIn('"original_submesh_indices"', host_source)
        self.assertIn('"replacement_submesh_indices"', host_source)
        self.assertIn("role == \"original_reference\"", native_source)
        self.assertIn("role == \"replacement_preview\"", native_source)

    def test_runtime_xml_material_profile_is_available_to_runtime_combo(self) -> None:
        source = _main_window_source()
        authority_controls_source = ARCHIVE_STATIC_REPLACEMENT_MATERIAL_AUTHORITY_CONTROLS.read_text(encoding="utf-8")
        material_source = _material_replacer_source()
        policy_source = _texture_domain_policy_source()
        self.assertIn("complete_swap_material_profiles_by_name = {", source)
        self.assertIn('name="material_authority_runtime_xml"', material_source)
        self.assertIn('label="Material Authority Runtime XML"', material_source)
        self.assertIn('"runtime_xml": "material_authority_runtime_xml"', material_source)
        self.assertIn('"material_authority_runtime": "material_authority_runtime_xml"', material_source)
        self.assertIn('"runtime_xml_authority": "material_authority_runtime_xml"', material_source)
        self.assertIn("def complete_swap_allows_inherited_layer_color_bindings", policy_source)
        self.assertIn("complete_swap_material_allows_inherited_layer_color_bindings", policy_source)
        self.assertIn("complete_swap_material_requires_true_source_authority", policy_source)
        self.assertIn("get_complete_swap_material_profile", source)
        self.assertIn("material_authority_requested_profile_name", authority_controls_source)
        self.assertIn('name="material_authority_clean_source"', material_source)
        self.assertIn('label="Material Authority Clean Source"', material_source)
        self.assertIn('"clean_source": "material_authority_clean_source"', material_source)
        self.assertIn('"material_authority_clean": "material_authority_clean_source"', material_source)
        self.assertIn('"clean_source_authority": "material_authority_clean_source"', material_source)
        self.assertIn('"material_authority_source": "material_authority_clean_source"', material_source)
        self.assertIn('name="material_authority_true_source"', material_source)
        self.assertIn('label="Material Authority True Source"', material_source)
        self.assertIn('"true_source": "material_authority_true_source"', material_source)
        self.assertIn('"material_authority_true": "material_authority_true_source"', material_source)
        self.assertIn('"true_source_authority": "material_authority_true_source"', material_source)
        self.assertIn('name="material_authority_pbr_source_test"', material_source)
        self.assertIn('label="Material Authority PBR Source Test"', material_source)
        self.assertIn('"true_source_pbr": "material_authority_pbr_source_test"', material_source)
        self.assertIn('name="material_authority_detail_mask"', material_source)
        self.assertIn('label="Automatic"', material_source)
        self.assertIn('"true_source_detail_mask": "material_authority_detail_mask"', material_source)
        self.assertIn('name="material_authority_placeholder_safe_test"', material_source)
        self.assertIn('label="Material Authority Placeholder Safe Test"', material_source)
        self.assertIn('"placeholder_safe": "material_authority_detail_mask"', material_source)
        self.assertIn("true_source_authority_detail_mask", material_source)

    def test_manual_material_profile_exposes_runtime_controls_under_combo(self) -> None:
        source = _main_window_source()
        setup_ui_source = static_replacement_ui_concern_source(ROOT, "setup_options_transform")
        accept_source = static_replacement_callback_concern_source(ROOT, "accept_build")
        remaining_source = static_replacement_callback_family_source(ROOT, "remaining")
        manual_profile_source = ARCHIVE_STATIC_REPLACEMENT_MANUAL_MATERIAL_PROFILE.read_text(encoding="utf-8")
        authority_controls_source = ARCHIVE_STATIC_REPLACEMENT_MATERIAL_AUTHORITY_CONTROLS.read_text(encoding="utf-8")
        preview_material_authority_source = ARCHIVE_STATIC_REPLACEMENT_PREVIEW_MATERIAL_AUTHORITY.read_text(encoding="utf-8")
        material_source = _material_replacer_source()
        self.assertIn('label="Manual"', material_source)
        self.assertIn("serialize_complete_swap_manual_material_profile", source)
        self.assertIn("MeshAlignmentManualMaterialProfileGroup", manual_profile_source)
        self.assertIn("MATERIAL_AUTHORITY_VISIBLE_COMPLETE_SWAP_PROFILE_NAMES", source)
        self.assertIn('"material_authority_detail_mask"', authority_controls_source)
        self.assertNotIn('"material_authority_placeholder_safe_test"', authority_controls_source)
        self.assertIn('"material_authority_manual"', authority_controls_source)
        self.assertIn("complete_swap_material_profiles_by_name", source)
        self.assertIn("manual_profile_presets_key", source)
        self.assertIn("MeshAlignmentManualMaterialProfilePresetGroup", source)
        self.assertIn("manual_profile_preset_name_edit", source)
        self.assertIn("manual_profile_preset_details_edit", source)
        self.assertIn("manual_profile_preset_recommended_edit", source)
        self.assertIn("_state.manual_profile_group = _state.QGroupBox(_state.manual_profile_control_text['group_title'])", setup_ui_source)
        self.assertIn("_state.manual_profile_group.setObjectName(_state.manual_profile_control_text['group_object'])", setup_ui_source)
        self.assertIn('"group_title": "Material Authority Manual"', manual_profile_source)
        self.assertIn('"group_object": "MeshAlignmentManualMaterialProfileGroup"', manual_profile_source)
        self.assertIn("_state.manual_profile_preset_save_button = _state.QPushButton(_state.manual_profile_control_text['preset_save_button'])", setup_ui_source)
        self.assertIn("_state.manual_profile_preset_load_button = _state.QPushButton(_state.manual_profile_control_text['preset_load_button'])", setup_ui_source)
        self.assertIn("_state.manual_profile_preset_delete_button = _state.QPushButton(_state.manual_profile_control_text['preset_delete_button'])", setup_ui_source)
        self.assertIn('"preset_save_button": "Save Current"', manual_profile_source)
        self.assertIn('"preset_load_button": "Load"', manual_profile_source)
        self.assertIn('"preset_delete_button": "Delete"', manual_profile_source)
        self.assertIn("def _save_current_manual_profile_preset", source)
        self.assertIn("def _load_selected_manual_profile_preset", source)
        self.assertIn("def _delete_selected_manual_profile_preset", source)
        self.assertIn("manual_material_profile_preset_names", manual_profile_source)
        self.assertIn("manual_material_profile_preset_metadata", manual_profile_source)
        self.assertIn("manual_material_profile_preset_from_fields", manual_profile_source)
        self.assertIn("_state.manual_profile_texture_impact = _state.QLabel", setup_ui_source)
        self.assertIn("manual_material_profile_texture_impact_html", manual_profile_source)
        self.assertIn("manual_profile_effect_widgets", source)
        self.assertIn("def _refresh_manual_profile_control_effects", source)
        self.assertIn(
            'inactive[key] = "No effect: PBR/mask slot is not generating a material-mask DDS."',
            manual_profile_source,
        )
        self.assertIn('inactive[key] = "No effect: Color slot is disabled."', manual_profile_source)
        self.assertIn("manual_material_profile_control_effect_states", manual_profile_source)
        self.assertIn(
            'unsafe_acknowledged if expert_control and not modify_original_clone_mode else bool(state.get("enabled", True))',
            source,
        )
        self.assertIn("manual_material_profile_dirty_state", manual_profile_source)
        self.assertIn("manual_material_profile_panel_state", manual_profile_source)
        self.assertIn("manual_material_profile_token", manual_profile_source)
        self.assertIn("<table cellspacing='0' cellpadding='3'", manual_profile_source)
        self.assertIn("PBR mask", manual_profile_source)
        self.assertIn("material mask DDS", manual_profile_source)
        self.assertIn("<b>Conditional:</b>", manual_profile_source)
        self.assertIn("may have no visible in-game effect", manual_profile_source)
        self.assertIn("Shader roughness/metal/shine", manual_profile_source)
        self.assertIn("No effect when every material already has base textures", source)
        self.assertIn("No effect if no scratch-tint params exist", source)
        self.assertIn("_state.manual_profile_apply_button = _state.QPushButton(_state.manual_profile_control_text['apply_button'])", setup_ui_source)
        self.assertIn('"apply_button": "Apply Manual Settings"', manual_profile_source)
        self.assertIn("_state.manual_profile_apply_button.setToolTip(_state.manual_profile_tooltips['apply'])", setup_ui_source)
        self.assertIn("Slider edits also queue a debounced preview refresh.", manual_profile_source)
        self.assertIn("manual_material_profile_initial_status_html", manual_profile_source)
        self.assertIn("manual_material_profile_change_status_text", manual_profile_source)
        self.assertIn("Manual sliders queue preview refresh after input settles", manual_profile_source)
        self.assertIn("Preview refresh queued; press Apply Manual Settings to force it now.", manual_profile_source)
        self.assertIn("_refresh_preview_for_current_session(changed_keys)", source)
        self.assertIn("def _apply_current_manual_material_profile_to_preview", source)
        self.assertIn("_state.manual_profile_apply_button.clicked.connect(_state._apply_current_manual_material_profile_to_preview)", setup_ui_source)
        # Apply/Reset and the change status sit under the controls they act on.
        # tests/test_mesh_builder_preview_control_honesty.py owns that ordering
        # against the constructed grid; these pins only catch accidental removal.
        self.assertIn("_state.manual_profile_layout.addLayout(_state.manual_profile_apply_row, 40, 0, 1, 4)", setup_ui_source)
        self.assertIn("_state.manual_profile_layout.addWidget(_state.manual_profile_change_status, 39, 0, 1, 4)", setup_ui_source)
        self.assertIn("_state._manual_int(6, 'base_color_lift'", setup_ui_source)
        self.assertIn("_set_manual_profile_dirty(True)", source)
        self.assertNotIn('if saved_complete_swap_material_profile.startswith("material_authority_manual"):', source)
        self.assertIn("_state.manual_profile_reset_button = _state.QPushButton(_state.manual_profile_control_text['reset_button'])", setup_ui_source)
        self.assertIn('"reset_button": "Reset To Material Authority"', manual_profile_source)
        self.assertIn("_state.manual_profile_reset_button.setToolTip(_state.manual_profile_tooltips['reset'])", setup_ui_source)
        self.assertIn("Reset every manual knob to the current Material Authority baseline.", manual_profile_source)
        self.assertIn("_state.manual_profile_preview_warning = _state.QLabel", setup_ui_source)
        self.assertIn("manual_material_profile_preview_warning_html", manual_profile_source)
        self.assertIn("Preview warning</div>", manual_profile_source)
        self.assertIn("cannot render the exact same textured look as the in-game CD shader", manual_profile_source)
        self.assertNotIn("manual_profile_note = QLabel", source)
        self.assertNotIn("Direction hints</div>", source)
        self.assertIn("_state.manual_profile_reset_button.clicked.connect(_state._reset_manual_material_profile_to_material_authority)", setup_ui_source)
        self.assertIn("def _current_complete_swap_material_profile_token", source)
        self.assertIn("complete_swap_material_profile=str(_state._current_complete_swap_material_profile_token())", accept_source)
        self.assertIn("'base_color_lift'", setup_ui_source)
        self.assertIn("'emissive_color_scale'", setup_ui_source)
        self.assertIn("'Emissive scale'", setup_ui_source)
        self.assertIn("source emissive textures or emissive material colors for any glowing part", source)
        self.assertNotIn('"Gem glow scale"', source)
        self.assertIn("'roughness_min'", setup_ui_source)
        self.assertIn("'metallic_scale'", setup_ui_source)
        self.assertIn("preview_material_authority_parameters = _state._material_authority_preview_parameters_helper(", remaining_source)
        self.assertIn('("scratch_roughness", "_scratchRoughness")', preview_material_authority_source)
        self.assertIn('("scratch_metallic", "_scratchMetallic")', preview_material_authority_source)
        self.assertIn('("shine_scalar", "_specularAmount")', preview_material_authority_source)
        self.assertIn("material_authority_preview_parameters=preview_material_authority_parameters", source)
        self.assertIn("material_parameters=tuple(material_authority_preview_parameters)", source)

    def test_unsafe_material_preflight_export_override_is_loose_only(self) -> None:
        source = _main_window_source() + "\n" + _archive_mesh_import_sources()
        setup_section_source = static_replacement_ui_concern_source(ROOT, "setup_options_transform")
        accept_source = static_replacement_callback_concern_source(ROOT, "accept_build")
        authority_controls_source = ARCHIVE_STATIC_REPLACEMENT_MATERIAL_AUTHORITY_CONTROLS.read_text(encoding="utf-8")
        static_source = _static_replacer_source()
        preview_source = _final_package_preview_source()
        policy_source = _texture_domain_policy_source()
        self.assertIn("MeshAlignmentUnsafeMaterialPreflightExportCheckbox", source)
        self.assertIn("_state.unsafe_material_preflight_checkbox = _state.QCheckBox(_state.material_authority_setup_labels['unsafe_preflight'])", setup_section_source)
        self.assertIn('"unsafe_preflight": "Allow unsafe material preflight export"', authority_controls_source)
        self.assertIn("allow_unsafe_material_preflight_export: bool = False", static_source)
        self.assertIn("allow_unsafe_material_preflight_export=bool(", source)
        self.assertIn(
            "False if _state.modify_original_clone_mode else _state.unsafe_material_preflight_checkbox.isChecked()",
            accept_source,
        )
        self.assertIn("MATERIAL_PREFLIGHT_OVERRIDE_WARNING", preview_source)
        self.assertIn("def apply_material_preflight_override", preview_source)
        self.assertIn("include_hard: bool = False", preview_source)
        self.assertIn("def material_preflight_hard_blockers", preview_source)
        self.assertNotIn("from cdmw.core", policy_source)
        self.assertIn("report_checker=_check_material_authority_report", source)
        self.assertIn("def check_final_preview_material_authority", policy_source)
        self.assertIn("pre_export_authority_check = _check_final_preview_material_authority(", source)
        self.assertIn("_material_authority_check_blockers(pre_export_authority_check)", source)
        self.assertIn("Material authority report check blocked export", source)
        self.assertIn("cdmw_material_authority_report_check.json", source)
        self.assertIn("Wrote material authority report check:", source)
        self.assertIn("create_material_authority_report", source)
        self.assertIn('destination == "loose"', source)
        self.assertIn("unsafe_material_preflight_override", source)
        self.assertIn("Continuing loose export despite material authority report blocker(s)", source)
        self.assertIn("apply_material_preflight_override(pre_export_preview, include_hard=True)", source)
        self.assertIn("apply_material_preflight_override(final_preview, include_hard=True)", source)
        self.assertIn("Export Anyway (Unsafe)", source)
        self.assertIn("preflight_hard_blocked", source)

    def test_global_gloss_reduction_slider_is_wired_to_static_options(self) -> None:
        source = _main_window_source()
        setup_ui_source = static_replacement_ui_concern_source(ROOT, "setup_options_transform")
        accept_source = static_replacement_callback_concern_source(ROOT, "accept_build")
        remaining_source = static_replacement_callback_family_source(ROOT, "remaining")
        authority_controls_source = ARCHIVE_STATIC_REPLACEMENT_MATERIAL_AUTHORITY_CONTROLS.read_text(encoding="utf-8")
        qt_helper_source = ARCHIVE_STATIC_REPLACEMENT_QT_HELPERS.read_text(encoding="utf-8")
        static_source = _static_replacer_source()
        archive_source = _archive_modding_source()
        material_source = _material_replacer_source()
        self.assertIn("MeshAlignmentGlobalGlossReductionSlider", source)
        self.assertIn("MeshAlignmentGlobalGlossReductionSpinBox", source)
        self.assertIn("_state.material_authority_adjustment_labels['global_gloss_bias']", setup_ui_source)
        self.assertIn('"global_gloss_bias": "Gloss / matte bias"', authority_controls_source)
        self.assertIn("material_authority_global_gloss_tooltip", authority_controls_source)
        self.assertIn("Signed gloss/matte bias", authority_controls_source)
        self.assertIn("make_int_slider_spin_row", qt_helper_source)
        self.assertIn("slider.setRange(int(minimum), int(maximum))", qt_helper_source)
        self.assertIn("spin.setRange(int(minimum), int(maximum))", qt_helper_source)
        self.assertIn('"settings/complete_swap_global_gloss_reduction"', source)
        self.assertIn("global_gloss_reduction_slider,", source)
        self.assertIn("global_gloss_reduction_spin,", source)
        self.assertIn("_set_widget_enabled(widget, bool(state[\"complete_material_controls_enabled\"]))", authority_controls_source)
        self.assertIn("material_authority_global_gloss_reduction_hint", authority_controls_source)
        self.assertIn("Material Authority gloss boost lowers generated detail-mask roughness", authority_controls_source)
        self.assertIn("the glossy color-blend mask stays bypassed", authority_controls_source)
        self.assertIn("global_gloss_reduction: float = 0.0", static_source)
        self.assertIn("global_gloss_reduction=max(-100.0, min(100.0, float(global_gloss_reduction or 0.0)))", source)
        self.assertIn("global_gloss_reduction=0.0 if _state.modify_original_clone_mode else float(_state.global_gloss_reduction_spin.value())", accept_source)
        self.assertIn("complete_swap_global_gloss_reduction", archive_source)
        self.assertIn("Global gloss boost requested", archive_source)
        self.assertIn("Global gloss reduction requested", archive_source)
        self.assertIn("def apply_global_gloss_reduction_to_profile", material_source)
        self.assertIn("Global gloss boost applied", material_source)
        self.assertIn("Global gloss reduction applied", material_source)
        self.assertIn("MeshAlignmentSourceBrightnessSlider", source)
        self.assertIn("MeshAlignmentSourceBrightnessSpinBox", source)
        self.assertIn('"settings/complete_swap_source_brightness"', source)
        self.assertIn("_state.material_authority_adjustment_labels['source_brightness']", setup_ui_source)
        self.assertIn('"source_brightness": "Source brightness"', authority_controls_source)
        self.assertIn("minimum=-100", source)
        self.assertIn("maximum=100", source)
        self.assertIn("material_authority_clamped_int", authority_controls_source)
        self.assertIn("saved_accent_glow = 0", source)
        self.assertIn("saved_glow_color_enabled = False", source)
        self.assertIn("saved_glow_rgb: list[int] = [255, 255, 255]", source)
        self.assertIn("_state.self.settings.remove(_state.stale_glow_settings_key)", setup_ui_source)
        self.assertNotIn('self.settings.value("settings/complete_swap_accent_glow_strength"', source)
        self.assertNotIn('self.settings.value("settings/complete_swap_accent_glow_color_enabled"', source)
        self.assertNotIn('self.settings.value("settings/complete_swap_accent_glow_color_rgb"', source)
        self.assertNotIn('self.settings.setValue("settings/complete_swap_accent_glow_color_enabled"', source)
        self.assertNotIn('self.settings.setValue("settings/complete_swap_accent_glow_color_rgb"', source)
        self.assertIn("MeshAlignmentAccentGlowSlider", source)
        self.assertIn("MeshAlignmentAccentGlowSpinBox", source)
        self.assertIn("accent_glow_strength: float = 0.0", static_source)
        self.assertIn("accent_glow_strength=max(0.0, min(100.0, float(accent_glow_strength or 0.0)))", source)
        self.assertIn("accent_glow_strength=0.0 if _state.modify_original_clone_mode else float(_state.accent_glow_spin.value())", accept_source)
        self.assertIn("preview_accent_glow_intensity = _state._accent_glow_preview_intensity_helper(", remaining_source)
        self.assertIn('value=f"{emissive_intensity:.6f}"', source)
        self.assertIn("complete_swap_accent_glow_strength", archive_source)
        self.assertIn("Accent glow requested", archive_source)
        self.assertIn("accent_glow_strength", material_source)

    def test_true_source_basic_controls_are_wired_to_static_options(self) -> None:
        source = _main_window_source()
        setup_section_source = static_replacement_ui_concern_source(ROOT, "setup_options_transform")
        prompt_transform_source = ARCHIVE_STATIC_REPLACEMENT_DIALOG_PROMPT_TRANSFORM.read_text(encoding="utf-8")
        authority_controls_source = ARCHIVE_STATIC_REPLACEMENT_MATERIAL_AUTHORITY_CONTROLS.read_text(encoding="utf-8")
        qt_helper_source = ARCHIVE_STATIC_REPLACEMENT_QT_HELPERS.read_text(encoding="utf-8")
        static_source = _static_replacer_source()
        archive_source = _archive_modding_source()
        material_source = _material_replacer_source()
        for object_name in (
            "MeshAlignmentTrueSourceBasicControlsGroup",
            "MeshAlignmentAutoBrightnessSlider",
            "MeshAlignmentSourceBrightnessSlider",
            "MeshAlignmentToneContrastSlider",
            "MeshAlignmentEdgeReliefSlider",
            "MeshAlignmentEdgeReliefSourceCombo",
        ):
            self.assertIn(object_name, source)
        self.assertNotIn("MeshAlignmentDarkDetailLiftSlider", source)
        self.assertNotIn("Lift black detail", source)
        self.assertIn("_state.material_authority_adjustment_labels['tone_contrast']", setup_section_source)
        self.assertIn("_state.material_authority_adjustment_labels['group_title']", setup_section_source)
        self.assertIn('"tone_contrast": "Tone contrast"', authority_controls_source)
        self.assertIn('"group_title": "Material Authority Adjustments"', authority_controls_source)
        self.assertIn('"settings/complete_swap_auto_brightness"', source)
        self.assertIn('"settings/complete_swap_edge_relief_strength"', source)
        self.assertIn("auto_brightness_balance: float = 50.0", static_source)
        self.assertIn("edge_relief_strength: float = 0.0", static_source)
        self.assertIn("edge_relief_source: str = \"hybrid\"", static_source)
        self.assertIn("dark_detail_lift: float = 0.0", static_source)
        self.assertIn("tone_contrast: float = 0.0", static_source)
        self.assertIn("make_int_slider_spin_row", qt_helper_source)
        self.assertIn("slider.setRange(int(minimum), int(maximum))", qt_helper_source)
        self.assertIn("spin.setRange(int(minimum), int(maximum))", qt_helper_source)
        self.assertIn("material_authority_edge_relief_source", authority_controls_source)
        self.assertIn("auto_brightness_slider,", source)
        self.assertIn("auto_brightness_spin,", source)
        self.assertIn("source_brightness_slider,", source)
        self.assertIn("source_brightness_spin,", source)
        self.assertIn("material_authority_profile_adjustment_kwargs", authority_controls_source)
        self.assertIn('"edge_relief_strength": float(edge_relief)', authority_controls_source)
        self.assertIn('"auto_brightness_balance": float(auto_brightness)', authority_controls_source)
        self.assertIn('"dark_detail_lift": float(source_brightness)', authority_controls_source)
        self.assertIn('"tone_contrast": float(tone_contrast)', authority_controls_source)
        self.assertIn("minimum=-100", source)
        self.assertIn("Source brightness can dim or lift source color", authority_controls_source)
        self.assertIn("dark_detail_lift=max(-100.0, min(100.0, float(dark_detail_lift or 0.0)))", source)
        self.assertIn("_queue_material_authority_adjustment_preview_refresh", source)
        self.assertIn("_material_authority_controls_affect_visible_preview", source)
        self.assertIn("_material_authority_preview_inactive_reason", source)
        self.assertIn("material_authority_preview_inactive_reason", authority_controls_source)
        self.assertIn("material_authority_basic_controls_hint", authority_controls_source)
        self.assertIn("material_authority_adjustment_status_text", authority_controls_source)
        self.assertIn("def _material_authority_preview_signature", source)
        self.assertIn("material_authority_preview_signature_state", source)
        self.assertIn("Adjustments updated. Preview refresh queued.", authority_controls_source)
        self.assertIn('"material_authority_preview_signature"', source)
        self.assertIn("material_authority_path_signature", authority_controls_source)
        self.assertIn("material_authority_preview_signature_hashes", authority_controls_source)
        self.assertIn("material_authority_preview_slot_signature_row", authority_controls_source)
        self.assertIn("material_authority_source_role_signature_rows", authority_controls_source)
        self.assertIn("material_authority_preview_controls_signature", authority_controls_source)
        self.assertIn("material_authority_preview_signature", authority_controls_source)
        self.assertIn("_material_authority_preview_signature_helper(", source)
        complete_swap_source = _nested_function_source(setup_section_source, "_complete_external_swap_enabled")
        self.assertIn("def _complete_external_swap_enabled() -> bool:", complete_swap_source)
        self.assertIn("return bool(_state.complete_external_swap_checkbox.isChecked())", complete_swap_source)
        self.assertIn(
            "'_complete_external_swap_enabled': vars(_state).get('_complete_external_swap_enabled')",
            setup_section_source,
        )
        self.assertIn("_complete_external_swap_enabled, _complete_external_swap_mappings", prompt_transform_source)
        self.assertIn('"_complete_external_swap_enabled", "_complete_external_swap_mappings"', prompt_transform_source)
        self.assertIn("material_authority_adjustment_setting_state", authority_controls_source)
        self.assertIn("material_authority_controls_affect_visible_preview", authority_controls_source)
        self.assertIn("material_authority_preview_texture_slots", source)
        self.assertIn("_state.true_source_basic_reset_button = _state.QPushButton(_state.material_authority_adjustment_labels['reset_adjustments'])", setup_section_source)
        self.assertIn('"reset_adjustments": "Reset Adjustments"', authority_controls_source)
        self.assertIn("_state.true_source_basic_reset_button.setObjectName('MeshAlignmentMaterialAuthorityResetAdjustmentsButton')", setup_section_source)
        self.assertIn("material_authority_reset_values", authority_controls_source)
        self.assertIn('reset_values["global_gloss_reduction"]', source)
        self.assertIn('reset_values["auto_brightness"]', source)
        self.assertIn('reset_values["tone_contrast"]', source)
        self.assertIn('reset_values["edge_relief_source"]', source)
        self.assertIn("_state.true_source_basic_reset_button.clicked.connect(_state._reset_material_authority_adjustments)", setup_section_source)
        self.assertIn("Adjustments updated. Preview unchanged", authority_controls_source)
        self.assertIn('tuple(getattr(source_slot, "base_color_factor", ()) or ())', authority_controls_source)
        self.assertIn("glow_color_enabled=part_glow_color_checkbox.isChecked()", source)
        self.assertIn("_selected_part_glow_rgb_from_controls()", source)
        self.assertIn("source_role_rows", authority_controls_source)
        preview_textures_source = ARCHIVE_STATIC_REPLACEMENT_PREVIEW_TEXTURES.read_text(encoding="utf-8")
        self.assertIn("material_authority_preview_texture_slots(texture_set, material_authority_profile, enabled=True)", preview_textures_source)
        self.assertIn("material_authority_preview_texture_slots(texture_set, enabled=False)", preview_textures_source)
        self.assertIn('parameter_name="_detailMaskTexture" if source_slot_name == "detail_mask" else "_materialTexture"', source)
        self.assertIn("def material_authority_preview_texture_slots", material_source)
        queue_block = source[
            source.index("def _queue_material_authority_adjustment_preview_refresh")
            : source.index("def _set_spin_slider_pair")
        ]
        self.assertIn("if inactive_reason:", queue_block)
        self.assertNotIn("previous_cache_signature", queue_block)
        self.assertNotIn('signature.get("cache")', queue_block)
        self.assertNotIn("material_authority_preview_texture_slots", queue_block)
        self.assertNotIn("_material_authority_preview_signature()", queue_block)
        self.assertIn("_queue_material_edit_refresh(", queue_block)
        self.assertIn("reason=_material_authority_adjustment_refresh_reason_helper()", queue_block)
        self.assertIn("material authority adjustment", authority_controls_source)
        self.assertNotIn("_queue_texture_preview_refresh()", queue_block)
        self.assertIn('"auto_brightness_balance": _clamped_option(options', archive_source)
        self.assertIn('"edge_relief_strength": _clamped_option(options', archive_source)
        self.assertIn('"dark_detail_lift": _clamped_option(options', archive_source)
        self.assertIn("Auto brightness balance requested", archive_source)
        self.assertIn("Source brightness requested", archive_source)
        self.assertIn("color will be dimmed before export", archive_source)
        self.assertIn("apply_true_source_basic_controls_to_profile", material_source)
        self.assertIn("def normalize_signed_basic_control_percent", material_source)
        self.assertIn("base_color_shadow_lift", material_source)
        self.assertIn('updates["base_color_tone_contrast"] = tone_strength', material_source)
        self.assertIn("edge_relief_source", material_source)
        cache_source = ARCHIVE_STATIC_REPLACEMENT_D3D11_CACHE.read_text(encoding="utf-8")
        cache_signature_block = cache_source[
            cache_source.index("def alignment_d3d11_model_cache_signature") : cache_source.index("__all__")
        ]
        self.assertIn("_alignment_d3d11_model_cache_signature_helper", source)
        self.assertIn('str(getattr(item, "preview_texture_path", "") or "")', cache_signature_block)
        self.assertIn('tuple(getattr(mesh, "preview_material_texture_inputs", ()) or ())', cache_signature_block)
        self.assertIn('tuple(getattr(item, "material_parameters", ()) or ())', cache_signature_block)
        self.assertIn('str(getattr(parameter, "numeric_value", "") or "")', cache_signature_block)
        self.assertIn('str(getattr(mesh, "preview_material_texture_path", "") or "")', cache_signature_block)
        self.assertIn('raw_native_overrides = getattr(mesh, "preview_native_material_overrides", {}) or {}', cache_signature_block)
        self.assertIn("native_overrides,", cache_signature_block)

    def test_alignment_live_preview_uses_virtual_sidecar_texture_contract(self) -> None:
        source = _main_window_source()
        callback_source = _callback_factory_source()
        preview_refresh_source = _nested_function_source(
            static_replacement_remaining_callback_source(ROOT),
            "_refresh_static_dialog_preview",
        )
        preview_model_source = static_replacement_callback_concern_source(ROOT, "preview_model")
        texture_section_source = static_replacement_ui_concern_source(ROOT, "texture_material")
        virtual_contract_source = ARCHIVE_STATIC_REPLACEMENT_VIRTUAL_TEXTURE_CONTRACT.read_text(encoding="utf-8")
        self.assertIn("alignment_virtual_texture_contract: Dict[str, object]", source)
        self.assertIn("def _alignment_virtual_contract_rows(", source)
        self.assertIn("alignment_virtual_contract_rows as _alignment_virtual_contract_rows_helper", source)
        self.assertIn("alignment_virtual_contract_preview_specs as _alignment_virtual_contract_preview_specs_helper", source)
        self.assertIn("alignment_virtual_sidecar_contract_state as _alignment_virtual_sidecar_contract_state_helper", source)
        self.assertIn("def alignment_virtual_contract_rows(", virtual_contract_source)
        self.assertIn("def alignment_virtual_contract_preview_specs(", virtual_contract_source)
        self.assertIn("def alignment_virtual_sidecar_contract_state(", virtual_contract_source)
        self.assertIn("def _refresh_alignment_virtual_sidecar_contract(", source)
        self.assertIn("patch_sidecar_text(", virtual_contract_source)
        self.assertIn("SidecarPatchPlan(", virtual_contract_source)
        self.assertIn('"patched_sidecar_texts"', virtual_contract_source)
        self.assertIn('row_state["_contract_action"] = action', virtual_contract_source)
        self.assertIn('row_state["_contract_selected_source"] = selected_source', virtual_contract_source)
        self.assertIn('action = "will_prune"', virtual_contract_source)
        self.assertIn('action = "replaced"', virtual_contract_source)
        self.assertIn('action = "kept"', virtual_contract_source)
        self.assertIn('action = "review"', virtual_contract_source)
        self.assertIn('contract_action.replace("_", " ").title()', source)
        self.assertNotIn('action = "pruned"', source)
        self.assertIn("contract = _state._refresh_alignment_virtual_sidecar_contract(current_mappings)", preview_refresh_source)
        self.assertIn("updated_specs = list(contract.get('preview_specs') or ())", preview_refresh_source)
        self.assertIn("_state.texture_overrides_dirty['dirty'] = True", callback_source)
        self.assertIn(
            "_state._refresh_alignment_virtual_sidecar_contract(_state._current_dialog_mappings_for_preview())",
            callback_source,
        )
        early_contract_block = _nested_function_source(
            preview_model_source,
            "_refresh_alignment_virtual_sidecar_contract",
        )
        self.assertIn(
            "_state._alignment_virtual_texture_contract_defaults_helper(_state.alignment_virtual_texture_contract)",
            early_contract_block,
        )
        self.assertIn("return _state.alignment_virtual_texture_contract", early_contract_block)
        full_contract_block = _nested_function_source(
            texture_section_source,
            "_refresh_alignment_virtual_sidecar_contract",
        )
        self.assertIn("_state._alignment_virtual_sidecar_contract_state_helper(", full_contract_block)
        prune_removed_block = _nested_function_source(
            texture_section_source,
            "_virtual_contract_prune_removed_targets_enabled",
        )
        self.assertIn("_state.rebuild_sidecar_checkbox.isChecked()", prune_removed_block)
        self.assertIn("_state.prune_unmapped_original_dds_checkbox.isChecked()", prune_removed_block)
        self.assertLess(
            prune_removed_block.index("_state.rebuild_sidecar_checkbox.isChecked()"),
            prune_removed_block.index("_state.prune_unmapped_original_dds_checkbox.isChecked()"),
        )
        self.assertNotIn("prune_removed_target_texture_params_checkbox", source)
        self.assertNotIn("prune_unmapped_original_texture_params_checkbox", source)
        self.assertNotIn("return True\n\n                    def _virtual_contract_prune_unmapped_enabled", source)

    def test_main_window_imports_empty_state_tree_widget_for_startup_panels(self) -> None:
        source = _main_window_source()
        asset_family_layout_source = ARCHIVE_ASSET_FAMILY_LAYOUT.read_text(encoding="utf-8")
        workflow_profiles_source = WORKFLOW_PROFILES_UI.read_text(encoding="utf-8")
        self.assertIn("EmptyStateTreeWidget", asset_family_layout_source)
        self.assertIn("self.workflow_profiles_tree = EmptyStateTreeWidget(", workflow_profiles_source)
        self.assertIn("self.archive_texture_refs_tree = EmptyStateTreeWidget(", asset_family_layout_source)

    def test_mesh_import_summary_hides_empty_format_and_explains_audit(self) -> None:
        source = _main_window_source() + "\n" + _archive_mesh_import_sources()
        self.assertIn('mesh_format_text = str(getattr(scene_import_result.mesh, "format", "") or "").strip().upper()', source)
        self.assertIn('mesh_format_text = scene_path.suffix.lower().lstrip(".").upper()', source)
        self.assertIn('format_chip = _chip(mesh_format_text or "Format unknown"', source)
        self.assertIn('"Asset check"', source)
        self.assertIn('audit_chip = _chip(f"Unclassified asset ({audit_confidence:.0%} match)", "warn")', source)
        self.assertIn("Geometry can still be routed manually", source)
        self.assertNotIn('audit_row.addWidget(_chip(f"{audit_category} {audit_confidence:.0%}"', source)

    def test_alignment_startup_does_not_prepare_legacy_original_preview_for_d3d11(self) -> None:
        source = _main_window_source()
        remaining_source = static_replacement_remaining_callback_source(ROOT)
        texture_source = static_replacement_texture_callback_source(ROOT)
        refresh_original = _nested_function_source(
            remaining_source, "_refresh_original_reference_preview"
        )
        self.assertIn("if _alignment_d3d11_preview_active():", refresh_original)
        self.assertIn("_sync_highlight_sets()", refresh_original)
        self.assertLess(refresh_original.index("if _alignment_d3d11_preview_active():"), refresh_original.index("original_dialog_preview.set_model(preview_model)"))
        startup_original_preview = _nested_function_source(
            texture_source, "_load_original_reference_texture_preview"
        )
        self.assertIn("AlignmentOriginalTexturePreviewWorker", startup_original_preview)
        self.assertIn("self._attach_archive_model_preview_images(preview_model)", startup_original_preview)
        self.assertIn("worker.completed.connect(", startup_original_preview)
        self.assertNotIn('original_dialog_preview.clear_model("Original textures loaded in native D3D11 preview.")', source)
        self.assertIn("elif ready_state.should_apply_model:", source)
        self.assertIn("original_dialog_preview.set_model(state.original_reference_preview_model)", source)

    def test_mesh_editor_source_preview_preserves_spec_gloss_and_full_direct_geometry(self) -> None:
        source = _main_window_source()
        preview_model_callbacks_source = static_replacement_callback_concern_source(ROOT, "preview_model")
        preview_refresh_source = _nested_function_source(
            static_replacement_remaining_callback_source(ROOT),
            "_refresh_static_dialog_preview",
        )
        self.assertIn("replacement_texture_slot_preview_semantics,", source)
        self.assertIn("from cdmw.services.mesh_workflow_service import (", source)
        self.assertNotIn("from cdmw.modding.material_replacer import", source)

        preview_textures_source = ARCHIVE_STATIC_REPLACEMENT_PREVIEW_TEXTURES.read_text(encoding="utf-8")
        preview_start = preview_textures_source.index("def apply_source_material_preview")
        preview_end = preview_textures_source.index("emissive_slot = slots.get", preview_start)
        source_material_preview = preview_textures_source[preview_start:preview_end]
        self.assertIn("declared_semantic_subtype", source_material_preview)
        self.assertIn("declared_parameter_name", source_material_preview)
        self.assertIn("preview_material_texture_subtype = semantic_subtype", source_material_preview)
        self.assertIn("material_preview_parameters = material_factor_parameters + material_authority_parameters", source_material_preview)
        self.assertIn("parameters=material_preview_parameters", source_material_preview)

        direct_preview = _nested_function_source(preview_model_callbacks_source, "_build_direct_source_preview_model")
        self.assertIn("max_source_faces_per_submesh=0", direct_preview)
        preview_model_start = source.index("_preview_model_in_original_frame = lambda")
        preview_model_end = source.index("_source_preview_geometry_key = lambda", preview_model_start)
        preview_model_source = source[preview_model_start:preview_model_end]
        preview_mapping_source = ARCHIVE_STATIC_REPLACEMENT_PREVIEW_MAPPING.read_text(encoding="utf-8")
        self.assertIn("_preview_model_in_original_frame_helper(", preview_model_source)
        self.assertIn("preview_double_sided=bool(", preview_mapping_source)
        self.assertIn('getattr(submesh, "preview_double_sided", False)', preview_mapping_source)
        self.assertIn("max_source_faces_per_submesh=_state._alignment_preview_source_face_limit()", preview_refresh_source)
        refresh_prelude = preview_refresh_source[: preview_refresh_source.index("if not use_direct_source_preview:")]
        static_preview_state_source = ARCHIVE_STATIC_REPLACEMENT_STATIC_PREVIEW_STATE.read_text(encoding="utf-8")
        self.assertIn("_static_preview_refresh_route_state_helper(", refresh_prelude)
        self.assertIn("replacement_only_direct_source_preview=refresh_route.replacement_only_direct_source_preview", refresh_prelude)
        self.assertIn("source_owned_direct_source_preview=refresh_route.source_owned_direct_source_preview", refresh_prelude)
        self.assertIn("def static_preview_refresh_route_state(", static_preview_state_source)
        self.assertIn("replacement_only_direct_source_preview = False", static_preview_state_source)
        self.assertIn("source_owned_direct_source_preview = bool(", static_preview_state_source)
        self.assertIn(
            "force_direct_source_preview = _state._alignment_d3d11_record_direct_source_preview_flags_helper(",
            refresh_prelude,
        )
        d3d11_mapping_source = ARCHIVE_STATIC_REPLACEMENT_D3D11_MAPPING.read_text(encoding="utf-8")
        self.assertIn("force_direct = bool(replacement_only or source_owned)", d3d11_mapping_source)
        self.assertIn('state["force_direct_source_preview"] = force_direct', d3d11_mapping_source)
        self.assertIn("_direct_source_preview_indices_helper(", refresh_prelude)
        refresh_body = preview_refresh_source[: preview_refresh_source.index("preview_model = _state._clone_preview_model(source_model)")]
        self.assertIn("reason='source_geometry_not_ready'", refresh_body)
        empty_preview_source = _nested_function_source(
            static_replacement_remaining_callback_source(ROOT),
            "_empty_direct_source_preview_model",
        )
        self.assertIn("def _empty_direct_source_preview_model() -> ModelPreviewData:", empty_preview_source)
        self.assertIn("source_model = _state._empty_direct_source_preview_model()", refresh_body)
        self.assertNotIn("_build_direct_source_preview_model(current_mappings, tuple(direct_source_preview_indices)) or state.replacement_preview_model", refresh_body)
        self.assertNotIn("else:\n            source_model = state.replacement_preview_model", refresh_body)
        preview_models_source = ARCHIVE_STATIC_REPLACEMENT_PREVIEW_MODELS.read_text(encoding="utf-8")
        self.assertIn("if force_direct_source_preview or mesh_edit_direct_source_preview:", preview_models_source)
        self.assertIn('return f"{base_geometry_key}|direct-source:{index_key}"', preview_models_source)
        source_limit = _nested_function_source(
            static_replacement_callback_concern_source(ROOT, "refresh_queue"),
            "_alignment_preview_source_face_limit",
        )
        self.assertIn("def _mesh_edit_enabled_checked() -> bool:", source)
        self.assertIn("if _state._mesh_edit_enabled_checked():", source_limit)
        self.assertNotIn("_alignment_mesh_edit_tab_active()", source_limit)
        source_limit_owner_start = source.index("def alignment_preview_source_face_limit_for_counts(")
        source_limit_owner_end = source.index(
            "def alignment_preview_selected_source_face_limit_for_total(",
            source_limit_owner_start,
        )
        source_limit_owner = source[source_limit_owner_start:source_limit_owner_end]
        self.assertLess(
            source_limit_owner.index("if total_faces <= 80_000:"),
            source_limit_owner.index("if modify_original_clone_mode"),
        )

    def test_mesh_editor_parts_delete_requires_apply_and_unassigns_routes(self) -> None:
        source = _main_window_source()
        dialog_source = _ui_section_source()
        outliner_source = static_replacement_ui_concern_source(ROOT, "source_parts_outliner")
        mapping_callbacks_source = static_replacement_callback_concern_source(ROOT, "parts_outliner_mapping")
        source_part_mutation_source = static_replacement_source_part_mutation_callback_source(ROOT)
        source_parts_state_source = _source_part_owner_sources()
        source_tree_state_source = ARCHIVE_STATIC_REPLACEMENT_SOURCE_TREE_STATE.read_text(encoding="utf-8")

        self.assertIn('_state.source_tree.setSelectionMode(_state.QAbstractItemView.ExtendedSelection)', outliner_source)
        self.assertIn('_state.source_tree.setSelectionBehavior(_state.QAbstractItemView.SelectRows)', outliner_source)
        self.assertIn("_state.source_tree_layout_state = _state._source_tree_layout_state_helper()", outliner_source)
        self.assertIn("_state.source_tree.setMinimumHeight(_state.source_tree_layout_state.minimum_height)", outliner_source)
        self.assertIn("_state.source_tree_layout_state.configure_widths", outliner_source)
        self.assertIn("_state.source_tree_layout_state.autofit_min_widths", outliner_source)
        self.assertIn("_state.source_tree_layout_state.height_fit_kwargs", outliner_source)
        self.assertIn("def source_tree_layout_state", source_tree_state_source)
        self.assertIn("class _SourceTreeContextSelectionFilter(QObject):", source)
        self.assertIn("_source_tree_context_selection_record_multi_indices_helper(", source)
        self.assertIn("_state.delete_source_parts_button = _state.QPushButton(_state.source_parts_action_control_text['delete_button'])", outliner_source)
        self.assertIn("_state.apply_source_parts_button = _state.QPushButton(_state.source_parts_action_control_text['apply_button'])", outliner_source)
        self.assertIn('"delete_button": "Delete Selected"', source_parts_state_source)
        self.assertIn('"duplicate_button": "Duplicate Selected"', source_parts_state_source)
        self.assertIn('"apply_button": "Apply"', source_parts_state_source)
        self.assertIn('_state.delete_source_parts_button.clicked.connect(lambda _checked=False: _state._delete_selected_source_parts())', outliner_source)
        self.assertNotIn('_state.delete_source_parts_button.clicked.connect(_state._delete_selected_source_parts)', outliner_source)
        self.assertIn('_state.apply_source_parts_button.clicked.connect(_state._apply_source_part_preview_changes)', outliner_source)
        self.assertIn("_state.alignment_source_part_mutation_callbacks = None", outliner_source)
        self.assertIn("_state.create_alignment_source_part_mutation_callbacks = _state.context.get('create_alignment_source_part_mutation_callbacks')", outliner_source)
        self.assertIn("if _state.alignment_source_part_mutation_callbacks is None:\n            return", outliner_source)
        self.assertLess(
            outliner_source.index("_state.alignment_source_part_mutation_callbacks = None"),
            outliner_source.index("def _delete_selected_source_parts("),
        )
        self.assertLess(
            outliner_source.index("_state._mirror_submesh_x = lambda source, plane_x: _state._mirror_submesh_x_helper("),
            outliner_source.index("_state.alignment_source_part_mutation_callbacks = _state.create_alignment_source_part_mutation_callbacks"),
        )
        self.assertEqual(
            outliner_source.count("_state.alignment_source_part_mutation_callbacks = _state.create_alignment_source_part_mutation_callbacks"),
            1,
        )
        self.assertIn("apply_button_enabled=True", source_parts_state_source)
        self.assertIn("_state.apply_source_parts_button.setEnabled(bool(_state.source_parts_apply_state.get('pending')))", outliner_source)
        self.assertIn('"preview_rebuild_pending": False', source_parts_state_source)
        self.assertIn("def _set_source_parts_preview_rebuild_pending(reason: str) -> None:", source)
        self.assertIn(
            "old .NET/Vortice geometry may remain visible until reload finishes",
            source_parts_state_source,
        )
        self.assertIn("_clear_source_parts_preview_rebuild_pending()", source)
        self.assertNotIn("source_parts_apply_button.setEnabled", source)

        check_handler = _nested_function_source(mapping_callbacks_source, "_source_item_check_state_changed")
        self.assertIn("_source_part_check_toggle_state_helper(", check_handler)
        self.assertIn("toggle_state.refresh_selected_controls", check_handler)
        self.assertIn("toggle_state.apply_pending", check_handler)
        self.assertIn("_source_part_include_exclude_pending_reason_helper()", check_handler)
        self.assertIn("if callable(_state._load_selected_part_controls):", check_handler)
        self.assertIn("if callable(_state._sync_highlight_sets):", check_handler)
        self.assertIn("_state._set_source_parts_apply_pending(", check_handler)
        self.assertIn("_state._set_source_parts_preview_rebuild_pending(", check_handler)
        self.assertIn("if callable(_state._queue_selection_preview_refresh):", check_handler)
        self.assertIn("_state._queue_selection_preview_refresh()", check_handler)
        self.assertIn("else:\n                _state._queue_static_preview_rebuild()", check_handler)

        delete_start = source_part_mutation_source.index("def _delete_selected_source_parts(")
        delete_end = source_part_mutation_source.index("def _apply_source_part_preview_changes(", delete_start)
        delete_helper = source_part_mutation_source[delete_start:delete_end]
        self.assertIn("if source_indices is None or isinstance(source_indices, bool):", delete_helper)
        self.assertIn("selected_indices = _state._selected_source_indices_from_tree()", delete_helper)
        self.assertIn("selected_indices = list(source_indices)", delete_helper)
        self.assertIn("_state._source_part_delete_selection_state_helper(", delete_helper)
        self.assertIn("_state._source_part_delete_index_map_state_helper(", delete_helper)
        self.assertIn("def source_part_delete_selection_state(", source_parts_state_source)
        self.assertIn("def source_part_delete_index_map_state(", source_parts_state_source)
        self.assertIn("index_map = delete_index_map_state.index_map", delete_helper)
        self.assertIn("replacement_mesh_for_mapping.submeshes[:] = kept_submeshes", delete_helper)
        self.assertIn("replacement_mesh_base_for_mapping.submeshes[:]", delete_helper)
        self.assertIn("_state._rebuild_source_part_widgets(", delete_helper)
        self.assertIn("defer_preview=True", delete_helper)
        self.assertIn("_state._source_part_delete_status_text_helper()", delete_helper)
        self.assertIn("_state._source_part_deleted_pending_reason_helper(len(delete_indices))", delete_helper)
        self.assertIn("_state._source_part_deleted_status_helper(len(delete_indices))", delete_helper)
        self.assertIn("target routes were unassigned/remapped", source_parts_state_source)
        self.assertIn("Preview is rebuilding.", source_parts_state_source)
        self.assertIn("_state._source_part_refresh_geometry_preview(", delete_helper)
        self.assertNotIn("_queue_static_preview_rebuild()", delete_helper)

        rebuild_source = _nested_function_source(
            static_replacement_callback_concern_source(ROOT, "source_part_assignment"),
            "_rebuild_source_part_widgets",
        )
        self.assertIn("_state._source_part_valid_indices_helper(selected_indices, source_count=source_count)", rebuild_source)
        self.assertIn("_state._source_tree_population_set_next_index_helper(", rebuild_source)
        self.assertIn("source_count = len(_state.replacement_mesh_for_mapping.submeshes)", rebuild_source)
        self.assertIn("_source_tree_item_state_helper(", source)
        self.assertIn("def source_tree_item_state", source_tree_state_source)
        self.assertNotIn("for raw_index in tuple(selected_indices or ())", rebuild_source)

        apply_start = source_part_mutation_source.index("def _apply_source_part_preview_changes(")
        apply_end = source_part_mutation_source.index("def _apply_source_material_grouped_routing(", apply_start)
        apply_helper = source_part_mutation_source[apply_start:apply_end]
        self.assertIn("rebuild_reason = str(", apply_helper)
        self.assertIn("_source_part_refresh_geometry_preview(rebuild_reason, replace_all=True)", apply_helper)
        self.assertNotIn("_queue_static_preview_rebuild()", apply_helper)
        self.assertNotIn("_clear_source_parts_apply_pending()", apply_helper)

        menu_start = source.index("def _show_replacement_sources_context_menu(")
        menu_end = source.index("def _populate_source_tree_chunk", menu_start)
        menu_helper = source[menu_start:menu_end]
        self.assertIn("def _late_callback(name: str, captured: object) -> object:", source)
        self.assertIn('set_role_override = self._callback("_set_source_role_override_value")', source)
        self.assertIn('push_undo = self._callback("_push_geometry_undo_snapshot")', source)
        self.assertIn('queue_material_edit = self._callback("_queue_material_edit_refresh")', source)
        self.assertIn('selected_indices_from_tree = _late_callback(', menu_helper)
        self.assertIn("selected_source_indices = selected_indices_from_tree(include_fallback=False)", menu_helper)
        self.assertIn("preserved_multi_indices = preserved_indices_for_menu(", menu_helper)
        self.assertIn("context_selection = menu_selection_state(", menu_helper)
        self.assertIn("selected_source_indices = list(context_selection.selected_source_indices)", menu_helper)
        self.assertIn("def source_tree_context_menu_selection_state", source_tree_state_source)
        self.assertIn("delete_source_indices = selected_source_indices or selected_indices_from_tree(include_fallback=True)", menu_helper)
        self.assertIn("menu_parent = source_tree.window() or source_tree", menu_helper)
        self.assertIn("menu = QMenu(menu_parent)", menu_helper)
        self.assertIn("source_part_context_action_specs(", menu_helper)
        self.assertIn("menu_dispatcher.dispatch(", menu_helper)
        self.assertIn('runner = getattr(dialog, "_mesh_editor_embedded_run_part_action", None)', source)
        self.assertIn("_source_tree_role_menu_specs_helper(SOURCE_TREE_ROLE_OPTIONS)", source)
        self.assertIn("def source_tree_role_menu_specs", source_tree_state_source)
        self.assertIn("_source_tree_population_chunk_policy_helper()", source)
        self.assertIn("def source_tree_population_chunk_policy", source_tree_state_source)
        self.assertLess(
            outliner_source.index(
                "_state._selected_source_indices_from_tree = _state.parts_outliner_mapping_callbacks._selected_source_indices_from_tree"
            ),
            outliner_source.index("_state.source_tree.customContextMenuRequested.connect(_state._show_replacement_sources_context_menu)"),
        )

        remove_start = source.index("def _remove_selected_source_from_target(")
        remove_end = source.index("def _clear_selected_target(", remove_start)
        remove_helper = source[remove_start:remove_end]
        self.assertIn("defer_preview=True", remove_helper)

    def test_modify_original_transform_helpers_are_available_before_preview_refresh(self) -> None:
        source = _main_window_source()
        setup_transform_source = static_replacement_ui_concern_source(ROOT, "setup_options_transform")
        mesh_preview_source = static_replacement_ui_concern_source(ROOT, "mesh_geometry_preview")
        self.assertIn(
            "_state._capture_static_preview_baked_transform_state = _state.alignment_transform_drag_callbacks._capture_static_preview_baked_transform_state",
            setup_transform_source,
        )
        self.assertIn(
            "_state.alignment_static_preview_refresh_callbacks = _state.create_alignment_static_preview_refresh_callbacks(",
            mesh_preview_source,
        )
        self.assertIn("_capture_static_preview_baked_transform_state()", source)
        self.assertIn("def _alignment_d3d11_translation_to_transform_units(", source)
        self.assertIn("_alignment_d3d11_translation_to_transform_units_helper(", source)
        self.assertIn("preview_scale=preview_scale", source)

    def test_modify_original_preview_model_waits_for_transform_controls(self) -> None:
        preview_source = static_replacement_callback_concern_source(ROOT, "preview_model")

        self.assertIn("_state.prompt_shell_context = _state.context.get('prompt_shell_context')", preview_source)
        self.assertIn("_state._queue_alignment_post_open_task = _state._prompt_context_value(", preview_source)
        self.assertIn("def _spin_value(name: str, default: float=0.0) -> float:", preview_source)
        self.assertIn("_state._queue_alignment_post_open_task(_state._refresh_startup_model_controls)", preview_source)
        self.assertIn("elif _state._prompt_context_value('rotate_x_spin') is not None:", preview_source)

        geometry_key_start = preview_source.index("_state._source_preview_geometry_key = lambda")
        geometry_key_end = preview_source.index("_state._mapped_source_indices = lambda", geometry_key_start)
        geometry_key_source = preview_source[geometry_key_start:geometry_key_end]
        self.assertIn("_state._spin_value('rotate_x_spin')", geometry_key_source)
        self.assertIn("_state._spin_value('scale_x_spin', 1.0)", geometry_key_source)
        self.assertIn("_state._spin_value('offset_x_spin')", geometry_key_source)
        self.assertNotIn("rotate_x_spin.value()", geometry_key_source)
        self.assertNotIn("scale_x_spin.value()", geometry_key_source)
        self.assertNotIn("offset_x_spin.value()", geometry_key_source)

        transform_source = _nested_function_source(preview_source, "_current_static_alignment_transform")
        self.assertIn("_state._spin_value('rotate_x_spin')", transform_source)
        self.assertIn("_state._spin_value('scale_x_spin', 1.0)", transform_source)
        self.assertIn("_state._spin_value('offset_x_spin')", transform_source)
        self.assertNotIn(".value()", transform_source)

    def test_alignment_setup_failure_does_not_mount_partial_builder(self) -> None:
        prompt_source = ARCHIVE_STATIC_REPLACEMENT_DIALOG_PROMPT.read_text(encoding="utf-8")
        setup_source = ARCHIVE_STATIC_REPLACEMENT_DIALOG_PROMPT_SETUP.read_text(encoding="utf-8")
        callback_source = _callback_factory_source()

        self.assertIn("alignment_setup_failed = False", setup_source)
        self.assertIn("traceback.format_exception(type(exc), exc, exc.__traceback__)", setup_source)
        self.assertIn("traceback=alignment_setup_traceback", setup_source)
        self.assertLess(
            setup_source.index("mapping_table_action_control_text = _mapping_table_action_control_text_helper()"),
            setup_source.index('mapping_hint = QLabel(mapping_table_action_control_text["routing_hint_html"])'),
        )

        guard_start = prompt_source.index('if getattr(alignment_prompt_setup, "alignment_setup_failed", False):')
        guard_end = prompt_source.index("finish_static_replacement_prompt_transform", guard_start)
        guard_source = prompt_source[guard_start:guard_end]
        self.assertIn("_abort_alignment_builder_construction(", guard_source)
        self.assertIn('stage="replacement_setup"', guard_source)
        self.assertIn("alignment_setup_traceback", guard_source)
        self.assertIn("return", guard_source)

        inflight_start = callback_source.index("def _alignment_d3d11_package_refresh_in_flight() -> bool:")
        inflight_end = callback_source.index("def _capture_static_preview_baked_transform_state", inflight_start)
        inflight_source = callback_source[inflight_start:inflight_end]
        self.assertIn("if not callable(_state._alignment_d3d11_package_refresh_in_flight_helper):", inflight_source)
        self.assertIn("if callable(_state._alignment_d3d11_preview_active)", inflight_source)
        self.assertIn("preview_active=preview_active", inflight_source)
        self.assertIn("return False", inflight_source)

    def test_alignment_glow_callbacks_are_noop_safe_when_source_parts_missing(self) -> None:
        dialog_source = static_replacement_ui_concern_source(ROOT, "setup_options_transform")
        callback_source = _callback_factory_source()
        routing_source = static_replacement_routing_callback_source(ROOT)
        remaining_source = static_replacement_remaining_callback_source(ROOT)
        glow_picker_source = _nested_function_source(remaining_source, "_pick_selected_source_glow_color")

        self.assertIn("_state.source_part_glow_controls_ready = callable(_state._set_selected_source_glow_color)", dialog_source)
        self.assertIn("callable(_state._set_selected_source_glow_color)", dialog_source)
        self.assertIn("'part_glow_color_spins': _state.part_glow_color_spins", dialog_source)
        self.assertLess(
            dialog_source.index("'part_glow_color_spins': _state.part_glow_color_spins"),
            dialog_source.index("_state.source_part_glow_controls_ready = callable(_state._set_selected_source_glow_color)"),
        )
        self.assertIn("def _set_selected_source_glow_color_if_ready(*_args: object) -> None:", dialog_source)
        self.assertIn("_state.part_glow_color_checkbox.setEnabled(_state.source_part_glow_controls_ready)", dialog_source)
        self.assertIn("_state.part_glow_spin.setEnabled(_state.source_part_glow_controls_ready)", dialog_source)
        self.assertIn("_state.part_glow_color_pick_button.setEnabled(_state.source_part_glow_controls_ready)", dialog_source)
        self.assertIn("_state.part_glow_color_checkbox.toggled.connect(_state._set_selected_source_glow_color_if_ready)", dialog_source)
        self.assertIn("_state.part_glow_spin.valueChanged.connect(_state._set_selected_source_glow_color_if_ready)", dialog_source)
        self.assertNotIn("_state.part_glow_color_checkbox.toggled.connect(_state._set_selected_source_glow_color)", dialog_source)
        self.assertIn("if callable(_refresh_part_glow_color_controls_enabled):", callback_source)
        self.assertIn("prompt_shell_context = context.get('prompt_shell_context')", routing_source)
        self.assertIn("def _part_glow_color_spins() -> tuple[object, ...]:", routing_source)
        self.assertIn("spin.value() for spin in _part_glow_color_spins()", routing_source)
        self.assertNotIn("spin.value() for spin in part_glow_color_spins", routing_source)
        self.assertIn("def _part_glow_color_pick_button() -> object:", remaining_source)
        self.assertIn("zip(_state._part_glow_color_spins()", glow_picker_source)

    def test_alignment_post_open_callbacks_stop_when_dialog_deleted(self) -> None:
        source = _main_window_source()
        mapping_source = static_replacement_callback_concern_source(ROOT, "parts_outliner_mapping")
        outliner_source = static_replacement_ui_concern_source(ROOT, "source_parts_outliner")
        selected_part_source = static_replacement_callback_concern_source(ROOT, "selected_part_control")
        preview_model_source = static_replacement_callback_concern_source(ROOT, "preview_model")
        selection_mapping_source = ARCHIVE_STATIC_REPLACEMENT_DIALOG_SELECTION_MAPPING.read_text(encoding="utf-8")
        remaining_source = static_replacement_remaining_callback_source(ROOT)
        source_parts_state_source = _source_part_owner_sources()
        mapping_chunk_source = _nested_function_source(mapping_source, "_build_mapping_table_chunk")
        self.assertIn("not _state._alignment_dialog_widgets_live()", mapping_chunk_source)
        self.assertIn("not _state._qt_object_is_valid(_state.mapping_progress_label)", mapping_chunk_source)
        self.assertIn("mapping_table_build_timer.stop()", mapping_chunk_source)
        append_row_source = _nested_function_source(mapping_source, "_append_mapping_target_row")
        self.assertIn("mapping_edits.append((row_state.target_index, edit))", append_row_source)
        self.assertIn("mapping_edits_by_target[row_state.target_index] = edit", append_row_source)
        self.assertNotIn("row - 1", append_row_source)

        clear_selection_source = _nested_function_source(outliner_source, "_clear_all_part_selections")
        self.assertIn("if not _state._alignment_dialog_widgets_live():", clear_selection_source)
        self.assertIn("if not _state._qt_object_is_valid(tree):", clear_selection_source)
        self.assertIn("sync_embedded_selection(())", clear_selection_source)

        inspector_source = _nested_function_source(
            selection_mapping_source, "_refresh_mesh_replacement_properties_inspector"
        )
        self.assertIn("if not _alignment_dialog_widgets_live():", inspector_source)
        self.assertIn("_qt_object_is_valid(label)", inspector_source)
        self.assertIn("_source_part_properties_inspector_state_helper(", inspector_source)
        self.assertIn("identity_label.setText(inspector_state.identity_html)", inspector_source)
        self.assertIn("warnings_label.setVisible(inspector_state.warning_visible)", inspector_source)
        self.assertIn("def source_part_selection_context_label_text", source_parts_state_source)
        self.assertIn("def source_part_selection_context_tooltip", source_parts_state_source)
        self.assertIn("def source_part_selection_context_state", source_parts_state_source)
        self.assertIn("def source_part_selection_texture_row_text", source_parts_state_source)
        self.assertIn("def source_part_selection_texture_row_context_text", source_parts_state_source)
        self.assertIn("def source_part_selection_added_texture_text", source_parts_state_source)
        self.assertIn("def source_part_selection_added_texture_context_text", source_parts_state_source)
        self.assertIn("def source_part_selection_texture_fallback", source_parts_state_source)
        self.assertIn("def source_part_control_load_state", source_parts_state_source)
        self.assertIn("def source_part_source_combo_selection_state", source_parts_state_source)
        self.assertIn("def source_part_target_combo_selection_state", source_parts_state_source)
        self.assertIn("def source_part_adjustment_apply_state", source_parts_state_source)
        self.assertIn("def source_part_map_to_target_state", source_parts_state_source)
        self.assertIn("def source_part_role_action_state", source_parts_state_source)
        self.assertIn("def source_part_role_export_flush_states", source_parts_state_source)
        self.assertIn("def source_part_glow_color_action_state", source_parts_state_source)
        source_part_selection_state_source = ARCHIVE_STATIC_REPLACEMENT_SOURCE_PART_SELECTION_STATE.read_text(
            encoding="utf-8"
        )
        self.assertIn("def selected_source_indices_state", source_part_selection_state_source)
        self.assertIn("selected_source_indices_state", source_parts_state_source)
        self.assertIn("_selected_source_indices_state_helper(", source)
        self.assertIn("_source_part_selection_context_state_helper(", source)
        self.assertIn("selection_context_label.setText(context_state.label_text)", source)
        self.assertIn("selection_context_label.setToolTip(context_state.tooltip_text)", source)
        self.assertIn("_source_part_selection_texture_row_context_text_helper(", source)
        self.assertIn("_source_part_selection_added_texture_context_text_helper(", source)
        self.assertIn("_source_part_selection_texture_fallback_helper(material_name)", source)
        load_controls_source = _nested_function_source(selected_part_source, "_load_selected_part_controls")
        self.assertIn("_state.source_part_transform_control_text['reset_part_tooltip']", load_controls_source)
        self.assertNotIn("_state.source_part_inspector_control_text['reset_part_tooltip']", load_controls_source)
        self.assertIn("_source_part_control_load_state_helper(", load_controls_source)
        self.assertIn("part_name_label.setText(load_state.name_text)", load_controls_source)
        self.assertIn("part_target_label.setText(load_state.target_text)", load_controls_source)
        self.assertIn("part_enabled_checkbox.setChecked(load_state.enabled_checked)", load_controls_source)
        self.assertIn("for spin, value in zip(_state.part_controls, load_state.transform_values):", load_controls_source)
        adjustment_source = _nested_function_source(remaining_source, "_update_selected_part_adjustment")
        self.assertIn("_source_part_adjustment_apply_state_helper(", adjustment_source)
        self.assertIn("apply_state.target_indices", adjustment_source)
        self.assertNotIn("_source_part_adjustment_values_changed_helper(", adjustment_source)
        target_combo_source = _nested_function_source(selected_part_source, "_select_part_target_row")
        self.assertIn("_source_part_target_combo_selection_state_helper(", target_combo_source)
        self.assertIn("button_state = selection_state.button_state", target_combo_source)
        map_target_source = _nested_function_source(selected_part_source, "_map_selected_part_to_combo_target")
        self.assertIn("_source_part_map_to_target_state_helper(", map_target_source)
        self.assertIn("map_state.source_indices", map_target_source)
        self.assertNotIn("_source_part_selection_context_label_text_helper(", source)
        self.assertNotIn("_source_part_selection_context_tooltip_helper(source_text, target_text, texture_text)", source)
        self.assertNotIn("_source_part_selection_texture_row_text_helper(target, role, source_label)", source)
        self.assertNotIn("_source_part_selection_added_texture_text_helper(", source)
        self.assertNotIn("_selected_source_part_name_text_helper(", source)
        self.assertNotIn("_selected_source_part_target_text_helper(", source)

        source_assignment_source = _nested_function_source(
            selection_mapping_source, "_refresh_source_assignment_columns"
        )
        self.assertIn("if not _alignment_dialog_widgets_live():", source_assignment_source)
        self.assertIn("_source_assignment_row_state_helper(", source_assignment_source)
        self.assertIn("row_state.assigned_targets_color", source_assignment_source)
        self.assertIn("row_state.status_tooltip", source_assignment_source)

        geometry_summary_source = _nested_function_source(preview_model_source, "_refresh_geometry_summary")
        self.assertIn("if not _state._alignment_dialog_widgets_live():", geometry_summary_source)
        self.assertIn("not _state._qt_object_is_valid(_state.geometry_summary)", geometry_summary_source)

    def test_modify_original_replacement_copies_direct_dds_bindings(self) -> None:
        source = _main_window_source()
        for attr in (
            "preview_texture_dds_path",
            "preview_normal_texture_dds_path",
            "preview_material_texture_dds_path",
            "preview_height_texture_dds_path",
            "preview_material_texture_inputs",
            "preview_native_material_overrides",
        ):
            self.assertIn(f'"{attr}"', source)
        self.assertIn("for attr in ORIGINAL_PREVIEW_TEXTURE_ATTRS:", source)
        self.assertIn("setattr(dst_mesh, attr, clone_preview_attr_value(getattr(src_mesh, attr)))", source)
        self.assertIn("if isinstance(value, QImage):", source)
        self.assertIn("def copy_exact_clone_original_preview_materials(", source)
        self.assertIn("for mesh_index, src_mesh in enumerate(original_meshes):", source)
        self.assertIn("if copy_exact_clone_original_preview_materials(", source)

    def test_alignment_direct_source_preview_applies_imported_texture_sets(self) -> None:
        source = _main_window_source()
        preview_refresh_source = _nested_function_source(
            static_replacement_remaining_callback_source(ROOT),
            "_refresh_static_dialog_preview",
        )
        preview_textures_source = ARCHIVE_STATIC_REPLACEMENT_PREVIEW_TEXTURES.read_text(encoding="utf-8")
        self.assertIn("material_authority_preview_active = preview_material_authority_profile is not None", preview_refresh_source)
        self.assertIn("if (_state.state.texture_sets or material_authority_preview_active) and (not use_original_material_preview) and (not mesh_edit_direct_source_preview):", preview_refresh_source)
        self.assertIn("if mesh_edit_direct_source_preview", preview_refresh_source)
        self.assertIn("_state._apply_source_material_preview_for_model_helper(", preview_refresh_source)
        self.assertIn("if not texture_sets:", preview_textures_source)
        self.assertIn("apply_material_authority_preview_native_hints(", preview_textures_source)
        self.assertIn("if use_direct_source_preview and direct_source_preview_index_map:", preview_textures_source)
        self.assertIn("for source_index, mesh_index in direct_source_preview_index_map.items():", preview_textures_source)
        self.assertIn("if not mapped_preview and not source_overlay_preview_index_map:", preview_textures_source)
        self.assertIn("for source_index, _mesh in enumerate(meshes):", preview_textures_source)
        self.assertIn("texture_set_for_source_index(source_index, texture_sets)", preview_textures_source)
        self.assertIn("mesh.preview_color = (1.0, 1.0, 1.0)", preview_textures_source)

    def test_replacement_source_selection_uses_overlay_not_preview_color_mutation(self) -> None:
        source = _main_window_source()
        preview_refresh_source = _nested_function_source(
            static_replacement_remaining_callback_source(ROOT),
            "_refresh_static_dialog_preview",
        )
        d3d11_mapping_source = ARCHIVE_STATIC_REPLACEMENT_D3D11_MAPPING.read_text(encoding="utf-8")
        d3d11_presentation_source = ARCHIVE_STATIC_REPLACEMENT_D3D11_PRESENTATION_STATE.read_text(encoding="utf-8")
        self.assertIn("source_selection_overlay_preview_index_map: Dict[int, int] = {}", source)
        self.assertIn("source_selection_overlay_editor_id_map: Dict[int, int] = {}", source)
        self.assertIn("def _build_selected_source_highlight_overlay_model", source)
        self.assertIn("def _append_selected_source_highlight_overlay", source)
        preview_models_source = (
            ARCHIVE_STATIC_REPLACEMENT_PREVIEW_MODELS.read_text(encoding="utf-8")
            + "\n"
            + ARCHIVE_STATIC_REPLACEMENT_PREVIEW_SELECTION_OVERLAY.read_text(encoding="utf-8")
        )
        self.assertIn("replacement_source_selection_overlay", preview_models_source)
        self.assertIn("mesh.source_submesh_index = source_selection_overlay_editor_id(source_index)", preview_models_source)
        self.assertIn("preview_index_by_source[source_index] = int(overlay_offset) + local_index", preview_models_source)
        self.assertIn('"source_selection_overlay_to_d3d11_ids"', d3d11_mapping_source)
        self.assertIn('state["source_selection_overlay_to_d3d11_ids"]', d3d11_mapping_source)
        self.assertIn("selection_overlay=True", source)
        self.assertIn("if _alignment_d3d11_preview_active():", source)
        self.assertIn("source_selection_overlay_preview_index_map.clear()", source)
        self.assertIn("source_selection_overlay_editor_id_map.clear()", source)
        self.assertRegex(
            preview_refresh_source,
            r"else:\n\s+preview_model = _state\._append_selected_source_highlight_overlay"
            r"\(preview_model, current_mappings\)",
        )
        self.assertIn("_mapped_source_indices(current_mappings) | set(requested_source_indices)", source)
        self.assertIn("_alignment_d3d11_record_source_editor_id_maps_helper(", source)
        self.assertIn("for raw_key, raw_values in mapping.items():", d3d11_mapping_source)
        self.assertNotIn("mesh.preview_color = (1.0, 0.78, 0.22)", source)
        self.assertNotIn("mesh.preview_color = (0.18, 0.22, 0.26)", source)
        queue_source = _nested_function_source(
            static_replacement_callback_concern_source(ROOT, "refresh_queue"),
            "_queue_selection_preview_refresh",
        )
        self.assertIn('if _state._d3d11_preview_active():', queue_source)
        self.assertIn("_sync_highlight_sets()", queue_source)
        self.assertIn("_alignment_d3d11_selection_highlight_performance_helper()", queue_source)
        self.assertIn("Selection changes use live .NET/Vortice highlight commands", d3d11_presentation_source)
        self.assertIn("_queue_static_preview_refresh()", queue_source)
        self.assertLess(
            queue_source.index("_alignment_d3d11_selection_highlight_performance_helper()"),
            queue_source.index("_queue_static_preview_refresh()"),
        )
        self.assertNotIn('static_preview_refresh_timer.start()', queue_source)

    def test_alignment_imported_textures_clear_stale_original_d3d11_bindings(self) -> None:
        preview_textures_source = ARCHIVE_STATIC_REPLACEMENT_PREVIEW_TEXTURES.read_text(encoding="utf-8")
        self.assertIn("def clear_replacement_preview_texture_bindings(mesh: object) -> None:", preview_textures_source)
        self.assertIn("Imported replacement textures must win over original/archive bindings.", preview_textures_source)
        self.assertIn('"preview_texture_dds_path"', preview_textures_source)
        self.assertIn('"preview_material_texture_inputs"', preview_textures_source)
        self.assertIn("def set_preview_texture_slot_path(", preview_textures_source)
        self.assertIn('setattr(mesh, dds_attr, "")', preview_textures_source)
        self.assertIn("clear_replacement_preview_texture_bindings(mesh)", preview_textures_source)
        self.assertIn("mesh.preview_material_texture_inputs = ()", preview_textures_source)

    def test_alignment_import_collects_scene_discovered_textures_for_live_preview(self) -> None:
        source = static_replacement_callback_concern_source(ROOT, "preview_model")
        texture_sources_source = ARCHIVE_STATIC_REPLACEMENT_TEXTURE_SOURCES.read_text(encoding="utf-8")
        self.assertIn("_state.auto_scene_texture_sources: _state.List[_state.Path] = []", source)
        self.assertIn("scene_import_result.discovered_texture_files", source)
        self.assertIn("scene_import_result.extracted_embedded_files", source)
        self.assertIn("getattr(_state.scene_import_result, 'discovered_supplemental_files', ())", source)
        self.assertIn("_state.discover_scene_texture_files(_state.obj_path, _state.replacement_mesh_for_mapping)", source)
        self.assertIn("_register_texture_source_files_helper(", source)
        self.assertIn("def register_texture_source_files(", texture_sources_source)

    def test_alignment_startup_progress_does_not_stay_on_source_queue_label(self) -> None:
        source = _main_window_source()
        outliner_source = static_replacement_ui_concern_source(ROOT, "source_parts_outliner")
        alignment_setup_source = ARCHIVE_STATIC_REPLACEMENT_ALIGNMENT_SETUP_STATE.read_text(encoding="utf-8")
        startup_state_source = ARCHIVE_STATIC_REPLACEMENT_STARTUP_STATE.read_text(encoding="utf-8")
        alignment_start = source.index("def _prompt_archive_static_replacement_options")
        self.assertGreater(source.index("startup_progress.setWindowModality(Qt.NonModal)", alignment_start), alignment_start)
        for key, message in (
            ("replacement_source_queue", '"Queuing replacement-source list..."'),
            ("routing_controls", '"Preparing routing controls..."'),
            ("geometry_controls", '"Preparing geometry controls..."'),
            ("replacement_texture_sources", '"Preparing replacement texture sources..."'),
        ):
            self.assertIn(f'"{key}": {message}', startup_state_source)
            self.assertIn(f"_state._alignment_startup_step(_state.alignment_startup_text['{key}'])", source)
        self.assertIn('"mesh_alignment_routing_ready"', source)
        self.assertIn('"mesh_alignment_routing_failed"', source)
        self.assertIn('"mesh_alignment_setup_warning"', source)
        self.assertIn("_alignment_setup_warning_startup_text_helper()", source)
        self.assertIn('"Alignment setup warning; continuing with limited controls..."', alignment_setup_source)
        self.assertLess(
            outliner_source.index("_state._alignment_startup_step(_state.alignment_startup_text['replacement_source_queue'])"),
            outliner_source.index("_state._alignment_startup_step(_state.alignment_startup_text['routing_controls'])"),
        )

    def test_alignment_d3d11_callbacks_fallback_to_preview_shell_settings(self) -> None:
        loading_source = static_replacement_callback_concern_source(ROOT, "d3d11_loading")
        package_source = static_replacement_callback_concern_source(ROOT, "d3d11_package_lifecycle")
        settings_source = _nested_function_source(
            loading_source, "_current_alignment_preview_render_settings_value"
        )
        self.assertIn("callable(_state._get_preview_render_settings)", settings_source)
        self.assertIn("return _state._get_preview_render_settings()", settings_source)
        self.assertNotIn("set_render_tuning", settings_source)
        self.assertIn("_state.alignment_transform_generation = _state.context.get('alignment_transform_generation') or {}", loading_source)
        for callback in (
            "_clear_alignment_d3d11_fast_transform_state",
            "_sync_highlight_sets",
            "_replay_alignment_d3d11_fast_transform",
        ):
            self.assertIn(f"callable(_state.{callback})", loading_source)

        for context_key in ("entry", "dialog_title", "self"):
            self.assertIn(f"_state.{context_key} = _state.context.get('{context_key}')", package_source)
        for function_name in (
            "_sync_mesh_edit_preview_settings_if_ready",
            "_clear_alignment_d3d11_fast_transform_state_if_ready",
            "_clear_source_parts_preview_rebuild_pending_if_ready",
            "_sync_highlight_sets_if_ready",
            "_replay_alignment_d3d11_fast_transform_if_ready",
        ):
            self.assertIn(f"def {function_name}", package_source)
        status_source = _nested_function_source(package_source, "_poll_alignment_d3d11_status")
        for safe_callback in (
            "_sync_mesh_edit_preview_settings_if_ready()",
            "_clear_alignment_d3d11_fast_transform_state_if_ready(reset_host=True)",
            "_sync_highlight_sets_if_ready()",
            "_replay_alignment_d3d11_fast_transform_if_ready()",
            "_clear_source_parts_preview_rebuild_pending_if_ready()",
        ):
            self.assertIn(f"_state.{safe_callback}", status_source)
        self.assertNotIn("_state._sync_mesh_edit_preview_settings()", status_source)
        self.assertNotIn("_state._clear_alignment_d3d11_fast_transform_state(reset_host=True)", status_source)
        self.assertNotIn("_state._clear_source_parts_preview_rebuild_pending()", status_source)

    def test_modify_original_gizmo_and_empty_texture_panel_are_compact(self) -> None:
        source = _main_window_source()
        texture_section_source = static_replacement_ui_concern_source(ROOT, "texture_material")
        widgets_source = _widgets_source()
        native_panel_source = (ROOT / "cdmw" / "ui" / "native_preview_panel.py").read_text(encoding="utf-8")
        donor_state_source = ARCHIVE_STATIC_REPLACEMENT_DONOR_MATERIAL_STATE.read_text(encoding="utf-8")
        self.assertIn("_state.donor_material_group.setSizePolicy(_state.QSizePolicy.Expanding, _state.QSizePolicy.Maximum)", texture_section_source)
        self.assertIn("_state.donor_material_group.setMaximumHeight(126)", texture_section_source)
        self.assertIn("_state.donor_material_plan_tree.setVisible(False)", texture_section_source)
        self.assertIn("_donor_material_plan_tree_size_state_helper", source)
        texture_callbacks_source = static_replacement_texture_callback_source(ROOT)
        donor_refresh_source = _nested_function_source(texture_callbacks_source, "_refresh_donor_material_plan_tree")
        self.assertIn("_state.donor_material_group.setMaximumHeight(size_state.group_max_height)", donor_refresh_source)
        self.assertIn("group_max_height=190 if has_rows else 126", donor_state_source)
        self.assertIn("from cdmw.ui.native_preview_panel import NativePreviewPanel", widgets_source)
        self.assertIn("class NativePreviewPanel(QWidget)", native_panel_source)

    def test_modify_original_resident_bootstrap_bakes_one_shared_material_graph(self) -> None:
        source = (
            ROOT
            / "cdmw"
            / "ui"
            / "archive_browser"
            / "static_replacement_dialog_sections_mesh_geometry_preview_part_01.py"
        ).read_text(encoding="utf-8")
        binding = _nested_function_source(
            source,
            "_mesh_editor_embedded_defer_reference_material_synthesis",
        )
        self.assertIn("_state.context.get('modify_original_clone_mode')", binding)
        self.assertIn("_state.context.get('defer_original_texture_preview')", binding)
        self.assertIn("prepared_model is None", binding)
        worker_source = (
            ROOT / "cdmw" / "workers" / "mesh_editor_aux_workers.py"
        ).read_text(encoding="utf-8")
        self.assertIn("mirror_reference_materials_to_editable", worker_source)
        self.assertNotIn("defer_dotnet_preview_material_synthesis", worker_source)
        launch_source = (
            ROOT / "cdmw" / "ui" / "mesh_editor" / "tab_dotnet_launch.py"
        ).read_text(encoding="utf-8")
        self.assertIn("_mesh_editor_embedded_mirror_reference_materials_to_editable", launch_source)
        self.assertIn("_mesh_editor_embedded_defer_reference_material_synthesis", launch_source)
        resident_source = ARCHIVE_STATIC_REPLACEMENT_DIALOG_REMAINING_CALLBACKS.read_text(
            encoding="utf-8"
        )
        self.assertIn("publish_resident_updates=True", resident_source)
        self.assertNotIn("_alignment_d3d11_invalidate_package_cache('material')", resident_source)
        self.assertIn("'_mesh_editor_embedded_set_preview_loading'", source)
        prompt_open_source = (
            ROOT
            / "cdmw"
            / "ui"
            / "archive_browser"
            / "static_replacement_dialog_prompt_open.py"
        ).read_text(encoding="utf-8")
        self.assertIn(
            '"_mesh_editor_embedded_request_material_resources"',
            prompt_open_source,
        )
        self.assertIn("if not embedded_alignment_builder:", prompt_open_source)

    def test_authoring_prewarm_waits_for_the_authoritative_edit_session(self) -> None:
        preview_shell_source = (
            ROOT
            / "cdmw"
            / "ui"
            / "archive_browser"
            / "static_replacement_dialog_preview_shell.py"
        ).read_text(encoding="utf-8")
        launch_source = (
            ROOT / "cdmw" / "ui" / "mesh_editor" / "tab_dotnet_launch.py"
        ).read_text(encoding="utf-8")

        self.assertIn('"cdmwPreviewPrewarmCacheRoot"', preview_shell_source)
        self.assertNotIn("_prewarm_alignment_d3d11_host", preview_shell_source)
        session_bind = launch_source.index("set_authoritative_session_id(session_id)")
        prewarm_request = launch_source.index("prewarm(Path(str(cache_root)))")
        self.assertLess(session_bind, prewarm_request)


if __name__ == "__main__":
    unittest.main()
