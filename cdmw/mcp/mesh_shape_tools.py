"""Shaping a mesh by where things are, not by vertex numbers.

``mesh.landmarks`` says which way the model faces and where its skeleton's bones are, in
the same model space as the vertices, and where each bone's weighted vertices sit.
``mesh.select_region`` selects vertices in a sphere, a box or by bone weight, as a
selection made in the view. ``mesh.sculpt`` draws one stroke of the Sculpt brushes
(Grab, Smooth, Inflate, Pinch) through the view, with the brush's falloff and symmetry.

Without these an AI app read 500 vertices, exported an OBJ, scripted it outside CDMW and
then scaled rings of vertices about a point it guessed, behind the body (2026-11-24).
"""

from __future__ import annotations

import math

from cdmw.mcp.errors import INVALID_ARGUMENTS, NOT_FOUND, UNAVAILABLE, ToolError
from cdmw.mcp.names import EDIT, READ
from cdmw.mcp.tools import ON_WORKER, Tool, object_schema

_VEC3 = {"type": "array", "minItems": 3, "maxItems": 3, "items": {"type": "number"}}
_PARTS = {"type": "array", "maxItems": 4096, "items": {"type": "integer", "minimum": 0},
          "description": "Part numbers, as mesh_state lists them; all parts when left out."}
#: Bones worth naming when no 'name' filter is given: the body's main joints.
_KEY_BONES = ("pelvis", "spine", "spine1", "spine2", "neck", "head", "l chest", "r chest", "l clavicle",
              "r clavicle", "l upperarm", "r upperarm", "l forearm", "r forearm", "l hand", "r hand",
              "l thigh", "r thigh", "l calf", "r calf", "l foot", "r foot", "l toe0", "r toe0")
_MAX_LISTED_BONES = 400
_MAX_REGION_VERTICES = 200000


# ----- reading the shown document ---------------------------------------------------------
def _shown_session(call):
    """(the service's session, the working parts) of the shown document."""

    from cdmw.mcp.mesh_tools import NO_EDITOR, NOT_READY, _session_of

    _facts, session = _session_of(call)
    if session is None:
        raise ToolError(UNAVAILABLE, NO_EDITOR)
    service, session_id = session.shadow_service, session.shadow_session_id
    try:
        parts = list(getattr(service.working_mesh(session_id), "submeshes", ()) or ())
        owned = service._session(session_id)
    except (KeyError, RuntimeError) as exc:
        raise ToolError(UNAVAILABLE, str(exc) or NOT_READY) from None
    return owned, parts


def _part_numbers(call, parts: list) -> list[int]:
    wanted = call.arguments.get("parts")
    numbers = sorted({int(n) for n in wanted}) if wanted else list(range(len(parts)))
    if any(not 0 <= n < len(parts) for n in numbers):
        raise ToolError(NOT_FOUND, f"The mesh has parts 0 to {len(parts) - 1}.")
    return numbers


def bone_position(bone) -> tuple[float, float, float] | None:
    """A bone's bind position in model space: the bind matrix's translation (row-major, last
    row). Checked on the female body (phw_01.pab): the chest and face bones sit on the
    PAC's own vertices (2026-11-24)."""

    matrix = tuple(getattr(bone, "bind_matrix", ()) or ())
    if len(matrix) != 16:
        return None
    position = tuple(float(value) for value in matrix[12:15])
    return position if all(math.isfinite(value) for value in position) else None


def _palette_bones(session, part) -> list | None:
    """Each palette slot's skeleton bone for a PAC part, or None when it is not resolved."""

    from cdmw.modding.mesh_parser import resolve_pac_bone_palette

    skeleton = getattr(session, "skeleton", None)
    bones = tuple(getattr(skeleton, "bones", ()) or ())
    data = bytes(getattr(session, "original_data", b"") or b"")
    if not bones or not data or str(getattr(session.working_mesh, "format", "") or "").lower() != "pac":
        return None
    try:
        palette = tuple(resolve_pac_bone_palette(data, skeleton))
    except (ValueError, IndexError, TypeError):
        return None
    return [bones[ordinal] if 0 <= ordinal < len(bones) else None for ordinal in palette] or None


