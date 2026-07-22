from __future__ import annotations

import json
import os
import shutil
import tempfile
import threading
import time
import weakref
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterator, Mapping, Optional, Sequence, Tuple


NATIVE_PREVIEW_PACKAGE_CACHE_SCHEMA = 1
NATIVE_PREVIEW_PACKAGE_CACHE_MODES = {"off", "balanced", "aggressive"}
BALANCED_NATIVE_PREVIEW_PACKAGE_MAX_BYTES = 512 * 1024 * 1024
BALANCED_NATIVE_PREVIEW_PACKAGE_TARGET_BYTES = 384 * 1024 * 1024
AGGRESSIVE_NATIVE_PREVIEW_PACKAGE_MAX_BYTES = 2 * 1024 * 1024 * 1024
AGGRESSIVE_NATIVE_PREVIEW_PACKAGE_TARGET_BYTES = 1536 * 1024 * 1024
NATIVE_PREVIEW_PACKAGE_CACHE_RECENT_USE_SECONDS = 30.0

_CACHE_STATE_LOCK = threading.RLock()
_CACHE_KEY_LOCKS: weakref.WeakValueDictionary[tuple[str, str], threading.RLock] = weakref.WeakValueDictionary()
_LEASED_STAGING_PATHS: dict[str, int] = {}
_ACTIVE_CACHE_KEYS: dict[tuple[str, str], int] = {}
_RECENT_CACHE_KEYS: dict[tuple[str, str], float] = {}


@dataclass(frozen=True)
class NativePreviewPackageCacheHit:
    cache_key: str
    entry_dir: Path
    package_dir: Path
    metadata: Mapping[str, object]


class NativePreviewPackageCacheLease:
    """Process-local pin that prevents pruning while a renderer uses a package."""

    def __init__(self, cache_root: Path, cache_key: str) -> None:
        self.cache_root = Path(cache_root)
        self.cache_key = str(cache_key or "").strip()
        self._key_id = _cache_key_id(self.cache_root, self.cache_key)
        self._released = False
        with _CACHE_STATE_LOCK:
            _ACTIVE_CACHE_KEYS[self._key_id] = _ACTIVE_CACHE_KEYS.get(self._key_id, 0) + 1

    @property
    def active(self) -> bool:
        return not self._released

    def release(self) -> None:
        with _CACHE_STATE_LOCK:
            if self._released:
                return
            self._released = True
            count = _ACTIVE_CACHE_KEYS.get(self._key_id, 0) - 1
            if count > 0:
                _ACTIVE_CACHE_KEYS[self._key_id] = count
            else:
                _ACTIVE_CACHE_KEYS.pop(self._key_id, None)

    close = release

    def __enter__(self) -> "NativePreviewPackageCacheLease":
        return self

    def __exit__(self, *_args: object) -> None:
        self.release()

    def __del__(self) -> None:
        self.release()


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


def _resolved_path_key(path: Path) -> str:
    try:
        return os.path.normcase(str(Path(path).resolve()))
    except OSError:
        return os.path.normcase(str(Path(path).absolute()))


def _cache_key_id(cache_root: Path, cache_key: str) -> tuple[str, str]:
    return _resolved_path_key(Path(cache_root)), str(cache_key or "").strip()


def native_preview_package_cache_build_lock(cache_root: Path, cache_key: str) -> threading.RLock:
    lock_id = _cache_key_id(cache_root, cache_key)
    with _CACHE_STATE_LOCK:
        lock = _CACHE_KEY_LOCKS.get(lock_id)
        if lock is None:
            lock = threading.RLock()
            _CACHE_KEY_LOCKS[lock_id] = lock
        return lock


def _acquire_staging_lease(staging_entry_dir: Path) -> None:
    path_key = _resolved_path_key(staging_entry_dir)
    with _CACHE_STATE_LOCK:
        _LEASED_STAGING_PATHS[path_key] = _LEASED_STAGING_PATHS.get(path_key, 0) + 1


def _release_staging_lease(staging_entry_dir: Path) -> None:
    path_key = _resolved_path_key(staging_entry_dir)
    with _CACHE_STATE_LOCK:
        count = _LEASED_STAGING_PATHS.get(path_key, 0) - 1
        if count > 0:
            _LEASED_STAGING_PATHS[path_key] = count
        else:
            _LEASED_STAGING_PATHS.pop(path_key, None)


