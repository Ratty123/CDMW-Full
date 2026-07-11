from __future__ import annotations

import hashlib
import mimetypes
import tempfile
from pathlib import Path
from typing import Any, AbstractSet

from cdmw.core.atomic_file import atomic_write_bytes

from .scene_gltf_uv import _validate_gltf_image_payload


_MIME_EXTENSIONS = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/jpg": ".jpg",
    "image/vnd-ms.dds": ".dds",
    "image/x-dds": ".dds",
    "image/tga": ".tga",
    "image/bmp": ".bmp",
    "image/tiff": ".tif",
    "image/webp": ".webp",
    "image/ktx": ".ktx",
    "image/ktx2": ".ktx2",
}


def write_embedded_gltf_image(
    payload: Any,
    image_index: int,
    data: bytes,
    mime_type: str,
    supported_extensions: AbstractSet[str],
) -> Path:
    ext = _MIME_EXTENSIONS.get(str(mime_type or "").lower(), "")
    if not ext:
        guessed = mimetypes.guess_extension(str(mime_type or "")) or ""
        ext = guessed if guessed.lower() in supported_extensions else ".bin"
    _validate_gltf_image_payload(data, image_index, ext)
    export_dir = _embedded_gltf_extract_dir(payload.source_path)
    export_dir.mkdir(parents=True, exist_ok=True)
    path = export_dir / f"image_{image_index}{ext}"
    try:
        unchanged = path.is_file() and path.stat().st_size == len(data) and path.read_bytes() == data
    except OSError:
        unchanged = False
    if not unchanged:
        atomic_write_bytes(path, data)
    payload.extracted_embedded_files.append(path.resolve())
    return path.resolve()


def _embedded_gltf_extract_dir(source_path: Path) -> Path:
    try:
        stat = source_path.stat()
        key = f"{source_path}|{stat.st_mtime_ns}|{stat.st_size}"
    except OSError:
        key = str(source_path)
    digest = hashlib.sha1(key.encode("utf-8", errors="ignore")).hexdigest()[:16]
    return Path(tempfile.gettempdir()) / "cdmw_gltf_imports" / digest


__all__ = ["write_embedded_gltf_image"]
