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

import re
import time
from pathlib import Path

from cdmw.mcp.errors import FAILED, INVALID_ARGUMENTS, NOT_FOUND, UNAVAILABLE, ToolError
from cdmw.mcp.mesh_panel_schemas import PANELS, PARAMS, actions_text, check, union_schema
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


NO_OUTPUT_COMMANDS = ("This Mesh Editor helper does not take these commands from CDMW; it is older than this "
                      "app (host_output_commands_v1).")
NO_CAMERA = "This Mesh Editor helper does not take its camera from CDMW; it is older than this app (host_camera_v1)."
NO_VIEW_STATE = ("This Mesh Editor helper does not take its view settings from CDMW; it is older than this app "
                 "(host_view_state_v1).")
NO_VIEW_LOOK = ("This Mesh Editor helper does not take its lighting or Studio look from CDMW; it is older than "
                "this app (host_view_look_v1).")
#: The commands that need host_output_commands_v1 (cdmw_session.rs, host_cdmw_output_command).
OUTPUT_COMMANDS = ("vertex_edit", "hair_begin", "hair_texture_export", "export_free_edit", "import_editable_package",
                   "morph_export_recipe", "morph_export_preset", "replacement_export_rig")


def _require(call, flag: str, message: str) -> None:
    from cdmw.mcp.mesh_tools import shown_document

    if not call.context.ui_call(lambda: bool(getattr(shown_document(call.context), flag, False))):
        raise ToolError(UNAVAILABLE, message)


def _send_output(call, command: str, arguments: dict[str, object]) -> dict[str, object]:
    _require(call, "standalone_rust_host_output_commands_supported", NO_OUTPUT_COMMANDS)
    return _send_edit(call, command, arguments)


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
        "begin", "color", "import_custom", "texture", "texture_export",
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
        "material_colours", "physics_profile", "reset", "shader_controls", "translucency", "weapon_collisions",
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
        command = f"{family}_{action}"
        arguments = dict(call.arguments.get("arguments") or {})
        if family in PANELS:
            check(PANELS[family], action, arguments, f"mesh {family}")
        from cdmw.mcp.mesh_archive_choice import picks_from_archive, send_with_choice

        if picks_from_archive(command, arguments):
            # Its button opens a picker; the call names the file instead, so none opens.
            return send_with_choice(call, command, arguments, _send_edit)
        if command in OUTPUT_COMMANDS:
            return _send_output(call, command, arguments)
        return _send_edit(call, command, arguments)

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
        params = dict(a.get("params") or {})
        if action in PARAMS[command]:
            check(PARAMS[command], action, params, f"{command.replace('_', ' ')} params for")
        label = str(a.get("label") or action.replace("_", " ").capitalize())
        return _send_edit(call, command, {"action": action, "params": params, "label": label})

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
                  "shader_controls", "material_colours", "emission", "translucency", "hair", "mesh_islands",
                  "vertex_parameters")

_PANEL_TOOLS = (
    ("rig", "mesh.weights", "Weights",
     "The Rig page's weight commands on the shown document's selected vertices, as its buttons send them."),
    ("morph", "mesh.morph", "Morphs",
     "The Morph & Refit page's morph commands, by the names its controls send; mesh_panels' morph_refit shows "
     "the profiles, sliders, presets and body controls they work on."),
    ("refit", "mesh.refit", "Refit",
     "The Morph & Refit page's refit commands. choose_archive is Load Body or Load Armor from the game "
     "archives: 'archive_path' names the file, as search_archive lists it, in place of the picker."),
    ("cloth", "mesh.cloth", "Cloth",
     "The Cloth page's commands on the selected vertices, and the cloth preview's collision inputs: "
     "collision_input takes {role, archive_path} (body or head: a .pabv, weapon: a .pac, from the game "
     "archives, in place of the picker), {role, path} (such a file on disk), {clear: true} or "
     "{weapon_placement: {offset: [x, y, z], rotation: [x, y, z] in degrees}} (moves the weapon chosen before)."),
    ("layer", "mesh.layers", "Layers",
     "The Layers list's commands. copy copies the current selection, as Copy does."),
    # Hair Tools has its own typed tool (mesh_hair_tools.py).
    ("replacement", "mesh.part_options", "Part options",
     "The Inspector's per-part options, as its controls send them ('part_ids' as mesh_panels' replacement "
     "section lists them; parts sharing a material change together), and Import Replacement's fit, compare and "
     "reset. shader_controls are the Shader experiments: its 'texture_files' gives a texture slot a file."),
)