def _facing(bones) -> dict[str, object]:
    """Which way the model faces, from its feet: toes are in front of the ankles. The
    body's left is the side its ' L ' bones are on."""

    by_name = {str(bone.name).casefold(): bone for bone in bones}
    forward = None
    for side in ("l", "r"):
        foot, toe = by_name.get(f"bip01 {side} foot"), by_name.get(f"bip01 {side} toe0")
        if foot is not None and toe is not None:
            a, b = bone_position(foot), bone_position(toe)
            if a and b:
                dx, dz = b[0] - a[0], b[2] - a[2]
                if abs(dz) >= abs(dx) and abs(dz) > 1e-4:
                    forward = "-Z" if dz < 0 else "+Z"
                elif abs(dx) > 1e-4:
                    forward = "-X" if dx < 0 else "+X"
                break
    left_x = [p[0] for bone in bones if " l " in f" {str(bone.name).casefold()} "
              for p in [bone_position(bone)] if p]
    left = None
    if left_x:
        mean = sum(left_x) / len(left_x)
        left = "+X" if mean > 0 else "-X" if mean < 0 else None
    facts: dict[str, object] = {"up": "+Y", "front": forward, "left": left}
    if forward == "-Z":
        facts["camera"] = ("mesh_camera yaw 180 looks at the front, 0 at the back, 90 from +X and 270 from -X "
                           "(pitch 0). Points in front of the body have smaller Z.")
    elif forward == "+Z":
        facts["camera"] = ("mesh_camera yaw 0 looks at the front, 180 at the back, 90 from +X and 270 from -X "
                           "(pitch 0). Points in front of the body have larger Z.")
    return facts


# ----- mesh.landmarks ---------------------------------------------------------------------
def _landmarks(call) -> dict[str, object]:
    session, parts = _shown_session(call)
    a = call.arguments
    numbers = _part_numbers(call, parts)
    points = [vertex for n in numbers for vertex in parts[n].vertices]
    out: dict[str, object] = {"parts": numbers}
    if points:
        lows = [min(p[i] for p in points) for i in range(3)]
        highs = [max(p[i] for p in points) for i in range(3)]
        out["bounds"] = {"min": lows, "max": highs}
    skeleton = getattr(session, "skeleton", None)
    bones = tuple(getattr(skeleton, "bones", ()) or ())
    if not bones:
        out["message"] = "No skeleton is attached to this mesh, so there are no bones to name."
        return out
    out["facing"] = _facing(bones)
    name = str(a.get("name") or "").casefold().strip()
    if name:
        chosen = [bone for bone in bones if name in str(bone.name).casefold()]
    else:
        chosen = [bone for bone in bones if str(bone.name).casefold().removeprefix("bip01 ") in _KEY_BONES]
    rows = []
    for bone in chosen[:_MAX_LISTED_BONES]:
        position = bone_position(bone)
        if position is not None:
            rows.append({"bone": int(bone.index), "name": str(bone.name),
                         "position": [round(value, 5) for value in position]})
    out["bones"] = rows
    if len(chosen) > _MAX_LISTED_BONES:
        out["truncated"] = f"{len(chosen)} bones match; give a narrower 'name'."
    if a.get("weighted"):
        out["weighted"] = _weighted_centres(session, parts, numbers, name)
    return out


def _weighted_centres(session, parts, numbers, name: str) -> list[dict[str, object]]:
    """Each bone's weighted vertices in the chosen parts: how many, the weighted centre and
    the extent, which is where that bone's flesh is (a chest bone's centre is the breast)."""

    sums: dict[int, list] = {}
    for n in numbers:
        part = parts[n]
        slots = _palette_bones(session, part)
        if slots is None:
            continue
        for vertex, indices, weights in zip(part.vertices, part.bone_indices, part.bone_weights):
            for slot, weight in zip(indices, weights):
                bone = slots[slot] if 0 <= slot < len(slots) else None
                if bone is None or weight <= 0.0:
                    continue
                if name and name not in str(bone.name).casefold():
                    continue
                row = sums.setdefault(int(bone.index), [bone, 0.0, [0.0, 0.0, 0.0], 0, None, None])
                row[1] += weight
                row[2] = [row[2][i] + vertex[i] * weight for i in range(3)]
                if weight >= 0.5:
                    row[3] += 1
                    row[4] = [min(row[4][i], vertex[i]) for i in range(3)] if row[4] else list(vertex)
                    row[5] = [max(row[5][i], vertex[i]) for i in range(3)] if row[5] else list(vertex)
    rows = []
    for index, (bone, total, weighted, mostly, low, high) in sorted(sums.items(), key=lambda kv: -kv[1][1]):
        row = {"bone": index, "name": str(bone.name), "weight_total": round(total, 3),
               "centre": [round(value / total, 5) for value in weighted], "mostly_this_bone": mostly}
        if low is not None:
            row["extent"] = {"min": [round(v, 5) for v in low], "max": [round(v, 5) for v in high]}
        rows.append(row)
    return rows[:_MAX_LISTED_BONES]


