from __future__ import annotations

import hashlib
import json
import os
import pickle
import re
import shutil
import threading
import time
from collections import OrderedDict, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Tuple

try:
    import lz4.block as lz4_block
except ImportError:
    lz4_block = None

from cdmw.core.atomic_file import atomic_binary_writer, atomic_copy_file, atomic_write_bytes, atomic_write_text
from cdmw.core.common import raise_if_cancelled
from cdmw.models import ArchiveEntry, RunCancelled


def format_byte_size(value: int) -> str:
    from cdmw.core.archive_extraction import format_byte_size as owner

    return owner(value)


def parse_archive_pamt(path: Path) -> List[ArchiveEntry]:
    from cdmw.core.archive_format import parse_archive_pamt as owner

    return owner(path)


def scan_archive_entries(package_root: Path, **options: Any) -> List[ArchiveEntry]:
    from cdmw.core.archive_format import scan_archive_entries as owner

    return owner(package_root, **options)


_ARCHIVE_SCAN_CACHE_MAGIC = b"CTFARCH1"
_ARCHIVE_SCAN_CACHE_VERSION = 3
_ARCHIVE_SCAN_SHARD_CACHE_MAGIC = b"CTFSHSC1"
_ARCHIVE_SCAN_SHARD_CACHE_VERSION = 1
_ARCHIVE_SCAN_SHARD_METADATA_VERSION = 1
_HKX_CONTEXT_MODEL_PREVIEW_CACHE_LIMIT = 16
_HKX_CONTEXT_MODEL_PREVIEW_CACHE: "OrderedDict[str, ModelPreviewData]" = OrderedDict()
_ARCHIVE_SCAN_CACHE_LEGACY_DIRNAMES: Tuple[str, ...] = ("cache", "archive_scan_cache")
_ARCHIVE_SIDECAR_CACHE_MAGIC = b"CTFSIDE1"
_ARCHIVE_SIDECAR_CACHE_VERSION = 10
_ARCHIVE_SIDECAR_ENTRY_SIGNATURE_FORMAT = 1
_ARCHIVE_DERIVED_INDEX_CACHE_MAGIC = b"CTFDERI1"
_ARCHIVE_DERIVED_INDEX_CACHE_VERSION = 11
_ARCHIVE_ITEM_ICON_THUMBNAIL_CACHE_VERSION = 1
_ARCHIVE_BASIC_INDEX_CACHE_MAGIC = b"CTFBASI1"
_ARCHIVE_BASIC_INDEX_CACHE_VERSION = 2
_ARCHIVE_BASIC_INDEX_SHARD_CACHE_MAGIC = b"CTFSHBI1"
_ARCHIVE_BASIC_INDEX_SHARD_CACHE_VERSION = 1
_ARCHIVE_NAME_SEARCH_SHARD_META_VERSION = 2
_ARCHIVE_ENTRY_METADATA_SIGNATURE_FORMAT = 1
_ARCHIVE_DERIVED_INDEX_CACHE_MAX_SAFE_BYTES = 64 * 1024 * 1024
_ARCHIVE_BASIC_INDEX_CACHE_MAX_SAFE_BYTES = 256 * 1024 * 1024
_ARCHIVE_CACHE_ROOT_MAX_BYTES = 512 * 1024 * 1024
_ARCHIVE_CACHE_ROOT_TARGET_BYTES = 384 * 1024 * 1024
_ARCHIVE_CACHE_ROOT_PREFIXES: Tuple[str, ...] = (
    "archive_scan_",
    "archive_scan_shards_",
    "archive_sidecars_",
    "archive_derived_indexes_",
    "archive_item_icon_thumbnails_",
    "archive_basic_indexes_",
    "archive_basic_index_shards_",
    "archive_name_search_",
    "archive_name_search_shards_",
)
_ARCHIVE_ITEM_ICON_THUMBNAIL_CACHE_LOCK = threading.Lock()
_ARCHIVE_ITEM_ICON_THUMBNAIL_MANIFEST_CACHE: Dict[str, Tuple[Tuple[int, int], Dict[str, object]]] = {}
_ARCHIVE_SCAN_CACHE_SUPPORTED_VERSIONS = {3}
_ARCHIVE_SCAN_IGNORED_TOP_LEVEL_DIRS: frozenset[str] = frozenset({"cdmods"})


def discover_pamt_files(package_root: Path) -> List[Path]:
    root = package_root.expanduser().resolve()
    if root.is_file() and root.suffix.lower() == ".pamt":
        return [root]
    if not root.exists() or not root.is_dir():
        raise ValueError(f"Archive package root does not exist or is not a folder: {root}")
    files: List[Path] = []
    for path in root.rglob("*.pamt"):
        if not path.is_file():
            continue
        try:
            top_level_dir = path.relative_to(root).parts[0].lower()
        except (IndexError, ValueError):
            top_level_dir = ""
        if top_level_dir in _ARCHIVE_SCAN_IGNORED_TOP_LEVEL_DIRS:
            continue
        files.append(path)
    files.sort()
    return files


def resolve_archive_scan_cache_path(package_root: Path, cache_root: Path) -> Path:
    digest = _archive_cache_root_digest(package_root)
    return cache_root / f"archive_scan_{digest}.bin"


def _archive_cache_root_digest(package_root: Path) -> str:
    try:
        resolved_root = package_root.expanduser().resolve()
    except OSError:
        resolved_root = package_root.expanduser()
    return hashlib.sha256(str(resolved_root).lower().encode("utf-8", errors="replace")).hexdigest()[:24]


def resolve_archive_scan_shard_cache_dir(package_root: Path, cache_root: Path) -> Path:
    return cache_root / f"archive_scan_shards_{_archive_cache_root_digest(package_root)}"


def resolve_archive_scan_shard_metadata_path(package_root: Path, cache_root: Path) -> Path:
    return resolve_archive_scan_shard_cache_dir(package_root, cache_root) / "_metadata.json"


def resolve_archive_basic_index_shard_cache_dir(package_root: Path, cache_root: Path) -> Path:
    return cache_root / f"archive_basic_index_shards_{_archive_cache_root_digest(package_root)}"


def resolve_archive_name_search_shard_cache_dir(package_root: Path, cache_root: Path) -> Path:
    return cache_root / f"archive_name_search_shards_{_archive_cache_root_digest(package_root)}"


def _archive_scan_shard_id(relative_pamt_path: str) -> str:
    normalized = str(relative_pamt_path or "").replace("\\", "/").strip().lower()
    return hashlib.sha256(normalized.encode("utf-8", errors="replace")).hexdigest()[:16]


def resolve_archive_sidecar_cache_path(package_root: Path, cache_root: Path) -> Path:
    return cache_root / f"archive_sidecars_{_archive_cache_root_digest(package_root)}.bin"


def resolve_archive_sidecar_cache_metadata_path(package_root: Path, cache_root: Path) -> Path:
    return resolve_archive_sidecar_cache_path(package_root, cache_root).with_suffix(".meta.json")


def resolve_archive_derived_index_cache_path(package_root: Path, cache_root: Path) -> Path:
    return cache_root / f"archive_derived_indexes_{_archive_cache_root_digest(package_root)}.bin"


def resolve_archive_item_icon_thumbnail_cache_dir(package_root: Path, cache_root: Path) -> Path:
    return cache_root / f"archive_item_icon_thumbnails_{_archive_cache_root_digest(package_root)}"


def resolve_archive_basic_index_cache_path(package_root: Path, cache_root: Path) -> Path:
    return cache_root / f"archive_basic_indexes_{_archive_cache_root_digest(package_root)}.bin"


def resolve_archive_name_search_index_cache_path(package_root: Path, cache_root: Path) -> Path:
    return cache_root / f"archive_name_search_{_archive_cache_root_digest(package_root)}.bin"


def archive_cache_protected_paths(package_root: Path, cache_root: Path) -> Tuple[Path, ...]:
    return (
        resolve_archive_scan_cache_path(package_root, cache_root),
        resolve_archive_scan_shard_cache_dir(package_root, cache_root),
        resolve_archive_sidecar_cache_path(package_root, cache_root),
        resolve_archive_sidecar_cache_metadata_path(package_root, cache_root),
        resolve_archive_derived_index_cache_path(package_root, cache_root),
        resolve_archive_item_icon_thumbnail_cache_dir(package_root, cache_root),
        resolve_archive_basic_index_cache_path(package_root, cache_root),
        resolve_archive_basic_index_shard_cache_dir(package_root, cache_root),
        resolve_archive_name_search_index_cache_path(package_root, cache_root),
        resolve_archive_name_search_shard_cache_dir(package_root, cache_root),
    )


def resolve_crimson_desert_executable(package_root: Path) -> Optional[Path]:
    base_dir = _archive_base_dir(package_root)
    candidate_roots: List[Path] = []
    for candidate_root in (base_dir, *base_dir.parents[:4]):
        normalized = str(candidate_root).strip().lower()
        if not normalized or any(str(existing).strip().lower() == normalized for existing in candidate_roots):
            continue
        candidate_roots.append(candidate_root)

    for candidate_root in candidate_roots:
        for relative_path in (
            Path("bin64") / "CrimsonDesert.exe",
            Path("CrimsonDesert.exe"),
        ):
            candidate = candidate_root / relative_path
            if candidate.is_file():
                try:
                    return candidate.expanduser().resolve()
                except OSError:
                    return candidate.expanduser()
    return None


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def invalidate_archive_browser_cache(
    package_root: Path,
    cache_root: Path,
    *,
    on_log: Optional[Callable[[str], None]] = None,
) -> List[Path]:
    try:
        resolved_cache_root = cache_root.expanduser().resolve()
    except OSError:
        resolved_cache_root = cache_root.expanduser()

    candidate_roots = [resolved_cache_root]
    sibling_parent = resolved_cache_root.parent
    for dirname in _ARCHIVE_SCAN_CACHE_LEGACY_DIRNAMES:
        candidate_roots.append(sibling_parent / dirname)

    cache_paths: List[Path] = []
    seen: set[str] = set()
    for candidate_root in candidate_roots:
        for candidate_path in (
            resolve_archive_scan_cache_path(package_root, candidate_root),
            resolve_archive_scan_shard_cache_dir(package_root, candidate_root),
            resolve_archive_sidecar_cache_path(package_root, candidate_root),
            resolve_archive_sidecar_cache_metadata_path(package_root, candidate_root),
            resolve_archive_derived_index_cache_path(package_root, candidate_root),
            resolve_archive_item_icon_thumbnail_cache_dir(package_root, candidate_root),
            resolve_archive_basic_index_cache_path(package_root, candidate_root),
            resolve_archive_basic_index_shard_cache_dir(package_root, candidate_root),
            resolve_archive_name_search_index_cache_path(package_root, candidate_root),
            resolve_archive_name_search_shard_cache_dir(package_root, candidate_root),
        ):
            normalized_path = str(candidate_path).strip().lower()
            if not normalized_path or normalized_path in seen:
                continue
            seen.add(normalized_path)
            cache_paths.append(candidate_path)

    deleted_paths: List[Path] = []
    for cache_path in cache_paths:
        if not cache_path.exists():
            continue
        try:
            if cache_path.is_dir():
                shutil.rmtree(cache_path)
            else:
                cache_path.unlink()
            deleted_paths.append(cache_path)
        except OSError as exc:
            if on_log:
                on_log(f"Warning: could not delete archive cache path {cache_path}: {exc}")

    return deleted_paths


