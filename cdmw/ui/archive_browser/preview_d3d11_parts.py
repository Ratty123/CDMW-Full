"""Browse Archives' Scene panel wiring: part visibility and prefab component loading."""

from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Mapping, Optional

from cdmw.ui.preview.part_manifest import read_part_manifest as _read_part_manifest


class ArchivePreviewD3D11PartsMixin:
    """Feeds the Scene panel from the shown package and sends its ticks to the preview host."""

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
        bridge = getattr(self, "archive_remote_bridge", None)
        if bridge is not None and hasattr(bridge, "preview_entry_for"):
            entry = bridge.preview_entry_for(entry)
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
        bridge = getattr(self, "archive_remote_bridge", None)
        if bridge is not None and hasattr(bridge, "preview_entry_for"):
            entry = bridge.preview_entry_for(entry)
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

    def _clear_archive_scene_parts(self) -> None:
        self._archive_item_set_visibility_active = False
        panel = getattr(self, "archive_item_set_components", None)
        if panel is not None:
            panel.hide()

    def _apply_archive_hidden_parts(self) -> None:
        """Send the Scene panel's unticked parts (and Character Context's) to the preview."""

        hidden: List[int] = [
            int(index)
            for index in tuple(getattr(self, "archive_character_context_pending_hidden_indices", ()) or ())
            if int(index) >= 0
        ]
        if getattr(self, "_archive_item_set_visibility_active", False):
            hidden.extend(self.archive_item_set_components.hidden_indices)
        self.archive_d3d11_preview_host.set_hidden_source_submeshes(sorted(set(hidden)))

    def _archive_item_set_visibility_changed(self, _hidden: object = ()) -> None:
        if not getattr(self, "_archive_item_set_visibility_active", False):
            return
        self._apply_archive_hidden_parts()

    def _populate_archive_scene_parts(self, package_dir: Path) -> None:
        """List the shown package's files and parts in the Scene panel.

        The Scene panel is the one place to show, hide and load parts (Fredric,
        2026-11-21: it replaced the Parts dropdown above the preview). Prefab
        components the model can load are listed with it, unticked until loaded.
        """

        self._clear_archive_scene_parts()
        self.archive_character_context_pending_hidden_indices = ()
        self.archive_character_context_loaded_indices = ()
        manifest = _read_part_manifest(Path(package_dir))
        if manifest is None:
            return
        batches = manifest.get("batches")
        if not isinstance(batches, list):
            return
        bridge = getattr(self, "archive_remote_bridge", None)
        panel = getattr(self, "archive_item_set_components", None)
        is_set = bool(bridge is not None
                      and bridge.item_set_contains(getattr(self, "archive_preview_request_entry", None)))
        current_entry_getter = getattr(self, "_current_archive_entry", None)
        current_entry = current_entry_getter() if callable(current_entry_getter) else None
        self._sync_archive_character_context_source(current_entry)
        prefab_components: Dict[str, str] = {}
        context_indices: List[int] = []
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
                if not self._archive_d3d11_prefab_component_path_key(model_path):
                    continue
                prefab_components.setdefault(
                    model_path, str(member.get("display_name") or Path(model_path).name or model_path)
                )
        for batch in batches:
            if not isinstance(batch, Mapping):
                continue
            identity = batch.get("editor_identity")
            if not isinstance(identity, Mapping):
                continue
            try:
                source_index = int(identity.get("source_submesh_index", batch.get("index", -1)))
            except (TypeError, ValueError):
                continue
            if source_index < 0:
                continue
            if bool(identity.get("context_component", False)):
                context_indices.append(source_index)
        self.archive_character_context_loaded_indices = tuple(sorted(set(context_indices)))
        if panel is None:
            return
        # P5: the Scene panel beside every 3D preview, not only Item Finder sets.
        members = tuple(entry.path for entry in bridge.item_set_members) if is_set else ()
        panel.set_parts(batches, members, prefab_components=tuple(prefab_components.items()))
        self._archive_item_set_visibility_active = panel.active
        if is_set:
            selected = self._current_archive_entry()
            panel.highlight_path(str(getattr(selected, "path", "")))
        if self._archive_item_set_visibility_active:
            self._apply_archive_hidden_parts()

    def _archive_scene_open_file(self, path: str) -> None:
        """Open in Mesh Editor on one file of the Scene panel (P5)."""

        key = self._archive_scene_path_key(path)
        current = self._current_archive_entry()
        shell = getattr(self, "shell", None)
        launch = getattr(shell, "_launch_archive_mesh_editor_for_entry", None)
        if not key or not callable(launch):
            return
        if self._archive_scene_path_key(getattr(current, "path", "")) == key:
            launch(current)
            return
        entry, openable = self._archive_scene_entry_for_path(key)
        if entry is not None and openable:
            launch(entry)
            return
        # v2 keeps no catalogue-wide index here: a file the preview did not prepare,
        # or a prefab component without a set of its own, opens from its own row.
        if callable(getattr(shell, "set_status_message", None)):
            name = Path(str(path or "").replace("\\", "/")).name or str(path or "")
            shell.set_status_message(
                f"Select {name} in the archive list, then choose Open in Mesh Editor; its own files are not prepared yet.",
                error=True,
            )

    @staticmethod
    def _archive_scene_path_key(path: object) -> str:
        return str(path or "").replace("\\", "/").strip().strip("/").casefold()

    def _archive_scene_entry_for_path(self, key: str) -> tuple[object | None, bool]:
        """(entry, whether Open in Mesh Editor can take it) for one Scene panel file.

        The legacy browser indexes the whole catalogue. In v2 that index stays empty, so
        the file is found among the item set's members (whose open prepares the set) or
        in the preview's prepared files; a prefab component found there opens only when
        its own set is prepared, as Open in Mesh Editor requires.
        """
        from cdmw.services.archive_catalogue_service import ArchiveCatalogueService

        bridge = getattr(self, "archive_remote_bridge", None)
        if bridge is None or not bool(getattr(bridge, "displays_v2", False)):
            entries = tuple((getattr(self, "archive_entries_by_normalized_path", {}) or {}).get(key, ()))
            return (entries[0], True) if entries else (None, False)
        if bool(getattr(bridge, "item_set_active", False)):
            for member in tuple(getattr(bridge, "item_set_members", ()) or ()):
                if self._archive_scene_path_key(getattr(member, "path", "")) == key:
                    entry = ArchiveCatalogueService.compatibility_entry(member)
                    prepared = bridge.prepared_dependencies_for(entry)
                    entries = tuple(getattr(prepared, "entries", ()) or ())
                    return next((item for item in entries if item.identity == entry.identity), entry), True
        preview = getattr(self, "archive_preview_request_entry", None) or self._current_archive_entry()
        prepared = bridge.prepared_dependencies_for(preview) if preview is not None else None
        entries = tuple((getattr(prepared, "entries_by_normalized_path", {}) or {}).get(key, ()))
        if not entries:
            return None, False
        own = bridge.prepared_dependencies_for(entries[0])
        selected = getattr(own, "selected_entry", None)
        return entries[0], getattr(selected, "identity", None) == entries[0].identity

    def _archive_scene_prefab_toggled(self, path: str, checked: bool) -> None:
        """A prefab component file ticked in the Scene panel is loaded into the preview (P5)."""

        path_key = self._archive_d3d11_prefab_component_path_key(path)
        selected_paths = set(self._archive_d3d11_enabled_prefab_component_paths())
        if checked and path_key:
            selected_paths.add(path_key)
        else:
            selected_paths.discard(path_key)
        if self._set_archive_d3d11_enabled_prefab_component_paths(selected_paths):
            self._reload_archive_d3d11_prefab_components()

    def _reload_archive_d3d11_prefab_components(self) -> None:
        refresh = getattr(self, "_refresh_current_model_preview_assets", None)
        if not callable(refresh):
            return
        status = getattr(self.shell, "set_status_message", None)
        if callable(status):
            enabled_count = len(self._archive_d3d11_enabled_prefab_component_paths())
            status(
                "Loading enabled prefab component(s)..."
                if enabled_count
                else "Removing prefab components from preview..."
            )
        refresh(force=True)

    def _sync_archive_character_context_source(self, entry: object | None) -> None:
        panel = getattr(self, "archive_character_context_panel", None)
        button = getattr(self, "archive_character_context_button", None)
        if panel is None or button is None:
            return
        button.setChecked(False)
        button.setEnabled(False)
        button.setVisible(False)
        panel.setVisible(False)

    def _archive_character_context_selection_applied(self, source_entry: object, _components: object) -> None:
        current_entry_getter = getattr(self, "_current_archive_entry", None)
        current_entry = current_entry_getter() if callable(current_entry_getter) else None
        if current_entry is None or getattr(current_entry, "identity", None) != getattr(source_entry, "identity", None):
            return
        self.archive_character_context_pending_hidden_indices = tuple(
            getattr(self, "archive_character_context_loaded_indices", ()) or ()
        )
        self._apply_archive_hidden_parts()
        refresh = getattr(self, "_refresh_current_model_preview_assets", None)
        if callable(refresh):
            status = getattr(self.shell, "set_status_message", None)
            if callable(status):
                status("Updating Character Context preview...")
            refresh(force=True)
