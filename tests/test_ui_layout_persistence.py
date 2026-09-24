"""Real Qt resize gestures and fresh widgets/settings simulate app restarts."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QCoreApplication, QEvent, QSettings, Qt
from PySide6.QtWidgets import QApplication, QDialog, QHeaderView, QSplitter, QTreeWidget, QVBoxLayout, QWidget
from PySide6.QtTest import QTest
from PySide6.QtCore import QPoint

from cdmw.ui.layout_persistence import (
    install_layout_persistence, native_dialog_layout, remember_splitter_resize,
    restore_splitter_layout, saved_splitter_sizes,
)

_APP = QApplication.instance() or QApplication([])


@pytest.fixture
def layouts(tmp_path):
    owner = QWidget()
    settings = QSettings(str(tmp_path / "CrimsonDesertModWorkbench.cfg"), QSettings.IniFormat)
    policy = install_layout_persistence(owner, settings)
    yield policy, settings
    _APP.removeEventFilter(policy)
    _APP._cdmw_layout_persistence = None
    owner.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)


def settle():
    for _ in range(3):
        _APP.processEvents()


def panes(name="example", orientation=Qt.Horizontal):
    root = QDialog()
    root.setObjectName(name)
    root.resize(740, 700)
    layout = QVBoxLayout(root)
    split = QSplitter(orientation)
    split.setObjectName("preview")
    layout.addWidget(split)
    for _ in range(2):
        split.addWidget(QWidget())
    split.setSizes([500, 500])
    root.show()
    settle()
    return root, split


def close(widget):
    widget.close()
    widget.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)


def test_window_and_splitter_survive_fresh_settings_and_lazy_recreation(layouts):
    policy, settings = layouts
    first, split = panes()
    first.resize(720, 640)
    first.move(25, 30)
    split.moveSplitter(310, 1)
    expected_size, expected_panes = first.size(), split.sizes()
    # Close before a debounce timer fires; state has already been captured.
    first.close()
    policy.flush()
    close(first)
    policy.settings = QSettings(settings.fileName(), QSettings.IniFormat)
    second, restored = panes()
    try:
        assert second.size() == expected_size
        assert restored.sizes() == expected_panes
        assert policy.settings.fileName().endswith("CrimsonDesertModWorkbench.cfg")
    finally:
        close(second)


def test_responsive_defaults_hidden_panes_and_orientation_keep_user_choices(layouts):
    _policy, _settings = layouts
    root, split = panes()
    try:
        split.moveSplitter(275, 1)
        horizontal = saved_splitter_sizes(split)
        split.widget(1).hide()
        split.setSizes([1000, 0])
        settle()
        assert saved_splitter_sizes(split) == horizontal
        split.widget(1).show()
        settle()
        assert restore_splitter_layout(split)
        assert split.sizes() == horizontal
        split.setOrientation(Qt.Vertical)
        settle()
        split.moveSplitter(205, 1)
        vertical = saved_splitter_sizes(split)
        assert vertical != horizontal
        split.setOrientation(Qt.Horizontal)
        split.setSizes([1, 1])
        settle()
        assert split.sizes() == horizontal
        split.setOrientation(Qt.Vertical)
        settle()
        assert split.sizes() == vertical
    finally:
        close(root)


def test_splitter_identity_survives_detaching_owner_and_other_dialogs(layouts):
    _policy, _settings = layouts
    root, split = panes("tool-dialog")
    root2, other = panes("different-dialog")
    try:
        split.moveSplitter(210, 1)
        saved = saved_splitter_sizes(split)
        assert not saved_splitter_sizes(other)
        shell = QWidget()
        root.setParent(shell, Qt.Window)
        root.show()
        settle()
        assert saved_splitter_sizes(split) == saved
        root.setParent(None)
        close(shell)
    finally:
        close(root)
        close(root2)


def test_resizing_beside_a_never_opened_pane_does_not_save_it_as_collapsed(layouts):
    root, split = panes()
    try:
        split.widget(1).hide()
        settle()
        remember_splitter_resize(split)
        split.widget(1).show()
        split.setSizes([420, 260])
        settle()
        assert restore_splitter_layout(split)
        assert split.sizes()[1] > 100
        # An intentional collapse of a visible pane remains a collapse.
        split.moveSplitter(split.width(), 1)
        assert saved_splitter_sizes(split)[1] == 0
    finally:
        close(root)


def test_malformed_settings_and_disabled_preference_do_not_apply(layouts):
    policy, settings = layouts
    root, split = panes()
    try:
        key = policy._splitter_key(split)
        for value in ("invalid", "[1]", "[-10, 50]", "[0, 0]", "[true, 40]"):
            settings.setValue(key, value)
            assert not restore_splitter_layout(split)
        settings.setValue(key, "[150, 750]")
        settings.setValue("preferences/remember_splitter_sizes", False)
        assert not restore_splitter_layout(split)
        split.moveSplitter(400, 1)
        assert settings.value(key) == "[150, 750]"
    finally:
        close(root)


def test_native_split_and_dialog_geometry_use_same_cfg(layouts):
    policy, settings = layouts
    root, split = panes()
    try:
        remember_splitter_resize(split, [760, 320])
        assert saved_splitter_sizes(split) == [760, 320]
        native_dialog_layout(root, [50, 80, 820, 540])
        policy.flush()
        policy.settings = QSettings(settings.fileName(), QSettings.IniFormat)
        assert native_dialog_layout(root) == [50, 80, 820, 540]
    finally:
        close(root)


def test_column_width_survives_real_header_drag_and_recreation(layouts):
    policy, _settings = layouts

    def table():
        dialog = QDialog()
        dialog.setObjectName("column-layout")
        dialog.resize(700, 400)
        view = QTreeWidget()
        view.setColumnCount(2)
        view.setHeaderLabels(["First", "Second"])
        view.header().setStretchLastSection(False)
        view.header().setSectionResizeMode(QHeaderView.Interactive)
        QVBoxLayout(dialog).addWidget(view)
        dialog.show()
        settle()
        return dialog, view

    root, view = table()
    header = view.header()
    start = QPoint(header.sectionSize(0), header.height() // 2)
    end = start + QPoint(95, 0)
    QTest.mousePress(header.viewport(), Qt.LeftButton, pos=start)
    QTest.mouseMove(header.viewport(), end)
    QTest.mouseRelease(header.viewport(), Qt.LeftButton, pos=end)
    expected = header.sectionSize(0)
    assert expected >= 180
    policy.flush()
    close(root)
    root, view = table()
    try:
        assert view.header().sectionSize(0) == expected
    finally:
        close(root)


def test_placement_studio_real_nested_viewports_restore(layouts, tmp_path):
    from tools.placement_studio.corpus import Baseline
    from tools.placement_studio.window import PlacementStudioWindow

    policy, _settings = layouts
    expected = {}
    for attempt in range(2):
        window = PlacementStudioWindow(Baseline(tmp_path, {}))
        window.resize(1700, 1000)
        window.show()
        settle()
        try:
            # Include panes on inactive animation/constraint pages as well.
            for split in window.findChildren(QSplitter):
                if not attempt:
                    policy._splitter_key(split)
                    split.setSizes([200 + 137 * i for i in range(split.count())])
                    remember_splitter_resize(split)
                    expected[policy._splitter_key(split)] = saved_splitter_sizes(split)
                else:
                    assert restore_splitter_layout(split)
                    assert saved_splitter_sizes(split) == expected[policy._splitter_key(split)]
            assert len(expected) >= 5
            policy.flush()
        finally:
            close(window)
