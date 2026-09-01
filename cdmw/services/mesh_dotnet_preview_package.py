"""Legacy import aliases for the Rust Archive Preview package service.

Production code imports :mod:`mesh_rust_preview_cache` directly.  These names
remain only so third-party extensions written against the pre-cutover Python
API fail softly while receiving Rust packages.
"""

from cdmw.services.mesh_rust_preview_cache import (
    build_or_lookup_rust_preview_package as build_or_lookup_dotnet_preview_package,
    build_or_lookup_rust_preview_package_from_model as build_or_lookup_dotnet_preview_package_from_model,
    build_rust_preview_cache_prewarm_package as build_dotnet_preview_prewarm_package,
    lookup_rust_preview_package_from_model_identity as lookup_dotnet_preview_package_from_model_identity,
    lookup_rust_preview_package_hit_from_model_identity as lookup_dotnet_preview_package_hit_from_model_identity,
    parsed_mesh_from_model_preview,
    rust_preview_overlays_from_model as dotnet_preview_overlays_from_model,
    rust_preview_overlays_from_preview_core_package as dotnet_preview_overlays_from_preview_core_package,
    rust_preview_package_cache_key as dotnet_preview_package_cache_key,
    rust_preview_package_cache_root,
    validate_rust_preview_cache_package as validate_dotnet_preview_package,
)

DOTNET_PREVIEW_PACKAGE_CACHE_SCHEMA = 1
DOTNET_PREVIEW_PACKAGE_COMPILER_SCHEMA = 1

__all__ = [
    "DOTNET_PREVIEW_PACKAGE_CACHE_SCHEMA",
    "DOTNET_PREVIEW_PACKAGE_COMPILER_SCHEMA",
    "build_or_lookup_dotnet_preview_package",
    "build_or_lookup_dotnet_preview_package_from_model",
    "build_dotnet_preview_prewarm_package",
    "dotnet_preview_overlays_from_model",
    "dotnet_preview_overlays_from_preview_core_package",
    "dotnet_preview_package_cache_key",
    "lookup_dotnet_preview_package_from_model_identity",
    "lookup_dotnet_preview_package_hit_from_model_identity",
    "parsed_mesh_from_model_preview",
    "rust_preview_package_cache_root",
    "validate_dotnet_preview_package",
]
