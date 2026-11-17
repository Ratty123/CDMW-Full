"""The New painting dialog: frames, several paintings, texts per language and the build request."""
from __future__ import annotations

import os
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PySide6.QtCore import QObject, QThreadPool, Signal  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from cdmw.core.painting_picture import CanvasMapping  # noqa: E402
from cdmw.services.new_item_painting import PaintingFrameCatalogue  # noqa: E402

_APPLICATION = None


def _app():
    global _APPLICATION
    _APPLICATION = QApplication.instance() or QApplication([])
    return _APPLICATION


def frame(mesh, size, canvas_box=()):
    return SimpleNamespace(
        mesh=mesh, stem=mesh.rsplit("/", 1)[-1][:-4], label=f"{mesh} frame", size_m=size, texture_size=(512, 256),
        canvas=CanvasMapping(material="pic", uv_rect=(0, 0, 1, 1), size_m=size, vertex_count=4),
        source=SimpleNamespace(name="Collection_Prop_Picture_0001"), shipped_paintings=3, canvas_box=canvas_box)


SMALL, LARGE = "object/a/small.pam", "object/a/large.pam"


class Controller(QObject):
    log_message = Signal(str)

    def __init__(self, *, busy=False, thumbnails=None):
        super().__init__()
        self.busy = busy
        self.builds = []
        self.cancelled = []
        self.thumbnails = dict(thumbnails or {})

    def start_painting_frames(self, on_done, on_error):
        if self.busy:
            return False
        on_done((PaintingFrameCatalogue(frames=(frame(SMALL, (0.5, 0.4)), frame(LARGE, (1.5, 2.0))),
                                        left_out=(("object/a/turned.pam", "no canvas"),)), self.thumbnails))
        return True

    def start_painting_build(self, requests, folder, title, on_done, on_error):
        self.builds.append((requests, folder, title))
        self.finish = on_done
        return True

    def cancel_operation(self, lane=""):
        self.cancelled.append(lane)
        return True


def _png(width, height, rgba=0xFF3366CC, margin=0):
    """PNG bytes of a `width` x `height` icon, with `margin` transparent pixels round it."""
    from PySide6.QtCore import QBuffer, QByteArray, QIODevice
    from PySide6.QtGui import QColor, QImage, QPainter

    icon = QImage(width + 2 * margin, height + 2 * margin, QImage.Format.Format_ARGB32)
    icon.fill(0)
    painter = QPainter(icon)
    painter.fillRect(margin, margin, width, height, QColor.fromRgba(rgba))
    painter.end()
    data = QByteArray()
    buffer = QBuffer(data)
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    icon.save(buffer, "PNG")
    return bytes(data)


@pytest.fixture
def dialog():
    _app()
    from cdmw.ui.new_item.painting_dialog import PaintingDialog
    controller = Controller()
    view = PaintingDialog(controller)
    yield view, controller
    QThreadPool.globalInstance().waitForDone(5000)
    view.hide()
    view.deleteLater()


def test_the_frames_are_offered_after_the_read(dialog):
    view, _controller = dialog
    assert [view.frame.itemData(i) for i in range(view.frame.count())] == [SMALL, LARGE]
    assert view.frame.current_frame_row() == -1
    assert view.status.text() == "2 frames found; 1 left out because CDMW cannot map their canvas."


