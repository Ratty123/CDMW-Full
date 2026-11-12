"""The typed tools this part of stage C builds, in one list."""

from __future__ import annotations

from cdmw.mcp.tools import Tool


def typed_tools() -> list[Tool]:
    from cdmw.mcp.app_tools import app_tools
    from cdmw.mcp.read_tools import read_tools

    return [*app_tools(), *read_tools()]
