"""Solid (Textured) must survive the presentation snapshot that carries it.

The display mode reaches the resident helper two ways. `viewport_display_update`
is the narrow message the Mesh view control sends; the presentation snapshot is
the other, and it is republished after every accepted scene frame. That snapshot
carries the whole Preview Settings quality payload beside the mode, including
`use_textures_by_default` -- "load textures automatically after geometry", which
is off by default.

The helper applied the mode first and the quality payload second, so every
republish switched textures back off under a mode whose entire meaning is that
they are on. The viewport drew Faces (No Textures) while both Mesh view controls
read "Solid (Textured)", and picking the mode again re-textured the scene only
until the next frame landed -- which is what made it look intermittent.

The rule is now "a named mode owns the textures". These pin both directions: a
fix that simply dropped the flag would strand the archive preview's own toggle,
which is the only texture authority a payload that names no mode has.
"""

from __future__ import annotations

import json
import subprocess
import tempfile
from pathlib import Path

from cdmw.models import ModelPreviewRenderSettings
from cdmw.ui.archive_browser.static_replacement_dotnet_presentation import (
    builder_presentation_state,
)

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


def test_the_builder_really_publishes_textured_beside_a_false_texture_flag() -> None:
    """The payload the helper has to cope with, from the code that builds it.

    Without this the renderer gate below could be dismissed as a synthetic
    combination nothing sends.
    """
    display = builder_presentation_state(
        comparison_mode="replacement_only",
        display_mode="textured",
        mesh_edit_display_mode="textured",
        camera={},
        render_settings=ModelPreviewRenderSettings(),
        grid_visible=True,
        gizmo_visible=False,
        part_pick_enabled=False,
        mesh_edit_active=True,
    )["display"]

    assert display["mode"] == "textured"
    assert display["quality"]["use_textures_by_default"] is False
