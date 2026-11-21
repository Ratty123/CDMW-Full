"""A lazy tool's widget is built, attached and published on separate event-loop turns.

The review measured 367 ms (545 ms cold) on the UI thread opening Model
Library, in one load step that ran the tool's constructor and then moved the
finished widget into its container, which restyles the whole subtree. The
move now has its own step.
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEvent, QObject  # noqa: E402
from types import SimpleNamespace  # noqa: E402

from PySide6.QtWidgets import QApplication, QLabel, QVBoxLayout, QWidget  # noqa: E402

from cdmw.ui.shell.lazy_tool_tab import LazyToolTab  # noqa: E402


def _factory():
    widget = QWidget()
    layout = QVBoxLayout(widget)
    for index in range(10):
        layout.addWidget(QLabel(f"row {index}"))
    return widget


def _app():
    return QApplication.instance() or QApplication([])


def test_construction_and_attachment_are_separate_steps():
    _app()
    container = LazyToolTab(_factory)
    created = []
    container.when_created(created.append)
    container._construct_requested_widget()
    pending = container._pending_widget
    assert pending is not None
    assert pending.parentWidget() is None, "the constructor's step must not also move the widget"
    assert container._next_load_step == container._attach_requested_widget
    container._run_load_step()
    assert pending.parentWidget() is container
    assert not created
    container._run_load_step()
    assert created == [pending]
    assert container.widget_if_created() is pending
    container.deleteLater()


def test_shutdown_before_attachment_still_owns_the_widget():
    _app()
    container = LazyToolTab(_factory)
    container._construct_requested_widget()
    pending = container._pending_widget
    container.request_shutdown()
    assert container.widget_if_created() is pending
    assert pending.parentWidget() is container
    container.deleteLater()


def test_ensure_widget_still_builds_at_once():
    _app()
    container = LazyToolTab(_factory)
    widget = container.ensure_widget()
    assert widget.parentWidget() is container
    assert container.widget_if_created() is widget
    container.deleteLater()


class _StepBuiltTool(QWidget):
    """Builds its rows in steps, as Texture Editor does (``build_in_steps``)."""

    def __init__(self, steps: int = 3, rows: int = 40) -> None:
        super().__init__()
        self._layout = QVBoxLayout(self)
        self._left = steps
        self._rows = rows
        self.parents_while_building: list[object] = []

    @property
    def construction_complete(self) -> bool:
        return self._left == 0

    def continue_construction(self) -> bool:
        if self._left == 0:
            return False
        self.parents_while_building.append(self.parentWidget())
        for index in range(self._rows):
            self._layout.addWidget(QLabel(f"row {index}"))
        self._left -= 1
        return True


class _StyleChanges(QObject):
    def __init__(self) -> None:
        super().__init__()
        self.count = 0

    def eventFilter(self, _watched, event) -> bool:  # noqa: N802 - Qt API
        if event.type() == QEvent.Type.StyleChange:
            self.count += 1
        return False


def test_a_tool_built_in_steps_is_attached_before_its_steps_restyle_nothing_later():
    """Textures held the UI thread 106 ms (158 ms warm) in the attach step in the
    2026-11-17 review: moving a finished widget into the container restyles every
    widget in it. A step-built tool moves in while it is still nearly empty."""

    app = _app()
    previous_sheet = app.styleSheet()
    app.setStyleSheet("QLabel { padding: 1px; }")  # the app always runs with a style sheet
    tool = _StepBuiltTool()
    container = LazyToolTab(lambda: tool)
    counter = _StyleChanges()
    try:
        container._construct_requested_widget()
        while container._next_load_step == container._continue_requested_construction:
            container._run_load_step()
        assert tool.parents_while_building == [container] * 3, "the steps built a widget outside its container"
        assert container._next_load_step == container._attach_requested_widget
        app.installEventFilter(counter)
        container._run_load_step()  # the attach step
        app.removeEventFilter(counter)
        assert counter.count == 0, f"the attach step restyled {counter.count} widgets"
        container._run_load_step()
        assert container.widget_if_created() is tool
    finally:
        app.removeEventFilter(counter)
        app.setStyleSheet(previous_sheet)
        container.deleteLater()


def test_a_tool_still_being_built_does_not_save_its_settings():
    """A pending tool was never shown, so its controls hold no change of the user's; saving
    them at close would overwrite newer values the shell saved (the lazy Settings tab)."""

    _app()
    saved = []

    class _Tool(QWidget):
        def flush_settings_save(self):
            saved.append("flush")

    container = LazyToolTab(_Tool)
    container._construct_requested_widget()
    assert container._pending_widget is not None
    container.flush_settings_save()
    assert saved == []
    container._attach_requested_widget()
    container._finish_requested_widget()
    container.flush_settings_save()
    assert saved == ["flush"]


def test_the_settings_tab_catches_up_with_changes_made_while_it_was_built():
    from types import SimpleNamespace

    from cdmw.ui.shell.tool_tabs import ShellToolTabsMixin

    _app()
    calls = []

    class _SettingsTab(QWidget):
        def _load_settings(self, theme):
            calls.append(("load", theme))

        def _apply_model_preview_controls(self, settings):
            calls.append(("preview", settings))

        def sync_archive_performance_controls(self, settings):
            calls.append(("performance", settings))

        def sync_appearance_controls(self, theme):
            calls.append(("appearance", theme))

        def set_language_options(self, languages, *, current_code):
            calls.append(("language", current_code))

    values = {"preview": "before", "theme": "graphite"}
    shell = SimpleNamespace(
        archive=SimpleNamespace(_current_model_preview_render_settings=lambda: values["preview"]),
        _current_archive_performance_settings=lambda: "performance",
        ui_localizer=SimpleNamespace(available_languages=lambda: ("en",), language_code="en"),
    )
    container = LazyToolTab(_SettingsTab)
    container.when_created(lambda tab: ShellToolTabsMixin._sync_published_settings_tab(shell, tab))
    container._construct_requested_widget()
    # Changed while the tab was pending: the shell skipped it then.
    values["preview"] = "after"
    shell.current_theme_key = "light"
    assert calls == []
    container._attach_requested_widget()
    container._finish_requested_widget()
    assert ("preview", "after") in calls and ("appearance", "light") in calls
    assert ("performance", "performance") in calls and ("language", "en") in calls
    # What was saved meanwhile (a profile import) is read first, then the live values.
    assert calls[0] == ("load", "light")


def test_a_tool_published_only_to_shut_it_down_does_not_save_its_settings():
    """Closing CDMW publishes a pending tool so it can shut down; it was never shown,
    so its stale controls must not be saved over newer values."""

    _app()
    saved = []

    class _Tool(QWidget):
        def flush_settings_save(self):
            saved.append("flush")

    container = LazyToolTab(_Tool)
    container._construct_requested_widget()
    container.request_shutdown()
    assert container.widget_if_created() is not None
    container.flush_settings_save()
    assert saved == []


def test_preview_and_archive_syncs_do_not_build_a_lazy_settings_tab():
    """The first preview pushes its settings to Settings; with Settings not built yet that
    must not build it (it used to, on the first archive selection)."""

    from types import SimpleNamespace

    from cdmw.ui.archive_browser.preview_settings import ArchivePreviewSettingsMixin

    _app()
    built = []

    def factory():
        built.append(True)
        return QWidget()

    settings_tab = LazyToolTab(factory)
    owner = SimpleNamespace(
        shell=SimpleNamespace(settings_tab=settings_tab, _current_archive_performance_settings=lambda: None),
        _current_model_preview_render_settings=lambda: None,
    )
    ArchivePreviewSettingsMixin._sync_model_preview_settings_controls(owner)
    ArchivePreviewSettingsMixin._sync_archive_performance_settings_controls(owner)
    assert built == [] and settings_tab.widget_if_created() is None


def test_create_new_item_follows_a_settings_tab_built_after_it():
    from PySide6.QtCore import Signal

    from cdmw.ui.new_item.tab import NewItemStudioTab

    _app()

    class _Settings(QWidget):
        model_preview_settings_changed = Signal(object)
        archive_performance_settings_changed = Signal(object)

    received = []
    owner = SimpleNamespace(set_preview_render_settings=lambda s: received.append(("preview", s)),
                            set_archive_performance_settings=lambda s: received.append(("archive", s)))
    owner._follow_settings_tab = lambda tab: NewItemStudioTab._follow_settings_tab(owner, tab)
    settings_tab = LazyToolTab(_Settings)
    settings_tab.when_created(owner._follow_settings_tab)
    widget = settings_tab.ensure_widget()
    widget.model_preview_settings_changed.emit("p")
    widget.archive_performance_settings_changed.emit("a")
    assert received == [("preview", "p"), ("archive", "a")]


def test_the_layout_restart_notice_is_never_shown_before_it_has_a_parent():
    from PySide6.QtWidgets import QFormLayout

    from cdmw.ui.shell.compact.settings import CompactWorkspaceSettingsMixin

    _app()
    shown_unparented = []

    class _Owner(QWidget, CompactWorkspaceSettingsMixin):
        settings = SimpleNamespace(value=lambda *_a, **_k: None)

    owner = _Owner()
    form = QFormLayout(owner)
    owner._build_compact_workspace_settings_ui(form)
    label = owner.application_layout_restart_label
    if label.parentWidget() is None:
        shown_unparented.append(not label.isHidden())
    assert shown_unparented in ([], [False])
