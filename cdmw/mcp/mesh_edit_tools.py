"""The Mesh Editor edited by numbers: selection, topology, mesh actions, output and findings.

Each edit goes the way its button goes. CDMW asks the editor's helper to send the
command its button sends (``cdmw_command``, with the ``host_edit_commands_v1`` names);
the helper puts in its own selection for topology and mesh actions, as its buttons do,
and sends one request, which CDMW's authoring session checks and records as one
History step, exactly as after a click. The tool then waits for that request to come
back (``settle``) and returns the history before and after, the status line and the
selection, so a refusal is seen, not just "sent".
"""

from __future__ import annotations

import time
from pathlib import Path

from cdmw.mcp.errors import FAILED, INVALID_ARGUMENTS, NOT_FOUND, UNAVAILABLE, ToolError
from cdmw.mcp.names import EDIT, OUTPUT, READ
from cdmw.mcp.tools import ON_CALL, ON_WORKER, Tool, object_schema

SETTLE_S = 30.0
ARRIVE_S = 5.0
NO_EDIT_COMMANDS = ("This Mesh Editor helper does not take editing commands from CDMW; it is older than "
                    "this app (host_edit_commands_v1).")
OUTPUT_POLICIES = ("exact_game_asset", "replacement_game_asset", "free_edit_rebuild")
SELECT_OPERATIONS = ("replace", "add", "subtract", "toggle")
#: The folder the Output page's Free Edit makes inside the folder chosen (main.rs, configure_output_policy).
FREE_EDIT_FOLDER = "cdmw-rust-free-edit"
_PART = {"type": "integer", "minimum": 0, "description": "A part's number, as mesh_state lists it."}
_INDICES = {"type": "array", "maxItems": 200000, "items": {"type": "integer", "minimum": 0}}
_VEC3 = {"type": "array", "minItems": 3, "maxItems": 3, "items": {"type": "number"}}


def _topology_actions() -> tuple[str, ...]:
    from cdmw.services.mesh_rust_authoring import _HOST_TOPOLOGY_ACTIONS

    return tuple(sorted(_HOST_TOPOLOGY_ACTIONS))


def _mesh_actions() -> tuple[str, ...]:
    from cdmw.services.mesh_rust_authoring import _HOST_MESH_ACTION_PARAMS

    return tuple(sorted(_HOST_MESH_ACTION_PARAMS))


# ----- waiting for the round trip -------------------------------------------------------
def request_mark(context) -> int:
    """The number of the helper's latest request, read before sending a command."""

    from cdmw.mcp.mesh_tools import shown_document

    def read() -> int:
        tab = shown_document(context)
        return int(getattr(tab, "standalone_rust_last_client_request_id", 0) or 0)

    return context.ui_call(read)


def settle(call, mark: int, history_before: object, *, timeout: float = SETTLE_S) -> dict[str, object]:
    """Wait for the helper's request after ``mark`` to arrive and its reply to be applied,
    then say what changed. A helper that refuses locally (busy, nothing selected) sends no
    request: its status line then says why, after a short wait."""

    from cdmw.mcp.mesh_tools import _busy, _state, shown_document

    context = call.context

    def progress() -> tuple[int, bool]:
        tab = shown_document(context)
        return int(getattr(tab, "standalone_rust_last_client_request_id", 0) or 0), _busy(tab)

    arrived, busy = False, True
    start = time.monotonic()
    while True:
        call.check_cancelled()
        request, busy = context.ui_call(progress)
        arrived = arrived or request > mark
        waited = time.monotonic() - start
        if (arrived and not busy) or (not arrived and waited > ARRIVE_S) or waited > timeout:
            break
        time.sleep(0.05)
    after = _state(call)
    outcome: dict[str, object] = {"done": arrived and not busy, "status": after.get("status", ""),
                                  "history_before": history_before, "history": after.get("history"),
                                  "selection": after.get("selection"), "revision": after.get("revision")}
    if not arrived:
        outcome["message"] = ("The Mesh Editor did not send the request; its status line says why (for "
                              "example nothing is selected, or Free Edit output is needed).")
    elif busy:
        outcome["message"] = "The Mesh Editor is still working on it; mesh_state shows when it is done."
    return outcome


def history_now(call) -> object:
    from cdmw.mcp.mesh_tools import _state

    return _state(call).get("history")


