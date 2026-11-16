"""Create New Item's painting template: pictures of your own as new paintings in a DMM mod.

The dialog collects one or more paintings (a frame, a picture, how it fits, a name and a
description in each language), then the controller's worker plans and writes them with
:mod:`cdmw.services.new_item_painting`. Reading the frames and building run off the UI
thread; the picture preview is made on the thread pool.
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Optional

from PySide6.QtCore import QObject, QRunnable, Qt, QThreadPool, Signal
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from cdmw.domain.new_item.rules import LOCALIZATION_LANGUAGES
from cdmw.ui.new_item.panels_identity import LANGUAGE_LABELS

PICTURE_FILTER = "Pictures (*.png *.jpg *.jpeg *.bmp *.webp *.tga);;All files (*)"
_PREVIEW_SIZE = 220


class _PreviewSignals(QObject):
    ready = Signal(int, QImage, str)


class _PreviewJob(QRunnable):
    """The picture cropped or padded to the canvas shape, small, made off the UI thread."""

    def __init__(self, token: int, path: str, aspect: float, fit: str, signals: _PreviewSignals) -> None:
        super().__init__()
        self.token, self.path, self.aspect, self.fit, self.signals = token, path, aspect, fit, signals

    def run(self) -> None:
        from cdmw.core.painting_picture import PaintingPictureError, load_picture, shape_picture

        try:
            shaped = shape_picture(load_picture(self.path), self.aspect, self.fit)
            shaped.thumbnail((_PREVIEW_SIZE, _PREVIEW_SIZE))
            data = shaped.convert("RGBA").tobytes("raw", "RGBA")
            image = QImage(data, shaped.width, shaped.height, shaped.width * 4, QImage.Format.Format_RGBA8888).copy()
            self.signals.ready.emit(self.token, image, "")
        except PaintingPictureError as exc:
            self.signals.ready.emit(self.token, QImage(), str(exc))


def _new_painting() -> Dict[str, object]:
    return {"frame": "", "picture": "", "fit": "fill", "names": {}, "descriptions": {}}


class PaintingDialog(QDialog):
    """Add pictures as new paintings: frame, picture, name and description, then Build mod."""

    def __init__(self, controller, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("New painting")
        self.setObjectName("new_item_painting_dialog")
        self._controller = controller
        self._frames: List[object] = []
        self._thumbnails: Dict[str, bytes] = {}
        self._paintings: List[Dict[str, object]] = [_new_painting()]
        self._current = 0
        self._language = "eng"
        self._syncing = False
        self._building = False
        self._preview_token = 0
        self._preview_signals = _PreviewSignals(self)
        self._preview_signals.ready.connect(self._show_preview)

        layout = QVBoxLayout(self)
        intro = QLabel(
            "Add your own pictures as new paintings. Each painting is a new item with its own housing object, "
            "written into a DMM mod folder; no painting of the game is replaced, and nothing is written into the game. "
            "Build more paintings into the same folder to keep them in one mod. Custom paintings are untested in the game.")
        intro.setWordWrap(True)
        layout.addWidget(intro)

        body = QHBoxLayout()
        left = QVBoxLayout()
        left.addWidget(QLabel("Paintings in this build:"))
        self.painting_list = QListWidget()
        self.painting_list.setObjectName("new_item_painting_list")
        self.painting_list.currentRowChanged.connect(self._select_painting)
        left.addWidget(self.painting_list, 1)
        buttons = QHBoxLayout()
        self.add_button = QPushButton("Add painting")
        self.add_button.clicked.connect(self._add_painting)
        self.remove_button = QPushButton("Remove")
        self.remove_button.clicked.connect(self._remove_painting)
        buttons.addWidget(self.add_button)
        buttons.addWidget(self.remove_button)
        left.addLayout(buttons)
        body.addLayout(left, 1)

        editor = QGroupBox("Painting")
        form = QFormLayout(editor)
        self.frame = QComboBox()
        self.frame.setObjectName("new_item_painting_frame")
        self.frame.setToolTip("The frame decides the painting's size. Each is a frame a painting of the game uses; its mesh is shared, not copied.")
        self.frame.currentIndexChanged.connect(self._frame_changed)
        form.addRow("Frame:", self.frame)
        frame_row = QHBoxLayout()
        self.frame_thumbnail = QLabel()
        self.frame_thumbnail.setFixedSize(96, 96)
        self.frame_thumbnail.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.frame_info = QLabel("Reading the frames...")
        self.frame_info.setWordWrap(True)
        frame_row.addWidget(self.frame_thumbnail)
        frame_row.addWidget(self.frame_info, 1)
        form.addRow("", frame_row)
        picture_row = QHBoxLayout()
        self.picture = QLineEdit()
        self.picture.setReadOnly(True)
        self.picture.setPlaceholderText("PNG or JPG")
        self.choose_picture = QPushButton("Choose picture...")
        self.choose_picture.clicked.connect(self._choose_picture)
        picture_row.addWidget(self.picture, 1)
        picture_row.addWidget(self.choose_picture)
        form.addRow("Picture:", picture_row)
        self.fit = QComboBox()
        self.fit.addItem("Fill the canvas (crop the edges)", "fill")
        self.fit.addItem("Show the whole picture (add bands)", "whole")
        self.fit.currentIndexChanged.connect(self._fit_changed)
        form.addRow("Fit:", self.fit)
        self.preview = QLabel("No picture yet.")
        self.preview.setMinimumSize(_PREVIEW_SIZE, _PREVIEW_SIZE // 2)
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview.setWordWrap(True)
        form.addRow("Preview:", self.preview)
        self.language = QComboBox()
        for code in LOCALIZATION_LANGUAGES:
            self.language.addItem(f"{LANGUAGE_LABELS.get(code, code)} ({code})", code)
        self.language.currentIndexChanged.connect(self._language_changed)
        form.addRow("Language:", self.language)
        self.name = QLineEdit()
        self.name.setPlaceholderText("Shown in game; English is required, other languages fall back to it")
        self.name.textEdited.connect(self._name_edited)
        form.addRow("Name:", self.name)
        self.description = QPlainTextEdit()
        self.description.setPlaceholderText("Shown in game; empty uses the English text, or the name")
        self.description.setMaximumHeight(90)
        self.description.textChanged.connect(self._description_edited)
        form.addRow("Description:", self.description)
        body.addWidget(editor, 2)
        layout.addLayout(body, 1)

        output = QGroupBox("Mod")
        output_form = QFormLayout(output)
        self.mod_name = QLineEdit("Custom paintings")
        output_form.addRow("Mod name:", self.mod_name)
        folder_row = QHBoxLayout()
        self.folder = QLineEdit()
        self.folder.setPlaceholderText("An empty folder, or a painting mod built here before")
        self.choose_folder = QPushButton("Browse...")
        self.choose_folder.clicked.connect(self._choose_folder)
        folder_row.addWidget(self.folder, 1)
        folder_row.addWidget(self.choose_folder)
        output_form.addRow("Mod folder:", folder_row)
        layout.addWidget(output)

        self.status = QLabel("")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumHeight(140)
        layout.addWidget(self.log)
        self.button_box = QDialogButtonBox()
        self.build_button = self.button_box.addButton("Build mod", QDialogButtonBox.ButtonRole.AcceptRole)
        self.cancel_button = self.button_box.addButton("Cancel build", QDialogButtonBox.ButtonRole.ActionRole)
        self.close_button = self.button_box.addButton("Close", QDialogButtonBox.ButtonRole.RejectRole)
        self.build_button.clicked.connect(self._build)
        self.cancel_button.clicked.connect(lambda: self._controller.cancel_operation("paintings"))
        self.close_button.clicked.connect(self.reject)
        layout.addWidget(self.button_box)
        controller.log_message.connect(self._log_line)
        self._refresh_list()
        self._show_painting()
        self.reload_frames()

    def reload_frames(self) -> None:
        """Read the frames again (also when the dialog is opened again after a busy start)."""
        if self._frames:
            return
        self._set_building(True)
        if not self._controller.start_painting_frames(self._frames_ready, self._frames_failed):
            self._set_building(False)
            if not self.status.text():
                self._say("Create New Item is busy with another step; open New painting again when it finishes.", True)

    # ------------------------------------------------------------------ frames

    def _frames_ready(self, result) -> None:
        catalogue, thumbnails = result
        self._frames = list(catalogue.frames)
        self._thumbnails = dict(thumbnails)
        self._set_building(False)
        self._syncing = True
        self.frame.clear()
        self.frame.addItem("Choose a frame", "")
        for frame in self._frames:
            self.frame.addItem(frame.label, frame.mesh)
        self._syncing = False
        left_out = len(catalogue.left_out)
        if left_out:
            self._say(f"{len(self._frames)} frames found; {left_out} left out because CDMW cannot map their canvas.", False)
        else:
            self._say(f"{len(self._frames)} frames found.", False)
        self._show_painting()

    def _frames_failed(self, message: str) -> None:
        self._set_building(False)
        self.frame_info.setText("")
        self._say(message, True)

    def _frame_of(self, mesh: str):
        return next((frame for frame in self._frames if frame.mesh == mesh), None)

    def _frame_changed(self, _index: int) -> None:
        if self._syncing:
            return
        self._paintings[self._current]["frame"] = str(self.frame.currentData() or "")
        self._refresh_list()
        self._show_frame()
        self._request_preview()

    def _show_frame(self) -> None:
        frame = self._frame_of(str(self._paintings[self._current]["frame"]))
        pixmap = QPixmap()
        if frame is not None and frame.mesh in self._thumbnails:
            pixmap.loadFromData(self._thumbnails[frame.mesh], "PNG")
        self.frame_thumbnail.setPixmap(pixmap)
        if frame is None:
            self.frame_info.setText("Choose the frame; it decides the painting's size." if self._frames else "")
            return
        width, height = frame.texture_size
        self.frame_info.setText(
            f"Picture area {frame.canvas.size_m[0]:.2f} x {frame.canvas.size_m[1]:.2f} m. "
            f"Copied from {frame.source.name}; {frame.shipped_paintings} painting(s) of the game use this frame. "
            f"The picture is written as a {width} x {height} texture.")

    # ------------------------------------------------------------------ paintings

    def _title_of(self, index: int) -> str:
        painting = self._paintings[index]
        name = str(painting["names"].get("eng", "") or "").strip() or "Unnamed painting"
        frame = self._frame_of(str(painting["frame"]))
        return f"{index + 1}. {name}" + (f" ({frame.stem})" if frame is not None else "")

    def _refresh_list(self) -> None:
        self._syncing = True
        self.painting_list.clear()
        for index in range(len(self._paintings)):
            self.painting_list.addItem(self._title_of(index))
        self.painting_list.setCurrentRow(self._current)
        self._syncing = False
        self.remove_button.setEnabled(len(self._paintings) > 1 and not self._building)

    def _select_painting(self, row: int) -> None:
        if self._syncing or row < 0:
            return
        self._current = row
        self._show_painting()

    def _add_painting(self) -> None:
        self._paintings.append(_new_painting())
        self._current = len(self._paintings) - 1
        self._refresh_list()
        self._show_painting()

    def _remove_painting(self) -> None:
        if len(self._paintings) <= 1:
            return
        del self._paintings[self._current]
        self._current = min(self._current, len(self._paintings) - 1)
        self._refresh_list()
        self._show_painting()

    def _show_painting(self) -> None:
        painting = self._paintings[self._current]
        self._syncing = True
        index = self.frame.findData(painting["frame"])
        self.frame.setCurrentIndex(max(0, index))
        self.picture.setText(str(painting["picture"]))
        self.fit.setCurrentIndex(max(0, self.fit.findData(painting["fit"])))
        self.name.setText(str(painting["names"].get(self._language, "")))
        self.description.setPlainText(str(painting["descriptions"].get(self._language, "")))
        self._syncing = False
        self._show_frame()
        self._request_preview()

    def _choose_picture(self) -> None:
        start = str(self._paintings[self._current]["picture"] or "")
        path, _selected = QFileDialog.getOpenFileName(self, "Choose a picture for the painting", start, PICTURE_FILTER)
        if not path:
            return
        painting = self._paintings[self._current]
        painting["picture"] = path
        if not str(painting["names"].get("eng", "") or "").strip():
            painting["names"]["eng"] = Path(path).stem.replace("_", " ").strip()
        self._show_painting()
        self._refresh_list()

    def _fit_changed(self, _index: int) -> None:
        if self._syncing:
            return
        self._paintings[self._current]["fit"] = str(self.fit.currentData() or "fill")
        self._request_preview()

    def _language_changed(self, _index: int) -> None:
        self._language = str(self.language.currentData() or "eng")
        self._show_painting()

    def _name_edited(self, text: str) -> None:
        if self._syncing:
            return
        self._paintings[self._current]["names"][self._language] = text
        if self._language == "eng":
            item = self.painting_list.item(self._current)
            if item is not None:
                item.setText(self._title_of(self._current))

    def _description_edited(self) -> None:
        if self._syncing:
            return
        self._paintings[self._current]["descriptions"][self._language] = self.description.toPlainText()

    # ------------------------------------------------------------------ preview

    def _request_preview(self) -> None:
        painting = self._paintings[self._current]
        frame = self._frame_of(str(painting["frame"]))
        self._preview_token += 1
        if not painting["picture"]:
            self.preview.setPixmap(QPixmap())
            self.preview.setText("No picture yet.")
            return
        if frame is None:
            self.preview.setPixmap(QPixmap())
            self.preview.setText("Choose a frame to see how the picture fits.")
            return
        self.preview.setText("Preparing the preview...")
        QThreadPool.globalInstance().start(_PreviewJob(
            self._preview_token, str(painting["picture"]), frame.canvas.aspect, str(painting["fit"]), self._preview_signals))

    def _show_preview(self, token: int, image: QImage, message: str) -> None:
        if token != self._preview_token:
            return
        if message:
            self.preview.setPixmap(QPixmap())
            self.preview.setText(message)
            return
        self.preview.setText("")
        self.preview.setPixmap(QPixmap.fromImage(image))

    # ------------------------------------------------------------------ build

    def _choose_folder(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "Choose the mod folder", self.folder.text())
        if path:
            self.folder.setText(path)

    def painting_requests(self):
        """The paintings as service requests, in list order."""
        from cdmw.services.new_item_painting import PaintingRequest

        return tuple(PaintingRequest(frame=str(p["frame"]), picture=str(p["picture"]), fit=str(p["fit"]),
                                     names={k: v for k, v in dict(p["names"]).items() if str(v).strip()},
                                     descriptions={k: v for k, v in dict(p["descriptions"]).items() if str(v).strip()})
                     for p in self._paintings)

    def _build(self) -> None:
        folder = self.folder.text().strip()
        if not folder:
            self._say("Choose a folder for the mod.", True)
            return
        self.log.clear()
        self._set_building(True)
        if not self._controller.start_painting_build(self.painting_requests(), Path(folder), self.mod_name.text(),
                                                     self._built, self._build_failed):
            self._set_building(False)

    def _built(self, result) -> None:
        self._set_building(False)
        # Built paintings are in the mod now; building again must not write them twice.
        self._paintings = [_new_painting()]
        self._current = 0
        self._refresh_list()
        self._show_painting()
        for line in result.plan.summary_lines:
            self.log.appendPlainText(line)
        names = ", ".join(str(p.get("names", {}).get("eng") or p.get("internal_name")) for p in result.paintings)
        self._say(f"Wrote {len(result.paintings)} painting(s) to {result.export.package_root}: {names}. "
                  "Enable the folder in DMM. Custom paintings are untested in the game.", False)

    def _build_failed(self, message: str) -> None:
        self._set_building(False)
        self._say(message, True)

    def _set_building(self, building: bool) -> None:
        self._building = building
        for widget in (self.build_button, self.add_button, self.choose_picture, self.choose_folder, self.frame):
            widget.setEnabled(not building)
        self.cancel_button.setEnabled(building)
        self.remove_button.setEnabled(not building and len(self._paintings) > 1)

    def _say(self, message: str, error: bool) -> None:
        self.status.setText(message)
        self.status.setProperty("severity", "error" if error else "")

    def _log_line(self, message: str) -> None:
        if self._building:
            self.log.appendPlainText(str(message))

    def done(self, result: int) -> None:
        if self._building:
            self._controller.cancel_operation("paintings")
        try:
            self._controller.log_message.disconnect(self._log_line)
        except (RuntimeError, TypeError):
            pass
        super().done(result)


__all__ = ["PaintingDialog"]
