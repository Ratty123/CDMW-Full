"""A whole worn set's edit report fits in one native mesh-core reply line (2026-11-15).

A delete across the five files of a set produced a reply line over 16 MiB; the
client's cap ended the service, and every open session with it, so the delete was
refused and the set could not be finished. The cap is now 256 MiB.
"""

from __future__ import annotations

import os
import subprocess
import sys

import pytest

from cdmw.modding import mesh_native_client as client

pytestmark = pytest.mark.skipif(os.name != "nt", reason="the Windows pipe reader")


def test_a_reply_line_over_16_mib_is_read_whole(tmp_path) -> None:
    size = 20 * 1024 * 1024
    # The service stays up between replies; so does this stand-in.
    script = ("import sys, time; out = sys.stdout.buffer; "
              f"out.write(b'x' * {size} + bytes([10])); out.write(b'next' + bytes([10])); out.flush(); time.sleep(30)")
    process = subprocess.Popen([sys.executable, "-c", script], stdout=subprocess.PIPE)
    service = client.NativeMeshCoreServiceClient(tmp_path / "cdmw-mesh-core.exe")
    service._process = process
    service._stdout_stream = process.stdout
    try:
        line = service._read_stdout_line_locked(60.0)
        assert len(line) == size and set(line) == {"x"}
        assert service._read_stdout_line_locked(10.0) == "next"
    finally:
        process.kill()
        process.wait(10)
    assert client._MESH_CORE_PROTOCOL_LINE_MAX_BYTES >= 128 * 1024 * 1024
