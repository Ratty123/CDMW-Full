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

Two things keep that first read off the critical path. `scan_rig_files` is a generator
that yields every 20,000 entries, so the caller can step it from the Qt event loop and
the window keeps painting -- a `QThread` does not work here, because the walk is pure
Python and holds the GIL for the whole four seconds. And the result, under a megabyte, is
written to `work_root()/rig-files` and reloaded in about six milliseconds on every later
session, stamped with each package file's size and mtime so a game update invalidates it.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterator, Optional, Tuple

from . import corpus

#: Entries between progress yields. Small enough that one slice is a few ms,
#: large enough that the yield overhead stays invisible against 1.6M entries.
_SLICE = 20_000

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


def scan_rig_files(
    game_root: Optional[Path] = None,
    *,
    refresh: bool = False,
) -> Iterator[Tuple[int, int, Optional[RigFiles]]]:
    """Walk the archives a slice at a time, yielding `(done, total, result)`.

    `result` is None until the final yield. Written as a generator rather than run on a
    worker thread because the walk is pure Python: a `QThread` holds the GIL for the whole
    four seconds and starves the UI exactly as badly as calling it inline did -- measured
    at a 12-second gap between UI heartbeats. Stepping it from the event loop keeps the
    window alive between slices, and bounds each slice by entry count so one large package
    cannot stall it.
    """

    global _CACHE
    if _CACHE is not None and not refresh and game_root is None:
        yield (1, 1, _CACHE)
        return

    from cdmw.core.archive_extraction import read_archive_entry_data

    root = Path(game_root) if game_root is not None else corpus.game_root()
    if not refresh:
        # The whole result is under a megabyte, so the second session onwards pays
        # milliseconds instead of the walk. The first one still costs it.
        cached = _load_from_disk(root)
        if cached is not None:
            if game_root is None:
                _CACHE = cached
            yield (1, 1, cached)
            return
    total = _package_count(root)
    constraints: Dict[str, bytes] = {}
    pose_modifier = b""
    seen_package = None
    done = 0
    since_yield = 0
    # Iteration stays with `corpus._iter_archive_entries`, the one place that knows how to
    # walk the package tables. Progress comes from watching the package name change, so
    # this needs no second traversal and no duplicate of that logic.
    for package, entry in corpus._iter_archive_entries(root):
        if package != seen_package:
            seen_package = package
            done += 1
        path = corpus.normalize_game_path(entry.path)
        if path.endswith(".papr"):
            if path not in constraints:
                constraints[path] = _read(read_archive_entry_data, entry)
        elif path == POSE_MODIFIER_PATH and not pose_modifier:
            pose_modifier = _read(read_archive_entry_data, entry)
        since_yield += 1
        if since_yield >= _SLICE:
            since_yield = 0
            yield (done, total, None)

    files = RigFiles(
        constraint_paths=tuple(sorted(constraints)),
        constraints=constraints,
        pose_modifier=pose_modifier,
    )
    if game_root is None:
        _CACHE = files
    _save_to_disk(root, files)
    yield (max(done, total), max(done, total), files)


def read_rig_files(game_root: Optional[Path] = None, *, refresh: bool = False) -> RigFiles:
    """The whole walk in one call. Blocks; use `scan_rig_files` on a UI thread."""

    files: Optional[RigFiles] = None
    for _done, _total, result in scan_rig_files(game_root, refresh=refresh):
        if result is not None:
            files = result
    assert files is not None  # the generator always yields a result last
    return files


def _cache_dir(root: Path) -> Path:
    """Per-install cache directory, keyed on the archive root's own path."""

    digest = hashlib.sha256(str(root).encode("utf-8", "replace")).hexdigest()[:16]
    return corpus.work_root() / "rig-files" / digest


def _stamp(root: Path) -> dict:
    """What the cache is valid for: the package files, their sizes and their times.

    Reads only directory metadata, so it costs milliseconds against the walk's seconds.
    """

    from cdmw.core.archive_format import discover_pamt_files

    packages = []
    for pamt in sorted(discover_pamt_files(root)):
        try:
            info = pamt.stat()
        except OSError:
            continue
        packages.append([str(pamt), info.st_size, int(info.st_mtime)])
    return {"version": 1, "packages": packages}


def _load_from_disk(root: Path) -> Optional[RigFiles]:
    """The previous scan, if the archives have not changed since. Never raises."""

    directory = _cache_dir(root)
    try:
        manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
        if manifest.get("stamp") != _stamp(root):
            return None
        constraints = {
            path: (directory / name).read_bytes()
            for path, name in manifest["constraints"].items()
        }
        descriptor = manifest.get("pose_modifier") or ""
        pose_modifier = (directory / descriptor).read_bytes() if descriptor else b""
    except Exception:  # noqa: BLE001 - a stale or damaged cache means rescan, not fail
        return None
    return RigFiles(
        constraint_paths=tuple(sorted(constraints)),
        constraints=constraints,
        pose_modifier=pose_modifier,
    )


def _save_to_disk(root: Path, files: RigFiles) -> None:
    """Write the scan for next time. Failure here costs a rescan, nothing else."""

    directory = _cache_dir(root)
    try:
        directory.mkdir(parents=True, exist_ok=True)
        names = {}
        for index, path in enumerate(files.constraint_paths):
            name = f"{index:03d}.papr"
            (directory / name).write_bytes(files.constraints.get(path, b""))
            names[path] = name
        descriptor = ""
        if files.pose_modifier:
            descriptor = "posemodifierdata.xml"
            (directory / descriptor).write_bytes(files.pose_modifier)
        manifest = {"stamp": _stamp(root), "constraints": names, "pose_modifier": descriptor}
        (directory / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    except Exception:  # noqa: BLE001 - caching is an optimisation, never a failure mode
        return


def _package_count(root: Path) -> int:
    """How many packages the walk will visit, for a determinate bar.

    Best effort: a root the archive layer refuses is not a reason to fail the read, and a
    zero total simply means the caller shows a busy bar instead of a percentage.
    """

    from cdmw.core.archive_format import discover_pamt_files

    try:
        return len(list(discover_pamt_files(root)))
    except Exception:  # noqa: BLE001 - progress is decoration, never the reason to stop
        return 0


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
