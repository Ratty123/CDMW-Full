"""Read-only archive relationship and index queries."""

from __future__ import annotations

from typing import Any


def build_archive_asset_family_graph(*args: Any, **kwargs: Any) -> Any:
    from cdmw.core.archive_asset_family import build_archive_asset_family_graph as owner

    return owner(*args, **kwargs)


def build_archive_relationship_references(*args: Any, **kwargs: Any) -> Any:
    from cdmw.core.archive_references import build_archive_relationship_references as owner

    return owner(*args, **kwargs)


def build_archive_item_icon_references_from_catalog(*args: Any, **kwargs: Any) -> Any:
    from cdmw.core.archive_references import build_archive_item_icon_references_from_catalog as owner

    return owner(*args, **kwargs)


def merge_archive_reference_rows(*args: Any, **kwargs: Any) -> Any:
    from cdmw.core.archive_references import merge_archive_reference_rows as owner

    return owner(*args, **kwargs)


def find_archive_model_related_entries(*args: Any, **kwargs: Any) -> Any:
    from cdmw.core.archive_model_references import _find_archive_model_related_entries as owner

    return owner(*args, **kwargs)


def find_archive_model_sidecar_entries(*args: Any, **kwargs: Any) -> Any:
    from cdmw.core.archive_model_references import _find_archive_model_sidecar_entries as owner

    return owner(*args, **kwargs)


def extract_archive_model_sidecar_texture_references(*args: Any, **kwargs: Any) -> Any:
    from cdmw.core.archive_model_references import _extract_archive_model_sidecar_texture_references as owner

    return owner(*args, **kwargs)


def build_archive_model_texture_references(*args: Any, **kwargs: Any) -> Any:
    from cdmw.core.archive_model_textures import build_archive_model_texture_references as owner

    return owner(*args, **kwargs)


def build_archive_tree_index(*args: Any, **kwargs: Any) -> Any:
    from cdmw.core.archive_preview_support import build_archive_tree_index as owner

    return owner(*args, **kwargs)


def build_archive_structure_children_map(*args: Any, **kwargs: Any) -> Any:
    from cdmw.core.archive_preview_support import build_archive_structure_children_map as owner

    return owner(*args, **kwargs)


def resolve_archive_pathc_path(*args: Any, **kwargs: Any) -> Any:
    from cdmw.core.archive_preview_support import resolve_archive_pathc_path as owner

    return owner(*args, **kwargs)


def sort_archive_entries_for_browser(*args: Any, **kwargs: Any) -> Any:
    from cdmw.core.archive_filtering import sort_archive_entries_for_browser as owner

    return owner(*args, **kwargs)


__all__ = [
    "build_archive_asset_family_graph",
    "build_archive_item_icon_references_from_catalog",
    "build_archive_model_texture_references",
    "build_archive_relationship_references",
    "build_archive_structure_children_map",
    "build_archive_tree_index",
    "extract_archive_model_sidecar_texture_references",
    "find_archive_model_related_entries",
    "find_archive_model_sidecar_entries",
    "merge_archive_reference_rows",
    "resolve_archive_pathc_path",
    "sort_archive_entries_for_browser",
]
