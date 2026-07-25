"""Shared QSettings reader for archive performance settings.

Both the settings tab and the main shell restore these values independently.
They must read the same keys with the same fallbacks, so the key mapping lives
here once rather than in each caller.
"""

from __future__ import annotations

from typing import Protocol

from cdmw.models import ArchivePerformanceSettings, clamp_archive_performance_settings


class _SettingsSource(Protocol):
    def value(self, key: str, default: object = None) -> object: ...

    def contains(self, key: str) -> bool: ...


def _read_bool(settings: _SettingsSource, key: str, default: bool) -> bool:
    value = settings.value(key, default)
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _read_int(settings: _SettingsSource, key: str, default: int) -> int:
    value = settings.value(key, default)
    try:
        return int(value)
    except (TypeError, ValueError):
        return int(default)


def read_archive_performance_settings(
    settings: _SettingsSource,
) -> ArchivePerformanceSettings:
    defaults = clamp_archive_performance_settings()
    sidecar_worker_count = _read_int(
        settings,
        "archive/sidecar_worker_count",
        defaults.sidecar_worker_count,
    )
    if not settings.contains("archive/sidecar_worker_count"):
        # Pre-split installs stored one shared worker limit.
        sidecar_worker_count = _read_int(
            settings,
            "performance/background_worker_limit",
            defaults.sidecar_worker_count,
        )
    return clamp_archive_performance_settings(
        ArchivePerformanceSettings(
            resource_profile=str(
                settings.value("performance/resource_profile", defaults.resource_profile)
                or defaults.resource_profile
            ),
            archive_fetch_batch_size=_read_int(
                settings,
                "performance/archive_fetch_batch_size",
                defaults.archive_fetch_batch_size,
            ),
            native_archive_acceleration=_read_bool(
                settings,
                "performance/native_archive_acceleration",
                defaults.native_archive_acceleration,
            ),
            enable_sidecar_indexing=_read_bool(
                settings,
                "archive/enable_sidecar_indexing",
                defaults.enable_sidecar_indexing,
            ),
            sidecar_worker_count=sidecar_worker_count,
            preview_cache_limit=_read_int(
                settings,
                "archive/preview_cache_limit",
                defaults.preview_cache_limit,
            ),
            native_preview_cache_mode=str(
                settings.value("archive/native_preview_cache_mode", defaults.native_preview_cache_mode)
                or defaults.native_preview_cache_mode
            ),
            quick_then_full_preview=_read_bool(
                settings,
                "archive/quick_then_full_preview",
                defaults.quick_then_full_preview,
            ),
            maximum_indexing_priority=_read_bool(
                settings,
                "archive/maximum_indexing_priority",
                defaults.maximum_indexing_priority,
            ),
        )
    )


__all__ = ["read_archive_performance_settings"]
