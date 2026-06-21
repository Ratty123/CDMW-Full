from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QApplication, QCheckBox, QComboBox, QDoubleSpinBox, QTreeWidget, QTreeWidgetItem, QWidget

from cdmw.ui.archive_browser.static_replacement_qt_helpers import (
    IntSliderSpinRow,
    alignment_camera_button,
    auto_fit_tree_columns,
    clear_tree_current_item,
    configure_alignment_tree,
    configure_texture_mapping_tree,
    commit_spinbox_text,
    fit_tree_height_to_rows,
    inline_help_button,
    install_tree_column_autofit,
    make_double_spin,
    make_int_spin,
    make_int_slider_spin_row,
    make_spinbox_slider,
    new_alignment_scroll_tab,
    parts_outliner_source_index,
    qt_object_is_valid,
    safe_start_timer,
    safe_stop_timer,
    safe_timer_active,
    set_checkbox_checked_silently,
    set_combo_index_silently,
    set_double_spin_value_silently,
    set_int_slider_spin_value_silently,
    tree_item_primary_index,
    tree_item_source_index_or_fallback,
    tree_item_target_index_or_fallback,
    visible_tree_row_count,
    wrap_spin_with_slider,
)

_APP = QApplication.instance() or QApplication([])


def test_inline_and_camera_button_factories_apply_expected_widget_contract() -> None:
    help_button = inline_help_button("Help text")
    camera_button = alignment_camera_button("Front", "CameraFront", "View front")

    assert help_button.text() == "?"
    assert help_button.objectName() == "InlineHelpButton"
    assert help_button.width() == 16
    assert help_button.height() == 16
    assert help_button.toolTip() == "Help text"
    assert help_button.focusPolicy() == Qt.NoFocus
    assert camera_button.text() == "Front"
    assert camera_button.objectName() == "CameraFront"
    assert camera_button.minimumWidth() == 0
    assert camera_button.maximumWidth() == 64
    assert camera_button.toolTip() == "View front"


def test_new_alignment_scroll_tab_builds_scroll_area_page_and_layout() -> None:
    parent = QWidget()

    scroll, page, layout = new_alignment_scroll_tab(
        parent,
        "TestScroll",
        embedded=False,
        content_minimum_width=320,
    )

    assert scroll.parent() is parent
    assert scroll.objectName() == "TestScroll"
    assert scroll.widgetResizable() is True
    assert scroll.widget() is page
    assert page.minimumWidth() == 320
    assert page.layout() is layout
    assert layout.spacing() == 3


def test_clear_tree_current_item_clears_selection_and_current_index() -> None:
    tree = QTreeWidget()
    item = QTreeWidgetItem(["row"])
    tree.addTopLevelItem(item)
    tree.setCurrentItem(item)
    item.setSelected(True)

    clear_tree_current_item(tree)

    assert tree.selectedItems() == []
    assert tree.currentIndex().isValid() is False


def test_commit_spinbox_text_interprets_pending_line_edit_text() -> None:
    spin = QDoubleSpinBox()
    spin.setRange(-10.0, 10.0)
    spin.setDecimals(2)
    spin.lineEdit().setText(f"2{spin.locale().decimalPoint()}50")

    commit_spinbox_text(spin, block_signals=True)

    assert spin.value() == 2.5


def test_make_double_spin_applies_numeric_configuration() -> None:
    spin = make_double_spin(
        value=2.5,
        minimum=-5.0,
        maximum=5.0,
        decimals=3,
        step=0.25,
        suffix=" deg",
    )

    assert spin.minimum() == -5.0
    assert spin.maximum() == 5.0
    assert spin.decimals() == 3
    assert spin.singleStep() == 0.25
    assert spin.value() == 2.5
    assert spin.keyboardTracking() is False
    assert spin.suffix() == " deg"

    positional_spin = make_double_spin(1.0, 0.0, 2.0, 1, 0.5)
    assert positional_spin.value() == 1.0
    assert positional_spin.suffix() == ""


def test_make_spinbox_slider_links_values_and_wraps_spin() -> None:
    spin = make_double_spin(1.0, -2.0, 2.0, 2, 0.25)
    slider = make_spinbox_slider(
        spin,
        scale=100.0,
        tooltip="Move",
        object_name="TestSlider",
        minimum_width=72,
        slider_minimum=-1.0,
        slider_maximum=1.0,
    )

    assert slider.objectName() == "TestSlider"
    assert slider.toolTip() == "Move"
    assert slider.minimum() == -100
    assert slider.maximum() == 100
    assert slider.singleStep() == 25
    assert slider.minimumWidth() == 72

    spin.setValue(0.5)
    assert slider.value() == 50
    slider.setValue(-25)
    assert spin.value() == -0.25

    wrapper = wrap_spin_with_slider(spin, slider)
    assert wrapper.layout().count() == 2


