"""Texture workflow validation helpers."""

from __future__ import annotations

from cdmw.domain.textures.profiles import get_texture_processing_profile_keys


def is_known_texture_profile_key(profile_key: str) -> bool:
    return str(profile_key or "").strip() in set(get_texture_processing_profile_keys())


__all__ = ["is_known_texture_profile_key"]
