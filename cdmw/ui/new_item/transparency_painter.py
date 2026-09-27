"""Focused greyscale painter using the Texture workspace's canvas and brushes."""
import numpy as np
from dataclasses import replace

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout, QGridLayout,
                              QLabel, QPushButton, QScrollArea, QSpinBox, QVBoxLayout)

from cdmw.domain.textures.editor_brush import apply_texture_editor_stroke
from cdmw.domain.textures.transparency_mask import TransparencyMask
from cdmw.models import TextureEditorDocument, TextureEditorLayer, TextureEditorToolSettings
from cdmw.ui.texture_workflow.editor_canvas import TextureEditorCanvas


class TransparencyPaintDialog(QDialog):
    def __init__(self, prepared, apply_mask, *, part, glass=False, run_file_task=None, cancel_file_task=None, parent=None):
        super().__init__(parent)
        self.setProperty("cdmwNativeCanvasDialog", True)
        self.setWindowTitle(f"Paint transparency — {part}")
        self.setWindowModality(Qt.WindowModality.WindowModal)
        self.resize(920, 700)
        self._apply_mask = apply_mask
        self._run_file_task, self._cancel_file_task = run_file_task, cancel_file_task
        self._io_active = False
        self.finished.connect(self._cancel_io)
        self._initial = prepared.mask
        self._controls = prepared.controls
        self._mode = prepared.mode
        self._dual = prepared.surface_mask is not None
        self._surface_initial = prepared.surface_mask
        self._history = [prepared.mask.pixels]
        self._surface_history = [prepared.surface_mask.pixels if self._dual else b""]
        self._edited_history = [(False, False)]
        self._history_index = 0
        self._history_limit = max(2, min(40, 64 * 1024 * 1024 //
            (len(prepared.mask.pixels) + len(self._surface_history[0]))))
        self._reference = np.frombuffer(prepared.reference_rgba, dtype=np.uint8).reshape(
            prepared.mask.height, prepared.mask.width, 4)
        self.document = TextureEditorDocument("Transparency mask", prepared.mask.width, prepared.mask.height,
            active_layer_id="mask", layers=(TextureEditorLayer("mask", "Mask", "", alpha_locked=True),))
        layout = QVBoxLayout(self)
        if glass:
            note = QLabel("Paint lighter for more transparency and darker for less. White reduces absorption; black uses the selected absorption strength. Reflections can remain.")
        elif self._mode == "cutout":
            note = QLabel("Experimental hard cutout: white removes surface pixels; black keeps them. Grays form a threshold field, not continuous transparency. Test fine holes, animation, shadows and LODs in game.")
        else:
            note = QLabel("White fades; black retains. Choose colour, surface or both. Switching targets keeps your work.")
            note.setToolTip("Surface response means normal/material contribution, independent of colour. Linked fade edits both masks in one undo step. This does not guarantee an invisible surface.")
        note.setWordWrap(True)
        layout.addWidget(note)
        self.target = QComboBox()
        self.target.addItems(["Colour coverage", "Surface response", "Linked fade"])
        self.target.setVisible(self._dual)
        layout.addWidget(self.target)
        toolbar = QGridLayout()
        self.value = QSpinBox()
        self.value.setRange(0, 255)
        self.value.setValue(255)
        self.value.setToolTip("Paint value: 0 black, 255 white. Intermediate values produce partial transparency.")
        self.brush_size, self.hardness, self.opacity = QSpinBox(), QSpinBox(), QSpinBox()
        for control, maximum, initial in ((self.brush_size, 1024, 64), (self.hardness, 100, 50), (self.opacity, 100, 50)):
            control.setRange(1 if control is self.brush_size else 0, maximum)
            control.setValue(initial)
        for column, (title, control) in enumerate((("Value", self.value), ("Brush", self.brush_size), ("Hardness", self.hardness), ("Opacity", self.opacity))):
            form = QFormLayout()
            form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapAllRows)
            form.addRow(title, control)
            toolbar.addLayout(form, 0, column)
        self.view = QComboBox()
        self.view.addItems(["Texture + mask", "Mask only"])
        toolbar.addWidget(self.view, 1, 0, 1, 4)
        layout.addLayout(toolbar)
        actions = QGridLayout()
        self.more = QPushButton("More transparent")
        self.less = QPushButton("Less transparent")
        self.more.clicked.connect(lambda: self.value.setValue(255))
        self.less.clicked.connect(lambda: self.value.setValue(0))
        self.undo_button, self.redo_button = QPushButton("Undo"), QPushButton("Redo")
        self.undo_button.clicked.connect(lambda: self._move_history(-1))
        self.redo_button.clicked.connect(lambda: self._move_history(1))
        self.reset_button = QPushButton("Reset")
        self.reset_button.setToolTip("Reset painting")
        self.reset_button.clicked.connect(lambda: self._edit(lambda _pixels, mask, _channel: mask.pixels))
        self.fit_button = QPushButton("Fit")
        for button in (self.more, self.less, self.undo_button, self.redo_button, self.reset_button, self.fit_button):
            button.setAutoDefault(False)
        actions.addWidget(self.more, 0, 0, 1, 2)
        actions.addWidget(self.less, 0, 2, 1, 2)
        for column, button in enumerate((self.undo_button, self.redo_button, self.reset_button, self.fit_button)):
            actions.addWidget(button, 1, column)
        layout.addLayout(actions)
        utilities = QGridLayout()
        self.fill_button, self.invert_button = QPushButton("Fill"), QPushButton("Invert")
        self.gradient_button = QPushButton("Gradient")
        self.gradient_direction = QComboBox()
        self.gradient_direction.addItems(["Left to right", "Top to bottom"])
        self.fill_button.clicked.connect(lambda: self._edit(lambda pixels, _mask, _channel: bytes([self.value.value()]) * len(pixels)))
        self.invert_button.clicked.connect(lambda: self._edit(lambda pixels, _mask, _channel: pixels.translate(bytes(reversed(range(256))))))
        self.gradient_button.clicked.connect(self._gradient)
        for column, control in enumerate((self.fill_button, self.invert_button, self.gradient_button, self.gradient_direction)):
            utilities.addWidget(control, column // 2, column % 2)
            if isinstance(control, QPushButton):
                control.setAutoDefault(False)
        layout.addLayout(utilities)
        self.import_button, self.export_button = QPushButton("Import PNG…"), QPushButton("Export PNG…")
        self.import_channel = QComboBox()
        self.import_channel.addItems(["Gray", "R", "G", "B", "A"])
        self.import_channel.setToolTip("Imported image channel. Gray requires a grayscale PNG. Dimensions and orientation must match; no stretching or flipping.")
        self.import_button.clicked.connect(self._import_mask)
        self.export_button.clicked.connect(self._export_mask)
        file_row = QGridLayout()
        for column, control in enumerate((self.import_button, self.import_channel, self.export_button)):
            file_row.addWidget(control, 0, column)
            control.setVisible(run_file_task is not None)
        layout.addLayout(file_row)
        self.canvas = TextureEditorCanvas()
        scroll = QScrollArea()
        scroll.setWidget(self.canvas)
        scroll.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.canvas.attach_scroll_area(scroll)
        self.canvas.stroke_committed.connect(self._stroke)
        self.canvas.wheel_zoom_requested.connect(self._zoom)
        self.fit_button.clicked.connect(lambda: self.canvas.set_fit_to_view(True))
        self.brush_size.valueChanged.connect(self.canvas.set_brush_size)
        self.hardness.valueChanged.connect(self._brush_visuals)
        self._brush_visuals()
        self.canvas.set_brush_size(self.brush_size.value())
        layout.addWidget(scroll, 1)
        self.message = QLabel(f"Mask: {prepared.mask.width} × {prepared.mask.height}. The mask is resized to the material texture on export. Red overlay shows the painted transparency. Scroll to zoom; middle-drag to pan.")
        self.message.setWordWrap(True)
        layout.addWidget(self.message)
        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Apply | QDialogButtonBox.StandardButton.Cancel)
        self.buttons.button(QDialogButtonBox.StandardButton.Apply).clicked.connect(self._apply)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)
        self.view.currentIndexChanged.connect(self._refresh)
        self.target.currentIndexChanged.connect(self._refresh)
        self._undo_shortcut = QShortcut(QKeySequence.StandardKey.Undo, self)
        self._undo_shortcut.activated.connect(lambda: self._move_history(-1))
        self._redo_shortcut = QShortcut(QKeySequence.StandardKey.Redo, self)
        self._redo_shortcut.activated.connect(lambda: self._move_history(1))
        self._refresh()

    def _brush_visuals(self, *_args):
        self.canvas.set_brush_visual_state(hardness=self.hardness.value(), tip="round", roundness=100,
                                          angle_degrees=0, pattern="solid")

    def _channel(self):
        return int(self._dual and self.target.currentIndex() == 1)

    def _pixels(self, channel=None):
        channel = self._channel() if channel is None else channel
        mask = self._surface_initial if channel else self._initial
        history = self._surface_history if channel else self._history
        plane = np.frombuffer(history[self._history_index], dtype=np.uint8).reshape(mask.height, mask.width)
        rgba = np.empty((*plane.shape, 4), dtype=np.uint8)
        rgba[..., :3], rgba[..., 3] = plane[..., None], 255
        return rgba

    def _refresh(self, *_args):
        image = self._pixels()
        self.document = replace(self.document, width=image.shape[1], height=image.shape[0])
        if self.view.currentIndex() == 0:
            reference = self._reference
            if reference.shape[:2] != image.shape[:2]:
                from PIL import Image
                reference = np.asarray(Image.fromarray(reference).resize((image.shape[1], image.shape[0]), Image.Resampling.BILINEAR))
            weight = image[..., :1].astype(np.float32) / 510.
            image[..., :3] = np.round(reference[..., :3] * (1. - weight) + np.array([255, 45, 20]) * weight).astype(np.uint8)
        self.canvas.set_rgba_images(image)
        self.undo_button.setEnabled(self._history_index > 0)
        self.redo_button.setEnabled(self._history_index + 1 < len(self._history))
        self.message.setText(f"Mask: {self.document.width} × {self.document.height}. Red shows fade. Scroll to zoom; middle-drag to pan. Mirrored, overlapping and tiled UVs share paint.")

    def _remember(self, pixels):
        self._edit(lambda _pixels, _mask, _channel: pixels)

    def _edit(self, operation):
        if self._io_active:
            return
        colour, surface = self._history[self._history_index], self._surface_history[self._history_index]
        edited = list(self._edited_history[self._history_index])
        channels = (0, 1) if self._dual and self.target.currentIndex() == 2 else (self._channel(),)
        for channel in channels:
            before = surface if channel else colour
            mask = self._surface_initial if channel else self._initial
            after = operation(before, mask, channel)
            if len(after) != len(before):
                raise ValueError("Mask dimensions must match the selected target.")
            if self._dual:
                edited[channel] = True
            if after != before:
                edited[channel] = True
                if channel:
                    surface = after
                else:
                    colour = after
        if (colour == self._history[self._history_index] and surface == self._surface_history[self._history_index]
                and tuple(edited) == self._edited_history[self._history_index]):
            return
        self._history = self._history[:self._history_index + 1] + [colour]
        self._surface_history = self._surface_history[:self._history_index + 1] + [surface]
        self._edited_history = self._edited_history[:self._history_index + 1] + [tuple(edited)]
        self._history = self._history[-self._history_limit:]
        self._surface_history = self._surface_history[-self._history_limit:]
        self._edited_history = self._edited_history[-self._history_limit:]
        self._history_index = len(self._history) - 1
        self._refresh()

    def _stroke(self, payload):
        if not isinstance(payload, dict) or not payload.get("points"):
            return
        shade = f"{self.value.value():02X}"
        settings = TextureEditorToolSettings(tool="paint", color_hex="#" + shade * 3,
            size=self.brush_size.value(), hardness=self.hardness.value(), opacity=self.opacity.value())
        width, height = self.document.width, self.document.height
        def stroke(_pixels, mask, channel):
            document = replace(self.document, width=mask.width, height=mask.height)
            points = [(x * mask.width / width, y * mask.height / height) for x, y in payload["points"]]
            scaled = replace(settings, size=max(1, round(settings.size * mask.width / width)))
            result = apply_texture_editor_stroke(document, {"mask": self._pixels(channel)}, scaled, points)
            return result["mask"][..., 0].tobytes()
        self._edit(stroke)

    def _gradient(self):
        def gradient(_pixels, mask, _channel):
            vertical = self.gradient_direction.currentIndex() == 1
            line = np.rint(np.linspace(0, 255, mask.height if vertical else mask.width)).astype(np.uint8)
            return np.broadcast_to(line[:, None] if vertical else line, (mask.height, mask.width)).tobytes()
        self._edit(gradient)

    def _move_history(self, direction):
        if self._io_active:
            return
        self._history_index = max(0, min(len(self._history) - 1, self._history_index + direction))
        self._refresh()

    def _cancel_io(self, *_args):
        if self._io_active and self._cancel_file_task is not None:
            self._cancel_file_task()
        self._io_active = False

    def _file_task(self, task, apply_result):
        if self._run_file_task is None or self._io_active:
            return
        from shiboken6 import isValid
        controls = (self.canvas, self.target, self.fill_button, self.invert_button, self.gradient_button,
                    self.reset_button, self.undo_button, self.redo_button, self.import_button, self.export_button,
                    self.buttons.button(QDialogButtonBox.StandardButton.Apply))
        self._io_active = True
        for control in controls:
            control.setEnabled(False)
        self.message.setText("Preparing mask file…")
        def finish(result=None, error=None):
            if not isValid(self) or not self._io_active:
                return
            self._io_active = False
            for control in controls:
                control.setEnabled(True)
            if error is None:
                apply_result(result)
                self._refresh()
            else:
                self._refresh()
                self.message.setText(error)
        if not self._run_file_task(task, lambda result: finish(result), lambda error: finish(error=error)):
            finish(error="Another material operation is still finishing. Try again shortly.")

    def _import_mask(self):
        path, _ = QFileDialog.getOpenFileName(self, "Import mask", "", "Mask PNG (*.png)")
        if not path:
            return
        if self._dual and self.target.currentIndex() == 2 and (
                self._initial.width, self._initial.height) != (self._surface_initial.width, self._surface_initial.height):
            self.message.setText("These masks have different resolutions. Import each target separately.")
            return
        from cdmw.services.transparency_masks import read_mask_image
        size, channel = (self.document.width, self.document.height), self.import_channel.currentText()
        self._file_task(lambda _log, stop: read_mask_image(path, size, channel, stop_event=stop),
                        lambda mask: self._remember(mask.pixels))

    def _export_mask(self):
        if self._dual and self.target.currentIndex() == 2:
            self.message.setText("Select Colour coverage or Surface response to export its independent mask.")
            return
        path, _ = QFileDialog.getSaveFileName(self, "Export mask", "mask.png", "Mask PNG (*.png)")
        if not path:
            return
        from cdmw.services.transparency_masks import write_mask_image
        mask = TransparencyMask(self.document.width, self.document.height, self._pixels()[..., 0].tobytes())
        self._file_task(lambda _log, stop: write_mask_image(path, mask, stop_event=stop), lambda _result: None)

    def _zoom(self, delta, _x, _y):
        self.canvas.set_zoom_factor(max(.05, min(16., self.canvas._display_scale * (1.25 if delta > 0 else .8))))

    def _apply(self):
        mask = TransparencyMask(self._initial.width, self._initial.height, self._history[self._history_index])
        if self._dual:
            # Apply only edited targets; opening or switching does not author an
            # otherwise inherited channel. History restores both targets at once.
            changes = {}
            if self._edited_history[self._history_index][0]:
                changes["transparency_mask"] = TransparencyMask(self._initial.width, self._initial.height, self._history[self._history_index])
            if self._edited_history[self._history_index][1]:
                changes["surface_response_mask"] = TransparencyMask(self._surface_initial.width, self._surface_initial.height, self._surface_history[self._history_index])
            mask = replace(self._controls, **changes)
        elif self._mode == "cutout" and self._controls is not None:
            mask = replace(self._controls, cutout_mask=mask)
        try:
            self._apply_mask(mask)
        except ValueError as exc:
            self.message.setText(str(exc))
            return
        self.accept()
