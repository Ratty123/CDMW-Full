"""An index of the motion clips in the install, filtered by rig, category and name.

The archives hold ~316,000 `.paa` files. Reading the package tables to enumerate them takes
a few seconds and no decompression, so the index is built once — a slice per event-loop turn,
so the window stays alive while it runs — and kept in memory. There is no on-disk cache to go
stale against a game patch.

Categories come from filename tokens rather than directory layout, because the layout does
not separate them: a draw, a sprint and a parry all sit side by side in the model's root
folder. The tokens are the game's own naming, so they classify the corpus without a lookup
table to maintain.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, Iterator, List, Optional, Sequence

#: Order matters: the first pattern that matches wins, so the specific ones lead.
_CATEGORIES: tuple[tuple[str, str], ...] = (
    ("draw", r"weapon_out"),
    ("sheathe", r"weapon_in"),
    ("damage", r"_dam_|_hit|_stun|_knock|_death|_die"),
    ("guard", r"_guard|_block|_parry|_counter"),
    ("attack", r"_att_|_attack|_atk|_slash|_thrust|_smash|_combo|_skill|_charge"),
    ("throw", r"_throw|_grab|_kick"),
    ("jump", r"_jump|_land|_fall"),
    ("climb", r"_climb|_ladder"),
    ("swim", r"_swim"),
    ("run", r"_run|_sprint|_dash"),
    ("walk", r"_walk|_step"),
    ("turn", r"_turn|_sidestep"),
    ("roll", r"_roll"),
    ("sit", r"_sit"),
    ("idle", r"_idle|_stand"),
)
_COMPILED = tuple((label, re.compile(pattern)) for label, pattern in _CATEGORIES)

ALL_CATEGORIES = ("(any)", *[label for label, _p in _CATEGORIES], "other")
ANY = "(any)"


def classify(name: str) -> str:
    lowered = name.lower()
    for label, pattern in _COMPILED:
        if pattern.search(lowered):
            return label
    return "other"


def rig_of(game_path: str) -> str:
    """`character/motion/1_pc/1_phm/foo.paa` -> `1_pc/1_phm`.

    The rig, not the character: several characters share `1_phm`, and a clip is playable on
    whichever rig defines its bones.
    """

    parts = game_path.replace("\\", "/").split("/")
    if len(parts) > 4 and parts[0] == "character" and parts[1] == "motion":
        return f"{parts[2]}/{parts[3]}"
    return ""


@dataclass(frozen=True, slots=True)
class ClipEntry:
    """One clip, and enough to read it back."""

    path: str
    rig: str
    category: str
    is_lod: bool
    source: object = None  # archive entry, or a filesystem Path

    @property
    def name(self) -> str:
        return self.path.rsplit("/", 1)[-1][:-4]


class ClipIndex:
    """Every clip found, queryable without touching the archives again."""

    __slots__ = ("_entries", "_rigs")

    def __init__(self, entries: Iterable[ClipEntry] = ()) -> None:
        self._entries: tuple[ClipEntry, ...] = tuple(entries)
        self._rigs = tuple(sorted({entry.rig for entry in self._entries if entry.rig}))

    def __len__(self) -> int:
        return len(self._entries)

    @property
    def entries(self) -> tuple[ClipEntry, ...]:
        return self._entries

    def rigs(self) -> tuple[str, ...]:
        return self._rigs

    def filter(
        self,
        *,
        rig: str = ANY,
        category: str = ANY,
        text: str = "",
        include_lod: bool = False,
        limit: Optional[int] = None,
    ) -> tuple[List[ClipEntry], int]:
        """Matching clips, capped at `limit`, plus the total that matched.

        The total is returned separately so the UI can say how much it is hiding — a capped
        list that silently truncates reads as "the clip is not there".
        """

        needles = [part for part in text.lower().split() if part]
        found: List[ClipEntry] = []
        total = 0
        for entry in self._entries:
            if not include_lod and entry.is_lod:
                continue
            if rig != ANY and entry.rig != rig:
                continue
            if category != ANY and entry.category != category:
                continue
            if needles:
                lowered = entry.path.lower()
                if not all(needle in lowered for needle in needles):
                    continue
            total += 1
            if limit is None or len(found) < limit:
                found.append(entry)
        return found, total


def _entry(path: str, source: object) -> ClipEntry:
    name = path.rsplit("/", 1)[-1]
    return ClipEntry(
        path=path,
        rig=rig_of(path),
        category=classify(name),
        is_lod=name.lower().endswith("_lod.paa"),
        source=source,
    )


#: Entries walked between yields. Small enough that one slice is a few milliseconds — the
#: budget a frame has — and large enough that the per-slice overhead stays invisible.
_SLICE = 20_000


def scan_archives(
    game_root, *, should_stop: Optional[Callable[[], bool]] = None
) -> Iterator[tuple[int, int, Optional["ClipIndex"]]]:
    """Walk the package tables a slice at a time, yielding `(done, total, result)`.

    `result` is None until the final yield.

    A generator rather than a worker thread, for the reason `rig_files.scan_rig_files`
    documents: the walk is pure Python, so a `QThread` holds the GIL for its whole four to
    five seconds and starves the UI exactly as badly as calling it inline did — measured at
    19 event-loop ticks where 150 were due, an 87% starved window, which is what opening
    the studio felt like. Stepping it from the event loop keeps the window painting and
    answering the mouse while the index builds.
    """

    from .corpus import _iter_archive_entries, normalize_game_path

    root = Path(game_root)
    total = _package_count(root)
    entries: List[ClipEntry] = []
    seen_package = None
    done = 0
    since_yield = 0
    for package, archive_entry in _iter_archive_entries(root):
        if should_stop is not None and should_stop():
            return
        if package != seen_package:
            seen_package = package
            done += 1
        path = normalize_game_path(archive_entry.path)
        if path.endswith(".paa"):
            entries.append(_entry(path, archive_entry))
        since_yield += 1
        if since_yield >= _SLICE:
            since_yield = 0
            yield (done, total, None)
    yield (max(done, total), max(done, total), ClipIndex(entries))


def _package_count(root: Path) -> int:
    """How many packages the walk will visit, for a determinate bar.

    Best effort: a zero total simply means the caller shows a busy bar instead of a
    percentage, which is never a reason to fail the read.
    """

    from cdmw.core.archive_format import discover_pamt_files

    try:
        return len(list(discover_pamt_files(root)))
    except Exception:  # noqa: BLE001 - progress is decoration, never the reason to stop
        return 0


def index_archives(game_root, *, should_stop: Optional[Callable[[], bool]] = None) -> ClipIndex:
    """The whole walk in one call. Blocks; use `scan_archives` on a UI thread."""

    for _done, _total, result in scan_archives(game_root, should_stop=should_stop):
        if result is not None:
            return result
    return ClipIndex()


def index_directory(root) -> ClipIndex:
    """Index an extracted tree — the pinned vanilla baseline, or an export folder."""

    base = Path(root)
    entries: List[ClipEntry] = []
    for path in base.rglob("*.paa"):
        relative = path.relative_to(base).as_posix()
        entries.append(_entry(relative, path))
    return ClipIndex(entries)


def read_clip(entry: ClipEntry) -> bytes:
    """The clip's bytes, from wherever it was indexed."""

    if isinstance(entry.source, Path):
        return entry.source.read_bytes()
    if entry.source is None:
        raise ValueError(f"{entry.path} has no source to read from")
    from cdmw.core.archive_extraction import read_archive_entry_data

    data, _decoded, message = read_archive_entry_data(entry.source)
    if not data:
        raise ValueError(f"{entry.path}: archive read returned nothing ({message})")
    return data


def summarise(entries: Sequence[ClipEntry], total: int, limit: int) -> str:
    if not total:
        return "No clips match"
    if total > len(entries):
        return f"{len(entries)} of {total:,} shown — refine the filter to see the rest"
    return f"{total:,} clip(s)"
