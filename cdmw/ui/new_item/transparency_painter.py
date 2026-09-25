"""Focused greyscale painter using the Texture workspace's canvas and brushes."""
import numpy as np

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (QComboBox, QDialog, QDialogButtonBox, QFormLayout, QGridLayout,
                              QLabel, QPushButton, QScrollArea, QSpinBox, QVBoxLayout)

from cdmw.domain.textures.editor_brush import apply_texture_editor_stroke
from cdmw.domain.textures.transparency_mask import TransparencyMask
from cdmw.models import TextureEditorDocument, TextureEditorLayer, TextureEditorToolSettings
from cdmw.ui.texture_workflow.editor_canvas import TextureEditorCanvas


class TransparencyPaintDialog(QDialog):
    def __init__(self, prepared, apply_mask, *, part, glass=False, parent=None):
        super().__init__(parent)
        self.setProperty("cdmwNativeCanvasDialog", True)
        self.setWindowTitle(f"Paint transparency — {part}")
        self.setWindowModality(Qt.WindowModality.WindowModal)
        self.resize(920, 700)
        self._apply_mask = apply_mask
        self._initial = prepared.mask
        self._history = [prepared.mask.pixels]
        self._history_index = 0
        self._history_limit = max(2, min(40, 64 * 1024 * 1024 // len(prepared.mask.pixels)))
        self._reference = np.frombuffer(prepared.reference_rgba, dtype=np.uint8).reshape(
            prepared.mask.height, prepared.mask.width, 4)
        self.document = TextureEditorDocument("Transparency mask", prepared.mask.width, prepared.mask.height,
            active_layer_id="mask", layers=(TextureEditorLayer("mask", "Mask", "", alpha_locked=True),))
        layout = QVBoxLayout(self)
        if glass:
            note = QLabel("Paint lighter for more transparency and darker for less. White reduces absorption; black uses the selected absorption strength. Reflections can remain.")
        else:
            note = QLabel("Paint lighter for more transparency and darker for less. White reduces colour coverage; black uses the selected Colour mixing. Surface detail and shine are controlled separately.")
        note.setWordWrap(True)
        layout.addWidget(note)
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
        self.reset_button.clicked.connect(lambda: self._remember(self._initial.pixels))
        self.fit_button = QPushButton("Fit")
        for button in (self.more, self.less, self.undo_button, self.redo_button, self.reset_button, self.fit_button):
            button.setAutoDefault(False)
        actions.addWidget(self.more, 0, 0, 1, 2)
        actions.addWidget(self.less, 0, 2, 1, 2)
        for column, button in enumerate((self.undo_button, self.redo_button, self.reset_button, self.fit_button)):
            actions.addWidget(button, 1, column)
        layout.addLayout(actions)
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
        self._undo_shortcut = QShortcut(QKeySequence.StandardKey.Undo, self)
        self._undo_shortcut.activated.connect(lambda: self._move_history(-1))
        self._redo_shortcut = QShortcut(QKeySequence.StandardKey.Redo, self)
        self._redo_shortcut.activated.connect(lambda: self._move_history(1))
        self._refresh()

    def _brush_visuals(self, *_args):
        self.canvas.set_brush_visual_state(hardness=self.hardness.value(), tip="round", roundness=100,
                                          angle_degrees=0, pattern="solid")

    def _pixels(self):
        plane = np.frombuffer(self._history[self._history_index], dtype=np.uint8).reshape(
            self.document.height, self.document.width)
        rgba = np.empty((*plane.shape, 4), dtype=np.uint8)
        rgba[..., :3], rgba[..., 3] = plane[..., None], 255
        return rgba

    def _refresh(self, *_args):
        image = self._pixels()
        if self.view.currentIndex() == 0:
            weight = image[..., :1].astype(np.float32) / 510.
            image[..., :3] = np.round(self._reference[..., :3] * (1. - weight) + np.array([255, 45, 20]) * weight).astype(np.uint8)
        self.canvas.set_rgba_images(image)
        self.undo_button.setEnabled(self._history_index > 0)
        self.redo_button.setEnabled(self._history_index + 1 < len(self._history))

    def _remember(self, pixels):
        if pixels == self._history[self._history_index]:
            return
        self._history = self._history[:self._history_index + 1] + [pixels]
        self._history = self._history[-self._history_limit:]
        self._history_index = len(self._history) - 1
        self._refresh()

    def _stroke(self, payload):
        if not isinstance(payload, dict) or not payload.get("points"):
            return
        shade = f"{self.value.value():02X}"
        settings = TextureEditorToolSettings(tool="paint", color_hex="#" + shade * 3,
            size=self.brush_size.value(), hardness=self.hardness.value(), opacity=self.opacity.value())
        result = apply_texture_editor_stroke(self.document, {"mask": self._pixels()}, settings, payload["points"])
        self._remember(result["mask"][..., 0].tobytes())

    def _move_history(self, direction):
        self._history_index = max(0, min(len(self._history) - 1, self._history_index + direction))
        self._refresh()

    def _zoom(self, delta, _x, _y):
        self.canvas.set_zoom_factor(max(.05, min(16., self.canvas._display_scale * (1.25 if delta > 0 else .8))))

    def _apply(self):
        mask = TransparencyMask(self.document.width, self.document.height, self._history[self._history_index])
        try:
            self._apply_mask(mask)
        except ValueError as exc:
            self.message.setText(str(exc))
            return
        self.accept()
