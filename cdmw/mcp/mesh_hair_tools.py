"""Hair Tools by numbers: the setup, the panel's commands and its local edits.

Hair Tools has three kinds of control, and each goes the way its own goes:

* the setup (``HairSetupDialog``), which chooses the character, Create or Edit and the
  donor, is filled and started from the call as its controls are;
* the panel's commands that CDMW carries out (``hair_begin``, ``hair_color``,
  ``hair_texture``, ``hair_texture_export``, ``hair_import_custom``) are sent as their
  buttons send them, with the file or the head and body their choosers would give, so
  no chooser opens;
* the panel's own edits (prepare, fill, width and density, rigid sections, name ...),
  its motion preview and display options are used by name (``editor_control`` "hair"),
  and the helper answers with the panel's state and its reason when it refuses.

Edits are prepared in the background as after a click; the tool waits until the edit is
prepared and saved (``wait``), then returns the panel's state and the history.
"""

from __future__ import annotations

import threading
import time
from pathlib import Path

from cdmw.mcp.errors import FAILED, INVALID_ARGUMENTS, UNAVAILABLE, ToolError
from cdmw.mcp.names import EDIT, READ
from cdmw.mcp.tools import ON_WORKER, Tool, object_schema

#: What Apply edited DDS… takes; an image is re-encoded to the template's DDS layout.
HAIR_TEXTURE_SUFFIXES = (".dds", ".png", ".jpg", ".jpeg", ".webp", ".bmp")

PREPARE_S = 120.0
#: A lock offset past every lock: the panel's state with its counts and no lock list.
COUNTS_ONLY = 1 << 31
SETUP_S = 180.0
NO_EDITOR_CONTROLS = ("This Mesh Editor helper does not take its hair control from CDMW; it is older than this "
                      "app (host_editor_controls_v1).")
#: The panel's own edits and settings, used by name (cdmw_hair_host.rs, HAIR_HOST_ACTIONS).
LOCAL_ACTIONS = ("state", "select_locks", "prepare", "empty", "fill", "lock_uv", "rigid", "rebind", "convert",
                 "settings", "settle", "reset", "name", "delete", "motion", "display")
#: The panel's commands CDMW carries out, by the name each is sent with.
HOST_ACTIONS = {"begin": "hair_begin", "color": "hair_color", "texture": "hair_texture",
                "texture_export": "hair_texture_export", "import_custom": "hair_import_custom"}
ACTIONS = (*LOCAL_ACTIONS, *HOST_ACTIONS)
#: The arguments each action takes besides 'action' and 'wait'; any other is refused.
ACTION_ARGUMENTS: dict[str, tuple[str, ...]] = {
    "state": ("lock_offset",), "select_locks": ("lock_ids",), "prepare": (), "empty": (),
    "fill": ("preset", "length"), "lock_uv": ("lock_ids", "uv_rect"), "rigid": ("lock_ids",), "rebind": (),
    "convert": (), "settings": ("lock_ids", "width", "density"), "settle": (), "reset": (),
    "name": ("style_name",), "delete": ("lock_ids",),
    "motion": ("play", "test", "damping", "shape_softness", "gravity", "wind"),
    "display": ("show_reference", "show_guides", "show_collisions"),
    "begin": ("head", "body"), "color": ("color",), "texture": ("texture_path", "dds_path"),
    "texture_export": ("texture_path",), "import_custom": ("path",),
}
REQUIRED: dict[str, tuple[str, ...]] = {
    "select_locks": ("lock_ids",), "fill": ("preset",), "lock_uv": ("uv_rect",), "name": ("style_name",),
    "begin": ("head", "body"), "color": ("color",), "texture": ("texture_path", "dds_path"),
    "texture_export": ("texture_path",), "import_custom": ("path",),
}
MOVEMENT_TESTS = ("still", "turn", "nod", "head_and_shoulders", "body_sway", "wind")
_PATH = {"type": "string", "minLength": 3, "maxLength": 1024}
_ARCHIVE_PATH = {"type": "string", "minLength": 3, "maxLength": 512}


def _shown(context):
    from cdmw.mcp.mesh_tools import shown_document

    return shown_document(context)


# ----- the panel's own edits (editor_control "hair") ------------------------------------
def _control(call, arguments: dict[str, object]) -> dict[str, object]:
    """Send one hair control and return its answer (ok, message, state)."""

    from cdmw.mcp.editor_control import editor_control

    return editor_control(call, "hair", arguments)


