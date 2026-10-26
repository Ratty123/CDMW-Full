from __future__ import annotations

import os
from types import SimpleNamespace
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QCoreApplication, QEvent, QRect, QSize, Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication, QDialog, QLabel, QMainWindow, QMenu, QPushButton, QVBoxLayout, QWidget

from cdmw.ui.display_scaling import (
    CurrentToolStack, ensure_app_display_scaling, fit_window_to_screen,
    protect_control_text, scrollable_content,
)
from tests.qt_font_metrics_support import ensure_default_ui_font_available
from cdmw.ui.shell.compact.icons import compact_line_icon
from cdmw.ui.wrapping_layout import WrappingLayout


@pytest.fixture
def app():
    app = QApplication.instance() or QApplication([])
    if not ensure_default_ui_font_available():
        pytest.skip("The application font is required for text geometry checks")
    app.setStyle("Fusion")
    yield app
    policy = getattr(app, "_cdmw_display_scaling", None)
    if policy is not None:
        app.removeEventFilter(policy)
        policy.deleteLater()
        del app._cdmw_display_scaling
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)


def _settle(app):
    for _ in range(8):
        app.processEvents()


@pytest.mark.skipif(os.name != "nt", reason="Windows native host isolation policy")
def test_native_host_keeps_ordinary_siblings_and_ancestors_non_native(app):
    attribute = Qt.AA_DontCreateNativeWidgetSiblings
    previous = app.testAttribute(attribute)
    window = None
    try:
        app.setAttribute(attribute, False)
        ensure_app_display_scaling(app)
        window = QWidget()
        ancestor = QWidget(window)
        container = QWidget(ancestor)
        sibling = QWidget(container)
        host = QWidget(container)
        host.setAttribute(Qt.WA_DontCreateNativeAncestors, True)
        host.setAttribute(Qt.WA_NativeWindow, True)
        window.show()
        _settle(app)

        assert host.testAttribute(Qt.WA_NativeWindow)
        assert host.windowHandle() is not None
        assert host.winId() != 0
        assert host.parentWidget() is container
        assert sibling.parentWidget() is container
        assert container.parentWidget() is ancestor
        assert ancestor.parentWidget() is window
        for ordinary_widget in (ancestor, container, sibling):
            assert not ordinary_widget.testAttribute(Qt.WA_NativeWindow)
            assert ordinary_widget.windowHandle() is None
    finally:
        if window is not None:
            window.close()
            window.deleteLater()
            QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        app.setAttribute(attribute, previous)


def test_late_controls_and_font_changes_keep_full_text(app):
    ensure_app_display_scaling(app)
    dialog = QDialog()
    layout = QVBoxLayout(dialog)
    dialog.show()
    button = QPushButton("References and selected files")
    button.setFixedSize(90, 26)
    layout.addWidget(button)
    button.show()
    button.setFont(QFont("Segoe UI", 15))
    _settle(app)
    assert button.font().pointSize() == 15
    assert button.height() >= button.fontMetrics().height() + 12
    assert button.width() >= button.sizeHint().width()
    button.setText("A longer translated action with selected references")
    _settle(app)
    assert button.width() >= button.sizeHint().width()
    large_width = button.minimumWidth()
    button.setFont(QFont("Segoe UI", 8))
    _settle(app)
    assert button.minimumWidth() < large_width
    assert button.font().pointSize() == 8
    dialog.close()
    dialog.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)


