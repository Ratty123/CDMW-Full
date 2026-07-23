from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication, QWidget

from cdmw.services.settings_service import create_settings
from cdmw.ui.shell.app_startup import (
    ShellApplicationStartup,
    finish_gui_startup_smoke_if_requested,
    prepare_shell_application,
    prepare_shell_main_window,
    read_shell_startup_theme_key,
    run_shell_event_loop,
)
from cdmw.ui.shell.app_context import AppContext
from cdmw.ui.themes import UI_THEME_SCHEMES


class _SettingsStub:
    def __init__(self, value: object) -> None:
        self._value = value

    def value(self, key: str, default: object = None) -> object:
        return self._value if key == "appearance/theme" else default


class _AppStub:
    def __init__(self, *, exit_code: int = 0) -> None:
        self.process_events_called = False
        self.exit_code = exit_code

    def windowIcon(self) -> QIcon:
        return QIcon()

    def processEvents(self) -> None:
        self.process_events_called = True

    def exec(self) -> int:
        return self.exit_code


class _WindowStub:
    def __init__(self) -> None:
        self._app_window_icon_filter: object | None = None
        self.attached_splash: object | None = None
        self.hold_main_window = False
        self.released = False
        self.finalized = False

    def setWindowIcon(self, icon: QIcon) -> None:
        return

    def attach_startup_splash(self, splash: object, *, hold_main_window: bool = False) -> None:
        self.attached_splash = splash
        self.hold_main_window = hold_main_window

    def _release_startup_splash(self) -> None:
        self.released = True

    def _finalize_close(self) -> None:
        self.finalized = True


class _TabsStub:
    def __init__(self, expected_widget: object) -> None:
        self.expected_widget = expected_widget
        self.current_index: int | None = None

    def indexOf(self, widget: object) -> int:
        return 0 if widget is self.expected_widget else -1

    def setCurrentIndex(self, index: int) -> None:
        self.current_index = int(index)


class _SignalStub:
    def __init__(self) -> None:
        self._callbacks = []

    def connect(self, callback) -> None:
        self._callbacks.append(callback)

    def emit(self, *args) -> None:
        for callback in tuple(self._callbacks):
            callback(*args)


class _MeshSmokeServiceStub:
    def __init__(self) -> None:
        self.calls: list[tuple[object, ...]] = []
        self.validation = SimpleNamespace(ok=True, blockers=())
        self.mesh = SimpleNamespace(path="mesh.pac")

    def working_mesh(self, session_id: str, *, clone: bool = False) -> object:
        self.calls.append(("working_mesh", session_id, clone))
        return self.mesh

    def replace_working_mesh(self, session_id: str, mesh: object) -> object:
        self.calls.append(("replace_working_mesh", session_id, mesh))
        return SimpleNamespace(session_id=session_id)

    def validate_export(self, session_id: str) -> object:
        self.calls.append(("validate_export", session_id))
        return self.validation


