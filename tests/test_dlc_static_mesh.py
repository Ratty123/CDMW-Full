"""Native PAMLOD regression with wholly owned descriptor/geometry bytes."""
import json
from pathlib import Path
import struct
import subprocess

import pytest


def test_material_dds_text_is_not_another_mesh_descriptor(tmp_path):
    helper = Path(__file__).resolve().parents[1] / "native/cdmw_preview_core/build/Release/cdmw-preview-core.exe"
    if not helper.is_file():
        pytest.skip("Native Preview Core build is required")
    geometry = 80 + 2 * 536
    data = bytearray(geometry + 6 * 20 + 12)
    struct.pack_into("<II", data, 0, 1, geometry)
    struct.pack_into("<3f", data, 28, 1, 1, 1)
    for index in range(2):
        at = 80 + index * 536
        struct.pack_into("<4I", data, at, 3, 3, index * 3, index * 3)
        data[at + 16:at + 26] = b"owned.dds\0"
        for vertex, xyz in enumerate(((0, 0, 0), (32767, 0, 0), (0, 32767, 0))):
            struct.pack_into("<3H", data, geometry + (index * 3 + vertex) * 20, *xyz)
    fake = 80 + 16 + 256 + 32
    struct.pack_into("<4I", data, fake, 3, 3, 0, 0)
    data[fake + 16:fake + 27] = b"nested.dds\0"
    struct.pack_into("<6H", data, geometry + 120, 0, 1, 2, 0, 1, 2)
    source, report = tmp_path / "owned.pamlod", tmp_path / "audit.json"
    source.write_bytes(data)
    run = subprocess.run([str(helper), "mesh-audit-job", str(source), str(report), "owned.pamlod"],
                         capture_output=True, text=True, timeout=30)
    result = json.loads(report.read_text())
    assert run.returncode == 0 and result["status"] == "ok", result
    assert result["submesh_count"] == 2 and result["vertex_count"] == 6
