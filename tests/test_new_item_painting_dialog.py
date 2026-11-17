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


def frame(mesh, size):
    return SimpleNamespace(
        mesh=mesh, stem=mesh.rsplit("/", 1)[-1][:-4], label=f"{mesh} frame", size_m=size, texture_size=(512, 256),
        canvas=CanvasMapping(material="pic", uv_rect=(0, 0, 1, 1), size_m=size, vertex_count=4),
        source=SimpleNamespace(name="Collection_Prop_Picture_0001"), shipped_paintings=3)


class Controller(QObject):
    log_message = Signal(str)

    def __init__(self, *, busy=False):
        super().__init__()
        self.busy = busy
        self.builds = []
        self.cancelled = []

    def start_painting_frames(self, on_done, on_error):
        if self.busy:
            return False
        on_done((PaintingFrameCatalogue(frames=(frame("object/a/small.pam", (0.5, 0.4)), frame("object/a/large.pam", (1.5, 2.0))),
                                        left_out=(("object/a/turned.pam", "no canvas"),)), {}))
        return True

    def start_painting_build(self, requests, folder, title, on_done, on_error):
        self.builds.append((requests, folder, title))
        self.finish = on_done
        return True

    def cancel_operation(self, lane=""):
        self.cancelled.append(lane)
        return True


@pytest.fixture
def dialog():
    _app()
    from cdmw.ui.new_item.painting_dialog import PaintingDialog
    controller = Controller()
    view = PaintingDialog(controller)
    yield view, controller
    QThreadPool.globalInstance().waitForDone(5000)
    view.deleteLater()


def test_the_frames_are_offered_after_the_read(dialog):
    view, _controller = dialog
    assert [view.frame.itemData(i) for i in range(view.frame.count())] == ["", "object/a/small.pam", "object/a/large.pam"]
    assert view.status.text() == "2 frames found; 1 left out because CDMW cannot map their canvas."


def test_two_paintings_become_two_requests_with_their_own_texts(dialog, tmp_path):
    view, controller = dialog
    view.frame.setCurrentIndex(1)
    view.name.setText("First")
    view.name.textEdited.emit("First")
    view.language.setCurrentIndex(view.language.findData("ger"))
    view.name.setText("Erstes")
    view.name.textEdited.emit("Erstes")
    view.description.setPlainText("Beschreibung")
    view._paintings[0]["picture"] = str(tmp_path / "one.png")
    view.add_button.click()
    view.frame.setCurrentIndex(2)
    view.language.setCurrentIndex(view.language.findData("eng"))
    view.name.setText("Second")
    view.name.textEdited.emit("Second")
    view.fit.setCurrentIndex(view.fit.findData("whole"))
    view._paintings[1]["picture"] = str(tmp_path / "two.jpg")
    assert view.painting_list.count() == 2
    first, second = view.painting_requests()
    assert (first.frame, first.names, first.descriptions, first.fit) == (
        "object/a/small.pam", {"eng": "First", "ger": "Erstes"}, {"ger": "Beschreibung"}, "fill")
    assert (second.frame, second.names, second.fit) == ("object/a/large.pam", {"eng": "Second"}, "whole")
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
