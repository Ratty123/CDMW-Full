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


def prefab_binary_error() -> type[Exception]:
    """The exception type raised for payloads that break the grammar."""
    from cdmw.core.prefab_binary import PrefabBinaryError

    return PrefabBinaryError


__all__ = [
    "decode_prefab_binary",
    "plan_prefab_path_edits",
    "pointer_sites",
    "prefab_binary_error",
    "rewrite_prefab_paths",
]
