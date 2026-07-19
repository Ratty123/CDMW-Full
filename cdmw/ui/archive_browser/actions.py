"""Archive browser action descriptors."""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import List, Optional, Sequence, Tuple

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import QApplication, QMenu, QPushButton

from cdmw.domain.archives.constants import (
    ARCHIVE_AUDIO_EXPORT_EXTENSIONS,
    ARCHIVE_AUDIO_PATCH_EXTENSIONS,
    ARCHIVE_MESH_EXTENSIONS,
)
from cdmw.services.material_sidecar_service import is_material_sidecar_entry
from cdmw.models import ArchiveEntry


ARCHIVE_CONTEXT_MENU_ICON_COLORS = {
    "view": "#6AA9FF",
    "file": "#7BD88F",
    "workflow": "#F6C85F",
    "family": "#B58CFF",
    "mesh": "#FF8A65",
    "texture": "#45D4C8",
    "physics": "#D1D5DB",
    "data": "#9CA3AF",
    "audio": "#F472B6",
    "maintenance": "#94A3B8",
}


def archive_context_menu_icon(color: str) -> QIcon:
    pixmap = QPixmap(12, 12)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    try:
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(color))
        painter.drawRoundedRect(1, 1, 10, 10, 2, 2)
    finally:
        painter.end()
    return QIcon(pixmap)


def archive_context_menu_icons() -> dict[str, QIcon]:
    return {
        key: archive_context_menu_icon(color)
        for key, color in ARCHIVE_CONTEXT_MENU_ICON_COLORS.items()
    }


@dataclass(frozen=True, slots=True)
class ArchiveBrowserAction:
    key: str
    text: str


