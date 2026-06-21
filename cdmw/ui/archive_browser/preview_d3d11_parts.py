"""Part visibility controls for native D3D11 archive previews."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List, Mapping


class ArchivePreviewD3D11PartsMixin:
    """Menu helpers for toggling source submeshes in the D3D11 preview host."""

    def _clear_archive_d3d11_part_visibility_menu(self) -> None:
        menu = getattr(self, "archive_d3d11_part_visibility_menu", None)
        if menu is not None:
            menu.clear()
        self.archive_d3d11_part_visibility_actions = {}
        self.archive_d3d11_part_visibility_groups = {}
        self.archive_d3d11_part_visibility_button.setText("Parts")
        self.archive_d3d11_part_visibility_button.setEnabled(False)
        self.archive_d3d11_part_visibility_button.setVisible(False)

    def _set_archive_d3d11_hidden_parts_from_menu(self) -> None:
        groups = getattr(self, "archive_d3d11_part_visibility_groups", {}) or {}
        hidden: List[int] = []
        shown_count = 0
        for action, source_indices, _prefab_component in groups.values():
            if hasattr(action, "isChecked") and bool(action.isChecked()):
                shown_count += 1
            else:
                hidden.extend(int(index) for index in source_indices if int(index) >= 0)
        total_count = len(groups)
        self.archive_d3d11_part_visibility_button.setText(f"Parts {shown_count}/{total_count}" if total_count else "Parts")
        self.archive_d3d11_preview_host.set_hidden_source_submeshes(hidden)

    def _populate_archive_d3d11_part_visibility_menu(self, package_dir: Path) -> None:
        self._clear_archive_d3d11_part_visibility_menu()
        manifest_path = Path(package_dir) / "manifest.json"
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            return
        batches = manifest.get("batches")
        if not isinstance(batches, list):
            return
        rows: Dict[str, Dict[str, object]] = {}
        for batch in batches:
            if not isinstance(batch, Mapping):
                continue
            identity = batch.get("editor_identity")
            if not isinstance(identity, Mapping):
                identity = {}
            try:
                source_index = int(identity.get("source_submesh_index", batch.get("index", -1)))
            except (TypeError, ValueError):
                continue
            if source_index < 0:
                continue
            label = str(
                identity.get("part_label")
                or identity.get("source_component_label")
                or batch.get("material_name")
                or f"Batch {source_index}"
            )
            model_path = str(identity.get("source_model_path") or "")
            prefab_component = bool(identity.get("prefab_component", False))
            component_index = identity.get("source_component_index", "")
            group_key = f"{component_index}|{model_path}" if model_path else f"batch|{source_index}"
            row = rows.setdefault(
                group_key,
                {
                    "label": label,
                    "model_path": model_path,
                    "prefab_component": prefab_component,
                    "source_indices": [],
                },
            )
            source_indices = row.get("source_indices")
            if isinstance(source_indices, list) and source_index not in source_indices:
                source_indices.append(source_index)
        if len(rows) <= 1:
            return
        menu = self.archive_d3d11_part_visibility_menu
        show_all_action = menu.addAction("Show all parts")
        hide_added_action = menu.addAction("Hide added prefab pieces")
        menu.addSeparator()
        self.archive_d3d11_part_visibility_actions = {}
        self.archive_d3d11_part_visibility_groups = {}
        ordered_rows = sorted(
            rows.items(),
            key=lambda item: (str(item[1].get("label") or "").lower(), str(item[0])),
        )
        for group_key, row in ordered_rows:
            label = str(row.get("label") or group_key)
            model_path = str(row.get("model_path") or "")
            prefab_component = bool(row.get("prefab_component", False))
            raw_indices = row.get("source_indices")
            source_indices = tuple(
                sorted(
                    int(index)
                    for index in (raw_indices if isinstance(raw_indices, list) else [])
                    if int(index) >= 0
                )
            )
            if not source_indices:
                continue
            action = menu.addAction(label)
            action.setCheckable(True)
            action.setChecked(True)
            action.setToolTip(model_path or "Native D3D11 preview component")
            action.setStatusTip(model_path or "")
            action.setData(list(source_indices))
            for source_index in source_indices:
                self.archive_d3d11_part_visibility_actions[source_index] = action
            self.archive_d3d11_part_visibility_groups[group_key] = (action, source_indices, prefab_component)
            action.toggled.connect(lambda _checked=False: self._set_archive_d3d11_hidden_parts_from_menu())

        def _show_all() -> None:
            for action, _source_indices, _prefab_component in self.archive_d3d11_part_visibility_groups.values():
                if hasattr(action, "setChecked"):
                    action.setChecked(True)
            self._set_archive_d3d11_hidden_parts_from_menu()

        def _hide_added() -> None:
            for action, _source_indices, prefab_component in self.archive_d3d11_part_visibility_groups.values():
                if hasattr(action, "setChecked"):
                    action.setChecked(not prefab_component)
            self._set_archive_d3d11_hidden_parts_from_menu()

        show_all_action.triggered.connect(_show_all)
        hide_added_action.triggered.connect(_hide_added)
        self.archive_d3d11_part_visibility_button.setVisible(True)
        self.archive_d3d11_part_visibility_button.setEnabled(True)
        visible_count = len(self.archive_d3d11_part_visibility_groups)
        self.archive_d3d11_part_visibility_button.setText(f"Parts {visible_count}/{visible_count}")
