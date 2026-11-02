"""Read-only inspectors for the small metadata files the October 2026 DLC update added.

Each layout below was read from the shipped files of game 1.0.0.3446; what the
fields mean to the game is not established, so the inspectors show them as read.

* `.admeta` (`gamedata/binarymisc__/bin/dlc_01.admeta`): u32 name length, the DLC
  id in ASCII (`dlc_01`), then one u32 (1).
* `.contentgroupkeymap` (`base` and `dlc_01`): u32 count, then that many u32 keys
  (base 999000, 998003, 0, 8, 10, 11; DLC 1001-1006 without 1004, and 998002).
* `.binarygimmickcacheddata` (`gimmickchartcacheddata.<layer>`): three u32 header
  fields, the first a count that tracks the layer's size (base 14,210, DLC 1,503),
  then records whose first 64 bytes are identical in both layers.
"""
from __future__ import annotations

import struct
from dataclasses import dataclass

DLC_METADATA_EXTENSIONS = frozenset({".admeta", ".contentgroupkeymap", ".binarygimmickcacheddata"})
_MAX_KEYS = 4096


class DlcMetadataError(ValueError):
    """The bytes do not have the layout the shipped DLC metadata files have."""


@dataclass(frozen=True)
class DlcMetadataPreview:
    metadata_label: str
    preview_text: str
    detail_lines: tuple[str, ...]


def _u32(data: bytes, offset: int) -> int:
    if offset + 4 > len(data):
        raise DlcMetadataError("The file ends inside a 32-bit field.")
    return struct.unpack_from("<I", data, offset)[0]


def _admeta(data: bytes, virtual_path: str) -> DlcMetadataPreview:
    length = _u32(data, 0)
    end = 4 + length
    if length == 0 or length > 64 or end + 4 != len(data):
        raise DlcMetadataError("The DLC id length does not match the file size.")
    try:
        name = data[4:end].decode("ascii")
    except UnicodeDecodeError as exc:
        raise DlcMetadataError("The DLC id is not ASCII text.") from exc
    value = _u32(data, end)
    lines = [f"DLC metadata for {virtual_path}", "", f"DLC id: {name}", f"Value after the id: {value}"]
    return DlcMetadataPreview(f"DLC id {name}", "\n".join(lines),
                              ("The meaning of the value after the DLC id is not known.",))


def _content_group_keys(data: bytes, virtual_path: str) -> DlcMetadataPreview:
    count = _u32(data, 0)
    if count > _MAX_KEYS or 4 + count * 4 != len(data):
        raise DlcMetadataError("The key count does not match the file size.")
    keys = struct.unpack_from(f"<{count}I", data, 4)
    lines = [f"Content group key map for {virtual_path}", "", f"Keys: {count}"]
    lines.extend(f"  {index}: {key}" for index, key in enumerate(keys))
    return DlcMetadataPreview(f"{count} content group keys", "\n".join(lines),
                              ("Which content groups these keys select is not known.",))


def _gimmick_cache(data: bytes, virtual_path: str) -> DlcMetadataPreview:
    if len(data) < 12:
        raise DlcMetadataError("The gimmick cache header is truncated.")
    count, second, third = struct.unpack_from("<3I", data, 0)
    lines = [f"Gimmick chart cache for {virtual_path}", "", f"Record count: {count:,}",
             f"Header field 2: 0x{second:08X}", f"Header field 3: {third}", f"Size: {len(data):,} bytes"]
    return DlcMetadataPreview(f"{count:,} cached gimmick records", "\n".join(lines), (
        "The record layout after the header is not decoded.",
        "This cache is probably built from the .binarygimmick charts; a mod that changes those charts may need it rebuilt.",
    ))


def build_dlc_metadata_preview(data: bytes, virtual_path: str, *, extension: str) -> DlcMetadataPreview:
    """Describe a DLC metadata file; raises `DlcMetadataError` when its layout differs."""
    normalized = str(extension or "").lower()
    if normalized == ".admeta":
        return _admeta(data, virtual_path)
    if normalized == ".contentgroupkeymap":
        return _content_group_keys(data, virtual_path)
    if normalized == ".binarygimmickcacheddata":
        return _gimmick_cache(data, virtual_path)
    raise DlcMetadataError(f"No DLC metadata inspector for {normalized or 'this file'}.")


__all__ = ["DLC_METADATA_EXTENSIONS", "DlcMetadataError", "DlcMetadataPreview", "build_dlc_metadata_preview"]