def test_two_paintings_become_two_requests_with_their_own_texts(dialog, tmp_path):
    view, controller = dialog
    view.frame.set_current_frame_row(0)
    view.name.setText("First")
    view.name.textEdited.emit("First")
    view.language.setCurrentIndex(view.language.findData("ger"))
    view.name.setText("Erstes")
    view.name.textEdited.emit("Erstes")
    view.description.setPlainText("Beschreibung")
    view._paintings[0]["picture"] = str(tmp_path / "one.png")
    view.add_button.click()
    assert view.frame.current_frame_row() == -1  # a new painting has no frame yet
    view.frame.set_current_frame_row(1)
    view.language.setCurrentIndex(view.language.findData("eng"))
    view.name.setText("Second")
    view.name.textEdited.emit("Second")
    view.fit.setCurrentIndex(view.fit.findData("whole"))
    view._paintings[1]["picture"] = str(tmp_path / "two.jpg")
    assert view.painting_list.count() == 2
    first, second = view.painting_requests()
    assert (first.frame, first.names, first.descriptions, first.fit) == (
        SMALL, {"eng": "First", "ger": "Erstes"}, {"ger": "Beschreibung"}, "fill")
    assert (second.frame, second.names, second.fit) == (LARGE, {"eng": "Second"}, "whole")
    view.painting_list.setCurrentRow(0)
    assert view.frame.currentData() == SMALL
    view.folder.setText(str(tmp_path / "mod"))
    view.build_button.click()
    requests, folder, title = controller.builds[-1]
    assert len(requests) == 2 and str(folder) == str(tmp_path / "mod") and title == "Custom paintings"
    # Once written, the paintings leave the list, so a second Build mod cannot write them twice.
    controller.finish(SimpleNamespace(plan=SimpleNamespace(summary_lines=("ItemInfo: 2 painting item(s) appended",)),
                                      export=SimpleNamespace(package_root=tmp_path / "mod"),
                                      paintings=({"names": {"eng": "First"}}, {"names": {"eng": "Second"}})))
    assert view.painting_list.count() == 1 and view.painting_requests()[0].names == {}
    assert "Wrote 2 painting(s)" in view.status.text()


def test_a_build_without_a_folder_is_refused_and_close_cancels_a_running_build(dialog):
    view, controller = dialog
    view.build_button.click()
    assert view.status.text() == "Choose a folder for the mod."
    assert controller.builds == []
    view._set_building(True)
    view.reject()
    assert controller.cancelled == ["paintings"]


def test_a_busy_controller_is_reported():
    _app()
    from cdmw.ui.new_item.painting_dialog import PaintingDialog
    view = PaintingDialog(Controller(busy=True))
    assert "busy with another step" in view.status.text()
    assert view.build_button.isEnabled()
    view.deleteLater()


def test_a_dialog_opened_again_after_close_still_shows_its_build_log(dialog, tmp_path):
    """New painting... keeps one dialog and opens it again; Close must not leave it deaf
    to the build's log for the next opening."""
    import warnings

    view, controller = dialog
    result = SimpleNamespace(plan=SimpleNamespace(summary_lines=[]), paintings=[],
                             export=SimpleNamespace(package_root=tmp_path))
    for opening in ("first", "second"):
        view.open()
        view.folder.setText(str(tmp_path))
        view.build_button.click()
        controller.log_message.emit(f"{opening} build: writing the mod")
        assert f"{opening} build: writing the mod" in view.log.toPlainText()
        controller.finish(result)
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            view.done(0)


def _wait_for_preview(view, timeout_s=5.0):
    import time

    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        QThreadPool.globalInstance().waitForDone(100)
        _app().processEvents()
        if view.preview.has_picture():
            return view.preview.picture()
    raise AssertionError(f"no preview shown: {view.preview.message.text()!r}")


def test_a_small_picture_fills_the_canvas_of_the_frame_drawn_to_scale(dialog, tmp_path):
    """Fredric (2026-11-17): the painting preview was so small it could hardly be seen.
    The picture is drawn on the frame's canvas, as large as the preview allows."""
    from PIL import Image

    view, _controller = dialog
    picture = tmp_path / "small.png"
    Image.new("RGB", (12, 24), (200, 30, 30)).save(picture)
    view.resize(1300, 850)
    view.show()
    view.frame.set_current_frame_row(1)  # 1.5 x 2.0 m: a tall canvas
    view._paintings[0]["picture"] = str(picture)
    view.picture.setText(str(picture))
    view._request_preview()
    image = _wait_for_preview(view)
    # Sampled to the texels the canvas covers in the 512 x 256 texture the build writes.
    assert (image.width(), image.height()) == (512, 256)
    canvas = view.preview.canvas_rect()
    # Drawn at the canvas's shape in metres, filling the preview's height.
    assert abs(canvas.width() / canvas.height() - 1.5 / 2.0) < 0.02
    assert canvas.height() >= view.preview.height() * 0.8
    assert view.preview.message.isHidden()


