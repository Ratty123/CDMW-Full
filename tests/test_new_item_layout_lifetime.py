"""Rust projection must not retain wrappers for layout items Qt can delete."""

import os
import threading

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QApplication, QDialogButtonBox, QFormLayout, QGridLayout, QHBoxLayout,
    QPushButton, QVBoxLayout, QWidget, QWidgetItem,
)
from shiboken6 import delete, getAllValidWrappers, invalidate, isValid

from cdmw.ui.new_item.rust_ui_document import PresentationDocument
from cdmw.ui.new_item.rust_ui_portals import PreviewPortals
from cdmw.ui.wrapping_layout import WrappingLayout
from tests.test_new_item_model_apply import studio


@pytest.mark.parametrize("layout_type", [QVBoxLayout, QGridLayout, QFormLayout])
def test_projection_does_not_retain_items_after_widget_moves(layout_type):
    app = QApplication.instance() or QApplication([])
    original, destination = QWidget(), QWidget()
    layout, target = layout_type(original), QVBoxLayout(destination)
    # QObject creation order deliberately differs from layout order.
    last, first = QPushButton("Last", original), QPushButton("First", original)
    nested = QHBoxLayout()
    middle = QPushButton("Middle", original)
    if layout_type is QGridLayout:
        layout.addWidget(first, 0, 1, 1, 2)
        layout.addLayout(nested, 1, 0, 2, 3)
        layout.addWidget(last, 3, 2)
    elif layout_type is QFormLayout:
        layout.addRow(first)
        layout.addRow(nested)
        layout.addRow(last)
    else:
        layout.addWidget(first, 2)
        layout.addStretch()
        layout.addLayout(nested, 3)
        layout.addWidget(last)
    nested.addWidget(middle)
    observed = []
    try:
        projection = PresentationDocument()
        existing_bindings = {id(obj) for obj in getAllValidWrappers()}
        node = projection.layout(layout)
        observed = [obj for obj in getAllValidWrappers()
                    if isinstance(obj, QWidgetItem) and id(obj) not in existing_bindings]
        target.addWidget(first)
        target.addWidget(middle)
        assert not any(isValid(item) for item in observed), "Projection retained Qt-owned items across a move"
        assert [child["label"] for child in node["children"]] == ["First", "", "Last"]
        assert node["children"][1]["children"][0]["label"] == "Middle"
        if layout_type is QGridLayout:
            assert [child["cell"] for child in node["children"]] == [[0, 1, 1, 2], [1, 0, 2, 3], [3, 2, 1, 1]]
        elif layout_type is QFormLayout:
            assert [child["cell"] for child in node["children"]] == [[0, 0, 1, 2], [1, 0, 1, 2], [2, 0, 1, 2]]
        else:
            assert [child["stretch"] for child in node["children"]] == [2, 3, 0]
        assert nested.parent() is layout
    finally:
        # A failing pre-fix run must not leave dangling bindings in this process.
        for item in observed:
            invalidate(item)
        delete(original)
        delete(destination)


def test_projection_preserves_custom_layout_items_and_dialog_actions():
    app = QApplication.instance() or QApplication([])
    root = QWidget()
    layout = QVBoxLayout(root)
    wrapping = WrappingLayout()
    button = QPushButton("Wrapped")
    wrapping.addWidget(button)
    layout.addLayout(wrapping)
    actions = QHBoxLayout()
    buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
    actions.addWidget(buttons)
    layout.addLayout(actions)
    item = wrapping.itemAt(0)
    try:
        projection = PresentationDocument()
        node = projection.layout(layout)
        assert node["children"][0]["children"][0]["label"] == "Wrapped"
        assert node["children"][1]["props"]["dialog_actions"]
        assert isValid(item) and item.widget() is button
        wrapping.setGeometry(root.rect())
        assert projection.layout(layout) == node
    finally:
        delete(root)


def test_portal_retires_replaced_items_before_parent_teardown():
    app = QApplication.instance() or QApplication([])
    original, host = QWidget(), QWidget()
    host.resize(800, 600)
    layout = QVBoxLayout(original)
    viewport = QWidget()
    layout.addWidget(viewport, 2, Qt.AlignHCenter)
    portals = PreviewPortals(host)
    projection = PresentationDocument()
    projection.portals["preview"] = viewport
    original_item = layout.itemAt(0)
    replacement_item = None
    try:
        portals.update(projection, {"pixels_per_point": 1, "portals": [
            {"id": "preview", "rect": [0, 0, 400, 300], "clip": [0, 0, 800, 600]},
        ]})
        assert not isValid(original_item)
        replacement_item = layout.itemAt(0)
        assert replacement_item.widget() is portals._placeholders["preview"]
        portals.restore()
        assert not isValid(replacement_item)
        assert viewport.parentWidget() is original and layout.indexOf(viewport) == 0
        assert layout.stretch(0) == 2
        assert layout.itemAt(0).alignment() == Qt.AlignHCenter
    finally:
        portals.restore()
        # Unfixed replaceWidget() leaves its returned native items caller-owned.
        for item in (original_item, replacement_item):
            if item is not None and isValid(item):
                layout.removeItem(item)
                delete(item)
        delete(original)
        delete(host)


