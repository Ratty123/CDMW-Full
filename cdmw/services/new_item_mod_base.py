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

import threading
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Callable, Dict, Iterable, Mapping, Optional, Sequence

__all__ = [
    "MOD_BASE_TABLE_PATHS",
    "ModFolderPayload",
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


@dataclass(frozen=True, slots=True)
class ModFolderPayload:
    """One game-relative payload, either loose or inside an exported archive group."""

    path: Optional[Path] = None
    entry: object = None

    def read_bytes(self) -> bytes:
        if self.path is not None:
            return self.path.read_bytes()
        if self.entry is None:
            raise FileNotFoundError("Source folder does not exist.")
        from cdmw.core.archive_extraction import read_archive_entry_data

        return bytes(read_archive_entry_data(self.entry)[0])

def _payload(value: object) -> ModFolderPayload:
    return value if isinstance(value, ModFolderPayload) else ModFolderPayload(path=Path(value))


def mod_folder_payloads(
    folder: Path,
    *,
    stop_event: Optional[threading.Event] = None,
) -> Dict[str, ModFolderPayload]:
    """`{game path: the file in the folder}` for everything the folder carries.

    Both layouts the studio writes are read: game-relative at the top of the folder, and
    the same tree under `files/`.
    """

    found: Dict[str, ModFolderPayload] = {}
    from cdmw.domain.cancellation import raise_if_cancelled

    raise_if_cancelled(stop_event, "New item plan cancelled.")
    root = Path(folder)
    if not root.is_dir():
        return found
    for base in _roots(root):
        for path in base.rglob("*"):
            raise_if_cancelled(stop_event, "New item plan cancelled.")
            if not path.is_file():
                continue
            relative = path.relative_to(base)
            parts = relative.parts
            if not parts or parts[0].lower() in {"files", "meta"} and base == root and parts[0].lower() == "files":
                continue
            if len(parts) < 2:
                continue  # manifest.json, modinfo.json, README.txt and the like
            if len(parts) == 2 and parts[0].isdigit() and parts[1].casefold() in {"0.pamt", "0.paz"}:
                continue  # an archive group's contents are indexed below, not as loose paths
            found.setdefault(PurePosixPath(*parts).as_posix().lower(), ModFolderPayload(path=path))

    # DMM writes the game-relative files inside ``<group>/0.pamt`` and ``0.paz``.
    # ``discover_pamt_files`` follows meta/0.papgt, so setdefault preserves the same
    # first-mounted-wins rule the game uses when more than one group is present.
    from cdmw.core.archive_format import discover_pamt_files, parse_archive_pamt

    for pamt in discover_pamt_files(root):
        for entry in parse_archive_pamt(pamt):
            raise_if_cancelled(stop_event, "New item plan cancelled.")
            found.setdefault(_normalize(getattr(entry, "path", "")), ModFolderPayload(entry=entry))
    return found


def read_entry_over_mod_folder(
    read_entry: Callable[[object], bytes],
    payloads: Mapping[str, object],
) -> Callable[[object], bytes]:
    """`read_entry`, but a path the folder carries reads from the folder.

    The entry itself is untouched: it still names the archive the install writes into.
    """

    files = {_normalize(key): _payload(value) for key, value in dict(payloads or {}).items()}

    def read(entry) -> bytes:
        loose = files.get(_normalize(getattr(entry, "path", "")))
        if loose is not None:
            # A selected mod base is authoritative. Falling through to the game after a
            # read failure silently plans a replacement that drops the mod's prior rows.
            return loose.read_bytes()
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
