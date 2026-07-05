from __future__ import annotations

import unittest
from pathlib import Path
from typing import Mapping

from cdmw.workers.asset_authoring_workers import MaterialMakerExportWorker, OpenImageIOTaskWorker


class _FakeOpenImageIOService:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[object, ...], Mapping[str, object] | None, float | None]] = []

    def run_openimageio_metadata(
        self,
        source_path: Path | str,
        configured_paths: Mapping[str, object] | None = None,
        timeout_s: float | None = None,
    ) -> dict[str, object]:
        self.calls.append(("metadata", (source_path,), configured_paths, timeout_s))
        return {"status": "ok", "operation": "metadata", "metadata": {"width": 8, "height": 4}}

    def run_openimageio_convert(
        self,
        source_path: Path | str,
        output_path: Path | str,
        configured_paths: Mapping[str, object] | None = None,
        timeout_s: float | None = None,
    ) -> dict[str, object]:
        self.calls.append(("convert", (source_path, output_path), configured_paths, timeout_s))
        return {"status": "ok", "operation": "convert", "output_path": str(output_path)}

    def run_openimageio_diff(
        self,
        left_path: Path | str,
        right_path: Path | str,
        configured_paths: Mapping[str, object] | None = None,
        timeout_s: float | None = None,
    ) -> dict[str, object]:
        self.calls.append(("diff", (left_path, right_path), configured_paths, timeout_s))
        return {"status": "different", "operation": "diff", "returncode": 1}


class _FakeMaterialMakerService:
    def __init__(self, *, export_status: str = "ok") -> None:
        self.export_status = export_status
        self.calls: list[tuple[str, tuple[object, ...], Mapping[str, object] | None, float | None]] = []

    def run_material_maker_export(
        self,
        project_path: Path | str,
        output_dir: Path | str,
        configured_paths: Mapping[str, object] | None = None,
        timeout_s: float | None = None,
    ) -> dict[str, object]:
        self.calls.append(("export", (project_path, output_dir), configured_paths, timeout_s))
        return {"status": self.export_status, "project_path": str(project_path), "output_dir": str(output_dir)}

    def ingest_exported_texture_set(
        self,
        export_dir: Path | str,
        *,
        material_name: str = "",
        channel_overrides: Mapping[str, object] | None = None,
    ) -> dict[str, object]:
        self.calls.append(("ingest", (export_dir, material_name, dict(channel_overrides or {})), None, None))
        return {"status": "ok", "material_name": material_name, "channels": {"base_color": {"path": "oak.png"}}}


