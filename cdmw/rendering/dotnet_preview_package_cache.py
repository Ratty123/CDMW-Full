"""Canonical names for the shared .NET preview package cache.

The storage engine predates the renderer migration and retains legacy symbols
as compatibility aliases.  Production .NET preview code imports this module.
"""

from cdmw.rendering.native_preview_package_cache import (
    DOTNET_PREVIEW_PACKAGE_CACHE_MODES,
    DOTNET_PREVIEW_PACKAGE_CACHE_SCHEMA,
    DotNetPreviewPackageCacheHit,
    DotNetPreviewPackageCacheLease,
    acquire_dotnet_preview_package_cache_lease,
    acquire_dotnet_preview_package_cache_lease_for_path,
    clamp_dotnet_preview_package_cache_mode,
    clear_dotnet_preview_package_cache,
    create_dotnet_preview_package_staging_dir,
    dotnet_preview_package_cache_budget,
    dotnet_preview_package_cache_build_lock,
    dotnet_preview_package_cache_entry_dir,
    dotnet_preview_package_cache_packages_root,
    dotnet_preview_package_cache_use,
    dotnet_preview_package_prefetch_limit,
    is_durable_dotnet_preview_package_path,
    is_temp_dotnet_preview_package_path,
    lookup_dotnet_preview_package_cache,
    prune_dotnet_preview_package_cache,
    release_dotnet_preview_package_staging_dir,
    store_dotnet_preview_package_cache,
)


__all__ = [
    "DotNetPreviewPackageCacheHit",
    "DotNetPreviewPackageCacheLease",
    "DOTNET_PREVIEW_PACKAGE_CACHE_MODES",
    "DOTNET_PREVIEW_PACKAGE_CACHE_SCHEMA",
    "acquire_dotnet_preview_package_cache_lease",
    "acquire_dotnet_preview_package_cache_lease_for_path",
    "clamp_dotnet_preview_package_cache_mode",
    "clear_dotnet_preview_package_cache",
    "create_dotnet_preview_package_staging_dir",
    "dotnet_preview_package_cache_budget",
    "dotnet_preview_package_cache_build_lock",
    "dotnet_preview_package_cache_entry_dir",
    "dotnet_preview_package_cache_packages_root",
    "dotnet_preview_package_cache_use",
    "dotnet_preview_package_prefetch_limit",
    "is_durable_dotnet_preview_package_path",
    "is_temp_dotnet_preview_package_path",
    "lookup_dotnet_preview_package_cache",
    "prune_dotnet_preview_package_cache",
    "release_dotnet_preview_package_staging_dir",
    "store_dotnet_preview_package_cache",
]
