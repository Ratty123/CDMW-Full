"""Part visibility controls for native D3D11 archive previews."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List, Mapping, Optional


class ArchivePreviewD3D11PartsMixin:
    """Menu helpers for toggling source submeshes in the D3D11 preview host."""

    @staticmethod
    def _archive_d3d11_prefab_component_path_key(path_value: object) -> str:
        return str(path_value or "").replace("\\", "/").strip().casefold()

    @classmethod
    def _archive_d3d11_prefab_entry_key(cls, entry: Optional[object]) -> str:
        if entry is None:
            return ""
        path = cls._archive_d3d11_prefab_component_path_key(getattr(entry, "path", ""))
        pamt_path = str(getattr(entry, "pamt_path", "") or "").strip().casefold()
        try:
            offset = int(getattr(entry, "offset", 0) or 0)
        except (TypeError, ValueError):
            offset = 0
        return f"{pamt_path}|{path}|{offset}" if path else ""

    def _archive_d3d11_enabled_prefab_component_paths(
        self,
        entry: Optional[object] = None,
    ) -> tuple[str, ...]:
        if entry is None:
            current_entry = getattr(self, "_current_archive_entry", None)
            entry = current_entry() if callable(current_entry) else None
        entry_key = self._archive_d3d11_prefab_entry_key(entry)
        if not entry_key:
            return ()
        selections = getattr(self, "archive_d3d11_prefab_component_selections", {}) or {}
        selected = selections.get(entry_key, set())
        return tuple(sorted(str(path) for path in selected if str(path).strip()))

    def _set_archive_d3d11_enabled_prefab_component_paths(
        self,
        component_paths: object,
    ) -> bool:
        current_entry = getattr(self, "_current_archive_entry", None)
        entry = current_entry() if callable(current_entry) else None
        entry_key = self._archive_d3d11_prefab_entry_key(entry)
        if not entry_key:
            return False
        normalized = {
            self._archive_d3d11_prefab_component_path_key(path)
            for path in tuple(component_paths or ())
            if self._archive_d3d11_prefab_component_path_key(path)
        }
        selections = getattr(self, "archive_d3d11_prefab_component_selections", None)
        if not isinstance(selections, dict):
            selections = {}
            self.archive_d3d11_prefab_component_selections = selections
        previous = set(selections.get(entry_key, set()))
        if previous == normalized:
            return False
        if normalized:
            selections[entry_key] = normalized
        else:
            selections.pop(entry_key, None)
        return True

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
        for action, source_indices, _prefab_component, _model_path in groups.values():
            if hasattr(action, "isChecked") and bool(action.isChecked()):
                shown_count += 1
            else:
                hidden.extend(int(index) for index in source_indices if int(index) >= 0)
        total_count = len(groups)
        self.archive_d3d11_part_visibility_button.setText(
            f"Parts {shown_count}/{total_count}" if total_count else "Parts"
        )
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
        asset_family = manifest.get("asset_family")
        member_rows = asset_family.get("member_rows") if isinstance(asset_family, Mapping) else ()
        if isinstance(member_rows, list):
            for member in member_rows:
                if not isinstance(member, Mapping):
                    continue
                if str(member.get("group") or "").strip() != "Prefab / Components":
                    continue
                if str(member.get("role") or "").strip() != "Model Component":
                    continue
                model_path = str(member.get("path") or "").replace("\\", "/").strip()
                path_key = self._archive_d3d11_prefab_component_path_key(model_path)
                if not path_key:
                    continue
                rows[f"prefab|{path_key}"] = {
                    "label": str(member.get("display_name") or Path(model_path).name or model_path),
                    "model_path": model_path,
                    "prefab_component": True,
                    "source_indices": [],
                }
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
            path_key = self._archive_d3d11_prefab_component_path_key(model_path)
            group_key = (
                f"prefab|{path_key}"
                if prefab_component and path_key
                else (f"{component_index}|{model_path}" if model_path else f"batch|{source_index}")
            )
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
        selected_prefab_paths = set(self._archive_d3d11_enabled_prefab_component_paths())
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
            if not source_indices and not prefab_component:
                continue
            action = menu.addAction(label)
            action.setCheckable(True)
            prefab_path_key = self._archive_d3d11_prefab_component_path_key(model_path)
            action.setChecked(not prefab_component or prefab_path_key in selected_prefab_paths)
            action.setToolTip(
                (
                    f"Enable to build and load this prefab component: {model_path}"
                    if prefab_component and not source_indices
                    else model_path
                )
                or "Native D3D11 preview component"
            )
            action.setStatusTip(model_path or "")
            action.setData(list(source_indices))
            for source_index in source_indices:
                self.archive_d3d11_part_visibility_actions[source_index] = action
            self.archive_d3d11_part_visibility_groups[group_key] = (
                action,
                source_indices,
                prefab_component,
                model_path,
            )
            action.toggled.connect(
                lambda checked=False, key=group_key: self._handle_archive_d3d11_part_toggled(
                    key,
                    bool(checked),
                )
            )

        def _apply_bulk_prefab_selection(*, enabled: bool) -> None:
            selected_paths = set(self._archive_d3d11_enabled_prefab_component_paths())
            self.archive_d3d11_part_visibility_bulk_update = True
            try:
                for (
                    action,
                    _source_indices,
                    prefab_component,
                    model_path,
                ) in self.archive_d3d11_part_visibility_groups.values():
                    if hasattr(action, "setChecked"):
                        action.setChecked(bool(enabled) if prefab_component else True)
                    if prefab_component:
                        path_key = self._archive_d3d11_prefab_component_path_key(model_path)
                        if enabled and path_key:
                            selected_paths.add(path_key)
                        else:
                            selected_paths.discard(path_key)
            finally:
                self.archive_d3d11_part_visibility_bulk_update = False
            changed = self._set_archive_d3d11_enabled_prefab_component_paths(selected_paths)
            self._set_archive_d3d11_hidden_parts_from_menu()
            if changed:
                self._reload_archive_d3d11_prefab_components()

        def _show_all() -> None:
            _apply_bulk_prefab_selection(enabled=True)

        def _hide_added() -> None:
            _apply_bulk_prefab_selection(enabled=False)

        show_all_action.triggered.connect(_show_all)
        hide_added_action.triggered.connect(_hide_added)
        self.archive_d3d11_part_visibility_button.setVisible(True)
        self.archive_d3d11_part_visibility_button.setEnabled(True)
        self._set_archive_d3d11_hidden_parts_from_menu()

    def _handle_archive_d3d11_part_toggled(self, group_key: str, checked: bool) -> None:
        if bool(getattr(self, "archive_d3d11_part_visibility_bulk_update", False)):
            return
        group = (getattr(self, "archive_d3d11_part_visibility_groups", {}) or {}).get(group_key)
        if group is None:
            return
        _action, _source_indices, prefab_component, model_path = group
        if not prefab_component:
            self._set_archive_d3d11_hidden_parts_from_menu()
            return
        selected_paths = set(self._archive_d3d11_enabled_prefab_component_paths())
        path_key = self._archive_d3d11_prefab_component_path_key(model_path)
        if checked and path_key:
            selected_paths.add(path_key)
        else:
            selected_paths.discard(path_key)
        changed = self._set_archive_d3d11_enabled_prefab_component_paths(selected_paths)
        self._set_archive_d3d11_hidden_parts_from_menu()
        if changed:
            self._reload_archive_d3d11_prefab_components()

    def _reload_archive_d3d11_prefab_components(self) -> None:
        refresh = getattr(self, "_refresh_current_model_preview_assets", None)
        if not callable(refresh):
            return
        status = getattr(self, "set_status_message", None)
        if callable(status):
            enabled_count = len(self._archive_d3d11_enabled_prefab_component_paths())
            status(
                "Loading enabled prefab component(s)..."
                if enabled_count
                else "Removing prefab components from preview..."
            )
        refresh(force=True)
