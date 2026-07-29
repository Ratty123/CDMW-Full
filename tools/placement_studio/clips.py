"""An index of the motion clips in the install, filtered by rig, category and name.

The archives hold ~316,000 `.paa` files. Reading the package tables to enumerate them takes
a few seconds and no decompression, so the index is built a slice per event-loop turn, so the
window stays alive while it runs.

It is also written to disk, keyed by the same package-table signature the wearables index
uses, so the walk is paid once per game version rather than once per launch: 4.9 seconds
becomes 0.7. The stored rows carry each clip's category, because deriving it costs fifteen
regex probes per path — 0.66s of that 0.7s if it is recomputed on load rather than read.

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
    game_root, *, should_stop: Optional[Callable[[], bool]] = None, cache: bool = True
) -> Iterator[tuple[int, int, Optional["ClipIndex"]]]:
    """Build the index a slice at a time, yielding `(done, total, result)`.

    `result` is None until the final yield. Reads the on-disk cache when one matches the
    install, and otherwise walks the package tables and writes one.

    A generator rather than a worker thread, for the reason `rig_files.scan_rig_files`
    documents: the work is pure Python, so a `QThread` holds the GIL for its whole four to
    five seconds and starves the UI exactly as badly as calling it inline did — measured at
    19 event-loop ticks where 150 were due, an 87% starved window, which is what opening
    the studio felt like. Stepping it from the event loop keeps the window painting and
    answering the mouse while the index builds. That applies to the cached path too: 0.7
    seconds of object building is still six missed frames if it happens in one call.
    """

    from .corpus import _iter_archive_entries, normalize_game_path

    root = Path(game_root)
    if cache:
        cached = _read_cache(root)
        if cached is not None:
            yield from _decode_cache(cached, should_stop=should_stop)
            return

    from .corpus import package_signature

    total = _package_count(root)
    entries: List[ClipEntry] = []
    seen_package = None
    done = 0
    since_yield = 0
    # Read before the walk, compared again after it. The walk takes ~5 seconds, which is
    # long enough for the game's launcher to patch underneath it; signing the result
    # afterwards would stamp a body built from the old packages with the new install's key
    # and every later launch would accept it.
    signature_before = package_signature(root) if cache else []
    failures: List[Path] = []
    for package, archive_entry in _iter_archive_entries(
        root, on_error=lambda pamt, _error: failures.append(pamt)
    ):
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
    index = ClipIndex(entries)
    if (
        cache
        and (should_stop is None or not should_stop())
        # A partial walk is fine to show and wrong to keep.
        and not failures
        and package_signature(root) == signature_before
    ):
        _write_cache(root, index, signature=signature_before)
    yield (max(done, total), max(done, total), index)


# ── on-disk cache ────────────────────────────────────────────────────
#
# Bump when the stored shape changes, so a stale file is ignored rather than misread.
_CACHE_VERSION = 1

#: Entries rebuilt between yields on the cached path. ~7 ms of work, a frame's budget.
#: Reading the file itself is one 250 ms block before the first yield — zlib, a `split` over
#: a 19 MB blob and two `tolist` calls, all of them single C calls with nothing to slice.
_DECODE_SLICE = 4_000

#: Category labels, by stored id. Order is the file format, so append — never reorder.
_CATEGORY_BY_ID: tuple[str, ...] = (*[label for label, _p in _CATEGORIES], "other")
_CATEGORY_ID = {label: index for index, label in enumerate(_CATEGORY_BY_ID)}


def _classifier_signature() -> str:
    """A digest of the rules, not just their names.

    Storing the label vocabulary catches a category being added or renamed. It does not
    catch the case that actually happens during development: a *pattern* edited while its
    label stays put — widening `attack` to match `_cleave`, say. Every stored row would keep
    the classification the old regex gave it, on an install whose signature is unchanged, so
    nothing would ever re-derive them. Digesting the patterns makes that a cache miss.
    """

    import hashlib

    return hashlib.sha256(repr(_CATEGORIES).encode("utf-8")).hexdigest()[:16]


def _cache_file() -> Path:
    from .corpus import work_root

    return Path(work_root()) / "clip-index.bin"


def _staging_path(target: Path) -> Path:
    """A temporary name only this writer uses.

    A fixed `<name>.tmp` is shared, and two Studios open at once — a second app instance, or
    the same one reopened — both truncate and write it before either renames. The rename
    itself is atomic; what it publishes is then a mix of two writers. The reader's CRC and
    length checks turn that into a rejected cache rather than bad data, so this is about not
    wasting the write, not about safety. Last valid writer wins, which is correct here.
    """

    import os

    return target.with_name(f"{target.name}.{os.getpid()}.tmp")


def _write_cache(game_root, index: "ClipIndex", *, signature=None) -> None:
    """Store the index. A failure here costs a rescan next launch, nothing more.

    Rows keep scan order and name their package by id, rather than being grouped under it.
    Grouping is the obvious encoding and it is wrong here: one `.pamt` table references
    several `.paz` files, so grouping by the pair splits a package's rows and reorders the
    index. `filter` returns in stored order and the browser draws the first 800, so that
    silently changed which clips a broad search listed, cold versus cached.
    """

    import array
    import json
    import zlib

    from .corpus import package_signature

    packages: List[list] = []
    package_id: dict[tuple[str, str], int] = {}
    paths: List[str] = []
    categories = bytearray()
    sources = array.array("i")
    numbers = array.array("q")
    for clip in index.entries:
        source = clip.source
        if source is None or isinstance(source, Path):
            continue
        key = (str(source.pamt_path), str(source.paz_file))
        identifier = package_id.get(key)
        if identifier is None:
            identifier = len(packages)
            package_id[key] = identifier
            packages.append([key[0], key[1]])
        paths.append(clip.path)
        categories.append(_CATEGORY_ID.get(clip.category, _CATEGORY_ID["other"]))
        sources.append(identifier)
        numbers.extend((
            source.offset, source.comp_size, source.orig_size,
            source.flags, source.paz_index,
        ))

    header = json.dumps({
        "version": _CACHE_VERSION,
        # The caller's reading, taken *before* the walk it is labelling.
        "signature": package_signature(Path(game_root)) if signature is None else signature,
        "classifier": _classifier_signature(),
        "packages": packages,
        "count": len(paths),
        "categories": list(_CATEGORY_BY_ID),
    }).encode("utf-8")
    path_bytes = "\n".join(paths).encode("utf-8")
    # Level 1: the blob is mostly repeated directory prefixes, so it still lands around
    # 4 MiB, and a slower level would cost more on the write than it saves on every read.
    body = zlib.compress(
        len(header).to_bytes(8, "little") + header
        + len(path_bytes).to_bytes(8, "little") + path_bytes
        + bytes(categories)
        + sources.tobytes()
        + numbers.tobytes(),
        1,
    )

    target = _cache_file()
    temporary = _staging_path(target)
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary.write_bytes(body)
        temporary.replace(target)
    except OSError:
        # A lost write costs a rescan. Do not leave the staging file behind for it.
        try:
            temporary.unlink()
        except OSError:
            pass


def _read_cache(game_root):
    """The cached index's raw parts, or `None` when there is no usable file."""

    import array
    import json
    import zlib

    from .corpus import package_signature

    try:
        raw = zlib.decompress(_cache_file().read_bytes())
    except (OSError, zlib.error):
        return None
    try:
        at = 0
        header_length = int.from_bytes(raw[at:at + 8], "little")
        at += 8
        header = json.loads(raw[at:at + header_length])
        at += header_length
        # A valid zlib stream is not a valid cache. `json.loads` returning a list — or any
        # other shape — turned `.get` into an AttributeError that escaped the handler below,
        # surfaced through the generator into the UI stepper, and dropped the browser to the
        # pinned baseline permanently instead of falling back to a cold scan.
        if not isinstance(header, dict):
            return None
        if header.get("version") != _CACHE_VERSION:
            return None
        # The vocabulary is stored rather than assumed: a build that added a category would
        # otherwise read every id after the insertion point as the wrong label.
        if list(header.get("categories", ())) != list(_CATEGORY_BY_ID):
            return None
        if header.get("classifier") != _classifier_signature():
            return None
        if header.get("signature") != package_signature(Path(game_root)):
            return None
        count = int(header["count"])
        path_length = int.from_bytes(raw[at:at + 8], "little")
        at += 8
        paths = raw[at:at + path_length].decode("utf-8").split("\n") if count else []
        at += path_length
        categories = raw[at:at + count]
        at += count
        sources = array.array("i")
        sources.frombytes(raw[at:at + count * sources.itemsize])
        at += count * sources.itemsize
        numbers = array.array("q")
        numbers.frombytes(raw[at:at + count * 5 * numbers.itemsize])
        if (
            len(paths) != count
            or len(categories) != count
            or len(sources) != count
            or len(numbers) != count * 5
        ):
            return None
    except Exception:  # noqa: BLE001 - any malformed cache is a cache miss, never a crash
        return None
    # `tolist` once, in C, rather than boxing each int on every indexed read.
    return header, paths, categories, sources.tolist(), numbers.tolist()


