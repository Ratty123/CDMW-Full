"""Texture handoffs into the shared job and adjacent authoring tools."""
from __future__ import annotations

from pathlib import Path
from typing import List, Mapping, Optional, Tuple
from PySide6.QtWidgets import QMessageBox, QWidget
from cdmw.models import ArchiveEntry, TextureEditorSourceBinding


class TextureWorkflowEditorHandoffMixin:
    def _set_pending_archive_workflow_extract(self, *, entries, output_root: Path) -> None:
        """Adopt already-extracted DDS sources directly into the current job."""
        for entry in entries:
            if not isinstance(entry, ArchiveEntry):
                continue
            relative = Path(entry.pamt_path.parent.name) / Path(entry.path.replace("\\", "/"))
            source = output_root / relative
            asset = self.job.add_source(source, TextureEditorSourceBinding(
                source_path=str(source), original_dds_path=str(source),
                archive_relative_path=entry.path, relative_path=relative.as_posix(),
                package_root=entry.pamt_path.parent.name,
            ))
            asset.original_entry = entry
        self._refresh_texture_assets()
        self.set_texture_mode("upscale")

    def _handle_texture_editor_send_to_replace_assistant(self, png_path_text: str, binding: object) -> None:
        self.open_texture_sources([Path(png_path_text)], binding=binding)
        self.show_texture_review(operation="replacement")

    def _handle_texture_editor_send_to_texture_workflow(self, png_path_text: str, binding: object) -> None:
        self.open_texture_sources([Path(png_path_text)], binding=binding)
        self.set_texture_mode("upscale")

    def _manual_workflow_cleanup_targets(self) -> List[Tuple[str, str, Optional[Path]]]:
        targets: List[Tuple[str, str, Optional[Path]]] = []
        for key, label, text in (
            ("rebuilt_textures", "Rebuilt textures", self.output_root_edit.text().strip()),
            ("original_dds", "Original DDS sources", self.original_dds_edit.text().strip()),
            ("dds_input_png", "DDS input PNG staging", self.dds_staging_root_edit.text().strip()),
            ("upscaled_png", "Upscaled PNG staging", self.png_root_edit.text().strip()),
            ("texture_editor_png", "Texture Editor PNG staging", self.texture_editor_png_root_edit.text().strip()),
        ):
            targets.append((key, label, Path(text).expanduser() if text else None))
        return targets

    def _handle_texture_editor_send_to_item_icons(self, png_path_text: str, binding: object) -> None:
        source_path = Path(png_path_text).expanduser()
        if not source_path.exists():
            self.shell.set_status_message(f"Texture Editor export not found: {source_path}", error=True)
            return
        del binding
        try:
            imported_path = self.shell.item_icons_tab.add_imported_source(source_path)
        except Exception as exc:
            self.shell.set_status_message(f"Texture Editor export could not be added to Icon Creator: {exc}", error=True)
            return
        self.shell._activate_tool_widget(self.shell.item_icons_tab)
        if imported_path is not None:
            self.shell.item_icons_tab.select_source_path(imported_path)
            self.shell.set_status_message(f"Texture Editor export added to Icon Creator: {Path(imported_path).name}")

    def _handle_model_library_item_icon_generated(self, png_path_text: str, model_payload: object) -> None:
        source_path = Path(png_path_text).expanduser()
        if not source_path.is_file():
            self.shell.set_status_message(f"Generated model icon was not found: {source_path}", error=True)
            return
        try:
            imported_path = self.shell.item_icons_tab.add_imported_source(source_path)
        except Exception as exc:
            self.shell.set_status_message(f"Generated model icon could not be added to Icon Creator: {exc}", error=True)
            return
        self.shell._activate_tool_widget(self.shell.item_icons_tab)
        if imported_path is not None:
            self.shell.item_icons_tab.select_source_path(imported_path)
        metadata = model_payload if isinstance(model_payload, Mapping) else {}
        model_name = str(metadata.get("name", "") or source_path.stem).strip()
        self.shell.set_status_message(f"Generated model preview icon added to Icon Creator: {model_name}.")

    def _choose_item_icon_library_source(self, parent: Optional[QWidget] = None) -> Optional[Path]:
        tab = getattr(self.shell, "item_icons_tab", None)
        if tab is None:
            self.shell.set_status_message("Icon Creator library is unavailable.", error=True)
            return None
        try:
            return tab.choose_source_dialog(parent)
        except Exception as exc:
            QMessageBox.warning(parent or self, "Icon Creator", str(exc))
            self.shell.set_status_message(f"Icon Creator library picker failed: {exc}", error=True)
            return None

    def _show_compare_from_texture_editor(self, relative_path_text: str, binding: object) -> None:
        del relative_path_text, binding
        self.shell._activate_tool_key("textures")
        self._with_texture_editor(lambda editor: editor.view_mode_combo.setCurrentIndex(editor.view_mode_combo.findData("split")))
