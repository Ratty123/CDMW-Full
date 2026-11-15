"""Drafts & Mods' actions as registry commands (P12), registered by the page itself.

Like Browse's commands (``cdmw/ui/archive_browser/browse_commands.py``), the
page registers into the application's one registry when it is built, so the
shell needs no change. The command reads its state and reason from the page,
so the button, the palette and a shortcut agree.
"""

from __future__ import annotations

from cdmw.ui.commands.registry import Command, CommandRegistry, command_registry
from cdmw.ui.mesh_editor.saved_work_combine import COMMAND_ID, LABEL

CONTEXT = "shell"
REASON_PAGE_HIDDEN = "Open Drafts & Mods and select two or more built mods."
UNAVAILABLE = "Unavailable"


def combine_command(page) -> Command:
    def reason() -> str:
        try:
            if not page.isVisible():
                return REASON_PAGE_HIDDEN
            return page.combine_reason()
        except RuntimeError:  # the page was closed
            return UNAVAILABLE

    def run() -> None:
        try:
            page.combine_button.click()
        except RuntimeError:
            return

    return Command(COMMAND_ID, LABEL, CONTEXT, run, reason,
                   keywords=("combine", "merge", "drafts", "mods", "issue 31"))


def install_saved_work_commands(page) -> CommandRegistry | None:
    """Register Drafts & Mods' commands; the newest page replaces an older one's."""

    registry = command_registry()
    if registry is None:
        return None
    registry.register(combine_command(page), replace=True)
    return registry


__all__ = ["CONTEXT", "REASON_PAGE_HIDDEN", "combine_command", "install_saved_work_commands"]
