from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from cdmw.ui.archive_browser.static_replacement_added_part_texture_items import added_part_texture_item

_APP = QApplication.instance() or QApplication([])


def test_added_part_texture_item_populates_columns_roles_and_status_colors() -> None:
    item = added_part_texture_item(
        source_index=4,
        source_display_name="source 4",
        target_summary="Body",
        material_name="Skin",
        base_display="base.dds",
        normal_display="normal.dds",
        material_display="mask.dds",
        height_display="-",
        status_label="Ready",
        status_color="#3fb950",
    )

    assert item.text(0) == "source 4"
    assert item.text(2) == "Skin"
    assert item.text(7) == "Ready"
    assert item.data(0, Qt.UserRole) == 4
    assert item.toolTip(4) == "normal.dds"
    assert item.background(7).color().name() == "#3fb950"
    assert item.foreground(7).color().name() == "#0d1117"

    warning_item = added_part_texture_item(
        source_index=5,
        source_display_name="source 5",
        target_summary="Attach required",
        material_name="Cloth",
        base_display="-",
        normal_display="-",
        material_display="-",
        height_display="-",
        status_label="Missing base",
        status_color="#f85149",
    )
    assert warning_item.foreground(7).color().name() == "#ffffff"
