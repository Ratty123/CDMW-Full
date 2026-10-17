"""Qt native-widget isolation regressions, without launching a renderer.

These checks exercise real QWidget construction and ownership. Offscreen runs
do not establish Windows clipping, visible stacking, or monitor smoothness.
"""

from __future__ import annotations

import os
from collections.abc import Callable, Iterator
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QCoreApplication, QEvent, QPoint, QRect, Qt
from PySide6.QtGui import QRegion
from PySide6.QtWidgets import QApplication, QPushButton, QScrollArea, QVBoxLayout, QWidget

import cdmw.ui.display_scaling as display_scaling
from cdmw.ui.mesh_editor.rust_host import RustMeshEditorHostFrame
from cdmw.ui.mesh_editor.tab_dotnet_lifecycle import _host_widget_hwnd
from cdmw.ui.preview.dotnet_host import RustPreviewHostFrame
from cdmw.ui.shell.theme_overlay import ThemeChangeBusyOverlay


class _SignalStub:
    def __init__(self) -> None:
        self._callbacks: list[Callable[..., object]] = []

    def connect(self, callback: Callable[..., object]) -> None:
        self._callbacks.append(callback)

    def emit(self, *args: object) -> None:
        for callback in tuple(self._callbacks):
            callback(*args)


class _PreviewControllerStub:
    """Only the controller interface reached by construction and window events."""

    def __init__(self) -> None:
        self.state_changed = _SignalStub()
        self.protocol_event = _SignalStub()
        self.view_state_changed = _SignalStub()
        self.part_pick_result = _SignalStub()
        self.capture_completed = _SignalStub()
        self.renderer_ready = _SignalStub()
        self.capabilities: tuple[str, ...] = ()
        self.applied_package_path: Path | None = None
        self.visible = False
        self.localizer: object | None = None
        self.reembedded: list[int] = []

    def set_ui_localizer(self, localizer: object | None) -> None:
        self.localizer = localizer

    def set_visible(self, visible: bool) -> None:
        self.visible = bool(visible)

    def reembed(self, hwnd: int) -> None:
        self.reembedded.append(int(hwnd))

    def retry_now(self) -> None:
        return

    def deactivate(self) -> None:
        self.visible = False

    def shutdown(self, _destroyed: object | None = None) -> None:
        self.visible = False


@pytest.fixture
def isolated_application(monkeypatch: pytest.MonkeyPatch) -> Iterator[QApplication]:
    application = QApplication.instance() or QApplication([])
    attribute = Qt.ApplicationAttribute.AA_DontCreateNativeWidgetSiblings
    previous = application.testAttribute(attribute)
    try:
        application.setAttribute(attribute, False)
        # Exercise the production Windows policy without installing another
        # application-wide fitting filter in an existing test QApplication.
        monkeypatch.setattr(display_scaling, "sys", SimpleNamespace(platform="win32"))
        policy = object()
        monkeypatch.setattr(application, "_cdmw_display_scaling", policy, raising=False)
        assert display_scaling.ensure_app_display_scaling(application) is policy
        yield application
    finally:
        application.setAttribute(attribute, previous)


def _assert_nonnative(*widgets: QWidget) -> None:
    for widget in widgets:
        assert not widget.testAttribute(Qt.WidgetAttribute.WA_NativeWindow)
        # Unlike winId(), windowHandle() does not create a native window.
        assert widget.windowHandle() is None


def _shown_parent(
    application: QApplication,
) -> tuple[QWidget, QWidget, QVBoxLayout, QPushButton]:
    window = QWidget()
    window.resize(700, 560)
    root_layout = QVBoxLayout(window)
    container = QWidget(window)
    root_layout.addWidget(container)
    layout = QVBoxLayout(container)
    sibling = QPushButton("Ordinary sibling", container)
    layout.addWidget(sibling)
    window.show()
    application.processEvents()
    assert window.windowHandle() is not None
    _assert_nonnative(container, sibling)
    return window, container, layout, sibling


def _destroy_windows(application: QApplication, *windows: QWidget) -> None:
    for window in windows:
        window.close()
        window.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    application.processEvents()


def test_existing_display_policy_enables_native_sibling_isolation(
    isolated_application: QApplication,
) -> None:
    assert isolated_application.testAttribute(
        Qt.ApplicationAttribute.AA_DontCreateNativeWidgetSiblings
    )