# ----- mesh.select_region -----------------------------------------------------------------
def region_vertices(parts, numbers, *, sphere=None, box=None, bones=None, min_weight=0.3,
                    palettes=None) -> dict[str, list[int]]:
    """{part: [vertex]} inside the sphere and the box and weighted to the bones (each given
    one narrows the others)."""

    out: dict[str, list[int]] = {}
    names = [str(name).casefold() for name in bones or ()]
    for n in numbers:
        part = parts[n]
        slots = (palettes or {}).get(n)
        if names and slots is None:
            continue
        chosen = []
        for index, vertex in enumerate(part.vertices):
            if sphere is not None:
                centre, radius = sphere
                if sum((vertex[i] - centre[i]) ** 2 for i in range(3)) > radius * radius:
                    continue
            if box is not None:
                low, high = box
                if any(not low[i] <= vertex[i] <= high[i] for i in range(3)):
                    continue
            if names:
                weight = 0.0
                for slot, value in zip(part.bone_indices[index], part.bone_weights[index]):
                    bone = slots[slot] if 0 <= slot < len(slots) else None
                    if bone is not None and str(bone.name).casefold() in names:
                        weight += float(value)
                if weight < min_weight:
                    continue
            chosen.append(index)
        if chosen:
            out[str(n)] = chosen
    return out


def _select_region(call) -> dict[str, object]:
    from cdmw.mcp.mesh_edit_tools import _send_edit, selection_payload

    session, parts = _shown_session(call)
    a = call.arguments
    numbers = _part_numbers(call, parts)
    sphere = box = None
    if a.get("sphere") is not None:
        sphere = ([float(v) for v in a["sphere"]["centre"]], float(a["sphere"]["radius"]))
    if a.get("box") is not None:
        low, high = [float(v) for v in a["box"]["min"]], [float(v) for v in a["box"]["max"]]
        if any(low[i] > high[i] for i in range(3)):
            raise ToolError(INVALID_ARGUMENTS, "box min must not be above box max on any axis.")
        box = (low, high)
    bones = [str(name) for name in a.get("bones") or ()]
    if sphere is None and box is None and not bones:
        raise ToolError(INVALID_ARGUMENTS, "Give a sphere, a box or bones (any of them narrow each other).")
    palettes = {}
    if bones:
        skeleton_names = {str(bone.name).casefold() for bone in getattr(session.skeleton, "bones", ()) or ()} \
            if getattr(session, "skeleton", None) is not None else set()
        unknown = [name for name in bones if name.casefold() not in skeleton_names]
        if unknown:
            raise ToolError(NOT_FOUND, f"The skeleton has no bone {unknown[0]!r}; mesh_landmarks lists them.")
        palettes = {n: _palette_bones(session, parts[n]) for n in numbers}
        if not any(palettes.values()):
            raise ToolError(UNAVAILABLE, "These parts' bone slots are not resolved to bones (PAC files with an "
                                         "attached skeleton only).")
    found = region_vertices(parts, numbers, sphere=sphere, box=box, bones=bones,
                            min_weight=float(a.get("min_weight", 0.3)), palettes=palettes)
    total = sum(len(rows) for rows in found.values())
    if total == 0:
        raise ToolError(NOT_FOUND, "No vertex is in that region; mesh_landmarks gives the bones and bounds.")
    if total > _MAX_REGION_VERTICES:
        raise ToolError(INVALID_ARGUMENTS, f"The region holds {total} vertices; narrow it below "
                                           f"{_MAX_REGION_VERTICES}.")
    payload = selection_payload({"vertices": found}, parts)
    operation = str(a.get("operation") or "replace")
    result = _send_edit(call, "select", {"selection": payload, "operation": operation})
    return {**result, "region_vertices": {part: len(rows) for part, rows in found.items()}}


# ----- mesh.sculpt ------------------------------------------------------------------------
def _sculpt(call) -> dict[str, object]:
    from cdmw.mcp.editor_control import control_outcome, editor_control, has_control, older_helper
    from cdmw.mcp.mesh_edit_tools import history_now, request_mark, settle

    if not has_control(call, "sculpt"):
        from cdmw.mcp.mesh_tools import ready_document

        call.context.ui_call(lambda: ready_document(call.context))  # a stopped editor says so first
        raise ToolError(UNAVAILABLE, older_helper("sculpt"))
    arguments = {key: value for key, value in call.arguments.items() if value is not None}
    before, mark = history_now(call), request_mark(call.context)
    answer = editor_control(call, "sculpt", arguments)
    outcome = control_outcome(answer, "stroke")
    if answer.get("ok"):
        settled = settle(call, mark, before)
        outcome.update({name: settled[name] for name in ("history_before", "history", "status", "revision")
                        if name in settled})
        if settled.get("message"):
            outcome["message"] = settled["message"]
    return outcome


