"""Texture semantic lookup helpers."""

from __future__ import annotations

from collections.abc import Mapping

from cdmw.domain.textures.profiles import _DEFAULT_SEMANTIC_SUBTYPES


def default_semantic_subtypes() -> Mapping[str, tuple[str, ...]]:
    return dict(_DEFAULT_SEMANTIC_SUBTYPES)


__all__ = ["default_semantic_subtypes"]
