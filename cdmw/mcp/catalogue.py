"""Every typed tool, in one list."""

from __future__ import annotations

from cdmw.mcp.tools import Tool


def typed_tools() -> list[Tool]:
    from cdmw.mcp.app_read_tools import app_read_tools
    from cdmw.mcp.app_tools import app_tools
    from cdmw.mcp.archive_tools import archive_tools
    from cdmw.mcp.control_tools import control_tools
    from cdmw.mcp.mesh_edit_tools import mesh_edit_tools
    from cdmw.mcp.mesh_tools import mesh_tools
    from cdmw.mcp.new_item_tools import new_item_tools
    from cdmw.mcp.placement_tools import placement_tools
    from cdmw.mcp.read_tools import read_tools
    from cdmw.mcp.texture_tools import texture_tools
    from cdmw.mcp.view_tools import view_tools

    return [*app_tools(), *control_tools(), *archive_tools(), *read_tools(), *app_read_tools(), *view_tools(), *mesh_tools(),
            *mesh_edit_tools(), *texture_tools(), *new_item_tools(), *placement_tools()]
