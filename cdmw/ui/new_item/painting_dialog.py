"""Create New Item's painting template: pictures of your own as new paintings in a DMM mod.

The dialog collects one or more paintings (a frame, a picture, how it fits, a name and a
description in each language), then the controller's worker plans and writes them with
:mod:`cdmw.services.new_item_painting`. Reading the frames and building run off the UI
thread; the picture preview is made on the thread pool.

The dialog is built around the result (Fredric, 2026-11-17: the frame and the picture
were too small to see, and the log took most of the room). The frames are a list with
their game icons, the middle is the frame drawn to scale with the picture on its canvas,
and the build log folds away under one status line.
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable, Dict, List, Optional

from PySide6.QtCore import QObject, QRunnable, Qt, QThreadPool, QTimer, Signal
from PySide6.QtGui import QGuiApplication, QIcon, QImage, QPainter, QPixmap
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
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSplitter,
    QTabWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from cdmw.domain.new_item.rules import LOCALIZATION_LANGUAGES
from cdmw.ui.new_item.painting_preview import FrameList, PaintingFrameView, frame_colour
from cdmw.ui.new_item.panels_identity import LANGUAGE_LABELS

PICTURE_FILTER = "Pictures (*.png *.jpg *.jpeg *.bmp *.webp *.tga);;All files (*)"
#: The longest side of the picture preview when the frame's texture size is not known.
_PREVIEW_SIZE = 1600
#: The share of the screen's free area the dialog opens at, and the size it never opens below.
_SCREEN_SHARE = (0.8, 0.85)
_OPENING_MINIMUM = (900, 620)
#: The widest the dialog opens, as a multiple of its height: on an ultrawide screen the
#: extra width would only widen the side columns around the preview.
_MAX_ASPECT = 1.8
#: The splitter's first shares: frames, the preview, the painting's details.
_SPLIT_SHARES = (0.22, 0.52, 0.26)


class _PreviewSignals(QObject):
    ready = Signal(int, QImage, str)


class _PreviewJob(QRunnable):
    """The picture as the frame's canvas will show it, made off the UI thread.

    Cropped or padded to the canvas's shape, then sampled to the texels the canvas covers
    in the texture the build writes, so a small texture looks as soft here as it will in
    the game. Without a known texture it is only shrunk to `_PREVIEW_SIZE`."""

    def __init__(self, token: int, path: str, frame, fit: str, signals: _PreviewSignals) -> None:
        super().__init__()
        self.token, self.path, self.frame, self.fit, self.signals = token, path, frame, fit, signals

    def _texels(self):
        from cdmw.core.painting_picture import PaintingPictureError, plan_picture_texture

        canvas = getattr(self.frame, "canvas", None)
        size = getattr(self.frame, "texture_size", None)
        if canvas is None or size is None or not hasattr(canvas, "uv_rect"):
            return None
        try:
            x0, y0, x1, y1 = plan_picture_texture(size, canvas).rect
        except (PaintingPictureError, TypeError, ValueError):
            return None
        return x1 - x0, y1 - y0

    def run(self) -> None:
        from PIL import Image

        from cdmw.core.painting_picture import PaintingPictureError, load_picture, shape_picture

        try:
            shaped = shape_picture(load_picture(self.path), self.frame.canvas.aspect, self.fit)
            texels = self._texels()
            if texels is not None:
                shaped = shaped.resize(texels, Image.Resampling.LANCZOS)
            else:
                shaped.thumbnail((_PREVIEW_SIZE, _PREVIEW_SIZE))
            data = shaped.convert("RGBA").tobytes("raw", "RGBA")
            image = QImage(data, shaped.width, shaped.height, shaped.width * 4, QImage.Format.Format_RGBA8888).copy()
            self.signals.ready.emit(self.token, image, "")
        except PaintingPictureError as exc:
            self.signals.ready.emit(self.token, QImage(), str(exc))


def _new_painting() -> Dict[str, object]:
    return {"frame": "", "picture": "", "fit": "fill", "names": {}, "descriptions": {}}


def _frame_text(frame) -> str:
    """`0.86 x 1.38 m` over `picture 0.71 x 1.26 m`, for the frame list."""

    width, height = frame.size_m
    canvas_w, canvas_h = frame.canvas.size_m
    return f"{width:.2f} x {height:.2f} m\npicture {canvas_w:.2f} x {canvas_h:.2f} m"


def _default_viewport(parent: QWidget):
    """Create New Item's own viewport frame: it builds the package on its worker and
    starts the resident 3D preview only once it is on screen."""

    from cdmw.ui.new_item.item_preview import ItemPreviewFrame

    return ItemPreviewFrame(parent)


def _picture_stamp(path: str):
    """The picture file's change time and size, so a picture saved again is shown again."""

    try:
        stat = Path(path).stat()
    except OSError:
        return None
    return stat.st_mtime_ns, stat.st_size