def settled(handler):
    """``handler`` (a helper command sent as its button sends it), then what it did."""

    def run(call) -> dict[str, object]:
        before = history_now(call)
        mark = request_mark(call.context)
        sent = handler(call)
        return {**sent, **settle(call, mark, before)}

    return run


def _send_edit(call, command: str, arguments: dict[str, object]) -> dict[str, object]:
    from cdmw.automation.authoring_commands import _send
    from cdmw.mcp.mesh_tools import BUSY, _act, _busy, ready_document

    context = call.context
    before = history_now(call)
    mark = request_mark(context)

    def send() -> dict[str, object]:
        tab = ready_document(context, commands=True)
        if not getattr(tab, "standalone_rust_host_edit_commands_supported", False):
            raise ToolError(UNAVAILABLE, NO_EDIT_COMMANDS)
        if _busy(tab):
            raise ToolError(UNAVAILABLE, BUSY)
        if not _send(tab, command, arguments):
            raise ToolError(FAILED, "The Mesh Editor did not take the command.")
        return {}

    sent = _act(call, send)
    outcome = settle(call, mark, before)
    if sent.get("asked"):
        outcome["asked"] = sent["asked"]
    return outcome


# ----- the panels: weights, morphs, refit, cloth, layers, hair, replacement options --------
NO_PANEL_COMMANDS = ("This Mesh Editor helper does not take its panels' commands from CDMW; it is older than "
                     "this app (host_panel_commands_v1).")
#: The commands each panel sends, by family, as the helper takes them by name
#: (``host_cdmw_panel_command`` in cdmw_session.rs). Exports that write files are not here.
PANEL_COMMANDS: dict[str, tuple[str, ...]] = {
    "cloth": (
        "collision_input", "paint_set", "pin_set",
    ),
    "hair": (
        "color", "texture",
    ),
    "layer": (
        "activate", "copy", "delete", "move", "paste", "rename", "visibility",
    ),
    "morph": (
        "activate", "apply_preset", "apply_setup", "bake", "begin_correction", "cancel_baseline",
        "cancel_correction", "capture_authored", "capture_baseline", "clear_driver_region", "clear_influence",
        "create", "delete_definition", "delete_preset", "delete_profile", "generate_body_controls",
        "import_preset", "import_recipe", "reset", "reset_correction", "reset_macros", "save_correction",
        "save_preset", "save_profile", "save_setup", "set_corrections_enabled", "set_driver_region",
        "set_influence", "set_macro", "set_side_value", "set_symmetry", "set_value",
    ),
    "refit": (
        "bind", "choose_archive", "clear", "configure", "diagnostics", "fit_to_body", "island_configure",
        "load_mesh", "restore_shape_apply", "restore_shape_cancel", "restore_shape_preview", "set_driver",
        "use_loaded_body",
    ),
    "replacement": (
        "cloth", "collision_volumes", "compare", "emission", "fit", "guides", "include", "islands", "jiggle",
        "physics_profile", "reset", "shader_controls", "translucency", "weapon_collisions",
    ),
    "rig": (
        "adjust_weight", "normalize_weights", "select_bone", "transfer_weights",
    ),
}


def _panel(family: str):
    def handler(call) -> dict[str, object]:
        from cdmw.mcp.mesh_tools import shown_document

        action = str(call.arguments["action"])
        if action not in PANEL_COMMANDS[family]:
            raise ToolError(INVALID_ARGUMENTS, f"The {family} commands are: {', '.join(PANEL_COMMANDS[family])}.")

        def supported() -> bool:
            return bool(getattr(shown_document(call.context), "standalone_rust_host_panel_commands_supported", False))

        if not call.context.ui_call(supported):
            raise ToolError(UNAVAILABLE, NO_PANEL_COMMANDS)
        return _send_edit(call, f"{family}_{action}", dict(call.arguments.get("arguments") or {}))

    return handler


# ----- the tools -------------------------------------------------------------------------
def _working_parts(call) -> list:
    from cdmw.mcp.mesh_tools import NO_EDITOR, NOT_READY, _session_of

    _facts, session = _session_of(call)
    if session is None:
        raise ToolError(UNAVAILABLE, NO_EDITOR)
    try:
        mesh = session.shadow_service.working_mesh(session.shadow_session_id)
    except (KeyError, RuntimeError) as exc:
        raise ToolError(UNAVAILABLE, str(exc) or NOT_READY) from None
    return list(getattr(mesh, "submeshes", ()) or ())


