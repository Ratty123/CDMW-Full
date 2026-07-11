"""Archive installation and cache-environment coordination."""

from __future__ import annotations

from typing import Any


def autodetect_archive_package_roots(*args: Any, **kwargs: Any) -> Any:
    from cdmw.core.archive_format import autodetect_archive_package_roots as owner

    return owner(*args, **kwargs)


def looks_like_archive_package_root(*args: Any, **kwargs: Any) -> Any:
    from cdmw.core.archive_format import looks_like_archive_package_root as owner

    return owner(*args, **kwargs)


def archive_scan_shard_cache_health(*args: Any, **kwargs: Any) -> Any:
    from cdmw.core.archive_scan_cache import archive_scan_shard_cache_health as owner

    return owner(*args, **kwargs)


def find_suspicious_archive_tree_roots(*args: Any, **kwargs: Any) -> Any:
    from cdmw.core.archive_tree_preflight import find_suspicious_archive_tree_roots as owner

    return owner(*args, **kwargs)


def invalidate_archive_browser_cache(*args: Any, **kwargs: Any) -> Any:
    from cdmw.core.archive_scan_cache import invalidate_archive_browser_cache as owner

    return owner(*args, **kwargs)


def resolve_crimson_desert_executable(*args: Any, **kwargs: Any) -> Any:
    from cdmw.core.archive_scan_cache import resolve_crimson_desert_executable as owner

    return owner(*args, **kwargs)


def sha256_file(*args: Any, **kwargs: Any) -> Any:
    from cdmw.core.archive_scan_cache import sha256_file as owner

    return owner(*args, **kwargs)


__all__ = [
    "archive_scan_shard_cache_health",
    "autodetect_archive_package_roots",
    "find_suspicious_archive_tree_roots",
    "invalidate_archive_browser_cache",
    "looks_like_archive_package_root",
    "resolve_crimson_desert_executable",
    "sha256_file",
]
