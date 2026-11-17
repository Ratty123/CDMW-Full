"""A native fault leaves a small minidump next to faulthandler's log (Windows).

The B pass 13 crashes were on a thread with "<no Python frame>", and faulthandler
cannot read a C stack on Windows. A dump of the crashing process lets the next
crash's C stack be read. A text report beside it names the Python objects the
faulting thread's registers point at, which a debugger cannot read from the dump:
the 2026-11-17 crash in ``QThread(self)`` came from an older wrapper PySide found
at the new QThread's address, and the dump alone could not say of what type.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

# A thread that starts at address 1: an access violation on a native thread with no
# Python frame, while the main thread runs Python, as in the crash.
_CRASH = r'''
import ctypes, faulthandler, sys, threading
from pathlib import Path
from cdmw.services.native_crash_dump import install_native_crash_dump
folder = Path(sys.argv[1])
log = (folder / "native_fault_current.log").open("a", encoding="utf-8")
faulthandler.enable(file=log, all_threads=True)
print("dump", install_native_crash_dump(folder), flush=True)
kernel32 = ctypes.WinDLL("kernel32")
kernel32.CreateThread.argtypes = [ctypes.c_void_p, ctypes.c_size_t, ctypes.c_void_p, ctypes.c_void_p,
                                  ctypes.c_uint32, ctypes.c_void_p]
kernel32.CreateThread.restype = ctypes.c_void_p
kernel32.CreateThread(None, 0, ctypes.c_void_p(1), None, 0, None)
while True:
    sum(index * index for index in range(5000))
'''


@pytest.mark.skipif(sys.platform != "win32", reason="Windows minidumps")
def test_native_fault_writes_one_small_dump_and_keeps_its_exit_code(tmp_path):
    from cdmw.services.native_crash_dump import native_crash_dumps, native_crash_report_path

    env = dict(os.environ, PYTHONPATH=str(ROOT))
    env.pop("CDMW_NATIVE_CRASH_DUMP", None)
    completed = subprocess.run([sys.executable, "-c", _CRASH, str(tmp_path)], cwd=ROOT, env=env,
                               capture_output=True, text=True, timeout=120)
    assert completed.returncode == 0xC0000005, (completed.returncode, completed.stdout, completed.stderr[-2000:])
    dumps = native_crash_dumps(tmp_path)
    assert len(dumps) == 1, list(tmp_path.iterdir())
    data = dumps[0].read_bytes()
    assert data[:4] == b"MDMP"
    assert 0 < len(data) < 32 * 1024 * 1024
    # faulthandler (it runs first) still wrote its log.
    assert "access violation" in (tmp_path / "native_fault_current.log").read_text(encoding="utf-8")
    report = native_crash_report_path(dumps[0]).read_text(encoding="utf-8")
    assert "exception 0xC0000005 (access violation) at 0x1" in report
    assert "execution at 0x1" in report
    assert "rip = 0x0000000000000001" in report


# The 2026-11-17 crash, made on purpose: PySide still holds a wrapper of a QWidgetItem
# Qt deleted (a label of a row added with addLayout, then deleted), and a QThread
# lands on its address.
_STALE_WRAPPER_CRASH = r'''
import faulthandler, sys
from pathlib import Path
from cdmw.services.native_crash_dump import install_native_crash_dump
import shiboken6
from PySide6.QtCore import QObject, QThread
from PySide6.QtWidgets import QApplication, QHBoxLayout, QLabel, QVBoxLayout, QWidget
folder = Path(sys.argv[1])
log = (folder / "native_fault_current.log").open("a", encoding="utf-8")
faulthandler.enable(file=log, all_threads=True)
app = QApplication([])
print("dump", install_native_crash_dump(folder), flush=True)
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
del items
for label in labels:
    shiboken6.delete(label)
parent = QObject()
kept = []
for index in range(20000):
    thread = QThread(parent)
    kept.append(thread)
    if shiboken6.getCppPointer(thread)[0] in freed:
        print("landed", flush=True)
        break
else:
    print("no reuse", flush=True)
'''


@pytest.mark.skipif(sys.platform != "win32", reason="Windows minidumps")
def test_the_report_names_the_stale_wrapper_pyside_found_for_a_new_qthread(tmp_path):
    from cdmw.services.native_crash_dump import native_crash_dumps, native_crash_report_path

    env = dict(os.environ, PYTHONPATH=str(ROOT), QT_QPA_PLATFORM="offscreen")
    env.pop("CDMW_NATIVE_CRASH_DUMP", None)
    completed = subprocess.run([sys.executable, "-c", _STALE_WRAPPER_CRASH, str(tmp_path)], cwd=ROOT, env=env,
                               capture_output=True, text=True, timeout=180)
    if "no reuse" in completed.stdout:
        pytest.skip("no QThread landed on a freed layout item")
    assert completed.returncode == 0xC0000005, (completed.returncode, completed.stdout, completed.stderr[-2000:])
    dumps = native_crash_dumps(tmp_path)
    assert len(dumps) == 1
    assert len(dumps[0].read_bytes()) < 32 * 1024 * 1024
    report = native_crash_report_path(dumps[0]).read_text(encoding="utf-8")
    # The fault and its caller, as in the app's dump: pyside6.abi3+0x1c8d4 from QtCore.pyd.
    assert "(access violation) at 0x" in report and "pyside6.abi3.dll+0x" in report
    assert "read of 0x0" in report
    assert "QtCore.pyd+0x" in report
    registers = report.split("stack:", 1)[0]
    stale = [line for line in registers.splitlines() if "'PySide6.QtWidgets.QWidgetItem'" in line]
    made = [line for line in registers.splitlines() if "'PySide6.QtCore.QThread'" in line and "made by Python" in line]
    assert stale and made, report
    # Both wrappers stand for one C++ address: the old one hides the new one.
    address = stale[0].split("wrapper of C++ ", 1)[1].split(" ", 1)[0]
    assert f"wrapper of C++ {address} " in made[0], report


@pytest.mark.skipif(sys.platform != "win32", reason="Windows minidumps")
def test_no_dump_without_a_crash_and_old_dumps_are_pruned(tmp_path):
    from cdmw.services import native_crash_dump as module

    for index in range(5):
        path = tmp_path / f"{module.DUMP_PREFIX}20261117-00000{index}-1{module.DUMP_SUFFIX}"
        path.write_bytes(b"MDMP")
        os.utime(path, (1_000_000 + index, 1_000_000 + index))
        module.native_crash_report_path(path).write_text("report", encoding="utf-8")
    (tmp_path / "keep-me.log").write_text("x", encoding="utf-8")
    env = dict(os.environ, PYTHONPATH=str(ROOT))
    script = ("import sys; from pathlib import Path; from cdmw.services.native_crash_dump import "
              "install_native_crash_dump as install; print(install(Path(sys.argv[1])))")
    completed = subprocess.run([sys.executable, "-c", script, str(tmp_path)], cwd=ROOT, env=env,
                               capture_output=True, text=True, timeout=60)
    assert completed.returncode == 0, completed.stderr
    left = sorted(path.name for path in tmp_path.glob(f"{module.DUMP_PREFIX}*"))
    # Room for this run's dump: the two newest old ones stay, with their reports, and a
    # clean exit adds none.
    assert left == [f"{module.DUMP_PREFIX}20261117-000003-1.dmp", f"{module.DUMP_PREFIX}20261117-000003-1.txt",
                    f"{module.DUMP_PREFIX}20261117-000004-1.dmp", f"{module.DUMP_PREFIX}20261117-000004-1.txt"]
    assert (tmp_path / "keep-me.log").is_file()


def test_turned_off_by_the_environment(monkeypatch, tmp_path):
    from cdmw.services.native_crash_dump import install_native_crash_dump

    monkeypatch.setenv("CDMW_NATIVE_CRASH_DUMP", "0")
    assert install_native_crash_dump(tmp_path) is None
