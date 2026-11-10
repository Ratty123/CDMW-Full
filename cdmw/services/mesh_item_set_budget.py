"""Admit the most source files within the existing authoring package limits."""
from __future__ import annotations

import copy
from contextlib import ExitStack
from pathlib import Path
import tempfile


def largest_fitting_subset(costs, limits, stop_event=None):
    """Maximum file count under geometry, texture and total byte limits.

    At most 32 optional files. Cheapest-first search supplies an early bound;
    each remaining resource independently bounds how many more can fit.
    """
    order = sorted(range(len(costs)), key=lambda i: sum(costs[i][n] / max(1, limits[n]) for n in range(3)))
    best = ()

    def visit(position, remaining, chosen):
        nonlocal best
        if stop_event is not None and stop_event.is_set():
            from cdmw.domain.cancellation import raise_if_cancelled
            raise_if_cancelled(stop_event, "Item set loading cancelled")
        if len(chosen) > len(best):
            best = chosen
        available = order[position:]
        upper = len(available)
        for dimension in range(3):
            used = count = 0
            for cost in sorted(costs[i][dimension] for i in available):
                if used + cost > remaining[dimension]:
                    break
                used += cost
                count += 1
            upper = min(upper, count)
        if len(chosen) + upper <= len(best):
            return
        index = order[position]
        if all(cost <= limit for cost, limit in zip(costs[index], remaining)):
            visit(position + 1, tuple(limit - cost for limit, cost in zip(remaining, costs[index])), (*chosen, index))
        visit(position + 1, remaining, chosen)

    if all(limit >= 0 for limit in limits):
        visit(0, tuple(limits), ())
    return frozenset(best)


def _lod0(mesh):
    result = copy.copy(mesh)
    result.submeshes = list(mesh.submeshes)
    result.lod_levels = []
    result.active_lod_index = 0
    return result


