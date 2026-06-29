from __future__ import annotations

import re
import struct
import threading
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import PurePosixPath
from typing import Callable, Dict, List, Mapping, Optional, Sequence, Tuple

from cdmw.constants import ARCHIVE_TEXT_PREVIEW_LIMIT
from cdmw.models import ArchiveEntry
from cdmw.core.common import raise_if_cancelled
from cdmw.core.archive_extraction import format_byte_size
from cdmw.core.archive_format import (
    _ARCHIVE_ANIMATION_SEQUENCE_EXTENSIONS,
    _ARCHIVE_XML_LIKE_EXTENSIONS,
)
from cdmw.core.archive_model_references import (
    _StructuredBinaryPreviewBundle,
    _find_archive_model_related_entries,
)
from cdmw.core.archive_binary_preview import (
    _binary_sidecar_schema_declarations,
    _build_binary_sidecar_related_references,
    _build_grouped_schema_declaration_lines,
    _build_grouped_structured_section_lines,
    _extract_binary_asset_references,
    _extract_text_asset_references,
    _group_animation_field_name,
    _group_character_customization_field_name,
    _group_meshinfo_field_name,
    _group_model_property_header_field_name,
    _group_prefab_field_name,
    _group_rig_variant_field_name,
    _group_seqmt_field_name,
    _group_world_field_name,
    _looks_like_structured_field_name,
    _paccd_analysis_document,
    _seqmt_analysis_document,
    _structured_field_type_hint,
    build_archive_related_file_references,
    build_archive_relationship_references,
    build_binary_sidecar_analysis_document,
    build_binary_strings_preview,
    extract_binary_strings,
    format_binary_header_preview,
    merge_archive_reference_rows,
    try_decode_text_like_archive_data,
)
from cdmw.core.upscale_profiles import parse_texture_sidecar_bindings

def build_meshinfo_preview(
    data: bytes,
    virtual_path: str,
    *,
    source_entry: Optional[ArchiveEntry] = None,
    archive_entries_by_normalized_path: Optional[Dict[str, Sequence[ArchiveEntry]]] = None,
    archive_entries_by_basename: Optional[Dict[str, Sequence[ArchiveEntry]]] = None,
) -> _StructuredBinaryPreviewBundle:
    strings = extract_binary_strings(data, sample_limit=262_144, max_strings=256)
    field_names = sorted({text for text in strings if _looks_like_structured_field_name(text)}, key=str.casefold)
    asset_references = _extract_binary_asset_references(data, sample_limit=262_144, max_references=64)
    related_references = _build_binary_sidecar_related_references(
        source_entry,
        asset_references=asset_references,
        archive_entries_by_normalized_path=archive_entries_by_normalized_path,
        archive_entries_by_basename=archive_entries_by_basename,
    )
    sidecar_document = build_binary_sidecar_analysis_document(
        data,
        virtual_path,
        extension=".meshinfo",
        source_entry=source_entry,
        archive_entries_by_normalized_path=archive_entries_by_normalized_path,
        archive_entries_by_basename=archive_entries_by_basename,
    )
    summary = sidecar_document.get("summary", {})
    container = sidecar_document.get("container", {})
    tables = sidecar_document.get("tables", {})
    schema_declarations = sidecar_document.get("schema_declarations", {})
    declared_rows = (
        list(schema_declarations.get("declared_member_rows") or [])
        if isinstance(schema_declarations, Mapping)
        else []
    )
    strings_preview = build_binary_strings_preview(data, sample_limit=65_536, max_strings=32)
    header_preview = format_binary_header_preview(data)
    lines = [f"MeshInfo inspector for {virtual_path}", "", "Summary:"]
    lines.append(f"- Declared member rows: {len(declared_rows):,}")
    lines.append(f"- Field-like entries: {len(field_names):,}")
    lines.append(f"- Readable strings: {len(strings):,}")
    lines.append(f"- Related asset hints: {len(asset_references):,}")
    if related_references:
        resolved_count = sum(1 for reference in related_references if reference.resolved_entry is not None)
        lines.append(f"- Resolved related files: {resolved_count:,} / {len(related_references):,}")
    lines.append(f"- Container family: {container.get('recognized_family') or 'unknown'}")
    if isinstance(schema_declarations, Mapping) and schema_declarations.get("layout_signature"):
        lines.append(f"- Declaration layout signature: {schema_declarations.get('layout_signature')}")
    lines.append(f"- Candidate offsets: {int(summary.get('offset_candidates') or 0):,}")
    lines.append(f"- Candidate count/offset tables: {int(summary.get('count_offset_pair_candidates') or 0):,}")
    lines.append(f"- Candidate float/vector rows: {int(summary.get('float_vector_candidates') or 0):,}")
    lines.append("- Editing: read-only until MeshInfo schema and no-edit rebuilds are proven.")

    if declared_rows:
        lines.extend(["", "Declared Fields:"])
        lines.extend(
            _build_grouped_schema_declaration_lines(
                [row for row in declared_rows if isinstance(row, Mapping)],
                section_order=("Physics", "Collision", "Breakable", "Bounds", "Sockets", "Tree", "Data Model", "Misc"),
            )
        )
    else:
        lines.extend(
            _build_grouped_structured_section_lines(
                field_names,
                group_func=_group_meshinfo_field_name,
                section_order=("Physics", "Collision", "Breakable", "Bounds", "Sockets", "Tree", "Data Model", "Misc"),
            )
        )
    if asset_references:
        lines.extend(["", "Detected asset references:"])
        lines.extend(f"  - {reference}" for reference in asset_references[:24])
        if len(asset_references) > 24:
            lines.append(f"  ... {len(asset_references) - 24} more")
    count_offset_pairs = list(tables.get("count_offset_pair_candidates") or []) if isinstance(tables, Mapping) else []
    if count_offset_pairs:
        lines.extend(["", "Candidate count/offset tables:"])
        for row in count_offset_pairs[:8]:
            if not isinstance(row, Mapping):
                continue
            lines.append(
                "  - "
                f"offset 0x{int(row.get('owner_offset') or 0):X}: "
                f"count={int(row.get('count') or 0):,}, data=0x{int(row.get('data_offset') or 0):X}, "
                f"confidence={row.get('confidence') or 'candidate'}"
            )
    offset_candidates = list(tables.get("offset_candidates") or []) if isinstance(tables, Mapping) else []
    if offset_candidates:
        lines.extend(["", "Candidate internal offsets:"])
        for row in offset_candidates[:8]:
            if not isinstance(row, Mapping):
                continue
            preview = str(row.get("target_preview") or "").strip()
            suffix = f" -> {preview}" if preview else ""
            lines.append(
                "  - "
                f"slot 0x{int(row.get('owner_offset') or 0):X} -> 0x{int(row.get('target_offset') or 0):X}"
                f" ({row.get('confidence') or 'candidate'}){suffix}"
            )
    float_rows = list(tables.get("float_vector_candidates") or []) if isinstance(tables, Mapping) else []
    if float_rows:
        lines.extend(["", "Candidate numeric/vector rows:"])
        for row in float_rows[:8]:
            if not isinstance(row, Mapping):
                continue
            lines.append(
                "  - "
                f"0x{int(row.get('offset') or 0):X} {row.get('type') or 'float'} = {row.get('values')}"
            )
    if strings_preview:
        lines.extend(["", strings_preview])
    lines.extend(["", "Binary header preview:", header_preview])

    detail_lines = [
        f"Detected {len(declared_rows):,} declared member row(s) and {len(field_names):,} field-like identifier(s) from the preview sample.",
        "Declared fields come from length-prefixed member/type rows; raw strings remain separate recovery evidence.",
        "Sidecar JSON export includes string offsets, header words, related files, candidate offsets, count/offset tables, and numeric rows.",
        "Direct editing is disabled because MeshInfo count/offset semantics are not stable enough for safe writes yet.",
    ]
    if asset_references:
        detail_lines.append(f"Detected {len(asset_references):,} related asset reference(s).")
    if related_references:
        detail_lines.append(f"Matched {len(related_references):,} related archive file row(s).")

    return _StructuredBinaryPreviewBundle(
        preview_text="\n".join(lines),
        detail_lines=tuple(detail_lines),
        related_references=related_references,
        metadata_label="Mesh Metadata",
    )


