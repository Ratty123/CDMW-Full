"""Refit's Choose from Archive and Cloth's archive collision input, answered by an archive path.

Their buttons open a modal picker when the editor's request arrives, after the tool has sent
the command and left the action that answers dialogs: nothing would answer that picker, and
the editor would wait on it. The tool names the file instead ('archive_path'). CDMW prepares
it as the picker would (``cdmw.ui.mesh_editor.host_archive_choice``) and offers it to that
request, which then opens no picker. Without a path the tool refuses before sending anything.
"""

from __future__ import annotations

import threading
import time

from cdmw.mcp.errors import FAILED, INVALID_ARGUMENTS, NOT_FOUND, UNAVAILABLE, ToolError

#: How long preparing the file (its dependency set, or its bytes) may take.
CHOICE_S = 120.0
REFIT_ROLES = ("body", "armor")
CLOTH_ROLES = ("body", "head", "weapon")
NO_PICKER = ("An AI connection is not shown the archive picker: give 'archive_path', the file's path in the "
             "game archives (search_archive finds it).")


def picks_from_archive(command: str, arguments: dict) -> bool:
    """Whether this panel command would open an archive picker."""

    from cdmw.ui.mesh_editor.host_archive_choice import CLOTH_COMMAND, REFIT_COMMAND

    if command == REFIT_COMMAND:
        return True
    return command == CLOTH_COMMAND and (arguments.get("source") == "archive" or "archive_path" in arguments)


def _resolve(call, command: str, role: str, path: str):
    from cdmw.mcp.mesh_tools import ready_document
    from cdmw.ui.mesh_editor import host_archive_choice

    context = call.context
    finished = threading.Event()
    box: dict[str, object] = {}

    def done(choice) -> None:
        box["choice"] = choice
        finished.set()

    def failed(message: str) -> None:
        box["error"] = str(message)
        finished.set()

    def begin():
        return host_archive_choice.start(ready_document(context), command, role, path, on_done=done,
                                         on_failed=failed)

    cancel = context.ui_call(begin)
    deadline = time.monotonic() + CHOICE_S
    try:
        while not finished.wait(0.05):
            call.check_cancelled()
            if time.monotonic() > deadline:
                raise ToolError(FAILED, f"Preparing {path} from the archives took too long.")
    except BaseException:
        context.ui_call(cancel)
        raise
    if "error" in box:
        message = str(box["error"])
        code = NOT_FOUND if "have no file" in message else UNAVAILABLE if "Load the game" in message \
            else INVALID_ARGUMENTS
        raise ToolError(code, message)
    return box["choice"]


def send_with_choice(call, command: str, arguments: dict, send) -> dict[str, object]:
    """Prepare the named archive file, offer it to the editor's request, then ``send`` the command
    as its button sends it. An offer the request did not take is withdrawn."""

    from cdmw.mcp.mesh_tools import shown_document
    from cdmw.ui.mesh_editor.host_archive_choice import REFIT_COMMAND, offer, withdraw

    refit = command == REFIT_COMMAND
    roles = REFIT_ROLES if refit else CLOTH_ROLES
    role = str(arguments.get("role") or "")
    if role not in roles:
        raise ToolError(INVALID_ARGUMENTS, f"'role' is {' or '.join(roles)}.")
    extra = sorted(set(arguments) - {"role", "archive_path", "source"})
    if extra:
        raise ToolError(INVALID_ARGUMENTS, f"Unknown argument {extra[0]!r} for this command.")
    path = str(arguments.get("archive_path") or "").replace("\\", "/").strip().strip("/")
    if not path:
        raise ToolError(INVALID_ARGUMENTS, NO_PICKER)
    choice = _resolve(call, command, role, path)
    context = call.context

    def put() -> None:
        tab = shown_document(context)
        if tab is None:
            raise ToolError(UNAVAILABLE, "The Mesh Editor closed while the archive file was prepared.")
        offer(tab, choice)

    def forget() -> bool:
        tab = shown_document(context)
        return bool(tab is not None and withdraw(tab, command, choice))

    context.ui_call(put)
    try:
        outcome = send(call, command, {"role": role} if refit else {"role": role, "source": "archive"})
    finally:
        unused = context.ui_call(forget)
    outcome["archive_path"] = choice.path
    if unused:
        outcome.setdefault("message", "The Mesh Editor did not use the archive file; its status line says why.")
    return outcome


__all__ = ["CHOICE_S", "picks_from_archive", "send_with_choice"]