class ArchiveBrowserActionMixin:
    """Archive browser button action handlers."""

    @staticmethod
    def _archive_action_menu_text(source_button: QPushButton, label: Optional[str], enabled: bool) -> str:
        base_text = str(label or source_button.text()).replace("...", "").strip() or "Action"
        return base_text if enabled else f"{base_text} (unavailable)"

    @staticmethod
    def _set_action_button_state(
        button: QPushButton,
        enabled: bool,
        active_tooltip: str,
        disabled_reason: str,
    ) -> None:
        button.setEnabled(bool(enabled))
        active_text = str(active_tooltip or "").strip()
        reason_text = str(disabled_reason or "").strip()
        if enabled or not reason_text:
            button.setToolTip(active_text)
        elif active_text:
            button.setToolTip(f"Unavailable: {reason_text}\n\n{active_text}")
        else:
            button.setToolTip(f"Unavailable: {reason_text}")

    @staticmethod
    def _first_unavailable_tooltip(tooltips: Sequence[str]) -> str:
        for tooltip in tooltips:
            text = str(tooltip or "").strip()
            if text.startswith("Unavailable:"):
                return text
        for tooltip in tooltips:
            text = str(tooltip or "").strip()
            if text:
                return text
        return "No action is available for the current selection."

    def _sync_archive_model_action_menu_buttons(self) -> None:
        for menu_group in getattr(self, "archive_model_action_menu_groups", ()):
            if len(menu_group) == 3:
                menu_button, title, action_pairs = menu_group
            else:
                menu_button, action_pairs = menu_group
                title = str(getattr(menu_button, "text", lambda: "Action")())
            any_enabled = False
            enabled_labels: List[str] = []
            disabled_tooltips: List[str] = []
            for action, source_button, label in action_pairs:
                enabled = source_button.isEnabled()
                action.setText(self._archive_action_menu_text(source_button, label, enabled))
                tooltip = source_button.toolTip()
                action.setToolTip(tooltip)
                action.setStatusTip(tooltip)
                action.setWhatsThis(tooltip)
                action.setEnabled(enabled)
                any_enabled = any_enabled or enabled
                if enabled:
                    enabled_labels.append(action.text())
                else:
                    disabled_tooltips.append(tooltip)
            menu_button.setEnabled(any_enabled)
            if any_enabled:
                enabled_text = ", ".join(enabled_labels[:4])
                suffix = f" Available now: {enabled_text}." if enabled_text else ""
                menu_button.setToolTip(
                    f"{title} actions for the current Archive Preview selection.{suffix} "
                    "Unavailable rows are greyed out; hover a menu row for the reason."
                )
            else:
                menu_button.setToolTip(
                    f"No {title} actions are available for the current Archive Preview selection.\n\n"
                    f"{self._first_unavailable_tooltip(disabled_tooltips)}"
                )

    @staticmethod
    def _archive_family_context_extensions() -> set[str]:
        return {
            ".pac",
            ".pam",
            ".pamlod",
            ".pac_xml",
            ".pam_xml",
            ".pamlod_xml",
            ".pami",
            ".app_xml",
            ".prefabdata_xml",
            ".prefab",
            ".hkx",
            ".hkt",
            ".meshinfo",
            ".paa",
            ".paa_metabin",
            ".pae",
            ".paem",
            ".motionblending",
            ".seqmt",
            ".pab",
            ".pabc",
            ".pabv",
            ".pabgb",
            ".pabgh",
        }

    def _archive_entry_supports_family_context_actions(self, entry: Optional[ArchiveEntry]) -> bool:
        return bool(
            isinstance(entry, ArchiveEntry)
            and (
                str(entry.extension or "").strip().lower() in self._archive_family_context_extensions()
                or is_material_sidecar_entry(entry)
            )
        )

    @staticmethod
    def _archive_entry_supports_attachment_placement_workflow(entry: Optional[ArchiveEntry]) -> bool:
        if not isinstance(entry, ArchiveEntry):
            return False
        extension = str(entry.extension or "").lower()
        basename = PurePosixPath(str(entry.path or "").replace("\\", "/")).name.casefold()
        if extension in set(ARCHIVE_MESH_EXTENSIONS) | {".prefab", ".hkx", ".hkt"}:
            return True
        return extension == ".xml" and basename.endswith(".sockets.xml")

    def _current_archive_mesh_entry(self) -> Optional[ArchiveEntry]:
        if self.archive_preview_showing_loose:
            return None
        current_entry = self._current_archive_entry()
        if current_entry is None or current_entry.extension not in ARCHIVE_MESH_EXTENSIONS:
            return None
        return current_entry

    def _current_archive_hkx_entry(self) -> Optional[ArchiveEntry]:
        if self.archive_preview_showing_loose:
            return None
        current_entry = self._current_archive_entry()
        if current_entry is None or str(current_entry.extension or "").lower() not in {".hkx", ".hkt"}:
            return None
        return current_entry

    @staticmethod
    def _archive_entry_is_hkx(entry: Optional[ArchiveEntry]) -> bool:
        return isinstance(entry, ArchiveEntry) and str(entry.extension or "").lower() in {".hkx", ".hkt"}

    def _archive_hkx_placement_candidates_for_entry(self, entry: Optional[ArchiveEntry]) -> Tuple[ArchiveEntry, ...]:
        if not isinstance(entry, ArchiveEntry):
            return ()
        if self._archive_entry_is_hkx(entry):
            return (entry,)

        candidates: List[ArchiveEntry] = []
        seen: set[Tuple[str, str, int]] = set()

        def add(candidate: Optional[ArchiveEntry]) -> None:
            if not self._archive_entry_is_hkx(candidate):
                return
            assert isinstance(candidate, ArchiveEntry)
            key = self._attachment_package_entry_key(candidate)
            if key in seen:
                return
            seen.add(key)
            candidates.append(candidate)

        for reference in self._current_archive_related_references_for_entry(entry):
            add(getattr(reference, "resolved_entry", None))

        return tuple(candidates)

    def _current_archive_hkx_placement_candidates(self) -> Tuple[ArchiveEntry, ...]:
        return self._archive_hkx_placement_candidates_for_entry(self._current_archive_entry())

    def _current_archive_binary_sidecar_entry(self) -> Optional[ArchiveEntry]:
        if self.archive_preview_showing_loose:
            return None
        current_entry = self._current_archive_entry()
        if current_entry is None:
            return None
        if str(current_entry.extension or "").lower() not in {
            ".meshinfo",
            ".motionblending",
            ".paa",
            ".paa_metabin",
            ".pae",
            ".paem",
            ".papr",
            ".paseq",
            ".paseqc",
            ".paschedule",
            ".paschedulepath",
            ".pastage",
            ".prefab",
            ".pappt",
            ".pamhc",
            ".seqmt",
        }:
            return None
        return current_entry

    def _selected_archive_bulk_placement_targets(self) -> List[ArchiveEntry]:
        targets: List[ArchiveEntry] = []
        seen: set[Tuple[str, str, int]] = set()
        for entry in self._selected_archive_entries():
            if not self._archive_entry_supports_attachment_placement_workflow(entry):
                continue
            key = self._attachment_package_entry_key(entry)
            if key in seen:
                continue
            seen.add(key)
            targets.append(entry)
        return targets

    def _archive_entry_at_tree_position(self, position) -> Optional[ArchiveEntry]:
        remote_bridge = getattr(self, "archive_remote_bridge", None)
        if remote_bridge is not None and remote_bridge.displays_v2:
            return remote_bridge.compatibility_entry_for_index(self.archive_tree.indexAt(position))
        item = self.archive_tree.itemAt(position)
        if item is None:
            return None
        kind = self._archive_tree_item_kind(item)
        value = self._archive_tree_item_value(item)
        if kind != "file" or not isinstance(value, int):
            return None
        if 0 <= value < len(self.archive_filtered_entries):
            return self.archive_filtered_entries[value]
        return None

    def _add_archive_material_context_action(
        self,
        menu: QMenu,
        menu_icons: dict[str, QIcon],
        entry: ArchiveEntry,
    ) -> None:
        material_sidecar_entry = self._related_material_sidecar_entry_for_archive_entry(entry)
        if entry.extension not in ARCHIVE_MESH_EXTENSIONS and not is_material_sidecar_entry(entry):
            return
        menu.addSection(menu_icons["texture"], "Material")
        edit_material_action = menu.addAction(menu_icons["texture"], "Edit Material Values...")
        edit_material_action.setEnabled(material_sidecar_entry is not None)
        if material_sidecar_entry is None:
            edit_material_action.setToolTip(
                "Unavailable: no recognized companion .pac_xml/.pac.xml/.pam_xml/.pam.xml/"
                ".pamlod_xml/.pamlod.xml/.pami material sidecar was found. Material values are "
                "stored in the sidecar, not in the selected mesh bytes."
            )
            return
        edit_material_action.setToolTip(
            "Read recognized values from the selected or companion material sidecar and export edited values as a mod-ready package."
        )
        edit_material_action.triggered.connect(
            lambda _checked=False, current_material_entry=material_sidecar_entry: self._open_material_sidecar_editor(current_material_entry)
        )

    def _show_archive_tree_context_menu(self, position) -> None:
        context_started_at = time.perf_counter()
        item = self.archive_tree.itemAt(position)
        if item is None:
            return
        kind = self._archive_tree_item_kind(item)
        value = self._archive_tree_item_value(item)
        if kind != "file" or not isinstance(value, int):
            return
        entry = self._archive_entry_at_tree_position(position)
        if entry is None:
            return
        self.archive_context_menu_selection_suppressed = True
        if not item.isSelected():
            self.archive_tree.clearSelection()
        try:
            self.archive_tree.setCurrentItem(item)
        finally:
            self.archive_context_menu_selection_suppressed = False
        self._schedule_archive_selection_state_update()

        menu = QMenu(self)
        if hasattr(menu, "setToolTipsVisible"):
            menu.setToolTipsVisible(True)

        menu_icons = archive_context_menu_icons()

        def _add_menu_section(kind: str, label: str) -> None:
            menu.addSection(menu_icons[kind], label)

        def _copy_archive_filename(current_entry: ArchiveEntry) -> None:
            QApplication.clipboard().setText(current_entry.basename)
            self.set_status_message(f"Copied filename to clipboard: {current_entry.basename}")

        _add_menu_section("view", "View + Inspect")
        preview_action = menu.addAction(menu_icons["view"], "Preview")
        preview_action.triggered.connect(lambda _checked=False, current_entry=entry: self._render_archive_preview(current_entry))
        preview_window_action = menu.addAction(menu_icons["view"], "Open Preview Window...")
        preview_window_action.triggered.connect(
            lambda _checked=False, current_entry=entry: self._open_archive_reference_preview_entry(current_entry)
        )

        _add_menu_section("file", "File")
        copy_filename_action = menu.addAction(menu_icons["file"], "Copy Filename")
        copy_filename_action.setToolTip("Copy only the archive file name, without folders.")
        copy_filename_action.triggered.connect(
            lambda _checked=False, current_entry=entry: _copy_archive_filename(current_entry)
        )
        export_file_action = menu.addAction(menu_icons["file"], "Export File...")
        export_file_action.triggered.connect(
            lambda _checked=False, current_entry=entry: self._export_archive_reference_entry(current_entry, title="Export Archive File")
        )
        extract_file_action = menu.addAction(menu_icons["file"], "Extract File...")
        extract_file_action.triggered.connect(
            lambda _checked=False, current_entry=entry: self._run_archive_extract(
                [current_entry],
                allow_original_dds_root=True,
                description=f"Extracting {current_entry.basename}...",
            )
        )
        scope_file_action = menu.addAction(menu_icons["file"], "Show Only This File")
        scope_file_action.triggered.connect(lambda _checked=False: self._scope_current_archive_entry_only())

        _add_menu_section("workflow", "Workflow")
        import_loose_mod_action = menu.addAction(menu_icons["workflow"], "Import Loose Mod Folder...")
        import_loose_mod_action.triggered.connect(lambda _checked=False: self._open_archive_loose_mod_overlay_dialog())
        weapon_placement_studio_action = menu.addAction(menu_icons["workflow"], "Weapon Placement Studio (Disabled - WIP)")
        weapon_placement_studio_action.setToolTip(
            "Disabled - WIP. Weapon Placement Studio is paused until the preview/export flow is ready again."
        )
        weapon_placement_studio_action.setEnabled(False)

        if self._archive_entry_supports_family_context_actions(entry):
            _add_menu_section("family", "Asset Family")
            family_action = menu.addAction(menu_icons["family"], "Asset Family...")
            family_action.triggered.connect(
                lambda _checked=False, current_entry=entry: self._open_archive_asset_family_workspace_dialog(current_entry)
            )
            hkx_placement_action = menu.addAction(menu_icons["family"], "Edit HKX...")
            hkx_placement_action.setToolTip(
                "Edit the related HKX/HKT directly on Placement. Related HKX/HKT files are resolved only after this action is clicked."
            )
            hkx_placement_action.setEnabled(self._archive_entry_supports_attachment_placement_workflow(entry))
            hkx_placement_action.triggered.connect(
                lambda _checked=False, current_entry=entry: self._open_archive_hkx_placement_for_entry(current_entry)
            )
            scope_family_action = menu.addAction(menu_icons["family"], "Filter to Family")
            scope_family_action.setToolTip("Filter Archive Files to the required/recommended files in this Asset Family.")
            scope_family_action.triggered.connect(
                lambda _checked=False, current_entry=entry: self._scope_archive_asset_family_for_entry(current_entry, include_hints=False)
            )
            export_family_action = menu.addAction(menu_icons["family"], "Export Family...")
            export_family_action.triggered.connect(
                lambda _checked=False, current_entry=entry: self._export_archive_asset_family_for_entry(current_entry, include_hints=False)
            )
            _add_menu_section("workflow", "Source Package")
            source_mix_action = menu.addAction(menu_icons["workflow"], "Build Loose Package From Sources...")
            source_mix_action.triggered.connect(
                lambda _checked=False, current_entry=entry: self._open_archive_source_mix_package_dialog(current_entry)
            )
        elif entry.extension not in ARCHIVE_MESH_EXTENSIONS:
            _add_menu_section("workflow", "Source Package")
            source_mix_action = menu.addAction(menu_icons["workflow"], "Build Loose Package From Sources...")
            source_mix_action.triggered.connect(
                lambda _checked=False, current_entry=entry: self._open_archive_source_mix_package_dialog(current_entry)
            )

        if entry.extension in ARCHIVE_MESH_EXTENSIONS:
            _add_menu_section("mesh", "Mesh Export")
            export_obj_action = menu.addAction(menu_icons["mesh"], "Export OBJ...")
            export_obj_action.triggered.connect(lambda _checked=False, current_entry=entry: self._start_archive_mesh_export(current_entry, "obj"))
            export_fbx_action = menu.addAction(menu_icons["mesh"], "Export FBX...")
            export_fbx_action.triggered.connect(lambda _checked=False, current_entry=entry: self._start_archive_mesh_export(current_entry, "fbx"))
            export_character_dependencies_action = menu.addAction(menu_icons["mesh"], "Export Character Dependency Package...")
            export_character_dependencies_action.setToolTip(
                "Collect the selected body/model with its strict appearance, prefab, material, texture, skeleton, physics, and motion dependencies."
            )
            export_character_dependencies_action.triggered.connect(
                lambda _checked=False, current_entry=entry: self._export_character_dependency_package_for_entry(current_entry)
            )
            _add_menu_section("mesh", "Mesh Edit")
            modify_original_action = menu.addAction(menu_icons["mesh"], "Modify Original...")
            modify_original_action.triggered.connect(
                lambda _checked=False, current_entry=entry: self._mesh_editor_modify_original_requested(current_entry)
            )
            import_patch_action = menu.addAction(menu_icons["mesh"], "Import Mesh...")
            import_patch_action.triggered.connect(
                lambda _checked=False, current_entry=entry: self._start_archive_mesh_patch(current_entry)
            )
            pending_swap_target = self.pending_in_game_mesh_swap_target
            if pending_swap_target is not None and not self._same_archive_entry(entry, pending_swap_target):
                swap_label = "Use This as Swap Source..."
            elif pending_swap_target is not None and self._same_archive_entry(entry, pending_swap_target):
                swap_label = "Cancel In-Game Mesh Swap Target"
            else:
                swap_label = "Start In-Game Mesh Swap..."
            swap_mesh_action = menu.addAction(menu_icons["mesh"], swap_label)
            swap_mesh_action.triggered.connect(
                lambda _checked=False, current_entry=entry: self._handle_archive_in_game_mesh_swap_entry(current_entry)
            )

        if entry.extension == ".dds":
            _add_menu_section("texture", "Texture")
            texture_editor_action = menu.addAction(menu_icons["texture"], "Open In Texture Editor...")
            texture_editor_action.triggered.connect(
                lambda _checked=False, current_entry=entry: self._open_archive_entry_in_texture_editor(current_entry)
            )
            workflow_action = menu.addAction(menu_icons["texture"], "DDS To Workflow...")
            workflow_action.triggered.connect(
                lambda _checked=False, current_entry=entry: self._run_archive_extract(
                    [current_entry],
                    set_original_dds_root=True,
                    allow_original_dds_root=True,
                    description=f"Extracting {current_entry.basename} to workflow...",
                )
            )

        if entry.extension in {".hkx", ".hkt"}:
            _add_menu_section("physics", "Physics / HKX")
            edit_hkx_action = menu.addAction(menu_icons["physics"], "Edit HKX...")
            edit_hkx_action.triggered.connect(lambda _checked=False, current_entry=entry: self._edit_archive_hkx_entry(current_entry))
            export_hkx_json_action = menu.addAction(menu_icons["physics"], "Export HKX JSON...")
            export_hkx_json_action.triggered.connect(lambda _checked=False: self._export_current_archive_hkx_json())
            export_hkx_xml_action = menu.addAction(menu_icons["physics"], "Export HKX XML...")
            export_hkx_xml_action.triggered.connect(lambda _checked=False: self._export_current_archive_hkx_xml())
            export_havok_view_action = menu.addAction(menu_icons["physics"], "Export Havok XML View...")
            export_havok_view_action.triggered.connect(lambda _checked=False: self._export_current_archive_hkx_havok_xml_view())

        if entry.extension in {".meshinfo", ".motionblending", ".paa", ".paa_metabin", ".pae", ".paem", ".papr", ".paseq", ".paseqc", ".paschedule", ".paschedulepath", ".pastage", ".prefab", ".pappt", ".pamhc", ".seqmt"}:
            _add_menu_section("data", "Structured Data")
            inspect_sidecar_action = menu.addAction(menu_icons["data"], "Inspect Structured Data...")
            inspect_sidecar_action.triggered.connect(lambda _checked=False: self._inspect_current_archive_binary_sidecar())
            export_sidecar_json_action = menu.addAction(menu_icons["data"], "Export Decode JSON...")
            export_sidecar_json_action.triggered.connect(lambda _checked=False: self._export_current_archive_binary_sidecar_json())
            if entry.extension == ".prefab":
                export_prefab_edit_json_action = menu.addAction(menu_icons["data"], "Export Prefab Edit JSON...")
                export_prefab_edit_json_action.triggered.connect(lambda _checked=False: self._export_current_archive_prefab_edit_json())
                import_prefab_edit_json_action = menu.addAction(menu_icons["data"], "Import Prefab Edit JSON...")
                import_prefab_edit_json_action.triggered.connect(lambda _checked=False: self._import_current_archive_prefab_edit_json())

        if entry.extension in {".paseq", ".paseqc", ".pastage", ".pabgh"}:
            edit_structured_action = menu.addAction(menu_icons["data"], "Edit Structured Data Safely...")
            edit_structured_action.setToolTip(
                "Create an edited sidecar copy using only fixed-size string edits or validated PABGH table rows."
            )
            edit_structured_action.triggered.connect(
                lambda _checked=False, current_entry=entry: self._edit_archive_structured_binary_sidecar(current_entry)
            )

        self._add_archive_material_context_action(menu, menu_icons, entry)

        if entry.extension in ARCHIVE_AUDIO_EXPORT_EXTENSIONS or entry.extension in ARCHIVE_AUDIO_PATCH_EXTENSIONS:
            _add_menu_section("audio", "Audio")
            export_audio_action = menu.addAction(menu_icons["audio"], "Export WAV...")
            export_audio_action.triggered.connect(
                lambda _checked=False, current_entry=entry: self._start_archive_audio_export(current_entry)
            )
            if entry.extension in ARCHIVE_AUDIO_PATCH_EXTENSIONS:
                import_audio_action = menu.addAction(menu_icons["audio"], "Import WAV + Patch to Game...")
                import_audio_action.triggered.connect(
                    lambda _checked=False, current_entry=entry: self._start_archive_audio_patch(current_entry)
                )

        elapsed_ms = max(0.0, (time.perf_counter() - context_started_at) * 1000.0)
        self.append_archive_log(
            f"Archive context menu timing | build={elapsed_ms:.0f}ms | path={entry.path}",
            verbose=True,
        )
        menu.exec(self.archive_tree.viewport().mapToGlobal(position))

    def _preview_current_archive_entry(self) -> None:
        entry = self._current_archive_action_entry("Preview")
        if entry is None:
            return
        self._render_archive_preview(entry)

    def _open_current_archive_preview_window(self) -> None:
        entry = self._current_archive_action_entry("Open Preview Window")
        if entry is None:
            return
        self._open_archive_reference_preview_entry(entry)

    def _copy_current_archive_filename(self) -> None:
        entry = self._current_archive_action_entry("Copy Filename")
        if entry is None:
            return
        QApplication.clipboard().setText(entry.basename)
        self.set_status_message(f"Copied filename to clipboard: {entry.basename}")

    def _export_current_archive_file(self) -> None:
        entry = self._current_archive_action_entry("Export File")
        if entry is None:
            return
        self._export_archive_reference_entry(entry, title="Export Archive File")

    def _extract_current_archive_file(self) -> None:
        entry = self._current_archive_action_entry("Extract File")
        if entry is None:
            return
        remote_bridge = getattr(self, "archive_remote_bridge", None)
        if remote_bridge is not None and remote_bridge.displays_v2:
            selection = remote_bridge.current_entry_export_selection()
            if selection is None:
                self.set_status_message("Select an archive file before using Extract File.", error=True)
                return
            self._run_remote_archive_export(
                selection,
                allow_original_dds_root=True,
                description=f"Extracting {entry.basename}...",
            )
            return
        self._run_archive_extract(
            [entry],
            allow_original_dds_root=True,
            description=f"Extracting {entry.basename}...",
        )

    def _scope_current_archive_asset_family(self) -> None:
        entry = self._current_archive_action_entry("Filter to Family")
        if entry is None:
            return
        self._scope_archive_asset_family_for_entry(entry, include_hints=False)

    def _export_current_archive_asset_family(self) -> None:
        entry = self._current_archive_action_entry("Export Family")
        if entry is None:
            return
        self._export_archive_asset_family_for_entry(entry, include_hints=False)

    def _open_current_archive_source_mix_package(self) -> None:
        entry = self._current_archive_action_entry("Build Loose Package From Sources")
        if entry is None:
            return
        self._open_archive_source_mix_package_dialog(entry)

    def _export_current_archive_character_dependency_package(self) -> None:
        entry = self._current_archive_action_entry("Export Character Dependency Package")
        if entry is None:
            return
        self._export_character_dependency_package_for_entry(entry)


__all__ = [
    "ArchiveBrowserAction",
    "ArchiveBrowserActionMixin",
    "archive_context_menu_icon",
    "archive_context_menu_icons",
]
