"""Element type and selection gesture are two things, and one field held both.

`selection_mode` meant "which element kind does this action need" on an action
descriptor and "how is the reader dragging" in the resident protocol. The two
met in `MeshEditorController.active_selection_mode`, and the tab normalised
whatever arrived through `normalize_mesh_selection_shape`, whose alias table
maps `vertex`, `edge`, and `face` to `brush`.

So picking a tool that declares an element type reset the reader's gesture:
Lasso became Brush, silently, mid-session. That is ME-EDIT-004's stated impact,
and these tests pin the separation rather than the alias table that hid it.
"""

from __future__ import annotations

import pytest

from cdmw.modding.mesh_parser import ParsedMesh, SubMesh
from cdmw.ui.mesh_editor.actions import (
    mesh_editor_actions_by_key,
    normalize_mesh_element_type,
    normalize_mesh_selection_shape,
)
from cdmw.ui.mesh_editor.controller import MeshEditorController


_EDGE_ACTIONS = ("loop_cut", "edge_split", "bridge")


def _controller() -> MeshEditorController:
    return MeshEditorController()


def _opened_controller() -> MeshEditorController:
    controller = _controller()
    controller.open_mesh(
        ParsedMesh(
            path="vocabulary.pac",
            format="pac",
            submeshes=[
                SubMesh(
                    name="part",
                    material="part",
                    vertices=[(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)],
                    faces=[(0, 1, 2)],
                )
            ],
        ),
        mode="edit",
    )
    return controller


@pytest.mark.parametrize("key", _EDGE_ACTIONS)
def test_an_actions_element_type_does_not_become_the_gesture(key: str) -> None:
    controller = _opened_controller()
    controller.active_selection_mode = "lasso"

    # The action itself is refused without a selection; what is under test is
    # the tool state it leaves behind, which is written before that refusal.
    controller.apply_editor_action(mesh_editor_actions_by_key()[key])

    assert controller.active_selection_mode == "lasso"
    assert controller.active_element_type == "edge"


def test_the_controller_opens_on_a_gesture_and_an_element_type() -> None:
    controller = _controller()

    assert controller.active_selection_mode == "brush"
    assert controller.active_element_type == "vertex"


@pytest.mark.parametrize("key", _EDGE_ACTIONS)
def test_the_descriptor_declares_an_element_type(key: str) -> None:
    action = mesh_editor_actions_by_key()[key]

    assert action.element_type == "edge"
    # Kept as an alias because a Qt button property and the shell bridge read
    # it by that name; it is not a second place to set the value.
    assert action.selection_mode == "edge"


def test_no_action_declares_a_gesture_as_its_element_type() -> None:
    # The overload was only ever wrong in one direction: every descriptor value
    # is an element kind. If one ever holds a gesture, the two have merged again.
    for action in mesh_editor_actions_by_key().values():
        assert action.element_type in {"", "vertex", "edge", "face", "part"}, action.key


def test_element_types_normalize_to_themselves_rather_than_to_brush() -> None:
    for value in ("vertex", "edge", "face", "part"):
        assert normalize_mesh_element_type(value) == value
    assert normalize_mesh_element_type("select_edge") == "edge"
    assert normalize_mesh_element_type("") == "vertex"
    assert normalize_mesh_element_type("lasso") == "vertex"


def test_the_shape_alias_table_is_still_there_for_callers_outside_this_split() -> None:
    # `normalize_mesh_selection_shape` keeps folding element names onto brush.
    # That is the compatibility path for a caller that has not been separated
    # yet; what changed is that the Mesh Editor no longer routes through it.
    assert normalize_mesh_selection_shape("edge") == "brush"
    assert normalize_mesh_selection_shape("lasso") == "lasso"


def test_the_protocol_carries_both_names_under_their_own_keys() -> None:
    """The session_state payload separates gesture from element kind.

    The helper whitelists `selection_mode` as brush/lasso/rectangle and ignores
    anything else, so an element kind sent under that key was dropped on its
    side and normalised onto brush on ours. Both now travel under their own
    name, and the helper keeps reading the one it already read.

    Built through the real payload method with a stub transport rather than
    asserted against the source, because what matters is the dict that reaches
    the helper.
    """
    from cdmw.ui.mesh_editor.tab_dotnet_payloads import MeshEditorDotNetPayloadMixin

    controller = _opened_controller()
    controller.active_selection_mode = "lasso"
    controller.active_element_type = "edge"
    sent: list[dict] = []

    class _Tab(MeshEditorDotNetPayloadMixin):
        current_selection_mode = "brush"
        current_element_type = "vertex"
        standalone_dotnet_process_generation = 1

        def _dotnet_target_controller(self):
            return controller

        def _dotnet_selection_payload(self, selection):
            return {}

        def _send_dotnet_protocol_message(self, payload):
            sent.append(payload)
            return True

    assert _Tab()._send_dotnet_session_state() is True
    payload = sent[0]
    assert payload["selection_mode"] == "lasso"
    assert payload["element_type"] == "edge"


def test_the_protocol_falls_back_to_the_tabs_own_values() -> None:
    from cdmw.ui.mesh_editor.tab_dotnet_payloads import MeshEditorDotNetPayloadMixin

    controller = _opened_controller()
    controller.active_selection_mode = ""
    controller.active_element_type = ""
    sent: list[dict] = []

    class _Tab(MeshEditorDotNetPayloadMixin):
        current_selection_mode = "rectangle"
        current_element_type = "face"
        standalone_dotnet_process_generation = 1

        def _dotnet_target_controller(self):
            return controller

        def _dotnet_selection_payload(self, selection):
            return {}

        def _send_dotnet_protocol_message(self, payload):
            sent.append(payload)
            return True

    _Tab()._send_dotnet_session_state()
    assert sent[0]["selection_mode"] == "rectangle"
    assert sent[0]["element_type"] == "face"
