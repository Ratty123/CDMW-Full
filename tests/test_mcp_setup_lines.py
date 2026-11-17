"""AI connections: the lines Settings shows to add CDMW to an AI app, for the packaged CDMW.exe."""
from __future__ import annotations

import json
import sys
import tomllib
from pathlib import Path

from cdmw.mcp import setup_lines


def _packaged(monkeypatch, executable: str) -> str:
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", executable)
    return str(Path(executable).resolve())


def test_the_packaged_exe_is_the_command_every_client_starts(monkeypatch) -> None:
    exe = _packaged(monkeypatch, r"C:\Program Files\CDMW\CDMW.exe")
    assert setup_lines.bridge_command() == (exe, ["--mcp-bridge"])
    lines = setup_lines.client_setup_lines()
    assert set(lines) == {"Claude Code", "Codex CLI", "Codex CLI (config.toml)",
                          "Claude Desktop (claude_desktop_config.json)"}
    desktop = json.loads(lines["Claude Desktop (claude_desktop_config.json)"])
    assert desktop == {"mcpServers": {"cdmw": {"command": exe, "args": ["--mcp-bridge"]}}}
    # User scope, so Claude Code finds CDMW whatever folder it is started in.
    assert lines["Claude Code"] == f'claude mcp add --scope user cdmw -- "{exe}" --mcp-bridge'
    assert lines["Codex CLI"] == f'codex mcp add cdmw -- "{exe}" --mcp-bridge'


def test_the_codex_config_parses_whatever_the_folder_is_called(monkeypatch) -> None:
    exe = _packaged(monkeypatch, r"C:\Users\O'Neil\Mods\CDMW.exe")
    config = tomllib.loads(setup_lines.client_setup_lines()["Codex CLI (config.toml)"])
    assert config == {"mcp_servers": {"cdmw": {"command": exe, "args": ["--mcp-bridge"]}}}


def test_from_source_the_interpreter_runs_the_entry_script(monkeypatch) -> None:
    monkeypatch.setattr(sys, "frozen", False, raising=False)
    command, args = setup_lines.bridge_command()
    assert Path(command) == Path(sys.executable).resolve()
    assert Path(args[0]).name == "cdmw_app.py" and Path(args[0]).is_file() and args[1:] == ["--mcp-bridge"]
