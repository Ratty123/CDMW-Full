"""Which registry commands still need their effect class set (section 7, answer 3).

A command's effect class is a field on ``Command`` with ``edit`` as its
default, set explicitly for read, output and destructive commands. The
commands below are registered outside ``cdmw/ui/commands/`` by code the main
thread owns, so they still have the default. Each maps to the class this
thread recommends; the main thread sets ``effect=`` where the command is made
and then removes its row here. ``USER_ONLY`` commands never become tools.

``tests/test_mcp_tool_table.py`` fails when a command whose label starts with
Build, Export, Delete or Remove has the default and is not listed here, and
when a listed command no longer has the default (its row is then stale).
"""

from __future__ import annotations

from cdmw.mcp.names import DEFAULT_EFFECT, DESTRUCTIVE, EDIT, OUTPUT, READ

#: Words that mark a command as more than an edit unless it says otherwise.
RISKY_LABEL_WORDS = ("Build", "Export", "Delete", "Remove")
#: Ids whose action part names an export, for commands whose label is read
#: from a button at run time (Browse Archives).
RISKY_ID_WORDS = ("export", "build", "delete", "remove")
#: Not a tool, whatever its class: it can change the AI connection setting,
#: the approval classes, Full access or the game folder (section 7, answer 8).
USER_ONLY = "user_only"


def needs_explicit_effect(command) -> bool:
    """A command whose label or id marks it as output or destructive but still has the default class."""

    if command.effect != DEFAULT_EFFECT:
        return False
    label = str(command.label or "").lstrip()
    action = str(command.id).split(".", 1)[-1].casefold()
    return label.startswith(RISKY_LABEL_WORDS) or any(word in action for word in RISKY_ID_WORDS)


#: Command id -> the class this thread recommends. The main thread owns these files.
AWAITING_CLASSIFICATION: dict[str, str] = {
    # Every command registered outside cdmw/ui/commands/ now sets its class where it
    # is made (shell_commands.py, browse_commands.py, texture_workflow/editor_commands.py).
}

#: Commands that never become tools, whatever class they are given later.
USER_ONLY_COMMANDS = frozenset({
    "shell.import_profile",  # a profile carries the AI settings and the game folder
    # The two routes that write into the game folder (decisions 41, 42): only the user
    # may confirm them, so no AI tool lists them under any setting.
    "browse.remove_old_install",
    "browse.restore_backup",
})

#: Every class a recommendation may name.
RECOMMENDATIONS = (READ, EDIT, DESTRUCTIVE, OUTPUT, USER_ONLY)