#: The Vertex Parameters inspector's page size (cdmw/services/mesh_vertex_parameters.py, MAX_PAGE_SIZE).
VERTEX_PAGE_SIZE = 128
_TOKEN_SCHEMA = object_schema({
    "session_id": {"type": "string", "minLength": 1, "maxLength": 256},
    "mesh_revision": {"type": "integer", "minimum": 0},
    "selection_revision": {"type": "integer", "minimum": 0},
    "topology_generation": {"type": "integer", "minimum": 0},
}, ["session_id", "mesh_revision", "selection_revision", "topology_generation"])
_TOKEN_SCHEMA["description"] = ("The 'token' mesh_vertex_inspect returned, as it is: it names the selection and "
                                "mesh revision it read, so an edit after either changed is refused.")


def _component(width: int, *, nullable: bool = True) -> dict[str, object]:
    item = {"type": ["number", "null"]} if nullable else {"type": "number"}
    return {"type": "array", "minItems": width, "maxItems": width, "items": item}


def _channel_edit(width: int, what: str, *, offsets: bool = True) -> dict[str, object]:
    schema = object_schema({"mode": {"type": "string", "enum": ["set", "offset"] if offsets else ["set"],
                                     "default": "set"},
                            "values": _component(width)}, ["values"])
    schema["description"] = what
    return schema


_VERTEX_EDITS = object_schema({
    "position": _channel_edit(3, "Model-space position [x, y, z]; null keeps that axis. 'offset' adds to it."),
    "uv0": _channel_edit(2, "UV0 [u, v]; null keeps that component. 'offset' adds to it."),
    "normal": _channel_edit(3, "The normal direction [x, y, z], all three given; it is normalised.", offsets=False),
    "weights": {**object_schema({
        "mode": {"type": "string", "enum": ["set", "offset", "remove", "normalize"]},
        "bone": {"type": "integer", "minimum": 0,
                 "description": "The skeleton bone (a 'bones' row's 'bone'), not its palette slot."},
        "value": {"type": "number", "minimum": -1, "maximum": 1}}, ["mode"]),
        "description": "Skin weights: set or offset one bone's influence (the others are scaled to keep the "
                       "total 1), remove it, or normalize each vertex's row."},
})


def _vertex_request(session) -> dict[str, object]:
    """The identity the helper's own inspector requests carry, for the inspection route."""

    from cdmw.services.mesh_rust_contract import RUST_MESH_EDITOR_PROTOCOL

    view = session.shadow_service.session_view(session.shadow_session_id)
    return {"protocol": RUST_MESH_EDITOR_PROTOCOL, "session_id": session.session_id,
            "process_generation": session.process_generation, "base_revision": int(view.revision)}


