"""The link between the running app and its MCP bridge (P13 stage C, design record 2.2).

An MCP client starts ``CDMW.exe --mcp-bridge``; the bridge speaks MCP on its
stdin and stdout and relays every message over a named pipe to the app that
is already open. The pipe:

* is ``\\\\.\\pipe\\cdmw-mcp-<scope>``, the scope a hash of the Windows user and
  the CDMW folder, so two copies of CDMW (or a test profile) never answer
  each other's clients;
* refuses remote clients and clients of another user (``automation.pipe``'s
  listener), and, as CDMW Next does, is created with a protected DACL that
  grants the current user alone;
* takes one connected app at a time, as CDMW Next does;
* wants the per-session token from ``workspace\\ai-connection.token``, a file
  only the current user can read, written when "Allow AI connections" is
  turned on and deleted when it is turned off. CDMW Next has no token; the
  design record adds one, so a local process of the same user still has to
  read that file.

Standard library and ``automation.pipe`` only; no Qt.
"""

from __future__ import annotations

import ctypes
import hashlib
import os
import secrets
import threading
from collections.abc import Callable
from ctypes import wintypes
from pathlib import Path

from cdmw.automation import pipe as automation_pipe
from cdmw.automation.pipe import LocalPipeServer, recv_json, send_json

PIPE_PREFIX = "\\\\.\\pipe\\cdmw-mcp-"
TOKEN_FILENAME = "ai-connection.token"
TOKEN_BYTES = 32
#: The bridge waits this long for the app, as CDMW Next's does (about 5 s).
CONNECT_ATTEMPTS = 50
CONNECT_INTERVAL_S = 0.1
BUSY_MESSAGE = "Another app is connected to CDMW. Close it, or its MCP server, and try again."


class _SecurityAttributes(ctypes.Structure):
    _fields_ = [("nLength", wintypes.DWORD), ("lpSecurityDescriptor", ctypes.c_void_p),
                ("bInheritHandle", wintypes.BOOL)]


def _advapi32():
    advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
    advapi32.ConvertSidToStringSidW.argtypes = (ctypes.c_void_p, ctypes.POINTER(ctypes.c_wchar_p))
    advapi32.ConvertSidToStringSidW.restype = wintypes.BOOL
    advapi32.ConvertStringSecurityDescriptorToSecurityDescriptorW.argtypes = (
        wintypes.LPCWSTR, wintypes.DWORD, ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(wintypes.ULONG))
    advapi32.ConvertStringSecurityDescriptorToSecurityDescriptorW.restype = wintypes.BOOL
    advapi32.GetNamedSecurityInfoW.argtypes = (
        wintypes.LPCWSTR, ctypes.c_int, wintypes.DWORD, ctypes.c_void_p, ctypes.c_void_p,
        ctypes.POINTER(ctypes.c_void_p), ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p))
    advapi32.GetNamedSecurityInfoW.restype = wintypes.DWORD
    advapi32.ConvertSecurityDescriptorToStringSecurityDescriptorW.argtypes = (
        ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD, ctypes.POINTER(ctypes.c_wchar_p),
        ctypes.POINTER(wintypes.ULONG))
    advapi32.ConvertSecurityDescriptorToStringSecurityDescriptorW.restype = wintypes.BOOL
    return advapi32


def _local_free(pointer) -> None:
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.LocalFree.argtypes = (ctypes.c_void_p,)
    kernel32.LocalFree(pointer)


def current_user_sid() -> str:
    """This process's user as an SID string (``S-1-5-21-...``)."""

    raw = automation_pipe._token_user_sid(automation_pipe._apis()[1].GetCurrentProcess())
    if not raw:
        raise OSError("The Windows user of this process could not be read.")
    buffer = ctypes.create_string_buffer(raw, len(raw))
    text = ctypes.c_wchar_p()
    if not _advapi32().ConvertSidToStringSidW(ctypes.cast(buffer, ctypes.c_void_p), ctypes.byref(text)):
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        return str(text.value)
    finally:
        _local_free(text)


