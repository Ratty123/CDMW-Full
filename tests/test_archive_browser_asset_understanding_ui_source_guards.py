from pathlib import Path
import unittest


REPO_ROOT = Path(__file__).resolve().parents[1]
MAIN_WINDOW = REPO_ROOT / "cdmw" / "ui" / "main_window.py"


class ArchiveBrowserAssetUnderstandingUiSourceGuards(unittest.TestCase):
    def test_asset_map_tabs_and_preview_health_are_present(self) -> None:
        source = MAIN_WINDOW.read_text(encoding="utf-8")

        self.assertIn("self.archive_asset_map_tabs = QTabWidget()", source)
        self.assertIn('self.archive_asset_family_button = QPushButton("Asset Family")', source)
        self.assertIn("self.archive_asset_family_button.clicked.connect(self._open_archive_asset_family_workspace_dialog)", source)
        self.assertIn("self.archive_asset_family_summary_label = QLabel", source)
        self.assertIn('self.archive_asset_map_tabs.addTab(self.archive_asset_map_tree, "Asset Family")', source)
        self.assertIn('self.archive_asset_map_tabs.addTab(self.archive_asset_uses_tree, "Uses")', source)
        self.assertIn('self.archive_asset_map_tabs.addTab(self.archive_asset_used_by_tree, "Used By")', source)
        self.assertIn('self.archive_asset_map_tabs.addTab(self.archive_asset_placement_tree, "Placement")', source)
        self.assertIn('self.archive_asset_map_tabs.addTab(self.archive_texture_refs_tree, "Raw Table")', source)
        self.assertIn("self.archive_preview_role_badge = QLabel", source)
        self.assertIn("self.archive_preview_health_label = QLabel", source)
        self.assertIn("def _archive_preview_health_text(", source)
        self.assertIn('"Preview OK"', source)
        self.assertIn('"Physics Linked"', source)
        self.assertIn('"Name Inferred"', source)

    def test_asset_relationship_actions_use_direct_scope_and_no_live_scan(self) -> None:
        source = MAIN_WINDOW.read_text(encoding="utf-8")

        self.assertIn("def _scope_current_archive_entry_only(self) -> None:", source)
        self.assertIn("def _current_archive_asset_set_entries(self, *, include_used_by: bool = False, include_hints: bool = False)", source)
        self.assertIn("def _scope_current_archive_asset_set(self, *, include_used_by: bool = False, include_hints: bool = False)", source)
        self.assertIn("def _scope_archive_asset_family_for_entry(self, entry: ArchiveEntry, *, include_hints: bool = False) -> None:", source)
        self.assertIn("def _export_archive_asset_family_for_entry(self, entry: ArchiveEntry, *, include_hints: bool = False) -> None:", source)
        self.assertIn("def _export_current_archive_asset_set(self) -> None:", source)
        self.assertIn("def _show_archive_smart_actions_menu(self) -> None:", source)
        self.assertIn("self._apply_archive_direct_scope(", source)
        self.assertIn("Single-file scoped Archive Browser to:", source)
        self.assertIn("no full archive scan", source)
        self.assertIn('self.archive_texture_smart_actions_button = QPushButton("Smart Actions")', source)
        self.assertIn('self.archive_texture_scope_all_button = QPushButton("Show Only This Family")', source)
        self.assertIn('self.archive_texture_export_asset_set_button = QPushButton("Export Family...")', source)
        self.assertIn('show_asset_set_hints_action = menu.addAction("Show Family + Hints")', source)

    def test_archive_file_context_menu_exposes_role_aware_actions(self) -> None:
        source = MAIN_WINDOW.read_text(encoding="utf-8")

        self.assertIn("def _show_archive_tree_context_menu(self, position) -> None:", source)
        self.assertIn('preview_action = menu.addAction("Preview")', source)
        self.assertIn('preview_window_action = menu.addAction("Open Preview Window...")', source)
        self.assertIn('export_file_action = menu.addAction("Export File...")', source)
        self.assertIn('extract_file_action = menu.addAction("Extract File...")', source)
        self.assertIn('family_action = menu.addAction("Asset Family Workspace...")', source)
        self.assertIn('placement_action = menu.addAction("Open Placement Workspace...")', source)
        self.assertIn('import_loose_mod_action = menu.addAction("Import Loose Mod Folder...")', source)
        self.assertIn('modify_original_action = menu.addAction("Modify Original...")', source)
        self.assertIn('texture_editor_action = menu.addAction("Open In Texture Editor...")', source)
        self.assertIn('edit_hkx_action = menu.addAction("Edit HKX...")', source)
        self.assertIn('inspect_sidecar_action = menu.addAction("Inspect Structured Data...")', source)
        self.assertIn('edit_material_action = menu.addAction("Edit Material Values...")', source)

    def test_modify_original_workspace_uses_safe_roundtrip_clone_path(self) -> None:
        source = MAIN_WINDOW.read_text(encoding="utf-8")

        self.assertIn('self.archive_model_modify_original_button = QPushButton("Modify Original...")', source)
        self.assertIn("self.archive_model_modify_original_button.clicked.connect(self._modify_current_archive_original_mesh)", source)
        self.assertIn('("Modify Original", self.archive_model_modify_original_button)', source)
        self.assertIn("def _start_archive_modify_original_workspace(self, entry: ArchiveEntry) -> None:", source)
        self.assertIn('export_archive_mesh(', source)
        self.assertIn('"format": "cdmw_modify_original_workspace_v1"', source)
        self.assertIn('"policy": "safe_clone_workspace_imports_through_mesh_replacement_geometry_path"', source)
        self.assertIn("def _open_modify_original_mesh_setup(", source)
        self.assertIn("force_static_replacement=True", source)
        self.assertIn('placement_review_title="Modify Original Geometry"', source)
        self.assertIn("self._start_archive_mesh_patch(", source)
        self.assertIn("MODIFY_ORIGINAL_README.txt", source)
        self.assertIn("find_available_output_path(parent_root / workspace_name)", source)

    def test_roles_name_evidence_and_grouping_are_user_facing(self) -> None:
        source = MAIN_WINDOW.read_text(encoding="utf-8")

        self.assertIn('self.archive_tree.setHeaderLabels(["Name", "Exact Name", "Name Evidence", "Role / Type"', source)
        self.assertIn("def _archive_entry_role_label(", source)
        self.assertIn("def _archive_asset_map_group_label(", source)
        self.assertIn("def _archive_known_used_by_references(", source)
        self.assertIn('"Selected Model"', source)
        self.assertIn('"Attachment / Placement"', source)
        self.assertIn('"Physics / HKX"', source)
        self.assertIn('"MeshInfo"', source)
        self.assertIn('"Prefab / Metadata"', source)
        self.assertIn('"Exact localization"', source)
        self.assertIn('"Name hint: {first_related_name}"', source)
        self.assertIn("variant_count", source)
        self.assertIn("category_evidence", source)
        self.assertIn("Category evidence:", source)
        self.assertIn("Generated thumbnail from asset texture", source)

    def test_placement_workspace_and_loose_overlay_review_are_present(self) -> None:
        source = MAIN_WINDOW.read_text(encoding="utf-8")

        self.assertIn("def _open_archive_attachment_placement_workspace_dialog", source)
        self.assertIn("Weapon / Attachment Placement", source)
        self.assertIn("Placement is prefab/socket driven. HKX rows are physics context only.", source)
        self.assertIn("Raw Model Origin", source)
        self.assertIn("Character Socket", source)
        self.assertIn("Weapon Pivot", source)
        self.assertIn("Final Attachment", source)
        self.assertIn("Compare Original vs Donor", source)
        self.assertIn("Copy Placement From Another Asset", source)
        self.assertIn("keeps binary prefab/PAA/HKX writes disabled", source)
        self.assertIn("def _open_archive_loose_mod_overlay_dialog", source)
        self.assertIn("Loose Mod Overlay Review", source)
        self.assertIn("Select Exact Family", source)
        self.assertIn("Select All Families", source)
        self.assertIn("Select All Exact Matches", source)
        self.assertIn("Use as Mesh Replacement Source", source)
        self.assertIn("group_source_mix_candidates_by_family(candidates)", source)

    def test_relation_selection_covers_asset_map_uses_and_used_by(self) -> None:
        source = MAIN_WINDOW.read_text(encoding="utf-8")

        self.assertIn("def _archive_reference_from_item(", source)
        self.assertIn('if source == "uses"', source)
        self.assertIn('if source == "used_by"', source)
        self.assertIn('if source == "family"', source)
        self.assertIn("self.current_archive_used_by_references", source)
        self.assertIn("self.current_archive_family_member_rows", source)
        self.assertIn("relation_tree.customContextMenuRequested.connect", source)
        self.assertIn("sender = self.sender()", source)
        self.assertIn("tree = sender if isinstance(sender, QTreeWidget) else self.archive_texture_refs_tree", source)

    def test_dds_asset_family_promotes_used_by_materials_and_models(self) -> None:
        source = MAIN_WINDOW.read_text(encoding="utf-8")

        self.assertIn("texture_sidecars: List[ArchiveEntry] = []", source)
        self.assertIn("texture_stem_candidates: List[str] = []", source)
        self.assertIn("def add_texture_sidecar(candidate: ArchiveEntry, *, reason: str, confidence: str) -> None:", source)
        self.assertIn("def add_material_sidecar_candidates_for_stem(stem: str) -> None:", source)
        self.assertIn("def add_model_candidates_for_stem(stem: str, *, reason: str, confidence: str) -> None:", source)
        self.assertIn("Material sidecar references this exact texture path.", source)
        self.assertIn("Material sidecar shares the selected texture stem", source)
        self.assertIn("Model shares the selected texture stem in the current archive index", source)
        self.assertIn("Model candidate shares the basename with a material sidecar that references this texture", source)
        self.assertIn('if isinstance(current_entry, ArchiveEntry) and str(current_entry.extension or "").lower() == ".dds":', source)
        self.assertIn("family_references.extend(self.current_archive_used_by_references)", source)
        self.assertIn("asset_family_graph_for_view = build_archive_asset_family_graph(current_entry, tuple(family_references))", source)
        self.assertIn("raw_table_references = list(self.current_archive_model_texture_references)", source)
        self.assertIn('raw_table_sources.extend(("used_by", index) for index in range(len(self.current_archive_used_by_references)))', source)
        self.assertIn('if str(entry.extension or "").lower() == ".dds":', source)
        self.assertIn("combined_references.extend(self._archive_known_used_by_references(entry))", source)

    def test_asset_family_splitter_width_is_stable_across_preview_refresh(self) -> None:
        source = MAIN_WINDOW.read_text(encoding="utf-8")

        self.assertIn("self.archive_asset_family_preferred_width = 420", source)
        self.assertIn("Preserve the user's Asset Family splitter width while loading or when a file", source)
        self.assertIn('getattr(self, "archive_asset_family_preferred_width", 420)', source)
        self.assertIn('not getattr(self, "_archive_preview_splitter_clamping", False)', source)
        self.assertIn("self.archive_asset_family_preferred_width = sizes[1]", source)

    def test_scope_banner_is_visible_for_direct_asset_scopes(self) -> None:
        source = MAIN_WINDOW.read_text(encoding="utf-8")

        self.assertIn("self.archive_scope_banner_label = QLabel", source)
        self.assertIn("Scope active: {scope_text}. Clear Scope returns to normal archive filtering.", source)
        self.assertIn("self.archive_scope_banner_label.setVisible(True)", source)
        self.assertIn("self.archive_scope_banner_label.setVisible(False)", source)


if __name__ == "__main__":
    unittest.main()
