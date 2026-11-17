"""A QPainter ends when its function ends, not when Python frees it.

Qt's raster paint engine is one per backing store, shared by every widget of a
window. A painter that is still active when the next widget starts painting
clears the engine's state when it is finally destroyed, and the painter then in
use reads or writes through a null pointer. Python frees a ``paintEvent``'s
painter when the call returns, unless something holds the call's frame: a stack
sampler on another thread (``sys._current_frames()``), a traceback, a debugger.

That was the start-up splash crash of 2026-11-17 (an access violation in
``Qt6Gui`` ``QRasterPaintEngine::penChanged`` under
``startup_dialogs._draw_iso_block``, 1 in 5 launches driven through the
automation bridge, whose ``ui_stack`` held the window thread's frames): the
progress card's painter outlived its paint event and died while the block wave
painted on the same window.
"""

from __future__ import annotations

import ast
import os
import subprocess
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]

# The splash painting while another thread holds the window thread's frames, as
# the automation bridge's ui_stack did every 50 ms. Before the fix this died of an
# access violation in Qt6Gui within the first second.
_SCENARIO = r'''
import faulthandler, os, sys, threading, time, traceback
os.environ["QT_QPA_PLATFORM"] = "offscreen"
faulthandler.enable()
import gc
gc.disable()  # as the app does: nothing is collected on the sampler's thread
from PySide6.QtWidgets import QApplication
from cdmw.ui.shell.startup_dialogs import StartupSplashDialog

app = QApplication([])
splash = StartupSplashDialog()
splash.show()
stop = threading.Event()
main_ident = threading.main_thread().ident
samples = 0

def sampler():
    global samples
    while not stop.is_set():
        frame = sys._current_frames().get(main_ident)
        if frame is not None:
            traceback.extract_stack(frame)
        samples += 1
        time.sleep(0.0005)  # still holding the frame, as a caller formatting it does
        del frame

thread = threading.Thread(target=sampler, daemon=True)
thread.start()
end = time.monotonic() + float(sys.argv[1])
paints = 0
while time.monotonic() < end:
    splash.set_detail(f"Loading {paints}", paints % 100, 100)
    splash.signal_mark.repaint()
    paints += 1
    app.processEvents()
stop.set()
thread.join()
print(f"OK paints={paints} samples={samples}", flush=True)
'''


def _app():
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


def _painter_left_by(widget, method_name: str):
    """Repaint ``widget`` while keeping its paintEvent's frame, as a stack sampler on
    another thread does, and return the painter that frame still holds."""

    held = []
    original = getattr(widget, method_name)

    def keeping_the_callers_frame(*args, **kwargs):
        held.append(sys._getframe(1))
        return original(*args, **kwargs)

    setattr(widget, method_name, keeping_the_callers_frame)
    try:
        widget.repaint()
    finally:
        delattr(widget, method_name)
    assert held, f"{method_name} was not reached: the widget did not paint"
    assert held[-1].f_code.co_name == "paintEvent"
    return held[-1].f_locals["painter"]


@pytest.mark.parametrize("part, method_name", [
    ("progress_card", "_draw_falling_blocks"),
    ("signal_mark", "_draw_cdmw_block_wave"),
])
def test_a_splash_painter_has_ended_when_its_paint_event_returns_even_if_its_frame_is_kept(part, method_name):
    from cdmw.ui.shell.startup_dialogs import StartupSplashDialog

    app = _app()
    splash = StartupSplashDialog()
    splash.show()
    app.processEvents()  # the window is exposed, so repaint() paints
    try:
        painter = _painter_left_by(getattr(splash, part), method_name)
        try:
            assert not painter.isActive(), (
                f"the {part} painter is still painting on the window after its paint event")
        finally:
            painter.end()  # so that a failure here cannot take the test process down later
    finally:
        splash.finish()


def _painter_constructions(tree: ast.AST):
    """(statement, the statement after it in the same block) for each ``x = QPainter(...)``."""

    for node in ast.walk(tree):
        for field in ("body", "orelse", "finalbody"):
            block = getattr(node, field, None)
            if not isinstance(block, list):
                continue
            for index, statement in enumerate(block):
                value = getattr(statement, "value", None)
                if not isinstance(statement, ast.Assign) or not isinstance(value, ast.Call):
                    continue
                called = value.func
                if getattr(called, "id", getattr(called, "attr", "")) != "QPainter":
                    continue
                yield statement, (block[index + 1] if index + 1 < len(block) else None)


def _ends_in_finally(statement: ast.Assign, following: ast.stmt | None) -> bool:
    target = statement.targets[0]
    if not isinstance(target, ast.Name) or not isinstance(following, ast.Try):
        return False
    return any(
        isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "end"
        and isinstance(node.func.value, ast.Name) and node.func.value.id == target.id
        for final in following.finalbody for node in ast.walk(final)
    )


def test_every_painter_cdmw_makes_is_ended_in_a_finally():
    """``painter = QPainter(...)`` is followed by ``try: ... finally: painter.end()``
    everywhere, so no painter's end waits for Python to free it."""

    left_to_python = []
    seen = 0
    for path in sorted((ROOT / "cdmw").rglob("*.py")):
        source = path.read_text(encoding="utf-8")
        if "QPainter(" not in source:
            continue
        for statement, following in _painter_constructions(ast.parse(source)):
            seen += 1
            if not _ends_in_finally(statement, following):
                left_to_python.append(f"{path.relative_to(ROOT).as_posix()}:{statement.lineno}")
    assert seen >= 25, "the scan no longer finds CDMW's painters"
    assert not left_to_python, left_to_python


def test_the_splash_keeps_painting_while_another_thread_holds_the_window_threads_frames():
    env = dict(os.environ, PYTHONPATH=str(ROOT), QT_QPA_PLATFORM="offscreen", CDMW_NATIVE_CRASH_DUMP="0")
    done = subprocess.run([sys.executable, "-c", _SCENARIO, "4"], cwd=ROOT, env=env,
                          capture_output=True, text=True, timeout=120)
    assert done.returncode == 0, (done.returncode, done.stdout, done.stderr[-3000:])
    assert "OK paints=" in done.stdout, done.stdout
