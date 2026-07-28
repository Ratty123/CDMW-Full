"""Which languages the archives ship, and which package table holds each one.

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
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Mapping, Optional, Tuple

#: `gamedata/stringtable/binary__/localizationstring_<language>.paloc`
PALOC_DIR = "gamedata/stringtable/binary__"
PALOC_PREFIX = "localizationstring_"

_CACHE_VERSION = 1


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
    """`.../localizationstring_eng.paloc` -> `eng`."""

    name = str(game_path or "").rsplit("/", 1)[-1]
    if not name.startswith(PALOC_PREFIX) or not name.endswith(".paloc"):
        return ""
    return name[len(PALOC_PREFIX):-len(".paloc")]


def game_path_for(language: str) -> str:
    return f"{PALOC_DIR}/{PALOC_PREFIX}{language}.paloc"


@dataclass(frozen=True)
class LanguageIndex:
    """Every language in the archives, and the package table each one was found in."""

    root: str
    languages: Tuple[str, ...] = ()
    #: language -> the `.pamt` that lists its table, as a string path.
    sources: Mapping[str, str] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.sources is None:
            object.__setattr__(self, "sources", {})

    def source_for(self, language: str) -> Optional[Path]:
        found = self.sources.get(language)
        return Path(found) if found else None


# ------------------------------------------------------------------ fingerprint


def _package_tables(root: Path):
    from cdmw.core.archive_format import discover_pamt_files

    return list(discover_pamt_files(Path(root)))


def _fingerprint(paths) -> Tuple[Tuple[str, int, int], ...]:
    """Size and mtime per package table: cheap enough to run on every open."""

    out = []
    for path in paths:
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
    stored = tuple(tuple(entry) for entry in payload.get("fingerprint") or ())
    stored = tuple((str(a), int(b), int(c)) for a, b, c in stored)
    if stored != _fingerprint(_package_tables(root)):
        return None
    sources = {str(k): str(v) for k, v in (payload.get("sources") or {}).items()}
    languages = tuple(str(name) for name in payload.get("languages") or ())
    return LanguageIndex(root=str(root), languages=languages, sources=sources)


# ---------------------------------------------------------------------- build


def build_index(
    root: Path, *, on_progress: Optional[Callable[[int, int], None]] = None
) -> LanguageIndex:
    """Sweep every package table once and record where each language lives.

    Later packages patch earlier ones, so the highest-numbered package wins -- the same
    rule `corpus.extract_baseline` applies when it resolves a path.
    """

    from cdmw.core.archive_format import parse_archive_pamt

    root = Path(root)
    tables = _package_tables(root)
    fingerprint = _fingerprint(tables)
    found: dict[str, tuple[str, str]] = {}
    for done, pamt in enumerate(tables, start=1):
        if on_progress is not None:
            on_progress(done, len(tables))
        try:
            entries = parse_archive_pamt(pamt)
        except Exception:  # noqa: BLE001 - one unreadable package must not hide the rest
            continue
        package = pamt.parent.name
        for entry in entries:
            path = str(getattr(entry, "path", "") or "").replace("\\", "/").strip().strip("/").lower()
            language = language_of(path)
            if not language:
                continue
            previous = found.get(language)
            if previous is None or package >= previous[0]:
                found[language] = (package, str(pamt))
    index = LanguageIndex(
        root=str(root),
        languages=tuple(sorted(found)),
        sources={language: source for language, (_package, source) in found.items()},
    )
    _write_cache(index, fingerprint)
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
