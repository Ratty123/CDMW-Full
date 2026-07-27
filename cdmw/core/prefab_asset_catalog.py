"""Archive paths grouped by file kind, for checking and picking prefab targets.

The Prefab Inspector can tell whether a replacement path *looks* right from its
text alone, but not whether the file exists -- and a path that is correctly
shaped but misspelt produces a prefab that loads nothing. This module supplies
the missing half: the set of paths the archives actually contain, per
extension.

Scanning the whole catalogue costs a few seconds even warm, so callers should
build the index off the UI thread and hand the result to the dialog. Per
extension the result is small: ``.pac`` is roughly 13,000 paths.
"""

from __future__ import annotations

import threading
from pathlib import Path, PurePosixPath
from typing import Iterable, Mapping, Sequence

_LOCK = threading.Lock()
_CACHE: dict[tuple[str, str], tuple[str, ...]] = {}


def _normalise(path: str) -> str:
    return str(path or "").replace("\\", "/").strip().lstrip("/")


def _extension_of(path: str) -> str:
    lowered = _normalise(path).lower()
    if lowered.endswith(".sockets.xml"):
        return ".sockets.xml"
    return PurePosixPath(lowered).suffix


def extension_for(path: str) -> str:
    """The extension used to group a path, treating ``.sockets.xml`` as one unit."""
    return _extension_of(path)


def collect_asset_paths(
    package_root: Path | str,
    extensions: Iterable[str],
    *,
    scan: object = None,
) -> dict[str, tuple[str, ...]]:
    """Every archive path for each requested extension, sorted.

    Results are cached per ``(package_root, extension)`` because the underlying
    catalogue scan is the expensive part and callers ask repeatedly.
    """
    root = str(package_root or "").strip()
    wanted = {str(item or "").strip().lower() for item in extensions if str(item or "").strip()}
    if not root or not wanted:
        return {}

    with _LOCK:
        cached = {ext: _CACHE[(root, ext)] for ext in wanted if (root, ext) in _CACHE}
    missing = wanted - set(cached)
    if not missing:
        return cached

    if scan is None:
        from cdmw.core.archive_scan_cache import scan_archive_entries as scan  # noqa: PLC0415

    entries = scan(Path(root))
    found: dict[str, list[str]] = {ext: [] for ext in missing}
    for entry in entries:
        path = _normalise(getattr(entry, "path", ""))
        if not path:
            continue
        extension = _extension_of(path)
        bucket = found.get(extension)
        if bucket is not None:
            bucket.append(path)

    resolved = {ext: tuple(sorted(set(values))) for ext, values in found.items()}
    with _LOCK:
        for ext, values in resolved.items():
            _CACHE[(root, ext)] = values
    return {**cached, **resolved}


def path_is_known(known: Mapping[str, Sequence[str]], path: str) -> bool | None:
    """Whether ``path`` exists, or ``None`` when no index covers its kind.

    ``None`` matters: it means "not checked", and the caller must not report it
    as missing.
    """
    normalised = _normalise(path).lower()
    if not normalised:
        return None
    candidates = known.get(_extension_of(normalised))
    if candidates is None:
        return None
    return normalised in {str(item).lower() for item in candidates}


def clear_cache() -> None:
    """Drop cached indexes, e.g. after the package root changes."""
    with _LOCK:
        _CACHE.clear()


__all__ = ["clear_cache", "collect_asset_paths", "extension_for", "path_is_known"]
