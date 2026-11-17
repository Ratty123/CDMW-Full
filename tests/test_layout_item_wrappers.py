"""PySide must not keep wrappers of layout items Qt deleted.

``outer.addLayout(row)`` on a layout with a widget makes PySide wrap each of
row's Qt-made items and keep the wrappers. Qt deletes an item when its widget
is deleted or reparented, and the wrapper stayed registered under the freed
address. A QThread made later at that address got the old wrapper from PySide's
map, and PySide's meta-object lookup read a null pointer: the access violation
in ``QThread(self)`` of the Item Finder warm-up (2026-11-17, closing Mesh Editor
tabs). The subprocess test crashes that way without the releaser.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
import shiboken6  # noqa: E402
from PySide6.QtCore import QEvent, QObject  # noqa: E402
from PySide6.QtWidgets import (  # noqa: E402
    QApplication,
    QHBoxLayout,
    QLabel,
    QLayoutItem,
    QSizePolicy,
    QSpacerItem,
    QVBoxLayout,
    QWidget,
)

from cdmw.ui.layout_item_wrappers import (  # noqa: E402
    ensure_app_layout_item_wrapper_release,
    release_all_layout_item_wrappers,
    release_layout_item_wrappers,
)

ROOT = Path(__file__).resolve().parents[1]

# Rows added to a laid-out widget, their labels deleted, then QThreads made until
# one lands on a freed QWidgetItem (QWidgetItem 88 bytes, QThreadWrapper 80: one
# heap size class). "fixed" installs CDMW's releaser first.
_SCENARIO = r'''
import faulthandler, sys
faulthandler.enable()
import shiboken6
from PySide6.QtCore import QObject, QThread
from PySide6.QtWidgets import QApplication, QHBoxLayout, QLabel, QVBoxLayout, QWidget
app = QApplication([])
if sys.argv[1] == "fixed":
    from cdmw.ui.layout_item_wrappers import ensure_app_layout_item_wrapper_release
    ensure_app_layout_item_wrapper_release(app)
host = QWidget()
outer = QVBoxLayout(host)
labels = []
for _ in range(200):
    row = QHBoxLayout()
    label = QLabel("x")
    row.addWidget(label)
    outer.addLayout(row)
    labels.append(label)
items = [w for w in shiboken6.getAllValidWrappers() if type(w).__name__ == "QWidgetItem"]
freed = {shiboken6.getCppPointer(item)[0] for item in items}
print("wrapped items", len(items), flush=True)
del items
for label in labels:
    shiboken6.delete(label)
left = sum(1 for w in shiboken6.getAllValidWrappers() if type(w).__name__ == "QWidgetItem")
print("registered after delete", left, flush=True)
parent = QObject()
kept = []
for index in range(20000):
    thread = QThread(parent)
    kept.append(thread)
    if shiboken6.getCppPointer(thread)[0] in freed:
        print("landed", thread.metaObject().className(), flush=True)
        break
else:
    print("no reuse", flush=True)
'''


def _app():
    return QApplication.instance() or QApplication([])


def _registered_items():
    return [
        wrapper
        for wrapper in shiboken6.getAllValidWrappers()
        if isinstance(wrapper, QLayoutItem) and not isinstance(wrapper, QObject)
    ]


def _run(mode):
    env = dict(os.environ, PYTHONPATH=str(ROOT), QT_QPA_PLATFORM="offscreen", CDMW_NATIVE_CRASH_DUMP="0")
    return subprocess.run([sys.executable, "-c", _SCENARIO, mode], cwd=ROOT, env=env,
                          capture_output=True, text=True, timeout=180)


@pytest.mark.skipif(sys.platform != "win32", reason="the heap reuse that turns this into a crash is Windows'")
def test_a_qthread_on_a_freed_layout_item_crashes_without_the_releaser_and_not_with_it():
    old = _run("old")
    if "no reuse" in old.stdout:
        pytest.skip("no QThread landed on a freed layout item")
    assert "registered after delete 200" in old.stdout, old.stdout
    assert old.returncode == 0xC0000005, (old.returncode, old.stdout, old.stderr[-2000:])
    assert "access violation" in old.stderr

    fixed = _run("fixed")
    assert fixed.returncode == 0, (fixed.returncode, fixed.stdout, fixed.stderr[-2000:])
    assert "registered after delete 0" in fixed.stdout, fixed.stdout
    assert "landed QThread" in fixed.stdout or "no reuse" in fixed.stdout, fixed.stdout


def _laid_out_rows(count=3):
    host = QWidget()
    outer = QVBoxLayout(host)
    labels = []
    for _ in range(count):
        row = QHBoxLayout()
        label = QLabel("x")
        row.addWidget(label)
        row.addStretch(1)
        outer.addLayout(row)
        labels.append(label)
    return host, outer, labels


@pytest.mark.parametrize("remove", ["delete", "unparent", "delete_later"])
def test_child_removal_drops_the_parent_layouts_item_wrappers(remove):
    app = _app()
    ensure_app_layout_item_wrapper_release(app)
    host, outer, labels = _laid_out_rows()
    before = len(_registered_items())
    assert before >= 6  # a QWidgetItem and a QSpacerItem a row
    victim = labels[1]
    if remove == "delete":
        shiboken6.delete(victim)
    elif remove == "unparent":
        victim.setParent(None)
    else:
        victim.deleteLater()
        app.sendPostedEvents(None, QEvent.Type.DeferredDelete.value)
    assert _registered_items() == []
    # The layout and the other rows are untouched; itemAt wraps a live item again.
    assert outer.count() == 3
    first_row = outer.itemAt(0).layout()
    assert first_row.itemAt(0).widget() is labels[0]
    assert labels[0].parentWidget() is host
    shiboken6.delete(host)


def test_items_made_in_python_and_taken_items_are_left_alone():
    _app()
    host = QWidget()
    layout = QVBoxLayout(host)
    spacer = QSpacerItem(10, 10, QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Expanding)
    layout.addItem(spacer)
    row = QHBoxLayout()
    row.addWidget(QLabel("x"))
    layout.addLayout(row)
    taken = layout.takeAt(0)
    assert taken is spacer
    layout.addItem(spacer)
    released = release_layout_item_wrappers(layout)
    assert released == 1  # the label's QWidgetItem only
    assert shiboken6.isValid(spacer)
    assert spacer.sizeHint().height() == 10
    shiboken6.delete(host)


def test_the_idle_sweep_reaches_every_layout():
    _app()
    hosts = [_laid_out_rows(2)[0] for _ in range(3)]
    assert len(_registered_items()) >= 12
    assert release_all_layout_item_wrappers() >= 12
    assert _registered_items() == []
    for host in hosts:
        shiboken6.delete(host)


def test_installed_once_per_application_through_the_hub():
    from cdmw.ui.app_event_hub import app_event_hub

    app = _app()
    first = ensure_app_layout_item_wrapper_release(app)
    assert ensure_app_layout_item_wrapper_release(app) is first
    assert first in app_event_hub(app).filters()


def test_a_layout_written_in_python_keeps_its_items_and_held_wrappers_stay_valid():
    from cdmw.ui.wrapping_layout import WrappingLayout

    app = _app()
    ensure_app_layout_item_wrapper_release(app)
    host = QWidget()
    outer = QVBoxLayout(host)
    flow = WrappingLayout()
    labels = [QLabel(f"tag {index}") for index in range(4)]
    for label in labels:
        flow.addWidget(label)
    outer.addLayout(flow)
    row = QHBoxLayout()
    row.addWidget(QLabel("kept"))
    outer.addLayout(row)
    held = row.itemAt(0)
    shiboken6.delete(labels[0])  # ChildRemoved: the sweep runs
    assert release_all_layout_item_wrappers() >= 0
    # WrappingLayout's own list still hands Qt valid items.
    assert flow.count() == 3
    assert all(shiboken6.isValid(flow.itemAt(index)) for index in range(3))
    host.resize(300, 200)
    host.show()
    app.processEvents()
    assert labels[1].isVisible()
    assert shiboken6.isValid(held) and held.widget().text() == "kept"
    shiboken6.delete(host)