def test_make_int_slider_spin_row_configures_clamped_pair() -> None:
    row = make_int_slider_spin_row(
        slider_object_name="Slider",
        spin_object_name="Spin",
        minimum=-10,
        maximum=10,
        value=20,
        tooltip="Adjust",
        suffix=" pts",
        single_step=2,
        page_step=4,
        spacing=7,
    )

    assert isinstance(row, IntSliderSpinRow)
    assert row.slider.objectName() == "Slider"
    assert row.spin.objectName() == "Spin"
    assert row.slider.minimum() == -10
    assert row.slider.maximum() == 10
    assert row.slider.singleStep() == 2
    assert row.slider.pageStep() == 4
    assert row.slider.value() == 10
    assert row.spin.value() == 10
    assert row.spin.suffix() == " pts"
    assert row.slider.toolTip() == "Adjust"
    assert row.spin.toolTip() == "Adjust"
    assert row.row.spacing() == 7
    assert row.row.count() == 2


def test_make_int_spin_configures_optional_properties_and_clamps_value() -> None:
    spin = make_int_spin(
        object_name="Channel",
        minimum=0,
        maximum=255,
        value=300,
        prefix="R ",
        suffix=" px",
        tooltip="Red",
        minimum_width=64,
        keyboard_tracking=False,
    )

    assert spin.objectName() == "Channel"
    assert spin.minimum() == 0
    assert spin.maximum() == 255
    assert spin.value() == 255
    assert spin.prefix() == "R "
    assert spin.suffix() == " px"
    assert spin.toolTip() == "Red"
    assert spin.minimumWidth() == 64
    assert spin.keyboardTracking() is False


def test_set_int_slider_spin_value_silently_clamps_and_blocks_signals() -> None:
    row = make_int_slider_spin_row(
        slider_object_name="Slider",
        spin_object_name="Spin",
        minimum=0,
        maximum=100,
        value=10,
        tooltip="Adjust",
    )
    signal_counts = {"slider": 0, "spin": 0}
    row.slider.valueChanged.connect(lambda _value: signal_counts.__setitem__("slider", signal_counts["slider"] + 1))
    row.spin.valueChanged.connect(lambda _value: signal_counts.__setitem__("spin", signal_counts["spin"] + 1))

    value = set_int_slider_spin_value_silently(row.slider, row.spin, 200, minimum=0, maximum=100)

    assert value == 100
    assert row.slider.value() == 100
    assert row.spin.value() == 100
    assert signal_counts == {"slider": 0, "spin": 0}


def test_set_double_spin_value_silently_blocks_signals() -> None:
    spin = make_double_spin(0.0, -10.0, 10.0, 2, 0.25)
    signal_count = {"value": 0}
    spin.valueChanged.connect(lambda _value: signal_count.__setitem__("value", signal_count["value"] + 1))

    set_double_spin_value_silently(spin, 2.5)

    assert spin.value() == 2.5
    assert signal_count["value"] == 0


def test_tree_item_primary_index_reads_scalar_or_first_sequence_value() -> None:
    item = QTreeWidgetItem()

    assert tree_item_primary_index(None) == -1
    item.setData(0, Qt.UserRole, (4, 5))
    assert tree_item_primary_index(item) == 4
    item.setData(0, Qt.UserRole, "7")
    assert tree_item_primary_index(item) == 7
    item.setData(0, Qt.UserRole, "bad")
    assert tree_item_primary_index(item) == -1


def test_visible_tree_row_count_respects_hidden_and_expanded_children() -> None:
    tree = QTreeWidget()
    parent = QTreeWidgetItem(["parent"])
    child = QTreeWidgetItem(["child"])
    hidden_child = QTreeWidgetItem(["hidden"])
    parent.addChild(child)
    parent.addChild(hidden_child)
    tree.addTopLevelItem(parent)
    hidden_child.setHidden(True)

    assert visible_tree_row_count(parent) == 1
    parent.setExpanded(True)
    assert visible_tree_row_count(parent) == 2
    parent.setHidden(True)
    assert visible_tree_row_count(parent) == 0


def test_fit_tree_height_to_rows_sets_fixed_height_with_screen_cap() -> None:
    class _Geometry:
        def height(self) -> int:
            return 220

    class _Screen:
        def availableGeometry(self) -> _Geometry:
            return _Geometry()

    tree = QTreeWidget()
    tree.setColumnCount(1)
    tree.addTopLevelItem(QTreeWidgetItem(["row"]))

    fit_tree_height_to_rows(
        tree,
        minimum=40,
        screen_margin=20,
        maximum=80,
        screen_provider=lambda: _Screen(),
    )

    assert tree.minimumHeight() == tree.maximumHeight()
    assert 40 <= tree.minimumHeight() <= 80