def build_par_structured_preview(
    data: bytes,
    virtual_path: str,
    *,
    extension: str,
    source_entry: Optional[ArchiveEntry] = None,
    archive_entries_by_normalized_path: Optional[Dict[str, Sequence[ArchiveEntry]]] = None,
    archive_entries_by_basename: Optional[Dict[str, Sequence[ArchiveEntry]]] = None,
) -> _StructuredBinaryPreviewBundle:
    strings = extract_binary_strings(data, sample_limit=262_144, max_strings=224)
    field_names = sorted({text for text in strings if _looks_like_structured_field_name(text)}, key=str.casefold)
    asset_references = _extract_binary_asset_references(data, sample_limit=262_144, max_references=64)
    strings_preview = build_binary_strings_preview(data, sample_limit=65_536, max_strings=32)
    header_preview = format_binary_header_preview(data)
    markers = [
        marker
        for marker in ("AnimationMetaData", "ParameterizedMotionSpace", "Sequencer", "SceneObject", "EmitterData")
        if marker in data[:16_384].decode("latin-1", errors="ignore")
        or marker in strings
    ]
    companion_entries = (
        _find_archive_model_related_entries(source_entry, archive_entries_by_basename)
        if source_entry is not None and archive_entries_by_basename is not None
        else ()
    )
    related_references = _build_binary_sidecar_related_references(
        source_entry,
        asset_references=asset_references,
        archive_entries_by_normalized_path=archive_entries_by_normalized_path,
        archive_entries_by_basename=archive_entries_by_basename,
    )
    sidecar_document = build_binary_sidecar_analysis_document(
        data,
        virtual_path,
        extension=extension,
        source_entry=source_entry,
        archive_entries_by_normalized_path=archive_entries_by_normalized_path,
        archive_entries_by_basename=archive_entries_by_basename,
    )
    summary = sidecar_document.get("summary", {})
    container = sidecar_document.get("container", {})
    tables = sidecar_document.get("tables", {})
    schema_declarations = sidecar_document.get("schema_declarations", {})
    declared_rows = (
        list(schema_declarations.get("declared_member_rows") or [])
        if isinstance(schema_declarations, Mapping)
        else []
    )
    animation_metadata = (
        sidecar_document.get("animation_metadata", {})
        if str(extension or "").strip().lower() == ".paa_metabin"
        else {}
    )

    normalized_extension = str(extension or "").strip().lower()
    paseq_metadata = (
        sidecar_document.get("paseq", {})
        if normalized_extension in _ARCHIVE_ANIMATION_SEQUENCE_EXTENSIONS
        else {}
    )
    paseq_timeline = paseq_metadata.get("timeline", {}) if isinstance(paseq_metadata, Mapping) else {}
    paseq_playback = paseq_metadata.get("playback_readiness", {}) if isinstance(paseq_metadata, Mapping) else {}
    papr_metadata = (
        sidecar_document.get("papr", {})
        if normalized_extension == ".papr"
        else {}
    )
    if normalized_extension == ".paa":
        title = "PAA animation inspector"
        metadata_label = "Animation"
    elif normalized_extension == ".paa_metabin":
        title = "PAA animation metadata inspector"
        metadata_label = "Animation Metadata"
    elif normalized_extension in {".pae", ".paem"}:
        title = "PAE effect inspector"
        metadata_label = "Effect"
    elif normalized_extension == ".motionblending":
        title = "Motion blending inspector"
        metadata_label = "Motion Blending"
    elif normalized_extension == ".papr":
        title = "Animation constraint inspector"
        metadata_label = "Animation Constraint"
    elif normalized_extension in _ARCHIVE_ANIMATION_SEQUENCE_EXTENSIONS:
        title = "Animation schedule inspector"
        metadata_label = "Animation / Schedule Metadata"
    else:
        title = f"{normalized_extension.lstrip('.').upper()} structured inspector"
        metadata_label = "Structured Binary"

    lines = [f"{title} for {virtual_path}", "", "Summary:"]
    lines.append(f"- Declared member rows: {len(declared_rows):,}")
    lines.append(f"- Field-like entries: {len(field_names):,}")
    lines.append(f"- Readable strings: {len(strings):,}")
    if markers:
        lines.append(f"- Detected markers: {', '.join(markers)}")
    if isinstance(animation_metadata, Mapping) and animation_metadata:
        declared_type = str(animation_metadata.get("declared_type") or "").strip()
        animation_stem = str(animation_metadata.get("animation_stem") or "").strip()
        stream = animation_metadata.get("packed_metadata_stream", {})
        if declared_type:
            lines.append(f"- Declared metadata type: {declared_type}")
        if animation_stem:
            lines.append(f"- Animation stem: {animation_stem}")
        if isinstance(stream, Mapping):
            lines.append(f"- Packed metadata stream: {int(stream.get('stream_size') or 0):,} byte(s)")
    if isinstance(paseq_timeline, Mapping) and paseq_timeline:
        lane_kind_counts = paseq_timeline.get("lane_kind_counts") if isinstance(paseq_timeline.get("lane_kind_counts"), Mapping) else {}
        lines.append(f"- Timeline lanes: {int(paseq_timeline.get('lane_count') or 0):,}")
        if lane_kind_counts:
            kind_text = ", ".join(f"{key}:{value}" for key, value in lane_kind_counts.items())
            lines.append(f"- Timeline lane kinds: {kind_text}")
        lines.append(f"- Timeline fields: {int(paseq_timeline.get('timeline_field_count') or 0):,}")
        lines.append(f"- Event/phase markers: {int(paseq_timeline.get('event_marker_count') or 0):,}")
        lines.append(f"- Timing candidates: {int(paseq_timeline.get('timing_candidate_count') or 0):,}")
    if isinstance(papr_metadata, Mapping) and papr_metadata:
        lines.append(f"- Constraint string evidence: {int(papr_metadata.get('string_evidence_count') or 0):,}")
        physics_rows = papr_metadata.get("related_physics_rows") if isinstance(papr_metadata.get("related_physics_rows"), Sequence) else ()
        if physics_rows:
            lines.append(f"- Related physics references: {len(physics_rows):,}")
    if asset_references:
        lines.append(f"- Related asset hints: {len(asset_references):,}")
    if related_references:
        resolved_count = sum(1 for reference in related_references if reference.resolved_entry is not None)
        lines.append(f"- Resolved related files: {resolved_count:,} / {len(related_references):,}")
    if companion_entries:
        lines.append(f"- Same-stem companion files: {len(companion_entries):,}")
    lines.append(f"- Container family: {container.get('recognized_family') or 'unknown'}")
    if isinstance(schema_declarations, Mapping) and schema_declarations.get("layout_signature"):
        lines.append(f"- Declaration layout signature: {schema_declarations.get('layout_signature')}")
    lines.append(f"- Candidate offsets: {int(summary.get('offset_candidates') or 0):,}")
    lines.append(f"- Candidate count/offset tables: {int(summary.get('count_offset_pair_candidates') or 0):,}")
    lines.append(f"- Candidate float/vector rows: {int(summary.get('float_vector_candidates') or 0):,}")
    if normalized_extension == ".paa":
        lines.append(f"- Candidate animation keyframe tables: {int(summary.get('animation_keyframe_table_candidates') or 0):,}")
        lines.append(f"- Candidate animation keyframe rows: {int(summary.get('animation_keyframe_rows') or 0):,}")
    if normalized_extension == ".motionblending":
        lines.append("- Editing: read-only until motion-blending schema and no-edit rebuilds are proven.")
    elif normalized_extension == ".paa":
        lines.append("- Editing: read-only until animation channel ownership, compression rules, and no-edit rebuilds are proven.")
    elif normalized_extension == ".paa_metabin":
        lines.append("- Editing: read-only; this metadata sidecar is used for browsing and relationships only.")
    elif normalized_extension in _ARCHIVE_ANIMATION_SEQUENCE_EXTENSIONS:
        lines.append("- Editing: read-only; playback is disabled until sequence timing and model/skeleton binding are proven.")

    if isinstance(animation_metadata, Mapping) and animation_metadata:
        hint_rows = [
            row
            for row in animation_metadata.get("filename_hints") or []
            if isinstance(row, Mapping)
        ]
        if hint_rows:
            lines.extend(["", "Filename-derived animation hints:"])
            for row in hint_rows[:18]:
                lines.append(
                    "  - "
                    f"{row.get('kind') or 'Hint'}: {row.get('meaning') or '-'} "
                    f"(token={row.get('token') or '-'}, confidence={row.get('confidence') or 'filename_token'})"
                )
        header_rows = [
            row
            for row in animation_metadata.get("header_rows") or []
            if isinstance(row, Mapping)
        ]
        if header_rows:
            lines.extend(["", "Stable header evidence:"])
            for row in header_rows[:10]:
                lines.append(
                    "  - "
                    f"0x{int(row.get('offset') or 0):X} {row.get('name') or 'word'} = {row.get('value')}; "
                    f"confidence={row.get('confidence') or 'observed'}"
                )
        stream = animation_metadata.get("packed_metadata_stream", {})
        if isinstance(stream, Mapping):
            marker_counts = stream.get("marker_counts") if isinstance(stream.get("marker_counts"), Mapping) else {}
            if marker_counts:
                marker_text = ", ".join(f"{key}:{value}" for key, value in list(marker_counts.items())[:8])
                lines.extend(["", "Packed metadata stream:"])
                lines.append(
                    f"  - offset=0x{int(stream.get('stream_offset') or 0):X}, "
                    f"size={int(stream.get('stream_size') or 0):,}, markers={marker_text}"
                )
                lines.append("  - Stream rows are shown as recovery evidence only; their tuple semantics are not proven.")
            preview_rows = [
                row
                for row in stream.get("preview_rows") or []
                if isinstance(row, Mapping)
            ]
            if preview_rows:
                lines.append("  - First packed bytes:")
                for row in preview_rows[:6]:
                    lines.append(f"    0x{int(row.get('offset') or 0):X}: {row.get('hex') or ''}")

    if isinstance(paseq_timeline, Mapping) and paseq_timeline:
        lanes = [row for row in paseq_timeline.get("lanes") or [] if isinstance(row, Mapping)]
        if lanes:
            lines.extend(["", "Recovered timeline lanes:"])
            for row in lanes[:18]:
                lines.append(
                    "  - "
                    f"[{row.get('kind') or 'asset'}] {row.get('path') or ''} "
                    f"({row.get('role') or 'related_asset'}, offset=0x{int(row.get('source_offset') or 0):X}, "
                    f"confidence={row.get('confidence') or 'asset_reference'})"
                )
            if len(lanes) > 18:
                lines.append(f"  ... {len(lanes) - 18} more")
        timeline_fields = [row for row in paseq_timeline.get("timeline_fields") or [] if isinstance(row, Mapping)]
        if timeline_fields:
            lines.extend(["", "Timeline field evidence:"])
            for row in timeline_fields[:18]:
                declared_type = str(row.get("declared_type") or "").strip()
                type_suffix = f": {declared_type}" if declared_type else ""
                lines.append(
                    "  - "
                    f"[{row.get('role') or 'timeline_field'}] {row.get('name') or ''}{type_suffix} "
                    f"@0x{int(row.get('offset') or 0):X} ({row.get('confidence') or row.get('source') or 'evidence'})"
                )
            if len(timeline_fields) > 18:
                lines.append(f"  ... {len(timeline_fields) - 18} more")
        event_markers = [row for row in paseq_timeline.get("event_markers") or [] if isinstance(row, Mapping)]
        if event_markers:
            lines.extend(["", "Event/phase marker strings:"])
            for row in event_markers[:12]:
                lines.append(
                    "  - "
                    f"0x{int(row.get('offset') or 0):X} {row.get('text') or ''} "
                    f"({row.get('role') or 'event'})"
                )
            if len(event_markers) > 12:
                lines.append(f"  ... {len(event_markers) - 12} more")
        timing_evidence = paseq_timeline.get("timing_evidence") if isinstance(paseq_timeline.get("timing_evidence"), Mapping) else {}
        if timing_evidence:
            lines.extend(["", "FPS timing evidence:"])
            lines.append(f"  - Status: {timing_evidence.get('fps_binding_status') or 'unknown'}")
            lines.append(f"  - Confidence: {timing_evidence.get('fps_binding_confidence') or 'unknown'}")
            declarations = [row for row in timing_evidence.get("fps_field_declarations") or [] if isinstance(row, Mapping)]
            for row in declarations[:4]:
                lines.append(
                    "  - "
                    f"{row.get('name') or '_framesPerSecond'}: {row.get('declared_type') or 'unknown'} "
                    f"@0x{int(row.get('offset') or 0):X} "
                    f"(field={row.get('confidence') or 'unknown'}, value={row.get('value_confidence') or 'unknown'})"
                )
            candidate_rows = [
                row for row in timing_evidence.get("fps_candidate_value_rows") or [] if isinstance(row, Mapping)
            ]
            for row in candidate_rows[:6]:
                lines.append(
                    "  - "
                    f"candidate {row.get('kind') or 'fps'} @0x{int(row.get('offset') or 0):X} "
                    f"= {row.get('value')} "
                    f"({row.get('status') or row.get('confidence') or 'unknown'}, "
                    f"value={row.get('value_confidence') or 'unknown'})"
                )
            proof_gap = str(timing_evidence.get("proof_gap") or "").strip()
            if proof_gap:
                lines.append(f"  - Gap: {proof_gap}")
            blend_declarations = [
                row for row in timing_evidence.get("blend_field_declarations") or [] if isinstance(row, Mapping)
            ]
            if blend_declarations:
                lines.extend(["", "Blend window evidence:"])
                lines.append(f"  - Status: {timing_evidence.get('blend_binding_status') or 'unknown'}")
                lines.append(f"  - Confidence: {timing_evidence.get('blend_binding_confidence') or 'unknown'}")
                for row in blend_declarations[:8]:
                    lines.append(
                        "  - "
                        f"{row.get('name') or 'blend'}: {row.get('declared_type') or 'unknown'} "
                        f"@0x{int(row.get('offset') or 0):X} "
                        f"({row.get('kind') or 'blend_field'}, field={row.get('confidence') or 'unknown'}, "
                        f"value={row.get('value_confidence') or 'unknown'})"
                    )
                blend_candidate_rows = [
                    row for row in timing_evidence.get("blend_candidate_value_rows") or [] if isinstance(row, Mapping)
                ]
                for row in blend_candidate_rows[:6]:
                    lines.append(
                        "  - "
                        f"candidate {row.get('kind') or 'blend'} @0x{int(row.get('offset') or 0):X} "
                        f"= {row.get('value')} "
                        f"({row.get('status') or row.get('confidence') or 'unknown'}, "
                        f"value={row.get('value_confidence') or 'unknown'})"
                    )
                blend_gap = str(timing_evidence.get("blend_proof_gap") or "").strip()
                if blend_gap:
                    lines.append(f"  - Gap: {blend_gap}")
        timing_candidates = [row for row in paseq_timeline.get("timing_candidates") or [] if isinstance(row, Mapping)]
        if timing_candidates:
            lines.extend(["", "Candidate timing values:"])
            for row in timing_candidates[:10]:
                lines.append(
                    "  - "
                    f"0x{int(row.get('offset') or 0):X} {row.get('kind') or 'candidate'} = {row.get('value')}"
                )
            if len(timing_candidates) > 10:
                lines.append(f"  ... {len(timing_candidates) - 10} more")
        if isinstance(paseq_playback, Mapping) and paseq_playback:
            lines.extend(["", "Playback readiness:"])
            lines.append(f"  - Status: {paseq_playback.get('status') or 'unknown'}")
            lines.append(f"  - Ready for 3D playback: {bool(paseq_playback.get('ready_for_3d_playback'))}")
            for blocker in [str(value) for value in paseq_playback.get("blocking_gaps") or [] if str(value).strip()][:6]:
                lines.append(f"  - Blocker: {blocker}")

    if isinstance(papr_metadata, Mapping) and papr_metadata:
        evidence_rows = [row for row in papr_metadata.get("evidence_rows") or [] if isinstance(row, Mapping)]
        role_counts = papr_metadata.get("role_counts") if isinstance(papr_metadata.get("role_counts"), Mapping) else {}
        if role_counts or evidence_rows:
            lines.extend(["", "Constraint string evidence:"])
            if role_counts:
                role_text = ", ".join(f"{key}:{value}" for key, value in sorted(role_counts.items()))
                lines.append(f"  - Roles: {role_text}")
            for row in evidence_rows[:18]:
                lines.append(
                    "  - "
                    f"0x{int(row.get('offset') or 0):X} {row.get('role') or 'constraint_string'}: "
                    f"{row.get('text') or ''} "
                    f"(field={row.get('field_confidence') or 'unknown'}, role={row.get('role_confidence') or 'unknown'})"
                )
            if len(evidence_rows) > 18:
                lines.append(f"  ... {len(evidence_rows) - 18} more")
        expression_evidence = papr_metadata.get("expression_evidence")
        if isinstance(expression_evidence, Mapping) and expression_evidence:
            lines.extend(["", "Constraint expression evidence:"])
            channel_counts = expression_evidence.get("channel_counts") if isinstance(expression_evidence.get("channel_counts"), Mapping) else {}
            limit_counts = expression_evidence.get("limit_operator_counts") if isinstance(expression_evidence.get("limit_operator_counts"), Mapping) else {}
            shape_counts = expression_evidence.get("shape_counts") if isinstance(expression_evidence.get("shape_counts"), Mapping) else {}
            numeric_role_counts = expression_evidence.get("numeric_role_counts") if isinstance(expression_evidence.get("numeric_role_counts"), Mapping) else {}
            if channel_counts:
                channel_text = ", ".join(f"{key}:{value}" for key, value in sorted(channel_counts.items()))
                lines.append(f"  - Channels: {channel_text}")
            if limit_counts:
                limit_text = ", ".join(f"{key}:{value}" for key, value in sorted(limit_counts.items()))
                lines.append(f"  - Limit operators: {limit_text}")
            if shape_counts:
                shape_text = ", ".join(f"{key}:{value}" for key, value in sorted(shape_counts.items()))
                lines.append(f"  - Syntax shapes: {shape_text}")
            if numeric_role_counts:
                role_text = ", ".join(f"{key}:{value}" for key, value in sorted(numeric_role_counts.items()))
                lines.append(f"  - Numeric roles: {role_text}")
            lines.append(
                "  - "
                f"Numeric constants: {int(expression_evidence.get('numeric_value_count') or 0)} "
                f"(tokens={expression_evidence.get('token_confidence') or 'unknown'}, "
                f"semantics={expression_evidence.get('semantics_confidence') or 'unknown'})"
            )
        offset_evidence = papr_metadata.get("offset_evidence")
        if isinstance(offset_evidence, Mapping) and offset_evidence:
            lines.extend(["", "Constraint field offset evidence:"])
            lines.append(
                "  - "
                f"{offset_evidence.get('status') or 'readable_string_offsets'}: "
                f"target={int(offset_evidence.get('target_offset_count') or 0)}, "
                f"helper={int(offset_evidence.get('helper_offset_count') or 0)}, "
                f"parent={int(offset_evidence.get('parent_offset_count') or 0)} "
                f"(offsets={offset_evidence.get('offset_confidence') or 'unknown'}, "
                f"record={offset_evidence.get('record_confidence') or 'unknown'})"
            )
        record_candidates = [row for row in papr_metadata.get("record_candidates") or [] if isinstance(row, Mapping)]
        if record_candidates:
            lines.extend(["", "Constraint record candidates:"])
            record_candidate_count = int(papr_metadata.get("record_candidate_count") or len(record_candidates))
            for row in record_candidates[:12]:
                target = str(row.get("target_bone") or "").strip() or "unknown target"
                parent = str(row.get("parent_bone") or "").strip()
                helper = str(row.get("helper_bone") or "").strip()
                context = f"target={target}"
                if helper:
                    context = f"{context}, helper={helper}"
                if parent:
                    context = f"{context}, parent={parent}"
                field_sequence = tuple(str(value) for value in row.get("record_field_sequence") or () if str(value))
                sequence_text = f"; order={'>'.join(field_sequence)}" if field_sequence else ""
                gap_counts = row.get("record_gap_class_counts") if isinstance(row.get("record_gap_class_counts"), Mapping) else {}
                gap_status = str(row.get("record_gap_status") or "")
                gap_text = ""
                if gap_status or gap_counts:
                    gap_summary = ", ".join(f"{key}:{value}" for key, value in sorted(gap_counts.items()))
                    gap_text = f"; gaps={gap_status or 'unknown'}"
                    if gap_summary:
                        gap_text = f"{gap_text} ({gap_summary})"
                scalar_counts = row.get("record_gap_scalar_kind_counts") if isinstance(row.get("record_gap_scalar_kind_counts"), Mapping) else {}
                scalar_text = ""
                if scalar_counts:
                    scalar_summary = ", ".join(f"{key}:{value}" for key, value in sorted(scalar_counts.items()))
                    scalar_text = f"; scalars={row.get('record_gap_scalar_status') or 'unknown'} ({scalar_summary})"
                match_counts = row.get("record_gap_numeric_match_role_counts") if isinstance(row.get("record_gap_numeric_match_role_counts"), Mapping) else {}
                match_text = ""
                if match_counts:
                    match_summary = ", ".join(f"{key}:{value}" for key, value in sorted(match_counts.items()))
                    match_text = f"; numeric_matches={row.get('record_gap_numeric_match_status') or 'unknown'} ({match_summary})"
                lines.append(
                    "  - "
                    f"0x{int(row.get('offset') or 0):X} {row.get('constraint_type') or 'constraint_candidate'}: "
                    f"{context}; expr={row.get('expression') or ''}{sequence_text}{gap_text}{scalar_text}{match_text} "
                    f"(field={row.get('field_confidence') or 'unknown'}, record={row.get('record_confidence') or 'unknown'}, "
                    f"solver={row.get('solver_status') or 'blocked'})"
                )
            if record_candidate_count > 12:
                lines.append(f"  ... {record_candidate_count - 12} more")
        physics_rows = [row for row in papr_metadata.get("related_physics_rows") or [] if isinstance(row, Mapping)]
        if physics_rows:
            lines.extend(["", "Related physics evidence:"])
            for row in physics_rows[:8]:
                lines.append(
                    "  - "
                    f"{row.get('reference_name') or 'physics'} -> {row.get('resolved_archive_path') or ''} "
                    f"({row.get('relation_confidence') or 'unknown'})"
                )
        proof_gap = str(papr_metadata.get("proof_gap") or "").strip()
        if proof_gap:
            lines.append(f"  - Gap: {proof_gap}")

    if declared_rows:
        lines.extend(["", "Declared Fields:"])
        motion_section_order = (
            ("Skeleton", "Animation Files", "Motion Space", "Parameters", "Delaunay", "Scene / Object", "Resources", "Misc")
            if normalized_extension == ".motionblending"
            else ("Animation Files", "Motion Space", "Parameters", "Emitter / Effect", "Scene / Object", "Resources", "Misc")
        )
        lines.extend(
            _build_grouped_schema_declaration_lines(
                [row for row in declared_rows if isinstance(row, Mapping)],
                section_order=motion_section_order,
            )
        )
    else:
        section_order = (
            ("Skeleton", "Animation Files", "Motion Space", "Parameters", "Delaunay", "Scene / Object", "Resources", "Misc")
            if normalized_extension == ".motionblending"
            else ("Animation Files", "Motion Space", "Parameters", "Emitter / Effect", "Scene / Object", "Resources", "Misc")
        )
        lines.extend(
            _build_grouped_structured_section_lines(
                field_names,
                group_func=_group_animation_field_name,
                section_order=section_order,
            )
        )
    if asset_references:
        lines.extend(["", "Detected asset references:"])
        lines.extend(f"  - {reference}" for reference in asset_references[:24])
        if len(asset_references) > 24:
            lines.append(f"  ... {len(asset_references) - 24} more")
    animation_keyframes = list(tables.get("animation_keyframe_table_candidates") or []) if isinstance(tables, Mapping) else []
    if animation_keyframes:
        lines.extend(["", "Candidate animation keyframe tables:"])
        for row in animation_keyframes[:6]:
            if not isinstance(row, Mapping):
                continue
            lines.append(
                "  - "
                f"offset 0x{int(row.get('offset') or 0):X}: "
                f"{int(row.get('row_count') or 0):,} row(s), "
                f"frames {int(row.get('frame_start') or 0):,}-{int(row.get('frame_end') or 0):,}, "
                f"{row.get('row_format') or 'keyframe rows'}, "
                f"{row.get('value_kind') or 'half-float values'}, "
                f"confidence={row.get('confidence') or 'candidate'}"
            )
            preview_rows = [preview_row for preview_row in row.get("preview_rows") or [] if isinstance(preview_row, Mapping)]
            for preview_row in preview_rows[:4]:
                lines.append(
                    "    "
                    f"0x{int(preview_row.get('offset') or 0):X} "
                    f"frame={int(preview_row.get('frame') or 0):,} "
                    f"values={preview_row.get('values')} "
                    f"norm={preview_row.get('norm')}"
                )
        lines.append("  - Keyframe rows are read-only recovery evidence; exact animation channels are not proven.")
    count_offset_pairs = list(tables.get("count_offset_pair_candidates") or []) if isinstance(tables, Mapping) else []
    if count_offset_pairs:
        lines.extend(["", "Candidate count/offset tables:"])
        for row in count_offset_pairs[:8]:
            if not isinstance(row, Mapping):
                continue
            lines.append(
                "  - "
                f"offset 0x{int(row.get('owner_offset') or 0):X}: "
                f"count={int(row.get('count') or 0):,}, data=0x{int(row.get('data_offset') or 0):X}, "
                f"confidence={row.get('confidence') or 'candidate'}"
            )
    float_rows = list(tables.get("float_vector_candidates") or []) if isinstance(tables, Mapping) else []
    if float_rows:
        lines.extend(["", "Candidate numeric/vector rows:"])
        for row in float_rows[:8]:
            if not isinstance(row, Mapping):
                continue
            lines.append(
                "  - "
                f"0x{int(row.get('offset') or 0):X} {row.get('type') or 'float'} = {row.get('values')}"
            )
    if strings_preview:
        lines.extend(["", strings_preview])
    else:
        lines.extend(["", "Readable strings:", "  None detected in the preview sample."])
    lines.extend(["", "Binary header preview:", header_preview])

    detail_lines = [
        f"Detected {len(declared_rows):,} declared member row(s) and {len(field_names):,} field-like identifier(s) from the preview sample.",
    ]
    if declared_rows:
        detail_lines.append("Declared fields come from length-prefixed member/type rows; raw strings remain separate recovery evidence.")
    if markers:
        detail_lines.append(f"Detected structured marker(s): {', '.join(markers)}.")
    if not field_names and not markers and not strings:
        detail_lines.append("No readable strings or structured markers were detected, so the preview falls back to raw header bytes.")
    if asset_references:
        detail_lines.append(f"Detected {len(asset_references):,} related asset reference(s).")
    if related_references:
        detail_lines.append(f"Matched {len(related_references):,} related archive file row(s).")
    if normalized_extension == ".paa":
        detail_lines.append(
            "This inspector summarizes animation clip metadata, candidate half-float keyframe rows, and readable markers. Playback/editing is not implemented yet."
        )
    elif normalized_extension in {".pae", ".paem"}:
        detail_lines.append("This inspector summarizes effect/emitter-side metadata and readable markers. Real particle or timeline playback is not implemented yet.")
    elif normalized_extension == ".motionblending":
        detail_lines.append(
            "This inspector summarizes motion/blend references, candidate tables, and numeric rows. Playback/editing is still disabled until the schema is stable."
        )
    elif normalized_extension == ".paa_metabin":
        detail_lines.append(
            "This inspector summarizes AnimationMetaData headers, filename-derived motion hints, same-stem relationships, and packed metadata bytes. Editing is disabled."
        )
    elif normalized_extension == ".papr":
        detail_lines.append("This inspector summarizes animation constraint declarations and readable rig references. Constraint solving and editing remain disabled.")
    elif normalized_extension in _ARCHIVE_ANIMATION_SEQUENCE_EXTENSIONS:
        detail_lines.append(
            "This inspector summarizes animation schedule/sequence timeline lanes, dependency references, timing candidates, and same-stem motion references. Editing and playback remain disabled."
        )
        if isinstance(paseq_playback, Mapping) and paseq_playback.get("blocking_gaps"):
            detail_lines.append("3D playback path is tracked in playback_readiness.blocking_gaps in the exported decode JSON.")

    return _StructuredBinaryPreviewBundle(
        preview_text="\n".join(lines),
        detail_lines=tuple(detail_lines),
        related_references=related_references,
        metadata_label=metadata_label,
    )


