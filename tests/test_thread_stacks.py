"""Stack samples must not keep the sampled thread's locals alive.

``sys._current_frames()`` hands out live frames; a function that returns while
its frame is held leaves its locals to die later, on the holder's thread. The
automation bridge's ``ui_stack`` and ``thread_stacks`` and the hang watchdog's
thread dump read the stacks as text instead (cdmw/services/thread_stacks.py).
"""

from __future__ import annotations

import ast
import threading
import weakref
from pathlib import Path

from cdmw.services.thread_stacks import parse_faulthandler_traceback, python_thread_stacks

ROOT = Path(__file__).resolve().parents[1]


class _Local:
    pass


def _thread_parked_in_a_function_with_a_local():
    """A thread waiting inside a function that holds a local object; returns the thread,
    the event that lets the function return, and what the local's finalizer recorded."""

    parked = threading.Event()
    release = threading.Event()
    died_on: list[int] = []
    refs: list[weakref.ref] = []

    def function_with_a_local_for_the_sampler():
        local = _Local()
        refs.append(weakref.ref(local, lambda _ref: died_on.append(threading.get_ident())))
        parked.set()
        release.wait(10)

    thread = threading.Thread(target=function_with_a_local_for_the_sampler, name="sampled-worker")
    thread.start()
    assert parked.wait(10)
    return thread, release, died_on


def test_a_sample_names_each_thread_and_its_calls_outermost_first():
    thread, release, _died_on = _thread_parked_in_a_function_with_a_local()
    try:
        stacks = python_thread_stacks()
    finally:
        release.set()
        thread.join(10)
    by_ident = {stack.ident: stack for stack in stacks}
    worker = by_ident[thread.ident]
    assert worker.name == "sampled-worker" and not worker.current
    names = [frame.name for frame in worker.frames]
    parked = worker.frames[names.index("function_with_a_local_for_the_sampler")]
    assert parked.filename.endswith("test_thread_stacks.py") and parked.lineno > 0
    assert names.index("function_with_a_local_for_the_sampler") < names.index("wait")
    own = by_ident[threading.get_ident()]
    assert own.current
    names = [frame.name for frame in own.frames]
    assert names.index("test_a_sample_names_each_thread_and_its_calls_outermost_first") < names.index(
        "python_thread_stacks")


def test_a_held_sample_does_not_keep_a_returned_functions_locals_alive():
    thread, release, died_on = _thread_parked_in_a_function_with_a_local()
    held = python_thread_stacks()  # kept until the end, as a caller formatting it would
    release.set()
    thread.join(10)
    assert died_on == [thread.ident], "the local outlived its function, or died on another thread"
    assert any(stack.ident == thread.ident for stack in held)


def test_the_bridge_and_the_thread_dump_do_not_keep_locals_alive_either():
    from cdmw.automation.bridge import AutomationBridge
    from cdmw.services.diagnostics_service import format_thread_dump

    thread, release, died_on = _thread_parked_in_a_function_with_a_local()
    held = (AutomationBridge._ui_stack(), AutomationBridge._thread_stacks(), format_thread_dump())
    release.set()
    thread.join(10)
    assert died_on == [thread.ident]
    rows = [row for row in held[1] if row["name"] == "sampled-worker"]
    assert rows and any("function_with_a_local_for_the_sampler" in line for line in rows[0]["frames"])
    assert "--- Thread sampled-worker" in held[2]
    assert "function_with_a_local_for_the_sampler" in held[2]


def test_faulthandler_text_is_parsed_into_threads():
    text = (
        'Thread 0x000049bc [w\\xf6rker] (most recent call first):\n'
        '  File "C:\\\\app\\\\worker.py", line 3 in run\n'
        '  File "C:\\\\py\\\\threading.py", line 1024 in _bootstrap\n'
        '\n'
        'Current thread 0x0000b330 (most recent call first):\n'
        '  File "C:\\\\app\\\\deep.py", line 9 in inner\n'
        '  ...\n'
        '\n'
        'Thread 0x00000010 (most recent call first):\n'
        '  <no Python frame>\n'
    )
    worker, current, bare = parse_faulthandler_traceback(text)
    assert (worker.ident, worker.name, worker.current, worker.truncated) == (0x49BC, "w\\xf6rker", False, False)
    assert [(frame.name, frame.lineno) for frame in worker.frames] == [("_bootstrap", 1024), ("run", 3)]
    assert current.current and current.truncated and current.frames[0].name == "inner"
    assert bare.frames == ()


def test_cdmw_reads_other_threads_stacks_only_as_text():
    callers = []
    for path in sorted((ROOT / "cdmw").rglob("*.py")):
        source = path.read_text(encoding="utf-8")
        if "_current_frames" not in source:
            continue
        for node in ast.walk(ast.parse(source)):
            if isinstance(node, ast.Attribute) and node.attr == "_current_frames":
                callers.append(f"{path.relative_to(ROOT).as_posix()}:{node.lineno}")
    assert not callers, callers
