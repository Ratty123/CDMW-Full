"""The one rule for a path an output is written to (P13 stage C, design record 2.6).

CDMW makes mods; it never writes into the game. Every tool that writes a
file, and the job runner before it writes, passes the path through
:func:`check_output_path`, which refuses, after resolving links:

* a path that is not absolute;
* a path whose folder does not exist;
* a path inside the configured game folder;
* a path inside any folder that holds ``meta/0.papgt`` (a game installation,
  configured or not, or a copy of one);
* a path inside a DLC folder of the game (``dlc/dlc_<digits>``);
* an existing file or folder: no output replaces one (section 7, answer 11).

No setting reaches this rule, Full access included. Pure: no Qt, no settings.
"""

from __future__ import annotations

import os
from pathlib import Path

GAME_INDEX = Path("meta") / "0.papgt"
DLC_PARENT = "dlc"
DLC_PREFIX = "dlc_"


class OutputPathRefused(ValueError):
    """The path may not be written to; the message says why, for the user and the client."""


def _resolved(path: Path) -> Path:
    # strict=False: the target itself need not exist; links and junctions in
    # the existing part are followed, so a junction into the game is caught.
    return Path(os.path.realpath(path))


def _key(path: Path) -> str:
    return os.path.normcase(os.path.normpath(str(path)))


def _inside(path: Path, folder: Path) -> bool:
    inner, outer = _key(path), _key(folder)
    return inner == outer or inner.startswith(outer.rstrip("\\/") + os.sep)


def is_dlc_folder(folder: Path) -> bool:
    name = folder.name.casefold()
    digits = name[len(DLC_PREFIX):]
    return (name.startswith(DLC_PREFIX) and digits.isascii() and digits.isdigit()
            and folder.parent.name.casefold() == DLC_PARENT)


def game_folder_holding(path: Path) -> Path | None:
    """The nearest folder at or above ``path`` that holds ``meta/0.papgt`` or is a game DLC folder."""

    for folder in (path, *path.parents):
        try:
            if (folder / GAME_INDEX).is_file() or is_dlc_folder(folder):
                return folder
        except OSError:
            continue
    return None


def check_output_path(path: str | os.PathLike[str], *, game_folder: str | os.PathLike[str] | None = None,
                      allow_existing: bool = False) -> Path:
    """The resolved path when it may be written to; otherwise raise :class:`OutputPathRefused`."""

    text = os.fspath(path) if path is not None else ""
    if not str(text).strip():
        raise OutputPathRefused("An output path is needed.")
    raw = Path(text)
    if not raw.is_absolute() or not raw.anchor or (os.name == "nt" and not raw.drive):
        raise OutputPathRefused(f"The output path must be absolute: {text}")
    target = _resolved(raw)
    parent = target.parent
    if not parent.is_dir():
        raise OutputPathRefused(f"The folder for the output does not exist: {parent}")
    configured = str(os.fspath(game_folder) if game_folder is not None else "").strip()
    if configured:
        game = _resolved(Path(configured))
        if _inside(target, game):
            raise OutputPathRefused(
                "CDMW does not write into the game folder. Choose a folder outside it; "
                "a mod manager installs the mod.")
    holder = game_folder_holding(target)
    if holder is not None:
        what = "a DLC folder of the game" if is_dlc_folder(holder) else "a game installation"
        raise OutputPathRefused(
            f"CDMW does not write into {what} ({holder}). Choose a folder outside it; a mod manager installs the mod.")
    if not allow_existing and os.path.lexists(target):
        raise OutputPathRefused(f"Something already exists at {target}; outputs never replace a file or folder.")
    return target