@pytest.mark.parametrize("host_kind", ("preview", "mesh", "generic"))
def test_native_hosts_isolate_siblings_and_ancestors_after_show_and_reparent(
    isolated_application: QApplication,
    host_kind: str,
) -> None:
    application = isolated_application
    first_window, first_container, first_layout, first_sibling = _shown_parent(application)
    second_window, second_container, second_layout, second_sibling = _shown_parent(application)
    host: QWidget | None = None
    try:
        if host_kind == "preview":
            controller = _PreviewControllerStub()
            host = RustPreviewHostFrame(first_container, controller=controller)
            native_children = (host._viewport, host._status_panel, host._resident_banner)
            ordinary_children = (
                host._camera_hint,
                host._status_label,
                host._retry_button,
                host._resident_banner_label,
                host._resident_retry_button,
            )
        elif host_kind == "mesh":
            host = RustMeshEditorHostFrame(first_container)
            native_children = (host._surface, host._pages)
            ordinary_children = (
                host._status_page,
                host._status_label,
                host._retry_button,
                host._result_page,
                host._result_label,
            )
        else:
            host = QWidget(first_container)
            host.setMinimumSize(320, 240)
            native_children = ()
            ordinary_children = ()
            returned_handle = _host_widget_hwnd(host)
            assert returned_handle > 0
            assert host.windowHandle() is not None
            assert returned_handle == int(host.windowHandle().winId())

        first_layout.addWidget(host)
        later_sibling = QPushButton("Later ordinary sibling", first_container)
        first_layout.addWidget(later_sibling)

        # This observation occurs before show to catch eager promotion when a
        # host is constructed under a parent that already has a native window.
        _assert_nonnative(first_container, first_sibling, later_sibling)
        assert host.testAttribute(Qt.WidgetAttribute.WA_DontCreateNativeAncestors)
        assert host.testAttribute(Qt.WidgetAttribute.WA_NativeWindow)
        for child in native_children:
            assert child.parentWidget() is host
            assert child.testAttribute(Qt.WidgetAttribute.WA_NativeWindow)

        host.show()
        application.processEvents()
        if host_kind == "preview":
            controller.state_changed.emit("error", "Isolation fixture status")
            application.processEvents()
            assert host._status_panel.isVisible()
            assert host._status_panel.windowHandle() is not None
            # A path value selects resident-banner presentation only. No
            # package is loaded and the stub owns no worker or child process.
            controller.applied_package_path = Path("resident-preview-fixture")
            host.show_preparation_status("Isolation fixture resident notice")
            application.processEvents()
            assert host._resident_banner.isVisible()
            assert not host._status_panel.isVisible()

        def assert_ownership(expected_container: QWidget, expected_window: QWidget) -> None:
            assert host.parentWidget() is expected_container
            assert host.windowHandle() is not None
            assert host.windowHandle().parent() == expected_window.windowHandle()
            _assert_nonnative(
                first_container,
                second_container,
                first_sibling,
                second_sibling,
                later_sibling,
                *ordinary_children,
            )
            for child in native_children:
                assert child.parentWidget() is host
                assert child.windowHandle() is not None
                assert child.windowHandle().parent() == host.windowHandle()

        assert_ownership(first_container, first_window)
        host.hide()
        application.processEvents()
        assert not host.isVisible()
        host.show()
        application.processEvents()
        assert_ownership(first_container, first_window)

        first_layout.removeWidget(host)
        host.setParent(second_container)
        second_layout.addWidget(host)
        host.show()
        application.processEvents()
        assert_ownership(second_container, second_window)
        if host_kind == "generic":
            assert _host_widget_hwnd(host) == int(host.windowHandle().winId())
    finally:
        if host is not None:
            host.close()
        _destroy_windows(application, first_window, second_window)


