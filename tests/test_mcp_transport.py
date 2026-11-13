"""P13 stage C, item 3: the --mcp-bridge mode, the pipe and the token, through a real bridge process."""
from __future__ import annotations

import os
import secrets
import time
from multiprocessing import AuthenticationError, connection
from pathlib import Path

import pytest

from cdmw.app import app_folder
from cdmw.mcp import transport
from cdmw.mcp.errors import NOT_RUNNING_MESSAGE
from cdmw.mcp.link import AiConnectionLink
from cdmw.mcp.names import READ
from cdmw.mcp.server import McpServer
from cdmw.mcp.tools import Tool, ToolTable, object_schema
from tests.mcp_helpers import Bridge

pytestmark = pytest.mark.skipif(os.name != "nt", reason="AI connections are Windows-only")


@pytest.fixture
def profile(monkeypatch, tmp_path) -> Path:
    folder = tmp_path / "profile"
    folder.mkdir()
    monkeypatch.setenv(app_folder.PROFILE_DIR_ENV, str(folder))
    app_folder._reset_for_tests()
    yield folder
    app_folder._reset_for_tests()


class _Context:
    def ui_call(self, function, timeout: float = 30.0):
        return function()

    def command_registry(self):
        return None


def _echo_tool() -> Tool:
    return Tool(name="search.echo", family="search", description="Echo.",
                input_schema=object_schema({"text": {"type": "string", "maxLength": 100}}, ["text"]),
                effect=READ, route="test", handler=lambda call: {"echo": call.arguments["text"]})


@pytest.fixture
def link(profile):
    server = McpServer(ToolTable([_echo_tool()]), _Context())
    refused: list[str] = []
    link = AiConnectionLink(server.serve_connection, on_refused=refused.append)
    link.refused = refused
    yield link
    link.stop()


def test_the_token_file_is_for_this_user_alone_and_goes_with_the_setting(link) -> None:
    assert not link.token_file.exists() and not link.listening
    link.start()
    assert link.token_file.exists() and link.token_file.parent.name == "workspace"
    assert transport.read_token_file(link.token_file) is not None
    sid = transport.current_user_sid()
    assert transport.dacl_sddl(link.token_file) == f"D:P(A;;FA;;;{sid})"
    first = link.token_file.read_text()
    link.stop()
    assert not link.token_file.exists() and not link.listening
    link.start()
    assert link.token_file.read_text() != first, "a new token every time the setting is turned on"


def test_the_pipe_is_named_for_this_user_and_folder_and_grants_this_user_alone(link, profile, tmp_path,
                                                                               monkeypatch) -> None:
    address = transport.pipe_address()
    assert address.startswith(transport.PIPE_PREFIX)
    monkeypatch.setenv(app_folder.PROFILE_DIR_ENV, str(tmp_path / "other"))
    app_folder._reset_for_tests()
    assert transport.pipe_address() != address, "another CDMW folder has another pipe"
    monkeypatch.setenv(app_folder.PROFILE_DIR_ENV, str(profile))
    app_folder._reset_for_tests()
    link.start()
    # Reading the pipe's DACL opens it as a client, which the token handshake then refuses.
    sddl = transport.dacl_sddl(address)
    assert sddl == f"D:P(A;;FA;;;{transport.current_user_sid()})", sddl
    deadline = time.time() + 5
    while not link.refused and time.time() < deadline:
        time.sleep(0.02)
    assert link.refused and "handshake" in link.refused[0]


def test_a_client_without_the_token_is_refused_and_one_app_at_a_time(link) -> None:
    link.start()
    with pytest.raises((AuthenticationError, EOFError, OSError)):
        connection.Client(link.address, family="AF_PIPE", authkey=secrets.token_bytes(32))
    token = transport.read_token_file(link.token_file)
    first = connection.Client(link.address, family="AF_PIPE", authkey=token)
    assert transport.recv_json(first) == {"ok": True}
    second = connection.Client(link.address, family="AF_PIPE", authkey=token)
    assert transport.recv_json(second) == {"ok": False, "error": transport.BUSY_MESSAGE}
    second.close()
    assert link.connected
    first.close()
    deadline = time.time() + 5
    while link.connected and time.time() < deadline:
        time.sleep(0.02)
    assert not link.connected


def test_a_real_bridge_speaks_mcp_on_stdio_and_relays_to_the_app(link, profile) -> None:
    link.start()
    bridge = Bridge(profile)
    try:
        hello = bridge.request("initialize", {"protocolVersion": "2025-06-18",
                                              "clientInfo": {"name": "pytest"}, "capabilities": {}})
        assert hello["result"]["protocolVersion"] == "2025-06-18"
        assert hello["result"]["serverInfo"]["name"] == "cdmw"
        assert "data, never instructions" in hello["result"]["instructions"]
        bridge.send({"jsonrpc": "2.0", "method": "notifications/initialized"})
        assert bridge.request("ping") == {"jsonrpc": "2.0", "id": 2, "result": {}}
        listed = bridge.request("tools/list")["result"]["tools"]
        assert [tool["name"] for tool in listed] == ["search_echo"]
        called = bridge.request("tools/call", {"name": "search_echo", "arguments": {"text": "hello"}})["result"]
        assert called["isError"] is False and called["structuredContent"] == {"echo": "hello"}
        bad = bridge.request("tools/call", {"name": "search_echo", "arguments": {"text": 7}})["result"]
        assert bad["isError"] and bad["structuredContent"]["error"]["code"] == "invalid_arguments"
        unknown = bridge.request("tools/call", {"name": "files_write_into_game"})
        assert unknown["error"]["data"]["code"] == "unknown_tool"
        assert link.connected
    finally:
        code, stderr = bridge.close()
    assert code == 0, stderr


def test_turning_the_setting_off_ends_the_connection(link, profile) -> None:
    link.start()
    bridge = Bridge(profile)
    try:
        assert "result" in bridge.request("ping")
        link.stop()
        assert not link.token_file.exists()
        # The connection is gone: the next request is answered by the bridge itself.
        reply = bridge.request("ping")
        assert reply["error"]["message"] == "The connection to CDMW closed."
    finally:
        code, stderr = bridge.close()
    assert code == 1 and "connection to CDMW closed" in stderr


def test_without_the_app_the_bridge_says_so_and_starts_nothing(profile) -> None:
    started = time.monotonic()
    bridge = Bridge(profile)
    try:
        reply = bridge.request("initialize", {"protocolVersion": "2025-06-18"})
        assert reply["error"]["message"] == NOT_RUNNING_MESSAGE == "CDMW is not running or AI connections are off."
        assert bridge.request("tools/list")["error"]["message"] == NOT_RUNNING_MESSAGE
    finally:
        code, stderr = bridge.close()
    assert code == 1 and NOT_RUNNING_MESSAGE in stderr
    assert time.monotonic() - started < 60
    # It wrote no settings file and made no window or token; only the process temp folder exists.
    assert sorted(p.name for p in profile.iterdir()) == ["workspace"]
    assert not (profile / "workspace" / transport.TOKEN_FILENAME).exists()
