"""Admit the most source files within the existing authoring package limits."""
from __future__ import annotations

import copy
from contextlib import ExitStack
import os
from pathlib import Path
import tempfile
import threading
from typing import NamedTuple


_BUDGET_NEUTRAL_MESHES = threading.local()


def pop_budget_neutral_meshes(sources_id: int) -> dict[int, object]:
    stored = getattr(_BUDGET_NEUTRAL_MESHES, "by_sources_id", None)
    if isinstance(stored, dict):
        return stored.pop(sources_id, {})
    return {}


def _remember_budget_neutral_meshes(sources_id: int, meshes: dict[int, object]) -> None:
    stored = getattr(_BUDGET_NEUTRAL_MESHES, "by_sources_id", None)
    if not isinstance(stored, dict):
        stored = {}
        _BUDGET_NEUTRAL_MESHES.by_sources_id = stored
    stored.clear()
    stored[sources_id] = meshes


class ItemSetBudget(NamedTuple):
    """What the session budget admitted.

    ``references`` maps each file turned into a reduced-detail reference, by identity,
    to its reduced mesh. ``reason`` names the limit the whole set passed, so the files
    and why can be said before the session opens (P5): "geometry", "textures", "size",
    or "" when every file fits.
    """

    admitted: frozenset
    references: dict
    materials: object
    reason: str = ""


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


def _conservative_mesh_upper_bounds(mesh) -> tuple[int, int]:
    """Conservative upper bounds for binary document.bin and compact channels.json."""
    verts = 0
    faces = 0
    submeshes = tuple(getattr(mesh, "submeshes", ()) or ())
    for part in submeshes:
        verts += len(tuple(getattr(part, "vertices", ()) or ()))
        faces += len(tuple(getattr(part, "faces", ()) or ()))
    # document.bin: positions (24B) + normals (24B) + uvs (16B) + shader_masks (32B)
    # + source_vertex_indices (4B) = 100B/vert, indices = 12B/tri, plus headers.
    geom_upper = verts * 128 + faces * 16 + len(submeshes) * 2048 + 8192
    # channels.json: tangents/uv1/weights/maps in compact JSON.
    chan_upper = verts * 384 + faces * 64 + len(submeshes) * 4096 + 16384
    return geom_upper, chan_upper