def _local(call, action: str) -> dict[str, object]:
    from cdmw.mcp.mesh_edit_tools import history_now

    a = call.arguments
    arguments = {"action": action, **{key: a[key] for key in ACTION_ARGUMENTS[action] if a.get(key) is not None}}
    before = history_now(call) if action != "state" else None
    answer = _control(call, arguments)
    state = answer.get("state") or {}
    waited = False
    if answer["ok"] and action != "state" and a.get("wait", True):
        # Prepared in the background, then saved as one History step, as after a click.
        deadline = time.monotonic() + PREPARE_S
        while isinstance(state, dict) and (state.get("preparing") or state.get("busy")):
            call.check_cancelled()
            if time.monotonic() > deadline:
                break
            time.sleep(0.1)
            state = _control(call, {"action": "state", "lock_offset": COUNTS_ONLY}).get("state") or {}
            waited = True
    outcome: dict[str, object] = {"done": bool(answer["ok"]), "hair": state}
    if not answer["ok"]:
        outcome["message"] = answer.get("message") or "Hair Tools did not take it."
    elif isinstance(state, dict) and state.get("preparing"):
        outcome["message"] = "Hair Tools is still preparing the edit; action 'state' shows when it is done."
    if before is not None:
        outcome.update(history_before=before, history=history_now(call))
    if waited:
        outcome["waited"] = True
    return outcome


# ----- the panel's commands CDMW carries out ---------------------------------------------
def _require_new_helper(call) -> None:
    from cdmw.mcp.editor_control import has_control

    if not has_control(call, "hair"):
        raise ToolError(UNAVAILABLE, NO_EDITOR_CONTROLS)


def _hair_character(tab) -> str:
    session = getattr(tab, "standalone_rust_authoring_session", None)
    if session is None:
        return ""
    try:
        state = session.shadow_service._session(session.shadow_session_id).hair_state
    except Exception:
        return ""
    return str(state.payload["template"]["character"]) if state is not None else ""


def _references(call, head: str, body: str) -> str:
    """Find the head and body as Change references' choosers would, and keep them for the command."""

    from cdmw.mcp.mesh_tools import ready_document
    from cdmw.ui.mesh_editor.hair_flow import offer_hair_references
    from cdmw.ui.mesh_editor.hair_reference_resolution import HairReferenceResolution
    from cdmw.ui.shell.tab_registry import DetachedToolWindow

    context = call.context
    found: dict[str, object] = {}

    def character_and_owner():
        tab = ready_document(context)
        character = _hair_character(tab)
        if not character:
            raise ToolError(UNAVAILABLE, "Open a hairstyle with Hair Tools first (mesh_hair_setup).")
        owner = tab.window()
        if isinstance(owner, DetachedToolWindow):
            owner = owner.owner
        return tab, owner, character

    deadline = time.monotonic() + PREPARE_S
    for role, path in (("head", head), ("body", body)):
        done = threading.Event()
        box: dict[str, object] = {}

        def start(role=role, path=path, done=done, box=box) -> None:
            tab, owner, character = character_and_owner()
            resolution = HairReferenceResolution(owner, tab)

            def finished(entry, dependencies, error):
                box["found"] = (entry, dependencies, error)
                resolution.deleteLater()
                done.set()

            resolution.done.connect(finished)
            box["resolution"] = resolution
            resolution.start(role, path, character)

        context.ui_call(start)
        while not done.wait(0.05):
            call.check_cancelled()
            if time.monotonic() > deadline:
                context.ui_call(lambda box=box: box["resolution"].cancel())
                raise ToolError(FAILED, "CDMW did not find the head and body in time.")
        entry, dependencies, error = box["found"]
        if error:
            raise ToolError(INVALID_ARGUMENTS, str(error))
        found[role] = (entry, dependencies)
    return context.ui_call(lambda: offer_hair_references(ready_document(context), found["head"], found["body"]))