def _index_map(value, what: str, parts: list) -> dict[str, list]:
    """{part: [items]} as the selection payload carries it (part numbers as text)."""

    out: dict[str, list] = {}
    for key, items in dict(value or {}).items():
        try:
            part = int(key)
        except (TypeError, ValueError):
            raise ToolError(INVALID_ARGUMENTS, f"{what}: '{key}' is not a part number.") from None
        if not 0 <= part < len(parts):
            raise ToolError(NOT_FOUND, f"{what}: the mesh has parts 0 to {len(parts) - 1}.")
        out[str(part)] = [list(item) if isinstance(item, (list, tuple)) else int(item) for item in items or ()]
    return out


def selection_payload(arguments: dict, parts: list) -> dict[str, object]:
    """The selection for ``select``, checked against the parts' own counts."""

    vertices = _index_map(arguments.get("vertices"), "vertices", parts)
    faces = _index_map(arguments.get("faces"), "faces", parts)
    edges = _index_map(arguments.get("edges"), "edges", parts)
    for part, rows in vertices.items():
        count = len(parts[int(part)].vertices)
        if any(not 0 <= index < count for index in rows):
            raise ToolError(INVALID_ARGUMENTS, f"Part {part} has vertices 0 to {count - 1}.")
    for part, rows in faces.items():
        count = len(parts[int(part)].faces)
        if any(not 0 <= index < count for index in rows):
            raise ToolError(INVALID_ARGUMENTS, f"Part {part} has triangles 0 to {count - 1}.")
    for part, rows in edges.items():
        count = len(parts[int(part)].vertices)
        if any(len(edge) != 2 or not all(0 <= int(v) < count for v in edge) for edge in rows):
            raise ToolError(INVALID_ARGUMENTS,
                            f"An edge of part {part} is not two of its vertices 0 to {count - 1}.")
    whole = sorted({int(index) for index in arguments.get("parts") or ()})
    if any(not 0 <= index < len(parts) for index in whole):
        raise ToolError(NOT_FOUND, f"The mesh has parts 0 to {len(parts) - 1}.")
    return {"vertices_by_submesh": vertices, "edges_by_submesh": edges, "faces_by_submesh": faces,
            "source_indices": whole}


def _select(call) -> dict[str, object]:
    selection = selection_payload(call.arguments, _working_parts(call))
    operation = str(call.arguments.get("operation") or "replace")
    return _send_edit(call, "select", {"selection": selection, "operation": operation})


def _labelled(command: str):
    def handler(call) -> dict[str, object]:
        a = call.arguments
        action = str(a["action"])
        label = str(a.get("label") or action.replace("_", " ").capitalize())
        return _send_edit(call, command, {"action": action, "params": dict(a.get("params") or {}),
                                          "label": label})

    return handler


def _transform(call) -> dict[str, object]:
    a = call.arguments
    params: dict[str, object] = {}
    for name in ("translate", "rotate_degrees", "scale", "pivot"):
        if a.get(name) is not None:
            params[name] = [float(value) for value in a[name]]
    if not any(name in params for name in ("translate", "rotate_degrees", "scale")):
        raise ToolError(INVALID_ARGUMENTS, "Give translate, rotate_degrees or scale.")
    if a.get("recompute_normals") is not None:
        params["recompute_normals"] = bool(a["recompute_normals"])
    label = str(a.get("label") or "Transform")
    return _send_edit(call, "mesh_action", {"action": "transform", "params": params, "label": label})


def _output_policy(call) -> dict[str, object]:
    from cdmw.mcp.mesh_tools import _state

    a = call.arguments
    arguments: dict[str, object] = {"policy": str(a["policy"])}
    if a.get("destination"):
        from cdmw.core.archive_extraction import find_available_output_path

        # As the Output page's folder chooser: a new folder inside the one chosen.
        arguments["destination"] = str(find_available_output_path(Path(str(a["destination"])) / FREE_EDIT_FOLDER))
    elif a["policy"] == "free_edit_rebuild":
        raise ToolError(INVALID_ARGUMENTS, "Free Edit writes an editable package: give 'destination', an "
                                           "existing folder outside the game.")
    outcome = _send_edit(call, "configure_output_policy", arguments)
    outcome["output"] = _state(call).get("output")
    return outcome


