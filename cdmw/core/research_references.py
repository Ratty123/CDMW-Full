"""Research archive reference, sidecar, and UI-constraint queries."""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from collections import defaultdict
from pathlib import PurePosixPath
from typing import Callable, Dict, List, Optional, Sequence, Tuple

from cdmw.core.archive_extraction import read_archive_entry_data
from cdmw.core.archive_media_preview import ensure_archive_preview_source
from cdmw.core.common import raise_if_cancelled
from cdmw.core.research_archive_analysis import TEXTURE_IMAGE_EXTENSIONS, TEXTURE_SIDECAR_EXTENSIONS, derive_texture_group_key
from cdmw.core.texture_pipeline.inspection import parse_dds
from cdmw.domain.research.classification import _normalized_parts
from cdmw.domain.research.contracts import (
    RESEARCH_REFERENCE_SOURCE_EXTENSIONS,
    MaterialTextureReferenceRow,
    SidecarDiscoveryRow,
)
from cdmw.models import ArchiveEntry

REFERENCE_SOURCE_EXTENSIONS = set(RESEARCH_REFERENCE_SOURCE_EXTENSIONS)


TEXTURE_REFERENCE_PATTERN = re.compile(
    r"(?i)([A-Za-z0-9_./\\\\-]+\.(?:dds|png|tga|jpg|jpeg|bmp|gif|tiff?|webp|hdr))"
)


_XML_ATTRIBUTE_PATTERN = re.compile(r"([A-Za-z_:][A-Za-z0-9_.:-]*)\s*=\s*\"([^\"]*)\"")


_GET_RECT_PATTERN = re.compile(r"^\s*(-?\d+)\s*,\s*(-?\d+)\s*,\s*(-?\d+)\s*,\s*(-?\d+)\s*$")


def _decode_reference_text(data: bytes) -> str:
    for encoding in ("utf-8-sig", "utf-8", "utf-16-le", "cp1252"):
        try:
            return data.decode(encoding, errors="replace").replace("\r\n", "\n").replace("\r", "\n")
        except Exception:
            continue
    return data.decode("utf-8", errors="replace").replace("\r\n", "\n").replace("\r", "\n")


def _normalize_reference_token(token: str) -> str:
    normalized = token.strip().strip("'\"").replace("\\", "/").lower()
    while normalized.startswith("./"):
        normalized = normalized[2:]
    return normalized.strip("/")


def _extract_texture_reference_tokens(text: str) -> List[str]:
    tokens: List[str] = []
    seen: set[str] = set()
    for match in TEXTURE_REFERENCE_PATTERN.finditer(text):
        normalized = _normalize_reference_token(match.group(1))
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        tokens.append(normalized)
    return tokens


def _tail_path_key(path_value: str, depth: int) -> str:
    parts = _normalized_parts(path_value)
    if len(parts) < depth:
        return ""
    return "/".join(parts[-depth:]).lower()


def _build_texture_reference_indexes(
    entries: Sequence[ArchiveEntry],
) -> Tuple[
    Dict[str, ArchiveEntry],
    Dict[str, List[ArchiveEntry]],
    Dict[str, List[ArchiveEntry]],
    Dict[str, List[ArchiveEntry]],
]:
    by_path: Dict[str, ArchiveEntry] = {}
    by_basename: Dict[str, List[ArchiveEntry]] = defaultdict(list)
    by_tail2: Dict[str, List[ArchiveEntry]] = defaultdict(list)
    by_tail3: Dict[str, List[ArchiveEntry]] = defaultdict(list)
    for entry in entries:
        lowered = entry.path.replace("\\", "/").lower()
        if entry.extension not in TEXTURE_IMAGE_EXTENSIONS and "/texture/" not in lowered:
            continue
        by_path[lowered] = entry
        by_basename[PurePosixPath(lowered).name].append(entry)
        tail2 = _tail_path_key(lowered, 2)
        tail3 = _tail_path_key(lowered, 3)
        if tail2:
            by_tail2[tail2].append(entry)
        if tail3:
            by_tail3[tail3].append(entry)
    return by_path, by_basename, by_tail2, by_tail3


