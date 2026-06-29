from __future__ import annotations

import hashlib
import json
import math
import os
import re
import struct
import threading
from collections import Counter, defaultdict
from pathlib import Path, PurePosixPath
from typing import Callable, Dict, List, Mapping, Optional, Sequence, Tuple

from cdmw.constants import ARCHIVE_BINARY_HEX_PREVIEW_LIMIT, ARCHIVE_TEXT_PREVIEW_LIMIT
from cdmw.models import ArchiveEntry, ArchiveModelTextureReference
from cdmw.core.common import RunCancelled, raise_if_cancelled
from cdmw.core.archive_extraction import format_byte_size
from cdmw.core.archive_filtering import (
    _STRUCTURED_BINARY_ASSET_REFERENCE_EXTENSIONS,
    _STRUCTURED_BINARY_ASSET_SEGMENT_RE,
    _STRUCTURED_BINARY_ASSET_TOKEN_RE,
    _STRUCTURED_BINARY_IDENTIFIER_RE,
)
from cdmw.core.archive_format import (
    _ARCHIVE_ANIMATION_SEQUENCE_EXTENSIONS,
    _PRINTABLE_BINARY_STRING_RE,
)
from cdmw.core.archive_model_references import (
    _BinarySidecarStringRecord,
    _find_archive_model_related_entries,
    _normalize_model_texture_reference,
)
from cdmw.core.upscale_profiles import parse_texture_sidecar_bindings


def _archive_core():
    from cdmw.core import archive as archive_core

    return archive_core


def _prefab_evidence_rows(*args, **kwargs):
    return _archive_core()._prefab_evidence_rows(*args, **kwargs)


def _prefab_material_override_evidence_rows(*args, **kwargs):
    return _archive_core()._prefab_material_override_evidence_rows(*args, **kwargs)


def build_archive_related_file_references(*args, **kwargs):
    return _archive_core().build_archive_related_file_references(*args, **kwargs)


def build_archive_relationship_references(*args, **kwargs):
    return _archive_core().build_archive_relationship_references(*args, **kwargs)


def merge_archive_reference_rows(*args, **kwargs):
    return _archive_core().merge_archive_reference_rows(*args, **kwargs)

