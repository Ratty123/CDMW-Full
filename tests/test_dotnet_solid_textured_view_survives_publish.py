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
DOTNET_HELPER = DOTNET_ROOT / "bin" / "Release" / "net10.0-windows" / "cdmw-mesh-dotnet-editor.exe"


def _build_helper() -> None:
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


def test_a_named_display_mode_owns_the_textures() -> None:
    _build_helper()
    with tempfile.TemporaryDirectory(prefix="cdmw-edit-mesh-entry-") as temp_dir:
        report_path = Path(temp_dir) / "entry.json"
        completed = subprocess.run(
            [
                str(DOTNET_HELPER),
                "--headless-edit-mesh-entry-smoke",
                "--edit-mesh-entry-report",
                str(report_path),
            ],
            cwd=REPO_ROOT,
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
            timeout=300,
        )
        report = (
            json.loads(report_path.read_text(encoding="utf-8"))
            if report_path.is_file()
            else {"ok": False, "error": completed.stderr}
        )
        assert completed.returncode == 0, json.dumps(report, indent=2)

    proof = report["solid_textured_view"]
    assert proof["ok"] is True, json.dumps(proof, indent=2)

    # The whole defect: mode "textured" published beside the flag turned off.
    textured = proof["named_textured_mode"]
    assert textured["display_mode"] == "textured"
    assert textured["textures_enabled"] is True
    # The panes hold their own copy and are what the renderer draws from, so a
    # synchronisation that never reached them would still leave the scene flat.
    assert textured["pane_textures_enabled"] is True

    # The other direction of the same rule: an untextured mode stays untextured
    # however the flag is set, or Faces (No Textures) stops meaning anything.
    untextured = proof["named_untextured_mode"]
    assert untextured["display_mode"] == "untextured_faces"
    assert untextured["textures_enabled"] is False
    assert untextured["pane_textures_enabled"] is False

    # And a payload that names no mode still answers to the flag, which is the
    # archive preview's only way to turn textures off.
    unnamed = proof["unnamed_mode_honours_flag"]
    assert unnamed["display_mode"] == "textured"
    assert unnamed["textures_enabled"] is False


def test_the_quality_payload_defers_to_a_named_mode_in_source() -> None:
    """The ordering is the contract, and it is one line either way.

    ApplyPresentationQualityAndUv runs immediately after the mode was resolved,
    so an unconditional read of the flag here silently outranks it again.
    """
    settings = (DOTNET_ROOT / "MeshViewport.PresentationSettings.cs").read_text(
        encoding="utf-8"
    )

    assert "PayloadNamesDisplayMode(display)" in settings
    assert (
        'var texturesEnabled = JsonBool(quality, "use_textures_by_default", TexturesEnabled);'
        not in settings
    )