def _resolve_texture_reference_token(
    token: str,
    *,
    by_path: Dict[str, ArchiveEntry],
    by_basename: Dict[str, List[ArchiveEntry]],
    by_tail2: Dict[str, List[ArchiveEntry]],
    by_tail3: Dict[str, List[ArchiveEntry]],
) -> Tuple[List[ArchiveEntry], str]:
    normalized = _normalize_reference_token(token)
    if not normalized:
        return [], "unresolved"
    exact = by_path.get(normalized)
    if exact is not None:
        return [exact], "exact path"
    tail3 = _tail_path_key(normalized, 3)
    if tail3 and len(by_tail3.get(tail3, ())) == 1:
        return list(by_tail3[tail3]), "tail path"
    tail2 = _tail_path_key(normalized, 2)
    if tail2 and len(by_tail2.get(tail2, ())) == 1:
        return list(by_tail2[tail2]), "tail path"
    basename = PurePosixPath(normalized).name
    basename_matches = by_basename.get(basename, [])
    if len(basename_matches) == 1:
        return list(basename_matches), "unique basename"
    return [], "unresolved"


def _build_reference_snippet(text: str, token: str, *, radius: int = 80) -> str:
    lowered_text = text.lower()
    lowered_token = token.lower()
    index = lowered_text.find(lowered_token)
    if index < 0:
        compact = re.sub(r"\s+", " ", text.strip())
        return compact[: (radius * 2)] if compact else ""
    start = max(0, index - radius)
    end = min(len(text), index + len(token) + radius)
    snippet = re.sub(r"\s+", " ", text[start:end]).strip()
    prefix = "..." if start > 0 else ""
    suffix = "..." if end < len(text) else ""
    return f"{prefix}{snippet}{suffix}"


def _extract_reference_tag_text(text: str, token: str) -> str:
    escaped_token = re.escape(token)
    tag_match = re.search(rf"<[^>]*{escaped_token}[^>]*>", text, re.IGNORECASE)
    if tag_match:
        return tag_match.group(0)
    lowered_text = text.lower()
    lowered_token = token.lower()
    index = lowered_text.find(lowered_token)
    if index < 0:
        return ""
    line_start = text.rfind("\n", 0, index)
    line_end = text.find("\n", index)
    if line_start < 0:
        line_start = 0
    else:
        line_start += 1
    if line_end < 0:
        line_end = len(text)
    return text[line_start:line_end].strip()


def _parse_get_rect(value: str) -> Tuple[int, int, int, int]:
    match = _GET_RECT_PATTERN.match(value.strip())
    if match is None:
        return -1, -1, 0, 0
    return tuple(int(match.group(index)) for index in range(1, 5))


def _build_ui_constraint_warning(
    *,
    rect_width: int,
    rect_height: int,
    texture_width: int = 0,
    texture_height: int = 0,
) -> Tuple[str, str]:
    if rect_width <= 0 or rect_height <= 0:
        return "", ""
    if texture_width > 0 and texture_height > 0:
        if rect_width < texture_width or rect_height < texture_height:
            constraint_kind = "Explicit UI rect smaller than texture"
        elif rect_width == texture_width and rect_height == texture_height:
            constraint_kind = "Explicit UI rect matches texture"
        else:
            constraint_kind = "Explicit UI rect larger than texture"
    else:
        constraint_kind = "Explicit UI rect found"
    warning_text = (
        f"Referenced by UI XML with GetRect {rect_width}x{rect_height}. "
        "Upscaling the DDS alone may not change rendered size if the UI layout still uses the same rect."
    )
    return constraint_kind, warning_text


def _extract_ui_reference_metadata(
    source_path: str,
    text: str,
    token: str,
    *,
    texture_width: int = 0,
    texture_height: int = 0,
) -> Dict[str, object]:
    source_kind = PurePosixPath(source_path.replace("\\", "/")).suffix.lower().lstrip(".")
    result: Dict[str, object] = {
        "source_kind": source_kind,
        "texture_name": "",
        "filename_token": token,
        "get_rect_raw": "",
        "rect_x": -1,
        "rect_y": -1,
        "rect_width": 0,
        "rect_height": 0,
        "constraint_kind": "",
        "warning_text": "",
        "evidence_level": "",
    }
    if source_kind != "xml":
        return result
    tag_text = _extract_reference_tag_text(text, token)
    if not tag_text:
        return result
    attributes: Dict[str, str] = {}
    try:
        element = ET.fromstring(tag_text)
        attributes = {str(key): str(value) for key, value in element.attrib.items()}
    except Exception:
        attributes = {match.group(1): match.group(2) for match in _XML_ATTRIBUTE_PATTERN.finditer(tag_text)}
    normalized_attrs = {key.lower(): value for key, value in attributes.items()}
    texture_name = normalized_attrs.get("name", "")
    filename_value = normalized_attrs.get("filename", "")
    get_rect_raw = normalized_attrs.get("getrect", "")
    rect_x, rect_y, rect_width, rect_height = _parse_get_rect(get_rect_raw)
    constraint_kind, warning_text = _build_ui_constraint_warning(
        rect_width=rect_width,
        rect_height=rect_height,
        texture_width=texture_width,
        texture_height=texture_height,
    )
    evidence_level = "explicit_xml_rect" if get_rect_raw else ("explicit_xml_filename" if filename_value else "")
    result.update(
        {
            "texture_name": texture_name,
            "filename_token": filename_value or token,
            "get_rect_raw": get_rect_raw,
            "rect_x": rect_x,
            "rect_y": rect_y,
            "rect_width": rect_width,
            "rect_height": rect_height,
            "constraint_kind": constraint_kind,
            "warning_text": warning_text,
            "evidence_level": evidence_level,
        }
    )
    return result


def _archive_entry_texture_size(entry: ArchiveEntry) -> Tuple[int, int]:
    if entry.extension.lower() != ".dds":
        return 0, 0
    try:
        source_path, _note = ensure_archive_preview_source(entry)
        info = parse_dds(source_path)
    except Exception:
        return 0, 0
    return int(info.width), int(info.height)


def _material_reference_row(
    *,
    source_entry: ArchiveEntry,
    related_path: str,
    related_package_label: str,
    relation_kind: str,
    match_count: int,
    snippet: str,
    ui_meta: Dict[str, object],
    texture_size: Tuple[int, int],
) -> MaterialTextureReferenceRow:
    texture_width, texture_height = texture_size
    return MaterialTextureReferenceRow(
        source_path=source_entry.path,
        source_package_label=source_entry.package_label,
        related_path=related_path,
        related_package_label=related_package_label,
        relation_kind=relation_kind,
        match_count=match_count,
        snippet=snippet,
        source_kind=str(ui_meta.get("source_kind", "") or ""),
        texture_name=str(ui_meta.get("texture_name", "") or ""),
        filename_token=str(ui_meta.get("filename_token", "") or ""),
        get_rect_raw=str(ui_meta.get("get_rect_raw", "") or ""),
        rect_x=int(ui_meta.get("rect_x", -1)),
        rect_y=int(ui_meta.get("rect_y", -1)),
        rect_width=int(ui_meta.get("rect_width", 0) or 0),
        rect_height=int(ui_meta.get("rect_height", 0) or 0),
        texture_width=texture_width,
        texture_height=texture_height,
        constraint_kind=str(ui_meta.get("constraint_kind", "") or ""),
        warning_text=str(ui_meta.get("warning_text", "") or ""),
        evidence_level=str(ui_meta.get("evidence_level", "") or ""),
    )


def _resolve_outbound_texture_references(
    target_entry: ArchiveEntry,
    *,
    by_path: Dict[str, ArchiveEntry],
    by_basename: Dict[str, List[ArchiveEntry]],
    by_tail2: Dict[str, List[ArchiveEntry]],
    by_tail3: Dict[str, List[ArchiveEntry]],
    limit: int,
    on_progress: Optional[Callable[[int, int, str], None]],
    stop_event: Optional[object],
) -> Tuple[List[MaterialTextureReferenceRow], Dict[str, object]]:
    if on_progress:
        on_progress(0, 1, f"Resolving outbound texture references from {target_entry.path}")
    try:
        data, _decompressed, _note = read_archive_entry_data(target_entry, stop_event=stop_event)
        text = _decode_reference_text(data)
    except Exception:
        return [], {"mode": "outbound", "searched_count": 0, "candidate_count": 1, "unreadable_count": 1}

    rows: List[MaterialTextureReferenceRow] = []
    seen_related: set[str] = set()
    for token in _extract_texture_reference_tokens(text):
        raise_if_cancelled(stop_event)
        resolved_entries, resolution_kind = _resolve_texture_reference_token(
            token,
            by_path=by_path,
            by_basename=by_basename,
            by_tail2=by_tail2,
            by_tail3=by_tail3,
        )
        for related_entry in resolved_entries:
            lowered_related = related_entry.path.replace("\\", "/").lower()
            if lowered_related in seen_related:
                continue
            seen_related.add(lowered_related)
            texture_size = _archive_entry_texture_size(related_entry)
            ui_meta = _extract_ui_reference_metadata(
                target_entry.path,
                text,
                token,
                texture_width=texture_size[0],
                texture_height=texture_size[1],
            )
            rows.append(
                _material_reference_row(
                    source_entry=target_entry,
                    related_path=related_entry.path,
                    related_package_label=related_entry.package_label,
                    relation_kind=f"references texture ({resolution_kind})",
                    match_count=max(1, text.lower().count(token.lower())),
                    snippet=_build_reference_snippet(text, token),
                    ui_meta=ui_meta,
                    texture_size=texture_size,
                )
            )
            if len(rows) >= limit:
                break
        if len(rows) >= limit:
            break
    rows.sort(key=lambda row: (row.related_path.lower(), row.relation_kind))
    return rows, {"mode": "outbound", "searched_count": 1, "candidate_count": 1, "unreadable_count": 0}


def _match_inbound_texture_reference(
    text: str,
    *,
    lowered_target: str,
    target_basename: str,
    target_exists: bool,
    by_path: Dict[str, ArchiveEntry],
    by_basename: Dict[str, List[ArchiveEntry]],
    by_tail2: Dict[str, List[ArchiveEntry]],
    by_tail3: Dict[str, List[ArchiveEntry]],
) -> Tuple[int, str, str]:
    match_count = 0
    match_kind = ""
    snippet = ""
    for token in _extract_texture_reference_tokens(text):
        resolved_entries, resolution_kind = _resolve_texture_reference_token(
            token,
            by_path=by_path,
            by_basename=by_basename,
            by_tail2=by_tail2,
            by_tail3=by_tail3,
        )
        resolved_paths = {entry.path.replace("\\", "/").lower() for entry in resolved_entries}
        if lowered_target in resolved_paths:
            match_count += 1
            match_kind = resolution_kind
        elif not target_exists and PurePosixPath(token).name.lower() == target_basename:
            match_count += 1
            match_kind = "basename match"
        else:
            continue
        if not snippet:
            snippet = _build_reference_snippet(text, token)
    return match_count, match_kind, snippet


def _resolve_inbound_texture_references(
    text_entries: Sequence[ArchiveEntry],
    normalized_target: str,
    target_entry: Optional[ArchiveEntry],
    *,
    by_path: Dict[str, ArchiveEntry],
    by_basename: Dict[str, List[ArchiveEntry]],
    by_tail2: Dict[str, List[ArchiveEntry]],
    by_tail3: Dict[str, List[ArchiveEntry]],
    limit: int,
    on_progress: Optional[Callable[[int, int, str], None]],
    stop_event: Optional[object],
) -> Tuple[List[MaterialTextureReferenceRow], Dict[str, object]]:
    rows: List[MaterialTextureReferenceRow] = []
    unreadable_count = 0
    lowered_target = normalized_target.lower()
    target_basename = PurePosixPath(lowered_target).name
    target_size = _archive_entry_texture_size(target_entry) if target_entry is not None else (0, 0)
    total = len(text_entries)
    for index, entry in enumerate(text_entries, start=1):
        raise_if_cancelled(stop_event)
        if on_progress:
            on_progress(index - 1, total, f"Searching material/sidecar references in {entry.path}")
        try:
            data, _decompressed, _note = read_archive_entry_data(entry, stop_event=stop_event)
            text = _decode_reference_text(data)
        except Exception:
            unreadable_count += 1
            continue
        lowered_text = text.lower()
        if lowered_target not in lowered_text and target_basename not in lowered_text:
            continue
        match_count, match_kind, snippet = _match_inbound_texture_reference(
            text,
            lowered_target=lowered_target,
            target_basename=target_basename,
            target_exists=target_entry is not None,
            by_path=by_path,
            by_basename=by_basename,
            by_tail2=by_tail2,
            by_tail3=by_tail3,
        )
        if match_count <= 0:
            continue
        metadata_token = target_entry.path if target_entry is not None else target_basename
        ui_meta = _extract_ui_reference_metadata(
            entry.path,
            text,
            metadata_token,
            texture_width=target_size[0],
            texture_height=target_size[1],
        )
        rows.append(
            _material_reference_row(
                source_entry=entry,
                related_path=normalized_target,
                related_package_label=target_entry.package_label if target_entry is not None else "",
                relation_kind=f"references selected texture ({match_kind or 'text match'})",
                match_count=match_count,
                snippet=snippet,
                ui_meta=ui_meta,
                texture_size=target_size,
            )
        )
        if len(rows) >= limit:
            break
    if on_progress:
        on_progress(total, total, f"Reference resolution complete. Found {len(rows):,} match(es).")
    rows.sort(key=lambda row: (-row.match_count, row.source_path.lower()))
    return rows, {
        "mode": "inbound",
        "searched_count": total - unreadable_count,
        "candidate_count": total,
        "unreadable_count": unreadable_count,
    }


def resolve_material_texture_references(
    entries: Sequence[ArchiveEntry],
    target_path: str,
    *,
    limit: int = 240,
    on_progress: Optional[Callable[[int, int, str], None]] = None,
    stop_event: Optional[object] = None,
) -> Tuple[List[MaterialTextureReferenceRow], Dict[str, object]]:
    normalized_target = target_path.strip().replace("\\", "/").strip("/")
    if not normalized_target:
        return [], {"mode": "none", "searched_count": 0, "candidate_count": 0, "unreadable_count": 0}

    all_entries_by_path = {entry.path.replace("\\", "/").lower(): entry for entry in entries}
    target_entry = all_entries_by_path.get(normalized_target.lower())
    by_path, by_basename, by_tail2, by_tail3 = _build_texture_reference_indexes(entries)
    indexes = {
        "by_path": by_path,
        "by_basename": by_basename,
        "by_tail2": by_tail2,
        "by_tail3": by_tail3,
    }
    if target_entry is not None and target_entry.extension in REFERENCE_SOURCE_EXTENSIONS:
        return _resolve_outbound_texture_references(
            target_entry,
            limit=limit,
            on_progress=on_progress,
            stop_event=stop_event,
            **indexes,
        )
    text_entries = [entry for entry in entries if entry.extension in REFERENCE_SOURCE_EXTENSIONS]
    return _resolve_inbound_texture_references(
        text_entries,
        normalized_target,
        target_entry,
        limit=limit,
        on_progress=on_progress,
        stop_event=stop_event,
        **indexes,
    )


def _reference_path_keys(path_value: str) -> set[str]:
    normalized = path_value.strip().replace("\\", "/").strip("/")
    if not normalized:
        return set()
    keys = {normalized.casefold()}
    parts = [part for part in PurePosixPath(normalized).parts if part]
    if len(parts) > 1 and len(parts[0]) == 4 and parts[0].isdigit():
        stripped = "/".join(parts[1:]).strip("/")
        if stripped:
            keys.add(stripped.casefold())
    return keys


def resolve_ui_reference_constraints(
    entries: Sequence[ArchiveEntry],
    target_path: str,
    *,
    limit: int = 240,
    stop_event: Optional[object] = None,
) -> List[MaterialTextureReferenceRow]:
    rows, _stats = resolve_material_texture_references(
        entries,
        target_path,
        limit=limit,
        stop_event=stop_event,
    )
    target_keys = _reference_path_keys(target_path)
    if not target_keys:
        return []
    filtered: List[MaterialTextureReferenceRow] = []
    for row in rows:
        if not isinstance(row, MaterialTextureReferenceRow):
            continue
        if not row.get_rect_raw:
            continue
        if not (_reference_path_keys(row.related_path) & target_keys):
            continue
        filtered.append(row)
    return filtered


def summarize_ui_reference_constraints(
    entries: Sequence[ArchiveEntry],
    target_path: str,
    *,
    stop_event: Optional[object] = None,
) -> Dict[str, object]:
    rows = resolve_ui_reference_constraints(entries, target_path, stop_event=stop_event)
    if not rows:
        return {"warning_text": "", "rows": [], "constraint_count": 0}
    first = rows[0]
    warning = first.warning_text or (
        f"Referenced by UI XML with GetRect {first.rect_width}x{first.rect_height}. "
        "Upscaling the DDS alone may not change rendered size if the UI layout still uses the same rect."
    )
    return {
        "warning_text": warning,
        "rows": rows,
        "constraint_count": len(rows),
        "source_paths": [row.source_path for row in rows],
    }


def build_ui_constraint_reference_rows(
    entries: Sequence[ArchiveEntry],
    *,
    limit: int = 2000,
    stop_event: Optional[object] = None,
    on_progress: Optional[Callable[[int, int, str], None]] = None,
) -> List[MaterialTextureReferenceRow]:
    by_path, by_basename, by_tail2, by_tail3 = _build_texture_reference_indexes(entries)
    rows: List[MaterialTextureReferenceRow] = []
    seen_keys: set[tuple[str, str, str]] = set()
    reference_entries = [
        entry
        for entry in entries
        if isinstance(entry, ArchiveEntry) and entry.extension.lower() in REFERENCE_SOURCE_EXTENSIONS
    ]
    total_entries = len(reference_entries)
    for index, entry in enumerate(reference_entries, start=1):
        raise_if_cancelled(stop_event, "Research refresh cancelled.")
        if callable(on_progress):
            on_progress(index - 1, total_entries, f"Scanning UI rect references: {entry.path}")
        try:
            data, _decompressed, _note = read_archive_entry_data(entry)
        except Exception:
            continue
        text = _decode_reference_text(data)
        tokens = _extract_texture_reference_tokens(text)
        if not tokens:
            continue
        for token in tokens:
            raise_if_cancelled(stop_event, "Research refresh cancelled.")
            ui_meta = _extract_ui_reference_metadata(entry.path, text, token)
            if not ui_meta.get("get_rect_raw"):
                continue
            resolved_entries, resolution_kind = _resolve_texture_reference_token(
                token,
                by_path=by_path,
                by_basename=by_basename,
                by_tail2=by_tail2,
                by_tail3=by_tail3,
            )
            for related_entry in resolved_entries:
                if related_entry.extension.lower() != ".dds":
                    continue
                texture_width, texture_height = _archive_entry_texture_size(related_entry)
                refreshed_meta = _extract_ui_reference_metadata(
                    entry.path,
                    text,
                    token,
                    texture_width=texture_width,
                    texture_height=texture_height,
                )
                if not refreshed_meta.get("get_rect_raw"):
                    continue
                seen_key = (
                    entry.path.casefold(),
                    related_entry.path.casefold(),
                    str(refreshed_meta.get("get_rect_raw", "") or ""),
                )
                if seen_key in seen_keys:
                    continue
                seen_keys.add(seen_key)
                rows.append(
                    MaterialTextureReferenceRow(
                        source_path=entry.path,
                        source_package_label=entry.package_label,
                        related_path=related_entry.path,
                        related_package_label=related_entry.package_label,
                        relation_kind=f"references texture ({resolution_kind})",
                        match_count=max(1, text.lower().count(token.lower())),
                        snippet=_build_reference_snippet(text, token),
                        source_kind=str(refreshed_meta.get("source_kind", "") or ""),
                        texture_name=str(refreshed_meta.get("texture_name", "") or ""),
                        filename_token=str(refreshed_meta.get("filename_token", "") or ""),
                        get_rect_raw=str(refreshed_meta.get("get_rect_raw", "") or ""),
                        rect_x=int(refreshed_meta.get("rect_x", -1) or -1),
                        rect_y=int(refreshed_meta.get("rect_y", -1) or -1),
                        rect_width=int(refreshed_meta.get("rect_width", 0) or 0),
                        rect_height=int(refreshed_meta.get("rect_height", 0) or 0),
                        texture_width=texture_width,
                        texture_height=texture_height,
                        constraint_kind=str(refreshed_meta.get("constraint_kind", "") or ""),
                        warning_text=str(refreshed_meta.get("warning_text", "") or ""),
                        evidence_level=str(refreshed_meta.get("evidence_level", "") or ""),
                    )
                )
                if len(rows) >= limit:
                    if callable(on_progress):
                        on_progress(total_entries, total_entries, f"UI rect scan reached the current limit ({limit:,} rows).")
                    return rows
    if callable(on_progress):
        on_progress(total_entries, total_entries, f"Scanned {total_entries:,} XML/text reference file(s) for UI rect evidence.")
    rows.sort(key=lambda row: (row.related_path.casefold(), row.source_path.casefold()))
    return rows


