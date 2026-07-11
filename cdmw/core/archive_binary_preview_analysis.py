from __future__ import annotations

import hashlib
import json
from pathlib import PurePosixPath
from typing import Dict, Mapping, Optional, Sequence

from cdmw.models import ArchiveEntry


def _collect_analysis_parts(
    data: bytes,
    virtual_path: str,
    normalized_extension: str,
    source_entry: Optional[ArchiveEntry],
    archive_entries_by_normalized_path: Optional[Dict[str, Sequence[ArchiveEntry]]],
    archive_entries_by_basename: Optional[Dict[str, Sequence[ArchiveEntry]]],
) -> Dict[str, object]:
    from cdmw.core import archive_binary_preview as preview

    animation_metadata = (
        preview._paa_metabin_analysis_document(data, virtual_path)
        if normalized_extension == ".paa_metabin"
        else {}
    )
    seqmt_metadata = (
        preview._seqmt_analysis_document(data, virtual_path)
        if normalized_extension == ".seqmt"
        else {}
    )
    paccd_metadata = (
        preview._paccd_analysis_document(data, virtual_path)
        if normalized_extension == ".paccd"
        else {}
    )
    string_records = preview._extract_binary_string_records(data, sample_limit=262_144, max_strings=512)
    field_records = [
        record for record in string_records if preview._looks_like_structured_field_name(record.text)
    ]
    asset_reference_rows = preview._binary_sidecar_asset_reference_rows(string_records, max_references=96)
    asset_references = []
    seen_references: set[str] = set()
    for row in asset_reference_rows:
        path = str(row.get("path") or "").strip()
        normalized = preview._normalize_model_texture_reference(path)
        if normalized and normalized not in seen_references:
            seen_references.add(normalized)
            asset_references.append(path)
    for path in preview._extract_binary_asset_references(data, sample_limit=262_144, max_references=96):
        normalized = preview._normalize_model_texture_reference(path)
        if normalized and normalized not in seen_references:
            seen_references.add(normalized)
            asset_references.append(path)
    related_references = preview._build_binary_sidecar_related_references(
        source_entry,
        asset_references=asset_references,
        archive_entries_by_normalized_path=archive_entries_by_normalized_path,
        archive_entries_by_basename=archive_entries_by_basename,
    )
    offset_candidates = preview._binary_sidecar_offset_candidates(data)
    count_offset_pairs = preview._binary_sidecar_count_offset_pairs(data)
    float_rows = preview._binary_sidecar_float_rows(data)
    animation_keyframe_tables = (
        preview._binary_sidecar_animation_keyframe_tables(data)
        if normalized_extension == ".paa"
        else []
    )
    schema_declarations = preview._binary_sidecar_schema_declarations(data, normalized_extension)
    schema_member_rows = [
        row for row in schema_declarations.get("declared_member_rows", []) if isinstance(row, Mapping)
    ]
    paseq_metadata = (
        preview._paseq_analysis_document(
            data,
            virtual_path,
            string_records=string_records,
            asset_reference_rows=asset_reference_rows,
            schema_member_rows=schema_member_rows,
        )
        if normalized_extension in preview._ARCHIVE_ANIMATION_SEQUENCE_EXTENSIONS
        else {}
    )
    papr_metadata = (
        preview._papr_constraint_analysis_document(data, string_records, related_references)
        if normalized_extension == ".papr"
        else {}
    )
    prefab_evidence_rows = (
        preview._prefab_evidence_rows(schema_member_rows, asset_references)
        if normalized_extension == ".prefab"
        else []
    )
    prefab_material_override_rows = (
        preview._prefab_material_override_evidence_rows(schema_member_rows, asset_references)
        if normalized_extension == ".prefab"
        else []
    )
    field_group_func = preview._binary_sidecar_group_func_for_extension(normalized_extension)
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
    editable_candidate_rows = [
        {
            "offset": row["offset"],
            "type": row["type"],
            "value": row["values"],
            "edit_status": "disabled_until_schema_is_proven",
            "confidence": row["confidence"],
        }
        for row in float_rows[:16]
    ]
    return locals()