def _collect_native_piece_textures(mesh, offset: int, files: dict, bindings: dict, unique_dds: dict) -> bool:
    """Collect direct DDS bindings + stat unique DDS sizes (base + native layers)."""
    from cdmw.services import mesh_rust_authoring as a
    from cdmw.services.mesh_preview_material_source import unedited_preview_core_material_source
    from cdmw.services.mesh_rust_preview_package import (
        _collect_preview_core_layer_sources,
        _preview_core_layer_parameter_index,
    )
    from cdmw.services.shader_controls_preview import authored_veil_layer_textures

    def record_dds(path: Path) -> bool:
        try:
            st = path.stat()
        except OSError:
            return False
        if st.st_size <= 0 or st.st_size > a._TEXTURE_MAX_FILE_BYTES:
            return False
        ino = int(getattr(st, "st_ino", 0) or 0)
        key = (int(st.st_dev), ino) if ino else str(path).casefold()
        unique_dds.setdefault(key, (path, int(st.st_size)))
        return True

    param_indices: dict[int, dict] = {}
    for submesh_index, submesh in enumerate(tuple(getattr(mesh, "submeshes", ()) or ())):
        resolved_roles: set[str] = set()
        veil_height, veil_detail = authored_veil_layer_textures(submesh)
        veil_paths = {
            role: path
            for role, item in (("height", veil_height), ("shader_mask", veil_detail))
            if item is not None and (path := a._material_input_dds_path(item)) is not None
        }
        if "shader_mask" in veil_paths and not any(
            a._material_input_texture_role(item) == "shader_mask"
            for item in getattr(submesh, "preview_material_texture_inputs", ()) or ()
        ):
            path = veil_paths["shader_mask"]
            if not record_dds(path):
                return False
            path_text = str(path)
            files[path_text] = path
            bindings.setdefault((path_text, "shader_mask"), [set()])[0].add(submesh_index + offset)
            resolved_roles.add("shader_mask")
        for role, attributes in a._TEXTURE_RESOURCE_SPECS:
            path = veil_paths["height"] if (role == "height" and "shader_mask" in veil_paths and "height" in veil_paths) else None
            if path is None:
                path = a._first_texture_resource_dds_path(submesh, role, attributes)
            if path is None:
                continue
            if not record_dds(path):
                return False
            path_text = str(path)
            files[path_text] = path
            bindings.setdefault((path_text, role), [set()])[0].add(submesh_index + offset)
            resolved_roles.add(role)
        for item in tuple(getattr(submesh, "preview_material_texture_inputs", ()) or ()):
            role = a._material_input_texture_role(item)
            if not role or role in resolved_roles:
                continue
            if not a._material_input_is_renderer_role_eligible(submesh, item, role):
                continue
            path = a._material_input_dds_path(item)
            if path is None:
                continue
            if not record_dds(path):
                return False
            path_text = str(path)
            files[path_text] = path
            bindings.setdefault((path_text, role), [set()])[0].add(submesh_index + offset)
            resolved_roles.add(role)
        source = unedited_preview_core_material_source(submesh)
        if source is not None:
            conservation = source["conservation"]
            cid = id(conservation)
            pindex = param_indices.get(cid)
            if pindex is None:
                pindex = _preview_core_layer_parameter_index(conservation.get("parameters", ()))
                param_indices[cid] = pindex
            for layer_path in _collect_preview_core_layer_sources(
                [source["batch"]], Path(source["package"]), pindex,
            ):
                if not record_dds(layer_path):
                    return False
    return True


def _try_fast_native_budget(sources, neutral_meshes, root, root_identity, payload_limit, session_limit, stop_event):
    """Avoid throwaway encode/channels/staging/material-graph when all pieces provably fit."""
    from cdmw.services import mesh_rust_authoring as a, mesh_rust_preview_package as preview

    graph_fn = getattr(preview, "_composite_preview_core_material_graph", None)
    if getattr(graph_fn, "__module__", "") != "cdmw.services.mesh_rust_preview_package":
        return None
    if any(a._mesh_has_material_synthesis_inputs(mesh) for mesh in neutral_meshes):
        return None
    upper_geom = 0
    upper_chan = 0
    bindings: dict[tuple[str, str], list[set[int]]] = {}
    files: dict[str, Path] = {}
    unique_dds: dict[object, tuple[Path, int]] = {}
    offset = 0
    for mesh in neutral_meshes:
        a._raise_if_texture_copy_cancelled(stop_event)
        g, c = _conservative_mesh_upper_bounds(mesh)
        upper_geom += g
        upper_chan += c
        if not _collect_native_piece_textures(mesh, offset, files, bindings, unique_dds):
            return None
        offset += len(mesh.submeshes)
    total_dds = sum(size for _path, size in unique_dds.values())
    if upper_geom > payload_limit or total_dds > payload_limit or (upper_geom + upper_chan + total_dds) > session_limit:
        return None
    # Deduplicate files that share an inode across paths (e.g. different string forms).
    canonical_by_ino: dict[tuple[int, int], str] = {}
    dedup_files: dict[str, Path] = {}
    dedup_bindings: dict[tuple[str, str], list[set[int]]] = {}
    for (path_text, role), ownership in bindings.items():
        path = files[path_text]
        try:
            st = path.stat()
            ino = int(getattr(st, "st_ino", 0) or 0)
            key = (int(st.st_dev), ino) if ino else None
        except OSError:
            key = None
        if key is not None:
            canonical = canonical_by_ino.setdefault(key, path_text)
        else:
            canonical = path_text
        dedup_files[canonical] = files[canonical]
        dedup_bindings.setdefault((canonical, role), [set()])[0].update(ownership[0])
    textures = a._publish_rust_texture_resources(root, dedup_bindings, dedup_files, stop_event, root_identity)
    presentations = []
    offset = 0
    for mesh in neutral_meshes:
        for presentation in a._mesh_material_presentations(mesh):
            presentation = copy.deepcopy(presentation)
            presentation["material_index"] += offset
            presentations.append(presentation)
        offset += len(mesh.submeshes)
    synthesis = a._RustMaterialSynthesisState()
    return ItemSetBudget(frozenset(range(len(sources))), {}, (textures, presentations, synthesis), "")


