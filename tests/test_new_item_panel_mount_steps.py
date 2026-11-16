"""Create New Item mounts its panels in steps that each stay small.

The review measured 1.8 s on the UI thread in one step of opening Create New
Item: the last step built the page stack and moved every finished panel into
it, the stack into a body and the body into the tab, restyling the whole
subtree each time; and the Model panel took 0.8 s in one constructor call.
The page stack now exists, attached to the tab, before any panel is built,
each panel moves into its page in its own step, and the Model panel is built
a section per step.
"""

from __future__ import annotations

import os
import sys
import tempfile
import time
from pathlib import Path
from unittest.mock import patch

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "tests"))

from PySide6.QtCore import QCoreApplication, QEvent  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402
from shiboken6 import isValid  # noqa: E402

from cdmw.core.archive_format import parse_archive_pamt  # noqa: E402
from cdmw.services.new_item_service import NewItemService  # noqa: E402
from test_new_item_service import _read, build_package, synthetic_files  # noqa: E402


@pytest.fixture
def make_tab():
    app = QApplication.instance() or QApplication([])
    temp = tempfile.TemporaryDirectory()
    root = Path(temp.name)
    entries = tuple(parse_archive_pamt(build_package(root, synthetic_files())))
    patches = [
        patch("cdmw.constants.MOD_FOLDER_TOOLS_ENABLED", True),
        patch("cdmw.core.archive_patching.ARCHIVE_PATCH_BACKUP_ROOT", root / "backups"),
        patch("cdmw.ui.new_item.item_preview.ItemPreviewFrame._start_package", lambda *_a, **_k: None),
        patch("cdmw.ui.new_item.panels_output.resolve_settings_file_path", lambda: root / "CDMW.cfg"),
        patch("cdmw.ui.new_item.panels_output.QDesktopServices.openUrl", return_value=True),
    ]
    for item in patches:
        item.start()
    tabs = []

    def make():
        from cdmw.ui.new_item.controller import NewItemStudioController
        from cdmw.ui.new_item.tab import NewItemStudioTab

        controller = NewItemStudioController(service=NewItemService(), read_entry=_read, synchronous=True)
        tab = NewItemStudioTab(controller=controller, get_archive_entries=lambda: entries)
        tabs.append(tab)
        return tab

    yield make
    for tab in tabs:
        if isValid(tab):
            tab.close()
            deadline = time.monotonic() + 5
            while tab.iter_shutdown_workers() and time.monotonic() < deadline:
                app.processEvents()
                time.sleep(0.001)
            tab.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    app.processEvents()
    for item in reversed(patches):
        item.stop()
    temp.cleanup()


def _ancestors(widget):
    current = widget.parentWidget()
    while current is not None:
        yield current
        current = current.parentWidget()


def test_the_page_stack_is_in_the_tab_before_any_panel_is_built(make_tab):
    tab = make_tab()
    tab.show()
    steps = tab._build_panels()
    next(steps)
    assert not hasattr(tab, "template_panel")
    assert tab.pages.count() == 7
    assert tab in set(_ancestors(tab.pages)), "the stack is attached to the tab from the first step"
    assert tab._step_body.isHidden()
    next(steps)
    # The template panel is in its page right after the step that built it.
    assert tab.pages in set(_ancestors(tab.template_panel))
    for _ in steps:
        pass
    assert tab._panels_built
    assert not tab._step_body.isHidden()
    for index, panel in ((0, tab.template_panel), (1, tab.identity_panel), (2, tab.model_panel), (6, tab.output_panel)):
        page = tab.pages.widget(index)
        assert page is panel or page.isAncestorOf(panel)
    assert tab.pages.currentIndex() == 0


def test_the_model_panel_is_built_a_section_per_step(make_tab):
    from cdmw.ui.new_item.panels_model import ModelPanel

    tab = make_tab()
    panel = ModelPanel(tab.controller, build_in_steps=True)
    assert not hasattr(panel, "components")
    sections = sum(1 for _ in panel.remaining_build_steps)
    assert sections >= 5
    assert panel._workspace_ready and hasattr(panel, "components")
    whole = ModelPanel(tab.controller)
    assert whole._workspace_ready and hasattr(whole, "components")
    whole.deleteLater()
    panel.deleteLater()


def test_the_mount_survives_event_loop_turns_between_every_step(make_tab):
    tab = make_tab()
    tab.show()
    app = QApplication.instance()
    steps = tab._build_panels()
    count = 0
    for _ in steps:
        count += 1
        for _turn in range(3):
            app.processEvents()
    assert count >= 10
    assert tab._panels_built and tab._model_panel_in_build is None
    tab._panels_ready()
    app.processEvents()
    assert tab.pages.currentIndex() == 0


def test_a_shutdown_while_the_model_panel_is_half_built_reaches_its_preview(make_tab):
    tab = make_tab()
    tab.show()
    steps = tab._build_panels()
    tab._panel_mount_steps = steps
    while getattr(tab, "_model_panel_in_build", None) is None or not hasattr(tab._model_panel_in_build, "preview"):
        next(steps)
    preview = tab._model_panel_in_build.preview
    calls = []
    with patch.object(type(preview), "request_shutdown", lambda self: calls.append("request")), \
            patch.object(type(preview), "shutdown", lambda self: calls.append("shutdown")):
        tab.shutdown()
    assert "request" in calls and "shutdown" in calls
    assert not hasattr(tab, "model_panel") or tab.model_panel is None
