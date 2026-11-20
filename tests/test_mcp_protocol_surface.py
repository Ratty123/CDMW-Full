"""MCP gap plan item 17: resources and prompts on the CDMW MCP server."""
from __future__ import annotations

import json
import threading

import pytest

from cdmw.mcp import protocol_surface as surface
from cdmw.mcp.audit import AuditLog
from cdmw.mcp.server import INVALID_PARAMS, McpServer, McpSession, _RpcError
from cdmw.mcp.tools import ToolTable


class _Context:
    def ui_call(self, function, timeout: float = 30.0):
        return function()

    def command_registry(self):
        return None


@pytest.fixture
def server(tmp_path):
    return McpServer(ToolTable([]), _Context(), audit=AuditLog(tmp_path / "ai-calls.log"))


def _call(server, method, params=None):
    session = McpSession(server, lambda message: None)
    return server.dispatch(session, method, params or {}, threading.Event())


def test_initialize_offers_resources_and_prompts(server) -> None:
    capabilities = _call(server, "initialize", {"protocolVersion": "2025-06-18"})["capabilities"]
    assert capabilities["resources"] == {"listChanged": False}
    assert capabilities["prompts"] == {"listChanged": False}


def test_resources_list_has_the_manual_coverage_and_calls(server) -> None:
    rows = _call(server, "resources/list")["resources"]
    uris = {row["uri"] for row in rows}
    assert {surface.MANUAL_INDEX, surface.COVERAGE, surface.CALLS} <= uris
    assert f"{surface.MANUAL_PREFIX}mesh_editor" in uris
    assert all(row["uri"].startswith("cdmw://") and row["mimeType"] for row in rows)
    assert _call(server, "resources/templates/list") == {"resourceTemplates": []}


def test_resources_read_returns_each_kind(server, tmp_path) -> None:
    index = _call(server, "resources/read", {"uri": surface.MANUAL_INDEX})["contents"][0]
    assert index["mimeType"] == "text/markdown" and "cdmw://manual/mesh_editor" in index["text"]
    topic = _call(server, "resources/read", {"uri": "cdmw://manual/mesh_editor"})["contents"][0]
    assert topic["text"].startswith("# ") and len(topic["text"]) > 200
    coverage = json.loads(_call(server, "resources/read", {"uri": surface.COVERAGE})["contents"][0]["text"])
    assert coverage["schema"] == 1 and coverage["capabilities"]

    assert _call(server, "resources/read", {"uri": surface.CALLS})["contents"][0]["text"] == ""
    for number in range(surface.CALL_LINES + 5):
        server.audit.record(client="test", tool=f"tool{number}", effect="read", arguments={}, approval="",
                            result="ok", duration_s=0.0)
    lines = _call(server, "resources/read", {"uri": surface.CALLS})["contents"][0]["text"].splitlines()
    assert len(lines) == surface.CALL_LINES
    assert json.loads(lines[-1])["tool"] == f"tool{surface.CALL_LINES + 4}"


def test_an_unknown_resource_is_refused(server) -> None:
    for uri in ("cdmw://nothing", "cdmw://manual/no_such_topic", "file:///etc/passwd"):
        with pytest.raises(_RpcError) as error:
            _call(server, "resources/read", {"uri": uri})
        assert error.value.code == -32002


def test_prompts_say_ai_connections_are_experimental(server) -> None:
    prompts = _call(server, "prompts/list")["prompts"]
    assert {p["name"] for p in prompts} >= {"find_and_extract", "edit_mesh_supervised", "make_new_item",
                                            "review_ai_changes"}
    for prompt in prompts:
        arguments = {a["name"]: "a sword" for a in prompt["arguments"]}
        result = _call(server, "prompts/get", {"name": prompt["name"], "arguments": arguments})
        text = result["messages"][0]["content"]["text"]
        assert result["messages"][0]["role"] == "user"
        assert "experimental" in text and "not a mod maker" in text and "test it in game" in text
        assert "{" not in text


def test_prompts_get_checks_its_arguments(server) -> None:
    with pytest.raises(_RpcError) as error:
        _call(server, "prompts/get", {"name": "find_and_extract", "arguments": {}})
    assert error.value.code == INVALID_PARAMS and "what" in error.value.message
    with pytest.raises(_RpcError) as error:
        _call(server, "prompts/get", {"name": "no_such_prompt"})
    assert error.value.code == INVALID_PARAMS
    text = _call(server, "prompts/get", {"name": "find_and_extract", "arguments": {"what": "Kliff's boots"}})
    assert "Kliff's boots" in text["messages"][0]["content"]["text"]
