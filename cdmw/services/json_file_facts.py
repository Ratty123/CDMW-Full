"""Small facts read from a JSON file, parsed once per unchanged file.

A preview package's manifest can be several megabytes. The UI thread asks
it small questions (which model it shows, whether it has textures, which
session wrote it) several times per click, and parsing the whole file each
time held the window. A fact is remembered with the file's identity (volume,
file id, size, modification time) and given again while that identity holds;
any rewrite, replacement or removal makes the next call read the file again.

A fact is remembered only when the file was last written at least
``_MIN_AGE_NS`` before it was read, so a same-size rewrite inside one
timestamp tick is never mistaken for the old file (the rule the preview file
digests use). Errors are never remembered: the caller sees them every time.
Facts must be small, immutable-by-convention values.

One parse answers every question asked so far of files with the same name:
the first launch on a new package parses its manifest once, not once per
question.
"""

from __future__ import annotations

import json
import os
import stat
import threading
import time
from collections import OrderedDict
from pathlib import Path
from typing import Callable, TypeVar

T = TypeVar("T")

_LIMIT = 1024
_MIN_AGE_NS = 100_000_000
_COARSE_STEP_NS = 10_000_000
_COARSE_MIN_AGE_NS = 3_000_000_000
_lock = threading.Lock()
_facts: "OrderedDict[tuple, tuple[tuple[int, int, int, int], dict]]" = OrderedDict()
#: The fact functions asked of each file name, so one parse can answer them all.
_known_facts: dict[tuple[str, str], list] = {}
#: Facts their modules declare up front, so even the first parse answers them.
_registered_facts: dict[tuple[str, str], list] = {}


def _identity(stat_result: os.stat_result) -> tuple[int, int, int, int]:
    return (
        int(stat_result.st_dev),
        int(getattr(stat_result, "st_ino", 0) or 0),
        int(stat_result.st_size),
        int(stat_result.st_mtime_ns),
    )


def _old_enough(identity: tuple[int, int, int, int], read_at_ns: int) -> bool:
    mtime = identity[3]
    margin = _COARSE_MIN_AGE_NS if mtime % _COARSE_STEP_NS == 0 else _MIN_AGE_NS
    return read_at_ns - mtime >= margin


def json_file_fact(
    path: Path | str,
    fact: Callable[[object], T],
    *,
    encoding: str = "utf-8",
) -> T:
    """``fact(json.loads(text))`` for the file at ``path``, remembered per file identity.

    Raises what reading and parsing the file raise (``OSError``,
    ``UnicodeError``, ``ValueError``). ``fact`` itself may raise; nothing is
    remembered then. ``fact`` must be a module-level function: it is part of
    the memo's key.
    """

    text_path = os.fspath(path)
    key = (os.path.normcase(os.path.abspath(text_path)), encoding)
    family = (os.path.normcase(os.path.basename(text_path)), encoding)
    before = os.stat(text_path)
    identity = _identity(before) if stat.S_ISREG(before.st_mode) else None
    memorable = identity is not None and bool(identity[1])
    if memorable:
        with _lock:
            known = _facts.get(key)
            if known is not None and known[0] == identity and fact in known[1]:
                _facts.move_to_end(key)
                return known[1][fact]  # type: ignore[return-value]
    read_at_ns = time.time_ns()
    with open(text_path, "rb") as stream:
        opened = _identity(os.fstat(stream.fileno()))
        data = stream.read()
    payload = json.loads(data.decode(encoding))
    value = fact(payload)
    if not (memorable and opened == identity and _old_enough(identity, read_at_ns)):
        return value
    with _lock:
        learned = _known_facts.setdefault(family, [])
        if fact not in learned:
            learned.append(fact)
        others = [
            other for other in (*_registered_facts.get(family, ()), *learned)
            if other is not fact
        ]
    answers = {fact: value}
    for other in others:
        try:
            answers[other] = other(payload)
        except Exception:
            continue
    with _lock:
        known = _facts.get(key)
        if known is not None and known[0] == identity:
            known[1].update(answers)
        else:
            _facts[key] = (identity, answers)
        _facts.move_to_end(key)
        while len(_facts) > _LIMIT:
            _facts.popitem(last=False)
    return value


def register_json_file_fact(file_name: str, fact: Callable[[object], object], *, encoding: str = "utf-8") -> None:
    """Answer ``fact`` from every parse of a file called ``file_name``, the first included."""

    family = (os.path.normcase(file_name), encoding)
    with _lock:
        registered = _registered_facts.setdefault(family, [])
        if fact not in registered:
            registered.append(fact)


def forget_json_file_facts() -> None:
    """Start from an empty memo (tests)."""

    with _lock:
        _facts.clear()
        _known_facts.clear()


__all__ = ["forget_json_file_facts", "json_file_fact", "register_json_file_fact"]