def _structured_asset_profile(
    extension: str,
) -> Tuple[str, str, Callable[[str], str], Tuple[str, ...], str]:
    normalized_extension = str(extension or "").strip().lower()
    if normalized_extension == ".prefab":
        return (
            "Prefab inspector",
            "Prefab",
            _group_prefab_field_name,
            (
                "Scene / Object",
                "Resources",
                "Skeleton / Sockets",
                "Mesh / Cloth",
                "Transform / Bounds",
                "Physics / Collision",
                "Logic / Events",
                "Presentation",
                "Misc",
            ),
            "Summarizes object composition, resource links, transforms, collision, and event-like markers when readable. A .prefab is metadata, not the renderable mesh; linked .pac/.pam/.pamlod files usually hold geometry.",
        )
    if normalized_extension == ".pappt":
        return (
            "Part prefab table inspector",
            "Part Prefab Metadata",
            _group_prefab_field_name,
            (
                "Scene / Object",
                "Resources",
                "Skeleton / Sockets",
                "Mesh / Cloth",
                "Transform / Bounds",
                "Physics / Collision",
                "Logic / Events",
                "Presentation",
                "Misc",
            ),
            "Summarizes part-prefab metadata and readable model/prefab/resource links. The rows are relationship evidence only; linked model files still hold geometry.",
        )
    if normalized_extension == ".pamhc":
        return (
            "Model property header inspector",
            "Model Property Metadata",
            _group_model_property_header_field_name,
            (
                "Material / Texture",
                "Model Resources",
                "Skeleton / Rig",
                "Physics / Collision",
                "Transform / Bounds",
                "Variant / Part",
                "Misc",
            ),
            "Summarizes model-property header metadata, material/resource hints, and same-stem companions. It is read-only relationship evidence, not an editable material sidecar.",
        )
    if normalized_extension == ".paccd":
        return (
            "Character customization inspector",
            "Character Customization Data",
            _group_character_customization_field_name,
            (
                "Customization Slots",
                "Palette / Color",
                "Body / Face",
                "Material / Texture",
                "Variant / Part",
                "Misc",
            ),
            "Summarizes PACCD customization slot rows and palette-like byte values. It is read-only evidence for character appearance variants.",
        )
    if normalized_extension in _ARCHIVE_ANIMATION_SEQUENCE_EXTENSIONS:
        return (
            "Animation schedule inspector",
            "Animation / Schedule Metadata",
            _group_animation_field_name,
            ("Skeleton", "Animation Files", "Motion Space", "Parameters", "Delaunay Data", "Scene / Stage", "Misc"),
            "Summarizes schedule/sequence metadata and readable animation references. Playback and editing are not implemented.",
        )
    if normalized_extension == ".papr":
        return (
            "Animation constraint inspector",
            "Animation Constraint",
            _group_animation_field_name,
            ("Skeleton", "Animation Files", "Motion Space", "Parameters", "Delaunay Data", "Scene / Stage", "Misc"),
            "Summarizes animation constraint metadata and readable rig references. Constraint solving and editing are not implemented.",
        )
    if normalized_extension == ".seqmt":
        return (
            "SEQMT sequence texture inspector",
            "Sequence Texture Metadata",
            _group_seqmt_field_name,
            ("Material / Texture", "Sequence / Timeline", "Resources", "Effect / Presentation", "Transform / Bounds", "Misc"),
            "Summarizes DDS! sequence texture atlas metadata, frame records, readable resource links, and same-stem companions. It is read-only relationship evidence.",
        )
    if normalized_extension in {".levelinfo", ".palevel"}:
        return (
            "Level inspector",
            "Level Metadata",
            _group_world_field_name,
            ("World / Region", "Scene Objects", "Terrain", "Road / Path", "Navigation", "Bounds / Transform", "Misc"),
            "Summarizes world/region metadata and resolved object or region references. It does not render the level.",
        )
    if normalized_extension in {".roadsector", ".road", ".nav"}:
        return (
            "World navigation inspector",
            "World / Navigation",
            _group_world_field_name,
            ("Road / Path", "Navigation", "World / Region", "Scene Objects", "Terrain", "Bounds / Transform", "Misc"),
            "Summarizes road, path, navigation, region, and scene-object markers when readable.",
        )
    if normalized_extension in {".pabc", ".pabv", ".pabgb", ".pabgh"}:
        return (
            "Rig variant inspector",
            "Rig / Gameplay Variant",
            _group_rig_variant_field_name,
            ("Skeleton / Rig", "Physics", "Animation", "Variant / Body", "Gameplay", "Misc"),
            "Summarizes skeleton, physics, body-variant, and gameplay markers. Replacement remains manual because incompatible rigs can break assets.",
        )
    return (
        f"{normalized_extension.lstrip('.').upper()} structured inspector",
        "Structured Binary",
        _group_prefab_field_name,
        ("Resources", "Scene / Object", "Transform / Bounds", "Physics / Collision", "Logic / Events", "Misc"),
        "Summarizes readable identifiers and resolved references from the binary preview sample.",
    )


