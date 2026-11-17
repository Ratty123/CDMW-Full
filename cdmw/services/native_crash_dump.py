"""A small minidump of CDMW when it dies of a native fault (Windows).

``faulthandler`` writes every thread's Python stack to native_fault_current.log,
but on Windows it cannot read the C stack ("<cannot get C stack on this
system>"), and a crash inside Qt or PySide shows only "<no Python frame>". This
adds an unhandled-exception filter that writes a minidump next to that log, so
the crashing thread's C stack can be read with a debugger afterwards.

The dump holds every thread's stack, the loaded modules, thread information and
the memory the stacks point at (MiniDumpNormal with thread info, unloaded modules
and indirectly referenced memory: a few megabytes, not the whole heap). It is
written only when the process dies of an exception nothing handled, after
faulthandler (a vectored handler, so it runs first) has written its log. The
filter then hands the exception on unchanged, so the process still ends with its
own exit code (0xC0000005 for an access violation). Only the newest few dumps
are kept.

Beside the dump, a text file with the same name and ``.txt`` says where the
fault was (module and offset) and names, for each register of the faulting
thread and the top of its stack, the Python object it points at: its type and,
for a PySide wrapper, the C++ address it stands for. A debugger cannot do that
from the dump, which holds no Python type names. The memory is read with
ReadProcessMemory, so a stale or garbage pointer gives "not readable", never a
second fault. It names, for example, the old wrapper a stale binding entry gave
PySide when a new QObject landed on a freed C++ address (the Item Finder warm-up
crash of 2026-11-17 in ``QThread(self)``).

Set CDMW_NATIVE_CRASH_DUMP=0 to leave it off. The filter is Python code called
through ctypes, so it needs the GIL: everything it uses is prepared here, and
the call itself is a handful of Win32 calls. The text file is written after the
dump, so a failure while writing it cannot cost the dump.
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

DUMP_PREFIX = "native-crash-"
DUMP_SUFFIX = ".dmp"
#: Dumps kept in the folder, this run's included.
KEEP_DUMPS = 3

REPORT_SUFFIX = ".txt"

# MiniDumpNormal | MiniDumpWithIndirectlyReferencedMemory | MiniDumpWithUnloadedModules
# | MiniDumpWithThreadInfo
DUMP_TYPE = 0x00000000 | 0x00000040 | 0x00000020 | 0x00001000
#: Stack slots above the faulting thread's stack pointer looked at for Python objects.
REPORT_STACK_SLOTS = 96
_EXCEPTION_CONTINUE_SEARCH = 0
_GENERIC_WRITE = 0x40000000
_CREATE_ALWAYS = 2
_FILE_ATTRIBUTE_NORMAL = 0x80

#: Kept for the life of the process: the filter, its callback object and what it uses.
_installed: dict[str, object] = {}


def native_crash_dumps(directory: Path) -> list[Path]:
    """The dumps in ``directory``, newest first."""

    try:
        found = [path for path in Path(directory).glob(f"{DUMP_PREFIX}*{DUMP_SUFFIX}") if path.is_file()]
    except OSError:
        return []
    return sorted(found, key=lambda path: (path.stat().st_mtime, path.name), reverse=True)


def native_crash_report_path(dump: Path) -> Path:
    """The text file written beside ``dump``."""

    return Path(dump).with_suffix(REPORT_SUFFIX)


def prune_native_crash_dumps(directory: Path, *, keep: int = KEEP_DUMPS) -> list[Path]:
    removed = []
    for path in native_crash_dumps(directory)[max(0, int(keep)):]:
        for doomed in (path, native_crash_report_path(path)):
            try:
                doomed.unlink()
                removed.append(doomed)
            except OSError:
                pass
    return removed


def native_crash_dump_path(directory: Path, *, now: float | None = None, pid: int | None = None) -> Path:
    stamp = time.strftime("%Y%m%d-%H%M%S", time.localtime(time.time() if now is None else now))
    return Path(directory) / f"{DUMP_PREFIX}{stamp}-{os.getpid() if pid is None else pid}{DUMP_SUFFIX}"


def install_native_crash_dump(directory: Path, *, keep: int = KEEP_DUMPS) -> Path | None:
    """Write a minidump into ``directory`` if the process dies of a native fault.

    Returns the path the dump would be written to, or None when it is not
    installed (not Windows, turned off, already installed, or the Win32 calls
    are missing)."""

    if sys.platform != "win32" or os.environ.get("CDMW_NATIVE_CRASH_DUMP", "1").strip() == "0":
        return None
    if "filter" in _installed:
        return None
    try:
        directory = Path(directory)
        directory.mkdir(parents=True, exist_ok=True)
        # The dump about to be written counts: keep room for it.
        prune_native_crash_dumps(directory, keep=max(0, int(keep) - 1))
        return _install(native_crash_dump_path(directory))
    except Exception:  # noqa: BLE001 - crash evidence must never stop the app starting
        return None


#: x64 CONTEXT: where each general register is kept.
_CONTEXT_REGISTERS = (
    ("rip", 0xF8), ("rax", 0x78), ("rbx", 0x90), ("rcx", 0x80), ("rdx", 0x88), ("rsi", 0xA8),
    ("rdi", 0xB0), ("rbp", 0xA0), ("rsp", 0x98), ("r8", 0xB8), ("r9", 0xC0), ("r10", 0xC8),
    ("r11", 0xD0), ("r12", 0xD8), ("r13", 0xE0), ("r14", 0xE8), ("r15", 0xF0),
)
_EXCEPTION_NAMES = {
    0xC0000005: "access violation",
    0xC0000374: "heap corruption",
    0xC00000FD: "stack overflow",
    0xC0000409: "stack buffer overrun (fail fast)",
    0xC000001D: "illegal instruction",
    0xC0000094: "integer divide by zero",
    0x80000003: "breakpoint",
}
_USER_SPACE_END = 1 << 47


class _CrashReporter:
    """Names what the faulting thread's registers and stack point at.

    Memory is read with ReadProcessMemory: a stale or garbage pointer reads as
    nothing, never as a second fault."""

    def __init__(self, kernel32, current_process) -> None:
        import ctypes
        from ctypes import wintypes

        self._ctypes = ctypes
        read = kernel32.ReadProcessMemory
        read.argtypes = [wintypes.HANDLE, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_size_t,
                         ctypes.POINTER(ctypes.c_size_t)]
        read.restype = wintypes.BOOL
        module_from_address = kernel32.GetModuleHandleExW
        module_from_address.argtypes = [wintypes.DWORD, ctypes.c_void_p, ctypes.POINTER(wintypes.HMODULE)]
        module_from_address.restype = wintypes.BOOL
        module_name = kernel32.GetModuleFileNameW
        module_name.argtypes = [wintypes.HMODULE, wintypes.LPWSTR, wintypes.DWORD]
        module_name.restype = wintypes.DWORD
        self._read = read
        self._module_from_address = module_from_address
        self._module_name = module_name
        self._process = current_process()
        self._word = ctypes.c_uint64()
        self._count = ctypes.c_size_t()
        self._text = ctypes.create_string_buffer(256)
        self._name = ctypes.create_unicode_buffer(520)
        self._module = wintypes.HMODULE()
        self._type_id = id(type)
        self._x64 = ctypes.sizeof(ctypes.c_void_p) == 8

    def _u64(self, address: int | None) -> int | None:
        if address is None or address < 0x10000 or address >= _USER_SPACE_END:
            return None
        if not self._read(self._process, address, self._ctypes.byref(self._word), 8,
                          self._ctypes.byref(self._count)) or self._count.value != 8:
            return None
        return int(self._word.value)

    def _u32(self, address: int | None) -> int | None:
        value = self._u64(address)
        return None if value is None else value & 0xFFFFFFFF

    def _c_string(self, address: int | None) -> str | None:
        if address is None or address < 0x10000 or address >= _USER_SPACE_END:
            return None
        self._count.value = 0
        # Shorter reads too: a name close to the end of a page must not fail as a whole.
        for size in (255, 128, 64, 32):
            if self._read(self._process, address, self._text, size, self._ctypes.byref(self._count)):
                break
        raw = self._text.raw[: self._count.value].split(b"\0", 1)[0]
        if not raw or any(byte < 0x20 or byte > 0x7E for byte in raw):
            return None
        return raw.decode("ascii")

    def _crash_module_offset(self, address: int) -> str | None:
        if address < 0x10000 or address >= _USER_SPACE_END:
            return None
        # GET_MODULE_HANDLE_EX_FLAG_FROM_ADDRESS | GET_MODULE_HANDLE_EX_FLAG_UNCHANGED_REFCOUNT
        if not self._module_from_address(0x4 | 0x2, address, self._ctypes.byref(self._module)):
            return None
        base = int(self._module.value or 0)
        length = self._module_name(self._module, self._name, 520)
        name = self._name.value[:length].replace("/", "\\").rsplit("\\", 1)[-1] if length else "?"
        return f"{name}+0x{address - base:x}"

    def _crash_python_object(self, address: int, shiboken_meta: int) -> str | None:
        """What the Python object at ``address`` is, or None when it does not look like one."""

        if address % 8:
            return None
        refcount = self._u64(address)
        ob_type = self._u64(address + 8)
        if not refcount or ob_type is None:
            return None
        meta = self._u64(ob_type + 8)
        if meta is None or self._type_id not in (meta, self._u64(meta + 8)):
            return None
        type_name = self._c_string(self._u64(ob_type + 24))
        if type_name is None:
            return None
        text = f"Python object of type {type_name!r} (refcount {refcount})"
        if ob_type == self._type_id or (shiboken_meta and ob_type == shiboken_meta):
            own = self._c_string(self._u64(address + 24))
            if own:
                text = f"the Python type {own!r} (a {type_name})"
        elif shiboken_meta and meta == shiboken_meta:
            private = self._u64(address + 32)  # SbkObject: head, ob_dict, weakreflist, d
            cpp = self._u64(self._u64(private))  # d->cptr[0]
            flags = self._u32(private + 8) if private is not None else None
            if cpp is not None and flags is not None:
                states = [label for bit, label in ((0, "owned by Python"), (1, "made by Python"),
                                                   (2, "valid"), (3, "constructed")) if flags & (1 << bit)]
                text += f", a PySide wrapper of C++ 0x{cpp:x} ({', '.join(states) or 'invalid'})"
        return text

    def _crash_describe(self, value: int, shiboken_meta: int) -> str:
        return self._crash_python_object(value, shiboken_meta) or self._crash_module_offset(value) or ""

    def write(self, target: Path, pointers: int, thread_id: int) -> None:
        shiboken = sys.modules.get("shiboken6.Shiboken")
        base = getattr(shiboken, "Object", None) if shiboken is not None else None
        shiboken_meta = id(type(base)) if base is not None else 0
        lines = [f"CDMW native crash: process {os.getpid()}, thread {thread_id} (0x{thread_id:x}), "
                 f"{time.strftime('%Y-%m-%d %H:%M:%S')}"]
        record = self._u64(pointers) if pointers else None
        context = self._u64(pointers + 8) if pointers else None
        if record is not None:
            code = self._u32(record) or 0
            address = self._u64(record + 0x10) or 0
            where = self._crash_module_offset(address) or ""
            lines.append(f"exception 0x{code:08X} ({_EXCEPTION_NAMES.get(code, 'unknown')}) "
                         f"at 0x{address:x} {where}".rstrip())
            if code == 0xC0000005 and (self._u32(record + 0x18) or 0) >= 2:
                kind = {0: "read of", 1: "write to", 8: "execution at"}.get(
                    self._u64(record + 0x20) or 0, "access to")
                lines.append(f"  {kind} 0x{(self._u64(record + 0x28) or 0):x}")
        if context is None or not self._x64:
            lines.append("registers: not readable")
        else:
            lines.append("registers (a Python object is named by its type, a code address by its module):")
            for name, offset in _CONTEXT_REGISTERS:
                value = self._u64(context + offset)
                if value is not None:
                    lines.append(f"  {name:<4}= 0x{value:016x}  {self._crash_describe(value, shiboken_meta)}".rstrip())
            rsp = self._u64(context + 0x98)
            if rsp is not None:
                lines.append(f"stack: the slots of the first {REPORT_STACK_SLOTS} above rsp that point at "
                             "a Python object or into a module:")
                for slot in range(REPORT_STACK_SLOTS):
                    value = self._u64(rsp + slot * 8)
                    if value is None:
                        break
                    found = self._crash_describe(value, shiboken_meta)
                    if found:
                        lines.append(f"  rsp+0x{slot * 8:03x} = 0x{value:016x}  {found}")
        with open(target, "w", encoding="utf-8") as handle:
            handle.write("\n".join(lines) + "\n")


def _install(path: Path) -> Path:
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32")
    dbghelp = ctypes.WinDLL("dbghelp")

    class MinidumpExceptionInformation(ctypes.Structure):
        _pack_ = 4  # dbghelp.h packs its structures to four bytes
        _fields_ = [("ThreadId", wintypes.DWORD), ("ExceptionPointers", ctypes.c_void_p),
                    ("ClientPointers", wintypes.BOOL)]

    filter_type = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p)

    create_file = kernel32.CreateFileW
    create_file.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p,
                            wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    create_file.restype = wintypes.HANDLE
    close_handle = kernel32.CloseHandle
    close_handle.argtypes = [wintypes.HANDLE]
    close_handle.restype = wintypes.BOOL
    current_process = kernel32.GetCurrentProcess
    current_process.argtypes = []
    current_process.restype = wintypes.HANDLE
    current_thread_id = kernel32.GetCurrentThreadId
    current_thread_id.argtypes = []
    current_thread_id.restype = wintypes.DWORD
    set_filter = kernel32.SetUnhandledExceptionFilter
    set_filter.argtypes = [ctypes.c_void_p]
    set_filter.restype = ctypes.c_void_p
    write_dump = dbghelp.MiniDumpWriteDump
    write_dump.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.HANDLE, ctypes.c_int,
                           ctypes.POINTER(MinidumpExceptionInformation), ctypes.c_void_p, ctypes.c_void_p]
    write_dump.restype = wintypes.BOOL

    target = str(path)
    report = native_crash_report_path(path)
    reporter = _CrashReporter(kernel32, current_process)
    pid = os.getpid()
    information = MinidumpExceptionInformation()
    information_pointer = ctypes.pointer(information)
    invalid_handle = wintypes.HANDLE(-1).value
    state = {"previous": None, "written": False}

    def on_unhandled_exception(pointers):
        if not state["written"]:
            state["written"] = True  # once: a fault while writing must not loop
            handle = create_file(target, _GENERIC_WRITE, 0, None, _CREATE_ALWAYS, _FILE_ATTRIBUTE_NORMAL, None)
            if handle and handle != invalid_handle:
                information.ThreadId = current_thread_id()
                information.ExceptionPointers = pointers
                information.ClientPointers = False
                write_dump(current_process(), pid, handle, DUMP_TYPE, information_pointer, None, None)
                close_handle(handle)
            try:  # after the dump, so a failure here cannot cost it
                reporter.write(report, pointers or 0, current_thread_id())
            except Exception:  # noqa: BLE001 - the process is ending anyway
                pass
        previous = state["previous"]
        if previous is not None:
            return previous(pointers)
        return _EXCEPTION_CONTINUE_SEARCH

    callback = filter_type(on_unhandled_exception)
    previous = set_filter(ctypes.cast(callback, ctypes.c_void_p))
    if previous:
        state["previous"] = filter_type(previous)
    _installed.update(filter=callback, function=on_unhandled_exception, information=information,
                      pointer=information_pointer, calls=(create_file, close_handle, current_process,
                                                          current_thread_id, write_dump, set_filter),
                      libraries=(kernel32, dbghelp), state=state, path=path, reporter=reporter)
    return path


__all__ = [
    "DUMP_TYPE",
    "install_native_crash_dump",
    "native_crash_dump_path",
    "native_crash_dumps",
    "native_crash_report_path",
    "prune_native_crash_dumps",
]
