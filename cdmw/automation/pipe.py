"""A named pipe for the current user that refuses remote clients.

Python's ``multiprocessing.connection`` gives the pipe and an HMAC handshake
on a shared key; this adds what it lacks: ``PIPE_REJECT_REMOTE_CLIENTS`` on
every pipe instance and a check that the client process runs as this user.
Messages are JSON, never pickles.
"""

from __future__ import annotations

import ctypes
import json
import os
import threading
from collections.abc import Callable
from ctypes import wintypes
from multiprocessing import connection

PIPE_REJECT_REMOTE_CLIENTS = 0x00000008
MAX_MESSAGE_BYTES = 16 * 1024 * 1024


def send_json(conn, payload: object) -> None:
    conn.send_bytes(json.dumps(payload, separators=(",", ":"), default=str).encode("utf-8"))


def recv_json(conn) -> object:
    return json.loads(conn.recv_bytes(MAX_MESSAGE_BYTES).decode("utf-8"))


if os.name == "nt":
    import _winapi

    class _LocalPipeListener(connection.PipeListener):
        def _new_handle(self, first=False):
            flags = _winapi.PIPE_ACCESS_DUPLEX | _winapi.FILE_FLAG_OVERLAPPED
            if first:
                flags |= _winapi.FILE_FLAG_FIRST_PIPE_INSTANCE
            return _winapi.CreateNamedPipe(
                self._address, flags,
                _winapi.PIPE_TYPE_MESSAGE | _winapi.PIPE_READMODE_MESSAGE | _winapi.PIPE_WAIT
                | PIPE_REJECT_REMOTE_CLIENTS,
                _winapi.PIPE_UNLIMITED_INSTANCES, connection.BUFSIZE, connection.BUFSIZE,
                _winapi.NMPWAIT_WAIT_FOREVER, _winapi.NULL,
            )


def _apis():
    advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    advapi32.OpenProcessToken.argtypes = (wintypes.HANDLE, wintypes.DWORD, ctypes.POINTER(wintypes.HANDLE))
    advapi32.OpenProcessToken.restype = wintypes.BOOL
    advapi32.GetTokenInformation.argtypes = (wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD,
                                             ctypes.POINTER(wintypes.DWORD))
    advapi32.GetTokenInformation.restype = wintypes.BOOL
    advapi32.GetLengthSid.argtypes = (ctypes.c_void_p,)
    advapi32.GetLengthSid.restype = wintypes.DWORD
    kernel32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
    kernel32.CloseHandle.restype = wintypes.BOOL
    kernel32.GetCurrentProcess.argtypes = ()
    kernel32.GetCurrentProcess.restype = wintypes.HANDLE
    kernel32.GetNamedPipeClientProcessId.argtypes = (wintypes.HANDLE, ctypes.POINTER(wintypes.ULONG))
    kernel32.GetNamedPipeClientProcessId.restype = wintypes.BOOL
    return advapi32, kernel32


def _token_user_sid(process_handle) -> bytes | None:
    advapi32, kernel32 = _apis()
    token = wintypes.HANDLE()
    if not advapi32.OpenProcessToken(process_handle, 0x0008, ctypes.byref(token)):  # TOKEN_QUERY
        return None
    try:
        size = wintypes.DWORD()
        advapi32.GetTokenInformation(token, 1, None, 0, ctypes.byref(size))  # TokenUser
        buffer = ctypes.create_string_buffer(size.value)
        if not advapi32.GetTokenInformation(token, 1, buffer, size, ctypes.byref(size)):
            return None
        sid = ctypes.cast(buffer, ctypes.POINTER(ctypes.c_void_p))[0]
        length = advapi32.GetLengthSid(ctypes.c_void_p(sid))
        return ctypes.string_at(sid, length)
    finally:
        kernel32.CloseHandle(token)


def client_runs_as_this_user(conn) -> bool:
    """Whether the process at the other end of ``conn`` has this process's user."""

    if os.name != "nt":
        return False
    _advapi32, kernel32 = _apis()
    pid = wintypes.ULONG()
    if not kernel32.GetNamedPipeClientProcessId(wintypes.HANDLE(conn.fileno()), ctypes.byref(pid)):
        return False
    handle = kernel32.OpenProcess(0x1000, False, pid.value)  # PROCESS_QUERY_LIMITED_INFORMATION
    if not handle:
        return False
    try:
        theirs = _token_user_sid(handle)
    finally:
        kernel32.CloseHandle(handle)
    mine = _token_user_sid(kernel32.GetCurrentProcess())
    return theirs is not None and theirs == mine


class LocalPipeServer:
    """Accept connections on a thread; hand each one to ``handler`` on its own."""

    def __init__(self, address: str, token: bytes, handler: Callable[[object], None],
                 refused: Callable[[str], None] | None = None) -> None:
        if os.name != "nt":
            raise RuntimeError("The automation pipe is Windows-only.")
        self.address = address
        self._token = bytes(token)
        self._handler = handler
        self._refused = refused or (lambda _reason: None)
        self._stop = threading.Event()
        self._listener = _LocalPipeListener(address)
        self._thread = threading.Thread(target=self._accept_loop, name="cdmw-automation-listener", daemon=True)

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        try:
            # Wake the blocking accept; this client fails the handshake.
            connection.Client(self.address, family="AF_PIPE").close()
        except Exception:
            pass
        try:
            self._listener.close()
        except Exception:
            pass

    def _accept_loop(self) -> None:
        while not self._stop.is_set():
            try:
                conn = self._listener.accept()
            except Exception:
                if self._stop.is_set():
                    return
                continue
            if self._stop.is_set():
                conn.close()
                return
            threading.Thread(target=self._admit, args=(conn,), name="cdmw-automation-client", daemon=True).start()

    def _admit(self, conn) -> None:
        # Refused before any command is read: another user first, then a
        # client that cannot answer the token challenge.
        try:
            if not client_runs_as_this_user(conn):
                self._refused("client is not this user")
                conn.close()
                return
            connection.deliver_challenge(conn, self._token)
            connection.answer_challenge(conn, self._token)
        except Exception as exc:
            self._refused(f"handshake failed: {type(exc).__name__}")
            conn.close()
            return
        try:
            self._handler(conn)
        finally:
            conn.close()