def _findings(call) -> dict[str, object]:
    from cdmw.mcp.mesh_tools import NO_EDITOR, NOT_READY, _session_of
    from cdmw.services.mesh_rust_authoring import _json_safe

    _facts, session = _session_of(call)
    if session is None:
        raise ToolError(UNAVAILABLE, NO_EDITOR)
    try:
        report = session.shadow_service.validate_export(session.shadow_session_id)
    except (KeyError, RuntimeError) as exc:
        raise ToolError(UNAVAILABLE, str(exc) or NOT_READY) from None
    payload = _json_safe(report)
    return payload if isinstance(payload, dict) else {"report": payload}


#: Message boxes that end a button's handler before it writes anything.
REFUSAL_KINDS = ("warning", "critical", "information", "question")


def _export_pac(call) -> dict[str, object]:
    """Export PAC As, as its button does after its file chooser: the finished PAC alone."""

    from cdmw.mcp.mesh_tools import NO_EDITOR, _act, _status, shown_document

    context = call.context
    path = str(Path(str(call.arguments["path"])))
    if Path(path).suffix.lower() != ".pac":
        raise ToolError(INVALID_ARGUMENTS, "Export PAC As writes a .pac file.")

    def press() -> dict[str, object]:
        tab = shown_document(context)
        if tab is None or getattr(tab, "standalone_controller", None) is None:
            raise ToolError(UNAVAILABLE, NO_EDITOR)
        tab._start_standalone_export_pac_requested()
        return {"status": _status(tab)}

    outcome = _act(call, press, {"save_file": path})
    refused = [row for row in outcome.get("asked") or () if str(row.get("kind", "")) in REFUSAL_KINDS]
    chose = any("save" in str(row.get("kind", "")) for row in outcome.get("asked") or ())
    if refused or not chose:
        outcome["message"] = "Export PAC As did not start: 'asked' says why (Build Mod writes edits a PAC alone cannot hold)."
    else:
        outcome.update(started=True, path=path, message="The PAC is being written; mesh_state's status says when it is done.")
    return outcome


def _panels(call) -> dict[str, object]:
    """The panels' state as the editor is given it (the host's state, without the mesh)."""

    from cdmw.mcp.mesh_tools import NO_EDITOR, NOT_READY, _session_of
    from cdmw.services.mesh_rust_authoring import _json_safe

    _facts, session = _session_of(call)
    if session is None:
        raise ToolError(UNAVAILABLE, NO_EDITOR)
    try:
        payload = session.state_payload(include_document=False)
    except (KeyError, RuntimeError) as exc:
        raise ToolError(UNAVAILABLE, str(exc) or NOT_READY) from None
    wanted = [str(name) for name in call.arguments.get("sections") or ()]
    sections = {key: value for key, value in dict(payload).items()
                if (key in wanted if wanted else key in PANEL_SECTIONS)}
    return {"sections": _json_safe(sections), "available": sorted(str(key) for key in dict(payload))}


#: The host state's sections the panels draw from, returned by default.
PANEL_SECTIONS = ("skeleton", "rig_influence", "morph_refit", "geometry_layers", "cloth", "cloth_guides", "cloth_paint",
                  "jiggle", "physics", "physics_profiles", "collision_volumes", "weapon_collisions", "replacement",
                  "shader_controls", "emission", "translucency", "hair", "mesh_islands", "vertex_parameters")

