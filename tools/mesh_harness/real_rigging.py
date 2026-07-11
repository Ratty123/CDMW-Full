from __future__ import annotations

from cdmw.models import ArchiveEntry
from collections.abc import Mapping
from cdmw.services.mesh_service import MeshService
from cdmw.modding.mesh_parser import ParsedMesh
from pathlib import Path
from collections.abc import Sequence
from cdmw.core.archive_format import parse_archive_pamt
from cdmw.modding.mesh_parser import parse_mesh
from cdmw.modding.skeleton_parser import parse_pab
from cdmw.core.skeleton_resolver import resolve_skeleton_for_model

from tools.mesh_harness.constants import (
    _REAL_ARCHIVE_RIGGING_SAMPLES,
)

from tools.mesh_harness.evidence import (
    _mesh_editor_advanced_authoring_corpus_manifest,
)

from tools.mesh_harness.papr import (
    _papr_constraint_evidence_for_path,
)

from tools.mesh_harness.real_common import (
    _archive_entry_indexes,
    _archive_key,
    _read_archive_payload,
)

from tools.mesh_harness.service_summary import (
    _mesh_vertices_changed,
    _tuple_row,
)

def run_real_archive_rigging_smoke(game_root: Path) -> dict[str, object]:
    pamt_path = game_root / "0009" / "0.pamt"
    if not pamt_path.is_file():
        return {
            "ok": False,
            "read_only": True,
            "skipped": f"missing PAMT: {pamt_path}",
            "game_root": str(game_root),
            "pamt_path": str(pamt_path),
        }

    entries = parse_archive_pamt(pamt_path)
    entries_by_path, entries_by_basename = _archive_entry_indexes(entries)
    samples = [
        _run_real_archive_rigging_sample(model_path, entries, entries_by_path, entries_by_basename)
        for model_path in _REAL_ARCHIVE_RIGGING_SAMPLES
    ]
    return {
        "ok": bool(samples) and all(bool(sample.get("ok")) for sample in samples),
        "read_only": True,
        "game_root": str(game_root),
        "pamt_path": str(pamt_path),
        "sample_count": len(samples),
        "corpus_manifest": _mesh_editor_advanced_authoring_corpus_manifest(entries, entries_by_path),
        "samples": samples,
    }

def _run_real_archive_rigging_sample(
    model_path: str,
    entries: Sequence[ArchiveEntry],
    entries_by_path: Mapping[str, Sequence[ArchiveEntry]],
    entries_by_basename: Mapping[str, Sequence[ArchiveEntry]],
) -> dict[str, object]:
    model_entry = next(iter(entries_by_path.get(_archive_key(model_path), ())), None)
    if model_entry is None:
        return {"ok": False, "model_path": model_path, "error": "model entry not found"}

    try:
        pac_data = _read_archive_payload(model_entry)
        mesh = parse_mesh(pac_data, model_entry.path)
        skeleton_entry, report = resolve_skeleton_for_model(
            model_entry,
            entries,
            archive_entries_by_normalized_path=entries_by_path,
            archive_entries_by_basename=entries_by_basename,
            pac_data=pac_data,
            read_entry_data=_read_archive_payload,
        )
        if skeleton_entry is None:
            return {
                "ok": False,
                "model_path": model_entry.path,
                "confidence": report.confidence,
                "descriptor_path": report.descriptor_path,
                "error": "skeleton entry not resolved",
            }
        skeleton = parse_pab(_read_archive_payload(skeleton_entry), skeleton_entry.path)
        constraint_evidence = _papr_constraint_evidence_for_path(
            entries_by_path,
            entries_by_basename,
            report.animation_constraint_path,
        )

        service = MeshService()
        view = service.open_edit_session(mesh, mode="object")
        summary = service.attach_skeleton(
            view.session_id,
            skeleton,
            source_path=skeleton_entry.path,
            skeleton_descriptor_source=report.descriptor_path,
            skeleton_variation_source=report.skeleton_variation_path,
            animation_constraint_source=report.animation_constraint_path,
            animation_constraint_evidence=constraint_evidence,
            socket_source=report.socket_path,
        )
        selected_bone, pose_changed = _prove_pose_deformation(service, view.session_id, len(getattr(skeleton, "bones", ()) or ()))
        summary = service.skeleton_summary(view.session_id)
        return {
            "ok": bool(pose_changed and report.confidence == "descriptor"),
            "model_path": model_entry.path,
            "skeleton_path": skeleton_entry.path,
            "confidence": report.confidence,
            "descriptor_path": report.descriptor_path,
            "skeleton_variation_path": report.skeleton_variation_path,
            "animation_constraint_path": report.animation_constraint_path,
            "socket_path": report.socket_path,
            "bone_count": int(getattr(skeleton, "bone_count", 0) or len(getattr(skeleton, "bones", ()) or ())),
            "submesh_count": len(getattr(mesh, "submeshes", ()) or ()),
            "vertex_count": int(getattr(mesh, "total_vertices", 0) or 0),
            "weighted_vertex_count": summary.weighted_vertex_count,
            "selected_bone_index": selected_bone,
            "pose_changed": pose_changed,
            "animation_status": summary.animation_status,
            "animation_playback_ready": summary.animation_playback_ready,
            "animation_blockers": list(summary.animation_blockers),
            "constraint_evidence_status": summary.animation_constraint_evidence.status,
            "constraint_string_evidence": summary.animation_constraint_evidence.string_evidence_count,
            "constraint_record_candidates": summary.animation_constraint_evidence.record_candidate_count,
            "constraint_related_physics": summary.animation_constraint_evidence.related_physics_count,
        }
    except Exception as exc:
        return {"ok": False, "model_path": model_entry.path, "error": f"{type(exc).__name__}: {exc}"}

def _prove_pose_deformation(service: MeshService, session_id: str, bone_count: int) -> tuple[int, bool]:
    for bone_index in _weighted_bone_candidates(service.working_mesh(session_id), bone_count):
        service.reset_pose(session_id)
        service.set_pose_preview(session_id, True)
        service.select_bone(session_id, bone_index)
        service.rotate_selected_bone(session_id, (0.0, 20.0, 0.0))
        if _mesh_vertices_changed(service.working_mesh(session_id), service.pose_preview_mesh(session_id)):
            return bone_index, True
    return -1, False

def _weighted_bone_candidates(mesh: ParsedMesh, bone_count: int) -> tuple[int, ...]:
    result: list[int] = []
    seen: set[int] = set()
    for submesh in tuple(getattr(mesh, "submeshes", ()) or ()):
        for index_row, weight_row in zip(getattr(submesh, "bone_indices", ()) or (), getattr(submesh, "bone_weights", ()) or ()):
            for raw_index, raw_weight in zip(_tuple_row(index_row), _tuple_row(weight_row)):
                try:
                    bone_index = int(raw_index)
                    weight = float(raw_weight)
                except (TypeError, ValueError, OverflowError):
                    continue
                if 0 <= bone_index < bone_count and weight > 1e-6 and bone_index not in seen:
                    seen.add(bone_index)
                    result.append(bone_index)
                    if len(result) >= 32:
                        return tuple(result)
    return tuple(result)