def test_theme_overlay_is_native_without_promoting_parent_or_siblings(
    isolated_application: QApplication,
) -> None:
    application = isolated_application
    window, container, _layout, sibling = _shown_parent(application)
    overlay: ThemeChangeBusyOverlay | None = None
    try:
        overlay = ThemeChangeBusyOverlay(container)
        assert overlay.parentWidget() is container
        assert overlay.testAttribute(Qt.WidgetAttribute.WA_DontCreateNativeAncestors)
        assert overlay.testAttribute(Qt.WidgetAttribute.WA_NativeWindow)
        _assert_nonnative(container, sibling)

        overlay.show_appearance_change(
            "graphite", title="Isolation fixture", detail="Checking overlay ownership."
        )
        application.processEvents()
        assert overlay.isVisible()
        assert overlay.geometry() == container.rect()
        assert overlay.windowHandle() is not None
        assert overlay.windowHandle().parent() == window.windowHandle()
        assert overlay._spinner_timer.isActive()
        _assert_nonnative(container, sibling)

        overlay.finish(0)
        application.processEvents()
        assert not overlay.isVisible()
        assert not overlay._spinner_timer.isActive()
        assert not overlay._hide_timer.isActive()
        _assert_nonnative(container, sibling)
    finally:
        if overlay is not None:
            overlay._hide_now()
        _destroy_windows(application, window)


def _shown_nested_scroll_parent(application: QApplication) -> SimpleNamespace:
    window = QWidget()
    window.resize(680, 510)
    root_layout = QVBoxLayout(window)
    outer_scroll = QScrollArea(window)
    outer_scroll.setWidgetResizable(False)
    root_layout.addWidget(outer_scroll)
    outer_content = QWidget()
    outer_content.resize(960, 900)
    outer_scroll.setWidget(outer_content)
    outer_button = QPushButton("Outer ordinary sibling", outer_content)
    outer_button.setGeometry(16, 8, 180, 28)

    inner_scroll = QScrollArea(outer_content)
    inner_scroll.setGeometry(18, 44, 520, 360)
    inner_scroll.setWidgetResizable(False)
    inner_content = QWidget()
    inner_content.resize(1000, 820)
    inner_scroll.setWidget(inner_content)
    inner_button = QPushButton("Inner ordinary sibling", inner_content)
    inner_button.setGeometry(16, 8, 180, 28)
    intermediate = QWidget(inner_content)
    intermediate.setGeometry(16, 48, 760, 620)
    host_layout = QVBoxLayout(intermediate)
    sibling = QPushButton("Host ordinary sibling", intermediate)
    host_layout.addWidget(sibling)

    scroll_areas = (outer_scroll, inner_scroll)
    scroll_boundaries = (
        outer_scroll, outer_scroll.viewport(), outer_content,
        inner_scroll, inner_scroll.viewport(), inner_content,
    )
    ordinary_widgets = (
        outer_button,
        inner_button,
        intermediate,
        sibling,
        *(scrollbar for area in scroll_areas for scrollbar in (
            area.horizontalScrollBar(), area.verticalScrollBar()
        )),
        *(scrollbar.parentWidget() for area in scroll_areas for scrollbar in (
            area.horizontalScrollBar(), area.verticalScrollBar()
        )),
    )
    window.show()
    application.processEvents()
    _assert_nonnative(*ordinary_widgets, *scroll_boundaries)
    return SimpleNamespace(
        window=window,
        outer_scroll=outer_scroll,
        inner_scroll=inner_scroll,
        inner_content=inner_content,
        intermediate=intermediate,
        host_layout=host_layout,
        ordinary_widgets=ordinary_widgets,
        scroll_areas=scroll_areas,
        scroll_boundaries=scroll_boundaries,
    )


