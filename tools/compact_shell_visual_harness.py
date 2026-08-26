"""Capture deterministic Compact Workspace geometry and screenshots.

The harness constructs one production ``MainWindow`` with temporary settings,
then visits the same registered tool instances at the reference and responsive
window sizes.  Fixture rows are added directly to views with signals blocked;
the harness never opens or mutates game archives.
"""

from __future__ import annotations

import os
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ.setdefault("CDMW_GUI_STARTUP_SMOKE", "1")
if sys.platform != "win32":
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from tools.compact_shell_visual.capture import (
    _BITMAPINFO,
    _BITMAPINFOHEADER,
    _RECT,
    _RGBQUAD,
    _capture_print_window,
    _rect_payload,
    _splitter_payload,
    capture_window,
    geometry_payload,
)
from tools.compact_shell_visual.cli import build_argument_parser, main
from tools.compact_shell_visual.contracts import (
    EXPECTED_MESH_EDIT_BACKEND,
    EXPECTED_MESH_RENDERER_BACKEND,
    MESH_RENDERER_READY_TIMEOUT_SECONDS,
    REFERENCE_FILENAMES,
    REFERENCE_SIZE,
    RESPONSIVE_SIZES,
    SYNTHETIC_MESH_SESSION_ID,
    SYNTHETIC_MESH_SOURCE_PATH,
    _BUNDLED_HELPER_RESOLUTION_SOURCES,
    _SIZE_PATTERN,
    build_capture_plan,
    capture_sizes,
    parse_size,
    relative_capture_path,
)
from tools.compact_shell_visual.fixtures import (
    _install_safe_workspace_fixture,
    _seed_in_memory_rows,
    _write_texture_fixture_pair,
)
from tools.compact_shell_visual.mesh_fixture import (
    _require_bundled_mesh_helper,
    _synthetic_mesh_package_evidence,
    _synthetic_mesh_renderer_evidence,
    _wait_for_synthetic_mesh_renderer,
)
from tools.compact_shell_visual.runner import (
    _PlacementBaselineGuard,
    _configure_fixture_settings,
    _selected_keys,
    run_harness,
)
from tools.compact_shell_visual.runtime import (
    _apply_presentation,
    _assert_real_texture_editor,
    _process_events,
    _registered_widgets,
    _resize_frame,
    _resolve_tool_widget,
    _wait_until,
)


__all__ = [
    "EXPECTED_MESH_EDIT_BACKEND",
    "EXPECTED_MESH_RENDERER_BACKEND",
    "MESH_RENDERER_READY_TIMEOUT_SECONDS",
    "REFERENCE_FILENAMES",
    "REFERENCE_SIZE",
    "RESPONSIVE_SIZES",
    "ROOT",
    "SYNTHETIC_MESH_SESSION_ID",
    "SYNTHETIC_MESH_SOURCE_PATH",
    "_BITMAPINFO",
    "_BITMAPINFOHEADER",
    "_BUNDLED_HELPER_RESOLUTION_SOURCES",
    "_PlacementBaselineGuard",
    "_RECT",
    "_RGBQUAD",
    "_SIZE_PATTERN",
    "_apply_presentation",
    "_assert_real_texture_editor",
    "_capture_print_window",
    "_configure_fixture_settings",
    "_install_safe_workspace_fixture",
    "_process_events",
    "_rect_payload",
    "_registered_widgets",
    "_require_bundled_mesh_helper",
    "_resize_frame",
    "_resolve_tool_widget",
    "_seed_in_memory_rows",
    "_selected_keys",
    "_splitter_payload",
    "_synthetic_mesh_package_evidence",
    "_synthetic_mesh_renderer_evidence",
    "_wait_for_synthetic_mesh_renderer",
    "_wait_until",
    "_write_texture_fixture_pair",
    "build_argument_parser",
    "build_capture_plan",
    "capture_sizes",
    "capture_window",
    "geometry_payload",
    "main",
    "parse_size",
    "relative_capture_path",
    "run_harness",
]


if __name__ == "__main__":
    raise SystemExit(main())
