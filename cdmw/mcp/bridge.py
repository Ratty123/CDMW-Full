"""``CDMW.exe --mcp-bridge``: the MCP server an AI client starts (P13 stage C).

It relays newline-delimited JSON-RPC between its stdin and stdout and the
running app's pipe, in both directions at once, so the app can send progress
while a call runs and the client can cancel one. When stdin ends it waits
for the replies to the requests already sent, then exits.

When there is no app to reach (CDMW is not running, AI connections are off,
the token is stale, or another app is connected) it answers every request
with an error that says so, writes the reason to stderr, which MCP clients
show in their logs, and exits when the client closes stdin. It never starts
the app.

Standard library and ``cdmw.mcp.transport`` only: no Qt, no window.
"""

from __future__ import annotations

import json
import os
import sys
import threading
import time
from typing import BinaryIO

from cdmw.mcp.errors import NOT_RUNNING_MESSAGE

#: JSON-RPC error code for "the server cannot reach CDMW" (implementation-defined range).
NOT_RUNNING_CODE = -32001
LOST_MESSAGE = "The connection to CDMW closed."
MAX_LINE_BYTES = 16 * 1024 * 1024


def _std_streams() -> tuple[BinaryIO, BinaryIO, object]:
    """Binary stdin and stdout, also in a windowed build where ``sys.stdin`` may be None."""

    def stream(current, fd: int, std_handle: int, mode: str):
        if current is not None and getattr(current, "buffer", None) is not None:
            return current.buffer
        if os.name == "nt":
            import _winapi
            import msvcrt

            handle = _winapi.GetStdHandle(std_handle)
            if handle:
                return os.fdopen(msvcrt.open_osfhandle(handle, os.O_RDONLY if "r" in mode else os.O_WRONLY),
                                 mode, buffering=0)
        return os.fdopen(fd, mode, buffering=0)

    stdin = stream(sys.stdin, 0, -10, "rb")
    stdout = stream(sys.stdout, 1, -11, "wb")
    stderr = sys.stderr if sys.stderr is not None else open(os.devnull, "w", encoding="utf-8")
    return stdin, stdout, stderr


def _kind(line: bytes) -> str:
    try:
        message = json.loads(line)
    except (ValueError, UnicodeDecodeError):
        return "other"
    if not isinstance(message, dict):
        return "other"
    if message.get("method") == "notifications/cancelled":
        return "cancel"
    if "id" not in message:
        return "other"
    return "request" if "method" in message else "response"


def _request_id(line: bytes) -> object:
    try:
        message = json.loads(line)
    except (ValueError, UnicodeDecodeError):
        return None
    return message.get("id") if isinstance(message, dict) and "method" in message else None


def connect_to_app(attempts: int | None = None, interval: float | None = None):
    """The connected pipe, or a reason why there is none."""

    from multiprocessing import AuthenticationError, connection

    from cdmw.mcp import transport

    attempts = transport.CONNECT_ATTEMPTS if attempts is None else attempts
    interval = transport.CONNECT_INTERVAL_S if interval is None else interval
    address = transport.pipe_address()
    for attempt in range(max(1, attempts)):
        # Read the token each time: the app writes a new one when the setting is turned on.
        token = transport.read_token_file(transport.token_path())
        if token is not None:
            try:
                conn = connection.Client(address, family="AF_PIPE", authkey=token)
            except (FileNotFoundError, ConnectionError, OSError, AuthenticationError, EOFError):
                conn = None
            if conn is not None:
                try:
                    hello = transport.recv_json(conn)
                except (EOFError, OSError, ValueError):
                    hello = {"ok": False, "error": LOST_MESSAGE}
                if isinstance(hello, dict) and hello.get("ok"):
                    return conn, ""
                conn.close()
                return None, str((hello or {}).get("error") or NOT_RUNNING_MESSAGE)
        if attempt + 1 < attempts:
            time.sleep(interval)
    return None, NOT_RUNNING_MESSAGE


