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


def prefab_source_digest(*args: Any, **kwargs: Any) -> Any:
    from cdmw.core.prefab_binary_edit import prefab_source_digest as owner

    return owner(*args, **kwargs)


def __getattr__(name: str) -> Any:
    """Re-export owned dataclasses lazily.

    Callers need :class:`PrefabPathEdit` as a type, not just as a factory, so a
    wrapper function will not do -- but importing it eagerly would pull
    ``cdmw.core`` in at module load, which is exactly what this facade exists
    to prevent.
    """
    if name in {"PrefabPathEdit", "PrefabPlacementEdit", "PrefabRewriteResult"}:
        from cdmw.core import prefab_binary_edit

        return getattr(prefab_binary_edit, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def rewrite_prefab_placements(*args, **kwargs):
    from cdmw.core.prefab_binary_edit import rewrite_prefab_placements as owner

    return owner(*args, **kwargs)


def recover_pointee_strings(*args: Any, **kwargs: Any) -> Any:
    from cdmw.core.prefab_binary import recover_pointee_strings as owner

    return owner(*args, **kwargs)


def rewrite_prefab_paths_same_length(*args: Any, **kwargs: Any) -> Any:
    from cdmw.core.prefab_binary_edit import rewrite_prefab_paths_same_length as owner

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
    "PrefabPathEdit",
    "prefab_source_digest",
    "pointer_sites",
    "prefab_binary_error",
    "recover_pointee_strings",
    "rewrite_prefab_paths",
    "rewrite_prefab_paths_same_length",
    "rewrite_prefab_placements",
]
