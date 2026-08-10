"""Opening Edit Mesh must leave the scene inspector already settled.

The rail adopts the Parts, Layers, Action History and Viewport sections from the
placement flanks with every layout suspended, and resumes without a pass of its
own. Nothing downstream is guaranteed to force the measure: a form-wide layout
only cascades where a bound actually changes. A section left on its previous
parent's bounds reads as the right-hand menu opening with its rows on top of
each other and its buttons clipped past the column edge -- and as dragging the
window border repairing it, because that is what finally changes the width.

The existing layout smoke builds stand-in controls, so it cannot see this. This
gate drives a real form, and both entries: the standalone one, and the embedded
one the workbench launches, which defers building its authoring panels until the
first mesh-edit entry and so adopts sections that were never laid out anywhere.
"""

from __future__ import annotations

import json
import subprocess
import tempfile
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
DOTNET_ROOT = REPO_ROOT / "tools" / "dotnet_mesh_editor_experiment"
DOTNET_PROJECT = DOTNET_ROOT / "Cdmw.MeshEditorExperiment.csproj"
DOTNET_HELPER = DOTNET_ROOT / "bin" / "Release" / "net10.0-windows" / "cdmw-mesh-dotnet-editor.dll"


def _build_helper() -> Path:
    completed = subprocess.run(
        [
            "dotnet",
            "build",
            str(DOTNET_PROJECT),
            "--configuration",
            "Release",
            "--nologo",
            "--verbosity:quiet",
        ],
        cwd=REPO_ROOT,
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        timeout=300,
    )
    assert completed.returncode == 0, completed.stdout
    assert DOTNET_HELPER.is_file(), completed.stdout
    return DOTNET_HELPER


def test_headless_entry_smoke_does_not_arm_host_disconnect_exit() -> None:
    constructor = (DOTNET_ROOT / "Program.cs").read_text(encoding="utf-8")
    smoke = (DOTNET_ROOT / "EditMeshEntrySmoke.cs").read_text(encoding="utf-8")

    assert "if (!options.HeadlessSmoke) StartProtocolReader();" in constructor
    assert "HeadlessSmoke: true," in smoke


@pytest.fixture(scope="module")
def entry_report() -> dict:
    with tempfile.TemporaryDirectory(prefix="cdmw-edit-mesh-entry-layout-") as temp_dir:
        temp = Path(temp_dir)
        helper = _build_helper()
        report_path = temp / "entry.json"
        completed = subprocess.run(
            [
                "dotnet",
                str(helper),
                "--headless-edit-mesh-entry-smoke",
                "--edit-mesh-entry-report",
                str(report_path),
            ],
            cwd=REPO_ROOT,
            stdin=subprocess.DEVNULL,
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
            timeout=300,
        )
        assert report_path.is_file(), (
            f"Edit Mesh entry smoke exited {completed.returncode} without a report: {completed.stderr}"
        )
        report = json.loads(report_path.read_text(encoding="utf-8"))
        assert "error" not in report, json.dumps(report, indent=2)
        assert completed.returncode == 0, json.dumps(report, indent=2)
        return report


@pytest.mark.parametrize(
    "key",
    ("scene_inspector_entry_layout", "scene_inspector_entry_layout_embedded"),
)
def test_the_scene_inspector_opens_settled_and_inside_its_column(
    key: str,
    entry_report: dict,
) -> None:
    proof = entry_report[key]

    assert proof["ok"] is True, json.dumps(proof, indent=2)
    # What a window resize would produce is what entering must already produce.
    assert proof["settled_on_entry"] is True
    # Stability alone is not enough: a column that clips every section the same
    # way before and after a resize is stable and still unusable.
    assert proof["sections_overflowing_column"] == []
    # All four rows, each inside the column, none sharing a top edge with
    # another -- overlapping rows are what the reader actually reports.
    bounds = proof["bounds_after_entry"]
    assert len(bounds) == 4, json.dumps(proof["diagnostic"], indent=2)
    tops = [int(value.split(",")[1]) for value in bounds.values()]
    assert len(set(tops)) == 4, json.dumps(bounds, indent=2)
