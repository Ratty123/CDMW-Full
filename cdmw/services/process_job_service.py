"""Kill-on-close job object that binds owned child processes to this process.

The shell's close path stops every helper it knows about, but that path only
runs on a graceful close. A segfault, a force-kill, or any exit that skips
``atexit`` leaves the .NET and native helpers resident: they hold GPU devices
and archive mappings, and nothing ever reaps them.

A Windows job object closes that hole in the kernel rather than in shutdown
code. This process joins the job at startup and keeps the only handle open, so
the handle closes exactly when this process dies -- by any means -- and the job
terminates every process still assigned to it. Child processes inherit job
membership, so helpers spawned later are covered without registering anywhere.

Processes that are meant to outlive the workbench (the game, external authoring
tools) must opt out with ``CREATE_BREAKAWAY_FROM_JOB``; see
``breakaway_creation_flags``.
"""

from __future__ import annotations

import os
import subprocess


JOB_OBJECT_LIMIT_BREAKAWAY_OK = 0x00000800
JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000
_JOB_OBJECT_EXTENDED_LIMIT_INFORMATION = 9

# The handle must stay open for this process's whole lifetime: closing the last
# handle is what triggers the kill, so a garbage-collected handle would tear the
# helpers down mid-session.
_app_job_handle: int = 0
_app_job_bound: bool | None = None


def _extended_limit_information_type():
    import ctypes
    from ctypes import wintypes

    class BasicLimitInformation(ctypes.Structure):
        _fields_ = [
            ("PerProcessUserTimeLimit", ctypes.c_int64),
            ("PerJobUserTimeLimit", ctypes.c_int64),
            ("LimitFlags", wintypes.DWORD),
            ("MinimumWorkingSetSize", ctypes.c_size_t),
            ("MaximumWorkingSetSize", ctypes.c_size_t),
            ("ActiveProcessLimit", wintypes.DWORD),
            ("Affinity", ctypes.c_void_p),
            ("PriorityClass", wintypes.DWORD),
            ("SchedulingClass", wintypes.DWORD),
        ]

    class IoCounters(ctypes.Structure):
        _fields_ = [
            ("ReadOperationCount", ctypes.c_uint64),
            ("WriteOperationCount", ctypes.c_uint64),
            ("OtherOperationCount", ctypes.c_uint64),
            ("ReadTransferCount", ctypes.c_uint64),
            ("WriteTransferCount", ctypes.c_uint64),
            ("OtherTransferCount", ctypes.c_uint64),
        ]

    class ExtendedLimitInformation(ctypes.Structure):
        _fields_ = [
            ("BasicLimitInformation", BasicLimitInformation),
            ("IoInfo", IoCounters),
            ("ProcessMemoryLimit", ctypes.c_size_t),
            ("JobMemoryLimit", ctypes.c_size_t),
            ("PeakProcessMemoryUsed", ctypes.c_size_t),
            ("PeakJobMemoryUsed", ctypes.c_size_t),
        ]

    return ExtendedLimitInformation


def bind_process_tree_to_app_lifetime() -> bool:
    """Join a kill-on-close job so no owned child can outlive this process.

    Idempotent, and a no-op off Windows. Returns whether the binding is in
    effect; a false return means helpers fall back to the graceful close path
    alone, which is why this is best effort rather than fatal.
    """

    global _app_job_handle, _app_job_bound

    if _app_job_bound is not None:
        return _app_job_bound
    if os.name != "nt":
        _app_job_bound = False
        return False

    import ctypes
    from ctypes import wintypes

    try:
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        create_job_object = kernel32.CreateJobObjectW
        create_job_object.argtypes = (ctypes.c_void_p, wintypes.LPCWSTR)
        create_job_object.restype = wintypes.HANDLE
        set_information_job_object = kernel32.SetInformationJobObject
        set_information_job_object.argtypes = (
            wintypes.HANDLE,
            ctypes.c_int,
            ctypes.c_void_p,
            wintypes.DWORD,
        )
        set_information_job_object.restype = wintypes.BOOL
        assign_process_to_job_object = kernel32.AssignProcessToJobObject
        assign_process_to_job_object.argtypes = (wintypes.HANDLE, wintypes.HANDLE)
        assign_process_to_job_object.restype = wintypes.BOOL
        get_current_process = kernel32.GetCurrentProcess
        get_current_process.argtypes = ()
        get_current_process.restype = wintypes.HANDLE
        close_handle = kernel32.CloseHandle
        close_handle.argtypes = (wintypes.HANDLE,)
        close_handle.restype = wintypes.BOOL

        # An unnamed job with default security is not inheritable, so a child
        # cannot hold the job open past this process's death.
        handle = create_job_object(None, None)
        if not handle:
            _app_job_bound = False
            return False

        information = _extended_limit_information_type()()
        information.BasicLimitInformation.LimitFlags = (
            JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE | JOB_OBJECT_LIMIT_BREAKAWAY_OK
        )
        if not set_information_job_object(
            handle,
            _JOB_OBJECT_EXTENDED_LIMIT_INFORMATION,
            ctypes.byref(information),
            ctypes.sizeof(information),
        ):
            close_handle(handle)
            _app_job_bound = False
            return False

        # Nested jobs are supported from Windows 8 on, so an outer job (a CI
        # runner, a debugger, a terminal that sandboxes its children) does not
        # block this. Where it does fail, the graceful close path still runs.
        if not assign_process_to_job_object(handle, get_current_process()):
            close_handle(handle)
            _app_job_bound = False
            return False
    except (AttributeError, OSError, ValueError):
        _app_job_bound = False
        return False

    _app_job_handle = int(handle)
    _app_job_bound = True
    return True


def app_lifetime_job_is_bound() -> bool:
    """Whether owned children are currently tied to this process's lifetime."""

    return bool(_app_job_bound)


def breakaway_creation_flags() -> int:
    """Creation flags that let a spawned process outlive the workbench.

    Only for processes the user owns rather than the app: the game, and
    external authoring tools launched on the user's behalf. Everything the app
    drives as a helper must stay inside the job.
    """

    # Only meaningful against our own job. If the binding never happened, the
    # app may still sit inside somebody else's job (a CI runner, a sandbox)
    # that withholds JOB_OBJECT_LIMIT_BREAKAWAY_OK -- and there the flag makes
    # CreateProcess fail outright rather than break away.
    if os.name != "nt" or not _app_job_bound:
        return 0
    return int(getattr(subprocess, "CREATE_BREAKAWAY_FROM_JOB", 0x01000000))


__all__ = [
    "JOB_OBJECT_LIMIT_BREAKAWAY_OK",
    "JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE",
    "app_lifetime_job_is_bound",
    "bind_process_tree_to_app_lifetime",
    "breakaway_creation_flags",
]
