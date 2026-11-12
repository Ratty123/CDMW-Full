"""P1's parity check as a journey: Browse and the Mesh Editor draw the same pixels.

The same staged helper renders Browse's package and the editor's live session
at 1024 px from three cameras, in Textured and Base Color. Tolerances, mean
absolute difference in 8-bit levels, come from the P1 results in the report:
Base Color agreed within 0.0143 on every case; Textured differs at silhouette
and specular edges (MSAA resolve) up to 0.049, and on the head up to 0.138
because its companions are composed on the CPU in the editor (closed by V3).
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from PIL import Image, ImageChops

from tests.journeys import driver

pytestmark = [pytest.mark.real_game, pytest.mark.skipif(bool(driver.skip_reason()), reason=driver.skip_reason() or "-")]

CAMERAS = ((135, -25), (315, -25), (90, 0))
CASES = {
    "sword": (driver.SWORD, 0.06),
    "scabbard": (driver.SCABBARD, 0.06),
    "upper": (driver.UPPER, 0.06),
    "set": (driver.HONOR_GUARD_SET, 0.06),
    "wyvern": (driver.WYVERN, 0.06),
    "head": (driver.HEAD, 0.15),
}
BASE_COLOR_TOLERANCE = 0.02


def _mean_difference(a: Path, b: Path) -> float:
    left, right = Image.open(a).convert("RGB"), Image.open(b).convert("RGB")
    diff = ImageChops.difference(left, right)
    histogram = diff.histogram()
    total = sum(level * count for channel in range(3) for level, count in enumerate(histogram[channel * 256:(channel + 1) * 256]))
    return total / (3 * left.width * left.height)


def _capture(helper: Path, flag: str, manifest: Path, output: Path, yaw: int, pitch: int) -> None:
    command = [str(helper), flag, str(manifest), "--capture-output", str(output), "--capture-size", "1024",
               "--capture-yaw-degrees", str(yaw), "--capture-pitch-degrees", str(pitch),
               "--capture-report-json", str(output.with_suffix(".json"))]
    done = subprocess.run(command, capture_output=True, text=True, timeout=300,
                          creationflags=subprocess.CREATE_NO_WINDOW)
    assert done.returncode == 0, done.stderr[-1500:]


@pytest.mark.parametrize("case", list(CASES))
def test_browse_and_the_mesh_editor_draw_the_same_pixels(case, tmp_path):
    from cdmw.services.mesh_rust_contract import resolve_rust_mesh_editor

    target, textured_tolerance = CASES[case]
    profile = driver.make_profile(f"parity-{case}")
    app = driver.Run(profile)
    try:
        app.wait_usable()
        app.call("activate_tool", key="archive_browser")
        app.select(target)
        editor = app.open_mesh_editor(item_set=not isinstance(target, str))
        assert editor["texture_unavailable_reason"] == "", editor
        if isinstance(target, str):
            # P4 V3: one scene before and after enter_edit, in Browse's own process.
            assert app.state()["mesh_editor"]["in_browse"], "the edit did not open in Browse's viewport"
        state = app.state()
        browse = Path(state["browse_package"])
        browse = browse / "manifest.json" if browse.is_dir() else browse
        session = Path(editor["session_manifest"])
        helper = Path(resolve_rust_mesh_editor(None).resolved_path)
        results = {}
        for yaw, pitch in CAMERAS:
            pair = {}
            for label, flag, manifest in (("browse", "--capture-cdmw-preview-session", browse),
                                          ("editor", "--capture-cdmw-session", session)):
                pair[label] = tmp_path / f"{label}-{yaw}-{pitch}.bmp"
                _capture(helper, flag, manifest, pair[label], yaw, pitch)
            results[(yaw, pitch)] = (
                _mean_difference(pair["browse"], pair["editor"]),
                _mean_difference(pair["browse"].with_name(pair["browse"].stem + "-base-color.bmp"),
                                 pair["editor"].with_name(pair["editor"].stem + "-base-color.bmp")),
            )
    finally:
        app.close()
        driver.keep_log_and_remove(profile, f"parity-{case}")
    for camera, (textured, base_color) in results.items():
        assert textured <= textured_tolerance, (case, camera, "Textured", textured)
        assert base_color <= BASE_COLOR_TOLERANCE, (case, camera, "Base Color", base_color)
