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
_PART = {"type": "integer", "minimum": 0, "description": "A part's number, as mesh_state lists it."}
_ISLAND = {"type": "integer", "minimum": 0, "description": "An island's number within its part, as action 'state' lists it."}


def _islands(call) -> dict[str, object]:
    from cdmw.mcp.editor_control import control_outcome, editor_control

    a = call.arguments
    action = str(a["action"])
    wanted = _ISLAND_ARGUMENTS[action]
    extra = sorted(key for key, value in a.items() if key not in {"action", *wanted} and value is not None)
    if extra:
        raise ToolError(INVALID_ARGUMENTS, f"Action {action} takes {', '.join(wanted) or 'nothing more'}; "
                                           f"not {extra[0]}.")
    missing = [key for key in wanted if a.get(key) is None]
    if missing:
        raise ToolError(INVALID_ARGUMENTS, f"Action {action} needs {', '.join(missing)}.")
    arguments = {"action": action, **{key: a[key] for key in wanted}}
    return control_outcome(editor_control(call, "islands", arguments), "islands")


def _islands_effect(call) -> str:
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
             effect=EDIT, effect_of=_islands_effect, route="helper:editor_control islands", handler=_islands,
             runs_on=ON_WORKER),
    ]


__all__ = ["ISLAND_ACTIONS", "mesh_viewport_tools"]