def _iteminfo_internal_name_candidates(strings: Sequence[str], *, max_names: int = 48) -> List[str]:
    candidates: List[str] = []
    seen: set[str] = set()
    for raw_text in strings:
        text = str(raw_text or "").strip()
        if len(text) < 3 or len(text) > 96:
            continue
        if text in seen or text.isdigit():
            continue
        if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", text):
            continue
        if text.lower() in {"animationmetadata", "sceneobject", "reflectobject", "staticstringa"}:
            continue
        seen.add(text)
        candidates.append(text)
        if len(candidates) >= max_names:
            break
    return candidates


def _prefab_capability_lines(
    declaration_rows: Sequence[Mapping[str, object]],
    asset_references: Sequence[str],
) -> List[str]:
    lines = [
        f"- {row['label']}: {row['detail']}"
        for row in _prefab_evidence_rows(declaration_rows, asset_references)
    ]
    override_rows = _prefab_material_override_evidence_rows(declaration_rows, asset_references)
    if override_rows:
        routed = sum(1 for row in override_rows if row.get("role") == "resolved_material_sidecar_reference")
        lines.append(
            "- Material override routing: "
            f"{len(override_rows):,} read-only candidate row(s)"
            + (f", {routed:,} resolved material sidecar reference(s)" if routed else "")
        )
    return lines


