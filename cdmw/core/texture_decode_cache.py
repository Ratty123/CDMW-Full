from __future__ import annotations

import binascii
import json
import os
import shutil
import tempfile
import threading
from contextlib import contextmanager
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterator, Mapping, Sequence

_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
_LOCK_STRIPE_COUNT = 64
_LOCK_STRIPES = tuple(threading.Lock() for _ in range(_LOCK_STRIPE_COUNT))


def preview_sidecar_path(png_path: Path) -> Path:
    return png_path.with_name(f"{png_path.name}.cdmw_texture.json")


def preview_png_is_valid(path: Path) -> bool:
    try:
        stat = path.stat()
    except OSError:
        return False
    return _preview_png_stream_is_valid(
        str(path.absolute()),
        max(0, int(stat.st_size)),
        int(stat.st_mtime_ns),
    )


@lru_cache(maxsize=8192)
def _preview_png_stream_is_valid(
    path_text: str,
    file_size: int,
    modified_ns: int,
) -> bool:
    del modified_ns
    try:
        with Path(path_text).open("rb") as stream:
            if stream.read(8) != _PNG_SIGNATURE:
                return False
            saw_header = False
            saw_image_data = False
            while stream.tell() < file_size:
                length_bytes = stream.read(4)
                chunk_type = stream.read(4)
                if len(length_bytes) != 4 or len(chunk_type) != 4:
                    return False
                chunk_length = int.from_bytes(length_bytes, "big")
                if chunk_length < 0 or chunk_length + 4 > file_size - stream.tell():
                    return False
                checksum = binascii.crc32(chunk_type)
                header_data = bytearray()
                remaining = chunk_length
                while remaining:
                    block = stream.read(min(64 * 1024, remaining))
                    if not block:
                        return False
                    if chunk_type == b"IHDR":
                        header_data.extend(block)
                    checksum = binascii.crc32(block, checksum)
                    remaining -= len(block)
                expected_checksum = stream.read(4)
                if len(expected_checksum) != 4 or (
                    checksum & 0xFFFFFFFF
                ) != int.from_bytes(expected_checksum, "big"):
                    return False
                if not saw_header:
                    if chunk_type != b"IHDR" or chunk_length != 13:
                        return False
                    width = int.from_bytes(header_data[0:4], "big")
                    height = int.from_bytes(header_data[4:8], "big")
                    if width <= 0 or height <= 0 or header_data[8] not in {
                        1,
                        2,
                        4,
                        8,
                        16,
                    }:
                        return False
                    saw_header = True
                elif chunk_type == b"IHDR":
                    return False
                if chunk_type == b"IDAT":
                    saw_image_data = True
                if chunk_type == b"IEND":
                    return (
                        chunk_length == 0
                        and saw_header
                        and saw_image_data
                        and stream.tell() == file_size
                    )
    except OSError:
        return False
    return False


def preview_sidecar_is_valid(path: Path) -> bool:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return False
    if not isinstance(payload, dict):
        return False
    status = str(payload.get("status") or "").strip().lower()
    return bool(status) and status not in {"error", "failed", "cancelled"}


def preview_pair_is_valid(png_path: Path) -> bool:
    return preview_png_is_valid(png_path) and preview_sidecar_is_valid(preview_sidecar_path(png_path))


@contextmanager
def preview_cache_locks(keys: Sequence[str]) -> Iterator[None]:
    indexes = sorted({hash(str(key)) % _LOCK_STRIPE_COUNT for key in keys})
    locks = [_LOCK_STRIPES[index] for index in indexes]
    for lock in locks:
        lock.acquire()
    try:
        yield
    finally:
        for lock in reversed(locks):
            lock.release()


def preview_cache_lock_registry_size() -> int:
    return len(_LOCK_STRIPES)


@contextmanager
def preview_staging_dir(final_dir: Path) -> Iterator[Path]:
    final_dir.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=".decode-staging-", dir=str(final_dir)))
    try:
        yield staging
    finally:
        shutil.rmtree(staging, ignore_errors=True)


def publish_preview_pair(staged_png: Path, final_png: Path, report: Mapping[str, Any]) -> Path:
    if preview_pair_is_valid(final_png):
        return final_png
    if not preview_png_is_valid(staged_png):
        raise ValueError(f"Preview helper produced an invalid PNG: {staged_png}")
    final_png.parent.mkdir(parents=True, exist_ok=True)
    staged_sidecar = preview_sidecar_path(staged_png)
    final_sidecar = preview_sidecar_path(final_png)
    normalized_report = dict(report)
    normalized_report["output_path"] = str(final_png)
    staged_sidecar.write_text(json.dumps(normalized_report, indent=2, sort_keys=True), encoding="utf-8")
    if not preview_sidecar_is_valid(staged_sidecar):
        raise ValueError(f"Preview helper produced an invalid report sidecar: {staged_sidecar}")
    _remove_invalid_pair(final_png)
    try:
        os.replace(staged_sidecar, final_sidecar)
        os.replace(staged_png, final_png)
        if not preview_pair_is_valid(final_png):
            raise ValueError(f"Published preview cache entry failed validation: {final_png}")
    except Exception:
        _safe_unlink(final_png)
        _safe_unlink(final_sidecar)
        raise
    return final_png


def _remove_invalid_pair(png_path: Path) -> None:
    if preview_pair_is_valid(png_path):
        return
    _safe_unlink(png_path)
    _safe_unlink(preview_sidecar_path(png_path))


def _safe_unlink(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass
