from __future__ import annotations

from cdmw.models import ArchiveEntry
from collections.abc import Mapping
from pathlib import Path
from collections.abc import Sequence
import json
import os
import tempfile

from tools.mesh_harness.constants import (
    _ADVANCED_AUTHORING_CONFIDENCE_LABELS,
    _ADVANCED_AUTHORING_CORPUS_EXTENSIONS,
    _ADVANCED_AUTHORING_STATE_LABELS,
    _REAL_ARCHIVE_RIGGING_SAMPLES,
    _REAL_ARCHIVE_SEQUENCE_PTM_DESCRIPTOR,
    _REAL_ARCHIVE_SEQUENCE_PTM_PAA,
    _REAL_ARCHIVE_SEQUENCE_PTM_PAB,
    _REAL_ARCHIVE_SEQUENCE_PTM_PAPR,
    _REAL_ARCHIVE_SEQUENCE_SAMPLE,
)

from tools.mesh_harness.archive_provenance import (
    _sha256_file,
)

from tools.mesh_harness.real_common import (
    _archive_entry_indexes,
    _entry_by_archive_path,
)

def _write_json_atomic(path: Path, payload: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=path.parent,
        delete=False,
    ) as handle:
        temp_path = Path(handle.name)
        json.dump(payload, handle, indent=2, sort_keys=True)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    try:
        os.replace(temp_path, path)
    finally:
        temp_path.unlink(missing_ok=True)

def _mesh_editor_evidence_report(scenario: str, result: Mapping[str, object]) -> dict[str, object]:
    report: dict[str, object] = {
        "schema": "cdmw_mesh_editor_evidence_report_v2",
        "scenario": scenario,
        "ok": bool(result.get("ok")),
        "read_only": _result_contains_read_only(result),
        "scenario_metadata": dict(result.get("scenario_metadata", {}))
        if isinstance(result.get("scenario_metadata"), Mapping)
        else {},
        "confidence_labels": list(_ADVANCED_AUTHORING_CONFIDENCE_LABELS),
        "state_labels": list(_ADVANCED_AUTHORING_STATE_LABELS),
        "feature_status_rows": _mesh_editor_feature_status_rows(result),
        "corpus_manifest": _result_corpus_manifest(result),
    }
    visual_proof = result.get("real_archive_mesh_editor_dotnet_edit")
    if not isinstance(visual_proof, Mapping):
        visual_proof = result.get("real_archive_mesh_editor_d3d11_side_by_side_edit")
    if isinstance(visual_proof, Mapping):
        report["real_game_proof"] = _real_game_mesh_evidence(visual_proof)
    return report

def _proof_artifact(path_value: object) -> dict[str, object]:
    path = Path(str(path_value or ""))
    try:
        return {
            "path": str(path),
            "bytes": int(path.stat().st_size),
            "sha256": _sha256_file(path),
        }
    except OSError:
        return {"path": str(path), "bytes": 0, "sha256": ""}

def _proof_gate(proof: Mapping[str, object], name: str, *aliases: str) -> bool:
    for key in (name, *aliases):
        if key in proof:
            return bool(proof.get(key))
    nested = proof.get("gates")
    if not isinstance(nested, Mapping):
        return False
    for key in (name, *aliases):
        if key in nested:
            return bool(nested.get(key))
    return False

def _real_game_mesh_evidence(proof: Mapping[str, object]) -> dict[str, object]:
    textures = proof.get("resolved_production_textures")
    texture_rows = [dict(row) for row in textures] if isinstance(textures, (list, tuple)) else []
    captures = {
        name: _proof_artifact(proof.get(key))
        for name, key in (
            ("before", "before_capture_png"),
            ("selected_before", "selected_before_capture_png"),
            ("after", "after_capture_png"),
            ("diff", "visual_edit_proof_png"),
        )
    }
    gate_aliases = {
        "texture_gate_ok": ("real_textures_bound_and_decoded",),
        "real_texture_provenance_ok": ("real_texture_provenance",),
        "no_synthetic_fallback": (),
        "archive_sources_unchanged": ("source_archives_unchanged",),
        "archive_source_content_unchanged": (),
        "source_payload_unchanged": (),
        "changed_only_selected_geometry": ("selected_geometry_only",),
        "selected_face_moved": ("selected_geometry_only",),
        "selected_projection_ok": ("selected_projection_tracks_cursor",),
        "selected_projected_drag_tracks_cursor": ("selected_projection_tracks_cursor",),
        "native_window_stationary_ok": ("native_window_stationary",),
        "live_stroke_frame_budget_ok": (),
        "heartbeat_ok": (),
        "native_fallback_ok": ("edit_backend_ok",),
    }
    gate_names = list(gate_aliases)
    if any(key in proof for key in ("backend_gate_ok", "renderer_backend_ok", "edit_backend_ok")):
        gate_names.extend(("renderer_backend_ok", "edit_backend_ok", "backend_gate_ok"))
    gates = {
        key: _proof_gate(proof, key, *gate_aliases.get(key, ()))
        for key in gate_names
    }
    if "selected_face_moved" not in proof:
        gates["selected_face_moved"] = bool(gates["selected_face_moved"] and int(proof.get("changed_vertex_count", 0) or 0) > 0)
    nested_gates = proof.get("gates")
    if isinstance(nested_gates, Mapping) and (proof.get("renderer_backend") or "backend_gate_ok" in proof):
        gates.update({str(key): bool(value) for key, value in nested_gates.items()})
    return {
        "schema": "cdmw_real_game_mesh_proof_v1",
        "ok": bool(proof.get("ok")) and all(gates.values()),
        "backend": str(proof.get("backend", "")),
        "renderer_backend": str(proof.get("renderer_backend", "")),
        "edit_backend": str(proof.get("edit_backend", "")),
        "asset": {
            "path": str(proof.get("model_path", "")),
            "sha256": str(proof.get("source_payload_sha256", "")),
            "archive_provenance": dict(proof.get("archive_provenance", {}))
            if isinstance(proof.get("archive_provenance"), Mapping)
            else {},
        },
        "textures": texture_rows,
        "bound_texture_count": int(proof.get("bound_texture_count", 0) or 0),
        "archive_content_fingerprints_before": dict(proof.get("archive_content_fingerprints_before", {}))
        if isinstance(proof.get("archive_content_fingerprints_before"), Mapping)
        else {},
        "archive_content_fingerprints_after": dict(proof.get("archive_content_fingerprints_after", {}))
        if isinstance(proof.get("archive_content_fingerprints_after"), Mapping)
        else {},
        "captures": captures,
        "selected_geometry": {
            "submesh_index": int(proof.get("submesh_index", -1) or -1),
            "face_count": int(proof.get("selected_face_count", 0) or len(tuple(proof.get("selected_faces", ()) or ()))),
            "vertex_indices": list(proof.get("selected_face_vertices", ())),
            "changed_vertex_count": int(proof.get("changed_vertex_count", 0) or 0),
        },
        "projected_drag": {
            "start": list(proof.get("mouse_drag_start", ())),
            "points": list(proof.get("mouse_drag_points", ())),
            "end": list(proof.get("mouse_drag_end", ())),
            "screen_delta": list(proof.get("selected_projected_screen_delta", ())),
            "screen_error": float(proof.get("selected_projected_screen_error", 0.0) or 0.0),
        },
        "frame_timings": dict(proof.get("live_stroke_timing_summary", proof.get("stroke_handler_timing_summary", {})))
        if isinstance(proof.get("live_stroke_timing_summary", proof.get("stroke_handler_timing_summary", {})), Mapping)
        else {},
        "heartbeat": {
            "count": int(proof.get("heartbeat_count", proof.get("heartbeat_sample_count", 0)) or 0),
            "max_gap_ms": float(proof.get("max_heartbeat_gap_ms", 0.0) or 0.0),
        },
        "resident_material_update": dict(proof.get("resident_material_update", {}))
        if isinstance(proof.get("resident_material_update"), Mapping)
        else {},
        "resident_material_parameter_update": dict(proof.get("resident_material_parameter_update", {}))
        if isinstance(proof.get("resident_material_parameter_update"), Mapping)
        else {},
        "geometry_display": dict(proof.get("geometry_display", {}))
        if isinstance(proof.get("geometry_display"), Mapping)
        else {},
        "builder_presentation": dict(proof.get("builder_presentation", {}))
        if isinstance(proof.get("builder_presentation"), Mapping)
        else {},
        "production_flow": [
            dict(row) for row in tuple(proof.get("production_flow", ()) or ()) if isinstance(row, Mapping)
        ],
        "linked_texture_updates": dict(proof.get("linked_texture_updates", {}))
        if isinstance(proof.get("linked_texture_updates"), Mapping)
        else {},
        "resident_mesh_edits": dict(proof.get("resident_mesh_edits", {}))
        if isinstance(proof.get("resident_mesh_edits"), Mapping)
        else {},
        "part_selection": dict(proof.get("part_selection", {}))
        if isinstance(proof.get("part_selection"), Mapping)
        else {},
        "resident_export": dict(proof.get("resident_export", {}))
        if isinstance(proof.get("resident_export"), Mapping)
        else {},
        "performance_capture": dict(proof.get("performance_capture", {}))
        if isinstance(proof.get("performance_capture"), Mapping)
        else {},
        "lifecycle_counts": dict(proof.get("lifecycle_counts", {}))
        if isinstance(proof.get("lifecycle_counts"), Mapping)
        else {},
        "process_identity": dict(proof.get("process_identity", {}))
        if isinstance(proof.get("process_identity"), Mapping)
        else {},
        "helper_provenance": dict(proof.get("helper_provenance", {}))
        if isinstance(proof.get("helper_provenance"), Mapping)
        else {},
        "offscreen_icon_capture": dict(proof.get("offscreen_icon_capture", {}))
        if isinstance(proof.get("offscreen_icon_capture"), Mapping)
        else {},
        "native_window": {
            "before": proof.get("native_window_rect_before", proof.get("form_rect_before")),
            "after": proof.get("native_window_rect_after", proof.get("form_rect_after")),
        },
        "gates": gates,
    }

def _mesh_editor_feature_status_rows(result: Mapping[str, object]) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    service = result.get("service") if isinstance(result.get("service"), Mapping) else None
    if service is not None:
        rows.append(
            _feature_status_row(
                "Mesh edit session",
                "exportable" if bool(service.get("ok")) else "blocked",
                "proven" if bool(service.get("ok")) else "blocked",
                "Synthetic PAC/PAM/PAMLOD edit commands and package export validator path covered.",
            )
        )
    real_archive = result.get("real_archive") if isinstance(result.get("real_archive"), Mapping) else None
    if real_archive is not None:
        rows.append(
            _feature_status_row(
                "Rig pose preview",
                "preview-only" if bool(real_archive.get("ok")) else "blocked",
                "proven" if bool(real_archive.get("ok")) else "unknown",
                "Read-only real archive PAB skinning smoke.",
            )
        )
    animation = result.get("real_archive_animation") if isinstance(result.get("real_archive_animation"), Mapping) else None
    if animation is not None:
        rows.append(
            _feature_status_row(
                "PAA playback",
                "preview-only" if bool(animation.get("safe_playback_ready")) else "blocked",
                "proven" if bool(animation.get("safe_playback_ready")) else "unknown",
                "Exact PAB bone-hash-owned tracks only.",
            )
        )
    sequence = result.get("real_archive_sequence") if isinstance(result.get("real_archive_sequence"), Mapping) else None
    if sequence is not None:
        paa_binding = sequence.get("paa_binding") if isinstance(sequence.get("paa_binding"), Mapping) else {}
        rows.append(
            _feature_status_row(
                "PASEQ/PASEQC playback",
                "preview-only" if bool(paa_binding.get("ready")) else "blocked",
                "proven" if bool(paa_binding.get("ready")) else "unknown",
                str(sequence.get("timing_status") or "timing evidence unavailable"),
            )
        )
        rows.append(
            _feature_status_row(
                "PAPR constraints",
                "blocked",
                "unknown",
                "Read-only PAR metadata; solver fields not proven.",
            )
        )
    rows.append(
        _feature_status_row(
            "Direct archive mutation",
            "blocked",
            "blocked",
            "Harness is read-only; ArchiveMutationService dry-run/backup/readback gates still required.",
        )
    )
    return rows

def _feature_status_row(feature: str, state: str, confidence: str, detail: str) -> dict[str, str]:
    return {
        "feature": feature,
        "state": state if state in _ADVANCED_AUTHORING_STATE_LABELS else "blocked",
        "confidence": confidence if confidence in _ADVANCED_AUTHORING_CONFIDENCE_LABELS else "unknown",
        "detail": detail,
    }

def _result_contains_read_only(value: object) -> bool:
    if isinstance(value, Mapping):
        if bool(value.get("read_only")):
            return True
        return any(_result_contains_read_only(child) for child in value.values())
    if isinstance(value, (list, tuple)):
        return any(_result_contains_read_only(child) for child in value)
    return False

def _result_corpus_manifest(result: Mapping[str, object]) -> dict[str, object]:
    for key in ("real_archive_sequence", "real_archive_animation", "real_archive"):
        nested = result.get(key)
        if isinstance(nested, Mapping) and isinstance(nested.get("corpus_manifest"), Mapping):
            return dict(nested["corpus_manifest"])  # type: ignore[index]
    return _mesh_editor_advanced_authoring_corpus_manifest(())

def _mesh_editor_advanced_authoring_corpus_manifest(
    entries: Sequence[ArchiveEntry],
    entries_by_path: Mapping[str, Sequence[ArchiveEntry]] | None = None,
) -> dict[str, object]:
    entries_by_path = entries_by_path or _archive_entry_indexes(entries)[0]
    formats: dict[str, dict[str, object]] = {
        extension: {"entry_count": 0, "packages": [], "examples": []}
        for extension in _ADVANCED_AUTHORING_CORPUS_EXTENSIONS
    }
    packages_by_extension: dict[str, set[str]] = {extension: set() for extension in _ADVANCED_AUTHORING_CORPUS_EXTENSIONS}
    examples_by_extension: dict[str, list[str]] = {extension: [] for extension in _ADVANCED_AUTHORING_CORPUS_EXTENSIONS}
    for entry in entries:
        extension = str(entry.extension or "").lower()
        if extension not in formats:
            continue
        formats[extension]["entry_count"] = int(formats[extension]["entry_count"]) + 1
        packages_by_extension[extension].add(entry.pamt_path.parent.name)
        if len(examples_by_extension[extension]) < 4:
            examples_by_extension[extension].append(entry.path)
    for extension, row in formats.items():
        row["packages"] = sorted(packages_by_extension[extension])
        row["examples"] = tuple(examples_by_extension[extension])
    return {
        "schema": "cdmw_mesh_editor_advanced_authoring_corpus_v1",
        "formats": formats,
        "sample_families": tuple(_mesh_editor_sample_family_rows(entries_by_path)),
    }

def _mesh_editor_sample_family_rows(
    entries_by_path: Mapping[str, Sequence[ArchiveEntry]],
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for name, path, linked_descriptor, linked_skeleton, linked_mesh, confidence in (
        (
            "ptm-skinned-mesh-rig",
            _REAL_ARCHIVE_RIGGING_SAMPLES[0],
            _REAL_ARCHIVE_SEQUENCE_PTM_DESCRIPTOR,
            _REAL_ARCHIVE_SEQUENCE_PTM_PAB,
            _REAL_ARCHIVE_RIGGING_SAMPLES[0],
            "proven",
        ),
        (
            "ptm-sequence-playback",
            _REAL_ARCHIVE_SEQUENCE_SAMPLE,
            "",
            _REAL_ARCHIVE_SEQUENCE_PTM_PAB,
            _REAL_ARCHIVE_RIGGING_SAMPLES[0],
            "inferred",
        ),
        (
            "ptm-paa-bound-clip",
            _REAL_ARCHIVE_SEQUENCE_PTM_PAA,
            "",
            _REAL_ARCHIVE_SEQUENCE_PTM_PAB,
            _REAL_ARCHIVE_RIGGING_SAMPLES[0],
            "proven",
        ),
        (
            "ptm-papr-constraint-metadata",
            _REAL_ARCHIVE_SEQUENCE_PTM_PAPR,
            _REAL_ARCHIVE_SEQUENCE_PTM_DESCRIPTOR,
            _REAL_ARCHIVE_SEQUENCE_PTM_PAB,
            _REAL_ARCHIVE_RIGGING_SAMPLES[0],
            "unknown",
        ),
    ):
        entry = _entry_by_archive_path(entries_by_path, path)
        if entry is None:
            continue
        rows.append(
            {
                "family": name,
                "path": entry.path,
                "format": entry.extension,
                "archive_package": entry.pamt_path.parent.name,
                "linked_descriptor": linked_descriptor,
                "linked_skeleton": linked_skeleton,
                "linked_mesh": linked_mesh,
                "confidence": confidence,
            }
        )
    return rows