def _prefab_evidence_rows(
    declaration_rows: Sequence[Mapping[str, object]],
    asset_references: Sequence[str],
) -> List[Dict[str, str]]:
    names = {
        str(row.get("name") or "").strip().lstrip("_").lower()
        for row in declaration_rows
        if isinstance(row, Mapping)
    }
    declared_types = {
        str(row.get("declared_type") or "").strip().lower()
        for row in declaration_rows
        if isinstance(row, Mapping)
    }
    reference_exts = {
        PurePosixPath(str(reference or "").replace("\\", "/")).suffix.lower()
        for reference in asset_references
        if str(reference or "").strip()
    }
    rows: List[Dict[str, str]] = []

    def add(label: str, detail: str, confidence: str = "declared_member_evidence") -> None:
        rows.append({"label": label, "detail": detail, "confidence": confidence})

    if any(value in names for value in ("sceneobjectuid", "sceneobjectuuid", "tag", "isenable", "generateuuid")):
        add("Scene object identity", "declares enable, tag, uid, or uuid fields that help identify the placed object instance.")
    if "components" in names or any("component" in value for value in declared_types):
        add("Scene hierarchy", "declares component and/or child-object containers.")
    if (
        "meshcomponent" in declared_types
        or "resourcereferencepath_staticmesh" in declared_types
        or any(value in names for value in ("objectfilename", "staticmeshinstancefilename", "path"))
        or ".pac" in reference_exts
        or ".pam" in reference_exts
    ):
        add("Static mesh/resource component", "can point at renderable .pac/.pam resources, but this prefab is still the metadata wrapper.")
    if (
        "skinnedmeshcomponent" in declared_types
        or "resourcereferencepath_skinnedmesh" in declared_types
        or "resourcereferencepath_characterskeleton" in declared_types
        or any(value in names for value in ("skinnedmeshfile", "skinnedmeshfilename", "skeletonfilename", "masterposeskinnedmeshcomponent"))
    ):
        add("Skinned mesh component", "declares skinned mesh, skeleton, socket, and model-property style fields.")
    if any(token in value for value in names | declared_types for token in ("cloth", "pbd", "shrink", "dynamicmotion", "sdf", "anchormeshnode")):
        add("Cloth/PBD hooks", "declares cloth, PBD, anchor, shrink-mask, or dynamic-motion fields; these are currently browse-only evidence.")
    if any("socket" in value for value in names | declared_types) or any(reference.endswith(".sockets.xml") for reference in asset_references):
        add("Socket attachments", "contains socket names or socket descriptor references useful for attaching held/body objects.")
    if any(token in value for value in names | declared_types for token in ("collision", "physics", "pbd", "shape")):
        add("Physics/collision hooks", "declares physics or collision-related component fields; editing remains read-only.")
    if any(token in value for value in names for token in ("render", "opacity", "priority")):
        add("Render/presentation overrides", "contains opacity or custom render-pass fields.")
    if (
        any(
            token in value
            for value in names | declared_types
            for token in (
                "materialinstance",
                "prefabmaterialreference",
                "prefabmaterialreferences",
                "materialparameter",
                "resourcereferencepath_material",
            )
        )
        or any(extension in reference_exts for extension in (".material", ".technique", ".pami", ".pac_xml", ".pam_xml", ".pamlod_xml"))
    ):
        add(
            "Material override hooks",
            (
                "declares material instance/reference fields or material sidecar references. These are useful for preview "
                "routing evidence, but binary override values remain read-only until the value layout is proven."
            ),
        )
    if ".xml" in reference_exts or ".prefabdata_xml" in reference_exts:
        add("Descriptor references", "points at XML descriptor data such as sockets or prefab metadata.")
    if not rows:
        add("Readable metadata", "no specific component family was proven, but identifiers and references are still shown below.")
    return rows


_PREFAB_MATERIAL_FIELD_TOKENS = (
    "material",
    "modelproperty",
    "materialproperty",
    "prefabmaterial",
    "override",
    "overrided",
    "pbdmaterial",
    "resource",
    "texture",
    "shader",
    "technique",
    "dye",
    "tint",
    "color",
    "roughness",
    "specular",
    "metal",
    "grime",
    "detail",
)


def _prefab_material_reference_role(reference: str) -> str:
    suffix = PurePosixPath(str(reference or "").replace("\\", "/")).suffix.lower()
    normalized = str(reference or "").replace("\\", "/").lower()
    if suffix in {".pac_xml", ".pam_xml", ".pamlod_xml", ".pami"} or "modelproperty/" in normalized:
        return "resolved_material_sidecar_reference"
    if suffix in {".material", ".technique"}:
        return "resolved_shader_material_reference"
    if suffix == ".dds":
        return "resolved_texture_reference"
    if suffix in {".prefabdata_xml", ".prefabdata"}:
        return "resolved_prefab_metadata_reference"
    return "asset_reference"


def _normalize_prefab_material_token_text(value: object) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value or "").strip().lower())


def _prefab_material_override_evidence_rows(
    declaration_rows: Sequence[Mapping[str, object]],
    asset_references: Sequence[str],
) -> List[Dict[str, str]]:
    rows: List[Dict[str, str]] = []
    seen: set[Tuple[str, str, str]] = set()

    def add(
        *,
        field_name: str,
        declared_type: str,
        role: str,
        confidence: str,
        offset: object = "",
        descriptor_hex: object = "",
        edit_status: str = "read_only_layout_unproven",
    ) -> None:
        key = (str(field_name), str(declared_type), str(role))
        if key in seen:
            return
        seen.add(key)
        row: Dict[str, str] = {
            "field_name": str(field_name or ""),
            "declared_type": str(declared_type or ""),
            "role": str(role or ""),
            "confidence": str(confidence or ""),
            "edit_status": str(edit_status or ""),
        }
        if offset not in ("", None):
            row["offset"] = str(offset)
        if descriptor_hex not in ("", None):
            row["descriptor_hex"] = str(descriptor_hex)
        rows.append(row)

    for row in declaration_rows:
        if not isinstance(row, Mapping):
            continue
        field_name = str(row.get("name") or "").strip()
        declared_type = str(row.get("declared_type") or "").strip()
        normalized = _normalize_prefab_material_token_text(f"{field_name} {declared_type}")
        if not normalized:
            continue
        if not any(token in normalized for token in _PREFAB_MATERIAL_FIELD_TOKENS):
            continue
        role = "material_override_field"
        if "texture" in normalized:
            role = "texture_override_field"
        if "technique" in normalized or "shader" in normalized:
            role = "shader_override_field"
        if "override" in normalized or "overrided" in normalized or "prefabmaterial" in normalized:
            role = "material_instance_override_field"
        add(
            field_name=field_name,
            declared_type=declared_type,
            role=role,
            confidence="declared_member_name",
            offset=row.get("offset", ""),
            descriptor_hex=row.get("descriptor_hex", ""),
        )

    for reference in asset_references:
        reference_text = str(reference or "").strip()
        if not reference_text:
            continue
        role = _prefab_material_reference_role(reference_text)
        if role == "asset_reference":
            continue
        add(
            field_name=reference_text,
            declared_type="asset_reference",
            role=role,
            confidence="readable_asset_reference",
            edit_status="read_only_reference_routing",
        )

    return rows[:64]