def user_only_sddl() -> str:
    """A protected DACL that grants the current user full access and nobody else."""

    return f"D:P(A;;GA;;;{current_user_sid()})"


class _Descriptor:
    """A security descriptor and its SECURITY_ATTRIBUTES, freed when dropped."""

    def __init__(self, sddl: str) -> None:
        self.pointer = ctypes.c_void_p()
        if not _advapi32().ConvertStringSecurityDescriptorToSecurityDescriptorW(sddl, 1, ctypes.byref(self.pointer),
                                                                                None):
            raise ctypes.WinError(ctypes.get_last_error())
        self.attributes = _SecurityAttributes(ctypes.sizeof(_SecurityAttributes), self.pointer, False)

    @property
    def address(self) -> int:
        return ctypes.addressof(self.attributes)

    def __del__(self) -> None:
        if self.pointer:
            _local_free(self.pointer)
            self.pointer = ctypes.c_void_p()


def dacl_sddl(path: str | os.PathLike[str]) -> str:
    """The DACL of a file or pipe as SDDL, for tests and diagnostics."""

    advapi32 = _advapi32()
    descriptor = ctypes.c_void_p()
    dacl = ctypes.c_void_p()
    # SE_FILE_OBJECT, DACL_SECURITY_INFORMATION
    error = advapi32.GetNamedSecurityInfoW(os.fspath(path), 1, 0x4, None, None, ctypes.byref(dacl), None,
                                           ctypes.byref(descriptor))
    if error:
        raise ctypes.WinError(error)
    try:
        text = ctypes.c_wchar_p()
        if not advapi32.ConvertSecurityDescriptorToStringSecurityDescriptorW(descriptor, 1, 0x4, ctypes.byref(text),
                                                                             None):
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            return str(text.value)
        finally:
            _local_free(text)
    finally:
        _local_free(descriptor)


# ----- where -----------------------------------------------------------------
def connection_scope() -> str:
    """A short name for this Windows user and this CDMW folder."""

    from cdmw.app.app_folder import cdmw_folder

    folder = os.path.normcase(str(cdmw_folder()))
    return hashlib.sha256(f"{current_user_sid()}|{folder}".encode("utf-8")).hexdigest()[:24]


def pipe_address() -> str:
    return PIPE_PREFIX + connection_scope()


def token_path() -> Path:
    from cdmw.app.app_folder import workspace_folder

    return workspace_folder() / TOKEN_FILENAME


# ----- the token file --------------------------------------------------------
def new_token() -> bytes:
    return secrets.token_bytes(TOKEN_BYTES)


def write_token_file(path: Path, token: bytes) -> Path:
    """Write ``token`` as hex to a new file only the current user can open."""

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    remove_token_file(path)
    descriptor = _Descriptor(f"D:P(A;;FA;;;{current_user_sid()})")
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateFileW.argtypes = (wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p,
                                     wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE)
    kernel32.CreateFileW.restype = wintypes.HANDLE
    kernel32.WriteFile.argtypes = (wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD,
                                   ctypes.POINTER(wintypes.DWORD), ctypes.c_void_p)
    kernel32.WriteFile.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
    # GENERIC_WRITE, no sharing, CREATE_NEW (so the DACL applies), FILE_ATTRIBUTE_NORMAL
    handle = kernel32.CreateFileW(str(path), 0x40000000, 0, descriptor.address, 1, 0x80, None)
    if handle in (None, wintypes.HANDLE(-1).value):
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        data = token.hex().encode("ascii")
        written = wintypes.DWORD()
        if not kernel32.WriteFile(handle, data, len(data), ctypes.byref(written), None) or written.value != len(data):
            raise ctypes.WinError(ctypes.get_last_error())
    finally:
        kernel32.CloseHandle(handle)
    return path


def read_token_file(path: Path) -> bytes | None:
    try:
        text = Path(path).read_text(encoding="ascii").strip()
        token = bytes.fromhex(text)
    except (OSError, ValueError):
        return None
    return token if len(token) >= 16 else None


