from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Callable, Dict, List, Mapping, Optional, Sequence, Tuple

from cdmw.core.archive_hkx_corpus_planning import _hkx_corpus_role_for_document
from cdmw.core.archive_hkx_corpus_scan import (
    HkxCorpusScanState,
    _hkx_fixup_semantics_summary,
    _hkx_tagfile_reference_fixup_summary,
    _hkx_xml_parity_summary,
)
from cdmw.core.common import raise_if_cancelled
from cdmw.models import RunCancelled


def _hkx_metadata_graph_status(readiness: Mapping[str, object], state: HkxCorpusScanState) -> Dict[str, object]:
    native_model_graph = readiness.get("native_model_graph")
    native_model_graph_status = ""
    rust_parse_status = ""
    if isinstance(native_model_graph, Mapping):
        native_model_graph_status = str(native_model_graph.get("status") or "")
        rust_parse_status = str(native_model_graph.get("rust_low_level_parse_status") or "")
        if native_model_graph_status:
            state.aggregate_native_model_graph_status_counts[native_model_graph_status] += 1
        if rust_parse_status:
            state.aggregate_native_low_level_parse_status_counts[rust_parse_status] += 1
    no_edit_binary_writer = readiness.get("no_edit_binary_writer")
    no_edit_binary_writer_status = ""
    if isinstance(no_edit_binary_writer, Mapping):
        no_edit_binary_writer_status = str(no_edit_binary_writer.get("status") or "")
        if no_edit_binary_writer_status:
            state.aggregate_no_edit_binary_writer_status_counts[no_edit_binary_writer_status] += 1
    biggest_remaining_gate = readiness.get("biggest_remaining_gate")
    biggest_remaining_gate_status = ""
    if isinstance(biggest_remaining_gate, Mapping):
        biggest_remaining_gate_status = str(biggest_remaining_gate.get("status") or "")
        if biggest_remaining_gate_status:
            state.aggregate_biggest_remaining_gate_status_counts[biggest_remaining_gate_status] += 1
    return {
        "native_model_graph": native_model_graph,
        "native_model_graph_status": native_model_graph_status,
        "rust_parse_status": rust_parse_status,
        "no_edit_binary_writer": no_edit_binary_writer,
        "no_edit_binary_writer_status": no_edit_binary_writer_status,
        "biggest_remaining_gate": biggest_remaining_gate,
        "biggest_remaining_gate_status": biggest_remaining_gate_status,
    }


def _hkx_metadata_class_status(readiness: Mapping[str, object], state: HkxCorpusScanState) -> Dict[str, object]:
    class_internals = readiness.get("class_internals")
    status = ""
    observed_count = 0
    if isinstance(class_internals, Mapping):
        status = str(class_internals.get("status") or "")
        if status:
            state.aggregate_class_internals_status_counts[status] += 1
        try:
            observed_count = int(class_internals.get("observed_target_count") or 0)
        except (TypeError, ValueError, OverflowError):
            observed_count = 0
        targets = class_internals.get("targets")
        if isinstance(targets, list):
            for target in targets:
                if not isinstance(target, Mapping) or not bool(target.get("present_in_file")):
                    continue
                target_class = str(target.get("class") or "")
                if target_class:
                    state.aggregate_class_internals_target_counts[target_class] += 1
    return {"value": class_internals, "status": status, "observed_count": observed_count}


def _hkx_metadata_hard_status(readiness: Mapping[str, object], state: HkxCorpusScanState) -> Dict[str, object]:
    hard_targets = readiness.get("hard_decoder_targets")
    status = ""
    observed_count = 0
    unresolved_count = 0
    observed_targets: List[str] = []
    if isinstance(hard_targets, Mapping):
        status = str(hard_targets.get("status") or "")
        if status:
            state.aggregate_hard_decoder_target_status_counts[status] += 1
        try:
            observed_count = int(hard_targets.get("observed_target_count") or 0)
        except (TypeError, ValueError, OverflowError):
            observed_count = 0
        try:
            unresolved_count = int(hard_targets.get("unresolved_target_count") or 0)
        except (TypeError, ValueError, OverflowError):
            unresolved_count = 0
        targets = hard_targets.get("targets")
        if isinstance(targets, list):
            for target in targets:
                if not isinstance(target, Mapping):
                    continue
                target_status = str(target.get("status") or "")
                if target_status:
                    state.aggregate_hard_decoder_target_status_counts[target_status] += 1
                key = str(target.get("key") or "")
                if bool(target.get("present_in_file")) and key:
                    state.aggregate_hard_decoder_target_counts[key] += 1
                    observed_targets.append(key)
                    try:
                        state.aggregate_hard_decoder_target_byte_counts[key] += int(
                            target.get("observed_byte_count") or 0
                        )
                    except (TypeError, ValueError, OverflowError):
                        pass
    return {
        "value": hard_targets,
        "status": status,
        "observed_count": observed_count,
        "unresolved_count": unresolved_count,
        "observed_targets": observed_targets,
    }


def _hkx_metadata_gui_status(readiness: Mapping[str, object], state: HkxCorpusScanState) -> Dict[str, object]:
    gui_readiness = readiness.get("gui_readiness")
    status = ""
    partial_count = 0
    missing_count = 0
    if isinstance(gui_readiness, Mapping):
        status = str(gui_readiness.get("status") or "")
        if status:
            state.aggregate_gui_readiness_status_counts[status] += 1
        try:
            partial_count = int(gui_readiness.get("partial_target_count") or 0)
        except (TypeError, ValueError, OverflowError):
            partial_count = 0
        try:
            missing_count = int(gui_readiness.get("missing_target_count") or 0)
        except (TypeError, ValueError, OverflowError):
            missing_count = 0
        targets = gui_readiness.get("targets")
        if isinstance(targets, list):
            for target in targets:
                target_status = str(target.get("status") or "") if isinstance(target, Mapping) else ""
                if target_status:
                    state.aggregate_gui_readiness_target_status_counts[target_status] += 1
    return {"status": status, "partial_count": partial_count, "missing_count": missing_count}


def _hkx_metadata_readiness_summary(readiness: object, state: HkxCorpusScanState) -> Dict[str, object]:
    if not isinstance(readiness, Mapping):
        return {}
    status = str(readiness.get("status") or "")
    if status:
        state.aggregate_hkclass_metadata_readiness_status_counts[status] += 1
    graph = _hkx_metadata_graph_status(readiness, state)
    class_status = _hkx_metadata_class_status(readiness, state)
    hard = _hkx_metadata_hard_status(readiness, state)
    gui = _hkx_metadata_gui_status(readiness, state)
    unresolved_counts = readiness.get("unresolved_real_metadata_counts")
    if isinstance(unresolved_counts, Mapping):
        for key, count in unresolved_counts.items():
            try:
                state.aggregate_hkclass_metadata_missing_counts[str(key)] += int(count or 0)
            except (TypeError, ValueError, OverflowError):
                continue
    missing_requirements = readiness.get("missing_real_hkclass_metadata")
    native_model_graph = graph["native_model_graph"]
    no_edit_binary_writer = graph["no_edit_binary_writer"]
    biggest_remaining_gate = graph["biggest_remaining_gate"]
    class_internals = class_status["value"]
    hard_targets = hard["value"]
    return {
        "status": status,
        "types_section_status": readiness.get("types_section_status"),
        "__types_section_status": readiness.get("__types_section_status"),
        "real_hkclass_metadata_recovered": readiness.get("real_hkclass_metadata_recovered"),
        "class_count": readiness.get("class_count"),
        "synthetic_class_count": readiness.get("synthetic_class_count"),
        "real_hkclass_metadata_class_count": readiness.get("real_hkclass_metadata_class_count"),
        "declared_member_count": readiness.get("declared_member_count"),
        "recovered_member_count": readiness.get("recovered_member_count"),
        "missing_real_hkclass_metadata": [
            str(requirement.get("key") or "")
            for requirement in missing_requirements
            if isinstance(requirement, Mapping) and str(requirement.get("key") or "")
        ]
        if isinstance(missing_requirements, list)
        else [],
        "unresolved_real_metadata_counts": dict(unresolved_counts) if isinstance(unresolved_counts, Mapping) else {},
        "native_model_graph_status": graph["native_model_graph_status"],
        "rust_low_level_parse_status": graph["rust_parse_status"],
        "rust_parses_sections_items_fixups_objects": native_model_graph.get(
            "rust_parses_sections_items_fixups_objects"
        )
        if isinstance(native_model_graph, Mapping)
        else False,
        "python_builds_richer_graph_export": native_model_graph.get("python_builds_richer_graph_export")
        if isinstance(native_model_graph, Mapping)
        else True,
        "native_object_graph_available": native_model_graph.get("native_object_graph_available")
        if isinstance(native_model_graph, Mapping)
        else False,
        "native_fixup_backed_reference_graph_available": native_model_graph.get(
            "native_fixup_backed_reference_graph_available"
        )
        if isinstance(native_model_graph, Mapping)
        else False,
        "native_owner_array_resolution_available": native_model_graph.get("native_owner_array_resolution_available")
        if isinstance(native_model_graph, Mapping)
        else False,
        "native_root_container_semantics_available": native_model_graph.get(
            "native_root_container_semantics_available"
        )
        if isinstance(native_model_graph, Mapping)
        else False,
        "native_model_graph_node_count": native_model_graph.get("native_model_graph_node_count")
        if isinstance(native_model_graph, Mapping)
        else 0,
        "native_model_graph_edge_count": native_model_graph.get("native_model_graph_edge_count")
        if isinstance(native_model_graph, Mapping)
        else 0,
        "native_model_graph_fixup_backed_reference_edge_count": native_model_graph.get(
            "native_model_graph_fixup_backed_reference_edge_count"
        )
        if isinstance(native_model_graph, Mapping)
        else 0,
        "native_model_graph_owner_array_count": native_model_graph.get("native_model_graph_owner_array_count")
        if isinstance(native_model_graph, Mapping)
        else 0,
        "required_native_graph_capabilities": [
            str(capability.get("key") or "")
            for capability in native_model_graph.get("required_native_graph_capabilities", [])
            if isinstance(capability, Mapping) and str(capability.get("key") or "")
        ]
        if isinstance(native_model_graph, Mapping)
        else [],
        "no_edit_binary_writer_status": graph["no_edit_binary_writer_status"],
        "byte_identical_no_edit_rebuild_supported": no_edit_binary_writer.get(
            "byte_identical_no_edit_rebuild_supported"
        )
        if isinstance(no_edit_binary_writer, Mapping)
        else False,
        "biggest_remaining_gate": str(biggest_remaining_gate.get("key") or "")
        if isinstance(biggest_remaining_gate, Mapping)
        else "",
        "biggest_remaining_gate_status": graph["biggest_remaining_gate_status"],
        "native_read_model_write_available": biggest_remaining_gate.get("native_read_model_write_available")
        if isinstance(biggest_remaining_gate, Mapping)
        else False,
        "representative_binary_writer_roles": biggest_remaining_gate.get("representative_file_roles", [])
        if isinstance(biggest_remaining_gate, Mapping)
        else [],
        "class_internals_status": class_status["status"],
        "class_internals_observed_target_count": class_status["observed_count"],
        "class_internals_targets": [
            str(target.get("class") or "")
            for target in class_internals.get("targets", [])
            if isinstance(target, Mapping) and bool(target.get("present_in_file")) and str(target.get("class") or "")
        ]
        if isinstance(class_internals, Mapping)
        else [],
        "hard_decoder_targets_status": hard["status"],
        "hard_decoder_observed_target_count": hard["observed_count"],
        "hard_decoder_unresolved_target_count": hard["unresolved_count"],
        "hard_decoder_observed_targets": hard["observed_targets"],
        "hard_decoder_native_evidence_status": hard_targets.get("native_evidence_status")
        if isinstance(hard_targets, Mapping)
        else "",
        "hard_decoder_native_observed_byte_count": hard_targets.get("native_total_observed_byte_count")
        if isinstance(hard_targets, Mapping)
        else 0,
        "gui_readiness_status": gui["status"],
        "gui_partial_target_count": gui["partial_count"],
        "gui_missing_target_count": gui["missing_count"],
    }


def _hkx_roundtrip_status(
    hkx,
    data: bytes,
    document: Mapping[str, object],
    path: Path,
    *,
    allowed: bool,
) -> Tuple[str, Optional[bool], Optional[bool]]:
    if not allowed:
        return "skipped_roundtrip_limit", None, None
    json_result = hkx.apply_hkx_editable_geometry_document(data, document)
    xml_text = hkx.build_hkx_editable_geometry_xml(data, str(path))
    xml_result = hkx.apply_hkx_editable_geometry_xml(data, xml_text)
    return (
        "verified",
        json_result.data == data and not json_result.changed_fields,
        xml_result.data == data and not xml_result.changed_fields,
    )


def _hkx_document_counts(
    document: Mapping[str, object],
    report: Mapping[str, object],
    physics_body_context: object,
    state: HkxCorpusScanState,
) -> Dict[str, object]:
    raw_records = document.get("raw_records")
    raw_record_count = len(raw_records) if isinstance(raw_records, list) else 0
    type_registry = document.get("type_registry")
    type_names: List[str] = []
    if isinstance(type_registry, Mapping) and isinstance(type_registry.get("type_names"), list):
        type_names = [str(value) for value in type_registry["type_names"] if str(value)]
    for type_name in type_names:
        state.aggregate_type_counts[type_name] += 1
    status_counts = report.get("record_status_counts")
    if isinstance(status_counts, Mapping):
        for status, count in status_counts.items():
            if isinstance(count, int):
                state.aggregate_status_counts[str(status)] += count
    unknown_schema_areas = report.get("failed_or_unknown_schema_areas")
    if isinstance(unknown_schema_areas, list):
        for area in unknown_schema_areas:
            if not isinstance(area, Mapping):
                continue
            type_name = str(area.get("type_name") or "")
            if not type_name:
                continue
            try:
                state.aggregate_unknown_schema_record_counts[type_name] += int(area.get("record_count") or 0)
                state.aggregate_unknown_schema_byte_counts[type_name] += int(
                    area.get("unresolved_byte_count") or area.get("raw_preserved_byte_count") or 0
                )
            except (TypeError, ValueError, OverflowError):
                continue
    physics_names = document.get("physics_names")
    shape_name_count = 0
    if isinstance(physics_names, Mapping) and isinstance(physics_names.get("shape_name_properties"), list):
        shape_name_count = sum(
            1
            for shape_name in physics_names["shape_name_properties"]
            if isinstance(shape_name, Mapping) and str(shape_name.get("name") or "").strip()
        )
    collision_shapes = document.get("collision_shapes")
    named_collision_shape_count = 0
    mesh_shape_count = 0
    mesh_detail_shape_count = 0
    mesh_detail_group_counts: Dict[str, int] = {}
    if isinstance(collision_shapes, list):
        named_collision_shape_count = sum(
            1
            for shape in collision_shapes
            if isinstance(shape, Mapping) and isinstance(shape.get("name_hint"), Mapping)
        )
        for shape in collision_shapes:
            if not isinstance(shape, Mapping) or shape.get("shape_type") != "hknpMeshShape":
                continue
            mesh_shape_count += 1
            mesh_details = shape.get("mesh_details")
            if not isinstance(mesh_details, Mapping):
                continue
            mesh_detail_shape_count += 1
            for group_name in (
                "mesh_shape_records",
                "geometry_sections",
                "primitive_buffers",
                "aabb_tree_nodes",
                "shape_tag_table",
                "mesh_byte_buffers",
            ):
                group = mesh_details.get(group_name)
                if isinstance(group, list):
                    mesh_detail_group_counts[group_name] = mesh_detail_group_counts.get(group_name, 0) + len(group)
                    state.aggregate_mesh_detail_group_counts[group_name] += len(group)
    physics_body_summary = document.get("physics_body_summary")
    physics_constraint_summary = document.get("physics_constraint_summary")
    editable_field_catalog = document.get("editable_field_catalog")
    byte_patch_map = document.get("byte_patch_map")
    effect_counts: Dict[str, object] = {}
    if isinstance(editable_field_catalog, Mapping) and isinstance(editable_field_catalog.get("effect_counts"), Mapping):
        effect_counts = dict(editable_field_catalog["effect_counts"])
        for effect, count in editable_field_catalog["effect_counts"].items():
            if isinstance(count, int):
                state.aggregate_editable_effect_counts[str(effect)] += count
    body_context_count = 0
    constraint_hint_count = 0
    matched_shape_context_count = 0
    if isinstance(physics_body_context, Mapping):
        body_context_count = int(physics_body_context.get("body_count") or 0)
        constraint_hint_count = int(physics_body_context.get("constraint_hint_count") or 0)
        body_contexts = physics_body_context.get("body_contexts")
        if isinstance(body_contexts, list):
            for body_context in body_contexts:
                shape_matches = body_context.get("shape_matches") if isinstance(body_context, Mapping) else None
                if isinstance(shape_matches, list):
                    matched_shape_context_count += sum(
                        1
                        for match in shape_matches
                        if isinstance(match, Mapping) and match.get("decoded_shape_index") is not None
                    )
    return {
        "item_record_count": report.get("item_record_count"),
        "raw_record_count": raw_record_count,
        "status_counts": status_counts,
        "unknown_schema_areas": unknown_schema_areas,
        "type_names": type_names,
        "shape_name_count": shape_name_count,
        "named_collision_shape_count": named_collision_shape_count,
        "mesh_shape_count": mesh_shape_count,
        "mesh_detail_shape_count": mesh_detail_shape_count,
        "mesh_detail_group_counts": mesh_detail_group_counts,
        "physics_body_summary_count": int(physics_body_summary.get("body_count") or 0)
        if isinstance(physics_body_summary, Mapping)
        else 0,
        "physics_constraint_summary_count": int(physics_constraint_summary.get("constraint_count") or 0)
        if isinstance(physics_constraint_summary, Mapping)
        else 0,
        "editable_field_catalog_count": int(editable_field_catalog.get("field_count") or 0)
        if isinstance(editable_field_catalog, Mapping)
        else 0,
        "byte_patch_map_count": int(byte_patch_map.get("entry_count") or 0)
        if isinstance(byte_patch_map, Mapping)
        else 0,
        "editable_field_effect_counts": effect_counts,
        "body_context_count": body_context_count,
        "constraint_hint_count": constraint_hint_count,
        "matched_shape_context_count": matched_shape_context_count,
    }


