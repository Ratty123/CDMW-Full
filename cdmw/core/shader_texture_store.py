"""Textures a user chose for a shader experiment, kept by content.

A shader-control edit names its replacement textures by SHA-256 only, so drafts
and undo steps stay small. The bytes live here, on this computer, beside the
other CDMW records, and are never changed once written.
"""

from __future__ import annotations

import hashlib
import os
import re
from pathlib import Path
from uuid import uuid4

from cdmw.constants import APP_NAME

DDS_MAGIC = b"DDS "
MAX_TEXTURE_BYTES = 256 * 1024 * 1024
_ENVIRONMENT_ROOT = "CDMW_SHADER_TEXTURE_STORE"
_DIGEST = re.compile(r"[0-9a-f]{64}")


def store_root() -> Path:
    override = os.environ.get(_ENVIRONMENT_ROOT, "").strip()
    if override:
        return Path(override)
    local = os.environ.get("LOCALAPPDATA", "").strip()
    return (Path(local) if local else Path.home() / ".local" / "share") / APP_NAME / "shader_textures"


def is_texture_digest(value: object) -> bool:
    return isinstance(value, str) and _DIGEST.fullmatch(value) is not None


def _path(digest: str) -> Path:
    if not is_texture_digest(digest):
        raise ValueError("Invalid replacement texture reference.")
    return store_root() / f"{digest}.dds"


def store_texture(data: bytes) -> str:
    """Keep one DDS and return the SHA-256 that names it."""

    payload = bytes(data)
    if not payload.startswith(DDS_MAGIC) or len(payload) < 128:
        raise ValueError("The replacement texture is not a DDS file.")
    if len(payload) > MAX_TEXTURE_BYTES:
        raise ValueError("The replacement texture exceeds the 256 MiB limit.")
    digest = hashlib.sha256(payload).hexdigest()
    target = _path(digest)
    if not target.is_file() or target.stat().st_size != len(payload):
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_name(f"{target.name}.{uuid4().hex[:8]}.tmp")
        temporary.write_bytes(payload)
        os.replace(temporary, target)
    return digest


def read_texture(digest: str) -> bytes:
    target = _path(digest)
    try:
        payload = target.read_bytes()
    except OSError as exc:
        raise ValueError(
            "A replacement texture of this edit is no longer on this computer. Choose the texture again."
        ) from exc
    if hashlib.sha256(payload).hexdigest() != digest:
        raise ValueError("A stored replacement texture has been changed. Choose the texture again.")
    return payload


__all__ = ["DDS_MAGIC", "is_texture_digest", "read_texture", "store_root", "store_texture"]
