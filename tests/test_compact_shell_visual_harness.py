from __future__ import annotations

import argparse
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("CDMW_GUI_STARTUP_SMOKE", "1")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QHBoxLayout, QPushButton, QSplitter, QWidget

from tools.compact_shell_visual_harness import (
    REFERENCE_FILENAMES,
    REFERENCE_SIZE,
    RESPONSIVE_SIZES,
    SYNTHETIC_MESH_SESSION_ID,
    _require_bundled_mesh_helper,
    _synthetic_mesh_package_evidence,
    _synthetic_mesh_renderer_evidence,
    _write_texture_fixture_pair,
    build_argument_parser,
    build_capture_plan,
    capture_sizes,
    clipped_button_error,
    geometry_payload,
    parse_size,
)
from tools.compact_shell_visual.mesh_fixture import _wait_for_synthetic_mesh_renderer


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


class CompactShellVisualHarnessTests(unittest.TestCase):
    def _synthetic_package(self, root: Path) -> SimpleNamespace:
        package_dir = root / "synthetic-package"
        package_dir.mkdir()
        paths = {
            "mesh_path": package_dir / "mesh.obj",
            "cdmeta_path": package_dir / "mesh.cdmeta.json",
            "scene_manifest_path": package_dir / "dotnet_scene.json",
            "launch_manifest_path": package_dir / "dotnet_launch.json",
        }
        for path in paths.values():
            path.write_text("fixture", encoding="utf-8")
        return SimpleNamespace(
            package_dir=package_dir,
            scene_session_id=SYNTHETIC_MESH_SESSION_ID,
            scene_frame=SimpleNamespace(
                source_identity="synthetic-source-identity",
                interaction_mode="mesh_edit",
            ),
            material_signature="geometry_only",
            editable_submesh_count=1,
            reference_submesh_count=1,
            **paths,
        )

    def test_reference_capture_names_map_one_to_one_to_all_tools(self) -> None:
        self.assertEqual(15, len(REFERENCE_FILENAMES))
        self.assertEqual(15, len(set(REFERENCE_FILENAMES.values())))
        self.assertEqual(
            [f"{index:02d}" for index in range(1, 16)],
            [name[:2] for name in REFERENCE_FILENAMES.values()],
        )

    def test_capture_plan_uses_reference_names_at_primary_and_scoped_responsive_paths(self) -> None:
        keys = ("archive_browser", "texture_editor")
        plan = build_capture_plan(keys, REFERENCE_SIZE)
        self.assertEqual(6, len(plan))
        primary_paths = [path for _key, size, path in plan if size == REFERENCE_SIZE]
        self.assertEqual(
            [Path("01-browse-archives.png"), Path("10-texture-editor.png")],
            primary_paths,
        )
        responsive_paths = [path.as_posix() for _key, size, path in plan if size != REFERENCE_SIZE]
        self.assertTrue(all(path.startswith("responsive/") for path in responsive_paths))
        self.assertEqual(len(responsive_paths), len(set(responsive_paths)))

    def test_requested_size_is_first_and_required_responsive_sizes_are_deduplicated(self) -> None:
        self.assertEqual((REFERENCE_SIZE, *RESPONSIVE_SIZES), capture_sizes(REFERENCE_SIZE))
        self.assertEqual(
            (RESPONSIVE_SIZES[0], RESPONSIVE_SIZES[1]),
            capture_sizes(RESPONSIVE_SIZES[0]),
        )

    def test_size_parser_and_exact_objective_cli(self) -> None:
        parser = build_argument_parser()
        parsed = parser.parse_args(
            [
                "--all",
                "--output",
                "visual-output",
                "--size",
                "1672x941",
                "--theme",
                "crimson_desert",
            ]
        )
        self.assertTrue(parsed.all)
        self.assertEqual(REFERENCE_SIZE, parsed.size)
        self.assertEqual("crimson_desert", parsed.theme)
        with self.assertRaises(argparse.ArgumentTypeError):
            parse_size("1672,941")

    def test_geometry_payload_measures_real_qt_splitter(self) -> None:
        app = _app()
        window = QWidget()
        window.resize(1120, 720)
        layout = QHBoxLayout(window)
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setObjectName("fixture_splitter")
        splitter.setHandleWidth(1)
        splitter.addWidget(QWidget())
        splitter.addWidget(QWidget())
        splitter.setSizes([330, 770])
        layout.addWidget(splitter)
        window.show()
        app.processEvents()

        payload = geometry_payload(window, "archive_browser", window)

        self.assertEqual("archive_browser", payload["key"])
        self.assertEqual(1120, payload["window_geometry"]["width"])
        self.assertEqual(1, payload["splitters"][0]["handle_width"])
        self.assertEqual("fixture_splitter", payload["splitters"][0]["id"])
        self.assertEqual(2, len(payload["splitters"][0]["sizes"]))
        self.assertEqual([], payload["resident_hosts"])
        window.close()

    def test_geometry_payload_reports_only_visible_clipped_button_text(self) -> None:
        app = _app()
        window = QWidget()
        layout = QHBoxLayout(window)
        clipped = QPushButton("A deliberately long action", window)
        clipped.setObjectName("ClippedAction")
        clipped.setFixedWidth(48)
        fitting = QPushButton("Fits", window)
        fitting.setFixedWidth(120)
        hidden = QPushButton("Hidden long action", window)
        hidden.setFixedWidth(20)
        hidden.hide()
        layout.addWidget(clipped)
        layout.addWidget(fitting)
        layout.addWidget(hidden)
        window.resize(220, 80)
        window.show()
        app.processEvents()

        payload = geometry_payload(window, "archive_browser", window)

        self.assertEqual(2, payload["visible_button_count"])
        self.assertEqual(1, payload["clipped_button_count"])
        self.assertEqual("ClippedAction", payload["clipped_buttons"][0]["id"])
        self.assertGreater(payload["clipped_buttons"][0]["shortfall"], 0)
        window.close()

    def test_clipped_button_error_is_bounded_and_empty_on_success(self) -> None:
        self.assertEqual("", clipped_button_error(({"clipped_buttons": []},)))
        captures = (
            {
                "key": "archive_browser",
                "requested_size": "1120x720",
                "clipped_buttons": [
                    {"text": f"Action {index}", "actual_width": 40, "needed_width": 80}
                    for index in range(14)
                ],
            },
        )

        message = clipped_button_error(captures)

        self.assertIn("archive_browser@1120x720:Action 0 (40/80 px)", message)
        self.assertIn("plus 2 more", message)

    def test_bundled_helper_resolution_requires_expected_executable_and_source(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            executable = Path(temporary) / "cdmw-mesh-dotnet-editor.exe"
            executable.write_bytes(b"fixture")
            widget = SimpleNamespace(
                _dotnet_editor_executable_resolution=lambda **_kwargs: SimpleNamespace(
                    resolved_path=str(executable),
                    source="source_release",
                    is_file=True,
                )
            )

            evidence = _require_bundled_mesh_helper(widget)

            self.assertTrue(evidence["available"])
            self.assertEqual("source_release", evidence["resolution_source"])

            widget._dotnet_editor_executable_resolution = lambda **_kwargs: SimpleNamespace(
                resolved_path=str(executable),
                source="env_path",
                is_file=True,
            )
            with self.assertRaisesRegex(RuntimeError, "bundled resident helper"):
                _require_bundled_mesh_helper(widget)

    def test_synthetic_mesh_package_and_renderer_require_exact_ready_session(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            package = self._synthetic_package(Path(temporary))
            controller = SimpleNamespace(
                is_running=True,
                process_id=42,
                applied_package_path=str(package.package_dir),
                serving_prewarm_placeholder=False,
                _protocol_ready=True,
                _renderer_ready=True,
                _session_established=True,
                _localization_initial_established=True,
            )
            widget = SimpleNamespace(
                standalone_dotnet_experiment_package=package,
                standalone_native_host_frame=SimpleNamespace(controller=controller),
                standalone_dotnet_status_payload={
                    "renderer": {"backend": "d3d11_vortice_shader"}
                },
                standalone_dotnet_capabilities=(),
                standalone_dotnet_provenance_verified=False,
                standalone_native_editor_available=True,
            )

            package_evidence = _synthetic_mesh_package_evidence(
                widget,
                expected_source_identity="synthetic-source-identity",
            )
            renderer_evidence = _synthetic_mesh_renderer_evidence(
                widget,
                expected_source_identity="synthetic-source-identity",
            )

            self.assertEqual(SYNTHETIC_MESH_SESSION_ID, package_evidence["session_id"])
            self.assertEqual("d3d11_vortice_shader", renderer_evidence["renderer_backend"])
            self.assertEqual("cdmw_mesh_core_0.1", renderer_evidence["edit_backend"])
            self.assertTrue(renderer_evidence["no_game_or_archive_data"])

            package.scene_session_id = "wrong-session"
            with self.assertRaisesRegex(RuntimeError, "wrong package session"):
                _synthetic_mesh_package_evidence(
                    widget,
                    expected_source_identity="synthetic-source-identity",
                )

    def test_renderer_timeout_reports_the_resident_controller_failure(self) -> None:
        controller = SimpleNamespace(
            _retry_reason="helper provenance blocked: manifest mismatch",
            _stderr_tail="native stderr detail",
            _stdout_tail="protocol stdout detail",
            _last_event={"event": "protocol_ready"},
        )
        widget = SimpleNamespace(
            standalone_status_label=SimpleNamespace(text=lambda: "Session pending"),
            standalone_dotnet_stderr_tail="",
            standalone_native_host_frame=SimpleNamespace(controller=controller),
        )

        with patch(
            "tools.compact_shell_visual.mesh_fixture._wait_until",
            return_value=False,
        ):
            with self.assertRaisesRegex(
                RuntimeError,
                "helper provenance blocked: manifest mismatch",
            ):
                _wait_for_synthetic_mesh_renderer(
                    widget,
                    expected_source_identity="synthetic-source-identity",
                )

    def test_generated_texture_pair_is_decodable_and_bounded(self) -> None:
        _app()
        with tempfile.TemporaryDirectory() as temporary:
            before_path, after_path, before, after = _write_texture_fixture_pair(
                Path(temporary)
            )

            self.assertTrue(before_path.is_file())
            self.assertTrue(after_path.is_file())
            self.assertEqual((640, 480), (before.width(), before.height()))
            self.assertEqual((640, 480), (after.width(), after.height()))


if __name__ == "__main__":
    unittest.main()
