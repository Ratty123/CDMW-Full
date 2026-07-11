from __future__ import annotations

from cdmw.models import ArchiveEntry
from collections import Counter
from collections.abc import Mapping
from pathlib import Path
from collections.abc import Sequence
from cdmw.core.archive_format import parse_archive_pamt
from cdmw.core.archive_extraction import read_archive_entry_data

def _real_archive_all_pamt_entries(game_root: Path) -> tuple[tuple[ArchiveEntry, ...], tuple[Path, ...], tuple[dict[str, str], ...]]:
    pamt_paths = tuple(sorted(Path(game_root).glob("*/0.pamt")))
    entries: list[ArchiveEntry] = []
    errors: list[dict[str, str]] = []
    for pamt_path in pamt_paths:
        try:
            entries.extend(parse_archive_pamt(pamt_path))
        except Exception as exc:
            errors.append({"pamt_path": str(pamt_path), "error": f"{type(exc).__name__}: {exc}"})
    return tuple(entries), pamt_paths, tuple(errors)

def _real_archive_extension_counts_by_package(
    entries: Sequence[ArchiveEntry],
    extensions: Sequence[str],
) -> dict[str, dict[str, int]]:
    wanted = {str(extension).lower() for extension in extensions}
    counts: dict[str, Counter[str]] = {}
    for entry in entries:
        extension = str(entry.extension or "").lower()
        if extension not in wanted:
            continue
        package = entry.pamt_path.parent.name
        counts.setdefault(package, Counter())[extension] += 1
    return {package: dict(counter) for package, counter in sorted(counts.items())}

def _entry_by_archive_path(
    entries_by_path: Mapping[str, Sequence[ArchiveEntry]],
    path: object,
) -> ArchiveEntry | None:
    return next(iter(entries_by_path.get(_archive_key(path), ())), None)

def _archive_entry_indexes(
    entries: Sequence[ArchiveEntry],
) -> tuple[dict[str, tuple[ArchiveEntry, ...]], dict[str, tuple[ArchiveEntry, ...]]]:
    by_path: dict[str, list[ArchiveEntry]] = {}
    by_basename: dict[str, list[ArchiveEntry]] = {}
    for entry in entries:
        key = _archive_key(entry.path)
        if key:
            by_path.setdefault(key, []).append(entry)
            by_basename.setdefault(key.rsplit("/", 1)[-1], []).append(entry)
    return (
        {key: tuple(values) for key, values in by_path.items()},
        {key: tuple(values) for key, values in by_basename.items()},
    )

def _archive_key(path: object) -> str:
    return str(path or "").replace("\\", "/").lower().strip("/")

def _read_archive_payload(entry: ArchiveEntry) -> bytes:
    data, _decompressed, _note = read_archive_entry_data(entry)
    return data
