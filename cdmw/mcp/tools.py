"""The tool table: every tool an AI client can call (P13 stage C).

A tool has a name, a family, an input schema, an effect class (read, edit,
destructive or output) and a route, the service or command it calls. Two
kinds exist:

* **Typed tools**, named ``<family>.<action>`` with one of the reserved family
  prefixes (``search.archive``). They take arguments.
* **Command tools**, one per registry command, named after the command's id
  and taking no arguments (section 7, answer 1). Running one runs the command
  as its menu entry or button does; an unavailable command returns the
  registry's reason.

Clients see names with dots as underscores (``names.wire_name``).

This part of stage C builds read tools only. A command tool whose command is
an edit, destructive or output command, and every typed tool of those
classes, is listed in ``coverage.json`` as "not built yet" with the milestone
that builds it; the table neither lists nor runs it.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field

from cdmw.mcp.names import (
    DESTRUCTIVE,
    EFFECT_CLASSES,
    OUTPUT,
    READ,
    RESERVED_PREFIXES,
    WIRE_NAME_PATTERN,
    reserved_prefix,
    wire_name,
)
from cdmw.mcp.schema import check_schema_shape

#: The command tools' family. Not a typed family, so not a reserved prefix.
COMMAND_FAMILY = "command"
#: Effect classes whose tools exist in this part of stage C.
BUILT_EFFECTS = frozenset({READ})
#: Registry commands as tools are P13 stage C part 2 (the control branch): until it
#: switches this on, a classified command is listed in coverage, not as a tool.
COMMAND_TOOLS_BUILT = False
#: Where a tool's work runs. The UI thread only starts work or reads widget
#: state; anything slow runs on a worker.
ON_WORKER = "worker"
ON_UI = "ui"
#: Quick bookkeeping (jobs, pages): runs on the call's own thread, never as a job.
ON_CALL = "call"
#: Arguments the server adds to a paged tool's schema.
PAGE_LIMIT_DEFAULT = 100
PAGE_LIMIT_MAX = 500

EMPTY_SCHEMA: Mapping[str, object] = {"type": "object", "properties": {}, "additionalProperties": False}


def object_schema(properties: Mapping[str, Mapping[str, object]] | None = None,
                  required: Iterable[str] = ()) -> dict[str, object]:
    return {"type": "object", "properties": dict(properties or {}), "required": list(required),
            "additionalProperties": False}


class ToolTableError(ValueError):
    """The table was defined wrongly: a programming error, not a message for clients."""


@dataclass(frozen=True, slots=True)
class Tool:
    name: str
    family: str
    description: str
    input_schema: Mapping[str, object]
    effect: str
    #: What it calls, for the coverage file and the report: ``registry:<id>``
    #: or ``service:<module>.<callable>``.
    route: str
    #: ``handler(call)`` does the work; ``call`` is a ``server.ToolCall``.
    handler: Callable[..., object] | None = None
    runs_on: str = ON_WORKER
    #: The name of the list in the result that the server pages ("" for none).
    paged: str = ""
    #: Argument names that are output paths; the server checks each with
    #: ``cdmw.domain.output_paths.check_output_path`` before asking anyone.
    output_paths: tuple[str, ...] = ()
    #: For a command tool: the registry id it runs.
    command_id: str = ""
    title: str = ""
    keywords: tuple[str, ...] = field(default_factory=tuple)

    @property
    def wire(self) -> str:
        return wire_name(self.name)

    @property
    def built(self) -> bool:
        if self.family == COMMAND_FAMILY and not COMMAND_TOOLS_BUILT:
            return False
        return self.handler is not None and self.effect in BUILT_EFFECTS

    def schema_for_clients(self) -> dict[str, object]:
        schema = dict(self.input_schema)
        if self.paged:
            properties = dict(schema.get("properties") or {})
            properties.setdefault("limit", {"type": "integer", "minimum": 1, "maximum": PAGE_LIMIT_MAX,
                                            "default": PAGE_LIMIT_DEFAULT,
                                            "description": "Rows a page holds."})
            properties.setdefault("page_token", {"type": "string", "maxLength": 128,
                                                 "description": "next_page_token from the previous page."})
            schema["properties"] = properties
        return schema

    def listing(self) -> dict[str, object]:
        """The tool as MCP ``tools/list`` shows it."""

        return {
            "name": self.wire,
            "title": self.title or self.name,
            "description": self.description,
            "inputSchema": self.schema_for_clients(),
            "annotations": {
                "readOnlyHint": self.effect == READ,
                "destructiveHint": self.effect == DESTRUCTIVE,
                "idempotentHint": self.effect == READ,
                # Nothing a tool does reaches beyond this computer.
                "openWorldHint": False,
            },
        }


def _check_tool(tool: Tool) -> None:
    if tool.effect not in EFFECT_CLASSES:
        raise ToolTableError(f"{tool.name}: unknown effect class {tool.effect!r}")
    if not WIRE_NAME_PATTERN.match(tool.wire):
        raise ToolTableError(f"{tool.name}: clients cannot call {tool.wire!r}")
    if tool.runs_on not in (ON_WORKER, ON_UI, ON_CALL):
        raise ToolTableError(f"{tool.name}: runs_on must be {ON_WORKER}, {ON_UI} or {ON_CALL}")
    if tool.effect == OUTPUT and not tool.output_paths and tool.family != COMMAND_FAMILY:
        raise ToolTableError(f"{tool.name}: an output tool names the arguments it writes to")
    for name in tool.output_paths:
        if name not in dict(tool.input_schema.get("properties") or {}):
            raise ToolTableError(f"{tool.name}: output path {name!r} is not an argument")
    try:
        check_schema_shape(tool.input_schema, tool.name)
    except ValueError as exc:
        raise ToolTableError(str(exc)) from None
    if tool.family == COMMAND_FAMILY:
        if not tool.command_id or reserved_prefix(tool.name):
            raise ToolTableError(f"{tool.name}: a command tool is named after its command id")
        return
    if tool.family + "." not in RESERVED_PREFIXES:
        raise ToolTableError(f"{tool.name}: {tool.family!r} is not a typed tool family")
    if not tool.name.startswith(tool.family + "."):
        raise ToolTableError(f"{tool.name}: a typed tool is named <family>.<action>")


def command_tool(command) -> Tool:
    """The tool for one registry command: no arguments, the command's own class."""

    context = str(command.context).replace("_", " ")
    return Tool(
        name=command.id, family=COMMAND_FAMILY,
        description=(f"{command.label} ({context}). Runs the command as its menu entry or button does. "
                     "When it is unavailable the result is the interface's reason and nothing changes."),
        input_schema=EMPTY_SCHEMA, effect=command.effect, route=f"registry:{command.id}",
        handler=_run_registry_command, runs_on=ON_UI, command_id=command.id, title=command.label,
    )


