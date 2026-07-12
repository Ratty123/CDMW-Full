"""Pure archive extension and text-payload rules."""

from __future__ import annotations

from typing import Optional

from cdmw.constants import ARCHIVE_TEXT_PREVIEW_LIMIT


ARCHIVE_MATERIAL_SIDECAR_EXTENSIONS: frozenset[str] = frozenset(
    {".pami", ".pac_xml", ".pam_xml", ".pamlod_xml"}
)
ARCHIVE_METADATA_XML_EXTENSIONS: frozenset[str] = frozenset(
    {".xml", ".app_xml", ".prefabdata_xml"}
)
ARCHIVE_XML_LIKE_EXTENSIONS: frozenset[str] = (
    ARCHIVE_MATERIAL_SIDECAR_EXTENSIONS | ARCHIVE_METADATA_XML_EXTENSIONS
)


def is_material_sidecar_extension(extension: str, basename: str = "") -> bool:
    normalized_extension = str(extension or "").strip().lower()
    normalized_basename = str(basename or "").strip().lower()
    return normalized_extension in ARCHIVE_MATERIAL_SIDECAR_EXTENSIONS or (
        normalized_extension == ".xml"
        and normalized_basename.endswith((".pac.xml", ".pam.xml", ".pamlod.xml"))
    )


def normalize_archive_extension_filter(extension_filter: str) -> str:
    normalized_extension = str(extension_filter or "").strip().lower()
    if normalized_extension == "all files":
        return "*"
    if normalized_extension.startswith("all files."):
        normalized_extension = normalized_extension.removeprefix("all files")
    if not normalized_extension or normalized_extension in {"*", "all", ".*"}:
        return normalized_extension
    return normalized_extension if normalized_extension.startswith(".") else f".{normalized_extension}"


def try_decode_text_like_archive_data(data: bytes) -> Optional[str]:
    if not data:
        return None

    preview_bytes = data[:ARCHIVE_TEXT_PREVIEW_LIMIT]
    for bom, encoding in (
        (b"\xef\xbb\xbf", "utf-8-sig"),
        (b"\xff\xfe", "utf-16-le"),
        (b"\xfe\xff", "utf-16-be"),
    ):
        if preview_bytes.startswith(bom):
            text = preview_bytes.decode(encoding, errors="replace")
            return text if text.strip("\ufeff\r\n\t ") else None

    sample = preview_bytes[:4096]
    if not sample or sample.count(0) > max(2, len(sample) // 100):
        return None
    printable_count = sum(1 for value in sample if value in (9, 10, 13) or 32 <= value <= 126)
    stripped_sample = sample.lstrip(b"\xef\xbb\xbf\r\n\t ")
    if printable_count / len(sample) < 0.92 and not stripped_sample.startswith((b"<?xml", b"<", b"{", b"[")):
        return None

    text = preview_bytes.decode("utf-8", errors="replace")
    non_whitespace = [char for char in text[:1024] if not char.isspace()]
    if not non_whitespace:
        return None
    control_count = sum(1 for char in non_whitespace if ord(char) < 32 and char not in "\r\n\t")
    return None if control_count > max(2, len(non_whitespace) // 20) else text


__all__ = [
    "ARCHIVE_MATERIAL_SIDECAR_EXTENSIONS",
    "ARCHIVE_METADATA_XML_EXTENSIONS",
    "ARCHIVE_XML_LIKE_EXTENSIONS",
    "is_material_sidecar_extension",
    "normalize_archive_extension_filter",
    "try_decode_text_like_archive_data",
]