def test_oversized_dialog_scrolls_to_actions_and_preserves_nested_preview_parent(app):
    dialog = QDialog()
    dialog.setMinimumSize(1180, 780)
    layout = QVBoxLayout(dialog)
    preview_container = QWidget()
    preview_layout = QVBoxLayout(preview_container)
    preview = QLabel("Resident preview stand-in")
    preview_layout.addWidget(preview)
    layout.addWidget(preview_container)
    action = QPushButton("Apply")
    layout.addWidget(action)
    dialog.show()
    fit_window_to_screen(dialog, QRect(100, 80, 960, 500))
    _settle(app)
    scroll = dialog._display_overflow_scroll
    assert QRect(100, 80, 960, 500).contains(dialog.frameGeometry())
    assert scroll.horizontalScrollBar().maximum() > 0
    assert scroll.verticalScrollBar().maximum() > 0
    scroll.ensureWidgetVisible(action)
    _settle(app)
    assert scroll.viewport().rect().intersects(action.rect().translated(action.mapTo(scroll.viewport(), action.rect().topLeft())))
    assert preview.parentWidget() is preview_container
    body = scroll.widget()
    fit_window_to_screen(dialog, QRect(0, 0, 1920, 1040))
    fit_window_to_screen(dialog, QRect(0, 0, 960, 500))
    assert scroll.widget() is body
    assert body.layout() is layout
    assert preview.parentWidget() is preview_container
    dialog.close()
    dialog.deleteLater()


def test_inactive_tools_do_not_force_scrollbars_on_small_tools(app):
    stack = CurrentToolStack()
    large, small = QWidget(), QWidget()
    large.setMinimumSize(1600, 1000)
    small.setMinimumSize(200, 100)
    stack.addWidget(large)
    stack.addWidget(small)
    scroll = scrollable_content(stack)
    scroll.resize(600, 400)
    scroll.show()
    _settle(app)
    assert scroll.horizontalScrollBar().maximum() > 0
    stack.setCurrentWidget(small)
    _settle(app)
    assert stack.minimumSizeHint() == QSize(200, 100)
    assert scroll.horizontalScrollBar().maximum() == 0
    assert scroll.verticalScrollBar().maximum() == 0
    scroll.close()
    scroll.deleteLater()


def test_artwork_and_popups_keep_their_geometry(app):
    artwork = QLabel()
    artwork.setFixedSize(24, 24)
    protect_control_text(artwork)
    assert artwork.size() == QSize(24, 24)
    menu = QMenu()
    menu.resize(1100, 700)
    before = menu.size()
    fit_window_to_screen(menu, QRect(0, 0, 640, 400))
    assert menu.size() == before
    artwork.deleteLater()
    menu.deleteLater()


def test_monitor_resize_burst_fits_once_and_keeps_text_updates_responsive(app, monkeypatch):
    from PySide6.QtTest import QTest
    import cdmw.ui.display_scaling as scaling

    ensure_app_display_scaling(app)
    window = QWidget()
    layout = QVBoxLayout(window)
    button = QPushButton('Action')
    button.setFixedSize(90, 26)
    layout.addWidget(button)
    window.resize(500, 300)
    window.show()
    QTest.qWait(180)
    _settle(app)
    fits = []
    original = scaling.fit_window_to_screen

    def fit(target, *args):
        fits.append(target)
        original(target, *args)

    monkeypatch.setattr(scaling, 'fit_window_to_screen', fit)
    try:
        for width in range(500, 530):
            window.resize(width, 300)
            QTest.qWait(3)
        button.setText('Select installed model')
        button.setFont(QFont('Segoe UI', 15))
        _settle(app)
        assert window not in fits, 'Window fitting must wait until the resize burst settles.'
        assert button.minimumWidth() >= button.fontMetrics().horizontalAdvance(button.text())
        assert button.minimumHeight() >= button.fontMetrics().height() + 12
        QTest.qWait(180)
        assert fits.count(window) == 1
    finally:
        window.close()
        window.deleteLater()


