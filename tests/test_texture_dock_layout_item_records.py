"""The Mesh Editor's texture panel must not leave PySide records of deleted layout items.

The panel builds a Texture Editor and moves its canvas, tool buttons and sections
into its own rail. Qt deletes the layout item of each moved widget in the
editor's layout, and PySide kept its record of the canvas's item, registered
under the freed address (cdmw/ui/layout_item_wrappers.py has the whole story).
The next object Qt made at that address got the old record:

* a ``QThread`` (the editor's open worker): an access violation in
  ``pyside6.abi3.dll`` under ``editor_async_task_ui.py`` ``QThread(self)``; the
  crash report names a ``QWidgetItem`` record at the new thread's address;
* a ``QListWidgetItem`` of the History or Adjustments list: an access violation
  in ``Shiboken::BindingManager::releaseWrapper`` under ``QListWidget.clear()``
  (``editor_history_ui.py`` ``_refresh_history_list``).

The app drops such records as widgets leave their parents; it installs that at
start. A process that never runs app start-up, such as a test run, had no such
rule: ``tests/test_texture_editor_tool_audit.py`` died in 21 of 300 runs under
load, and in none of 300 with the rule. The panel now makes sure of the rule
itself before it moves anything, and the test process applies it as the app does.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parents[1]

# A fresh process with no app start-up: the panel builds its editor, then every
# record PySide holds of a Qt-made layout item is checked against the items the
# layouts really have.
_SCENARIO = r'''
import faulthandler, gc, os, sys
os.environ["QT_QPA_PLATFORM"] = "offscreen"
faulthandler.enable()
import shiboken6
from PySide6.QtCore import QObject, QSettings
from PySide6.QtWidgets import QApplication, QLayout, QLayoutItem
from cdmw.ui.mesh_editor.texture_tools_dock import MeshEditorTextureTools

app = QApplication([])
folder = sys.argv[1]
tools = MeshEditorTextureTools(settings=QSettings(os.path.join(folder, "s.ini"), QSettings.Format.IniFormat),
                               base_dir=folder)
editor = tools._ensure_editor()
print("canvas moved out of the editor:", editor.canvas_scroll.parentWidget() is not editor, flush=True)
stale = []
for layout in [w for w in shiboken6.getAllValidWrappers() if isinstance(w, QLayout)]:
    recorded = [child for child in gc.get_referents(layout)
                if isinstance(child, QLayoutItem) and not isinstance(child, QObject)
                and shiboken6.isValid(child) and not shiboken6.createdByPython(child)]
    if not recorded:
        continue
    addresses = {shiboken6.getCppPointer(child)[0] for child in recorded}
    del recorded
    living = set()
    pending = [layout]
    while pending:  # the layout's items and its sub-layouts' items
        current = pending.pop()
        for index in range(current.count()):
            item = current.itemAt(index)
            living.add(shiboken6.getCppPointer(item)[0])
            if item.layout() is not None:
                pending.append(item.layout())
    stale.extend(sorted(addresses - living))
print("records of deleted layout items:", len(stale), flush=True)
'''


def test_building_the_texture_panel_leaves_no_record_of_a_deleted_layout_item(tmp_path):
    env = dict(os.environ, PYTHONPATH=str(ROOT), QT_QPA_PLATFORM="offscreen", CDMW_NATIVE_CRASH_DUMP="0")
    done = subprocess.run([sys.executable, "-c", _SCENARIO, str(tmp_path)], cwd=ROOT, env=env,
                          capture_output=True, text=True, timeout=180)
    assert done.returncode == 0, (done.returncode, done.stdout, done.stderr[-3000:])
    assert "canvas moved out of the editor: True" in done.stdout, done.stdout
    assert "records of deleted layout items: 0" in done.stdout, done.stdout


def test_the_test_process_drops_layout_item_records_as_the_app_does():
    """tests/conftest.py applies the app's rule once a test has made the application."""

    from PySide6.QtWidgets import QApplication

    from cdmw.ui import layout_item_wrappers
    from cdmw.ui.app_event_hub import app_event_hub
    from tests.gui_thread_gc import apply_layout_item_rule

    app = QApplication.instance() or QApplication([])
    apply_layout_item_rule()  # what the set-up and teardown of every test call
    assert layout_item_wrappers._releaser is not None
    assert layout_item_wrappers._releaser in app_event_hub(app).filters()


def test_conftest_applies_the_rule_around_every_test():
    source = (ROOT / "tests" / "conftest.py").read_text(encoding="utf-8")
    assert source.count("apply_layout_item_rule(") >= 2, "set-up and teardown both apply it"