@pytest.mark.parametrize("host_kind", ("preview", "mesh", "generic"))
def test_native_hosts_clip_to_nested_scroll_areas_without_native_ancestors(
    isolated_application: QApplication,
    host_kind: str,
) -> None:
    application = isolated_application
    first = _shown_nested_scroll_parent(application)
    second = _shown_nested_scroll_parent(application)
    host: QWidget | None = None
    try:
        # Construct the host before it has any scroll ancestors. This also
        # covers native surfaces which are reused in a different hierarchy.
        if host_kind == "preview":
            controller = _PreviewControllerStub()
            host = RustPreviewHostFrame(controller=controller)
            renderer_surface = host._viewport
            request_handle = host._host_hwnd
        elif host_kind == "mesh":
            host = RustMeshEditorHostFrame()
            renderer_surface = host._surface
            request_handle = host.host_hwnd
        else:
            host = QWidget()
            host.setMinimumSize(320, 240)
            renderer_surface = host
            request_handle = lambda: _host_widget_hwnd(host)
        assert request_handle() > 0

        def assert_clip_ownership(hierarchy: SimpleNamespace) -> None:
            assert host.parentWidget() is hierarchy.intermediate
            _assert_nonnative(
                *first.ordinary_widgets, *second.ordinary_widgets,
                *first.scroll_boundaries, *second.scroll_boundaries,
            )
            assert host.windowHandle() is not None
            assert host.windowHandle().parent() == hierarchy.window.windowHandle()
            assert host.windowHandle().position() == host.mapTo(hierarchy.window, QPoint())
            visible = host.mask().intersected(QRegion(host.rect()))
            assert not visible.isEmpty()
            for area in hierarchy.scroll_areas:
                assert area.viewport().rect().contains(
                    host.mapTo(area.viewport(), visible.boundingRect().center())
                )
            assert renderer_surface.windowHandle() is not None
            assert request_handle() == int(renderer_surface.windowHandle().winId())
            if renderer_surface is not host:
                assert renderer_surface.parentWidget() is host
                assert renderer_surface.windowHandle().parent() == host.windowHandle()

        host.setParent(first.intermediate)
        first.host_layout.addWidget(host, 1)
        host.show()
        assert request_handle() > 0
        application.processEvents()
        assert_clip_ownership(first)
        # Both the active hierarchy and its future destination stay alien.
        _assert_nonnative(*second.scroll_boundaries)

        native_owner = host.windowHandle().parent()
        qt_parent = host.parentWidget()
        qt_geometry = host.geometry()
        for area in first.scroll_areas:
            for scrollbar in (area.horizontalScrollBar(), area.verticalScrollBar()):
                assert scrollbar.maximum() > 0
                scrollbar.setValue(max(1, scrollbar.maximum() // 2))
        application.processEvents()
        assert host.parentWidget() is qt_parent
        assert host.windowHandle().parent() == native_owner
        assert host.geometry() == qt_geometry
        assert_clip_ownership(first)

        for area in first.scroll_areas:
            area.verticalScrollBar().setValue(area.verticalScrollBar().maximum())
        for _ in range(3):
            application.processEvents()
        assert host.isVisible()
        assert host.mask().intersected(QRegion(host.rect())).isEmpty()
        assert host.geometry() == qt_geometry
        assert host.windowHandle().parent() == native_owner
        _assert_nonnative(*first.ordinary_widgets, *first.scroll_boundaries)

        host.hide()
        first.host_layout.removeWidget(host)
        host.setParent(second.intermediate)
        second.host_layout.addWidget(host, 1)
        host.show()
        assert request_handle() > 0
        application.processEvents()
        assert_clip_ownership(second)
    finally:
        if host is not None:
            host.close()
        _destroy_windows(application, first.window, second.window)


def test_owned_top_level_host_does_not_promote_owner_scroll_viewports(
    isolated_application: QApplication,
) -> None:
    application = isolated_application
    owner = _shown_nested_scroll_parent(application)
    host = QWidget(owner.intermediate, Qt.WindowType.Window)
    try:
        assert host.isWindow()
        assert _host_widget_hwnd(host) > 0
        application.processEvents()
        assert host.parentWidget() is owner.intermediate
        _assert_nonnative(*owner.ordinary_widgets, *owner.scroll_boundaries)
    finally:
        host.close()
        host.deleteLater()
        _destroy_windows(application, owner.window)


@pytest.mark.parametrize("overflow_change", ("viewport_resize", "content_resize"))
def test_native_host_clipping_follows_late_overflow_without_promoting_ancestors(
    isolated_application: QApplication,
    overflow_change: str,
) -> None:
    application = isolated_application
    window = QWidget()
    window.resize(680, 510)
    layout = QVBoxLayout(window)
    scroll = QScrollArea(window)
    scroll.setWidgetResizable(False)
    layout.addWidget(scroll)
    content = QWidget()
    content.resize(320, 240)
    scroll.setWidget(content)
    sibling = QPushButton("Ordinary sibling", content)
    sibling.setGeometry(8, 4, 160, 28)
    host = QWidget(content)
    host.setGeometry(16, 42, 280, 180)
    assert _host_widget_hwnd(host) > 0
    boundaries = (scroll, scroll.viewport(), content)
    try:
        window.show()
        for _ in range(3):
            application.processEvents()
        assert scroll.horizontalScrollBar().maximum() == 0
        assert scroll.verticalScrollBar().maximum() == 0
        _assert_nonnative(*boundaries, sibling)

        if overflow_change == "viewport_resize":
            window.resize(250, 200)
        else:
            content.resize(920, 820)
            scroll.horizontalScrollBar().setValue(120)
            scroll.verticalScrollBar().setValue(120)
        # No further handle request: the observer follows the changed layout.
        for _ in range(3):
            application.processEvents()
        assert scroll.horizontalScrollBar().maximum() > 0
        assert scroll.verticalScrollBar().maximum() > 0
        _assert_nonnative(*boundaries, sibling)
        assert host.parentWidget() is content
        assert host.windowHandle().parent() == window.windowHandle()
        assert host.windowHandle().position() == host.mapTo(window, QPoint())
        assert not host.mask().isEmpty()
        assert not host.mask().intersected(QRegion(host.rect())).isEmpty()
        native_handle = int(host.windowHandle().winId())

        content.resize(320, 240)
        window.resize(680, 510)
        for _ in range(3):
            application.processEvents()
        assert scroll.horizontalScrollBar().maximum() == 0
        assert scroll.verticalScrollBar().maximum() == 0
        assert native_handle == int(host.windowHandle().winId())
        assert host.mask().isEmpty()
        _assert_nonnative(*boundaries, sibling)
    finally:
        _destroy_windows(application, window)


@pytest.mark.parametrize("overflow_change", ("host_resize", "host_move"))
def test_native_host_overflow_is_clipped_even_when_scroll_content_fits(
    isolated_application: QApplication,
    overflow_change: str,
) -> None:
    application = isolated_application
    window = QWidget()
    window.resize(680, 510)
    layout = QVBoxLayout(window)
    scroll = QScrollArea(window)
    scroll.setWidgetResizable(False)
    layout.addWidget(scroll)
    content = QWidget()
    content.resize(320, 240)
    scroll.setWidget(content)
    host = QWidget(content)
    host.setGeometry(16, 42, 280, 180)
    assert _host_widget_hwnd(host) > 0
    boundaries = (scroll, scroll.viewport(), content)
    try:
        window.show()
        for _ in range(3):
            application.processEvents()
        _assert_nonnative(*boundaries)

        if overflow_change == "host_resize":
            host.resize(900, 700)
        else:
            host.move(scroll.viewport().width() - 80, 42)
        for _ in range(3):
            application.processEvents()
        assert scroll.viewport().rect().contains(content.geometry())
        assert scroll.horizontalScrollBar().maximum() == 0
        assert scroll.verticalScrollBar().maximum() == 0
        _assert_nonnative(*boundaries)
        assert host.windowHandle().parent() == window.windowHandle()
        assert not host.mask().isEmpty()
        if overflow_change == "host_resize":
            assert host.mask() == QRegion(QRect(0, 0, 304, 198))
        else:
            assert host.mask().intersected(QRegion(host.rect())).isEmpty()
    finally:
        _destroy_windows(application, window)


def test_reparenting_an_ancestor_refreshes_clipping_without_another_handle_request(
    isolated_application: QApplication,
) -> None:
    application = isolated_application
    window, container, _layout, sibling = _shown_parent(application)
    destination = _shown_nested_scroll_parent(application)
    intermediate = QWidget(container)
    intermediate.setGeometry(0, 0, 340, 280)
    host = QWidget(intermediate)
    host.setGeometry(10, 10, 320, 240)
    assert _host_widget_hwnd(host) > 0
    intermediate.show()
    try:
        application.processEvents()
        _assert_nonnative(container, intermediate, sibling, *destination.scroll_boundaries)
        intermediate.setParent(destination.intermediate)
        intermediate.show()
        for _ in range(3):
            application.processEvents()
        assert host.parentWidget() is intermediate
        assert host.windowHandle().parent() == destination.window.windowHandle()
        assert host.windowHandle().position() == host.mapTo(destination.window, QPoint())
        assert host.geometry() == QRect(10, 10, 320, 240)
        _assert_nonnative(
            container, intermediate, sibling,
            *destination.ordinary_widgets, *destination.scroll_boundaries,
        )
    finally:
        _destroy_windows(application, window, destination.window)



@pytest.mark.parametrize("outside_position", ((-400, 20), (800, 20), (20, -400), (20, 800)))
def test_fully_clipped_host_returns_with_the_same_handle_and_logical_geometry(
    isolated_application: QApplication,
    outside_position: tuple[int, int],
) -> None:
    application = isolated_application
    window, container, _layout, sibling = _shown_parent(application)
    host = QWidget(container)
    host.setGeometry(20, 20, 240, 180)
    assert _host_widget_hwnd(host) > 0
    host.show()
    try:
        for _ in range(3):
            application.processEvents()
        native_handle = int(host.windowHandle().winId())
        host.move(*outside_position)
        for _ in range(3):
            application.processEvents()
        assert host.isVisible()
        assert host.pos() == QPoint(*outside_position)
        assert host.mask().intersected(QRegion(host.rect())).isEmpty()
        assert int(host.windowHandle().winId()) == native_handle
        host.move(20, 20)
        for _ in range(3):
            application.processEvents()
        assert host.geometry() == QRect(20, 20, 240, 180)
        assert host.mask().isEmpty()
        assert int(host.windowHandle().winId()) == native_handle
        _assert_nonnative(container, sibling)
    finally:
        _destroy_windows(application, window)


def test_existing_host_mask_survives_clipping_recovery_and_top_level_detach(
    isolated_application: QApplication,
) -> None:
    application = isolated_application
    if application.platformName() == "offscreen":
        # Qt 6.11 also crashes here with a bare QWidget and no CDMW code.
        # The native Windows run covers detach, mask restoration and destruction.
        pytest.skip("Native-child detach requires the Windows Qt platform; offscreen crashes at teardown")
    window = QWidget()
    window.resize(420, 320)
    parent = QWidget(window)
    parent.setGeometry(0, 0, 400, 300)
    host = QWidget(parent)
    host.setGeometry(20, 20, 280, 180)
    baseline = QRegion(QRect(10, 10, 240, 140))
    host.setMask(baseline)
    assert _host_widget_hwnd(host) > 0
    window.show()
    try:
        for _ in range(3):
            application.processEvents()
        assert host.mask() == baseline
        parent.resize(180, 130)
        for _ in range(3):
            application.processEvents()
        assert host.mask() != baseline
        assert host.mask().subtracted(baseline).isEmpty()
        parent.resize(400, 300)
        for _ in range(3):
            application.processEvents()
        assert host.mask() == baseline

        parent.resize(180, 130)
        for _ in range(3):
            application.processEvents()
        host.setParent(None, Qt.WindowType.Window)
        host.show()
        for _ in range(3):
            application.processEvents()
        assert host.isWindow()
        assert host.mask() == baseline
        assert host.windowHandle().parent() is None
        parent.resize(80, 60)
        for _ in range(3):
            application.processEvents()
        assert host.mask() == baseline
        _assert_nonnative(parent)
    finally:
        host.close()
        host.deleteLater()
        _destroy_windows(application, window)


@pytest.mark.parametrize("notification", (QEvent.Type.WinIdChange, QEvent.Type.DevicePixelRatioChange))
def test_native_mask_is_reapplied_after_handle_or_dpi_notification_without_size_change(
    isolated_application: QApplication,
    monkeypatch: pytest.MonkeyPatch,
    notification: QEvent.Type,
) -> None:
    application = isolated_application
    window = QWidget()
    parent = QWidget(window)
    parent.setGeometry(0, 0, 160, 120)
    host = QWidget(parent)
    host.setGeometry(20, 20, 280, 180)
    assert _host_widget_hwnd(host) > 0
    window.show()
    try:
        for _ in range(3):
            application.processEvents()
        handle = host.windowHandle()
        mask, geometry = QRegion(host.mask()), host.geometry()
        calls = []
        original = handle.setMask

        def record_mask(region):
            calls.append(QRegion(region))
            original(region)

        # Restore the Qt method while its C++ window is still alive.
        with monkeypatch.context() as mask_patch:
            mask_patch.setattr(handle, "setMask", record_mask)
            QCoreApplication.sendEvent(host, QEvent(notification))
            for _ in range(3):
                application.processEvents()
            assert calls == [mask]
            assert host.mask() == mask
            assert host.geometry() == geometry
            _assert_nonnative(parent)
    finally:
        _destroy_windows(application, window)