def _staging_is_leased(staging_entry_dir: Path) -> bool:
    with _CACHE_STATE_LOCK:
        return _LEASED_STAGING_PATHS.get(_resolved_path_key(staging_entry_dir), 0) > 0


def create_native_preview_package_staging_dir(cache_root: Path, *, leased: bool = False) -> Path:
    packages_root = native_preview_package_cache_packages_root(cache_root)
    if not leased:
        packages_root.mkdir(parents=True, exist_ok=True)
        return Path(tempfile.mkdtemp(prefix="_staging_", dir=str(packages_root)))
    with _CACHE_STATE_LOCK:
        packages_root.mkdir(parents=True, exist_ok=True)
        staging_entry_dir = Path(tempfile.mkdtemp(prefix="_staging_", dir=str(packages_root)))
        _acquire_staging_lease(staging_entry_dir)
        return staging_entry_dir


def release_native_preview_package_staging_dir(
    staging_entry_dir: Path,
    *,
    cleanup: bool = False,
) -> None:
    staging_entry_dir = Path(staging_entry_dir)
    if cleanup:
        shutil.rmtree(staging_entry_dir, ignore_errors=True)
    _release_staging_lease(staging_entry_dir)


def _mark_cache_key_recent(cache_root: Path, cache_key: str) -> None:
    with _CACHE_STATE_LOCK:
        _RECENT_CACHE_KEYS[_cache_key_id(cache_root, cache_key)] = (
            time.monotonic() + NATIVE_PREVIEW_PACKAGE_CACHE_RECENT_USE_SECONDS
        )


def _cache_key_is_protected(cache_root: Path, cache_key: str) -> bool:
    key_id = _cache_key_id(cache_root, cache_key)
    with _CACHE_STATE_LOCK:
        deadline = _RECENT_CACHE_KEYS.get(key_id, 0.0)
        if deadline <= time.monotonic():
            _RECENT_CACHE_KEYS.pop(key_id, None)
            deadline = 0.0
        return _ACTIVE_CACHE_KEYS.get(key_id, 0) > 0 or deadline > 0.0


def _cache_key_is_active(cache_root: Path, cache_key: str) -> bool:
    with _CACHE_STATE_LOCK:
        return _ACTIVE_CACHE_KEYS.get(_cache_key_id(cache_root, cache_key), 0) > 0


@contextmanager
def native_preview_package_cache_use(cache_root: Path, cache_key: str) -> Iterator[None]:
    lease = acquire_native_preview_package_cache_lease(cache_root, cache_key)
    try:
        yield
    finally:
        lease.release()


def acquire_native_preview_package_cache_lease(
    cache_root: Path,
    cache_key: str,
) -> NativePreviewPackageCacheLease:
    return NativePreviewPackageCacheLease(cache_root, cache_key)


