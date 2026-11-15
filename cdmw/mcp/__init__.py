"""AI connections over MCP (P13 stage C).

The tool table, its schemas, approvals, the audit log, jobs and the
transport: a hidden ``--mcp-bridge`` mode of the same executable speaks MCP
(JSON-RPC 2.0) on stdin and stdout and relays over a named pipe of its own to
the running app. Everything is off until the user turns on "Allow AI
connections" in Settings.

CDMW makes mods; no tool writes into the game, under any setting.

This package imports nothing heavy at import time; the bridge process loads
only ``names``, ``errors`` and ``transport``.
"""