def prune_archive_cache_root(
    cache_root: Path,
    *,
    max_bytes: int = _ARCHIVE_CACHE_ROOT_MAX_BYTES,
    target_bytes: int = _ARCHIVE_CACHE_ROOT_TARGET_BYTES,
    protected_paths: Sequence[Path] = (),
) -> Dict[str, int]:
    root = Path(cache_root)
    if max_bytes <= 0 or target_bytes < 0 or not root.is_dir():
        return {"files": 0, "bytes": 0, "removed_files": 0, "removed_bytes": 0}

    def protection_key(path: Path) -> str:
        try:
            resolved = Path(path).expanduser().resolve()
        except OSError:
            resolved = Path(path).expanduser()
        return os.path.normcase(os.fspath(resolved)).rstrip("\\/").casefold()

    protected_keys = tuple(key for key in (protection_key(path) for path in protected_paths) if key)

    def is_protected(path: Path) -> bool:
        if not protected_keys:
            return False
        path_key = protection_key(path)
        for protected_key in protected_keys:
            if (
                path_key == protected_key
                or path_key.startswith(protected_key + os.sep)
                or protected_key.startswith(path_key + os.sep)
            ):
                return True
        return False

    units: List[Tuple[float, int, int, Path]] = []
    total_bytes = 0
    try:
        children = tuple(root.iterdir())
    except OSError:
        return {"files": 0, "bytes": 0, "removed_files": 0, "removed_bytes": 0}
    for path in children:
        if not any(path.name.startswith(prefix) for prefix in _ARCHIVE_CACHE_ROOT_PREFIXES):
            continue
        protected = is_protected(path)
        file_count = 0
        latest_mtime = 0.0
        size = 0
        if path.is_file():
            try:
                stat = path.stat()
            except OSError:
                continue
            size = max(0, int(stat.st_size))
            latest_mtime = float(stat.st_mtime)
            file_count = 1
        elif path.is_dir():
            try:
                for child in path.rglob("*"):
                    if not child.is_file():
                        continue
                    try:
                        stat = child.stat()
                    except OSError:
                        continue
                    size += max(0, int(stat.st_size))
                    latest_mtime = max(latest_mtime, float(stat.st_mtime))
                    file_count += 1
                if latest_mtime <= 0.0:
                    latest_mtime = float(path.stat().st_mtime)
            except OSError:
                continue
        else:
            continue
        total_bytes += size
        if protected:
            continue
        units.append((latest_mtime, size, file_count, path))
    if total_bytes <= max_bytes:
        return {"files": sum(item[2] for item in units), "bytes": total_bytes, "removed_files": 0, "removed_bytes": 0}
    current_bytes = total_bytes
    removed_files = 0
    removed_bytes = 0
    for _mtime, size, file_count, path in sorted(units, key=lambda item: (item[0], str(item[3]).lower())):
        if current_bytes <= min(target_bytes, max_bytes):
            break
        try:
            if path.is_dir():
                shutil.rmtree(path)
            else:
                path.unlink()
        except OSError:
            continue
        current_bytes = max(0, current_bytes - size)
        removed_files += max(1, int(file_count))
        removed_bytes += size
    return {
        "files": max(0, sum(item[2] for item in units) - removed_files),
        "bytes": current_bytes,
        "removed_files": removed_files,
        "removed_bytes": removed_bytes,
    }


def _candidate_archive_scan_cache_paths(package_root: Path, cache_root: Path) -> List[Path]:
    try:
        resolved_cache_root = cache_root.expanduser().resolve()
    except OSError:
        resolved_cache_root = cache_root.expanduser()

    root_candidates = [resolved_cache_root]
    sibling_parent = resolved_cache_root.parent
    for dirname in _ARCHIVE_SCAN_CACHE_LEGACY_DIRNAMES:
        root_candidates.append(sibling_parent / dirname)

    cache_paths: List[Path] = []
    seen: set[str] = set()
    for candidate_root in root_candidates:
        normalized_root = str(candidate_root).strip()
        if not normalized_root:
            continue
        lowered_root = normalized_root.lower()
        if lowered_root in seen:
            continue
        seen.add(lowered_root)
        cache_paths.append(resolve_archive_scan_cache_path(package_root, candidate_root))
    return cache_paths


def _archive_base_dir(package_root: Path) -> Path:
    try:
        resolved_root = package_root.expanduser().resolve()
    except OSError:
        resolved_root = package_root.expanduser()
    return resolved_root.parent if resolved_root.is_file() else resolved_root


def _archive_relative_source_path(base_dir: Path, path: Path) -> str:
    try:
        resolved_base_dir = base_dir.resolve()
    except OSError:
        resolved_base_dir = base_dir
    return _archive_relative_source_path_cached(base_dir, resolved_base_dir, {}, path)


def _archive_relative_source_path_cached(
    base_dir: Path,
    resolved_base_dir: Path,
    cache: Dict[Path, str],
    path: Path,
) -> str:
    cached = cache.get(path)
    if cached is not None:
        return cached
    try:
        relative_path = path.resolve().relative_to(resolved_base_dir).as_posix()
    except (OSError, ValueError):
        try:
            relative_path = path.relative_to(base_dir).as_posix()
        except ValueError:
            relative_path = path.name
    cache[path] = relative_path
    return relative_path


def _collect_archive_scan_sources_and_files(
    package_root: Path,
    *,
    pamt_files: Optional[Sequence[Path]] = None,
) -> Tuple[Path, List[Tuple[str, int, int]], List[Path]]:
    base_dir = _archive_base_dir(package_root)
    files = list(pamt_files) if pamt_files is not None else discover_pamt_files(package_root)
    sources: List[Tuple[str, int, int]] = []
    for pamt_path in files:
        try:
            stat_result = pamt_path.stat()
        except FileNotFoundError:
            continue
        sources.append(
            (
                _archive_relative_source_path(base_dir, pamt_path),
                int(stat_result.st_size),
                int(getattr(stat_result, "st_mtime_ns", int(stat_result.st_mtime * 1_000_000_000))),
            )
        )
    return base_dir, sources, files


def _collect_archive_scan_sources(
    package_root: Path,
    *,
    pamt_files: Optional[Sequence[Path]] = None,
) -> Tuple[Path, List[Tuple[str, int, int]]]:
    base_dir, sources, _files = _collect_archive_scan_sources_and_files(
        package_root,
        pamt_files=pamt_files,
    )
    return base_dir, sources


def _collect_archive_scan_sources_from_entries(
    package_root: Path,
    entries: Sequence[ArchiveEntry],
) -> Tuple[Path, List[Tuple[str, int, int]]]:
    base_dir = _archive_base_dir(package_root)
    unique_archive_paths: Dict[str, Path] = {}
    for entry in entries:
        for raw_path in (getattr(entry, "pamt_path", None), getattr(entry, "paz_file", None)):
            if raw_path is None:
                continue
            archive_path = raw_path if isinstance(raw_path, Path) else Path(raw_path).expanduser()
            try:
                normalized_key = os.path.normcase(os.fspath(archive_path)).strip().lower()
            except (OSError, TypeError, ValueError):
                normalized_key = str(archive_path).strip().lower()
            if not normalized_key or normalized_key in unique_archive_paths:
                continue
            unique_archive_paths[normalized_key] = archive_path

    sources: List[Tuple[str, int, int]] = []
    for archive_path in sorted(unique_archive_paths.values(), key=lambda value: str(value).lower()):
        try:
            stat_result = archive_path.stat()
        except FileNotFoundError:
            continue
        sources.append(
            (
                _archive_relative_source_path(base_dir, archive_path),
                int(stat_result.st_size),
                int(getattr(stat_result, "st_mtime_ns", int(stat_result.st_mtime * 1_000_000_000))),
            )
        )
    return base_dir, sources


def _normalize_archive_source_rows(rows: object) -> Optional[List[Tuple[str, int, int]]]:
    if not isinstance(rows, list):
        return None
    normalized_rows: List[Tuple[str, int, int]] = []
    for row in rows:
        if not isinstance(row, (list, tuple)) or len(row) != 3:
            return None
        relative_path, raw_size, raw_mtime_ns = row
        normalized_rows.append((str(relative_path), int(raw_size), int(raw_mtime_ns)))
    return normalized_rows


def _normalize_archive_entry_metadata_signature(value: object) -> str:
    text = str(value or "").strip().lower()
    if re.fullmatch(r"[0-9a-f]{64}", text):
        return text
    return ""


def _archive_source_rows_from_paths(
    base_dir: Path,
    paths: Sequence[Path],
) -> List[Tuple[str, int, int]]:
    unique_paths: Dict[str, Path] = {}
    for raw_path in paths:
        archive_path = raw_path if isinstance(raw_path, Path) else Path(raw_path).expanduser()
        try:
            normalized_key = os.path.normcase(os.fspath(archive_path)).strip().lower()
        except (OSError, TypeError, ValueError):
            normalized_key = str(archive_path).strip().lower()
        if normalized_key and normalized_key not in unique_paths:
            unique_paths[normalized_key] = archive_path

    sources: List[Tuple[str, int, int]] = []
    for archive_path in sorted(unique_paths.values(), key=lambda value: str(value).lower()):
        try:
            stat_result = archive_path.stat()
        except FileNotFoundError:
            continue
        sources.append(
            (
                _archive_relative_source_path(base_dir, archive_path),
                int(stat_result.st_size),
                int(getattr(stat_result, "st_mtime_ns", int(stat_result.st_mtime * 1_000_000_000))),
            )
        )
    return sources


def _update_archive_entry_metadata_row_hash(hasher: "hashlib._Hash", row: Sequence[object]) -> None:
    for value in row:
        hasher.update(str(value).encode("utf-8", errors="replace"))
        hasher.update(b"\x1f")
    hasher.update(b"\x1e")


