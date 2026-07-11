from __future__ import annotations

import os
import shutil
import tempfile
import threading
import time
import weakref
from collections import OrderedDict
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator, Optional, Sequence

from cdmw.constants import APP_NAME


APP_TEMP_CACHE_DIRNAMES: tuple[str, ...] = (
    "archive_preview_cache",
    "directxtex_texture_preview",
    "native_texture_preview",
    "static_mesh_texture_previews",
    "final_package_preview",
    "preview_cache",
    "preview_cache_display",
)
_APP_TEMP_CACHE_DIRNAME_KEYS = frozenset(name.casefold() for name in APP_TEMP_CACHE_DIRNAMES)
DEFAULT_APP_TEMP_CACHE_MAX_BYTES = 512 * 1024 * 1024
DEFAULT_APP_TEMP_CACHE_TARGET_BYTES = 384 * 1024 * 1024
DEFAULT_APP_TEMP_CACHE_PRUNE_INTERVAL_SECONDS = 60.0
DEFAULT_APP_TEMP_CACHE_RECENT_USE_SECONDS = 30.0
APP_TEMP_CACHE_ROOT_ENV = "CDMW_TEMP_CACHE_ROOT"

_PRUNE_LOCK = threading.Lock()
_last_prune_monotonic = 0.0
_CACHE_STATE_LOCK = threading.RLock()
_CACHE_UNIT_LOCKS: weakref.WeakValueDictionary[str, threading.RLock] = weakref.WeakValueDictionary()
_ACTIVE_CACHE_UNITS: dict[str, int] = {}
_RECENT_CACHE_UNITS: "OrderedDict[str, float]" = OrderedDict()
_RECENT_CACHE_UNIT_LIMIT = 8192


@dataclass(frozen=True)
class AppTempCachePruneReport:
    total_bytes_before: int
    total_bytes_after: int
    removed_bytes: int
    scanned_units: int
    removed_units: int
    failed_units: int


@dataclass(frozen=True)
class _CacheUnit:
    path: Path
    size: int
    mtime: float
    is_dir: bool


class AppTempCacheLease:
    """Process-local pin preventing one managed cache unit from being pruned."""

    def __init__(self, cache_path: Path | str) -> None:
        self.cache_unit = _app_temp_cache_unit_path(cache_path)
        self._key = _cache_unit_key(self.cache_unit)
        self._released = False
        with _cache_unit_lock(self.cache_unit):
            with _CACHE_STATE_LOCK:
                _ACTIVE_CACHE_UNITS[self._key] = _ACTIVE_CACHE_UNITS.get(self._key, 0) + 1

    @property
    def active(self) -> bool:
        return not self._released

    def release(self) -> None:
        with _CACHE_STATE_LOCK:
            if self._released:
                return
            self._released = True
            count = _ACTIVE_CACHE_UNITS.get(self._key, 0) - 1
            if count > 0:
                _ACTIVE_CACHE_UNITS[self._key] = count
            else:
                _ACTIVE_CACHE_UNITS.pop(self._key, None)

    close = release

    def __enter__(self) -> "AppTempCacheLease":
        return self

    def __exit__(self, *_args: object) -> None:
        self.release()

    def __del__(self) -> None:
        try:
            self.release()
        except Exception:
            pass


def _env_bytes(name: str, default: int) -> int:
    text = os.environ.get(name, "").strip()
    if not text:
        return int(default)
    try:
        value = int(float(text))
    except ValueError:
        return int(default)
    return max(0, value * 1024 * 1024)


def app_temp_root(*, temp_root: Optional[Path] = None) -> Path:
    if temp_root is None:
        env_root = os.environ.get(APP_TEMP_CACHE_ROOT_ENV, "").strip()
        if env_root:
            return Path(env_root).expanduser()
    return Path(temp_root or tempfile.gettempdir()) / APP_NAME


def app_temp_cache_path(dirname: str, *parts: object, temp_root: Optional[Path] = None) -> Path:
    return app_temp_root(temp_root=temp_root).joinpath(str(dirname), *(str(part) for part in parts))


def _absolute_path(path: Path | str) -> Path:
    try:
        return Path(path).expanduser().absolute()
    except OSError:
        return Path(path)


def _app_temp_cache_unit_path(path: Path | str) -> Path:
    """Return the direct managed-cache child containing path, or path itself."""

    candidate = _absolute_path(path)
    current = candidate
    while current.parent != current:
        if current.parent.name.casefold() in _APP_TEMP_CACHE_DIRNAME_KEYS:
            return current
        current = current.parent
    return candidate


def _resolved_path_key(path: Path | str) -> str:
    candidate = _absolute_path(path)
    try:
        candidate = candidate.resolve()
    except OSError:
        pass
    return os.path.normcase(str(candidate))


