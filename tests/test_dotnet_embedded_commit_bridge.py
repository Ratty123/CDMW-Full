"""An edit the embedded .NET editor raises must reach the builder's state.

Applying the native update only repaints the preview. Before this bridge existed,
Subdivide and Duplicate Selection on the editor's Topology page mutated the edit
session and nothing else: the builder's mesh, totals, revision and part rows all
kept describing the mesh as it was, so the commands read as doing nothing.
"""

from __future__ import annotations

import os
from types import SimpleNamespace

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from cdmw.domain.mesh import MeshEditResult, MeshEditSelection
from cdmw.ui.mesh_editor.controller import MeshEditorNativeUpdate
from cdmw.ui.mesh_editor import tab as _mesh_editor_tab_facade  # noqa: F401  (loads the compat facade)
from cdmw.ui.mesh_editor.tab_dotnet_payloads import MeshEditorDotNetPayloadMixin
from cdmw.ui.mesh_editor.tab_interaction import MeshEditorInteractionMixin


# Both mixins, because the payload parser leans on the interaction mixin's
# coercion helpers. Composing only one silently yields an empty selection.
class _Bridge(MeshEditorDotNetPayloadMixin, MeshEditorInteractionMixin):
    def __init__(self, builder: object) -> None:
        self._builder = builder
        self.runtime_events: list[tuple[str, dict[str, object]]] = []

    def active_builder(self) -> object:
        return self._builder

    def _record_runtime_event(self, name: str, **fields: object) -> None:
        self.runtime_events.append((name, dict(fields)))


def _result(action: str = "subdivide", revision: int = 7) -> MeshEditResult:
    return MeshEditResult(action=action, status="ok", revision=revision)


def _builder_recording_commits() -> SimpleNamespace:
    calls: list[dict[str, object]] = []

    def commit(result, *, action_key="", action_text="", selection=None) -> bool:
        calls.append(
            {
                "action_key": action_key,
                "action_text": action_text,
                "selection": selection,
                "revision": int(result.revision),
            }
        )
        return True

    return SimpleNamespace(_mesh_editor_commit_dotnet_edit_result=commit, calls=calls)


def test_a_command_the_editor_raised_is_committed_to_the_builder() -> None:
    builder = _builder_recording_commits()
    bridge = _Bridge(builder)

    assert bridge._commit_embedded_edit_result(
        _result(),
        command_name="subdivide",
        request_payload={"local_selection": {"vertices_by_submesh": {"0": [1, 2, 3]}}},
    )

    assert len(builder.calls) == 1
    call = builder.calls[0]
    assert call["action_key"] == "subdivide"
    assert call["revision"] == 7
    # The selection the command ran with has to travel with it, or the builder
    # cannot describe which part the edit landed on.
    assert isinstance(call["selection"], MeshEditSelection)
    assert not call["selection"].is_empty()


def test_the_action_name_falls_back_to_the_result_when_the_command_is_unnamed() -> None:
    builder = _builder_recording_commits()
    bridge = _Bridge(builder)

    assert bridge._commit_embedded_edit_result(_result(action="duplicate"))

    call = builder.calls[0]
    assert call["action_key"] == "duplicate"
    assert call["action_text"] == "duplicate"
    assert call["selection"] is None


def test_a_builder_without_the_bridge_is_not_an_error() -> None:
    # Placement builders and the standalone tab have no mesh-edit state to
    # commit into; the editor still runs, so this must stay quiet.
    bridge = _Bridge(SimpleNamespace())
    assert bridge._commit_embedded_edit_result(_result()) is False
    assert bridge.runtime_events == []


def test_a_failing_builder_commit_is_reported_rather_than_raised() -> None:
    def explode(_result, **_kwargs) -> bool:
        raise RuntimeError("session went away")

    bridge = _Bridge(SimpleNamespace(_mesh_editor_commit_dotnet_edit_result=explode))

    # A raise here would escape into the protocol reader and take the editor
    # down over a bookkeeping failure.
    assert bridge._commit_embedded_edit_result(_result()) is False
    assert [name for name, _ in bridge.runtime_events] == ["mesh_editor_embedded_commit_failed"]


@pytest.mark.parametrize(
    "command_name",
    ["clear_selection", "select_all", "grow", "shrink", "invert"],
)
def test_direct_selection_aliases_publish_once_without_derived_workspace_refresh(
    command_name: str,
) -> None:
    bridge = _Bridge(_builder_recording_commits())
    bridge.standalone_dotnet_target_embedded = True
    embedded_applies: list[object] = []
    workspace_refreshes: list[bool] = []
    native_sends: list[object] = []
    session_selection_flags: list[bool] = []
    update = MeshEditorNativeUpdate(
        selection_groups=({"source_submesh_index": 0, "face_indices": (0, 1)},),
        refresh_selection=True,
    )
    controller = SimpleNamespace(native_update_for_result=lambda _result: update)
    bridge._apply_embedded_native_update = lambda payload: embedded_applies.append(payload) or True
    bridge._refresh_embedded_workspace_from_builder = (
        lambda *, include_derived=True, session_view=None: workspace_refreshes.append(bool(include_derived))
    )
    bridge._send_dotnet_native_update = (
        lambda payload, **_kwargs: native_sends.append(payload) or True
    )
    bridge._send_dotnet_session_state = (
        lambda *, include_selection=True, session_view=None: session_selection_flags.append(bool(include_selection)) or True
    )
    bridge._send_dotnet_cached_morph_state = lambda **_kwargs: True
    bridge._set_dotnet_status = lambda *_args, **_kwargs: None
    summary_refreshes: list[bool] = []
    bridge._refresh_embedded_active_selection_summary = (
        lambda *, selection=None: summary_refreshes.append(True)
    )

    assert bridge._apply_dotnet_result_update(
        controller,
        MeshEditResult(action="select", status="ok", revision=7),
        command_name=command_name,
        request_payload={"request_id": 12},
    )

    assert embedded_applies == []
    assert len(bridge._builder.calls) == 1
    assert bridge._builder.calls[0]["action_key"] == command_name
    assert workspace_refreshes == [False]
    assert native_sends == [update]
    assert session_selection_flags == [False]
    assert summary_refreshes == [True]
