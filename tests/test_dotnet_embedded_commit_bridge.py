"""An edit the embedded .NET editor raises must reach the builder's state.

Applying the native update only repaints the preview. Before this bridge existed,
Subdivide and Duplicate Selection on the editor's Topology page mutated the edit
session and nothing else: the builder's mesh, totals, revision and part rows all
kept describing the mesh as it was, so the commands read as doing nothing.
"""

from __future__ import annotations

import os
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from cdmw.domain.mesh import MeshEditResult, MeshEditSelection
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
