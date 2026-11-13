"""The window's layer commands run on the action worker (2026-11-13).

Activate, rename, show or hide and move each take the session's lock, which a
draft autosave holds while it opens the native session; since a native open may
wait a minute on a busy machine (7ab62e5e8), running them from the window could
block it that long. The review of 7ab62e5e8 asked for them to go to a worker,
as Delete already did.
"""

from __future__ import annotations

from uuid import uuid4

import pytest

from cdmw.domain.mesh import MeshEditCommand, MeshEditSelection
from cdmw.modding.mesh_native_availability import native_mesh_core_available
from cdmw.services.mesh_service import GEOMETRY_LAYER_WORKER_ACTION, MeshService
import cdmw.ui.mesh_editor.tab  # noqa: F401  (loads the facade the mixins use)
from cdmw.ui.mesh_editor.tab_dotnet_named_commands import MeshEditorDotNetNamedCommandMixin
from tests.test_mesh_geometry_layers import _layer_mesh


class _Tab:
    def __init__(self) -> None:
        self.started: list[tuple[object, str, dict]] = []

    def _start_dotnet_action_worker(self, controller, command, *, command_name, request_payload):
        self.started.append((command, command_name, dict(request_payload)))
        return True

    @staticmethod
    def _standalone_native_payload_int(value, default):
        return int(value) if value is not None else default


class _Controller:
    def __getattr__(self, name):  # the window must not call the service itself
        raise AssertionError(f"the layer command ran {name} on the window's thread")


@pytest.mark.parametrize("command, payload", [
    ("layer_activate", {"layer_id": "base"}),
    ("layer_rename", {"layer_id": "base", "name": "Body"}),
    ("layer_visibility", {"layer_id": "base", "visible": False}),
    ("layer_move", {"layer_id": "base", "direction": 1}),
])
def test_each_layer_command_starts_the_worker(command, payload) -> None:
    tab = _Tab()
    handle = MeshEditorDotNetNamedCommandMixin._handle_dotnet_layer_command
    assert handle(tab, _Controller(), command, {"command": command, **payload}) is True
    (worker_command, command_name, request_payload), = tab.started
    assert worker_command.action == GEOMETRY_LAYER_WORKER_ACTION
    assert worker_command.params["command"] == command and worker_command.params["layer_id"] == "base"
    assert command_name == command and request_payload["command"] == command


@pytest.mark.skipif(not native_mesh_core_available(), reason="the native mesh core is not built")
def test_the_worker_action_changes_the_layer_as_the_direct_calls_did() -> None:
    service = MeshService()
    session_id = f"layer-worker-{uuid4().hex}"
    service.open_edit_session(_layer_mesh(), session_id=session_id, mode="edit")
    try:
        service.apply_command(session_id, MeshEditCommand(
            "select", selection=MeshEditSelection.from_maps(faces_by_submesh={0: (0,)}), params={"operation": "replace"}))
        service.copy_selection(session_id, target="face")
        service.paste_selection(session_id)
        layer_id = service.geometry_layer_state(session_id)["layers"][-1]["layer_id"]

        def run(command, **params):
            return service.apply_command(session_id, MeshEditCommand(
                GEOMETRY_LAYER_WORKER_ACTION, params={"command": command, "layer_id": layer_id, **params}, mode="edit"))

        assert run("layer_rename", name="Variant").ok
        assert run("layer_visibility", visible=False).ok
        layers = {item["layer_id"]: item for item in service.geometry_layer_state(session_id)["layers"]}
        assert layers[layer_id]["name"] == "Variant" and layers[layer_id]["visible"] is False
        assert run("layer_activate").ok
        assert service.geometry_layer_state(session_id)["active_layer_id"] == layer_id
        with pytest.raises(ValueError, match="Unsupported mesh edit action"):
            run("layer_explode")
    finally:
        service.close_edit_session(session_id)
