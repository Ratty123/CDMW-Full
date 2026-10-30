"""Media details must not prevent resizing the neighbouring Asset Family pane."""
from __future__ import annotations

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QLabel, QSplitter, QStackedWidget, QTabWidget, QTreeWidget

from cdmw.ui.preview_widgets import MediaPreviewWidget


@pytest.mark.parametrize("page", ["media", "details", "other_preview"])
def test_long_audio_details_allow_asset_family_splitter_resize(page: str) -> None:
    app = QApplication.instance() or QApplication([])
    media = MediaPreviewWidget("Select a file", theme_key="dark")
    stack = QStackedWidget()
    stack.addWidget(media)
    stack.addWidget(QLabel("Another preview"))
    tabs = QTabWidget()
    tabs.addTab(stack, "Preview")
    tabs.addTab(QTreeWidget(), "Details")
    family = QTreeWidget()
    family.setMinimumWidth(320)
    splitter = QSplitter(Qt.Horizontal)
    splitter.setChildrenCollapsible(False)
    splitter.addWidget(tabs)
    splitter.addWidget(family)
    splitter.resize(1500, 800)
    splitter.show()
    app.processEvents()
    try:
        cache_path = (
            "\\\\?\\D:\\CDMW Full\\dist\\workspace\\cache\\archive_preview_cache\\"
            + "0123456789abcdef" * 4
            + "\\unique_kliff_aidialogstringinfo_affinity_collection_50996.vgmstream.wav"
        )
        details = f"Archive preview source: {cache_path}\nPlayback source: {cache_path}"
        media.clear_media(details)
        if page == "details":
            tabs.setCurrentIndex(1)
        elif page == "other_preview":
            stack.setCurrentIndex(1)
        app.processEvents()

        assert splitter.width() == 1500
        splitter.moveSplitter(600, 1)
        app.processEvents()
        assert 580 <= tabs.width() <= 620
        assert family.width() >= 850
        assert media.info_label.text() == details
        if page == "media":
            assert media.play_button.geometry().left() >= 0
            assert media.position_slider.width() >= 100
            assert media.time_label.geometry().right() < media.width()

        splitter.resize(1000, 700)
        splitter.moveSplitter(450, 1)
        app.processEvents()
        assert splitter.width() == 1000
        assert 430 <= tabs.width() <= 470
        assert family.width() >= 500
    finally:
        media.shutdown()
        splitter.close()
        splitter.deleteLater()
        app.processEvents()
