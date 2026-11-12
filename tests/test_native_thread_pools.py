"""OpenBLAS's thread pool is bounded before numpy loads (P16 stage 2, numpy without OpenBLAS)."""

from __future__ import annotations

import ast
import os
import subprocess
import sys
from pathlib import Path

import pytest

from cdmw.app.native_threads import OPENBLAS_THREADS, limit_native_thread_pools


def test_sets_a_default_and_keeps_the_users_value():
    environ: dict[str, str] = {}
    limit_native_thread_pools(environ)
    assert environ == {"OPENBLAS_NUM_THREADS": OPENBLAS_THREADS}
    environ = {"OPENBLAS_NUM_THREADS": "12"}
    limit_native_thread_pools(environ)
    assert environ["OPENBLAS_NUM_THREADS"] == "12"


def test_the_entry_point_imports_the_package_before_anything_else():
    tree = ast.parse(Path("cdmw_app.py").read_text(encoding="utf-8"))
    main_block = next(node for node in tree.body if isinstance(node, ast.If))
    first = main_block.body[0]
    assert isinstance(first, ast.Import) and [alias.name for alias in first.names] == ["cdmw"]


def test_the_tests_import_the_package_first():
    tree = ast.parse(Path("tests/conftest.py").read_text(encoding="utf-8"))
    imports = [node for node in tree.body if isinstance(node, (ast.Import, ast.ImportFrom))
               and not (isinstance(node, ast.ImportFrom) and node.module == "__future__")]
    assert isinstance(imports[0], ast.Import) and imports[0].names[0].name == "cdmw"


def test_importing_the_package_sets_the_bound_before_numpy():
    code = "import os, sys; import cdmw; print(os.environ.get('OPENBLAS_NUM_THREADS'), 'numpy' in sys.modules)"
    environ = {key: value for key, value in os.environ.items() if key != "OPENBLAS_NUM_THREADS"}
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True, env=environ,
                            cwd=os.getcwd())
    assert result.stdout.split() == [OPENBLAS_THREADS, "False"]


def test_nothing_imported_before_it_loads_numpy():
    code = ("import sys; import cdmw.app.native_threads; from multiprocessing import freeze_support; "
            "import cdmw.app.app_folder; import cdmw.app.bootstrap; print('numpy' in sys.modules)")
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True, cwd=os.getcwd())
    assert result.stdout.strip() == "False"


@pytest.mark.skipif(sys.platform != "win32", reason="reads the Windows commit charge")
def test_the_bounded_pool_commits_far_less_than_one_thread_per_core():
    code = r'''
import ctypes, ctypes.wintypes as wt
import cdmw
import numpy
class PMC(ctypes.Structure):
    _fields_ = [("cb", wt.DWORD), ("faults", wt.DWORD)] + [(n, ctypes.c_size_t) for n in ("pws", "ws", "a", "b", "c", "d", "commit", "peak")]
k = ctypes.WinDLL("kernel32"); p = ctypes.WinDLL("psapi")
k.GetCurrentProcess.restype = ctypes.c_void_p
p.GetProcessMemoryInfo.argtypes = (ctypes.c_void_p, ctypes.POINTER(PMC), wt.DWORD)
m = PMC(); m.cb = ctypes.sizeof(PMC); p.GetProcessMemoryInfo(k.GetCurrentProcess(), ctypes.byref(m), m.cb)
print(m.commit // (1 << 20))
'''
    environ = {key: value for key, value in os.environ.items() if key != "OPENBLAS_NUM_THREADS"}
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True, env=environ,
                            cwd=os.getcwd())
    # One thread per core committed about 500 MiB at import on a 24-thread machine; two commit about 50.
    assert int(result.stdout.strip()) < 120
