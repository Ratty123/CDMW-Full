from pathlib import Path
import unittest


REPO_ROOT = Path(__file__).resolve().parents[1]
MAIN_WINDOW = REPO_ROOT / "cdmw" / "ui" / "main_window.py"


class ArchiveBrowserAssetUnderstandingUiSourceGuards(unittest.TestCase):
    def test_asset_map_tabs_and_preview_health_are_present(self) -> None:
        source = MAIN_WINDOW.read_text(encoding="utf-8")

        self.assertIn("self.archive_asset_map_tabs = QTabWidget()", source)
        self.assertIn('self.archive_asset_map_tabs.addTab(self.archive_asset_map_tree, "Asset Map")', source)
        self.assertIn('self.archive_asset_map_tabs.addTab(self.archive_asset_uses_tree, "Uses")', source)
        self.assertIn('self.archive_asset_map_tabs.addTab(self.archive_asset_used_by_tree, "Used By")', source)
        self.assertIn('self.archive_asset_map_tabs.addTab(self.archive_texture_refs_tree, "Raw Table")', source)
        self.assertIn("self.archive_preview_role_badge = QLabel", source)
        self.assertIn("self.archive_preview_health_label = QLabel", source)
        self.assertIn("def _archive_preview_health_text(", source)
        self.assertIn('"Preview OK"', source)
        self.assertIn('"Physics Linked"', source)
        self.assertIn('"Name Hint"', source)

    def test_asset_relationship_actions_use_direct_scope_and_no_live_scan(self) -> None:
        source = MAIN_WINDOW.read_text(encoding="utf-8")

        self.assertIn("def _scope_current_archive_entry_only(self) -> None:", source)
        self.assertIn("def _current_archive_asset_set_entries(self, *, include_used_by: bool = False)", source)
        self.assertIn("def _scope_current_archive_asset_set(self, *, include_used_by: bool = False)", source)
        self.assertIn("def _export_current_archive_asset_set(self) -> None:", source)
        self.assertIn("def _show_archive_smart_actions_menu(self) -> None:", source)
        self.assertIn("self._apply_archive_direct_scope(", source)
        self.assertIn("Single-file scoped Archive Browser to:", source)
        self.assertIn("no full archive scan", source)
        self.assertIn('self.archive_texture_smart_actions_button = QPushButton("Smart Actions")', source)
        self.assertIn('self.archive_texture_export_asset_set_button = QPushButton("Export Asset Set...")', source)

    def test_roles_name_evidence_and_grouping_are_user_facing(self) -> None:
        source = MAIN_WINDOW.read_text(encoding="utf-8")

        self.assertIn('self.archive_tree.setHeaderLabels(["Name", "Exact Name", "Name Evidence", "Role / Type"', source)
        self.assertIn("def _archive_entry_role_label(", source)
        self.assertIn("def _archive_asset_map_group_label(", source)
        self.assertIn("def _archive_known_used_by_references(", source)
        self.assertIn('"Model / Mesh"', source)
        self.assertIn('"Prefab / Metadata"', source)
        self.assertIn('"Exact localization"', source)
        self.assertIn('"Name hint: {first_related_name}"', source)
        self.assertIn("variant_count", source)
        self.assertIn("Generated thumbnail from asset texture", source)

    def test_relation_selection_covers_asset_map_uses_and_used_by(self) -> None:
        source = MAIN_WINDOW.read_text(encoding="utf-8")

        self.assertIn("def _archive_reference_from_item(", source)
        self.assertIn('if source == "uses"', source)
        self.assertIn('if source == "used_by"', source)
        self.assertIn("self.current_archive_used_by_references", source)
        self.assertIn("relation_tree.customContextMenuRequested.connect", source)
        self.assertIn("sender = self.sender()", source)
        self.assertIn("tree = sender if isinstance(sender, QTreeWidget) else self.archive_texture_refs_tree", source)

    def test_scope_banner_is_visible_for_direct_asset_scopes(self) -> None:
        source = MAIN_WINDOW.read_text(encoding="utf-8")

        self.assertIn("self.archive_scope_banner_label = QLabel", source)
        self.assertIn("Scope active: {scope_text}. Clear Scope returns to normal archive filtering.", source)
        self.assertIn("self.archive_scope_banner_label.setVisible(True)", source)
        self.assertIn("self.archive_scope_banner_label.setVisible(False)", source)


if __name__ == "__main__":
    unittest.main()
