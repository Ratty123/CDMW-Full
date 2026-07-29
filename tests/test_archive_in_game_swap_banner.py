"""The armed in-game swap state must be visible inside Archive Browser.

Before this, arming a swap only wrote to the Textures tab progress label and to a
menu item buried in a collapsed dropdown, so from Archive Browser the action looked
like it had done nothing at all.
"""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from cdmw.app.events import AppEventBus
from cdmw.models import ArchiveEntry
from cdmw.services.service_container import ServiceContainer
from cdmw.services.settings_service import create_settings
from cdmw.ui.main_window import MainWindow
from cdmw.ui.shell.app_context import AppContext


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def _entry(path: str, root: Path) -> ArchiveEntry:
    pamt_path = root / "0009" / "0009.pamt"
    pamt_path.parent.mkdir(parents=True, exist_ok=True)
    return ArchiveEntry(
        path=path,
        pamt_path=pamt_path,
        paz_file=root / "0009" / "0.paz",
        offset=0,
        comp_size=1,
        orig_size=1,
        flags=0,
        paz_index=0,
    )


class ArchiveInGameSwapBannerTests(unittest.TestCase):
    def setUp(self) -> None:
        self._smoke_env = patch.dict(os.environ, {"CDMW_GUI_STARTUP_SMOKE": "1"})
        self._smoke_env.start()
        self.addCleanup(self._smoke_env.stop)
        _app()
        self._temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self._temp_dir.name)
        settings = create_settings(settings_file_path=self.root / "cdmw-test.cfg")
        context = AppContext(
            settings=settings,
            services=ServiceContainer.create_default(settings=settings),
            event_bus=AppEventBus(),
        )
        self.window = MainWindow(app_context=context)

    def tearDown(self) -> None:
        self.window._finalize_close()
        self.window.deleteLater()
        _app().processEvents()
        self._temp_dir.cleanup()

    def test_banner_is_hidden_until_a_swap_target_is_armed(self) -> None:
        self.assertFalse(self.window.archive_swap_banner.isVisibleTo(self.window.archive_files_group))
        self.assertEqual("", self.window.archive_swap_banner_label.text())

    def test_arming_a_target_shows_the_banner_with_the_target_path(self) -> None:
        target = _entry("character/model/weapon/002_sword/cd_phm_02_sword_0019.pac", self.root)

        self.window._handle_archive_in_game_mesh_swap_entry(target)

        self.assertIs(self.window.pending_in_game_mesh_swap_target, target)
        self.assertTrue(self.window.archive_swap_banner.isVisibleTo(self.window.archive_files_group))
        self.assertIn(target.path, self.window.archive_swap_banner_label.text())

    def test_banner_says_use_this_as_swap_source_once_the_target_is_prepared(self) -> None:
        target = _entry("character/model/weapon/002_sword/cd_phm_02_sword_0019.pac", self.root)

        with patch.object(
            self.window,
            "_pin_in_game_mesh_swap_target_dependencies",
            return_value=True,
        ):
            self.window._handle_archive_in_game_mesh_swap_entry(target)

        self.assertIn("Use This as Swap Source", self.window.archive_swap_banner_label.text())

    def test_banner_says_preparing_while_the_target_has_no_snapshot(self) -> None:
        """Arming can beat the async dependency preparation on the v2 backend."""

        target = _entry("character/model/weapon/002_sword/cd_phm_02_sword_0019.pac", self.root)

        with patch.object(
            self.window,
            "_pin_in_game_mesh_swap_target_dependencies",
            return_value=False,
        ):
            self.window._handle_archive_in_game_mesh_swap_entry(target)

        self.assertIn("Still preparing", self.window.archive_swap_banner_label.text())

    def test_banner_cancel_button_clears_the_armed_target(self) -> None:
        target = _entry("character/model/weapon/002_sword/cd_phm_02_sword_0019.pac", self.root)
        self.window._handle_archive_in_game_mesh_swap_entry(target)

        self.window.archive_swap_banner_cancel_button.click()

        self.assertIsNone(self.window.pending_in_game_mesh_swap_target)
        self.assertFalse(self.window.archive_swap_banner.isVisibleTo(self.window.archive_files_group))

    def test_arming_from_the_action_button_stays_in_archive_browser(self) -> None:
        """The toolbar path used to jump to the Mesh Editor before arming."""

        target = _entry("character/model/weapon/002_sword/cd_phm_02_sword_0019.pac", self.root)
        archive_browser = self.window._tool_widgets_by_key["archive_browser"]
        self.window._activate_tool_widget(archive_browser)

        with patch.object(self.window, "_current_archive_mesh_entry", return_value=target):
            self.window._swap_current_archive_mesh_with_in_game()

        self.assertIs(self.window.pending_in_game_mesh_swap_target, target)
        self.assertIs(self.window._current_navigation_widget(), archive_browser)


if __name__ == "__main__":
    unittest.main()
