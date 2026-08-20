"""Build the next item on top of a mod folder the studio already wrote.

A loose mod carries whole tables: its `iteminfo.pabgb` is the shipped one with the item's
row appended, and so on for the strings, the groups, the shop and the fourteen language
tables. Two such mods therefore cannot both be enabled -- whichever the manager mounts
last owns the table, and the other item's row is simply not there. That is not a fault in
any manager; it is what replacing a whole file means.

The way out is to stop making a second mod. An item planned against the tables *in the
folder* appends its row to the rows already there, so one folder holds both, and the
manager mounts one table with two items in it. Nothing about the archives changes: the
plan still patches the same archive entries, and only the bytes it starts from are the
mod's rather than the game's, which is exactly what the overlay install does when it
reads the archives back after an install.

Only the payloads are taken from the folder. The entries stay the game's own, because an
entry names where a file lives in the archives, and an install has to write there.
"""

from __future__ import annotations

from pathlib import Path, PurePosixPath
from typing import Callable, Dict, Iterable, Mapping, Optional, Sequence

__all__ = [
    "MOD_BASE_TABLE_PATHS",
    "mod_folder_payloads",
    "read_entry_over_mod_folder",
    "describe_mod_folder",
]

#: The tables a new item rewrites; a folder holding any of them is one to build on.
MOD_BASE_TABLE_PATHS: tuple = (
    "gamedata/binary__/client/bin/iteminfo.pabgb",
    "gamedata/binary__/client/bin/iteminfo.pabgh",
    "gamedata/binary__/client/bin/stringinfo.pabgb",
    "gamedata/binary__/client/bin/stringinfo.pabgh",
    "gamedata/binary__/client/bin/itemgroupinfo.pabgb",
    "gamedata/binary__/client/bin/itemgroupinfo.pabgh",
    "gamedata/binary__/client/bin/storeinfo.pabgb",
    "gamedata/binary__/client/bin/storeinfo.pabgh",
)


def _normalize(path: str) -> str:
    return str(path or "").replace("\\", "/").strip().strip("/").lower()


def _roots(folder: Path) -> Iterable[Path]:
    """Where a manager's layout puts the game-relative tree: at the top, or under
    `files/` for the wrapper layouts."""

    yield folder
    wrapper = folder / "files"
    if wrapper.is_dir():
        yield wrapper


def mod_folder_payloads(folder: Path) -> Dict[str, Path]:
    """`{game path: the file in the folder}` for everything the folder carries.

    Both layouts the studio writes are read: game-relative at the top of the folder, and
    the same tree under `files/`.
    """

    found: Dict[str, Path] = {}
    root = Path(folder)
    if not root.is_dir():
        return found
    for base in _roots(root):
        for path in base.rglob("*"):
            if not path.is_file():
                continue
            relative = path.relative_to(base)
            parts = relative.parts
            if not parts or parts[0].lower() in {"files", "meta"} and base == root and parts[0].lower() == "files":
                continue
            if len(parts) < 2:
                continue  # manifest.json, modinfo.json, README.txt and the like
            found.setdefault(PurePosixPath(*parts).as_posix().lower(), path)
    return found


def read_entry_over_mod_folder(
    read_entry: Callable[[object], bytes],
    payloads: Mapping[str, Path],
) -> Callable[[object], bytes]:
    """`read_entry`, but a path the folder carries reads from the folder.

    The entry itself is untouched: it still names the archive the install writes into.
    """

    files = {_normalize(key): Path(value) for key, value in dict(payloads or {}).items()}

    def read(entry) -> bytes:
        loose = files.get(_normalize(getattr(entry, "path", "")))
        if loose is not None:
            try:
                return loose.read_bytes()
            except OSError:
                pass
        return read_entry(entry)

    return read


def describe_mod_folder(folder: Path, *, item_keys: Optional[Sequence[int]] = None) -> str:
    """One line about what is already in the folder, or "" when there is nothing to say."""

    payloads = mod_folder_payloads(folder)
    if not payloads:
        return ""
    tables = [path for path in payloads if path in {value.lower() for value in MOD_BASE_TABLE_PATHS}]
    if not tables:
        return f"{Path(folder).name} holds {len(payloads)} file(s), but none of the tables a new item is built from."
    counted = f", {len(item_keys)} item(s) in its table" if item_keys else ""
    return f"{Path(folder).name} already holds a mod: {len(payloads)} file(s), {len(tables)} table file(s){counted}."
