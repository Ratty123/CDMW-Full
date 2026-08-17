"""Allocation policy for a new item's identity: its key, its model stem, and its
localisation keys. Pure functions over sets the caller already holds; nothing
here reads a table.

Why these shapes:

* Item keys are authored integers with no visible ranges in the shipped table
  (Wolf's Fang is 1001295, a test sword 200997, a legendary 13810). New items go
  to `1990000..1999999` by default: high enough not to meet the shipped ids, low
  enough to stay seven digits, and it is the range the in-game-verified spike used
  (1990001, 1990002). The caller passes every key it can see (ItemInfo, plus the
  tables that refer to items) and gets the lowest free one.
* Stems are the shipped `cd_phm_01_sword_0109` shape. Keeping the length equal to
  the template's is what lets the prefab's `.pac` path be rewritten in place, so
  the default suggestion only replaces the leading digit of the template's last
  four-digit run with 9 (`cd_phm_01_sword_9109`) and counts up from there.
* Localisation keys are opaque strings; the shipped ones are 16-digit numbers.
  `43005292` + the seven-digit key + `1` (name) / `2` (description) keeps that
  look and is unique per item key.
"""

from __future__ import annotations

import re
from typing import Iterable, Mapping, Optional, Tuple

DEFAULT_ITEM_KEY_RANGE = range(1_990_000, 2_000_000)
_LOC_KEY_PREFIX = "43005292"
_DIGIT_RUN = re.compile(r"\d{4,}")


class AllocationError(ValueError):
    """Raised when no free identity value exists under the policy."""


def allocate_item_key(
    used: Iterable[int],
    *,
    preferred: Optional[int] = None,
    key_range: range = DEFAULT_ITEM_KEY_RANGE,
) -> int:
    """The preferred key when it is free, else the lowest free key in `key_range`."""

    taken = {int(value) for value in used}
    if preferred is not None:
        candidate = int(preferred)
        if candidate <= 0:
            raise AllocationError("item keys are positive")
        if candidate in taken:
            raise AllocationError(f"item key {candidate} is already used")
        return candidate
    for candidate in key_range:
        if candidate not in taken:
            return candidate
    raise AllocationError(f"no free item key in {key_range.start}..{key_range.stop - 1}")


def _stem_taken(stem: str, taken: Iterable[str]) -> bool:
    for existing in taken:
        if existing == stem or existing.startswith(stem + "_"):
            return True
    return False


def suggest_stem(
    template_stem: str,
    taken: Iterable[str],
    *,
    replacement_digit: str = "9",
) -> str:
    """A free stem of the template's length: its last four-digit-or-longer run with
    the leading digit swapped for `replacement_digit`, counting up while taken.

    `taken` should hold every stem the archives know (part-prefab stems, StringInfo
    texts, model family stems); a stem is taken when it or any `<stem>_...`
    variant is present.
    """

    stem = str(template_stem or "")
    runs = list(_DIGIT_RUN.finditer(stem))
    if not runs:
        raise AllocationError(f"template stem {stem!r} has no digit run to vary")
    if len(replacement_digit) != 1 or not replacement_digit.isdigit():
        raise AllocationError("replacement digit must be one digit")
    run = runs[-1]
    width = run.end() - run.start()
    head, tail = stem[: run.start()], stem[run.end() :]
    taken_list = list(taken)
    start = int(replacement_digit + run.group()[1:])
    for number in range(start, 10**width):
        candidate = f"{head}{number:0{width}d}{tail}"
        if candidate != stem and not _stem_taken(candidate, taken_list):
            return candidate
    raise AllocationError(f"no free stem of the shape {head}{replacement_digit}...{tail}")


def derive_family_stems(template_stem: str, new_stem: str, owned_stems: Iterable[str]) -> Mapping[str, str]:
    """old part stem -> new part stem, for every stem of the template's model family.

    Owned stems are the template's `<template_stem>_r`, `_l`, `_in`, ... prefabs;
    borrowed stems (another family's sheath) must not be passed, and are refused
    because they do not start with the template stem.
    """

    template = str(template_stem or "")
    replacement = str(new_stem or "")
    if not template or not replacement:
        raise AllocationError("both the template stem and the new stem are needed")
    if template == replacement:
        raise AllocationError("the new stem equals the template stem")
    mapping: dict[str, str] = {}
    for stem in owned_stems:
        if stem != template and not stem.startswith(template + "_"):
            raise AllocationError(f"{stem} is not part of the {template} family")
        mapping[stem] = replacement + stem[len(template) :]
    return mapping


def localization_keys(item_key: int) -> Tuple[str, str]:
    """(name key, description key) for an item key."""

    key = int(item_key)
    if key <= 0:
        raise AllocationError("item keys are positive")
    return f"{_LOC_KEY_PREFIX}{key:07d}1", f"{_LOC_KEY_PREFIX}{key:07d}2"


__all__ = [
    "AllocationError",
    "DEFAULT_ITEM_KEY_RANGE",
    "allocate_item_key",
    "derive_family_stems",
    "localization_keys",
    "suggest_stem",
]