def _hkx_scan_file_document(
    path: Path,
    file_index: int,
    file_count: int,
    descriptor_hints: List[Dict[str, object]],
    roundtrip_limit: int,
    state: HkxCorpusScanState,
    *,
    stop_event: Optional[threading.Event],
    progress_callback: Optional[Callable[[int, int, str], None]],
) -> Dict[str, object]:
    from cdmw.core import archive_hkx as hkx

    data = path.read_bytes()
    raise_if_cancelled(stop_event, "HKX corpus scan stopped by user.")
    document = hkx.build_hkx_editable_geometry_document(data, str(path))
    raise_if_cancelled(stop_event, "HKX corpus scan stopped by user.")
    report = document.get("converter_report") if isinstance(document, Mapping) else None
    if not isinstance(report, Mapping):
        raise ValueError("HKX converter report was not generated.")
    if descriptor_hints:
        document_with_descriptors = hkx.build_hkx_editable_geometry_document(data, str(path), descriptor_hints)
        raise_if_cancelled(stop_event, "HKX corpus scan stopped by user.")
        physics_body_context = document_with_descriptors.get("physics_body_context")
    else:
        physics_body_context = document.get("physics_body_context")
    fixup_summary = _hkx_tagfile_reference_fixup_summary(document.get("tagfile_reference_fixups"), state)
    semantics_summary = _hkx_fixup_semantics_summary(document.get("fixup_semantics_report"), state)
    parity_summary = _hkx_xml_parity_summary(document.get("hkx_xml_parity_report"), state)
    metadata_summary = _hkx_metadata_readiness_summary(document.get("hkclass_metadata_readiness"), state)
    compatibility = document.get("cdmw_hkx_compatibility")
    compatibility_status = (
        str(compatibility.get("status") or "")
        if isinstance(compatibility, Mapping)
        else str(report.get("cdmw_hkx_compatibility_status") or report.get("status") or "")
    )
    if compatibility_status:
        state.aggregate_compatibility_status_counts[compatibility_status] += 1
    roundtrip_allowed = roundtrip_limit <= 0 or file_index <= roundtrip_limit
    if roundtrip_allowed and progress_callback is not None:
        progress_callback(
            file_index - 1,
            file_count,
            f"Verifying no-edit HKX roundtrip {file_index:,} / {file_count:,}: {path.name}",
        )
    roundtrip_status, json_identical, xml_identical = _hkx_roundtrip_status(
        hkx,
        data,
        document,
        path,
        allowed=roundtrip_allowed,
    )
    counts = _hkx_document_counts(document, report, physics_body_context, state)
    corpus_role = _hkx_corpus_role_for_document(path, document, report)
    state.aggregate_role_counts[corpus_role] += 1
    if len(state.role_examples[corpus_role]) < 5:
        state.role_examples[corpus_role].append(str(path))
    if json_identical and xml_identical:
        state.aggregate_role_roundtrip_counts[corpus_role] += 1
    item_record_count = counts["item_record_count"]
    return {
        "ok": True,
        "corpus_role": corpus_role,
        "sdk_version": report.get("sdk_version"),
        "cdmw_hkx_compatibility_status": compatibility_status,
        "declared_size": report.get("declared_size"),
        "size_matches": report.get("size_matches"),
        "type_count": report.get("type_count"),
        "item_record_count": item_record_count,
        "editable_record_count": report.get("editable_record_count"),
        "decoded_or_partial_record_count": report.get("decoded_or_partial_record_count"),
        "decoded_coverage": report.get("decoded_coverage"),
        "raw_record_count": counts["raw_record_count"],
        "raw_records_cover_items": counts["raw_record_count"] == item_record_count,
        "no_edit_json_roundtrip_identical": json_identical,
        "no_edit_xml_roundtrip_identical": xml_identical,
        "no_edit_roundtrip_status": roundtrip_status,
        "no_edit_roundtrip_skipped": not roundtrip_allowed,
        "record_status_counts": counts["status_counts"] or {},
        "unknown_schema_areas": counts["unknown_schema_areas"]
        if isinstance(counts["unknown_schema_areas"], list)
        else [],
        "type_names": counts["type_names"],
        "companion_descriptor_hints": descriptor_hints,
        "companion_descriptor_hint_count": len(descriptor_hints),
        "physics_shape_name_count": counts["shape_name_count"],
        "physics_named_collision_shape_count": counts["named_collision_shape_count"],
        "physics_body_summary_count": counts["physics_body_summary_count"],
        "physics_constraint_summary_count": counts["physics_constraint_summary_count"],
        "editable_field_catalog_count": counts["editable_field_catalog_count"],
        "byte_patch_map_count": counts["byte_patch_map_count"],
        "editable_field_effect_counts": counts["editable_field_effect_counts"],
        "mesh_shape_count": counts["mesh_shape_count"],
        "mesh_detail_shape_count": counts["mesh_detail_shape_count"],
        "mesh_detail_group_counts": counts["mesh_detail_group_counts"],
        "hkx_xml_parity_summary": parity_summary,
        "hkclass_metadata_readiness_summary": metadata_summary,
        "tagfile_reference_fixup_summary": fixup_summary,
        "fixup_semantics_summary": semantics_summary,
        "physics_body_context_body_count": counts["body_context_count"],
        "physics_body_context_constraint_hint_count": counts["constraint_hint_count"],
        "physics_body_context_matched_shape_count": counts["matched_shape_context_count"],
    }


