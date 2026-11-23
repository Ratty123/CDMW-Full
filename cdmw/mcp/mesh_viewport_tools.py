"""The Mesh Editor's view by numbers: what the helper's own lists and overlays show.

These change only what the view shows and what is selected, as the controls do; nothing
in the mesh or its output changes. Each goes to the helper's control by name
(``editor_control``), which answers with that control's state and its reason when it
refuses.
"""

from __future__ import annotations

from cdmw.mcp.errors import INVALID_ARGUMENTS, ToolError
from cdmw.mcp.names import EDIT, READ
from cdmw.mcp.tools import ON_WORKER, Tool, object_schema

#: The Mesh islands list's actions (cdmw_islands_host.rs, ISLAND_HOST_ACTIONS).
ISLAND_ACTIONS = ("state", "select", "select_many", "visibility", "isolate", "show_all", "colours")
_ISLAND_ARGUMENTS: dict[str, tuple[str, ...]] = {
    "state": (), "select": ("part", "island"), "select_many": ("islands",),
    "visibility": ("part", "island", "visible"), "isolate": ("part", "island"), "show_all": (),
    "colours": ("enabled",),
}
#: The view's overlays and inspection aids (cdmw_overlays_host.rs, OVERLAY_HOST_ACTIONS).
OVERLAY_ACTIONS = ("state", "set", "frame_bone", "frame_influence", "select_influence", "inspection")
_OVERLAY_ARGUMENTS: dict[str, tuple[str, ...]] = {
    "state": (), "set": ("deformation_heatmap", "weight_colours", "hide_selection_highlight"),
    "frame_bone": (), "frame_influence": (), "select_influence": (),
    "inspection": ("hide_selection", "light", "light_strength", "veil_screen"),
}
_PART = {"type": "integer", "minimum": 0, "description": "A part's number, as mesh_state lists it."}
_ISLAND = {"type": "integer", "minimum": 0, "description": "An island's number within its part, as action 'state' lists it."}


def _checked(call, table: dict[str, tuple[str, ...]], *, all_required: bool) -> dict[str, object]:
    """The control's arguments: only the action's own, each required or at least one given."""

    a = call.arguments
    action = str(a["action"])
    wanted = table[action]
    extra = sorted(key for key, value in a.items() if key not in {"action", *wanted} and value is not None)
    if extra:
        raise ToolError(INVALID_ARGUMENTS, f"Action {action} takes {', '.join(wanted) or 'nothing more'}; "
                                           f"not {extra[0]}.")
    given = {key: a[key] for key in wanted if a.get(key) is not None}
    missing = [key for key in wanted if key not in given]
    if all_required and missing:
        raise ToolError(INVALID_ARGUMENTS, f"Action {action} needs {', '.join(missing)}.")
    if not all_required and wanted and not given:
        raise ToolError(INVALID_ARGUMENTS, f"Action {action} needs one of {', '.join(wanted)}.")
    return {"action": action, **given}


def _islands(call) -> dict[str, object]:
    from cdmw.mcp.editor_control import control_outcome, editor_control

    arguments = _checked(call, _ISLAND_ARGUMENTS, all_required=True)
    return control_outcome(editor_control(call, "islands", arguments), "islands")


def _overlays(call) -> dict[str, object]:
    from cdmw.mcp.editor_control import control_outcome, editor_control

    arguments = _checked(call, _OVERLAY_ARGUMENTS, all_required=False)
    return control_outcome(editor_control(call, "overlays", arguments), "overlays")


def _state_reads(call) -> str:
    return READ if call.arguments.get("action") == "state" else EDIT


def mesh_viewport_tools() -> list[Tool]:
    return [
        Tool(name="mesh.islands", family="mesh", title="Mesh islands",
             description="The Inspector's Mesh islands list in the shown document, by numbers: state (each "
                         "part's islands with their face counts, which are shown in the view, selected and "
                         "included in the output, and whether the list can be used now); select {part, island} "
                         "(a click on the island's name: its faces become the selection); select_many {islands: "
                         "[{part, island}]}; visibility {part, island, visible} (the View box: the view only, "
                         "not the output); isolate {part, island} (shows only that island within its part and "
                         "selects it); show_all (Show all islands); colours {enabled} (Island colors). The "
                         "mesh is not changed; Include, which changes the output, is mesh_part_options' "
                         "islands. Refused, as the list is disabled, while the editor works on a request or "
                         "outside the Edit comparison view.",
             input_schema=object_schema({
                 "action": {"type": "string", "enum": list(ISLAND_ACTIONS)},
                 "part": _PART, "island": _ISLAND,
                 "islands": {"type": "array", "minItems": 1, "maxItems": 4096,
                             "items": object_schema({"part": _PART, "island": _ISLAND}, ["part", "island"])},
                 "visible": {"type": "boolean"}, "enabled": {"type": "boolean"}}, ["action"]),
             effect=EDIT, effect_of=_state_reads, route="helper:editor_control islands", handler=_islands,
             runs_on=ON_WORKER),
        Tool(name="mesh.overlays", family="mesh", title="View overlays and inspection",
             description="The shown document's view aids, which change only what the view shows: state; set "
                         "{deformation_heatmap (Persistent edit colours: green, yellow and red for small to large "
                         "changes since the mesh opened), weight_colours (the Rig page's Weight colours for its "
                         "bone), hide_selection_highlight}; frame_bone, frame_influence (the Rig page's Frame bone "
                         "and Frame influence, which move the camera only); select_influence (Select influenced "
                         "vertices: replaces the selection, one History step); inspection {hide_selection, light "
                         "(camera, front, side, behind or above), light_strength 0 to 2, veil_screen (1920x1080, "
                         "2560x1440 or 3840x2160)}, the material inspector's preview light and veil net screen "
                         "size. view_capture shows the result.",
             input_schema=object_schema({
                 "action": {"type": "string", "enum": list(OVERLAY_ACTIONS)},
                 "deformation_heatmap": {"type": "boolean"}, "weight_colours": {"type": "boolean"},
                 "hide_selection_highlight": {"type": "boolean"}, "hide_selection": {"type": "boolean"},
                 "light": {"type": "string", "enum": ["camera", "front", "side", "behind", "above"]},
                 "light_strength": {"type": "number", "minimum": 0, "maximum": 2},
                 "veil_screen": {"type": "string", "enum": ["1920x1080", "2560x1440", "3840x2160"]}}, ["action"]),
             effect=EDIT, effect_of=_state_reads, route="helper:editor_control overlays", handler=_overlays,
             runs_on=ON_WORKER),
    ]


__all__ = ["ISLAND_ACTIONS", "OVERLAY_ACTIONS", "mesh_viewport_tools"]