def test_hidden_rust_workflow_is_not_fitted_or_resized_as_a_desktop_window(app, monkeypatch):
    import cdmw.ui.display_scaling as scaling

    policy = ensure_app_display_scaling(app)
    workflow = QWidget(None, Qt.Tool | Qt.FramelessWindowHint)
    workflow.setAttribute(Qt.WA_DontShowOnScreen, True)
    layout = QVBoxLayout(workflow)
    layout.addWidget(QPushButton('Offscreen authority'))
    workflow.resize(1800, 950)
    fits = []
    monkeypatch.setattr(scaling, 'fit_window_to_screen', lambda window: fits.append(window))
    try:
        workflow.show()
        _settle(app)
        policy._refresh_windows()
        policy._fit_pending_windows()
        assert workflow not in fits
        assert workflow.size() == QSize(1800, 950)
        assert workflow.layout() is layout
        fit_window_to_screen(workflow, QRect(0, 0, 800, 600))
        assert workflow.size() == QSize(1800, 950)
    finally:
        workflow.close()
        workflow.deleteLater()


@pytest.mark.parametrize("ratio", [1.0, 1.25, 1.5, 2.0, 3.0])
def test_line_icons_render_at_requested_device_resolution(app, ratio):
    icon = compact_line_icon("folder", app.palette())
    pixmap = icon.pixmap(QSize(18, 18), ratio)
    assert pixmap.width() >= int(18 * ratio)
    assert pixmap.devicePixelRatio() == pytest.approx(ratio, abs=0.03)
    assert not pixmap.isNull()


def test_actions_wrap_without_squeezing_translated_text(app):
    panel = QWidget()
    panel.setFont(QFont("Segoe UI", 15))
    layout = WrappingLayout(panel)
    buttons = [QPushButton(text) for text in ("References", "Selected files", "Refresh")]
    for button in buttons:
        button.setFont(panel.font())
        protect_control_text(button)
        layout.addWidget(button)
    panel.resize(290, 200)
    panel.show()
    _settle(app)
    assert buttons[-1].y() > buttons[0].y()
    assert all(button.width() >= button.minimumWidth() for button in buttons)
    panel.resize(900, 200)
    _settle(app)
    assert len({button.y() for button in buttons}) == 1
    panel.close()
    panel.deleteLater()


def test_settings_performance_cards_use_one_column_when_narrow(app, tmp_path):
    from cdmw.services.settings_service import create_settings
    from cdmw.ui.settings_tab import SettingsTab
    settings = create_settings(settings_file_path=tmp_path / "settings.ini")
    settings.setValue("appearance/ui_font_size", 15)
    tab = SettingsTab(settings=settings, theme_key="crimson_desert")
    tab.setFont(QFont("Segoe UI", 15))
    tab.show_settings_section("performance")
    tab.resize(1000, 680)
    tab.show()
    _settle(app)
    grid = tab.findChild(QWidget, "SettingsPerformanceGrid")
    first, second = grid.layout().itemAt(0).widget(), grid.layout().itemAt(1).widget()
    assert first.x() == second.x()
    assert second.y() >= first.y() + first.height()
    last = grid.layout().itemAt(3).widget()
    assert last.geometry().bottom() < grid.height()
    tab.resize(1700, 900)
    _settle(app)
    assert first.y() == second.y()
    assert second.x() > first.x()
    tab.request_shutdown()
    tab.close()
    tab.deleteLater()


def _fake_work_areas(monkeypatch, window, areas):
    import cdmw.ui.display_scaling as scaling

    monkeypatch.setattr(scaling, "_available_screen_rects", lambda: tuple(areas))
    monkeypatch.setattr(window, "screen", lambda: SimpleNamespace(availableGeometry=lambda: areas[0]))


@pytest.mark.parametrize("geometry", [
    QRect(700, 100, 600, 350),  # A normal window straddles the screen boundary.
    QRect(-250, 100, 600, 350),  # Partial visibility still leaves usable content.
    QRect(350, 100, 1300, 450),  # Content spans screens and exceeds either one's width.
    QRect(350, 300, 1300, 450),  # A small clipped outer edge must not collapse that span.
])
def test_usable_manual_window_placement_is_preserved(app, monkeypatch, geometry):
    window = QWidget()
    _fake_work_areas(monkeypatch, window, [QRect(0, 0, 960, 720), QRect(960, 0, 960, 720)])
    try:
        window.show()
        window.setGeometry(geometry)
        _settle(app)
        before = window.frameGeometry()
        fit_window_to_screen(window)
        assert window.frameGeometry() == before
    finally:
        window.close()
        window.deleteLater()


