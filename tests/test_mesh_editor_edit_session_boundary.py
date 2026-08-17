"""Finish Edit Mesh has to be a boundary, not a hopeful sequence of steps.

The state machine is unit-tested on its own; this exercises the tab wiring, so
that a helper removed or a transition dropped fails here rather than at the
moment a reader clicks Finish. The case that matters most is the one that used
to report success: the resident renderer dying partway through a finish.
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication

from cdmw.services.mesh_edit_session_state import MeshEditSessionState as S
from cdmw.ui.mesh_editor import MeshEditorTab
from tests.test_mesh_editor_action_bar import (
    _EmbeddedMeshBuilder,
    _FakeProcess,
    _install_shared_dotnet_test_process,
)


def _mounted_tab(name: str):
    app = QApplication.instance() or QApplication([])
    settings = QSettings("CDMWTests", name)
    settings.clear()
    tab = MeshEditorTab(settings=settings)
    builder = _EmbeddedMeshBuilder()
    tab.mount_embedded_builder(builder)
    process = _FakeProcess(tab)
    process._state = process.Running
    tab.standalone_dotnet_target_embedded = True
    tab.standalone_dotnet_target_controller = builder.controller
    tab._connect_dotnet_protocol(process)
    _install_shared_dotnet_test_process(tab, process)
    return app, tab, builder, process


def _teardown(app, tab, builder) -> None:
    app.processEvents()
    tab.deleteLater()
    builder.deleteLater()
    app.processEvents()


def _open_edit_session(tab) -> None:
    tab.standalone_dotnet_edit_session.transition(S.PREPARING_EDIT, reason="test")
    tab.standalone_dotnet_edit_session.transition(S.EDIT_ACTIVE, reason="test")


def test_a_new_tab_starts_idle_and_reports_it() -> None:
    app, tab, builder, _process = _mounted_tab("MeshEditorSessionIdle")

    assert tab.standalone_dotnet_edit_session.state is S.BUILDER_IDLE
    snapshot = builder._mesh_editor_embedded_runtime_diagnostics()["edit_session"]
    assert snapshot["state"] == "builder_idle"
    assert snapshot["has_uncommitted_edits"] is False
    assert snapshot["accepts_commands"] is False

    _teardown(app, tab, builder)


def test_a_mesh_edit_scene_frame_opens_the_session() -> None:
    app, tab, builder, _process = _mounted_tab("MeshEditorSessionEntry")
    tab.standalone_dotnet_scene_desired["interaction_mode"] = "mesh_edit"

    tab._observe_edit_session_from_scene_frame()

    assert tab.standalone_dotnet_edit_session.state is S.EDIT_ACTIVE
    assert tab.standalone_dotnet_edit_session.accepts_commands

    # A repeated frame is not a second entry.
    generation = tab.standalone_dotnet_edit_session.generation
    tab._observe_edit_session_from_scene_frame()
    assert tab.standalone_dotnet_edit_session.generation == generation

    _teardown(app, tab, builder)


def test_a_placement_scene_frame_does_not_open_a_session() -> None:
    app, tab, builder, _process = _mounted_tab("MeshEditorSessionPlacement")
    tab.standalone_dotnet_scene_desired["interaction_mode"] = "placement"

    tab._observe_edit_session_from_scene_frame()

    assert tab.standalone_dotnet_edit_session.state is S.BUILDER_IDLE

    _teardown(app, tab, builder)


def test_losing_the_renderer_mid_edit_puts_the_session_into_recovery() -> None:
    app, tab, builder, _process = _mounted_tab("MeshEditorSessionRecovery")
    _open_edit_session(tab)

    tab._stop_standalone_dotnet_editor_process()

    assert tab.standalone_dotnet_edit_session.state is S.EDIT_RECOVERY_REQUIRED
    assert tab.standalone_dotnet_edit_session.has_uncommitted_edits
    # And it cannot be talked back into committing.
    assert not tab.standalone_dotnet_edit_session.transition(
        S.EDIT_COMMITTED, reason="test"
    ).accepted

    _teardown(app, tab, builder)


def test_losing_the_renderer_with_no_open_edit_does_not_invent_a_session() -> None:
    app, tab, builder, _process = _mounted_tab("MeshEditorSessionIdleStop")

    tab._stop_standalone_dotnet_editor_process()

    assert tab.standalone_dotnet_edit_session.state is S.BUILDER_IDLE

    _teardown(app, tab, builder)


def test_a_session_in_recovery_refuses_to_complete_a_finish() -> None:
    """The case that used to report a saved edit over a lost working state."""
    app, tab, builder, _process = _mounted_tab("MeshEditorSessionRecoveryFinish")
    _open_edit_session(tab)
    tab.standalone_dotnet_edit_session.transition(S.FINISHING_EDIT, reason="test")
    tab.standalone_dotnet_edit_session.require_recovery(reason="renderer_died")
    # A finish was armed and the acknowledgement arrives after the loss.
    tab.standalone_dotnet_finish_scene_pending = {"request_payload": {}}

    assert tab._complete_embedded_dotnet_edit_mode_finish() is True

    assert tab.standalone_dotnet_edit_session.state is S.EDIT_RECOVERY_REQUIRED
    assert tab.standalone_dotnet_finish_scene_pending is None

    _teardown(app, tab, builder)


def test_closing_the_standalone_session_returns_the_machine_to_idle() -> None:
    app, tab, builder, _process = _mounted_tab("MeshEditorSessionClose")
    _open_edit_session(tab)

    tab.close_standalone_session()

    assert tab.standalone_dotnet_edit_session.state is S.BUILDER_IDLE
    assert not tab.standalone_dotnet_edit_session.has_uncommitted_edits

    _teardown(app, tab, builder)


def test_a_command_result_from_a_retired_session_is_refused() -> None:
    """The request id alone cannot tell that the session moved on underneath it.

    A Finish, a Cancel, or a renderer restart between submitting a command and
    its result landing leaves a result that is the newest one and still applies
    to a working state that no longer exists.
    """
    app, tab, builder, _process = _mounted_tab("MeshEditorCommandCorrelation")
    _open_edit_session(tab)

    # A command is submitted against this session.
    tab.standalone_action_request_id = 7
    tab.standalone_action_edit_session_generation = tab._edit_session_generation()
    assert tab._dotnet_action_belongs_to_current_edit_session(7)

    # The session is lost while the command runs.
    tab.standalone_dotnet_edit_session.require_recovery(reason="renderer_died")
    assert not tab._dotnet_action_belongs_to_current_edit_session(7)
    # A different request id is refused for the older reason, unchanged.
    assert not tab._dotnet_action_belongs_to_current_edit_session(6)

    _teardown(app, tab, builder)


def test_a_command_submitted_outside_an_edit_session_is_not_gated() -> None:
    app, tab, builder, _process = _mounted_tab("MeshEditorCommandUngated")

    tab.standalone_action_request_id = 3
    tab.standalone_action_edit_session_generation = -1

    assert tab._dotnet_action_belongs_to_current_edit_session(3)

    _teardown(app, tab, builder)


def test_a_dropped_result_still_lets_a_pending_exit_complete() -> None:
    """Dropping the result must not strand whatever was waiting for it."""
    app, tab, builder, _process = _mounted_tab("MeshEditorCommandDropCompletes")
    _open_edit_session(tab)
    tab.standalone_action_request_id = 4
    tab.standalone_action_edit_session_generation = tab._edit_session_generation()
    tab.standalone_dotnet_edit_session.require_recovery(reason="renderer_died")

    completions: list[str] = []
    tab._complete_pending_dotnet_exit = lambda: completions.append("exit")

    tab._handle_standalone_action_completed(4, object())

    assert completions == ["exit"]
    assert tab.standalone_action_finished_request_id == 4

    _teardown(app, tab, builder)


def test_the_session_helpers_tolerate_a_host_that_skipped_the_initialiser() -> None:
    """Composed into a host with no runtime state, the helpers decline quietly.

    Several of these mixins really are composed into hosts that never run the
    tab's runtime initialiser, so there is no session machine to move. What they
    must not do is raise, and — since the helpers now arrive by inheritance
    rather than by whatever else the host happened to compose — the methods
    themselves are guaranteed to be there.
    """
    from cdmw.ui.mesh_editor.tab_dotnet_session_events import (
        MeshEditorDotNetSessionEventMixin,
    )

    events: list[str] = []

    class _BareHost(MeshEditorDotNetSessionEventMixin):
        def _record_mesh_dotnet_event(self, name: str, **_fields: object) -> None:
            events.append(name)

    host = _BareHost()

    assert host._edit_session_machine() is None
    assert host._edit_session_generation() == -1
    assert host._edit_session_transition(S.EDIT_ACTIVE, reason="no_machine") is False
    assert host._require_edit_session_recovery(reason="no_machine") is False
    host._observe_edit_session_from_scene_frame()
    host._record_dotnet_material_publication(None)
    # Nothing happened, so nothing was recorded as though it had.
    assert events == []
