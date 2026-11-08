"""Character part role names on both sides of the October 2026 rename.

The DLC update dropped the ``CD_`` prefix from every part role and descriptor element
name: ``CD_MainWeapon_Sword_R`` became ``MainWeapon_Sword_R``, ``CD_Upperbody`` became
``Upperbody`` and the ``CD_Bag_For_Dock`` element became ``Bag_For_Dock``. Files
extracted before the update, and mods built from them, still carry the old form.

So a comparison accepts either form, and a name CDMW writes takes the form of the file
it is written into, which is the form the game that file came from reads.
"""

from __future__ import annotations

import re
from typing import Iterable

__all__ = [
    "LEGACY_PART_PREFIX",
    "bare_part_name",
    "find_part_name",
    "is_part_role_name",
    "part_name_like",
    "same_part_name",
]

#: The prefix part names carried before the DLC update.
LEGACY_PART_PREFIX = "CD_"

# Part roles are plain identifiers (`MainWeapon_Sword_IN_R`, `Hair_UpTail`, `p1`); paths,
# file names and socket names are told apart by the callers that need it.
_PART_ROLE = re.compile(r"[A-Za-z][A-Za-z0-9_]{0,127}\Z")


def bare_part_name(name: object) -> str:
    """`name` without the pre-update ``CD_`` prefix; a current name is returned unchanged."""

    text = str(name or "").strip()
    if text.startswith(LEGACY_PART_PREFIX):
        return text[len(LEGACY_PART_PREFIX):]
    return text


def same_part_name(left: object, right: object) -> bool:
    """Whether two part names are the same role, whichever side of the rename each is from."""

    bare = bare_part_name(left)
    return bool(bare) and bare == bare_part_name(right)


def part_name_like(name: object, reference: object) -> str:
    """`name` in the naming form `reference` uses.

    The old ``CD_`` form only when `reference` has it, so a role copied from a pre-update
    source into a current file is written the way the current game reads it, and the
    reverse for a file that still has the old names.
    """

    bare = bare_part_name(name)
    if not bare:
        return ""
    if str(reference or "").strip().startswith(LEGACY_PART_PREFIX):
        return LEGACY_PART_PREFIX + bare
    return bare


def find_part_name(names: Iterable[object], wanted: object) -> str:
    """The first of `names` that is the same role as `wanted`, as spelled there, or ``""``."""

    for name in names:
        if same_part_name(name, wanted):
            return str(name).strip()
    return ""


def is_part_role_name(text: object) -> bool:
    """Whether `text` is shaped like a part role name in either form."""

    return bool(_PART_ROLE.match(str(text or "")))
