from __future__ import annotations

import json
import os
import shutil
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Mapping, Optional, Sequence, Tuple


NATIVE_PREVIEW_PACKAGE_CACHE_SCHEMA = 1
NATIVE_PREVIEW_PACKAGE_CACHE_MODES = {"off", "balanced", "aggressive"}
BALANCED_NATIVE_PREVIEW_PACKAGE_MAX_BYTES = 512 * 1024 * 1024
BALANCED_NATIVE_PREVIEW_PACKAGE_TARGET_BYTES = 384 * 1024 * 1024
AGGRESSIVE_NATIVE_PREVIEW_PACKAGE_MAX_BYTES = 2 * 1024 * 1024 * 1024
AGGRESSIVE_NATIVE_PREVIEW_PACKAGE_TARGET_BYTES = 1536 * 1024 * 1024


@dataclass(frozen=True)
class NativePreviewPackageCacheHit:
    cache_key: str
    entry_dir: Path
    package_dir: Path
    metadata: Mapping[str, object]


def clamp_native_preview_package_cache_mode(mode: object) -> str:
    normalized = str(mode or "balanced").strip().lower()
    return normalized if normalized in NATIVE_PREVIEW_PACKAGE_CACHE_MODES else "balanced"


def native_preview_package_cache_budget(mode: object) -> Tuple[int, int]:
    normalized = clamp_native_preview_package_cache_mode(mode)
    if normalized == "aggressive":
        return AGGRESSIVE_NATIVE_PREVIEW_PACKAGE_MAX_BYTES, AGGRESSIVE_NATIVE_PREVIEW_PACKAGE_TARGET_BYTES
    if normalized == "balanced":
        return BALANCED_NATIVE_PREVIEW_PACKAGE_MAX_BYTES, BALANCED_NATIVE_PREVIEW_PACKAGE_TARGET_BYTES
    return 0, 0


def native_preview_package_prefetch_limit(mode: object) -> int:
    return 2 if clamp_native_preview_package_cache_mode(mode) == "aggressive" else 0


def native_preview_package_cache_packages_root(cache_root: Path) -> Path:
    return Path(cache_root) / "packages"


def native_preview_package_cache_entry_dir(cache_root: Path, cache_key: str) -> Path:
    return native_preview_package_cache_packages_root(cache_root) / str(cache_key)


def is_temp_native_preview_package_path(path_value: object) -> bool:
    try:
        path = Path(str(path_value or ""))
    except (OSError, ValueError):
        return False
    return path.name == "package" and path.parent.name.startswith("cdmw_preview_core_")


def is_durable_native_preview_package_path(cache_root: Path, path_value: object) -> bool:
    try:
        package_path = Path(str(path_value or "")).resolve()
        packages_root = native_preview_package_cache_packages_root(cache_root).resolve()
    except (OSError, ValueError):
        return False
    if package_path.name != "package":
        return False
    try:
        package_path.relative_to(packages_root)
    except ValueError:
        return False
    return True


def _metadata_path(entry_dir: Path) -> Path:
    return Path(entry_dir) / "cache_entry.json"


def _read_metadata(entry_dir: Path) -> dict:
    try:
        payload = json.loads(_metadata_path(entry_dir).read_text(encoding="utf-8"))
    except Exception:
        return {}
    return dict(payload) if isinstance(payload, Mapping) else {}


def _write_metadata(entry_dir: Path, metadata: Mapping[str, object]) -> None:
    entry_dir.mkdir(parents=True, exist_ok=True)
    payload = dict(metadata)
    payload.setdefault("schema", NATIVE_PREVIEW_PACKAGE_CACHE_SCHEMA)
    payload["last_access_ns"] = int(time.time_ns())
    temp_path = _metadata_path(entry_dir).with_suffix(".tmp")
    temp_path.write_text(json.dumps(payload, separators=(",", ":"), default=str), encoding="utf-8")
    os.replace(temp_path, _metadata_path(entry_dir))


def _directory_size(path: Path) -> int:
    total = 0
    try:
        iterator = path.rglob("*")
        for child in iterator:
            try:
                if child.is_file():
                    total += max(0, int(child.stat().st_size))
            except OSError:
                continue
    except OSError:
        return 0
    return total


def lookup_native_preview_package_cache(
    cache_root: Path,
    cache_key: str,
    *,
    validate_package: Callable[[Path], Tuple[bool, Sequence[str]]],
) -> Optional[NativePreviewPackageCacheHit]:
    key = str(cache_key or "").strip()
    if not key:
        return None
    entry_dir = native_preview_package_cache_entry_dir(cache_root, key)
    package_dir = entry_dir / "package"
    metadata = _read_metadata(entry_dir)
    if int(metadata.get("schema", 0) or 0) != NATIVE_PREVIEW_PACKAGE_CACHE_SCHEMA:
        shutil.rmtree(entry_dir, ignore_errors=True)
        return None
    ok, _missing = validate_package(package_dir)
    if not ok:
        shutil.rmtree(entry_dir, ignore_errors=True)
        return None
    metadata = dict(metadata)
    metadata["last_access_ns"] = int(time.time_ns())
    try:
        _write_metadata(entry_dir, metadata)
    except OSError:
        pass
    return NativePreviewPackageCacheHit(key, entry_dir, package_dir, metadata)


