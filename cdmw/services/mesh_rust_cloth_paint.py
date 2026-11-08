"""Cloth paint for the Rust Mesh Editor: overlay state and the explicit-selection command.

Paint is for models imported in Create New Item. Original game models already carry
their own cloth bindings, edited on the Cloth page's Cloth amount controls instead.
"""

from __future__ import annotations

from collections.abc import Mapping

CLOTH_PAINT_ARGUMENTS = frozenset({"selection", "value"})


def cloth_paint_state(session, cache=None) -> dict[str, object]:
    """Painted rows only, cached per session revision."""
    if str(getattr(session, "mesh_format", "") or "").casefold() == "pac":
        return {"supported": False,
                "reason": "Cloth paint is for models imported in Create New Item. "
                          "Game models keep their own cloth; use Cloth amount below."}
    mesh = session.working_mesh
    key = (id(session), int(getattr(session, "revision", 0) or 0), id(mesh))
    cached = getattr(cache, "cloth_paint", None)
    if cached is not None and cached[0] == key:
        return cached[1]
    parts, painted = [], 0
    for index, part in enumerate(getattr(mesh, "submeshes", ()) or ()):
        values = list(getattr(part, "cloth_paint", ()) or ())
        if len(values) != len(getattr(part, "vertices", ()) or ()):
            continue
        rounded = ((vertex, round(min(1.0, float(value)), 4)) for vertex, value in enumerate(values))
        rows = [[vertex, value] for vertex, value in rounded if value > 0.0]
        if rows:
            parts.append({"submesh_index": index, "values": rows})
            painted += len(rows)
    state = {"supported": True, "painted_vertex_count": painted, "parts": parts,
             "reason": "" if painted else "Nothing is painted yet."}
    if cache is not None:
        cache.cloth_paint = key, state
    return state


def run_cloth_paint_command(authoring, args: Mapping[str, object]) -> dict[str, object]:
    """Set the explicitly selected vertices' paint; the selection travels with the command."""
    from cdmw.services.mesh_rust_authoring import RustMeshValidationError

    selection = authoring._apply_explicit_rig_selection(
        args, allowed=CLOTH_PAINT_ARGUMENTS, command="cloth_paint_set")
    session = authoring.shadow_service._session(authoring.shadow_session_id)
    if str(getattr(session, "mesh_format", "") or "").casefold() == "pac":
        raise RustMeshValidationError("Cloth paint is for models imported in Create New Item.")
    # Whole Parts picked in the Parts list arrive as source indices: paint all their vertices.
    from cdmw.domain.mesh.editing import MeshEditSelection
    vertices = {index: set(rows) for index, rows in selection.vertex_map().items()}
    submeshes = session.working_mesh.submeshes
    for index in selection.source_indices:
        if 0 <= int(index) < len(submeshes):
            vertices.setdefault(int(index), set()).update(range(len(submeshes[int(index)].vertices)))
    if not any(vertices.values()):
        raise RustMeshValidationError("Select one or more vertices before painting cloth.")
    previous = session.selection
    session.selection = MeshEditSelection.from_maps(
        vertices_by_submesh={index: tuple(sorted(rows)) for index, rows in vertices.items() if rows})
    try:
        changed = authoring.shadow_service.set_selected_vertex_cloth_paint(
            authoring.shadow_session_id, args.get("value"))
    except ValueError as exc:
        session.selection = previous
        raise RustMeshValidationError(str(exc)) from exc
    except Exception:
        session.selection = previous
        raise
    return {"changed_vertex_count": changed}
