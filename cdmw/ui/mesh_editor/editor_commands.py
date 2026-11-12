"""The Mesh Editor's commands in the registry, mirrored from its helper (P12 step 2).

The helper draws the editor's controls and owns its keymap. It reports each
command's id (the keymap id, such as ``tool.grab``), label, current keys and
whether it can run (``commands_state``); this module registers them under the
``mesh_editor`` context. Running one from the palette sends the helper the same
id its own key press runs (``run_command``).
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping

from cdmw.ui.commands.registry import Command, CommandRegistry

CONTEXT = "mesh_editor"
NOT_READY_REASON = "The Mesh Editor is not ready."
_ID_PREFIX = "mesh_editor."


def registry_id(helper_id: str) -> str:
    return _ID_PREFIX + helper_id


def mirror_helper_commands(registry: CommandRegistry, commands: Iterable[Mapping[str, object]],
                           send: Callable[[str], bool], ready: Callable[[], bool]) -> int:
    """Register the helper's commands; ``send(helper_id)`` asks the helper to run one."""

    mirrored = []
    for row in commands:
        helper_id = str(row.get("id", "") or "")
        label = str(row.get("label", "") or "").strip()
        if not helper_id or not label:
            continue
        reported = str(row.get("reason", "") or "")
        keys = tuple(str(key) for key in (row.get("keys") or ()) if str(key))

        def reason(reported: str = reported) -> str:
            return reported if ready() else NOT_READY_REASON

        mirrored.append(Command(registry_id(helper_id), label, CONTEXT,
                                lambda helper_id=helper_id: send(helper_id), reason, keys=keys,
                                helper=True, keywords=(helper_id,)))
    registry.replace_helper_commands(CONTEXT, mirrored)
    return len(mirrored)


def clear_helper_commands(registry: CommandRegistry) -> None:
    registry.replace_helper_commands(CONTEXT, ())
