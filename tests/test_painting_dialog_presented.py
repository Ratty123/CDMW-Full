"""New painting as Create New Item's page presents it: the Front view and the frame thumbnails.

Fredric (2026-11-17), in the built app: the Front view showed no frame and no picture,
only its hint, and the frame list showed no thumbnails, only truncated sizes. The page
is drawn from a description of the Qt widgets; the Front view draws in paintEvent and
the thumbnails are the list items' icons, and neither was in the description.
"""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PySide6.QtCore import QThreadPool, Qt  # noqa: E402
from PySide6.QtGui import QColor, QImage  # noqa: E402
from PySide6.QtWidgets import QApplication, QWidget  # noqa: E402

from cdmw.ui.new_item.rust_ui_document import PresentationDocument  # noqa: E402
from cdmw.core.painting_picture import CanvasMapping  # noqa: E402
from cdmw.services.new_item_painting import PaintingFrameCatalogue  # noqa: E402
from tests.test_new_item_painting_dialog import LARGE, SMALL, Controller, _png, frame  # noqa: E402

_APPLICATION = None


def _app():
    global _APPLICATION
    _APPLICATION = QApplication.instance() or QApplication([])
    return _APPLICATION


def _find(node, name):
    if node.get("name") == name:
        return node
    for child in node.get("children", []):
        found = _find(child, name)
        if found is not None:
            return found
    return None


def _labels(node):
    found = [node["props"].get("text", "")] if node.get("kind") == "label" else []
    for child in node.get("children", []):
        found.extend(_labels(child))
    return found


def _image(snapshot, identifier):
    asset = snapshot["assets"][identifier]
    image = QImage.fromData(bytes.fromhex(asset["png_hex"]), "PNG")
    assert (image.width(), image.height()) == (asset["width"], asset["height"])
    return image


class FramedController(Controller):
    """Frames whose canvas is smaller than the frame, so the frame shows round the picture."""

    def start_painting_frames(self, on_done, on_error):
        frames = []
        for mesh, size, canvas in ((SMALL, (0.5, 0.4), (0.4, 0.3)), (LARGE, (1.5, 2.0), (1.1, 1.6))):
            shown = frame(mesh, size)
            shown.canvas = CanvasMapping(material="pic", uv_rect=(0, 0, 1, 1), size_m=canvas, vertex_count=4)
            frames.append(shown)
        on_done((PaintingFrameCatalogue(frames=tuple(frames), left_out=()), self.thumbnails))
        return True


@pytest.fixture
def presented():
    """The dialog shown as the page shows it: open in Qt, but not on screen."""

    _app()
    from cdmw.ui.new_item.painting_dialog import PaintingDialog

    host = QWidget()
    controller = FramedController(thumbnails={SMALL: _png(64, 48, 0xFF3366CC), LARGE: _png(40, 60, 0xFF8B5A2B)})
    dialog = PaintingDialog(controller, host)
    dialog.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
    dialog.show()
    dialog.resize(1200, 760)
    _app().processEvents()
    document = PresentationDocument()

    def snapshot():
        _app().processEvents()
        state = document.snapshot(QWidget(), dialogs=(dialog,))
        return state, state["dialogs"][0]

    yield dialog, snapshot
    QThreadPool.globalInstance().waitForDone(5000)
    dialog.hide()
    dialog.deleteLater()
    host.deleteLater()


def test_the_front_view_is_presented_as_its_drawing_of_the_frame(presented):
    dialog, snapshot = presented
    state, window = snapshot()
    front = _find(window, "new_item_painting_preview")
    assert front["kind"] == "picture"
    # Without a frame there is nothing drawn but the hint, which stays a label over it.
    assert dialog.preview.message.text() and _labels(front) == [dialog.preview.message.text()]

    dialog.frame.set_current_frame_row(1)
    state, window = snapshot()
    front = _find(window, "new_item_painting_preview")
    assert front["kind"] == "picture"
    assert front["props"]["min_height"] == 220 and front["props"]["width"] == dialog.preview.width()
    image = _image(state, front["props"]["image"])
    scale = image.width() / dialog.preview.width()
    middle = dialog.preview.canvas_rect().center()
    canvas = image.pixelColor(int(middle.x() * scale), int(middle.y() * scale))
    assert (canvas.red(), canvas.green(), canvas.blue()) == (222, 214, 198)  # the empty canvas
    frame = dialog.preview.frame_rect()
    edge = image.pixelColor(int((frame.left() + 2) * scale), int(frame.center().y() * scale))
    assert edge.alpha() == 255 and edge != canvas  # the frame round it
    corner = image.pixelColor(1, 1)
    assert corner.alpha() == 0  # the page's own background shows round the frame

    picture = QImage(40, 60, QImage.Format.Format_ARGB32)
    picture.fill(QColor(200, 30, 40))
    dialog.preview.set_picture(picture)
    state, window = snapshot()
    shown = _find(window, "new_item_painting_preview")
    assert shown["props"]["image"] != front["props"]["image"]
    pixel = _image(state, shown["props"]["image"]).pixelColor(int(middle.x() * scale), int(middle.y() * scale))
    assert (pixel.red(), pixel.green(), pixel.blue()) == (200, 30, 40)


def test_an_unchanged_front_view_is_not_drawn_again(presented, monkeypatch):
    dialog, snapshot = presented
    dialog.frame.set_current_frame_row(0)
    paints = []
    original = PresentationDocument._render

    def counted(widget, scale):
        paints.append(widget)
        return original(widget, scale)

    monkeypatch.setattr(PresentationDocument, "_render", staticmethod(counted))
    first, window = snapshot()
    drawn = len(paints)
    assert drawn >= 1
    for _ in range(3):
        again, window = snapshot()
    assert len(paints) == drawn
    assert _find(window, "new_item_painting_preview")["props"]["image"] in again["assets"]
    dialog.frame.set_current_frame_row(1)  # another frame: drawn again
    snapshot()
    assert len(paints) > drawn


def test_the_frame_list_rows_carry_their_thumbnails_at_the_list_s_icon_size(presented):
    dialog, snapshot = presented
    state, window = snapshot()
    frames = _find(window, "new_item_painting_frame")
    assert frames["kind"] == "table"
    assert frames["props"]["icon_size"] == [72, 72]
    rows = frames["props"]["rows"]
    assert [row["cells"][0]["text"].splitlines()[0] for row in rows] == ["0.50 x 0.40 m", "1.50 x 2.00 m"]
    assert all(len(row["cells"][0]["text"].splitlines()) == 2 for row in rows)  # size and picture area
    thumbnails = [_image(state, row["cells"][0]["image"]) for row in rows]
    ratio = dialog.frame.devicePixelRatioF()
    # At the list's icon size, centred and never enlarged, as Qt draws them.
    assert all((image.width(), image.height()) == (round(72 * ratio), round(72 * ratio)) for image in thumbnails)
    # Each row its own frame's icon: blue for the small frame, brown for the large one.
    middle = [image.pixelColor(image.width() // 2, image.height() // 2) for image in thumbnails]
    assert (middle[0].red(), middle[0].green(), middle[0].blue()) == (0x33, 0x66, 0xCC)
    assert (middle[1].red(), middle[1].green(), middle[1].blue()) == (0x8B, 0x5A, 0x2B)
    # The painting list sets no icon size, so it sends no icons.
    assert "icon_size" not in _find(window, "new_item_painting_list")["props"]
