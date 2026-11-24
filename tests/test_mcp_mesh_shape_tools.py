"""AI connections: finding a region by where it is and shaping it with the Sculpt brushes
(mesh_landmarks, mesh_select_region, mesh_sculpt). An AI app without them read 500
vertices, scripted an exported OBJ outside CDMW and scaled the wrong side of the body
(2026-11-24)."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from types import SimpleNamespace


from cdmw.mcp import approvals  # noqa: F401  (the approvals module is loaded as the app loads it)
from cdmw.mcp.mesh_shape_tools import _facing, bone_position, region_vertices
from tests.test_mcp_area_tools import app, connect, profile, settings  # noqa: F401  (fixtures)
from tests.test_mcp_mesh_tool_repairs import answered  # noqa: F401  (fixture)
from tests.test_automation_authoring_commands import editor  # noqa: F401  (fixture)


def _bone(index: int, name: str, position: tuple[float, float, float]) -> SimpleNamespace:
    matrix = (1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, *position, 1.0)
    return SimpleNamespace(index=index, name=name, bind_matrix=matrix)


# The female skeleton's own numbers (phw_01.pab, read 2026-11-24): face and toes at -Z.
_BODY = [
    _bone(0, "Bip01 Pelvis", (0.0, 0.972, 0.0)),
    _bone(1, "Bip01 L Chest", (0.069, 1.41, -0.065)),
    _bone(2, "Bip01 R Chest", (-0.069, 1.41, -0.065)),
    _bone(3, "Bip01 L Foot", (0.19, 0.086, 0.079)),
    _bone(4, "Bip01 L Toe0", (0.207, 0.0, -0.046)),
    _bone(5, "Bip01 R Foot", (-0.19, 0.086, 0.079)),
    _bone(6, "Bip01 R Toe0", (-0.207, 0.0, -0.046)),
]


def test_a_bone_is_where_its_bind_matrix_puts_it_and_the_body_faces_where_its_toes_point() -> None:
    assert bone_position(_BODY[1]) == (0.069, 1.41, -0.065)
    assert bone_position(SimpleNamespace(bind_matrix=())) is None
    facing = _facing(_BODY)
    assert (facing["up"], facing["front"], facing["left"]) == ("+Y", "-Z", "+X")
    assert "yaw 180 looks at the front" in facing["camera"]


def test_a_region_is_the_vertices_in_the_sphere_box_and_bone_weights_together() -> None:
    part = SimpleNamespace(
        vertices=[(0.07, 1.40, -0.10), (0.07, 1.40, 0.05), (-0.07, 1.40, -0.10), (0.0, 1.0, 0.1)],
        bone_indices=[(0,), (0,), (1,), (2,)], bone_weights=[(1.0,), (1.0,), (1.0,), (1.0,)])
    palettes = {0: [_BODY[1], _BODY[2], _BODY[0]]}
    # The left breast: near its bone, and in front of the body (smaller Z).
    sphere = region_vertices([part], [0], sphere=((0.069, 1.41, -0.065), 0.06))
    assert sphere == {"0": [0]}
    front = region_vertices([part], [0], box=((-1, 0, -1), (1, 2, 0)))
    assert front == {"0": [0, 2]}
    left = region_vertices([part], [0], bones=["Bip01 L Chest"], palettes=palettes)
    assert left == {"0": [0, 1]}
    narrowed = region_vertices([part], [0], bones=["bip01 l chest"], box=((-1, 0, -1), (1, 2, 0)),
                               palettes=palettes)
    assert narrowed == {"0": [0]}
    assert region_vertices([part], [0], bones=["Bip01 L Chest"], palettes={}) == {}


def test_select_region_selects_through_the_editor_and_landmarks_say_what_is_missing(answered) -> None:  # noqa: F811
    editor, mcp = answered, answered.mcp
    service, session_id = editor.host.shadow_service, editor.host.shadow_session_id
    part = service.working_mesh(session_id).submeshes[0]
    centre = list(part.vertices[0])
    expected = region_vertices([part], [0], sphere=(centre, 1.0e-6))

    selected = mcp.ok("mesh_select_region", {"parts": [0], "sphere": {"centre": centre, "radius": 1.0e-6}})
    assert selected["done"], selected
    assert selected["region_vertices"] == {"0": len(expected["0"])}
    assert selected["selection"]["vertices"] == len(expected["0"])

    nothing = mcp.error("mesh_select_region", {"sphere": {"centre": [1e4, 1e4, 1e4], "radius": 0.01}})
    assert nothing["code"] == "not_found" and "mesh_landmarks" in nothing["message"]
    assert mcp.error("mesh_select_region", {"parts": [0]})["code"] == "invalid_arguments"
    flipped = mcp.error("mesh_select_region", {"box": {"min": [1, 0, 0], "max": [0, 1, 1]}})
    assert flipped["code"] == "invalid_arguments"

    landmarks = mcp.ok("mesh_landmarks")
    assert landmarks["bounds"]["min"] and landmarks["bounds"]["max"]
    if "facing" not in landmarks:
        assert "No skeleton" in landmarks["message"]


def test_sculpt_sends_one_stroke_and_waits_for_its_history_step(answered, monkeypatch) -> None:  # noqa: F811
    from cdmw.mcp import editor_control, mesh_edit_tools

    editor, mcp = answered, answered.mcp
    sent = []
    monkeypatch.setattr(editor_control, "has_control", lambda call, control: control == "sculpt")

    def fake(call, control, arguments):
        sent.append((control, dict(arguments)))
        return {"ok": True, "state": {"tool": arguments["tool"], "status": "Inflate committed"}}

    monkeypatch.setattr(editor_control, "editor_control", fake)
    monkeypatch.setattr(mesh_edit_tools, "ARRIVE_S", 0.2)
    stroke = {"tool": "inflate", "points": [[0.069, 1.41, -0.12]], "radius": 0.07, "strength": 0.3,
              "symmetry": "x", "dabs": 4}
    result = mcp.ok("mesh_sculpt", stroke)
    assert sent == [("sculpt", stroke)]
    assert result["done"] and result["stroke"]["tool"] == "inflate" and "history" in result

    monkeypatch.setattr(editor_control, "editor_control",
                        lambda call, control, arguments: {"ok": False, "message": "Point 0 is not in the 3D view"})
    refused = mcp.ok("mesh_sculpt", stroke)
    assert not refused["done"] and "not in the 3D view" in refused["message"]
    assert mcp.error("mesh_sculpt", {"tool": "carve", "points": [[0, 0, 0]], "radius": 0.1})["code"] == \
        "invalid_arguments"


def test_the_instructions_keep_an_ai_app_inside_cdmw() -> None:
    from cdmw.mcp.server import INSTRUCTIONS

    assert "Do not export files, write scripts or run other programs" in INSTRUCTIONS
    assert "ask the user before doing anything outside CDMW" in INSTRUCTIONS


def test_export_takes_only_a_full_path(answered) -> None:  # noqa: F811
    error = answered.mcp.error("mesh_export", {"path": "relative\\body.obj"})
    assert error["code"] == "refused" and "absolute" in error["message"]
