from __future__ import annotations

import os
import shutil
import tempfile
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Sequence

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
DEFAULT_APP_TEMP_CACHE_MAX_BYTES = 512 * 1024 * 1024
DEFAULT_APP_TEMP_CACHE_TARGET_BYTES = 384 * 1024 * 1024
DEFAULT_APP_TEMP_CACHE_PRUNE_INTERVAL_SECONDS = 60.0
APP_TEMP_CACHE_ROOT_ENV = "CDMW_TEMP_CACHE_ROOT"

_PRUNE_LOCK = threading.Lock()
_last_prune_monotonic = 0.0


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
            try:
                directory.rmdir()
            except OSError:
                pass
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
    try:
        now = time.monotonic()
        if now - _last_prune_monotonic < max(0.0, float(min_interval_seconds)):
            return None
        _last_prune_monotonic = now
        return prune_app_temp_cache(max_bytes=max_bytes, target_bytes=target_bytes)
    finally:
        _PRUNE_LOCK.release()
