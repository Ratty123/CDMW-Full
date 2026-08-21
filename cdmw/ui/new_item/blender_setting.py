"""Where the studio's Blender lives: chosen by the reader, remembered between sessions.

FBX is read by converting it (see :mod:`cdmw.services.fbx_blender_conversion`), and the
conversion only ever runs against a Blender the reader pointed at. Nothing here searches
the machine and uses what it finds on its own: :func:`suggested_blender` is what a file
dialog opens on, and the path that is stored is the one they chose in it.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

__all__ = ["BLENDER_SETTING", "blender_for_fbx", "remember_blender", "suggested_blender"]

#: the studio's own settings scope, the one the Model step already writes into
_SETTINGS_SCOPE = "CrimsonDesertModWorkbench"
BLENDER_SETTING = "new_item/blender_executable"


def blender_for_fbx() -> str:
    """The Blender the reader chose, or "" when they have not chosen one."""

    from PySide6.QtCore import QSettings

    from cdmw.services.fbx_blender_conversion import is_blender_executable

    try:
        stored = str(QSettings(_SETTINGS_SCOPE, _SETTINGS_SCOPE).value(BLENDER_SETTING, "") or "")
    except Exception:  # noqa: BLE001 - a session with no settings has chosen nothing
        return ""
    return stored if is_blender_executable(stored) else ""


def remember_blender(path: object) -> str:
    """Store `path` as the studio's Blender; "" forgets it. Returns what was stored."""

    from PySide6.QtCore import QSettings

    from cdmw.services.fbx_blender_conversion import is_blender_executable

    chosen = str(path or "")
    if chosen and not is_blender_executable(chosen):
        return blender_for_fbx()
    try:
        QSettings(_SETTINGS_SCOPE, _SETTINGS_SCOPE).setValue(BLENDER_SETTING, chosen)
    except Exception:  # noqa: BLE001 - not remembering is not worth an error
        pass
    return chosen


def suggested_blender() -> Optional[Path]:
    """Where a file dialog should open: a Blender this machine looks to have, or None.

    A suggestion only. Finding one here does not make it the studio's Blender -- the
    reader has to pick it, so that a conversion is always something they asked for.
    """

    from cdmw.services.fbx_blender_conversion import likely_blender_executables

    found = likely_blender_executables()
    return found[0] if found else None
