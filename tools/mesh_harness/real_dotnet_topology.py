"""Real-game proof for the exact PAC LOD0 topology rebuild.

Each of the three admitted operations gets its own resident session over the
same archive payload, and each is rebuilt into its own loose PAC. Running them
separately is deliberate: a chained proof would only show that the last
operation composed, while the contract has to hold for each of them on its own.
Loop Cut and Subdivide also derive vertices, so they are the only ones that
exercise the blended skin path at all.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace

from cdmw.domain.mesh import MeshEditCommand, MeshEditSelection
from cdmw.modding.mesh_pac_topology_builder import PacTopologyRebuildBlocked
from cdmw.domain.mesh.topology import (
    TOPOLOGY_OPERATION_DELETE_FACES,
    TOPOLOGY_OPERATION_LOOP_CUT,
    TOPOLOGY_OPERATION_SUBDIVIDE_MIDPOINT,
    validate_topology_provenance,
)
from tools.mesh_harness.real_dotnet_flow import record_flow_step


def _edit_command(action: str, part_index: int, *, first_edge: tuple[int, int] | None) -> MeshEditCommand:
    """The one command that performs `action` on the first face of `part_index`."""
    if action == "loop_cut":
        return MeshEditCommand(
            "loop_cut",
            selection=MeshEditSelection.from_maps(edges_by_submesh={part_index: (first_edge,)}),
            params={"_include_preview_deltas": False},
            mode="edit",
        )
    params: dict[str, object] = {"_include_preview_deltas": False}
    if action == "subdivide":
        params["max_faces_per_submesh"] = 4096
    return MeshEditCommand(
        action,
        selection=MeshEditSelection.from_maps(faces_by_submesh={part_index: (0,)}),
        params=params,
        mode="edit",
    )


def _admitted_operations() -> tuple[tuple[str, str, str], ...]:
    """(native action, contract operation name, output file stem)."""
    return (
        ("delete", TOPOLOGY_OPERATION_DELETE_FACES, "rebuilt_lod0"),
        ("loop_cut", TOPOLOGY_OPERATION_LOOP_CUT, "rebuilt_lod0_loop_cut"),
        ("subdivide", TOPOLOGY_OPERATION_SUBDIVIDE_MIDPOINT, "rebuilt_lod0_subdivide"),
    )


def _proven_part_index(mesh: object) -> int:
    return next(
        (
            index
            for index, submesh in enumerate(tuple(getattr(mesh, "submeshes", ()) or ()))
            if len(tuple(submesh.faces or ())) >= 4
            and int(getattr(submesh, "source_vertex_stride", 0) or 0) == 40
        ),
        -1,
    )


def _first_edge(mesh: object, part_index: int) -> tuple[int, int] | None:
    """An edge shared by two triangles, which is what Loop Cut needs to cut."""
    faces = tuple(getattr(mesh, "submeshes", ())[part_index].faces or ())
    seen: dict[tuple[int, int], int] = {}
    for face in faces:
        corners = tuple(int(value) for value in face[:3])
        for start, end in ((corners[0], corners[1]), (corners[1], corners[2]), (corners[2], corners[0])):
            key = (min(start, end), max(start, end))
            seen[key] = seen.get(key, 0) + 1
            if seen[key] > 1:
                return key
    return None


def _rebuild_evidence(
    *,
    state: SimpleNamespace,
    operation: str,
    original_mesh: object,
    edited_submesh: object,
    provenance: object,
    part_index: int,
    face_count_before: int,
    revision: int,
    report: object,
    topology_report: Mapping[str, object],
    output_path: Path,
    rebuilt_bytes: bytes,
    reparse_ok: bool,
    bounds_preserved: bool,
) -> dict[str, object]:
    return {
        "operation": operation,
        "model_path": state.model_entry.path,
        "part_index": part_index,
        "face_count_before": face_count_before,
        "face_count_after": len(tuple(edited_submesh.faces or ())),
        "vertex_count_after": len(tuple(edited_submesh.vertices or ())),
        "original_vertex_count": provenance.original_vertex_count,
        "original_face_count": provenance.original_face_count,
        "direct_vertex_count": provenance.direct_vertex_count,
        "blended_vertex_count": provenance.derived_vertex_count,
        "operations": [
            dict(entry) if isinstance(entry, Mapping) else entry
            for entry in tuple(getattr(report, "edit_operations", ()) or ())
        ],
        "rebuild_report": dict(topology_report),
        "output_path": str(output_path),
        "output_sha256": sha256(rebuilt_bytes).hexdigest(),
        "output_bytes": len(rebuilt_bytes),
        "source_payload_sha256": state.source_payload_sha256,
        "reparse_ok": reparse_ok,
        "bounds_preserved": bounds_preserved,
        "result_revision": revision,
        "original_bounds": [
            list(getattr(original_mesh, "submeshes")[part_index].source_bbox_min or ()),
            list(getattr(original_mesh, "submeshes")[part_index].source_bbox_extent or ()),
        ],
    }


def _blocked_evidence(
    state: SimpleNamespace,
    operation: str,
    part_index: int,
    face_count_before: int,
    edited_submesh: object,
    blocked: Exception,
    output_path: Path,
) -> dict[str, object]:
    """A refusal is evidence too, provided it names its reason and wrote nothing."""
    code = next(
        (part for part in str(blocked).replace(":", " ").split() if part.startswith("TOPOLOGY_")),
        "",
    )
    return {
        "operation": operation,
        "model_path": state.model_entry.path,
        "part_index": part_index,
        "rebuilt": False,
        "blocked": True,
        "blocker": code,
        "blocker_message": str(blocked),
        "wrote_no_output": not output_path.exists(),
        "face_count_before": face_count_before,
        "face_count_after": len(tuple(edited_submesh.faces or ())),
        "vertex_count_after": len(tuple(edited_submesh.vertices or ())),
        "source_payload_sha256": state.source_payload_sha256,
    }


def _prove_operation(
    state: SimpleNamespace,
    original_data: bytes,
    action: str,
    operation: str,
    output_stem: str,
) -> tuple[dict[str, object], str]:
    """Apply one admitted operation to a fresh session and rebuild it exactly."""
    from cdmw.domain.mesh.skeleton import summarize_mesh_skinning
    from cdmw.modding.mesh_parser import parse_pac
    from cdmw.services.mesh_service import MeshService

    mesh = parse_pac(original_data, state.model_entry.path)
    # The session needs the source bytes to rebuild into them at all; without
    # this the snapshot has nothing to write back over.
    setattr(mesh, "_cdmw_original_data", original_data)
    part_index = _proven_part_index(mesh)
    if part_index < 0:
        return {}, f"No proven 40-byte PAC part with enough faces for {operation}."
    face_count_before = len(tuple(mesh.submeshes[part_index].faces or ()))
    first_edge = _first_edge(mesh, part_index)
    if action == "loop_cut" and first_edge is None:
        return {}, "No interior edge on the proven PAC part to Loop Cut."

    service = MeshService()
    session_id = f"{state.controller.active_session_id}-{operation}"
    view = service.open_edit_session(mesh, session_id=session_id, mode="edit")
    try:
        service.apply_command(
            view.session_id,
            MeshEditCommand(
                "select",
                selection=MeshEditSelection.from_maps(faces_by_submesh={part_index: (0,)}),
                params={"operation": "replace"},
                mode="edit",
            ),
        )
        applied = service.apply_command(
            view.session_id, _edit_command(action, part_index, first_edge=first_edge)
        )
        if not applied.ok:
            return {}, f"Resident {action} was rejected on the real PAC part."

        edited = service.working_mesh(view.session_id, clone=True)
        submesh = edited.submeshes[part_index]
        provenance = getattr(submesh, "topology_provenance", None)
        output_faces = len(tuple(submesh.faces or ()))
        if output_faces < 1 or output_faces == face_count_before:
            return {}, f"Resident {action} changed no face count while retaining geometry."
        if provenance is None or validate_topology_provenance(
            provenance,
            output_vertex_count=len(tuple(submesh.vertices or ())),
            output_face_count=output_faces,
        ):
            return {}, f"Resident {action} produced no usable topology contract."

        output_path = Path(state.output_dir) / "topology_rebuild" / f"{output_stem}.pac"
        output_path.parent.mkdir(parents=True, exist_ok=True)
        # This session is opened straight from archive bytes, so it has no
        # skeleton link the way the visual flow's session does. The skinned-mesh
        # gate wants the bone count the skinning actually references, which the
        # mesh itself proves.
        skeleton_bone_count = int(summarize_mesh_skinning(mesh).inferred_bone_count or 0) or None
        try:
            report = service.rebuild_asset(
                view.session_id, output_path, skeleton_bone_count=skeleton_bone_count
            )
        except PacTopologyRebuildBlocked as blocked:
            # Refusing is the contract working, not failing. Stock geometry
            # rarely has parents that agree on every protected byte, which the
            # feasibility measurement put at 0.0072% of real LOD0 edges, so a
            # derived vertex on this asset is expected to be refused. What has
            # to hold is that the refusal is stable, named, and writes nothing.
            return (
                _blocked_evidence(state, operation, part_index, face_count_before, submesh, blocked, output_path),
                "",
            )
        topology_report = dict(getattr(report, "topology_rebuild", {}) or {})
        if topology_report.get("serializer") != "pac_lod0_topology_exact_v1":
            return {}, (
                f"{operation} did not use the exact topology serializer: "
                f"{topology_report.get('serializer')!r}."
            )
        if topology_report.get("fallback_used") is not False:
            return {}, f"{operation} reported a fallback."

        rebuilt_bytes = output_path.read_bytes()
        reparsed = parse_pac(rebuilt_bytes, str(output_path))
        reparsed_part = reparsed.submeshes[part_index] if part_index < len(reparsed.submeshes) else None
        if reparsed_part is None:
            return {}, f"{operation} lost the edited part on reparse."
        reparse_ok = bool(
            len(reparsed.submeshes) == len(edited.submeshes)
            and len(tuple(reparsed_part.vertices or ())) == len(tuple(submesh.vertices or ()))
            and len(tuple(reparsed_part.faces or ())) == output_faces
            and tuple(tuple(face) for face in reparsed_part.faces)
            == tuple(tuple(int(value) for value in face[:3]) for face in submesh.faces)
        )
        base_part = mesh.submeshes[part_index]
        bounds_preserved = bool(
            reparsed_part.source_bbox_min == base_part.source_bbox_min
            and reparsed_part.source_bbox_extent == base_part.source_bbox_extent
        )
        evidence = _rebuild_evidence(
            state=state,
            operation=operation,
            original_mesh=mesh,
            edited_submesh=submesh,
            provenance=provenance,
            part_index=part_index,
            face_count_before=face_count_before,
            revision=int(applied.revision),
            report=report,
            topology_report=topology_report,
            output_path=output_path,
            rebuilt_bytes=rebuilt_bytes,
            reparse_ok=reparse_ok,
            bounds_preserved=bounds_preserved,
        )
        if not (reparse_ok and bounds_preserved):
            return evidence, f"{operation} did not reparse into the authored LOD0 with the source bounds."
        return evidence, ""
    finally:
        service.close_edit_session(view.session_id)


def exercise_exact_topology_rebuild(state: SimpleNamespace, *, pump_until: Callable[..., bool]) -> str:
    """Rebuild each admitted operation exactly into the real PAC's own LOD0.

    These run on their own resident sessions over the same archive payload the
    visual flow used, not on the flow's session. By this point that session has
    a committed texture assignment and an Auto UV edit, which the export
    validator blocks for reasons that have nothing to do with topology; reusing
    it would test those blockers rather than this contract. The payload is read
    from the archive again, so the proof is still real game data and still
    read-only.
    """
    from tools.mesh_harness.real_common import _read_archive_payload

    original_data = _read_archive_payload(state.model_entry)
    if sha256(original_data).hexdigest() != state.source_payload_sha256:
        return "Real PAC payload changed between the visual flow and the rebuild proof."

    by_operation: dict[str, object] = {}
    for action, operation, output_stem in _admitted_operations():
        evidence, error = _prove_operation(state, original_data, action, operation, output_stem)
        if evidence:
            by_operation[operation] = evidence
        if error:
            state.topology_rebuild_evidence = {
                "source_payload_sha256": state.source_payload_sha256,
                "by_operation": by_operation,
                "failed_operation": operation,
                "failure": error,
            }
            return error

    attempted = tuple(by_operation)
    rebuilt = {name: row for name, row in by_operation.items() if not row.get("blocked")}
    refused = {name: row for name, row in by_operation.items() if row.get("blocked")}
    blended = sum(int(row.get("blended_vertex_count") or 0) for row in rebuilt.values())
    state.topology_rebuild_evidence = {
        "model_path": state.model_entry.path,
        "source_payload_sha256": state.source_payload_sha256,
        "operations_attempted": list(attempted),
        "operations_rebuilt": list(rebuilt),
        "operations_refused": list(refused),
        "refusal_blockers": {name: row.get("blocker") for name, row in refused.items()},
        "blended_vertex_count_total": blended,
        # This asset's parents disagree on protected bytes, so a derived vertex
        # is refused rather than approximated. The blended skin path therefore
        # has synthetic coverage only; saying so here keeps the evidence from
        # implying real-game proof it does not hold.
        "blended_skin_path_proven": blended > 0,
        # Every admitted operation avoided the generic path, not just one. A
        # refusal counts: it wrote nothing at all, generic or otherwise.
        "all_operations_avoided_fallback": all(
            row.get("blocked")
            or dict(row.get("rebuild_report") or {}).get("fallback_used") is False
            for row in by_operation.values()
        ),
        "all_rebuilds_reparsed": all(bool(row.get("reparse_ok")) for row in rebuilt.values()),
        "all_rebuilds_preserved_bounds": all(
            bool(row.get("bounds_preserved")) for row in rebuilt.values()
        ),
        # A refusal that left a file behind would be worse than a bad rebuild.
        "all_refusals_named_and_wrote_nothing": all(
            str(row.get("blocker") or "").startswith("TOPOLOGY_") and bool(row.get("wrote_no_output"))
            for row in refused.values()
        ),
        "by_operation": by_operation,
    }
    if not rebuilt:
        state.topology_rebuild_ok = False
        return "No admitted operation rebuilt at all, so nothing proves the exact writer."
    state.topology_rebuild_ok = bool(
        len(attempted) == len(_admitted_operations())
        and state.topology_rebuild_evidence["all_rebuilds_reparsed"]
        and state.topology_rebuild_evidence["all_rebuilds_preserved_bounds"]
        and state.topology_rebuild_evidence["all_refusals_named_and_wrote_nothing"]
        and state.topology_rebuild_evidence["all_operations_avoided_fallback"]
    )
    if not state.topology_rebuild_ok:
        return "An admitted operation neither rebuilt exactly nor refused cleanly."
    record_flow_step(
        state,
        "topology_rebuild",
        rebuilt=list(rebuilt),
        refused=list(refused),
        blended_vertices=blended,
    )
    return ""


__all__ = ["exercise_exact_topology_rebuild"]