def _run_registry_command(call) -> object:
    from cdmw.mcp.errors import UNAVAILABLE, ToolError
    from cdmw.ui.commands.registry import CommandRefused

    registry = call.context.command_registry()
    if registry is None or call.tool.command_id not in registry:
        from cdmw.mcp.errors import NOT_FOUND

        raise ToolError(NOT_FOUND, f"The command {call.tool.command_id} is not registered now.")
    try:
        registry.run(call.tool.command_id)
    except CommandRefused as refused:
        raise ToolError(UNAVAILABLE, str(refused)) from None
    return {"ran": True, "command": call.tool.command_id}


class ToolTable:
    """The typed tools, fixed at start, and the command tools, read from the registry when asked."""

    def __init__(self, typed: Iterable[Tool], registry: Callable[[], object] | None = None) -> None:
        self._typed: dict[str, Tool] = {}
        wires: dict[str, str] = {}
        for tool in typed:
            _check_tool(tool)
            if tool.family == COMMAND_FAMILY:
                raise ToolTableError(f"{tool.name}: command tools come from the registry")
            if tool.wire in wires:
                raise ToolTableError(f"{tool.name} and {wires[tool.wire]} have the same client name")
            wires[tool.wire] = tool.name
            self._typed[tool.name] = tool
        self._registry = registry or (lambda: None)

    def typed(self) -> list[Tool]:
        return list(self._typed.values())

    def command_tools(self) -> list[Tool]:
        """One tool per registered command (call on the UI thread: the registry is a QObject)."""

        from cdmw.mcp.classification import USER_ONLY_COMMANDS

        registry = self._registry()
        if registry is None:
            return []
        tools = []
        wires = {tool.wire for tool in self._typed.values()}
        for command in registry.commands():
            if command.id in USER_ONLY_COMMANDS:
                continue
            tool = command_tool(command)
            if tool.wire in wires:
                # A typed tool keeps its name; the command is reported as a gap.
                continue
            wires.add(tool.wire)
            tools.append(tool)
        return tools

    def all(self) -> list[Tool]:
        return [*self.typed(), *self.command_tools()]

    def built(self) -> list[Tool]:
        return [tool for tool in self.all() if tool.built]

    def find(self, name: str, *, tools: Iterable[Tool] | None = None) -> Tool | None:
        """By client name or by table name."""

        text = str(name or "")
        for tool in tools if tools is not None else self.all():
            if text in (tool.wire, tool.name):
                return tool
        return None