def _host(call, action: str) -> dict[str, object]:
    from cdmw.mcp.mesh_edit_tools import NO_PANEL_COMMANDS, _send_edit, _send_output

    a = call.arguments
    from cdmw.mcp.mesh_tools import ready_document

    supported = call.context.ui_call(
        lambda: bool(getattr(ready_document(call.context), "standalone_rust_host_panel_commands_supported", False)))
    if not supported:
        raise ToolError(UNAVAILABLE, NO_PANEL_COMMANDS)
    if action == "color":
        color = [float(value) for value in a["color"]]
        return _send_edit(call, "hair_color", {"color": color})
    if action == "texture":
        dds = Path(str(a["dds_path"]))
        if not dds.is_absolute() or dds.suffix.lower() not in HAIR_TEXTURE_SUFFIXES or not dds.is_file():
            raise ToolError(INVALID_ARGUMENTS, "dds_path must be the full path of an existing .dds, .png, .jpg, "
                                               ".jpeg, .webp or .bmp file; an image is re-encoded to the "
                                               "template's DDS layout.")
        return _send_edit(call, "hair_texture", {"texture_path": str(a["texture_path"]), "dds_path": str(dds)})
    if action == "texture_export":
        return _send_output(call, "hair_texture_export", {"texture_path": str(a["texture_path"])})
    if action == "import_custom":
        _require_new_helper(call)
        from cdmw.ui.mesh_editor.replacement_flow import _given_hair_mesh

        try:
            path = _given_hair_mesh(a["path"])
        except ValueError as error:
            raise ToolError(INVALID_ARGUMENTS, str(error)) from None
        return _send_output(call, "hair_import_custom", {"source_path": path})
    # begin: Change references…, with the head and body found first.
    _require_new_helper(call)
    token = _references(call, str(a["head"]), str(a["body"]))
    return _send_output(call, "hair_begin", {"change_references": True, "references_token": token})


def _hair(call) -> dict[str, object]:
    a = call.arguments
    action = str(a["action"])
    allowed = {"action", "wait", *ACTION_ARGUMENTS[action]}
    extra = sorted(key for key, value in a.items() if key not in allowed and value is not None)
    if extra:
        raise ToolError(INVALID_ARGUMENTS, f"Action {action} takes {', '.join(ACTION_ARGUMENTS[action]) or 'nothing more'}; "
                                           f"not {extra[0]}.")
    missing = [key for key in REQUIRED.get(action, ()) if a.get(key) is None]
    if missing:
        raise ToolError(INVALID_ARGUMENTS, f"Action {action} needs {', '.join(missing)}.")
    if action in HOST_ACTIONS:
        return _host(call, action)
    return _local(call, action)


def _hair_effect(call) -> str:
    action = str(call.arguments.get("action") or "")
    return READ if action == "state" else EDIT


# ----- the setup dialog -------------------------------------------------------------------
_MODES = {"create": "generated", "edit": "existing"}


def _setup_document(context):
    """The document Hair Tools starts in: the shown one, or a new one beside an unfinished edit,
    so that starting never asks whether to finish or discard it."""

    from cdmw.mcp.mesh_tools import _view
    from cdmw.ui.mesh_editor.live_edit.end_edit_prompt import has_pending_edit

    view = _view(context)
    if view is None:
        raise ToolError(UNAVAILABLE, "Open the Mesh Editor first (mesh_open, or its rail page).")
    tab = getattr(view, "active", None) or view
    if has_pending_edit(tab):
        opened = getattr(view, "open_new_document", None)
        tab = opened() if callable(opened) else None
        if tab is None:
            raise ToolError(UNAVAILABLE, "The shown document has an unfinished edit and no other can be opened; "
                                         "finish or close it first.")
    return tab


