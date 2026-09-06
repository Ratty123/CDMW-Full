"""Select one generation of item metadata without reading or changing archives."""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Mapping, Sequence

from cdmw.domain.archives.filters import archive_entry_load_priority
from cdmw.models import ArchiveEntry

LEGACY_TABLE_ROOT = "gamedata/binary__/client/bin"
STATIC_TABLE_ROOT = "gamedata/binarystaticinfo__/bin"
LOCALIZATION_ROOT = "gamedata/stringtable/binary__"


def source_package(entry: ArchiveEntry) -> str:
    return str(entry.pamt_path).replace("\\", "/").rsplit("/", 1)[0].casefold()


def item_localization_language(path: str) -> str:
    path = path.replace("\\", "/").strip("/").lower()
    if not path.startswith(LOCALIZATION_ROOT + "/"):
        return ""
    relative = path[len(LOCALIZATION_ROOT) + 1:]
    if relative.startswith("localizationstring_") and relative.endswith(".paloc"):
        return relative[len("localizationstring_"):-6]
    parts = relative.split("/")
    return parts[0] if len(parts) == 2 and parts[1] == "item.paloc" else ""


@dataclass(frozen=True)
class ItemDataSources:
    tables: Mapping[str, tuple[ArchiveEntry, ArchiveEntry]]
    localizations: Mapping[str, ArchiveEntry]
    static_layout: bool
    obsolete_packages: frozenset[str]
    mount_priorities: Mapping[str, int]

    def accepts(self, entry: ArchiveEntry) -> bool:
        return source_package(entry) not in self.obsolete_packages

    def priority(self, entry: ArchiveEntry) -> tuple:
        return (self.mount_priorities.get(source_package(entry), 0), *archive_entry_load_priority(entry))


def resolve_item_data_sources(entries: Iterable[ArchiveEntry]) -> ItemDataSources:
    candidates: dict[str, list[ArchiveEntry]] = defaultdict(list)
    pamt_paths = set()
    for entry in entries:
        pamt_paths.add(str(entry.pamt_path))
        path = entry.path.replace("\\", "/").strip("/").lower()
        if path.startswith((LEGACY_TABLE_ROOT + "/", STATIC_TABLE_ROOT + "/")) or item_localization_language(path):
            candidates[path].append(entry)

    mount_priorities = {}
    unmounted = set()
    packages = {Path(path).parent for path in pamt_paths}
    for root in {package.parent for package in packages}:
        papgt = root / "meta" / "0.papgt"
        if not papgt.is_file():
            continue
        from cdmw.core.papgt_format import parse_papgt
        if papgt.stat().st_size > 1024 * 1024:
            raise ValueError(f"Archive mount table is unexpectedly large: {papgt}")
        mounts = parse_papgt(papgt.read_bytes())
        mounted = {str(root / row.name).replace("\\", "/").casefold(): len(mounts) - index
                   for index, row in enumerate(mounts)}
        mount_priorities.update(mounted)
        unmounted.update(str(package).replace("\\", "/").casefold() for package in packages
                         if package.parent == root and str(package).replace("\\", "/").casefold() not in mounted)

    def priority(entry):
        return (mount_priorities.get(source_package(entry), 0), *archive_entry_load_priority(entry))

    def pamt(entry):
        return str(entry.pamt_path).replace("\\", "/").casefold()

    def pairs(root: str, body: str, header: str, excluded: frozenset[str] = frozenset()):
        result = {}
        for path, bodies in candidates.items():
            if not path.startswith(root + "/") or not path.endswith(body):
                continue
            headers = {pamt(e): e for e in candidates.get(path[:-len(body)] + header, ())}
            complete = [(e, headers[pamt(e)]) for e in bodies
                        if pamt(e) in headers and source_package(e) not in excluded | unmounted]
            if complete:
                result[path.rsplit("/", 1)[1][:-len(body)]] = max(complete, key=lambda pair: priority(pair[0]))
        return result

    current = pairs(STATIC_TABLE_ROOT, ".staticinfobody", ".staticinfoheader")
    static_layout = any(source_package(e) not in unmounted
                        for suffix in (".staticinfobody", ".staticinfoheader")
                        for e in candidates.get(f"{STATIC_TABLE_ROOT}/iteminfo{suffix}", ()))
    current_packages = {source_package(e) for e in candidates.get(f"{STATIC_TABLE_ROOT}/iteminfo.staticinfobody", ())}
    obsolete = frozenset(unmounted | {source_package(e) for e in candidates.get(f"{LEGACY_TABLE_ROOT}/iteminfo.pabgb", ())
                         if static_layout and source_package(e) not in current_packages})
    legacy = pairs(LEGACY_TABLE_ROOT, ".pabgb", ".pabgh", obsolete)
    tables = dict(current if static_layout else legacy)
    root, suffixes = ((STATIC_TABLE_ROOT, (".staticinfobody", ".staticinfoheader")) if static_layout
                      else (LEGACY_TABLE_ROOT, (".pabgb", ".pabgh")))
    # Never use a lower mounted copy to hide an incomplete authoritative pair.
    stems = {path[len(root) + 1:].rsplit(".", 1)[0] for path in candidates
             if path.startswith(root + "/") and path.endswith(suffixes)}
    for stem in stems:
        paths = [f"{root}/{stem}{suffix}" for suffix in suffixes]
        options = [entry for path in paths for entry in candidates.get(path, ())
                   if source_package(entry) not in obsolete]
        if not options:
            continue
        selected = max(options, key=priority)
        package = source_package(selected)
        if any(not any(pamt(e) == pamt(selected) for e in candidates.get(path, ())) for path in paths):
            raise ValueError(f"Incomplete {stem} table pair in {package}: {' and '.join(paths)}")
    # Older installations can ship these two read-only dictionaries in either layout.
    if not static_layout:
        for stem in ("statusinfo", "equiptypeinfo"):
            if stem in current:
                tables.setdefault(stem, current[stem])
    languages: dict[str, list[ArchiveEntry]] = defaultdict(list)
    for path, options in candidates.items():
        language = item_localization_language(path)
        if not language or path.endswith("/item.paloc") != static_layout:
            continue
        languages[language].extend(e for e in options if source_package(e) not in obsolete)
    localizations = {language: max(options, key=priority)
                     for language, options in sorted(languages.items()) if options}
    return ItemDataSources(tables, localizations, static_layout, obsolete, mount_priorities)


def active_item_source(entries: Sequence[ArchiveEntry], sources: ItemDataSources) -> ArchiveEntry | None:
    return max((e for e in entries if sources.accepts(e)), key=sources.priority, default=None)
