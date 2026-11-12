"""The Mesh Editor's commands in the registry, mirrored from its helper (P12 step 2).

The helper draws the editor's controls and owns its keymap. It reports each
command's id (the keymap id, such as ``tool.grab``), label, current keys and
whether it can run (``commands_state``); this module registers them under the
``mesh_editor`` context. Running one from the palette sends the helper the same
id its own key press runs (``run_command``).

Each open document has its own helper (P15). Each reports its commands with
itself as ``owner``; the registry shows the commands of one owner, the document
the user sees (``set_command_owner``), and closing one document removes only its
own (section 8.7 E2).
"""

from __future__ import annotations

import weakref
from collections.abc import Callable, Iterable, Mapping

from cdmw.ui.commands.registry import Command, CommandRegistry

CONTEXT = "mesh_editor"
NOT_READY_REASON = "The Mesh Editor is not ready."
_ID_PREFIX = "mesh_editor."


def registry_id(helper_id: str) -> str:
    return _ID_PREFIX + helper_id


class _Mirror:
    """One document's reported commands. It holds its owner weakly and reaches it
    only when a command runs, so a closed document is never kept alive (8.8 R6)."""

    def __init__(self, owner: object, rows: list[Mapping[str, object]]) -> None:
        self.owner = weakref.ref(owner)
        self.rows = rows

    def send(self, helper_id: str) -> bool:
        owner = self.owner()
        send = getattr(owner, "_send_rust_command", None)
        return bool(callable(send) and send(helper_id))

    def ready(self) -> bool:
        return bool(getattr(self.owner(), "standalone_rust_ready", False))


class _Mirrors:
    """What each document's helper reported, and whose commands the registry shows."""

    def __init__(self) -> None:
        self.by_owner: dict[int, _Mirror] = {}
        self.owner: weakref.ref | None = None

    def alive(self) -> list[_Mirror]:
        for key in [key for key, mirror in self.by_owner.items() if mirror.owner() is None]:
            del self.by_owner[key]
        return list(self.by_owner.values())

    def shown(self) -> _Mirror | None:
        owner = self.owner() if self.owner is not None else None
        mirror = self.by_owner.get(id(owner)) if owner is not None else None
        # An id can be reused after its owner is gone: only its own mirror counts.
        return mirror if mirror is not None and mirror.owner() is owner else None


def _mirrors(registry: CommandRegistry) -> _Mirrors:
    mirrors = registry.__dict__.get("_mesh_editor_mirrors")
    if mirrors is None:
        mirrors = _Mirrors()
        registry.__dict__["_mesh_editor_mirrors"] = mirrors
    return mirrors


def _owner_of(document: object | None) -> object | None:
    """A Mesh Editor tab's helper is its live-edit component: that is the owner."""

    return getattr(document, "live_edit", None) or document


def _visible(owner: object) -> bool:
    frame = getattr(owner, "standalone_native_host_frame", None)
    try:
        return bool(frame is not None and frame.isVisible())
    except (AttributeError, RuntimeError):
        return False


def _target(registry: CommandRegistry) -> _Mirror | None:
    """The document a command runs in: the shown owner, or a visible one when the
    shown owner's editor is out of sight (the rail moved to Browse's edit)."""

    mirrors = _mirrors(registry)
    shown = mirrors.shown()
    if shown is not None and _visible(shown.owner()):
        return shown
    for mirror in reversed(mirrors.alive()):
        if _visible(mirror.owner()):
            return mirror
    return shown


def mirror_helper_commands(registry: CommandRegistry, commands: Iterable[Mapping[str, object]],
                           send: Callable[[str], bool], ready: Callable[[], bool], *,
                           owner: object | None = None) -> int:
    """Register the helper's commands; ``send(helper_id)`` asks the helper to run one.

    With an ``owner`` (the document whose helper reported them) they are kept for
    that document and shown when it is the shown owner, or when none is.
    """

    rows = [row for row in commands if isinstance(row, Mapping)]
    owner = _owner_of(owner)
    if owner is None:
        return _publish(registry, rows, send, ready)
    mirrors = _mirrors(registry)
    mirrors.by_owner[id(owner)] = _Mirror(owner, rows)
    shown = mirrors.shown()
    if shown is None or shown.owner() is owner:
        mirrors.owner = weakref.ref(owner)
        return _publish(registry, rows, None, None)
    return len(_command_rows(rows))


def set_command_owner(registry: CommandRegistry, owner: object | None) -> None:
    """The document the user now sees: the registry shows its commands."""

    owner = _owner_of(owner)
    mirrors = _mirrors(registry)
    mirrors.owner = weakref.ref(owner) if owner is not None else None
    mirror = mirrors.shown()
    _publish(registry, mirror.rows if mirror is not None else [], None, None)


def _command_rows(rows: Iterable[Mapping[str, object]]) -> list[Mapping[str, object]]:
    return [row for row in rows if str(row.get("id", "") or "") and str(row.get("label", "") or "").strip()]


def _publish(registry: CommandRegistry, commands: Iterable[Mapping[str, object]],
             send: Callable[[str], bool] | None, ready: Callable[[], bool] | None) -> int:
    """Show ``commands``; without ``send``/``ready`` each runs in the target document."""

    def run_in_target(helper_id: str) -> bool:
        target = _target(registry)
        return bool(target is not None and target.send(helper_id))

    def target_ready() -> bool:
        target = _target(registry)
        return bool(target is not None and target.ready())

    send = send or run_in_target
    ready = ready or target_ready
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


def clear_helper_commands(registry: CommandRegistry, owner: object | None = None) -> None:
    """Remove the commands ``owner``'s helper reported (all, without an owner).

    When it was the shown owner, the most recent other document's commands are
    shown instead, so one closing tab never takes another's commands along.
    """

    owner = _owner_of(owner)
    mirrors = _mirrors(registry)
    if owner is None:
        mirrors.by_owner.clear()
        mirrors.owner = None
        registry.replace_helper_commands(CONTEXT, ())
        return
    mirrors.by_owner.pop(id(owner), None)
    shown = mirrors.shown()
    if shown is not None:
        return
    remaining = mirrors.alive()
    next_owner = remaining[-1].owner() if remaining else None
    set_command_owner(registry, next_owner)
