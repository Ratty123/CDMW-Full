"""MCP gap plan item 17: read tools say what their results hold (outputSchema)."""
from __future__ import annotations

from cdmw.mcp.catalogue import typed_tools
from cdmw.mcp.paging import PageStore
from cdmw.mcp.schema import _check
from cdmw.mcp.tools import ToolTable


def test_every_paged_tool_lists_the_shape_of_its_pages() -> None:
    tools = [tool for tool in ToolTable(typed_tools()).typed() if tool.built and tool.paged]
    assert tools
    for tool in tools:
        schema = tool.listing()["outputSchema"]
        assert schema["type"] == "object" and not schema.get("required"), tool.name
        assert schema["properties"][tool.paged]["type"] == "array", tool.name


def test_a_page_the_server_sends_matches_the_listed_schema() -> None:
    tool = next(tool for tool in ToolTable(typed_tools()).typed() if tool.name == "search.characters")
    pages = PageStore()
    first = pages.first(tool.name, tool.paged, {"characters": [{"key": str(n)} for n in range(5)],
                                                "total_matches": 5, "truncated": False, "warnings": []}, 2)
    _check(first, tool.listing()["outputSchema"], "result")
    following = pages.next(tool.name, first["next_page_token"], 10)
    _check(following, tool.listing()["outputSchema"], "result")
    assert "next_page_token" not in following and following["offset"] == 2


def test_a_tool_without_pages_or_a_schema_lists_none() -> None:
    tool = next(tool for tool in ToolTable(typed_tools()).typed() if not tool.paged and tool.output_schema is None)
    assert "outputSchema" not in tool.listing()