def acquire_native_preview_package_cache_lease_for_path(
    package_dir: Path,
) -> Optional[NativePreviewPackageCacheLease]:
    """Pin ``<cache>/packages/<key>/package``; ignore non-cache packages."""

    try:
        package_path = Path(package_dir).resolve()
    except (OSError, ValueError):
        return None
    entry_dir = package_path.parent
    packages_root = entry_dir.parent
    if package_path.name != "package" or packages_root.name != "packages":
        return None
    cache_key = entry_dir.name
    if not cache_key or cache_key.startswith("_staging_"):
        return None
    cache_root = packages_root.parent
    with native_preview_package_cache_build_lock(cache_root, cache_key):
        if not package_path.is_dir():
            return None
        return acquire_native_preview_package_cache_lease(cache_root, cache_key)


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
    with native_preview_package_cache_build_lock(cache_root, key):
        entry_dir = native_preview_package_cache_entry_dir(cache_root, key)
        package_dir = entry_dir / "package"
        metadata = _read_metadata(entry_dir)
        if int(metadata.get("schema", 0) or 0) != NATIVE_PREVIEW_PACKAGE_CACHE_SCHEMA:
            if not _cache_key_is_protected(cache_root, key):
                shutil.rmtree(entry_dir, ignore_errors=True)
            return None
        ok, _missing = validate_package(package_dir)
        if not ok:
            if not _cache_key_is_protected(cache_root, key):
                shutil.rmtree(entry_dir, ignore_errors=True)
            return None
        metadata = dict(metadata)
        metadata["last_access_ns"] = int(time.time_ns())
        try:
            _write_metadata(entry_dir, metadata)
        except OSError:
            pass
        _mark_cache_key_recent(cache_root, key)
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
    _acquire_staging_lease(staging_entry_dir)
    try:
        with native_preview_package_cache_build_lock(cache_root, key):
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
                if _cache_key_is_active(cache_root, key):
                    return None
                shutil.rmtree(final_entry_dir, ignore_errors=True)
                if final_entry_dir.exists():
                    return None
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
                hit = lookup_native_preview_package_cache(cache_root, key, validate_package=validate_package)
                if hit is None:
                    return None
                shutil.rmtree(staging_entry_dir, ignore_errors=True)
                return hit
            _mark_cache_key_recent(cache_root, key)
    finally:
        _release_staging_lease(staging_entry_dir)
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
            if not _staging_is_leased(entry_dir):
                shutil.rmtree(entry_dir, ignore_errors=True)
            continue
        with native_preview_package_cache_build_lock(cache_root, entry_dir.name):
            if not entry_dir.is_dir():
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
        with native_preview_package_cache_build_lock(cache_root, entry_dir.name):
            if entry_dir.name in protected or _cache_key_is_protected(cache_root, entry_dir.name):
                continue
            if not entry_dir.is_dir():
                continue
            shutil.rmtree(entry_dir, ignore_errors=True)
            if entry_dir.exists():
                continue
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
    packages_root = native_preview_package_cache_packages_root(cache_root)
    try:
        children = tuple(path for path in packages_root.iterdir() if path.is_dir())
    except OSError:
        return
    for entry_dir in children:
        if entry_dir.name.startswith("_staging_"):
            if not _staging_is_leased(entry_dir):
                shutil.rmtree(entry_dir, ignore_errors=True)
            continue
        with native_preview_package_cache_build_lock(cache_root, entry_dir.name):
            if not _cache_key_is_active(cache_root, entry_dir.name):
                shutil.rmtree(entry_dir, ignore_errors=True)
    try:
        packages_root.rmdir()
    except OSError:
        pass


# Canonical .NET/Vortice names.  The implementation remains in this module so
# older extensions can keep importing the historical symbols, but production
# renderer code imports the canonical facade in ``dotnet_preview_package_cache``.
DOTNET_PREVIEW_PACKAGE_CACHE_SCHEMA = NATIVE_PREVIEW_PACKAGE_CACHE_SCHEMA
DOTNET_PREVIEW_PACKAGE_CACHE_MODES = NATIVE_PREVIEW_PACKAGE_CACHE_MODES
DotNetPreviewPackageCacheHit = NativePreviewPackageCacheHit
DotNetPreviewPackageCacheLease = NativePreviewPackageCacheLease
clamp_dotnet_preview_package_cache_mode = clamp_native_preview_package_cache_mode
dotnet_preview_package_cache_budget = native_preview_package_cache_budget
dotnet_preview_package_prefetch_limit = native_preview_package_prefetch_limit
dotnet_preview_package_cache_packages_root = native_preview_package_cache_packages_root
dotnet_preview_package_cache_entry_dir = native_preview_package_cache_entry_dir
dotnet_preview_package_cache_build_lock = native_preview_package_cache_build_lock
create_dotnet_preview_package_staging_dir = create_native_preview_package_staging_dir
release_dotnet_preview_package_staging_dir = release_native_preview_package_staging_dir
dotnet_preview_package_cache_use = native_preview_package_cache_use
acquire_dotnet_preview_package_cache_lease = acquire_native_preview_package_cache_lease
acquire_dotnet_preview_package_cache_lease_for_path = acquire_native_preview_package_cache_lease_for_path
is_temp_dotnet_preview_package_path = is_temp_native_preview_package_path
is_durable_dotnet_preview_package_path = is_durable_native_preview_package_path
lookup_dotnet_preview_package_cache = lookup_native_preview_package_cache
store_dotnet_preview_package_cache = store_native_preview_package_cache
prune_dotnet_preview_package_cache = prune_native_preview_package_cache
clear_dotnet_preview_package_cache = clear_native_preview_package_cache