_PANEL_TOOLS = (
    ("rig", "mesh.weights", "Weights",
     "The Rig page's weight commands on the shown document's selected vertices, as its buttons send them: "
     "select_bone {bone_index}, adjust_weight {delta}, normalize_weights {}, transfer_weights {}."),
    ("morph", "mesh.morph", "Morphs",
     "The Morph & Refit page's morph commands, by the names its controls send (activate, create, set_value, "
     "set_macro, set_side_value, set_symmetry, set_influence, set_driver_region, bake, reset, save_profile, "
     "apply_preset, save_preset, import_preset, corrections ...), with the arguments the page sends; "
     "mesh_panels shows the morph state they work on."),
    ("refit", "mesh.refit", "Refit",
     "The Morph & Refit page's refit commands: set_driver {submesh_indices}, use_loaded_body, load_mesh, "
     "choose_archive, bind {submesh_indices}, configure {submesh_indices, clearance_percent, intensity_percent, "
     "tightness_percent, skin_pull_percent, mode, enabled}, island_configure, fit_to_body, restore_shape_preview, "
     "restore_shape_apply, restore_shape_cancel, clear, diagnostics."),
    ("cloth", "mesh.cloth", "Cloth",
     "The Cloth page's commands on the selected vertices: pin_set {value}, paint_set {value}, "
     "collision_input {role, source}."),
    ("layer", "mesh.layers", "Layers",
     "The Layers list's commands: activate {layer_id}, rename {layer_id, name}, move {layer_id, direction}, "
     "visibility {layer_id, visible}, copy, paste, delete {layer_id}."),
    ("hair", "mesh.hair", "Hair",
     "Hair Tools' commands for a hairstyle being made: color {color: [r, g, b]}, texture {...}."),
    ("replacement", "mesh.part_options", "Part options",
     "The Inspector's per-part options for the selected parts ('part_ids' as mesh_panels lists them), as its "
     "controls send them: shader_controls (Shader experiments, {part_ids, shader_controls}), emission, "
     "translucency, jiggle, physics_profile, collision_volumes, weapon_collisions, cloth, guides, islands, "
     "include {part_ids, included}; and Import Replacement's fit, compare and reset."),
)


