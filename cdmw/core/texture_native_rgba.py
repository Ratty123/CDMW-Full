"""Read a DDS straight into RGBA8 pixels, without a PNG in between.

The Texture Editor wants the pixels in memory. Going through a PNG compresses a 4096 px
texture in the helper and decompresses it again here, which is most of the wait. The
helper's ``rgba8_raw`` container holds the same final pixels behind a 32-byte header.

Every way this can fail returns ``None``: the caller then takes the PNG route, which
reports the problem as it always has. A helper built before the container existed
ignores the request and writes a PNG; that file is used as it is.
"""

from __future__ import annotations

import json
import struct
import threading
from contextlib import ExitStack
from pathlib import Path
from typing import Optional

import numpy as np
from PIL import Image

from cdmw.core import texture_native as backend
from cdmw.core.common import raise_if_cancelled, run_process_with_cancellation
from cdmw.core.filesystem import filesystem_path
from cdmw.core.temp_cache import (
    DIRECTXTEX_TEXTURE_PREVIEW_CACHE_DIRNAME,
    app_temp_cache_path,
    app_temp_cache_use,
)
from cdmw.core.texture_decode_cache import preview_staging_dir
from cdmw.models import RunCancelled

RGBA8_RAW_CONTAINER = "rgba8_raw"
_RAW_MAGIC = b"CDMWRGBA"
_RAW_HEADER = struct.Struct("<8sIIIIQ")
_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def _full_size_request(source_path: Path, output_path: Path) -> backend.NativeTextureDecodeRequest:
    # What the Texture Editor has always asked for: mip 0, no size cap, colour as stored.
    return backend.NativeTextureDecodeRequest(
        input_path=source_path,
        output_path=output_path,
        max_dimension=0,
        requested_mip=0,
        output_pixel_type="rgba8",
        slot_kind="base",
        normal_space="auto",
    )


def _cached_full_size_png_exists(source_path: Path, binary: Path) -> bool:
    try:
        cached = backend._directxtex_preview_cache_path(
            source_path,
            max_dimension=0,
            slot_kind="base",
            srgb="auto",
            normal_space="auto",
            requested_mip=0,
            output_pixel_type="rgba8",
            binary=binary,
        )
        return backend._cached_preview_is_valid(cached)
    except (OSError, ValueError):
        return False


def _raw_staging_root() -> Path:
    # Beside the PNG previews, in the temporary cache: a 4096 px texture is 64 MB of
    # pixels and an 8192 px one 256 MB, held for the moment between the helper writing
    # them and this process reading them. A project folder can sit on a slow disk.
    return filesystem_path(app_temp_cache_path(DIRECTXTEX_TEXTURE_PREVIEW_CACHE_DIRNAME, "raw-pixels"))


def read_rgba8_raw(path: Path, *, width: int, height: int) -> Optional[np.ndarray]:
    """The pixels of a ``rgba8_raw`` file, or ``None`` unless it is exactly as reported."""

    try:
        with path.open("rb") as handle:
            header = handle.read(_RAW_HEADER.size)
        if len(header) != _RAW_HEADER.size:
            return None
        magic, version, raw_width, raw_height, bytes_per_pixel, payload_bytes = _RAW_HEADER.unpack(header)
        expected = int(width) * int(height) * 4
        if (
            magic != _RAW_MAGIC
            or version != 1
            or bytes_per_pixel != 4
            or raw_width != int(width)
            or raw_height != int(height)
            or expected <= 0
            or payload_bytes != expected
            or path.stat().st_size != _RAW_HEADER.size + expected
        ):
            return None
        pixels = np.fromfile(path, dtype=np.uint8, count=expected, offset=_RAW_HEADER.size)
    except (OSError, ValueError, struct.error):
        return None
    if pixels.size != expected:
        return None
    return pixels.reshape(int(height), int(width), 4)


def decode_dds_rgba8_with_directxtex(
    dds_path: Path,
    *,
    staging_parent: Optional[Path] = None,
    stop_event: Optional[threading.Event] = None,
) -> Optional[np.ndarray]:
    """Mip 0 of ``dds_path`` as an owned ``(height, width, 4)`` uint8 array, or ``None``."""

    raise_if_cancelled(stop_event, "DirectXTex preview conversion cancelled.")
    binary = backend.find_directxtex_texture_binary()
    if binary is None:
        return None
    try:
        source_path = Path(dds_path).expanduser().resolve()
    except OSError:
        return None
    if not source_path.is_file() or backend._dds_decode_rejection_reason(source_path):
        return None
    if _cached_full_size_png_exists(source_path, binary):
        return None  # already decoded for another view: that file opens faster than a new decode
    try:
        with ExitStack() as stack:
            if staging_parent is None:
                staging_parent = _raw_staging_root()
                stack.enter_context(app_temp_cache_use(staging_parent))
            job_root = stack.enter_context(preview_staging_dir(Path(staging_parent)))
            staged = job_root / "0000.rgba"
            job_path = job_root / "job.json"
            report_path = job_root / "report.json"
            request = _full_size_request(source_path, staged)
            job = backend._decode_request_payload(request, output_path=staged)
            job["output_container"] = RGBA8_RAW_CONTAINER
            job_path.write_text(
                json.dumps(
                    {
                        "version": backend.NATIVE_TEXTURE_PROTOCOL_VERSION,
                        "backend": backend.DIRECTXTEX_TEXTURE_BACKEND_ID,
                        "jobs": [job],
                    }
                ),
                encoding="utf-8",
            )
            returncode, _stdout, _stderr = run_process_with_cancellation(
                [
                    str(binary),
                    "batch-preview-json",
                    str(job_path),
                    str(report_path),
                    *backend._native_diagnostic_args(),
                ],
                timeout_seconds=backend.native_decode_timeout_seconds((request,)),
                stop_event=stop_event,
            )
            if returncode != 0 or not report_path.is_file() or not staged.is_file():
                return None
            items = json.loads(report_path.read_text(encoding="utf-8")).get("items")
            item = items[0] if isinstance(items, list) and len(items) == 1 else None
            if not isinstance(item, dict) or str(item.get("status") or "").lower() != "decoded":
                return None
            if str(item.get("output_container") or "") == RGBA8_RAW_CONTAINER:
                return read_rgba8_raw(
                    staged,
                    width=int(item.get("prepared_width") or 0),
                    height=int(item.get("prepared_height") or 0),
                )
            with staged.open("rb") as handle:
                is_png = handle.read(len(_PNG_SIGNATURE)) == _PNG_SIGNATURE
            if not is_png:
                return None
            # An older helper: it wrote the PNG it knows. The pixels are the same.
            with Image.open(staged) as image:
                return np.asarray(image.convert("RGBA"), dtype=np.uint8).copy()
    except RunCancelled:
        raise
    except Exception:
        return None


__all__ = ["RGBA8_RAW_CONTAINER", "decode_dds_rgba8_with_directxtex", "read_rgba8_raw"]
