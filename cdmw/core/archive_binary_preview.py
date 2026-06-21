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
    elif normalized_extension in {".paseq", ".paschedule", ".paschedulepath", ".pastage"}:
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
    if normalized_extension in {".paseq", ".paschedule", ".paschedulepath", ".pastage"}:
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
    max_rows: int = 96,
) -> List[Dict[str, object]]:
    rows: List[Dict[str, object]] = []
    seen: set[Tuple[str, str]] = set()

    def add_row(
        *,
        name: str,
        source: str,
        offset: int,
        declared_type: str = "",
        descriptor_hex: str = "",
        confidence: str = "",
    ) -> None:
        clean_name = str(name or "").strip()
        if not clean_name:
            return
        normalized = clean_name.lstrip("_").lower()
        if not any(token in normalized for token in (*_PASEQ_TIMELINE_FIELD_TOKENS, *_PASEQ_EFFECT_FIELD_TOKENS, *_PASEQ_SCENE_FIELD_TOKENS)):
            return
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
    return {
        "status": "dependency_timeline_recovered_read_only" if lanes or timeline_fields else "no_timeline_evidence_recovered",
        "ready_for_3d_playback": False,
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
        },
        "playback_readiness": playback_readiness,
        "editing_supported": False,
        "notes": [
            "PASEQ schedule evidence is read-only; offsets are decoded-payload byte offsets.",
            "Timeline lanes are recovered from asset reference strings and same payload evidence, not from proven executable game logic.",
            "3D playback remains disabled until sequence timing, clip binding, and skeleton/model application are validated.",
        ],
    }


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
                ".meshinfo, .motionblending, .paa, .paa_metabin, .paseq/.paschedule/.pastage, .prefab, .pappt, .pamhc, .paccd, and .seqmt layout/count semantics are not proven yet. "
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
    ".paseq",
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
            "paseq_files_scanned": len(by_extension_paths.get(".paseq", [])),
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
