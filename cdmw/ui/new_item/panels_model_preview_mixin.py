"""Preview, placement, import, and icon interactions for the New Item model panel."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSettings, Qt
from PySide6.QtWidgets import QFileDialog

from cdmw.domain.new_item.spec import IconSource
from cdmw.ui.new_item.model_import import ModelPlacement
from cdmw.ui.new_item.ui_kit import EDIT, OK, WARN

IMPORT_FILE_FILTER = (
    "Model files (*.gltf *.glb *.obj *.dae *.fbx *.zip);;glTF / GLB (*.gltf *.glb);;Wavefront OBJ (*.obj);;"
    "Collada DAE (*.dae);;FBX, converted with Blender (*.fbx);;Zip with a model inside (*.zip);;All files (*)"
)
IMPORT_DIR_SETTING = "ui/new_item_import_dir"


class ModelPanelPreviewMixin:
    def _icon_source_changed(self, keep: bool) -> None:
        self._controller.draft.icon = IconSource.TEMPLATE if keep else IconSource.GENERATED
        for widget in (self.icon_source, self.icon_file_button, self.icon_folder_button):
            widget.setEnabled(not keep)
        self._controller.invalidate_plan()

    def _character_preview_changed(self, checked: bool) -> None:
        """Rebuild only the preview reference; item placement and output stay untouched."""

        if checked:
            overlay_index = self.view_mode.findData("overlay")
            if overlay_index >= 0:
                self.view_mode.setCurrentIndex(overlay_index)
            self.preview.set_view_mode("overlay")
        self._preview_mesh_token = None
        self.refresh_preview()

    def showEvent(self, event) -> None:  # noqa: N802 - Qt virtual
        super().showEvent(event)
        self._show_preview_timer.start()

    def refresh_preview(self) -> None:
        """Show the selected item source in the inline resident viewport."""

        window = self.window()
        if not (self.isVisible() or (window is not None and window.isVisible())):
            return
        show_character = self.show_character.isChecked()
        source = self._controller.item_preview_source(include_character=show_character)
        if source is None:
            self.preview.show(None)
            self.capture_inline_button.setEnabled(False)
            self._preview_mesh_token = None
            return
        token, build = source
        imported = self._controller.model_import
        if imported is not None or show_character:
            if token != self._preview_mesh_token:
                self.capture_inline_button.setEnabled(False)
            self._preview_mesh_token = token
            placement = self._controller.model_placement if imported is not None else ModelPlacement()
            model_bounds = imported.baked_bounds() if imported is not None else None
            self.preview.show_placement(
                build,
                token=token,
                placement=placement,
                model_bounds=model_bounds,
                gizmo_enabled=imported is not None,
            )
            self._refresh_placement_enabled()
            return
        if token == self._preview_mesh_token and self.preview.is_ready:
            return
        self._preview_mesh_token = token
        self.capture_inline_button.setEnabled(False)
        self.preview.show(build, token=token)

    def _pick_model_file(self) -> None:
        settings = QSettings("CrimsonDesertModWorkbench", "CrimsonDesertModWorkbench")
        start_dir = str(settings.value(IMPORT_DIR_SETTING, "") or "")
        if not start_dir or not Path(start_dir).is_dir():
            start_dir = str(Path.home())
        path, _selected = QFileDialog.getOpenFileName(
            self,
            "Import a model file",
            start_dir,
            IMPORT_FILE_FILTER,
        )
        if not path:
            return
        settings.setValue(IMPORT_DIR_SETTING, str(Path(path).parent))
        self.import_model.setChecked(True)
        self._controller.start_model_import(Path(path))

    def _refresh_apply_status(self) -> None:
        if self._controller.model_import is None:
            return
        if self._controller.model_result is not None:
            self.apply_status.set_note("Applied: the plan will write this mesh.", OK)
        else:
            self.apply_status.set_note("Not applied yet: the plan needs Apply the placement.", WARN)

    def _fit_to_template(self) -> None:
        self._controller.fit_model_placement()

    def _placement_changed(self, placement: object) -> None:
        if isinstance(placement, ModelPlacement):
            self._sync_placement_numbers(placement)
            if self._controller.model_import is not None:
                self.preview.set_placement(placement)
                self.refresh_preview()

    def _sync_placement_numbers(self, placement: ModelPlacement) -> None:
        self._syncing_numbers = True
        try:
            groups = (
                (self.offset_spins, placement.offset),
                (self.rotation_spins, placement.rotation),
                (self.scale_spins, placement.scale),
            )
            for spins, values in groups:
                for spin, value in zip(spins, values):
                    if abs(spin.value() - float(value)) > 0.5 * 10 ** (-spin.decimals()):
                        spin.setValue(float(value))
        finally:
            self._syncing_numbers = False

    def _numbers_changed(self, _value: float) -> None:
        if self._syncing_numbers or self._controller.model_import is None:
            return
        self._controller.set_model_placement(
            ModelPlacement(
                offset=tuple(spin.value() for spin in self.offset_spins),
                rotation=tuple(spin.value() for spin in self.rotation_spins),
                scale=tuple(spin.value() for spin in self.scale_spins),
            )
        )

    def _gizmo_moved(self, placement: object, finished: bool) -> None:
        if not isinstance(placement, ModelPlacement):
            return
        self._sync_placement_numbers(placement)
        if finished:
            self._controller.set_model_placement(placement)

    def _import_failed(self, message: object) -> None:
        self.model_status.set_note(str(message or "The model could not be read."), WARN)
        self.busy_bar.setVisible(False)

    def _busy_changed(self, busy: bool) -> None:
        lane = getattr(self._controller, "_lane", "")
        for widget in (
            self.import_button,
            self.apply_button,
            self.fit_button,
            self.open_part_editor_button,
            self.use_part_editor_button,
        ):
            widget.setEnabled(not busy)
        model_busy = bool(busy) and lane in {"model_import", "model_apply", "model_part_edit"}
        self.operation_banner.setVisible(model_busy or self._preview_busy)
        self.operation_spinner.set_running(model_busy or self._preview_busy)
        self.cancel_operation_button.setVisible(model_busy)
        self.cancel_operation_button.setEnabled(model_busy)
        if model_busy:
            self.busy_bar.setRange(0, 0)
            self.busy_bar.setVisible(True)
        elif not self._preview_busy:
            self.busy_bar.setVisible(False)
        if busy and lane == "model_import":
            self.model_status.set_note("Reading the model file...", EDIT)
            self.operation_label.setText("Reading the model file…")
        elif busy and lane == "model_apply":
            self.apply_status.set_note("Building the item's mesh at this placement...", EDIT)
            self.operation_label.setText("Building the item's mesh…")
        elif busy and lane == "model_part_edit":
            self.part_editor_status.setVisible(True)
            self.part_editor_status.set_note("Preparing the Mesh Editor changes...", EDIT)
            self.operation_label.setText("Preparing Mesh Editor changes…")
        self._refresh_placement_enabled()

    def _operation_progress(self, lane: str, current: int, total: int, detail: str) -> None:
        if str(lane) not in {"model_import", "model_apply", "model_part_edit"}:
            return
        self.operation_label.setText(str(detail or "Working…"))
        if int(total) > 0:
            self.busy_bar.setRange(0, int(total))
            self.busy_bar.setValue(max(0, min(int(total), int(current))))
        else:
            self.busy_bar.setRange(0, 0)

    def _cancel_operation(self) -> None:
        lane = str(getattr(self._controller, "_lane", "") or "")
        if self._controller.cancel_operation(lane):
            self.operation_label.setText("Cancelling…")
            self.cancel_operation_button.setEnabled(False)

    def _preview_status(self, text: str) -> None:
        message = str(text or "")
        self._preview_busy = message in {
            "Building the preview...",
            "Loading the viewport...",
            "Loading model textures…",
        }
        self.preview_status.setText("" if self._preview_busy else message)
        if not self._controller.busy:
            self.operation_banner.setVisible(self._preview_busy)
            self.operation_spinner.set_running(self._preview_busy)
            self.cancel_operation_button.setVisible(False)
            self.busy_bar.setRange(0, 0)
            self.busy_bar.setVisible(self._preview_busy)
            if self._preview_busy:
                self.operation_label.setText(message.replace("...", "…"))
        self._refresh_placement_enabled()

    def _refresh_placement_enabled(self) -> None:
        ready = bool(getattr(self.preview, "showing_placement", False)) and not self._controller.busy
        widgets = (
            *self.offset_spins,
            *self.rotation_spins,
            *self.scale_spins,
            *self.gizmo_buttons.values(),
            self.view_mode,
            self.grid_visible,
            self.frame_view_button,
        )
        for widget in widgets:
            widget.setEnabled(ready)
        building = self._controller.model_import is not None and not ready
        if building and not self._controller.busy:
            self.apply_status.set_note("Building the preview with your model...", EDIT)

    def _capture_inline(self) -> None:
        if not self.preview.capture():
            self.preview_status.setText(
                "The viewport is not showing the item yet; wait for it, then capture."
            )

    @staticmethod
    def icon_region_dialog_factory(parent, image):
        from cdmw.ui.archive_browser.static_replacement_icon_selection import AlignmentIconSelectionDialog

        return AlignmentIconSelectionDialog(image, parent)

    def _inline_capture_done(self, path: object, image: object) -> None:
        from PySide6.QtGui import QImage, QPixmap
        from PySide6.QtWidgets import QDialog

        from cdmw.ui.archive_browser.static_replacement_custom_icon import custom_item_icon_selected_preview_image

        captured = image if isinstance(image, QImage) and not image.isNull() else QImage(str(path))
        if captured.isNull():
            self.preview_status.setText("The capture came back empty.")
            return
        dialog = self.icon_region_dialog_factory(self, captured)
        if dialog.exec() != QDialog.Accepted:
            self.preview_status.setText("Capture dropped; the icon is unchanged.")
            return
        try:
            icon = custom_item_icon_selected_preview_image(
                captured,
                dialog.selected_source_rect(),
                size=512,
            )
            target = Path(str(path)).with_name(f"icon_{Path(str(path)).stem}_selected.png")
            if not icon.save(str(target)):
                raise ValueError(f"the icon could not be written to {target}")
        except Exception as exc:  # noqa: BLE001
            self.preview_status.setText(f"The icon could not be made from that selection: {exc}")
            return
        self.generate_icon.setChecked(True)
        self.icon_source.setText(str(target))
        self.preview_status.setText(f"Icon taken from the view: {icon.width()} x {icon.height()}.")
        try:
            pixmap = QPixmap.fromImage(icon).scaled(
                self.icon_thumbnail.size(),
                Qt.KeepAspectRatio,
                Qt.SmoothTransformation,
            )
            self.icon_thumbnail.setPixmap(pixmap)
            self.icon_thumbnail.setVisible(True)
        except Exception:  # noqa: BLE001
            pass

    def shutdown_preview(self) -> None:
        self._show_preview_timer.stop()
        self.operation_spinner.set_running(False)
        try:
            self.preview.shutdown()
        except Exception:  # noqa: BLE001
            pass

    def request_shutdown_preview(self) -> None:
        self._show_preview_timer.stop()
        self.operation_spinner.set_running(False)
        try:
            self.preview.request_shutdown()
        except Exception:  # noqa: BLE001
            pass

    def iter_shutdown_workers(self):
        try:
            return self.preview.iter_shutdown_workers()
        except Exception:  # noqa: BLE001
            return ()

    def _store_icon_source(self, text: str) -> None:
        self._controller.draft.icon_source_path = str(text)
        self._controller.invalidate_plan()

    def _pick_icon_file(self) -> None:
        path, _selected = QFileDialog.getOpenFileName(
            self,
            "Choose an icon source image",
            self.icon_source.text() or "",
            "Images (*.png *.jpg *.jpeg *.bmp *.tga *.dds *.webp);;All files (*)",
        )
        if path:
            self.icon_source.setText(path)

    def _pick_icon_folder(self) -> None:
        path = QFileDialog.getExistingDirectory(
            self,
            "Choose a folder of icon source images",
            self.icon_source.text() or "",
        )
        if path:
            self.icon_source.setText(path)


__all__ = [
    "IMPORT_DIR_SETTING",
    "IMPORT_FILE_FILTER",
    "ModelPanelPreviewMixin",
]
