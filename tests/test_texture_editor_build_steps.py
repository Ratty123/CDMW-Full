"""The Textures workspace's editor is built one part per event-loop turn.

Its constructor built every panel in one go: the review measured 206 ms warm
and 358 ms cold on the window thread opening the Textures workspace
(texture_editor_tab.py __init__ via the lazy tab's construction step). The
shell now builds it in steps; the finished editor is the same.
"""

from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEvent  # noqa: E402
from PySide6.QtWidgets import QApplication, QWidget  # noqa: E402

from cdmw.ui.shell.lazy_tool_tab import LazyToolTab  # noqa: E402


def _app():
    return QApplication.instance() or QApplication([])


def _editor(tmp_path: Path, **kwargs):
    from cdmw.services.settings_service import create_settings
    from cdmw.ui.texture_editor_tab import TextureEditorTab
    from cdmw.ui.texture_workflow.job import TextureJob

    _app()
    return TextureEditorTab(
        settings=create_settings(settings_file_path=tmp_path / "settings.cfg"),
        base_dir=tmp_path,
        get_png_root=lambda: str(tmp_path),
        workspace_job=TextureJob(),
        **kwargs,
    )


def _close(editor) -> None:
    editor.request_shutdown()
    editor.deleteLater()
    _app().sendPostedEvents(None, QEvent.Type.DeferredDelete)


def _tree(widget: QWidget) -> list[tuple[str, str]]:
    return sorted((type(child).__name__, child.objectName()) for child in widget.findChildren(QWidget))


def test_an_editor_built_in_steps_matches_one_built_at_once(tmp_path):
    whole = _editor(tmp_path / "a")
    stepped = _editor(tmp_path / "b", build_in_steps=True)
    finished = []
    try:
        stepped.after_construction(lambda: finished.append(len(_tree(stepped))))
        assert not stepped.construction_complete
        sizes = [len(_tree(stepped))]
        while stepped.continue_construction():
            sizes.append(len(_tree(stepped)))
        assert len(sizes) >= 5, "the editor is built in several parts"
        assert sizes == sorted(sizes) and sizes[0] < sizes[-1]
        assert stepped.construction_complete and finished == [len(_tree(whole))]
        assert _tree(stepped) == _tree(whole)
        assert stepped.history_section is not None and stepped._settings_ready
        # Further calls change nothing, and late callbacks run at once.
        assert stepped.continue_construction() is False
        late = []
        stepped.after_construction(lambda: late.append(True))
        assert late == [True]
    finally:
        _close(whole)
        _close(stepped)


class _SteppedWidget(QWidget):
    def __init__(self, parts: int) -> None:
        super().__init__()
        self.remaining = parts
        self.calls = 0

    @property
    def construction_complete(self) -> bool:
        return self.remaining == 0

    def continue_construction(self) -> bool:
        if self.remaining == 0:
            return False
        self.calls += 1
        self.remaining -= 1
        return True


def test_the_lazy_tab_runs_one_construction_step_per_turn_before_publishing():
    _app()
    widget = _SteppedWidget(3)
    container = LazyToolTab(lambda: widget)
    created = []
    container.when_created(created.append)
    try:
        container._construct_requested_widget()
        for expected_calls in (1, 2, 3):
            assert container._next_load_step == container._continue_requested_construction
            container._run_load_step()
            # In its container from the start (see test_lazy_tool_attach_step), not published yet.
            assert widget.calls == expected_calls and widget.parentWidget() is container and not created
        container._run_load_step()  # the last check finds it complete
        assert container._next_load_step == container._attach_requested_widget
        container._run_load_step()
        container._run_load_step()
        assert created == [widget] and widget.parentWidget() is container
    finally:
        container.deleteLater()


def test_a_direct_request_mid_construction_finishes_the_widget():
    _app()
    widget = _SteppedWidget(4)
    container = LazyToolTab(lambda: widget)
    try:
        container._construct_requested_widget()
        container._run_load_step()

        assert container.ensure_widget() is widget

        assert widget.construction_complete and container.widget_if_created() is widget
    finally:
        container.deleteLater()


def test_shutdown_mid_construction_finishes_and_owns_the_widget():
    _app()
    widget = _SteppedWidget(4)
    container = LazyToolTab(lambda: widget)
    try:
        container._construct_requested_widget()

        container.request_shutdown()

        assert widget.construction_complete
        assert container.widget_if_created() is widget and widget.parentWidget() is container
    finally:
        container.deleteLater()
