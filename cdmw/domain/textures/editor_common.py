"""Shared dependency-free Texture Editor value rules."""

from __future__ import annotations

import uuid
from typing import Tuple


def safe_texture_editor_slug(value: str) -> str:
    cleaned = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in value.strip())
    cleaned = "_".join(part for part in cleaned.split("_") if part)
    return cleaned or "texture_editor"


def normalize_texture_editor_hex(value: str, fallback: str) -> str:
    text = value.strip().upper()
    if not text:
        return fallback.upper()
    if not text.startswith("#"):
        text = f"#{text}"
    if len(text) != 7:
        return fallback.upper()
    try:
        int(text[1:], 16)
    except ValueError:
        return fallback.upper()
    return text


def parse_texture_editor_hex_rgb(value: str, fallback: str = "#C85A30") -> Tuple[int, int, int]:
    text = normalize_texture_editor_hex(value, fallback)
    return (int(text[1:3], 16), int(text[3:5], 16), int(text[5:7], 16))


def new_texture_editor_layer_id() -> str:
    return uuid.uuid4().hex[:12]


# Private compatibility names remain direct aliases, preserving object identity.
_new_layer_id = new_texture_editor_layer_id
_normalize_hex = normalize_texture_editor_hex
_parse_hex_rgb = parse_texture_editor_hex_rgb
_safe_slug = safe_texture_editor_slug


__all__ = [
    "new_texture_editor_layer_id",
    "normalize_texture_editor_hex",
    "parse_texture_editor_hex_rgb",
    "safe_texture_editor_slug",
]