def scan_hkx_corpus_files(
    hkx_paths: Sequence[Path],
    descriptor_hints_by_stem: Mapping[str, List[Dict[str, object]]],
    roundtrip_limit: int,
    state: HkxCorpusScanState,
    *,
    stop_event: Optional[threading.Event],
    progress_callback: Optional[Callable[[int, int, str], None]],
) -> None:
    for file_index, path in enumerate(hkx_paths, start=1):
        file_scan_started = time.perf_counter()
        raise_if_cancelled(stop_event, "HKX corpus scan stopped by user.")
        if progress_callback is not None:
            progress_callback(
                file_index - 1,
                len(hkx_paths),
                f"Scanning HKX {file_index:,} / {len(hkx_paths):,}: {path.name}",
            )
        row: Dict[str, object] = {
            "path": str(path),
            "size": path.stat().st_size if path.exists() else None,
            "ok": False,
        }
        try:
            row.update(
                _hkx_scan_file_document(
                    path,
                    file_index,
                    len(hkx_paths),
                    descriptor_hints_by_stem.get(path.stem, []),
                    roundtrip_limit,
                    state,
                    stop_event=stop_event,
                    progress_callback=progress_callback,
                )
            )
        except RunCancelled:
            raise
        except Exception as exc:
            row["error"] = str(exc)
        finally:
            row["scan_seconds"] = round(time.perf_counter() - file_scan_started, 3)
            if progress_callback is not None:
                progress_callback(
                    file_index,
                    len(hkx_paths),
                    f"Finished HKX {file_index:,} / {len(hkx_paths):,}: {path.name} ({row['scan_seconds']}s)",
                )
        state.rows.append(row)
    if progress_callback is not None:
        progress_callback(
            len(hkx_paths),
            len(hkx_paths),
            f"Finished detailed HKX scan: {len(hkx_paths):,} file(s).",
        )
