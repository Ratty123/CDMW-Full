"""Every typed tool, in one list."""

from __future__ import annotations

from cdmw.mcp.tools import Tool


def typed_tools() -> list[Tool]:
    from cdmw.mcp.action_chart_tools import action_chart_tools
    from cdmw.mcp.app_read_tools import app_read_tools
    from cdmw.mcp.app_tools import app_tools
    from cdmw.mcp.archive_tools import archive_tools
    from cdmw.mcp.browse_archive_tools import browse_archive_tools
    from cdmw.mcp.control_tools import control_tools
    from cdmw.mcp.decal_tools import decal_tools
    from cdmw.mcp.diagnostics_tools import diagnostics_tools
    from cdmw.mcp.game_table_tools import game_table_tools
    from cdmw.mcp.hkx_tools import hkx_tools
    from cdmw.mcp.item_icon_tools import item_icon_tools
    from cdmw.mcp.local_file_tools import local_file_tools
    from cdmw.mcp.mesh_edit_tools import mesh_edit_tools
    from cdmw.mcp.mesh_session_tools import mesh_session_tools
    from cdmw.mcp.mesh_tools import mesh_tools
    from cdmw.mcp.mod_management_tools import mod_management_tools
    from cdmw.mcp.model_library_tools import model_library_tools
    from cdmw.mcp.new_item_tools import new_item_tools
    from cdmw.mcp.npc_tools import npc_tools
    from cdmw.mcp.placement_tools import placement_tools
    from cdmw.mcp.prefab_tools import prefab_tools
    from cdmw.mcp.read_tools import read_tools
    from cdmw.mcp.research_tools import research_tools
    from cdmw.mcp.saved_work_tools import saved_work_tools
    from cdmw.mcp.settings_tools import settings_tools
    from cdmw.mcp.skeleton_tools import skeleton_tools
    from cdmw.mcp.sound_tools import sound_tools
    from cdmw.mcp.speed_tools import speed_tools
    from cdmw.mcp.text_search_tools import text_search_tools
    from cdmw.mcp.texture_tools import texture_tools
    from cdmw.mcp.translation_tools import translation_tools
    from cdmw.mcp.turn_tools import turn_tools
    from cdmw.mcp.view_tools import view_tools

    return [*app_tools(), *control_tools(), *archive_tools(), *read_tools(), *app_read_tools(), *view_tools(), *mesh_tools(), *mesh_session_tools(),
            *mesh_edit_tools(), *texture_tools(), *new_item_tools(), *placement_tools(), *browse_archive_tools(), *hkx_tools(), *sound_tools(), *action_chart_tools(), *skeleton_tools(), *prefab_tools(), *game_table_tools(), *decal_tools(),
            *local_file_tools(), *saved_work_tools(), *mod_management_tools(), *translation_tools(),
            *text_search_tools(), *model_library_tools(), *item_icon_tools(), *research_tools(), *settings_tools(),
            *speed_tools(), *diagnostics_tools(), *turn_tools(), *npc_tools()]
