from __future__ import annotations

import pytest

from cdmw.domain.mesh import MeshEditCommand, MeshEditSelection
from cdmw.modding.mesh_native_core import native_mesh_core_available
from cdmw.services.mesh_service import MeshService
from tests.test_native_mesh_editor_session import _quad_mesh, _screen_wvp


def _screen_selection(tool: str, target: str) -> dict[str, object]:
    common = {
        "viewport_width": 200.0,
        "viewport_height": 200.0,
        "world_view_projection": _screen_wvp(),
    }
    if tool in {"click", "brush"}:
        click_points = {
            "vertex": (100.0, 100.0),
            "edge": (150.0, 100.0),
            "face": (135.0, 65.0),
        }
        x, y = click_points[target]
        brush = {
            **common,
            "x": 150.0 if tool == "brush" else x,
            "y": 50.0 if tool == "brush" else y,
            "radius_pixels": 120.0 if tool == "brush" else 14.0,
        }
        return {
            "target_mode": target,
            "selection_depth_mode": "xray",
            "paint_sample": tool == "brush",
            "screen_brush": brush,
        }
    region: dict[str, object] = {
        **common,
        "mode": tool,
        "start_x": 90.0,
        "start_y": -10.0,
        "end_x": 210.0,
        "end_y": 110.0,
    }
    if tool == "lasso":
        region["points"] = ((90.0, -10.0), (210.0, -10.0), (210.0, 110.0), (90.0, 110.0))
    return {
        "target_mode": target,
        "selection_depth_mode": "xray",
        "screen_region": region,
    }


@pytest.mark.skipif(not native_mesh_core_available(), reason="native mesh core is unavailable")
@pytest.mark.parametrize("tool", ("click", "brush", "rectangle", "lasso"))
@pytest.mark.parametrize("target", ("vertex", "edge", "face"))
def test_every_viewport_selection_tool_honors_the_selected_element_target(tool: str, target: str) -> None:
    service = MeshService()
    session_id = f"selection-{tool}-{target}"
    service.open_edit_session(_quad_mesh(), session_id=session_id, mode="edit")

    result = service.apply_command(
        session_id,
        MeshEditCommand(
            "select",
            selection=MeshEditSelection(),
            params={
                "operation": "replace",
                "_native_screen_selection_payload": _screen_selection(tool, target),
            },
        ),
    )
    selection = service.session_view(session_id).selection
    populated = {
        "vertex": bool(selection.vertex_map()),
        "edge": bool(selection.edge_map()),
        "face": bool(selection.face_map()),
    }

    assert result.ok
    assert populated[target]
    assert all(not present for domain, present in populated.items() if domain != target)
    assert selection.source_indices == ()
