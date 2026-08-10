import unittest

from tests.test_archive_browser_asset_understanding_ui_source_guards import (
    ARCHIVE_ASSET_FAMILY_LAYOUT,
    ARCHIVE_ASSET_FAMILY_PANEL,
    ARCHIVE_FILES_PANEL,
    ARCHIVE_FILTER_CONTROLS,
    MAIN_WINDOW,
    SHELL_WINDOW_RUNTIME_STATE,
)


class ArchiveBrowserScopeBannerSourceGuardTests(unittest.TestCase):
    def test_asset_family_splitter_width_is_stable_across_preview_refresh(self) -> None:
        source = "\n".join(
            path.read_text(encoding="utf-8")
            for path in (
                MAIN_WINDOW,
                SHELL_WINDOW_RUNTIME_STATE,
                ARCHIVE_ASSET_FAMILY_LAYOUT,
                ARCHIVE_ASSET_FAMILY_PANEL,
            )
        )

        self.assertIn("self.archive_asset_family_preferred_width = 420", source)
        self.assertIn("self.archive_asset_family_panel_requested = False", source)
        self.assertIn("self.archive_texture_refs_group.setVisible(panel_requested)", source)
        self.assertIn('getattr(self, "archive_asset_family_preferred_width", 420)', source)
        self.assertIn('not getattr(self, "_archive_preview_splitter_clamping", False)', source)
        self.assertIn("self.archive_asset_family_preferred_width = sizes[1]", source)
        self.assertIn("def _refresh_archive_asset_family_panel_layout(self, *, prefer_default: bool = False) -> None:", source)
        self.assertIn("def _schedule_archive_asset_family_panel_layout(self, *, prefer_default: bool = False) -> None:", source)
        self.assertIn("self._schedule_archive_asset_family_panel_layout(prefer_default=True)", source)
        self.assertIn("Keep Asset Family visible even in compact or freshly reflowed layouts.", source)
        self.assertIn("target_sizes = [preview_width, max(1, refs_width)]", source)
        self.assertNotIn("target_sizes = [total, 0]", source)

    def test_scope_banner_is_visible_for_direct_asset_scopes(self) -> None:
        source = (
            MAIN_WINDOW.read_text(encoding="utf-8")
            + "\n"
            + ARCHIVE_FILES_PANEL.read_text(encoding="utf-8")
            + "\n"
            + ARCHIVE_FILTER_CONTROLS.read_text(encoding="utf-8")
        )

        self.assertIn("self.archive_scope_banner_label = QLabel", source)
        self.assertIn("Scope active: {scope_text}. Clear Scope returns to normal archive filtering.", source)
        self.assertIn("self.archive_scope_banner_label.setVisible(True)", source)
        self.assertIn("self.archive_scope_banner_label.setVisible(False)", source)


if __name__ == "__main__":
    unittest.main()
