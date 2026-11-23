"""The mesh-core service writes an ordinary reply whole into its stdout pipe (2026-11-23).

With Windows' default 4 KiB pipe the service wrote a reply one buffer at a time, and
the client took each piece only when it had the GIL again: the Demenissian Council
Robes' 370 KiB Morph state, made by the core in 10 ms, took 5-6 s to read beside three
busy Python threads (measured outside the app). The pipe now holds an ordinary reply
whole, so it is read in one piece. (In the app the replies were 40 MB, from material
attributes that now travel as tokens; see test_native_material_attrs_travel_as_tokens.)

A stand-in service writes a 2 MiB reply and only then marks a file; the test waits for
the mark without reading stdout, so the write must not block on the pipe.
"""

from __future__ import annotations

import os
import subprocess
import sys
import time

import pytest

from cdmw.modding import mesh_native_client as client

pytestmark = pytest.mark.skipif(os.name != "nt", reason="the Windows pipe reader")

REPLY_BYTES = 2 * 1024 * 1024

SERVICE = r'''
import json, sys
from pathlib import Path
marker = Path(sys.argv[1])
out = sys.stdout.buffer
out.write(b'{"event":"ready"}\n'); out.flush()
for line in sys.stdin:
    out.write(json.dumps({"status": "ok", "pad": "x" * %d}).encode() + b"\n"); out.flush()
    marker.write_text("written")
''' % REPLY_BYTES


def test_a_large_reply_is_written_whole_without_a_reader(tmp_path, monkeypatch) -> None:
    script, marker = tmp_path / "service.py", tmp_path / "written"
    script.write_text(SERVICE, encoding="utf-8")
    binary = tmp_path / "cdmw-mesh-core.exe"
    popen = subprocess.Popen

    def start(args, *rest, **kwargs):
        if args and str(args[0]) == str(binary):
            args = [sys.executable, "-I", str(script), str(marker)]
        return popen(args, *rest, **kwargs)

    monkeypatch.setattr(client.subprocess, "Popen", start)
    service = client.NativeMeshCoreServiceClient(binary)
    try:
        with service._lock:
            service._start_locked()
            service._process.stdin.write('{"command":"probe","payload":{}}\n')
            service._process.stdin.flush()
            deadline = time.monotonic() + 15.0
            while not marker.exists() and time.monotonic() < deadline:
                time.sleep(0.02)
            assert marker.exists(), "the service blocked writing its reply into the stdout pipe"
            line = service._read_reply_locked(10.0, stop_event=None)
        assert len(line) > REPLY_BYTES
        assert client._WINDOWS_STDOUT_PIPE_BYTES >= 4 * 1024 * 1024
    finally:
        service.shutdown()
