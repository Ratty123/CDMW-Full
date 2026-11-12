"""How Drafts & Mods names the game files of a draft or a built mod.

Two drafts of one armour often differ only in the middle of their paths
(`.../9_upperbody/cd_phw_00_ub_00_0151.pac` and `.../14_sho/cd_phw_00_sho_under_00_0151.pac`),
so a middle elide can show the same text for both. These rules keep the file
name whole and shorten only the folders in front of it, and turn a build that
writes several files into "first file + N more" with every file in the tooltip.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

ELLIPSIS = "…"


def _clean(path: object) -> str:
    return str(path or "").replace("\\", "/").strip().strip("/")


def shorten_game_path(path: object, max_chars: int) -> str:
    """`path` within `max_chars`, dropping leading folders first and never the file name.

    Folders are dropped from the front and replaced by one ellipsis segment, so
    the folders closest to the file stay. When even the file name alone is
    longer than `max_chars`, the file name is returned whole.
    """

    text = _clean(path)
    limit = max(1, int(max_chars))
    if len(text) <= limit:
        return text
    parts = text.split("/")
    name = parts[-1]
    folders = parts[:-1]
    kept: list[str] = []
    # ELLIPSIS + "/" + kept folders + "/" + name
    budget = limit - len(name) - 2
    for folder in reversed(folders):
        cost = len(folder) + 1
        if budget - cost < 0:
            break
        kept.insert(0, folder)
        budget -= cost
    if not kept:
        return f"{ELLIPSIS}/{name}" if len(name) + 2 <= limit else name
    return "/".join([ELLIPSIS, *kept, name])


@dataclass(frozen=True, slots=True)
class GameFileLabel:
    """The cell text, its tooltip and the full list behind them."""

    text: str
    tooltip: str
    paths: tuple[str, ...]

    @property
    def more_count(self) -> int:
        return max(0, len(self.paths) - 1)


def game_file_label(
    paths: Iterable[object],
    *,
    max_chars: int = 64,
    package: str = "",
    more_template: str = "{first} + {count} more",
) -> GameFileLabel:
    """Label for one row: the first file shortened, "+ N more", every file in the tooltip.

    `more_template` is the localized "+ N more" text with `{first}` and `{count}`.
    """

    unique: list[str] = []
    seen: set[str] = set()
    for value in paths:
        cleaned = _clean(value)
        if cleaned and cleaned.casefold() not in seen:
            seen.add(cleaned.casefold())
            unique.append(cleaned)
    if not unique:
        return GameFileLabel("", "", ())
    first = shorten_game_path(unique[0], max_chars)
    text = first if len(unique) == 1 else more_template.format(first=first, count=len(unique) - 1)
    tooltip = "\n".join(unique)
    if package:
        tooltip += "\n" + str(package)
    return GameFileLabel(text, tooltip, tuple(unique))


__all__ = ["ELLIPSIS", "GameFileLabel", "game_file_label", "shorten_game_path"]