def _cache_unit_key(path: Path | str) -> str:
    return _resolved_path_key(_app_temp_cache_unit_path(path))


def _cache_unit_lock(path: Path | str) -> threading.RLock:
    key = _cache_unit_key(path)
    with _CACHE_STATE_LOCK:
        lock = _CACHE_UNIT_LOCKS.get(key)
        if lock is None:
            lock = threading.RLock()
            _CACHE_UNIT_LOCKS[key] = lock
        return lock


def acquire_app_temp_cache_lease(cache_path: Path | str) -> AppTempCacheLease:
    """Pin the managed cache unit containing cache_path until release()."""

    return AppTempCacheLease(cache_path)


@contextmanager
def app_temp_cache_use(cache_path: Path | str) -> Iterator[Path]:
    """Pin a cache path while a reader consumes it."""

    lease = acquire_app_temp_cache_lease(cache_path)
    try:
        yield lease.cache_unit
    finally:
        lease.release()


@contextmanager
def app_temp_cache_build(cache_path: Path | str) -> Iterator[Path]:
    """Singleflight one cache-unit build and pin it against pruning."""

    cache_unit = _app_temp_cache_unit_path(cache_path)
    with _cache_unit_lock(cache_unit):
        with app_temp_cache_use(cache_unit):
            yield cache_unit


def _drop_expired_recent_units_locked(now: float) -> None:
    expired = [key for key, deadline in _RECENT_CACHE_UNITS.items() if deadline <= now]
    for key in expired:
        _RECENT_CACHE_UNITS.pop(key, None)


def mark_app_temp_cache_recent(
    cache_path: Path | str,
    *,
    seconds: float = DEFAULT_APP_TEMP_CACHE_RECENT_USE_SECONDS,
) -> None:
    """Give a just-returned cache unit a short grace period before pruning."""

    key = _cache_unit_key(cache_path)
    now = time.monotonic()
    with _CACHE_STATE_LOCK:
        if len(_RECENT_CACHE_UNITS) >= _RECENT_CACHE_UNIT_LIMIT:
            _drop_expired_recent_units_locked(now)
        _RECENT_CACHE_UNITS.pop(key, None)
        if float(seconds) > 0.0:
            _RECENT_CACHE_UNITS[key] = now + float(seconds)
        while len(_RECENT_CACHE_UNITS) > _RECENT_CACHE_UNIT_LIMIT:
            _RECENT_CACHE_UNITS.popitem(last=False)


def _cache_unit_is_protected(path: Path | str) -> bool:
    key = _cache_unit_key(path)
    now = time.monotonic()
    with _CACHE_STATE_LOCK:
        deadline = _RECENT_CACHE_UNITS.get(key, 0.0)
        if deadline and deadline <= now:
            _RECENT_CACHE_UNITS.pop(key, None)
            deadline = 0.0
        return _ACTIVE_CACHE_UNITS.get(key, 0) > 0 or deadline > now


def _cache_path_or_descendant_is_protected(path: Path | str) -> bool:
    key = _resolved_path_key(path).rstrip(os.sep)
    prefix = f"{key}{os.sep}"
    now = time.monotonic()
    with _CACHE_STATE_LOCK:
        _drop_expired_recent_units_locked(now)
        protected_keys = set(_ACTIVE_CACHE_UNITS).union(_RECENT_CACHE_UNITS)
        return any(candidate == key or candidate.startswith(prefix) for candidate in protected_keys)


def app_temp_cache_max_bytes() -> int:
    return _env_bytes("CDMW_TEMP_CACHE_MAX_MB", DEFAULT_APP_TEMP_CACHE_MAX_BYTES)


def app_temp_cache_target_bytes() -> int:
    return _env_bytes("CDMW_TEMP_CACHE_TARGET_MB", DEFAULT_APP_TEMP_CACHE_TARGET_BYTES)


def _collect_cache_unit(path: Path) -> Optional[_CacheUnit]:
    try:
        if path.is_symlink():
            stat = path.lstat()
            return _CacheUnit(path=path, size=max(0, int(stat.st_size)), mtime=float(stat.st_mtime), is_dir=False)
        if path.is_file():
            stat = path.stat()
            return _CacheUnit(path=path, size=max(0, int(stat.st_size)), mtime=float(stat.st_mtime), is_dir=False)
        if not path.is_dir():
            return None
    except OSError:
        return None

    total_size = 0
    newest_mtime = 0.0
    try:
        root_stat = path.stat()
        newest_mtime = float(root_stat.st_mtime)
    except OSError:
        pass
    try:
        descendants = path.rglob("*")
        for descendant in descendants:
            try:
                if descendant.is_symlink():
                    stat = descendant.lstat()
                elif descendant.is_file():
                    stat = descendant.stat()
                else:
                    try:
                        newest_mtime = max(newest_mtime, float(descendant.stat().st_mtime))
                    except OSError:
                        pass
                    continue
                total_size += max(0, int(stat.st_size))
                newest_mtime = max(newest_mtime, float(stat.st_mtime))
            except OSError:
                continue
    except OSError:
        return None
    return _CacheUnit(path=path, size=total_size, mtime=newest_mtime, is_dir=True)