def _vertex_inspect(call) -> dict[str, object]:
    """The Vertex Parameters inspector's page, read through the route its helper uses."""

    from cdmw.mcp.mesh_tools import NO_EDITOR, NOT_READY, _session_of
    from cdmw.services.mesh_rust_authoring import _json_safe
    from cdmw.services.mesh_vertex_parameters import inspection_token

    _facts, session = _session_of(call)
    if session is None:
        raise ToolError(UNAVAILABLE, NO_EDITOR)
    page = int(call.arguments.get("page") or 0)
    size = int(call.arguments.get("page_size") or VERTEX_PAGE_SIZE)
    last_error = ""
    # The selection or mesh can change between reading the token and reading the page: read again once.
    for _attempt in range(2):
        call.check_cancelled()
        try:
            request = {**_vertex_request(session),
                       "arguments": {"token": inspection_token(session), "page": page, "page_size": size}}
            result = session.vertex_inspect(request)
        except ValueError as exc:
            last_error = str(exc)
            continue
        except (KeyError, RuntimeError) as exc:
            raise ToolError(UNAVAILABLE, str(exc) or NOT_READY) from None
        payload = _json_safe(result)
        payload["pages"] = max(1, -(-int(payload.get("count") or 0) // size))
        if not payload.get("count"):
            payload["message"] = "No vertices are selected: select some first (mesh_select)."
        return payload
    raise ToolError(UNAVAILABLE, last_error or NOT_READY)


def _vertex_edit(call) -> dict[str, object]:
    a = call.arguments
    return _send_output(call, "vertex_edit", {"token": dict(a["token"]), "edits": dict(a["edits"])})


def _open_package(call) -> dict[str, object]:
    path = Path(str(call.arguments["path"]))
    if not path.exists():
        raise ToolError(NOT_FOUND, f"There is no package at {path}.")
    return _send_output(call, "import_editable_package", {"path": str(path)})


def _output(call) -> dict[str, object]:
    a = call.arguments
    action = str(a["action"])
    if action == "free_edit":
        return _send_output(call, "export_free_edit", {})
    if action == "rig":
        if not a.get("folder"):
            raise ToolError(INVALID_ARGUMENTS, "Export rig GLB writes into 'folder', an existing folder outside the game.")
        return _send_output(call, "replacement_export_rig", {"folder": str(Path(str(a["folder"])))})
    if not a.get("path"):
        raise ToolError(INVALID_ARGUMENTS, "Give 'path', a new .json file outside the game.")
    path = Path(str(a["path"]))
    if path.suffix.lower() != ".json":
        raise ToolError(INVALID_ARGUMENTS, "Morph presets and fitting setups are saved as .json files.")
    command = "morph_export_preset" if action == "morph_preset" else "morph_export_recipe"
    return _send_output(call, command, {"path": str(path), "name": str(a.get("name") or path.stem)})


#: Camera values the view takes, in degrees for the angles.
_CAMERA_KEYS = ("yaw", "pitch", "distance", "target")


def _camera_out(report: dict) -> dict[str, object]:
    import math

    return {"yaw": math.degrees(float(report.get("yaw", 0.0))), "pitch": math.degrees(float(report.get("pitch", 0.0))),
            "distance": report.get("distance"),
            "target": [report.get("target_x"), report.get("target_y"), report.get("target_z")]}


def _camera(call) -> dict[str, object]:
    import math

    from cdmw.mcp.mesh_tools import ready_document

    a = call.arguments
    values: dict[str, object] = {}
    for key in ("yaw", "pitch"):
        if a.get(key) is not None:
            values[key] = math.radians(float(a[key]))
    if a.get("distance") is not None:
        values["distance"] = float(a["distance"])
    if a.get("target") is not None:
        values["target"] = [float(value) for value in a["target"]]
    if a.get("frame"):
        values["frame"] = True

    def send() -> bool:
        tab = ready_document(call.context)
        if not getattr(tab, "standalone_rust_camera_supported", False):
            raise ToolError(UNAVAILABLE, NO_CAMERA)
        return tab.set_camera_in_view(values)

    if not call.context.ui_call(send):
        raise ToolError(FAILED, "The Mesh Editor did not take the camera.")
    deadline = time.monotonic() + ARRIVE_S
    while time.monotonic() < deadline:
        call.check_cancelled()
        report = call.context.ui_call(lambda: getattr(ready_document(call.context), "standalone_rust_camera", None))
        if report is not None:
            return {"camera": _camera_out(report)}
        time.sleep(0.03)
    raise ToolError(FAILED, "The Mesh Editor did not report its camera.")


#: mesh.view's arguments, as set_view_state takes them (cdmw_session.rs, decode_set_view_state).
_VIEW_KEYS = ("reset", "selection_shape", "selection_operation", "selection_xray", "brush_radius", "brush_strength",
              "brush_falloff", "colours", "wire_width", "vertex_size", "show_parts", "hide_parts",
              "lighting_preset", "wetness", "exposure", "light_rotation")
#: The keys that need host_view_look_v1 (the View panel's Lighting menu and Studio look sliders).
_LOOK_KEYS = ("lighting_preset", "wetness", "exposure", "light_rotation")
_HEX = {"type": "string", "minLength": 7, "maxLength": 7, "description": "#RRGGBB"}
_PARTS = {"type": "array", "items": {"type": "integer", "minimum": 0}, "maxItems": 4096}


def _view_effect(call) -> str:
    return EDIT if any(call.arguments.get(key) is not None for key in _VIEW_KEYS) else READ


def _view(call) -> dict[str, object]:
    from cdmw.mcp.mesh_tools import ready_document

    a = call.arguments
    values = {key: a[key] for key in _VIEW_KEYS if a.get(key) is not None}
    for name, colour in (values.get("colours") or {}).items():
        if not re.fullmatch(r"#[0-9A-Fa-f]{6}", str(colour)):
            raise ToolError(INVALID_ARGUMENTS, f"colours.{name} must be #RRGGBB.")
    shown = set(values.get("show_parts") or ())
    if shown & set(values.get("hide_parts") or ()):
        raise ToolError(INVALID_ARGUMENTS, "A part can be in show_parts or hide_parts, not both.")
    needs_look = values.get("reset") == "look" or any(key in values for key in _LOOK_KEYS)

    def send() -> bool:
        tab = ready_document(call.context)
        if not getattr(tab, "standalone_rust_view_state_supported", False):
            raise ToolError(UNAVAILABLE, NO_VIEW_STATE)
        if needs_look and not getattr(tab, "standalone_rust_view_look_supported", False):
            raise ToolError(UNAVAILABLE, NO_VIEW_LOOK)
        return tab.set_view_state_in_view(values)

    if not call.context.ui_call(send):
        raise ToolError(FAILED, "The Mesh Editor did not take the view settings.")
    deadline = time.monotonic() + ARRIVE_S
    while time.monotonic() < deadline:
        call.check_cancelled()
        report = call.context.ui_call(
            lambda: getattr(ready_document(call.context), "standalone_rust_view_state", None))
        if report is not None:
            return {"view": dict(report)}
        time.sleep(0.03)
    raise ToolError(FAILED, "The Mesh Editor did not report its view settings.")


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
                         "CDMW refuses what the output cannot hold, as for the button. In Exact output, delete "
                         "works on PAC faces only (not PAM or PAMLOD), and deleting whole Parts (params "
                         "delete_parts) needs Free Edit; untick Include instead. One History step.",
             input_schema=object_schema({"action": {"type": "string", "enum": list(_topology_actions())},
                                         "params": union_schema(PARAMS["topology"], "The action's params: "
                                                                + actions_text(PARAMS["topology"])),
                                         "label": label}, ["action"]),
             effect=EDIT, route="helper:cdmw_command topology", handler=_labelled("topology"),
             runs_on=ON_WORKER),
        Tool(name="mesh.mesh_action", family="mesh", title="Mesh action",
             description="A Mesh Data, Normals, Cleanup or UV action on the shown document's selection, as its "
                         "button does: mirror (axis, in_place), remove_doubles (threshold), "
                         "delete_loose_vertices, compact_orphans, fix_winding, fill_holes, recalculate_normals, "
                         "generate_tangents, flip_normals, sharpen_normals, soften_normals, weighted_normals, "
                         "copy_normals, uv_transform (offset, scale, rotate_degrees, pivot, flip_u, flip_v, "
                         "normalize, align_u, align_v ...). CDMW checks each against the output as for the "
                         "button: in Exact output flip_normals is refused (it reverses face winding), and on PAM "
                         "and PAMLOD the normal and tangent actions are refused outside Free Edit because those "
                         "files store no normals or tangents. generate_tangents that would split vertices along a "
                         "UV seam needs Free Edit. One History step.",
             input_schema=object_schema({"action": {"type": "string", "enum": list(_mesh_actions())},
                                         "params": union_schema(PARAMS["mesh_action"], "The action's params: "
                                                                + actions_text(PARAMS["mesh_action"])),
                                         "label": label}, ["action"]),
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
               description=text + (" Arguments by action (? marks an optional one): " + actions_text(PANELS[family])
                                   if family in PANELS else "")
                           + " CDMW checks each as it checks the panel's own; the result is the history "
                             "before and after and the status line, which says why a command was refused.",
               input_schema=object_schema({"action": {"type": "string", "enum": list(PANEL_COMMANDS[family])},
                                           "arguments": union_schema(PANELS[family], "The action's arguments.")
                                           if family in PANELS else {"type": "object"}}, ["action"]),
               effect=EDIT, route=f"helper:cdmw_command {family}_*", handler=_panel(family), runs_on=ON_WORKER)
          for family, name, title, text in _PANEL_TOOLS],
        Tool(name="mesh.panels", family="mesh", title="Mesh Editor panels",
             description="What the shown document's panels show, as the editor is given them: skeleton and "
                         "bone influence, morph_refit, geometry_layers, cloth, jiggle, physics, collisions, "
                         "replacement (with each part's id), shader_controls, material_colours (each part's "
                         "colour rows with original and alpha, and its edits), emission, translucency, hair, "
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
        Tool(name="mesh.camera", family="mesh", title="Mesh Editor camera",
             description="Read or set the 3D view's camera by numbers: yaw and pitch in degrees, distance from "
                         "the target, and target [x, y, z]; frame first frames the whole model, as Frame All "
                         "does. Values left out stay as they are; with none, it only reads the camera. Only the "
                         "view changes, not the mesh. Returns the camera as the editor holds it.",
             input_schema=object_schema({"yaw": {"type": "number"}, "pitch": {"type": "number", "minimum": -89.4,
                                                                             "maximum": 89.4},
                                         "distance": {"type": "number", "minimum": 0.0001}, "target": _VEC3,
                                         "frame": {"type": "boolean"}}),
             effect=READ, route="helper:set_camera", handler=_camera, runs_on=ON_WORKER),
        Tool(name="mesh.view", family="mesh", title="Mesh Editor view settings",
             description="Read or set how the Mesh Editor shows and selects, as its Selection, brush and Overlay "
                         "appearance panels and the Parts list's eye buttons do: selection_shape, "
                         "selection_operation, selection_xray (also select what is behind the front surface), "
                         "brush_radius in pixels (also Grab's radius), brush_strength (negative only for "
                         "Inflate), brush_falloff, overlay colours as #RRGGBB, wire_width, vertex_size, and parts "
                         "to show or hide by number. reset 'overlay' restores the four overlay colours, "
                         "'colours' the background and screen grid, 'look' the Studio look; it runs before the "
                         "other values. Experimental: lighting_preset picks the View panel's Lighting, and "
                         "wetness (0 to 1), exposure (0.5 to 2) and light_rotation (degrees, -180 to 180) are "
                         "its Wetness, Exposure and Light rotation sliders, which the view uses only under "
                         "'studio_fixed' (look_applies says whether it does now). Values left out stay as they "
                         "are; with none, it only reads. The mesh is not changed, but hiding a part drops it "
                         "from the selection. Returns the settings as the editor holds them, with "
                         "hidden_parts.",
             input_schema=object_schema({
                 "reset": {"type": "string", "enum": ["overlay", "colours", "look"]},
                 "selection_shape": {"type": "string", "enum": ["click", "brush", "rectangle", "lasso"]},
                 "selection_operation": {"type": "string", "enum": ["replace", "add", "subtract", "toggle"]},
                 "selection_xray": {"type": "boolean"},
                 "brush_radius": {"type": "number", "minimum": 4, "maximum": 240},
                 "brush_strength": {"type": "number", "minimum": -1, "maximum": 1},
                 "brush_falloff": {"type": "string", "enum": ["smooth", "linear", "constant"]},
                 "colours": object_schema({"wire": _HEX, "vertex": _HEX, "selection": _HEX,
                                           "live_selection": _HEX, "grid": _HEX}),
                 "wire_width": {"type": "number", "minimum": 0.5, "maximum": 6},
                 "vertex_size": {"type": "number", "minimum": 0.5, "maximum": 10},
                 "show_parts": _PARTS, "hide_parts": _PARTS,
                 "lighting_preset": {"type": "string",
                                     "enum": ["studio_fixed", "neutral_studio", "showcase", "dark"]},
                 "wetness": {"type": "number", "minimum": 0, "maximum": 1},
                 "exposure": {"type": "number", "minimum": 0.5, "maximum": 2},
                 "light_rotation": {"type": "number", "minimum": -180, "maximum": 180}}),
             effect=EDIT, effect_of=_view_effect, route="helper:set_view_state", handler=_view,
             runs_on=ON_WORKER),
        Tool(name="mesh.vertex_inspect", family="mesh", title="Inspect vertex parameters",
             description="The Vertex Parameters inspector on the shown document's selected vertices, as its "
                         "page reads them: each vertex's part, position, UV0, normal and tangent, its skin "
                         "weights (palette slot, skeleton bone, bone name and weight), cloth influence "
                         "(original, effective, fixed), its source vertex and topology lineage, summaries over "
                         "the whole selection, 'capabilities' (whether each channel can be edited here and why "
                         "not), 'bones' (the bones a weight edit can name) and the 'token' mesh_vertex_edit "
                         "needs. Pages of at most 128 vertices: 'page' counts from 0, 'pages' says how many.",
             input_schema=object_schema({"page": {"type": "integer", "minimum": 0, "default": 0},
                                         "page_size": {"type": "integer", "minimum": 1,
                                                       "maximum": VERTEX_PAGE_SIZE,
                                                       "default": VERTEX_PAGE_SIZE}}),
             effect=READ, route="service:RustMeshAuthoringSession.vertex_inspect", handler=_vertex_inspect,
             runs_on=ON_WORKER),
        Tool(name="mesh.vertex_edit", family="mesh", title="Edit vertex parameters",
             description="The Vertex Parameters inspector's Apply on the selected vertices: 'token' is the one "
                         "mesh_vertex_inspect returned for this selection, and only channels its "
                         "'capabilities' mark editable are taken. 'edits' holds one or more channels, for "
                         "example {position: {values: [null, null, 0.25]}} (null keeps an axis), {uv0: {mode: "
                         "offset, values: [0.1, 0]}}, {normal: {values: [0, 0, 1]}} or {weights: {mode: set, "
                         "bone: 3, value: 0.5}}. One History step; inspect again before the next edit.",
             input_schema=object_schema({"token": _TOKEN_SCHEMA, "edits": _VERTEX_EDITS}, ["token", "edits"]),
             effect=EDIT, route="helper:cdmw_command vertex_edit", handler=_vertex_edit, runs_on=ON_WORKER),
        Tool(name="mesh.open_package", family="mesh", title="Open an editable package",
             description="The Output page's Import editable package: open a Free Edit package folder (or its "
                         "file) at 'path' that was edited outside CDMW, for example in Blender, as the button "
                         "does after its chooser. One History step.",
             input_schema=object_schema({"path": {"type": "string", "minLength": 3, "maxLength": 1024}}, ["path"]),
             effect=EDIT, route="helper:cdmw_command import_editable_package", handler=_open_package,
             runs_on=ON_WORKER),
        Tool(name="mesh.output_files", family="mesh", title="Write Mesh Editor files",
             description="Buttons that write files, as they do after their chooser: free_edit (Export Free Edit "
                         "OBJ into the proven package folder), rig (Export rig GLB into 'folder'), morph_preset "
                         "(Export morph preset to 'path'), morph_setup (Save fitting setup to 'path'); 'name' "
                         "names the preset or setup. Paths are checked first: nothing is written inside the game.",
             input_schema=object_schema({"action": {"type": "string",
                                                    "enum": ["free_edit", "rig", "morph_preset", "morph_setup"]},
                                         "folder": {"type": "string", "minLength": 3, "maxLength": 1024},
                                         "path": {"type": "string", "minLength": 3, "maxLength": 1024},
                                         "name": {"type": "string", "maxLength": 128}}, ["action"]),
             effect=OUTPUT, route="helper:cdmw_command export_*", handler=_output, runs_on=ON_WORKER,
             output_paths=("path",), output_folders=("folder",)),
        Tool(name="mesh.findings", family="mesh", title="Mesh findings",
             description="The shown document's validation, as Finish runs it: whether the mesh can be written "
                         "for its output, and each finding with its part and what to do about it.",
             input_schema=object_schema(), effect=READ, route="service:MeshService.validate_export",
             handler=_findings, runs_on=ON_WORKER),
    ]


__all__ = ["mesh_edit_tools", "request_mark", "selection_payload", "settle", "settled"]
