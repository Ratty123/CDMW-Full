"""Archive browser columns fit their content on startup and yield to manual resizes."""

import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QSettings, QTimer
from PySide6.QtWidgets import QApplication, QHeaderView

from cdmw.models import ArchiveEntry
from cdmw.ui.archive_browser.header import ArchiveBrowserHeaderMixin
from cdmw.ui.archive_browser.model import ArchiveBrowserRowPayload, ArchiveBrowserTreeView
from cdmw.ui.shell.responsiveness_controller import ResponsivenessControllerMixin


BUILD_DEFAULT_WIDTHS = (480, 190, 110, 72, 130, 130, 122, 360)
NAMES = (
    "cd_pgw_00_nude_00_0001.pac",
    "cd_phm_00_nude_00_0001_dm01.pac",
    "cd_phm_00_nude_00_4001_hand_hair.pac",
    "cd_phw_00_nude_00_0001_damian.pac",
)


def _app() -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


class _ArchiveColumnHost(ArchiveBrowserHeaderMixin, ResponsivenessControllerMixin):
    """The archive tree plus the window mixins that own its column sizing."""

    def __init__(self, settings: QSettings) -> None:
        self.settings = settings
        self._shutting_down = False
        self._archive_tree_header_programmatic_depth = 0
        self._archive_tree_content_autofit_done = False
        self._column_autofit_timer = QTimer()
        self._column_autofit_timer.setSingleShot(True)
        self._column_autofit_timer.setInterval(0)
        self._column_autofit_timer.timeout.connect(self._autofit_archive_tree_columns)
        self.archive_tree = ArchiveBrowserTreeView("empty", "empty")
        self.archive_tree.set_archive_providers(row_provider=self._row_payload)
        header = self.archive_tree.header()
        header.setStretchLastSection(False)
        header.sectionResized.connect(self._handle_archive_tree_section_geometry_changed)
        header.sectionMoved.connect(self._handle_archive_tree_section_geometry_changed)
        with self._archive_tree_header_programmatic():
            for section in range(self.archive_tree.columnCount()):
                header.setSectionResizeMode(section, QHeaderView.Interactive)
            for section, width in enumerate(BUILD_DEFAULT_WIDTHS):
                header.resizeSection(section, width)
            self._apply_archive_tree_header_settings()
        self.archive_tree.resize(1200, 800)

    def schedule_settings_save(self) -> None:
        self._save_archive_tree_header_settings()

    def _update_archive_tree_sort_indicator(self) -> None:
        pass

    def _schedule_archive_files_pane_fit_to_columns(self) -> None:
        pass

    def _row_payload(self, entry_index: int, show_full_path: bool = False) -> ArchiveBrowserRowPayload:
        del show_full_path
        return ArchiveBrowserRowPayload(
            columns=(
                NAMES[entry_index % len(NAMES)],
                "-",
                "Model",
                "12.3 KB",
                "zlib",
                "0009/20.pamt",
                "-",
                "cd/mesh/body",
            )
        )

    def load_entries(self, count: int = 400) -> None:
        self.archive_tree.setRootIsDecorated(False)
        entries = [
            ArchiveEntry(
                path=f"cd/mesh/body/{NAMES[index % len(NAMES)]}",
                pamt_path=Path("0009/20.pamt"),
                paz_file=Path("0009/20.paz"),
                offset=0,
                comp_size=567,
                orig_size=1234,
                flags=0,
                paz_index=0,
            )
            for index in range(count)
        ]
        self.archive_tree.set_archive_state(entries, mode="flat", fetch_batch_size=500)

    def column_widths(self) -> list:
        header = self.archive_tree.header()
        return [header.sectionSize(column) for column in range(self.archive_tree.columnCount())]

    def longest_name_width(self) -> int:
        metrics = self.archive_tree.fontMetrics()
        return max(metrics.horizontalAdvance(name) for name in NAMES)


class ArchiveTreeColumnAutofitTests(unittest.TestCase):
    def setUp(self) -> None:
        self.app = _app()
        self._temp_dir = tempfile.TemporaryDirectory()
        self.settings_path = Path(self._temp_dir.name) / "settings.ini"

    def tearDown(self) -> None:
        self._temp_dir.cleanup()

    def _settings(self) -> QSettings:
        return QSettings(str(self.settings_path), QSettings.Format.IniFormat)

    def _fitted_host(self) -> _ArchiveColumnHost:
        host = _ArchiveColumnHost(self._settings())
        host.load_entries()
        self.app.processEvents()
        host._schedule_archive_tree_content_autofit()
        self.app.processEvents()
        return host

    def test_building_the_panel_is_not_a_manual_column_change(self) -> None:
        host = _ArchiveColumnHost(self._settings())

        self.assertEqual(list(BUILD_DEFAULT_WIDTHS), host.column_widths())
        self.assertFalse(host._archive_tree_columns_user_customized())

    def test_startup_autofit_sizes_the_name_column_to_its_longest_value(self) -> None:
        host = self._fitted_host()

        name_width = host.column_widths()[0]
        longest = host.longest_name_width()
        self.assertGreaterEqual(name_width, longest)
        self.assertLessEqual(name_width, longest + 40)
        self.assertFalse(host._archive_tree_columns_user_customized())

    def test_startup_autofit_runs_once_per_session(self) -> None:
        host = self._fitted_host()
        fitted = host.column_widths()

        host.archive_tree.header().resizeSection(0, 700)
        host._schedule_archive_tree_content_autofit()
        self.app.processEvents()

        self.assertEqual(700, host.column_widths()[0])
        self.assertNotEqual(fitted[0], 700)

    def test_a_manual_resize_is_recorded_and_survives_a_restart(self) -> None:
        host = self._fitted_host()
        host.archive_tree.header().resizeSection(0, 600)
        self.app.processEvents()
        self.assertTrue(host._archive_tree_columns_user_customized())
        host._save_archive_tree_header_settings()
        host.settings.sync()

        restored = _ArchiveColumnHost(self._settings())
        restored.load_entries()
        self.app.processEvents()
        restored._schedule_archive_tree_content_autofit()
        self.app.processEvents()

        self.assertEqual(600, restored.column_widths()[0])

    def test_reset_columns_hands_control_back_to_autofit(self) -> None:
        host = self._fitted_host()
        fitted = host.column_widths()
        host.archive_tree.header().resizeSection(0, 600)
        self.app.processEvents()
        self.assertTrue(host._archive_tree_columns_user_customized())

        host._reset_archive_tree_columns()
        self.app.processEvents()
        host._autofit_archive_tree_columns()

        self.assertFalse(host._archive_tree_columns_user_customized())
        self.assertEqual(fitted[0], host.column_widths()[0])

    def test_hiding_a_column_does_not_count_as_a_manual_resize(self) -> None:
        host = self._fitted_host()

        host._set_archive_tree_column_visible(4, False)
        self.app.processEvents()

        self.assertTrue(host.archive_tree.isColumnHidden(4))
        self.assertFalse(host._archive_tree_columns_user_customized())


if __name__ == "__main__":
    unittest.main()