def test_the_canvas_is_drawn_where_it_sits_in_the_frame():
    from PySide6.QtCore import QRectF

    from cdmw.ui.new_item.painting_preview import PaintingFrameView

    _app()
    view = PaintingFrameView()
    view.resize(500, 400)
    # A 1.0 x 0.8 m frame with a 0.6 x 0.4 m canvas 0.1 m from the left, 0.3 m from the top.
    view.set_frame((1.0, 0.8), (0.6, 0.4), (0.1, 0.3, 0.7, 0.7))
    frame, canvas = view.frame_rect(), view.canvas_rect()
    scale = frame.width() / 1.0
    assert frame.height() == pytest.approx(0.8 * scale, abs=1)
    assert canvas == QRectF(frame.left() + 0.1 * scale, frame.top() + 0.3 * scale, 0.6 * scale, 0.4 * scale)
    # Without a known place, the canvas is centred.
    view.set_frame((1.0, 0.8), (0.6, 0.4))
    centred = view.canvas_rect()
    assert centred.center().x() == pytest.approx(view.frame_rect().center().x())
    view.deleteLater()


def test_the_frame_list_shows_each_frame_with_its_icon_cut_to_the_frame():
    """Fredric (2026-11-17): the frame thumbnail was too small to see. Each frame in the
    list now has its game icon, and the preview takes the frame's colour from it."""
    _app()
    from cdmw.ui.new_item.painting_dialog import PaintingDialog

    controller = Controller(thumbnails={LARGE: _png(48, 64, 0xFF8A5A2B)})
    view = PaintingDialog(controller)
    item = view.frame.item(view.frame.findData(LARGE))
    assert not item.icon().isNull()
    assert view.frame.iconSize().width() >= 64
    assert "1.50 x 2.00 m" in item.text()
    assert view.frame.item(view.frame.findData(SMALL)).icon().isNull()
    view.frame.set_current_frame_row(view.frame.findData(LARGE))
    assert view.preview.has_frame()
    assert view.preview._colour.red() == 0x8A
    view.deleteLater()


def test_the_build_log_is_folded_away_under_the_status_line(dialog, tmp_path):
    """Fredric (2026-11-17): the log took most of the dialog. It is hidden until asked
    for, and a build's lines still land in it."""
    view, controller = dialog
    view.resize(1300, 850)
    view.show()
    _app().processEvents()
    assert view.log.isHidden() and not view.log_toggle.isChecked()
    view.folder.setText(str(tmp_path))
    view.build_button.click()
    controller.log_message.emit("Planning the painting...")
    assert "Planning the painting..." in view.log.toPlainText()
    assert view.log.isHidden()
    view.log_toggle.click()
    assert view.log.isVisible()
    assert view.log.height() <= view.log.fontMetrics().height() * 9


def test_the_preview_takes_most_of_the_dialog(dialog):
    view, _controller = dialog
    view.show()
    view.resize(1300, 850)
    _app().processEvents()
    preview = view.preview.size()
    assert preview.width() >= view.width() * 0.4
    assert preview.height() >= view.height() * 0.6
    # Larger dialog, larger preview.
    before = preview.width() * preview.height()
    view.resize(1600, 1000)
    _app().processEvents()
    assert view.preview.width() * view.preview.height() > before


def test_the_dialog_opens_at_a_share_of_the_screen(dialog):
    from cdmw.ui.new_item.painting_dialog import _MAX_ASPECT, _OPENING_MINIMUM, _SCREEN_SHARE

    view, _controller = dialog
    view.show()
    _app().processEvents()
    area = view.screen().availableGeometry()
    height = min(area.height(), max(_OPENING_MINIMUM[1], int(area.height() * _SCREEN_SHARE[1])))
    width = min(area.width(), max(_OPENING_MINIMUM[0], int(area.width() * _SCREEN_SHARE[0])))
    assert view.width() == min(width, max(_OPENING_MINIMUM[0], int(height * _MAX_ASPECT)))
    assert view.height() == height
    assert area.contains(view.geometry().topLeft())


@pytest.mark.parametrize("screen, expected", [
    ((1920, 1040), (1536, 884)),   # 1080p at 100%
    ((1706, 920), (1364, 782)),    # 2560 x 1440 at 150%, in logical pixels
    ((3440, 1400), (2142, 1190)),  # an ultrawide: no wider than 1.8 times its height
])
def test_the_opening_size_follows_the_screen_in_logical_pixels(dialog, screen, expected):
    from PySide6.QtCore import QRect

    view, _controller = dialog

    class Screen:
        def availableGeometry(self):
            return QRect(0, 0, *screen)

    view.screen = lambda: Screen()
    view._fit_to_screen()
    assert (view.width(), view.height()) == expected
    assert sum(view.splitter.sizes()) <= view.width()
