"""Which languages the archives ship, and the source package of every string table.

Current installs split languages into named tables under binary__/<language>/.
Older installs use localizationstring_<language>.paloc. Keep each file's provenance
so loading a language and exporting its edits preserve the game's table boundaries.

Opening the panel listed the languages by parsing all 33 package tables -- 3.6 s on this
machine, on the UI thread, inside the tab's constructor. Pressing Load then paid the same
3.6 s again to locate a single entry.

Almost all of that is waste for this question. The fourteen `.paloc` tables live in
packages 0019-0032, which hold *one entry each* and parse in well under a millisecond; the
time goes to 0000, 0004 and 0009, which carry 200,000-400,000 entries apiece and not one
localization string between them. There is no way to know that without parsing, so the
sweep happens once and the answer is cached against the package files' own sizes and
timestamps. A warm open is one `stat` per package, and Load parses the single table that
actually holds the language.

The cache is a derived artefact and is always safe to delete: a missing or stale one costs
a rebuild, never a wrong answer, because the fingerprint has to match before it is used.
"""

from __future__ import annotations

import json
import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Mapping, Optional, Tuple

#: `gamedata/stringtable/binary__/localizationstring_<language>.paloc`
PALOC_DIR = "gamedata/stringtable/binary__"
PALOC_PREFIX = "localizationstring_"

_CACHE_VERSION = 3


def _install_root() -> Path:
    """Where the workspace lives, source tree or frozen build.

    Matches `tools.placement_studio.corpus._install_root`: a frozen build puts this module
    under `_internal/`, so a `__file__`-relative root would write the cache somewhere the
    installed app never looks.
    """

    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[2]


def work_root() -> Path:
    raw = str(os.environ.get("CDMW_TS_WORK_ROOT", "") or "").strip()
    return Path(raw) if raw else _install_root() / "workspace" / "translation_studio"


def cache_path() -> Path:
    return work_root() / "language_index.json"


def language_of(game_path: str) -> str:
    """Recognize both legacy monolithic tables and current language folders."""

    path = str(game_path or "").replace("\\", "/").strip("/").lower()
    name = path.rsplit("/", 1)[-1]
    if name.startswith(PALOC_PREFIX) and name.endswith(".paloc"):
        return name[len(PALOC_PREFIX):-len(".paloc")]
    if path.startswith(PALOC_DIR + "/"):
        parts = path[len(PALOC_DIR) + 1:].split("/")
        if len(parts) == 2 and re.fullmatch(r"[a-z]{3}(?:-[a-z]{2})?", parts[0]) and parts[1].endswith(".paloc"):
            return parts[0]
    return ""


def game_path_for(language: str) -> str:
    return f"{PALOC_DIR}/{PALOC_PREFIX}{language}.paloc"


@dataclass(frozen=True)
class LanguageIndex:
    """Every language in the archives, and the package table each one was found in."""

    root: str
    languages: Tuple[str, ...] = ()
    #: language -> the `.pamt` that lists its table, as a string path.
    sources: Mapping[str, str] = None  # type: ignore[assignment]
    #: Exact game path -> package table; a language can span multiple files/packages.
    tables: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.sources is None:
            object.__setattr__(self, "sources", {})

    def source_for(self, language: str) -> Optional[Path]:
        found = self.sources.get(language)
        return Path(found) if found else None

    def tables_for(self, language: str) -> Mapping[str, Path]:
        return {path: Path(source) for path, source in self.tables.items() if language_of(path) == language}


# ------------------------------------------------------------------ fingerprint


def _package_tables(root: Path):
    from cdmw.core.archive_format import discover_pamt_files

    tables = list(discover_pamt_files(Path(root)))
    from cdmw.core.papgt_format import parse_papgt

    priorities = {}
    for parent in {path.parent.parent for path in tables}:
        mount_file = parent / "meta" / "0.papgt"
        if not mount_file.is_file():
            continue
        if mount_file.stat().st_size > 1024 * 1024:
            raise ValueError(f"Archive mount table is unexpectedly large: {mount_file}")
        mounts = parse_papgt(mount_file.read_bytes())
        order = {row.name.casefold(): -index for index, row in enumerate(mounts)}
        tables = [path for path in tables if path.parent.parent != parent or path.parent.name.casefold() in order]
        priorities.update({path: order[path.parent.name.casefold()] for path in tables if path.parent.parent == parent})
    # Last candidate wins below. With a mount list, its first package has priority;
    # legacy installations without a list retain their numeric package ordering.
    return sorted(tables, key=lambda path: (priorities.get(path, 0), str(path)))