def _seqmt_preview_lines(seqmt_metadata: Mapping[str, object], *, max_rows: int = 24) -> List[str]:
    if not bool(seqmt_metadata.get("recognized")):
        reason = str(seqmt_metadata.get("reason") or "unrecognized")
        return [
            "",
            "SEQMT atlas/frame table:",
            f"  - Not recognized as DDS! sequence texture metadata ({reason}).",
        ]

    columns = int(seqmt_metadata.get("columns") or 0)
    rows = int(seqmt_metadata.get("rows") or 0)
    frame_count = int(seqmt_metadata.get("frame_count") or 0)
    capacity = int(seqmt_metadata.get("grid_capacity") or 0)
    flags_or_packing = int(seqmt_metadata.get("flags_or_packing_byte") or 0)
    payload_complete = bool(seqmt_metadata.get("payload_complete"))
    trailing_payload_bytes = int(seqmt_metadata.get("trailing_payload_bytes") or 0)
    filename_hint = seqmt_metadata.get("filename_grid_hint", {})
    lines = [
        "",
        "SEQMT atlas/frame table:",
        "  - Format: DDS! sequence texture metadata",
        f"  - Atlas grid: {columns} x {rows} ({capacity:,} slot(s))",
        f"  - Frame count: {frame_count:,}",
        f"  - Flag/packing byte: 0x{flags_or_packing:02X}",
        (
            "  - Payload: "
            f"{int(seqmt_metadata.get('decoded_frame_count') or 0):,} frame record(s), "
            f"{int(seqmt_metadata.get('frame_record_size') or 0)} byte(s) each, "
            f"{'complete' if payload_complete else 'truncated'}"
        ),
    ]
    if trailing_payload_bytes > 0:
        lines.append(f"  - Extra trailing payload: {trailing_payload_bytes:,} byte(s), preserved as raw metadata")
    if isinstance(filename_hint, Mapping) and filename_hint:
        match_label = "matches header" if bool(filename_hint.get("matches_header")) else "does not match header"
        lines.append(
            "  - Filename grid hint: "
            f"{int(filename_hint.get('columns') or 0)} x {int(filename_hint.get('rows') or 0)} ({match_label})"
        )
    if frame_count != capacity:
        lines.append("  - Grid note: frame count does not equal atlas slot count; treat unused/extra slots as read-only evidence.")
    lines.append("  - Editing: disabled until the four-byte frame record meaning and rebuild rules are proven.")

    frame_records = [
        row
        for row in seqmt_metadata.get("frame_records_preview", [])
        if isinstance(row, Mapping)
    ]
    if frame_records:
        lines.extend(["", f"Frame records (first {min(len(frame_records), max_rows):,}; channel meaning unproven):"])
        for row in frame_records[:max_rows]:
            rgba = row.get("bytes_rgba") or []
            signed_values = row.get("bytes_signed") or []
            rgba_text = ",".join(str(int(value)) for value in rgba) if isinstance(rgba, Sequence) else ""
            signed_text = ",".join(str(int(value)) for value in signed_values) if isinstance(signed_values, Sequence) else ""
            lines.append(
                "  - "
                f"frame {int(row.get('index') or 0):>3} "
                f"(x={int(row.get('grid_x') or 0)}, y={int(row.get('grid_y') or 0)}) "
                f"@0x{int(row.get('offset') or 0):04X}: "
                f"raw={row.get('hex') or ''} bytes={rgba_text} signed={signed_text}"
            )
        if bool(seqmt_metadata.get("frame_records_preview_truncated")) or len(frame_records) > max_rows:
            remaining = max(0, int(seqmt_metadata.get("decoded_frame_count") or 0) - max_rows)
            lines.append(f"  ... {remaining:,} more frame record(s)")
    return lines


def _paccd_preview_lines(paccd_metadata: Mapping[str, object], *, max_rows: int = 14) -> List[str]:
    if not bool(paccd_metadata.get("recognized")):
        reason = str(paccd_metadata.get("reason") or "unrecognized")
        return ["", f"PACCD customization table: not recognized ({reason})."]

    lines = [
        "",
        "PACCD customization table:",
        f"  - Slots: {int(paccd_metadata.get('slot_count') or 0):,}",
        f"  - Profile/version word: {int(paccd_metadata.get('profile_version') or 0)}",
        f"  - Layout: {paccd_metadata.get('format_family') or 'unknown'}, row stride {int(paccd_metadata.get('row_stride') or 0):,} byte(s)",
        f"  - Payload offset: 0x{int(paccd_metadata.get('payload_offset') or 0):X}",
    ]
    trailing = int(paccd_metadata.get("trailing_payload_bytes") or 0)
    if trailing:
        lines.append(f"  - Unknown trailing payload: {trailing:,} byte(s)")

    rows = [row for row in paccd_metadata.get("rows_preview") or [] if isinstance(row, Mapping)]
    if rows:
        lines.append("  - Slot rows:")
        for row in rows[:max_rows]:
            rgb_rows = [
                rgb
                for rgb in row.get("rgb_candidates") or []
                if isinstance(rgb, Mapping)
            ]
            rgb_text = ""
            if rgb_rows:
                first_rgb = rgb_rows[0].get("rgb_bytes") or []
                rgb_text = f", rgb hint={first_rgb}"
            lines.append(
                "    "
                f"slot {int(row.get('slot_index') or 0):02d} "
                f"@0x{int(row.get('offset') or 0):X}: "
                f"range={int(row.get('min_byte') or 0)}-{int(row.get('max_byte') or 0)}, "
                f"non-neutral={int(row.get('non_neutral_bytes') or 0):,}, "
                f"bytes={row.get('preview_hex') or ''}{rgb_text}"
            )
        if bool(paccd_metadata.get("rows_preview_truncated")) or len(rows) > max_rows:
            remaining = max(0, int(paccd_metadata.get("slot_count") or 0) - max_rows)
            lines.append(f"    ... {remaining:,} more slot row(s)")
    lines.append("  - Row semantics are read-only evidence until customization slot ownership is proven.")
    return lines


