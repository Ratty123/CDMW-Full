from __future__ import annotations

from cdmw.core.archive_binary_preview_compat import bind_binary_preview_globals


@bind_binary_preview_globals(
    'ARCHIVE_BINARY_HEX_PREVIEW_LIMIT',
)
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


@bind_binary_preview_globals(
    '_PRINTABLE_BINARY_STRING_RE',
)
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


@bind_binary_preview_globals(
    'extract_binary_strings',
    'format_byte_size',
)
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


@bind_binary_preview_globals(
    '_STRUCTURED_BINARY_IDENTIFIER_RE',
)
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


@bind_binary_preview_globals(
    'PurePosixPath',
    '_STRUCTURED_BINARY_ASSET_REFERENCE_EXTENSIONS',
    '_STRUCTURED_BINARY_ASSET_SEGMENT_RE',
)
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


@bind_binary_preview_globals(
    '_STRUCTURED_BINARY_ASSET_REFERENCE_EXTENSIONS',
    '_looks_like_structured_asset_reference',
    're',
)
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


@bind_binary_preview_globals(
    '_STRUCTURED_BINARY_ASSET_TOKEN_RE',
    '_clean_structured_binary_asset_token',
    '_looks_like_structured_asset_reference',
    '_normalize_model_texture_reference',
    'extract_binary_strings',
)
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


@bind_binary_preview_globals(
    '_STRUCTURED_BINARY_ASSET_TOKEN_RE',
    '_looks_like_structured_asset_reference',
    '_normalize_model_texture_reference',
    'parse_texture_sidecar_bindings',
)
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


@bind_binary_preview_globals(
)
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


@bind_binary_preview_globals(
)
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


@bind_binary_preview_globals(
)
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
