"""Structural prefab decoding and path retargeting for UI callers."""

from __future__ import annotations

from typing import Any


def decode_prefab_binary(*args: Any, **kwargs: Any) -> Any:
    from cdmw.core.prefab_binary import decode_prefab_binary as owner

    return owner(*args, **kwargs)


def pointer_sites(*args: Any, **kwargs: Any) -> Any:
    from cdmw.core.prefab_binary import pointer_sites as owner

    return owner(*args, **kwargs)


def plan_prefab_path_edits(*args: Any, **kwargs: Any) -> Any:
    from cdmw.core.prefab_binary_edit import plan_prefab_path_edits as owner

    return owner(*args, **kwargs)


def rewrite_prefab_paths(*args: Any, **kwargs: Any) -> Any:
    from cdmw.core.prefab_binary_edit import rewrite_prefab_paths as owner

    return owner(*args, **kwargs)


def collect_asset_paths(*args: Any, **kwargs: Any) -> Any:
    from cdmw.core.prefab_asset_catalog import collect_asset_paths as owner

    return owner(*args, **kwargs)


def path_is_known(*args: Any, **kwargs: Any) -> Any:
    from cdmw.core.prefab_asset_catalog import path_is_known as owner

    return owner(*args, **kwargs)


def asset_extension_for(*args: Any, **kwargs: Any) -> Any:
    from cdmw.core.prefab_asset_catalog import extension_for as owner

    return owner(*args, **kwargs)


def rewrite_prefab_placements(*args, **kwargs):
    from cdmw.core.prefab_binary_edit import rewrite_prefab_placements as owner

    return owner(*args, **kwargs)


def prefab_binary_error() -> type[Exception]:
    """The exception type raised for payloads that break the grammar."""
    from cdmw.core.prefab_binary import PrefabBinaryError

    return PrefabBinaryError


__all__ = [
    "asset_extension_for",
    "collect_asset_paths",
    "decode_prefab_binary",
    "path_is_known",
    "plan_prefab_path_edits",
    "pointer_sites",
    "prefab_binary_error",
    "rewrite_prefab_paths",
    "rewrite_prefab_placements",
]