def _square_icon(image: QImage) -> QIcon:
    """The icon centred on a transparent square, so every frame's text starts at one edge."""

    side = max(image.width(), image.height())
    square = QPixmap(side, side)
    square.fill(Qt.GlobalColor.transparent)
    painter = QPainter(square)
    painter.drawImage((side - image.width()) // 2, (side - image.height()) // 2, image)
    painter.end()
    return QIcon(square)


class PaintingDialog(QDialog):
    """Add pictures as new paintings: frame, picture, name and description, then Build mod."""

    def __init__(self, controller, parent: Optional[QWidget] = None, *,
                 viewport_factory: Optional[Callable[[QWidget], object]] = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("New painting")
        #: Makes the 3D view's viewport frame (an ItemPreviewFrame) when the 3D tab is first shown.
        self._viewport_factory = viewport_factory or _default_viewport
        self._viewport = None
        #: Viewport frames closed with the dialog; kept until their workers have ended.
        self._retired_viewports: List[object] = []
        self._viewport_token = None
        self.setObjectName("new_item_painting_dialog")
        self.setSizeGripEnabled(True)
        self._controller = controller
        self._frames: List[object] = []
        self._thumbnails: Dict[str, bytes] = {}
        self._icons: Dict[str, QImage] = {}
        self._paintings: List[Dict[str, object]] = [_new_painting()]
        self._current = 0
        self._language = "eng"
        self._syncing = False
        self._building = False
        self._sized = False
        self._preview_token = 0
        self._preview_signals = _PreviewSignals(self)
        self._preview_signals.ready.connect(self._show_preview)

        layout = QVBoxLayout(self)
        intro = QLabel(
            "Add your own pictures as new paintings. Each painting is a new item with its own housing object, "
            "written into a DMM mod folder; no painting of the game is replaced, and nothing is written into the game. "
            "Build more paintings into the same folder to keep them in one mod. Custom paintings are untested in the game.")
        intro.setObjectName("HintLabel")
        intro.setWordWrap(True)
        layout.addWidget(intro)

        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        self.splitter.setChildrenCollapsible(False)
        layout.addWidget(self.splitter, 1)
        self.splitter.addWidget(self._build_choices())
        self.splitter.addWidget(self._build_result())
        self.splitter.addWidget(self._build_details())
        for index, stretch in enumerate((0, 1, 0)):
            self.splitter.setStretchFactor(index, stretch)

        # One status line; the build log folds out under it when asked for.
        status_row = QHBoxLayout()
        self.status = QLabel("")
        self.status.setWordWrap(True)
        self.status.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        status_row.addWidget(self.status, 1)
        self.log_toggle = QToolButton()
        self.log_toggle.setObjectName("new_item_painting_log_toggle")
        self.log_toggle.setText("Build log")
        self.log_toggle.setCheckable(True)
        self.log_toggle.setChecked(False)
        self.log_toggle.setArrowType(Qt.ArrowType.RightArrow)
        self.log_toggle.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.log_toggle.setAutoRaise(True)
        self.log_toggle.toggled.connect(self._show_log)
        status_row.addWidget(self.log_toggle, 0, Qt.AlignmentFlag.AlignTop)
        layout.addLayout(status_row)
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumHeight(self.log.fontMetrics().height() * 8)
        self.log.setVisible(False)
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
        self._log_connected = True
        self._refresh_list()
        self._show_painting()
        self.reload_frames()

    # ------------------------------------------------------------------ layout

    def _build_choices(self) -> QWidget:
        """The paintings in this build, and the frames with their game icons."""

        choices = QWidget()
        left = QVBoxLayout(choices)
        left.setContentsMargins(0, 0, 0, 0)
        left.addWidget(QLabel("Paintings in this build:"))
        self.painting_list = QListWidget()
        self.painting_list.setObjectName("new_item_painting_list")
        self.painting_list.currentRowChanged.connect(self._select_painting)
        self.painting_list.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
        self.painting_list.setMaximumHeight(self.painting_list.fontMetrics().height() * 6)
        self.painting_list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.painting_list.setTextElideMode(Qt.TextElideMode.ElideMiddle)
        left.addWidget(self.painting_list)
        buttons = QHBoxLayout()
        self.add_button = QPushButton("Add painting")
        self.add_button.clicked.connect(self._add_painting)
        self.remove_button = QPushButton("Remove")
        self.remove_button.clicked.connect(self._remove_painting)
        buttons.addWidget(self.add_button)
        buttons.addWidget(self.remove_button)
        buttons.addStretch(1)
        left.addLayout(buttons)
        left.addWidget(QLabel("Frame:"))
        self.frame = FrameList()
        self.frame.setToolTip("The frame decides the painting's size. Each is a frame a painting of the game uses; its mesh is shared, not copied.")
        self.frame.currentIndexChanged.connect(self._frame_changed)
        left.addWidget(self.frame, 1)
        choices.setMinimumWidth(200)
        return choices

    def _build_result(self) -> QWidget:
        """The result: the frame to scale with the picture on its canvas."""

        result = QWidget()
        middle = QVBoxLayout(result)
        middle.setContentsMargins(0, 0, 0, 0)
        self.preview_tabs = QTabWidget()
        self.preview_tabs.setObjectName("new_item_painting_preview_tabs")
        self.preview = PaintingFrameView()
        self.preview.clear_frame("Reading the frames...")
        self.preview_tabs.addTab(self.preview, "Front view")
        self.viewport_page = QWidget()
        self.viewport_page.setObjectName("new_item_painting_3d")
        viewport_layout = QVBoxLayout(self.viewport_page)
        viewport_layout.setContentsMargins(4, 4, 4, 4)
        viewport_row = QHBoxLayout()
        self.viewport_status = QLabel("The frame's mesh with your picture on its canvas, as the game's files will have it.")
        self.viewport_status.setObjectName("HintLabel")
        self.viewport_status.setWordWrap(True)
        viewport_row.addWidget(self.viewport_status, 1)
        self.reset_view_button = QPushButton("Reset view")
        self.reset_view_button.clicked.connect(self._reset_view)
        self.reset_view_button.setEnabled(False)
        viewport_row.addWidget(self.reset_view_button, 0, Qt.AlignmentFlag.AlignTop)
        viewport_layout.addLayout(viewport_row)
        self.viewport_busy = QProgressBar()
        self.viewport_busy.setRange(0, 0)
        self.viewport_busy.setTextVisible(False)
        self.viewport_busy.setFixedHeight(6)
        self.viewport_busy.hide()
        viewport_layout.addWidget(self.viewport_busy)
        self._viewport_slot = QVBoxLayout()
        viewport_layout.addLayout(self._viewport_slot, 1)
        self.preview_tabs.addTab(self.viewport_page, "3D view")
        self.preview_tabs.currentChanged.connect(self._preview_tab_changed)
        middle.addWidget(self.preview_tabs, 1)
        self.frame_info = QLabel("Reading the frames...")
        self.frame_info.setObjectName("HintLabel")
        self.frame_info.setWordWrap(True)
        middle.addWidget(self.frame_info)
        result.setMinimumWidth(280)
        return result

    def _build_details(self) -> QWidget:
        """The painting's picture and texts, and the mod it goes into."""

        details = QWidget()
        right = QVBoxLayout(details)
        right.setContentsMargins(0, 0, 0, 0)
        editor = QGroupBox("Painting")
        form = QFormLayout(editor)
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
        self.description.setMaximumHeight(self.description.fontMetrics().height() * 6)
        self.description.textChanged.connect(self._description_edited)
        form.addRow("Description:", self.description)
        right.addWidget(editor)
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
        right.addWidget(output)
        right.addStretch(1)
        scroll = QScrollArea()
        scroll.setObjectName("new_item_painting_details")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setWidget(details)
        scroll.setMinimumWidth(260)
        return scroll

    def _fit_to_screen(self) -> None:
        """Open at a share of the screen's free area, in logical pixels, so 96 dpi and
        150% screens both get a dialog of the same proportions; the preview takes what
        is left once the frames and the details have their room."""

        screen = self.screen() or QGuiApplication.primaryScreen()
        if screen is None:
            return
        area = screen.availableGeometry()
        width = min(area.width(), max(_OPENING_MINIMUM[0], int(area.width() * _SCREEN_SHARE[0])))
        height = min(area.height(), max(_OPENING_MINIMUM[1], int(area.height() * _SCREEN_SHARE[1])))
        width = min(width, max(_OPENING_MINIMUM[0], int(height * _MAX_ASPECT)))
        self.resize(width, height)
        anchor = self.parentWidget().window().frameGeometry().center() if self.parentWidget() is not None else area.center()
        left = min(max(area.left(), anchor.x() - width // 2), area.right() - width + 1)
        top = min(max(area.top(), anchor.y() - height // 2), area.bottom() - height + 1)
        self.move(left, top)
        self.splitter.setSizes([int(width * share) for share in _SPLIT_SHARES])

    def _show_log(self, shown: bool) -> None:
        self.log.setVisible(bool(shown))
        self.log_toggle.setArrowType(Qt.ArrowType.DownArrow if shown else Qt.ArrowType.RightArrow)

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
        self._icons = {}
        self._set_building(False)
        self._syncing = True
        self.frame.clear()
        for frame in self._frames:
            icon = self._icon_of(frame.mesh)
            self.frame.add_frame(_frame_text(frame), frame.mesh, _square_icon(icon) if not icon.isNull() else None,
                                 frame.label)
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
        self.preview.clear_frame("")
        self._say(message, True)

    def _icon_of(self, mesh: str) -> QImage:
        icon = self._icons.get(mesh)
        if icon is None:
            icon = QImage()
            if mesh in self._thumbnails:
                icon.loadFromData(self._thumbnails[mesh], "PNG")
            self._icons[mesh] = icon
        return icon

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
        if frame is None:
            message = "Choose the frame; it decides the painting's size." if self._frames else ""
            self.frame_info.setText(message)
            self.preview.clear_frame(message if self._frames else self.preview.message.text())
            return
        self.preview.set_frame(frame.size_m, frame.canvas.size_m, getattr(frame, "canvas_box", ()),
                               frame_colour(self._icon_of(frame.mesh)))
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
        self.frame.set_current_frame_row(self.frame.findData(painting["frame"]))
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
        self._request_front_view()
        self._request_viewport()

    def _request_front_view(self) -> None:
        painting = self._paintings[self._current]
        frame = self._frame_of(str(painting["frame"]))
        self._preview_token += 1
        if frame is None:
            if self._frames:
                self.preview.clear_frame("Choose a frame to see how the picture fits.")
            return
        if not painting["picture"]:
            self.preview.clear_picture("No picture yet.")
            return
        self.preview.clear_picture("Preparing the preview...")
        QThreadPool.globalInstance().start(_PreviewJob(
            self._preview_token, str(painting["picture"]), frame, str(painting["fit"]), self._preview_signals))

    def _show_preview(self, token: int, image: QImage, message: str) -> None:
        if token != self._preview_token:
            return
        if message:
            self.preview.clear_picture(message)
            return
        self.preview.set_picture(image)

    # ------------------------------------------------------------------ 3D view

    def _viewport_shown(self) -> bool:
        return self.isVisible() and self.preview_tabs.currentWidget() is self.viewport_page

    def _preview_tab_changed(self, _index: int) -> None:
        self._request_viewport()

    def _ensure_viewport(self):
        if self._viewport is not None:
            return self._viewport
        try:
            viewport = self._viewport_factory(self.viewport_page)
        except Exception as exc:  # noqa: BLE001 - the 3D view is optional; the rest of the dialog works
            self._viewport_failed(None, f"The 3D view is not available here: {exc}")
            return None
        gizmo = getattr(viewport, "gizmo_visible", None)
        if gizmo is not None:
            gizmo.hide()  # nothing here is placed or moved
        viewport.ready.connect(lambda shown=viewport: self._viewport_ready(shown))
        viewport.failed.connect(lambda message, shown=viewport: self._viewport_failed(shown, message))
        viewport.status_changed.connect(lambda message, shown=viewport: self._viewport_progress(shown, message))
        self._viewport_slot.addWidget(viewport, 1)
        self._viewport = viewport
        return viewport

    def _request_viewport(self) -> None:
        """Show the current painting in the 3D view. Only while the 3D tab is on screen:
        the package is built on the viewport frame's worker, so nothing heavy runs here."""

        if not self._viewport_shown():
            return
        painting = self._paintings[self._current]
        frame = self._frame_of(str(painting["frame"]))
        if frame is None:
            self._viewport_token = None
            if self._viewport is not None:
                self._viewport.show(None)
            self._set_viewport_busy(False, "Choose a frame to see it in 3D." if self._frames else "Reading the frames...")
            return
        make_source = getattr(self._controller, "painting_preview_source", None)
        picture = str(painting["picture"] or "")
        source = make_source(frame, picture, str(painting["fit"])) if callable(make_source) else None
        if source is None:
            self._set_viewport_busy(False, "The 3D view needs the game's archives; read them in Create New Item first.")
            return
        viewport = self._ensure_viewport()
        if viewport is None:
            return
        token = ("painting", frame.mesh, picture, _picture_stamp(picture) if picture else None, str(painting["fit"]))
        self._viewport_token = token
        self._set_viewport_busy(True, "Preparing the 3D view...")
        # The camera stays put while only the picture or its fit changes.
        viewport.show(source, token=token, framing_key=("painting", frame.mesh))
        # The viewport already shows this very package: it loads nothing and says nothing.
        showing = getattr(viewport, "showing", None)
        if callable(showing) and showing(token):
            self._viewport_ready(viewport)

    def _viewport_ready(self, viewport) -> None:
        if viewport is not self._viewport:
            return
        picture = str(self._paintings[self._current]["picture"] or "")
        self.reset_view_button.setEnabled(True)
        self._set_viewport_busy(False, "Drag to turn the painting, scroll to zoom." if picture else
                                "The frame with the game's own picture; choose a picture to see yours on it.")

    def _viewport_failed(self, viewport, message: str) -> None:
        if viewport is not None and viewport is not self._viewport:
            return
        self._set_viewport_busy(False, str(message or "The 3D view could not be shown."))
        self.viewport_status.setProperty("severity", "error")

    def _viewport_progress(self, viewport, message: str) -> None:
        if viewport is self._viewport and message and not self.viewport_busy.isHidden():
            self.viewport_status.setText(message)

    def _set_viewport_busy(self, busy: bool, message: str) -> None:
        self.viewport_busy.setVisible(bool(busy))
        self.viewport_status.setText(message)
        self.viewport_status.setProperty("severity", "")

    def _reset_view(self) -> None:
        if self._viewport is not None:
            self._viewport.fit_view()

    def viewport_busy_now(self) -> bool:
        """Whether the 3D view is still being prepared."""
        return not self.viewport_busy.isHidden()

    def _retire_viewport(self) -> None:
        """Stop the 3D view with the dialog; the next opening starts a new one."""
        viewport, self._viewport = self._viewport, None
        self._viewport_token = None
        if viewport is None:
            return
        try:
            viewport.request_shutdown()
        except Exception:  # noqa: BLE001 - a frame already gone has nothing to stop
            pass
        viewport.hide()
        self._viewport_slot.removeWidget(viewport)
        self._retired_viewports.append(viewport)
        self.reset_view_button.setEnabled(False)
        self._set_viewport_busy(False, "")

    def iter_shutdown_workers(self):
        """The 3D view's package builds and package clean-ups, for CDMW's exit."""
        for viewport in (self._viewport, *self._retired_viewports):
            if viewport is not None:
                yield from viewport.iter_shutdown_workers()

    def request_shutdown(self) -> None:
        self._retire_viewport()

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

    def showEvent(self, event) -> None:  # noqa: N802 - Qt API
        # New painting... opens this dialog again after Close, which let the log go.
        if not self._log_connected:
            self._controller.log_message.connect(self._log_line)
            self._log_connected = True
        if not self._sized:
            self._sized = True
            self._fit_to_screen()
        super().showEvent(event)
        # Opened again on the 3D tab: show the painting once the dialog is laid out.
        QTimer.singleShot(0, self._request_viewport)

    def done(self, result: int) -> None:
        self._retire_viewport()
        if self._building:
            self._controller.cancel_operation("paintings")
        if self._log_connected:
            self._log_connected = False
            try:
                self._controller.log_message.disconnect(self._log_line)
            except (RuntimeError, TypeError):
                pass
        super().done(result)


__all__ = ["PaintingDialog"]