def store_native_preview_package_cache(
    cache_root: Path,
    cache_key: str,
    staging_entry_dir: Path,
    metadata: Mapping[str, object],
    *,
    validate_package: Callable[[Path], Tuple[bool, Sequence[str]]],
    max_bytes: int,
    target_bytes: int,
) -> Optional[NativePreviewPackageCacheHit]:
    key = str(cache_key or "").strip()
    if not key:
        shutil.rmtree(staging_entry_dir, ignore_errors=True)
        return None
    staging_entry_dir = Path(staging_entry_dir)
    staging_package_dir = staging_entry_dir / "package"
    ok, _missing = validate_package(staging_package_dir)
    if not ok:
        shutil.rmtree(staging_entry_dir, ignore_errors=True)
        return None
    final_entry_dir = native_preview_package_cache_entry_dir(cache_root, key)
    if final_entry_dir.exists():
        hit = lookup_native_preview_package_cache(cache_root, key, validate_package=validate_package)
        if hit is not None:
            shutil.rmtree(staging_entry_dir, ignore_errors=True)
            return hit
        shutil.rmtree(final_entry_dir, ignore_errors=True)
    packages_root = native_preview_package_cache_packages_root(cache_root)
    packages_root.mkdir(parents=True, exist_ok=True)
    metadata_payload = dict(metadata)
    metadata_payload.update(
        {
            "schema": NATIVE_PREVIEW_PACKAGE_CACHE_SCHEMA,
            "cache_key": key,
            "package_bytes": _directory_size(staging_package_dir),
            "created_ns": int(time.time_ns()),
            "last_access_ns": int(time.time_ns()),
        }
    )
    _write_metadata(staging_entry_dir, metadata_payload)
    try:
        staging_entry_dir.replace(final_entry_dir)
    except OSError:
        shutil.move(str(staging_entry_dir), str(final_entry_dir))
    prune_native_preview_package_cache(
        cache_root,
        max_bytes=max_bytes,
        target_bytes=target_bytes,
        protected_keys=(key,),
    )
    return lookup_native_preview_package_cache(cache_root, key, validate_package=validate_package)


def prune_native_preview_package_cache(
    cache_root: Path,
    *,
    max_bytes: int,
    target_bytes: int,
    protected_keys: Sequence[str] = (),
) -> dict:
    packages_root = native_preview_package_cache_packages_root(cache_root)
    if max_bytes <= 0 or target_bytes < 0 or not packages_root.is_dir():
        return {"entries": 0, "bytes": 0, "removed_entries": 0, "removed_bytes": 0}
    entries: list[tuple[int, int, Path]] = []
    total_bytes = 0
    try:
        children = tuple(path for path in packages_root.iterdir() if path.is_dir())
    except OSError:
        return {"entries": 0, "bytes": 0, "removed_entries": 0, "removed_bytes": 0}
    protected = {str(key or "").strip() for key in protected_keys if str(key or "").strip()}
    for entry_dir in children:
        if entry_dir.name.startswith("_staging_"):
            shutil.rmtree(entry_dir, ignore_errors=True)
            continue
        size = _directory_size(entry_dir)
        metadata = _read_metadata(entry_dir)
        try:
            last_access_ns = int(metadata.get("last_access_ns", 0) or 0)
        except (TypeError, ValueError):
            last_access_ns = 0
        if last_access_ns <= 0:
            try:
                last_access_ns = int(entry_dir.stat().st_mtime_ns)
            except OSError:
                last_access_ns = 0
        total_bytes += size
        entries.append((last_access_ns, size, entry_dir))
    if total_bytes <= max_bytes:
        return {"entries": len(entries), "bytes": total_bytes, "removed_entries": 0, "removed_bytes": 0}
    removed_entries = 0
    removed_bytes = 0
    for _last_access_ns, size, entry_dir in sorted(entries, key=lambda item: item[0]):
        if total_bytes <= target_bytes:
            break
        if entry_dir.name in protected:
            continue
        shutil.rmtree(entry_dir, ignore_errors=True)
        total_bytes -= size
        removed_entries += 1
        removed_bytes += size
    return {
        "entries": max(0, len(entries) - removed_entries),
        "bytes": max(0, total_bytes),
        "removed_entries": removed_entries,
        "removed_bytes": removed_bytes,
    }


def clear_native_preview_package_cache(cache_root: Path) -> None:
    shutil.rmtree(native_preview_package_cache_packages_root(cache_root), ignore_errors=True)