def _fingerprint(paths) -> Tuple[Tuple[str, int, int], ...]:
    """Size and mtime per package table: cheap enough to run on every open."""

    paths = list(paths)
    mounts = {path.parent.parent / "meta" / "0.papgt" for path in paths}
    out = []
    for path in [*paths, *(path for path in mounts if path.is_file())]:
        try:
            stat = path.stat()
        except OSError:
            continue
        out.append((str(path), int(stat.st_size), int(stat.st_mtime_ns)))
    return tuple(sorted(out))


# ---------------------------------------------------------------------- cache


def _read_cache() -> Optional[dict]:
    try:
        raw = cache_path().read_text(encoding="utf-8")
    except (OSError, ValueError):
        return None
    try:
        payload = json.loads(raw)
    except ValueError:
        return None
    return payload if isinstance(payload, dict) else None


def _write_cache(index: LanguageIndex, fingerprint) -> None:
    payload = {
        "version": _CACHE_VERSION,
        "root": index.root,
        "fingerprint": [list(entry) for entry in fingerprint],
        "languages": list(index.languages),
        "sources": dict(index.sources),
        "tables": dict(index.tables),
    }
    target = cache_path()
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        scratch = target.with_suffix(".json.tmp")
        scratch.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        scratch.replace(target)
    except OSError:
        # A cache that cannot be written costs a rebuild next time; it is never fatal.
        pass


def load_cached(root: Path) -> Optional[LanguageIndex]:
    """The stored index, but only when it still describes the packages on disk."""

    payload = _read_cache()
    if not payload or payload.get("version") != _CACHE_VERSION:
        return None
    if str(payload.get("root") or "") != str(root):
        return None
    try:
        stored = tuple((str(a), int(b), int(c)) for a, b, c in payload.get("fingerprint") or ())
        sources = dict(payload["sources"])
        languages = tuple(payload["languages"])
        tables = dict(payload["tables"])
        if not all(isinstance(path, str) and isinstance(source, str) for path, source in tables.items()):
            return None
        if tuple(sorted({language_of(path) for path in tables})) != languages or "" in languages:
            return None
        if set(sources) != set(languages) or not set(tables.values()) <= {entry[0] for entry in stored}:
            return None
    except (TypeError, ValueError, KeyError):
        return None
    if stored != _fingerprint(_package_tables(root)):
        return None
    return LanguageIndex(root=str(root), languages=languages, sources=sources, tables=tables)


# ---------------------------------------------------------------------- build


def build_index(
    root: Path, *, on_progress: Optional[Callable[[int, int], None]] = None
) -> LanguageIndex:
    """Sweep every package table once and record where each language lives.

    Use the game's mount order when available and retain every selected file path.
    """

    from cdmw.core.archive_format import parse_archive_pamt

    root = Path(root)
    tables = _package_tables(root)
    fingerprint = _fingerprint(tables)
    found: dict[str, str] = {}
    failed = []
    for done, pamt in enumerate(tables, start=1):
        if on_progress is not None:
            on_progress(done, len(tables))
        try:
            entries = parse_archive_pamt(pamt)
        except Exception:  # noqa: BLE001 - one unreadable package must not hide the rest
            failed.append(str(pamt))
            continue
        for entry in entries:
            path = str(getattr(entry, "path", "") or "").replace("\\", "/").strip().strip("/").lower()
            language = language_of(path)
            if not language:
                continue
            found[path] = str(pamt)
    split_languages = {language_of(path) for path in found if not path.rsplit("/", 1)[-1].startswith(PALOC_PREFIX)}
    found = {path: source for path, source in found.items()
             if not (path.rsplit("/", 1)[-1].startswith(PALOC_PREFIX) and language_of(path) in split_languages)}
    sources = {language_of(path): source for path, source in found.items()}
    index = LanguageIndex(
        root=str(root),
        languages=tuple(sorted(sources)),
        sources=sources,
        tables=found,
    )
    if not failed:
        _write_cache(index, fingerprint)
    elif not found:
        raise ValueError(f"Could not read archive package: {failed[0]}")
    return index


def language_index(
    root: Path,
    *,
    refresh: bool = False,
    on_progress: Optional[Callable[[int, int], None]] = None,
) -> LanguageIndex:
    """The cached index when it is still valid, otherwise a fresh sweep."""

    root = Path(root)
    if not refresh:
        cached = load_cached(root)
        if cached is not None:
            return cached
    return build_index(root, on_progress=on_progress)


def is_warm(root: Path) -> bool:
    """Whether opening the panel can answer instantly instead of sweeping the archives."""

    return load_cached(Path(root)) is not None


__all__ = [
    "LanguageIndex",
    "PALOC_DIR",
    "PALOC_PREFIX",
    "build_index",
    "cache_path",
    "game_path_for",
    "is_warm",
    "language_index",
    "language_of",
    "load_cached",
    "work_root",
]
