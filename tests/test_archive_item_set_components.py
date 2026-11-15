from __future__ import annotations

import json
from types import SimpleNamespace

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QMenu, QPushButton, QWidget

from cdmw.ui.archive_browser.item_set_components import ItemSetComponentsWidget
from cdmw.ui.archive_browser.preview_d3d11_parts import ArchivePreviewD3D11PartsMixin


def _batches(offset=0):
    return [{"index": index + offset, "material_name": label, "editor_identity": {
        "source_submesh_index": index + offset, "source_local_submesh_index": local,
        "source_model_path": path, "prefab_component": path == "lower.pac",
    }} for index, local, path, label in [(0, 0, "upper.pac", "Cloth"), (1, 1, "upper.pac", "Steel"), (2, 0, "lower.pac", "Legs")]]


class _Host:
    def set_hidden_source_submeshes(self, indices): self.hidden = tuple(indices)
    def set_highlighted_source_submeshes(self, indices): self.highlighted = tuple(indices)


class _Preview(QWidget, ArchivePreviewD3D11PartsMixin):
    def __init__(self):
        super().__init__()
        self.archive_d3d11_preview_host = _Host()
        self.archive_d3d11_part_visibility_menu = QMenu(self)
        self.archive_d3d11_part_visibility_button = QPushButton(self)
        self.archive_item_set_components = ItemSetComponentsWidget(self)
        self.archive_item_set_components.visibilityChanged.connect(self._archive_item_set_visibility_changed)
        self.archive_item_set_components.highlightRequested.connect(self.archive_d3d11_preview_host.set_highlighted_source_submeshes)
        self.primary = SimpleNamespace(path="upper.pac", pamt_path="game.pamt", offset=0)
        self.selected = self.primary
        self.archive_preview_request_entry = self.primary
        self.archive_remote_bridge = SimpleNamespace(item_set_contains=lambda entry: entry is self.primary,
            item_set_members=(self.primary, SimpleNamespace(path="lower.pac")), preview_entry_for=lambda entry: self.primary)
        self.archive_d3d11_prefab_component_selections = {self._archive_d3d11_prefab_entry_key(self.primary): {"lower.pac"}}
        self.reloads = 0

    def _current_archive_entry(self): return self.selected
    def _reload_archive_d3d11_prefab_components(self): self.reloads += 1


def test_component_tree_and_parts_menu_share_visibility_without_rebuilding(tmp_path):
    app = QApplication.instance() or QApplication([])
    preview = _Preview()
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"batches": _batches()}))
    preview._populate_archive_d3d11_part_visibility_menu(tmp_path)
    panel, host = preview.archive_item_set_components, preview.archive_d3d11_preview_host
    assert panel.tree.topLevelItemCount() == 2
    assert host.hidden == ()
    panel._parts[1].setCheckState(0, Qt.Unchecked)
    assert host.hidden == (1,)
    assert panel._groups["upper.pac"].checkState(0) == Qt.PartiallyChecked
    lower_action = next(value[0] for value in preview.archive_d3d11_part_visibility_groups.values() if value[3] == "lower.pac")
    lower_action.setChecked(False)
    assert host.hidden == (1, 2) and not preview.reloads
    panel.show_all_button.click()
    assert host.hidden == () and lower_action.isChecked()
    panel.highlight_path("lower.pac")
    assert host.highlighted == (2,)
    panel.isolate_button.click()
    assert host.hidden == (0, 1) and not preview.reloads
    # Texture promotion may renumber batches; retain choices by file + local part identity.
    manifest.write_text(json.dumps({"batches": _batches(10)}))
    preview._populate_archive_d3d11_part_visibility_menu(tmp_path)
    assert host.hidden == (10, 11)
    preview.archive_d3d11_part_visibility_menu.actions()[0].trigger()
    assert host.hidden == () and not preview.reloads
    preview.archive_d3d11_part_visibility_menu.actions()[1].trigger()
    assert host.hidden == (12,) and not preview.reloads
    assert preview._archive_d3d11_enabled_prefab_component_paths() == ("lower.pac",)
    preview.close()
    app.processEvents()
