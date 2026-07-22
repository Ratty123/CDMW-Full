"""Canonical names for the shared .NET preview package cache.

The storage engine predates the renderer migration and retains legacy symbols
as compatibility aliases.  Production .NET preview code imports this module.
"""

from cdmw.rendering.native_preview_package_cache import (
    NativePreviewPackageCacheHit as DotNetPreviewPackageCacheHit,
    NativePreviewPackageCacheLease as DotNetPreviewPackageCacheLease,
    acquire_native_preview_package_cache_lease as acquire_dotnet_preview_package_cache_lease,
    acquire_native_preview_package_cache_lease_for_path as acquire_dotnet_preview_package_cache_lease_for_path,
    clear_native_preview_package_cache as clear_dotnet_preview_package_cache,
    create_native_preview_package_staging_dir as create_dotnet_preview_package_staging_dir,
    is_durable_native_preview_package_path as is_durable_dotnet_preview_package_path,
    is_temp_native_preview_package_path as is_temp_dotnet_preview_package_path,
    lookup_native_preview_package_cache as lookup_dotnet_preview_package_cache,
    native_preview_package_cache_budget as dotnet_preview_package_cache_budget,
    native_preview_package_cache_build_lock as dotnet_preview_package_cache_build_lock,
    native_preview_package_cache_entry_dir as dotnet_preview_package_cache_entry_dir,
    native_preview_package_cache_packages_root as dotnet_preview_package_cache_packages_root,
    native_preview_package_cache_use as dotnet_preview_package_cache_use,
    native_preview_package_prefetch_limit as dotnet_preview_package_prefetch_limit,
    prune_native_preview_package_cache as prune_dotnet_preview_package_cache,
    release_native_preview_package_staging_dir as release_dotnet_preview_package_staging_dir,
    store_native_preview_package_cache as store_dotnet_preview_package_cache,
)


__all__ = [
    "DotNetPreviewPackageCacheHit",
    "DotNetPreviewPackageCacheLease",
    "acquire_dotnet_preview_package_cache_lease",
    "acquire_dotnet_preview_package_cache_lease_for_path",
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