def _cache_units(root: Path, dirnames: Sequence[str]) -> list[_CacheUnit]:
    units: list[_CacheUnit] = []
    for dirname in dirnames:
        cache_dir = root / dirname
        try:
            children = list(cache_dir.iterdir())
        except OSError:
            continue
        for child in children:
            unit = _collect_cache_unit(child)
            if unit is not None:
                units.append(unit)
    return units


def _remove_empty_dirs(root: Path, dirnames: Sequence[str]) -> None:
    for dirname in dirnames:
        cache_dir = root / dirname
        try:
            directories = [path for path in cache_dir.rglob("*") if path.is_dir()]
        except OSError:
            continue
        for directory in sorted(directories, key=lambda value: len(value.parts), reverse=True):
            cache_unit = _app_temp_cache_unit_path(directory)
            if _cache_unit_is_protected(cache_unit):
                continue
            with _cache_unit_lock(cache_unit):
                if _cache_unit_is_protected(cache_unit):
                    continue
                try:
                    directory.rmdir()
                except OSError:
                    pass
        if _cache_path_or_descendant_is_protected(cache_dir):
            continue
        try:
            cache_dir.rmdir()
        except OSError:
            pass


def prune_app_temp_cache(
    *,
    max_bytes: Optional[int] = None,
    target_bytes: Optional[int] = None,
    root: Optional[Path] = None,
    dirnames: Sequence[str] = APP_TEMP_CACHE_DIRNAMES,
) -> AppTempCachePruneReport:
    max_size = app_temp_cache_max_bytes() if max_bytes is None else max(0, int(max_bytes))
    target_size = app_temp_cache_target_bytes() if target_bytes is None else max(0, int(target_bytes))
    if max_size <= 0:
        return AppTempCachePruneReport(0, 0, 0, 0, 0, 0)
    target_size = min(target_size, max_size)
    cache_root = Path(root) if root is not None else app_temp_root()
    units = _cache_units(cache_root, dirnames)
    total_before = sum(unit.size for unit in units)
    if total_before <= max_size:
        return AppTempCachePruneReport(total_before, total_before, 0, len(units), 0, 0)

    current_size = total_before
    removed_units = 0
    removed_bytes = 0
    failed_units = 0
    for unit in sorted(units, key=lambda value: (value.mtime, str(value.path).lower())):
        if current_size <= target_size:
            break
        if _cache_unit_is_protected(unit.path):
            continue
        with _cache_unit_lock(unit.path):
            if _cache_unit_is_protected(unit.path):
                continue
            try:
                if unit.is_dir:
                    shutil.rmtree(unit.path)
                else:
                    unit.path.unlink()
            except OSError:
                failed_units += 1
                continue
        removed_units += 1
        removed_bytes += unit.size
        current_size = max(0, current_size - unit.size)

    if removed_units:
        _remove_empty_dirs(cache_root, dirnames)
    return AppTempCachePruneReport(
        total_bytes_before=total_before,
        total_bytes_after=current_size,
        removed_bytes=removed_bytes,
        scanned_units=len(units),
        removed_units=removed_units,
        failed_units=failed_units,
    )


def request_app_temp_cache_prune(
    *,
    min_interval_seconds: float = DEFAULT_APP_TEMP_CACHE_PRUNE_INTERVAL_SECONDS,
    max_bytes: Optional[int] = None,
    target_bytes: Optional[int] = None,
) -> Optional[AppTempCachePruneReport]:
    global _last_prune_monotonic
    now = time.monotonic()
    if now - _last_prune_monotonic < max(0.0, float(min_interval_seconds)):
        return None
    if not _PRUNE_LOCK.acquire(blocking=False):
        return None
    previous_prune_monotonic = _last_prune_monotonic
    try:
        now = time.monotonic()
        if now - _last_prune_monotonic < max(0.0, float(min_interval_seconds)):
            _PRUNE_LOCK.release()
            return None
        _last_prune_monotonic = now

        def prune() -> None:
            try:
                prune_app_temp_cache(max_bytes=max_bytes, target_bytes=target_bytes)
            except Exception:
                pass
            finally:
                _PRUNE_LOCK.release()

        threading.Thread(target=prune, name="cdmw-temp-cache-prune", daemon=True).start()
    except Exception:
        _last_prune_monotonic = previous_prune_monotonic
        _PRUNE_LOCK.release()
        raise
    return None