def remove_token_file(path: Path) -> None:
    try:
        Path(path).unlink()
    except FileNotFoundError:
        pass


# ----- the app's side of the pipe ---------------------------------------------
if os.name == "nt":
    import _winapi
    from multiprocessing import connection

    class _UserOnlyPipeListener(automation_pipe._LocalPipeListener):
        """``automation.pipe``'s listener, with a DACL for the current user alone."""

        def __init__(self, address: str) -> None:
            self._descriptor = _Descriptor(user_only_sddl())
            super().__init__(address)

        def _new_handle(self, first=False):
            flags = _winapi.PIPE_ACCESS_DUPLEX | _winapi.FILE_FLAG_OVERLAPPED
            if first:
                flags |= _winapi.FILE_FLAG_FIRST_PIPE_INSTANCE
            return _winapi.CreateNamedPipe(
                self._address, flags,
                _winapi.PIPE_TYPE_MESSAGE | _winapi.PIPE_READMODE_MESSAGE | _winapi.PIPE_WAIT
                | automation_pipe.PIPE_REJECT_REMOTE_CLIENTS,
                _winapi.PIPE_UNLIMITED_INSTANCES, connection.BUFSIZE, connection.BUFSIZE,
                _winapi.NMPWAIT_WAIT_FOREVER, self._descriptor.address,
            )


class McpPipeServer(LocalPipeServer):
    """``LocalPipeServer`` with the user-only DACL, one app at a time, and a stop that ends connections.

    It reuses the automation listener's accept loop and its admission (another
    user, then the token handshake, refused before anything is read). After
    the handshake the app sends one hello: ``{"ok": true}``, or ``{"ok":
    false, "error": ...}`` when another app is connected.
    """

    def __init__(self, address: str, token: bytes, handler: Callable[[object], None],
                 refused: Callable[[str], None] | None = None) -> None:
        if os.name != "nt":
            raise RuntimeError("AI connections are Windows-only.")
        # Not LocalPipeServer.__init__: its listener would create the first
        # pipe instance with the default DACL.
        self.address = address
        self._token = bytes(token)
        self._serve = handler
        self._handler = self._one_at_a_time
        self._refused = refused or (lambda _reason: None)
        self._stop = threading.Event()
        self._listener = _UserOnlyPipeListener(address)
        self._thread = threading.Thread(target=self._accept_loop, name="cdmw-mcp-listener", daemon=True)
        self._lock = threading.Lock()
        self._active: list[object] = []

    @property
    def connected(self) -> int:
        with self._lock:
            return len(self._active)

    def _one_at_a_time(self, conn) -> None:
        with self._lock:
            busy = bool(self._active) or self._stop.is_set()
            if not busy:
                self._active.append(conn)
        if busy:
            self._refused("another app is connected")
            try:
                send_json(conn, {"ok": False, "error": BUSY_MESSAGE})
            except OSError:
                pass
            return
        try:
            send_json(conn, {"ok": True})
            self._serve(conn)
        finally:
            with self._lock:
                if conn in self._active:
                    self._active.remove(conn)

    def stop(self) -> None:
        """Stop listening and end the connected app's connection."""

        super().stop()
        with self._lock:
            active = list(self._active)
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.DisconnectNamedPipe.argtypes = (wintypes.HANDLE,)
        kernel32.CancelIoEx.argtypes = (wintypes.HANDLE, ctypes.c_void_p)
        for conn in active:
            # Not conn.close(): its own thread is reading it and closes it when
            # the read fails. Disconnecting tells the bridge at once.
            try:
                handle = wintypes.HANDLE(conn.fileno())
            except (OSError, ValueError):
                continue
            kernel32.DisconnectNamedPipe(handle)
            kernel32.CancelIoEx(handle, None)


__all__ = [
    "BUSY_MESSAGE", "McpPipeServer", "connection_scope", "dacl_sddl", "new_token", "pipe_address",
    "read_token_file", "recv_json", "remove_token_file", "send_json", "token_path", "user_only_sddl",
    "write_token_file",
]