def test_configure_alignment_tree_sets_columns_and_persistence() -> None:
    tree = QTreeWidget()
    tree.setColumnCount(3)
    calls: list[dict[str, object]] = []

    configure_alignment_tree(
        tree,
        (40, 80, 120),
        max_height=240,
        stretch_columns=(1,),
        persist_key="parts",
        settings=object(),
        save_callback=lambda: None,
        persist_columns=lambda *args, **kwargs: calls.append({"args": args, "kwargs": kwargs}),
    )

    assert tree.rootIsDecorated() is False
    assert tree.uniformRowHeights() is True
    assert tree.columnWidth(0) == 40
    assert tree.columnWidth(2) >= 120
    assert tree.maximumHeight() == 240
    assert calls
    assert calls[0]["args"][2] == "alignment/parts"
    assert calls[0]["kwargs"]["minimum_width"] == 28


def test_configure_texture_mapping_tree_sets_expected_defaults() -> None:
    tree = QTreeWidget()
    tree.setColumnCount(6)
    calls: list[dict[str, object]] = []

    configure_texture_mapping_tree(
        tree,
        persist_key="textures",
        settings=object(),
        save_callback=lambda: None,
        persist_columns=lambda *args, **kwargs: calls.append({"args": args, "kwargs": kwargs}),
    )

    assert tree.rootIsDecorated() is False
    assert tree.uniformRowHeights() is True
    assert [tree.columnWidth(column) for column in range(6)] == [56, 170, 150, 170, 118, 240]
    assert tree.maximumHeight() == 420
    assert calls
    assert calls[0]["args"][2] == "alignment/textures"
    assert calls[0]["kwargs"]["minimum_width"] == 38


def test_auto_fit_tree_columns_honors_defer_property() -> None:
    tree = QTreeWidget()
    tree.setColumnCount(2)
    tree.addTopLevelItem(QTreeWidgetItem(["wide value", "other"]))
    tree.setColumnWidth(0, 77)
    tree.setColumnWidth(1, 88)
    tree.setProperty("cdmw_defer_autofit", True)

    auto_fit_tree_columns(tree, (20, 20), (200, 200), expand_column=0)

    assert tree.columnWidth(0) == 77
    assert tree.columnWidth(1) == 88


def test_install_tree_column_autofit_registers_filter() -> None:
    tree = QTreeWidget()
    tree.setColumnCount(1)
    event_filters: list[object] = []

    event_filter = install_tree_column_autofit(
        tree,
        (20,),
        (100,),
        event_filters=event_filters,
    )

    assert event_filters == [event_filter]


def test_parts_outliner_source_index_requires_source_kind_and_reads_first_source() -> None:
    item = QTreeWidgetItem()

    assert parts_outliner_source_index(None) == -1
    item.setData(0, Qt.UserRole, "target")
    item.setData(0, Qt.UserRole + 2, (3,))
    assert parts_outliner_source_index(item) == -1
    item.setData(0, Qt.UserRole, "source")
    assert parts_outliner_source_index(item) == 3
    item.setData(0, Qt.UserRole + 2, "bad")
    assert parts_outliner_source_index(item) == -1


def test_tree_item_source_and_target_index_helpers_fallback_to_selection_state() -> None:
    source_item = QTreeWidgetItem()
    target_item = QTreeWidgetItem()

    assert tree_item_source_index_or_fallback(None, 6) == 6
    source_item.setData(1, Qt.UserRole, (8,))
    assert tree_item_source_index_or_fallback(source_item, 6) == 8
    source_item.setData(0, Qt.UserRole, "bad")
    source_item.setData(1, Qt.UserRole, "")
    assert tree_item_source_index_or_fallback(source_item, 6) == -1

    assert tree_item_target_index_or_fallback(None, 3) == 3
    target_item.setData(0, Qt.UserRole + 1, 9)
    assert tree_item_target_index_or_fallback(target_item, 3) == 9
    target_item.setData(0, Qt.UserRole + 1, "bad")
    assert tree_item_target_index_or_fallback(target_item, 3) == 3


def test_silent_checkbox_and_combo_setters_block_signals_and_skip_invalid_combo_index() -> None:
    checkbox = QCheckBox()
    combo = QComboBox()
    combo.addItems(["A", "B"])
    checkbox_count = {"value": 0}
    combo_count = {"value": 0}
    checkbox.toggled.connect(lambda _checked: checkbox_count.__setitem__("value", checkbox_count["value"] + 1))
    combo.currentIndexChanged.connect(lambda _index: combo_count.__setitem__("value", combo_count["value"] + 1))

    set_checkbox_checked_silently(checkbox, True)
    set_combo_index_silently(combo, 1)
    set_combo_index_silently(combo, -1)
    set_combo_index_silently(combo, 1)

    assert checkbox.isChecked() is True
    assert combo.currentIndex() == 1
    assert checkbox_count["value"] == 0
    assert combo_count["value"] == 0


def test_qt_object_and_timer_helpers_tolerate_missing_or_live_timers() -> None:
    timer = QTimer()

    assert qt_object_is_valid(None) is False
    assert qt_object_is_valid(timer) is True
    assert safe_timer_active(None) is False

    safe_start_timer(timer)
    assert safe_timer_active(timer) is True

    safe_stop_timer(timer)
    assert safe_timer_active(timer) is False