@pytest.mark.parametrize("geometry, areas", [
    (QRect(100, -80, 600, 350), [QRect(0, 0, 960, 720)]),  # Lost caption.
    (QRect(1080, 100, 100, 300), [QRect(0, 0, 960, 720), QRect(1280, 0, 960, 720)]),
    (QRect(350, 100, 1300, 450), [QRect(0, 0, 960, 720), QRect(1280, 0, 960, 720)]),
    (QRect(1500, 100, 600, 350), [QRect(0, 0, 960, 720)]),  # Removed screen.
])
def test_unreachable_windows_and_missing_spanning_content_are_recovered(app, monkeypatch, geometry, areas):
    window = QWidget()
    _fake_work_areas(monkeypatch, window, areas)
    try:
        window.show()
        window.setGeometry(geometry)
        _settle(app)
        fit_window_to_screen(window)
        assert areas[0].contains(window.frameGeometry())
    finally:
        window.close()
        window.deleteLater()


def test_direct_fit_cannot_modify_geometry_or_wrap_content_during_native_drag(app):
    from cdmw.ui.window_interaction import ensure_window_interaction_tracker

    window = QDialog()
    window.setMinimumSize(1180, 780)
    layout = QVBoxLayout(window)
    layout.addWidget(QPushButton("Apply"))
    tracker = ensure_window_interaction_tracker(app)
    try:
        window.show()
        _settle(app)
        tracker.begin(window)
        before = window.frameGeometry()
        fit_window_to_screen(window, QRect(0, 0, 960, 500))
        assert window.frameGeometry() == before
        assert "_display_overflow_scroll" not in window.__dict__
        tracker.end(window)
        assert tracker.is_active(window)
        fit_window_to_screen(window, QRect(0, 0, 960, 500))
        assert window.frameGeometry() == before
        _settle(app)
        fit_window_to_screen(window, QRect(0, 0, 960, 500))
        assert QRect(0, 0, 960, 500).contains(window.frameGeometry())
        assert window._display_overflow_scroll.widget().layout() is layout
    finally:
        window.close()
        window.deleteLater()


@pytest.mark.parametrize("show_method", ["showMaximized", "showFullScreen"])
def test_fit_preserves_maximized_and_fullscreen_geometry(app, show_method):
    window = QWidget()
    try:
        getattr(window, show_method)()
        _settle(app)
        before = window.geometry()
        state = window.windowState()
        fit_window_to_screen(window, QRect(0, 0, 300, 200))
        assert window.geometry() == before
        assert window.windowState() == state
    finally:
        window.close()
        window.deleteLater()


@pytest.fixture
def fit_policy(app, monkeypatch):
    import cdmw.ui.display_scaling as scaling
    from cdmw.ui.window_interaction import ensure_window_interaction_tracker

    state = SimpleNamespace(now=100.0, fits=[])
    monkeypatch.setattr(scaling, "monotonic", lambda: state.now)
    monkeypatch.setattr(scaling, "fit_window_to_screen", lambda window: state.fits.append(window))
    state.policy = ensure_app_display_scaling(app)
    state.tracker = ensure_window_interaction_tracker(app)
    windows = []

    def make_window(factory=QWidget):
        window = factory()
        window.setGeometry(100, 100, 450, 300)
        window.show()
        windows.append(window)
        _settle(app)
        return window

    state.make_window = make_window
    yield state
    for window in windows:
        window.close()
        window.deleteLater()
    _settle(app)


def test_move_only_continuation_postpones_an_existing_fit_beyond_120ms(app, fit_policy):
    state = fit_policy
    window = state.make_window()
    for offset in range(1, 8):
        state.now += 0.05
        window.move(100 + 10 * offset, 100)
        _settle(app)
        state.policy._fit_pending_windows()
        assert window not in state.fits
    state.now += 0.13
    state.policy._fit_pending_windows()
    assert state.fits == [window]