def _decode_cache(parts, *, should_stop: Optional[Callable[[], bool]] = None):
    """Rebuild the index from the cached parts, a slice per yield."""

    from cdmw.models import ArchiveEntry

    header, paths, categories, sources, numbers = parts
    total = int(header["count"])
    # One `Path` pair per package, shared by its rows: building 316,000 of them instead
    # costs more than everything else here put together.
    package_paths = [(Path(pamt), Path(paz)) for pamt, paz in header["packages"]]

    entries: List[ClipEntry] = []
    since_yield = 0
    for at in range(total):
        path = paths[at]
        base = at * 5
        pamt_path, paz_file = package_paths[sources[at]]
        entries.append(ClipEntry(
            path=path,
            rig=rig_of(path),
            category=_CATEGORY_BY_ID[categories[at]],
            is_lod=path.endswith("_lod.paa"),
            source=ArchiveEntry(
                path=path,
                pamt_path=pamt_path,
                paz_file=paz_file,
                offset=numbers[base],
                comp_size=numbers[base + 1],
                orig_size=numbers[base + 2],
                flags=numbers[base + 3],
                paz_index=numbers[base + 4],
            ),
        ))
        since_yield += 1
        if since_yield >= _DECODE_SLICE:
            since_yield = 0
            if should_stop is not None and should_stop():
                return
            yield (at + 1, total, None)
    yield (total, total, ClipIndex(entries))


def reset_cache() -> None:
    """Drop the stored index, so the next scan reads the archives again."""

    try:
        _cache_file().unlink()
    except OSError:
        pass


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
