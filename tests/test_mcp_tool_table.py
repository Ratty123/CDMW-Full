"""P13 stage C, item 1: the tool table, reserved family prefixes and the effect class on Command."""
from __future__ import annotations

import pytest
from PySide6.QtWidgets import QApplication

from cdmw.mcp import classification
from cdmw.mcp.names import (
    DEFAULT_EFFECT,
    EDIT,
    EFFECT_CLASSES,
    OUTPUT,
    READ,
    RESERVED_PREFIXES,
    WIRE_NAME_PATTERN,
    wire_name,
)
from cdmw.mcp.tools import COMMAND_FAMILY, EMPTY_SCHEMA, Tool, ToolTable, ToolTableError, object_schema
from cdmw.ui.commands.registry import Command, CommandDefinitionError, CommandRegistry


@pytest.fixture
def app():
    return QApplication.instance() or QApplication([])


def _tool(name="search.example", family="search", effect=READ, **extra) -> Tool:
    return Tool(name=name, family=family, description="Example.", input_schema=extra.pop("schema", EMPTY_SCHEMA),
                effect=effect, route="service:example", handler=lambda call: {}, **extra)


def test_a_command_is_an_edit_unless_it_says_otherwise() -> None:
    command = Command("shell.example", "Example", "shell", lambda: None)
    assert command.effect == DEFAULT_EFFECT == EDIT
    for effect in EFFECT_CLASSES:
        assert Command("shell.example", "Example", "shell", lambda: None, effect=effect).effect == effect
    with pytest.raises(CommandDefinitionError, match="effect class"):
        Command("shell.example", "Example", "shell", lambda: None, effect="dangerous")


@pytest.mark.parametrize("prefix", RESERVED_PREFIXES)
def test_a_registry_command_cannot_take_a_reserved_family_prefix(prefix) -> None:
    with pytest.raises(CommandDefinitionError, match="typed AI tools"):
        Command(prefix + "anything", "Anything", "shell", lambda: None)
    # The area part may still contain the word: "mesh_editor." is not "mesh.".
    Command(prefix.rstrip(".") + "_area.action", "Fine", "shell", lambda: None)


def test_the_reserved_prefixes_are_the_planning_sessions_list() -> None:
    assert set(RESERVED_PREFIXES) == {
        "search.", "files.", "view.", "mesh.", "textures.", "materials.", "saved.", "app.", "commands.",
        "new_item.", "mods.", "tables.", "strings."}


def test_typed_tools_are_checked_when_the_table_is_built() -> None:
    ToolTable([_tool()])
    with pytest.raises(ToolTableError, match="not a typed tool family"):
        ToolTable([_tool(name="shell.thing", family="shell")])
    with pytest.raises(ToolTableError, match="<family>.<action>"):
        ToolTable([_tool(name="files.thing", family="search")])
    with pytest.raises(ToolTableError, match="unknown effect"):
        ToolTable([_tool(effect="dangerous")])
    with pytest.raises(ToolTableError, match="same client name"):
        ToolTable([_tool(), _tool()])
    with pytest.raises(ToolTableError, match="names the arguments it writes to"):
        ToolTable([_tool(effect=OUTPUT)])
    with pytest.raises(ToolTableError, match="not an argument"):
        ToolTable([_tool(effect=OUTPUT, output_paths=("path",))])
    with pytest.raises(ToolTableError, match="unsupported keywords"):
        ToolTable([_tool(schema={"type": "object", "pattern": "x"})])
    with pytest.raises(ToolTableError, match="command tools come from the registry"):
        ToolTable([_tool(name="shell.x", family=COMMAND_FAMILY, command_id="shell.x")])


def test_a_listing_carries_the_class_as_mcp_hints_and_pages_get_their_arguments() -> None:
    read = _tool(paged="rows", schema=object_schema({"query": {"type": "string"}}, ["query"])).listing()
    assert read["name"] == "search_example"
    assert read["annotations"] == {"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True,
                                   "openWorldHint": False}
    assert {"query", "limit", "page_token"} <= set(read["inputSchema"]["properties"])
    assert read["inputSchema"]["required"] == ["query"]


