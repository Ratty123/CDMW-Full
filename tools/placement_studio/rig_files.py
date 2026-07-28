"""The per-rig files the Studio reads straight from the archives, in one pass.

Two panels need files that are not in the pinned baseline: Driven bones wants the
`.papr` that sits beside the current character's skeleton, and Rig behaviour wants the
single `posemodifierdata.xml`. Both live in the archives, and finding anything there
means walking the package tables -- 1.6 million entries, about four seconds.

Done naively that is four seconds per panel and again on every character switch. So this
module makes exactly one pass, collects everything either panel could want, and caches
it for the process. `.papr` is small enough to hold all of it: twenty files, 660 KB
together, against 120 KB for the descriptor.

Reading eagerly rather than per character is what lets the panels follow the Studio's
selection instantly, which is the only reason they are tabs in the Studio rather than a
separate tool.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Optional, Tuple

from . import corpus

POSE_MODIFIER_PATH = "character/descriptors/posemodifierdata/posemodifierdata.xml"


@dataclass(frozen=True)
class RigFiles:
    """Everything the two rig panels can show, read once."""

    #: Archive paths of every `.papr`, so a model can be resolved against them.
    constraint_paths: Tuple[str, ...] = ()
    #: `.papr` payloads by archive path.
    constraints: Dict[str, bytes] = field(default_factory=dict)
    #: The pose-modifier descriptor, or empty when the archives do not carry it.
    pose_modifier: bytes = b""

    @property
    def available(self) -> bool:
        return bool(self.constraint_paths) or bool(self.pose_modifier)


_CACHE: Optional[RigFiles] = None


def read_rig_files(game_root: Optional[Path] = None, *, refresh: bool = False) -> RigFiles:
    """Walk the archives once and return both panels' inputs.

    Blocks for about four seconds on a cold call. Callers on the UI thread should say so
    before calling; every later call is free.
    """

    global _CACHE
    if _CACHE is not None and not refresh and game_root is None:
        return _CACHE

    from cdmw.core.archive_extraction import read_archive_entry_data

    root = Path(game_root) if game_root is not None else corpus.game_root()
    constraints: Dict[str, bytes] = {}
    pose_modifier = b""
    for _package, entry in corpus._iter_archive_entries(root):
        path = corpus.normalize_game_path(entry.path)
        if path.endswith(".papr"):
            if path not in constraints:
                constraints[path] = _read(read_archive_entry_data, entry)
        elif path == POSE_MODIFIER_PATH and not pose_modifier:
            pose_modifier = _read(read_archive_entry_data, entry)

    files = RigFiles(
        constraint_paths=tuple(sorted(constraints)),
        constraints=constraints,
        pose_modifier=pose_modifier,
    )
    if game_root is None:
        _CACHE = files
    return files


def _read(reader, entry) -> bytes:
    """A single unreadable entry must not cost the whole pass."""

    try:
        return reader(entry)[0]
    except Exception:  # noqa: BLE001 - a bad entry is one missing panel, not a crash
        return b""


def reset_cache() -> None:
    """Drop the cached pass. For tests, and for a Studio told to re-read."""

    global _CACHE
    _CACHE = None