class _MeshEditorTabStub(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.opened_path: Path | None = None
        self.session_active = False
        self.standalone_last_export_validation_report = None
        self.mesh_smoke_service = _MeshSmokeServiceStub()
        self.standalone_controller = None

    def open_mesh_file_session(self, path: Path, *, session_id: str = "", mode: str = "object") -> object:
        self.opened_path = Path(path)
        self.session_active = True
        self.standalone_controller = SimpleNamespace(
            mesh_service=self.mesh_smoke_service,
            active_session_id=session_id or "startup-smoke-session",
        )
        self.standalone_last_export_validation_report = SimpleNamespace(
            ok=True,
            no_op_roundtrip_status="PASS",
        )
        return object()

    def has_active_standalone_session(self) -> bool:
        return self.session_active


class _StartupSmokeExportWorkerStub:
    def __init__(self, request_id: int, service: _MeshSmokeServiceStub, session_id: str, output_dir: Path, *, name: str = "mesh") -> None:
        self.request_id = request_id
        self.service = service
        self.session_id = session_id
        self.output_dir = Path(output_dir)
        self.name = name
        self.completed = _SignalStub()
        self.error = _SignalStub()

    def run(self) -> None:
        self.service.calls.append(("export", self.session_id, self.output_dir))
        self.output_dir.mkdir(parents=True, exist_ok=True)
        mesh_path = self.output_dir / f"{self.name}.obj"
        metadata_path = self.output_dir / "mesh.cdmeta.json"
        hash_path = self.output_dir / "original_asset_hash.txt"
        mesh_path.write_text("o mesh\n", encoding="utf-8")
        metadata_path.write_text("{}", encoding="utf-8")
        hash_path.write_text("hash", encoding="utf-8")
        self.completed.emit(
            self.request_id,
            {
                "package_dir": self.output_dir,
                "mesh_path": mesh_path,
                "metadata_path": metadata_path,
                "original_asset_hash_path": hash_path,
            },
            0.0,
        )


class _StartupSmokeImportWorkerStub:
    def __init__(self, request_id: int, service: _MeshSmokeServiceStub, session_id: str, package_path: Path) -> None:
        self.request_id = request_id
        self.service = service
        self.session_id = session_id
        self.package_path = Path(package_path)
        self.completed = _SignalStub()
        self.error = _SignalStub()

    def run(self) -> None:
        self.service.calls.append(("import", self.session_id, self.package_path))
        self.completed.emit(self.request_id, SimpleNamespace(session_id=self.session_id), self.service.validation, 0.0)


class _StartupSmokeRebuildWorkerStub:
    def __init__(
        self,
        request_id: int,
        service: _MeshSmokeServiceStub,
        session_id: str,
        *,
        action_text: str = "",
        output_path: Path | str = "",
    ) -> None:
        self.request_id = request_id
        self.service = service
        self.session_id = session_id
        self.output_path = Path(output_path)
        self.completed = _SignalStub()
        self.cancelled = _SignalStub()
        self.error = _SignalStub()

    def run(self) -> None:
        self.service.calls.append(("rebuild", self.session_id, self.output_path))
        self.output_path.write_bytes(b"rebuilt")
        self.completed.emit(
            self.request_id,
            SimpleNamespace(validation_status="passed", output_path=str(self.output_path)),
        )


class ShellAppStartupTests(unittest.TestCase):
    def test_read_shell_startup_theme_key_validates_saved_theme(self) -> None:
        theme_key = next(iter(UI_THEME_SCHEMES))

        self.assertEqual(theme_key, read_shell_startup_theme_key(_SettingsStub(theme_key)))  # type: ignore[arg-type]
        self.assertIn(read_shell_startup_theme_key(_SettingsStub("missing-theme")), UI_THEME_SCHEMES)  # type: ignore[arg-type]

    def test_prepare_shell_application_configures_qapplication(self) -> None:
        app = QApplication.instance() or QApplication([])

        with patch("cdmw.ui.shell.app_startup.create_settings", wraps=create_settings) as create_call:
            startup = prepare_shell_application(app)
            context = AppContext.from_settings(startup.settings)

        self.assertIsInstance(startup, ShellApplicationStartup)
        self.assertIs(context.settings, startup.settings)
        create_call.assert_called_once_with()
        self.assertIn(startup.theme_key, UI_THEME_SCHEMES)
        self.assertTrue(app.organizationName())
        self.assertTrue(app.applicationName())
        self.assertIsNotNone(startup.tree_column_width_filter)

    def test_prepare_shell_main_window_attaches_splash_and_records_event(self) -> None:
        window = _WindowStub()
        app = _AppStub()
        splash = object()
        icon_filter = object()
        events: list[str] = []

        with (
            patch("cdmw.ui.shell.app_startup.apply_window_ui_fonts") as apply_ui_fonts,
            patch("cdmw.ui.shell.app_startup.apply_window_data_fonts") as apply_fonts,
        ):
            prepare_shell_main_window(window, app, splash, icon_filter, events.append)  # type: ignore[arg-type]

        self.assertIs(window._app_window_icon_filter, icon_filter)
        self.assertEqual(["main_window_constructed"], events)
        self.assertIs(window.attached_splash, splash)
        self.assertTrue(window.hold_main_window)
        apply_ui_fonts.assert_called_once_with(window, app)
        apply_fonts.assert_called_once_with(window)

    def test_finish_gui_startup_smoke_only_when_requested(self) -> None:
        window = _WindowStub()
        app = _AppStub()

        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("CDMW_GUI_STARTUP_SMOKE", None)
            self.assertFalse(finish_gui_startup_smoke_if_requested(window, app))  # type: ignore[arg-type]

        with tempfile.TemporaryDirectory() as temp_dir:
            result_path = Path(temp_dir) / "startup-result.json"
            with patch.dict(
                os.environ,
                {
                    "CDMW_GUI_STARTUP_SMOKE": "1",
                    "CDMW_GUI_STARTUP_SMOKE_RESULT": str(result_path),
                    "CDMW_GUI_STARTUP_SMOKE_TARGET": "",
                },
            ):
                self.assertTrue(finish_gui_startup_smoke_if_requested(window, app))  # type: ignore[arg-type]
            payload = json.loads(result_path.read_text(encoding="utf-8"))

        self.assertTrue(window.released)
        self.assertTrue(app.process_events_called)
        self.assertTrue(window.finalized)
        self.assertEqual(
            {"ok": True, "pid": os.getpid(), "stage": "post_construction", "target": "default"},
            payload,
        )

    def test_finish_gui_startup_smoke_can_activate_mesh_editor_target(self) -> None:
        QApplication.instance() or QApplication([])
        window = _WindowStub()
        app = _AppStub()
        mesh_editor_tab = QWidget()
        workspace = QWidget(mesh_editor_tab)
        workspace.setObjectName("MeshEditorStandaloneWorkspace")
        for object_name in (
            "MeshEditorStandalonePreviewStack",
            "MeshEditorExportEditablePackageButton",
            "MeshEditorImportEditedPackageButton",
            "MeshEditorRunValidationReportButton",
            "MeshEditorRebuildPatchedAssetButton",
            "MeshEditorPreviewRebuiltAssetButton",
            "MeshEditorPackageRebuiltAssetButton",
            "MeshEditorDotNetExperimentButton",
        ):
            child = QWidget(workspace)
            child.setObjectName(object_name)
        window.mesh_editor_tab = mesh_editor_tab
        window.assets_tabs = _TabsStub(mesh_editor_tab)
        mesh_editor_tab.standalone_workspace = workspace  # type: ignore[attr-defined]

        with patch.dict(
            os.environ,
            {"CDMW_GUI_STARTUP_SMOKE": "1", "CDMW_GUI_STARTUP_SMOKE_TARGET": "mesh_editor"},
        ):
            self.assertTrue(finish_gui_startup_smoke_if_requested(window, app))  # type: ignore[arg-type]

        self.assertEqual(0, window.assets_tabs.current_index)
        self.assertTrue(window.finalized)
        mesh_editor_tab.deleteLater()

    def test_finish_gui_startup_smoke_can_construct_mesh_builder_target(self) -> None:
        window = _WindowStub()
        app = _AppStub()

        with (
            patch.dict(
                os.environ,
                {"CDMW_GUI_STARTUP_SMOKE": "1", "CDMW_GUI_STARTUP_SMOKE_TARGET": "mesh_builder"},
            ),
            patch(
                "cdmw.ui.shell.app_startup._verify_mesh_builder_startup_smoke_target"
            ) as verify_builder,
        ):
            self.assertTrue(finish_gui_startup_smoke_if_requested(window, app))  # type: ignore[arg-type]

        verify_builder.assert_called_once_with(window, app)
        self.assertTrue(window.finalized)

    def test_finish_gui_startup_smoke_can_load_mesh_editor_asset_target(self) -> None:
        QApplication.instance() or QApplication([])
        window = _WindowStub()
        app = _AppStub()
        mesh_editor_tab = _MeshEditorTabStub()
        workspace = QWidget(mesh_editor_tab)
        workspace.setObjectName("MeshEditorStandaloneWorkspace")
        for object_name in (
            "MeshEditorStandalonePreviewStack",
            "MeshEditorExportEditablePackageButton",
            "MeshEditorImportEditedPackageButton",
            "MeshEditorRunValidationReportButton",
            "MeshEditorRebuildPatchedAssetButton",
            "MeshEditorPreviewRebuiltAssetButton",
            "MeshEditorPackageRebuiltAssetButton",
            "MeshEditorDotNetExperimentButton",
        ):
            child = QWidget(workspace)
            child.setObjectName(object_name)
        window.mesh_editor_tab = mesh_editor_tab
        window.assets_tabs = _TabsStub(mesh_editor_tab)
        mesh_editor_tab.standalone_workspace = workspace  # type: ignore[attr-defined]

        with tempfile.TemporaryDirectory() as temp_dir:
            asset_path = Path(temp_dir) / "mesh.pac"
            asset_path.write_bytes(b"mesh")
            with patch.dict(
                os.environ,
                {
                    "CDMW_GUI_STARTUP_SMOKE": "1",
                    "CDMW_GUI_STARTUP_SMOKE_TARGET": "mesh_editor",
                    "CDMW_GUI_STARTUP_SMOKE_MESH_ASSET": str(asset_path),
                    "CDMW_GUI_STARTUP_SMOKE_MESH_ASSET_REBUILD": "",
                },
            ):
                self.assertTrue(finish_gui_startup_smoke_if_requested(window, app))  # type: ignore[arg-type]

        self.assertEqual(asset_path, mesh_editor_tab.opened_path)
        self.assertTrue(window.finalized)
        mesh_editor_tab.deleteLater()

    def test_finish_gui_startup_smoke_can_run_mesh_editor_asset_rebuild_pipeline(self) -> None:
        QApplication.instance() or QApplication([])
        window = _WindowStub()
        app = _AppStub()
        mesh_editor_tab = _MeshEditorTabStub()
        workspace = QWidget(mesh_editor_tab)
        workspace.setObjectName("MeshEditorStandaloneWorkspace")
        for object_name in (
            "MeshEditorStandalonePreviewStack",
            "MeshEditorExportEditablePackageButton",
            "MeshEditorImportEditedPackageButton",
            "MeshEditorRunValidationReportButton",
            "MeshEditorRebuildPatchedAssetButton",
            "MeshEditorPreviewRebuiltAssetButton",
            "MeshEditorPackageRebuiltAssetButton",
            "MeshEditorDotNetExperimentButton",
        ):
            child = QWidget(workspace)
            child.setObjectName(object_name)
        window.mesh_editor_tab = mesh_editor_tab
        window.assets_tabs = _TabsStub(mesh_editor_tab)
        mesh_editor_tab.standalone_workspace = workspace  # type: ignore[attr-defined]

        with tempfile.TemporaryDirectory() as temp_dir:
            asset_path = Path(temp_dir) / "mesh.pac"
            asset_path.write_bytes(b"mesh")
            with (
                patch.dict(
                    os.environ,
                    {
                        "CDMW_GUI_STARTUP_SMOKE": "1",
                        "CDMW_GUI_STARTUP_SMOKE_TARGET": "mesh_editor",
                        "CDMW_GUI_STARTUP_SMOKE_MESH_ASSET": str(asset_path),
                        "CDMW_GUI_STARTUP_SMOKE_MESH_ASSET_REBUILD": "1",
                    },
                ),
                patch(
                    "cdmw.workers.mesh_editor_workers.MeshEditablePackageExportWorker",
                    _StartupSmokeExportWorkerStub,
                ),
                patch(
                    "cdmw.workers.mesh_editor_workers.MeshEditablePackageImportWorker",
                    _StartupSmokeImportWorkerStub,
                ),
                patch("cdmw.workers.mesh_editor_workers.MeshRebuildReportWorker", _StartupSmokeRebuildWorkerStub),
            ):
                self.assertTrue(finish_gui_startup_smoke_if_requested(window, app))  # type: ignore[arg-type]

        self.assertEqual(["export", "import", "rebuild"], [call[0] for call in mesh_editor_tab.mesh_smoke_service.calls])
        self.assertTrue(window.finalized)
        mesh_editor_tab.deleteLater()

    def test_finish_gui_startup_smoke_can_run_mesh_editor_dotnet_pipeline(self) -> None:
        QApplication.instance() or QApplication([])
        window = _WindowStub()
        app = _AppStub()
        mesh_editor_tab = _MeshEditorTabStub()
        workspace = QWidget(mesh_editor_tab)
        workspace.setObjectName("MeshEditorStandaloneWorkspace")
        for object_name in (
            "MeshEditorStandalonePreviewStack",
            "MeshEditorExportEditablePackageButton",
            "MeshEditorImportEditedPackageButton",
            "MeshEditorRunValidationReportButton",
            "MeshEditorRebuildPatchedAssetButton",
            "MeshEditorPreviewRebuiltAssetButton",
            "MeshEditorPackageRebuiltAssetButton",
            "MeshEditorDotNetExperimentButton",
        ):
            child = QWidget(workspace)
            child.setObjectName(object_name)
        window.mesh_editor_tab = mesh_editor_tab
        window.assets_tabs = _TabsStub(mesh_editor_tab)
        mesh_editor_tab.standalone_workspace = workspace  # type: ignore[attr-defined]

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            asset_path = root / "mesh.pac"
            asset_path.write_bytes(b"mesh")
            exe_path = root / "cdmw-mesh-dotnet-editor.exe"
            exe_path.write_text("fake", encoding="utf-8")
            package_dir = root / "dotnet_package"
            output_dir = package_dir / "output"
            output_dir.mkdir(parents=True)
            package = SimpleNamespace(
                package_dir=package_dir,
                mesh_path=package_dir / "mesh.obj",
                obj_sidecar_path=package_dir / "mesh.obj.meta.json",
                cdmeta_path=package_dir / "mesh.cdmeta.json",
                original_asset_hash_path=package_dir / "original_asset_hash.txt",
                status_path=output_dir / "dotnet_status.json",
                output_dir=output_dir,
                edit_operations_path=output_dir / "edit_operations.json",
                launch_manifest_path=package_dir / "dotnet_launch.json",
            )
            calls: list[tuple[object, ...]] = []

            def fake_build_package(mesh: object, *, output_root: Path | str | None = None) -> object:
                calls.append(("build_package", mesh, output_root))
                return package

            def fake_command(executable: Path, package_arg: object) -> tuple[str, list[str]]:
                calls.append(("command", executable, package_arg))
                return (str(executable), ["--input-package", str(package_dir)])

            def fake_run(command: list[str], **kwargs: object) -> object:
                calls.append(("run", tuple(command), kwargs.get("cwd")))
                self.assertIn("--headless-smoke", command)
                package.status_path.write_text(
                    json.dumps(
                        {
                            "event": "saved",
                            "edited_mesh": str(output_dir / "mesh.obj"),
                            "edit_operations": str(output_dir / "edit_operations.json"),
                            "metrics": {
                                "average_fps": 72.0,
                                "frame_time_ms": 13.8,
                                "responsiveness_ms": 1.5,
                            },
                        }
                    ),
                    encoding="utf-8",
                )
                return SimpleNamespace(returncode=0)

            def fake_import_output(package_arg: object, payload: object) -> object:
                calls.append(("import_output", package_arg, payload))
                return SimpleNamespace(
                    path="edited.obj",
                    _cdmw_edit_operations=[{"operation": "replace_positions_same_count"}],
                )

            def fake_write_evaluation(package_arg: object, payload: object, *, validation_report: object) -> Path:
                calls.append(("write_evaluation", package_arg, payload, validation_report))
                evaluation_path = package_dir / "dotnet_evaluation.md"
                evaluation_path.write_text("Keep/drop Recommendation: keep as experiment only\n", encoding="utf-8")
                return evaluation_path

            with (
                patch.dict(
                    os.environ,
                    {
                        "CDMW_GUI_STARTUP_SMOKE": "1",
                        "CDMW_GUI_STARTUP_SMOKE_TARGET": "mesh_editor",
                        "CDMW_GUI_STARTUP_SMOKE_MESH_ASSET": str(asset_path),
                        "CDMW_GUI_STARTUP_SMOKE_MESH_DOTNET": "1",
                    },
                ),
                patch("cdmw.services.mesh_dotnet_experiment.find_mesh_dotnet_experiment_editor", return_value=exe_path),
                patch("cdmw.services.mesh_dotnet_experiment.build_mesh_dotnet_experiment_package", side_effect=fake_build_package),
                patch("cdmw.services.mesh_dotnet_experiment.mesh_dotnet_experiment_command", side_effect=fake_command),
                patch("cdmw.services.mesh_dotnet_experiment.import_mesh_dotnet_experiment_output", side_effect=fake_import_output),
                patch("cdmw.services.mesh_dotnet_experiment.write_mesh_dotnet_experiment_evaluation", side_effect=fake_write_evaluation),
                patch("cdmw.ui.mesh_editor.startup_smoke.subprocess.run", side_effect=fake_run),
            ):
                self.assertTrue(finish_gui_startup_smoke_if_requested(window, app))  # type: ignore[arg-type]

        self.assertIn("build_package", [call[0] for call in calls])
        self.assertIn("run", [call[0] for call in calls])
        self.assertIn("import_output", [call[0] for call in calls])
        self.assertIn("write_evaluation", [call[0] for call in calls])
        self.assertIn("replace_working_mesh", [call[0] for call in mesh_editor_tab.mesh_smoke_service.calls])
        self.assertIn("validate_export", [call[0] for call in mesh_editor_tab.mesh_smoke_service.calls])
        self.assertTrue(window.finalized)
        mesh_editor_tab.deleteLater()

    def test_mesh_editor_dotnet_startup_smoke_requires_same_count_position_operation(self) -> None:
        root = Path(__file__).resolve().parents[1]
        source = (root / "cdmw" / "ui" / "mesh_editor" / "startup_smoke.py").read_text(
            encoding="utf-8"
        )

        self.assertIn("_cdmw_edit_operations", source)
        self.assertIn("replace_positions_same_count", source)
        self.assertIn("same-count position operation", source)

    def test_run_shell_event_loop_reports_nonzero_exit(self) -> None:
        reports: list[tuple[tuple[object, ...], dict[str, object]]] = []

        exit_code = run_shell_event_loop(
            _AppStub(exit_code=7),  # type: ignore[arg-type]
            lambda *args, **kwargs: reports.append((args, kwargs)),
        )

        self.assertEqual(7, exit_code)
        self.assertEqual("nonzero_gui_exit", reports[0][0][0])
        self.assertIn("Exit code: 7", reports[0][0][2])
        self.assertTrue(reports[0][1]["force"])

    def test_run_shell_event_loop_ignores_zero_exit(self) -> None:
        reports: list[tuple[tuple[object, ...], dict[str, object]]] = []

        exit_code = run_shell_event_loop(
            _AppStub(exit_code=0),  # type: ignore[arg-type]
            lambda *args, **kwargs: reports.append((args, kwargs)),
        )

        self.assertEqual(0, exit_code)
        self.assertEqual([], reports)


if __name__ == "__main__":
    unittest.main()