def mesh_edit_tools() -> list[Tool]:
    label = {"type": "string", "maxLength": 128}
    return [
        Tool(name="mesh.select", family="mesh", title="Select by numbers",
             description="Selects vertices, edges, faces and whole parts in the shown document by their "
                         "numbers (as mesh_geometry lists them), as a selection made in the view does: "
                         "'vertices' and 'faces' map a part number to its vertex or triangle numbers, 'edges' a "
                         "part number to [vertex, vertex] pairs, 'parts' lists whole parts; 'operation' replaces "
                         "the selection, adds to it, subtracts from it or toggles. One History step. Returns the "
                         "selection, the status line and the history before and after.",
             input_schema=object_schema({
                 "vertices": {"type": "object", "additionalProperties": _INDICES},
                 "faces": {"type": "object", "additionalProperties": _INDICES},
                 "edges": {"type": "object", "additionalProperties": {
                     "type": "array", "maxItems": 200000,
                     "items": {"type": "array", "minItems": 2, "maxItems": 2,
                               "items": {"type": "integer", "minimum": 0}}}},
                 "parts": {"type": "array", "maxItems": 4096, "items": _PART},
                 "operation": {"type": "string", "enum": list(SELECT_OPERATIONS), "default": "replace"}}),
             effect=EDIT, route="helper:cdmw_command select", handler=_select, runs_on=ON_WORKER),
        Tool(name="mesh.topology", family="mesh", title="Topology",
             description="A topology operation on the shown document's selection, as its button on the "
                         "Topology page does: delete, duplicate, subdivide, refine_smooth (params "
                         "smooth_strength, smooth_iterations), loop_cut (cuts, factor), edge_split, split, "
                         "dissolve, bridge, fill, merge, weld (threshold), extrude (offset [x, y, z]), inset "
                         "(amount), separate (Create Part). Most need Free Edit output (mesh_output_policy); "
                         "CDMW refuses what the output cannot hold, as for the button. One History step.",
             input_schema=object_schema({"action": {"type": "string", "enum": list(_topology_actions())},
                                         "params": {"type": "object"}, "label": label}, ["action"]),
             effect=EDIT, route="helper:cdmw_command topology", handler=_labelled("topology"),
             runs_on=ON_WORKER),
        Tool(name="mesh.mesh_action", family="mesh", title="Mesh action",
             description="A Mesh Data, Normals, Cleanup or UV action on the shown document's selection, as its "
                         "button does: mirror (axis, in_place), remove_doubles (threshold), "
                         "delete_loose_vertices, compact_orphans, fix_winding, fill_holes, recalculate_normals, "
                         "generate_tangents, flip_normals, sharpen_normals, soften_normals, weighted_normals, "
                         "copy_normals, uv_transform (offset, scale, rotate_degrees, pivot, flip_u, flip_v, "
                         "normalize, align_u, align_v ...). CDMW checks each against the output as for the "
                         "button. One History step.",
             input_schema=object_schema({"action": {"type": "string", "enum": list(_mesh_actions())},
                                         "params": {"type": "object"}, "label": label}, ["action"]),
             effect=EDIT, route="helper:cdmw_command mesh_action", handler=_labelled("mesh_action"),
             runs_on=ON_WORKER),
        Tool(name="mesh.transform", family="mesh", title="Move, rotate, scale",
             description="Moves, rotates and scales the shown document's selected vertices (or faces, edges, "
                         "parts) by numbers, as the Move, Rotate and Scale tools do with the pointer: "
                         "'translate' [x, y, z] in model units, 'rotate_degrees' [x, y, z], 'scale' [x, y, z] "
                         "(1 keeps a size), about 'pivot' [x, y, z] or the selection's centre. Normals are "
                         "recomputed unless 'recompute_normals' is false. One History step.",
             input_schema=object_schema({"translate": _VEC3, "rotate_degrees": _VEC3, "scale": _VEC3,
                                         "pivot": _VEC3, "recompute_normals": {"type": "boolean"},
                                         "label": label}),
             effect=EDIT, route="helper:cdmw_command mesh_action transform", handler=_transform,
             runs_on=ON_WORKER),
        Tool(name="mesh.output_policy", family="mesh", title="Output",
             description="Chooses what the shown document's edit writes, as the Output page does: "
                         "'exact_game_asset' (the game's own PAC, same structure), 'replacement_game_asset' "
                         "(after Import Replacement), or 'free_edit_rebuild' (any change, written as an "
                         "editable package in a new folder inside 'destination', an existing folder outside the "
                         "game). "
                         "mesh_state's 'output' says what is chosen and why.",
             input_schema=object_schema({"policy": {"type": "string", "enum": list(OUTPUT_POLICIES)},
                                         "destination": {"type": "string", "minLength": 3, "maxLength": 1024}},
                                        ["policy"]),
             effect=EDIT, route="helper:cdmw_command configure_output_policy", handler=_output_policy,
             runs_on=ON_WORKER, output_folders=("destination",)),
        *[Tool(name=name, family="mesh", title=title,
               description=text + " CDMW checks each as it checks the panel's own; the result is the history "
                                  "before and after and the status line, which says why a command was refused.",
               input_schema=object_schema({"action": {"type": "string", "enum": list(PANEL_COMMANDS[family])},
                                           "arguments": {"type": "object"}}, ["action"]),
               effect=EDIT, route=f"helper:cdmw_command {family}_*", handler=_panel(family), runs_on=ON_WORKER)
          for family, name, title, text in _PANEL_TOOLS],
        Tool(name="mesh.panels", family="mesh", title="Mesh Editor panels",
             description="What the shown document's panels show, as the editor is given them: skeleton and "
                         "bone influence, morph_refit, geometry_layers, cloth, jiggle, physics, collisions, "
                         "replacement (with each part's id), shader_controls, emission, translucency, hair, "
                         "mesh_islands. 'sections' picks some; 'available' lists them all.",
             input_schema=object_schema({"sections": {"type": "array", "maxItems": 32,
                                                      "items": {"type": "string", "maxLength": 64}}}),
             effect=READ, route="service:RustMeshAuthoringSession.state_payload", handler=_panels,
             runs_on=ON_WORKER),
        Tool(name="mesh.export_pac", family="mesh", title="Export PAC As",
             description="Export PAC As: the shown document's finished mesh as one .pac file at 'path' (a new file "
                         "outside the game), as the button does after its file chooser. Refused, as the button "
                         "refuses, when the edit needs companion files (textures, materials, sets): use "
                         "mesh_build_mod then.",
             input_schema=object_schema({"path": {"type": "string", "minLength": 3, "maxLength": 1024}}, ["path"]),
             effect=OUTPUT, route="ui:_start_standalone_export_pac_requested", handler=_export_pac,
             runs_on=ON_CALL, output_paths=("path",)),
        Tool(name="mesh.findings", family="mesh", title="Mesh findings",
             description="The shown document's validation, as Finish runs it: whether the mesh can be written "
                         "for its output, and each finding with its part and what to do about it.",
             input_schema=object_schema(), effect=READ, route="service:MeshService.validate_export",
             handler=_findings, runs_on=ON_WORKER),
    ]


__all__ = ["mesh_edit_tools", "request_mark", "selection_payload", "settle", "settled"]