def format_binary_header_preview(data: bytes) -> str:
    if not data:
        return "No bytes available."
    lines: List[str] = []
    for offset in range(0, min(len(data), ARCHIVE_BINARY_HEX_PREVIEW_LIMIT), 16):
        chunk = data[offset : offset + 16]
        hex_part = " ".join(f"{value:02X}" for value in chunk)
        ascii_part = "".join(chr(value) if 32 <= value <= 126 else "." for value in chunk)
        lines.append(f"{offset:04X}  {hex_part:<47}  {ascii_part}")
    return "\n".join(lines)


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
    if not sample:
        return None
    if sample.count(0) > max(2, len(sample) // 100):
        return None

    printable_count = sum(1 for value in sample if value in (9, 10, 13) or 32 <= value <= 126)
    likely_text = printable_count / max(len(sample), 1) >= 0.92
    stripped_sample = sample.lstrip(b"\xef\xbb\xbf\r\n\t ")
    if not likely_text and not stripped_sample.startswith((b"<?xml", b"<", b"{", b"[")):
        return None

    text = preview_bytes.decode("utf-8", errors="replace")
    non_whitespace = [char for char in text[:1024] if not char.isspace()]
    if not non_whitespace:
        return None
    control_count = sum(1 for char in non_whitespace if ord(char) < 32 and char not in "\r\n\t")
    if control_count > max(2, len(non_whitespace) // 20):
        return None
    return text


def extract_binary_strings(data: bytes, *, sample_limit: int = 131_072, max_strings: int = 48) -> List[str]:
    sample = data[:sample_limit]
    strings: List[str] = []
    seen: set[str] = set()
    for match in _PRINTABLE_BINARY_STRING_RE.finditer(sample):
        text = match.group().decode("ascii", errors="ignore").strip()
        letter_count = sum(1 for char in text if char.isalpha())
        if len(text) < 4 or text in seen or letter_count == 0:
            continue
        allowed_char_count = sum(1 for char in text if char.isalnum() or char in " _./:-[](){}")
        if allowed_char_count / max(len(text), 1) < 0.85:
            continue
        if len(text) < 12 and letter_count < 4:
            continue
        if "_" not in text and "/" not in text and "::" not in text and " " not in text and len(text) < 12:
            continue
        if len(text) > 160:
            text = text[:157] + "..."
        seen.add(text)
        strings.append(text)
        if len(strings) >= max_strings:
            break
    return strings


def build_binary_strings_preview(data: bytes, *, sample_limit: int = 131_072, max_strings: int = 48) -> str:
    strings = extract_binary_strings(data, sample_limit=sample_limit, max_strings=max_strings)
    if not strings:
        return ""
    scanned_size = min(len(data), sample_limit)
    lines = [f"Readable strings from the first {format_byte_size(scanned_size)} of binary data:"]
    lines.extend(strings)
    if len(data) > sample_limit:
        lines.extend(["", "String scan truncated to keep the preview responsive."])
    return "\n".join(lines)


def _looks_like_structured_field_name(value: str) -> bool:
    text = str(value or "").strip()
    if len(text) < 3 or len(text) > 128:
        return False
    if "/" in text or "\\" in text:
        return False
    if "." in text and "::" not in text:
        return False
    if " " in text or "\t" in text:
        return False
    if not _STRUCTURED_BINARY_IDENTIFIER_RE.fullmatch(text):
        return False
    return any(character.isalpha() for character in text)


def _looks_like_structured_asset_reference(value: str) -> bool:
    raw_text = str(value or "").strip().strip("\x00")
    if len(raw_text) < 3 or len(raw_text) > 255:
        return False
    normalized_text = raw_text.replace("\\", "/")
    if normalized_text.startswith("/") or normalized_text.endswith("/"):
        return False
    if "//" in normalized_text:
        return False
    suffix = PurePosixPath(normalized_text).suffix.lower()
    if suffix not in _STRUCTURED_BINARY_ASSET_REFERENCE_EXTENSIONS:
        return False
    segments = normalized_text.split("/")
    if not segments:
        return False
    for segment in segments:
        if not segment or not _STRUCTURED_BINARY_ASSET_SEGMENT_RE.fullmatch(segment):
            return False
    return any(character.isalpha() for character in normalized_text)


def _clean_structured_binary_asset_token(value: str) -> str:
    raw_text = str(value or "").strip().strip("\x00").replace("\\", "/")
    if _looks_like_structured_asset_reference(raw_text):
        return raw_text
    lowered = raw_text.lower()
    for extension in sorted(_STRUCTURED_BINARY_ASSET_REFERENCE_EXTENSIONS, key=len, reverse=True):
        marker = str(extension or "").lower()
        if not marker:
            continue
        index = lowered.rfind(marker)
        if index < 0:
            continue
        end = index + len(marker)
        suffix = lowered[end:]
        if not suffix or len(suffix) > 2 or not re.fullmatch(r"[a-z0-9]{1,2}", suffix):
            continue
        candidate = raw_text[:end]
        if _looks_like_structured_asset_reference(candidate):
            return candidate
    return raw_text


def _extract_binary_asset_references(
    data: bytes,
    *,
    sample_limit: int = 262_144,
    max_references: int = 64,
) -> List[str]:
    references: List[str] = []
    seen: set[str] = set()
    for text in extract_binary_strings(data, sample_limit=sample_limit, max_strings=max(max_references * 6, 96)):
        for match in _STRUCTURED_BINARY_ASSET_TOKEN_RE.finditer(text):
            raw_text = _clean_structured_binary_asset_token(match.group(0))
            if not _looks_like_structured_asset_reference(raw_text):
                continue
            raw_text = raw_text.replace("\\", "/")
            normalized = _normalize_model_texture_reference(raw_text)
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            references.append(raw_text)
            if len(references) >= max_references:
                return references
    return references


def _extract_text_asset_references(
    text: str,
    *,
    sidecar_path: str = "",
    max_references: int = 96,
) -> List[str]:
    references: List[str] = []
    seen: set[str] = set()

    def add_reference(raw_value: str) -> None:
        raw_text = str(raw_value or "").strip().strip("\x00").replace("\\", "/")
        if not _looks_like_structured_asset_reference(raw_text):
            return
        normalized = _normalize_model_texture_reference(raw_text)
        if not normalized or normalized in seen:
            return
        seen.add(normalized)
        references.append(raw_text)

    for binding in parse_texture_sidecar_bindings(text, sidecar_path=sidecar_path):
        add_reference(binding.texture_path)
        if len(references) >= max_references:
            return references

    for match in _STRUCTURED_BINARY_ASSET_TOKEN_RE.finditer(text):
        add_reference(str(match.group(0) or ""))
        if len(references) >= max_references:
            return references
    return references


def _structured_field_type_hint(name: str) -> str:
    normalized = str(name or "").strip().lstrip("_").lower()
    if not normalized:
        return "field"
    if "reflectobject" in normalized or normalized.endswith("ptr") or "referencepath" in normalized:
        return "object ref"
    if "list" in normalized or "container" in normalized or "array" in normalized:
        return "list"
    if normalized.startswith(("is", "use", "enable", "disable", "auto", "apply", "has")):
        return "bool"
    if any(token in normalized for token in ("boundingbox", "bbox", "bound", "extent", "position", "rotation", "scale", "offset", "radius")):
        return "vector"
    if normalized.endswith(("type", "enum", "flag", "flags", "layer", "group")):
        return "enum/flag"
    return "field"


def _group_meshinfo_field_name(name: str) -> str:
    normalized = str(name or "").strip().lstrip("_").lower()
    if not normalized:
        return "Misc"
    if any(token in normalized for token in ("boundingbox", "bbox", "bound", "extent", "volume", "radius", "min", "max")):
        return "Bounds"
    if any(token in normalized for token in ("socket", "anchor", "attach")):
        return "Sockets"
    if any(token in normalized for token in ("tree", "branch", "cutting")):
        return "Tree"
    if any(token in normalized for token in ("break", "support", "fade", "convex", "fracture")):
        return "Breakable"
    if any(token in normalized for token in ("collision", "collidable", "constraint", "group", "layer")):
        return "Collision"
    if any(token in normalized for token in ("physics", "motion", "mass", "buoyancy", "dynamic", "pbd", "wind", "material")):
        return "Physics"
    if any(token in normalized for token in ("reflectobject", "vector", "container", "custom", "gamedata", "node")):
        return "Data Model"
    return "Misc"


def _group_animation_field_name(name: str) -> str:
    normalized = str(name or "").strip().lstrip("_").lower()
    if not normalized:
        return "Misc"
    if any(token in normalized for token in ("skeleton", "bone", "rig")):
        return "Skeleton"
    if any(token in normalized for token in ("delaunay", "triangle", "vert", "center")):
        return "Delaunay"
    if any(token in normalized for token in ("animationfilename", "animationfile", "animationdata", "animation")):
        return "Animation Files"
    if any(token in normalized for token in ("parameter", "dimension", "minmax", "smoothing")):
        return "Parameters"
    if any(token in normalized for token in ("phase", "motion", "blend", "speed", "loop", "sync")):
        return "Motion Space"
    if any(token in normalized for token in ("animation", "clip", "frame", "curve", "track", "event")):
        return "Animation"
    if any(token in normalized for token in ("motion", "blend", "space", "parameter")):
        return "Motion / Blend"
    if any(token in normalized for token in ("emitter", "effect", "particle")):
        return "Emitter / Effect"
    if any(token in normalized for token in ("scene", "object", "node", "prefab")):
        return "Scene / Object"
    if any(token in normalized for token in ("resource", "texture", "material", "sound", "audio", "video")):
        return "Resources"
    return "Misc"


_PAA_METABIN_TOKEN_HINTS: Dict[str, Tuple[str, str]] = {
    "nor": ("Motion state", "normal"),
    "abn": ("Motion state", "abnormal / reaction"),
    "dam": ("Action", "damage / hit reaction"),
    "atk": ("Action", "attack"),
    "skill": ("Action", "skill"),
    "move": ("Motion", "movement"),
    "idle": ("Motion", "idle"),
    "std": ("Pose", "standing"),
    "sit": ("Pose", "sitting"),
    "run": ("Motion", "running"),
    "walk": ("Motion", "walking"),
    "jump": ("Motion", "jump"),
    "upper": ("Body region", "upper body"),
    "lower": ("Body region", "lower body"),
    "stt": ("Timeline phase", "start"),
    "ing": ("Timeline phase", "in progress / loop body"),
    "end": ("Timeline phase", "end"),
    "loop": ("Timeline phase", "loop"),
    "f": ("Direction", "forward"),
    "b": ("Direction", "back"),
    "l": ("Direction", "left"),
    "r": ("Direction", "right"),
    "fd": ("Direction", "forward-down"),
    "fu": ("Direction", "forward-up"),
    "cvst": ("Scene use", "conversation / cutscene-style"),
    "quest": ("Scene use", "quest sequence"),
    "camera": ("Scene use", "camera animation"),
}


def _paa_metabin_animation_stem(virtual_path: str) -> str:
    basename = PurePosixPath(str(virtual_path or "").replace("\\", "/")).name
    lowered = basename.lower()
    if lowered.endswith(".paa_metabin"):
        return basename[: -len(".paa_metabin")]
    return PurePosixPath(basename).stem


def _paa_metabin_declared_type_name(data: bytes) -> Tuple[str, int, int]:
    if len(data) >= 0x18:
        name_length = struct.unpack_from("<I", data, 0x14)[0]
        if 0 < name_length <= 128 and 0x18 + name_length <= len(data):
            raw_name = data[0x18 : 0x18 + name_length]
            try:
                type_name = raw_name.decode("ascii", errors="strict").strip("\x00")
            except UnicodeDecodeError:
                type_name = ""
            if type_name and _looks_like_structured_field_name(type_name):
                return type_name, 0x18, int(name_length)
    for record in _extract_binary_string_records(data, sample_limit=4096, max_strings=16):
        if record.text == "AnimationMetaData":
            return record.text, record.offset, len(record.text)
    return "", 0, 0


def _paa_metabin_filename_hint_rows(virtual_path: str) -> List[Dict[str, str]]:
    stem = _paa_metabin_animation_stem(virtual_path)
    tokens = [token for token in re.split(r"[_\-.]+", stem.lower()) if token]
    rows: List[Dict[str, str]] = []
    seen: set[Tuple[str, str, str]] = set()

    def add(kind: str, token: str, meaning: str, confidence: str = "filename_token") -> None:
        key = (kind, token, meaning)
        if key in seen:
            return
        seen.add(key)
        rows.append(
            {
                "kind": kind,
                "token": token,
                "meaning": meaning,
                "confidence": confidence,
            }
        )

    if tokens and tokens[0] == "cd":
        add("Namespace", "cd", "Crimson Desert asset prefix", "filename_convention")
    if len(tokens) >= 2:
        add("Asset code", tokens[1], "character/object/sequence code from filename", "filename_token")
    for token in tokens:
        hint = _PAA_METABIN_TOKEN_HINTS.get(token)
        if hint is None:
            continue
        add(hint[0], token, hint[1])
    if stem:
        add("Animation stem", stem, "same-stem key used to find related animation files", "same_stem_relation_key")
    return rows


def _paa_metabin_header_rows(data: bytes) -> List[Dict[str, object]]:
    rows: List[Dict[str, object]] = []
    if len(data) >= 4:
        rows.append(
            {
                "offset": 0,
                "name": "signature_words",
                "value": f"u16[0]=0x{struct.unpack_from('<H', data, 0)[0]:04X}, u16[1]={struct.unpack_from('<H', data, 2)[0]}",
                "confidence": "stable_in_corpus",
            }
        )
    if len(data) >= 0x18:
        rows.append(
            {
                "offset": 0x14,
                "name": "declared_type_name_length",
                "value": int(struct.unpack_from("<I", data, 0x14)[0]),
                "confidence": "stable_length_prefixed_string",
            }
        )
    for offset, label in ((0x2C, "descriptor_a"), (0x30, "descriptor_b"), (0x38, "descriptor_c"), (0x44, "descriptor_count")):
        if len(data) < offset + 4:
            continue
        be_value = struct.unpack_from(">I", data, offset)[0]
        le_value = struct.unpack_from("<I", data, offset)[0]
        plausible_value = be_value if be_value <= 1_000_000 else le_value
        rows.append(
            {
                "offset": offset,
                "name": label,
                "value": plausible_value,
                "be_u32": be_value,
                "le_u32": le_value,
                "confidence": "stable_descriptor_word_observed",
            }
        )
    return rows


def _paa_metabin_packed_stream_summary(data: bytes) -> Dict[str, object]:
    stream_offset = 0x50 if len(data) > 0x50 else len(data)
    stream = data[stream_offset:]
    marker_counts = {
        f"0x{marker:02X}": int(stream.count(marker))
        for marker in (0x00, 0x01, 0x05, 0x3C, 0x80, 0xFF)
        if stream.count(marker)
    }
    preview_rows: List[Dict[str, object]] = []
    for offset in range(stream_offset, min(len(data), stream_offset + 96), 8):
        chunk = data[offset : min(len(data), offset + 8)]
        if not chunk:
            continue
        preview_rows.append(
            {
                "offset": offset,
                "hex": chunk.hex(" ").upper(),
                "u16_le": [
                    int.from_bytes(chunk[index : index + 2], "little")
                    for index in range(0, len(chunk) - 1, 2)
                ],
                "u16_be": [
                    int.from_bytes(chunk[index : index + 2], "big")
                    for index in range(0, len(chunk) - 1, 2)
                ],
                "confidence": "packed_stream_preview",
            }
        )
    return {
        "stream_offset": stream_offset,
        "stream_size": len(stream),
        "marker_counts": marker_counts,
        "preview_rows": preview_rows,
        "status": "packed_event_or_timing_stream_observed" if stream else "no_metadata_stream_bytes",
        "confidence": "stable_header_plus_experimental_payload",
    }


def _paa_metabin_analysis_document(data: bytes, virtual_path: str) -> Dict[str, object]:
    type_name, type_offset, type_length = _paa_metabin_declared_type_name(data)
    filename_hints = _paa_metabin_filename_hint_rows(virtual_path)
    stream_summary = _paa_metabin_packed_stream_summary(data)
    return {
        "declared_type": type_name or "unknown",
        "declared_type_offset": type_offset,
        "declared_type_length": type_length,
        "animation_stem": _paa_metabin_animation_stem(virtual_path),
        "filename_hints": filename_hints,
        "header_rows": _paa_metabin_header_rows(data),
        "packed_metadata_stream": stream_summary,
        "editing_supported": False,
        "relationship_use": (
            "Useful for linking animation metadata to same-stem .paa/.motionblending/.hkx style animation assets "
            "and for exposing filename-derived motion hints. The packed stream is not editable."
        ),
    }


def _extract_binary_string_records(
    data: bytes,
    *,
    sample_limit: int = 262_144,
    max_strings: int = 512,
) -> List[_BinarySidecarStringRecord]:
    sample = data[:sample_limit]
    records: List[_BinarySidecarStringRecord] = []
    seen: set[str] = set()
    for match in _PRINTABLE_BINARY_STRING_RE.finditer(sample):
        text = match.group().decode("ascii", errors="ignore").strip()
        letter_count = sum(1 for char in text if char.isalpha())
        if len(text) < 4 or text in seen or letter_count == 0:
            continue
        allowed_char_count = sum(1 for char in text if char.isalnum() or char in " _./:-[](){}")
        if allowed_char_count / max(len(text), 1) < 0.85:
            continue
        if len(text) < 12 and letter_count < 4:
            continue
        if "_" not in text and "/" not in text and "::" not in text and " " not in text and len(text) < 12:
            continue
        if len(text) > 240:
            text = text[:237] + "..."
        seen.add(text)
        records.append(_BinarySidecarStringRecord(offset=match.start(), text=text))
        if len(records) >= max_strings:
            break
    return records


def _read_binary_sidecar_string_at(data: bytes, offset: int, *, limit: int = 96) -> str:
    if offset < 0 or offset >= len(data):
        return ""
    match = _PRINTABLE_BINARY_STRING_RE.match(data[offset : min(len(data), offset + limit)])
    if match is None:
        return ""
    text = match.group().decode("ascii", errors="ignore").strip()
    if not text or sum(1 for char in text if char.isalpha()) == 0:
        return ""
    if len(text) > 96:
        text = text[:93] + "..."
    return text


def _binary_sidecar_asset_reference_rows(
    string_records: Sequence[_BinarySidecarStringRecord],
    *,
    max_references: int = 96,
) -> List[Dict[str, object]]:
    rows: List[Dict[str, object]] = []
    seen: set[str] = set()
    for record in string_records:
        for match in _STRUCTURED_BINARY_ASSET_TOKEN_RE.finditer(record.text):
            raw_text = _clean_structured_binary_asset_token(match.group(0))
            if not _looks_like_structured_asset_reference(raw_text):
                continue
            normalized = _normalize_model_texture_reference(raw_text)
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            rows.append(
                {
                    "offset": record.offset + match.start(),
                    "path": raw_text,
                    "extension": PurePosixPath(raw_text).suffix.lower(),
                    "confidence": "string_path",
                }
            )
            if len(rows) >= max_references:
                return rows
    return rows


def _binary_sidecar_header_words(data: bytes, *, max_words: int = 20) -> List[Dict[str, object]]:
    rows: List[Dict[str, object]] = []
    for offset in range(0, min(len(data) // 4, max_words) * 4, 4):
        value = struct.unpack_from("<I", data, offset)[0]
        rows.append(
            {
                "offset": offset,
                "le_u32": value,
                "le_i32": struct.unpack_from("<i", data, offset)[0],
                "hex": f"0x{value:08X}",
            }
        )
    return rows


def _seqmt_filename_grid_hint(virtual_path: str) -> Dict[str, object]:
    name = PurePosixPath(str(virtual_path or "").replace("\\", "/")).name.lower()
    match = re.search(r"(?:^|_)(\d{1,3})x(\d{1,3})(?:_|\.|$)", name)
    if match is None:
        return {}
    return {
        "columns": int(match.group(1)),
        "rows": int(match.group(2)),
        "source": "filename_token",
    }


def _seqmt_analysis_document(
    data: bytes,
    virtual_path: str,
    *,
    max_frame_records: int = 96,
) -> Dict[str, object]:
    """Decode observed SEQMT DDS! sequence texture atlas metadata.

    Local corpus samples use an unaligned compact header:
    DDS!, version byte, u16 columns, u16 rows, one flag/packing byte, u16 frame count,
    then one four-byte record per frame. The four-byte record semantics are still
    read-only evidence, so expose multiple byte interpretations without naming a
    final value type.
    """

    if len(data) < 12 or data[:4] != b"DDS!":
        return {
            "recognized": False,
            "reason": "missing_DDS_sequence_magic",
            "editing_supported": False,
        }

    version = int(data[4])
    columns = int(struct.unpack_from("<H", data, 5)[0])
    rows = int(struct.unpack_from("<H", data, 7)[0])
    flags_or_packing = int(data[9])
    frame_count = int(struct.unpack_from("<H", data, 10)[0])
    payload_offset = 12
    frame_record_size = 4
    expected_frame_payload_bytes = frame_count * frame_record_size
    available_payload_bytes = max(0, len(data) - payload_offset)
    decoded_frame_bytes = min(available_payload_bytes, expected_frame_payload_bytes)
    decoded_frame_count = decoded_frame_bytes // frame_record_size
    trailing_payload_offset = payload_offset + expected_frame_payload_bytes
    trailing_payload_bytes = max(0, len(data) - trailing_payload_offset)
    grid_capacity = columns * rows
    filename_hint = _seqmt_filename_grid_hint(virtual_path)
    if filename_hint:
        filename_hint = dict(filename_hint)
        filename_hint["matches_header"] = (
            int(filename_hint.get("columns") or 0) == columns
            and int(filename_hint.get("rows") or 0) == rows
        )

    frame_records: List[Dict[str, object]] = []
    preview_count = min(decoded_frame_count, max_frame_records)
    for index in range(preview_count):
        offset = payload_offset + index * frame_record_size
        raw = data[offset : offset + frame_record_size]
        byte_values = [int(value) for value in raw]
        signed_values = [value - 256 if value >= 128 else value for value in byte_values]
        frame_records.append(
            {
                "index": index,
                "grid_x": index % columns if columns > 0 else 0,
                "grid_y": index // columns if columns > 0 else 0,
                "offset": offset,
                "hex": raw.hex(" ").upper(),
                "bytes_rgba": byte_values,
                "bytes_bgra": [byte_values[2], byte_values[1], byte_values[0], byte_values[3]]
                if len(byte_values) == 4
                else byte_values,
                "bytes_signed": signed_values,
            }
        )

    notes = [
        "Frame records are exposed as four raw bytes because the channel semantics are not proven yet.",
        "Editing is disabled until frame record meaning and rebuild rules are validated.",
    ]
    if flags_or_packing == 1:
        notes.append("The flag/packing byte is 1; local samples often use this on filenames containing 4pack.")
    if trailing_payload_bytes > 0:
        notes.append("Extra trailing payload was preserved separately from the fixed frame table.")

    return {
        "recognized": True,
        "format": "DDS_sequence_texture_metadata",
        "magic": "DDS!",
        "version": version,
        "columns": columns,
        "rows": rows,
        "grid_capacity": grid_capacity,
        "frame_count": frame_count,
        "frame_count_matches_grid": frame_count == grid_capacity,
        "flags_or_packing_byte": flags_or_packing,
        "payload_offset": payload_offset,
        "frame_record_size": frame_record_size,
        "expected_frame_payload_bytes": expected_frame_payload_bytes,
        "available_payload_bytes": available_payload_bytes,
        "decoded_frame_count": decoded_frame_count,
        "payload_complete": available_payload_bytes >= expected_frame_payload_bytes,
        "trailing_payload_offset": trailing_payload_offset if trailing_payload_bytes > 0 else None,
        "trailing_payload_bytes": trailing_payload_bytes,
        "trailing_payload_preview_hex": data[trailing_payload_offset : min(len(data), trailing_payload_offset + 64)].hex(" ").upper()
        if trailing_payload_bytes > 0
        else "",
        "filename_grid_hint": filename_hint,
        "frame_records_preview": frame_records,
        "frame_records_preview_truncated": decoded_frame_count > preview_count,
        "editing_supported": False,
        "confidence": "confirmed_on_local_seqmt_corpus_header",
        "notes": notes,
    }


def _paccd_analysis_document(
    data: bytes,
    virtual_path: str,
    *,
    max_rows: int = 24,
    max_row_bytes: int = 32,
) -> Dict[str, object]:
    """Decode observed PACCD character customization byte tables.

    Local corpus samples are either a compact 298-byte table or a larger
    palette-style table. Both variants share a small integer header where
    word 1 is consistently 14, followed by per-slot byte payloads. The byte
    semantics are not named yet, so expose row/byte evidence read-only.
    """

    if len(data) < 28:
        return {
            "recognized": False,
            "reason": "too_small_for_paccd_header",
            "editing_supported": False,
        }

    header_word_count = min(len(data) // 4, 8)
    header_words = [int(struct.unpack_from("<I", data, offset * 4)[0]) for offset in range(header_word_count)]
    slot_count = int(header_words[1]) if len(header_words) > 1 else 0
    profile_version = int(header_words[2]) if len(header_words) > 2 else 0
    if slot_count <= 0 or slot_count > 128:
        return {
            "recognized": False,
            "reason": "invalid_slot_count",
            "header_words_le_u32": header_words,
            "editing_supported": False,
        }

    candidate_offsets = (32, 28, 24)
    payload_offset = 32 if len(data) >= 32 else 28
    for candidate in candidate_offsets:
        if len(data) <= candidate:
            continue
        if (len(data) - candidate) % slot_count == 0:
            payload_offset = candidate
            break
    payload_size = max(0, len(data) - payload_offset)
    row_stride = payload_size // slot_count if slot_count > 0 else 0
    trailing_payload_bytes = payload_size - row_stride * slot_count
    format_family = "compact_customization_rows" if row_stride <= 32 else "extended_customization_palette"

    rows: List[Dict[str, object]] = []
    neutral_values = {0, 50, 100, 125, 255}
    for row_index in range(min(slot_count, max_rows)):
        row_offset = payload_offset + row_index * row_stride
        if row_offset >= len(data):
            break
        raw = data[row_offset : min(len(data), row_offset + row_stride)]
        byte_values = [int(value) for value in raw[:max_row_bytes]]
        if raw:
            minimum = min(int(value) for value in raw)
            maximum = max(int(value) for value in raw)
            non_zero_count = sum(1 for value in raw if int(value) != 0)
            non_neutral_count = sum(1 for value in raw if int(value) not in neutral_values)
        else:
            minimum = maximum = non_zero_count = non_neutral_count = 0
        rgb_candidates: List[Dict[str, object]] = []
        for component_offset in range(0, min(len(raw), max_row_bytes) - 2, 3):
            triplet = [int(raw[component_offset + index]) for index in range(3)]
            if triplet in ([0, 0, 0], [255, 255, 255]):
                continue
            rgb_candidates.append(
                {
                    "byte_offset_in_row": component_offset,
                    "rgb_bytes": triplet,
                    "normalized_rgb": [round(value / 255.0, 4) for value in triplet],
                }
            )
            if len(rgb_candidates) >= 4:
                break
        rows.append(
            {
                "slot_index": row_index,
                "offset": row_offset,
                "row_stride": row_stride,
                "preview_hex": raw[:max_row_bytes].hex(" ").upper(),
                "preview_bytes": byte_values,
                "min_byte": minimum,
                "max_byte": maximum,
                "non_zero_bytes": non_zero_count,
                "non_neutral_bytes": non_neutral_count,
                "rgb_candidates": rgb_candidates,
                "confidence": "observed_fixed_slot_byte_row",
            }
        )

    notes = [
        "PACCD row bytes are exposed as customization slider/palette evidence; exact field names are not proven.",
        "Editing is disabled until row ownership, defaults, and no-edit rebuilds are validated.",
    ]
    if row_stride == 19 and payload_offset == 32:
        notes.append("This matches the common 298-byte compact corpus layout: 32-byte header plus 14 x 19-byte rows.")
    elif row_stride > 32:
        notes.append("This looks like the extended customization palette layout with larger per-slot byte rows.")
    if trailing_payload_bytes:
        notes.append("Trailing bytes exist after the evenly divided slot rows and are preserved as unknown payload.")

    return {
        "recognized": True,
        "format": "character_customization_byte_table",
        "path_hint": str(virtual_path or ""),
        "header_words_le_u32": header_words,
        "slot_count": slot_count,
        "profile_version": profile_version,
        "payload_offset": payload_offset,
        "payload_size": payload_size,
        "row_stride": row_stride,
        "format_family": format_family,
        "trailing_payload_bytes": trailing_payload_bytes,
        "trailing_payload_preview_hex": data[
            payload_offset + row_stride * slot_count : min(len(data), payload_offset + row_stride * slot_count + 64)
        ].hex(" ").upper()
        if trailing_payload_bytes > 0
        else "",
        "rows_preview": rows,
        "rows_preview_truncated": slot_count > len(rows),
        "editing_supported": False,
        "confidence": "confirmed_on_local_paccd_corpus_header",
        "notes": notes,
    }


def _binary_sidecar_offset_candidates(
    data: bytes,
    *,
    sample_limit: int = 262_144,
    max_candidates: int = 64,
) -> List[Dict[str, object]]:
    rows: List[Dict[str, object]] = []
    scan_limit = min(len(data), sample_limit)
    if scan_limit < 8:
        return rows
    for owner_offset in range(0, scan_limit - 3, 4):
        target_offset = struct.unpack_from("<I", data, owner_offset)[0]
        if target_offset <= 0 or target_offset >= len(data):
            continue
        if target_offset % 4 != 0:
            continue
        target_string = _read_binary_sidecar_string_at(data, target_offset)
        confidence = "string_target" if target_string else "aligned_in_file"
        rows.append(
            {
                "owner_offset": owner_offset,
                "target_offset": target_offset,
                "patched_slot_value": f"0x{target_offset:08X}",
                "target_preview": target_string,
                "confidence": confidence,
            }
        )
        if len(rows) >= max_candidates:
            break
    return rows


def _binary_sidecar_count_offset_pairs(
    data: bytes,
    *,
    sample_limit: int = 262_144,
    max_pairs: int = 48,
) -> List[Dict[str, object]]:
    rows: List[Dict[str, object]] = []
    scan_limit = min(len(data), sample_limit)
    if scan_limit < 12:
        return rows
    stride_candidates = (4, 8, 12, 16, 24, 32, 48, 64)
    for owner_offset in range(0, scan_limit - 7, 4):
        count = struct.unpack_from("<I", data, owner_offset)[0]
        target_offset = struct.unpack_from("<I", data, owner_offset + 4)[0]
        if count <= 0 or count > 1_000_000:
            continue
        if target_offset <= 0 or target_offset >= len(data) or target_offset % 4 != 0:
            continue
        remaining = len(data) - target_offset
        possible_strides = [stride for stride in stride_candidates if count * stride <= remaining]
        if not possible_strides:
            continue
        target_string = _read_binary_sidecar_string_at(data, target_offset)
        confidence = "strong_string_table" if target_string else "candidate_count_offset_pair"
        rows.append(
            {
                "owner_offset": owner_offset,
                "count": count,
                "data_offset": target_offset,
                "possible_element_sizes": possible_strides,
                "target_preview": target_string,
                "confidence": confidence,
            }
        )
        if len(rows) >= max_pairs:
            break
    return rows


def _is_binary_sidecar_plausible_float(value: float) -> bool:
    if not math.isfinite(value):
        return False
    if abs(value) > 1_000_000.0:
        return False
    if 0.0 < abs(value) < 1.0e-12:
        return False
    return True


def _binary_sidecar_float_rows(
    data: bytes,
    *,
    sample_limit: int = 262_144,
    max_rows: int = 48,
) -> List[Dict[str, object]]:
    rows: List[Dict[str, object]] = []
    scan_limit = min(len(data), sample_limit)
    if scan_limit < 12:
        return rows
    for offset in range(0, scan_limit - 15, 4):
        values = struct.unpack_from("<4f", data, offset)
        if not all(_is_binary_sidecar_plausible_float(value) for value in values):
            continue
        if all(abs(value) < 1.0e-6 for value in values):
            continue
        # Random integer tables can also look like floats. Keep these explicitly
        # experimental and only sample enough rows to guide format recovery.
        non_zero_count = sum(1 for value in values if abs(value) >= 1.0e-6)
        row_kind = "float4_candidate" if non_zero_count >= 4 else "float3_or_padded_float4_candidate"
        rows.append(
            {
                "offset": offset,
                "type": row_kind,
                "values": [round(float(value), 7) for value in values],
                "confidence": "experimental_numeric_scan",
            }
        )
        if len(rows) >= max_rows:
            break
    return rows


def _decode_binary_sidecar_half_float(raw_value: int) -> float:
    try:
        return float(struct.unpack("<e", int(raw_value & 0xFFFF).to_bytes(2, "little"))[0])
    except (struct.error, OverflowError, ValueError):
        return float("nan")


def _is_binary_sidecar_plausible_half_float(value: float) -> bool:
    if not math.isfinite(value):
        return False
    if abs(value) > 16.0:
        return False
    if 0.0 < abs(value) < 1.0e-7:
        return False
    return True


def _binary_sidecar_animation_keyframe_tables(
    data: bytes,
    *,
    sample_limit: int = 262_144,
    max_tables: int = 16,
    max_preview_rows: int = 8,
) -> List[Dict[str, object]]:
    """Recover read-only PAA-style keyframe table candidates."""

    row_size = 10
    component_count = 4
    minimum_rows = 4
    scan_limit = min(len(data), sample_limit)
    if scan_limit < row_size * minimum_rows:
        return []

    def read_row(offset: int) -> Optional[Tuple[int, Tuple[float, ...], float]]:
        if offset < 0 or offset + row_size > scan_limit:
            return None
        frame = struct.unpack_from("<H", data, offset)[0]
        values: List[float] = []
        for component_index in range(component_count):
            raw_value = struct.unpack_from("<H", data, offset + 2 + component_index * 2)[0]
            value = _decode_binary_sidecar_half_float(raw_value)
            if not _is_binary_sidecar_plausible_half_float(value):
                return None
            values.append(value)
        if all(abs(value) < 1.0e-7 for value in values):
            return None
        norm = math.sqrt(sum(value * value for value in values))
        return frame, tuple(values), norm

    candidates: List[Dict[str, object]] = []
    max_rows_per_candidate = 2048
    for offset in range(0, scan_limit - row_size * minimum_rows + 1, 2):
        first_rows: List[Tuple[int, Tuple[float, ...], float, int]] = []
        previous_frame: Optional[int] = None
        valid = True
        for row_index in range(minimum_rows):
            row_offset = offset + row_index * row_size
            row = read_row(row_offset)
            if row is None:
                valid = False
                break
            frame, values, norm = row
            if previous_frame is not None and not (0 < frame - previous_frame <= 256):
                valid = False
                break
            previous_frame = frame
            first_rows.append((frame, values, norm, row_offset))
        if not valid:
            continue

        rows = list(first_rows)
        while len(rows) < max_rows_per_candidate:
            row_offset = offset + len(rows) * row_size
            row = read_row(row_offset)
            if row is None:
                break
            frame, values, norm = row
            previous_frame = int(rows[-1][0])
            if not (0 < frame - previous_frame <= 256):
                break
            rows.append((frame, values, norm, row_offset))

        consecutive_steps = sum(1 for index in range(1, len(rows)) if int(rows[index][0]) - int(rows[index - 1][0]) == 1)
        normish_rows = sum(1 for _frame, _values, norm, _row_offset in rows if 0.75 <= norm <= 1.25)
        value_kind = "half_float_quaternion_or_vector4"
        if normish_rows >= max(3, int(len(rows) * 0.75)):
            value_kind = "half_float_quaternion_candidate"
        confidence = "strong_half_float_keyframe_run" if consecutive_steps >= len(rows) - 2 else "half_float_keyframe_run"
        preview_rows = [
            {
                "offset": row_offset,
                "frame": int(frame),
                "values": [round(float(value), 6) for value in values],
                "norm": round(float(norm), 6),
            }
            for frame, values, norm, row_offset in rows[:max_preview_rows]
        ]
        candidates.append(
            {
                "offset": offset,
                "row_size": row_size,
                "components": component_count,
                "row_format": "u16 frame + 4 half-float values",
                "row_count": len(rows),
                "frame_start": int(rows[0][0]),
                "frame_end": int(rows[-1][0]),
                "value_kind": value_kind,
                "confidence": confidence,
                "preview_rows": preview_rows,
            }
        )

    candidates.sort(key=lambda row: (-int(row.get("row_count") or 0), int(row.get("offset") or 0)))
    selected: List[Dict[str, object]] = []
    occupied_ranges: List[Tuple[int, int]] = []
    for candidate in candidates:
        start = int(candidate.get("offset") or 0)
        end = start + int(candidate.get("row_count") or 0) * row_size
        if any(start < occupied_end and end > occupied_start for occupied_start, occupied_end in occupied_ranges):
            continue
        selected.append(candidate)
        occupied_ranges.append((start, end))
        if len(selected) >= max_tables:
            break
    selected.sort(key=lambda row: int(row.get("offset") or 0))
    return selected


_BINARY_SIDECAR_DECL_IDENTIFIER_RE = re.compile(rb"[A-Za-z_][A-Za-z0-9_]{2,127}")
_BINARY_SIDECAR_PRIMITIVE_TYPES = {
    "bool",
    "float",
    "float2",
    "float3",
    "float4",
    "int",
    "int16",
    "int32",
    "uint16",
    "uint32",
}
_BINARY_SIDECAR_STRING_TYPES = {"staticstringa", "indexedstringa", "normalizedpatha"}
_BINARY_SIDECAR_KNOWN_TYPE_CODES = {0, 1, 2, 3, 4, 5, 7, 10}


def _looks_like_binary_sidecar_declared_type(value: str) -> bool:
    text = str(value or "").strip()
    if len(text) < 3 or len(text) > 96:
        return False
    if text.startswith("_") or "/" in text or "\\" in text or "." in text or " " in text:
        return False
    if not _STRUCTURED_BINARY_IDENTIFIER_RE.fullmatch(text):
        return False
    return any(character.isalpha() for character in text)


def _binary_sidecar_descriptor_likely_kind(
    member_name: str,
    declared_type: str,
    descriptor_words: Sequence[int],
) -> Tuple[str, str, str]:
    normalized_name = str(member_name or "").strip().lstrip("_").lower()
    normalized_type = str(declared_type or "").strip().lower()
    type_code = int(descriptor_words[0]) if descriptor_words else -1
    element_size = int(descriptor_words[1]) if len(descriptor_words) > 1 else 0
    flags_word = int(descriptor_words[2]) if len(descriptor_words) > 2 else 0

    is_array = (
        type_code in {3, 10}
        or bool(flags_word & 0x1000)
        or normalized_name.endswith(("list", "array"))
        or any(token in normalized_name for token in ("list", "container", "filenames", "triangles", "phases"))
    )
    array_status = "array_or_table" if is_array else "single_value"

    if normalized_type in _BINARY_SIDECAR_STRING_TYPES or "path" in normalized_type:
        reference_status = "string_reference" if "path" in normalized_type else "string"
        likely_kind = "string_array" if is_array else "string"
    elif "reflectobjectptr" in normalized_type or normalized_type.endswith("ptr"):
        reference_status = "object_reference"
        likely_kind = "object_reference_array" if is_array else "object_reference"
    elif "reflectobject" in normalized_type:
        reference_status = "object_reference"
        likely_kind = "object_value_or_reference"
    elif type_code == 2:
        reference_status = "type_or_enum_reference"
        likely_kind = "enum_or_flags"
    elif normalized_type in _BINARY_SIDECAR_PRIMITIVE_TYPES:
        reference_status = "value"
        likely_kind = "numeric_array" if is_array else ("bool" if normalized_type == "bool" else "numeric")
    elif element_size in {1, 2, 4, 8, 12, 16} and type_code == 0:
        reference_status = "value"
        likely_kind = "numeric_or_packed_value"
    else:
        reference_status = "type_or_class_reference"
        likely_kind = "array_or_table" if is_array else "typed_value"

    return likely_kind, array_status, reference_status


def _binary_sidecar_descriptor_confidence(
    member_name: str,
    declared_type: str,
    descriptor_words: Sequence[int],
) -> str:
    type_code = int(descriptor_words[0]) if descriptor_words else -1
    element_size = int(descriptor_words[1]) if len(descriptor_words) > 1 else -1
    normalized_type = str(declared_type or "").strip().lower()
    if not str(member_name or "").startswith("_"):
        return "low"
    if type_code in _BINARY_SIDECAR_KNOWN_TYPE_CODES:
        if normalized_type in _BINARY_SIDECAR_PRIMITIVE_TYPES and element_size in {1, 2, 4, 8, 12, 16}:
            return "strong_length_prefixed_member_declaration"
        if normalized_type in _BINARY_SIDECAR_STRING_TYPES or "reflectobject" in normalized_type:
            return "strong_length_prefixed_member_declaration"
        if type_code == 2 and _looks_like_binary_sidecar_declared_type(declared_type):
            return "strong_length_prefixed_member_declaration"
        return "length_prefixed_member_declaration"
    return "experimental_unknown_descriptor"


def _binary_sidecar_schema_declarations(
    data: bytes,
    extension: str,
    *,
    sample_limit: int = 262_144,
    max_rows: int = 512,
) -> Dict[str, object]:
    scan_limit = min(len(data), sample_limit)
    normalized_extension = str(extension or "").strip().lower()
    field_group_func = _binary_sidecar_group_func_for_extension(normalized_extension)
    rows: List[Dict[str, object]] = []
    seen_row_keys: set[Tuple[int, str, str]] = set()
    class_candidates: List[Dict[str, object]] = []
    seen_class_names: set[str] = set()

    for match in _BINARY_SIDECAR_DECL_IDENTIFIER_RE.finditer(data[:scan_limit]):
        name_offset = match.start()
        name = match.group().decode("ascii", errors="ignore")
        if name_offset < 4:
            continue
        try:
            name_length = struct.unpack_from("<I", data, name_offset - 4)[0]
        except struct.error:
            continue
        if name_length != len(name):
            continue

        if (
            not name.startswith("_")
            and len(class_candidates) < 24
            and _looks_like_binary_sidecar_declared_type(name)
            and name.lower() not in _BINARY_SIDECAR_PRIMITIVE_TYPES
            and name.lower() not in _BINARY_SIDECAR_STRING_TYPES
            and name not in seen_class_names
        ):
            seen_class_names.add(name)
            class_candidates.append(
                {
                    "offset": name_offset,
                    "name": name,
                    "confidence": "length_prefixed_type_or_class_name",
                }
            )

        if not name.startswith("_") or not _looks_like_structured_field_name(name):
            continue
        type_length_offset = name_offset + len(name)
        if type_length_offset + 4 > scan_limit:
            continue
        try:
            type_length = struct.unpack_from("<I", data, type_length_offset)[0]
        except struct.error:
            continue
        if type_length < 3 or type_length > 96:
            continue
        type_offset = type_length_offset + 4
        descriptor_offset = type_offset + type_length
        if descriptor_offset + 8 > scan_limit:
            continue
        declared_type_bytes = data[type_offset:descriptor_offset]
        if not _BINARY_SIDECAR_DECL_IDENTIFIER_RE.fullmatch(declared_type_bytes):
            continue
        declared_type = declared_type_bytes.decode("ascii", errors="ignore")
        if not _looks_like_binary_sidecar_declared_type(declared_type):
            continue
        descriptor_bytes = data[descriptor_offset:descriptor_offset + 8]
        descriptor_words = struct.unpack_from("<4H", descriptor_bytes, 0)
        if descriptor_words[0] > 64 or descriptor_words[1] > 256:
            continue
        row_key = (name_offset, name, declared_type)
        if row_key in seen_row_keys:
            continue
        seen_row_keys.add(row_key)
        likely_kind, array_status, reference_status = _binary_sidecar_descriptor_likely_kind(
            name,
            declared_type,
            descriptor_words,
        )
        rows.append(
            {
                "declaration_offset": name_offset - 4,
                "name_offset": name_offset,
                "name": name,
                "declared_type": declared_type,
                "type_offset": type_offset,
                "descriptor_offset": descriptor_offset,
                "descriptor_hex": descriptor_bytes.hex(" ").upper(),
                "descriptor_words_le_u16": [int(value) for value in descriptor_words],
                "type_code": int(descriptor_words[0]),
                "element_size": int(descriptor_words[1]),
                "descriptor_flags_hex": f"0x{int(descriptor_words[2]):04X}{int(descriptor_words[3]):04X}",
                "likely_kind": likely_kind,
                "array_status": array_status,
                "reference_status": reference_status,
                "group": field_group_func(name),
                "confidence": _binary_sidecar_descriptor_confidence(name, declared_type, descriptor_words),
                "edit_status": "read_only_declaration_only",
            }
        )
        if len(rows) >= max_rows:
            break

    signature_source = "\n".join(
        f"{row['name']}:{row['declared_type']}:{row['descriptor_hex']}"
        for row in rows
    )
    layout_signature = hashlib.sha1(signature_source.encode("utf-8")).hexdigest()[:16] if signature_source else ""
    declaration_end = 0
    if rows:
        declaration_end = max(int(row.get("descriptor_offset") or 0) + 8 for row in rows)
        declaration_end = min(len(data), (declaration_end + 3) & ~3)
    unusual_rows = [
        row
        for row in rows
        if int(row.get("type_code") or 0) not in _BINARY_SIDECAR_KNOWN_TYPE_CODES
        or str(row.get("confidence") or "").startswith("experimental")
    ]

    return {
        "status": "experimental_read_only_declaration_recovery",
        "declaration_count": len(rows),
        "unique_member_count": len({str(row.get("name") or "") for row in rows}),
        "layout_signature": layout_signature,
        "root_or_class_candidates": class_candidates,
        "declaration_region": {
            "start_offset": int(rows[0]["declaration_offset"]) if rows else 0,
            "end_offset": declaration_end,
            "candidate_value_region_start": declaration_end,
            "confidence": "declaration_end_heuristic" if rows else "no_declarations",
        },
        "declared_member_rows": rows,
        "unknown_descriptor_rows": unusual_rows[:64],
    }


def _build_grouped_schema_declaration_lines(
    declaration_rows: Sequence[Mapping[str, object]],
    *,
    section_order: Sequence[str],
    per_section_limit: int = 24,
) -> List[str]:
    grouped: Dict[str, List[Mapping[str, object]]] = defaultdict(list)
    for row in declaration_rows:
        if not isinstance(row, Mapping):
            continue
        group = str(row.get("group") or "Misc").strip() or "Misc"
        grouped[group].append(row)

    lines: List[str] = []
    ordered_sections = list(section_order) + [
        section_name
        for section_name in sorted(grouped, key=str.casefold)
        if section_name not in section_order
    ]
    for section_name in ordered_sections:
        rows = grouped.get(section_name, [])
        if not rows:
            continue
        lines.extend(["", f"{section_name} declared fields ({len(rows)})"])
        for row in rows[:per_section_limit]:
            name = str(row.get("name") or "").strip()
            declared_type = str(row.get("declared_type") or "").strip()
            likely_kind = str(row.get("likely_kind") or "field").strip()
            array_status = str(row.get("array_status") or "").strip()
            descriptor = str(row.get("descriptor_hex") or "").strip()
            array_suffix = ", array" if array_status and array_status != "single_value" else ""
            lines.append(
                f"  [{likely_kind}{array_suffix}] {name}: {declared_type} "
                f"@0x{int(row.get('name_offset') or 0):X} desc={descriptor}"
            )
        if len(rows) > per_section_limit:
            lines.append(f"  ... {len(rows) - per_section_limit} more")
    return lines


def _binary_sidecar_container_summary(data: bytes, extension: str) -> Dict[str, object]:
    head4 = data[:4]
    magic_ascii = "".join(chr(value) if 32 <= value <= 126 else "." for value in head4)
    normalized_extension = str(extension or "").strip().lower()
    container: Dict[str, object] = {
        "magic_ascii": magic_ascii,
        "magic_hex": head4.hex(" ").upper(),
        "recognized_family": "unknown",
    }
    if head4 == b"PAR ":
        container["recognized_family"] = "PAR"
        container["note"] = "PAR-family binary. Current decode is read-only and schema-recovery oriented."
    elif head4 == b"PARC":
        container["recognized_family"] = "PARC"
        container["note"] = "PARC structured container. Current decode is read-only and schema-recovery oriented."
    elif normalized_extension == ".meshinfo":
        container["note"] = "MeshInfo sidecar without a currently proven top-level magic."
    elif normalized_extension == ".motionblending":
        container["note"] = "Motion-blending sidecar without a currently proven top-level magic."
    elif normalized_extension == ".paa_metabin":
        container["note"] = "PAA animation metadata sidecar. Current decode is read-only and relationship/schema-recovery oriented."
    elif normalized_extension == ".pappt":
        container["note"] = "Part-prefab table metadata. Current decode is read-only and used for part/model relationship evidence."
    elif normalized_extension == ".pamhc":
        container["note"] = "Model-property header metadata. Current decode is read-only and used for material/model relationship evidence."
    elif normalized_extension == ".paccd":
        container["recognized_family"] = "PACCD_CUSTOMIZATION"
        container["note"] = "Character customization byte table. Current decode exposes compact/extended slot rows as read-only slider/palette evidence."
    elif normalized_extension == ".papr":
        container["note"] = "Animation constraint metadata. Current decode is read-only and schema-recovery oriented."
    elif normalized_extension in _ARCHIVE_ANIMATION_SEQUENCE_EXTENSIONS:
        container["note"] = "Animation schedule/sequence metadata. Current decode is read-only and relationship/schema-recovery oriented."
    elif normalized_extension == ".seqmt":
        if head4 == b"DDS!":
            container["recognized_family"] = "DDS_SEQUENCE_TEXTURE"
            container["note"] = "SEQMT DDS! sequence texture metadata. Current decode is read-only and exposes atlas/frame-table evidence."
        else:
            container["note"] = "SEQMT sequence texture metadata. Current decode is read-only and used for timeline/material relationship evidence."
    return container


def _binary_sidecar_kind_label(extension: str) -> str:
    normalized_extension = str(extension or "").strip().lower()
    if normalized_extension == ".meshinfo":
        return "MeshInfo"
    if normalized_extension == ".motionblending":
        return "Motion Blending"
    if normalized_extension == ".paa":
        return "PAA Animation Clip"
    if normalized_extension == ".paa_metabin":
        return "PAA Animation Metadata"
    if normalized_extension == ".pappt":
        return "Part Prefab Table"
    if normalized_extension == ".pamhc":
        return "Model Property Header"
    if normalized_extension == ".paccd":
        return "Character Customization Data"
    if normalized_extension == ".papr":
        return "Animation Constraint"
    if normalized_extension in _ARCHIVE_ANIMATION_SEQUENCE_EXTENSIONS:
        return "Animation Schedule"
    if normalized_extension == ".seqmt":
        return "SEQMT Sequence Texture Metadata"
    return normalized_extension.lstrip(".").upper() or "Binary Sidecar"


def _build_binary_sidecar_related_references(
    source_entry: Optional[ArchiveEntry],
    *,
    asset_references: Sequence[str],
    archive_entries_by_normalized_path: Optional[Dict[str, Sequence[ArchiveEntry]]] = None,
    archive_entries_by_basename: Optional[Dict[str, Sequence[ArchiveEntry]]] = None,
) -> Tuple[ArchiveModelTextureReference, ...]:
    if source_entry is None:
        return ()
    companion_entries = (
        _find_archive_model_related_entries(source_entry, archive_entries_by_basename)
        if archive_entries_by_basename is not None
        else ()
    )
    explicit_references = build_archive_related_file_references(
        source_entry,
        explicit_reference_names=asset_references,
        companion_entries=companion_entries,
        archive_entries_by_normalized_path=archive_entries_by_normalized_path,
        archive_entries_by_basename=archive_entries_by_basename,
    )
    graph_references = build_archive_relationship_references(
        source_entry,
        archive_entries_by_normalized_path=archive_entries_by_normalized_path,
        archive_entries_by_basename=archive_entries_by_basename,
    )
    return merge_archive_reference_rows(explicit_references, graph_references)


def _binary_sidecar_reference_document_rows(
    references: Sequence[ArchiveModelTextureReference],
) -> List[Dict[str, object]]:
    rows: List[Dict[str, object]] = []
    for reference in references:
        rows.append(
            {
                "reference_name": reference.reference_name,
                "semantic_label": reference.semantic_label,
                "resolution_status": reference.resolution_status,
                "resolved_archive_path": reference.resolved_archive_path,
                "resolved_package_label": reference.resolved_package_label,
                "reference_kind": reference.reference_kind,
                "relation_group": reference.relation_group,
                "relation_confidence": reference.relation_confidence,
                "relation_reason": reference.relation_reason,
                "usage_count": reference.usage_count,
            }
        )
    return rows


_PASEQ_TIMELINE_FIELD_TOKENS = (
    "animation",
    "clip",
    "duration",
    "end",
    "event",
    "frame",
    "key",
    "loop",
    "phase",
    "sequence",
    "start",
    "time",
    "timeline",
    "track",
    "trigger",
)
_PASEQ_EFFECT_FIELD_TOKENS = ("effect", "emitter", "particle", "sound", "seqmt", "visibility")
_PASEQ_SCENE_FIELD_TOKENS = ("camera", "object", "prefab", "scene", "stage", "target")


def _paseq_sequence_stem(virtual_path: str) -> str:
    basename = PurePosixPath(str(virtual_path or "").replace("\\", "/")).name
    lowered = basename.lower()
    for extension in sorted(_ARCHIVE_ANIMATION_SEQUENCE_EXTENSIONS, key=len, reverse=True):
        if lowered.endswith(extension):
            return basename[: -len(extension)]
    return PurePosixPath(basename).stem


def _paseq_reference_role(path: str) -> str:
    extension = PurePosixPath(str(path or "").replace("\\", "/")).suffix.lower()
    if extension in {".paa", ".paa_metabin", ".motionblending"}:
        return "animation_clip"
    if extension in {".hkx", ".hkt"}:
        return "havok_animation_or_skeleton"
    if extension in {".pae", ".paem", ".seqmt", ".dds", ".wem", ".bnk"}:
        return "effect_or_presentation"
    if extension in _ARCHIVE_ANIMATION_SEQUENCE_EXTENSIONS:
        return "sequence_or_stage"
    if extension in {".pac", ".pam", ".pamlod"}:
        return "model_context"
    if extension in {".pab", ".pabc", ".pabv", ".pabgb", ".pabgh", ".papr"}:
        return "skeleton_or_rig_context"
    if extension in {".prefab", ".prefabdata_xml", ".app_xml", ".xml"}:
        return "scene_or_descriptor_context"
    return "related_asset"


def _paseq_timeline_field_role(name: str) -> str:
    normalized = str(name or "").strip().lstrip("_").lower()
    if not normalized:
        return "field"
    if any(token in normalized for token in ("animation", "clip", "motion")):
        return "animation_track"
    if any(token in normalized for token in _PASEQ_EFFECT_FIELD_TOKENS):
        return "effect_track"
    if any(token in normalized for token in ("event", "notify", "trigger", "condition")):
        return "event"
    if any(token in normalized for token in ("duration", "frame", "start", "end", "time", "tick")):
        return "timing"
    if any(token in normalized for token in ("parameter", "blend", "phase", "loop", "speed")):
        return "motion_parameter"
    if any(token in normalized for token in _PASEQ_SCENE_FIELD_TOKENS):
        return "scene_context"
    return "timeline_field"


def _paseq_timeline_field_rows(
    schema_member_rows: Sequence[Mapping[str, object]],
    string_records: Sequence[_BinarySidecarStringRecord],
    *,
    max_rows: int = 512,
) -> List[Dict[str, object]]:
    rows: List[Dict[str, object]] = []
    seen: set[tuple[object, ...]] = set()

    def add_row(
        *,
        name: str,
        source: str,
        offset: int,
        declared_type: str = "",
        descriptor_hex: str = "",
        descriptor_offset: int = 0,
        confidence: str = "",
    ) -> None:
        clean_name = str(name or "").strip()
        if not clean_name:
            return
        normalized = clean_name.lstrip("_").lower()
        if not any(token in normalized for token in (*_PASEQ_TIMELINE_FIELD_TOKENS, *_PASEQ_EFFECT_FIELD_TOKENS, *_PASEQ_SCENE_FIELD_TOKENS)):
            return
        key: tuple[object, ...]
        if source == "schema_declaration":
            key = (source, clean_name.lower(), int(offset), declared_type)
        else:
            key = (source, clean_name.lower())
        if key in seen:
            return
        seen.add(key)
        rows.append(
            {
                "name": clean_name,
                "role": _paseq_timeline_field_role(clean_name),
                "source": source,
                "offset": int(offset),
                "declared_type": declared_type,
                "descriptor_hex": descriptor_hex,
                "descriptor_offset": int(descriptor_offset),
                "confidence": confidence or source,
            }
        )

    for row in schema_member_rows:
        if not isinstance(row, Mapping):
            continue
        add_row(
            name=str(row.get("name") or ""),
            source="schema_declaration",
            offset=int(row.get("name_offset") or row.get("declaration_offset") or 0),
            declared_type=str(row.get("declared_type") or ""),
            descriptor_hex=str(row.get("descriptor_hex") or ""),
            descriptor_offset=int(row.get("descriptor_offset") or 0),
            confidence=str(row.get("confidence") or "length_prefixed_declaration"),
        )
        if len(rows) >= max_rows:
            return rows

    for record in string_records:
        if not _looks_like_structured_field_name(record.text):
            continue
        add_row(
            name=record.text,
            source="readable_string_identifier",
            offset=int(record.offset),
            confidence="readable_string_identifier",
        )
        if len(rows) >= max_rows:
            break
    return rows


def _paseq_event_marker_rows(
    string_records: Sequence[_BinarySidecarStringRecord],
    *,
    max_rows: int = 64,
) -> List[Dict[str, object]]:
    rows: List[Dict[str, object]] = []
    seen: set[str] = set()
    marker_tokens = (
        "begin",
        "camera",
        "effect",
        "end",
        "event",
        "loop",
        "notify",
        "phase",
        "sound",
        "start",
        "trigger",
    )
    for record in string_records:
        text = str(record.text or "").strip()
        normalized = text.lower()
        if normalized in seen:
            continue
        if not any(token in normalized for token in marker_tokens):
            continue
        seen.add(normalized)
        rows.append(
            {
                "offset": int(record.offset),
                "text": text,
                "role": _paseq_timeline_field_role(text),
                "confidence": "readable_event_or_phase_marker",
            }
        )
        if len(rows) >= max_rows:
            break
    return rows


def _paseq_timing_candidate_rows(
    data: bytes,
    *,
    sample_limit: int = 262_144,
    max_rows: int = 64,
) -> List[Dict[str, object]]:
    rows: List[Dict[str, object]] = []
    seen_offsets: set[Tuple[int, str]] = set()
    scan_limit = min(len(data), sample_limit)
    if scan_limit < 4:
        return rows

    def add_row(offset: int, kind: str, value: object, confidence: str) -> None:
        key = (offset, kind)
        if key in seen_offsets:
            return
        seen_offsets.add(key)
        rows.append(
            {
                "offset": int(offset),
                "kind": kind,
                "value": value,
                "confidence": confidence,
            }
        )

    for offset in range(0, scan_limit - 3, 4):
        word = struct.unpack_from("<I", data, offset)[0]
        if 0 < word <= 120_000 and (word <= 3600 or word % 15 == 0 or word % 30 == 0):
            add_row(offset, "u32_frame_or_tick_candidate", int(word), "experimental_timing_scan")
        try:
            value = struct.unpack_from("<f", data, offset)[0]
        except struct.error:
            value = 0.0
        if math.isfinite(value) and 0.0 < value <= 3600.0:
            rounded = round(float(value), 6)
            if abs(rounded) >= 1.0e-5 and rounded not in {1.0, 2.0, 3.0, 4.0}:
                add_row(offset, "float_seconds_or_weight_candidate", rounded, "experimental_timing_scan")
        if len(rows) >= max_rows:
            break
    return rows


def _paseq_fps_candidate_value_rows(
    data: bytes,
    *,
    scan_start: int = 0,
    sample_limit: int = 262_144,
    max_rows: int = 32,
) -> List[Dict[str, object]]:
    rows: List[Dict[str, object]] = []
    scan_offset = max(0, (int(scan_start) + 3) & ~3)
    scan_limit = min(len(data), sample_limit)
    if scan_offset + 4 > scan_limit:
        return rows

    integer_values = {15, 24, 30, 60}
    float_values = {15.0, 24.0, 30.0, 60.0}
    scan_confidence = "after_recovered_declaration_region" if scan_start > 0 else "aligned_4_byte_little_endian"
    for offset in range(scan_offset, scan_limit - 3, 4):
        word = struct.unpack_from("<I", data, offset)[0]
        if word in integer_values:
            context = _paseq_fps_candidate_context(data, offset, "u32_fps_candidate")
            rows.append(
                {
                    "offset": int(offset),
                    "kind": "u32_fps_candidate",
                    "value": int(word),
                    "confidence": scan_confidence,
                    "value_confidence": context["value_confidence"],
                    "status": context["status"],
                    "context": context["context"],
                    "context_text": context["context_text"],
                }
            )
        try:
            value = struct.unpack_from("<f", data, offset)[0]
        except struct.error:
            value = 0.0
        if value in float_values:
            context = _paseq_fps_candidate_context(data, offset, "float32_fps_candidate")
            rows.append(
                {
                    "offset": int(offset),
                    "kind": "float32_fps_candidate",
                    "value": int(value),
                    "confidence": scan_confidence,
                    "value_confidence": context["value_confidence"],
                    "status": context["status"],
                    "context": context["context"],
                    "context_text": context["context_text"],
                }
            )
        if len(rows) >= max_rows:
            break
    return rows


def _paseq_fps_candidate_context(data: bytes, offset: int, kind: str) -> Dict[str, str]:
    if kind == "u32_fps_candidate":
        text = _paseq_length_prefixed_ascii(data, offset) or _paseq_length_prefixed_ascii(data, offset + 4)
        if text:
            return {
                "context": "length_prefixed_string_context",
                "context_text": text,
                "status": "not_bound_length_prefixed_string_context",
                "value_confidence": "blocked",
            }
    return {
        "context": "binary_scalar_context",
        "context_text": "",
        "status": "unbound_binary_scalar_candidate",
        "value_confidence": "unknown",
    }


def _paseq_blend_candidate_value_rows(
    data: bytes,
    *,
    scan_start: int = 0,
    sample_limit: int = 262_144,
    max_rows: int = 32,
) -> List[Dict[str, object]]:
    rows: List[Dict[str, object]] = []
    scan_offset = max(0, (int(scan_start) + 3) & ~3)
    scan_limit = min(len(data), sample_limit)
    if scan_offset + 4 > scan_limit:
        return rows
    scan_confidence = "after_recovered_declaration_region" if scan_start > 0 else "aligned_4_byte_little_endian"
    for offset in range(scan_offset, scan_limit - 3, 4):
        try:
            value = struct.unpack_from("<f", data, offset)[0]
        except struct.error:
            continue
        if not math.isfinite(value) or abs(value) < 1.0e-5 or abs(value) > 10.0:
            continue
        rows.append(
            {
                "offset": int(offset),
                "kind": "float32_blend_candidate",
                "value": round(float(value), 6),
                "confidence": scan_confidence,
                "value_confidence": "unknown",
                "status": "unbound_binary_scalar_candidate",
                "context": "binary_scalar_context",
                "context_text": "",
            }
        )
        if len(rows) >= max_rows:
            break
    return rows


def _paseq_length_prefixed_ascii(data: bytes, offset: int) -> str:
    if offset < 0 or offset + 4 > len(data):
        return ""
    length = int(struct.unpack_from("<I", data, offset)[0])
    if length <= 3 or length > 128 or offset + 4 + length > len(data):
        return ""
    raw = data[offset + 4 : offset + 4 + length]
    if any(value < 0x20 or value >= 0x7F for value in raw):
        return ""
    text = raw.decode("ascii", "ignore")
    return text if any(char.isalpha() for char in text) else ""


def _paseq_timing_evidence(
    data: bytes,
    timeline_fields: Sequence[Mapping[str, object]],
    *,
    sample_limit: int = 262_144,
) -> Dict[str, object]:
    fps_declarations: List[Dict[str, object]] = []
    blend_declarations: List[Dict[str, object]] = []
    declaration_region_end = 0
    for row in timeline_fields:
        if not isinstance(row, Mapping):
            continue
        descriptor_offset = int(row.get("descriptor_offset") or 0)
        if descriptor_offset > 0:
            declaration_region_end = max(declaration_region_end, descriptor_offset + 8)
        field_name = str(row.get("name") or "").strip()
        declared_type = str(row.get("declared_type") or "")
        if not declared_type:
            continue
        normalized_name = field_name.lstrip("_").lower()
        if normalized_name == "framespersecond":
            fps_declarations.append(
                {
                    "name": field_name,
                    "declared_type": declared_type,
                    "offset": int(row.get("offset") or 0),
                    "confidence": "proven",
                    "value_confidence": "unknown",
                }
            )
        if "blend" in normalized_name:
            blend_declarations.append(
                {
                    "name": field_name,
                    "declared_type": declared_type,
                    "offset": int(row.get("offset") or 0),
                    "kind": _paseq_blend_field_kind(field_name),
                    "confidence": "proven",
                    "value_confidence": "unknown",
                }
            )

    scan_limit = min(len(data), sample_limit)
    candidate_value_rows = _paseq_fps_candidate_value_rows(
        data,
        scan_start=declaration_region_end,
        sample_limit=sample_limit,
    )
    blend_candidate_value_rows = _paseq_blend_candidate_value_rows(
        data,
        scan_start=declaration_region_end,
        sample_limit=sample_limit,
    )
    integer_counts: Dict[str, int] = {str(value): 0 for value in (15, 24, 30, 60)}
    float_counts: Dict[str, int] = {str(value): 0 for value in (15, 24, 30, 60)}
    integer_values = {15, 24, 30, 60}
    float_values = {15.0, 24.0, 30.0, 60.0}
    for offset in range(0, scan_limit - 3, 4):
        word = struct.unpack_from("<I", data, offset)[0]
        if word in integer_values:
            integer_counts[str(word)] += 1
        try:
            value = struct.unpack_from("<f", data, offset)[0]
        except struct.error:
            continue
        if value in float_values:
            float_counts[str(int(value))] += 1
    candidate_total = sum(integer_counts.values()) + sum(float_counts.values())
    if fps_declarations:
        status = "source_paseq_fps_field_declared_value_offset_unmapped"
        confidence = "unknown"
        gap = "Field declaration is recovered, but current PAR schema recovery does not bind that declaration to a concrete value offset."
    else:
        status = "no_source_paseq_fps_field_declaration"
        confidence = "blocked"
        gap = "No _framesPerSecond declaration was recovered from this sequence payload."
    if blend_declarations:
        blend_status = "blend_fields_declared_value_offsets_unmapped"
        blend_confidence = "unknown"
        blend_gap = "Blend-related field declarations are recovered, but current PAR schema recovery does not bind them to concrete value offsets."
    else:
        blend_status = "no_blend_field_declaration"
        blend_confidence = "blocked"
        blend_gap = "No blend-related timeline field declaration was recovered from this sequence payload."
    return {
        "fps_field_declaration_count": len(fps_declarations),
        "fps_field_declarations": fps_declarations,
        "fps_candidate_value_counts": {
            "u32": integer_counts,
            "float32": float_counts,
        },
        "fps_candidate_value_scan": "aligned_4_byte_little_endian",
        "fps_candidate_value_region_start": int(declaration_region_end),
        "fps_candidate_value_rows": candidate_value_rows,
        "fps_candidate_value_count": int(candidate_total),
        "fps_binding_confidence": confidence,
        "fps_binding_status": status,
        "proof_gap": gap,
        "blend_field_declaration_count": len(blend_declarations),
        "blend_field_declarations": blend_declarations,
        "blend_candidate_value_scan": "aligned_4_byte_little_endian_nonzero_float32",
        "blend_candidate_value_region_start": int(declaration_region_end),
        "blend_candidate_value_rows": blend_candidate_value_rows,
        "blend_candidate_value_count": len(blend_candidate_value_rows),
        "blend_binding_confidence": blend_confidence,
        "blend_binding_status": blend_status,
        "blend_proof_gap": blend_gap,
    }


def _paseq_blend_field_kind(name: str) -> str:
    normalized = str(name or "").strip().lstrip("_").lower()
    if not normalized:
        return "blend_field"
    if "blendingtime" in normalized or ("blend" in normalized and any(token in normalized for token in ("start", "end", "time"))):
        return "blend_window"
    if "mask" in normalized:
        return "blend_mask_or_part"
    return "blend_parameter"


def _paseq_timeline_lane_rows(
    asset_reference_rows: Sequence[Mapping[str, object]],
    *,
    max_rows: int = 96,
) -> List[Dict[str, object]]:
    lanes: List[Dict[str, object]] = []
    seen: set[str] = set()
    for row in asset_reference_rows:
        if not isinstance(row, Mapping):
            continue
        path = str(row.get("path") or "").replace("\\", "/").strip()
        normalized = _normalize_model_texture_reference(path)
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        role = _paseq_reference_role(path)
        extension = PurePosixPath(path).suffix.lower()
        lane_kind = "animation"
        if role == "effect_or_presentation":
            lane_kind = "effect"
        elif role in {"model_context", "skeleton_or_rig_context", "scene_or_descriptor_context"}:
            lane_kind = "context"
        elif role == "sequence_or_stage":
            lane_kind = "sequence"
        elif role == "related_asset":
            lane_kind = "asset"
        lanes.append(
            {
                "index": len(lanes),
                "path": path,
                "extension": extension,
                "kind": lane_kind,
                "role": role,
                "source_offset": int(row.get("offset") or 0),
                "confidence": str(row.get("confidence") or "asset_reference"),
            }
        )
        if len(lanes) >= max_rows:
            break
    return lanes


def _paseq_playback_readiness(lanes: Sequence[Mapping[str, object]], timeline_fields: Sequence[Mapping[str, object]]) -> Dict[str, object]:
    animation_lane_count = sum(1 for lane in lanes if str(lane.get("kind") or "") == "animation")
    effect_lane_count = sum(1 for lane in lanes if str(lane.get("kind") or "") == "effect")
    context_lane_count = sum(1 for lane in lanes if str(lane.get("kind") or "") == "context")
    timing_field_count = sum(1 for row in timeline_fields if str(row.get("role") or "") == "timing")
    blockers: List[str] = []
    if animation_lane_count <= 0:
        blockers.append("No referenced .paa/.hkx/.motionblending animation lane was recovered.")
    if context_lane_count <= 0:
        blockers.append("No model, skeleton, rig, or scene context lane was recovered.")
    if timing_field_count <= 0:
        blockers.append("No declared timing field was recovered; timeline timing remains candidate-only.")
    blockers.append("Runtime binding from PASEQ lanes to the 3D model preview is not implemented yet.")
    blockers.append("Exact sequence record semantics and no-edit rebuilds are not proven.")
    timing_confidence = "unknown" if timing_field_count > 0 else "blocked"
    return {
        "status": "dependency_timeline_recovered_read_only" if lanes or timeline_fields else "no_timeline_evidence_recovered",
        "ready_for_3d_playback": False,
        "game_accurate_timing": False,
        "timing_confidence": timing_confidence,
        "timing_status": "declared_timing_fields_unbound" if timing_field_count > 0 else "no_declared_timing_field",
        "animation_lane_count": int(animation_lane_count),
        "effect_lane_count": int(effect_lane_count),
        "context_lane_count": int(context_lane_count),
        "timing_field_count": int(timing_field_count),
        "blocking_gaps": blockers,
        "next_step": "Bind recovered lanes to a loaded model/skeleton preview after animation clip and PASEQ timing semantics are proven.",
    }


def _paseq_analysis_document(
    data: bytes,
    virtual_path: str,
    *,
    string_records: Sequence[_BinarySidecarStringRecord],
    asset_reference_rows: Sequence[Mapping[str, object]],
    schema_member_rows: Sequence[Mapping[str, object]],
) -> Dict[str, object]:
    timeline_fields = _paseq_timeline_field_rows(schema_member_rows, string_records)
    event_markers = _paseq_event_marker_rows(string_records)
    timing_candidates = _paseq_timing_candidate_rows(data)
    timing_evidence = _paseq_timing_evidence(data, timeline_fields)
    lanes = _paseq_timeline_lane_rows(asset_reference_rows)
    playback_readiness = _paseq_playback_readiness(lanes, timeline_fields)
    lane_kind_counts = Counter(str(row.get("kind") or "asset") for row in lanes)
    reference_role_counts = Counter(str(row.get("role") or "related_asset") for row in lanes)
    return {
        "recognized": bool(timeline_fields or event_markers or timing_candidates or lanes),
        "format": "animation_sequence_schedule_metadata",
        "sequence_stem": _paseq_sequence_stem(virtual_path),
        "timeline": {
            "status": "read_only_recovered_timeline_evidence",
            "lane_count": len(lanes),
            "lane_kind_counts": dict(sorted(lane_kind_counts.items())),
            "reference_role_counts": dict(sorted(reference_role_counts.items())),
            "timeline_field_count": len(timeline_fields),
            "event_marker_count": len(event_markers),
            "timing_candidate_count": len(timing_candidates),
            "lanes": lanes,
            "timeline_fields": timeline_fields,
            "event_markers": event_markers,
            "timing_candidates": timing_candidates,
            "timing_evidence": timing_evidence,
        },
        "playback_readiness": playback_readiness,
        "editing_supported": False,
        "notes": [
            "PASEQ schedule evidence is read-only; offsets are decoded-payload byte offsets.",
            "Timeline lanes are recovered from asset reference strings and same payload evidence, not from proven executable game logic.",
            "3D playback remains disabled until sequence timing, clip binding, and skeleton/model application are validated.",
        ],
    }


def _papr_constraint_string_role(text: str) -> str:
    value = str(text or "").strip()
    if not value:
        return ""
    normalized = value.lower()
    if "local_euler" in normalized or "local_quat" in normalized or "local_position" in normalized:
        if normalized.startswith(("amin", "amax")) or "amin(" in normalized or "amax(" in normalized:
            return "limit_expression"
        return "driver_expression"
    if normalized.startswith(("amin", "amax")):
        return "limit_expression"
    if value.startswith("P_") or normalized.startswith("p_bip"):
        return "parent_bone_reference"
    if (
        "bip01" in normalized
        or normalized.startswith("b_")
        or normalized.startswith("bone")
        or normalized.endswith("_dummy")
        or "_dummy" in normalized
        or normalized.endswith("_sub")
    ):
        if "_dummy" in normalized or normalized.endswith("_sub"):
            return "helper_bone_reference"
        return "bone_reference"
    return ""


_PAPR_EXPRESSION_CHANNEL_RE = re.compile(r"\bLocal_(?:Euler|Quat|Position)_[XYZW]\b", re.IGNORECASE)
_PAPR_LIMIT_OPERATOR_RE = re.compile(r"\b(?:amin|amax)\b", re.IGNORECASE)
_PAPR_EXPRESSION_NUMBER_RE = re.compile(r"(?<![A-Za-z0-9_.])-?\d+(?:\.\d+)?")
_PAPR_ABS_OPERATOR_RE = re.compile(r"\babs\b", re.IGNORECASE)


def _papr_constraint_expression_evidence(expression: str) -> Dict[str, object]:
    text = str(expression or "")
    channels = tuple(match.group(0) for match in _PAPR_EXPRESSION_CHANNEL_RE.finditer(text))
    limit_operators = tuple(match.group(0).lower() for match in _PAPR_LIMIT_OPERATOR_RE.finditer(text))
    numeric_values = tuple(match.group(0) for match in _PAPR_EXPRESSION_NUMBER_RE.finditer(text))
    numeric_roles = _papr_constraint_expression_numeric_roles(text)
    shape = _papr_constraint_expression_shape(
        text,
        channels=channels,
        limit_operators=limit_operators,
        numeric_values=numeric_values,
    )
    syntax_signature = _papr_constraint_expression_syntax_signature(
        shape=shape,
        channels=channels,
        limit_operators=limit_operators,
        numeric_roles=numeric_roles,
    )
    return {
        "expression_channels": channels,
        "expression_channel_confidence": "proven" if channels else "unknown",
        "limit_operators": limit_operators,
        "limit_operator_confidence": "proven" if limit_operators else "unknown",
        "expression_numeric_values": numeric_values,
        "expression_numeric_value_confidence": "proven" if numeric_values else "unknown",
        "expression_numeric_roles": numeric_roles,
        "expression_numeric_role_confidence": "inferred_readable_expression_syntax" if numeric_roles else "unknown",
        "expression_shape": shape,
        "expression_syntax_signature": syntax_signature,
        "expression_shape_confidence": "inferred_readable_expression_syntax",
        "expression_shape_status": "solver_semantics_unknown",
        "expression_semantics_confidence": "unknown",
    }


def _papr_constraint_expression_syntax_signature(
    *,
    shape: str,
    channels: Sequence[str],
    limit_operators: Sequence[str],
    numeric_roles: Sequence[str],
) -> str:
    channel_text = ">".join(str(value) for value in channels if str(value)) or "none"
    limit_text = ">".join(str(value) for value in limit_operators if str(value)) or "none"
    numeric_role_text = ">".join(str(value) for value in numeric_roles if str(value)) or "none"
    return (
        f"shape={shape or 'unknown'}|channels={channel_text}|"
        f"limits={limit_text}|numeric_roles={numeric_role_text}"
    )


def _papr_constraint_expression_shape(
    expression: str,
    *,
    channels: Sequence[str],
    limit_operators: Sequence[str],
    numeric_values: Sequence[str],
) -> str:
    text = str(expression or "")
    has_channel = bool(channels)
    has_limit = bool(limit_operators)
    has_number = bool(numeric_values)
    has_abs = bool(_PAPR_ABS_OPERATOR_RE.search(text))
    has_arithmetic = any(operator in text for operator in ("*", "+", "-", "/"))
    if has_limit:
        if has_abs and has_channel:
            return "limit_absolute_channel_transform_candidate"
        if has_channel and has_number:
            return "limit_linear_channel_transform_candidate"
        if has_channel:
            return "limit_channel_expression_candidate"
        return "limit_expression_candidate"
    if has_abs and has_channel:
        return "absolute_channel_transform_candidate"
    if has_channel and has_number and has_arithmetic:
        return "linear_channel_transform_candidate"
    if has_channel:
        return "channel_reference_expression_candidate"
    return "opaque_expression_candidate"


def _papr_constraint_expression_numeric_roles(expression: str) -> Tuple[str, ...]:
    text = str(expression or "")
    limit_tail_start = _papr_limit_tail_start(text)
    roles: List[str] = []
    for match in _PAPR_EXPRESSION_NUMBER_RE.finditer(text):
        previous = _previous_non_space(text, match.start())
        if limit_tail_start > 0 and match.start() >= limit_tail_start:
            role = "limit_argument"
        elif previous == "*":
            role = "channel_coefficient"
        elif previous == "/":
            role = "channel_divisor"
        elif previous in {"+", "-"}:
            role = "additive_offset"
        else:
            role = "numeric_constant"
        roles.append(role)
    return tuple(roles)


def _papr_limit_tail_start(expression: str) -> int:
    match = _PAPR_LIMIT_OPERATOR_RE.search(expression)
    if match is None:
        return 0
    open_index = expression.find("(", match.end())
    if open_index < 0:
        return 0
    depth = 0
    for index in range(open_index, len(expression)):
        char = expression[index]
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
            if depth == 0:
                return index + 1
    return 0


def _previous_non_space(text: str, offset: int) -> str:
    for index in range(max(0, offset) - 1, -1, -1):
        char = text[index]
        if not char.isspace():
            return char
    return ""


def _papr_constraint_expression_summary(candidates: Sequence[Mapping[str, object]]) -> Dict[str, object]:
    if not candidates:
        return {}
    role_counts: Counter[str] = Counter()
    shape_counts: Counter[str] = Counter()
    channel_counts: Counter[str] = Counter()
    limit_operator_counts: Counter[str] = Counter()
    numeric_role_counts: Counter[str] = Counter()
    syntax_signature_counts: Counter[str] = Counter()
    numeric_value_count = 0
    numeric_value_row_count = 0
    for row in candidates:
        role = str(row.get("expression_role") or "")
        if role:
            role_counts[role] += 1
        shape = str(row.get("expression_shape") or "")
        if shape:
            shape_counts[shape] += 1
        for channel in row.get("expression_channels") or ():
            channel_counts[str(channel)] += 1
        for operator in row.get("limit_operators") or ():
            limit_operator_counts[str(operator)] += 1
        for numeric_role in row.get("expression_numeric_roles") or ():
            numeric_role_counts[str(numeric_role)] += 1
        syntax_signature = str(row.get("expression_syntax_signature") or "")
        if syntax_signature:
            signature_role = role or "expression"
            syntax_signature_counts[f"role={signature_role}|{syntax_signature}"] += 1
        numeric_values = row.get("expression_numeric_values") or ()
        if numeric_values:
            numeric_value_row_count += 1
            numeric_value_count += len(tuple(numeric_values))
    return {
        "status": "readable_expression_tokens_solver_semantics_unknown",
        "token_confidence": "proven",
        "shape_confidence": "inferred_readable_expression_syntax",
        "semantics_confidence": "unknown",
        "expression_role_counts": dict(sorted(role_counts.items())),
        "shape_counts": dict(sorted(shape_counts.items())),
        "channel_counts": dict(sorted(channel_counts.items())),
        "limit_operator_counts": dict(sorted(limit_operator_counts.items())),
        "numeric_role_counts": dict(sorted(numeric_role_counts.items())),
        "syntax_signature_counts": dict(sorted(syntax_signature_counts.items())),
        "numeric_value_row_count": numeric_value_row_count,
        "numeric_value_count": numeric_value_count,
    }


def _papr_constraint_offset_summary(candidates: Sequence[Mapping[str, object]]) -> Dict[str, object]:
    if not candidates:
        return {}
    return {
        "status": "readable_string_offsets_candidate_record_map",
        "offset_confidence": "proven",
        "record_confidence": "inferred_nearby_string_order",
        "candidate_count": len(candidates),
        "target_offset_count": sum(1 for row in candidates if int(row.get("target_bone_offset") or 0) > 0),
        "helper_offset_count": sum(1 for row in candidates if int(row.get("helper_bone_offset") or 0) > 0),
        "parent_offset_count": sum(1 for row in candidates if int(row.get("parent_bone_offset") or 0) > 0),
    }


def _papr_constraint_record_layout_summary(candidates: Sequence[Mapping[str, object]]) -> Dict[str, object]:
    if not candidates:
        return {}
    layout_counts: Counter[str] = Counter()
    field_sequence_counts: Counter[str] = Counter()
    gap_status_counts: Counter[str] = Counter()
    gap_class_counts: Counter[str] = Counter()
    gap_scalar_status_counts: Counter[str] = Counter()
    gap_scalar_kind_counts: Counter[str] = Counter()
    gap_numeric_match_status_counts: Counter[str] = Counter()
    gap_numeric_match_role_counts: Counter[str] = Counter()
    gap_numeric_match_scalar_kind_counts: Counter[str] = Counter()
    gap_numeric_match_storage_counts: Counter[str] = Counter()
    gap_numeric_match_pair_counts: Counter[str] = Counter()
    gap_numeric_match_value_confidence_counts: Counter[str] = Counter()
    gap_numeric_match_family_counts: Counter[str] = Counter()
    gap_numeric_match_family_row_counts: Counter[str] = Counter()
    gap_numeric_match_family_role_counts: Dict[str, Counter[str]] = defaultdict(Counter)
    gap_numeric_match_family_pair_counts: Dict[str, Counter[str]] = defaultdict(Counter)
    gap_numeric_match_family_value_confidence_counts: Dict[str, Counter[str]] = defaultdict(Counter)
    gap_numeric_match_signature_counts: Counter[str] = Counter()
    gap_numeric_match_candidate_relative_signature_counts: Counter[str] = Counter()
    gap_numeric_match_previous_delta_counts: Counter[str] = Counter()
    gap_numeric_match_next_delta_counts: Counter[str] = Counter()
    gap_numeric_match_candidate_relative_offset_counts: Counter[str] = Counter()
    gap_numeric_match_previous_deltas: List[int] = []
    gap_numeric_match_next_deltas: List[int] = []
    gap_numeric_match_candidate_relative_offsets: List[int] = []
    gap_numeric_match_rows: List[Dict[str, object]] = []
    span_sizes: List[int] = []
    gap_pair_count = 0
    max_gap_size = 0
    gap_aligned_word_count = 0
    gap_scalar_candidate_count = 0
    max_gap_scalar_candidate_count = 0
    gap_numeric_match_count = 0
    max_gap_numeric_match_count = 0
    for row in candidates:
        layout_status = str(row.get("record_layout_status") or "unknown")
        layout_counts[layout_status] += 1
        field_sequence = tuple(str(value) for value in row.get("record_field_sequence") or () if str(value))
        if field_sequence:
            field_sequence_counts[">".join(field_sequence)] += 1
        gap_status = str(row.get("record_gap_status") or "")
        if gap_status:
            gap_status_counts[gap_status] += 1
        for gap_class in row.get("record_gap_classes") or ():
            gap_class_counts[str(gap_class)] += 1
        gap_pair_count += int(row.get("record_gap_count") or 0)
        max_gap_size = max(max_gap_size, int(row.get("record_gap_max_size") or 0))
        gap_scalar_status = str(row.get("record_gap_scalar_status") or "")
        if gap_scalar_status:
            gap_scalar_status_counts[gap_scalar_status] += 1
        scalar_kind_counts = row.get("record_gap_scalar_kind_counts")
        if isinstance(scalar_kind_counts, Mapping):
            for scalar_kind, count in scalar_kind_counts.items():
                gap_scalar_kind_counts[str(scalar_kind)] += int(count or 0)
        gap_aligned_word_count += int(row.get("record_gap_aligned_word_count") or 0)
        candidate_scalar_count = int(row.get("record_gap_scalar_candidate_count") or 0)
        gap_scalar_candidate_count += candidate_scalar_count
        max_gap_scalar_candidate_count = max(max_gap_scalar_candidate_count, candidate_scalar_count)
        match_status = str(row.get("record_gap_numeric_match_status") or "")
        if match_status:
            gap_numeric_match_status_counts[match_status] += 1
        match_role_counts = row.get("record_gap_numeric_match_role_counts")
        if isinstance(match_role_counts, Mapping):
            for role, count in match_role_counts.items():
                gap_numeric_match_role_counts[str(role)] += int(count or 0)
        match_scalar_kind_counts = row.get("record_gap_numeric_match_scalar_kind_counts")
        if isinstance(match_scalar_kind_counts, Mapping):
            for scalar_kind, count in match_scalar_kind_counts.items():
                gap_numeric_match_scalar_kind_counts[str(scalar_kind)] += int(count or 0)
        match_storage_counts = row.get("record_gap_numeric_match_storage_counts")
        if isinstance(match_storage_counts, Mapping):
            for storage, count in match_storage_counts.items():
                gap_numeric_match_storage_counts[str(storage)] += int(count or 0)
        match_pair_counts = row.get("record_gap_numeric_match_pair_counts")
        if isinstance(match_pair_counts, Mapping):
            for pair, count in match_pair_counts.items():
                gap_numeric_match_pair_counts[str(pair)] += int(count or 0)
        match_value_confidence_counts = row.get("record_gap_numeric_match_value_confidence_counts")
        if isinstance(match_value_confidence_counts, Mapping):
            for confidence, count in match_value_confidence_counts.items():
                gap_numeric_match_value_confidence_counts[str(confidence)] += int(count or 0)
        match_previous_delta_counts = row.get("record_gap_numeric_match_previous_delta_counts")
        if isinstance(match_previous_delta_counts, Mapping):
            for delta, count in match_previous_delta_counts.items():
                gap_numeric_match_previous_delta_counts[str(delta)] += int(count or 0)
        match_next_delta_counts = row.get("record_gap_numeric_match_next_delta_counts")
        if isinstance(match_next_delta_counts, Mapping):
            for delta, count in match_next_delta_counts.items():
                gap_numeric_match_next_delta_counts[str(delta)] += int(count or 0)
        match_candidate_relative_offset_counts = row.get(
            "record_gap_numeric_match_candidate_relative_offset_counts"
        )
        if isinstance(match_candidate_relative_offset_counts, Mapping):
            for offset, count in match_candidate_relative_offset_counts.items():
                gap_numeric_match_candidate_relative_offset_counts[str(offset)] += int(count or 0)
        candidate_match_count = int(row.get("record_gap_numeric_match_count") or 0)
        gap_numeric_match_count += candidate_match_count
        max_gap_numeric_match_count = max(max_gap_numeric_match_count, candidate_match_count)
        if candidate_match_count > 0:
            family = str(row.get("constraint_type") or "constraint_candidate")
            gap_numeric_match_family_counts[family] += candidate_match_count
            gap_numeric_match_family_row_counts[family] += 1
            if isinstance(match_role_counts, Mapping):
                for role, count in match_role_counts.items():
                    gap_numeric_match_family_role_counts[family][str(role)] += int(count or 0)
            if isinstance(match_pair_counts, Mapping):
                for pair, count in match_pair_counts.items():
                    gap_numeric_match_family_pair_counts[family][str(pair)] += int(count or 0)
            if isinstance(match_value_confidence_counts, Mapping):
                for confidence, count in match_value_confidence_counts.items():
                    gap_numeric_match_family_value_confidence_counts[family][str(confidence)] += int(count or 0)
            match_signature_counts = row.get("record_gap_numeric_match_signature_counts")
            if isinstance(match_signature_counts, Mapping):
                for signature, count in match_signature_counts.items():
                    gap_numeric_match_signature_counts[f"family={family}|{signature}"] += int(count or 0)
            match_candidate_relative_signature_counts = row.get(
                "record_gap_numeric_match_candidate_relative_signature_counts"
            )
            if isinstance(match_candidate_relative_signature_counts, Mapping):
                for signature, count in match_candidate_relative_signature_counts.items():
                    gap_numeric_match_candidate_relative_signature_counts[
                        f"family={family}|{signature}"
                    ] += int(count or 0)
            match_rows = row.get("record_gap_numeric_match_rows")
            if isinstance(match_rows, tuple | list):
                for match_row in match_rows:
                    if len(gap_numeric_match_rows) >= 16:
                        break
                    if not isinstance(match_row, Mapping):
                        continue
                    candidate_offset = int(row.get("offset") or 0)
                    match_offset = int(match_row.get("offset") or 0)
                    candidate_relative_offset = match_row.get("candidate_relative_offset")
                    if candidate_relative_offset is None and candidate_offset > 0 and match_offset > 0:
                        candidate_relative_offset = match_offset - candidate_offset
                    gap_numeric_match_rows.append(
                        {
                            "candidate_offset": candidate_offset,
                            "constraint_type": family,
                            "expression": str(row.get("expression") or ""),
                            "match_offset": match_offset,
                            "candidate_relative_offset": int(candidate_relative_offset or 0),
                            "between_fields": str(match_row.get("between_fields") or ""),
                            "numeric_value": str(match_row.get("numeric_value") or ""),
                            "numeric_role": str(match_row.get("numeric_role") or ""),
                            "storage": str(match_row.get("storage") or ""),
                            "scalar_kind": str(match_row.get("scalar_kind") or ""),
                            "scalar_value": match_row.get("scalar_value"),
                            "previous_field_end_delta": int(match_row.get("previous_field_end_delta") or 0),
                            "next_field_start_delta": int(match_row.get("next_field_start_delta") or 0),
                            "value_confidence": str(match_row.get("value_confidence") or ""),
                            "match_signature": f"family={family}|{str(match_row.get('match_signature') or '')}",
                            "candidate_relative_match_signature": (
                                f"family={family}|{str(match_row.get('candidate_relative_match_signature') or '')}"
                                if match_row.get("candidate_relative_match_signature")
                                else ""
                            ),
                        }
                    )
            try:
                gap_numeric_match_previous_deltas.append(int(row.get("record_gap_numeric_match_min_previous_delta") or 0))
                gap_numeric_match_previous_deltas.append(int(row.get("record_gap_numeric_match_max_previous_delta") or 0))
                gap_numeric_match_next_deltas.append(int(row.get("record_gap_numeric_match_min_next_delta") or 0))
                gap_numeric_match_next_deltas.append(int(row.get("record_gap_numeric_match_max_next_delta") or 0))
                gap_numeric_match_candidate_relative_offsets.append(
                    int(row.get("record_gap_numeric_match_min_candidate_relative_offset") or 0)
                )
                gap_numeric_match_candidate_relative_offsets.append(
                    int(row.get("record_gap_numeric_match_max_candidate_relative_offset") or 0)
                )
            except (TypeError, ValueError):
                pass
        span_size = int(row.get("record_span_size") or 0)
        if span_size > 0:
            span_sizes.append(span_size)
    return {
        "status": "nearby_string_span_layout_evidence",
        "confidence": "inferred_nearby_string_order",
        "field_sequence_confidence": "proven_decoded_string_offset_order",
        "field_sequence_counts": dict(sorted(field_sequence_counts.items())),
        "layout_status_counts": dict(sorted(layout_counts.items())),
        "gap_status_counts": dict(sorted(gap_status_counts.items())),
        "gap_class_counts": dict(sorted(gap_class_counts.items())),
        "gap_scalar_status_counts": dict(sorted(gap_scalar_status_counts.items())),
        "gap_scalar_kind_counts": dict(sorted(gap_scalar_kind_counts.items())),
        "gap_numeric_match_status_counts": dict(sorted(gap_numeric_match_status_counts.items())),
        "gap_numeric_match_role_counts": dict(sorted(gap_numeric_match_role_counts.items())),
        "gap_numeric_match_scalar_kind_counts": dict(sorted(gap_numeric_match_scalar_kind_counts.items())),
        "gap_numeric_match_storage_counts": dict(sorted(gap_numeric_match_storage_counts.items())),
        "gap_numeric_match_pair_counts": dict(sorted(gap_numeric_match_pair_counts.items())),
        "gap_numeric_match_value_confidence_counts": dict(sorted(gap_numeric_match_value_confidence_counts.items())),
        "gap_numeric_match_family_counts": dict(sorted(gap_numeric_match_family_counts.items())),
        "gap_numeric_match_family_row_counts": dict(sorted(gap_numeric_match_family_row_counts.items())),
        "gap_numeric_match_family_role_counts": {
            family: dict(sorted(counts.items()))
            for family, counts in sorted(gap_numeric_match_family_role_counts.items())
        },
        "gap_numeric_match_family_pair_counts": {
            family: dict(sorted(counts.items()))
            for family, counts in sorted(gap_numeric_match_family_pair_counts.items())
        },
        "gap_numeric_match_family_value_confidence_counts": {
            family: dict(sorted(counts.items()))
            for family, counts in sorted(gap_numeric_match_family_value_confidence_counts.items())
        },
        "gap_numeric_match_signature_counts": dict(sorted(gap_numeric_match_signature_counts.items())),
        "gap_numeric_match_candidate_relative_signature_counts": dict(
            sorted(gap_numeric_match_candidate_relative_signature_counts.items())
        ),
        "gap_numeric_match_previous_delta_counts": dict(sorted(gap_numeric_match_previous_delta_counts.items())),
        "gap_numeric_match_next_delta_counts": dict(sorted(gap_numeric_match_next_delta_counts.items())),
        "gap_numeric_match_candidate_relative_offset_counts": dict(
            sorted(gap_numeric_match_candidate_relative_offset_counts.items())
        ),
        "gap_numeric_match_offset_confidence": (
            "observed_relative_to_decoded_string_gap_boundaries_value_layout_unproven"
            if gap_numeric_match_count
            else ""
        ),
        "gap_numeric_match_candidate_relative_offset_confidence": (
            "observed_relative_to_inferred_candidate_offset_value_layout_unproven"
            if gap_numeric_match_candidate_relative_offset_counts
            else ""
        ),
        "gap_pair_count": int(gap_pair_count),
        "max_gap_size": int(max_gap_size),
        "gap_aligned_word_count": int(gap_aligned_word_count),
        "gap_scalar_candidate_count": int(gap_scalar_candidate_count),
        "max_gap_scalar_candidate_count": int(max_gap_scalar_candidate_count),
        "gap_numeric_match_count": int(gap_numeric_match_count),
        "max_gap_numeric_match_count": int(max_gap_numeric_match_count),
        "gap_numeric_match_rows": tuple(gap_numeric_match_rows),
        "min_gap_numeric_match_previous_delta": min(gap_numeric_match_previous_deltas) if gap_numeric_match_previous_deltas else 0,
        "max_gap_numeric_match_previous_delta": max(gap_numeric_match_previous_deltas) if gap_numeric_match_previous_deltas else 0,
        "min_gap_numeric_match_next_delta": min(gap_numeric_match_next_deltas) if gap_numeric_match_next_deltas else 0,
        "max_gap_numeric_match_next_delta": max(gap_numeric_match_next_deltas) if gap_numeric_match_next_deltas else 0,
        "min_gap_numeric_match_candidate_relative_offset": (
            min(gap_numeric_match_candidate_relative_offsets) if gap_numeric_match_candidate_relative_offsets else 0
        ),
        "max_gap_numeric_match_candidate_relative_offset": (
            max(gap_numeric_match_candidate_relative_offsets) if gap_numeric_match_candidate_relative_offsets else 0
        ),
        "candidate_count": len(candidates),
        "min_span_size": min(span_sizes) if span_sizes else 0,
        "max_span_size": max(span_sizes) if span_sizes else 0,
    }


def _papr_constraint_analysis_document(
    data: bytes,
    string_records: Sequence[_BinarySidecarStringRecord],
    related_references: Sequence[object],
    *,
    max_rows: int = 96,
) -> Dict[str, object]:
    role_counts: Counter[str] = Counter()
    all_evidence_rows: List[Dict[str, object]] = []
    evidence_rows: List[Dict[str, object]] = []
    for record in string_records:
        role = _papr_constraint_string_role(record.text)
        if not role:
            continue
        role_counts[role] += 1
        row = {
            "offset": int(record.offset),
            "text": record.text,
            "role": role,
            "field_confidence": "proven_readable_string",
            "role_confidence": "inferred",
        }
        all_evidence_rows.append(row)
        if len(evidence_rows) >= max_rows:
            continue
        evidence_rows.append(row)
    all_record_candidates = _papr_constraint_record_candidates(all_evidence_rows, data=data, max_rows=None)
    record_candidates = all_record_candidates[:128]

    physics_rows: List[Dict[str, object]] = []
    for reference in related_references:
        reference_kind = str(getattr(reference, "reference_kind", "") or "")
        resolved_path = str(getattr(reference, "resolved_archive_path", "") or "")
        reference_name = str(getattr(reference, "reference_name", "") or "")
        if reference_kind != "physics" and not resolved_path.lower().endswith((".hkx", ".hkt")):
            continue
        physics_rows.append(
            {
                "reference_name": reference_name,
                "resolved_archive_path": resolved_path,
                "relation_confidence": str(getattr(reference, "relation_confidence", "") or "unknown"),
                "relation_reason": str(getattr(reference, "relation_reason", "") or ""),
            }
        )

    return {
        "recognized": bool(evidence_rows or physics_rows),
        "status": "read_only_constraint_string_evidence" if evidence_rows or physics_rows else "no_constraint_evidence_recovered",
        "constraint_solving_supported": False,
        "string_evidence_count": int(sum(role_counts.values())),
        "role_counts": dict(sorted(role_counts.items())),
        "evidence_rows": evidence_rows,
        "record_candidate_count": len(all_record_candidates),
        "record_candidates": record_candidates,
        "expression_evidence": _papr_constraint_expression_summary(all_record_candidates),
        "offset_evidence": _papr_constraint_offset_summary(all_record_candidates),
        "record_layout_evidence": _papr_constraint_record_layout_summary(all_record_candidates),
        "related_physics_rows": physics_rows,
        "proof_gap": (
            "PAPR readable strings expose bone names and expression text, and nearby strings can form inferred record candidates, but current recovery does not bind records, value offsets, or solver semantics."
            if evidence_rows or physics_rows
            else "No PAPR constraint strings or physics references were recovered from this payload."
        ),
    }


def _papr_constraint_record_candidates(
    evidence_rows: Sequence[Mapping[str, object]],
    *,
    data: bytes = b"",
    max_rows: int | None = 64,
) -> List[Dict[str, object]]:
    candidates: List[Dict[str, object]] = []
    last_parent: Mapping[str, object] | None = None
    last_bone: Mapping[str, object] | None = None
    last_helper: Mapping[str, object] | None = None
    for row in evidence_rows:
        role = str(row.get("role") or "")
        offset = int(row.get("offset") or 0)
        if role == "parent_bone_reference":
            last_parent = row
            continue
        if role == "helper_bone_reference":
            last_helper = row
            last_bone = row
            continue
        if role == "bone_reference":
            last_bone = row
            continue
        if role not in {"driver_expression", "limit_expression"}:
            continue
        target = last_bone if last_bone is not None and offset - int(last_bone.get("offset") or 0) <= 192 else None
        helper = last_helper if last_helper is not None and offset - int(last_helper.get("offset") or 0) <= 192 else None
        parent = last_parent if last_parent is not None and offset - int(last_parent.get("offset") or 0) <= 768 else None
        if target is None and parent is None:
            continue
        expression = str(row.get("text") or "")
        expression_evidence = _papr_constraint_expression_evidence(expression)
        target_offset = int(target.get("offset") or 0) if target is not None else 0
        helper_offset = int(helper.get("offset") or 0) if helper is not None else 0
        parent_offset = int(parent.get("offset") or 0) if parent is not None else 0
        span_start, span_end, span_field_count = _papr_candidate_span(row, target, helper, parent)
        field_sequence = _papr_candidate_field_sequence(
            ("parent", parent),
            ("helper", helper),
            ("target", target),
            ("expression", row),
        )
        gap_evidence = _papr_candidate_gap_evidence(
            data,
            ("parent", parent),
            ("helper", helper),
            ("target", target),
            ("expression", row),
            candidate_offset=offset,
            expression_numeric_values=expression_evidence.get("expression_numeric_values") or (),
            expression_numeric_roles=expression_evidence.get("expression_numeric_roles") or (),
        )
        candidates.append(
            {
                "offset": offset,
                "expression_offset": offset,
                "constraint_type": "local_transform_limit_candidate" if role == "limit_expression" else "driver_expression_candidate",
                "expression": expression,
                "expression_role": role,
                "target_bone": str(target.get("text") or "") if target is not None else "",
                "target_bone_offset": target_offset,
                "target_bone_delta": offset - target_offset if target_offset > 0 else 0,
                "parent_bone": str(parent.get("text") or "") if parent is not None else "",
                "parent_bone_offset": parent_offset,
                "parent_bone_delta": offset - parent_offset if parent_offset > 0 else 0,
                "helper_bone": str(helper.get("text") or "") if helper is not None else "",
                "helper_bone_offset": helper_offset,
                "helper_bone_delta": offset - helper_offset if helper_offset > 0 else 0,
                "field_confidence": "proven_readable_strings",
                "field_offset_confidence": "proven_decoded_string_offsets",
                "record_confidence": "inferred_nearby_string_order",
                "record_span_start": span_start,
                "record_span_end": span_end,
                "record_span_size": max(0, span_end - span_start),
                "record_span_field_count": span_field_count,
                "record_field_sequence": field_sequence,
                "record_field_sequence_confidence": "proven_decoded_string_offset_order",
                **gap_evidence,
                "record_layout_status": "nearby_string_span_only_value_layout_unproven",
                "solver_status": "blocked_record_layout_unproven",
                **expression_evidence,
            }
        )
        if max_rows is not None and len(candidates) >= max_rows:
            break
    return candidates


def _papr_candidate_span(*rows: Mapping[str, object] | None) -> Tuple[int, int, int]:
    spans: List[Tuple[int, int]] = []
    for row in rows:
        if row is None:
            continue
        offset = int(row.get("offset") or 0)
        text = str(row.get("text") or "")
        if offset <= 0 or not text:
            continue
        spans.append((offset, offset + len(text.encode("ascii", errors="ignore")) + 1))
    if not spans:
        return 0, 0, 0
    return min(start for start, _end in spans), max(end for _start, end in spans), len(spans)


def _papr_candidate_field_sequence(*fields: Tuple[str, Mapping[str, object] | None]) -> Tuple[str, ...]:
    ordered: List[Tuple[int, int, str]] = []
    for index, (label, row) in enumerate(fields):
        if row is None:
            continue
        offset = int(row.get("offset") or 0)
        text = str(row.get("text") or "")
        if offset <= 0 or not text:
            continue
        ordered.append((offset, index, label))
    ordered.sort()
    return tuple(label for _offset, _index, label in ordered)


def _papr_candidate_gap_evidence(
    data: bytes,
    *fields: Tuple[str, Mapping[str, object] | None],
    candidate_offset: int = 0,
    expression_numeric_values: Sequence[object] = (),
    expression_numeric_roles: Sequence[object] = (),
) -> Dict[str, object]:
    ordered: List[Tuple[int, int, str, str]] = []
    for index, (label, row) in enumerate(fields):
        if row is None:
            continue
        offset = int(row.get("offset") or 0)
        text = str(row.get("text") or "")
        if offset <= 0 or not text:
            continue
        ordered.append((offset, index, label, text))
    ordered.sort()
    gap_classes: List[str] = []
    gap_sizes: List[int] = []
    scalar_kind_counts: Counter[str] = Counter()
    numeric_match_role_counts: Counter[str] = Counter()
    numeric_match_scalar_kind_counts: Counter[str] = Counter()
    numeric_match_storage_counts: Counter[str] = Counter()
    numeric_match_pair_counts: Counter[str] = Counter()
    numeric_match_value_confidence_counts: Counter[str] = Counter()
    numeric_match_signature_counts: Counter[str] = Counter()
    numeric_match_candidate_relative_signature_counts: Counter[str] = Counter()
    numeric_match_previous_delta_counts: Counter[str] = Counter()
    numeric_match_next_delta_counts: Counter[str] = Counter()
    numeric_match_candidate_relative_offset_counts: Counter[str] = Counter()
    numeric_match_previous_deltas: List[int] = []
    numeric_match_next_deltas: List[int] = []
    numeric_match_candidate_relative_offsets: List[int] = []
    numeric_match_rows: List[Dict[str, object]] = []
    numeric_entries = _papr_expression_numeric_entries(expression_numeric_values, expression_numeric_roles)
    aligned_word_count = 0
    scalar_candidate_count = 0
    for current, following in zip(ordered, ordered[1:]):
        offset, _index, label, text = current
        next_offset, _next_index, next_label, _next_text = following
        end = offset + len(text.encode("ascii", errors="ignore")) + 1
        raw_gap_size = next_offset - end
        if raw_gap_size < 0:
            gap_class = "overlap_or_shared_string"
            gap_size = 0
        elif raw_gap_size == 0:
            gap_class = "contiguous_strings"
            gap_size = 0
        else:
            chunk = data[end:next_offset] if data else b""
            gap_class = _papr_gap_class(chunk)
            gap_size = raw_gap_size
            aligned_offset = (end + 3) & ~3
            while aligned_offset + 4 <= next_offset and aligned_offset + 4 <= len(data):
                word = struct.unpack_from("<I", data, aligned_offset)[0]
                float_value = struct.unpack_from("<f", data, aligned_offset)[0]
                scalar_kind = _papr_gap_scalar_kind(word, float_value)
                aligned_word_count += 1
                if scalar_kind != "opaque_word":
                    scalar_kind_counts[scalar_kind] += 1
                    scalar_candidate_count += 1
                    for numeric_match in _papr_gap_numeric_matches(
                        word,
                        float_value,
                        numeric_entries,
                        scalar_kind=scalar_kind,
                    ):
                        pair = f"{label}>{next_label}"
                        previous_delta = int(aligned_offset - end)
                        next_delta = int(next_offset - (aligned_offset + 4))
                        candidate_relative_offset = int(aligned_offset - candidate_offset) if candidate_offset > 0 else 0
                        numeric_role = str(numeric_match["numeric_role"])
                        value_confidence = str(
                            numeric_match.get("value_confidence")
                            or "numeric_match_value_layout_unproven"
                        )
                        match_signature = _papr_gap_numeric_match_signature(
                            numeric_role=numeric_role,
                            pair=pair,
                            storage=str(numeric_match["storage"]),
                            scalar_kind=scalar_kind,
                            value_confidence=value_confidence,
                            previous_delta=previous_delta,
                            next_delta=next_delta,
                        )
                        candidate_relative_match_signature = (
                            f"{match_signature}|rel={candidate_relative_offset}"
                            if candidate_offset > 0
                            else ""
                        )
                        numeric_match_role_counts[numeric_role] += 1
                        numeric_match_scalar_kind_counts[scalar_kind] += 1
                        numeric_match_storage_counts[str(numeric_match["storage"])] += 1
                        numeric_match_pair_counts[pair] += 1
                        numeric_match_value_confidence_counts[value_confidence] += 1
                        numeric_match_signature_counts[match_signature] += 1
                        if candidate_relative_match_signature:
                            numeric_match_candidate_relative_signature_counts[
                                candidate_relative_match_signature
                            ] += 1
                        numeric_match_previous_delta_counts[str(previous_delta)] += 1
                        numeric_match_next_delta_counts[str(next_delta)] += 1
                        if candidate_offset > 0:
                            numeric_match_candidate_relative_offset_counts[str(candidate_relative_offset)] += 1
                            numeric_match_candidate_relative_offsets.append(candidate_relative_offset)
                        numeric_match_previous_deltas.append(previous_delta)
                        numeric_match_next_deltas.append(next_delta)
                        if len(numeric_match_rows) < 8:
                            numeric_match_rows.append(
                                {
                                    "offset": int(aligned_offset),
                                    "between_fields": pair,
                                    "previous_field_end_delta": previous_delta,
                                    "next_field_start_delta": next_delta,
                                    "candidate_relative_offset": candidate_relative_offset,
                                    **numeric_match,
                                    "value_confidence": value_confidence,
                                    "match_signature": match_signature,
                                    "candidate_relative_match_signature": candidate_relative_match_signature,
                                }
                            )
                aligned_offset += 4
        gap_classes.append(gap_class)
        gap_sizes.append(gap_size)
    gap_class_counts = dict(sorted(Counter(gap_classes).items()))
    numeric_match_count = int(sum(numeric_match_role_counts.values()))
    return {
        "record_gap_status": _papr_gap_status(gap_classes),
        "record_gap_classes": tuple(gap_classes),
        "record_gap_class_counts": gap_class_counts,
        "record_gap_count": len(gap_classes),
        "record_gap_total_size": int(sum(gap_sizes)),
        "record_gap_max_size": max(gap_sizes) if gap_sizes else 0,
        "record_gap_confidence": "observed_between_decoded_string_offsets" if gap_classes else "",
        "record_gap_scalar_status": "unbound_interfield_scalar_candidates" if scalar_candidate_count else "no_interfield_scalar_candidates",
        "record_gap_scalar_kind_counts": dict(sorted(scalar_kind_counts.items())),
        "record_gap_aligned_word_count": int(aligned_word_count),
        "record_gap_scalar_candidate_count": int(scalar_candidate_count),
        "record_gap_scalar_confidence": "unbound_aligned_interfield_gap_scan" if aligned_word_count else "",
        "record_gap_numeric_match_status": "unbound_scalar_numeric_constant_matches" if numeric_match_count else "no_scalar_numeric_constant_matches",
        "record_gap_numeric_match_role_counts": dict(sorted(numeric_match_role_counts.items())),
        "record_gap_numeric_match_scalar_kind_counts": dict(sorted(numeric_match_scalar_kind_counts.items())),
        "record_gap_numeric_match_storage_counts": dict(sorted(numeric_match_storage_counts.items())),
        "record_gap_numeric_match_pair_counts": dict(sorted(numeric_match_pair_counts.items())),
        "record_gap_numeric_match_value_confidence_counts": dict(sorted(numeric_match_value_confidence_counts.items())),
        "record_gap_numeric_match_signature_counts": dict(sorted(numeric_match_signature_counts.items())),
        "record_gap_numeric_match_candidate_relative_signature_counts": dict(
            sorted(numeric_match_candidate_relative_signature_counts.items())
        ),
        "record_gap_numeric_match_previous_delta_counts": dict(sorted(numeric_match_previous_delta_counts.items())),
        "record_gap_numeric_match_next_delta_counts": dict(sorted(numeric_match_next_delta_counts.items())),
        "record_gap_numeric_match_candidate_relative_offset_counts": dict(
            sorted(numeric_match_candidate_relative_offset_counts.items())
        ),
        "record_gap_numeric_match_count": numeric_match_count,
        "record_gap_numeric_match_rows": tuple(numeric_match_rows),
        "record_gap_numeric_match_min_previous_delta": min(numeric_match_previous_deltas) if numeric_match_previous_deltas else 0,
        "record_gap_numeric_match_max_previous_delta": max(numeric_match_previous_deltas) if numeric_match_previous_deltas else 0,
        "record_gap_numeric_match_min_next_delta": min(numeric_match_next_deltas) if numeric_match_next_deltas else 0,
        "record_gap_numeric_match_max_next_delta": max(numeric_match_next_deltas) if numeric_match_next_deltas else 0,
        "record_gap_numeric_match_min_candidate_relative_offset": (
            min(numeric_match_candidate_relative_offsets) if numeric_match_candidate_relative_offsets else 0
        ),
        "record_gap_numeric_match_max_candidate_relative_offset": (
            max(numeric_match_candidate_relative_offsets) if numeric_match_candidate_relative_offsets else 0
        ),
        "record_gap_numeric_match_offset_confidence": (
            "observed_relative_to_decoded_string_gap_boundaries_value_layout_unproven"
            if numeric_match_count
            else ""
        ),
        "record_gap_numeric_match_candidate_relative_offset_confidence": (
            "observed_relative_to_inferred_candidate_offset_value_layout_unproven"
            if numeric_match_count and candidate_offset > 0
            else ""
        ),
        "record_gap_numeric_match_confidence": "exact_numeric_text_vs_interfield_scalar_match_value_layout_unproven" if numeric_match_count else "",
    }


def _papr_gap_numeric_match_signature(
    *,
    numeric_role: str,
    pair: str,
    storage: str,
    scalar_kind: str,
    value_confidence: str,
    previous_delta: int,
    next_delta: int,
) -> str:
    return (
        f"role={numeric_role}|pair={pair}|storage={storage}|scalar={scalar_kind}|"
        f"value={value_confidence}|prev={previous_delta}|next={next_delta}"
    )


def _papr_expression_numeric_entries(
    numeric_values: Sequence[object],
    numeric_roles: Sequence[object],
) -> Tuple[Tuple[str, str, float, int | None], ...]:
    roles = tuple(str(role) for role in numeric_roles or ())
    entries: List[Tuple[str, str, float, int | None]] = []
    for index, value in enumerate(numeric_values or ()):
        text = str(value)
        try:
            float_value = float(text)
        except ValueError:
            continue
        role = roles[index] if index < len(roles) and roles[index] else "numeric_constant"
        integer_value: int | None = None
        lowered = text.lower()
        if "." not in lowered and "e" not in lowered:
            try:
                integer_value = int(text, 10)
            except ValueError:
                integer_value = None
        entries.append((text, role, float_value, integer_value))
    return tuple(entries)


def _papr_gap_numeric_matches(
    word: int,
    float_value: float,
    numeric_entries: Sequence[Tuple[str, str, float, int | None]],
    *,
    scalar_kind: str,
) -> Tuple[Dict[str, object], ...]:
    if not numeric_entries:
        return ()
    matches: List[Dict[str, object]] = []
    for numeric_text, numeric_role, numeric_value, integer_value in numeric_entries:
        if integer_value is not None and 0 <= integer_value <= 0xFFFFFFFF and word == integer_value:
            matches.append(
                {
                    "numeric_value": numeric_text,
                    "numeric_role": numeric_role,
                    "storage": "u32",
                    "scalar_kind": scalar_kind,
                    "scalar_value": int(word),
                    "value_confidence": "exact_u32_numeric_value_match_layout_unproven",
                }
            )
            continue
        if math.isfinite(float_value) and math.isclose(float_value, numeric_value, rel_tol=1.0e-6, abs_tol=1.0e-6):
            value_confidence = (
                "exact_float32_numeric_value_match_layout_unproven"
                if float_value == numeric_value
                else "approx_float32_numeric_value_match_layout_unproven"
            )
            matches.append(
                {
                    "numeric_value": numeric_text,
                    "numeric_role": numeric_role,
                    "storage": "f32",
                    "scalar_kind": scalar_kind,
                    "scalar_value": float(float_value),
                    "value_confidence": value_confidence,
                }
            )
    return tuple(matches)


def _papr_gap_class(chunk: bytes) -> str:
    if not chunk:
        return "contiguous_strings"
    if all(value == 0 for value in chunk):
        return "zero_padding"
    printable = sum(1 for value in chunk if value in (9, 10, 13) or 32 <= value <= 126)
    if printable / max(len(chunk), 1) >= 0.85:
        return "printable_ascii_gap"
    if chunk.count(0) / max(len(chunk), 1) >= 0.5:
        return "mixed_null_binary_gap"
    return "binary_gap"


def _papr_gap_status(gap_classes: Sequence[str]) -> str:
    classes = set(gap_classes)
    if not classes:
        return ""
    if {"binary_gap", "mixed_null_binary_gap"} & classes:
        return "binary_like_interfield_gap_bytes_unbound"
    if "printable_ascii_gap" in classes:
        return "printable_interfield_gap_bytes_unbound"
    if "zero_padding" in classes:
        return "zero_padding_interfield_gap_bytes_unbound"
    return "no_interfield_gap_payload"


def _papr_gap_scalar_kind(word: int, float_value: float) -> str:
    if word == 0:
        return "zero_word"
    if word == 1:
        return "u32_bool_candidate"
    if 2 <= word <= 255:
        return "u32_u8_candidate"
    if 256 <= word <= 65535:
        return "u32_u16_candidate"
    if math.isfinite(float_value):
        absolute = abs(float_value)
        if 1.0e-6 <= absolute <= 1.0:
            return "f32_unit_candidate"
        if 1.0 < absolute <= 10.0:
            return "f32_small_candidate"
        if 10.0 < absolute <= 360.0:
            return "f32_angle_candidate"
    return "opaque_word"


def build_binary_sidecar_analysis_document(
    data: bytes,
    virtual_path: str,
    *,
    extension: str = "",
    source_entry: Optional[ArchiveEntry] = None,
    archive_entries_by_normalized_path: Optional[Dict[str, Sequence[ArchiveEntry]]] = None,
    archive_entries_by_basename: Optional[Dict[str, Sequence[ArchiveEntry]]] = None,
) -> Dict[str, object]:
    normalized_extension = str(extension or PurePosixPath(str(virtual_path or "")).suffix).strip().lower()
    animation_metadata = (
        _paa_metabin_analysis_document(data, virtual_path)
        if normalized_extension == ".paa_metabin"
        else {}
    )
    seqmt_metadata = (
        _seqmt_analysis_document(data, virtual_path)
        if normalized_extension == ".seqmt"
        else {}
    )
    paccd_metadata = (
        _paccd_analysis_document(data, virtual_path)
        if normalized_extension == ".paccd"
        else {}
    )
    string_records = _extract_binary_string_records(data, sample_limit=262_144, max_strings=512)
    field_records = [
        record
        for record in string_records
        if _looks_like_structured_field_name(record.text)
    ]
    asset_reference_rows = _binary_sidecar_asset_reference_rows(string_records, max_references=96)
    asset_references: List[str] = []
    seen_references: set[str] = set()
    for row in asset_reference_rows:
        path = str(row.get("path") or "").strip()
        normalized = _normalize_model_texture_reference(path)
        if not normalized or normalized in seen_references:
            continue
        seen_references.add(normalized)
        asset_references.append(path)
    for path in _extract_binary_asset_references(data, sample_limit=262_144, max_references=96):
        normalized = _normalize_model_texture_reference(path)
        if not normalized or normalized in seen_references:
            continue
        seen_references.add(normalized)
        asset_references.append(path)
    related_references = _build_binary_sidecar_related_references(
        source_entry,
        asset_references=asset_references,
        archive_entries_by_normalized_path=archive_entries_by_normalized_path,
        archive_entries_by_basename=archive_entries_by_basename,
    )
    offset_candidates = _binary_sidecar_offset_candidates(data)
    count_offset_pairs = _binary_sidecar_count_offset_pairs(data)
    float_rows = _binary_sidecar_float_rows(data)
    animation_keyframe_tables = (
        _binary_sidecar_animation_keyframe_tables(data)
        if normalized_extension == ".paa"
        else []
    )
    schema_declarations = _binary_sidecar_schema_declarations(data, normalized_extension)
    schema_member_rows = [
        row
        for row in schema_declarations.get("declared_member_rows", [])
        if isinstance(row, Mapping)
    ]
    paseq_metadata = (
        _paseq_analysis_document(
            data,
            virtual_path,
            string_records=string_records,
            asset_reference_rows=asset_reference_rows,
            schema_member_rows=schema_member_rows,
        )
        if normalized_extension in _ARCHIVE_ANIMATION_SEQUENCE_EXTENSIONS
        else {}
    )
    papr_metadata = (
        _papr_constraint_analysis_document(data, string_records, related_references)
        if normalized_extension == ".papr"
        else {}
    )
    field_group_func = _binary_sidecar_group_func_for_extension(normalized_extension)
    prefab_evidence_rows = (
        _prefab_evidence_rows(schema_member_rows, asset_references)
        if normalized_extension == ".prefab"
        else []
    )
    prefab_material_override_rows = (
        _prefab_material_override_evidence_rows(schema_member_rows, asset_references)
        if normalized_extension == ".prefab"
        else []
    )
    field_rows = [
        {
            "offset": record.offset,
            "name": record.text,
            "group": field_group_func(record.text),
            "confidence": "readable_string_identifier",
            "status": "experimental_schema_recovery",
        }
        for record in field_records[:256]
    ]
    editable_candidate_rows: List[Dict[str, object]] = []
    for row in float_rows[:16]:
        editable_candidate_rows.append(
            {
                "offset": row["offset"],
                "type": row["type"],
                "value": row["values"],
                "edit_status": "disabled_until_schema_is_proven",
                "confidence": row["confidence"],
            }
        )

    return {
        "document": "Crimson Desert Mod Workbench binary sidecar decode document.",
        "format_status": "experimental_read_only_schema_recovery",
        "source": {
            "path": virtual_path,
            "extension": normalized_extension,
            "kind": _binary_sidecar_kind_label(normalized_extension),
            "size": len(data),
            "sha1": hashlib.sha1(data).hexdigest(),
        },
        "summary": {
            "readable_strings": len(string_records),
            "field_like_identifiers": len(field_records),
            "asset_reference_hints": len(asset_references),
            "related_files_resolved": sum(1 for reference in related_references if reference.resolved_entry is not None),
            "related_file_rows": len(related_references),
            "offset_candidates": len(offset_candidates),
            "count_offset_pair_candidates": len(count_offset_pairs),
            "float_vector_candidates": len(float_rows),
            "animation_keyframe_table_candidates": len(animation_keyframe_tables),
            "animation_keyframe_rows": sum(int(row.get("row_count") or 0) for row in animation_keyframe_tables),
            "schema_declarations": int(schema_declarations.get("declaration_count") or 0),
            "schema_declared_members": len(schema_member_rows),
            "schema_layout_signature": str(schema_declarations.get("layout_signature") or ""),
            "prefab_evidence_rows": len(prefab_evidence_rows),
            "prefab_material_override_rows": len(prefab_material_override_rows),
            "seqmt_recognized": bool(seqmt_metadata.get("recognized"))
            if isinstance(seqmt_metadata, Mapping)
            else False,
            "seqmt_columns": int(seqmt_metadata.get("columns") or 0)
            if isinstance(seqmt_metadata, Mapping)
            else 0,
            "seqmt_rows": int(seqmt_metadata.get("rows") or 0)
            if isinstance(seqmt_metadata, Mapping)
            else 0,
            "seqmt_frame_count": int(seqmt_metadata.get("frame_count") or 0)
            if isinstance(seqmt_metadata, Mapping)
            else 0,
            "seqmt_payload_complete": bool(seqmt_metadata.get("payload_complete"))
            if isinstance(seqmt_metadata, Mapping)
            else False,
            "paccd_recognized": bool(paccd_metadata.get("recognized"))
            if isinstance(paccd_metadata, Mapping)
            else False,
            "paccd_slot_count": int(paccd_metadata.get("slot_count") or 0)
            if isinstance(paccd_metadata, Mapping)
            else 0,
            "paccd_row_stride": int(paccd_metadata.get("row_stride") or 0)
            if isinstance(paccd_metadata, Mapping)
            else 0,
            "animation_metadata_stream_bytes": int(
                ((animation_metadata.get("packed_metadata_stream") or {}).get("stream_size") or 0)
                if isinstance(animation_metadata.get("packed_metadata_stream"), Mapping)
                else 0
            ),
            "animation_metadata_filename_hints": len(animation_metadata.get("filename_hints") or [])
            if isinstance(animation_metadata, Mapping)
            else 0,
            "paseq_timeline_lanes": int(((paseq_metadata.get("timeline") or {}).get("lane_count") or 0))
            if isinstance(paseq_metadata.get("timeline"), Mapping)
            else 0,
            "paseq_timeline_fields": int(((paseq_metadata.get("timeline") or {}).get("timeline_field_count") or 0))
            if isinstance(paseq_metadata.get("timeline"), Mapping)
            else 0,
            "paseq_event_markers": int(((paseq_metadata.get("timeline") or {}).get("event_marker_count") or 0))
            if isinstance(paseq_metadata.get("timeline"), Mapping)
            else 0,
            "paseq_timing_candidates": int(((paseq_metadata.get("timeline") or {}).get("timing_candidate_count") or 0))
            if isinstance(paseq_metadata.get("timeline"), Mapping)
            else 0,
            "papr_constraint_string_evidence": int(papr_metadata.get("string_evidence_count") or 0)
            if isinstance(papr_metadata, Mapping)
            else 0,
            "papr_constraint_related_physics": len(papr_metadata.get("related_physics_rows") or ())
            if isinstance(papr_metadata, Mapping)
            else 0,
        },
        "container": _binary_sidecar_container_summary(data, normalized_extension),
        "header_words_le": _binary_sidecar_header_words(data),
        "schema_declarations": schema_declarations,
        "prefab": {
            "evidence_rows": prefab_evidence_rows,
            "material_override_rows": prefab_material_override_rows,
            "editing_supported": False,
            "note": ".prefab files describe scene/resource/component metadata; renderable geometry usually lives in linked .pac/.pam/.pamlod assets.",
        } if normalized_extension == ".prefab" else {},
        "animation_metadata": animation_metadata,
        "animation": {
            "keyframe_table_candidates": animation_keyframe_tables,
            "editing_supported": False,
            "note": ".paa animation clip rows are exposed as read-only recovery evidence. Channel ownership and write rules are not proven.",
        } if normalized_extension == ".paa" else {},
        "papr": papr_metadata,
        "paseq": paseq_metadata,
        "seqmt": seqmt_metadata,
        "paccd": paccd_metadata,
        "strings": {
            "field_rows": field_rows,
            "readable_rows": [
                {
                    "offset": record.offset,
                    "text": record.text,
                    "kind": "field" if _looks_like_structured_field_name(record.text) else "string",
                }
                for record in string_records[:256]
            ],
        },
        "references": {
            "asset_reference_hints": asset_reference_rows,
            "related_files": _binary_sidecar_reference_document_rows(related_references),
        },
        "tables": {
            "offset_candidates": offset_candidates,
            "count_offset_pair_candidates": count_offset_pairs,
            "float_vector_candidates": float_rows,
            "animation_keyframe_table_candidates": animation_keyframe_tables,
        },
        "editing": {
            "supported": False,
            "policy": "read_only_until_schema_and_no_edit_roundtrip_are_proven",
            "reason": (
                ".meshinfo, .motionblending, .paa, .paa_metabin, .papr, .paseq/.paseqc/.paschedule/.pastage, .prefab, .pappt, .pamhc, .paccd, and .seqmt layout/count semantics are not proven yet. "
                "The app can export decoded declarations and recovery evidence, but it will not write edited values "
                "until exact value offsets, fixed-size fields, array counts, offsets, and no-edit binary rebuilds "
                "are validated."
            ),
            "candidate_rows": editable_candidate_rows,
        },
        "notes": [
            "Offsets are byte offsets in the decoded archive payload used by preview/export.",
            "Schema declarations are length-prefixed member/type rows recovered from the binary; they identify fields but do not prove value write offsets.",
            "Offset/count/float rows are recovery evidence, not stable schema fields.",
            "Related files may include same-stem companions and archive relationship graph matches.",
        ],
    }


def build_binary_sidecar_analysis_json(
    data: bytes,
    virtual_path: str,
    *,
    extension: str = "",
    source_entry: Optional[ArchiveEntry] = None,
    archive_entries_by_normalized_path: Optional[Dict[str, Sequence[ArchiveEntry]]] = None,
    archive_entries_by_basename: Optional[Dict[str, Sequence[ArchiveEntry]]] = None,
) -> str:
    document = build_binary_sidecar_analysis_document(
        data,
        virtual_path,
        extension=extension,
        source_entry=source_entry,
        archive_entries_by_normalized_path=archive_entries_by_normalized_path,
        archive_entries_by_basename=archive_entries_by_basename,
    )
    return json.dumps(document, indent=2)


_BINARY_SIDECAR_CORPUS_EXTENSIONS = (
    ".meshinfo",
    ".motionblending",
    ".paa_metabin",
    ".papr",
    ".paseq",
    ".paseqc",
    ".paschedule",
    ".paschedulepath",
    ".pastage",
    ".prefab",
    ".pappt",
    ".pamhc",
    ".paccd",
    ".seqmt",
)


def _discover_binary_sidecar_corpus_paths(
    source_paths: Sequence[Path],
    *,
    discovery_limit: Optional[int] = None,
    stop_event: Optional[threading.Event] = None,
) -> List[Path]:
    candidates_by_extension: Dict[str, List[Path]] = defaultdict(list)
    seen_paths: set[str] = set()
    max_files = int(discovery_limit) if discovery_limit is not None and int(discovery_limit) > 0 else None

    def add_candidate(path: Path) -> None:
        extension = path.suffix.lower()
        if extension not in _BINARY_SIDECAR_CORPUS_EXTENSIONS:
            return
        normalized = str(path.expanduser().resolve()).lower()
        if normalized in seen_paths:
            return
        seen_paths.add(normalized)
        if max_files is None or len(candidates_by_extension[extension]) < max_files:
            candidates_by_extension[extension].append(path)

    for raw_source in source_paths:
        raise_if_cancelled(stop_event)
        source = Path(raw_source).expanduser()
        if source.is_file():
            add_candidate(source)
            continue
        if not source.is_dir():
            continue
        for dirpath, _dirnames, filenames in os.walk(source):
            raise_if_cancelled(stop_event)
            for filename in filenames:
                extension = PurePosixPath(filename).suffix.lower()
                if extension not in _BINARY_SIDECAR_CORPUS_EXTENSIONS:
                    continue
                add_candidate(Path(dirpath) / filename)

    for extension in _BINARY_SIDECAR_CORPUS_EXTENSIONS:
        candidates_by_extension[extension].sort(key=lambda item: str(item).casefold())

    discovered: List[Path] = []
    discovered_counts: Dict[str, int] = defaultdict(int)
    if max_files is None:
        for extension in _BINARY_SIDECAR_CORPUS_EXTENSIONS:
            discovered.extend(candidates_by_extension.get(extension, ()))
        return discovered

    while len(discovered) < max_files:
        added = False
        for extension in _BINARY_SIDECAR_CORPUS_EXTENSIONS:
            extension_paths = candidates_by_extension.get(extension, [])
            index = discovered_counts[extension]
            if index >= len(extension_paths):
                continue
            discovered.append(extension_paths[index])
            discovered_counts[extension] += 1
            added = True
            if len(discovered) >= max_files:
                break
        if not added:
            break
    return discovered


def _binary_sidecar_corpus_path_label(path: Path, source_paths: Sequence[Path]) -> str:
    for raw_source in source_paths:
        source = Path(raw_source).expanduser()
        try:
            if source.is_dir():
                return path.relative_to(source).as_posix()
            if source.is_file() and path.resolve() == source.resolve():
                return path.name
        except (OSError, ValueError):
            continue
    return str(path)


def _select_balanced_binary_sidecar_detail_paths(paths: Sequence[Path], max_files: Optional[int]) -> List[Path]:
    if max_files is None or max_files <= 0 or len(paths) <= max_files:
        return list(paths)
    by_extension: Dict[str, List[Path]] = defaultdict(list)
    for path in paths:
        by_extension[path.suffix.lower()].append(path)
    selected: List[Path] = []
    selected_counts: Dict[str, int] = defaultdict(int)
    while len(selected) < max_files:
        added = False
        for extension in _BINARY_SIDECAR_CORPUS_EXTENSIONS:
            extension_paths = by_extension.get(extension, [])
            index = selected_counts[extension]
            if index >= len(extension_paths):
                continue
            selected.append(extension_paths[index])
            selected_counts[extension] += 1
            added = True
            if len(selected) >= max_files:
                break
        if not added:
            break
    return selected


def _binary_sidecar_descriptor_is_unknown(row: Mapping[str, object]) -> bool:
    try:
        type_code = int(row.get("type_code") or 0)
    except (TypeError, ValueError):
        return True
    confidence = str(row.get("confidence") or "")
    return type_code not in _BINARY_SIDECAR_KNOWN_TYPE_CODES or confidence.startswith("experimental")


def _build_binary_sidecar_corpus_extension_report(
    paths: Sequence[Path],
    source_paths: Sequence[Path],
    *,
    stop_event: Optional[threading.Event] = None,
    progress_callback: Optional[Callable[[int, int, str], None]] = None,
    progress_offset: int = 0,
    progress_total: int = 0,
) -> Dict[str, object]:
    layout_counts: Counter[str] = Counter()
    layout_examples: Dict[str, Dict[str, object]] = {}
    field_file_counts: Counter[str] = Counter()
    field_decl_counts: Counter[str] = Counter()
    field_type_counts: Dict[str, Counter[str]] = defaultdict(Counter)
    field_descriptor_counts: Dict[Tuple[str, str], Counter[str]] = defaultdict(Counter)
    field_metadata: Dict[Tuple[str, str], Dict[str, str]] = {}
    unknown_descriptor_counts: Counter[str] = Counter()
    unknown_descriptor_examples: Dict[str, Dict[str, object]] = {}
    value_region_counts: Counter[int] = Counter()
    value_region_examples: Dict[int, str] = {}
    numeric_region_counts: Counter[int] = Counter()
    numeric_region_examples: Dict[int, str] = {}
    animation_type_counts: Counter[str] = Counter()
    animation_hint_counts: Counter[str] = Counter()
    animation_stream_size_counts: Counter[int] = Counter()
    animation_examples: Dict[str, str] = {}
    seqmt_grid_counts: Counter[str] = Counter()
    seqmt_flag_counts: Counter[int] = Counter()
    seqmt_payload_status_counts: Counter[str] = Counter()
    seqmt_examples: Dict[str, str] = {}
    paccd_layout_counts: Counter[str] = Counter()
    paccd_slot_counts: Counter[int] = Counter()
    paccd_stride_counts: Counter[int] = Counter()
    paccd_examples: Dict[str, str] = {}
    paseq_playback_status_counts: Counter[str] = Counter()
    paseq_lane_counts: Counter[int] = Counter()
    paseq_animation_lane_counts: Counter[int] = Counter()
    paseq_effect_lane_counts: Counter[int] = Counter()
    paseq_context_lane_counts: Counter[int] = Counter()
    paseq_examples: Dict[str, str] = {}
    scanned_count = 0
    failed_rows: List[Dict[str, object]] = []

    total = progress_total or len(paths)
    for local_index, path in enumerate(paths, start=1):
        raise_if_cancelled(stop_event)
        label = _binary_sidecar_corpus_path_label(path, source_paths)
        if progress_callback is not None:
            progress_callback(
                progress_offset + local_index - 1,
                total,
                f"Scanning binary sidecar corpus {progress_offset + local_index:,} / {total:,}: {path.name}",
            )
        try:
            data = path.read_bytes()
            document = build_binary_sidecar_analysis_document(data, label, extension=path.suffix.lower())
        except RunCancelled:
            raise
        except Exception as exc:
            failed_rows.append({"path": label, "error": str(exc)})
            continue

        scanned_count += 1
        seqmt_metadata = document.get("seqmt", {})
        if isinstance(seqmt_metadata, Mapping) and seqmt_metadata.get("recognized"):
            columns = int(seqmt_metadata.get("columns") or 0)
            rows_count = int(seqmt_metadata.get("rows") or 0)
            frame_count = int(seqmt_metadata.get("frame_count") or 0)
            grid_key = f"{columns}x{rows_count}:{frame_count}"
            seqmt_grid_counts[grid_key] += 1
            seqmt_examples.setdefault(grid_key, label)
            flag_value = int(seqmt_metadata.get("flags_or_packing_byte") or 0)
            seqmt_flag_counts[flag_value] += 1
            seqmt_examples.setdefault(f"flag_0x{flag_value:02X}", label)
            payload_status = "complete" if bool(seqmt_metadata.get("payload_complete")) else "truncated"
            if int(seqmt_metadata.get("trailing_payload_bytes") or 0) > 0:
                payload_status = "complete_with_trailing_payload"
            seqmt_payload_status_counts[payload_status] += 1
            seqmt_examples.setdefault(payload_status, label)

        paccd_metadata = document.get("paccd", {})
        if isinstance(paccd_metadata, Mapping) and paccd_metadata.get("recognized"):
            family = str(paccd_metadata.get("format_family") or "unknown")
            slot_count = int(paccd_metadata.get("slot_count") or 0)
            row_stride = int(paccd_metadata.get("row_stride") or 0)
            paccd_layout_counts[family] += 1
            paccd_slot_counts[slot_count] += 1
            paccd_stride_counts[row_stride] += 1
            paccd_examples.setdefault(family, label)
            paccd_examples.setdefault(f"slot_{slot_count}", label)
            paccd_examples.setdefault(f"stride_{row_stride}", label)

        paseq_metadata = document.get("paseq", {})
        if isinstance(paseq_metadata, Mapping) and paseq_metadata:
            timeline = paseq_metadata.get("timeline", {})
            playback = paseq_metadata.get("playback_readiness", {})
            if isinstance(timeline, Mapping):
                lane_count = int(timeline.get("lane_count") or 0)
                kind_counts = timeline.get("lane_kind_counts") if isinstance(timeline.get("lane_kind_counts"), Mapping) else {}
                animation_lanes = int(kind_counts.get("animation") or 0) if isinstance(kind_counts, Mapping) else 0
                effect_lanes = int(kind_counts.get("effect") or 0) if isinstance(kind_counts, Mapping) else 0
                context_lanes = int(kind_counts.get("context") or 0) if isinstance(kind_counts, Mapping) else 0
                paseq_lane_counts[lane_count] += 1
                paseq_animation_lane_counts[animation_lanes] += 1
                paseq_effect_lane_counts[effect_lanes] += 1
                paseq_context_lane_counts[context_lanes] += 1
                paseq_examples.setdefault(f"lanes_{lane_count}", label)
                paseq_examples.setdefault(f"animation_{animation_lanes}", label)
                paseq_examples.setdefault(f"effect_{effect_lanes}", label)
                paseq_examples.setdefault(f"context_{context_lanes}", label)
            if isinstance(playback, Mapping):
                status = str(playback.get("status") or "unknown")
                paseq_playback_status_counts[status] += 1
                paseq_examples.setdefault(status, label)

        animation_metadata = document.get("animation_metadata", {})
        if isinstance(animation_metadata, Mapping) and animation_metadata:
            declared_type = str(animation_metadata.get("declared_type") or "").strip()
            if declared_type:
                animation_type_counts[declared_type] += 1
                animation_examples.setdefault(declared_type, label)
            for hint in animation_metadata.get("filename_hints") or []:
                if not isinstance(hint, Mapping):
                    continue
                hint_key = f"{hint.get('kind') or 'Hint'}: {hint.get('meaning') or hint.get('token') or ''}".strip()
                if hint_key:
                    animation_hint_counts[hint_key] += 1
                    animation_examples.setdefault(hint_key, label)
            stream = animation_metadata.get("packed_metadata_stream", {})
            if isinstance(stream, Mapping):
                stream_size = int(stream.get("stream_size") or 0)
                if stream_size > 0:
                    bucket = (stream_size // 256) * 256
                    animation_stream_size_counts[bucket] += 1
                    animation_examples.setdefault(f"stream_0x{bucket:08X}", label)
        schema = document.get("schema_declarations", {})
        if not isinstance(schema, Mapping):
            continue
        rows = [
            row
            for row in schema.get("declared_member_rows", [])
            if isinstance(row, Mapping)
        ]
        signature = str(schema.get("layout_signature") or "")
        if signature:
            layout_counts[signature] += 1
            layout_examples.setdefault(
                signature,
                {
                    "signature": signature,
                    "example_path": label,
                    "declaration_count": len(rows),
                    "first_fields": [str(row.get("name") or "") for row in rows[:8]],
                    "candidate_value_region_start": int(
                        (schema.get("declaration_region", {}) or {}).get("candidate_value_region_start") or 0
                    )
                    if isinstance(schema.get("declaration_region", {}), Mapping)
                    else 0,
                },
            )
        declaration_region = schema.get("declaration_region", {})
        if isinstance(declaration_region, Mapping):
            region_start = int(declaration_region.get("candidate_value_region_start") or 0)
            if region_start > 0:
                region_bucket = (region_start // 256) * 256
                value_region_counts[region_bucket] += 1
                value_region_examples.setdefault(region_bucket, label)

        seen_names_in_file: set[str] = set()
        for row in rows:
            name = str(row.get("name") or "").strip()
            declared_type = str(row.get("declared_type") or "").strip()
            descriptor_hex = str(row.get("descriptor_hex") or "").strip()
            if not name or not declared_type:
                continue
            field_decl_counts[name] += 1
            field_type_counts[name][declared_type] += 1
            field_descriptor_counts[(name, declared_type)][descriptor_hex] += 1
            field_metadata.setdefault(
                (name, declared_type),
                {
                    "group": str(row.get("group") or ""),
                    "likely_kind": str(row.get("likely_kind") or ""),
                    "array_status": str(row.get("array_status") or ""),
                    "reference_status": str(row.get("reference_status") or ""),
                    "confidence": str(row.get("confidence") or ""),
                },
            )
            if name not in seen_names_in_file:
                seen_names_in_file.add(name)
                field_file_counts[name] += 1
            if _binary_sidecar_descriptor_is_unknown(row):
                unknown_descriptor_counts[descriptor_hex] += 1
                unknown_descriptor_examples.setdefault(
                    descriptor_hex,
                    {
                        "descriptor_hex": descriptor_hex,
                        "example_path": label,
                        "example_field": name,
                        "declared_type": declared_type,
                        "type_code": int(row.get("type_code") or 0),
                    },
                )

        tables = document.get("tables", {})
        float_rows = list(tables.get("float_vector_candidates") or []) if isinstance(tables, Mapping) else []
        for row in float_rows[:8]:
            if not isinstance(row, Mapping):
                continue
            offset = int(row.get("offset") or 0)
            if offset <= 0:
                continue
            offset_bucket = (offset // 256) * 256
            numeric_region_counts[offset_bucket] += 1
            numeric_region_examples.setdefault(offset_bucket, label)

    stable_fields: List[Dict[str, object]] = []
    for name, file_count in field_file_counts.items():
        type_counts = field_type_counts.get(name, Counter())
        if not type_counts:
            continue
        declared_type, type_count = type_counts.most_common(1)[0]
        descriptor_counts = field_descriptor_counts.get((name, declared_type), Counter())
        descriptor_hex, descriptor_count = descriptor_counts.most_common(1)[0] if descriptor_counts else ("", 0)
        metadata = field_metadata.get((name, declared_type), {})
        stable_fields.append(
            {
                "name": name,
                "declared_type": declared_type,
                "files_with_field": int(file_count),
                "declaration_count": int(field_decl_counts.get(name, 0)),
                "type_consistency": round(type_count / max(sum(type_counts.values()), 1), 4),
                "top_descriptor_hex": descriptor_hex,
                "top_descriptor_count": int(descriptor_count),
                "descriptor_consistency": round(descriptor_count / max(type_count, 1), 4),
                "group": metadata.get("group", ""),
                "likely_kind": metadata.get("likely_kind", ""),
                "array_status": metadata.get("array_status", ""),
                "reference_status": metadata.get("reference_status", ""),
                "confidence": metadata.get("confidence", ""),
            }
        )
    stable_fields.sort(
        key=lambda row: (
            -int(row.get("files_with_field") or 0),
            -float(row.get("type_consistency") or 0.0),
            str(row.get("name") or "").casefold(),
        )
    )

    layout_rows = []
    for signature, count in layout_counts.most_common(64):
        row = dict(layout_examples.get(signature, {}))
        row["file_count"] = int(count)
        layout_rows.append(row)

    unknown_rows = []
    for descriptor_hex, count in unknown_descriptor_counts.most_common(64):
        row = dict(unknown_descriptor_examples.get(descriptor_hex, {"descriptor_hex": descriptor_hex}))
        row["count"] = int(count)
        unknown_rows.append(row)

    value_region_rows = [
        {
            "region_start_bucket": f"0x{region_start:08X}",
            "file_count": int(count),
            "source": "declaration_end_bucket",
            "example_path": value_region_examples.get(region_start, ""),
        }
        for region_start, count in value_region_counts.most_common(32)
    ]
    value_region_rows.extend(
        {
            "region_start_bucket": f"0x{region_start:08X}",
            "file_count": int(count),
            "source": "numeric_candidate_bucket",
            "example_path": numeric_region_examples.get(region_start, ""),
        }
        for region_start, count in numeric_region_counts.most_common(32)
    )
    animation_rows = {
        "declared_types": [
            {
                "declared_type": name,
                "file_count": int(count),
                "example_path": animation_examples.get(name, ""),
            }
            for name, count in animation_type_counts.most_common(16)
        ],
        "filename_hints": [
            {
                "hint": name,
                "file_count": int(count),
                "example_path": animation_examples.get(name, ""),
            }
            for name, count in animation_hint_counts.most_common(32)
        ],
        "packed_stream_size_buckets": [
            {
                "stream_size_bucket": f"0x{bucket:08X}",
                "file_count": int(count),
                "example_path": animation_examples.get(f"stream_0x{bucket:08X}", ""),
            }
            for bucket, count in animation_stream_size_counts.most_common(32)
        ],
    }
    seqmt_rows = {
        "atlas_grids": [
            {
                "grid": name,
                "file_count": int(count),
                "example_path": seqmt_examples.get(name, ""),
            }
            for name, count in seqmt_grid_counts.most_common(32)
        ],
        "flag_or_packing_bytes": [
            {
                "value": f"0x{value:02X}",
                "file_count": int(count),
                "example_path": seqmt_examples.get(f"flag_0x{value:02X}", ""),
            }
            for value, count in seqmt_flag_counts.most_common(16)
        ],
        "payload_statuses": [
            {
                "status": name,
                "file_count": int(count),
                "example_path": seqmt_examples.get(name, ""),
            }
            for name, count in seqmt_payload_status_counts.most_common(16)
        ],
    }
    paccd_rows = {
        "layout_families": [
            {
                "format_family": name,
                "file_count": int(count),
                "example_path": paccd_examples.get(name, ""),
            }
            for name, count in paccd_layout_counts.most_common(16)
        ],
        "slot_counts": [
            {
                "slot_count": int(value),
                "file_count": int(count),
                "example_path": paccd_examples.get(f"slot_{value}", ""),
            }
            for value, count in paccd_slot_counts.most_common(16)
        ],
        "row_strides": [
            {
                "row_stride": int(value),
                "file_count": int(count),
                "example_path": paccd_examples.get(f"stride_{value}", ""),
            }
            for value, count in paccd_stride_counts.most_common(16)
        ],
    }
    paseq_rows = {
        "playback_statuses": [
            {
                "status": name,
                "file_count": int(count),
                "example_path": paseq_examples.get(name, ""),
            }
            for name, count in paseq_playback_status_counts.most_common(16)
        ],
        "timeline_lane_buckets": [
            {
                "lane_count": int(value),
                "file_count": int(count),
                "example_path": paseq_examples.get(f"lanes_{value}", ""),
            }
            for value, count in paseq_lane_counts.most_common(16)
        ],
        "animation_lane_buckets": [
            {
                "lane_count": int(value),
                "file_count": int(count),
                "example_path": paseq_examples.get(f"animation_{value}", ""),
            }
            for value, count in paseq_animation_lane_counts.most_common(16)
        ],
        "effect_lane_buckets": [
            {
                "lane_count": int(value),
                "file_count": int(count),
                "example_path": paseq_examples.get(f"effect_{value}", ""),
            }
            for value, count in paseq_effect_lane_counts.most_common(16)
        ],
        "context_lane_buckets": [
            {
                "lane_count": int(value),
                "file_count": int(count),
                "example_path": paseq_examples.get(f"context_{value}", ""),
            }
            for value, count in paseq_context_lane_counts.most_common(16)
        ],
    }

    return {
        "files_scanned": scanned_count,
        "files_failed": len(failed_rows),
        "failed_rows": failed_rows[:32],
        "layout_signatures": layout_rows,
        "stable_fields": stable_fields[:256],
        "unknown_descriptor_bytes": unknown_rows,
        "candidate_value_regions": value_region_rows,
        "animation_metadata": animation_rows,
        "seqmt": seqmt_rows,
        "paccd": paccd_rows,
        "paseq": paseq_rows,
    }


def build_binary_sidecar_corpus_report(
    source_paths: Sequence[Path],
    *,
    discovery_limit: Optional[int] = None,
    detail_scan_limit: Optional[int] = 1000,
    stop_event: Optional[threading.Event] = None,
    progress_callback: Optional[Callable[[int, int, str], None]] = None,
) -> Dict[str, object]:
    normalized_sources = tuple(Path(path).expanduser() for path in source_paths)
    discovered_paths = _discover_binary_sidecar_corpus_paths(
        normalized_sources,
        discovery_limit=discovery_limit,
        stop_event=stop_event,
    )
    max_detail = int(detail_scan_limit) if detail_scan_limit is not None and int(detail_scan_limit) > 0 else None
    detail_paths = _select_balanced_binary_sidecar_detail_paths(discovered_paths, max_detail)
    by_extension_paths: Dict[str, List[Path]] = defaultdict(list)
    for path in detail_paths:
        by_extension_paths[path.suffix.lower()].append(path)

    if progress_callback is not None:
        progress_callback(0, max(len(detail_paths), 1), f"Discovered {len(discovered_paths):,} binary sidecar file(s).")

    by_extension: Dict[str, object] = {}
    progress_offset = 0
    progress_total = max(len(detail_paths), 1)
    for extension in _BINARY_SIDECAR_CORPUS_EXTENSIONS:
        extension_paths = by_extension_paths.get(extension, [])
        by_extension[extension] = _build_binary_sidecar_corpus_extension_report(
            extension_paths,
            normalized_sources,
            stop_event=stop_event,
            progress_callback=progress_callback,
            progress_offset=progress_offset,
            progress_total=progress_total,
        )
        progress_offset += len(extension_paths)

    if progress_callback is not None:
        progress_callback(progress_total, progress_total, "Binary sidecar corpus report complete.")

    return {
        "document": "Crimson Desert Mod Workbench binary sidecar corpus report.",
        "format": "cdmw_binary_sidecar_corpus_v1",
        "format_status": "experimental_read_only_schema_recovery",
        "source_paths": [str(path) for path in normalized_sources],
        "summary": {
            "files_discovered": len(discovered_paths),
            "files_scanned": len(detail_paths),
            "discovery_limit": int(discovery_limit) if discovery_limit is not None and int(discovery_limit) > 0 else None,
            "detail_scan_limit": int(detail_scan_limit) if detail_scan_limit is not None and int(detail_scan_limit) > 0 else None,
            "meshinfo_files_scanned": len(by_extension_paths.get(".meshinfo", [])),
            "motionblending_files_scanned": len(by_extension_paths.get(".motionblending", [])),
            "paa_metabin_files_scanned": len(by_extension_paths.get(".paa_metabin", [])),
            "papr_files_scanned": len(by_extension_paths.get(".papr", [])),
            "paseq_files_scanned": len(by_extension_paths.get(".paseq", [])),
            "paseqc_files_scanned": len(by_extension_paths.get(".paseqc", [])),
            "paschedule_files_scanned": len(by_extension_paths.get(".paschedule", [])),
            "paschedulepath_files_scanned": len(by_extension_paths.get(".paschedulepath", [])),
            "pastage_files_scanned": len(by_extension_paths.get(".pastage", [])),
            "prefab_files_scanned": len(by_extension_paths.get(".prefab", [])),
            "pappt_files_scanned": len(by_extension_paths.get(".pappt", [])),
            "pamhc_files_scanned": len(by_extension_paths.get(".pamhc", [])),
            "paccd_files_scanned": len(by_extension_paths.get(".paccd", [])),
            "seqmt_files_scanned": len(by_extension_paths.get(".seqmt", [])),
        },
        "by_extension": by_extension,
        "editing": {
            "supported": False,
            "policy": "read_only_until_exact_value_offsets_and_no_edit_rebuilds_are_proven",
            "reason": "Corpus ranking proves declarations and layout frequency, not safe write offsets.",
        },
    }


def build_binary_sidecar_corpus_json(
    source_paths: Sequence[Path],
    *,
    discovery_limit: Optional[int] = None,
    detail_scan_limit: Optional[int] = 1000,
    stop_event: Optional[threading.Event] = None,
    progress_callback: Optional[Callable[[int, int, str], None]] = None,
) -> str:
    return json.dumps(
        build_binary_sidecar_corpus_report(
            source_paths,
            discovery_limit=discovery_limit,
            detail_scan_limit=detail_scan_limit,
            stop_event=stop_event,
            progress_callback=progress_callback,
        ),
        indent=2,
    )


def _group_prefab_field_name(name: str) -> str:
    normalized = str(name or "").strip().lstrip("_").lower()
    if not normalized:
        return "Misc"
    if any(token in normalized for token in ("cloth", "pbd", "shrink", "masterpose", "syncmeshcomponent", "anchormeshnode", "meshnode", "dynamicmotion", "sdf")):
        return "Mesh / Cloth"
    if any(token in normalized for token in ("socket", "skeleton", "bone")):
        return "Skeleton / Sockets"
    if any(token in normalized for token in ("path", "file", "filename", "mesh", "model", "lod", "material", "texture", "resource", "asset")):
        return "Resources"
    if any(token in normalized for token in ("component", "childsceneobjects", "masterpose", "customgamedata")):
        return "Scene / Object"
    if any(token in normalized for token in ("prefab", "scene", "object", "node", "actor", "entity", "spawn", "enable", "uuid", "uid", "tag", "generateuuid")):
        return "Scene / Object"
    if any(token in normalized for token in ("position", "rotation", "scale", "transform", "matrix", "bound", "bbox")):
        return "Transform / Bounds"
    if any(token in normalized for token in ("collision", "physics", "pbd", "shape", "constraint", "rigid", "mass")):
        return "Physics / Collision"
    if any(token in normalized for token in ("script", "event", "trigger", "condition", "gimmick", "logic")):
        return "Logic / Events"
    if any(token in normalized for token in ("render", "opacity", "priority", "sound", "audio", "effect", "emitter", "particle", "light")):
        return "Presentation"
    return "Misc"


def _binary_sidecar_group_func_for_extension(extension: str) -> Callable[[str], str]:
    normalized_extension = str(extension or "").strip().lower()
    if normalized_extension == ".meshinfo":
        return _group_meshinfo_field_name
    if normalized_extension in {".prefab", ".pappt"}:
        return _group_prefab_field_name
    if normalized_extension == ".pamhc":
        return _group_model_property_header_field_name
    if normalized_extension == ".paccd":
        return _group_character_customization_field_name
    if normalized_extension == ".seqmt":
        return _group_seqmt_field_name
    if normalized_extension in {".levelinfo", ".palevel", ".roadsector", ".road", ".nav"}:
        return _group_world_field_name
    if normalized_extension in {".pabc", ".pabv", ".pabgb", ".pabgh"}:
        return _group_rig_variant_field_name
    return _group_animation_field_name


def _group_model_property_header_field_name(name: str) -> str:
    normalized = str(name or "").strip().lstrip("_").lower()
    if not normalized:
        return "Misc"
    if any(token in normalized for token in ("material", "shader", "texture", "submesh", "parameter", "skin", "cloth")):
        return "Material / Texture"
    if any(token in normalized for token in ("mesh", "model", "lod", "resource", "path", "file", "filename", "asset")):
        return "Model Resources"
    if any(token in normalized for token in ("socket", "skeleton", "bone", "rig")):
        return "Skeleton / Rig"
    if any(token in normalized for token in ("physics", "collision", "hkx", "shape", "cloth", "pbd")):
        return "Physics / Collision"
    if any(token in normalized for token in ("bounds", "bbox", "position", "rotation", "scale", "transform")):
        return "Transform / Bounds"
    if any(token in normalized for token in ("variant", "part", "body", "gender", "race")):
        return "Variant / Part"
    return "Misc"


def _group_character_customization_field_name(name: str) -> str:
    normalized = str(name or "").strip().lstrip("_").lower()
    if not normalized:
        return "Misc"
    if any(token in normalized for token in ("custom", "slot", "slider", "morph", "blend", "palette", "preset")):
        return "Customization Slots"
    if any(token in normalized for token in ("color", "tint", "rgb", "skin", "hair", "dye")):
        return "Palette / Color"
    if any(token in normalized for token in ("face", "head", "body", "eye", "nose", "mouth", "brow")):
        return "Body / Face"
    if any(token in normalized for token in ("material", "texture", "shader", "mask")):
        return "Material / Texture"
    if any(token in normalized for token in ("part", "variant", "gender", "race", "class")):
        return "Variant / Part"
    return "Misc"


def _group_seqmt_field_name(name: str) -> str:
    normalized = str(name or "").strip().lstrip("_").lower()
    if not normalized:
        return "Misc"
    if any(token in normalized for token in ("material", "shader", "texture", "parameter", "color", "tint", "mask", "blend", "uv")):
        return "Material / Texture"
    if any(token in normalized for token in ("sequence", "sequencer", "timeline", "track", "key", "frame", "curve", "duration", "time")):
        return "Sequence / Timeline"
    if any(token in normalized for token in ("path", "file", "filename", "resource", "asset", "model", "mesh", "prefab")):
        return "Resources"
    if any(token in normalized for token in ("effect", "emitter", "particle", "light", "visibility", "opacity", "render", "presentation")):
        return "Effect / Presentation"
    if any(token in normalized for token in ("position", "rotation", "scale", "transform", "matrix", "bound", "bbox")):
        return "Transform / Bounds"
    return "Misc"


def _group_world_field_name(name: str) -> str:
    normalized = str(name or "").strip().lstrip("_").lower()
    if not normalized:
        return "Misc"
    if any(token in normalized for token in ("level", "world", "zone", "sector", "region", "cell", "tile", "block")):
        return "World / Region"
    if any(token in normalized for token in ("road", "spline", "lane", "path", "waypoint", "route")):
        return "Road / Path"
    if any(token in normalized for token in ("nav", "navigation", "navmesh", "obstacle", "agent")):
        return "Navigation"
    if any(token in normalized for token in ("prefab", "object", "entity", "spawn", "gimmick", "prop")):
        return "Scene Objects"
    if any(token in normalized for token in ("terrain", "height", "water", "foliage", "grass", "vegetation")):
        return "Terrain"
    if any(token in normalized for token in ("bound", "bbox", "extent", "position", "rotation", "scale")):
        return "Bounds / Transform"
    return "Misc"


def _group_rig_variant_field_name(name: str) -> str:
    normalized = str(name or "").strip().lstrip("_").lower()
    if not normalized:
        return "Misc"
    if any(token in normalized for token in ("skeleton", "bone", "joint", "rig", "socket")):
        return "Skeleton / Rig"
    if any(token in normalized for token in ("physics", "ragdoll", "constraint", "collision", "shape")):
        return "Physics"
    if any(token in normalized for token in ("animation", "motion", "blend", "pose", "clip")):
        return "Animation"
    if any(token in normalized for token in ("variant", "gender", "race", "body", "part", "custom")):
        return "Variant / Body"
    if any(token in normalized for token in ("gameplay", "state", "behavior", "ai", "event")):
        return "Gameplay"
    return "Misc"


def _build_grouped_structured_section_lines(
    field_names: Sequence[str],
    *,
    group_func: Callable[[str], str],
    section_order: Sequence[str],
    per_section_limit: int = 24,
) -> List[str]:
    grouped: Dict[str, List[str]] = defaultdict(list)
    for name in sorted({str(item or "").strip() for item in field_names if str(item or "").strip()}, key=str.casefold):
        grouped[group_func(name)].append(name)

    lines: List[str] = []
    for section_name in section_order:
        section_fields = grouped.get(section_name, [])
        if not section_fields:
            continue
        lines.extend(["", f"{section_name} ({len(section_fields)})"])
        for field_name in section_fields[:per_section_limit]:
            lines.append(f"  [{_structured_field_type_hint(field_name)}] {field_name}")
        if len(section_fields) > per_section_limit:
            lines.append(f"  ... {len(section_fields) - per_section_limit} more")

    remaining_sections = [
        section_name
        for section_name, section_fields in grouped.items()
        if section_name not in section_order and section_fields
    ]
    for section_name in sorted(remaining_sections, key=str.casefold):
        section_fields = grouped.get(section_name, [])
        if not section_fields:
            continue
        lines.extend(["", f"{section_name} ({len(section_fields)})"])
        for field_name in section_fields[:per_section_limit]:
            lines.append(f"  [{_structured_field_type_hint(field_name)}] {field_name}")
        if len(section_fields) > per_section_limit:
            lines.append(f"  ... {len(section_fields) - per_section_limit} more")

    return lines
