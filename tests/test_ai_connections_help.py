"""Help > AI Connections (MCP) names only tools, prompts, resources and setup lines CDMW still has."""
from __future__ import annotations

import html
import json
import os
import re

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from cdmw.mcp import approvals, audit, protocol_surface
from cdmw.mcp.catalogue import typed_tools
from cdmw.mcp.names import wire_name
from cdmw.mcp.setup_lines import client_setup_lines
from cdmw.mcp.tools import ToolTable
from cdmw.ui.shell.about_documentation_en import AI_CONNECTIONS_SECTION

EXAMPLE_EXE = "<CDMW folder>\\CDMW.exe"


def _code_cells() -> list[str]:
    found = re.findall(r'<code translate="no">(.*?)</code>', AI_CONNECTIONS_SECTION["html"], re.DOTALL)
    return [html.unescape(text) for text in found]


def _built_wire_names() -> set[str]:
    return {wire_name(tool.name) for tool in ToolTable(typed_tools()).typed() if tool.built}


def _looks_like_a_tool(text: str) -> bool:
    return re.fullmatch(r"[a-z][a-z0-9_]*\*?", text) is not None and "_" in text


def test_every_tool_the_page_names_is_built() -> None:
    built = _built_wire_names()
    prompts = {prompt["name"] for prompt in protocol_surface.list_prompts()}
    for text in filter(_looks_like_a_tool, _code_cells()):
        if text in prompts:
            continue
        if text.endswith("*"):
            assert any(name.startswith(text[:-1]) for name in built), f"no tool starts with {text[:-1]!r}"
        else:
            assert text in built, f"the Help names a tool CDMW does not have: {text}"


def test_the_tool_count_the_page_gives_still_holds() -> None:
    assert "more than 200 in all" in AI_CONNECTIONS_SECTION["html"]
    assert len(_built_wire_names()) > 200


def test_the_prompts_and_resources_tables_match_what_cdmw_offers() -> None:
    cells = set(_code_cells())
    prompts = {prompt["name"] for prompt in protocol_surface.list_prompts()}
    assert prompts <= cells, f"prompts missing from the Help: {sorted(prompts - cells)}"
    uris = {row["uri"] for row in protocol_surface.list_resources()}
    named = {text for text in cells if text.startswith("cdmw://")}
    assert named <= uris, f"the Help names resources CDMW does not have: {sorted(named - uris)}"
    assert {"cdmw://manual", "cdmw://coverage", "cdmw://calls/recent"} <= named


def test_the_setup_examples_are_the_lines_settings_shows() -> None:
    lines = client_setup_lines(EXAMPLE_EXE, ["--mcp-bridge"])
    cells = _code_cells()
    assert lines["Claude Code"] in cells
    assert lines["Codex CLI"] in cells
    shown = [json.loads(text) for text in cells if text.startswith("{")]
    assert json.loads(lines["Claude Desktop (claude_desktop_config.json)"]) in shown
    assert json.loads(lines["Other MCP clients (JSON, stdio)"]) in shown


def test_the_limits_the_page_gives_are_cdmws() -> None:
    body = AI_CONNECTIONS_SECTION["html"]
    assert approvals.PROMPT_TIMEOUT_S == 300.0 and "five minutes" in body
    assert audit.ROTATE_BYTES == 4 * 1024 * 1024 and "4 MB" in body
    assert "workspace\\logs\\ai-calls.log" in _code_cells()