def discover_archive_sidecars(
    entries: Sequence[ArchiveEntry],
    target_path: str,
    *,
    limit: int = 120,
    stop_event: Optional[object] = None,
) -> List[SidecarDiscoveryRow]:
    normalized_target = target_path.strip().replace("\\", "/").strip("/")
    if not normalized_target:
        return []
    lowered_target = normalized_target.lower()
    target_parts = _normalized_parts(lowered_target)
    target_parent = "/".join(target_parts[:-1])
    target_stem = PurePosixPath(lowered_target).stem.lower()
    target_group_key = derive_texture_group_key(lowered_target).lower()

    candidates: Dict[str, SidecarDiscoveryRow] = {}
    for entry in entries:
        raise_if_cancelled(stop_event)
        lowered_path = entry.path.replace("\\", "/").lower()
        if lowered_path == lowered_target:
            continue
        if entry.extension not in TEXTURE_IMAGE_EXTENSIONS and entry.extension not in TEXTURE_SIDECAR_EXTENSIONS:
            continue
        confidence = 0
        relation_kind = ""
        reason = ""
        entry_group_key = derive_texture_group_key(entry.path).lower()
        if entry_group_key == target_group_key:
            confidence = 96
            relation_kind = "same grouped set"
            reason = "Matches the same derived texture-set key."
        else:
            entry_parent = "/".join(_normalized_parts(lowered_path)[:-1])
            entry_stem = PurePosixPath(lowered_path).stem.lower()
            if entry_parent == target_parent and entry.extension in TEXTURE_SIDECAR_EXTENSIONS:
                if target_stem in entry_stem or entry_stem in target_stem:
                    confidence = 84
                    relation_kind = "same-folder sidecar"
                    reason = "Same folder with a matching or overlapping base stem."
            if confidence == 0 and entry_parent == target_parent and entry.extension in TEXTURE_IMAGE_EXTENSIONS:
                if target_stem in entry_stem or entry_stem in target_stem:
                    confidence = 74
                    relation_kind = "same-folder texture"
                    reason = "Nearby texture in the same folder with a similar base stem."
        if confidence <= 0:
            continue
        existing = candidates.get(lowered_path)
        if existing is not None and existing.confidence >= confidence:
            continue
        candidates[lowered_path] = SidecarDiscoveryRow(
            anchor_path=normalized_target,
            related_path=entry.path,
            package_label=entry.package_label,
            relation_kind=relation_kind,
            confidence=confidence,
            reason=reason,
        )

    rows = sorted(candidates.values(), key=lambda row: (-row.confidence, row.related_path.lower()))
    return rows[:limit]


__all__ = [
    "build_ui_constraint_reference_rows",
    "discover_archive_sidecars",
    "resolve_material_texture_references",
    "resolve_ui_reference_constraints",
    "summarize_ui_reference_constraints",
]