def mesh_shape_tools() -> list[Tool]:
    return [
        Tool(name="mesh.landmarks", family="mesh", title="Landmarks: facing and bones",
             description="Where things are on the shown document's model, in the same model space as its "
                         "vertices: 'facing' (which axis is up, front and the body's left, and which "
                         "mesh_camera yaw looks at the front), the parts' 'bounds', and the skeleton's bones "
                         "with their positions (the main joints, or those whose name contains 'name', for "
                         "example 'chest', 'breast', 'pelvis' or 'thigh'). 'weighted' adds, for each bone "
                         "the parts are skinned to, the centre and extent of its weighted vertices: that is "
                         "where its flesh is (a chest bone's centre is the breast). Use it before choosing "
                         "a region or a sculpt point.",
             input_schema=object_schema({"parts": _PARTS, "name": {"type": "string", "maxLength": 64},
                                         "weighted": {"type": "boolean", "default": False}}),
             effect=READ, route="service:MeshService.working_mesh+skeleton", handler=_landmarks,
             runs_on=ON_WORKER),
        Tool(name="mesh.select_region", family="mesh", title="Select a region",
             description="Selects the vertices of the shown document in a region, as a selection made in the "
                         "view does (one History step): inside a 'sphere' {centre, radius}, inside a 'box' "
                         "{min, max}, or weighted at least 'min_weight' (default 0.3) to 'bones' (names as "
                         "mesh_landmarks lists them); any given together narrow each other. 'parts' limits "
                         "it to some parts. Coordinates are model space, as mesh_landmarks and mesh_geometry "
                         "give them. A selection clips the Sculpt brushes and is what mesh_transform moves.",
             input_schema=object_schema({
                 "parts": _PARTS,
                 "sphere": object_schema({"centre": _VEC3, "radius": {"type": "number", "minimum": 1e-06}},
                                         ["centre", "radius"]),
                 "box": object_schema({"min": _VEC3, "max": _VEC3}, ["min", "max"]),
                 "bones": {"type": "array", "minItems": 1, "maxItems": 64,
                           "items": {"type": "string", "minLength": 1, "maxLength": 128}},
                 "min_weight": {"type": "number", "minimum": 0, "maximum": 1, "default": 0.3},
                 "operation": {"type": "string", "enum": ["replace", "add", "subtract", "toggle"],
                               "default": "replace"}}),
             effect=EDIT, route="helper:cdmw_command select", handler=_select_region, runs_on=ON_WORKER),
        Tool(name="mesh.sculpt", family="mesh", title="Sculpt brush stroke",
             description="One stroke of the Mesh Editor's Sculpt brushes through the 3D view, as a drag with "
                         "that brush does, so its falloff, symmetry and Undo step are the brush's own: "
                         "'tool' inflate (strength -1 to 1: positive swells along the surface normals, "
                         "negative shrinks), smooth, pinch, or grab (moves the surface from the first point "
                         "to the last); 'points' [[x, y, z], ...] on the surface in model space (one point "
                         "dabs in place); 'radius' in model units (a body's breast is about 0.06 to 0.09); "
                         "'dabs' (1 to 32) repeats the brush at each point for a stronger change; 'falloff' "
                         "smooth, linear or constant; 'symmetry' x mirrors across X=0 (the body's left and "
                         "right). The points must be in view: aim mesh_camera at them first (mesh_landmarks "
                         "says which yaw shows the front). A selection clips the brush to it, so "
                         "mesh_select_region first keeps a stroke off nearby parts of the body. Check the "
                         "result with view_capture; mesh_undo takes it back.",
             input_schema=object_schema({
                 "tool": {"type": "string", "enum": ["inflate", "smooth", "pinch", "grab"]},
                 "points": {"type": "array", "minItems": 1, "maxItems": 256, "items": _VEC3},
                 "radius": {"type": "number", "minimum": 1e-05, "maximum": 10000},
                 "strength": {"type": "number", "minimum": -1, "maximum": 1},
                 "dabs": {"type": "integer", "minimum": 1, "maximum": 32, "default": 1},
                 "falloff": {"type": "string", "enum": ["smooth", "linear", "constant"]},
                 "symmetry": {"type": "string", "enum": ["off", "x", "y", "z"]}},
                 ["tool", "points", "radius"]),
             effect=EDIT, route="helper:editor_control sculpt", handler=_sculpt, runs_on=ON_WORKER),
    ]


__all__ = ["bone_position", "mesh_shape_tools", "region_vertices"]
