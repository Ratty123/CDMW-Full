"""A native fault leaves a small minidump next to faulthandler's log (Windows).

The B pass 13 crashes were on a thread with "<no Python frame>", and faulthandler
cannot read a C stack on Windows. A dump of the crashing process lets the next
crash's C stack be read.
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
    from cdmw.services.native_crash_dump import native_crash_dumps

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


@pytest.mark.skipif(sys.platform != "win32", reason="Windows minidumps")
def test_no_dump_without_a_crash_and_old_dumps_are_pruned(tmp_path):
    from cdmw.services import native_crash_dump as module

    for index in range(5):
        path = tmp_path / f"{module.DUMP_PREFIX}20261117-00000{index}-1{module.DUMP_SUFFIX}"
        path.write_bytes(b"MDMP")
        os.utime(path, (1_000_000 + index, 1_000_000 + index))
    (tmp_path / "keep-me.log").write_text("x", encoding="utf-8")
    env = dict(os.environ, PYTHONPATH=str(ROOT))
    script = ("import sys; from pathlib import Path; from cdmw.services.native_crash_dump import "
              "install_native_crash_dump as install; print(install(Path(sys.argv[1])))")
    completed = subprocess.run([sys.executable, "-c", script, str(tmp_path)], cwd=ROOT, env=env,
                               capture_output=True, text=True, timeout=60)
    assert completed.returncode == 0, completed.stderr
    left = sorted(path.name for path in tmp_path.glob(f"{module.DUMP_PREFIX}*"))
    # Room for this run's dump: the two newest old ones stay, and a clean exit adds none.
    assert left == [f"{module.DUMP_PREFIX}20261117-000003-1.dmp", f"{module.DUMP_PREFIX}20261117-000004-1.dmp"]
    assert (tmp_path / "keep-me.log").is_file()


def test_turned_off_by_the_environment(monkeypatch, tmp_path):
    from cdmw.services.native_crash_dump import install_native_crash_dump

    monkeypatch.setenv("CDMW_NATIVE_CRASH_DUMP", "0")
    assert install_native_crash_dump(tmp_path) is None