def build_structured_asset_preview(
    data: bytes,
    virtual_path: str,
    *,
    extension: str,
    source_entry: Optional[ArchiveEntry] = None,
    archive_entries_by_normalized_path: Optional[Dict[str, Sequence[ArchiveEntry]]] = None,
    archive_entries_by_basename: Optional[Dict[str, Sequence[ArchiveEntry]]] = None,
    stop_event: Optional[threading.Event] = None,
) -> _StructuredBinaryPreviewBundle:
    raise_if_cancelled(stop_event)
    strings = extract_binary_strings(data, sample_limit=262_144, max_strings=256)
    raise_if_cancelled(stop_event)
    field_names = sorted({text for text in strings if _looks_like_structured_field_name(text)}, key=str.casefold)
    asset_references = _extract_binary_asset_references(data, sample_limit=262_144, max_references=96)
    raise_if_cancelled(stop_event)
    strings_preview = build_binary_strings_preview(data, sample_limit=65_536, max_strings=32)
    header_preview = format_binary_header_preview(data)
    title, metadata_label, group_func, section_order, inspector_note = _structured_asset_profile(extension)
    normalized_extension = str(extension or "").strip().lower()
    normalized_basename = PurePosixPath(str(virtual_path or "").replace("\\", "/")).name.lower()
    iteminfo_name_candidates: List[str] = []
    if normalized_extension in {".pabgb", ".pabgh"} and normalized_basename.startswith("iteminfo."):
        if normalized_extension == ".pabgb":
            title = "Item info table inspector"
            metadata_label = "Item Database"
            inspector_note = (
                "Summarizes recovered item identifiers from iteminfo.pabgb. The app uses this table with localization, "
                "icons, and model hashes for Item Finder names and archive relationships."
            )
            iteminfo_name_candidates = _iteminfo_internal_name_candidates(strings)
        else:
            title = "Item info hash table inspector"
            metadata_label = "Item Database Index"
            inspector_note = (
                "Summarizes the companion iteminfo.pabgh index/hash table. It is useful as relationship evidence, "
                "but not directly editable or human-readable by itself."
            )
    schema_declarations = _binary_sidecar_schema_declarations(data, normalized_extension)
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
    declared_rows = (
        list(schema_declarations.get("declared_member_rows") or [])
        if isinstance(schema_declarations, Mapping)
        else []
    )
    type_candidates = (
        list(schema_declarations.get("root_or_class_candidates") or [])
        if isinstance(schema_declarations, Mapping)
        else []
    )
    companion_entries = (
        _find_archive_model_related_entries(source_entry, archive_entries_by_basename)
        if source_entry is not None and archive_entries_by_basename is not None
        else ()
    )
    raise_if_cancelled(stop_event)
    related_references = (
        build_archive_related_file_references(
            source_entry,
            explicit_reference_names=asset_references,
            companion_entries=companion_entries,
            archive_entries_by_normalized_path=archive_entries_by_normalized_path,
            archive_entries_by_basename=archive_entries_by_basename,
        )
        if source_entry is not None
        else ()
    )
    graph_references = (
        build_archive_relationship_references(
            source_entry,
            archive_entries_by_normalized_path=archive_entries_by_normalized_path,
            archive_entries_by_basename=archive_entries_by_basename,
        )
        if source_entry is not None
        else ()
    )
    related_references = merge_archive_reference_rows(related_references, graph_references)
    if len(related_references) > 240:
        related_references = tuple(related_references[:240])
    raise_if_cancelled(stop_event)

    extension_counts: Counter[str] = Counter()
    for reference in asset_references:
        suffix = PurePosixPath(reference.replace("\\", "/")).suffix.lower()
        if suffix:
            extension_counts[suffix] += 1

    lines = [f"{title} for {virtual_path}", "", "Summary:"]
    lines.append(f"- Field-like entries: {len(field_names):,}")
    lines.append(f"- Readable strings: {len(strings):,}")
    lines.append(f"- Related asset hints: {len(asset_references):,}")
    lines.append(f"- Declared member rows: {len(declared_rows):,}")
    if iteminfo_name_candidates:
        lines.append(f"- Item identifier candidates: {len(iteminfo_name_candidates):,}")
    if isinstance(schema_declarations, Mapping) and schema_declarations.get("layout_signature"):
        lines.append(f"- Declaration layout signature: {schema_declarations.get('layout_signature')}")
    if related_references:
        resolved_count = sum(1 for reference in related_references if reference.resolved_entry is not None)
        lines.append(f"- Resolved referenced files: {resolved_count:,} / {len(related_references):,}")
    if extension_counts:
        top_types = ", ".join(f"{suffix}: {count:,}" for suffix, count in extension_counts.most_common(8))
        lines.append(f"- Reference types: {top_types}")
    if companion_entries:
        lines.append(f"- Same-stem companion files: {len(companion_entries):,}")
    if isinstance(seqmt_metadata, Mapping) and seqmt_metadata.get("recognized"):
        lines.append(
            "- SEQMT atlas: "
            f"{int(seqmt_metadata.get('columns') or 0)} x {int(seqmt_metadata.get('rows') or 0)}, "
            f"{int(seqmt_metadata.get('frame_count') or 0):,} frame record(s)"
        )
    if isinstance(paccd_metadata, Mapping) and paccd_metadata.get("recognized"):
        lines.append(
            "- PACCD customization table: "
            f"{int(paccd_metadata.get('slot_count') or 0):,} slot(s), "
            f"row stride {int(paccd_metadata.get('row_stride') or 0):,}, "
            f"{paccd_metadata.get('format_family') or 'unknown'}"
        )
    if type_candidates:
        type_names = [
            str(candidate.get("name") or "").strip()
            for candidate in type_candidates
            if isinstance(candidate, Mapping) and str(candidate.get("name") or "").strip()
        ]
        if type_names and not iteminfo_name_candidates:
            lines.append(f"- Type/class candidates: {', '.join(type_names[:12])}" + (" ..." if len(type_names) > 12 else ""))
    lines.append(f"- Inspector note: {inspector_note}")

    if normalized_extension == ".prefab":
        lines.extend(["", "Prefab evidence:"])
        lines.extend(_prefab_capability_lines(declared_rows, asset_references))
    if normalized_extension == ".seqmt":
        lines.extend(_seqmt_preview_lines(seqmt_metadata if isinstance(seqmt_metadata, Mapping) else {}))
    if normalized_extension == ".paccd":
        lines.extend(_paccd_preview_lines(paccd_metadata if isinstance(paccd_metadata, Mapping) else {}))

    if iteminfo_name_candidates:
        lines.extend(["", "Recovered item identifiers:"])
        for name in iteminfo_name_candidates[:32]:
            lines.append(f"  - {name}")
        if len(iteminfo_name_candidates) > 32:
            lines.append(f"  ... {len(iteminfo_name_candidates) - 32} more")

    if declared_rows:
        lines.extend(
            _build_grouped_schema_declaration_lines(
                [row for row in declared_rows if isinstance(row, Mapping)],
                section_order=section_order,
                per_section_limit=18,
            )
        )

    if not iteminfo_name_candidates:
        lines.extend(
            _build_grouped_structured_section_lines(
                field_names,
                group_func=group_func,
                section_order=section_order,
            )
        )
    if asset_references:
        lines.extend(["", "Detected asset references:"])
        lines.extend(f"  - {reference}" for reference in asset_references[:32])
        if len(asset_references) > 32:
            lines.append(f"  ... {len(asset_references) - 32} more")
    if strings_preview:
        lines.extend(["", strings_preview])
    else:
        lines.extend(["", "Readable strings:", "  None detected in the preview sample."])
    lines.extend(["", "Binary header preview:", header_preview])

    detail_lines = [
        inspector_note,
        f"Detected {len(field_names):,} field-like identifier(s) and {len(asset_references):,} asset reference hint(s).",
    ]
    if declared_rows:
        detail_lines.append(
            f"Recovered {len(declared_rows):,} length-prefixed member declaration(s); these identify fields and types but not safe edit offsets."
        )
    if related_references:
        detail_lines.append("Resolved related archive files are listed below.")
    if normalized_extension == ".prefab":
        detail_lines.append(
            "Prefab preview uses direct readable references, same-stem companions, and bounded binary prefab relationship evidence; it remains read-only."
        )
    if normalized_extension == ".seqmt":
        if isinstance(seqmt_metadata, Mapping) and seqmt_metadata.get("recognized"):
            detail_lines.append(
                "SEQMT preview decodes the observed DDS! atlas grid and four-byte frame table. Frame record channel meaning is still read-only evidence."
            )
        else:
            detail_lines.append(
                "SEQMT preview falls back to readable identifiers, asset references, and same-stem companions. Editing remains disabled."
            )
    if normalized_extension == ".paccd":
        if isinstance(paccd_metadata, Mapping) and paccd_metadata.get("recognized"):
            detail_lines.append(
                "PACCD preview decodes the observed 14-slot customization byte table. Slider/color ownership is still read-only evidence."
            )
        else:
            detail_lines.append(
                "PACCD preview falls back to raw header evidence because the customization table header was not recognized."
            )
    if iteminfo_name_candidates:
        detail_lines.append(
            "Item info preview exposes internal item identifiers as relationship/name evidence. Display names still come from localization tables when available."
        )
    if not field_names and not asset_references and not strings:
        detail_lines.append("No readable strings or structured markers were detected, so the preview falls back to raw header bytes.")

    return _StructuredBinaryPreviewBundle(
        preview_text="\n".join(lines),
        detail_lines=tuple(detail_lines),
        related_references=related_references,
        metadata_label=metadata_label,
    )


_SIMPLIFIED_XML_ATTR_NAMES: frozenset[str] = frozenset(
    {
        "name",
        "_name",
        "type",
        "_type",
        "path",
        "_path",
        "_value",
        "value",
        "_materialname",
        "_submeshname",
        "_prefabname",
        "_meshparamfile",
        "_nudename",
        "_skeletonfile",
        "_animationfile",
        "_normaltexture",
        "_heighttexture",
        "_overlaycolortexture",
        "_colorblendingmasktexture",
        "_detailmasktexture",
    }
)


def _parse_xmlish_preview_root(text: str) -> Optional[ET.Element]:
    stripped = str(text or "").strip()
    if not stripped:
        return None
    candidates = (stripped, f"<ArchivePreviewRoot>{stripped}</ArchivePreviewRoot>")
    for candidate in candidates:
        try:
            return ET.fromstring(candidate)
        except ET.ParseError:
            continue
    return None


def _humanize_xml_field_name(name: str) -> str:
    raw = str(name or "").strip().lstrip("_")
    if not raw:
        return "Value"
    raw = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", raw)
    raw = raw.replace("_", " ").replace("-", " ")
    return " ".join(raw.split()).title() or name


def _xml_field_value_hint(name: str, value: str) -> str:
    normalized = str(name or "").strip().lstrip("_").lower()
    normalized_value = str(value or "").strip().lower()
    if "damping" in normalized:
        return "physics damping value"
    if "inertia" in normalized or "mass" in normalized:
        return "physics mass/inertia value"
    if "friction" in normalized:
        return "physics friction value"
    if "angularlimit" in normalized or "twist" in normalized or "plane" in normalized or "coneangle" in normalized:
        return "physics angular limit"
    if "socket" in normalized:
        return "skeleton/socket binding"
    if "bodyname" in normalized:
        return "physics body name"
    if normalized in {"path", "value"} or normalized.endswith("path") or "/" in normalized_value or "\\" in normalized_value:
        return "asset/reference path"
    if "material" in normalized:
        return "material/shader binding"
    if "submesh" in normalized or "mesh" in normalized:
        return "mesh/submesh binding"
    if "texture" in normalized:
        return "texture slot"
    if "color" in normalized or normalized_value.startswith("#"):
        return "color/tint value"
    if "scale" in normalized or "size" in normalized or "radius" in normalized:
        return "size/scale value"
    if "flag" in normalized or normalized.startswith(("is", "use", "enable", "disable")):
        return "flag/toggle"
    if "category" in normalized or "type" in normalized:
        return "type/category"
    return _structured_field_type_hint(name)