def _reference_mesh(mesh):
    from cdmw.services.mesh_archive_refit import _clone
    from cdmw.modding.mesh_native_submesh_geometry import decimate_native_mesh_preview_submeshes
    from cdmw.modding.mesh_edit_ops import refresh_mesh_totals

    result = _clone(_lod0(mesh))
    limit = max(1, 4096 // max(1, len(result.submeshes)))
    if any(len(part.faces) > limit for part in result.submeshes):
        if decimate_native_mesh_preview_submeshes(result.submeshes, limit) is None:
            raise ValueError("Cannot prepare a bounded item-set reference mesh")
    refresh_mesh_totals(result)
    return result


def prepare_item_set_budget(sources, root, root_identity, stop_event):
    """Stage once, count actual payloads, publish only admitted material files."""
    from cdmw.services import mesh_rust_authoring as a
    from cdmw.services.mesh_rust_preview_package import _composite_preview_core_material_graph

    root = Path(root).resolve()
    payload_limit = a.RUST_MESH_MAX_PAYLOAD_BYTES
    # The final manifest has its own 16 MiB bound. Existing copied profiles are
    # counted, and each compact channel document is measured before admission.
    existing_bytes = a._validate_owned_session_tree(root, root_identity)[1]
    session_limit = a._SESSION_MAX_TOTAL_BYTES - existing_bytes - a._RUST_PREVIEW_PACKAGE_MANIFEST_MAX_BYTES
    rows = []
    with ExitStack() as stack:
        for entry, snapshot, appearance, _lease, *_dependencies in sources:
            a._raise_if_texture_copy_cancelled(stop_event)
            mesh = _lod0(snapshot.mesh)
            if appearance is not None:
                mesh = appearance.to_neutral(mesh)
            staging = Path(stack.enter_context(tempfile.TemporaryDirectory(prefix="item-set-materials-", dir=root.parent))).resolve()
            if staging.parent != root.parent:
                raise ValueError("Item set material staging escaped its owning directory")
            state = a._RustMaterialSynthesisState()
            geometry = len(a.encode_mesh_document(a._mesh_document_arrays(mesh), max_payload_bytes=2**63 - 1))
            channels = len(a._canonical_json_bytes(a._mesh_channel_payload(mesh, geometry_path="document.bin")))
            try:
                textures = a._mesh_texture_payloads(staging, mesh, expected_root_identity=a._session_root_identity(staging),
                                                    stop_event=stop_event, synthesis_state=state)
                texture_bytes = sum({row["file"]["path"]: row["file"]["byte_length"] for row in textures}.values())
                graph = _composite_preview_core_material_graph(
                    staging, mesh, textures, a._mesh_material_presentations(mesh), "full", a._session_root_identity(staging),
                    lambda: stop_event is not None and stop_event.is_set())
                if graph is not None:
                    # Count the owned files, including identical DDS content
                    # published under different bindings, against session limits.
                    texture_bytes = a._validate_owned_session_tree(staging, a._session_root_identity(staging))[1]
            except (a.RustMeshProtocolError, ValueError) as exc:
                if not any(message in str(exc) for message in ("512 MiB file limit", "768 MiB aggregate limit", "512 MiB package limit")):
                    raise
                texture_bytes, textures = payload_limit + 1, []
            rows.append(dict(entry=entry, mesh=mesh, staging=staging, state=state, textures=textures,
                             geometry=geometry, texture_bytes=texture_bytes, total=geometry + channels + texture_bytes))
        first = rows[0]
        if first["geometry"] > payload_limit or first["texture_bytes"] > payload_limit or first["total"] > session_limit:
            raise ValueError(f"Selected source file exceeds the Mesh Editor session limits: {first['entry'].basename}")
        all_fit = (sum(row["geometry"] for row in rows) <= payload_limit
                   and sum(row["texture_bytes"] for row in rows) <= payload_limit
                   and sum(row["total"] for row in rows) <= session_limit)
        references = {}
        if all_fit:
            admitted = frozenset(range(len(rows)))
        else:
            reference_bytes = []
            for row in rows[1:]:
                reduced = _reference_mesh(row["mesh"])
                size = len(a.encode_mesh_document(a._mesh_document_arrays(reduced), max_payload_bytes=payload_limit))
                references[row["entry"].identity] = reduced
                reference_bytes.append(size)
            costs = [(row["geometry"], row["texture_bytes"], row["total"] - size)
                     for row, size in zip(rows[1:], reference_bytes)]
            limits = (payload_limit - first["geometry"], payload_limit - first["texture_bytes"],
                      session_limit - first["total"] - sum(reference_bytes))
            if min(limits) < 0:
                raise ValueError("The selected source and its bounded references exceed the Mesh Editor session limits")
            admitted = {0, *(index + 1 for index in largest_fitting_subset(costs, limits, stop_event))}
            references = {row["entry"].identity: references[row["entry"].identity]
                          for index, row in enumerate(rows) if index not in admitted}
        bindings, files, presentations = {}, {}, []
        synthesis = a._RustMaterialSynthesisState()
        offset = 0
        for index, row in enumerate(rows):
            if index not in admitted:
                continue
            for texture in row["textures"]:
                path = row["staging"] / texture["file"]["path"]
                key = (str(path), texture["role"])
                files[str(path)] = path
                bindings[key] = [{part + offset for part in texture["material_indices_by_lod"][0]}]
            state = row["state"]
            for presentation in a._mesh_material_presentations(row["mesh"], generated_overrides=state.presentation_overrides):
                presentation = copy.deepcopy(presentation)
                presentation["material_index"] += offset
                presentations.append(presentation)
            synthesis.attempted |= state.attempted
            synthesis.generated_binding_count += state.generated_binding_count
            synthesis.budget_skipped.update((0, part + offset) for lod, part in state.budget_skipped if lod == 0)
            synthesis.diagnostics.extend(state.diagnostics)
            synthesis.dropped_diagnostic_count += state.dropped_diagnostic_count
            synthesis.luminance_guard_count += state.luminance_guard_count
            synthesis.luminance_guard_adjustments.extend(state.luminance_guard_adjustments)
            synthesis.dropped_luminance_guard_count += state.dropped_luminance_guard_count
            offset += len(row["mesh"].submeshes)
        textures = a._publish_rust_texture_resources(root, bindings, files, stop_event, root_identity)
        return frozenset(admitted), references, (textures, presentations, synthesis)