def test_every_registry_command_becomes_an_argument_free_tool_of_its_own_class(app) -> None:
    registry = CommandRegistry()
    registry.register(Command("shell.look", "Look", "shell", lambda: None, effect=READ))
    registry.register(Command("shell.change", "Change", "shell", lambda: None))
    registry.register(Command("shell.import_profile", "Import Profile...", "shell", lambda: None))
    table = ToolTable([_tool()], registry=lambda: registry)
    tools = {tool.name: tool for tool in table.command_tools()}
    # A profile can carry the AI settings and the game folder: never a tool.
    assert set(tools) == {"shell.look", "shell.change"}
    assert tools["shell.look"].effect == READ and tools["shell.look"].built
    assert tools["shell.look"].input_schema == EMPTY_SCHEMA and tools["shell.look"].wire == "shell_look"
    # Edit commands are tools of class edit, not built in this part of stage C.
    assert tools["shell.change"].effect == EDIT and not tools["shell.change"].built
    assert [tool.name for tool in table.built()] == ["search.example", "shell.look"]
    assert table.find("shell_look").name == table.find("shell.look").name == "shell.look"
    assert table.find("shell_nothing") is None


def test_client_names_fit_claude_and_openai() -> None:
    assert wire_name("mesh_editor.tool.grab") == "mesh_editor_tool_grab"
    assert WIRE_NAME_PATTERN.match("search_archive")
    assert not WIRE_NAME_PATTERN.match("search.archive")
    assert not WIRE_NAME_PATTERN.match("x" * 65)


# ----- the effect class of commands made elsewhere -----------------------------------
class _Shell:
    _shell_busy = False
    _window_menu_state = (True, True, True)


class _Editor:
    document = None

    def _busy(self):
        return False

    def export_dds_dialog(self):
        return None

    def preview_compressed_dds(self):
        return None


def _known_commands() -> list[Command]:
    from cdmw.domain.texture_editor_shortcuts import default_texture_editor_shortcuts
    from cdmw.ui.archive_browser.browse_commands import BROWSE_BUTTONS, CONTEXT, command_id
    from cdmw.ui.shell.shell_commands import shell_commands
    from cdmw.ui.texture_workflow.editor_commands import texture_editor_commands

    keys = default_texture_editor_shortcuts()
    bindings = {key: (lambda: None) for key in keys}
    commands = [*shell_commands(_Shell()), *texture_editor_commands(_Editor(), bindings, keys)]
    # Browse reads its labels from its buttons at run time; the id names the action.
    commands += [Command(command_id(name), name.replace("_", " ").capitalize(), CONTEXT, lambda: None)
                 for name in BROWSE_BUTTONS.values()]
    return commands


def test_a_command_named_build_export_delete_or_remove_does_not_keep_the_default_class(app) -> None:
    commands = _known_commands()
    unclassified = {command.id for command in commands if classification.needs_explicit_effect(command)}
    missing = sorted(unclassified - set(classification.AWAITING_CLASSIFICATION))
    assert not missing, f"Set effect= on these commands (output or destructive): {missing}"
    assert classification.needs_explicit_effect(Command("shell.zap", "Delete Draft", "shell", lambda: None))
    assert not classification.needs_explicit_effect(
        Command("shell.zap", "Delete Draft", "shell", lambda: None, effect="destructive"))


def test_the_list_awaiting_a_class_shrinks_as_the_main_thread_classifies(app) -> None:
    by_id = {command.id: command for command in _known_commands()}
    stale = sorted(command_id for command_id in classification.AWAITING_CLASSIFICATION
                   if command_id in by_id and by_id[command_id].effect != DEFAULT_EFFECT)
    assert not stale, f"These commands have their class now; remove their rows: {stale}"
    assert set(classification.AWAITING_CLASSIFICATION.values()) <= set(classification.RECOMMENDATIONS)
    # Every row names a command that exists, so the list cannot rot either.
    assert set(classification.AWAITING_CLASSIFICATION) <= set(by_id)