def prepare_item_set_budget(sources, root, root_identity, stop_event):
    """Stage once, count actual payloads, publish only admitted material files."""
    from cdmw.services import mesh_rust_authoring as a
    from cdmw.services.mesh_rust_preview_package import _composite_preview_core_material_graph
    from cdmw.services.mesh_preview_material_source import (
        restore_preview_core_sources, set_aside_preview_core_sources,
    )

    root = Path(root).resolve()
    payload_limit = a.RUST_MESH_MAX_PAYLOAD_BYTES
    # The final manifest has its own 16 MiB bound. Existing copied profiles are
    # counted, and each compact channel document is measured before admission.
    existing_bytes = a._validate_owned_session_tree(root, root_identity)[1]
    session_limit = a._SESSION_MAX_TOTAL_BYTES - existing_bytes - a._RUST_PREVIEW_PACKAGE_MANIFEST_MAX_BYTES
    neutral_meshes = []
    for _entry, snapshot, appearance, _lease, *_dependencies in sources:
        a._raise_if_texture_copy_cancelled(stop_event)
        mesh = _lod0(snapshot.mesh)
        if appearance is not None:
            set_aside = set_aside_preview_core_sources(mesh)
            try:
                neutral = appearance.to_neutral(mesh)
            finally:
                originals = list(mesh.submeshes)
                copies = list(neutral.submeshes) if "neutral" in locals() else []
                onto = ({id(original): copy_ for original, copy_ in zip(originals, copies)}
                        if len(originals) == len(copies) else None)
                restore_preview_core_sources(set_aside, onto=onto)
            mesh = neutral
        neutral_meshes.append(mesh)
    _remember_budget_neutral_meshes(id(sources), dict(enumerate(neutral_meshes)))

    fast = _try_fast_native_budget(
        sources, neutral_meshes, root, root_identity, payload_limit, session_limit, stop_event,
    )
    if fast is not None:
        return fast

    rows = []
    with ExitStack() as stack:
        for (entry, _snapshot, _appearance, _lease, *_dependencies), mesh in zip(sources, neutral_meshes):
            a._raise_if_texture_copy_cancelled(stop_event)
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
        reason = ""
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
            if sum(row["geometry"] for row in rows) > payload_limit:
                reason = "geometry"
            elif sum(row["texture_bytes"] for row in rows) > payload_limit:
                reason = "textures"
            else:
                reason = "size"
        bindings, files, presentations = {}, {}, []
        sha_to_path: dict[str, str] = {}
        synthesis = a._RustMaterialSynthesisState()
        offset = 0
        for index, row in enumerate(rows):
            if index not in admitted:
                continue
            for texture in row["textures"]:
                path = row["staging"] / texture["file"]["path"]
                sha = str(texture["file"].get("sha256", "") or "").upper()
                if sha:
                    canonical = sha_to_path.setdefault(sha, str(path))
                else:
                    canonical = str(path)
                files.setdefault(canonical, path)
                key = (canonical, texture["role"])
                bindings.setdefault(key, [set()])[0].update(part + offset for part in texture["material_indices_by_lod"][0])
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
        return ItemSetBudget(frozenset(admitted), references, (textures, presentations, synthesis), reason)
