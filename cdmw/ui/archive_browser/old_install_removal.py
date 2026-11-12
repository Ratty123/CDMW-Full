"""Browse Archives: Remove What an Older CDMW Installed... (decision 42).

The action is a registry command, ``browse.remove_old_install``, and, once the
Browse layout gives it one, a button beside Restore Backup...
(``archive_remove_old_install_button``). Restore Backup... becomes a command
too (``browse.restore_backup``). Both are user-only: no AI tool may list or
run them.

Both stages run on the shell's background runner: the check reads the game
folder, and the removal goes through ``cdmw.services.old_install_removal`` with
``ArchiveMutationService`` for its backup. No code here touches the game.
"""

from __future__ import annotations

import dataclasses
import threading
from collections.abc import Callable
from pathlib import Path

from PySide6.QtWidgets import QMessageBox

from cdmw.ui.commands.registry import Command, CommandRegistry, command_registry

REMOVE_COMMAND_ID = "browse.remove_old_install"
RESTORE_COMMAND_ID = "browse.restore_backup"
BUTTON_ATTRIBUTE = "archive_remove_old_install_button"
LABEL = "Remove What an Older CDMW Installed..."
TITLE = "Remove What an Older CDMW Installed"
REASON_NO_GAME = "Choose the game folder in Browse Archives first."
REASON_BUSY = "Wait for the current background task to finish"
_LIST_LIMIT = 40


def user_only_command(**fields) -> Command:
    """A Command no AI tool may list or run, once the registry knows the flag.

    The MCP branch adds ``Command.user_only``; until it is merged the field does
    not exist, so it is passed only when the dataclass has it.
    """

    if "user_only" in {item.name for item in dataclasses.fields(Command)}:
        fields["user_only"] = True
    return Command(**fields)


def _configured_root(browser) -> str:
    edit = getattr(browser, "archive_package_root_edit", None)
    try:
        return str(edit.text() or "").strip() if edit is not None else ""
    except RuntimeError:
        return ""


def _busy(browser) -> bool:
    shell = getattr(browser, "shell", None)
    check = getattr(shell, "_background_task_active", None)
    try:
        return bool(check()) if callable(check) else False
    except RuntimeError:
        return True


def _lines(values, limit: int = _LIST_LIMIT) -> str:
    values = tuple(values)
    shown = "\n".join(f"- {value}" for value in values[:limit])
    if len(values) > limit:
        shown += f"\n- ... {len(values) - limit:,} more"
    return shown