def _summarize_physics_attachment_xml(root: ET.Element, *, max_rows: int = 12) -> List[str]:
    elements = list(root.iter())
    if not any(str(element.tag or "").startswith("SkinnedMeshPhysicsAttachment") for element in elements):
        return []
    instance_count = sum(1 for element in elements if str(element.tag or "") == "SkinnedMeshPhysicsAttachmentInstanceDesc")
    body_elements = [
        element
        for element in elements
        if str(element.tag or "") == "SkinnedMeshPhysicsAttachmentBodyCreationDesc"
    ]
    constraint_elements = [
        element
        for element in elements
        if str(element.tag or "").startswith("SkinnedMeshPhysicsAttachment")
        and "ConstraintDesc" in str(element.tag or "")
    ]
    shape_counts: Counter[str] = Counter(
        str(element.tag or "")
        for element in elements
        if str(element.tag or "").startswith("SkinnedMeshPhysicsAttachment")
        and "ShapeDesc" in str(element.tag or "")
    )
    lines = [
        "- Physics attachment descriptor: controls extra socket-bound physics bodies, usually accessories or body-attached props.",
        f"- Physics attachment instances: {instance_count:,}; bodies: {len(body_elements):,}; constraints: {len(constraint_elements):,}",
    ]
    if shape_counts:
        lines.append("- Attachment collision shapes: " + ", ".join(f"{name}: {count:,}" for name, count in shape_counts.most_common(6)))

    socket_names = sorted(
        {
            str(element.attrib.get("_socketName") or "").strip()
            for element in body_elements
            if str(element.attrib.get("_socketName") or "").strip()
        },
        key=str.casefold,
    )
    body_names = sorted(
        {
            str(element.attrib.get("_bodyName") or "").strip()
            for element in body_elements
            if str(element.attrib.get("_bodyName") or "").strip()
        },
        key=str.casefold,
    )
    if socket_names:
        lines.append("- Socket bindings: " + ", ".join(socket_names[:10]) + (f" (+{len(socket_names) - 10} more)" if len(socket_names) > 10 else ""))
    if body_names:
        lines.append("- Physics bodies: " + ", ".join(body_names[:10]) + (f" (+{len(body_names) - 10} more)" if len(body_names) > 10 else ""))

    tunables: List[str] = []
    for element in elements:
        tag = str(element.tag or "")
        for key, value in sorted(element.attrib.items(), key=lambda item: item[0].casefold()):
            normalized = str(key or "").strip().lstrip("_").lower()
            if normalized not in {
                "angulardamping",
                "lineardamping",
                "inertiafactor",
                "maxfrictiontorque",
                "angularlimitmin",
                "angularlimitmax",
                "coneangle",
                "twistmin",
                "twistmax",
                "planemin",
                "planemax",
                "sphereradius",
                "cylinderheight",
                "radius",
            }:
                continue
            label = _humanize_xml_field_name(key)
            tunables.append(f"  - {tag}.{label}: {value} ({_xml_field_value_hint(key, value)})")
            if len(tunables) >= max_rows:
                break
        if len(tunables) >= max_rows:
            break
    if tunables:
        lines.extend(["", "Physics attachment tunables:"])
        lines.extend(tunables)
    lines.append(
        "Editing note: these XML values are much more explicitly named than HKX fields; damping, inertia, limits, shape size, and friction are reasonable modding targets when this descriptor is selected."
    )
    return lines


def build_simplified_text_asset_summary(
    text: str,
    *,
    extension: str,
    virtual_path: str,
    max_rows: int = 40,
) -> str:
    normalized_extension = str(extension or "").strip().lower()
    if normalized_extension not in _ARCHIVE_XML_LIKE_EXTENSIONS and normalized_extension not in {".material", ".xml"}:
        return ""
    root = _parse_xmlish_preview_root(text)
    asset_references = _extract_text_asset_references(text, sidecar_path=virtual_path, max_references=48)
    lines = [f"Simplified values for {virtual_path}", ""]
    if root is None:
        if not asset_references:
            return ""
        lines.extend(["Resolved-looking asset references:"])
        lines.extend(f"  - {reference}" for reference in asset_references[:24])
        if len(asset_references) > 24:
            lines.append(f"  ... {len(asset_references) - 24} more")
        return "\n".join(lines)

    elements = list(root.iter())
    tag_counts: Counter[str] = Counter(str(element.tag or "").strip() for element in elements if str(element.tag or "").strip())
    material_bindings = tuple(parse_texture_sidecar_bindings(text, sidecar_path=virtual_path))
    lines.append("What this appears to contain:")
    if tag_counts:
        top_tags = ", ".join(f"{tag}: {count:,}" for tag, count in tag_counts.most_common(8))
        lines.append(f"- XML/object types: {top_tags}")
    if material_bindings:
        submesh_names = sorted({binding.submesh_name for binding in material_bindings if binding.submesh_name}, key=str.casefold)
        parameter_names = sorted({binding.parameter_name for binding in material_bindings if binding.parameter_name}, key=str.casefold)
        lines.append(f"- Material texture bindings: {len(material_bindings):,}")
        if submesh_names:
            lines.append(f"- Submesh/material slots: {', '.join(submesh_names[:8])}" + (f" (+{len(submesh_names) - 8} more)" if len(submesh_names) > 8 else ""))
        if parameter_names:
            lines.append(f"- Texture parameter kinds: {', '.join(parameter_names[:10])}" + (f" (+{len(parameter_names) - 10} more)" if len(parameter_names) > 10 else ""))
    if asset_references:
        lines.append(f"- Asset/reference paths: {len(asset_references):,}")
    physics_attachment_lines = _summarize_physics_attachment_xml(root)
    if physics_attachment_lines:
        lines.extend(["", "Physics attachment summary:"])
        lines.extend(physics_attachment_lines)

    rows: List[Tuple[str, str, str]] = []
    seen_rows: set[Tuple[str, str]] = set()
    for element in elements:
        for key, value in sorted(element.attrib.items(), key=lambda item: item[0].casefold()):
            clean_key = str(key or "").strip()
            clean_value = str(value or "").strip()
            if not clean_key or not clean_value:
                continue
            normalized_key = clean_key.strip().lower()
            keep = (
                normalized_key in _SIMPLIFIED_XML_ATTR_NAMES
                or normalized_key.endswith(("path", "name", "type", "flag", "scale", "radius", "size", "color", "category"))
                or "/" in clean_value
                or "\\" in clean_value
                or clean_value.startswith("#")
            )
            if not keep:
                continue
            row_key = (normalized_key, clean_value)
            if row_key in seen_rows:
                continue
            seen_rows.add(row_key)
            rows.append((_humanize_xml_field_name(clean_key), clean_value, _xml_field_value_hint(clean_key, clean_value)))
            if len(rows) >= max_rows:
                break
        if len(rows) >= max_rows:
            break

    if rows:
        lines.extend(["", "Recognized fields:"])
        for label, value, hint in rows:
            compact_value = value if len(value) <= 160 else value[:157] + "..."
            lines.append(f"  - {label}: {compact_value} ({hint})")
    if asset_references:
        lines.extend(["", "Detected asset references:"])
        lines.extend(f"  - {reference}" for reference in asset_references[:24])
        if len(asset_references) > 24:
            lines.append(f"  ... {len(asset_references) - 24} more")
    lines.extend(
        [
            "",
            "Editing note: text/XML-like entries can be extracted or included in mod-ready loose folders, but only recognized material sidecars currently have a guided value editor.",
        ]
    )
    return "\n".join(lines)


def describe_archive_binary_content(extension: str, data: bytes) -> str:
    head4 = data[:4]
    if head4 == b"BKHD":
        return "Detected Wwise soundbank data."
    if extension == ".seqmt" and head4 == b"DDS!":
        if len(data) >= 12:
            columns = int(struct.unpack_from("<H", data, 5)[0])
            rows = int(struct.unpack_from("<H", data, 7)[0])
            frame_count = int(struct.unpack_from("<H", data, 10)[0])
            return f"Detected SEQMT DDS! sequence texture metadata ({columns} x {rows}, {frame_count} frame records)."
        return "Detected SEQMT DDS! sequence texture metadata."
    if head4 == b"PAR ":
        if extension == ".pac":
            return "Detected PAR skinned mesh data."
        if extension == ".pab":
            return "Detected PAR skeleton data."
        if extension == ".pat":
            return "Detected PAR model data. Visual model preview is not available yet."
        if extension == ".pam":
            return "Detected PAR mesh data."
        if extension == ".pamlod":
            return "Detected PAR mesh LOD data."
        if extension == ".paa":
            return "Detected PAR animation data. Visual animation preview is not available yet."
        if extension in {".pae", ".paem"}:
            return "Detected PAR effect or emitter data. Real effect playback is not available yet."
        return "Detected PAR-family binary data."
    if head4 == b"PARC":
        return "Detected PARC structured container data."
    if len(data) >= 16 and data[4:8] == b"TAG0" and data[12:16] == b"SDKV":
        return "Detected Havok tagfile data. Collision geometry and related skeleton context are shown when decoded."
    if data.startswith(b"RIFF") and data[8:12] == b"WAVE":
        return "Detected RIFF/WAVE audio data, likely Wwise `.wem`."
    if b"EmitterData" in data[:4096]:
        return "Structured emitter or effect data detected."
    if b"SceneObject" in data[:4096]:
        return "Structured scene or prefab metadata detected."
    if b"AnimationMetaData" in data[:4096]:
        return "Animation metadata detected."
    if b"ParameterizedMotionSpace" in data[:4096]:
        return "Animation motion-blending metadata detected."
    if b"Sequencer" in data[:4096]:
        return "Structured sequencer data detected."
    if extension == ".seqmt":
        return "Structured SEQMT sequence texture metadata detected."
    if extension == ".pabgb":
        return "Structured gameplay or table-like binary data detected."
    if extension == ".meshinfo":
        return "Structured mesh metadata detected."
    if extension in {".pae", ".paem"}:
        return "Structured emitter or effect data detected."
    if extension == ".levelinfo":
        return "Structured level metadata detected."
    if extension == ".prefab":
        return "Structured prefab metadata detected."
    return ""


def build_archive_binary_preview_payload(
    entry: ArchiveEntry,
    data: bytes,
    *,
    info_extra: str = "",
) -> Tuple[str, str, str]:
    text_preview = try_decode_text_like_archive_data(data)
    if text_preview:
        extra_parts = [part for part in [info_extra, "Binary content was sniffed as plain text."] if part]
        if len(data) > ARCHIVE_TEXT_PREVIEW_LIMIT:
            extra_parts.append(f"Preview truncated to {format_byte_size(ARCHIVE_TEXT_PREVIEW_LIMIT)}.")
        return "text", text_preview, "\n\n".join(extra_parts)

    strings_preview = build_binary_strings_preview(data)
    hint_text = describe_archive_binary_content(entry.extension, data)
    extra_parts = [part for part in [info_extra, hint_text] if part]
    if strings_preview:
        extra_parts.append(strings_preview)
        return "text", strings_preview, "\n\n".join(extra_parts)
    return "info", "", "\n\n".join(extra_parts)