def _analysis_summary(parts: Mapping[str, object]) -> Dict[str, object]:
    animation_metadata = parts["animation_metadata"]
    paseq_metadata = parts["paseq_metadata"]
    papr_metadata = parts["papr_metadata"]
    paccd_metadata = parts["paccd_metadata"]
    seqmt_metadata = parts["seqmt_metadata"]
    schema_declarations = parts["schema_declarations"]
    return {
        "readable_strings": len(parts["string_records"]),
        "field_like_identifiers": len(parts["field_records"]),
        "asset_reference_hints": len(parts["asset_references"]),
        "related_files_resolved": sum(
            1 for reference in parts["related_references"] if reference.resolved_entry is not None
        ),
        "related_file_rows": len(parts["related_references"]),
        "offset_candidates": len(parts["offset_candidates"]),
        "count_offset_pair_candidates": len(parts["count_offset_pairs"]),
        "float_vector_candidates": len(parts["float_rows"]),
        "animation_keyframe_table_candidates": len(parts["animation_keyframe_tables"]),
        "animation_keyframe_rows": sum(
            int(row.get("row_count") or 0) for row in parts["animation_keyframe_tables"]
        ),
        "schema_declarations": int(schema_declarations.get("declaration_count") or 0),
        "schema_declared_members": len(parts["schema_member_rows"]),
        "schema_layout_signature": str(schema_declarations.get("layout_signature") or ""),
        "prefab_evidence_rows": len(parts["prefab_evidence_rows"]),
        "prefab_material_override_rows": len(parts["prefab_material_override_rows"]),
        "seqmt_recognized": bool(seqmt_metadata.get("recognized"))
        if isinstance(seqmt_metadata, Mapping) else False,
        "seqmt_columns": int(seqmt_metadata.get("columns") or 0)
        if isinstance(seqmt_metadata, Mapping) else 0,
        "seqmt_rows": int(seqmt_metadata.get("rows") or 0)
        if isinstance(seqmt_metadata, Mapping) else 0,
        "seqmt_frame_count": int(seqmt_metadata.get("frame_count") or 0)
        if isinstance(seqmt_metadata, Mapping) else 0,
        "seqmt_payload_complete": bool(seqmt_metadata.get("payload_complete"))
        if isinstance(seqmt_metadata, Mapping) else False,
        "paccd_recognized": bool(paccd_metadata.get("recognized"))
        if isinstance(paccd_metadata, Mapping) else False,
        "paccd_slot_count": int(paccd_metadata.get("slot_count") or 0)
        if isinstance(paccd_metadata, Mapping) else 0,
        "paccd_row_stride": int(paccd_metadata.get("row_stride") or 0)
        if isinstance(paccd_metadata, Mapping) else 0,
        "animation_metadata_stream_bytes": int(
            ((animation_metadata.get("packed_metadata_stream") or {}).get("stream_size") or 0)
            if isinstance(animation_metadata.get("packed_metadata_stream"), Mapping)
            else 0
        ),
        "animation_metadata_filename_hints": len(animation_metadata.get("filename_hints") or [])
        if isinstance(animation_metadata, Mapping) else 0,
        "paseq_timeline_lanes": int(((paseq_metadata.get("timeline") or {}).get("lane_count") or 0))
        if isinstance(paseq_metadata.get("timeline"), Mapping) else 0,
        "paseq_timeline_fields": int(((paseq_metadata.get("timeline") or {}).get("timeline_field_count") or 0))
        if isinstance(paseq_metadata.get("timeline"), Mapping) else 0,
        "paseq_event_markers": int(((paseq_metadata.get("timeline") or {}).get("event_marker_count") or 0))
        if isinstance(paseq_metadata.get("timeline"), Mapping) else 0,
        "paseq_timing_candidates": int(((paseq_metadata.get("timeline") or {}).get("timing_candidate_count") or 0))
        if isinstance(paseq_metadata.get("timeline"), Mapping) else 0,
        "papr_constraint_string_evidence": int(papr_metadata.get("string_evidence_count") or 0)
        if isinstance(papr_metadata, Mapping) else 0,
        "papr_constraint_related_physics": len(papr_metadata.get("related_physics_rows") or ())
        if isinstance(papr_metadata, Mapping) else 0,
    }


def _analysis_document(data: bytes, virtual_path: str, parts: Mapping[str, object]) -> Dict[str, object]:
    from cdmw.core import archive_binary_preview as preview

    normalized_extension = str(parts["normalized_extension"])
    return {
        "document": "Crimson Desert Mod Workbench binary sidecar decode document.",
        "format_status": "experimental_read_only_schema_recovery",
        "source": {
            "path": virtual_path,
            "extension": normalized_extension,
            "kind": preview._binary_sidecar_kind_label(normalized_extension),
            "size": len(data),
            "sha1": hashlib.sha1(data).hexdigest(),
        },
        "summary": _analysis_summary(parts),
        "container": preview._binary_sidecar_container_summary(data, normalized_extension),
        "header_words_le": preview._binary_sidecar_header_words(data),
        "schema_declarations": parts["schema_declarations"],
        "prefab": {
            "evidence_rows": parts["prefab_evidence_rows"],
            "material_override_rows": parts["prefab_material_override_rows"],
            "editing_supported": False,
            "note": ".prefab files describe scene/resource/component metadata; renderable geometry usually lives in linked .pac/.pam/.pamlod assets.",
        } if normalized_extension == ".prefab" else {},
        "animation_metadata": parts["animation_metadata"],
        "animation": {
            "keyframe_table_candidates": parts["animation_keyframe_tables"],
            "editing_supported": False,
            "note": ".paa animation clip rows are exposed as read-only recovery evidence. Channel ownership and write rules are not proven.",
        } if normalized_extension == ".paa" else {},
        "papr": parts["papr_metadata"],
        "paseq": parts["paseq_metadata"],
        "seqmt": parts["seqmt_metadata"],
        "paccd": parts["paccd_metadata"],
        "strings": {
            "field_rows": parts["field_rows"],
            "readable_rows": [
                {
                    "offset": record.offset,
                    "text": record.text,
                    "kind": "field" if preview._looks_like_structured_field_name(record.text) else "string",
                }
                for record in parts["string_records"][:256]
            ],
        },
        "references": {
            "asset_reference_hints": parts["asset_reference_rows"],
            "related_files": preview._binary_sidecar_reference_document_rows(parts["related_references"]),
        },
        "tables": {
            "offset_candidates": parts["offset_candidates"],
            "count_offset_pair_candidates": parts["count_offset_pairs"],
            "float_vector_candidates": parts["float_rows"],
            "animation_keyframe_table_candidates": parts["animation_keyframe_tables"],
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
            "candidate_rows": parts["editable_candidate_rows"],
        },
        "notes": [
            "Offsets are byte offsets in the decoded archive payload used by preview/export.",
            "Schema declarations are length-prefixed member/type rows recovered from the binary; they identify fields but do not prove value write offsets.",
            "Offset/count/float rows are recovery evidence, not stable schema fields.",
            "Related files may include same-stem companions and archive relationship graph matches.",
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
    parts = _collect_analysis_parts(
        data,
        virtual_path,
        normalized_extension,
        source_entry,
        archive_entries_by_normalized_path,
        archive_entries_by_basename,
    )
    return _analysis_document(data, virtual_path, parts)


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