def test_glow_to_cold_perks_with_projection_portals_and_running_preview(studio, tmp_path, monkeypatch):
    from cdmw.ui.combo_popup_limiter import ensure_app_combo_popup_limiter
    from cdmw.ui.localization import UiLocalizer
    from cdmw.ui.new_item.effect_workspace import GuidedEffectsWorkspace
    from cdmw.ui.new_item.rust_ui_bridge import NewItemPresentationBridge
    from cdmw.workers.new_item_lookup import _LookupThread
    from tests.test_new_item_responsiveness import pump
    from tests.test_new_item_rust_ui import _send

    app, tab = studio
    localizer = UiLocalizer(language_dir=tmp_path / "language", language_code="en")
    ensure_app_combo_popup_limiter(app)
    localizer.activate_runtime_tracking(tab, application=app)
    # Exercise the real GUI/worker handoff without requiring game data or a GPU.
    monkeypatch.setattr(GuidedEffectsWorkspace, "_rebuild_preview", lambda self: None)
    monkeypatch.setattr(tab.controller, "material_parts", lambda: (("Blade", "Blade edge"),))
    ran = []
    original_run = _LookupThread.run

    def lookup_run(thread):
        ran.append(threading.get_ident())
        return original_run(thread)

    monkeypatch.setattr(_LookupThread, "run", lookup_run)
    bridge = NewItemPresentationBridge(tab)
    host = QWidget()
    host.resize(1440, 960)
    portals = PreviewPortals(host)
    snapshots, borrowed = [], []

    def project():
        snapshots.append(bridge.snapshot())
        portals.update(bridge.document, {"pixels_per_point": 1, "portals": [
            {"id": identifier, "rect": [0, 0, 600, 500], "clip": [0, 0, 1440, 960]}
            for identifier in bridge.document.portals
        ]})

    timer = QTimer()
    timer.setInterval(100)
    timer.timeout.connect(project)
    started, release = threading.Event(), threading.Event()

    def pending_preview(*_args):
        started.set()
        assert release.wait(10), "preview fixture timed out"
        return None

    try:
        tab.show()
        preview = tab.model_panel.preview
        assert preview._ensure_host()
        preview.host.show()
        app.processEvents()
        project()
        assert portals._attached
        for step in (1, 2, 0, 2):
            old_layout = preview.parentWidget().layout()
            old_item = old_layout.itemAt(old_layout.indexOf(preview))
            borrowed.append(old_item)
            tab.show_step(step)
            assert not isValid(old_item), "Preview move retained its deleted layout item"
            project()
        _send(bridge, tab.model_panel.inspector_tabs, "tab", 1)
        tab.model_panel.refresh_glow_parts()
        _send(bridge, tab.model_panel.glow_box, "toggle", True)
        _send(bridge, tab.model_panel.glow_parts, "check_cell", {"path": [0], "column": 0, "check": 2})
        preview._launch_package_worker(pending_preview, None)
        pump(app, started.is_set)
        ticks_before = len(snapshots)
        timer.start()
        assert tab._perks_panel is None
        tab.show_step(4)
        panel = tab.perks_panel
        lanes = (panel._perk_lookup, panel.effects_workspace._library_build_lane,
                 panel.effects_workspace._library_search_lane)
        assert all(not lane._synchronous for lane in lanes)
        pump(app, lambda: len(ran) >= 3 and not any(lane.busy for lane in lanes)
             and len(snapshots) > ticks_before)
        assert all(tid != threading.get_ident() for tid in ran)
        assert tab.controller.draft.glow_parts == ("Blade",)
        portals.restore()
        assert preview.host.parentWidget() is preview
        project()  # Renderer retry reattaches the same viewport safely.
    finally:
        release.set()
        timer.stop()
        for item in borrowed:
            if isValid(item):
                invalidate(item)
        portals.restore()
        bridge.close()
        tab.request_shutdown()
        pump(app, lambda: not tab.iter_shutdown_workers())
        localizer.shutdown()
        delete(host)