def _setup(call) -> dict[str, object]:
    from cdmw.domain.hair_characters import HAIR_CHARACTERS
    from cdmw.mcp.mesh_tools import _act

    context = call.context
    a = call.arguments
    character = str(a["character"])
    names = {profile.name.casefold(): profile.name for profile in HAIR_CHARACTERS}
    if character.casefold() not in names:
        raise ToolError(INVALID_ARGUMENTS, f"The characters are {', '.join(names.values())}.")
    character = names[character.casefold()]
    mode = str(a.get("mode") or "create")
    custom = bool(a.get("custom_donor_material", False))
    donor = str(a.get("donor") or "").replace("\\", "/").strip().strip("/")
    if (mode == "edit" or custom) and not donor:
        raise ToolError(INVALID_ARGUMENTS, "Give 'donor', the hairstyle's archive path (.pac), to "
                                           + ("edit." if mode == "edit" else "take its material and textures."))
    box: dict[str, object] = {}

    def open_setup() -> dict[str, object]:
        from cdmw.ui.mesh_editor.hair_flow import start_hair_workflow

        tab = _setup_document(context)
        dialog = start_hair_workflow(tab, _MODES[mode], character=character, target_path=donor)
        if mode == "create":
            dialog.keep_scalp_cap.setChecked(bool(a.get("keep_scalp_cap", True)))
            dialog.choose_donor_material.setChecked(custom)
        dialog.finished.connect(lambda result: box.setdefault("result", int(result)))
        box["dialog"] = dialog
        return {"opened": True}

    _act(call, open_setup)
    started = False
    deadline = time.monotonic() + SETUP_S

    def step() -> str:
        """Press Start once the setup offers it, as a click would; '' while it is not ready."""

        dialog = box["dialog"]
        if "result" in box:
            return "closed"
        picker = dialog._picker
        if picker is None or getattr(picker, "_closed", False):
            return ""
        if mode == "create" and not custom:
            if dialog.waiting_start.isEnabled():
                dialog._start()
                return "started"
            return ""
        # The embedded chooser selects the donor itself once it has checked it (preferred path).
        key = picker._key()
        row = picker._rows.get(key) if key is not None else None
        if (row is not None and str(row.path).casefold() == donor.casefold() and key in picker._verified
                and picker.choose.isEnabled()):
            picker._choose()
            return "started"
        return ""

    def status() -> str:
        dialog = box["dialog"]
        text = str(dialog.status.text() or "")
        picker = dialog._picker
        if picker is not None and not getattr(picker, "_closed", False):
            text = f"{text} {picker.status.text()}".strip()
        return text

    while True:
        call.check_cancelled()
        state = context.ui_call(step)
        if state == "started":
            started = True
        if state == "closed" or (started and "result" in box):
            break
        if time.monotonic() > deadline:
            text = context.ui_call(status)
            context.ui_call(lambda: box["dialog"].reject())
            raise ToolError(FAILED, f"Hair Tools did not start in time, so its setup was closed. It said: {text}")
        time.sleep(0.1)
    accepted = box.get("result") == 1
    outcome: dict[str, object] = {"started": accepted, "character": character, "mode": mode}
    if donor:
        outcome["donor"] = donor
    if accepted:
        outcome["message"] = ("Hair Tools is opening the hairstyle; mesh_state says when the editor is ready, and "
                              "mesh_hair with action 'state' reads the panel.")
    else:
        outcome["message"] = "Hair Tools did not start: " + (context.ui_call(status) or "it was cancelled.")
    return outcome


