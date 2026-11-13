"""The exact lines that add CDMW to an MCP client (draft for Help; P13 stage C).

Every client starts the same command: the CDMW executable with
``--mcp-bridge``. From source it is the interpreter and ``cdmw_app.py``.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

SERVER_KEY = "cdmw"


def bridge_command() -> tuple[str, list[str]]:
    """The program and arguments an MCP client runs."""

    if getattr(sys, "frozen", False):
        return str(Path(sys.executable).resolve()), ["--mcp-bridge"]
    script = Path(__file__).resolve().parents[2] / "cdmw_app.py"
    return str(Path(sys.executable).resolve()), [str(script), "--mcp-bridge"]


def _quoted(text: str) -> str:
    return f'"{text}"' if " " in text or not text else text


def client_setup_lines(command: str | None = None, args: list[str] | None = None) -> dict[str, str]:
    if command is None:
        command, args = bridge_command()
    args = list(args or [])
    shell_line = " ".join([_quoted(command), *(_quoted(a) for a in args)])
    toml_args = ", ".join("'" + a + "'" for a in args)
    return {
        "Claude Code": f"claude mcp add {SERVER_KEY} -- {shell_line}",
        "Codex CLI": f"codex mcp add {SERVER_KEY} -- {shell_line}",
        "Codex CLI (config.toml)": f"[mcp_servers.{SERVER_KEY}]\ncommand = '{command}'\nargs = [{toml_args}]",
        "Claude Desktop (claude_desktop_config.json)": json.dumps(
            {"mcpServers": {SERVER_KEY: {"command": command, "args": args}}}, indent=2),
    }