def _error_line(request_id: object, message: str) -> bytes:
    return json.dumps({"jsonrpc": "2.0", "id": request_id,
                       "error": {"code": NOT_RUNNING_CODE, "message": message}},
                      separators=(",", ":")).encode("utf-8") + b"\n"


def _answer_with(message: str, stdin: BinaryIO, stdout: BinaryIO, stderr) -> int:
    """Nothing to relay to: every request gets ``message`` as its error."""

    try:
        stderr.write(f"cdmw-mcp: {message} Open CDMW and turn on Settings > AI connections > "
                     "Allow AI connections.\n")
        stderr.flush()
    except (OSError, ValueError):
        pass
    for line in iter(stdin.readline, b""):
        line = line.strip()
        if line and _kind(line) == "request":
            stdout.write(_error_line(_request_id(line), message))
            stdout.flush()
    return 1


def run_bridge(stdin: BinaryIO | None = None, stdout: BinaryIO | None = None, stderr=None) -> int:
    if stdin is None or stdout is None:
        std_in, std_out, std_err = _std_streams()
        stdin, stdout, stderr = stdin or std_in, stdout or std_out, stderr or std_err
    stderr = stderr or sys.stderr
    if os.name != "nt":
        return _answer_with("AI connections are Windows-only.", stdin, stdout, stderr)
    conn, reason = connect_to_app()
    if conn is None:
        return _answer_with(reason, stdin, stdout, stderr)

    from cdmw.mcp import transport

    lock = threading.Condition()
    state = {"requests": 0, "responses": 0, "closed": False, "stdin_done": False, "pending": set()}
    out_lock = threading.Lock()

    def write(line: bytes) -> None:
        with out_lock:
            stdout.write(line.rstrip(b"\r\n") + b"\n")
            stdout.flush()

    def from_app() -> None:
        while True:
            try:
                data = conn.recv_bytes(MAX_LINE_BYTES)
            except (EOFError, OSError, RuntimeError):
                break
            if not data:
                continue
            kind = _kind(data)
            if kind == "response":
                try:
                    state["pending"].discard(json.loads(data).get("id"))
                except (ValueError, AttributeError, TypeError):
                    pass
            write(data)
            with lock:
                state["responses"] += kind == "response"
                lock.notify_all()
        with lock:
            state["closed"] = True
            lock.notify_all()

    def from_client() -> None:
        for line in iter(stdin.readline, b""):
            line = line.strip()
            if not line:
                continue
            kind = _kind(line)
            with lock:
                closed = state["closed"]
                if kind == "request":
                    state["requests"] += 1
                    state["pending"].add(_request_id(line))
                elif kind == "cancel":
                    state["responses"] += 1  # a cancelled request gets no response
            if closed:
                if kind == "request":
                    write(_error_line(_request_id(line), LOST_MESSAGE))
                continue
            try:
                conn.send_bytes(line)
            except (OSError, ValueError):
                with lock:
                    state["closed"] = True
                    lock.notify_all()
        with lock:
            state["stdin_done"] = True
            lock.notify_all()

    reader = threading.Thread(target=from_app, name="cdmw-mcp-from-app", daemon=True)
    writer = threading.Thread(target=from_client, name="cdmw-mcp-from-client", daemon=True)
    reader.start()
    writer.start()
    with lock:
        lock.wait_for(lambda: state["closed"] or (state["stdin_done"] and state["responses"] >= state["requests"]))
        lost = state["closed"]
    if lost:
        try:
            stderr.write(f"cdmw-mcp: {LOST_MESSAGE}\n")
            stderr.flush()
        except (OSError, ValueError):
            pass
        # Answer what was still waiting, then keep answering until the client lets go.
        for request_id in list(state["pending"]):
            write(_error_line(request_id, LOST_MESSAGE))
        state["pending"].clear()
        writer.join()
    try:
        conn.close()
    except OSError:
        pass
    del transport
    return 1 if lost else 0