def _archive_entry_metadata_signature_from_components(
    *,
    sources: Sequence[Tuple[str, int, int]],
    entry_count: int,
    row_hash: str,
) -> str:
    payload = {
        "format": _ARCHIVE_ENTRY_METADATA_SIGNATURE_FORMAT,
        "entry_count": int(entry_count),
        "row_hash": str(row_hash or ""),
        "sources": [[str(path), int(size), int(mtime_ns)] for path, size, mtime_ns in sources],
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8", errors="replace")
    return hashlib.sha256(encoded).hexdigest()


def _archive_entry_metadata_from_entries(
    package_root: Path,
    entries: Sequence[ArchiveEntry],
) -> Tuple[str, List[Tuple[str, int, int]]]:
    base_dir = _archive_base_dir(package_root)
    try:
        resolved_base_dir = base_dir.resolve()
    except OSError:
        resolved_base_dir = base_dir
    pamt_rel_cache: Dict[Path, str] = {}
    source_paths: Dict[str, Path] = {}
    row_hasher = hashlib.sha256()
    entry_count = 0
    for entry in entries:
        pamt_rel_text = pamt_rel_cache.get(entry.pamt_path)
        if pamt_rel_text is None:
            try:
                pamt_rel_text = entry.pamt_path.resolve().relative_to(resolved_base_dir).as_posix()
            except (OSError, ValueError):
                pamt_rel_text = entry.pamt_path.name
            pamt_rel_cache[entry.pamt_path] = pamt_rel_text
        row = (
            entry.path,
            pamt_rel_text,
            int(entry.offset),
            int(entry.comp_size),
            int(entry.orig_size),
            int(entry.flags),
            int(entry.paz_index),
        )
        _update_archive_entry_metadata_row_hash(row_hasher, row)
        for raw_path in (entry.pamt_path, entry.paz_file):
            try:
                normalized_key = os.path.normcase(os.fspath(raw_path)).strip().lower()
            except (OSError, TypeError, ValueError):
                normalized_key = str(raw_path).strip().lower()
            if normalized_key and normalized_key not in source_paths:
                source_paths[normalized_key] = raw_path
        entry_count += 1
    sources = _archive_source_rows_from_paths(base_dir, tuple(source_paths.values()))
    return (
        _archive_entry_metadata_signature_from_components(
            sources=sources,
            entry_count=entry_count,
            row_hash=row_hasher.hexdigest(),
        ),
        sources,
    )


def _archive_source_rows_match_files(base_dir: Path, rows: Sequence[Tuple[str, int, int]]) -> bool:
    for relative_path, expected_size, expected_mtime_ns in rows:
        try:
            source_path = base_dir / str(relative_path)
            stat_result = source_path.stat()
        except (OSError, TypeError, ValueError):
            return False
        actual_size = int(stat_result.st_size)
        actual_mtime_ns = int(getattr(stat_result, "st_mtime_ns", int(stat_result.st_mtime * 1_000_000_000)))
        if actual_size != int(expected_size) or actual_mtime_ns != int(expected_mtime_ns):
            return False
    return True


def _cache_file_source_rows(cache_dir: Path) -> List[Tuple[str, int, int]]:
    rows: List[Tuple[str, int, int]] = []
    if not cache_dir.is_dir():
        return rows
    for path in sorted(cache_dir.glob("*.bin"), key=lambda item: item.name.casefold()):
        try:
            stat_result = path.stat()
        except OSError:
            continue
        rows.append(
            (
                path.name,
                int(stat_result.st_size),
                int(getattr(stat_result, "st_mtime_ns", int(stat_result.st_mtime * 1_000_000_000))),
            )
        )
    return rows


def _cache_file_source_rows_match(cache_dir: Path, rows: Sequence[Tuple[str, int, int]]) -> bool:
    return _cache_file_source_rows(cache_dir) == _normalize_archive_source_rows(rows)


def _write_archive_scan_shard_metadata(
    package_root: Path,
    cache_root: Path,
    *,
    entry_count: int,
    shard_count: int,
    entry_metadata_signature: str,
    entry_metadata_sources: Sequence[Tuple[str, int, int]],
) -> None:
    metadata_path = resolve_archive_scan_shard_metadata_path(package_root, cache_root)
    metadata_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": _ARCHIVE_SCAN_SHARD_METADATA_VERSION,
        "created_at": time.time(),
        "package_root": str(package_root),
        "entry_count": int(entry_count),
        "shard_count": int(shard_count),
        "entry_metadata_signature_format": _ARCHIVE_ENTRY_METADATA_SIGNATURE_FORMAT,
        "entry_metadata_signature": str(entry_metadata_signature or ""),
        "entry_metadata_sources": [list(row) for row in _normalize_archive_source_rows(entry_metadata_sources)],
        "shard_cache_sources": [list(row) for row in _cache_file_source_rows(metadata_path.parent)],
    }
    atomic_write_text(metadata_path, json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n")


def _load_archive_scan_shard_metadata(
    package_root: Path,
    cache_root: Path,
    *,
    entry_count: int,
    shard_count: int,
) -> Optional[Tuple[str, List[Tuple[str, int, int]]]]:
    metadata_path = resolve_archive_scan_shard_metadata_path(package_root, cache_root)
    try:
        data = json.loads(metadata_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, Mapping):
        return None
    if int(data.get("version", 0) or 0) != _ARCHIVE_SCAN_SHARD_METADATA_VERSION:
        return None
    if int(data.get("entry_count", -1) or -1) != int(entry_count):
        return None
    if int(data.get("shard_count", -1) or -1) != int(shard_count):
        return None
    signature = _normalize_archive_entry_metadata_signature(data.get("entry_metadata_signature"))
    sources = _normalize_archive_source_rows(data.get("entry_metadata_sources"))
    shard_sources = _normalize_archive_source_rows(data.get("shard_cache_sources"))
    if not signature or sources is None or shard_sources is None:
        return None
    base_dir = _archive_base_dir(package_root)
    if not _archive_source_rows_match_files(base_dir, sources):
        return None
    if not _cache_file_source_rows_match(metadata_path.parent, shard_sources):
        return None
    return signature, sources


def _archive_scan_shard_metadata_or_build(
    package_root: Path,
    cache_root: Path,
    entries: Sequence[ArchiveEntry],
    *,
    shard_count: int,
    timings: Optional[Dict[str, float]] = None,
) -> Tuple[str, List[Tuple[str, int, int]]]:
    load_started_at = time.perf_counter()
    cached = _load_archive_scan_shard_metadata(
        package_root,
        cache_root,
        entry_count=len(entries),
        shard_count=shard_count,
    )
    if cached is not None:
        _record_timing(timings, "entry_metadata_load_s", load_started_at)
        if timings is not None:
            timings.setdefault("entry_metadata_build_s", 0.0)
        return cached
    build_started_at = time.perf_counter()
    entry_metadata_signature, entry_metadata_sources = _archive_entry_metadata_from_entries(package_root, entries)
    _record_timing(timings, "entry_metadata_build_s", build_started_at)
    if timings is not None:
        timings.setdefault("entry_metadata_load_s", 0.0)
    _write_archive_scan_shard_metadata(
        package_root,
        cache_root,
        entry_count=len(entries),
        shard_count=shard_count,
        entry_metadata_signature=entry_metadata_signature,
        entry_metadata_sources=entry_metadata_sources,
    )
    return entry_metadata_signature, entry_metadata_sources


def _serialize_cache_payload(payload: dict, *, magic: bytes, compress: Optional[bool] = None) -> bytes:
    raw = pickle.dumps(payload, protocol=pickle.HIGHEST_PROTOCOL)
    use_compression = lz4_block is not None if compress is None else bool(compress and lz4_block is not None)
    if use_compression:
        return magic + b"L" + lz4_block.compress(raw, store_size=True)
    return magic + b"R" + raw


def _deserialize_cache_payload(blob: bytes, *, magic: bytes, invalid_message: str) -> dict:
    if not blob.startswith(magic):
        raise ValueError(invalid_message)
    mode = blob[len(magic) : len(magic) + 1]
    payload = blob[len(magic) + 1 :]
    if mode == b"L":
        if lz4_block is None:
            raise ValueError("Compressed cache requires lz4, but python-lz4 is not available.")
        payload = lz4_block.decompress(payload)
    elif mode != b"R":
        raise ValueError("Cache compression mode is not supported.")
    data = pickle.loads(payload)
    if not isinstance(data, dict):
        raise ValueError("Cache payload is invalid.")
    return data


def _deserialize_cache_payload_from_path(
    cache_path: Path,
    *,
    magic: bytes,
    invalid_message: str,
) -> dict:
    with cache_path.open("rb") as handle:
        header = handle.read(len(magic) + 1)
        if len(header) < len(magic) + 1 or not header.startswith(magic):
            raise ValueError(invalid_message)
        mode = header[len(magic) : len(magic) + 1]
        if mode == b"R":
            data = pickle.load(handle)
            if not isinstance(data, dict):
                raise ValueError("Cache payload is invalid.")
            return data
        payload = handle.read()
    return _deserialize_cache_payload(header + payload, magic=magic, invalid_message=invalid_message)


def _write_raw_pickle_cache_payload_to_path(
    cache_path: Path,
    *,
    magic: bytes,
    payload: dict,
) -> None:
    with atomic_binary_writer(cache_path) as handle:
        handle.write(magic)
        handle.write(b"R")
        pickle.dump(payload, handle, protocol=pickle.HIGHEST_PROTOCOL)


def _serialize_archive_scan_cache_payload(payload: dict) -> bytes:
    return _serialize_cache_payload(payload, magic=_ARCHIVE_SCAN_CACHE_MAGIC)


def _serialize_archive_sidecar_cache_payload(payload: dict) -> bytes:
    # Sidecar caches are loaded after the archive browser becomes usable, so
    # faster writes/reads are more valuable than smaller files here.
    return _serialize_cache_payload(payload, magic=_ARCHIVE_SIDECAR_CACHE_MAGIC, compress=False)


def _deserialize_archive_scan_cache_payload(blob: bytes) -> dict:
    return _deserialize_cache_payload(
        blob,
        magic=_ARCHIVE_SCAN_CACHE_MAGIC,
        invalid_message="Archive cache header is not recognized.",
    )


def _deserialize_archive_scan_cache_payload_from_path(cache_path: Path) -> dict:
    return _deserialize_cache_payload_from_path(
        cache_path,
        magic=_ARCHIVE_SCAN_CACHE_MAGIC,
        invalid_message="Archive cache header is not recognized.",
    )


def _deserialize_archive_sidecar_cache_payload(blob: bytes) -> dict:
    return _deserialize_cache_payload(
        blob,
        magic=_ARCHIVE_SIDECAR_CACHE_MAGIC,
        invalid_message="Texture sidecar cache header is not recognized.",
    )


def _deserialize_archive_derived_index_cache_payload_from_path(cache_path: Path) -> dict:
    return _deserialize_cache_payload_from_path(
        cache_path,
        magic=_ARCHIVE_DERIVED_INDEX_CACHE_MAGIC,
        invalid_message="Archive derived index cache header is not recognized.",
    )


def _deserialize_archive_basic_index_cache_payload_from_path(cache_path: Path) -> dict:
    return _deserialize_cache_payload_from_path(
        cache_path,
        magic=_ARCHIVE_BASIC_INDEX_CACHE_MAGIC,
        invalid_message="Archive path lookup cache header is not recognized.",
    )


def _deserialize_archive_scan_shard_cache_payload_from_path(cache_path: Path) -> dict:
    return _deserialize_cache_payload_from_path(
        cache_path,
        magic=_ARCHIVE_SCAN_SHARD_CACHE_MAGIC,
        invalid_message="Archive scan shard cache header is not recognized.",
    )


def _deserialize_archive_basic_index_shard_cache_payload_from_path(cache_path: Path) -> dict:
    return _deserialize_cache_payload_from_path(
        cache_path,
        magic=_ARCHIVE_BASIC_INDEX_SHARD_CACHE_MAGIC,
        invalid_message="Archive path lookup shard cache header is not recognized.",
    )


def _write_archive_sidecar_cache_metadata(
    metadata_path: Path,
    *,
    version: int,
    sources: Sequence[Tuple[str, int, int]],
    entry_count: int,
) -> None:
    payload = {
        "version": int(version),
        "created_at": time.time(),
        "entry_count": int(entry_count),
        "sources": [[relative_path, int(size), int(mtime_ns)] for relative_path, size, mtime_ns in sources],
    }
    metadata_path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(metadata_path, json.dumps(payload, ensure_ascii=False, separators=(",", ":")))


def _read_archive_sidecar_cache_metadata(metadata_path: Path) -> Optional[dict]:
    if not metadata_path.is_file():
        return None
    payload = json.loads(metadata_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("Texture sidecar cache metadata is invalid.")
    return payload


def _archive_entry_cache_signature(package_root: Path, entry: ArchiveEntry) -> Tuple[object, ...]:
    base_dir = _archive_base_dir(package_root)
    paz_path = Path(getattr(entry, "paz_file", ""))
    try:
        paz_stat = paz_path.stat()
        paz_stamp = (
            int(paz_stat.st_size),
            int(getattr(paz_stat, "st_mtime_ns", int(paz_stat.st_mtime * 1_000_000_000))),
        )
    except OSError:
        paz_stamp = (0, 0)
    return (
        str(getattr(entry, "path", "") or "").replace("\\", "/"),
        _archive_relative_source_path(base_dir, Path(getattr(entry, "pamt_path", ""))),
        _archive_relative_source_path(base_dir, paz_path),
        paz_stamp,
        int(getattr(entry, "offset", 0)),
        int(getattr(entry, "comp_size", 0)),
        int(getattr(entry, "orig_size", 0)),
        int(getattr(entry, "flags", 0)),
        int(getattr(entry, "paz_index", 0)),
    )


def archive_item_icon_thumbnail_cache_key(
    package_root: Path,
    icon_paths: Sequence[object],
    source_entry: ArchiveEntry,
    *,
    size: int,
    converter_key: str = "",
) -> str:
    normalized_icon_paths = tuple(
        str(value or "").replace("\\", "/").strip()
        for value in icon_paths
        if str(value or "").strip()
    )
    payload = {
        "version": _ARCHIVE_ITEM_ICON_THUMBNAIL_CACHE_VERSION,
        "icon_paths": normalized_icon_paths,
        "source_entry": _archive_entry_cache_signature(package_root, source_entry),
        "size": max(1, int(size or 120)),
        "converter_key": str(converter_key or ""),
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode("utf-8")).hexdigest()


def _archive_item_icon_thumbnail_manifest_path(cache_dir: Path) -> Path:
    return cache_dir / "manifest.json"


def _archive_item_icon_thumbnail_manifest_cache_key(cache_dir: Path) -> str:
    try:
        return str(cache_dir.expanduser().resolve()).casefold()
    except OSError:
        return str(cache_dir.expanduser()).casefold()


def _read_archive_item_icon_thumbnail_manifest(cache_dir: Path) -> Dict[str, object]:
    manifest_path = _archive_item_icon_thumbnail_manifest_path(cache_dir)
    manifest_cache_key = _archive_item_icon_thumbnail_manifest_cache_key(cache_dir)
    try:
        stat = manifest_path.stat()
    except OSError:
        _ARCHIVE_ITEM_ICON_THUMBNAIL_MANIFEST_CACHE.pop(manifest_cache_key, None)
        return {
            "version": _ARCHIVE_ITEM_ICON_THUMBNAIL_CACHE_VERSION,
            "entries": {},
        }
    manifest_stamp = (
        int(stat.st_size),
        int(getattr(stat, "st_mtime_ns", int(stat.st_mtime * 1_000_000_000))),
    )
    cached = _ARCHIVE_ITEM_ICON_THUMBNAIL_MANIFEST_CACHE.get(manifest_cache_key)
    if cached is not None and cached[0] == manifest_stamp:
        return cached[1]
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except Exception:
        _ARCHIVE_ITEM_ICON_THUMBNAIL_MANIFEST_CACHE.pop(manifest_cache_key, None)
        return {
            "version": _ARCHIVE_ITEM_ICON_THUMBNAIL_CACHE_VERSION,
            "entries": {},
        }
    if not isinstance(manifest, dict) or int(manifest.get("version", 0) or 0) != _ARCHIVE_ITEM_ICON_THUMBNAIL_CACHE_VERSION:
        _ARCHIVE_ITEM_ICON_THUMBNAIL_MANIFEST_CACHE.pop(manifest_cache_key, None)
        return {
            "version": _ARCHIVE_ITEM_ICON_THUMBNAIL_CACHE_VERSION,
            "entries": {},
        }
    if not isinstance(manifest.get("entries"), dict):
        manifest["entries"] = {}
    _ARCHIVE_ITEM_ICON_THUMBNAIL_MANIFEST_CACHE[manifest_cache_key] = (manifest_stamp, manifest)
    return manifest


def _write_archive_item_icon_thumbnail_manifest(cache_dir: Path, manifest: Mapping[str, object]) -> None:
    manifest_path = _archive_item_icon_thumbnail_manifest_path(cache_dir)
    atomic_write_text(manifest_path, json.dumps(dict(manifest), ensure_ascii=False, separators=(",", ":")))
    try:
        stat = manifest_path.stat()
        manifest_stamp = (
            int(stat.st_size),
            int(getattr(stat, "st_mtime_ns", int(stat.st_mtime * 1_000_000_000))),
        )
        _ARCHIVE_ITEM_ICON_THUMBNAIL_MANIFEST_CACHE[
            _archive_item_icon_thumbnail_manifest_cache_key(cache_dir)
        ] = (manifest_stamp, dict(manifest))
    except OSError:
        _ARCHIVE_ITEM_ICON_THUMBNAIL_MANIFEST_CACHE.pop(_archive_item_icon_thumbnail_manifest_cache_key(cache_dir), None)


def load_archive_item_icon_thumbnail_cache(
    package_root: Path,
    cache_root: Path,
    icon_paths: Sequence[object],
    source_entry: ArchiveEntry,
    *,
    size: int,
    converter_key: str = "",
) -> Optional[Tuple[Path, str]]:
    cache_dir = resolve_archive_item_icon_thumbnail_cache_dir(package_root, cache_root)
    cache_key = archive_item_icon_thumbnail_cache_key(
        package_root,
        icon_paths,
        source_entry,
        size=size,
        converter_key=converter_key,
    )
    thumbnail_path = cache_dir / f"{cache_key}.png"
    try:
        if not thumbnail_path.is_file() or thumbnail_path.stat().st_size <= 0:
            return None
    except OSError:
        return None
    with _ARCHIVE_ITEM_ICON_THUMBNAIL_CACHE_LOCK:
        manifest = _read_archive_item_icon_thumbnail_manifest(cache_dir)
        entries = manifest.get("entries")
        row = entries.get(cache_key) if isinstance(entries, dict) else None
        if not isinstance(row, Mapping):
            return None
        if int(row.get("version", 0) or 0) != _ARCHIVE_ITEM_ICON_THUMBNAIL_CACHE_VERSION:
            return None
        if str(row.get("filename", "") or "") != thumbnail_path.name:
            return None
        note = str(row.get("note", "") or "Recovered inventory icon")
    return thumbnail_path, note


def save_archive_item_icon_thumbnail_cache(
    package_root: Path,
    cache_root: Path,
    icon_paths: Sequence[object],
    source_entry: ArchiveEntry,
    thumbnail_path: Path,
    *,
    size: int,
    converter_key: str = "",
    note: str = "",
) -> Path:
    source_path = Path(thumbnail_path)
    if not source_path.is_file():
        raise FileNotFoundError(f"Item icon thumbnail source was not found: {source_path}")
    cache_dir = resolve_archive_item_icon_thumbnail_cache_dir(package_root, cache_root)
    cache_key = archive_item_icon_thumbnail_cache_key(
        package_root,
        icon_paths,
        source_entry,
        size=size,
        converter_key=converter_key,
    )
    cache_dir.mkdir(parents=True, exist_ok=True)
    destination = cache_dir / f"{cache_key}.png"
    atomic_copy_file(source_path, destination)
    with _ARCHIVE_ITEM_ICON_THUMBNAIL_CACHE_LOCK:
        manifest = _read_archive_item_icon_thumbnail_manifest(cache_dir)
        entries = manifest.setdefault("entries", {})
        if not isinstance(entries, dict):
            entries = {}
            manifest["entries"] = entries
        entries[cache_key] = {
            "version": _ARCHIVE_ITEM_ICON_THUMBNAIL_CACHE_VERSION,
            "filename": destination.name,
            "size": max(1, int(size or 120)),
            "converter_key": str(converter_key or ""),
            "icon_paths": [
                str(value or "").replace("\\", "/").strip()
                for value in icon_paths
                if str(value or "").strip()
            ],
            "source_path": str(getattr(source_entry, "path", "") or "").replace("\\", "/"),
            "note": str(note or "Recovered inventory icon"),
            "created_at": time.time(),
            "last_used_at": time.time(),
        }
        _write_archive_item_icon_thumbnail_manifest(cache_dir, manifest)
    prune_archive_cache_root(
        cache_root,
        protected_paths=archive_cache_protected_paths(package_root, cache_root),
    )
    return destination


def _build_archive_entry_cache_signatures(
    package_root: Path,
    entries: Sequence[ArchiveEntry],
) -> Tuple[Tuple[object, ...], ...]:
    return tuple(_archive_entry_cache_signature(package_root, entry) for entry in entries)


def _describe_archive_cache_metadata_mismatch(
    cached_sources: Optional[Sequence[Tuple[str, int, int]]],
    current_sources: Sequence[Tuple[str, int, int]],
    cached_entry_count: int,
    current_entry_count: int,
) -> List[str]:
    reasons: List[str] = []
    if cached_entry_count >= 0 and cached_entry_count != current_entry_count:
        reasons.append(f"entry count changed {cached_entry_count:,}->{current_entry_count:,}")
    if cached_sources is None:
        reasons.append("source metadata missing or invalid")
        return reasons
    if len(cached_sources) != len(current_sources):
        reasons.append(f"source count changed {len(cached_sources):,}->{len(current_sources):,}")
    cached_by_path = {str(row[0]): row for row in cached_sources}
    current_by_path = {str(row[0]): row for row in current_sources}
    added = sorted(set(current_by_path) - set(cached_by_path))
    removed = sorted(set(cached_by_path) - set(current_by_path))
    changed = [
        path
        for path in sorted(set(cached_by_path) & set(current_by_path))
        if cached_by_path[path] != current_by_path[path]
    ]
    if added:
        reasons.append("sources added: " + ", ".join(added[:3]) + (" ..." if len(added) > 3 else ""))
    if removed:
        reasons.append("sources removed: " + ", ".join(removed[:3]) + (" ..." if len(removed) > 3 else ""))
    if changed:
        reasons.append("source stamps changed: " + ", ".join(changed[:3]) + (" ..." if len(changed) > 3 else ""))
    return reasons


def _record_timing(
    timings: Optional[Dict[str, float]],
    key: str,
    started_at: float,
) -> None:
    if timings is None:
        return
    timings[key] = max(0.0, float(time.perf_counter() - started_at))


def _archive_cache_row_for_entry(
    base_dir: Path,
    resolved_base_dir: Path,
    pamt_rel_cache: Dict[Path, str],
    entry: ArchiveEntry,
) -> Tuple[str, str, int, int, int, int, int]:
    pamt_rel_text = pamt_rel_cache.get(entry.pamt_path)
    if pamt_rel_text is None:
        try:
            pamt_rel_text = entry.pamt_path.resolve().relative_to(resolved_base_dir).as_posix()
        except (OSError, ValueError):
            pamt_rel_text = _archive_relative_source_path(base_dir, entry.pamt_path)
        pamt_rel_cache[entry.pamt_path] = pamt_rel_text
    return (
        entry.path,
        pamt_rel_text,
        int(entry.offset),
        int(entry.comp_size),
        int(entry.orig_size),
        int(entry.flags),
        int(entry.paz_index),
    )


def _archive_scan_cache_payload_components(
    package_root: Path,
    entries: Sequence[ArchiveEntry],
    *,
    base_dir: Optional[Path] = None,
) -> Dict[str, object]:
    resolved_base_dir = (base_dir or _archive_base_dir(package_root))
    try:
        resolved_base_dir_for_rows = resolved_base_dir.resolve()
    except OSError:
        resolved_base_dir_for_rows = resolved_base_dir
    pamt_rel_cache: Dict[Path, str] = {}
    pamt_source_paths: Dict[str, Path] = {}
    content_source_paths: Dict[str, Path] = {}
    row_hasher = hashlib.sha256()
    rows: List[Tuple[str, str, int, int, int, int, int]] = []
    for entry in entries:
        row = _archive_cache_row_for_entry(resolved_base_dir, resolved_base_dir_for_rows, pamt_rel_cache, entry)
        rows.append(row)
        _update_archive_entry_metadata_row_hash(row_hasher, row)
        for source_path, target in (
            (entry.pamt_path, pamt_source_paths),
            (entry.pamt_path, content_source_paths),
            (entry.paz_file, content_source_paths),
        ):
            try:
                normalized_key = os.path.normcase(os.fspath(source_path)).strip().lower()
            except (OSError, TypeError, ValueError):
                normalized_key = str(source_path).strip().lower()
            if normalized_key and normalized_key not in target:
                target[normalized_key] = source_path
    row_hash = row_hasher.hexdigest()
    pamt_sources = _archive_source_rows_from_paths(resolved_base_dir, tuple(pamt_source_paths.values()))
    content_sources = _archive_source_rows_from_paths(resolved_base_dir, tuple(content_source_paths.values()))
    entry_count = len(rows)
    entry_list_signature = _archive_entry_metadata_signature_from_components(
        sources=pamt_sources,
        entry_count=entry_count,
        row_hash=row_hash,
    )
    content_signature = _archive_entry_metadata_signature_from_components(
        sources=content_sources,
        entry_count=entry_count,
        row_hash=row_hash,
    )
    return {
        "rows": rows,
        "row_hash": row_hash,
        "entry_count": entry_count,
        "pamt_sources": pamt_sources,
        "content_sources": content_sources,
        "entry_list_signature": entry_list_signature,
        "content_signature": content_signature,
    }


def _decode_archive_scan_cache_rows(
    base_dir: Path,
    raw_rows: object,
    *,
    stop_event: Optional[threading.Event] = None,
    on_progress: Optional[Callable[[int, int, str], None]] = None,
    progress_message: str = "Loading archive cache",
) -> List[ArchiveEntry]:
    if not isinstance(raw_rows, list):
        raise ValueError("Archive cache rows are invalid.")
    total_rows = len(raw_rows)
    update_every = 50_000 if total_rows >= 500_000 else 10_000 if total_rows >= 100_000 else 2_000
    pamt_path_cache: Dict[str, Path] = {}
    paz_path_cache: Dict[Tuple[str, int], Path] = {}
    entries: List[ArchiveEntry] = []
    for index, row in enumerate(raw_rows, start=1):
        raise_if_cancelled(stop_event)
        if not isinstance(row, (list, tuple)) or len(row) != 7:
            raise ValueError("Archive cache row shape is invalid.")
        path, pamt_rel, offset, comp_size, orig_size, flags, paz_index = row
        pamt_rel_text = str(pamt_rel)
        pamt_path = pamt_path_cache.get(pamt_rel_text)
        if pamt_path is None:
            pamt_path = base_dir / pamt_rel_text
            pamt_path_cache[pamt_rel_text] = pamt_path
        paz_key = (pamt_rel_text, int(paz_index))
        paz_path = paz_path_cache.get(paz_key)
        if paz_path is None:
            paz_path = pamt_path.parent / f"{int(paz_index)}.paz"
            paz_path_cache[paz_key] = paz_path
        entries.append(
            ArchiveEntry(
                path=str(path),
                pamt_path=pamt_path,
                paz_file=paz_path,
                offset=int(offset),
                comp_size=int(comp_size),
                orig_size=int(orig_size),
                flags=int(flags),
                paz_index=int(paz_index),
            )
        )
        if on_progress and (index == 1 or index % update_every == 0 or index == total_rows):
            on_progress(index, max(total_rows, 1), f"{progress_message}... {index:,} / {total_rows:,} entries")
    return entries


@dataclass(frozen=True)
class _ArchiveEntryShardGroup:
    relative_pamt_path: str
    pamt_path: Path
    shard_id: str
    start_index: int
    entries: Tuple[ArchiveEntry, ...]
    entry_list_signature: str

    @property
    def entry_count(self) -> int:
        return len(self.entries)


def _archive_entry_shard_groups(
    package_root: Path,
    entries: Sequence[ArchiveEntry],
    *,
    include_signatures: bool = True,
    precomputed_entry_list_signatures: Optional[Mapping[str, str]] = None,
    precomputed_entry_counts: Optional[Mapping[str, int]] = None,
    on_progress: Optional[Callable[[int, int, str], None]] = None,
    stop_event: Optional[threading.Event] = None,
    progress_label: str = "Preparing archive shard metadata",
) -> List[_ArchiveEntryShardGroup]:
    base_dir = _archive_base_dir(package_root)
    try:
        resolved_base_dir = base_dir.resolve()
    except OSError:
        resolved_base_dir = base_dir
    pamt_rel_cache: Dict[Path, str] = {}
    groups_by_rel: OrderedDict[str, List[ArchiveEntry]] = OrderedDict()
    pamt_paths_by_rel: Dict[str, Path] = {}
    total_entries = len(entries)
    update_every = 50_000 if total_entries >= 500_000 else 10_000 if total_entries >= 100_000 else 2_000
    if on_progress is not None:
        on_progress(0 if total_entries > 0 else 1, max(total_entries, 1), f"{progress_label}... 0 / {total_entries:,} entries")
    for index, entry in enumerate(entries, start=1):
        if index == 1 or index % 4096 == 0:
            raise_if_cancelled(stop_event)
        pamt_path = Path(getattr(entry, "pamt_path", ""))
        relative_pamt_path = _archive_relative_source_path_cached(
            base_dir,
            resolved_base_dir,
            pamt_rel_cache,
            pamt_path,
        )
        if not relative_pamt_path:
            relative_pamt_path = pamt_path.name
        groups_by_rel.setdefault(relative_pamt_path, []).append(entry)
        pamt_paths_by_rel.setdefault(relative_pamt_path, pamt_path)
        if on_progress is not None and (index == 1 or index % update_every == 0 or index == total_entries):
            on_progress(index, max(total_entries, 1), f"{progress_label}... {index:,} / {total_entries:,} entries")
    groups: List[_ArchiveEntryShardGroup] = []
    start_index = 0
    total_groups = len(groups_by_rel)
    for group_index, (relative_pamt_path, group_entries_list) in enumerate(groups_by_rel.items(), start=1):
        raise_if_cancelled(stop_event)
        if include_signatures and on_progress is not None and (group_index == 1 or group_index % 20 == 0 or group_index == total_groups):
            on_progress(group_index, max(total_groups, 1), f"Hashing archive shard metadata... {group_index:,} / {total_groups:,} shards")
        group_entries = tuple(group_entries_list)
        entry_list_signature = ""
        if include_signatures:
            cached_signature = ""
            if isinstance(precomputed_entry_list_signatures, Mapping):
                cached_signature = str(precomputed_entry_list_signatures.get(relative_pamt_path, "") or "").strip()
            cached_count = -1
            if isinstance(precomputed_entry_counts, Mapping):
                try:
                    cached_count = int(precomputed_entry_counts.get(relative_pamt_path, -1))
                except (TypeError, ValueError):
                    cached_count = -1
            if cached_signature and cached_count == len(group_entries):
                entry_list_signature = cached_signature
            else:
                components = _archive_scan_cache_payload_components(package_root, group_entries, base_dir=base_dir)
                entry_list_signature = str(components.get("entry_list_signature") or "")
        groups.append(
            _ArchiveEntryShardGroup(
                relative_pamt_path=relative_pamt_path,
                pamt_path=pamt_paths_by_rel[relative_pamt_path],
                shard_id=_archive_scan_shard_id(relative_pamt_path),
                start_index=start_index,
                entries=group_entries,
                entry_list_signature=entry_list_signature,
            )
        )
        start_index += len(group_entries)
    return groups


def _archive_scan_shard_cache_path(cache_dir: Path, relative_pamt_path: str) -> Path:
    return cache_dir / f"{_archive_scan_shard_id(relative_pamt_path)}.bin"


def archive_scan_shard_cache_health(package_root: Path, cache_root: Path, *, deep: bool = False) -> Dict[str, object]:
    cache_dir = resolve_archive_scan_shard_cache_dir(package_root, cache_root)
    report: Dict[str, object] = {
        "status": "unknown",
        "reason": "Archive cache has not been checked.",
        "cache_dir": str(cache_dir),
        "pamt_count": 0,
        "shard_count": 0,
        "missing_count": 0,
        "stale_count": 0,
        "extra_count": 0,
        "stale_reasons": [],
    }
    try:
        base_dir, current_pamt_sources, pamt_files = _collect_archive_scan_sources_and_files(package_root)
    except Exception as exc:
        report.update(
            {
                "status": "unhealthy",
                "reason": f"Could not inspect archive source files: {exc}",
            }
        )
        return report
    if not pamt_files:
        report.update(
            {
                "status": "unhealthy",
                "reason": f"No .pamt files were found under {package_root}.",
            }
        )
        return report

    pamt_source_by_rel = {str(row[0]): row for row in current_pamt_sources}
    pamt_by_rel = {_archive_relative_source_path(base_dir, pamt_path): pamt_path for pamt_path in pamt_files}
    current_shard_ids = {_archive_scan_shard_id(relative_pamt_path) for relative_pamt_path in pamt_by_rel}
    existing_shard_files = tuple(cache_dir.glob("*.bin")) if cache_dir.is_dir() else ()
    report["pamt_count"] = len(pamt_files)
    report["shard_count"] = len(existing_shard_files)
    if not existing_shard_files:
        legacy_paths = [path for path in _candidate_archive_scan_cache_paths(package_root, cache_root) if path.is_file()]
        if legacy_paths:
            report.update(
                {
                    "status": "stale",
                    "reason": (
                        "Archive cache uses an older monolithic format. CDMW will migrate or rebuild it into the "
                        "current shard cache and remove the old cache file."
                    ),
                    "legacy_cache_count": len(legacy_paths),
                    "legacy_cache_paths": [str(path) for path in legacy_paths[:5]],
                }
            )
            return report
        report.update(
            {
                "status": "missing",
                "missing_count": len(pamt_files),
                "reason": "Archive cache has not been built for this Crimson Desert folder yet.",
            }
        )
        return report

    stale_reasons: List[str] = []
    extra_count = 0
    for cache_path in existing_shard_files:
        if cache_path.stem.lower() not in current_shard_ids:
            extra_count += 1
    missing_count = 0
    stale_count = 0
    for relative_pamt_path in sorted(pamt_by_rel):
        current_pamt_source = pamt_source_by_rel.get(relative_pamt_path)
        cache_path = _archive_scan_shard_cache_path(cache_dir, relative_pamt_path)
        if current_pamt_source is None:
            stale_count += 1
            stale_reasons.append(f"{relative_pamt_path}: source metadata missing")
            continue
        if not cache_path.is_file():
            missing_count += 1
            if len(stale_reasons) < 5:
                stale_reasons.append(f"{relative_pamt_path}: cache shard missing")
            continue
        if not deep:
            try:
                cache_stat = cache_path.stat()
                cache_mtime_ns = int(getattr(cache_stat, "st_mtime_ns", int(cache_stat.st_mtime * 1_000_000_000)))
                source_mtime_ns = int(current_pamt_source[2])
            except Exception as exc:
                stale_count += 1
                if len(stale_reasons) < 5:
                    stale_reasons.append(f"{relative_pamt_path}: could not compare timestamps ({exc})")
                continue
            if cache_mtime_ns < source_mtime_ns:
                stale_count += 1
                if len(stale_reasons) < 5:
                    stale_reasons.append(f"{relative_pamt_path}: source file is newer than cache shard")
            continue
        try:
            data = _deserialize_archive_scan_shard_cache_payload_from_path(cache_path)
            if int(data.get("version", 0)) != _ARCHIVE_SCAN_SHARD_CACHE_VERSION:
                raise ValueError("cache format changed")
            cached_relative_path = str(data.get("relative_pamt_path") or "").replace("\\", "/")
            if cached_relative_path != str(relative_pamt_path).replace("\\", "/"):
                raise ValueError("source path changed")
            cached_sources = _normalize_archive_source_rows(data.get("pamt_sources"))
            if cached_sources != [current_pamt_source]:
                raise ValueError("source size or timestamp changed")
        except Exception as exc:
            stale_count += 1
            if len(stale_reasons) < 5:
                stale_reasons.append(f"{relative_pamt_path}: {str(exc).strip() or 'changed'}")

    report["missing_count"] = missing_count
    report["stale_count"] = stale_count
    report["extra_count"] = extra_count
    report["stale_reasons"] = stale_reasons
    if missing_count or stale_count or extra_count:
        pieces: List[str] = []
        if missing_count:
            pieces.append(f"{missing_count:,} missing shard(s)")
        if stale_count:
            pieces.append(f"{stale_count:,} changed shard(s)")
        if extra_count:
            pieces.append(f"{extra_count:,} removed archive shard(s)")
        detail = "; ".join(stale_reasons[:3])
        reason = f"Archive cache is stale: {', '.join(pieces)}."
        if detail:
            reason = f"{reason} {detail}"
        report.update({"status": "stale", "reason": reason})
        return report

    report.update(
        {
            "status": "healthy",
            "reason": f"Cache Status: Healthy. {len(pamt_files):,} archive shard(s) match current source files.",
        }
    )
    return report


def _delete_obsolete_archive_scan_cache_path(cache_path: Path, *, on_log: Optional[Callable[[str], None]] = None, reason: str = "") -> None:
    try:
        cache_path.unlink()
    except FileNotFoundError:
        return
    except OSError as exc:
        if on_log:
            on_log(f"Warning: obsolete archive cache could not be removed: {cache_path}: {exc}")
        return
    if on_log:
        detail = f" ({reason})" if reason else ""
        on_log(f"Removed obsolete archive cache file: {cache_path.name}{detail}")


def _write_archive_scan_shard_cache(
    package_root: Path,
    cache_dir: Path,
    relative_pamt_path: str,
    pamt_path: Path,
    entries: Sequence[ArchiveEntry],
    *,
    shard_entry_signatures_out: Optional[Dict[str, str]] = None,
    shard_entry_counts_out: Optional[Dict[str, int]] = None,
) -> Path:
    cache_dir.mkdir(parents=True, exist_ok=True)
    components = _archive_scan_cache_payload_components(package_root, entries)
    cache_path = _archive_scan_shard_cache_path(cache_dir, relative_pamt_path)
    payload = {
        "version": _ARCHIVE_SCAN_SHARD_CACHE_VERSION,
        "created_at": time.time(),
        "package_root": str(package_root),
        "relative_pamt_path": str(relative_pamt_path),
        "pamt_path": str(pamt_path),
        "pamt_sources": components.get("pamt_sources") or [],
        "content_sources": components.get("content_sources") or [],
        "entry_count": int(components.get("entry_count") or 0),
        "row_hash": str(components.get("row_hash") or ""),
        "entry_list_signature": str(components.get("entry_list_signature") or ""),
        "content_signature": str(components.get("content_signature") or ""),
        "rows": components.get("rows") or [],
    }
    _write_raw_pickle_cache_payload_to_path(
        cache_path,
        magic=_ARCHIVE_SCAN_SHARD_CACHE_MAGIC,
        payload=payload,
    )
    if shard_entry_signatures_out is not None:
        shard_entry_signatures_out[str(relative_pamt_path)] = str(payload.get("entry_list_signature") or "")
    if shard_entry_counts_out is not None:
        shard_entry_counts_out[str(relative_pamt_path)] = int(payload.get("entry_count") or 0)
    return cache_path


def _load_archive_scan_shard_cache(
    package_root: Path,
    cache_path: Path,
    *,
    relative_pamt_path: str,
    pamt_sources: Sequence[Tuple[str, int, int]],
    stop_event: Optional[threading.Event] = None,
) -> Tuple[List[ArchiveEntry], dict]:
    data = _deserialize_archive_scan_shard_cache_payload_from_path(cache_path)
    if int(data.get("version", 0)) != _ARCHIVE_SCAN_SHARD_CACHE_VERSION:
        raise ValueError("format changed")
    cached_relative_path = str(data.get("relative_pamt_path") or "").replace("\\", "/")
    if cached_relative_path != str(relative_pamt_path).replace("\\", "/"):
        raise ValueError("shard path changed")
    cached_sources = _normalize_archive_source_rows(data.get("pamt_sources"))
    if cached_sources != list(pamt_sources):
        raise ValueError("source stamps changed")
    rows = data.get("rows")
    entries = _decode_archive_scan_cache_rows(
        _archive_base_dir(package_root),
        rows,
        stop_event=stop_event,
    )
    cached_count = int(data.get("entry_count", -1))
    if cached_count != len(entries):
        raise ValueError("entry count changed")
    return entries, data


def _scan_archive_pamt_shard(
    pamt_path: Path,
    *,
    shard_scan_func: Optional[Callable[[Path], Optional[Sequence[ArchiveEntry]]]] = None,
    on_log: Optional[Callable[[str], None]] = None,
    on_progress: Optional[Callable[[int, int, str], None]] = None,
    stop_event: Optional[threading.Event] = None,
) -> List[ArchiveEntry]:
    raise_if_cancelled(stop_event)
    if shard_scan_func is not None:
        try:
            native_entries = shard_scan_func(pamt_path)
            if native_entries is not None:
                return list(native_entries)
        except RunCancelled:
            raise
        except Exception as exc:
            if on_log is not None:
                on_log(f"Archive shard native scan failed for {pamt_path.name}; using Python parser: {exc}")
    entries = parse_archive_pamt(pamt_path)
    if on_progress is not None:
        on_progress(len(entries), max(len(entries), 1), f"Parsed archive shard {pamt_path.name}: {len(entries):,} entries")
    return entries


def _full_scan_archive_entries_for_shards(
    package_root: Path,
    *,
    full_scan_func: Optional[Callable[[], Optional[Sequence[ArchiveEntry]]]] = None,
    on_log: Optional[Callable[[str], None]] = None,
    on_progress: Optional[Callable[[int, int, str], None]] = None,
    on_breadcrumb: Optional[Callable[[Mapping[str, object]], None]] = None,
    stop_event: Optional[threading.Event] = None,
) -> Tuple[List[ArchiveEntry], str]:
    if full_scan_func is not None:
        try:
            entries = full_scan_func()
            if entries is not None:
                return list(entries), "native_scan"
        except RunCancelled:
            raise
        except Exception as exc:
            if on_log is not None:
                on_log(f"Native full archive scan failed; using Python parser: {exc}")
    entries = scan_archive_entries(
        package_root,
        on_log=on_log,
        on_progress=on_progress,
        on_breadcrumb=on_breadcrumb,
        stop_event=stop_event,
    )
    return entries, "scan"


def _partition_entries_by_pamt_relative_path(
    package_root: Path,
    entries: Sequence[ArchiveEntry],
    *,
    on_progress: Optional[Callable[[int, int, str], None]] = None,
    stop_event: Optional[threading.Event] = None,
) -> Dict[str, List[ArchiveEntry]]:
    base_dir = _archive_base_dir(package_root)
    try:
        resolved_base_dir = base_dir.resolve()
    except OSError:
        resolved_base_dir = base_dir
    pamt_rel_cache: Dict[Path, str] = {}
    groups: Dict[str, List[ArchiveEntry]] = defaultdict(list)
    total_entries = len(entries)
    update_every = 50_000 if total_entries >= 500_000 else 10_000 if total_entries >= 100_000 else 2_000
    if on_progress is not None:
        on_progress(0 if total_entries > 0 else 1, max(total_entries, 1), f"Preparing archive scan shard cache... 0 / {total_entries:,} entries")
    for index, entry in enumerate(entries, start=1):
        if index == 1 or index % 4096 == 0:
            raise_if_cancelled(stop_event)
        relative_pamt_path = _archive_relative_source_path_cached(
            base_dir,
            resolved_base_dir,
            pamt_rel_cache,
            Path(getattr(entry, "pamt_path", "")),
        )
        groups[relative_pamt_path].append(entry)
        if on_progress is not None and (index == 1 or index % update_every == 0 or index == total_entries):
            on_progress(
                index,
                max(total_entries, 1),
                f"Preparing archive scan shard cache... {index:,} / {total_entries:,} entries",
            )
    return groups


def _write_archive_scan_shards_from_entries(
    package_root: Path,
    cache_root: Path,
    entries: Sequence[ArchiveEntry],
    pamt_files: Optional[Sequence[Path]] = None,
    *,
    stop_event: Optional[threading.Event] = None,
    on_log: Optional[Callable[[str], None]] = None,
    on_progress: Optional[Callable[[int, int, str], None]] = None,
    shard_entry_signatures_out: Optional[Dict[str, str]] = None,
    shard_entry_counts_out: Optional[Dict[str, int]] = None,
) -> Path:
    cache_dir = resolve_archive_scan_shard_cache_dir(package_root, cache_root)
    base_dir = _archive_base_dir(package_root)
    files = list(pamt_files) if pamt_files is not None else discover_pamt_files(package_root)
    grouped_entries = _partition_entries_by_pamt_relative_path(
        package_root,
        entries,
        on_progress=on_progress,
        stop_event=stop_event,
    )
    if on_progress is not None:
        on_progress(0, max(len(files), 1), f"Writing archive scan shard cache... 0 / {len(files):,} shards")
    for shard_index, pamt_path in enumerate(files, start=1):
        raise_if_cancelled(stop_event)
        relative_pamt_path = _archive_relative_source_path(base_dir, pamt_path)
        _write_archive_scan_shard_cache(
            package_root,
            cache_dir,
            relative_pamt_path,
            pamt_path,
            grouped_entries.get(relative_pamt_path, ()),
            shard_entry_signatures_out=shard_entry_signatures_out,
            shard_entry_counts_out=shard_entry_counts_out,
        )
        if on_progress is not None and (shard_index == 1 or shard_index % 5 == 0 or shard_index == len(files)):
            on_progress(
                shard_index,
                max(len(files), 1),
                f"Writing archive scan shard cache... {shard_index:,} / {len(files):,} shards",
            )
    if on_log is not None:
        on_log(f"Archive scan shard cache updated: {cache_dir}")
    return cache_dir


def load_or_update_archive_scan_shards(
    package_root: Path,
    cache_root: Path,
    *,
    force_refresh: bool = False,
    on_log: Optional[Callable[[str], None]] = None,
    on_progress: Optional[Callable[[int, int, str], None]] = None,
    on_breadcrumb: Optional[Callable[[Mapping[str, object]], None]] = None,
    stop_event: Optional[threading.Event] = None,
    timings: Optional[Dict[str, float]] = None,
    metadata_out: Optional[Dict[str, object]] = None,
    full_scan_func: Optional[Callable[[], Optional[Sequence[ArchiveEntry]]]] = None,
    shard_scan_func: Optional[Callable[[Path], Optional[Sequence[ArchiveEntry]]]] = None,
    shard_scan_source: str = "scan",
    full_scan_source: str = "",
) -> Tuple[List[ArchiveEntry], str, Optional[Path]]:
    check_started_at = time.perf_counter()
    cache_root.mkdir(parents=True, exist_ok=True)
    cache_dir = resolve_archive_scan_shard_cache_dir(package_root, cache_root)
    base_dir, current_pamt_sources, pamt_files = _collect_archive_scan_sources_and_files(package_root)
    if not pamt_files:
        raise ValueError(f"No .pamt files were found under {package_root}.")
    pamt_source_by_rel = {str(row[0]): row for row in current_pamt_sources}
    pamt_by_rel = {_archive_relative_source_path(base_dir, pamt_path): pamt_path for pamt_path in pamt_files}
    scan_shard_entry_signatures: Dict[str, str] = {}
    scan_shard_entry_counts: Dict[str, int] = {}

    if force_refresh:
        if on_log is not None:
            on_log("Ignoring archive scan shard cache and performing a full rescan.")
        if timings is not None:
            timings["cache_check_s"] = 0.0
            timings["cache_load_s"] = 0.0
            timings["scan_shard_load_s"] = 0.0
    else:
        existing_shard_files = tuple(cache_dir.glob("*.bin")) if cache_dir.is_dir() else ()
        if not existing_shard_files:
            legacy_metadata: Dict[str, object] = {}
            legacy_entries = load_archive_scan_cache(
                package_root,
                cache_root,
                on_log=on_log,
                on_progress=on_progress,
                stop_event=stop_event,
                metadata_out=legacy_metadata,
            )
            if legacy_entries is not None:
                write_started_at = time.perf_counter()
                _write_archive_scan_shards_from_entries(
                    package_root,
                    cache_root,
                    legacy_entries,
                    pamt_files,
                    stop_event=stop_event,
                    on_log=on_log,
                    on_progress=on_progress,
                    shard_entry_signatures_out=scan_shard_entry_signatures,
                    shard_entry_counts_out=scan_shard_entry_counts,
                )
                _record_timing(timings, "scan_shard_write_s", write_started_at)
                if metadata_out is not None:
                    metadata_out.clear()
                    metadata_out.update(legacy_metadata)
                    metadata_out.update(
                        {
                            "scan_shard_count": len(pamt_files),
                            "scan_shard_loaded_count": len(pamt_files),
                            "scan_shard_rebuilt_count": 0,
                            "scan_shard_stale_count": 0,
                            "scan_shard_entry_signatures": dict(scan_shard_entry_signatures),
                            "scan_shard_entry_counts": dict(scan_shard_entry_counts),
                        }
                    )
                if timings is not None:
                    timings["cache_check_s"] = max(0.0, float(time.perf_counter() - check_started_at))
                    timings.setdefault("cache_load_s", 0.0)
                    timings.setdefault("archive_scan_s", 0.0)
                    timings.setdefault("cache_write_s", float(timings.get("scan_shard_write_s", 0.0) or 0.0))
                    timings.setdefault("scan_shard_load_s", 0.0)
                    timings.setdefault("scan_shard_rescan_s", 0.0)
                for legacy_cache_path in _candidate_archive_scan_cache_paths(package_root, cache_root):
                    _delete_obsolete_archive_scan_cache_path(
                        legacy_cache_path,
                        on_log=on_log,
                        reason="migrated to archive scan shard cache",
                    )
                return legacy_entries, "cache", cache_dir

        current_shard_ids = {_archive_scan_shard_id(relative_pamt_path) for relative_pamt_path in pamt_by_rel}
        for cache_path in existing_shard_files:
            if cache_path.stem.lower() in current_shard_ids:
                continue
            removed_label = cache_path.stem
            try:
                data = _deserialize_archive_scan_shard_cache_payload_from_path(cache_path)
                removed_label = str(data.get("relative_pamt_path") or removed_label)
            except Exception:
                pass
            if on_log is not None:
                on_log(f"Archive cache shard stale: {removed_label} removed")
            try:
                cache_path.unlink()
            except OSError:
                pass

        loaded_entries_by_rel: Dict[str, List[ArchiveEntry]] = {}
        stale_rels: List[str] = []
        load_started_at = time.perf_counter()
        if on_progress is not None:
            on_progress(0, len(pamt_files), f"Checking archive scan shards... 0 / {len(pamt_files):,}")
        for index, pamt_path in enumerate(pamt_files, start=1):
            raise_if_cancelled(stop_event)
            relative_pamt_path = _archive_relative_source_path(base_dir, pamt_path)
            cache_path = _archive_scan_shard_cache_path(cache_dir, relative_pamt_path)
            current_pamt_source = pamt_source_by_rel.get(relative_pamt_path)
            if current_pamt_source is None:
                stale_rels.append(relative_pamt_path)
                if on_log is not None:
                    on_log(f"Archive cache shard stale: {relative_pamt_path} source metadata missing")
                continue
            if not cache_path.is_file():
                stale_rels.append(relative_pamt_path)
                if on_log is not None:
                    on_log(f"Archive cache shard stale: {relative_pamt_path} added")
                continue
            try:
                shard_entries, _shard_data = _load_archive_scan_shard_cache(
                    package_root,
                    cache_path,
                    relative_pamt_path=relative_pamt_path,
                    pamt_sources=(current_pamt_source,),
                    stop_event=stop_event,
                )
                loaded_entries_by_rel[relative_pamt_path] = shard_entries
                scan_shard_entry_signatures[relative_pamt_path] = str(_shard_data.get("entry_list_signature") or "")
                scan_shard_entry_counts[relative_pamt_path] = int(_shard_data.get("entry_count") or len(shard_entries))
            except Exception as exc:
                stale_rels.append(relative_pamt_path)
                reason = str(exc).strip() or "changed"
                if reason == "source stamps changed":
                    reason = "source stamps changed"
                if on_log is not None:
                    on_log(f"Archive cache shard stale: {relative_pamt_path} {reason}")
            if on_progress is not None and (index == 1 or index % 20 == 0 or index == len(pamt_files)):
                on_progress(index, len(pamt_files), f"Checking archive scan shards... {index:,} / {len(pamt_files):,}")
        _record_timing(timings, "scan_shard_load_s", load_started_at)
        if timings is not None:
            timings["cache_check_s"] = max(0.0, float(time.perf_counter() - check_started_at))
            timings["cache_load_s"] = float(timings.get("scan_shard_load_s", 0.0) or 0.0)

        stale_threshold = max(8, int(len(pamt_files) * 0.30))
        if not stale_rels:
            entries: List[ArchiveEntry] = []
            for pamt_path in pamt_files:
                relative_pamt_path = _archive_relative_source_path(base_dir, pamt_path)
                entries.extend(loaded_entries_by_rel.get(relative_pamt_path, ()))
            entry_metadata_signature, entry_metadata_sources = _archive_scan_shard_metadata_or_build(
                package_root,
                cache_root,
                entries,
                shard_count=len(pamt_files),
                timings=timings,
            )
            if metadata_out is not None:
                metadata_out.clear()
                metadata_out.update(
                    {
                        "entry_count": len(entries),
                        "entry_metadata_signature_format": _ARCHIVE_ENTRY_METADATA_SIGNATURE_FORMAT,
                        "entry_metadata_signature": entry_metadata_signature,
                        "entry_metadata_sources": entry_metadata_sources,
                        "scan_shard_count": len(pamt_files),
                        "scan_shard_loaded_count": len(pamt_files),
                        "scan_shard_rebuilt_count": 0,
                        "scan_shard_stale_count": 0,
                        "scan_shard_entry_signatures": dict(scan_shard_entry_signatures),
                        "scan_shard_entry_counts": dict(scan_shard_entry_counts),
                    }
                )
            if timings is not None:
                timings.setdefault("archive_scan_s", 0.0)
                timings.setdefault("cache_write_s", 0.0)
                timings.setdefault("scan_shard_rescan_s", 0.0)
                timings.setdefault("scan_shard_write_s", 0.0)
            if on_log is not None:
                on_log(f"Loaded {len(entries):,} archive entries from {len(pamt_files):,} scan shard cache(s).")
            return entries, "cache", cache_dir

        if len(stale_rels) <= stale_threshold:
            rescan_started_at = time.perf_counter()
            rebuilt_entries_by_rel: Dict[str, List[ArchiveEntry]] = {}
            for stale_index, relative_pamt_path in enumerate(stale_rels, start=1):
                raise_if_cancelled(stop_event)
                pamt_path = pamt_by_rel[relative_pamt_path]
                if on_log is not None:
                    on_log(f"[{stale_index}/{len(stale_rels)}] Rebuilding archive cache shard {relative_pamt_path}...")
                if on_progress is not None:
                    on_progress(
                        stale_index - 1,
                        len(stale_rels),
                        f"Rebuilding archive scan shard {stale_index:,} / {len(stale_rels):,}: {relative_pamt_path}",
                    )
                rebuilt_entries_by_rel[relative_pamt_path] = _scan_archive_pamt_shard(
                    pamt_path,
                    shard_scan_func=shard_scan_func,
                    on_log=on_log,
                    on_progress=None,
                    stop_event=stop_event,
                )
            _record_timing(timings, "scan_shard_rescan_s", rescan_started_at)
            if timings is not None:
                timings["archive_scan_s"] = float(timings.get("scan_shard_rescan_s", 0.0) or 0.0)
            write_started_at = time.perf_counter()
            for relative_pamt_path, shard_entries in rebuilt_entries_by_rel.items():
                _write_archive_scan_shard_cache(
                    package_root,
                    cache_dir,
                    relative_pamt_path,
                    pamt_by_rel[relative_pamt_path],
                    shard_entries,
                    shard_entry_signatures_out=scan_shard_entry_signatures,
                    shard_entry_counts_out=scan_shard_entry_counts,
                )
            _record_timing(timings, "scan_shard_write_s", write_started_at)
            if timings is not None:
                timings["cache_write_s"] = float(timings.get("scan_shard_write_s", 0.0) or 0.0)
            loaded_entries_by_rel.update(rebuilt_entries_by_rel)
            entries = []
            for pamt_path in pamt_files:
                relative_pamt_path = _archive_relative_source_path(base_dir, pamt_path)
                entries.extend(loaded_entries_by_rel.get(relative_pamt_path, ()))
            source = "cache+native_scan" if str(shard_scan_source or "").strip() == "native_scan" else "cache+scan"
            entry_metadata_signature, entry_metadata_sources = _archive_scan_shard_metadata_or_build(
                package_root,
                cache_root,
                entries,
                shard_count=len(pamt_files),
                timings=timings,
            )
            if metadata_out is not None:
                metadata_out.clear()
                metadata_out.update(
                    {
                        "entry_count": len(entries),
                        "entry_metadata_signature_format": _ARCHIVE_ENTRY_METADATA_SIGNATURE_FORMAT,
                        "entry_metadata_signature": entry_metadata_signature,
                        "entry_metadata_sources": entry_metadata_sources,
                        "scan_shard_count": len(pamt_files),
                        "scan_shard_loaded_count": len(pamt_files) - len(stale_rels),
                        "scan_shard_rebuilt_count": len(stale_rels),
                        "scan_shard_stale_count": len(stale_rels),
                        "scan_shard_entry_signatures": dict(scan_shard_entry_signatures),
                        "scan_shard_entry_counts": dict(scan_shard_entry_counts),
                    }
                )
            if on_log is not None:
                on_log(
                    "Archive scan shard cache updated: "
                    f"{len(stale_rels):,} rebuilt, {len(pamt_files) - len(stale_rels):,} reused."
                )
            return entries, source, cache_dir

        if on_log is not None:
            on_log(
                "Many archive scan shards stale; using one full scan and repartitioning cache "
                f"({len(stale_rels):,}/{len(pamt_files):,})."
            )

    scan_started_at = time.perf_counter()
    entries, actual_source = _full_scan_archive_entries_for_shards(
        package_root,
        full_scan_func=full_scan_func,
        on_log=on_log,
        on_progress=on_progress,
        on_breadcrumb=on_breadcrumb,
        stop_event=stop_event,
    )
    if full_scan_source:
        actual_source = full_scan_source if actual_source == "native_scan" else actual_source
    _record_timing(timings, "archive_scan_s", scan_started_at)
    write_started_at = time.perf_counter()
    try:
        _write_archive_scan_shards_from_entries(
            package_root,
            cache_root,
            entries,
            pamt_files,
            stop_event=stop_event,
            on_log=on_log,
            on_progress=on_progress,
            shard_entry_signatures_out=scan_shard_entry_signatures,
            shard_entry_counts_out=scan_shard_entry_counts,
        )
        _record_timing(timings, "scan_shard_write_s", write_started_at)
        if timings is not None:
            timings["cache_write_s"] = float(timings.get("scan_shard_write_s", 0.0) or 0.0)
    except Exception as exc:
        if on_log is not None:
            on_log(f"Warning: archive scan shard cache could not be written: {exc}")
        if timings is not None:
            timings.setdefault("cache_write_s", 0.0)
            timings.setdefault("scan_shard_write_s", 0.0)
    entry_metadata_signature, entry_metadata_sources = _archive_scan_shard_metadata_or_build(
        package_root,
        cache_root,
        entries,
        shard_count=len(pamt_files),
        timings=timings,
    )
    if metadata_out is not None:
        metadata_out.clear()
        metadata_out.update(
            {
                "entry_count": len(entries),
                "entry_metadata_signature_format": _ARCHIVE_ENTRY_METADATA_SIGNATURE_FORMAT,
                "entry_metadata_signature": entry_metadata_signature,
                "entry_metadata_sources": entry_metadata_sources,
                "scan_shard_count": len(pamt_files),
                "scan_shard_loaded_count": 0,
                "scan_shard_rebuilt_count": len(pamt_files),
                "scan_shard_stale_count": len(pamt_files),
                "scan_shard_entry_signatures": dict(scan_shard_entry_signatures),
                "scan_shard_entry_counts": dict(scan_shard_entry_counts),
            }
        )
    if timings is not None:
        timings.setdefault("cache_check_s", max(0.0, float(time.perf_counter() - check_started_at)))
        timings.setdefault("cache_load_s", 0.0)
        timings.setdefault("scan_shard_load_s", 0.0)
        timings.setdefault("scan_shard_rescan_s", float(timings.get("archive_scan_s", 0.0) or 0.0))
    prune_report = prune_archive_cache_root(
        cache_root,
        protected_paths=archive_cache_protected_paths(package_root, cache_root),
    )
    if on_log is not None and prune_report.get("removed_files"):
        on_log(
            "Archive cache pruned: "
            f"{prune_report.get('removed_files', 0)} files, {format_byte_size(int(prune_report.get('removed_bytes', 0) or 0))}."
        )
    return entries, actual_source, cache_dir


def save_archive_scan_cache(
    package_root: Path,
    cache_root: Path,
    entries: Sequence[ArchiveEntry],
    *,
    on_log: Optional[Callable[[str], None]] = None,
    on_progress: Optional[Callable[[int, int, str], None]] = None,
    stop_event: Optional[threading.Event] = None,
    timings: Optional[Dict[str, float]] = None,
    metadata_out: Optional[Dict[str, object]] = None,
) -> Path:
    started_at = time.perf_counter()
    cache_root.mkdir(parents=True, exist_ok=True)
    cache_path = resolve_archive_scan_cache_path(package_root, cache_root)
    base_dir, sources = _collect_archive_scan_sources(package_root)
    resolved_base_dir = base_dir.resolve()
    pamt_rel_cache: Dict[Path, str] = {}
    entry_metadata_source_paths: Dict[str, Path] = {}
    entry_metadata_row_hasher = hashlib.sha256()

    rows = []
    total_entries = len(entries)
    update_every = 50_000 if total_entries >= 500_000 else 10_000 if total_entries >= 100_000 else 2_000
    for index, entry in enumerate(entries, start=1):
        raise_if_cancelled(stop_event)
        pamt_rel_text = pamt_rel_cache.get(entry.pamt_path)
        if pamt_rel_text is None:
            try:
                pamt_rel_text = entry.pamt_path.resolve().relative_to(resolved_base_dir).as_posix()
            except (OSError, ValueError):
                pamt_rel_text = entry.pamt_path.name
            pamt_rel_cache[entry.pamt_path] = pamt_rel_text
        row = (
            entry.path,
            pamt_rel_text,
            int(entry.offset),
            int(entry.comp_size),
            int(entry.orig_size),
            int(entry.flags),
            int(entry.paz_index),
        )
        rows.append(row)
        _update_archive_entry_metadata_row_hash(entry_metadata_row_hasher, row)
        for raw_path in (entry.pamt_path, entry.paz_file):
            try:
                normalized_key = os.path.normcase(os.fspath(raw_path)).strip().lower()
            except (OSError, TypeError, ValueError):
                normalized_key = str(raw_path).strip().lower()
            if normalized_key and normalized_key not in entry_metadata_source_paths:
                entry_metadata_source_paths[normalized_key] = raw_path
        if on_progress and (index == 1 or index % update_every == 0 or index == total_entries):
            on_progress(index, max(total_entries, 1), f"Building archive cache... {index:,} / {total_entries:,} entries")

    entry_metadata_sources = _archive_source_rows_from_paths(base_dir, tuple(entry_metadata_source_paths.values()))
    entry_metadata_signature = _archive_entry_metadata_signature_from_components(
        sources=entry_metadata_sources,
        entry_count=len(rows),
        row_hash=entry_metadata_row_hasher.hexdigest(),
    )
    payload = {
        "version": _ARCHIVE_SCAN_CACHE_VERSION,
        "package_root": str(package_root),
        "created_at": time.time(),
        "sources": sources,
        "entry_count": len(rows),
        "entry_metadata_signature_format": _ARCHIVE_ENTRY_METADATA_SIGNATURE_FORMAT,
        "entry_metadata_signature": entry_metadata_signature,
        "entry_metadata_sources": entry_metadata_sources,
        "rows": rows,
    }
    if metadata_out is not None:
        metadata_out.clear()
        metadata_out.update(
            {
                "entry_count": len(rows),
                "entry_metadata_signature_format": _ARCHIVE_ENTRY_METADATA_SIGNATURE_FORMAT,
                "entry_metadata_signature": entry_metadata_signature,
                "entry_metadata_sources": entry_metadata_sources,
            }
        )
    if on_log:
        on_log(f"Writing archive cache: {cache_path.name}")
    if on_progress:
        on_progress(0, 0, "Compressing archive cache...")
    blob = _serialize_archive_scan_cache_payload(payload)
    atomic_write_bytes(cache_path, blob)
    if on_progress:
        on_progress(1, 1, "Archive index cache written; preparing browser indexes...")
    if on_log:
        on_log(f"Archive cache updated: {cache_path}")
    prune_report = prune_archive_cache_root(
        cache_root,
        protected_paths=archive_cache_protected_paths(package_root, cache_root),
    )
    if on_log and prune_report.get("removed_files"):
        on_log(
            "Archive cache pruned: "
            f"{prune_report.get('removed_files', 0)} files, {format_byte_size(int(prune_report.get('removed_bytes', 0) or 0))}."
        )
    _record_timing(timings, "cache_write_s", started_at)
    return cache_path


def load_archive_scan_cache(
    package_root: Path,
    cache_root: Path,
    *,
    on_log: Optional[Callable[[str], None]] = None,
    on_progress: Optional[Callable[[int, int, str], None]] = None,
    stop_event: Optional[threading.Event] = None,
    timings: Optional[Dict[str, float]] = None,
    metadata_out: Optional[Dict[str, object]] = None,
) -> Optional[List[ArchiveEntry]]:
    check_started_at = time.perf_counter()
    candidate_paths = _candidate_archive_scan_cache_paths(package_root, cache_root)
    preferred_cache_path = candidate_paths[0]
    existing_candidate_paths = [candidate for candidate in candidate_paths if candidate.exists()]
    if not existing_candidate_paths:
        if timings is not None:
            timings.setdefault("cache_check_s", max(0.0, float(time.perf_counter() - check_started_at)))
            timings.setdefault("cache_load_s", 0.0)
        return None

    if on_progress:
        on_progress(0, 0, "Checking archive cache...")
    try:
        base_dir, current_sources = _collect_archive_scan_sources(package_root)
    except Exception as exc:
        if on_log:
            on_log(f"Archive cache check failed; will rescan instead: {exc}")
        if timings is not None:
            timings.setdefault("cache_check_s", max(0.0, float(time.perf_counter() - check_started_at)))
            timings.setdefault("cache_load_s", 0.0)
        return None

    last_failure_message = "Archive cache is unavailable; performing a full rescan."
    for cache_path in existing_candidate_paths:
        cache_label = "archive cache" if cache_path == preferred_cache_path else f"legacy archive cache at {cache_path.parent}"
        if cache_path != preferred_cache_path and on_log:
            on_log(f"Trying {cache_label}: {cache_path.name}")

        try:
            data = _deserialize_archive_scan_cache_payload_from_path(cache_path)
        except Exception as exc:
            last_failure_message = f"{cache_label.capitalize()} could not be read; will try another cache or rescan: {exc}"
            if on_log:
                on_log(last_failure_message)
            _delete_obsolete_archive_scan_cache_path(cache_path, on_log=on_log, reason="unreadable old format")
            continue

        if int(data.get("version", 0)) not in _ARCHIVE_SCAN_CACHE_SUPPORTED_VERSIONS:
            last_failure_message = f"{cache_label.capitalize()} format changed; will try another cache or rescan."
            if on_log:
                on_log(last_failure_message)
            _delete_obsolete_archive_scan_cache_path(cache_path, on_log=on_log, reason="unsupported old format")
            continue

        cached_sources = data.get("sources")
        if not isinstance(cached_sources, list):
            last_failure_message = f"{cache_label.capitalize()} is missing source metadata; will try another cache or rescan."
            if on_log:
                on_log(last_failure_message)
            _delete_obsolete_archive_scan_cache_path(cache_path, on_log=on_log, reason="missing old cache metadata")
            continue

        if cached_sources != current_sources:
            reasons = _describe_archive_cache_metadata_mismatch(
                _normalize_archive_source_rows(cached_sources),
                current_sources,
                int(data.get("entry_count", -1) or -1),
                int(data.get("entry_count", -1) or -1),
            )
            last_failure_message = (
                f"{cache_label.capitalize()} stale: "
                + "; ".join(reasons or ["archive indexes changed since the last scan"])
            )
            if on_log:
                on_log(last_failure_message)
            _delete_obsolete_archive_scan_cache_path(cache_path, on_log=on_log, reason="stale old format")
            continue

        raw_rows = data.get("rows")
        if not isinstance(raw_rows, list):
            last_failure_message = f"{cache_label.capitalize()} is missing entry rows; will try another cache or rescan."
            if on_log:
                on_log(last_failure_message)
            _delete_obsolete_archive_scan_cache_path(cache_path, on_log=on_log, reason="invalid old cache rows")
            continue

        total_rows = len(raw_rows)
        if on_log:
            on_log(f"Loading {total_rows:,} archive entries from cache...")
        cached_entry_metadata_signature = _normalize_archive_entry_metadata_signature(
            data.get("entry_metadata_signature")
        )
        cached_entry_metadata_sources = _normalize_archive_source_rows(
            data.get("entry_metadata_sources")
        )
        try:
            cached_entry_count = int(data.get("entry_count", total_rows))
        except (TypeError, ValueError):
            cached_entry_count = -1
        use_cached_entry_metadata = bool(
            cached_entry_count == total_rows
            and cached_entry_metadata_signature
            and cached_entry_metadata_sources is not None
            and _archive_source_rows_match_files(base_dir, cached_entry_metadata_sources)
        )
        if total_rows == 0:
            empty_signature = cached_entry_metadata_signature or _archive_entry_metadata_signature_from_components(
                sources=(),
                entry_count=0,
                row_hash=hashlib.sha256().hexdigest(),
            )
            if metadata_out is not None:
                metadata_out.clear()
                metadata_out.update(
                    {
                        "entry_count": 0,
                        "entry_metadata_signature_format": _ARCHIVE_ENTRY_METADATA_SIGNATURE_FORMAT,
                        "entry_metadata_signature": empty_signature,
                        "entry_metadata_sources": cached_entry_metadata_sources or [],
                    }
                )
            if on_progress:
                on_progress(1, 1, "Archive cache loaded. No entries were cached.")
            if timings is not None:
                timings["cache_check_s"] = max(0.0, float(time.perf_counter() - check_started_at))
                timings["cache_load_s"] = 0.0
            return []

        try:
            if timings is not None:
                timings["cache_check_s"] = max(0.0, float(time.perf_counter() - check_started_at))
            load_started_at = time.perf_counter()
            update_every = 50_000 if total_rows >= 500_000 else 10_000 if total_rows >= 100_000 else 2_000
            pamt_path_cache: Dict[str, Path] = {}
            paz_path_cache: Dict[Tuple[str, int], Path] = {}
            entry_metadata_source_paths: Dict[str, Path] = {}
            entry_metadata_row_hasher = hashlib.sha256() if not use_cached_entry_metadata else None
            entries: List[ArchiveEntry] = []
            for index, row in enumerate(raw_rows, start=1):
                raise_if_cancelled(stop_event)
                if not isinstance(row, tuple) or len(row) != 7:
                    raise ValueError("Archive cache row shape is invalid.")
                path, pamt_rel, offset, comp_size, orig_size, flags, paz_index = row
                if entry_metadata_row_hasher is not None:
                    _update_archive_entry_metadata_row_hash(entry_metadata_row_hasher, row)
                pamt_rel_text = str(pamt_rel)
                pamt_path = pamt_path_cache.get(pamt_rel_text)
                if pamt_path is None:
                    pamt_path = base_dir / pamt_rel_text
                    pamt_path_cache[pamt_rel_text] = pamt_path
                paz_key = (pamt_rel_text, int(paz_index))
                paz_path = paz_path_cache.get(paz_key)
                if paz_path is None:
                    paz_path = pamt_path.parent / f"{int(paz_index)}.paz"
                    paz_path_cache[paz_key] = paz_path
                if not use_cached_entry_metadata:
                    for source_path in (pamt_path, paz_path):
                        try:
                            normalized_key = os.path.normcase(os.fspath(source_path)).strip().lower()
                        except (OSError, TypeError, ValueError):
                            normalized_key = str(source_path).strip().lower()
                        if normalized_key and normalized_key not in entry_metadata_source_paths:
                            entry_metadata_source_paths[normalized_key] = source_path
                entries.append(
                    ArchiveEntry(
                        path=str(path),
                        pamt_path=pamt_path,
                        paz_file=paz_path,
                        offset=int(offset),
                        comp_size=int(comp_size),
                        orig_size=int(orig_size),
                        flags=int(flags),
                        paz_index=int(paz_index),
                    )
                )
                if on_progress and (index == 1 or index % update_every == 0 or index == total_rows):
                    on_progress(index, total_rows, f"Loading archive cache... {index:,} / {total_rows:,} entries")
            if use_cached_entry_metadata:
                entry_metadata_sources = list(cached_entry_metadata_sources or [])
                entry_metadata_signature = cached_entry_metadata_signature
            else:
                entry_metadata_sources = _archive_source_rows_from_paths(base_dir, tuple(entry_metadata_source_paths.values()))
                row_hash = (
                    entry_metadata_row_hasher.hexdigest()
                    if entry_metadata_row_hasher is not None
                    else hashlib.sha256().hexdigest()
                )
                entry_metadata_signature = _archive_entry_metadata_signature_from_components(
                    sources=entry_metadata_sources,
                    entry_count=len(entries),
                    row_hash=row_hash,
                )
                if cached_entry_metadata_signature and cached_entry_metadata_signature != entry_metadata_signature and on_log:
                    on_log("Archive cache compact entry metadata was stale; refreshed it from cached rows.")
            if metadata_out is not None:
                metadata_out.clear()
                metadata_out.update(
                    {
                        "entry_count": len(entries),
                        "entry_metadata_signature_format": _ARCHIVE_ENTRY_METADATA_SIGNATURE_FORMAT,
                        "entry_metadata_signature": entry_metadata_signature,
                        "entry_metadata_sources": entry_metadata_sources,
                    }
                )
            _record_timing(timings, "cache_load_s", load_started_at)
        except Exception as exc:
            last_failure_message = f"{cache_label.capitalize()} could not be loaded; will try another cache or rescan: {exc}"
            if on_log:
                on_log(last_failure_message)
            continue

        if cache_path != preferred_cache_path:
            try:
                preferred_cache_path.parent.mkdir(parents=True, exist_ok=True)
                if not preferred_cache_path.exists():
                    shutil.copy2(cache_path, preferred_cache_path)
                if on_log:
                    on_log(f"Migrated archive cache to preferred location: {preferred_cache_path}")
            except Exception as exc:
                if on_log:
                    on_log(f"Loaded archive cache from legacy location, but migration failed: {exc}")

        if on_log:
            on_log(f"Loaded {len(entries):,} archive entries from cache.")
        return entries

    if on_log:
        on_log(last_failure_message)
    if timings is not None:
        timings.setdefault("cache_check_s", max(0.0, float(time.perf_counter() - check_started_at)))
        timings.setdefault("cache_load_s", 0.0)
    return None


def scan_archive_entries_cached(
    package_root: Path,
    cache_root: Path,
    *,
    force_refresh: bool = False,
    on_log: Optional[Callable[[str], None]] = None,
    on_progress: Optional[Callable[[int, int, str], None]] = None,
    on_breadcrumb: Optional[Callable[[Mapping[str, object]], None]] = None,
    stop_event: Optional[threading.Event] = None,
) -> Tuple[List[ArchiveEntry], str, Optional[Path], Dict[str, float]]:
    started_at = time.perf_counter()
    timings: Dict[str, float] = {}
    entries, source, cache_path = load_or_update_archive_scan_shards(
        package_root,
        cache_root,
        force_refresh=force_refresh,
        on_log=on_log,
        on_progress=on_progress,
        on_breadcrumb=on_breadcrumb,
        stop_event=stop_event,
        timings=timings,
    )
    timings["total_s"] = max(0.0, float(time.perf_counter() - started_at))
    return entries, source, cache_path, timings


def _scan_archive_entries_cached_legacy(
    package_root: Path,
    cache_root: Path,
    *,
    force_refresh: bool = False,
    on_log: Optional[Callable[[str], None]] = None,
    on_progress: Optional[Callable[[int, int, str], None]] = None,
    on_breadcrumb: Optional[Callable[[Mapping[str, object]], None]] = None,
    stop_event: Optional[threading.Event] = None,
) -> Tuple[List[ArchiveEntry], str, Optional[Path], Dict[str, float]]:
    started_at = time.perf_counter()
    timings: Dict[str, float] = {}
    cache_path: Optional[Path] = resolve_archive_scan_cache_path(package_root, cache_root)
    scan_started_at = time.perf_counter()
    entries = scan_archive_entries(
        package_root,
        on_log=on_log,
        on_progress=on_progress,
        on_breadcrumb=on_breadcrumb,
        stop_event=stop_event,
    )
    _record_timing(timings, "archive_scan_s", scan_started_at)
    try:
        cache_path = save_archive_scan_cache(
            package_root,
            cache_root,
            entries,
            on_log=on_log,
            on_progress=on_progress,
            stop_event=stop_event,
            timings=timings,
        )
    except Exception as exc:
        if on_log:
            on_log(f"Warning: archive cache could not be written: {exc}")
        cache_path = None
        timings.setdefault("cache_write_s", 0.0)
    timings["total_s"] = max(0.0, float(time.perf_counter() - started_at))
    return entries, "scan", cache_path, timings
