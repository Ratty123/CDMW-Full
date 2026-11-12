"""Bound the thread pools that native numerical libraries start when they load.

numpy's wheel carries OpenBLAS, which starts one thread per core (24 on the
development machine) when numpy is imported and commits about 20 MiB for each:
490 MiB of commit in every CDMW Python process before any work is done, and
20 to 120 ms of import time (P16 stage 2 report, "numpy without OpenBLAS").
CDMW's matrix work is small (3 x 3 and 4 x 4 transforms, N x 3 vertex sets, one
texture-sized UV bake), so four threads lose almost nothing.

Must run before anything imports numpy. Child processes inherit the setting.
A value the user has set is kept.
"""

from __future__ import annotations

import os

OPENBLAS_THREADS = "4"


def limit_native_thread_pools(environ=None) -> None:
    target = os.environ if environ is None else environ
    target.setdefault("OPENBLAS_NUM_THREADS", OPENBLAS_THREADS)


__all__ = ["OPENBLAS_THREADS", "limit_native_thread_pools"]
