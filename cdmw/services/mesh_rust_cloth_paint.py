"""Cloth paint and cloth pins for the Rust Mesh Editor: overlay state and selection commands.

Paint is for models imported in Create New Item. Original game models already carry
their own cloth bindings, edited on the Cloth page's Cloth amount controls instead.
"""

from __future__ import annotations

from collections.abc import Mapping

CLOTH_PAINT_ARGUMENTS = frozenset({"selection", "value", "whole_model"})


def _pin_rows(mesh):
    parts, pinned = [], 0
    for index, part in enumerate(getattr(mesh, "submeshes", ()) or ()):
        pins = list(getattr(part, "cloth_pin", ()) or ())
        if len(pins) != len(getattr(part, "vertices", ()) or ()):
            continue
        rows = [vertex for vertex, pin in enumerate(pins) if pin]
        if rows:
            parts.append({"submesh_index": index, "vertices": rows})
            pinned += len(rows)
    return parts, pinned


def cloth_paint_state(session, cache=None) -> dict[str, object]:
    """Painted rows and pinned vertices, cached per session revision.

    Game models paint pins only: they hold the guides Create cloth guides builds.
    """
    mesh = getattr(session, "working_mesh", None)
    key = (id(session), int(getattr(session, "revision", 0) or 0), id(mesh))
    cached = getattr(cache, "cloth_paint", None)
    if cached is not None and cached[0] == key:
        return cached[1]
    pin_parts, pinned = _pin_rows(mesh)
    if str(getattr(session, "mesh_format", "") or "").casefold() == "pac":
        state = {"supported": False, "pins_supported": True, "pinned_vertex_count": pinned, "pin_parts": pin_parts,
                 "reason": "Cloth paint is for models imported in Create New Item. "
                           "Game models keep their own cloth; use Cloth amount below."}
        if cache is not None:
            cache.cloth_paint = key, state
        return state
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
    state = {"supported": True, "pins_supported": True, "painted_vertex_count": painted, "parts": parts,
             "pinned_vertex_count": pinned, "pin_parts": pin_parts,
             "reason": "" if painted else "Nothing is painted yet."}
    if cache is not None:
        cache.cloth_paint = key, state
    return state


def run_cloth_paint_command(authoring, args: Mapping[str, object]) -> dict[str, object]:
    """Set the explicitly selected vertices' paint; the selection travels with the command.

    ``whole_model`` paints every vertex of every part instead, for a garment that
    should move as cloth all over (or, with 0, to clear the paint everywhere).
    """
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
    whole_model = args.get("whole_model", False)
    if not isinstance(whole_model, bool):
        raise RustMeshValidationError("cloth_paint_set whole_model must be true or false.")
    if whole_model:
        vertices = {index: set(range(len(part.vertices))) for index, part in enumerate(submeshes)}
    for index in () if whole_model else selection.source_indices:
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


CLOTH_PIN_ARGUMENTS = frozenset({"selection", "value", "whole_model"})


def run_cloth_pin_command(authoring, args: Mapping[str, object]) -> dict[str, object]:
    """Pin or unpin the explicitly selected vertices (or, with whole_model, clear every pin)."""
    from cdmw.services.mesh_rust_authoring import RustMeshValidationError
    from cdmw.domain.mesh.editing import MeshEditSelection

    pinned = args.get("value")
    if type(pinned) is not bool:
        raise RustMeshValidationError("cloth_pin_set value must be true or false.")
    whole_model = args.get("whole_model", False)
    if not isinstance(whole_model, bool):
        raise RustMeshValidationError("cloth_pin_set whole_model must be true or false.")
    if whole_model and pinned:
        raise RustMeshValidationError("Pin a selection, not the whole model: pinned cloth cannot move.")
    selection = authoring._apply_explicit_rig_selection(args, allowed=CLOTH_PIN_ARGUMENTS, command="cloth_pin_set")
    session = authoring.shadow_service._session(authoring.shadow_session_id)
    submeshes = session.working_mesh.submeshes
    vertices = {index: set(rows) for index, rows in selection.vertex_map().items()}
    if whole_model:
        vertices = {index: set(range(len(part.vertices))) for index, part in enumerate(submeshes)}
    for index in () if whole_model else selection.source_indices:
        if 0 <= int(index) < len(submeshes):
            vertices.setdefault(int(index), set()).update(range(len(submeshes[int(index)].vertices)))
    if not any(vertices.values()):
        raise RustMeshValidationError("Select one or more vertices before pinning cloth.")
    previous = session.selection
    session.selection = MeshEditSelection.from_maps(
        vertices_by_submesh={index: tuple(sorted(rows)) for index, rows in vertices.items() if rows})
    try:
        changed = authoring.shadow_service.set_selected_vertex_cloth_pin(authoring.shadow_session_id, pinned)
    except ValueError as exc:
        session.selection = previous
        raise RustMeshValidationError(str(exc)) from exc
    except Exception:
        session.selection = previous
        raise
    return {"changed_vertex_count": changed}


def part_pinned_points(session, part_index: int) -> tuple[tuple[float, float, float], ...]:
    """Pinned vertex positions of one working-mesh part, for guide creation."""
    submeshes = session.working_mesh.submeshes
    if not 0 <= part_index < len(submeshes):
        return ()
    part = submeshes[part_index]
    pins = list(getattr(part, "cloth_pin", ()) or ())
    if len(pins) != len(part.vertices):
        return ()
    return tuple(tuple(float(v) for v in part.vertices[i][:3]) for i, pin in enumerate(pins) if pin)
