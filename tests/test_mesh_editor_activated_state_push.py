"""`activated` must not re-push state the rehydrator already delivered.

The helper emits ``activated`` *after* it has revealed its window, so anything
the host sends in response lands on screen. A mesh_edit interaction frame makes
the helper re-run its interaction-mode controls and re-assert the tool rail in
full view, which is the editor visibly rearranging itself on open.
``_rehydrate_shared_dotnet_controller`` already sends the same three frames from
inside the package-apply path, which runs before activation and therefore while
the window is still hidden.

These call the real handler and count the real sends rather than asserting on
source text, because a source guard would still pass if the guard were wired to
the wrong generation.
"""

from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QSettings

from PySide6.QtWidgets import QApplication

from cdmw.ui.mesh_editor.tab import MeshEditorTab
from tests.test_mesh_editor_action_bar import _EmbeddedMeshBuilder

ROOT = Path(__file__).resolve().parents[1]
_APP = QApplication.instance() or QApplication([])


def _embedded_tab(name: str) -> tuple[MeshEditorTab, _EmbeddedMeshBuilder]:
    settings = QSettings("CDMWTests", name)
    settings.clear()
    tab = MeshEditorTab(settings=settings)
    builder = _EmbeddedMeshBuilder()
    tab.mount_embedded_builder(builder)
    tab.standalone_dotnet_target_embedded = True
    tab.standalone_dotnet_target_controller = builder.controller
    return tab, builder


def _count_state_sends(tab: MeshEditorTab) -> dict[str, int]:
    """Instrument the direct-called senders; none of these are signal slots."""

    counts = {"session": 0, "scene": 0}
    original_session = tab._send_dotnet_session_state
    original_scene = tab._send_dotnet_scene_state

    def session(*args: object, **kwargs: object) -> object:
        counts["session"] += 1
        return original_session(*args, **kwargs)

    def scene(*args: object, **kwargs: object) -> object:
        counts["scene"] += 1
        return original_scene(*args, **kwargs)

    tab._send_dotnet_session_state = session  # type: ignore[method-assign]
    tab._send_dotnet_scene_state = scene  # type: ignore[method-assign]
    return counts


def test_activated_skips_state_the_rehydrator_already_pushed() -> None:
    tab, _builder = _embedded_tab("MeshEditorActivatedSkip")
    try:
        tab.standalone_dotnet_process_generation = 7
        # What _rehydrate_shared_dotnet_controller records once it has sent.
        tab.standalone_dotnet_state_pushed_generation = 7
        assert tab._dotnet_state_already_pushed_for_process()

        counts = _count_state_sends(tab)
        assert tab._handle_dotnet_protocol_event({"event": "activated"})

        assert counts == {"session": 0, "scene": 0}, (
            "activated re-pushed state after the reveal; the tool rail will "
            f"re-assert itself on screen ({counts})"
        )
    finally:
        tab.deleteLater()


def test_activated_still_pushes_when_no_rehydrate_preceded_it() -> None:
    """A suspend/resume activates without a package apply, so nothing rehydrated."""

    tab, _builder = _embedded_tab("MeshEditorActivatedResume")
    try:
        tab.standalone_dotnet_process_generation = 7
        tab.standalone_dotnet_state_pushed_generation = 6  # an earlier process
        assert not tab._dotnet_state_already_pushed_for_process()

        counts = _count_state_sends(tab)
        assert tab._handle_dotnet_protocol_event({"event": "activated"})

        assert counts["session"] == 1 and counts["scene"] == 1, (
            f"a resume must restate its session and scene ({counts})"
        )
    finally:
        tab.deleteLater()


def test_state_is_not_considered_pushed_for_a_fresh_process() -> None:
    """A relaunch gets a new generation, so the previous push must not count."""

    tab, _builder = _embedded_tab("MeshEditorActivatedFreshProcess")
    try:
        tab.standalone_dotnet_process_generation = 0
        tab.standalone_dotnet_state_pushed_generation = 0
        # Generation 0 means "no process yet"; it must never satisfy the guard,
        # or the very first activation would skip its only state push.
        assert not tab._dotnet_state_already_pushed_for_process()
    finally:
        tab.deleteLater()


def test_real_activated_envelope_uses_activation_correlation_not_mutation_request_id() -> None:
    tab, builder = _embedded_tab("MeshEditorActivatedCorrelation")
    try:
        tab.standalone_dotnet_process_generation = 7
        tab.standalone_dotnet_capabilities.add("resident_mutation_envelope_v2")
        tab.standalone_dotnet_state_pushed_generation = 7
        session_id = builder.controller.session_view().session_id
        command_results: list[dict[str, object]] = []
        tab._send_dotnet_command_result = (  # type: ignore[method-assign]
            lambda *args, **kwargs: command_results.append(dict(kwargs)) or True
        )

        assert tab._handle_dotnet_protocol_event(
            {
                "event": "activated",
                "activation_request_id": 4,
                "session_id": session_id,
                "process_generation": 7,
                "package_generation": 2,
            }
        )

        assert command_results == []
    finally:
        tab.deleteLater()
