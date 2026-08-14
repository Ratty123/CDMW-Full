"""Shared fixtures for the resident material UI tests.

The scenarios outgrew one file and were split in two. These helpers drive the
material compile loop and are needed by both halves, so they live here rather
than being duplicated or imported across test modules.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import time
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication
from PIL import Image

from cdmw.models import PreviewMaterialTextureInput
from cdmw.services.mesh_dotnet_experiment import (
    MeshDotNetExperimentPackage,
    mesh_dotnet_material_input_signature,
)
from cdmw.modding.static_mesh_scene_frame import static_scene_source_identity
from cdmw.ui.mesh_editor import MeshEditorTab
from cdmw.ui.mesh_editor.tab_dotnet_protocol import _dotnet_event_requires_correlation
from tests.test_mesh_editor_action_bar import (
    _EmbeddedMeshBuilder,
    _FakeProcess,
    _install_shared_dotnet_test_process,
)



def _material_writes(
    app: QApplication,
    process: _FakeProcess,
    *,
    minimum: int = 1,
    timeout: float = 3.0,
) -> list[dict[str, object]]:
    deadline = time.monotonic() + timeout
    writes: list[dict[str, object]] = []
    while time.monotonic() < deadline:
        app.processEvents()
        writes = [
            json.loads(raw.decode("utf-8"))
            for raw in process.stdin_writes
            if b'"event":"material_state_update"' in raw
        ]
        if len(writes) >= minimum:
            break
        time.sleep(0.005)
    return writes


def _wait_for_material_compile_idle(
    app: QApplication,
    tab: MeshEditorTab,
    *,
    timeout: float = 3.0,
) -> None:
    deadline = time.monotonic() + timeout
    while tab._dotnet_material_compile_active() and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.005)
    app.processEvents()


def _acknowledge_editable_materials(tab: MeshEditorTab, process: _FakeProcess) -> None:
    tab.standalone_dotnet_material_generation = 1
    tab.standalone_dotnet_material_generation_by_role["editable_imported"] = 1
    tab.standalone_dotnet_material_role_by_generation[1] = "editable_imported"
    process.emit_stdout(
        json.dumps(
            {
                "event": "material_state_applied",
                "generation": 1,
                "role": "replacement",
                "material_signature": "editable-materials",
                "texture_resources_ready": True,
            }
        )
        + "\n"
    )
