"""The Mesh Editor opens when the CDMW folder's path has letters outside ASCII (2026-11-20).

Python writes every native mesh-core job and request with ``ensure_ascii``, so a
CDMW folder such as ``C:\\Users\\Jörg\\CDMW`` reached the core as backslash-u
escapes. The core's JSON reader turned each escape into ``?``, looked for the job
in a folder that does not exist, could not write its report either, and every job
failed. Opening any mesh then stopped with "native edit-session clone failed and
Python fallback was blocked [snapshot creation: mesh-session-json: resident
RuntimeError: native mesh-core service returned an error]".
"""

from __future__ import annotations

import json
import subprocess
import tempfile

import pytest

import cdmw.services.mesh_service  # noqa: F401  (loads the service the clone helpers call)
from cdmw.modding import mesh_native_core
from cdmw.modding.mesh_native_availability import find_native_mesh_core_binary
from cdmw.modding.mesh_parser import ParsedMesh, SubMesh
from cdmw.services import mesh_service_native_clone

_BINARY = find_native_mesh_core_binary()

pytestmark = pytest.mark.skipif(_BINARY is None, reason="needs the native mesh core")

FOLDER_NAMES = (
    "J\u00f6rg CDMW",  # Latin with an umlaut
    "\u041c\u043e\u0434\u044b",  # Cyrillic
    "\u6a21\u7ec4",  # CJK
    "mods \U0001f600",  # outside the BMP: a surrogate pair in the JSON
)


def _triangle_mesh() -> ParsedMesh:
    submesh = SubMesh(name="tri", material="m", texture="")
    submesh.vertices = [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)]
    submesh.normals = [(0.0, 0.0, 1.0)] * 3
    submesh.uvs = [(0.0, 0.0), (1.0, 0.0), (0.0, 1.0)]
    submesh.faces = [(0, 1, 2)]
    mesh = ParsedMesh()
    mesh.submeshes = [submesh]
    mesh.total_vertices = 3
    mesh.total_faces = 1
    return mesh


@pytest.fixture
def temp_folder_named(tmp_path, monkeypatch):
    def use(name: str):
        folder = tmp_path / name / "workspace" / "temp"
        folder.mkdir(parents=True)
        # The app points tempfile at <CDMW folder>\workspace\temp at start.
        monkeypatch.setattr(tempfile, "tempdir", str(folder))
        return folder

    mesh_native_core.shutdown_native_mesh_core_service()
    yield use
    mesh_native_core.shutdown_native_mesh_core_service()


@pytest.mark.parametrize("name", FOLDER_NAMES)
def test_a_mesh_opens_for_editing_from_a_folder_with_letters_outside_ascii(temp_folder_named, name) -> None:
    temp_folder_named(name)
    working, base = mesh_service_native_clone._clone_mesh_pair_for_session_open(_triangle_mesh())
    assert len(working.submeshes[0].vertices) == 3
    assert len(base.submeshes[0].vertices) == 3


def _service_reply(lines: list[dict[str, object]]) -> list[dict[str, object]]:
    requests = "".join(json.dumps(line) + "\n" for line in lines) + json.dumps({"command": "shutdown"}) + "\n"
    completed = subprocess.run(
        [str(_BINARY), "--service"], input=requests.encode("ascii"), capture_output=True, timeout=60, check=False,
    )
    return [json.loads(line) for line in completed.stdout.decode("utf-8").splitlines()]


def test_the_core_reads_escaped_paths_as_utf8(tmp_path) -> None:
    folder = tmp_path / FOLDER_NAMES[3] / FOLDER_NAMES[0]
    folder.mkdir(parents=True)
    job = folder / "job.json"
    report = folder / "report.json"
    job.write_text("{}", encoding="utf-8")
    replies = _service_reply([{"command": "mesh-session-json", "job_path": str(job), "report_path": str(report)}])
    # The job is not a mesh, so the core refuses it, but it found the job and
    # wrote its answer where it was asked to.
    assert replies[1]["report_path"] == str(report)
    assert json.loads(report.read_text(encoding="utf-8"))["status"] != "ok"


def test_a_control_character_in_an_escape_comes_back_as_valid_json(tmp_path) -> None:
    missing = tmp_path / "no\u0001such" / "job.json"
    replies = _service_reply(
        [{"command": "mesh-session-json", "job_path": str(missing), "report_path": str(tmp_path / "r.json")}]
    )
    assert replies[1]["status"] == "error"
    report = json.loads((tmp_path / "r.json").read_text(encoding="utf-8"))
    assert "no\u0001such" in report["message"]