def test_native_hold_survives_pause_then_fits_once_after_queued_finish(app, fit_policy):
    state = fit_policy
    window = state.make_window()
    state.tracker.begin(window)
    for _ in range(3):
        state.now += 10.0
        state.policy.eventFilter(window, QEvent(QEvent.LayoutRequest))
        state.policy._fit_pending_windows()
        assert state.fits == []
        assert not state.policy._window_timer.isActive()
    state.tracker.end(window)
    state.policy._fit_pending_windows()
    assert state.fits == []
    _settle(app)
    state.now += 0.13
    state.policy._fit_pending_windows()
    assert state.fits == [window]
    # Late layout/monitor callbacks describing the same state need no second fit.
    for kind in (QEvent.LayoutRequest, QEvent.ScreenChangeInternal, QEvent.DevicePixelRatioChange):
        state.policy.eventFilter(window, QEvent(kind))
    state.now += 0.13
    state.policy._fit_pending_windows()
    assert state.fits == [window]


@pytest.mark.parametrize("native_hold", [False, True])
def test_moving_one_window_does_not_starve_another_window_fit(app, fit_policy, native_hold):
    state = fit_policy
    moving = state.make_window()
    settled = state.make_window()
    if native_hold:
        state.tracker.begin(moving)
    state.now += 0.10
    moving.move(180, 100)
    _settle(app)
    state.now += 0.03
    state.policy._fit_pending_windows()
    assert state.fits == [settled]
    if native_hold:
        state.tracker.end(moving)
        _settle(app)
    state.now += 0.13
    state.policy._fit_pending_windows()
    assert state.fits == [settled, moving]


def test_restarted_native_drag_and_hidden_window_do_not_run_stale_fits(app, fit_policy):
    state = fit_policy
    window = state.make_window()
    state.tracker.begin(window)
    state.tracker.end(window)
    state.tracker.begin(window)
    _settle(app)
    state.now += 1.0
    state.policy._fit_pending_windows()
    assert state.tracker.is_active(window)
    assert state.fits == []
    window.hide()
    _settle(app)
    state.now += 1.0
    state.policy._fit_pending_windows()
    assert state.fits == []
    assert not state.policy._window_timer.isActive()


def test_a_stale_window_handle_wrapper_waits_for_the_real_handle(app, fit_policy):
    from PySide6.QtWidgets import QWidgetItem

    class Window(QWidget):
        # PySide can hand back a stale wrapper of another type for a reused address.
        stale = True

        def windowHandle(self):
            return QWidgetItem(self) if self.stale else super().windowHandle()

    state = fit_policy
    window = state.make_window(Window)
    state.policy.schedule_window_fit(window)
    assert window not in state.policy._connected
    window.stale = False
    state.policy.schedule_window_fit(window)
    assert window in state.policy._connected


def test_shell_and_display_requests_have_one_fit_owner(app, fit_policy):
    from cdmw.ui.shell.responsiveness_controller import ResponsivenessControllerMixin

    class Shell(ResponsivenessControllerMixin, QMainWindow):
        pass

    state = fit_policy
    window = state.make_window(Shell)
    window._apply_responsive_window_defaults(
        restore_saved_splitters=False,
        schedule_column_autofit=False,
        apply_expensive_metrics=False,
    )
    state.policy.eventFilter(window, QEvent(QEvent.DevicePixelRatioChange))
    state.now += 0.13
    state.policy._fit_pending_windows()
    assert state.fits == [window]
    # The shell's later metrics timer used to invoke an independent geometry fit.
    state.now += 0.26
    window._responsive_metrics_dirty = True
    window._apply_responsive_resize_adjustments()
    state.policy._fit_pending_windows()
    assert state.fits == [window]
    assert not state.policy._window_timer.isActive()
