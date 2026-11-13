"""Stable error codes for AI tool calls (P13 stage C, design record 2.4 step 6).

A client can rely on the code; the message is the one the interface would
show and may change with the wording or the language.
"""

from __future__ import annotations

from collections.abc import Mapping

UNKNOWN_TOOL = "unknown_tool"  # no tool has that name
INVALID_ARGUMENTS = "invalid_arguments"  # the arguments do not match the tool's schema
UNAVAILABLE = "unavailable"  # the command cannot run now; the message is the registry's reason
REFUSED = "refused"  # a rule refused it: the game folder, an approval declined, connections off
NOT_FOUND = "not_found"  # the entry, file, row, job or page does not exist
NOT_BUILT = "not_built"  # the capability is listed but its tool is not built yet
FAILED = "failed"  # the work ran and failed; the message is the worker's
CANCELLED = "cancelled"  # the client or the user cancelled it
TOO_LARGE = "too_large"  # the request asks for more than one call may return

#: Every code a tool can return. Adding one is a contract change for clients.
ERROR_CODES = (UNKNOWN_TOOL, INVALID_ARGUMENTS, UNAVAILABLE, REFUSED, NOT_FOUND, NOT_BUILT, FAILED,
               CANCELLED, TOO_LARGE)

#: The refusal when the AI connection setting is off or the app is not there.
NOT_RUNNING_MESSAGE = "CDMW is not running or AI connections are off."
DECLINED_MESSAGE = "Declined in CDMW."


class ToolError(Exception):
    """A tool call that did not succeed, with a stable ``code``."""

    def __init__(self, code: str, message: str, data: Mapping[str, object] | None = None) -> None:
        if code not in ERROR_CODES:
            raise ValueError(f"Unknown tool error code {code!r}")
        super().__init__(message)
        self.code = code
        self.message = str(message)
        self.data = dict(data or {})

    def payload(self) -> dict[str, object]:
        return {"code": self.code, "message": self.message, **({"data": self.data} if self.data else {})}