class AssetAuthoringWorkerTests(unittest.TestCase):
    def test_material_maker_export_worker_runs_export_then_texture_set_review(self) -> None:
        service = _FakeMaterialMakerService()
        configured = {"material_maker": Path("C:/tools/material_maker.exe")}
        completed: list[dict[str, object]] = []
        progress: list[tuple[int, int, str]] = []
        errors: list[str] = []
        finished: list[bool] = []
        worker = MaterialMakerExportWorker(
            Path("wood.material"),
            Path("exports"),
            configured_paths=configured,
            material_name="Oak",
            channel_overrides={"custom.png": "ao"},
            timeout_s=30.0,
            service=service,  # type: ignore[arg-type]
        )
        worker.completed.connect(completed.append)
        worker.progress_changed.connect(lambda current, total, message: progress.append((current, total, message)))
        worker.error.connect(errors.append)
        worker.finished.connect(lambda: finished.append(True))

        worker.run()

        self.assertEqual([], errors)
        self.assertEqual([True], finished)
        self.assertEqual("material_maker_export", completed[0]["operation"])
        self.assertEqual("ok", completed[0]["status"])
        self.assertEqual("ok", completed[0]["texture_set_report"]["status"])  # type: ignore[index]
        self.assertEqual(
            [
                ("export", (Path("wood.material"), Path("exports")), configured, 30.0),
                ("ingest", (Path("exports"), "Oak", {"custom.png": "ao"}), None, None),
            ],
            service.calls,
        )
        self.assertEqual((0, 2, "Running Material Maker export..."), progress[0])
        self.assertEqual((2, 2, "Material Maker export finished."), progress[-1])

    def test_material_maker_export_worker_cancel_before_run_suppresses_service_call(self) -> None:
        service = _FakeMaterialMakerService()
        worker = MaterialMakerExportWorker(Path("wood.material"), Path("exports"), service=service)  # type: ignore[arg-type]
        completed: list[object] = []
        cancelled: list[str] = []
        finished: list[bool] = []
        worker.completed.connect(completed.append)
        worker.cancelled.connect(cancelled.append)
        worker.finished.connect(lambda: finished.append(True))

        worker.stop()
        worker.run()

        self.assertEqual([], service.calls)
        self.assertEqual([], completed)
        self.assertEqual(["Material Maker export stopped."], cancelled)
        self.assertEqual([True], finished)

    def test_material_maker_export_worker_skips_ingest_when_export_fails(self) -> None:
        service = _FakeMaterialMakerService(export_status="failed")
        completed: list[dict[str, object]] = []
        worker = MaterialMakerExportWorker(Path("wood.material"), Path("exports"), service=service)  # type: ignore[arg-type]
        worker.completed.connect(completed.append)

        worker.run()

        self.assertEqual("failed", completed[0]["status"])
        self.assertIsNone(completed[0]["texture_set_report"])
        self.assertEqual(["export"], [call[0] for call in service.calls])

    def test_openimageio_worker_routes_metadata_convert_and_diff(self) -> None:
        service = _FakeOpenImageIOService()
        configured = {"openimageio": Path("C:/tools/oiiotool.exe")}
        cases = (
            ("metadata", (Path("source.exr"),)),
            ("convert", (Path("source.exr"), Path("out/source.png"))),
            ("diff", (Path("out/source.png"), Path("rebuilt.png"))),
        )
        completed: list[dict[str, object]] = []
        errors: list[str] = []
        finished: list[bool] = []

        for operation, paths in cases:
            worker = OpenImageIOTaskWorker(
                operation,
                paths,
                configured_paths=configured,
                timeout_s=12.5,
                service=service,  # type: ignore[arg-type]
            )
            worker.completed.connect(completed.append)
            worker.error.connect(errors.append)
            worker.finished.connect(lambda: finished.append(True))
            worker.run()

        self.assertEqual([], errors)
        self.assertEqual(["metadata", "convert", "diff"], [str(result["operation"]) for result in completed])
        self.assertEqual(["metadata", "convert", "diff"], [call[0] for call in service.calls])
        self.assertTrue(all(call[2] == configured and call[3] == 12.5 for call in service.calls))
        self.assertEqual([True, True, True], finished)

    def test_openimageio_worker_cancel_before_run_suppresses_service_call(self) -> None:
        service = _FakeOpenImageIOService()
        worker = OpenImageIOTaskWorker("metadata", (Path("source.exr"),), service=service)  # type: ignore[arg-type]
        completed: list[object] = []
        cancelled: list[str] = []
        finished: list[bool] = []
        worker.completed.connect(completed.append)
        worker.cancelled.connect(cancelled.append)
        worker.finished.connect(lambda: finished.append(True))

        worker.stop()
        worker.run()

        self.assertEqual([], service.calls)
        self.assertEqual([], completed)
        self.assertEqual(["OpenImageIO task stopped."], cancelled)
        self.assertEqual([True], finished)

    def test_openimageio_worker_reports_invalid_operation(self) -> None:
        worker = OpenImageIOTaskWorker("unsupported", ())
        errors: list[str] = []
        finished: list[bool] = []
        worker.error.connect(errors.append)
        worker.finished.connect(lambda: finished.append(True))

        worker.run()

        self.assertEqual(["Unsupported OpenImageIO worker operation: unsupported"], errors)
        self.assertEqual([True], finished)


if __name__ == "__main__":
    unittest.main()