class OldInstallRemoval:
    """Runs the check and the removal for one Browse Archives page."""

    def __init__(self, browser) -> None:
        self.browser = browser

    def reason(self) -> str:
        if not _configured_root(self.browser):
            return REASON_NO_GAME
        if _busy(self.browser):
            return REASON_BUSY
        return ""

    def start(self) -> None:
        reason = self.reason()
        if reason:
            self.browser.shell.set_status_message(reason, error=True)
            return
        root = _configured_root(self.browser)

        def task(log: Callable[[str], None], stop_event: threading.Event):
            from cdmw.services.old_install_removal import find_old_install

            log(f"Looking for what an older CDMW installed in {root}...")
            return find_old_install(root, on_progress=log, stop_event=stop_event)

        self.browser.shell._run_utility_task(
            status_message="Looking for what an older CDMW installed...",
            task=task,
            on_complete=self._review,
            on_error=lambda message: self._failed(message),
            show_archive_progress=True,
            task_accepts_cancel=True,
        )

    def _failed(self, message: str) -> None:
        self.browser.shell.set_status_message(f"Nothing was changed: {message}", error=True)
        QMessageBox.warning(self.browser, TITLE, f"Nothing was changed.\n\n{message}")

    def _review(self, plan: object) -> None:
        from cdmw.services.old_install_removal import OldInstallPlan

        if not isinstance(plan, OldInstallPlan):
            return
        details = []
        if plan.not_cdmw:
            details.append("Not removed, not CDMW's:\n" + _lines(plan.not_cdmw))
        if plan.kept:
            details.append("Kept:\n" + _lines(plan.kept))
        if plan.nothing_found:
            text = f"Nothing an older CDMW installed was found in {plan.root}."
            self.browser.shell.set_status_message(text)
            QMessageBox.information(self.browser, TITLE, "\n\n".join([text, *details]))
            return
        if plan.blockers:
            QMessageBox.warning(self.browser, TITLE, "\n\n".join(
                ["Nothing can be removed yet.", _lines(plan.blockers), *details]))
            return
        parts = [f"Remove these from {plan.root}?", _lines(plan.review_lines())]
        if plan.overlay_items:
            parts.append("Items the old overlays held leave the game with them:\n" + _lines(plan.overlay_items))
        parts += details
        parts.append(
            f"Every file changed or removed ({plan.total_bytes:,} bytes) is backed up first, so Restore Backup... "
            "can put it all back. Close the game and DMM before you continue.")
        answer = QMessageBox.question(self.browser, TITLE, "\n\n".join(parts),
                                      QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if answer == QMessageBox.Yes:
            self._remove(plan)

    def _remove(self, plan) -> None:
        services = getattr(getattr(self.browser.shell, "app_context", None), "services", None)
        mutations = services.require_archive_mutations()
        configured = _configured_root(self.browser)

        def task(log: Callable[[str], None], stop_event: threading.Event):
            from cdmw.services.old_install_removal import remove_old_install

            return remove_old_install(
                plan, confirmed=True, configured_root=configured,
                backup=lambda paths, label: mutations.backup_files(paths, description=label, on_log=log),
                restore_backup=lambda path: mutations.restore_backup(path, confirmed=True, game_root=configured,
                                                                     on_log=log),
                on_log=log, stop_event=stop_event,
            )

        # This runs from the check's completion, while the shell still counts the check as busy.
        self.browser.shell._run_utility_task_when_idle(
            status_message="Removing what an older CDMW installed...",
            task=task,
            on_complete=self._removed,
            on_error=lambda message: self._failed(message),
            show_archive_progress=True,
            task_accepts_cancel=True,
        )

    def _removed(self, result: object) -> None:
        from cdmw.services.old_install_removal import OldInstallRemovalResult

        if not isinstance(result, OldInstallRemovalResult):
            return
        parts = [f"Removed {len(result.removed)} file(s) and entries from {result.root}.",
                 f"Backup: {result.backup_dir}\nRestore Backup... puts it all back."]
        if result.not_cdmw:
            parts.append("Not removed, not CDMW's:\n" + _lines(result.not_cdmw))
        if result.leftovers:
            parts.append("Folders left because they still hold other files:\n" + _lines(result.leftovers))
        if result.kept:
            parts.append("Kept:\n" + _lines(result.kept))
        self.browser.shell.set_status_message(f"Removed what an older CDMW installed. Backup: {result.backup_dir}")
        QMessageBox.information(self.browser, TITLE, "\n\n".join(parts))


def _restore_reason(browser) -> str:
    return REASON_BUSY if _busy(browser) else ""


def install_old_install_removal(browser) -> CommandRegistry | None:
    """Wire the action to Browse's button (when the layout has it) and register both commands."""

    action = OldInstallRemoval(browser)
    browser.old_install_removal = action
    button = getattr(browser, BUTTON_ATTRIBUTE, None)
    if button is not None:
        button.setText(LABEL)
        button.setToolTip("Take out the overlays and the game loader an older CDMW installed into this game folder. "
                          "Only what is proven CDMW's is removed, and it is backed up first.")
        button.clicked.connect(action.start)
    registry = command_registry()
    if registry is None:
        return None
    registry.register(user_only_command(
        id=REMOVE_COMMAND_ID, label=LABEL, context="browse", run=action.start, reason=action.reason,
        keywords=("remove", "uninstall", "overlay", "virtual loader", "old install", "cleanup"),
    ), replace=True)
    restore = getattr(browser, "_restore_archive_patch_backup_from_ui", None)
    if callable(restore):
        registry.register(user_only_command(
            id=RESTORE_COMMAND_ID, label="Restore Backup...", context="browse", run=restore,
            reason=lambda: _restore_reason(browser), keywords=("restore", "backup", "undo"),
        ), replace=True)
    return registry


__all__ = [
    "BUTTON_ATTRIBUTE",
    "LABEL",
    "OldInstallRemoval",
    "REMOVE_COMMAND_ID",
    "RESTORE_COMMAND_ID",
    "install_old_install_removal",
    "user_only_command",
]
