"""Mods is a list of CDMW packages that Send to DMM writes as one DMM mod."""
import pytest
from PySide6.QtCore import QEvent, QSettings, Qt
from PySide6.QtWidgets import QApplication, QMessageBox

from cdmw.ui.new_item.controller import NewItemStudioController
from cdmw.ui.tools.dmm_packages_page import DMM_MOD_TITLE, DmmPackagesPage
from tests.test_mod_management import pump


_OPEN = []


@pytest.fixture(autouse=True)
def _close_pages():
    yield
    app = QApplication.instance()
    while _OPEN:
        controller, page = _OPEN.pop()
        page.request_shutdown()
        controller.shutdown()
        page.deleteLater()
        controller.deleteLater()
    if app is not None:
        app.sendPostedEvents(None, QEvent.DeferredDelete)
        app.processEvents()


def _page(tmp_path, settings=None):
    app = QApplication.instance() or QApplication([])
    controller = NewItemStudioController()
    settings = settings or QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    page = DmmPackagesPage(controller, str(tmp_path / "game"), settings=settings)
    _OPEN.append((controller, page))
    return app, controller, page, settings


def _files(tmp_path, *names):
    paths = []
    for name in names:
        path = tmp_path / name
        path.write_bytes(b"package")
        paths.append(str(path))
    return paths


def test_mod_management_offers_only_the_dmm_list(tmp_path):
    from cdmw.ui.tools.mod_management import ModManagementTab
    app = QApplication.instance() or QApplication([])
    tab = ModManagementTab(get_package_root=lambda: str(tmp_path))
    try:
        assert isinstance(tab.virtual_page, DmmPackagesPage)
        assert [tab.pages.tabText(i) for i in range(tab.pages.count())] == ["Mods"]
        assert not hasattr(tab.virtual_page, "apply_button") and not hasattr(tab.virtual_page, "launch_button")
    finally:
        tab.request_shutdown()
        pump(app, lambda: not tab.iter_shutdown_workers())
        tab.deleteLater()
        app.sendPostedEvents(None, QEvent.DeferredDelete)


def test_the_list_survives_a_restart_and_removal_keeps_files(tmp_path):
    _app, _controller, page, settings = _page(tmp_path)
    files = _files(tmp_path, "Amber.cdmw", "Old.cditem")
    page._append(files + files[:1])
    assert page.packages() == files
    page.selection.topLevelItem(0).setSelected(True)
    removed = page.selection.topLevelItem(0).data(0, Qt.UserRole)
    page._remove()
    _app, _controller, again, _settings = _page(tmp_path, settings)
    assert again.packages() == [path for path in files if path != removed]
    assert all(__import__("pathlib").Path(path).is_file() for path in files)


def test_send_takes_the_selection_or_every_package(tmp_path, monkeypatch):
    from cdmw.services import dmm_send, dmm_send_process
    from cdmw.ui.new_item import dmm_send_ui
    app, controller, page, _settings = _page(tmp_path)
    files = _files(tmp_path, "Amber.cdmw", "Azure.cdmw")
    page._append(files)
    sent = []
    monkeypatch.setattr(dmm_send_ui, "choose_dmm_mods_folder", lambda parent: tmp_path / "mods")
    monkeypatch.setattr(dmm_send_process, "send_item_packages_in_subprocess", lambda paths, root, mods, title, **_: sent.append((tuple(paths), title))
                        or dmm_send.DmmSendResult(mods / title, False, title))
    monkeypatch.setattr(QMessageBox, "information", lambda *args: QMessageBox.Ok)
    page.selection.clearSelection()
    page._buttons()
    assert page.send_dmm_button.isEnabled()
    page.send_dmm_button.click()
    pump(app, lambda: bool(sent) and not controller.busy)
    assert sorted(sent[-1][0]) == sorted(files) and sent[-1][1] == DMM_MOD_TITLE
    page.selection.topLevelItem(1).setSelected(True)
    page.send_dmm_button.click()
    pump(app, lambda: len(sent) == 2 and not controller.busy)
    assert sent[-1][0] == (page.selection.topLevelItem(1).data(0, Qt.UserRole),)
    assert "Sent 1 item package(s) to DMM" in page.status.text()


def test_a_busy_worker_never_greys_out_the_list_and_send_waits_for_it(tmp_path, monkeypatch):
    from cdmw.services import dmm_send, dmm_send_process
    from cdmw.ui.new_item import dmm_send_ui
    app, controller, page, _settings = _page(tmp_path)
    page._append(_files(tmp_path, "Amber.cdmw"))
    sent = []
    monkeypatch.setattr(dmm_send_ui, "choose_dmm_mods_folder", lambda parent: tmp_path / "mods")
    monkeypatch.setattr(dmm_send_process, "send_item_packages_in_subprocess", lambda paths, root, mods, title, **_: sent.append(tuple(paths))
                        or dmm_send.DmmSendResult(mods / title, False, title))
    monkeypatch.setattr(QMessageBox, "information", lambda *args: QMessageBox.Ok)
    busy = {"value": True}
    monkeypatch.setattr(type(controller), "busy", property(lambda self: busy["value"]))
    page._buttons()
    # Reading the game archives after startup must not lock the list.
    assert page.add_items.isEnabled() and page.send_dmm_button.isEnabled()
    page.send_dmm_button.click()
    assert not sent and page.status.text() == "Waiting for the game archives to finish loading…"
    busy["value"] = False
    controller.busy_changed.emit(False)
    pump(app, lambda: bool(sent) and not controller.busy and not page._working)
    assert len(sent) == 1