def mesh_hair_tools() -> list[Tool]:
    number = {"type": "number"}
    lock_ids = {"type": "array", "maxItems": 4096, "items": {"type": "integer", "minimum": 0},
                "description": "Locks by id, as action 'state' lists them; selects them first (Settings, "
                               "strand card UV, rigid and delete act on the selected locks)."}
    return [
        Tool(name="mesh.hair", family="mesh", title="Hair Tools",
             description=(
                 "Hair Tools' panel for the hairstyle open in the shown document (mesh_hair_setup opens one). "
                 "'action' picks what it does, each with its own arguments: "
                 "state {lock_offset} (the panel: locks with id, kind and part, 400 at a time from "
                 "lock_offset, sections, the selected locks, display, motion, and whether an edit is still "
                 "being prepared; an edit's answer gives the counts only); select_locks {lock_ids}; "
                 "prepare (Prepare existing hair sections); empty (Start empty); fill {preset: cropped, bob, "
                 "long or ponytail, length 0.08 to 0.6} (Starter shapes); settings {width, density 1 to 32, "
                 "lock_ids} (Apply to selected locks); lock_uv {uv_rect [u, v, width, height] or null, "
                 "lock_ids} (Selected strand card; the hair section of mesh_panels lists each part's "
                 "uv_presets); rigid {lock_ids} (Mark selected scalp sections as rigid); delete {lock_ids}; "
                 "rebind (Rebind to changed head); convert (Convert to ordinary mesh); settle (Use settled "
                 "shape, after motion has played); reset (the motion preview); name {style_name} (Apply "
                 "name; the target stem is the template's and is not changed); motion {play, test, damping 0 "
                 "to 20, shape_softness 0 to 0.005, gravity -20 to 0, wind [x, y, z]}; display "
                 "{show_reference (the character bust), show_guides, show_collisions}; "
                 "begin {head, body} (Change references…: the archive paths of a compatible head and base "
                 "body, found as its choosers would); color {color [r, g, b] 0 to 1} (Apply hair color); "
                 "texture {texture_path, dds_path} (Apply edited DDS…: texture_path is one of the hair "
                 "section's textures, dds_path the edited DDS or image); texture_export {texture_path} (Open in "
                 "Texture Editor); import_custom {path} (Import custom hair mesh…: an OBJ, DAE, glTF or GLB "
                 "file). Each is checked as its button checks it; 'message' carries the panel's reason "
                 "when it refuses. An edit waits until it is prepared and saved as one History step "
                 "('wait', default true) and returns the history before and after."),
             input_schema=object_schema({
                 "action": {"type": "string", "enum": list(ACTIONS)},
                 "wait": {"type": "boolean", "default": True},
                 "lock_offset": {"type": "integer", "minimum": 0},
                 "lock_ids": lock_ids,
                 "preset": {"type": "string", "enum": ["cropped", "bob", "long", "ponytail"]},
                 "length": {"type": "number", "minimum": 0.08, "maximum": 0.6},
                 "width": {"type": "number", "minimum": 0.0001, "maximum": 10},
                 "density": {"type": "integer", "minimum": 1, "maximum": 32},
                 "uv_rect": {"type": ["array", "null"], "minItems": 4, "maxItems": 4,
                             "items": {"type": "number", "minimum": 0, "maximum": 1}},
                 "style_name": {"type": "string", "minLength": 1, "maxLength": 64},
                 "play": {"type": "boolean"},
                 "test": {"type": "string", "enum": list(MOVEMENT_TESTS)},
                 "damping": {"type": "number", "minimum": 0, "maximum": 20},
                 "shape_softness": {"type": "number", "minimum": 0, "maximum": 0.005},
                 "gravity": {"type": "number", "minimum": -20, "maximum": 0},
                 "wind": {"type": "array", "minItems": 3, "maxItems": 3,
                          "items": {"type": "number", "minimum": -30, "maximum": 30}},
                 "show_reference": {"type": "boolean"}, "show_guides": {"type": "boolean"},
                 "show_collisions": {"type": "boolean"},
                 "head": _ARCHIVE_PATH, "body": _ARCHIVE_PATH,
                 "color": {"type": "array", "minItems": 3, "maxItems": 3,
                           "items": {**number, "minimum": 0, "maximum": 1}},
                 "texture_path": {"type": "string", "minLength": 1, "maxLength": 512},
                 "dds_path": _PATH, "path": _PATH}, ["action"]),
             effect=EDIT, effect_of=_hair_effect, route="helper:editor_control hair + cdmw_command hair_*",
             handler=_hair, runs_on=ON_WORKER),
        Tool(name="mesh.hair_setup", family="mesh", title="Start Hair Tools",
             description="Hair Tools (Experimental) setup, filled and started as its controls are: 'character' "
                         "(Kliff, Damiane or Oongka), 'mode' create (Create hairstyle: an empty scalp to draw "
                         "on) or edit (Edit hairstyle: 'donor', the registered hairstyle's archive path), "
                         "'custom_donor_material' (Choose donor material & textures...: 'donor' gives them) and "
                         "'keep_scalp_cap' (Keep donor scalp cap, create only). Waits until the setup has "
                         "checked the choice and started the editor scene; an unfinished edit in the shown "
                         "document is kept, the hairstyle opening in a new document. Not tested in game.",
             input_schema=object_schema({
                 "character": {"type": "string", "enum": ["Kliff", "Damiane", "Oongka"]},
                 "mode": {"type": "string", "enum": list(_MODES), "default": "create"},
                 "donor": _ARCHIVE_PATH,
                 "custom_donor_material": {"type": "boolean", "default": False},
                 "keep_scalp_cap": {"type": "boolean", "default": True}}, ["character"]),
             effect=EDIT, route="ui:hair_flow.start_hair_workflow", handler=_setup, runs_on=ON_WORKER),
    ]


__all__ = ["ACTIONS", "ACTION_ARGUMENTS", "HOST_ACTIONS", "LOCAL_ACTIONS", "mesh_hair_tools"]
